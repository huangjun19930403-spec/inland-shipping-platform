"""Expand a channel boundary with a validated route endpoint connector.

This is for cases where a local route passes geometry/water validation through a
published centerline seed, but graph building disables the transport connector
because the current channel boundary misses a small endpoint access corridor.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import app.models  # noqa: F401
from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import unary_union
from shapely.validation import make_valid
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import NavigationChannelWaterBodyMatch, NavigationRouteRequest, NavigationRouteResult, NavigationWaterBody
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.modules.navigation.production_pipeline.boundary_quality_audit import audit_boundary_integrity


DEFAULT_OUTPUT = Path("runtime/navigation-production/reports/boundary_connector_repair_report.json")
GEOD_SCALE = Decimal("0.000000000000001")
MEASURE_SCALE = Decimal("0.000000000000000001")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair a channel boundary from a validated route connector.")
    parser.add_argument("--route-result-id", type=int, required=True)
    parser.add_argument("--min-existing-boundary-coverage", type=float, default=0.9)
    parser.add_argument("--min-water-body-coverage", type=float, default=0.9)
    parser.add_argument("--max-snap-distance-m", type=float, default=1000.0)
    parser.add_argument("--corridor-buffer-degree", type=float, default=0.001)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _q(value: Any, scale: Decimal = GEOD_SCALE) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(scale, rounding=ROUND_HALF_UP)


def _geometry_counts(geometry) -> tuple[int, int]:
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


def _point_distance_m(a: Point, b: Point) -> float:
    return (((a.x - b.x) * 111_320) ** 2 + ((a.y - b.y) * 110_540) ** 2) ** 0.5


def _line_coverage_ratio(line: LineString, geometry, *, tolerance_degree: float = 0.0002) -> float:
    try:
        return max(0.0, min(1.0, line.intersection(geometry.buffer(tolerance_degree)).length / max(line.length, 1e-12)))
    except Exception:
        return 0.0


def _connector_candidates(result: NavigationRouteResult, request: NavigationRouteRequest, *, max_snap_distance_m: float) -> list[dict[str, Any]]:
    summary = result.quality_summary_json if isinstance(result.quality_summary_json, dict) else {}
    candidates: list[dict[str, Any]] = []
    for role, endpoint in (
        ("origin", Point(float(request.origin_lng), float(request.origin_lat))),
        ("destination", Point(float(request.destination_lng), float(request.destination_lat))),
    ):
        snap = summary.get(f"{role}_snap")
        if not isinstance(snap, dict) or not snap.get("snap_point"):
            continue
        snap_point = Point(float(snap["snap_point"][0]), float(snap["snap_point"][1]))
        distance_m = float(snap.get("snap_distance_m") or _point_distance_m(endpoint, snap_point))
        if distance_m <= 200.0 or distance_m > max_snap_distance_m:
            continue
        line = LineString([(endpoint.x, endpoint.y), (snap_point.x, snap_point.y)])
        if line.length <= 0:
            continue
        candidates.append(
            {
                "role": role.upper(),
                "endpoint": [endpoint.x, endpoint.y],
                "snap_point": [snap_point.x, snap_point.y],
                "snap_distance_m": round(distance_m, 3),
                "line": line,
            }
        )
    return candidates


async def _matched_water_bodies(session, channel_id: int, connector: LineString) -> list[NavigationWaterBody]:
    min_lng, min_lat, max_lng, max_lat = connector.buffer(0.02).bounds
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
                    NavigationWaterBody.bbox_max_lng >= min_lng,
                    NavigationWaterBody.bbox_min_lng <= max_lng,
                    NavigationWaterBody.bbox_max_lat >= min_lat,
                    NavigationWaterBody.bbox_min_lat <= max_lat,
                )
                .order_by(NavigationChannelWaterBodyMatch.score.desc(), NavigationWaterBody.id)
            )
        ).scalars()
    )


async def main() -> None:
    args = parse_args()
    async with AsyncSessionLocal() as session:
        result = await session.get(NavigationRouteResult, int(args.route_result_id))
        if result is None:
            raise SystemExit(f"NavigationRouteResult not found: {args.route_result_id}")
        request = await session.get(NavigationRouteRequest, int(result.request_id))
        if request is None:
            raise SystemExit(f"NavigationRouteRequest not found: {result.request_id}")
        summary = result.quality_summary_json if isinstance(result.quality_summary_json, dict) else {}
        channel_id = int(summary.get("channel_id") or (result.channel_ids or [0])[0] or 0)
        if not channel_id:
            raise SystemExit("Route result has no channel_id for boundary repair")
        channel = await session.get(NavigationChannel, channel_id)
        boundary = await session.scalar(
            select(NavigationChannelBoundary).where(
                NavigationChannelBoundary.channel_id == channel_id,
                NavigationChannelBoundary.is_current.is_(True),
                NavigationChannelBoundary.geometry_status_code == "AVAILABLE",
            )
        )
        if channel is None or boundary is None or not boundary.geometry_json:
            raise SystemExit(f"Current boundary not found for channel {channel_id}")

        boundary_geometry = make_valid(shape(boundary.geometry_json))
        candidates = _connector_candidates(result, request, max_snap_distance_m=float(args.max_snap_distance_m))
        items: list[dict[str, Any]] = []
        accepted_lines: list[LineString] = []
        for candidate in candidates:
            line: LineString = candidate["line"]
            existing_coverage = _line_coverage_ratio(line, boundary_geometry)
            bodies = await _matched_water_bodies(session, channel_id, line)
            water_coverages = []
            for body in bodies:
                body_geometry = make_valid(shape(body.geometry_wgs84_json))
                coverage = _line_coverage_ratio(line, body_geometry)
                water_coverages.append(
                    {
                        "water_body_id": int(body.id),
                        "name": body.production_name or body.display_name or body.water_body_name or body.normalized_water_name,
                        "water_level_min": body.water_level_min,
                        "water_level_max": body.water_level_max,
                        "water_type_code": body.water_type_code,
                        "coverage_ratio": round(coverage, 6),
                    }
                )
            best_water_coverage = max((item["coverage_ratio"] for item in water_coverages), default=0.0)
            accepted = (
                existing_coverage >= float(args.min_existing_boundary_coverage)
                and best_water_coverage >= float(args.min_water_body_coverage)
            )
            item = {
                **{key: value for key, value in candidate.items() if key != "line"},
                "existing_boundary_coverage_ratio": round(existing_coverage, 6),
                "best_water_body_coverage_ratio": round(best_water_coverage, 6),
                "water_coverages": water_coverages[:10],
                "accepted": accepted,
            }
            items.append(item)
            if accepted:
                accepted_lines.append(line)

        report: dict[str, Any] = {
            "generated_at": datetime.now(UTC).isoformat(),
            "dry_run": bool(args.dry_run),
            "route_result_id": int(result.id),
            "request_id": int(request.id),
            "channel_id": channel_id,
            "channel_code": channel.channel_code,
            "channel_name": channel.channel_name,
            "previous_boundary_id": int(boundary.id),
            "accepted_connector_count": len(accepted_lines),
            "promoted_boundary_id": None,
            "items": items,
        }
        if not accepted_lines:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            raise SystemExit("No connector passed boundary repair validation")

        corridor = unary_union([line.buffer(float(args.corridor_buffer_degree), cap_style=1, join_style=2) for line in accepted_lines])
        repaired_geometry = make_valid(unary_union([boundary_geometry, corridor]))
        audit = audit_boundary_integrity(
            channel={
                "technical_grade_current_code": channel.technical_grade_current_code,
                "technical_grade_planned_code": channel.technical_grade_planned_code,
            },
            boundary={
                "geometry_status_code": "AVAILABLE",
                "geometry_json": mapping(repaired_geometry),
                "coverage_policy_code": boundary.coverage_policy_code,
                "source_trace_json": boundary.source_trace_json,
            },
            centerline_geometries=[mapping(line) for line in accepted_lines],
            require_centerline=True,
        )
        report["boundary_audit"] = audit
        if audit.get("blocking_issue_codes"):
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            raise SystemExit(f"Boundary repair audit blocked: {audit.get('blocking_issue_codes')}")

        if not args.dry_run:
            boundary.is_current = False
            centroid = repaired_geometry.centroid
            min_lng, min_lat, max_lng, max_lat = repaired_geometry.bounds
            ring_count, point_count = _geometry_counts(repaired_geometry)
            source_trace = {
                **(boundary.source_trace_json if isinstance(boundary.source_trace_json, dict) else {}),
                "connector_boundary_repair": {
                    "source": "repair_channel_boundary_from_validated_route_connector",
                    "route_result_id": int(result.id),
                    "request_id": int(request.id),
                    "previous_boundary_id": int(boundary.id),
                    "accepted_connectors": items,
                    "corridor_buffer_degree": float(args.corridor_buffer_degree),
                    "boundary_audit": audit,
                    "repaired_at": datetime.now(UTC).isoformat(),
                },
            }
            repaired = NavigationChannelBoundary(
                channel_id=channel_id,
                geometry_json=mapping(repaired_geometry),
                center_longitude=_q(centroid.x),
                center_latitude=_q(centroid.y),
                display_center_longitude=_q(centroid.x),
                display_center_latitude=_q(centroid.y),
                bbox_min_lng=_q(min_lng),
                bbox_min_lat=_q(min_lat),
                bbox_max_lng=_q(max_lng),
                bbox_max_lat=_q(max_lat),
                source_shape_length_degree=_q(repaired_geometry.length, MEASURE_SCALE),
                source_shape_area_degree=_q(repaired_geometry.area, MEASURE_SCALE),
                ring_count=ring_count,
                point_count=point_count,
                geometry_status_code="AVAILABLE",
                boundary_quality_code="AUTO_PUBLISHED",
                connectivity_status_code=boundary.connectivity_status_code or "CONNECTED_WITH_BRIDGES",
                repair_status_code="AUTO_REPAIRED",
                coverage_policy_code=boundary.coverage_policy_code,
                geometry_coordinate_system_code="WGS84",
                boundary_coordinate_system_code="WGS84",
                source_trace_json=source_trace,
                is_current=True,
                imported_at=datetime.now(UTC).replace(tzinfo=None),
            )
            session.add(repaired)
            await session.flush()
            await session.commit()
            report["promoted_boundary_id"] = int(repaired.id)

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"report_path={args.output}")


if __name__ == "__main__":
    asyncio.run(main())
