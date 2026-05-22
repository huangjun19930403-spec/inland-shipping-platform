"""Build water-area match reports and optional candidate channel boundaries.

Round 5 only links raw water areas to existing navigation channels. It preserves
seed boundaries and never creates centerlines, graph nodes, graph edges, or
route results.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, engine
from app.models import NavigationWaterArea
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.models.base import Base

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ALIAS_CONFIG = PROJECT_ROOT / "scripts" / "seed_data" / "navigation" / "navigation_channel_aliases.json"
DEFAULT_SCOPE_CONFIG = PROJECT_ROOT / "scripts" / "seed_data" / "navigation" / "navigation_real_scope.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "data_audit" / "navigation_channel_boundary_match_report.json"


@dataclass(slots=True)
class MatchCandidate:
    water_area_id: int
    water_name: str | None
    normalized_water_name: str | None
    source_layer_name: str
    source_object_id: str
    water_type_code: str
    match_type_code: str
    matched_term: str
    score: int
    area_km2: float | None
    bbox: list[float | None]


@dataclass(slots=True)
class ChannelMatchReport:
    channel_id: int
    channel_code: str
    channel_name: str
    planning_level_code: str
    channel_type_code: str
    review_required: bool
    seed_boundary_status_code: str
    seed_boundary_quality_code: str
    seed_boundary_repair_status_code: str
    matched_water_area_count: int
    best_score: int
    confidence_code: str
    review_status_code: str
    issue_codes: list[str] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)
    candidates: list[MatchCandidate] = field(default_factory=list)
    candidate_boundary_written: bool = False


@dataclass(slots=True)
class BuildBoundaryReport:
    report_version: str
    generated_at: str
    dry_run: bool
    write_candidate_boundaries: bool
    source_code: str | None
    alias_config_path: str
    scope_config_path: str
    output_path: str | None
    channel_count: int
    water_area_count: int
    candidate_boundaries_written: int
    channels: list[ChannelMatchReport]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["summary"] = {
            "matched_channels": sum(1 for item in self.channels if item.matched_water_area_count > 0),
            "missing_match_channels": sum(1 for item in self.channels if item.matched_water_area_count == 0),
            "need_review_channels": sum(1 for item in self.channels if item.review_status_code == "NEED_REVIEW"),
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
    for token in (" ", "\t", "\n", "—", "-", "_", "（", "）", "(", ")", "/"):
        text = text.replace(token, "")
    return text


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


def _bbox(row: NavigationWaterArea) -> list[float | None]:
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


def _confidence(best_score: int, matched_count: int) -> str:
    if matched_count == 0:
        return "MISSING"
    if best_score >= 90:
        return "HIGH_CONFIDENCE"
    if best_score >= 65:
        return "MEDIUM_CONFIDENCE"
    return "LOW_CONFIDENCE"


def _boundary_status(boundary: NavigationChannelBoundary | None) -> tuple[str, str, str]:
    if boundary is None:
        return ("MISSING", "MISSING", "MISSING")
    return (
        boundary.geometry_status_code,
        boundary.boundary_quality_code,
        boundary.repair_status_code,
    )


def _is_available_seed_boundary(boundary: NavigationChannelBoundary | None) -> bool:
    return bool(boundary and boundary.is_current and boundary.geometry_status_code == "AVAILABLE")


def _review_status(
    *,
    channel: NavigationChannel,
    boundary: NavigationChannelBoundary | None,
    matched_count: int,
    confidence_code: str,
) -> tuple[str, list[str]]:
    issues: list[str] = []
    if matched_count == 0:
        issues.append("NO_WATER_AREA_MATCH")
    if channel.review_required:
        issues.append("CHANNEL_REVIEW_REQUIRED")
    if boundary is None or boundary.geometry_status_code == "MISSING":
        issues.append("SEED_BOUNDARY_MISSING")
    elif boundary.boundary_quality_code == "REVIEW" or boundary.repair_status_code.startswith("REVIEW"):
        issues.append("SEED_BOUNDARY_NEED_REVIEW")
    if confidence_code in {"MISSING", "LOW_CONFIDENCE"}:
        issues.append("LOW_MATCH_CONFIDENCE")

    if issues:
        return ("NEED_REVIEW", sorted(set(issues)))
    return ("APPROVED", [])


def _candidate_from_row(row: NavigationWaterArea, match: tuple[str, str, int]) -> MatchCandidate:
    match_type, matched_term, score = match
    return MatchCandidate(
        water_area_id=row.id,
        water_name=row.water_name,
        normalized_water_name=row.normalized_water_name,
        source_layer_name=row.source_layer_name,
        source_object_id=row.source_object_id,
        water_type_code=row.water_type_code,
        match_type_code=match_type,
        matched_term=matched_term,
        score=score,
        area_km2=float(row.area_km2) if row.area_km2 is not None else None,
        bbox=_bbox(row),
    )


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
        "center_longitude": centroid.x,
        "center_latitude": centroid.y,
        "display_center_longitude": centroid.x,
        "display_center_latitude": centroid.y,
        "bbox_min_lng": min_lng,
        "bbox_min_lat": min_lat,
        "bbox_max_lng": max_lng,
        "bbox_max_lat": max_lat,
        "source_shape_length_degree": geometry.length,
        "source_shape_area_degree": geometry.area,
        "ring_count": ring_count,
        "point_count": point_count,
        "geometry_status_code": "AVAILABLE",
        "boundary_quality_code": "REVIEW",
        "connectivity_status_code": "UNKNOWN",
        "repair_status_code": "REVIEW_CANDIDATE",
        "coverage_policy_code": "RIVER_NAME_MATCH_CANDIDATE",
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
    geometries = [shape(row.geometry_json) for row in water_area_rows if row.geometry_json]
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
                NavigationChannelBoundary.coverage_policy_code == "RIVER_NAME_MATCH_CANDIDATE",
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


async def build_channel_boundary_report(
    *,
    session: AsyncSession,
    alias_config_path: Path = DEFAULT_ALIAS_CONFIG,
    scope_config_path: Path = DEFAULT_SCOPE_CONFIG,
    output_path: Path | None = DEFAULT_OUTPUT,
    source_code: str | None = None,
    channel_codes: Sequence[str] | None = None,
    dry_run: bool = False,
    write_candidate_boundaries: bool = False,
) -> BuildBoundaryReport:
    alias_config = load_json(alias_config_path)
    scope_config = load_json(scope_config_path)
    scope_bbox = _scope_bbox(scope_config)

    channel_query = select(NavigationChannel).where(NavigationChannel.is_enabled.is_(True)).order_by(NavigationChannel.sort_order, NavigationChannel.id)
    if channel_codes:
        channel_query = channel_query.where(NavigationChannel.channel_code.in_(list(channel_codes)))
    channels = list((await session.execute(channel_query)).scalars())

    water_query = select(NavigationWaterArea).where(NavigationWaterArea.is_enabled.is_(True))
    if source_code:
        water_query = water_query.where(NavigationWaterArea.source_code == source_code)
    water_areas = list((await session.execute(water_query)).scalars())

    current_boundaries = {
        boundary.channel_id: boundary
        for boundary in (
            await session.execute(
                select(NavigationChannelBoundary).where(NavigationChannelBoundary.is_current.is_(True))
            )
        ).scalars()
    }

    report_items: list[ChannelMatchReport] = []
    written = 0

    for channel in channels:
        terms = _terms_for_channel(channel, alias_config)
        candidates: list[MatchCandidate] = []
        matched_rows: dict[int, NavigationWaterArea] = {}
        for water_area in water_areas:
            water_bbox = _bbox(water_area)
            if scope_bbox and not _bbox_intersects(water_bbox, scope_bbox):
                continue
            match = _score_match(terms, water_area.water_name or water_area.normalized_water_name)
            if match is None:
                continue
            candidates.append(_candidate_from_row(water_area, match))
            matched_rows[water_area.id] = water_area

        candidates.sort(key=lambda item: (-item.score, item.source_layer_name, item.source_object_id))
        best_score = candidates[0].score if candidates else 0
        confidence_code = _confidence(best_score, len(candidates))
        boundary = current_boundaries.get(channel.id)
        boundary_status, boundary_quality, boundary_repair = _boundary_status(boundary)
        review_status, issues = _review_status(
            channel=channel,
            boundary=boundary,
            matched_count=len(candidates),
            confidence_code=confidence_code,
        )
        item = ChannelMatchReport(
            channel_id=channel.id,
            channel_code=channel.channel_code,
            channel_name=channel.channel_name,
            planning_level_code=channel.planning_level_code,
            channel_type_code=channel.channel_type_code,
            review_required=channel.review_required,
            seed_boundary_status_code=boundary_status,
            seed_boundary_quality_code=boundary_quality,
            seed_boundary_repair_status_code=boundary_repair,
            matched_water_area_count=len(candidates),
            best_score=best_score,
            confidence_code=confidence_code,
            review_status_code=review_status,
            issue_codes=issues,
            matched_terms=sorted({candidate.matched_term for candidate in candidates}),
            candidates=candidates[:20],
        )

        if (
            write_candidate_boundaries
            and not dry_run
            and candidates
            and not _is_available_seed_boundary(boundary)
        ):
            if await _write_candidate_boundary(session, channel.id, list(matched_rows.values())):
                item.candidate_boundary_written = True
                written += 1

        report_items.append(item)

    if write_candidate_boundaries and not dry_run:
        await session.commit()

    report = BuildBoundaryReport(
        report_version="round5_navigation_boundary_match_v1",
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        dry_run=dry_run,
        write_candidate_boundaries=write_candidate_boundaries,
        source_code=source_code,
        alias_config_path=str(alias_config_path),
        scope_config_path=str(scope_config_path),
        output_path=str(output_path) if output_path else None,
        channel_count=len(channels),
        water_area_count=len(water_areas),
        candidate_boundaries_written=written,
        channels=report_items,
    )

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    return report


async def _prepare_schema() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build navigation channel to water-area match report.")
    parser.add_argument("--source-code", default=None, help="Optional navigation_water_area source_code filter.")
    parser.add_argument("--channel-codes", nargs="*", default=None, help="Optional channel_code subset.")
    parser.add_argument("--alias-config", type=Path, default=DEFAULT_ALIAS_CONFIG)
    parser.add_argument("--scope-config", type=Path, default=DEFAULT_SCOPE_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true", help="Build report without writing candidate boundaries.")
    parser.add_argument(
        "--write-candidate-boundaries",
        action="store_true",
        help="Create or update non-current REVIEW candidate boundaries only for channels without an available seed boundary.",
    )
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    await _prepare_schema()
    async with AsyncSessionLocal() as session:
        report = await build_channel_boundary_report(
            session=session,
            alias_config_path=args.alias_config,
            scope_config_path=args.scope_config,
            output_path=args.output,
            source_code=args.source_code,
            channel_codes=args.channel_codes,
            dry_run=args.dry_run,
            write_candidate_boundaries=args.write_candidate_boundaries,
        )
    print(json.dumps(report.as_dict()["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
