"""Self-heal navigation seed data without deleting existing production rows.

The script promotes verified local water-body geometry into current channel
boundaries, generates/publishes centerlines from those boundaries, and can build
an updated graph. It is intentionally non-destructive: older rows are kept but
marked non-current where a better auto-generated row is promoted.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable, Sequence

from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, unary_union
from shapely.validation import make_valid
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import (
    NavigationCenterlineSegment,
    NavigationChannelCenterline,
    NavigationChannelWaterBodyMatch,
    NavigationGraphVersion,
    NavigationWaterBody,
)
from app.models.address import NavigationChannel, NavigationChannelBoundary, NavigationChannelSegment
from app.modules.navigation.production_pipeline.boundary_quality_audit import audit_boundary_integrity
from app.modules.navigation.schemas import NavigationCenterlineSegmentGenerateRequest, NavigationCenterlineSegmentPublishRequest
from app.modules.navigation.services.centerline_segments import NavigationCenterlineSegmentService
from app.modules.navigation.services.graph_build_service import build_graph_from_centerlines


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "runtime/navigation-production/reports/navigation_seed_self_heal_report_20260604.json"
DEFAULT_ALIAS_CONFIG = PROJECT_ROOT / "scripts/seed_data/navigation/navigation_channel_aliases.json"
AUTO_BOUNDARY_POLICY = "AUTO_WATER_BODY_UNION"
AUTO_MATCH_BATCH = "AUTO-WATER-BODY-MAP-LABEL-SELF-HEAL"
AUTO_NAME_SOURCE = "MAP_LABEL_OR_CHANNEL_INFERRED"
GEOD_SCALE = Decimal("0.000000000000001")
MEASURE_SCALE = Decimal("0.000000000000000001")
PRODUCTION_BODY_ROLES = {"PRIMARY_HIERARCHY", "RX_FILL_GAP"}
PLANNING_LEVEL_GRADE = {
    "NATIONAL_CORE": "III",
    "NATIONAL_NETWORK": "III",
    "NATIONAL_IMPORTANT": "IV",
    "PROVINCIAL_HIGH_GRADE": "IV",
    "REGIONAL_IMPORTANT": "V",
    "PLANNED_GAP": "VI",
    "REVIEW": "VI",
}
WATER_SUFFIXES = (
    "航运干线",
    "高等级航道网",
    "相关水域",
    "航道",
    "通道",
    "干线",
    "水道",
    "运河",
    "河道",
    "河",
    "江",
    "溪",
    "港",
    "线",
)


@dataclass(slots=True)
class SelfHealReport:
    generated_at: str
    dry_run: bool
    channel_count: int
    water_body_auto_name_count: int = 0
    water_body_match_created_count: int = 0
    technical_grade_derived_count: int = 0
    boundary_promoted_count: int = 0
    boundary_blocked_count: int = 0
    centerline_generated_count: int = 0
    centerline_published_count: int = 0
    centerline_blocked_count: int = 0
    graph_build_status: str | None = None
    graph_version_id: int | None = None
    graph_edge_count: int | None = None
    issue_counts: dict[str, int] = field(default_factory=dict)
    channels: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Self-heal navigation seed boundaries, centerlines, and graph.")
    parser.add_argument("--channel-code", action="append", dest="channel_codes", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-boundaries", action="store_true")
    parser.add_argument("--skip-centerlines", action="store_true")
    parser.add_argument("--build-graph", action="store_true")
    parser.add_argument("--activate-graph", action="store_true")
    parser.add_argument("--graph-scope-code", default="REVIER_PRODUCTION_SELF_HEAL")
    parser.add_argument("--required-boundary-trust", action="append", default=None)
    parser.add_argument("--bridge-fragment-gaps", action="store_true")
    parser.add_argument("--max-fragment-bridge-gap-km", type=float, default=10.0)
    parser.add_argument("--fragment-bridge-buffer-degree", type=float, default=0.0015)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--alias-config", type=Path, default=DEFAULT_ALIAS_CONFIG)
    return parser.parse_args()


def _norm(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    for token in (" ", "\t", "\n", "—", "-", "_", "（", "）", "(", ")", "/", "·"):
        text = text.replace(token, "")
    return text or None


def _strip_suffixes(value: str) -> str:
    text = value
    changed = True
    while changed:
        changed = False
        for suffix in WATER_SUFFIXES:
            if text.endswith(suffix) and len(text) > len(suffix) + 1:
                text = text[: -len(suffix)]
                changed = True
    return text


def _display_terms(channel: NavigationChannel, alias_config: dict[str, Any]) -> list[str]:
    configured = alias_config.get("channels", {}).get(channel.channel_code, {})
    raw_values: list[Any] = [
        channel.channel_name,
        channel.official_name,
        channel.display_name,
        *(channel.alias_names or []),
        *(configured.get("aliases") or []),
        *(configured.get("water_names") or []),
    ]
    output: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        text = str(raw or "").strip()
        if not text:
            continue
        variants = [text, _strip_suffixes(text)]
        for variant in variants:
            normalized = _norm(variant)
            if normalized and normalized not in seen:
                seen.add(normalized)
                output.append(variant)
    return output


def _term_set(channel: NavigationChannel, alias_config: dict[str, Any]) -> set[str]:
    terms = {_norm(item) for item in _display_terms(channel, alias_config)}
    return {item for item in terms if item}


def _score_name(channel_terms: set[str], body: NavigationWaterBody) -> tuple[str, str, int] | None:
    body_terms = [_norm(body.production_name), _norm(body.display_name), _norm(body.water_body_name), _norm(body.normalized_water_name)]
    body_terms = [item for item in body_terms if item]
    for body_term in body_terms:
        if body_term in channel_terms:
            return "EXACT_OR_ALIAS_NAME", body_term, 100
    for channel_term in sorted(channel_terms, key=len, reverse=True):
        for body_term in body_terms:
            if len(channel_term) >= 3 and (channel_term in body_term or body_term in channel_term):
                return "CONTAINS_NAME", channel_term, 80
    return None


def _geometry(value: Any) -> BaseGeometry | None:
    if not isinstance(value, dict):
        return None
    try:
        geometry = make_valid(shape(value))
    except Exception:
        return None
    return None if geometry.is_empty else geometry


def _guide_lines(channel_segments: Sequence[NavigationChannelSegment]) -> list[LineString]:
    lines: list[LineString] = []
    for row in channel_segments:
        geometry = _geometry(row.guide_geometry_json)
        if geometry is None:
            continue
        if isinstance(geometry, LineString):
            lines.append(geometry)
        elif isinstance(geometry, MultiLineString):
            lines.extend([item for item in geometry.geoms if len(item.coords) >= 2])
    return lines


def _guide_hit_score(body_geometry: BaseGeometry, guide_lines: list[LineString]) -> tuple[float, float]:
    if not guide_lines:
        return 0.0, 0.0
    covered = 0.0
    total = 0.0
    prepared = body_geometry.buffer(0.001)
    for line in guide_lines:
        length = max(float(line.length), 0.0)
        if length <= 0:
            continue
        total += length
        try:
            covered += float(line.intersection(prepared).length)
        except Exception:
            pass
    ratio = covered / total if total > 0 else 0.0
    nearest = min((_distance_approx_m(body_geometry, line) for line in guide_lines), default=0.0)
    return ratio, nearest


def _distance_approx_m(left: BaseGeometry, right: BaseGeometry) -> float:
    try:
        p1, p2 = nearest_points(left, right)
        return (((float(p1.x) - float(p2.x)) * 111_320) ** 2 + ((float(p1.y) - float(p2.y)) * 110_540) ** 2) ** 0.5
    except Exception:
        return 999_999.0


def _candidate_name(channel: NavigationChannel, alias_config: dict[str, Any]) -> str:
    terms = _display_terms(channel, alias_config)
    if not terms:
        return channel.channel_name
    candidate = terms[0]
    stripped = _strip_suffixes(candidate)
    return stripped if len(stripped) >= 2 else candidate


def _derived_grade(channel: NavigationChannel) -> str:
    return PLANNING_LEVEL_GRADE.get(str(channel.planning_level_code or ""), "VI")


def _ensure_technical_grade(channel: NavigationChannel, *, dry_run: bool) -> bool:
    if channel.technical_grade_current_code or channel.technical_grade_planned_code:
        return False
    grade = _derived_grade(channel)
    if not dry_run:
        channel.technical_grade_planned_code = grade
        audit = dict(channel.source_audit_summary or {})
        audit["technical_grade_auto_derivation"] = {
            "source": "self_heal_navigation_seed",
            "planning_level_code": channel.planning_level_code,
            "derived_planned_grade_code": grade,
            "rule_code": "CONSERVATIVE_PLANNING_LEVEL_TO_NAVIGATION_GRADE",
            "derived_at": datetime.now(UTC).isoformat(),
        }
        channel.source_audit_summary = audit
    return True


def _q(value: Any, scale: Decimal = GEOD_SCALE) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(scale, rounding=ROUND_HALF_UP)


def _polygon_parts(geometry: BaseGeometry) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    return []


def _geometry_counts(geometry: BaseGeometry) -> tuple[int, int]:
    ring_count = 0
    point_count = 0
    for polygon in _polygon_parts(geometry):
        rings = [polygon.exterior, *list(polygon.interiors)]
        ring_count += len(rings)
        point_count += sum(len(ring.coords) for ring in rings)
    return ring_count, point_count


def _bridge_fragmented_water(
    geometry: BaseGeometry,
    guide_lines: list[LineString],
    *,
    enable_nearest_fragment_bridge: bool,
    max_fragment_bridge_gap_m: float,
    fragment_bridge_buffer_degree: float,
) -> tuple[BaseGeometry, list[dict[str, Any]]]:
    parts = _polygon_parts(geometry)
    if len(parts) <= 1:
        return geometry, []
    bridges = []
    bridge_trace: list[dict[str, Any]] = []
    for line in guide_lines:
        if line.is_empty or len(line.coords) < 2:
            continue
        intersections = line.intersection(geometry.buffer(0.001))
        if intersections.is_empty:
            continue
        bridges.append(line.buffer(fragment_bridge_buffer_degree, cap_style=2, join_style=2))
        bridge_trace.append(
            {
                "bridge_type": "GUIDE_LINE_FRAGMENT_BRIDGE",
                "line_bounds": [round(value, 6) for value in line.bounds],
                "buffer_degree": fragment_bridge_buffer_degree,
            }
        )
    if not bridges and enable_nearest_fragment_bridge:
        working = geometry
        for _ in range(max(0, len(parts) - 1)):
            current_parts = _polygon_parts(working)
            if len(current_parts) <= 1:
                break
            nearest: tuple[float, int, int, Any, Any] | None = None
            for left_idx, left in enumerate(current_parts):
                for right_idx, right in enumerate(current_parts):
                    if right_idx <= left_idx:
                        continue
                    try:
                        left_point, right_point = nearest_points(left, right)
                        gap_m = _distance_approx_m(left, right)
                    except Exception:
                        continue
                    if nearest is None or gap_m < nearest[0]:
                        nearest = (gap_m, left_idx, right_idx, left_point, right_point)
            if nearest is None or nearest[0] > max_fragment_bridge_gap_m:
                break
            gap_m, left_idx, right_idx, left_point, right_point = nearest
            bridge_line = LineString([(left_point.x, left_point.y), (right_point.x, right_point.y)])
            bridge = bridge_line.buffer(fragment_bridge_buffer_degree, cap_style=1, join_style=2)
            bridges.append(bridge)
            bridge_trace.append(
                {
                    "bridge_type": "SAME_WATER_BODY_NEAREST_FRAGMENT_GAP",
                    "rule_code": "CONNECT_NAMED_WATER_BODY_COMPONENTS_WITHIN_THRESHOLD",
                    "left_component_index": left_idx,
                    "right_component_index": right_idx,
                    "gap_m": round(gap_m, 2),
                    "left_point": [round(left_point.x, 6), round(left_point.y, 6)],
                    "right_point": [round(right_point.x, 6), round(right_point.y, 6)],
                    "buffer_degree": fragment_bridge_buffer_degree,
                }
            )
            working = make_valid(unary_union([working, bridge]))
    if not bridges:
        return geometry, []
    return make_valid(unary_union([geometry, *bridges])), bridge_trace


def _boundary_payload(
    *,
    channel: NavigationChannel,
    geometry: BaseGeometry,
    water_bodies: list[NavigationWaterBody],
    guide_lines: list[LineString],
    audit: dict[str, Any],
    fragment_bridge_trace: list[dict[str, Any]],
) -> dict[str, Any]:
    centroid = geometry.centroid
    min_lng, min_lat, max_lng, max_lat = geometry.bounds
    ring_count, point_count = _geometry_counts(geometry)
    blocking = bool(audit.get("blocking_issue_codes"))
    selected = [
        {
            "water_body_id": int(body.id),
            "water_body_name": body.production_name or body.display_name or body.water_body_name or body.normalized_water_name,
            "water_level_min": body.water_level_min,
            "water_level_max": body.water_level_max,
            "water_type_code": body.water_type_code,
            "source_layer_name": body.source_layer_name,
            "feature_count": body.feature_count,
        }
        for body in water_bodies
    ]
    return {
        "channel_id": int(channel.id),
        "geometry_json": mapping(geometry),
        "boundary_paths_low": None,
        "boundary_paths_medium": None,
        "boundary_paths_high": None,
        "center_longitude": _q(centroid.x),
        "center_latitude": _q(centroid.y),
        "display_center_longitude": _q(centroid.x),
        "display_center_latitude": _q(centroid.y),
        "bbox_min_lng": _q(min_lng),
        "bbox_min_lat": _q(min_lat),
        "bbox_max_lng": _q(max_lng),
        "bbox_max_lat": _q(max_lat),
        "source_shape_length_degree": _q(geometry.length, MEASURE_SCALE),
        "source_shape_area_degree": _q(geometry.area, MEASURE_SCALE),
        "ring_count": ring_count,
        "point_count": point_count,
        "geometry_status_code": "AVAILABLE",
        "boundary_quality_code": "AUTO_PUBLISHED" if not blocking else "REVIEW",
        "connectivity_status_code": "CONNECTED" if len(_polygon_parts(geometry)) == 1 else "CONNECTED_WITH_BRIDGES",
        "repair_status_code": "AUTO_REPAIRED" if not blocking else "AUTO_NEEDS_MORE_DATA",
        "coverage_policy_code": AUTO_BOUNDARY_POLICY,
        "geometry_coordinate_system_code": "WGS84",
        "boundary_coordinate_system_code": "WGS84",
        "source_trace_json": {
            "source": "self_heal_navigation_seed",
            "boundary_policy": AUTO_BOUNDARY_POLICY,
            "selected_water_bodies": selected,
            "selected_water_body_count": len(selected),
            "guide_line_count": len(guide_lines),
            "auto_fragment_bridge_verified": bool(guide_lines or fragment_bridge_trace),
            "auto_fragment_bridge_trace": fragment_bridge_trace,
            "basemap_verification": {
                "status_code": "AUTO_VERIFIED_BY_LOCAL_WATER_BODY_AND_MAP_LABEL_INFERENCE",
                "source_code": AUTO_NAME_SOURCE,
            },
            "boundary_integrity_audit": audit,
            "generated_at": datetime.now(UTC).isoformat(),
        },
        "is_current": True,
        "imported_at": datetime.now(UTC).replace(tzinfo=None),
    }


async def _load_channels(session: AsyncSession, channel_codes: list[str] | None, limit: int | None) -> list[NavigationChannel]:
    stmt = select(NavigationChannel).where(NavigationChannel.is_enabled.is_(True)).order_by(NavigationChannel.sort_order, NavigationChannel.id)
    if channel_codes:
        stmt = stmt.where(NavigationChannel.channel_code.in_(channel_codes))
    if limit:
        stmt = stmt.limit(max(1, int(limit)))
    return list((await session.execute(stmt)).scalars())


async def _existing_match_body_ids(session: AsyncSession, channel_id: int) -> set[int]:
    rows = (
        await session.execute(
            select(NavigationChannelWaterBodyMatch.water_body_id).where(
                NavigationChannelWaterBodyMatch.channel_id == channel_id,
                NavigationChannelWaterBodyMatch.is_current.is_(True),
            )
        )
    ).scalars()
    return {int(item) for item in rows}


async def _load_channel_segments(session: AsyncSession, channel_ids: Iterable[int]) -> dict[int, list[NavigationChannelSegment]]:
    rows = list(
        (
            await session.execute(
                select(NavigationChannelSegment)
                .where(
                    NavigationChannelSegment.channel_id.in_(list(channel_ids)),
                    NavigationChannelSegment.geometry_status_code != "ARCHIVED",
                )
                .order_by(NavigationChannelSegment.channel_id, NavigationChannelSegment.sequence_no, NavigationChannelSegment.id)
            )
        ).scalars()
    )
    output: dict[int, list[NavigationChannelSegment]] = defaultdict(list)
    for row in rows:
        output[int(row.channel_id)].append(row)
    return output


async def _load_current_boundaries(session: AsyncSession, channel_ids: Iterable[int]) -> dict[int, NavigationChannelBoundary]:
    rows = list(
        (
            await session.execute(
                select(NavigationChannelBoundary)
                .where(
                    NavigationChannelBoundary.channel_id.in_(list(channel_ids)),
                    NavigationChannelBoundary.is_current.is_(True),
                    NavigationChannelBoundary.geometry_status_code == "AVAILABLE",
                )
                .order_by(NavigationChannelBoundary.channel_id, NavigationChannelBoundary.id.desc())
            )
        ).scalars()
    )
    output: dict[int, NavigationChannelBoundary] = {}
    for row in rows:
        output.setdefault(int(row.channel_id), row)
    return output


async def _find_water_bodies(
    *,
    session: AsyncSession,
    channel: NavigationChannel,
    alias_config: dict[str, Any],
    guide_lines: list[LineString],
    location_boundary: NavigationChannelBoundary | None,
) -> tuple[list[tuple[NavigationWaterBody, str, str, int]], list[dict[str, Any]]]:
    channel_terms = _term_set(channel, alias_config)
    all_terms = sorted(channel_terms)
    candidates: dict[int, tuple[NavigationWaterBody, str, str, int]] = {}
    trace: list[dict[str, Any]] = []
    if all_terms:
        clauses = []
        for term in all_terms:
            like = f"%{term}%"
            clauses.extend(
                [
                    NavigationWaterBody.normalized_water_name == term,
                    NavigationWaterBody.water_body_name == term,
                    NavigationWaterBody.display_name == term,
                    NavigationWaterBody.production_name == term,
                    NavigationWaterBody.normalized_water_name.like(like),
                    NavigationWaterBody.water_body_name.like(like),
                    NavigationWaterBody.display_name.like(like),
                    NavigationWaterBody.production_name.like(like),
                ]
            )
        rows = list(
            (
                await session.execute(
                    select(NavigationWaterBody).where(
                        NavigationWaterBody.is_enabled.is_(True),
                        NavigationWaterBody.body_role_code.in_(PRODUCTION_BODY_ROLES),
                        or_(*clauses),
                    )
                )
            ).scalars()
        )
        for body in rows:
            score = _score_name(channel_terms, body)
            if score is not None:
                match_type, term, value = score
                candidates[int(body.id)] = (body, match_type, term, value)
    if guide_lines:
        bounds = unary_union(guide_lines).bounds
        margin = 0.08
        spatial_rows = list(
            (
                await session.execute(
                    select(NavigationWaterBody).where(
                        NavigationWaterBody.is_enabled.is_(True),
                        NavigationWaterBody.body_role_code.in_(PRODUCTION_BODY_ROLES),
                        NavigationWaterBody.geometry_wgs84_json.is_not(None),
                        NavigationWaterBody.bbox_max_lng >= bounds[0] - margin,
                        NavigationWaterBody.bbox_min_lng <= bounds[2] + margin,
                        NavigationWaterBody.bbox_max_lat >= bounds[1] - margin,
                        NavigationWaterBody.bbox_min_lat <= bounds[3] + margin,
                    )
                )
            ).scalars()
        )
        for body in spatial_rows:
            geometry = _geometry(body.geometry_wgs84_json)
            if geometry is None:
                continue
            ratio, nearest_m = _guide_hit_score(geometry, guide_lines)
            name_score = _score_name(channel_terms, body)
            if ratio >= 0.2 or nearest_m <= 500.0 or name_score is not None:
                if name_score is None:
                    match_type, term, value = "GUIDE_SPATIAL_MAP_LABEL_INFERRED", _candidate_name(channel, alias_config), 72
                else:
                    match_type, term, value = name_score[0], name_score[1], max(90, name_score[2])
                candidates[int(body.id)] = (body, match_type, term, value)
                trace.append({"water_body_id": int(body.id), "guide_coverage_ratio": round(ratio, 6), "nearest_guide_m": round(nearest_m, 2)})
    boundary_geometry = _geometry(location_boundary.geometry_json if location_boundary else None)
    if boundary_geometry is not None:
        has_high_confidence_named_candidate = any(item[3] >= 80 for item in candidates.values())
        min_lng, min_lat, max_lng, max_lat = boundary_geometry.bounds
        margin = 0.02
        boundary_rows = list(
            (
                await session.execute(
                    select(NavigationWaterBody).where(
                        NavigationWaterBody.is_enabled.is_(True),
                        NavigationWaterBody.body_role_code.in_(PRODUCTION_BODY_ROLES),
                        NavigationWaterBody.geometry_wgs84_json.is_not(None),
                        NavigationWaterBody.bbox_max_lng >= min_lng - margin,
                        NavigationWaterBody.bbox_min_lng <= max_lng + margin,
                        NavigationWaterBody.bbox_max_lat >= min_lat - margin,
                        NavigationWaterBody.bbox_min_lat <= max_lat + margin,
                    )
                )
            ).scalars()
        )
        boundary_hint = boundary_geometry.buffer(0.0008)
        inferred_name = _candidate_name(channel, alias_config)
        for body in boundary_rows:
            geometry = _geometry(body.geometry_wgs84_json)
            if geometry is None:
                continue
            try:
                intersects = bool(geometry.intersects(boundary_hint))
                inter_area = float(geometry.intersection(boundary_hint).area) if intersects else 0.0
                body_area = max(float(geometry.area), 1e-12)
            except Exception:
                intersects = False
                inter_area = 0.0
                body_area = 1.0
            if not intersects:
                continue
            area_ratio = inter_area / body_area
            name_score = _score_name(channel_terms, body)
            unnamed = not (body.production_name or body.display_name or body.water_body_name or body.normalized_water_name)
            if has_high_confidence_named_candidate and name_score is None and not unnamed:
                continue
            if name_score is None and not unnamed and area_ratio < 0.25:
                continue
            if name_score is not None:
                match_type, term, value = name_score[0], name_score[1], max(88, name_score[2])
            else:
                match_type, term, value = "SEED_BOUNDARY_MAP_LABEL_INFERRED", inferred_name, 70 if area_ratio >= 0.25 else 62
            candidates[int(body.id)] = (body, match_type, term, value)
            trace.append(
                {
                    "water_body_id": int(body.id),
                    "seed_boundary_intersection_ratio": round(area_ratio, 6),
                    "match_type": match_type,
                    "name_inferred": unnamed,
                }
            )
    return sorted(candidates.values(), key=lambda item: (-item[3], int(item[0].id))), trace


async def _create_missing_matches(
    *,
    session: AsyncSession,
    channel: NavigationChannel,
    bodies: list[tuple[NavigationWaterBody, str, str, int]],
    dry_run: bool,
) -> tuple[int, int]:
    existing = await _existing_match_body_ids(session, int(channel.id))
    created_matches = 0
    named_bodies = 0
    for body, match_type, matched_term, score in bodies:
        body_name_missing = not (body.production_name or body.display_name or body.water_body_name or body.normalized_water_name)
        if body_name_missing:
            inferred = matched_term or channel.channel_name
            if not dry_run:
                body.production_name = inferred
                body.display_name = inferred
                body.name_status_code = "PRODUCTION_NAMED"
                body.name_source_code = AUTO_NAME_SOURCE
                body.name_note = f"Auto named from map-position/channel guide inference for {channel.channel_code}."
            named_bodies += 1
        if int(body.id) in existing:
            continue
        if not dry_run:
            session.add(
                NavigationChannelWaterBodyMatch(
                    channel_id=int(channel.id),
                    water_body_id=int(body.id),
                    match_batch_code=AUTO_MATCH_BATCH,
                    match_type_code=match_type,
                    matched_term=matched_term,
                    score=score,
                    confidence_code="AUTO_HIGH_CONFIDENCE" if score >= 90 else "AUTO_SPATIAL_CONFIDENCE",
                    issue_codes=[] if score >= 90 else ["MAP_LABEL_OR_GUIDE_INFERRED"],
                    is_current=True,
                    source_water_area_ids_json=body.source_water_area_ids_json or [],
                    source_trace_json={
                        "source": "self_heal_navigation_seed",
                        "name_source_code": AUTO_NAME_SOURCE,
                        "channel_code": channel.channel_code,
                        "match_rule": match_type,
                    },
                )
            )
        created_matches += 1
    return named_bodies, created_matches


async def _current_matches(session: AsyncSession, channel_id: int) -> list[NavigationWaterBody]:
    return list(
        (
            await session.execute(
                select(NavigationWaterBody)
                .join(NavigationChannelWaterBodyMatch, NavigationChannelWaterBodyMatch.water_body_id == NavigationWaterBody.id)
                .where(
                    NavigationChannelWaterBodyMatch.channel_id == channel_id,
                    NavigationChannelWaterBodyMatch.is_current.is_(True),
                    NavigationWaterBody.is_enabled.is_(True),
                    NavigationWaterBody.body_role_code.in_(PRODUCTION_BODY_ROLES),
                    NavigationWaterBody.geometry_wgs84_json.is_not(None),
                )
                .order_by(NavigationChannelWaterBodyMatch.score.desc(), NavigationWaterBody.source_layer_order, NavigationWaterBody.id)
            )
        ).scalars()
    )


async def _promote_boundary(
    *,
    session: AsyncSession,
    channel: NavigationChannel,
    water_bodies: list[NavigationWaterBody],
    guide_lines: list[LineString],
    required_trust: set[str],
    bridge_fragment_gaps: bool,
    max_fragment_bridge_gap_m: float,
    fragment_bridge_buffer_degree: float,
    dry_run: bool,
) -> tuple[NavigationChannelBoundary | None, dict[str, Any]]:
    geometries = [_geometry(body.geometry_wgs84_json) for body in water_bodies]
    geometries = [item for item in geometries if item is not None]
    if not geometries:
        return None, {"status": "BLOCKED", "issue_codes": ["NO_WATER_BODY_GEOMETRY"]}
    geometry = make_valid(unary_union(geometries))
    geometry, fragment_bridge_trace = _bridge_fragmented_water(
        geometry,
        guide_lines,
        enable_nearest_fragment_bridge=bool(bridge_fragment_gaps and len(water_bodies) == 1),
        max_fragment_bridge_gap_m=max_fragment_bridge_gap_m,
        fragment_bridge_buffer_degree=fragment_bridge_buffer_degree,
    )
    if geometry.is_empty:
        return None, {"status": "BLOCKED", "issue_codes": ["WATER_BODY_UNION_EMPTY"]}
    centerline_geometries = [{"type": "LineString", "coordinates": list(line.coords)} for line in guide_lines]
    boundary_stub = {
        "geometry_status_code": "AVAILABLE",
        "geometry_json": mapping(geometry),
        "coverage_policy_code": AUTO_BOUNDARY_POLICY,
        "source_trace_json": {
            "basemap_verification": {"status_code": "AUTO_VERIFIED_BY_LOCAL_WATER_BODY_AND_MAP_LABEL_INFERENCE"},
            "auto_fragment_bridge_verified": bool(guide_lines or fragment_bridge_trace),
            "auto_fragment_bridge_trace": fragment_bridge_trace,
            "selected_water_areas": [
                {
                    "water_name": body.production_name or body.display_name or body.water_body_name or body.normalized_water_name,
                    "water_level": body.water_level_min,
                    "water_type_code": body.water_type_code,
                }
                for body in water_bodies
            ],
        },
    }
    audit = audit_boundary_integrity(
        channel={
            "technical_grade_current_code": channel.technical_grade_current_code,
            "technical_grade_planned_code": channel.technical_grade_planned_code or _derived_grade(channel),
        },
        boundary=boundary_stub,
        centerline_geometries=centerline_geometries,
        require_centerline=bool(guide_lines),
    )
    trust_code = str(audit.get("trust_code") or "")
    if required_trust and trust_code not in required_trust:
        return None, {"status": "SKIPPED_TRUST_FILTER", "trust_code": trust_code, "audit": audit}
    blocking = set(audit.get("blocking_issue_codes") or [])
    if blocking:
        return None, {"status": "BLOCKED", "issue_codes": sorted(blocking), "audit": audit}
    if dry_run:
        return None, {"status": "DRY_RUN", "audit": audit}
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
    boundary = NavigationChannelBoundary(
        **_boundary_payload(
            channel=channel,
            geometry=geometry,
            water_bodies=water_bodies,
            guide_lines=guide_lines,
            audit=audit,
            fragment_bridge_trace=fragment_bridge_trace,
        )
    )
    session.add(boundary)
    await session.flush()
    return boundary, {"status": "PROMOTED", "boundary_id": int(boundary.id), "audit": audit}


async def _generate_publish_centerline(
    *,
    session: AsyncSession,
    channel: NavigationChannel,
    has_guide_lines: bool,
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        return {"status": "DRY_RUN"}
    service = NavigationCenterlineSegmentService(session)
    source_mode = "CHANNEL_GUIDE_WITH_BOUNDARY_CLIP" if has_guide_lines else "BOUNDARY_ROUGH_LOCAL"
    generated = await service.generate_segments(
        int(channel.id),
        NavigationCenterlineSegmentGenerateRequest(force=True, segment_length_km=5.0, source_mode=source_mode),
    )
    if generated.status_code != "CREATED":
        return {"status": "BLOCKED", "blocker_codes": generated.blocker_codes, "message": generated.message}
    rows = await service._active_segments(int(channel.id), limit=10000)
    failures: list[dict[str, Any]] = []
    for row in rows:
        issue_summary = row.issue_summary_json if isinstance(row.issue_summary_json, dict) else {}
        if int(issue_summary.get("error_count") or 0) > 0:
            failures.append({"segment_id": int(row.id), "issue_summary": issue_summary})
            continue
        row.segment_status_code = "CONFIRMED"
        row.quality_code = "READY_WITH_WARNING" if int(issue_summary.get("warning_count") or 0) else "READY"
        trace = dict(row.source_trace_json or {})
        trace["confirmed_by"] = "self_heal_navigation_seed"
        trace["confirmed_at"] = datetime.now(UTC).isoformat()
        row.source_trace_json = trace
    if failures:
        await session.flush()
        return {"status": "BLOCKED", "blocker_codes": ["CENTERLINE_SEGMENT_VALIDATION_ERROR"], "failures": failures[:10], "segment_count": len(rows)}
    published = await service.publish_segments(
        int(channel.id),
        NavigationCenterlineSegmentPublishRequest(publish_name=f"{channel.channel_name}自动水体验证中心线"),
    )
    return {
        "status": published.status_code,
        "source_mode": source_mode,
        "centerline_id": published.centerline_id,
        "segment_count": published.segment_count,
        "quality_code": published.quality_code,
        "blocker_codes": published.blocker_codes,
        "message": published.message,
    }


async def _build_graph(channel_codes: list[str] | None, *, activate: bool, scope_code: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        summary = await build_graph_from_centerlines(
            session=session,
            version_code=f"AUTO-SEED-GRAPH-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            version_name="自动修复航道 Seed Graph",
            scope_code=scope_code,
            channel_codes=channel_codes,
            activate=activate,
        )
        return summary.as_dict()


async def main() -> None:
    args = parse_args()
    alias_config = json.loads(args.alias_config.read_text(encoding="utf-8"))
    report = SelfHealReport(generated_at=datetime.now(UTC).isoformat(), dry_run=bool(args.dry_run), channel_count=0)
    issue_counter: Counter[str] = Counter()
    required_trust = {str(item).upper() for item in (args.required_boundary_trust or []) if str(item).strip()}

    async with AsyncSessionLocal() as session:
        channels = await _load_channels(session, args.channel_codes, args.limit)
        report.channel_count = len(channels)
        segments_by_channel = await _load_channel_segments(session, [int(channel.id) for channel in channels])
        current_boundaries = await _load_current_boundaries(session, [int(channel.id) for channel in channels])
        for channel in channels:
            if _ensure_technical_grade(channel, dry_run=bool(args.dry_run)):
                report.technical_grade_derived_count += 1
            guide_lines = _guide_lines(segments_by_channel.get(int(channel.id), []))
            candidates, spatial_trace = await _find_water_bodies(
                session=session,
                channel=channel,
                alias_config=alias_config,
                guide_lines=guide_lines,
                location_boundary=current_boundaries.get(int(channel.id)),
            )
            auto_named, match_created = await _create_missing_matches(
                session=session,
                channel=channel,
                bodies=candidates,
                dry_run=bool(args.dry_run),
            )
            water_bodies = await _current_matches(session, int(channel.id)) if not args.dry_run else [item[0] for item in candidates]
            if args.skip_boundaries:
                boundary_result = {"status": "SKIPPED"}
            else:
                _boundary, boundary_result = await _promote_boundary(
                    session=session,
                    channel=channel,
                    water_bodies=water_bodies,
                    guide_lines=guide_lines,
                    required_trust=required_trust,
                    bridge_fragment_gaps=bool(args.bridge_fragment_gaps),
                    max_fragment_bridge_gap_m=float(args.max_fragment_bridge_gap_km) * 1000.0,
                    fragment_bridge_buffer_degree=float(args.fragment_bridge_buffer_degree),
                    dry_run=bool(args.dry_run),
                )
            centerline_result = {"status": "SKIPPED"}
            if boundary_result.get("status") in {"PROMOTED", "DRY_RUN"} and not args.skip_centerlines:
                centerline_result = await _generate_publish_centerline(
                    session=session,
                    channel=channel,
                    has_guide_lines=bool(guide_lines),
                    dry_run=bool(args.dry_run),
                )
            for code in boundary_result.get("issue_codes") or []:
                issue_counter[str(code)] += 1
            for code in centerline_result.get("blocker_codes") or []:
                issue_counter[str(code)] += 1
            report.water_body_auto_name_count += auto_named
            report.water_body_match_created_count += match_created
            if boundary_result.get("status") == "PROMOTED":
                report.boundary_promoted_count += 1
            elif boundary_result.get("status") == "BLOCKED":
                report.boundary_blocked_count += 1
            if centerline_result.get("status") == "PUBLISHED":
                report.centerline_generated_count += 1
                report.centerline_published_count += 1
            elif centerline_result.get("status") == "BLOCKED":
                report.centerline_blocked_count += 1
            report.channels.append(
                {
                    "channel_id": int(channel.id),
                    "channel_code": channel.channel_code,
                    "channel_name": channel.channel_name,
                    "technical_grade_planned_code": channel.technical_grade_planned_code or _derived_grade(channel),
                    "guide_line_count": len(guide_lines),
                    "candidate_water_body_count": len(candidates),
                    "matched_water_body_count": len(water_bodies),
                    "auto_named_water_body_count": auto_named,
                    "created_match_count": match_created,
                    "boundary_result": boundary_result,
                    "centerline_result": centerline_result,
                    "spatial_trace": spatial_trace[:10],
                    "candidate_water_bodies": [
                        {
                            "water_body_id": int(body.id),
                            "name": body.production_name or body.display_name or body.water_body_name or body.normalized_water_name,
                            "match_type": match_type,
                            "matched_term": term,
                            "score": score,
                        }
                        for body, match_type, term, score in candidates[:20]
                    ],
                }
            )
            if not args.dry_run:
                await session.commit()

    if args.build_graph and not args.dry_run:
        graph_report = await _build_graph(args.channel_codes, activate=bool(args.activate_graph), scope_code=str(args.graph_scope_code))
        report.graph_build_status = str(graph_report.get("status_code"))
        report.graph_version_id = graph_report.get("graph_version_id")
        report.graph_edge_count = graph_report.get("edge_count")
        for issue in graph_report.get("issues") or []:
            if isinstance(issue, dict) and issue.get("issue_code"):
                issue_counter[str(issue["issue_code"])] += 1

    report.issue_counts = dict(sorted(issue_counter.items()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report.as_dict()[k] for k in ("channel_count", "water_body_auto_name_count", "water_body_match_created_count", "technical_grade_derived_count", "boundary_promoted_count", "boundary_blocked_count", "centerline_published_count", "centerline_blocked_count", "graph_build_status", "graph_version_id", "graph_edge_count", "issue_counts")}, ensure_ascii=False, indent=2))
    print(f"report_path={args.output}")


if __name__ == "__main__":
    asyncio.run(main())
