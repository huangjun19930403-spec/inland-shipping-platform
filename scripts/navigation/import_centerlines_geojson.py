"""Import navigation centerlines from GeoJSON.

This importer creates centerline assets and publish state. It never creates graph
nodes, graph edges, route requests, or route results.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from shapely.geometry import LineString, MultiLineString, mapping, shape
from shapely.geometry.base import BaseGeometry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, engine
from app.models import NavigationChannelCenterline
from app.models.address import NavigationChannel, NavigationChannelBoundary, NavigationChannelSegment
from app.models.base import Base

DIRECT_PUBLISHABLE_SOURCES = {"MANUAL", "SEED_CENTERLINE"}
PUBLISHABLE_AFTER_CONFIRMATION_SOURCES = {"OSM_WATERWAY"}
NEVER_AUTO_PUBLISH_SOURCES = {"WATER_SKELETON", "HIFLEET_REFERENCE", "AIS_INFERRED", "HYDRORIVERS"}
SUPPORTED_SOURCES = DIRECT_PUBLISHABLE_SOURCES | PUBLISHABLE_AFTER_CONFIRMATION_SOURCES | NEVER_AUTO_PUBLISH_SOURCES
GRAPH_READY_QUALITY_CODES = {"READY", "READY_WITH_WARNING"}


@dataclass(slots=True)
class CenterlineImportIssue:
    centerline_code: str | None
    issue_code: str
    message: str


@dataclass(slots=True)
class CenterlineImportRow:
    channel_id: int
    segment_id: int | None
    centerline_code: str
    centerline_name: str | None
    geometry_json: dict[str, Any]
    source_type_code: str
    direction_code: str
    is_main_line: bool
    confidence_score: int
    quality_code: str
    review_status_code: str
    version_no: int
    parent_centerline_id: int | None
    is_current: bool
    source_trace_json: dict[str, Any] | None
    approved_by: int | None
    approved_at: datetime | None
    bbox_min_lng: float | None
    bbox_min_lat: float | None
    bbox_max_lng: float | None
    bbox_max_lat: float | None

    def model_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CenterlineImportSummary:
    source_file: str
    dry_run: bool
    rows_read: int = 0
    rows_prepared: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_need_review: int = 0
    rows_rejected: int = 0
    rows_out_of_boundary: int = 0
    rows_duplicated: int = 0
    rows_skipped: int = 0
    issues: list[CenterlineImportIssue] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["issues"] = [asdict(issue) for issue in self.issues]
        return payload


def _load_geojson(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("type") != "FeatureCollection":
        raise ValueError("Centerline input must be a GeoJSON FeatureCollection")
    return payload


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _geometry_parts(geometry_json: dict[str, Any]) -> list[BaseGeometry]:
    geometry = shape(geometry_json)
    if isinstance(geometry, LineString):
        return [geometry]
    if isinstance(geometry, MultiLineString):
        return list(geometry.geoms)
    return [geometry]


def _line_is_broken(geometry: BaseGeometry) -> bool:
    return not isinstance(geometry, LineString) or geometry.is_empty or len(geometry.coords) < 2 or not geometry.is_valid


def _resolve_status(
    *,
    source_type_code: str,
    requested_review_status: str,
    requested_quality: str,
    requested_current: bool,
    confidence_score: int,
    out_of_boundary: bool,
    duplicated: bool,
    broken: bool,
) -> tuple[str, str, bool, list[str]]:
    review_status = requested_review_status or "NEED_REVIEW"
    quality = requested_quality or "NEED_REVIEW"
    is_current = requested_current
    issues: list[str] = []

    if source_type_code not in SUPPORTED_SOURCES:
        review_status = "NEED_REVIEW"
        quality = "NEED_REVIEW"
        is_current = False
        issues.append("UNSUPPORTED_SOURCE_TYPE")

    if broken:
        review_status = "NEED_REVIEW"
        quality = "BROKEN"
        is_current = False
        issues.append("CENTERLINE_BROKEN")

    if duplicated:
        review_status = "REJECTED"
        quality = "DUPLICATED"
        is_current = False
        issues.append("CENTERLINE_DUPLICATED")

    if out_of_boundary:
        review_status = "NEED_REVIEW"
        quality = "OUT_OF_BOUNDARY"
        is_current = False
        issues.append("CENTERLINE_OUT_OF_BOUNDARY")

    if confidence_score < 75 and quality in GRAPH_READY_QUALITY_CODES:
        review_status = "NEED_REVIEW"
        quality = "NEED_REVIEW"
        is_current = False
        issues.append("CENTERLINE_LOW_CONFIDENCE")

    if source_type_code in NEVER_AUTO_PUBLISH_SOURCES:
        review_status = "NEED_REVIEW"
        if quality in GRAPH_READY_QUALITY_CODES:
            quality = "NEED_REVIEW"
        is_current = False
        issues.append("SOURCE_NOT_AUTO_PUBLISHABLE")

    if source_type_code == "OSM_WATERWAY" and review_status != "PUBLISHED":
        is_current = False
        issues.append("OSM_NEEDS_CONFIRMATION")

    if review_status != "PUBLISHED":
        is_current = False

    if is_current and (quality not in GRAPH_READY_QUALITY_CODES or review_status != "PUBLISHED"):
        is_current = False
        issues.append("CURRENT_REQUIRES_PUBLISHED_READY")

    return review_status, quality, is_current, sorted(set(issues))


def _feature_code(base_code: str, part_count: int, part_index: int) -> str:
    if part_count == 1:
        return base_code
    return f"{base_code}-part-{part_index:03d}"


async def _load_channels(session: AsyncSession) -> dict[str, NavigationChannel]:
    rows = (await session.execute(select(NavigationChannel))).scalars()
    return {row.channel_code: row for row in rows}


async def _load_segments(session: AsyncSession) -> dict[str, NavigationChannelSegment]:
    rows = (await session.execute(select(NavigationChannelSegment))).scalars()
    return {row.segment_code: row for row in rows}


async def _load_boundaries(session: AsyncSession) -> dict[int, BaseGeometry]:
    rows = (
        await session.execute(
            select(NavigationChannelBoundary).where(
                NavigationChannelBoundary.is_current.is_(True),
                NavigationChannelBoundary.geometry_status_code == "AVAILABLE",
            )
        )
    ).scalars()
    return {row.channel_id: shape(row.geometry_json) for row in rows if row.geometry_json}


async def _load_existing_geometry_keys(session: AsyncSession) -> dict[int, dict[str, set[str]]]:
    rows = (await session.execute(select(NavigationChannelCenterline))).scalars()
    keys: dict[int, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in rows:
        if row.geometry_json:
            keys[row.channel_id][shape(row.geometry_json).wkb_hex].add(row.centerline_code)
    return keys


async def _upsert_centerline(session: AsyncSession, row: CenterlineImportRow) -> str:
    existing = (
        await session.execute(
            select(NavigationChannelCenterline).where(
                NavigationChannelCenterline.centerline_code == row.centerline_code
            )
        )
    ).scalar_one_or_none()
    payload = row.model_payload()
    if existing is None:
        session.add(NavigationChannelCenterline(**payload))
        return "inserted"
    for key, value in payload.items():
        setattr(existing, key, value)
    return "updated"


def _row_from_feature(
    *,
    feature: dict[str, Any],
    part_geometry: BaseGeometry,
    part_count: int,
    part_index: int,
    channel: NavigationChannel,
    segment: NavigationChannelSegment | None,
    boundary_geometry: BaseGeometry | None,
    existing_geometry_keys: dict[str, set[str]],
) -> tuple[CenterlineImportRow, list[str]]:
    props = feature.get("properties") or {}
    base_code = str(props.get("centerline_code") or "").strip()
    centerline_code = _feature_code(base_code, part_count, part_index)
    source_type_code = str(props.get("source_type_code") or "MANUAL").strip().upper()
    direction_code = str(props.get("direction_code") or "BIDIRECTIONAL").strip().upper()
    confidence_score = max(0, min(100, _as_int(props.get("confidence_score"), 0)))
    requested_review_status = str(props.get("review_status_code") or "NEED_REVIEW").strip().upper()
    requested_quality = str(props.get("quality_code") or "NEED_REVIEW").strip().upper()
    requested_current = _as_bool(props.get("is_current"), default=requested_review_status == "PUBLISHED")

    broken = _line_is_broken(part_geometry)
    out_of_boundary = bool(
        boundary_geometry is not None
        and not broken
        and not (boundary_geometry.covers(part_geometry) or boundary_geometry.intersects(part_geometry))
    )
    duplicate_codes = existing_geometry_keys.get(part_geometry.wkb_hex, set())
    duplicated = any(code != centerline_code for code in duplicate_codes)
    review_status, quality, is_current, issues = _resolve_status(
        source_type_code=source_type_code,
        requested_review_status=requested_review_status,
        requested_quality=requested_quality,
        requested_current=requested_current,
        confidence_score=confidence_score,
        out_of_boundary=out_of_boundary,
        duplicated=duplicated,
        broken=broken,
    )

    min_lng, min_lat, max_lng, max_lat = part_geometry.bounds if not part_geometry.is_empty else (None, None, None, None)
    source_trace = {
        "source_group_id": props.get("source_group_id"),
        "source_operator": props.get("source_operator"),
        "source_trace": props.get("source_trace"),
        "notes": props.get("notes"),
        "part_index": part_index,
        "part_count": part_count,
        "issues": issues,
    }
    published_at = None
    if review_status == "PUBLISHED":
        published_at = datetime.now(UTC).replace(tzinfo=None)

    return (
        CenterlineImportRow(
            channel_id=channel.id,
            segment_id=segment.id if segment else None,
            centerline_code=centerline_code,
            centerline_name=props.get("centerline_name"),
            geometry_json=mapping(part_geometry),
            source_type_code=source_type_code,
            direction_code=direction_code,
            is_main_line=_as_bool(props.get("is_main_line"), default=True),
            confidence_score=confidence_score,
            quality_code=quality,
            review_status_code=review_status,
            version_no=_as_int(props.get("version_no"), 1),
            parent_centerline_id=None,
            is_current=is_current,
            source_trace_json=source_trace,
            approved_by=_as_int(props.get("approved_by"), 0) or None,
            approved_at=published_at,
            bbox_min_lng=float(min_lng) if min_lng is not None else None,
            bbox_min_lat=float(min_lat) if min_lat is not None else None,
            bbox_max_lng=float(max_lng) if max_lng is not None else None,
            bbox_max_lat=float(max_lat) if max_lat is not None else None,
        ),
        issues,
    )


async def import_centerlines_geojson(
    *,
    input_path: Path,
    dry_run: bool = False,
    session: AsyncSession,
) -> CenterlineImportSummary:
    payload = _load_geojson(input_path)
    summary = CenterlineImportSummary(source_file=str(input_path), dry_run=dry_run)
    channels_by_code = await _load_channels(session)
    segments_by_code = await _load_segments(session)
    boundaries_by_channel_id = await _load_boundaries(session)
    existing_geometry_keys = await _load_existing_geometry_keys(session)
    batch_geometry_keys: dict[int, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

    for feature in payload.get("features", []):
        summary.rows_read += 1
        props = feature.get("properties") or {}
        base_code = str(props.get("centerline_code") or "").strip()
        if not base_code:
            summary.rows_skipped += 1
            summary.issues.append(CenterlineImportIssue(None, "CENTERLINE_CODE_REQUIRED", "centerline_code is required"))
            continue

        channel = None
        channel_id = props.get("channel_id")
        if channel_id is not None:
            channel = (
                await session.execute(select(NavigationChannel).where(NavigationChannel.id == int(channel_id)))
            ).scalar_one_or_none()
        if channel is None:
            channel_code = str(props.get("channel_code") or "").strip()
            channel = channels_by_code.get(channel_code)
        if channel is None:
            summary.rows_skipped += 1
            summary.issues.append(CenterlineImportIssue(base_code, "CHANNEL_NOT_RESOLVED", "channel_code or channel_id was not resolved"))
            continue

        segment = None
        segment_code = props.get("segment_code")
        if segment_code:
            segment = segments_by_code.get(str(segment_code))

        try:
            parts = _geometry_parts(feature["geometry"])
        except Exception as exc:
            summary.rows_skipped += 1
            summary.issues.append(CenterlineImportIssue(base_code, "CENTERLINE_GEOMETRY_INVALID", str(exc)))
            continue

        for part_index, part_geometry in enumerate(parts, start=1):
            part_code = _feature_code(base_code, len(parts), part_index)
            known_keys = existing_geometry_keys[channel.id].copy()
            for geometry_key, centerline_codes in batch_geometry_keys[channel.id].items():
                known_keys.setdefault(geometry_key, set()).update(centerline_codes)
            row, issues = _row_from_feature(
                feature=feature,
                part_geometry=part_geometry,
                part_count=len(parts),
                part_index=part_index,
                channel=channel,
                segment=segment,
                boundary_geometry=boundaries_by_channel_id.get(channel.id),
                existing_geometry_keys=known_keys,
            )
            summary.rows_prepared += 1
            if row.review_status_code == "NEED_REVIEW":
                summary.rows_need_review += 1
            if row.review_status_code == "REJECTED":
                summary.rows_rejected += 1
            if row.quality_code == "OUT_OF_BOUNDARY":
                summary.rows_out_of_boundary += 1
            if row.quality_code == "DUPLICATED":
                summary.rows_duplicated += 1
            for issue in issues:
                summary.issues.append(CenterlineImportIssue(part_code, issue, issue))

            batch_geometry_keys[channel.id][part_geometry.wkb_hex].add(part_code)
            if dry_run:
                continue
            action = await _upsert_centerline(session, row)
            if action == "inserted":
                summary.rows_inserted += 1
            else:
                summary.rows_updated += 1

    if not dry_run:
        await session.commit()

    return summary


async def _prepare_schema() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import navigation centerline candidates from GeoJSON.")
    parser.add_argument("--input", required=True, type=Path, help="GeoJSON FeatureCollection path.")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing centerline rows.")
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    if not args.dry_run:
        await _prepare_schema()
    async with AsyncSessionLocal() as session:
        summary = await import_centerlines_geojson(input_path=args.input, dry_run=args.dry_run, session=session)
    print(json.dumps(summary.as_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
