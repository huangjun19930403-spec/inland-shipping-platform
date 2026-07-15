"""Promote the evidence-backed Wushen local chain into current seed geometry."""

from __future__ import annotations

import argparse
import asyncio
import heapq
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPoint, Point, mapping, shape
from shapely.strtree import STRtree
from shapely.ops import substring, unary_union, voronoi_diagram
from shapely.validation import make_valid
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import NavigationChannelCenterline, NavigationChannelWaterBodyMatch, NavigationWaterBody
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.modules.navigation.production_pipeline.boundary_quality_audit import audit_boundary_integrity
from app.modules.navigation.services.centerline_segments import NavigationCenterlineSegmentService


DEFAULT_OUTPUT = Path("runtime/navigation-production/reports/wushen_mixed_seed_promotion_20260606.json")
DEFAULT_OSM_JSON = Path("/private/tmp/osm_wushen_context.json")
CHANNEL_CODE = "NC-WUSHEN-LINE"
LOCAL_WATER_BODY_IDS = [287838, 287836, 287484, 287837]
MATCH_WATER_BODY_IDS = [287838, 287836, 287484, 287837]
ORDERED_OSM_WAY_IDS = [184905711, 1040665115, 58728113, 481668466, 1074378432]
CENTERLINE_CODE = "MIXED-WUSHEN-QINGSHAN-YUNLIANG-SHUIYANG-20260606"
GEOD_SCALE = Decimal("0.000000000000001")
MEASURE_SCALE = Decimal("0.000000000000000001")


@dataclass(slots=True)
class PromotionReport:
    generated_at: str
    dry_run: bool
    channel_code: str
    channel_id: int | None = None
    centerline_code: str = CENTERLINE_CODE
    promoted_boundary_id: int | None = None
    promoted_centerline_id: int | None = None
    validation: dict[str, Any] = field(default_factory=dict)
    boundary_audit: dict[str, Any] | None = None
    water_body_match_results: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Promote Wushen local mixed OSM/Revier seed centerline.")
    parser.add_argument("--osm-json", type=Path, default=DEFAULT_OSM_JSON)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--corridor-buffer-degree", type=float, default=0.0012)
    parser.add_argument("--max-step-km", type=float, default=1.0)
    parser.add_argument("--min-boundary-coverage", type=float, default=0.98)
    return parser.parse_args()


def _q(value: Any, scale: Decimal = GEOD_SCALE) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(scale, rounding=ROUND_HALF_UP)


def _clean_coords(coords: list[tuple[float, float]]) -> list[tuple[float, float]]:
    output: list[tuple[float, float]] = []
    previous: tuple[float, float] | None = None
    for lng, lat in coords:
        coord = (round(float(lng), 8), round(float(lat), 8))
        if coord == previous:
            continue
        output.append(coord)
        previous = coord
    return output


def _distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    return (((a[0] - b[0]) * 111_320) ** 2 + ((a[1] - b[1]) * 110_540) ** 2) ** 0.5


def _line_length_km(line: LineString) -> float:
    coords = [(float(lng), float(lat)) for lng, lat, *_rest in line.coords]
    return sum(_distance_m(a, b) for a, b in zip(coords[:-1], coords[1:])) / 1000.0


def _max_step_km(coords: list[tuple[float, float]]) -> float:
    if len(coords) < 2:
        return 0.0
    return max(_distance_m(a, b) for a, b in zip(coords[:-1], coords[1:])) / 1000.0


def _densify_coords(coords: list[tuple[float, float]], *, max_step_m: float) -> list[tuple[float, float]]:
    if len(coords) < 2:
        return coords
    output: list[tuple[float, float]] = []
    for start, end in zip(coords[:-1], coords[1:]):
        if not output:
            output.append(start)
        distance_m = _distance_m(start, end)
        split_count = max(1, int(distance_m // max_step_m) + (1 if distance_m % max_step_m else 0))
        for index in range(1, split_count + 1):
            ratio = index / split_count
            output.append(
                (
                    start[0] + (end[0] - start[0]) * ratio,
                    start[1] + (end[1] - start[1]) * ratio,
                )
            )
    return _clean_coords(output)


def _self_intersection_samples(line: LineString, *, limit: int = 8) -> list[dict[str, Any]]:
    coords = list(line.coords)
    if len(coords) < 4:
        return []
    segments = [LineString([coords[index], coords[index + 1]]) for index in range(len(coords) - 1)]
    tree = STRtree(segments)
    samples: list[dict[str, Any]] = []
    seen: set[tuple[int, int, float, float]] = set()
    for left_index, segment in enumerate(segments):
        for raw_right_index in tree.query(segment):
            right_index = int(raw_right_index)
            if right_index <= left_index + 1:
                continue
            if left_index == 0 and right_index == len(segments) - 1:
                continue
            if not segment.intersects(segments[right_index]):
                continue
            intersection = segment.intersection(segments[right_index])
            points: list[Point] = []
            if isinstance(intersection, Point):
                points = [intersection]
            elif isinstance(intersection, MultiPoint):
                points = list(intersection.geoms)
            elif isinstance(intersection, GeometryCollection):
                points = [item for item in intersection.geoms if isinstance(item, Point)]
            elif isinstance(intersection, (LineString, MultiLineString)):
                continue
            for point in points:
                key = (left_index, right_index, round(point.x, 8), round(point.y, 8))
                if key in seen:
                    continue
                seen.add(key)
                samples.append(
                    {
                        "segment_indexes": [left_index, right_index],
                        "point": [round(point.x, 8), round(point.y, 8)],
                        "left_segment": [
                            [round(float(coord[0]), 8), round(float(coord[1]), 8)]
                            for coord in segments[left_index].coords
                        ],
                        "right_segment": [
                            [round(float(coord[0]), 8), round(float(coord[1]), 8)]
                            for coord in segments[right_index].coords
                        ],
                    }
                )
                if len(samples) >= limit:
                    return samples
    return samples


def _coverage_ratio(line: LineString, geometry: Any, tolerance_degree: float = 0.0002) -> float:
    return float(line.intersection(geometry.buffer(tolerance_degree)).length / max(line.length, 1e-12))


def _load_osm_way_coords(path: Path, way_ids: list[int]) -> dict[int, list[tuple[float, float]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    requested = set(way_ids)
    output: dict[int, list[tuple[float, float]]] = {}
    for element in payload.get("elements") or []:
        if element.get("type") != "way" or int(element.get("id", 0)) not in requested:
            continue
        geometry = element.get("geometry")
        if not isinstance(geometry, list):
            continue
        coords = _clean_coords([(float(item["lon"]), float(item["lat"])) for item in geometry])
        if len(coords) >= 2:
            output[int(element["id"])] = coords
    missing = sorted(requested - set(output))
    if missing:
        raise SystemExit(f"OSM way ids not found: {missing}")
    return output


def _append_coords(base: list[tuple[float, float]], next_coords: list[tuple[float, float]], trace: list[dict[str, Any]], label: str) -> None:
    if not next_coords:
        return
    if not base:
        base.extend(next_coords)
        return
    gap_m = _distance_m(base[-1], next_coords[0])
    trace.append(
        {
            "label": label,
            "from": [round(base[-1][0], 6), round(base[-1][1], 6)],
            "to": [round(next_coords[0][0], 6), round(next_coords[0][1], 6)],
            "gap_m": round(gap_m, 2),
        }
    )
    if gap_m <= 1:
        base.extend(next_coords[1:])
    else:
        base.extend(next_coords)


def _osm_tail_from_anchor(way_coords: list[tuple[float, float]], anchor: tuple[float, float]) -> list[tuple[float, float]]:
    line = LineString(way_coords)
    if line.is_empty or len(line.coords) < 2:
        return way_coords
    start_measure = line.project(Point(anchor))
    tail = substring(line, start_measure, line.length)
    if isinstance(tail, Point):
        return _clean_coords([(tail.x, tail.y)])
    if not isinstance(tail, LineString) or tail.is_empty:
        return way_coords
    return _clean_coords([(float(lng), float(lat)) for lng, lat, *_rest in tail.coords])


def _restore_path(parents: dict[tuple[float, float], tuple[float, float] | None], end: tuple[float, float]) -> list[tuple[float, float]]:
    path = [end]
    current = end
    while parents[current] is not None:
        current = parents[current]
        path.append(current)
    path.reverse()
    return path


def _qingshan_anchor_path(
    *,
    service: NavigationCenterlineSegmentService,
    polygon: Any,
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[list[tuple[float, float]], dict[str, Any]]:
    points = service._sample_polygon_boundary_points(polygon, max_points=1400)
    span = max(polygon.bounds[2] - polygon.bounds[0], polygon.bounds[3] - polygon.bounds[1])
    diagram = voronoi_diagram(MultiPoint(points), envelope=polygon.envelope.buffer(span * 0.05), edges=True)
    candidates = service._internal_voronoi_lines(diagram, polygon)
    graph: dict[tuple[float, float], list[tuple[tuple[float, float], float]]] = defaultdict(list)

    def key(point: tuple[float, float]) -> tuple[float, float]:
        return (round(float(point[0]), 8), round(float(point[1]), 8))

    def add_edge(a: tuple[float, float], b: tuple[float, float]) -> bool:
        a = key(a)
        b = key(b)
        if a == b:
            return False
        edge = LineString([a, b])
        if not polygon.buffer(0.0002).covers(edge):
            return False
        weight = service._distance_m(a, b)
        graph[a].append((b, weight))
        graph[b].append((a, weight))
        return True

    for line in candidates:
        coords = [key((float(lng), float(lat))) for lng, lat, *_rest in line.coords]
        for a, b in zip(coords[:-1], coords[1:]):
            add_edge(a, b)

    bridge_count = 0
    nodes = list(graph)
    for index, a in enumerate(nodes):
        for b in nodes[index + 1 :]:
            if service._distance_m(a, b) <= 500 and add_edge(a, b):
                bridge_count += 1

    start_key = key(start)
    end_key = key(end)
    for anchor in [start_key, end_key]:
        nearest = sorted((service._distance_m(anchor, node), node) for node in graph)[:30]
        for distance_m, node in nearest:
            if distance_m <= 180:
                add_edge(anchor, node)

    distances = {start_key: 0.0}
    parents: dict[tuple[float, float], tuple[float, float] | None] = {start_key: None}
    heap = [(0.0, start_key)]
    while heap:
        distance, node = heapq.heappop(heap)
        if node == end_key:
            break
        if distance > distances.get(node, float("inf")):
            continue
        for nxt, weight in graph.get(node, []):
            next_distance = distance + weight
            if next_distance < distances.get(nxt, float("inf")):
                distances[nxt] = next_distance
                parents[nxt] = node
                heapq.heappush(heap, (next_distance, nxt))
    if end_key not in parents:
        raise SystemExit("Qingshan local medial path not connected")
    path = _restore_path(parents, end_key)
    line = LineString(path)
    return path, {
        "candidate_count": len(candidates),
        "graph_node_count": len(graph),
        "component_bridge_count": bridge_count,
        "path_length_km": round(_line_length_km(line), 4),
        "path_point_count": len(path),
        "path_coverage_ratio": round(_coverage_ratio(line, polygon), 6),
        "max_step_km": round(_max_step_km(path), 4),
    }


def _geometry_counts(geometry: Any) -> tuple[int, int]:
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


async def _ensure_match(session, channel: NavigationChannel, body: NavigationWaterBody, *, dry_run: bool) -> dict[str, Any]:
    existing = await session.scalar(
        select(NavigationChannelWaterBodyMatch).where(
            NavigationChannelWaterBodyMatch.channel_id == int(channel.id),
            NavigationChannelWaterBodyMatch.water_body_id == int(body.id),
            NavigationChannelWaterBodyMatch.is_current.is_(True),
        )
    )
    name = body.production_name or body.display_name or body.water_body_name or body.normalized_water_name
    result = {"water_body_id": int(body.id), "water_body_name": name}
    if existing is not None:
        result["status"] = "EXISTS"
        result["match_id"] = int(existing.id)
        return result
    if not dry_run:
        match = NavigationChannelWaterBodyMatch(
            channel_id=int(channel.id),
            water_body_id=int(body.id),
            match_batch_code="AUTO-WUSHEN-MIXED-SEED-20260606",
            match_type_code="LOCAL_REVIER_AND_OSM_WUSHEN_CHAIN",
            matched_term=str(name or body.water_body_code),
            score=92 if int(body.id) in {287836, 287484} else 88,
            confidence_code="AUTO_HIGH_CONFIDENCE",
            issue_codes=["WUSHEN_CHAIN_WATER_BODY_EVIDENCE"],
            is_current=True,
            source_water_area_ids_json=body.source_water_area_ids_json or [],
            source_trace_json={
                "source": "promote_wushen_mixed_seed",
                "evidence": "local Revier water body intersects or supports OSM Wushen chain",
                "applied_at": datetime.now(UTC).isoformat(),
            },
        )
        session.add(match)
        await session.flush()
        result["match_id"] = int(match.id)
    result["status"] = "DRY_RUN_CREATE" if dry_run else "CREATED"
    return result


async def main() -> None:
    args = parse_args()
    report = PromotionReport(
        generated_at=datetime.now(UTC).isoformat(),
        dry_run=bool(args.dry_run),
        channel_code=CHANNEL_CODE,
    )
    osm_way_coords = _load_osm_way_coords(args.osm_json, ORDERED_OSM_WAY_IDS)
    async with AsyncSessionLocal() as session:
        channel = await session.scalar(select(NavigationChannel).where(NavigationChannel.channel_code == CHANNEL_CODE))
        if channel is None:
            raise SystemExit(f"channel not found: {CHANNEL_CODE}")
        report.channel_id = int(channel.id)
        bodies = [
            body
            for body in (
                await session.execute(select(NavigationWaterBody).where(NavigationWaterBody.id.in_(LOCAL_WATER_BODY_IDS)))
            ).scalars()
            if body.geometry_wgs84_json
        ]
        body_by_id = {int(body.id): body for body in bodies}
        if set(LOCAL_WATER_BODY_IDS) - set(body_by_id):
            raise SystemExit(f"local water bodies missing geometry: {sorted(set(LOCAL_WATER_BODY_IDS) - set(body_by_id))}")
        body_geometries = [make_valid(shape(body.geometry_wgs84_json)) for body in bodies]
        local_boundary = make_valid(unary_union(body_geometries))
        service = NavigationCenterlineSegmentService(session)

        qingyi_endpoint = (118.475012, 31.313401)
        qingyi_qingshan_intersection = (118.4768, 31.3102)
        qingshan_local_end = (118.569796, 31.294638)
        shuiyang_graph_endpoint = (118.728903, 31.285128)
        coords: list[tuple[float, float]] = []
        gap_trace: list[dict[str, Any]] = []
        _append_coords(coords, [qingyi_endpoint, qingyi_qingshan_intersection], gap_trace, "QINGYI_TO_LOCAL_QINGSHAN_CONFLUENCE")
        qingshan_path, qingshan_meta = _qingshan_anchor_path(
            service=service,
            polygon=shape(body_by_id[287836].geometry_wgs84_json),
            start=qingyi_qingshan_intersection,
            end=qingshan_local_end,
        )
        _append_coords(coords, qingshan_path, gap_trace, "LOCAL_QINGSHAN_MEDIAL_AXIS")
        for index, way_id in enumerate(ORDERED_OSM_WAY_IDS):
            way_coords = osm_way_coords[way_id]
            if index == 0:
                oriented = _osm_tail_from_anchor(way_coords, coords[-1])
                if oriented:
                    snap_gap_m = _distance_m(coords[-1], oriented[0])
                    if snap_gap_m <= 30:
                        gap_trace.append(
                            {
                                "label": "SNAP_LOCAL_QINGSHAN_END_TO_OSM_PROJECTED_ANCHOR",
                                "from": [round(coords[-1][0], 6), round(coords[-1][1], 6)],
                                "to": [round(oriented[0][0], 6), round(oriented[0][1], 6)],
                                "gap_m": round(snap_gap_m, 2),
                            }
                        )
                        coords[-1] = oriented[0]
            else:
                forward_gap = _distance_m(coords[-1], way_coords[0])
                reverse_gap = _distance_m(coords[-1], way_coords[-1])
                oriented = way_coords if forward_gap <= reverse_gap else list(reversed(way_coords))
            _append_coords(coords, oriented, gap_trace, f"OSM_WAY_{way_id}")
        _append_coords(coords, [shuiyang_graph_endpoint], gap_trace, "YUNLIANG_TO_CURRENT_SHUIYANG_GRAPH_ENDPOINT")
        coords = _densify_coords(_clean_coords(coords), max_step_m=500.0)
        line = LineString(coords)
        corridor = line.buffer(float(args.corridor_buffer_degree), cap_style=1, join_style=2)
        boundary_geometry = make_valid(unary_union([local_boundary, corridor]))
        validation = {
            "status": "READY",
            "local_water_body_ids": LOCAL_WATER_BODY_IDS,
            "ordered_osm_way_ids": ORDERED_OSM_WAY_IDS,
            "gap_trace": gap_trace,
            "qingshan_local_medial_axis": qingshan_meta,
            "point_count": len(coords),
            "line_length_km": round(_line_length_km(line), 4),
            "max_step_km": round(_max_step_km(coords), 4),
            "boundary_coverage_ratio": round(_coverage_ratio(line, boundary_geometry), 6),
            "local_boundary_coverage_ratio": round(_coverage_ratio(line, local_boundary), 6),
            "line_is_simple": bool(line.is_simple),
            "self_intersection_samples": _self_intersection_samples(line),
            "line_bounds": [round(value, 6) for value in line.bounds],
        }
        blockers: list[str] = []
        if not validation["line_is_simple"]:
            blockers.append("CENTERLINE_SELF_INTERSECTION")
        if validation["max_step_km"] > float(args.max_step_km):
            blockers.append("CENTERLINE_STEP_TOO_LONG")
        if validation["boundary_coverage_ratio"] < float(args.min_boundary_coverage):
            blockers.append("CENTERLINE_BOUNDARY_COVERAGE_LOW")
        audit = audit_boundary_integrity(
            channel={
                "technical_grade_current_code": channel.technical_grade_current_code,
                "technical_grade_planned_code": channel.technical_grade_planned_code,
            },
            boundary={
                "geometry_status_code": "AVAILABLE",
                "geometry_json": mapping(boundary_geometry),
                "coverage_policy_code": "MIXED_LOCAL_OSM_WATERWAY_CORRIDOR",
                "source_trace_json": {"source": "promote_wushen_mixed_seed", "validation": validation},
            },
            centerline_geometries=[mapping(line)],
            require_centerline=True,
        )
        report.boundary_audit = audit
        if audit.get("blocking_issue_codes"):
            blockers.extend(str(code) for code in audit.get("blocking_issue_codes") or [])
        validation["blockers"] = sorted(set(blockers))
        report.validation = validation
        if blockers:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
            raise SystemExit(f"blocked: {sorted(set(blockers))}")

        for body_id in MATCH_WATER_BODY_IDS:
            report.water_body_match_results.append(
                await _ensure_match(session, channel, body_by_id[body_id], dry_run=bool(args.dry_run))
            )

        if not args.dry_run:
            current_boundaries = list(
                (
                    await session.execute(
                        select(NavigationChannelBoundary).where(
                            NavigationChannelBoundary.channel_id == int(channel.id),
                            NavigationChannelBoundary.is_current.is_(True),
                        )
                    )
                ).scalars()
            )
            for row in current_boundaries:
                row.is_current = False
            centroid = boundary_geometry.centroid
            min_lng, min_lat, max_lng, max_lat = boundary_geometry.bounds
            ring_count, point_count = _geometry_counts(boundary_geometry)
            source_trace = {
                "source": "promote_wushen_mixed_seed",
                "osm_json": str(args.osm_json),
                "local_water_body_ids": LOCAL_WATER_BODY_IDS,
                "ordered_osm_way_ids": ORDERED_OSM_WAY_IDS,
                "validation": validation,
                "boundary_integrity_audit": audit,
                "previous_boundary_ids": [int(row.id) for row in current_boundaries],
                "generated_at": datetime.now(UTC).isoformat(),
            }
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
                connectivity_status_code="CONNECTED" if boundary_geometry.geom_type == "Polygon" else "CONNECTED_WITH_BRIDGES",
                repair_status_code="AUTO_REPAIRED",
                coverage_policy_code="MIXED_LOCAL_OSM_WATERWAY_CORRIDOR",
                geometry_coordinate_system_code="WGS84",
                boundary_coordinate_system_code="WGS84",
                source_trace_json=source_trace,
                is_current=True,
                imported_at=datetime.now(UTC).replace(tzinfo=None),
            )
            session.add(boundary)
            await session.flush()
            report.promoted_boundary_id = int(boundary.id)

            existing_current = list(
                (
                    await session.execute(
                        select(NavigationChannelCenterline).where(
                            NavigationChannelCenterline.channel_id == int(channel.id),
                            NavigationChannelCenterline.is_current.is_(True),
                        )
                    )
                ).scalars()
            )
            for row in existing_current:
                row.is_current = False
            existing = await session.scalar(
                select(NavigationChannelCenterline).where(NavigationChannelCenterline.centerline_code == CENTERLINE_CODE)
            )
            min_lng, min_lat, max_lng, max_lat = line.bounds
            payload = {
                "channel_id": int(channel.id),
                "segment_id": None,
                "centerline_code": CENTERLINE_CODE,
                "centerline_name": "芜申线青山河-运粮河-水阳江混合证据中心线",
                "geometry_json": mapping(line),
                "source_type_code": "OSM_WATERWAY",
                "direction_code": "BIDIRECTIONAL",
                "is_main_line": True,
                "confidence_score": 84,
                "quality_code": "READY_WITH_WARNING",
                "review_status_code": "PUBLISHED",
                "version_no": 1,
                "parent_centerline_id": int(existing_current[0].id) if existing_current else None,
                "is_current": True,
                "source_trace_json": source_trace,
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
                report.promoted_centerline_id = int(centerline.id)
            else:
                for key, value in payload.items():
                    setattr(existing, key, value)
                await session.flush()
                report.promoted_centerline_id = int(existing.id)
            await session.commit()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    print(f"report_path={args.output}")


if __name__ == "__main__":
    asyncio.run(main())
