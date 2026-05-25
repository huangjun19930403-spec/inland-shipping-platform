"""Persist real water-area matches for navigation channels.

This production step links curated seed channels to imported real water areas.
It writes only match rows and non-current candidate boundaries. It never
replaces seed/current boundaries, never creates centerlines, and never builds
graph edges.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable, Sequence

from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, engine
from app.models import NavigationChannelWaterAreaMatch, NavigationWaterArea
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.models.base import Base
from scripts.navigation.refresh_postgis_geometry_columns import refresh_postgis_geometry_columns

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ALIAS_CONFIG = PROJECT_ROOT / "scripts" / "seed_data" / "navigation" / "navigation_channel_aliases.json"
DEFAULT_SCOPE_CONFIG = PROJECT_ROOT / "scripts" / "seed_data" / "navigation" / "navigation_real_scope.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "data_audit" / "navigation_channel_water_area_match_report.json"
DEFAULT_BATCH_PREFIX = "REAL-WATER-MATCH"
COORDINATE_SCALE = Decimal("0.000000000000001")
DEGREE_MEASURE_SCALE = Decimal("0.000000000000000001")

LAYER_PRIORITY = {
    "一级水系": 1,
    "二级水系": 2,
    "三级水系": 3,
    "四级水系": 4,
    "五级水系": 5,
    "六级水系": 6,
    "七级水系": 7,
    "rx": 80,
    "rx8": 90,
}


@dataclass(slots=True)
class MatchWriteItem:
    water_area_id: int
    water_name: str | None
    source_layer_name: str
    source_object_id: str
    match_type_code: str
    matched_term: str
    score: int
    confidence_code: str
    review_status_code: str
    issue_codes: list[str] = field(default_factory=list)
    duplicate_layer_names: list[str] = field(default_factory=list)
    bbox: list[float | None] = field(default_factory=list)


@dataclass(slots=True)
class ChannelWaterAreaMatchReport:
    channel_id: int
    channel_code: str
    channel_name: str
    matched_water_area_count: int
    best_score: int
    confidence_code: str
    review_status_code: str
    issue_codes: list[str]
    candidate_boundary_written: bool
    candidates: list[MatchWriteItem] = field(default_factory=list)


@dataclass(slots=True)
class BuildMatchReport:
    report_version: str
    generated_at: str
    dry_run: bool
    write_candidate_boundaries: bool
    source_code: str | None
    match_batch_code: str
    alias_config_path: str
    scope_config_path: str
    output_path: str | None
    channel_count: int
    water_area_count: int
    match_row_count: int
    candidate_boundaries_written: int
    channels: list[ChannelWaterAreaMatchReport]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["summary"] = {
            "matched_channels": sum(1 for item in self.channels if item.matched_water_area_count > 0),
            "missing_match_channels": sum(1 for item in self.channels if item.matched_water_area_count == 0),
            "need_review_channels": sum(1 for item in self.channels if item.review_status_code == "NEED_REVIEW"),
            "match_row_count": self.match_row_count,
            "candidate_boundaries_written": self.candidate_boundaries_written,
        }
        return payload


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _norm(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    for token in (" ", "\t", "\n", "—", "-", "_", "（", "）", "(", ")", "/", "·"):
        text = text.replace(token, "")
    return text


def _quantize_decimal(value: Any, scale: Decimal) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value)).quantize(scale, rounding=ROUND_HALF_UP)


def _terms_for_channel(channel: NavigationChannel, alias_config: dict[str, Any]) -> dict[str, set[str]]:
    configured = alias_config.get("channels", {}).get(channel.channel_code, {})
    exact_terms: set[str] = set()
    alias_terms: set[str] = set()

    for value in (
        channel.channel_name,
        channel.official_name,
        channel.display_name,
        *(channel.alias_names or []),
        *configured.get("water_names", []),
    ):
        normalized = _norm(value)
        if normalized:
            exact_terms.add(normalized)

    for value in configured.get("aliases", []):
        normalized = _norm(value)
        if normalized:
            alias_terms.add(normalized)

    return {"exact": exact_terms, "alias": alias_terms}


def _score_match(channel_terms: dict[str, set[str]], water_name: str | None) -> tuple[str, str, int] | None:
    normalized = _norm(water_name)
    if not normalized:
        return None
    if normalized in channel_terms["exact"]:
        return ("EXACT_NAME", normalized, 95)
    if normalized in channel_terms["alias"]:
        return ("ALIAS_NAME", normalized, 90)
    for term in sorted(channel_terms["exact"] | channel_terms["alias"], key=len, reverse=True):
        if len(term) >= 2 and (term in normalized or normalized in term):
            return ("CONTAINS_NAME", term, 65)
    return None


def _bbox(row: Any) -> list[float | None]:
    return [
        float(row.bbox_min_lng) if row.bbox_min_lng is not None else None,
        float(row.bbox_min_lat) if row.bbox_min_lat is not None else None,
        float(row.bbox_max_lng) if row.bbox_max_lng is not None else None,
        float(row.bbox_max_lat) if row.bbox_max_lat is not None else None,
    ]


def _bbox_intersects(a: Sequence[float | None], b: Sequence[float | None]) -> bool:
    if any(value is None for value in (*a, *b)):
        return True
    return bool(a[2] >= b[0] and a[0] <= b[2] and a[3] >= b[1] and a[1] <= b[3])


def _scope_bbox(scope_config: dict[str, Any]) -> list[float] | None:
    bbox = scope_config.get("bbox")
    if not bbox:
        return None
    return [float(bbox["min_lng"]), float(bbox["min_lat"]), float(bbox["max_lng"]), float(bbox["max_lat"])]


def _scope_for_channel(channel: NavigationChannel, scope_config: dict[str, Any]) -> dict[str, Any] | None:
    if channel.channel_code in set(scope_config.get("priority_channel_codes") or []):
        return scope_config
    for scope_code, scope in (scope_config.get("scopes") or {}).items():
        if channel.channel_code in set(scope.get("priority_channel_codes") or []):
            return {"scope_code": scope.get("scope_code") or scope_code, **scope}
    return None


def _scope_bbox_for_channel(channel: NavigationChannel, scope_config: dict[str, Any]) -> list[float] | None:
    scope = _scope_for_channel(channel, scope_config)
    if scope:
        return _scope_bbox(scope)
    return _scope_bbox(scope_config)


def _scope_code_for_channel(channel: NavigationChannel, scope_config: dict[str, Any]) -> str | None:
    scope = _scope_for_channel(channel, scope_config)
    if scope:
        return str(scope.get("scope_code") or "")
    return scope_config.get("scope_code")


def _layer_priority(layer_name: str | None) -> int:
    return LAYER_PRIORITY.get(str(layer_name or ""), 99)


def _duplicate_key(row: NavigationWaterArea) -> tuple[str, str, str | None]:
    return (row.source_code, str(row.source_object_id), _norm(row.water_name or row.normalized_water_name))


def _dedupe_water_areas(rows: Iterable[NavigationWaterArea]) -> tuple[list[NavigationWaterArea], dict[int, list[str]]]:
    grouped: dict[tuple[str, str, str | None], list[NavigationWaterArea]] = {}
    for row in rows:
        grouped.setdefault(_duplicate_key(row), []).append(row)

    primary_rows: list[NavigationWaterArea] = []
    duplicate_layers_by_id: dict[int, list[str]] = {}
    for group in grouped.values():
        ordered = sorted(group, key=lambda item: (_layer_priority(item.source_layer_name), item.id))
        primary = ordered[0]
        primary_rows.append(primary)
        duplicate_layers_by_id[primary.id] = [item.source_layer_name for item in ordered[1:]]

    primary_rows.sort(key=lambda item: (_layer_priority(item.source_layer_name), item.source_layer_name, item.source_object_id, item.id))
    return primary_rows, duplicate_layers_by_id


def _confidence(best_score: int, matched_count: int) -> str:
    if matched_count == 0:
        return "MISSING"
    if best_score >= 90:
        return "HIGH_CONFIDENCE"
    if best_score >= 65:
        return "MEDIUM_CONFIDENCE"
    return "LOW_CONFIDENCE"


def _geometry_intersects(boundary_geometry: BaseGeometry | None, water_area: NavigationWaterArea) -> bool:
    if boundary_geometry is None:
        return True
    try:
        water_geometry = shape(water_area.geometry_json)
        return bool(boundary_geometry.intersects(water_geometry))
    except Exception:
        return True


def _boundary_geometry(boundary: NavigationChannelBoundary | None) -> BaseGeometry | None:
    if boundary is None or not boundary.geometry_json:
        return None
    try:
        return shape(boundary.geometry_json)
    except Exception:
        return None


def _review_status(
    *,
    channel: NavigationChannel,
    matched_count: int,
    confidence_code: str,
    base_issues: Iterable[str],
) -> tuple[str, list[str]]:
    issues = set(base_issues)
    if matched_count == 0:
        issues.add("NO_WATER_AREA_MATCH")
    if channel.review_required:
        issues.add("CHANNEL_REVIEW_REQUIRED")
    if confidence_code in {"MISSING", "LOW_CONFIDENCE"}:
        issues.add("LOW_MATCH_CONFIDENCE")
    review_status = "NEED_REVIEW" if issues else "PUBLISHED"
    return review_status, sorted(issues)


def _geometry_counts(geometry: BaseGeometry) -> tuple[int, int]:
    if geometry.geom_type == "Polygon":
        rings = [geometry.exterior, *geometry.interiors]
        return len(rings), sum(len(ring.coords) for ring in rings)
    if geometry.geom_type == "MultiPolygon":
        ring_count = 0
        point_count = 0
        for polygon in geometry.geoms:
            rings = [polygon.exterior, *polygon.interiors]
            ring_count += len(rings)
            point_count += sum(len(ring.coords) for ring in rings)
        return ring_count, point_count
    return 0, 0


def _boundary_payload(channel_id: int, geometry: BaseGeometry) -> dict[str, Any]:
    centroid = geometry.centroid
    min_lng, min_lat, max_lng, max_lat = geometry.bounds
    ring_count, point_count = _geometry_counts(geometry)
    return {
        "channel_id": channel_id,
        "geometry_json": mapping(geometry),
        "boundary_paths_low": None,
        "boundary_paths_medium": None,
        "boundary_paths_high": None,
        "center_longitude": _quantize_decimal(centroid.x, COORDINATE_SCALE),
        "center_latitude": _quantize_decimal(centroid.y, COORDINATE_SCALE),
        "display_center_longitude": _quantize_decimal(centroid.x, COORDINATE_SCALE),
        "display_center_latitude": _quantize_decimal(centroid.y, COORDINATE_SCALE),
        "bbox_min_lng": _quantize_decimal(min_lng, COORDINATE_SCALE),
        "bbox_min_lat": _quantize_decimal(min_lat, COORDINATE_SCALE),
        "bbox_max_lng": _quantize_decimal(max_lng, COORDINATE_SCALE),
        "bbox_max_lat": _quantize_decimal(max_lat, COORDINATE_SCALE),
        "source_shape_length_degree": _quantize_decimal(geometry.length, DEGREE_MEASURE_SCALE),
        "source_shape_area_degree": _quantize_decimal(geometry.area, DEGREE_MEASURE_SCALE),
        "ring_count": ring_count,
        "point_count": point_count,
        "geometry_status_code": "AVAILABLE",
        "boundary_quality_code": "REVIEW",
        "connectivity_status_code": "UNKNOWN",
        "repair_status_code": "REVIEW_CANDIDATE",
        "coverage_policy_code": "RIVER_MATCH_CANDIDATE",
        "geometry_coordinate_system_code": "WGS84",
        "boundary_coordinate_system_code": "WGS84",
        "is_current": False,
        "imported_at": datetime.now(UTC).replace(tzinfo=None),
    }


async def _write_candidate_boundary(
    session: AsyncSession,
    channel_id: int,
    water_area_rows: list[NavigationWaterArea],
) -> bool:
    geometries: list[BaseGeometry] = []
    for row in water_area_rows:
        if not row.geometry_json:
            continue
        try:
            geometry = shape(row.geometry_json)
            if not geometry.is_empty:
                geometries.append(geometry)
        except Exception:
            continue
    if not geometries:
        return False
    geometry = unary_union(geometries)
    if geometry.is_empty:
        return False

    existing = (
        await session.execute(
            select(NavigationChannelBoundary).where(
                NavigationChannelBoundary.channel_id == channel_id,
                NavigationChannelBoundary.is_current.is_(False),
                NavigationChannelBoundary.coverage_policy_code == "RIVER_MATCH_CANDIDATE",
            )
        )
    ).scalar_one_or_none()
    payload = _boundary_payload(channel_id, geometry)
    if existing is None:
        session.add(NavigationChannelBoundary(**payload))
    else:
        for key, value in payload.items():
            setattr(existing, key, value)
    return True


async def build_channel_water_area_matches(
    *,
    session: AsyncSession,
    alias_config_path: Path = DEFAULT_ALIAS_CONFIG,
    scope_config_path: Path = DEFAULT_SCOPE_CONFIG,
    output_path: Path | None = DEFAULT_OUTPUT,
    source_code: str | None = None,
    match_batch_code: str | None = None,
    channel_codes: Sequence[str] | None = None,
    dry_run: bool = False,
    write_candidate_boundaries: bool = False,
) -> BuildMatchReport:
    alias_config = load_json(alias_config_path)
    scope_config = load_json(scope_config_path)
    batch_code = match_batch_code or f"{DEFAULT_BATCH_PREFIX}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

    channel_query = (
        select(NavigationChannel)
        .where(NavigationChannel.is_enabled.is_(True))
        .order_by(NavigationChannel.sort_order, NavigationChannel.id)
    )
    if channel_codes:
        channel_query = channel_query.where(NavigationChannel.channel_code.in_(list(channel_codes)))
    channels = list((await session.execute(channel_query)).scalars())

    water_query = select(NavigationWaterArea).where(
        NavigationWaterArea.is_enabled.is_(True),
        NavigationWaterArea.source_layer_name != "rx8",
        or_(
            NavigationWaterArea.source_layer_role_code.is_(None),
            NavigationWaterArea.source_layer_role_code != "BACKUP_WATER_AREA",
        ),
    )
    if source_code:
        water_query = water_query.where(NavigationWaterArea.source_code == source_code)
    raw_water_areas = list((await session.execute(water_query)).scalars())
    all_water_areas, duplicate_layers_by_id = _dedupe_water_areas(raw_water_areas)

    current_boundaries = {
        boundary.channel_id: boundary
        for boundary in (
            await session.execute(
                select(NavigationChannelBoundary).where(NavigationChannelBoundary.is_current.is_(True))
            )
        ).scalars()
    }

    if not dry_run:
        channel_ids = [channel.id for channel in channels]
        if channel_ids:
            await session.execute(
                delete(NavigationChannelWaterAreaMatch).where(
                    NavigationChannelWaterAreaMatch.channel_id.in_(channel_ids),
                    NavigationChannelWaterAreaMatch.match_batch_code == batch_code,
                )
            )
            await session.execute(
                update(NavigationChannelWaterAreaMatch)
                .where(
                    NavigationChannelWaterAreaMatch.channel_id.in_(channel_ids),
                    NavigationChannelWaterAreaMatch.is_current.is_(True),
                )
                .values(is_current=False)
            )

    reports: list[ChannelWaterAreaMatchReport] = []
    match_row_count = 0
    candidate_boundaries_written = 0

    for channel in channels:
        terms = _terms_for_channel(channel, alias_config)
        channel_scope_bbox = _scope_bbox_for_channel(channel, scope_config)
        water_areas = [
            row for row in all_water_areas if channel_scope_bbox is None or _bbox_intersects(_bbox(row), channel_scope_bbox)
        ]
        boundary = current_boundaries.get(channel.id)
        boundary_bbox = _bbox(boundary) if boundary else None
        boundary_geometry = _boundary_geometry(boundary)
        base_issues: set[str] = set()
        if boundary is None or boundary.geometry_status_code != "AVAILABLE":
            base_issues.add("SEED_BOUNDARY_MISSING")
        elif boundary.boundary_quality_code == "REVIEW" or str(boundary.repair_status_code or "").startswith("REVIEW"):
            base_issues.add("SEED_BOUNDARY_NEED_REVIEW")

        matched_rows: dict[int, tuple[NavigationWaterArea, tuple[str, str, int], list[str]]] = {}
        for water_area in water_areas:
            match = _score_match(terms, water_area.water_name or water_area.normalized_water_name)
            if match is None:
                continue
            issue_codes: list[str] = []
            if boundary_bbox and not _bbox_intersects(_bbox(water_area), boundary_bbox):
                if match[2] < 90:
                    continue
                issue_codes.append("OUT_OF_CHANNEL_BOUNDARY_BBOX")
            elif boundary_geometry is not None and not _geometry_intersects(boundary_geometry, water_area):
                if match[2] < 90:
                    continue
                issue_codes.append("OUT_OF_CHANNEL_BOUNDARY_GEOMETRY")
            matched_rows[water_area.id] = (water_area, match, issue_codes)

        ordered_matches = sorted(
            matched_rows.values(),
            key=lambda item: (-item[1][2], _layer_priority(item[0].source_layer_name), item[0].source_layer_name, item[0].source_object_id),
        )
        best_score = ordered_matches[0][1][2] if ordered_matches else 0
        confidence_code = _confidence(best_score, len(ordered_matches))
        review_status_code, channel_issues = _review_status(
            channel=channel,
            matched_count=len(ordered_matches),
            confidence_code=confidence_code,
            base_issues=base_issues,
        )

        candidate_items: list[MatchWriteItem] = []
        for water_area, match, item_issues in ordered_matches:
            match_type_code, matched_term, score = match
            item_issue_codes = sorted(set(channel_issues + item_issues))
            item_review_status = "NEED_REVIEW" if item_issue_codes else "PUBLISHED"
            item = MatchWriteItem(
                water_area_id=water_area.id,
                water_name=water_area.water_name,
                source_layer_name=water_area.source_layer_name,
                source_object_id=water_area.source_object_id,
                match_type_code=match_type_code,
                matched_term=matched_term,
                score=score,
                confidence_code=confidence_code,
                review_status_code=item_review_status,
                issue_codes=item_issue_codes,
                duplicate_layer_names=duplicate_layers_by_id.get(water_area.id, []),
                bbox=_bbox(water_area),
            )
            candidate_items.append(item)
            if not dry_run:
                session.add(
                    NavigationChannelWaterAreaMatch(
                        channel_id=channel.id,
                        water_area_id=water_area.id,
                        match_batch_code=batch_code,
                        match_type_code=match_type_code,
                        matched_term=matched_term,
                        score=score,
                        confidence_code=confidence_code,
                        review_status_code=item_review_status,
                        issue_codes=item_issue_codes,
                        is_current=True,
                        source_trace_json={
                            "source_code": water_area.source_code,
                            "source_layer_name": water_area.source_layer_name,
                            "source_object_id": water_area.source_object_id,
                            "duplicate_layer_names": duplicate_layers_by_id.get(water_area.id, []),
                            "scope_code": _scope_code_for_channel(channel, scope_config),
                            "alias_config_version": alias_config.get("version"),
                        },
                    )
                )
                match_row_count += 1

        candidate_written = False
        if write_candidate_boundaries and not dry_run and ordered_matches:
            if await _write_candidate_boundary(session, channel.id, [item[0] for item in ordered_matches]):
                candidate_written = True
                candidate_boundaries_written += 1

        reports.append(
            ChannelWaterAreaMatchReport(
                channel_id=channel.id,
                channel_code=channel.channel_code,
                channel_name=channel.channel_name,
                matched_water_area_count=len(ordered_matches),
                best_score=best_score,
                confidence_code=confidence_code,
                review_status_code=review_status_code,
                issue_codes=channel_issues,
                candidate_boundary_written=candidate_written,
                candidates=candidate_items[:50],
            )
        )

    if not dry_run:
        await session.commit()
        if session.get_bind().dialect.name == "postgresql":
            await refresh_postgis_geometry_columns()

    if dry_run:
        match_row_count = sum(item.matched_water_area_count for item in reports)

    report = BuildMatchReport(
        report_version="navigation_channel_water_area_match_v1",
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        dry_run=dry_run,
        write_candidate_boundaries=write_candidate_boundaries,
        source_code=source_code,
        match_batch_code=batch_code,
        alias_config_path=str(alias_config_path),
        scope_config_path=str(scope_config_path),
        output_path=str(output_path) if output_path else None,
        channel_count=len(channels),
        water_area_count=len(raw_water_areas),
        match_row_count=match_row_count,
        candidate_boundaries_written=candidate_boundaries_written,
        channels=reports,
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return report


async def _prepare_schema() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Persist navigation channel water-area matches.")
    parser.add_argument("--source-code", default=None, help="Optional navigation_water_area source_code filter.")
    parser.add_argument("--match-batch-code", default=None, help="Optional stable match batch code.")
    parser.add_argument("--channel-codes", nargs="*", default=None, help="Optional channel_code subset.")
    parser.add_argument("--alias-config", type=Path, default=DEFAULT_ALIAS_CONFIG)
    parser.add_argument("--scope-config", type=Path, default=DEFAULT_SCOPE_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true", help="Build report without writing match rows or candidate boundaries.")
    parser.add_argument(
        "--write-candidate-boundaries",
        action="store_true",
        help="Create/update non-current RIVER_MATCH_CANDIDATE boundaries for matched channels.",
    )
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    await _prepare_schema()
    async with AsyncSessionLocal() as session:
        report = await build_channel_water_area_matches(
            session=session,
            alias_config_path=args.alias_config,
            scope_config_path=args.scope_config,
            output_path=args.output,
            source_code=args.source_code,
            match_batch_code=args.match_batch_code,
            channel_codes=args.channel_codes,
            dry_run=args.dry_run,
            write_candidate_boundaries=args.write_candidate_boundaries,
        )
    print(json.dumps(report.as_dict()["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
