"""Promote validated local HiFleet trajectories into navigation seed geometry.

This script is intentionally deterministic and local-only. HiFleet trajectories
are treated as reference evidence: they must be anchored to known endpoints,
fit the matched water-body boundary, and pass simple polyline quality gates
before becoming graph-ready SEED_CENTERLINE rows.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, Point, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import (
    NavigationChannelCenterline,
    NavigationChannelWaterBodyMatch,
    NavigationGraphVersion,
    NavigationHifleetRouteCache,
    NavigationWaterBody,
)
from app.models.address import NavigationChannel, NavigationChannelBoundary, TransportNode
from app.modules.navigation.production_pipeline.boundary_quality_audit import audit_boundary_integrity
from app.modules.navigation.services.graph_build_service import build_graph_from_centerlines


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "runtime/navigation-production/reports/hifleet_trajectory_seed_promotion_report.json"
GEOD_SCALE = Decimal("0.000000000000001")
MEASURE_SCALE = Decimal("0.000000000000000001")
AUTO_BOUNDARY_POLICY = "AUTO_WATER_BODY_UNION"
SOURCE_TYPE = "SEED_CENTERLINE"


@dataclass(slots=True)
class PromotionReport:
    generated_at: str
    channel_code: str
    channel_id: int | None = None
    dry_run: bool = False
    selected_cache_ids: list[int] = field(default_factory=list)
    promoted_boundary_id: int | None = None
    promoted_centerline_ids: list[int] = field(default_factory=list)
    graph_build_status: str | None = None
    graph_version_id: int | None = None
    graph_edge_count: int | None = None
    validations: list[dict[str, Any]] = field(default_factory=list)
    boundary_audit: dict[str, Any] | None = None
    issue_counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Promote local HiFleet trajectories into validated navigation seed centerlines.")
    parser.add_argument("--channel-code", required=True)
    parser.add_argument("--hifleet-cache-id", action="append", type=int, default=None)
    parser.add_argument("--coverage-threshold", type=float, default=0.65)
    parser.add_argument("--max-step-km", type=float, default=30.0)
    parser.add_argument("--densify-max-step-km", type=float, default=8.0)
    parser.add_argument("--min-point-count", type=int, default=8)
    parser.add_argument("--max-endpoint-anchor-m", type=float, default=100.0)
    parser.add_argument("--slice-start-index", type=int, default=None)
    parser.add_argument("--slice-end-index", type=int, default=None)
    parser.add_argument("--allow-unanchored-slice", action="store_true")
    parser.add_argument("--corridor-buffer-degree", type=float, default=0.002)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--build-graph", action="store_true")
    parser.add_argument("--activate-graph", action="store_true")
    parser.add_argument("--graph-scope-code", default="REVIER_PRODUCTION_HIFLEET_SEED")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _q(value: Any, scale: Decimal = GEOD_SCALE) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(scale, rounding=ROUND_HALF_UP)


def _safe_geometry(value: Any) -> BaseGeometry | None:
    if not isinstance(value, dict):
        return None
    try:
        geometry = make_valid(shape(value))
    except Exception:
        return None
    return None if geometry.is_empty else geometry


def _safe_line(value: Any) -> LineString | None:
    geometry = _safe_geometry(value)
    if isinstance(geometry, LineString) and len(geometry.coords) >= 2:
        return _clean_line(geometry)
    return None


def _clean_line(line: LineString) -> LineString:
    coords: list[tuple[float, float]] = []
    previous: tuple[float, float] | None = None
    for lng, lat, *_rest in line.coords:
        coord = (round(float(lng), 8), round(float(lat), 8))
        if coord == previous:
            continue
        coords.append(coord)
        previous = coord
    return LineString(coords) if len(coords) >= 2 else line


def _point_distance_m(a: Point, b: Point) -> float:
    return (((a.x - b.x) * 111_320) ** 2 + ((a.y - b.y) * 110_540) ** 2) ** 0.5


def _line_length_km(line: LineString) -> float:
    coords = list(line.coords)
    total = 0.0
    for (lng1, lat1), (lng2, lat2) in zip(coords, coords[1:]):
        total += (((lng1 - lng2) * 111_320) ** 2 + ((lat1 - lat2) * 110_540) ** 2) ** 0.5
    return total / 1000.0


def _max_step_km(line: LineString) -> float:
    coords = list(line.coords)
    if len(coords) < 2:
        return 0.0
    return max(
        (((lng1 - lng2) * 111_320) ** 2 + ((lat1 - lat2) * 110_540) ** 2) ** 0.5 / 1000.0
        for (lng1, lat1), (lng2, lat2) in zip(coords, coords[1:])
    )


def _densify_line(line: LineString, max_step_km: float) -> LineString:
    if max_step_km <= 0:
        return line
    coords = list(line.coords)
    if len(coords) < 2:
        return line
    output: list[tuple[float, float]] = []
    for start, end in zip(coords, coords[1:]):
        start_coord = (float(start[0]), float(start[1]))
        end_coord = (float(end[0]), float(end[1]))
        if not output:
            output.append(start_coord)
        segment_km = _point_distance_m(Point(start_coord), Point(end_coord)) / 1000.0
        split_count = max(1, int(segment_km // max_step_km) + (1 if segment_km % max_step_km > 1e-9 else 0))
        for index in range(1, split_count + 1):
            ratio = index / split_count
            output.append(
                (
                    start_coord[0] + (end_coord[0] - start_coord[0]) * ratio,
                    start_coord[1] + (end_coord[1] - start_coord[1]) * ratio,
                )
            )
    return _clean_line(LineString(output))


def _coverage_ratio(line: LineString, boundary: BaseGeometry, *, tolerance_degree: float = 0.0002) -> float:
    try:
        covered = line.intersection(boundary.buffer(tolerance_degree)).length
    except Exception:
        return 0.0
    return max(0.0, min(1.0, covered / max(line.length, 1e-12)))


def _endpoint_anchor(row: NavigationHifleetRouteCache, line: LineString) -> tuple[LineString, dict[str, Any]]:
    coords = list(line.coords)
    origin = Point(float(row.origin_lng), float(row.origin_lat))
    destination = Point(float(row.destination_lng), float(row.destination_lat))
    forward = max(_point_distance_m(Point(coords[0]), origin), _point_distance_m(Point(coords[-1]), destination))
    reverse = max(_point_distance_m(Point(coords[0]), destination), _point_distance_m(Point(coords[-1]), origin))
    if reverse < forward:
        line = LineString(list(reversed(coords)))
        distance = reverse
        direction = "REVERSED_TO_MATCH_ENDPOINTS"
    else:
        distance = forward
        direction = "FORWARD"
    return line, {"endpoint_anchor_max_m": round(distance, 2), "endpoint_direction": direction}


def _geometry_counts(geometry: BaseGeometry) -> tuple[int, int]:
    polygons = []
    if geometry.geom_type == "Polygon":
        polygons = [geometry]
    elif geometry.geom_type == "MultiPolygon":
        polygons = list(geometry.geoms)
    ring_count = 0
    point_count = 0
    for polygon in polygons:
        rings = [polygon.exterior, *list(polygon.interiors)]
        ring_count += len(rings)
        point_count += sum(len(ring.coords) for ring in rings)
    return ring_count, point_count


async def _channel(session: AsyncSession, channel_code: str) -> NavigationChannel:
    channel = await session.scalar(select(NavigationChannel).where(NavigationChannel.channel_code == channel_code))
    if channel is None:
        raise SystemExit(f"Navigation channel not found: {channel_code}")
    return channel


async def _matched_water_bodies(session: AsyncSession, channel_id: int) -> list[NavigationWaterBody]:
    return list(
        (
            await session.execute(
                select(NavigationWaterBody)
                .join(NavigationChannelWaterBodyMatch, NavigationChannelWaterBodyMatch.water_body_id == NavigationWaterBody.id)
                .where(
                    NavigationChannelWaterBodyMatch.channel_id == channel_id,
                    NavigationChannelWaterBodyMatch.is_current.is_(True),
                    NavigationWaterBody.is_enabled.is_(True),
                    NavigationWaterBody.geometry_wgs84_json.is_not(None),
                )
                .order_by(NavigationChannelWaterBodyMatch.score.desc(), NavigationWaterBody.source_layer_order, NavigationWaterBody.id)
            )
        ).scalars()
    )


async def _candidate_rows(
    session: AsyncSession,
    *,
    cache_ids: list[int] | None,
    line_boundary: BaseGeometry,
    coverage_threshold: float,
    limit: int,
) -> list[NavigationHifleetRouteCache]:
    stmt = select(NavigationHifleetRouteCache).where(
        NavigationHifleetRouteCache.status_code == "READY",
        NavigationHifleetRouteCache.geometry_json.is_not(None),
    )
    if cache_ids:
        stmt = stmt.where(NavigationHifleetRouteCache.id.in_(cache_ids))
    rows = list((await session.execute(stmt)).scalars())
    if cache_ids:
        return rows
    scored: list[tuple[float, float, NavigationHifleetRouteCache]] = []
    for row in rows:
        line = _safe_line(row.geometry_json)
        if line is None:
            continue
        coverage = _coverage_ratio(line, line_boundary)
        if coverage >= coverage_threshold:
            scored.append((coverage, _line_length_km(line), row))
    scored.sort(key=lambda item: (-item[0], -item[1], int(item[2].id)))
    return [item[2] for item in scored[: max(1, limit)]]


async def _transport_node(session: AsyncSession, ref_type: str | None, ref_id: int | None) -> TransportNode | None:
    if str(ref_type or "").upper() != "TRANSPORT_NODE" or ref_id is None:
        return None
    return await session.get(TransportNode, int(ref_id))


async def _validate_row(
    session: AsyncSession,
    row: NavigationHifleetRouteCache,
    *,
    water_boundary: BaseGeometry,
    coverage_threshold: float,
    max_step_km: float,
    densify_max_step_km: float,
    min_point_count: int,
    max_endpoint_anchor_m: float,
    slice_start_index: int | None = None,
    slice_end_index: int | None = None,
    allow_unanchored_slice: bool = False,
) -> tuple[LineString | None, dict[str, Any]]:
    line = _safe_line(row.geometry_json)
    if line is None:
        return None, {"hifleet_cache_id": int(row.id), "status": "BLOCKED", "issue_codes": ["HIFLEET_GEOMETRY_INVALID"]}
    original_coord_count = len(line.coords)
    slice_applied = slice_start_index is not None or slice_end_index is not None
    if slice_applied:
        coords = list(line.coords)
        start = 0 if slice_start_index is None else max(0, int(slice_start_index))
        end = len(coords) - 1 if slice_end_index is None else min(len(coords) - 1, int(slice_end_index))
        if end < start or end - start + 1 < 2:
            return None, {
                "hifleet_cache_id": int(row.id),
                "status": "BLOCKED",
                "issue_codes": ["HIFLEET_SLICE_INVALID"],
                "slice_start_index": slice_start_index,
                "slice_end_index": slice_end_index,
                "original_coord_count": original_coord_count,
            }
        line = _clean_line(LineString(coords[start : end + 1]))
        anchor = {
            "endpoint_anchor_max_m": None,
            "endpoint_direction": "UNANCHORED_SLICE" if allow_unanchored_slice else "SLICE_REQUIRES_ANCHOR_VALIDATION",
            "slice_start_index": start,
            "slice_end_index": end,
            "original_coord_count": original_coord_count,
        }
    else:
        line, anchor = _endpoint_anchor(row, line)
    original_point_count = len(line.coords)
    original_max_step = _max_step_km(line)
    line = _densify_line(line, densify_max_step_km)
    point_count = len(line.coords)
    length_km = _line_length_km(line)
    max_step = _max_step_km(line)
    coverage = _coverage_ratio(line, water_boundary)
    issue_codes: list[str] = []
    if point_count < min_point_count:
        issue_codes.append("HIFLEET_POINT_COUNT_TOO_LOW")
    if max_step > max_step_km:
        issue_codes.append("HIFLEET_MAX_STEP_TOO_LONG")
    if coverage < coverage_threshold:
        issue_codes.append("HIFLEET_WATER_BODY_COVERAGE_LOW")
    if slice_applied and not allow_unanchored_slice:
        issue_codes.append("HIFLEET_SLICE_UNANCHORED_NOT_ALLOWED")
    if anchor["endpoint_anchor_max_m"] is not None and float(anchor["endpoint_anchor_max_m"]) > max_endpoint_anchor_m:
        issue_codes.append("HIFLEET_ENDPOINT_NOT_ANCHORED")
    origin_node = await _transport_node(session, row.origin_ref_type_code, row.origin_ref_id)
    destination_node = await _transport_node(session, row.destination_ref_type_code, row.destination_ref_id)
    return (
        None if issue_codes else line,
        {
            "hifleet_cache_id": int(row.id),
            "status": "BLOCKED" if issue_codes else "READY",
            "issue_codes": issue_codes,
            "route_key": row.route_key,
            "origin": {"type": row.origin_ref_type_code, "id": row.origin_ref_id, "name": row.origin_name},
            "destination": {"type": row.destination_ref_type_code, "id": row.destination_ref_id, "name": row.destination_name},
            "origin_node_exists": origin_node is not None if row.origin_ref_type_code else None,
            "destination_node_exists": destination_node is not None if row.destination_ref_type_code else None,
            "original_point_count": original_point_count,
            "point_count": point_count,
            "line_length_km": round(length_km, 3),
            "provider_distance_km": float(row.distance_km or 0),
            "original_max_step_km": round(original_max_step, 3),
            "max_step_km": round(max_step, 3),
            "densify_max_step_km": round(densify_max_step_km, 3),
            "water_body_coverage_ratio": round(coverage, 6),
            **anchor,
        },
    )


async def _promote_boundary(
    *,
    session: AsyncSession,
    channel: NavigationChannel,
    water_bodies: list[NavigationWaterBody],
    water_boundary: BaseGeometry,
    lines: list[LineString],
    validations: list[dict[str, Any]],
    buffer_degree: float,
    dry_run: bool,
) -> tuple[NavigationChannelBoundary | None, dict[str, Any]]:
    current_rows = list(
        (
            await session.execute(
                select(NavigationChannelBoundary).where(
                    NavigationChannelBoundary.channel_id == int(channel.id),
                    NavigationChannelBoundary.is_current.is_(True),
                )
            )
        ).scalars()
    )
    existing_boundaries = [
        geometry
        for row in current_rows
        if (geometry := _safe_geometry(row.geometry_json)) is not None
    ]
    corridor = unary_union([line.buffer(buffer_degree, cap_style=1, join_style=2) for line in lines])
    boundary_geometry = make_valid(unary_union([water_boundary, corridor, *existing_boundaries]))
    selected = [
        {
            "water_body_id": int(body.id),
            "water_name": body.production_name or body.display_name or body.water_body_name or body.normalized_water_name,
            "water_level": body.water_level_min,
            "water_level_min": body.water_level_min,
            "water_level_max": body.water_level_max,
            "water_type_code": body.water_type_code,
            "source_layer_name": body.source_layer_name,
            "feature_count": body.feature_count,
        }
        for body in water_bodies
    ]
    source_trace = {
        "source": "promote_hifleet_trajectory_seed",
        "boundary_policy": AUTO_BOUNDARY_POLICY,
        "previous_boundary_ids": [int(row.id) for row in current_rows],
        "basemap_verification": {
            "status_code": "AUTO_VERIFIED_BY_LOCAL_WATER_BODY_AND_HIFLEET_TRAJECTORY",
            "source_code": "LOCAL_REVIER_WATER_BODY_PLUS_LOCAL_HIFLEET_CACHE",
        },
        "auto_fragment_bridge_verified": True,
        "selected_water_areas": selected,
        "selected_water_bodies": selected,
        "hifleet_corridor": {
            "cache_ids": [item["hifleet_cache_id"] for item in validations if item.get("status") == "READY"],
            "buffer_degree": buffer_degree,
            "validation": validations,
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }
    boundary_stub = {
        "geometry_status_code": "AVAILABLE",
        "geometry_json": mapping(boundary_geometry),
        "coverage_policy_code": AUTO_BOUNDARY_POLICY,
        "source_trace_json": source_trace,
    }
    audit = audit_boundary_integrity(
        channel={
            "technical_grade_current_code": channel.technical_grade_current_code,
            "technical_grade_planned_code": channel.technical_grade_planned_code,
        },
        boundary=boundary_stub,
        centerline_geometries=[mapping(line) for line in lines],
        require_centerline=True,
    )
    if audit.get("blocking_issue_codes"):
        return None, audit
    if dry_run:
        return None, audit
    for row in current_rows:
        row.is_current = False
    centroid = boundary_geometry.centroid
    min_lng, min_lat, max_lng, max_lat = boundary_geometry.bounds
    ring_count, point_count = _geometry_counts(boundary_geometry)
    boundary = NavigationChannelBoundary(
        channel_id=int(channel.id),
        geometry_json=mapping(boundary_geometry),
        center_longitude=_q(centroid.x),
        center_latitude=_q(centroid.y),
        display_center_longitude=_q(centroid.x),
        display_center_latitude=_q(centroid.y),
        bbox_min_lng=_q(min_lng),
        bbox_min_lat=_q(min_lat),
        bbox_max_lng=_q(max_lng),
        bbox_max_lat=_q(max_lat),
        source_shape_length_degree=_q(boundary_geometry.length, MEASURE_SCALE),
        source_shape_area_degree=_q(boundary_geometry.area, MEASURE_SCALE),
        ring_count=ring_count,
        point_count=point_count,
        geometry_status_code="AVAILABLE",
        boundary_quality_code="AUTO_PUBLISHED",
        connectivity_status_code="CONNECTED_WITH_BRIDGES" if boundary_geometry.geom_type == "MultiPolygon" else "CONNECTED",
        repair_status_code="AUTO_REPAIRED",
        coverage_policy_code=AUTO_BOUNDARY_POLICY,
        geometry_coordinate_system_code="WGS84",
        boundary_coordinate_system_code="WGS84",
        source_trace_json={**source_trace, "boundary_integrity_audit": audit},
        is_current=True,
        imported_at=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(boundary)
    await session.flush()
    return boundary, audit


async def _promote_centerline(
    *,
    session: AsyncSession,
    channel: NavigationChannel,
    row: NavigationHifleetRouteCache,
    line: LineString,
    boundary_id: int | None,
    validation: dict[str, Any],
    dry_run: bool,
) -> int | None:
    if dry_run:
        return None
    centerline_code = f"AUTO-HIFLEET-SEED-{channel.channel_code}-{row.id}"[:96]
    existing = await session.scalar(
        select(NavigationChannelCenterline).where(NavigationChannelCenterline.centerline_code == centerline_code)
    )
    min_lng, min_lat, max_lng, max_lat = line.bounds
    payload = {
        "channel_id": int(channel.id),
        "segment_id": None,
        "centerline_code": centerline_code,
        "centerline_name": f"{channel.channel_name}本地轨迹清洗中心线 {row.id}",
        "geometry_json": mapping(line),
        "source_type_code": SOURCE_TYPE,
        "direction_code": "BIDIRECTIONAL",
        "is_main_line": True,
        "confidence_score": 82,
        "quality_code": "READY_WITH_WARNING",
        "review_status_code": "PUBLISHED",
        "version_no": 1,
        "parent_centerline_id": None,
        "is_current": True,
        "source_trace_json": {
            "source": "promote_hifleet_trajectory_seed",
            "source_hifleet_cache_id": int(row.id),
            "source_hifleet_route_key": row.route_key,
            "source_hifleet_provider_trace_id": row.provider_trace_id,
            "source_boundary_id": boundary_id,
            "validation": validation,
            "conversion_policy": "LOCAL_HIFLEET_TRAJECTORY_AS_SEED_EVIDENCE_WITH_WATER_BODY_BOUNDARY_AUDIT",
            "published_at": datetime.now(UTC).isoformat(),
        },
        "approved_by": None,
        "approved_at": datetime.now(UTC).replace(tzinfo=None),
        "bbox_min_lng": _q(min_lng),
        "bbox_min_lat": _q(min_lat),
        "bbox_max_lng": _q(max_lng),
        "bbox_max_lat": _q(max_lat),
    }
    if existing is None:
        centerline = NavigationChannelCenterline(**payload)
        session.add(centerline)
        await session.flush()
        return int(centerline.id)
    for key, value in payload.items():
        setattr(existing, key, value)
    await session.flush()
    return int(existing.id)


async def _build_graph(channel_code: str, *, activate: bool, scope_code: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        summary = await build_graph_from_centerlines(
            session=session,
            version_code=f"AUTO-HIFLEET-SEED-GRAPH-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            version_name="本地 HiFleet 清洗 Seed Graph",
            scope_code=scope_code,
            channel_codes=[channel_code],
            activate=activate,
        )
        return summary.as_dict()


async def main() -> None:
    args = parse_args()
    report = PromotionReport(
        generated_at=datetime.now(UTC).isoformat(),
        channel_code=args.channel_code,
        dry_run=bool(args.dry_run),
    )
    issue_counter: dict[str, int] = {}

    async with AsyncSessionLocal() as session:
        channel = await _channel(session, args.channel_code)
        report.channel_id = int(channel.id)
        water_bodies = await _matched_water_bodies(session, int(channel.id))
        water_geometries = [_safe_geometry(body.geometry_wgs84_json) for body in water_bodies]
        water_geometries = [item for item in water_geometries if item is not None]
        if not water_geometries:
            raise SystemExit(f"Channel {args.channel_code} has no matched water-body geometry")
        water_boundary = make_valid(unary_union(water_geometries))
        rows = await _candidate_rows(
            session,
            cache_ids=args.hifleet_cache_id,
            line_boundary=water_boundary,
            coverage_threshold=float(args.coverage_threshold),
            limit=int(args.limit or 1),
        )
        lines: list[tuple[NavigationHifleetRouteCache, LineString, dict[str, Any]]] = []
        for row in rows:
            line, validation = await _validate_row(
                session,
                row,
                water_boundary=water_boundary,
                coverage_threshold=float(args.coverage_threshold),
                max_step_km=float(args.max_step_km),
                densify_max_step_km=float(args.densify_max_step_km),
                min_point_count=int(args.min_point_count),
                max_endpoint_anchor_m=float(args.max_endpoint_anchor_m),
                slice_start_index=args.slice_start_index,
                slice_end_index=args.slice_end_index,
                allow_unanchored_slice=bool(args.allow_unanchored_slice),
            )
            report.validations.append(validation)
            for code in validation.get("issue_codes") or []:
                issue_counter[str(code)] = issue_counter.get(str(code), 0) + 1
            if line is not None:
                lines.append((row, line, validation))
        if not lines:
            report.issue_counts = dict(sorted(issue_counter.items()))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
            raise SystemExit("No HiFleet trajectory passed seed promotion validation")

        report.selected_cache_ids = [int(row.id) for row, _line, _validation in lines]
        boundary, audit = await _promote_boundary(
            session=session,
            channel=channel,
            water_bodies=water_bodies,
            water_boundary=water_boundary,
            lines=[line for _row, line, _validation in lines],
            validations=report.validations,
            buffer_degree=float(args.corridor_buffer_degree),
            dry_run=bool(args.dry_run),
        )
        report.boundary_audit = audit
        for code in audit.get("issue_codes") or []:
            issue_counter[str(code)] = issue_counter.get(str(code), 0) + 1
        if audit.get("blocking_issue_codes"):
            report.issue_counts = dict(sorted(issue_counter.items()))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
            raise SystemExit(f"Boundary audit blocked promotion: {audit.get('blocking_issue_codes')}")

        for row, line, validation in lines:
            centerline_id = await _promote_centerline(
                session=session,
                channel=channel,
                row=row,
                line=line,
                boundary_id=int(boundary.id) if boundary is not None else None,
                validation=validation,
                dry_run=bool(args.dry_run),
            )
            if centerline_id is not None:
                report.promoted_centerline_ids.append(centerline_id)
        if boundary is not None:
            report.promoted_boundary_id = int(boundary.id)
        if not args.dry_run:
            await session.commit()

    if args.build_graph and not args.dry_run:
        graph_report = await _build_graph(args.channel_code, activate=bool(args.activate_graph), scope_code=str(args.graph_scope_code))
        report.graph_build_status = str(graph_report.get("status_code"))
        report.graph_version_id = graph_report.get("graph_version_id")
        report.graph_edge_count = graph_report.get("edge_count")
        for issue in graph_report.get("issues") or []:
            if isinstance(issue, dict) and issue.get("issue_code"):
                code = str(issue["issue_code"])
                issue_counter[code] = issue_counter.get(code, 0) + 1

    report.issue_counts = dict(sorted(issue_counter.items()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "channel_code": report.channel_code,
                "selected_cache_ids": report.selected_cache_ids,
                "promoted_boundary_id": report.promoted_boundary_id,
                "promoted_centerline_ids": report.promoted_centerline_ids,
                "graph_build_status": report.graph_build_status,
                "graph_version_id": report.graph_version_id,
                "graph_edge_count": report.graph_edge_count,
                "issue_counts": report.issue_counts,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"report_path={args.output}")


if __name__ == "__main__":
    asyncio.run(main())
