"""Seed final navigation channel base data.

The seed is intentionally self-contained: it reads curated JSON result data and
does not read revier.zip or any long-running cleaning source at runtime.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from datetime import timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from pyproj import Geod
from sqlalchemy import delete, or_, select, text, update
from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point, mapping, shape
from shapely.validation import make_valid

from app.core.database import AsyncSessionLocal, engine
from app.models import (
    NavigationAnnotationTask,
    NavigationCenterlineControlPoint,
    NavigationCenterlinePointSet,
    NavigationCenterlineSegment,
    NavigationChannelCenterline,
    NavigationChannelWaterAreaMatch,
    NavigationChannelWaterBodyMatch,
    NavigationGeometryDraft,
    NavigationGraphEdge,
    NavigationGraphEdgeConstraint,
    NavigationGraphNode,
    NavigationRouteQualityIssue,
)
from app.models.address import (
    NavigationChannel,
    NavigationChannelBoundary,
    NavigationChannelSegment,
    NavigationChannelSourceAudit,
)
from app.models.base import Base

PROJECT_ROOT = Path(__file__).resolve().parents[3]
NAVIGATION_CHANNEL_DATA_FILE = PROJECT_ROOT / "scripts" / "seed_data" / "navigation" / "navigation_channels.json"
COORDINATE_SCALE = Decimal("0.000000000000001")
DEGREE_MEASURE_SCALE = Decimal("0.000000000000000001")
GEOD = Geod(ellps="WGS84")


def load_navigation_channel_seed(path: Path = NAVIGATION_CHANNEL_DATA_FILE) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


_NAVIGATION_METADATA = load_navigation_channel_seed()
DATA_VERSION = str(_NAVIGATION_METADATA["data_version"])
CHANNEL_COUNT = int(_NAVIGATION_METADATA["metadata"]["channel_count"])
BOUNDARY_COUNT = int(_NAVIGATION_METADATA["metadata"]["boundary_count"])
SEGMENT_COUNT = int(_NAVIGATION_METADATA["metadata"]["segment_count"])
SOURCE_AUDIT_COUNT = int(_NAVIGATION_METADATA["metadata"]["source_audit_count"])
EXCLUDED_TOP_LEVEL_NATURAL_WATER_AREA_COUNT = int(
    _NAVIGATION_METADATA["metadata"]["excluded_top_level_natural_water_area_count"]
)
CHANNEL_TYPE_COUNTS = dict(_NAVIGATION_METADATA["metadata"]["channel_type_counts"])
PLANNING_LEVEL_COUNTS = dict(_NAVIGATION_METADATA["metadata"]["planning_level_counts"])
BOUNDARY_STATUS_COUNTS = dict(_NAVIGATION_METADATA["metadata"]["boundary_status_counts"])
LABELS = dict(_NAVIGATION_METADATA["metadata"]["labels"])


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _quantize_decimal(value: Any, scale: Decimal) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value)).quantize(scale, rounding=ROUND_HALF_UP)


def _normalize_boundary_numeric_fields(payload: dict[str, Any]) -> dict[str, Any]:
    for field in (
        "center_longitude",
        "center_latitude",
        "display_center_longitude",
        "display_center_latitude",
        "bbox_min_lng",
        "bbox_min_lat",
        "bbox_max_lng",
        "bbox_max_lat",
    ):
        payload[field] = _quantize_decimal(payload.get(field), COORDINATE_SCALE)
    for field in ("source_shape_length_degree", "source_shape_area_degree"):
        payload[field] = _quantize_decimal(payload.get(field), DEGREE_MEASURE_SCALE)
    return payload


def _normalize_segment_guide_fields(payload: dict[str, Any]) -> dict[str, Any]:
    for field in (
        "guide_bbox_min_lng",
        "guide_bbox_min_lat",
        "guide_bbox_max_lng",
        "guide_bbox_max_lat",
    ):
        payload[field] = _quantize_decimal(payload.get(field), COORDINATE_SCALE)
    payload["guide_length_m"] = _quantize_decimal(payload.get("guide_length_m"), Decimal("0.01"))
    return payload


def _geojson_geometry(geometry_json: dict[str, Any]) -> dict[str, Any]:
    if geometry_json.get("type") == "Feature" and isinstance(geometry_json.get("geometry"), dict):
        return geometry_json["geometry"]
    return geometry_json


def _longest_line(geometry: Any) -> LineString | None:
    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, LineString):
        return geometry if len(geometry.coords) >= 2 else None
    if isinstance(geometry, MultiLineString):
        lines = [item for item in geometry.geoms if len(item.coords) >= 2]
        return max(lines, key=_line_length_m) if lines else None
    if isinstance(geometry, GeometryCollection):
        lines = [line for part in geometry.geoms if (line := _longest_line(part)) is not None]
        return max(lines, key=_line_length_m) if lines else None
    return None


def _line_length_m(line: LineString) -> float:
    coords = list(line.coords)
    if len(coords) < 2:
        return 0.0
    lngs = [float(coord[0]) for coord in coords]
    lats = [float(coord[1]) for coord in coords]
    return abs(float(GEOD.line_length(lngs, lats)))


def _clean_coords(coords: list[tuple[float, float]]) -> list[tuple[float, float]]:
    cleaned: list[tuple[float, float]] = []
    for lng, lat in coords:
        point = (round(float(lng), 6), round(float(lat), 6))
        if cleaned and abs(cleaned[-1][0] - point[0]) < 1e-8 and abs(cleaned[-1][1] - point[1]) < 1e-8:
            continue
        cleaned.append(point)
    return cleaned


def _derive_boundary_midline(boundary_geometry_json: dict[str, Any]) -> LineString | None:
    try:
        geometry = make_valid(shape(_geojson_geometry(boundary_geometry_json)))
    except Exception:
        return None
    if geometry.is_empty:
        return None
    min_lng, min_lat, max_lng, max_lat = geometry.bounds
    span_lng = float(max_lng - min_lng)
    span_lat = float(max_lat - min_lat)
    if span_lng <= 0 or span_lat <= 0:
        return None
    span = max(span_lng, span_lat)
    tolerance = max(span / 1400.0, 0.00008)
    try:
        working_geometry = make_valid(geometry.simplify(tolerance, preserve_topology=True))
        if not working_geometry.is_empty:
            geometry = working_geometry
            min_lng, min_lat, max_lng, max_lat = geometry.bounds
            span_lng = float(max_lng - min_lng)
            span_lat = float(max_lat - min_lat)
            span = max(span_lng, span_lat)
    except Exception:
        pass
    count = 180 if span > 10 else 120 if span > 6 else 72
    margin = max(span_lng, span_lat) * 0.02
    coords: list[tuple[float, float]] = []
    if span_lng >= span_lat:
        for index in range(count):
            lng = min_lng + span_lng * index / max(count - 1, 1)
            cutter = LineString([(lng, min_lat - margin), (lng, max_lat + margin)])
            line = _longest_line(geometry.intersection(cutter))
            if line is None:
                continue
            point = line.interpolate(0.5, normalized=True)
            coords.append((float(point.x), float(point.y)))
    else:
        for index in range(count):
            lat = min_lat + span_lat * index / max(count - 1, 1)
            cutter = LineString([(min_lng - margin, lat), (max_lng + margin, lat)])
            line = _longest_line(geometry.intersection(cutter))
            if line is None:
                continue
            point = line.interpolate(0.5, normalized=True)
            coords.append((float(point.x), float(point.y)))
    cleaned = _clean_coords(coords)
    if len(cleaned) < 2:
        return None
    line = LineString(cleaned)
    return line if _line_length_m(line) > 100.0 else None


def _split_line_evenly(line: LineString, count: int) -> list[LineString]:
    if count <= 0:
        return []
    if count == 1:
        return [line]
    parts: list[LineString] = []
    interior = [(Point(coord), line.project(Point(coord), normalized=True)) for coord in line.coords[1:-1]]
    for index in range(count):
        start_ratio = index / count
        end_ratio = (index + 1) / count
        start = line.interpolate(start_ratio, normalized=True)
        end = line.interpolate(end_ratio, normalized=True)
        coords: list[tuple[float, float]] = [(float(start.x), float(start.y))]
        coords.extend(
            (float(point.x), float(point.y))
            for point, ratio in interior
            if start_ratio < ratio < end_ratio
        )
        coords.append((float(end.x), float(end.y)))
        cleaned = _clean_coords(coords)
        if len(cleaned) >= 2:
            parts.append(LineString(cleaned))
    return parts


def _segment_payload_with_guide(
    segment_payload: dict[str, Any],
    boundary_payload: dict[str, Any],
    *,
    derive_missing_guides: bool,
    derived_boundary_midline: LineString | None = None,
) -> dict[str, Any]:
    payload = dict(segment_payload)
    if payload.get("guide_geometry_json"):
        return _normalize_segment_guide_fields(payload)
    if not derive_missing_guides:
        return _normalize_segment_guide_fields(payload)
    line = derived_boundary_midline or _derive_boundary_midline(boundary_payload.get("geometry_json") or {})
    if line is None:
        return _normalize_segment_guide_fields(payload)
    min_lng, min_lat, max_lng, max_lat = line.bounds
    payload.update(
        {
            "guide_geometry_json": json.loads(json.dumps(mapping(line))),
            "guide_source_type_code": "SEED_BOUNDARY_SECTION_MIDPOINT_GUIDE",
            "guide_quality_code": "READY_WITH_WARNING",
            "guide_length_m": round(_line_length_m(line), 2),
            "guide_bbox_min_lng": min_lng,
            "guide_bbox_min_lat": min_lat,
            "guide_bbox_max_lng": max_lng,
            "guide_bbox_max_lat": max_lat,
            "guide_trace_json": {
                "source": "production_navigation_seed",
                "algorithm": "BOUNDARY_SECTION_MIDPOINT_GUIDE_V1",
                "requires_operator_review": True,
            },
        }
    )
    return _normalize_segment_guide_fields(payload)


async def _prepare_schema(drop_legacy: bool) -> None:
    async with engine.begin() as conn:
        if drop_legacy:
            await _drop_legacy_table_if_exists(conn, "water_system_boundary")
            await _drop_legacy_table_if_exists(conn, "water_system")
        await conn.run_sync(Base.metadata.create_all)


async def _drop_legacy_table_if_exists(conn: Any, table_name: str) -> None:
    if conn.dialect.name == "mysql":
        exists = await conn.scalar(
            text(
                """
                SELECT COUNT(*)
                  FROM information_schema.tables
                 WHERE table_schema = DATABASE()
                   AND table_name = :table_name
                """
            ),
            {"table_name": table_name},
        )
        if not exists:
            return
        await conn.execute(text(f"DROP TABLE `{table_name}`"))
        return

    await conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))


async def seed_navigation_channels(*, drop_legacy: bool = True, derive_missing_guides: bool = False) -> dict[str, int]:
    await _prepare_schema(drop_legacy)
    payload = load_navigation_channel_seed()
    records = payload["records"]
    excluded_source_audit = payload["excluded_source_audit"]

    async with AsyncSessionLocal() as session:
        await _clear_navigation_channel_dependents(session)
        await session.execute(delete(NavigationChannelSourceAudit))
        await session.execute(delete(NavigationChannelWaterAreaMatch))
        await session.execute(delete(NavigationChannelWaterBodyMatch))
        await session.execute(delete(NavigationChannelSegment))
        await session.execute(delete(NavigationChannelBoundary))
        await session.execute(delete(NavigationChannel))
        await session.flush()

        channel_by_code: dict[str, NavigationChannel] = {}
        segment_by_code: dict[str, NavigationChannelSegment] = {}

        for record in records:
            channel = NavigationChannel(**record["channel"])
            session.add(channel)
            await session.flush()
            channel_by_code[channel.channel_code] = channel

            boundary_payload = dict(record["boundary"])
            boundary_payload["imported_at"] = _parse_datetime(boundary_payload.get("imported_at"))
            boundary_payload = _normalize_boundary_numeric_fields(boundary_payload)
            session.add(NavigationChannelBoundary(channel_id=channel.id, **boundary_payload))
            derived_boundary_midline = (
                _derive_boundary_midline(boundary_payload.get("geometry_json") or {})
                if derive_missing_guides
                else None
            )
            derived_guide_by_segment_index: dict[int, LineString] = {}
            if derived_boundary_midline is not None:
                missing_guide_indexes = [
                    index
                    for index, segment_payload in enumerate(record["segments"])
                    if not segment_payload.get("guide_geometry_json")
                ]
                derived_parts = _split_line_evenly(derived_boundary_midline, len(missing_guide_indexes))
                derived_guide_by_segment_index = {
                    segment_index: part
                    for segment_index, part in zip(missing_guide_indexes, derived_parts, strict=False)
                }

            for segment_index, segment_payload in enumerate(record["segments"]):
                segment = NavigationChannelSegment(
                    channel_id=channel.id,
                    **_segment_payload_with_guide(
                        segment_payload,
                        boundary_payload,
                        derive_missing_guides=derive_missing_guides,
                        derived_boundary_midline=derived_guide_by_segment_index.get(segment_index),
                    ),
                )
                session.add(segment)
                segment_by_code[segment.segment_code] = segment

        await session.flush()

        for record in records:
            channel = channel_by_code[record["channel"]["channel_code"]]
            for audit_payload in record["source_audit"]:
                payload_for_db = dict(audit_payload)
                payload_for_db.setdefault("channel_code", channel.channel_code)
                segment_code = payload_for_db.get("segment_code")
                segment = segment_by_code.get(segment_code) if segment_code else None
                session.add(
                    NavigationChannelSourceAudit(
                        channel_id=channel.id,
                        segment_id=segment.id if segment else None,
                        **payload_for_db,
                    )
                )

        for audit_payload in excluded_source_audit:
            session.add(NavigationChannelSourceAudit(**audit_payload))

        await session.commit()

    return {
        "version": DATA_VERSION,
        "channels": len(records),
        "boundaries": sum(1 for item in records if item["boundary"]["geometry_status_code"] == "AVAILABLE"),
        "segments": sum(len(item["segments"]) for item in records),
        "source_audits": sum(len(item["source_audit"]) for item in records) + len(excluded_source_audit),
        "boundary_derived_guides": (
            sum(len(item["segments"]) for item in records)
            if derive_missing_guides
            else 0
        ),
    }


async def _clear_navigation_channel_dependents(session: Any) -> None:
    edge_ids = [
        int(row[0])
        for row in (
            await session.execute(
                select(NavigationGraphEdge.id).where(
                    or_(
                        NavigationGraphEdge.channel_id.is_not(None),
                        NavigationGraphEdge.centerline_id.is_not(None),
                    )
                )
            )
        ).all()
    ]
    node_ids = [
        int(row[0])
        for row in (
            await session.execute(select(NavigationGraphNode.id).where(NavigationGraphNode.channel_id.is_not(None)))
        ).all()
    ]
    task_ids = [
        int(row[0])
        for row in (
            await session.execute(select(NavigationAnnotationTask.id).where(NavigationAnnotationTask.channel_id.is_not(None)))
        ).all()
    ]
    if edge_ids:
        await session.execute(delete(NavigationGraphEdgeConstraint).where(NavigationGraphEdgeConstraint.edge_id.in_(edge_ids)))
    quality_filters = []
    if edge_ids:
        quality_filters.append(NavigationRouteQualityIssue.related_edge_id.in_(edge_ids))
    if node_ids:
        quality_filters.append(NavigationRouteQualityIssue.related_node_id.in_(node_ids))
    if task_ids:
        quality_filters.append(NavigationRouteQualityIssue.related_annotation_task_id.in_(task_ids))
    if quality_filters:
        await session.execute(delete(NavigationRouteQualityIssue).where(or_(*quality_filters)))
    if edge_ids:
        await session.execute(delete(NavigationGraphEdge).where(NavigationGraphEdge.id.in_(edge_ids)))
    if node_ids:
        await session.execute(delete(NavigationGraphNode).where(NavigationGraphNode.id.in_(node_ids)))
    if task_ids:
        await session.execute(delete(NavigationAnnotationTask).where(NavigationAnnotationTask.id.in_(task_ids)))

    point_set_ids = [int(row[0]) for row in (await session.execute(select(NavigationCenterlinePointSet.id))).all()]
    if point_set_ids:
        await session.execute(
            delete(NavigationCenterlineControlPoint).where(NavigationCenterlineControlPoint.point_set_id.in_(point_set_ids))
        )
        await session.execute(delete(NavigationCenterlinePointSet).where(NavigationCenterlinePointSet.id.in_(point_set_ids)))
    await session.execute(update(NavigationGeometryDraft).where(NavigationGeometryDraft.channel_id.is_not(None)).values(channel_id=None))
    await session.execute(update(NavigationCenterlineSegment).values(previous_segment_id=None, next_segment_id=None))
    await session.execute(delete(NavigationCenterlineSegment))
    await session.execute(update(NavigationChannelCenterline).values(parent_centerline_id=None))
    await session.execute(delete(NavigationChannelCenterline))


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Seed final navigation channel base data.")
    parser.add_argument(
        "--keep-legacy",
        action="store_true",
        help="Keep legacy water_system tables if they still exist.",
    )
    parser.add_argument(
        "--derive-boundary-guides",
        action="store_true",
        help="Derive review-only guide lines from boundary polygons when no verified guide line exists.",
    )
    args = parser.parse_args()
    result = await seed_navigation_channels(
        drop_legacy=not args.keep_legacy,
        derive_missing_guides=args.derive_boundary_guides,
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(_main())
