"""Extract seed gap segments from real waybill reference tracks.

This script does not publish seed data. It cuts REFERENCE_ONLY waybill tracks
against the current active graph and current channel boundaries, so only the
uncovered portions become candidates for endpoint access, graph connectivity,
or missing water-system seed repair.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models import NavigationRouteTrajectoryCache
from app.models.address import NavigationChannelBoundary
from app.models.navigation import NavigationGraphEdge, NavigationGraphVersion


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CANDIDATE_REPORT = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_seed_candidate_report_20260608.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_seed_gap_segments_20260608.json"
DEFAULT_GEOJSON_OUTPUT = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_seed_gap_segments_20260608.geojson"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract uncovered segments from waybill seed candidates.")
    parser.add_argument("--candidate-report", type=Path, default=DEFAULT_CANDIDATE_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--geojson-output", type=Path, default=DEFAULT_GEOJSON_OUTPUT)
    parser.add_argument("--graph-version-id", type=int, default=None)
    parser.add_argument("--graph-buffer-m", type=float, default=450.0)
    parser.add_argument("--boundary-buffer-m", type=float, default=80.0)
    parser.add_argument("--segment-buffer-m", type=float, default=350.0)
    parser.add_argument("--min-gap-length-km", type=float, default=0.5)
    parser.add_argument("--max-endpoint-access-km", type=float, default=35.0)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    source = json.loads(args.candidate_report.read_text(encoding="utf-8"))
    candidates = list(source.get("candidates") or [])
    async with AsyncSessionLocal() as session:
        graph_version = await _active_graph_version(session, args.graph_version_id)
        graph_corridor = await _graph_corridor(
            session,
            graph_version_id=int(graph_version.id) if graph_version else None,
            buffer_m=float(args.graph_buffer_m),
        )
        boundary_corridor = await _boundary_corridor(session, buffer_m=float(args.boundary_buffer_m))
        caches = await _load_caches(session, [item.get("trajectory_cache_id") for item in candidates])
    items: list[dict[str, Any]] = []
    features: list[dict[str, Any]] = []
    for candidate in candidates:
        cache = caches.get(int(candidate.get("trajectory_cache_id") or 0))
        item, item_features = _process_candidate(
            candidate,
            cache=cache,
            graph_corridor=graph_corridor,
            boundary_corridor=boundary_corridor,
            min_gap_length_km=float(args.min_gap_length_km),
            max_endpoint_access_km=float(args.max_endpoint_access_km),
            segment_buffer_m=float(args.segment_buffer_m),
        )
        items.append(item)
        features.extend(item_features)
    report = {
        "report_version": "WAYBILL_SEED_GAP_SEGMENTS_V1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_candidate_report": str(args.candidate_report),
        "args": {
            "graph_version_id": args.graph_version_id,
            "graph_buffer_m": float(args.graph_buffer_m),
            "boundary_buffer_m": float(args.boundary_buffer_m),
            "segment_buffer_m": float(args.segment_buffer_m),
            "min_gap_length_km": float(args.min_gap_length_km),
            "max_endpoint_access_km": float(args.max_endpoint_access_km),
        },
        "active_graph_version": _graph_payload(graph_version),
        "summary": _summary(items),
        "items": items,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.geojson_output:
        args.geojson_output.parent.mkdir(parents=True, exist_ok=True)
        args.geojson_output.write_text(
            json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"report_path={args.output}")
    if args.geojson_output:
        print(f"geojson_path={args.geojson_output}")


async def _active_graph_version(session, graph_version_id: int | None) -> NavigationGraphVersion | None:
    if graph_version_id is not None:
        return await session.get(NavigationGraphVersion, int(graph_version_id))
    return (
        await session.execute(
            select(NavigationGraphVersion)
            .where(
                NavigationGraphVersion.is_active.is_(True),
                NavigationGraphVersion.status_code == "READY",
                NavigationGraphVersion.scope_code.not_like("MVP%"),
                NavigationGraphVersion.edge_count > 0,
            )
            .order_by(
                NavigationGraphVersion.channel_count.desc(),
                NavigationGraphVersion.edge_count.desc(),
                NavigationGraphVersion.node_count.desc(),
                NavigationGraphVersion.id.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()


async def _graph_corridor(session, *, graph_version_id: int | None, buffer_m: float) -> BaseGeometry | None:
    if graph_version_id is None:
        return None
    rows = list(
        (
            await session.execute(
                select(NavigationGraphEdge.geometry_json).where(
                    NavigationGraphEdge.graph_version_id == graph_version_id,
                    NavigationGraphEdge.routing_enabled.is_(True),
                    NavigationGraphEdge.geometry_json.is_not(None),
                )
            )
        ).scalars()
    )
    geometries = [_line(value) for value in rows]
    geometries = [geometry for geometry in geometries if geometry is not None]
    if not geometries:
        return None
    return make_valid(unary_union([line.buffer(_degree_buffer(buffer_m), cap_style=2, join_style=2) for line in geometries]))


async def _boundary_corridor(session, *, buffer_m: float) -> BaseGeometry | None:
    rows = list(
        (
            await session.execute(
                select(NavigationChannelBoundary.geometry_json).where(
                    NavigationChannelBoundary.is_current.is_(True),
                    NavigationChannelBoundary.geometry_status_code == "AVAILABLE",
                    NavigationChannelBoundary.geometry_json.is_not(None),
                )
            )
        ).scalars()
    )
    geometries = [_geometry(value) for value in rows]
    geometries = [geometry for geometry in geometries if geometry is not None]
    if not geometries:
        return None
    unioned = make_valid(unary_union(geometries))
    return make_valid(unioned.buffer(_degree_buffer(buffer_m))) if buffer_m > 0 else unioned


async def _load_caches(session, cache_ids: Iterable[Any]) -> dict[int, NavigationRouteTrajectoryCache]:
    ids = sorted({int(item) for item in cache_ids if _int_or_none(item) is not None})
    if not ids:
        return {}
    rows = list(
        (
            await session.execute(
                select(NavigationRouteTrajectoryCache)
                .where(NavigationRouteTrajectoryCache.id.in_(ids))
                .order_by(NavigationRouteTrajectoryCache.id)
            )
        ).scalars()
    )
    return {int(row.id): row for row in rows}


def _process_candidate(
    candidate: dict[str, Any],
    *,
    cache: NavigationRouteTrajectoryCache | None,
    graph_corridor: BaseGeometry | None,
    boundary_corridor: BaseGeometry | None,
    min_gap_length_km: float,
    max_endpoint_access_km: float,
    segment_buffer_m: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    line = _line(cache.geometry_json if cache else None)
    if line is None:
        return {
            "target_code": candidate.get("target_code"),
            "status": "SKIPPED",
            "skip_reason": "REFERENCE_GEOMETRY_MISSING",
        }, []
    target_code = str(candidate.get("target_code") or "")
    cache_summary = cache.validation_summary_json if isinstance(cache.validation_summary_json, dict) else {}
    raw_request = cache.raw_request_json if isinstance(cache.raw_request_json, dict) else {}
    origin_code = str(((raw_request.get("origin") or {}).get("code")) or "")
    destination_code = str(((raw_request.get("destination") or {}).get("code")) or "")
    graph_gap_segments = _gap_segments(line, graph_corridor, min_gap_length_km=min_gap_length_km)
    boundary_gap_segments = _gap_segments(line, boundary_corridor, min_gap_length_km=min_gap_length_km)
    endpoint_access = _endpoint_access_segment(
        line,
        graph_corridor=graph_corridor,
        target_code=target_code,
        origin_code=origin_code,
        destination_code=destination_code,
        max_length_km=max_endpoint_access_km,
        min_length_km=min_gap_length_km,
    )
    segment_records = []
    features = []
    for role, segments in (
        ("GRAPH_GAP_SEGMENT", graph_gap_segments),
        ("BOUNDARY_GAP_SEGMENT", boundary_gap_segments),
        ("ENDPOINT_ACCESS_SEGMENT", [endpoint_access] if endpoint_access is not None else []),
    ):
        for index, segment in enumerate(segments, start=1):
            segment_record = _segment_record(role, index, segment, segment_buffer_m=segment_buffer_m)
            segment_records.append(segment_record)
            features.extend(_segment_features(candidate, segment_record, segment, segment_buffer_m=segment_buffer_m))
    priority = _priority(candidate, segment_records)
    item = {
        "target_code": target_code,
        "target_name": candidate.get("target_name"),
        "seed_use_code": candidate.get("seed_use_code"),
        "source_priority_code": candidate.get("priority_code"),
        "gap_priority_code": priority,
        "trajectory_cache_id": int(cache.id),
        "waybill_code": cache_summary.get("waybill_code"),
        "route_code": cache_summary.get("route_code"),
        "origin_code": origin_code,
        "destination_code": destination_code,
        "line_length_km": round(_line_length_km(line), 3),
        "water_system_actions": candidate.get("water_system_actions") or [],
        "segment_counts": dict(Counter(record["segment_role_code"] for record in segment_records)),
        "segment_total_length_km": round(sum(float(record["length_km"]) for record in segment_records), 3),
        "segments": segment_records,
        "next_action_codes": _next_actions(candidate, segment_records),
    }
    return item, features


def _gap_segments(line: LineString, coverage: BaseGeometry | None, *, min_gap_length_km: float) -> list[LineString]:
    if coverage is None or coverage.is_empty:
        return [line] if _line_length_km(line) >= min_gap_length_km else []
    try:
        diff = line.difference(coverage)
    except Exception:
        return []
    segments = _line_parts(diff)
    return [segment for segment in segments if _line_length_km(segment) >= min_gap_length_km]


def _endpoint_access_segment(
    line: LineString,
    *,
    graph_corridor: BaseGeometry | None,
    target_code: str,
    origin_code: str,
    destination_code: str,
    max_length_km: float,
    min_length_km: float,
) -> LineString | None:
    if target_code not in {origin_code, destination_code}:
        return None
    coords = list(line.coords)
    if target_code == destination_code:
        coords = list(reversed(coords))
    if len(coords) < 2:
        return None
    output = [coords[0]]
    length_km = 0.0
    entered_graph = False
    for start, end in zip(coords[:-1], coords[1:]):
        segment = LineString([start, end])
        length_km += _line_length_km(segment)
        output.append(end)
        if graph_corridor is not None and (Point(end).intersects(graph_corridor) or segment.intersects(graph_corridor)):
            entered_graph = True
            break
        if length_km >= max_length_km:
            break
    if len(output) < 2 or _line_length_km(LineString(output)) < min_length_km:
        return None
    if not entered_graph and length_km < min(max_length_km, _line_length_km(line)):
        return None
    if target_code == destination_code:
        output = list(reversed(output))
    return LineString(output)


def _segment_record(role: str, index: int, segment: LineString, *, segment_buffer_m: float) -> dict[str, Any]:
    buffer_geometry = _buffer(segment, segment_buffer_m)
    return {
        "segment_role_code": role,
        "segment_no": index,
        "length_km": round(_line_length_km(segment), 3),
        "point_count": len(segment.coords),
        "bbox": [round(float(value), 7) for value in segment.bounds],
        "buffer_m": segment_buffer_m,
        "buffer_bbox": [round(float(value), 7) for value in buffer_geometry.bounds] if buffer_geometry is not None else None,
        "geometry_json": mapping(segment),
        "buffer_geometry_json": mapping(buffer_geometry) if buffer_geometry is not None else None,
    }


def _segment_features(candidate: dict[str, Any], record: dict[str, Any], segment: LineString, *, segment_buffer_m: float) -> list[dict[str, Any]]:
    base = {
        "target_code": candidate.get("target_code"),
        "target_name": candidate.get("target_name"),
        "seed_use_code": candidate.get("seed_use_code"),
        "source_priority_code": candidate.get("priority_code"),
        "segment_role_code": record["segment_role_code"],
        "segment_no": record["segment_no"],
        "length_km": record["length_km"],
    }
    features = [
        {"type": "Feature", "properties": {**base, "feature_role": "gap_segment"}, "geometry": mapping(segment)}
    ]
    buffer_geometry = _buffer(segment, segment_buffer_m)
    if buffer_geometry is not None:
        features.append(
            {"type": "Feature", "properties": {**base, "feature_role": "gap_segment_buffer"}, "geometry": mapping(buffer_geometry)}
        )
    return features


def _priority(candidate: dict[str, Any], segments: list[dict[str, Any]]) -> str:
    roles = {record["segment_role_code"] for record in segments}
    missing_water = any(
        action.get("action_code") == "CREATE_MISSING_WATER_SYSTEM_SEED"
        for action in candidate.get("water_system_actions") or []
    )
    if missing_water and roles.intersection({"GRAPH_GAP_SEGMENT", "BOUNDARY_GAP_SEGMENT"}):
        return "P0_MISSING_WATER_SYSTEM_UNCOVERED_SEGMENT"
    if "ENDPOINT_ACCESS_SEGMENT" in roles:
        return "P0_ENDPOINT_ACCESS_SEGMENT"
    if "GRAPH_GAP_SEGMENT" in roles:
        return "P1_GRAPH_GAP_SEGMENT"
    if "BOUNDARY_GAP_SEGMENT" in roles:
        return "P1_BOUNDARY_GAP_SEGMENT"
    return "NO_SIGNIFICANT_GAP"


def _next_actions(candidate: dict[str, Any], segments: list[dict[str, Any]]) -> list[str]:
    roles = {record["segment_role_code"] for record in segments}
    actions = []
    if any(action.get("action_code") == "CREATE_MISSING_WATER_SYSTEM_SEED" for action in candidate.get("water_system_actions") or []):
        actions.append("CREATE_OR_EXTEND_MISSING_WATER_SYSTEM_FROM_GAP_SEGMENT")
    if "ENDPOINT_ACCESS_SEGMENT" in roles:
        actions.append("PROMOTE_ENDPOINT_ACCESS_CENTERLINE_AFTER_VALIDATION")
    if "GRAPH_GAP_SEGMENT" in roles:
        actions.append("PROMOTE_GRAPH_GAP_CENTERLINE_AFTER_VALIDATION")
    if "BOUNDARY_GAP_SEGMENT" in roles:
        actions.append("PROMOTE_BOUNDARY_BUFFER_AFTER_WATER_VALIDATION")
    if not actions:
        actions.append("NO_PROMOTION_UNTIL_NEW_EVIDENCE")
    actions.append("REBUILD_GRAPH_AND_RERUN_ROUTE_AUDIT")
    return actions


def _summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    priority_counts = Counter(item.get("gap_priority_code") for item in items)
    role_counts = Counter(
        role
        for item in items
        for role, count in (item.get("segment_counts") or {}).items()
        for _ in range(int(count))
    )
    next_counts = Counter(action for item in items for action in item.get("next_action_codes") or [])
    missing_targets = [
        item
        for item in items
        if item.get("gap_priority_code") == "P0_MISSING_WATER_SYSTEM_UNCOVERED_SEGMENT"
    ]
    return {
        "candidate_count": len(items),
        "with_segments_count": sum(1 for item in items if item.get("segments")),
        "priority_counts": dict(sorted(priority_counts.items())),
        "segment_role_counts": dict(sorted(role_counts.items())),
        "next_action_counts": dict(sorted(next_counts.items())),
        "missing_water_system_uncovered_target_count": len(missing_targets),
        "total_segment_length_km": round(sum(float(item.get("segment_total_length_km") or 0) for item in items), 3),
    }


def _graph_payload(row: NavigationGraphVersion | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": int(row.id),
        "version_code": row.version_code,
        "scope_code": row.scope_code,
        "node_count": row.node_count,
        "edge_count": row.edge_count,
        "channel_count": row.channel_count,
    }


def _line_parts(geometry: BaseGeometry) -> list[LineString]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry] if len(geometry.coords) >= 2 else []
    if isinstance(geometry, MultiLineString):
        return [part for part in geometry.geoms if len(part.coords) >= 2]
    if isinstance(geometry, GeometryCollection):
        output = []
        for part in geometry.geoms:
            output.extend(_line_parts(part))
        return output
    return []


def _line(value: Any) -> LineString | None:
    geometry = _geometry(value)
    if isinstance(geometry, LineString) and len(geometry.coords) >= 2:
        return geometry
    return None


def _geometry(value: Any) -> BaseGeometry | None:
    if not isinstance(value, dict):
        return None
    try:
        geometry = make_valid(shape(value))
    except Exception:
        return None
    return None if geometry.is_empty else geometry


def _buffer(line: LineString, buffer_m: float) -> BaseGeometry | None:
    try:
        return make_valid(line.buffer(_degree_buffer(buffer_m), cap_style=2, join_style=2))
    except Exception:
        return None


def _degree_buffer(meters: float) -> float:
    return float(meters) / 111_320.0


def _line_length_km(line: LineString) -> float:
    coords = list(line.coords)
    return sum(_haversine_km(start, end) for start, end in zip(coords[:-1], coords[1:]))


def _haversine_km(left: Iterable[float], right: Iterable[float]) -> float:
    lng1, lat1 = [float(item) for item in left[:2] if hasattr(left, "__getitem__")] if not isinstance(left, Point) else [left.x, left.y]
    lng2, lat2 = [float(item) for item in right[:2] if hasattr(right, "__getitem__")] if not isinstance(right, Point) else [right.x, right.y]
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    asyncio.run(main())
