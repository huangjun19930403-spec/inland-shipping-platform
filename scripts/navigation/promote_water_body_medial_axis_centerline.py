"""Promote a connected local water-body medial-axis line as a current centerline.

This is intended for named waterways where boundary-derived rough generation
kept only a short local axis although the local water body contains a longer
continuous skeleton. It never uses provider route geometry as the centerline.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, MultiPoint, Point, mapping, shape
from shapely.ops import voronoi_diagram
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import NavigationChannelCenterline, NavigationWaterBody
from app.models.address import NavigationChannel, NavigationChannelBoundary, TransportNode
from app.modules.navigation.production_pipeline.boundary_quality_audit import audit_boundary_integrity
from app.modules.navigation.services.centerline_segments import NavigationCenterlineSegmentService


DEFAULT_OUTPUT = Path("runtime/navigation-production/reports/water_body_medial_axis_centerline_promotion_report.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Promote a connected local water-body medial-axis centerline.")
    parser.add_argument("--channel-code", required=True)
    parser.add_argument("--water-body-id", type=int, default=None)
    parser.add_argument("--anchor-transport-node-id", type=int, default=None)
    parser.add_argument("--max-component-gap-m", type=float, default=1500.0)
    parser.add_argument("--max-sample-points", type=int, default=800)
    parser.add_argument("--min-boundary-coverage", type=float, default=0.98)
    parser.add_argument("--min-line-length-km", type=float, default=1.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _distance_m(a: Point, b: Point) -> float:
    return (((a.x - b.x) * 111_320) ** 2 + ((a.y - b.y) * 110_540) ** 2) ** 0.5


def _line_coverage(line: LineString, polygon: Any, tolerance_degree: float = 0.0002) -> float:
    try:
        return float(line.intersection(polygon.buffer(tolerance_degree)).length / max(line.length, 1e-12))
    except Exception:
        return 0.0


def _graph_edges_as_lines(graph: dict[tuple[float, float], list[tuple[tuple[float, float], float]]]) -> list[LineString]:
    lines: list[LineString] = []
    seen: set[tuple[tuple[float, float], tuple[float, float]]] = set()
    for start, edges in graph.items():
        for end, _weight in edges:
            key = (start, end) if start <= end else (end, start)
            if key in seen:
                continue
            seen.add(key)
            lines.append(LineString([start, end]))
    return lines


def _build_connected_graph(
    *,
    service: NavigationCenterlineSegmentService,
    candidates: list[LineString],
    boundary_geometry: Any,
    max_component_gap_m: float,
) -> tuple[dict[tuple[float, float], list[tuple[tuple[float, float], float]]], list[dict[str, Any]]]:
    graph: dict[tuple[float, float], list[tuple[tuple[float, float], float]]] = defaultdict(list)

    def add_edge(start: tuple[float, float], end: tuple[float, float], weight: float) -> None:
        graph[start].append((end, weight))
        graph[end].append((start, weight))

    for line in candidates:
        coords = service._dedupe_coords([(float(lng), float(lat)) for lng, lat, *_rest in line.coords])
        for start, end in zip(coords, coords[1:]):
            if start != end:
                add_edge(start, end, service._distance_m(start, end))

    bridge_trace: list[dict[str, Any]] = []
    while graph:
        components = []
        seen: set[tuple[float, float]] = set()
        for node in list(graph):
            if node in seen:
                continue
            component = service._component_nodes(graph, node)
            seen.update(component)
            components.append(component)
        if len(components) <= 1:
            break
        nearest: tuple[float, int, int, tuple[float, float], tuple[float, float]] | None = None
        for left_idx, left in enumerate(components):
            for right_idx, right in enumerate(components):
                if right_idx <= left_idx:
                    continue
                for start in left:
                    start_point = Point(start)
                    for end in right:
                        gap_m = service._distance_m(start, end)
                        if gap_m > max_component_gap_m:
                            continue
                        connector = LineString([start, end])
                        if not boundary_geometry.buffer(0.0003).covers(connector):
                            continue
                        if nearest is None or gap_m < nearest[0]:
                            nearest = (gap_m, left_idx, right_idx, start, end)
                    # Keep pyflakes from treating start_point as removable while
                    # still making point construction failures visible in tests.
                    _ = start_point
        if nearest is None:
            break
        gap_m, left_idx, right_idx, start, end = nearest
        add_edge(start, end, gap_m)
        bridge_trace.append(
            {
                "bridge_type": "MEDIAL_AXIS_COMPONENT_CONNECTOR",
                "left_component_index": left_idx,
                "right_component_index": right_idx,
                "gap_m": round(gap_m, 2),
                "start": [round(start[0], 6), round(start[1], 6)],
                "end": [round(end[0], 6), round(end[1], 6)],
                "rule_code": "CONNECT_INTERNAL_SKELETON_COMPONENTS_WITHIN_WATER_BOUNDARY",
            }
        )
    return graph, bridge_trace


async def main() -> None:
    args = parse_args()
    async with AsyncSessionLocal() as session:
        channel = await session.scalar(select(NavigationChannel).where(NavigationChannel.channel_code == args.channel_code))
        if channel is None:
            raise SystemExit(f"channel not found: {args.channel_code}")
        boundary = await session.scalar(
            select(NavigationChannelBoundary).where(
                NavigationChannelBoundary.channel_id == channel.id,
                NavigationChannelBoundary.is_current.is_(True),
                NavigationChannelBoundary.geometry_status_code == "AVAILABLE",
            )
        )
        if boundary is None or not boundary.geometry_json:
            raise SystemExit(f"current boundary not found for {args.channel_code}")
        water_body = await session.get(NavigationWaterBody, args.water_body_id) if args.water_body_id else None
        anchor = await session.get(TransportNode, args.anchor_transport_node_id) if args.anchor_transport_node_id else None
        service = NavigationCenterlineSegmentService(session)

        boundary_geometry = shape(boundary.geometry_json)
        polygon = boundary_geometry
        if polygon.geom_type == "MultiPolygon":
            polygon = max(polygon.geoms, key=lambda item: item.area)
        span = max(polygon.bounds[2] - polygon.bounds[0], polygon.bounds[3] - polygon.bounds[1])
        points = service._sample_polygon_boundary_points(polygon, max_points=int(args.max_sample_points))
        if len(points) < 4:
            raise SystemExit("not enough boundary sample points")
        diagram = voronoi_diagram(MultiPoint(points), envelope=polygon.envelope.buffer(span * 0.05), edges=True)
        candidates = service._internal_voronoi_lines(diagram, polygon)
        graph, bridge_trace = _build_connected_graph(
            service=service,
            candidates=candidates,
            boundary_geometry=boundary_geometry,
            max_component_gap_m=float(args.max_component_gap_m),
        )
        if not graph:
            raise SystemExit("no medial-axis graph generated")
        line = service._longest_graph_path(_graph_edges_as_lines(graph))
        if line is None:
            raise SystemExit("connected medial-axis path generation failed")
        length_km = service._length_m(line) / 1000.0
        boundary_coverage = _line_coverage(line, boundary_geometry)
        anchor_distance_m = None
        if anchor is not None:
            anchor_distance_m = line.distance(Point(float(anchor.longitude), float(anchor.latitude))) * 111_320
        audit = audit_boundary_integrity(
            channel={
                "technical_grade_current_code": channel.technical_grade_current_code,
                "technical_grade_planned_code": channel.technical_grade_planned_code,
            },
            boundary={
                "geometry_status_code": "AVAILABLE",
                "geometry_json": boundary.geometry_json,
                "coverage_policy_code": boundary.coverage_policy_code,
                "source_trace_json": boundary.source_trace_json,
            },
            centerline_geometries=[mapping(line)],
            require_centerline=True,
        )
        report: dict[str, Any] = {
            "generated_at": datetime.now(UTC).isoformat(),
            "dry_run": bool(args.dry_run),
            "channel_id": int(channel.id),
            "channel_code": channel.channel_code,
            "channel_name": channel.channel_name,
            "boundary_id": int(boundary.id),
            "water_body_id": int(water_body.id) if water_body is not None else None,
            "water_body_name": (
                water_body.production_name or water_body.display_name or water_body.water_body_name or water_body.normalized_water_name
                if water_body is not None
                else None
            ),
            "candidate_line_count": len(candidates),
            "bridge_count": len(bridge_trace),
            "bridge_trace_sample": bridge_trace[:20],
            "line_length_km": round(length_km, 6),
            "line_point_count": len(line.coords),
            "line_bounds": [round(value, 6) for value in line.bounds],
            "boundary_coverage_ratio": round(boundary_coverage, 6),
            "anchor_transport_node_id": int(anchor.id) if anchor is not None else None,
            "anchor_distance_m": round(anchor_distance_m, 2) if anchor_distance_m is not None else None,
            "audit": audit,
            "promoted_centerline_id": None,
        }
        blockers: list[str] = []
        if length_km < float(args.min_line_length_km):
            blockers.append("CENTERLINE_TOO_SHORT")
        if boundary_coverage < float(args.min_boundary_coverage):
            blockers.append("CENTERLINE_OUT_OF_BOUNDARY")
        if audit.get("blocking_issue_codes"):
            blockers.extend(str(code) for code in audit.get("blocking_issue_codes") or [])
        report["blockers"] = blockers
        if blockers:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            raise SystemExit(f"blocked: {blockers}")

        if not args.dry_run:
            existing_current = list(
                (
                    await session.execute(
                        select(NavigationChannelCenterline).where(
                            NavigationChannelCenterline.channel_id == channel.id,
                            NavigationChannelCenterline.is_current.is_(True),
                            NavigationChannelCenterline.is_main_line.is_(True),
                        )
                    )
                ).scalars()
            )
            for row in existing_current:
                row.is_current = False
            bbox_min_lng, bbox_min_lat, bbox_max_lng, bbox_max_lat = line.bounds
            previous_centerline_id = int(existing_current[0].id) if existing_current else None
            centerline = NavigationChannelCenterline(
                channel_id=int(channel.id),
                centerline_code=f"AUTO-MEDIAL-CL-{channel.id}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
                centerline_name=f"{channel.channel_name}水体骨架自动中心线",
                geometry_json=mapping(line),
                source_type_code="AUTO_WATER_BODY_MEDIAL_AXIS",
                direction_code="BIDIRECTIONAL",
                is_main_line=True,
                confidence_score=86,
                quality_code="READY_WITH_WARNING" if audit.get("issue_codes") else "READY",
                review_status_code="PUBLISHED",
                version_no=(max((int(row.version_no or 1) for row in existing_current), default=0) + 1),
                parent_centerline_id=previous_centerline_id,
                is_current=True,
                source_trace_json={
                    "source": "promote_water_body_medial_axis_centerline",
                    "algorithm": "CONNECTED_VORONOI_MEDIAL_AXIS_V1",
                    "source_boundary_id": int(boundary.id),
                    "based_on_boundary_id": int(boundary.id),
                    "water_body_id": int(water_body.id) if water_body is not None else None,
                    "candidate_line_count": len(candidates),
                    "component_bridge_count": len(bridge_trace),
                    "component_bridge_trace": bridge_trace,
                    "boundary_coverage_ratio": round(boundary_coverage, 6),
                    "anchor_transport_node_id": int(anchor.id) if anchor is not None else None,
                    "anchor_distance_m": round(anchor_distance_m, 2) if anchor_distance_m is not None else None,
                    "boundary_integrity_audit": audit,
                    "previous_centerline_id": previous_centerline_id,
                    "no_approval_task_created": True,
                    "published_at": datetime.now(UTC).isoformat(),
                },
                bbox_min_lng=bbox_min_lng,
                bbox_min_lat=bbox_min_lat,
                bbox_max_lng=bbox_max_lng,
                bbox_max_lat=bbox_max_lat,
            )
            session.add(centerline)
            await session.flush()
            report["promoted_centerline_id"] = int(centerline.id)
            await session.commit()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
