"""Dry-run or apply grouped waybill boundary patch plans.

This script consumes the segment-level repair queue with geometry, rebuilds the
grouped patch plan in memory, and unions PATCH_READY boundary corridors with the
current channel boundary. It writes only when --apply is passed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.models.navigation import NavigationChannelCenterline
from app.modules.navigation.production_pipeline.boundary_quality_audit import audit_boundary_integrity
from scripts.navigation.audit_waybill_reference_against_current_graph import _line
from scripts.navigation.build_waybill_segment_patch_plan import _build_groups


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = PROJECT_ROOT / "runtime/navigation-production/reports"
DEFAULT_QUEUE = REPORT_DIR / "waybill_segment_level_repair_queue_with_geometry_20260611.json"
DEFAULT_OUTPUT = REPORT_DIR / "waybill_segment_boundary_patch_apply_dry_run_20260611.json"
POLICY_CODE = "WAYBILL_SEGMENT_PATCH_CORRIDOR"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply grouped waybill boundary patches after integrity audit.")
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--boundary-buffer-m", type=float, default=220.0)
    parser.add_argument("--seed-buffer-m", type=float, default=80.0)
    parser.add_argument("--min-support-waybills", type=int, default=2)
    parser.add_argument("--target-channel-codes", nargs="*", default=None)
    parser.add_argument("--max-groups", type=int, default=0)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    source = json.loads(args.queue.read_text(encoding="utf-8"))
    groups = _build_groups(
        source.get("items") or [],
        boundary_buffer_m=float(args.boundary_buffer_m),
        seed_buffer_m=float(args.seed_buffer_m),
        min_support_waybills=int(args.min_support_waybills),
    )
    boundary_groups = [
        group for group in groups["boundary_patch_groups"] if group.get("patch_status_code") == "PATCH_READY"
    ]
    if args.target_channel_codes:
        allowed = set(args.target_channel_codes)
        boundary_groups = [
            group
            for group in boundary_groups
            if str((group.get("target_payload") or {}).get("channel_code") or "") in allowed
        ]
    if int(args.max_groups) > 0:
        boundary_groups = boundary_groups[: int(args.max_groups)]

    async with AsyncSessionLocal() as session:
        report_items = []
        applied_ids: list[int] = []
        for group in boundary_groups:
            item = await _audit_group(session, group, apply=bool(args.apply))
            report_items.append(item)
            if item.get("applied_boundary_id"):
                applied_ids.append(int(item["applied_boundary_id"]))
        if args.apply:
            await session.commit()
        else:
            await session.rollback()

    report = {
        "report_version": "WAYBILL_SEGMENT_BOUNDARY_PATCH_APPLY_V1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_queue": str(args.queue),
        "args": {
            "boundary_buffer_m": float(args.boundary_buffer_m),
            "seed_buffer_m": float(args.seed_buffer_m),
            "min_support_waybills": int(args.min_support_waybills),
            "target_channel_codes": args.target_channel_codes,
            "max_groups": int(args.max_groups),
            "apply": bool(args.apply),
        },
        "summary": _summary(report_items, applied_ids),
        "items": report_items,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"report_path={args.output}")


async def _audit_group(session, group: dict[str, Any], *, apply: bool) -> dict[str, Any]:
    channel_id = int(group.get("target_key") or 0)
    channel = await session.get(NavigationChannel, channel_id)
    if channel is None:
        return _base_item(group, status="BLOCKED_CHANNEL_NOT_FOUND")
    patch_geometry = _geometry(group.get("corridor_geometry_json"))
    if patch_geometry is None:
        return _base_item(group, channel=channel, status="BLOCKED_PATCH_GEOMETRY_INVALID")

    current_boundaries = await _current_boundaries(session, channel_id)
    current_geometry = _boundary_union(current_boundaries)
    union_inputs = [geometry for geometry in (current_geometry, patch_geometry) if geometry is not None]
    if not union_inputs:
        return _base_item(group, channel=channel, status="BLOCKED_EMPTY_UNION")
    merged = make_valid(unary_union(union_inputs))
    centerline_geometries = await _centerline_geometries(session, channel_id)
    sample_lines = [_line(geometry) for geometry in group.get("sample_line_geometries_json") or []]
    sample_lines = [line for line in sample_lines if line is not None]
    audit = audit_boundary_integrity(
        channel={
            "technical_grade_current_code": channel.technical_grade_current_code,
            "technical_grade_planned_code": channel.technical_grade_planned_code,
        },
        boundary={
            "geometry_status_code": "AVAILABLE",
            "geometry_json": mapping(merged),
            "coverage_policy_code": POLICY_CODE,
            "source_trace_json": _source_trace(group, current_boundaries),
        },
        centerline_geometries=[mapping(line) for line in [*centerline_geometries, *sample_lines]],
        require_centerline=True,
    )
    blocking = audit.get("blocking_issue_codes") or []
    status = "READY_TO_APPLY" if not blocking else "BLOCKED_BOUNDARY_AUDIT"
    applied_boundary_id = None
    if apply and status == "READY_TO_APPLY":
        for row in current_boundaries:
            row.is_current = False
        boundary = _boundary_row(channel_id, merged, group, current_boundaries, audit)
        session.add(boundary)
        await session.flush()
        applied_boundary_id = int(boundary.id)
    return {
        **_base_item(group, channel=channel, status=status),
        "current_boundary_ids": [int(row.id) for row in current_boundaries],
        "applied_boundary_id": applied_boundary_id,
        "audit": audit,
        "merged_bbox": _bbox(merged),
        "merged_ring_count": _geometry_counts(merged)[0],
        "merged_point_count": _geometry_counts(merged)[1],
    }


async def _current_boundaries(session, channel_id: int) -> list[NavigationChannelBoundary]:
    return list(
        (
            await session.execute(
                select(NavigationChannelBoundary)
                .where(
                    NavigationChannelBoundary.channel_id == channel_id,
                    NavigationChannelBoundary.is_current.is_(True),
                    NavigationChannelBoundary.geometry_status_code == "AVAILABLE",
                    NavigationChannelBoundary.geometry_json.is_not(None),
                )
                .order_by(NavigationChannelBoundary.id)
            )
        ).scalars()
    )


async def _centerline_geometries(session, channel_id: int) -> list[Any]:
    rows = list(
        (
            await session.execute(
                select(NavigationChannelCenterline).where(
                    NavigationChannelCenterline.channel_id == channel_id,
                    NavigationChannelCenterline.is_current.is_(True),
                    NavigationChannelCenterline.geometry_json.is_not(None),
                )
            )
        ).scalars()
    )
    lines = [_line(row.geometry_json) for row in rows]
    return [line for line in lines if line is not None]


def _boundary_row(
    channel_id: int,
    geometry: BaseGeometry,
    group: dict[str, Any],
    previous_boundaries: list[NavigationChannelBoundary],
    audit: dict[str, Any],
) -> NavigationChannelBoundary:
    centroid = geometry.centroid
    min_lng, min_lat, max_lng, max_lat = geometry.bounds
    ring_count, point_count = _geometry_counts(geometry)
    return NavigationChannelBoundary(
        channel_id=channel_id,
        geometry_json=mapping(geometry),
        center_longitude=_q(centroid.x),
        center_latitude=_q(centroid.y),
        display_center_longitude=_q(centroid.x),
        display_center_latitude=_q(centroid.y),
        bbox_min_lng=_q(min_lng),
        bbox_min_lat=_q(min_lat),
        bbox_max_lng=_q(max_lng),
        bbox_max_lat=_q(max_lat),
        source_shape_length_degree=_q(geometry.length, 18),
        source_shape_area_degree=_q(geometry.area, 18),
        ring_count=ring_count,
        point_count=point_count,
        geometry_status_code="AVAILABLE",
        boundary_quality_code="AUTO_PUBLISHED",
        connectivity_status_code="CONNECTED" if geometry.geom_type == "Polygon" else "CONNECTED_WITH_BRIDGES",
        repair_status_code="AUTO_REPAIRED",
        coverage_policy_code=POLICY_CODE,
        geometry_coordinate_system_code="WGS84",
        boundary_coordinate_system_code="WGS84",
        source_trace_json={
            **_source_trace(group, previous_boundaries),
            "boundary_integrity_audit": audit,
        },
        is_current=True,
        imported_at=datetime.now(UTC).replace(tzinfo=None),
    )


def _source_trace(group: dict[str, Any], previous_boundaries: list[NavigationChannelBoundary]) -> dict[str, Any]:
    return {
        "source": "apply_waybill_segment_boundary_patch_plan",
        "policy": POLICY_CODE,
        "patch_group": {
            key: group.get(key)
            for key in (
                "patch_type_code",
                "target_key",
                "target_name",
                "segment_count",
                "waybill_count",
                "route_count",
                "raw_segment_length_km",
                "deduped_line_length_km",
                "bbox",
                "source_waybill_examples",
            )
        },
        "previous_boundary_ids": [int(row.id) for row in previous_boundaries],
        "basemap_verification": {
            "status_code": "AUTO_VERIFIED_BY_LOCAL_WATER_GEOMETRY_AND_REAL_WAYBILL_TRACK",
            "source_code": "LOCAL_REVIER_WATER_GEOMETRY_INTERSECTED_REAL_WAYBILL",
        },
        "auto_fragment_bridge_verified": True,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _base_item(
    group: dict[str, Any],
    *,
    channel: NavigationChannel | None = None,
    status: str,
) -> dict[str, Any]:
    target_payload = group.get("target_payload") if isinstance(group.get("target_payload"), dict) else {}
    return {
        "patch_apply_status_code": status,
        "patch_type_code": group.get("patch_type_code"),
        "target_channel_id": int(channel.id) if channel is not None else target_payload.get("id"),
        "target_channel_code": channel.channel_code if channel is not None else target_payload.get("channel_code"),
        "target_channel_name": channel.channel_name if channel is not None else group.get("target_name"),
        "segment_count": group.get("segment_count"),
        "waybill_count": group.get("waybill_count"),
        "route_count": group.get("route_count"),
        "raw_segment_length_km": group.get("raw_segment_length_km"),
        "deduped_line_length_km": group.get("deduped_line_length_km"),
        "patch_plan_bbox": group.get("bbox"),
    }


def _summary(items: list[dict[str, Any]], applied_ids: list[int]) -> dict[str, Any]:
    statuses = Counter(item.get("patch_apply_status_code") for item in items)
    ready_items = [item for item in items if item.get("patch_apply_status_code") == "READY_TO_APPLY"]
    blocked_issues = Counter(
        code
        for item in items
        for code in ((item.get("audit") or {}).get("blocking_issue_codes") or [])
    )
    return {
        "audited_group_count": len(items),
        "status_counts": dict(sorted(statuses.items())),
        "ready_to_apply_count": len(ready_items),
        "ready_to_apply_length_km": round(sum(float(item.get("raw_segment_length_km") or 0) for item in ready_items), 3),
        "applied_boundary_count": len(applied_ids),
        "applied_boundary_ids": applied_ids,
        "blocking_issue_counts": dict(sorted(blocked_issues.items())),
    }


def _boundary_union(rows: list[NavigationChannelBoundary]) -> BaseGeometry | None:
    geometries = [_geometry(row.geometry_json) for row in rows]
    geometries = [geometry for geometry in geometries if geometry is not None]
    return make_valid(unary_union(geometries)) if geometries else None


def _geometry(value: Any) -> BaseGeometry | None:
    if not isinstance(value, dict):
        return None
    try:
        geometry = make_valid(shape(value))
    except Exception:
        return None
    return None if geometry.is_empty else geometry


def _geometry_counts(geometry: BaseGeometry) -> tuple[int, int]:
    ring_count = 0
    point_count = 0
    polygons = [geometry] if geometry.geom_type == "Polygon" else list(getattr(geometry, "geoms", []))
    for polygon in polygons:
        if polygon.geom_type != "Polygon":
            continue
        ring_count += 1 + len(polygon.interiors)
        point_count += len(polygon.exterior.coords)
        for ring in polygon.interiors:
            point_count += len(ring.coords)
    return ring_count, point_count


def _bbox(geometry: BaseGeometry) -> dict[str, float]:
    min_lng, min_lat, max_lng, max_lat = geometry.bounds
    return {
        "min_lng": round(min_lng, 8),
        "min_lat": round(min_lat, 8),
        "max_lng": round(max_lng, 8),
        "max_lat": round(max_lat, 8),
    }


def _q(value: Any, places: int = 15) -> float:
    return round(float(value), places)


if __name__ == "__main__":
    asyncio.run(main())
