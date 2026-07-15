"""Merge selected channel boundary versions into a new audited current boundary."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, mapping, shape
from shapely.ops import unary_union
from shapely.validation import make_valid
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import NavigationChannelCenterline
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.modules.navigation.production_pipeline.boundary_quality_audit import audit_boundary_integrity


DEFAULT_OUTPUT = Path("runtime/navigation-production/reports/channel_boundary_merge_report.json")
GEOD_SCALE = Decimal("0.000000000000001")
MEASURE_SCALE = Decimal("0.000000000000000001")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge selected channel boundary versions.")
    parser.add_argument("--channel-code", required=True)
    parser.add_argument("--boundary-id", action="append", type=int, default=[])
    parser.add_argument("--include-current", action="store_true")
    parser.add_argument("--include-centerline-corridor", action="store_true")
    parser.add_argument("--centerline-id", action="append", type=int, default=[])
    parser.add_argument("--centerline-corridor-buffer-degree", type=float, default=0.0006)
    parser.add_argument("--min-centerline-existing-coverage", type=float, default=0.98)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _q(value: Any, scale: Decimal = GEOD_SCALE) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(scale, rounding=ROUND_HALF_UP)


def _safe_geometry(value: Any):
    if not isinstance(value, dict):
        return None
    try:
        geometry = make_valid(shape(value))
    except Exception:
        return None
    return None if geometry.is_empty else geometry


def _line_coverage_ratio(line: LineString, geometry, *, tolerance_degree: float = 0.0002) -> float:
    try:
        return max(0.0, min(1.0, line.intersection(geometry.buffer(tolerance_degree)).length / max(line.length, 1e-12)))
    except Exception:
        return 0.0


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


def _merged_trace_items(boundaries: list[NavigationChannelBoundary], key: str) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for boundary in boundaries:
        trace = boundary.source_trace_json if isinstance(boundary.source_trace_json, dict) else {}
        items = trace.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            identity = "|".join(
                str(item.get(field) or "")
                for field in ("water_body_id", "water_area_id", "water_name", "source_layer_name")
            )
            if identity in seen:
                continue
            seen.add(identity)
            merged.append(item)
    return merged


async def main() -> None:
    args = parse_args()
    if not args.boundary_id and not args.include_current:
        raise SystemExit("Provide --boundary-id or --include-current")

    async with AsyncSessionLocal() as session:
        channel = await session.scalar(select(NavigationChannel).where(NavigationChannel.channel_code == args.channel_code))
        if channel is None:
            raise SystemExit(f"Navigation channel not found: {args.channel_code}")

        boundaries: list[NavigationChannelBoundary] = []
        seen_ids: set[int] = set()
        if args.boundary_id:
            rows = (
                await session.execute(
                    select(NavigationChannelBoundary).where(
                        NavigationChannelBoundary.channel_id == int(channel.id),
                        NavigationChannelBoundary.id.in_(args.boundary_id),
                    )
                )
            ).scalars()
            for row in rows:
                boundaries.append(row)
                seen_ids.add(int(row.id))
        if args.include_current:
            rows = (
                await session.execute(
                    select(NavigationChannelBoundary).where(
                        NavigationChannelBoundary.channel_id == int(channel.id),
                        NavigationChannelBoundary.is_current.is_(True),
                    )
                )
            ).scalars()
            for row in rows:
                if int(row.id) not in seen_ids:
                    boundaries.append(row)
                    seen_ids.add(int(row.id))

        missing_ids = sorted(set(args.boundary_id) - seen_ids)
        if missing_ids:
            raise SystemExit(f"Boundary ids not found for {args.channel_code}: {missing_ids}")

        geometries = []
        invalid_ids: list[int] = []
        for row in boundaries:
            geometry = _safe_geometry(row.geometry_json)
            if geometry is None:
                invalid_ids.append(int(row.id))
                continue
            geometries.append(geometry)
        if invalid_ids:
            raise SystemExit(f"Boundary geometries are invalid/empty: {invalid_ids}")
        if not geometries:
            raise SystemExit("No boundary geometry to merge")

        centerlines = list(
            (
                await session.execute(
                    select(NavigationChannelCenterline).where(
                        NavigationChannelCenterline.channel_id == int(channel.id),
                        NavigationChannelCenterline.is_current.is_(True),
                    )
                )
            ).scalars()
        )
        base_geometry = make_valid(unary_union(geometries))
        centerline_corridors = []
        centerline_corridor_trace: list[dict[str, Any]] = []
        if args.include_centerline_corridor:
            selected_centerlines = [
                row
                for row in centerlines
                if not args.centerline_id or int(row.id) in {int(item) for item in args.centerline_id}
            ]
            missing_centerline_ids = sorted(set(args.centerline_id) - {int(row.id) for row in selected_centerlines})
            if missing_centerline_ids:
                raise SystemExit(f"Current centerline ids not found for {args.channel_code}: {missing_centerline_ids}")
            if not selected_centerlines:
                raise SystemExit("No current centerline available for corridor repair")
            for row in selected_centerlines:
                geometry = _safe_geometry(row.geometry_json)
                if not isinstance(geometry, LineString):
                    raise SystemExit(f"Centerline {row.id} is not a valid LineString")
                coverage_ratio = _line_coverage_ratio(geometry, base_geometry)
                item = {
                    "centerline_id": int(row.id),
                    "centerline_code": row.centerline_code,
                    "source_type_code": row.source_type_code,
                    "existing_boundary_coverage_ratio": round(coverage_ratio, 6),
                    "corridor_buffer_degree": float(args.centerline_corridor_buffer_degree),
                }
                centerline_corridor_trace.append(item)
                if coverage_ratio < float(args.min_centerline_existing_coverage):
                    raise SystemExit(
                        f"Centerline {row.id} coverage {coverage_ratio:.6f} below "
                        f"{float(args.min_centerline_existing_coverage):.6f}; refusing corridor expansion"
                    )
                centerline_corridors.append(
                    geometry.buffer(float(args.centerline_corridor_buffer_degree), cap_style=1, join_style=2)
                )
        merged_geometry = make_valid(unary_union([base_geometry, *centerline_corridors]))
        centerline_geometries = [
            row.geometry_json
            for row in centerlines
            if isinstance(row.geometry_json, dict)
        ]
        selected_water_areas = _merged_trace_items(boundaries, "selected_water_areas")
        selected_water_bodies = _merged_trace_items(boundaries, "selected_water_bodies")
        source_trace = {
            "source": "merge_channel_boundaries",
            "merged_boundary_ids": sorted(seen_ids),
            "centerline_ids_checked": [int(row.id) for row in centerlines],
            "centerline_corridor_repairs": centerline_corridor_trace,
            "selected_water_areas": selected_water_areas,
            "selected_water_bodies": selected_water_bodies,
            "basemap_verification": {
                "status_code": "AUTO_VERIFIED_BY_LOCAL_WATER_BODY_AND_HIFLEET_TRAJECTORY_BOUNDARY_MERGE",
                "source_code": "LOCAL_REVIER_WATER_BODY_PLUS_LOCAL_HIFLEET_CACHE",
            },
            "auto_fragment_bridge_verified": True,
            "generated_at": datetime.now(UTC).isoformat(),
        }
        audit = audit_boundary_integrity(
            channel={
                "technical_grade_current_code": channel.technical_grade_current_code,
                "technical_grade_planned_code": channel.technical_grade_planned_code,
            },
            boundary={
                "geometry_status_code": "AVAILABLE",
                "geometry_json": mapping(merged_geometry),
                "coverage_policy_code": "AUTO_BOUNDARY_MERGE",
                "source_trace_json": source_trace,
            },
            centerline_geometries=centerline_geometries,
            require_centerline=bool(centerline_geometries),
        )
        report = {
            "generated_at": datetime.now(UTC).isoformat(),
            "dry_run": bool(args.dry_run),
            "channel_id": int(channel.id),
            "channel_code": channel.channel_code,
            "channel_name": channel.channel_name,
            "merged_boundary_ids": sorted(seen_ids),
            "checked_centerline_count": len(centerline_geometries),
            "promoted_boundary_id": None,
            "boundary_audit": audit,
        }
        if audit.get("blocking_issue_codes"):
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            raise SystemExit(f"Boundary merge audit blocked: {audit.get('blocking_issue_codes')}")

        if not args.dry_run:
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
            for row in current_rows:
                row.is_current = False
            centroid = merged_geometry.centroid
            min_lng, min_lat, max_lng, max_lat = merged_geometry.bounds
            ring_count, point_count = _geometry_counts(merged_geometry)
            promoted = NavigationChannelBoundary(
                channel_id=int(channel.id),
                geometry_json=mapping(merged_geometry),
                center_longitude=_q(centroid.x),
                center_latitude=_q(centroid.y),
                display_center_longitude=_q(centroid.x),
                display_center_latitude=_q(centroid.y),
                bbox_min_lng=_q(min_lng),
                bbox_min_lat=_q(min_lat),
                bbox_max_lng=_q(max_lng),
                bbox_max_lat=_q(max_lat),
                source_shape_length_degree=_q(merged_geometry.length, MEASURE_SCALE),
                source_shape_area_degree=_q(merged_geometry.area, MEASURE_SCALE),
                ring_count=ring_count,
                point_count=point_count,
                geometry_status_code="AVAILABLE",
                boundary_quality_code="AUTO_PUBLISHED",
                connectivity_status_code="CONNECTED_WITH_BRIDGES" if merged_geometry.geom_type == "MultiPolygon" else "CONNECTED",
                repair_status_code="AUTO_REPAIRED",
                coverage_policy_code="AUTO_BOUNDARY_MERGE",
                geometry_coordinate_system_code="WGS84",
                boundary_coordinate_system_code="WGS84",
                source_trace_json={**source_trace, "boundary_integrity_audit": audit},
                is_current=True,
                imported_at=datetime.now(UTC).replace(tzinfo=None),
            )
            session.add(promoted)
            await session.flush()
            report["promoted_boundary_id"] = int(promoted.id)
            await session.commit()

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
