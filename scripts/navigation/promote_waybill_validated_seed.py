"""Promote validated real-waybill gap segments into conservative seed patches.

The waybill route cache is reference-only evidence. This script promotes only
segments that have already passed water coverage validation and can be assigned
to exactly one existing navigation channel from local named water context.
Ambiguous, water-body-only, and missing-name segments stay as candidate evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from pyproj import Geod
from shapely.geometry import LineString, Point, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid
from sqlalchemy import or_, select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models import NavigationChannelCenterline
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.models.navigation import NavigationWaterArea, NavigationWaterBody
from app.modules.navigation.production_pipeline.boundary_quality_audit import audit_boundary_integrity


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VALIDATION_REPORT = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_seed_gap_validation_20260608.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_validated_seed_promotion_20260608.json"
DEFAULT_GEOJSON_OUTPUT = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_validated_seed_promotion_20260608.geojson"
GEOD = Geod(ellps="WGS84")
AUTO_STATUS = "AUTO_PROMOTE_EXISTING_CHANNEL_CENTERLINE"
SOURCE_TYPE_CODE = "SEED_CENTERLINE"


@dataclass(frozen=True)
class ChannelRef:
    id: int
    code: str
    name: str
    names: tuple[str, ...]
    technical_grade_current_code: str | None
    technical_grade_planned_code: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify and optionally promote validated waybill gap seed segments.")
    parser.add_argument("--validation-report", type=Path, default=DEFAULT_VALIDATION_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--geojson-output", type=Path, default=DEFAULT_GEOJSON_OUTPUT)
    parser.add_argument("--min-water-coverage", type=float, default=0.98)
    parser.add_argument("--boundary-patch-buffer-m", type=float, default=350.0)
    parser.add_argument("--water-query-buffer-m", type=float, default=180.0)
    parser.add_argument("--boundary-coverage-threshold", type=float, default=0.98)
    parser.add_argument("--allow-waybill-corridor-boundary-patch", action="store_true")
    parser.add_argument("--waybill-corridor-patch-max-length-km", type=float, default=5.0)
    parser.add_argument("--max-auto-segments", type=int, default=200)
    parser.add_argument("--apply", action="store_true", help="Write AUTO_PROMOTE items to seed centerlines and boundaries.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    source = json.loads(args.validation_report.read_text(encoding="utf-8"))
    rows = [
        item
        for item in source.get("items") or []
        if item.get("promote_allowed") and item.get("validation_status_code") == "READY_FOR_SEED_CANDIDATE"
    ]
    async with AsyncSessionLocal() as session:
        channels = await _load_channels(session)
        current_boundaries = await _load_current_boundaries(session)
        items = []
        features = []
        for row in rows:
            item = await _classify_row(
                session,
                row,
                channels=channels,
                current_boundaries=current_boundaries,
                min_water_coverage=float(args.min_water_coverage),
                boundary_patch_buffer_m=float(args.boundary_patch_buffer_m),
                water_query_buffer_m=float(args.water_query_buffer_m),
                boundary_coverage_threshold=float(args.boundary_coverage_threshold),
                allow_waybill_corridor_boundary_patch=bool(args.allow_waybill_corridor_boundary_patch),
                waybill_corridor_patch_max_length_km=float(args.waybill_corridor_patch_max_length_km),
            )
            items.append(item)
            features.extend(_features(item))
        auto_items = [item for item in items if item.get("promotion_status_code") == AUTO_STATUS]
        if int(args.max_auto_segments) >= 0:
            auto_items = auto_items[: int(args.max_auto_segments)]
        apply_summary = await _apply_promotions(session, auto_items) if args.apply else {"applied": False}

    report = {
        "report_version": "WAYBILL_VALIDATED_SEED_PROMOTION_V1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_validation_report": str(args.validation_report),
        "args": {
            "min_water_coverage": float(args.min_water_coverage),
            "boundary_patch_buffer_m": float(args.boundary_patch_buffer_m),
            "water_query_buffer_m": float(args.water_query_buffer_m),
            "boundary_coverage_threshold": float(args.boundary_coverage_threshold),
            "allow_waybill_corridor_boundary_patch": bool(args.allow_waybill_corridor_boundary_patch),
            "waybill_corridor_patch_max_length_km": float(args.waybill_corridor_patch_max_length_km),
            "max_auto_segments": int(args.max_auto_segments),
            "apply": bool(args.apply),
        },
        "summary": _summary(items),
        "apply_summary": apply_summary,
        "items": items,
        "guardrails": [
            "REAL_WAYBILL rows remain REFERENCE_ONLY and are never returned as VALID routes by this script.",
            "Only READY graph-gap segments with local named water coverage and one existing channel assignment are auto-promoted.",
            "Route-level water-system labels such as 苏州河 or 通榆河 are not used as segment names without local segment-level evidence.",
            "Boundary updates are generated by unioning the current boundary with local water geometry clipped around promoted lines.",
            "Waybill corridor buffer patches remain candidate evidence after graph 53 route-audit regression; they are not auto-promoted.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.geojson_output:
        args.geojson_output.parent.mkdir(parents=True, exist_ok=True)
        args.geojson_output.write_text(
            json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    print(json.dumps({"summary": report["summary"], "apply_summary": apply_summary}, ensure_ascii=False, indent=2))
    print(f"report_path={args.output}")
    if args.geojson_output:
        print(f"geojson_path={args.geojson_output}")


async def _load_channels(session) -> list[ChannelRef]:
    rows = list(
        (
            await session.execute(
                select(NavigationChannel)
                .where(NavigationChannel.is_enabled.is_(True))
                .order_by(NavigationChannel.id)
            )
        ).scalars()
    )
    refs: list[ChannelRef] = []
    for row in rows:
        names: list[str] = []
        for value in (row.channel_name, row.official_name, row.display_name):
            if value:
                names.append(str(value))
        for value in row.alias_names or []:
            if value:
                names.append(str(value))
        refs.append(
            ChannelRef(
                id=int(row.id),
                code=row.channel_code,
                name=row.channel_name,
                names=tuple(dict.fromkeys(names)),
                technical_grade_current_code=row.technical_grade_current_code,
                technical_grade_planned_code=row.technical_grade_planned_code,
            )
        )
    return refs


async def _load_current_boundaries(session) -> dict[int, list[NavigationChannelBoundary]]:
    rows = list(
        (
            await session.execute(
                select(NavigationChannelBoundary)
                .where(
                    NavigationChannelBoundary.is_current.is_(True),
                    NavigationChannelBoundary.geometry_status_code == "AVAILABLE",
                    NavigationChannelBoundary.geometry_json.is_not(None),
                )
                .order_by(NavigationChannelBoundary.channel_id, NavigationChannelBoundary.id)
            )
        ).scalars()
    )
    output: dict[int, list[NavigationChannelBoundary]] = defaultdict(list)
    for row in rows:
        output[int(row.channel_id)].append(row)
    return output


async def _classify_row(
    session,
    row: dict[str, Any],
    *,
    channels: list[ChannelRef],
    current_boundaries: dict[int, list[NavigationChannelBoundary]],
    min_water_coverage: float,
    boundary_patch_buffer_m: float,
    water_query_buffer_m: float,
    boundary_coverage_threshold: float,
    allow_waybill_corridor_boundary_patch: bool,
    waybill_corridor_patch_max_length_km: float,
) -> dict[str, Any]:
    line = _line(row.get("geometry_json"))
    base = _base_item(row)
    if line is None:
        return {**base, "promotion_status_code": "BLOCKED_INVALID_SEGMENT_GEOMETRY"}
    coverage = float(row.get("local_water_coverage_ratio") or 0.0)
    context_names = _context_names(row)
    channel_matches = _channel_matches(row, channels, context_names)
    selected_match = _selected_match(channel_matches)
    patch_geometry, patch_source = await _water_patch_geometry(
        session,
        line,
        context_names=context_names,
        patch_buffer_m=boundary_patch_buffer_m,
        query_buffer_m=water_query_buffer_m,
    )
    patch_coverage = _coverage_ratio(line, patch_geometry, tolerance_m=20.0)
    patch_fallback_reason = None
    corridor_patch_used = False

    status = "NEEDS_SEGMENT_NAME_EVIDENCE"
    selected_channel: dict[str, Any] | None = None
    if coverage < min_water_coverage:
        status = "BLOCKED_LOW_WATER_COVERAGE"
    elif not context_names:
        status = "NEEDS_SEGMENT_NAME_EVIDENCE"
    elif _has_multi_context_channel_match(channel_matches):
        status = "AMBIGUOUS_EXISTING_CHANNEL_ASSIGNMENT"
    elif selected_match is None and channel_matches:
        status = "AMBIGUOUS_EXISTING_CHANNEL_ASSIGNMENT"
    elif selected_match is not None:
        channel = selected_match["channel"]
        selected_channel = _channel_payload(channel)
        existing_blocked = await _existing_blocked_centerline(session, channel, row)
        if existing_blocked is not None:
            status = "BLOCKED_PREVIOUS_PROMOTION_FAILED"
        elif (
            patch_geometry is not None
            and patch_coverage < boundary_coverage_threshold
            and allow_waybill_corridor_boundary_patch
            and row.get("segment_role_code") == "GRAPH_GAP_SEGMENT"
            and coverage >= min_water_coverage
            and float(row.get("length_km") or 0.0) <= waybill_corridor_patch_max_length_km
        ):
            patch_geometry = _waybill_corridor_patch(
                line,
                base_geometry=patch_geometry,
                patch_buffer_m=boundary_patch_buffer_m,
            )
            patch_coverage = _coverage_ratio(line, patch_geometry, tolerance_m=20.0)
            patch_source = "WAYBILL_CORRIDOR_BUFFER_WITH_LOCAL_NAMED_WATER_TOLERANCE"
            patch_fallback_reason = "LOCAL_NAMED_WATER_COVERAGE_PASSED_BUT_EXACT_POLYGON_PATCH_UNDER_COVERED"
            corridor_patch_used = True
            if patch_geometry is None or patch_coverage < boundary_coverage_threshold:
                status = "BLOCKED_BOUNDARY_PATCH_NOT_WATER_BACKED"
            else:
                status = "CANDIDATE_WAYBILL_CORRIDOR_BOUNDARY_PATCH_NEEDS_GRAPH_AUDIT"
    elif await _has_local_named_water(session, context_names):
        status = "CREATE_CHANNEL_FROM_LOCAL_WATER_BODY_CANDIDATE"

    boundary_coverage = None
    boundary_needs_extension = None
    if selected_channel:
        boundary_geometry = _boundary_union(current_boundaries.get(int(selected_channel["id"])) or [])
        boundary_coverage = _coverage_ratio(line, boundary_geometry, tolerance_m=20.0)
        boundary_needs_extension = boundary_coverage < boundary_coverage_threshold

    return {
        **base,
        "promotion_status_code": status,
        "selected_channel": selected_channel,
        "channel_match_candidates": [
            {
                **_channel_payload(match["channel"]),
                "match_score": match["score"],
                "matched_context_names": match["matched_context_names"],
                "action_matched": match["action_matched"],
            }
            for match in channel_matches
        ],
        "segment_context_names": context_names,
        "local_water_coverage_ratio": round(coverage, 6),
        "boundary_coverage_ratio": round(boundary_coverage, 6) if boundary_coverage is not None else None,
        "boundary_needs_extension": boundary_needs_extension,
        "boundary_patch_source_code": patch_source,
        "boundary_patch_fallback_reason": patch_fallback_reason,
        "corridor_patch_used": corridor_patch_used,
        "boundary_patch_coverage_ratio": round(patch_coverage, 6),
        "boundary_patch_geometry_json": mapping(patch_geometry) if patch_geometry is not None else None,
        "geometry_json": mapping(line),
        "source_trace": {
            "source": "promote_waybill_validated_seed",
            "validation_status_code": row.get("validation_status_code"),
            "blocking_issue_codes": row.get("blocking_issue_codes") or [],
            "matched_water_context": row.get("matched_water_context"),
            "water_system_actions": row.get("water_system_actions") or [],
        },
    }


def _base_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_code": row.get("target_code"),
        "target_name": row.get("target_name"),
        "segment_role_code": row.get("segment_role_code"),
        "segment_no": row.get("segment_no"),
        "length_km": row.get("length_km"),
        "waybill_code": row.get("waybill_code"),
        "route_code": row.get("route_code"),
        "origin_code": row.get("origin_code"),
        "destination_code": row.get("destination_code"),
        "trajectory_cache_id": row.get("trajectory_cache_id"),
        "max_step_km": row.get("max_step_km"),
        "line_is_simple": row.get("line_is_simple"),
    }


async def _existing_blocked_centerline(
    session,
    channel: ChannelRef,
    row: dict[str, Any],
) -> NavigationChannelCenterline | None:
    code = _centerline_code_from_ref(channel, row)
    existing = await session.scalar(
        select(NavigationChannelCenterline)
        .where(NavigationChannelCenterline.centerline_code == code)
        .order_by(NavigationChannelCenterline.id.desc())
        .limit(1)
    )
    if (
        existing is not None
        and existing.is_current is False
        and str(existing.review_status_code or "") == "NEED_REVIEW"
        and str(existing.quality_code or "") == "NEED_REVIEW"
    ):
        return existing
    return None


def _centerline_code_from_ref(channel: ChannelRef, row: dict[str, Any]) -> str:
    target = _clean_code(str(row.get("target_code") or "TARGET"), 28)
    segment_no = _clean_code(str(row.get("segment_no") or "SEG"), 8)
    channel_code = _clean_code(channel.code, 32)
    return f"WB-SEED-{channel_code}-{target}-{segment_no}"[:96]


def _context_names(row: dict[str, Any]) -> list[str]:
    context = row.get("matched_water_context") if isinstance(row.get("matched_water_context"), dict) else {}
    names: list[str] = []
    for key in ("named_water_areas", "named_water_bodies"):
        for item in context.get(key) or []:
            name = str((item or [None])[0] or "").strip()
            if _usable_name(name):
                names.append(name)
    return list(dict.fromkeys(names))


def _channel_matches(row: dict[str, Any], channels: list[ChannelRef], context_names: list[str]) -> list[dict[str, Any]]:
    action_ids: dict[int, str] = {}
    for action in row.get("water_system_actions") or []:
        matched = action.get("matched_channel") if isinstance(action, dict) else None
        if not isinstance(matched, dict):
            continue
        ref_id = _int_or_none(matched.get("ref_id"))
        action_name = str(action.get("water_system_name") or "")
        if ref_id is not None and _action_matches_context(action_name, context_names):
            action_ids[ref_id] = action_name
    matches = []
    for channel in channels:
        score = 0
        matched_context_names: list[str] = []
        for context_name in context_names:
            if any(_name_matches(context_name, channel_name) for channel_name in channel.names):
                matched_context_names.append(context_name)
                score += 100
        action_matched = False
        if channel.id in action_ids:
            matched_context_names.append(action_ids[channel.id])
            score += 75
            action_matched = True
        if score > 0:
            matches.append(
                {
                    "channel": channel,
                    "score": score,
                    "matched_context_names": list(dict.fromkeys(matched_context_names)),
                    "action_matched": action_matched,
                }
            )
    matches.sort(key=lambda item: (-int(item["score"]), item["channel"].id))
    return matches


def _has_multi_context_channel_match(matches: list[dict[str, Any]]) -> bool:
    context_names = {
        name
        for match in matches
        for name in match.get("matched_context_names") or []
        if not _looks_like_route_level_action_name(name)
    }
    return len(context_names) > 1


def _selected_match(matches: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    action_matches = [match for match in matches if match.get("action_matched")]
    if len(action_matches) == 1 and int(action_matches[0].get("score") or 0) > int(matches[1].get("score") or 0):
        return action_matches[0]
    return None


async def _has_local_named_water(session, names: list[str]) -> bool:
    for name in names:
        if await session.scalar(
            select(NavigationWaterBody.id)
            .where(
                NavigationWaterBody.is_enabled.is_(True),
                or_(
                    NavigationWaterBody.water_body_name == name,
                    NavigationWaterBody.display_name == name,
                    NavigationWaterBody.production_name == name,
                ),
            )
            .limit(1)
        ):
            return True
        if await session.scalar(
            select(NavigationWaterArea.id)
            .where(NavigationWaterArea.is_enabled.is_(True), NavigationWaterArea.water_name == name)
            .limit(1)
        ):
            return True
    return False


async def _water_patch_geometry(
    session,
    line: LineString,
    *,
    context_names: list[str],
    patch_buffer_m: float,
    query_buffer_m: float,
) -> tuple[BaseGeometry | None, str]:
    if not context_names:
        return None, "NO_LOCAL_SEGMENT_NAME"
    minx, miny, maxx, maxy = line.bounds
    margin = _degree_buffer(max(patch_buffer_m, query_buffer_m)) + 0.01
    line_query = line.buffer(_degree_buffer(query_buffer_m), cap_style=2, join_style=2)
    line_patch = line.buffer(_degree_buffer(patch_buffer_m), cap_style=2, join_style=2)
    area_rows = list(
        (
            await session.execute(
                select(NavigationWaterArea).where(
                    NavigationWaterArea.is_enabled.is_(True),
                    NavigationWaterArea.geometry_json.is_not(None),
                    NavigationWaterArea.bbox_min_lng <= maxx + margin,
                    NavigationWaterArea.bbox_max_lng >= minx - margin,
                    NavigationWaterArea.bbox_min_lat <= maxy + margin,
                    NavigationWaterArea.bbox_max_lat >= miny - margin,
                )
            )
        ).scalars()
    )
    body_rows = list(
        (
            await session.execute(
                select(NavigationWaterBody).where(
                    NavigationWaterBody.is_enabled.is_(True),
                    NavigationWaterBody.geometry_wgs84_json.is_not(None),
                    NavigationWaterBody.bbox_min_lng <= maxx + margin,
                    NavigationWaterBody.bbox_max_lng >= minx - margin,
                    NavigationWaterBody.bbox_min_lat <= maxy + margin,
                    NavigationWaterBody.bbox_max_lat >= miny - margin,
                )
            )
        ).scalars()
    )
    geometries: list[BaseGeometry] = []
    for row in area_rows:
        name = _usable_name(row.water_name)
        if not name or not any(_name_matches(name, context_name) for context_name in context_names):
            continue
        geometry = _geometry(row.geometry_json)
        if geometry is not None and geometry.intersects(line_query):
            clipped = make_valid(geometry.intersection(line_patch))
            if not clipped.is_empty:
                geometries.append(clipped)
    for row in body_rows:
        name = _usable_name(row.production_name or row.display_name or row.water_body_name)
        if not name or not any(_name_matches(name, context_name) for context_name in context_names):
            continue
        geometry = _geometry(row.geometry_wgs84_json)
        if geometry is not None and geometry.intersects(line_query):
            clipped = make_valid(geometry.intersection(line_patch))
            if not clipped.is_empty:
                geometries.append(clipped)
    if geometries:
        return make_valid(unary_union(geometries)), "LOCAL_NAMED_WATER_GEOMETRY_CLIPPED"
    return make_valid(line_patch), "LINE_BUFFER_FALLBACK"


def _waybill_corridor_patch(
    line: LineString,
    *,
    base_geometry: BaseGeometry,
    patch_buffer_m: float,
) -> BaseGeometry:
    corridor = line.buffer(_degree_buffer(patch_buffer_m), cap_style=2, join_style=2)
    return make_valid(unary_union([base_geometry, corridor]))


async def _apply_promotions(session, items: list[dict[str, Any]]) -> dict[str, Any]:
    by_channel: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        selected = item.get("selected_channel") if isinstance(item.get("selected_channel"), dict) else None
        if selected and item.get("boundary_patch_geometry_json"):
            by_channel[int(selected["id"])].append(item)
    if not by_channel:
        return {"applied": True, "promoted_centerline_count": 0, "promoted_boundary_count": 0}

    channels = {
        int(row.id): row
        for row in (
            await session.execute(select(NavigationChannel).where(NavigationChannel.id.in_(sorted(by_channel))))
        ).scalars()
    }
    promoted_centerline_ids: list[int] = []
    promoted_boundary_ids: list[int] = []
    skipped_channels: list[dict[str, Any]] = []
    for channel_id, channel_items in sorted(by_channel.items()):
        channel = channels.get(channel_id)
        if channel is None:
            skipped_channels.append({"channel_id": channel_id, "skip_reason": "CHANNEL_NOT_FOUND"})
            continue
        current_boundaries = list(
            (
                await session.execute(
                    select(NavigationChannelBoundary).where(
                        NavigationChannelBoundary.channel_id == channel_id,
                        NavigationChannelBoundary.is_current.is_(True),
                        NavigationChannelBoundary.geometry_status_code == "AVAILABLE",
                    )
                )
            ).scalars()
        )
        existing_geometries = [_geometry(row.geometry_json) for row in current_boundaries]
        patch_geometries = [_geometry(item.get("boundary_patch_geometry_json")) for item in channel_items]
        centerline_geometries = [_line(item.get("geometry_json")) for item in channel_items]
        needs_boundary_update = any(bool(item.get("boundary_needs_extension")) for item in channel_items) or not current_boundaries
        union_inputs = [
            geometry
            for geometry in ([*existing_geometries, *patch_geometries] if needs_boundary_update else existing_geometries)
            if geometry is not None
        ]
        if not union_inputs:
            skipped_channels.append({"channel_id": channel_id, "skip_reason": "BOUNDARY_PATCH_MISSING"})
            continue
        boundary_geometry = make_valid(unary_union(union_inputs))
        source_trace = {
            "source": "promote_waybill_validated_seed",
            "waybill_segment_count": len(channel_items),
            "target_codes": sorted({str(item.get("target_code") or "") for item in channel_items}),
            "waybill_codes": sorted({str(item.get("waybill_code") or "") for item in channel_items if item.get("waybill_code")}),
            "previous_boundary_ids": [int(row.id) for row in current_boundaries],
            "boundary_patch_source_counts": dict(Counter(item.get("boundary_patch_source_code") for item in channel_items)),
            "basemap_verification": {
                "status_code": "AUTO_VERIFIED_BY_LOCAL_WATER_GEOMETRY_AND_REAL_WAYBILL_TRACK",
                "source_code": "LOCAL_REVIER_WATER_GEOMETRY_INTERSECTED_REAL_WAYBILL",
            },
            "generated_at": datetime.now(UTC).isoformat(),
        }
        audit = audit_boundary_integrity(
            channel={
                "technical_grade_current_code": channel.technical_grade_current_code,
                "technical_grade_planned_code": channel.technical_grade_planned_code,
            },
            boundary={
                "geometry_status_code": "AVAILABLE",
                "geometry_json": mapping(boundary_geometry),
                "coverage_policy_code": "WAYBILL_VALIDATED_WATER_CORRIDOR",
                "source_trace_json": source_trace,
            },
            centerline_geometries=[mapping(line) for line in centerline_geometries if line is not None],
            require_centerline=True,
        )
        if audit.get("blocking_issue_codes"):
            skipped_channels.append(
                {
                    "channel_id": channel_id,
                    "channel_code": channel.channel_code,
                    "skip_reason": "BOUNDARY_AUDIT_BLOCKED",
                    "blocking_issue_codes": audit.get("blocking_issue_codes"),
                }
            )
            continue

        if needs_boundary_update:
            for row in current_boundaries:
                row.is_current = False
            centroid = boundary_geometry.centroid
            min_lng, min_lat, max_lng, max_lat = boundary_geometry.bounds
            ring_count, point_count = _geometry_counts(boundary_geometry)
            boundary = NavigationChannelBoundary(
                channel_id=channel_id,
                geometry_json=mapping(boundary_geometry),
                center_longitude=_q(centroid.x),
                center_latitude=_q(centroid.y),
                display_center_longitude=_q(centroid.x),
                display_center_latitude=_q(centroid.y),
                bbox_min_lng=_q(min_lng),
                bbox_min_lat=_q(min_lat),
                bbox_max_lng=_q(max_lng),
                bbox_max_lat=_q(max_lat),
                source_shape_length_degree=_q(boundary_geometry.length, 18),
                source_shape_area_degree=_q(boundary_geometry.area, 18),
                ring_count=ring_count,
                point_count=point_count,
                geometry_status_code="AVAILABLE",
                boundary_quality_code="AUTO_PUBLISHED",
                connectivity_status_code="CONNECTED" if boundary_geometry.geom_type == "Polygon" else "CONNECTED_WITH_BRIDGES",
                repair_status_code="AUTO_REPAIRED",
                coverage_policy_code="WAYBILL_VALIDATED_WATER_CORRIDOR",
                geometry_coordinate_system_code="WGS84",
                boundary_coordinate_system_code="WGS84",
                source_trace_json={**source_trace, "boundary_integrity_audit": audit},
                is_current=True,
                imported_at=datetime.now(UTC).replace(tzinfo=None),
            )
            session.add(boundary)
            await session.flush()
            boundary_id = int(boundary.id)
            promoted_boundary_ids.append(boundary_id)
        else:
            boundary_id = int(max(current_boundaries, key=lambda row: int(row.id)).id)

        for item in channel_items:
            line = _line(item.get("geometry_json"))
            if line is None:
                continue
            code = _centerline_code(channel, item)
            min_lng, min_lat, max_lng, max_lat = line.bounds
            source_trace = {
                **(item.get("source_trace") if isinstance(item.get("source_trace"), dict) else {}),
                "source": "promote_waybill_validated_seed",
                "source_validation_report": str(DEFAULT_VALIDATION_REPORT),
                "selected_channel": item.get("selected_channel"),
                "boundary_id": boundary_id,
                "boundary_patch_source_code": item.get("boundary_patch_source_code"),
                "generated_at": datetime.now(UTC).isoformat(),
            }
            payload = {
                "channel_id": channel_id,
                "segment_id": None,
                "centerline_code": code,
                "centerline_name": f"{channel.channel_name} 运单验证补段 {item.get('target_code')}-{item.get('segment_no')}",
                "geometry_json": mapping(line),
                "source_type_code": SOURCE_TYPE_CODE,
                "direction_code": "BIDIRECTIONAL",
                "is_main_line": False,
                "confidence_score": 88,
                "quality_code": "READY_WITH_WARNING",
                "review_status_code": "PUBLISHED",
                "version_no": 1,
                "parent_centerline_id": None,
                "is_current": True,
                "source_trace_json": source_trace,
                "approved_by": None,
                "approved_at": datetime.now(UTC).replace(tzinfo=None),
                "bbox_min_lng": _q(min_lng),
                "bbox_min_lat": _q(min_lat),
                "bbox_max_lng": _q(max_lng),
                "bbox_max_lat": _q(max_lat),
            }
            existing = await session.scalar(
                select(NavigationChannelCenterline).where(NavigationChannelCenterline.centerline_code == code)
            )
            if existing is None:
                centerline = NavigationChannelCenterline(**payload)
                session.add(centerline)
                await session.flush()
                promoted_centerline_ids.append(int(centerline.id))
            else:
                for key, value in payload.items():
                    setattr(existing, key, value)
                await session.flush()
                promoted_centerline_ids.append(int(existing.id))
    await session.commit()
    return {
        "applied": True,
        "promoted_centerline_count": len(promoted_centerline_ids),
        "promoted_centerline_ids": promoted_centerline_ids,
        "promoted_boundary_count": len(promoted_boundary_ids),
        "promoted_boundary_ids": promoted_boundary_ids,
        "skipped_channels": skipped_channels,
    }


def _centerline_code(channel: NavigationChannel, item: dict[str, Any]) -> str:
    target = _clean_code(str(item.get("target_code") or "TARGET"), 28)
    segment_no = _clean_code(str(item.get("segment_no") or "SEG"), 8)
    channel_code = _clean_code(channel.channel_code, 32)
    return f"WB-SEED-{channel_code}-{target}-{segment_no}"[:96]


def _summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(item.get("promotion_status_code") for item in items)
    channel_counts = Counter(
        (item.get("selected_channel") or {}).get("code")
        for item in items
        if item.get("promotion_status_code") == AUTO_STATUS and item.get("selected_channel")
    )
    auto_items = [item for item in items if item.get("promotion_status_code") == AUTO_STATUS]
    return {
        "validated_segment_count": len(items),
        "promotion_status_counts": dict(sorted(status_counts.items())),
        "auto_promote_count": len(auto_items),
        "auto_promote_length_km": round(sum(float(item.get("length_km") or 0) for item in auto_items), 3),
        "auto_promote_channel_counts": dict(sorted(channel_counts.items())),
        "auto_boundary_extension_count": sum(1 for item in auto_items if item.get("boundary_needs_extension")),
        "blocked_or_candidate_count": len(items) - len(auto_items),
        "blocked_or_candidate_length_km": round(
            sum(float(item.get("length_km") or 0) for item in items if item.get("promotion_status_code") != AUTO_STATUS),
            3,
        ),
    }


def _features(item: dict[str, Any]) -> list[dict[str, Any]]:
    geometry = item.get("geometry_json")
    if not isinstance(geometry, dict):
        return []
    props = {
        "target_code": item.get("target_code"),
        "target_name": item.get("target_name"),
        "segment_no": item.get("segment_no"),
        "length_km": item.get("length_km"),
        "promotion_status_code": item.get("promotion_status_code"),
        "selected_channel_code": ((item.get("selected_channel") or {}).get("code") if item.get("selected_channel") else None),
        "context_names": ",".join(item.get("segment_context_names") or []),
        "boundary_needs_extension": item.get("boundary_needs_extension"),
    }
    features = [{"type": "Feature", "properties": {**props, "feature_role": "centerline_segment"}, "geometry": geometry}]
    patch_geometry = item.get("boundary_patch_geometry_json")
    if isinstance(patch_geometry, dict):
        features.append({"type": "Feature", "properties": {**props, "feature_role": "boundary_patch"}, "geometry": patch_geometry})
    return features


def _boundary_union(rows: list[NavigationChannelBoundary]) -> BaseGeometry | None:
    geometries = [_geometry(row.geometry_json) for row in rows]
    geometries = [geometry for geometry in geometries if geometry is not None]
    return make_valid(unary_union(geometries)) if geometries else None


def _coverage_ratio(line: LineString, geometry: BaseGeometry | None, *, tolerance_m: float) -> float:
    if geometry is None or geometry.is_empty:
        return 0.0
    try:
        covered = line.intersection(geometry.buffer(_degree_buffer(tolerance_m))).length
    except Exception:
        return 0.0
    return max(0.0, min(1.0, covered / max(line.length, 1e-12)))


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


def _channel_payload(channel: ChannelRef) -> dict[str, Any]:
    return {
        "id": channel.id,
        "code": channel.code,
        "name": channel.name,
        "technical_grade_current_code": channel.technical_grade_current_code,
        "technical_grade_planned_code": channel.technical_grade_planned_code,
    }


def _usable_name(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text.startswith("未命名"):
        return None
    return text


def _action_matches_context(action_name: str, context_names: list[str]) -> bool:
    if not context_names:
        return False
    return any(_name_matches(action_name, context_name) for context_name in context_names)


def _name_matches(left: str, right: str) -> bool:
    left_norm = _normalize_name(left)
    right_norm = _normalize_name(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    if _reservoir_name_conflict(left_norm, right_norm):
        return False
    if len(left_norm) >= 2 and left_norm in right_norm:
        return True
    if len(right_norm) >= 2 and right_norm in left_norm:
        return True
    return False


def _reservoir_name_conflict(left_norm: str, right_norm: str) -> bool:
    return ("水库" in left_norm) != ("水库" in right_norm)


def _looks_like_route_level_action_name(value: str) -> bool:
    text = str(value or "")
    return bool(re.search(r"[（(].*?[)）]", text) or "干流" in text or "大运河" in text)


def _normalize_name(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[（(].*?[)）]", "", text)
    for token in ("航道", "干线", "干流", "水系", "河道", "主线"):
        text = text.replace(token, "")
    text = text.replace("大运河", "运河")
    text = text.replace("运河", "河")
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", text)


def _degree_buffer(meters: float) -> float:
    return float(meters) / 111_320.0


def _q(value: Any, digits: int = 15) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _clean_code(value: str, max_len: int = 64) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_-]+", "-", value).strip("-")
    return (cleaned or "WB")[:max_len]


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _line_length_km(line: LineString) -> float:
    coords = list(line.coords)
    if len(coords) < 2:
        return 0.0
    return sum(_haversine_km(start, end) for start, end in zip(coords[:-1], coords[1:]))


def _haversine_km(left: Iterable[float], right: Iterable[float]) -> float:
    lng1, lat1 = float(left[0]), float(left[1])
    lng2, lat2 = float(right[0]), float(right[1])
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


if __name__ == "__main__":
    asyncio.run(main())
