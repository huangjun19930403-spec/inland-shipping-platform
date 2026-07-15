from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Polygon, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points
from shapely.validation import make_valid

from app.modules.navigation.production_pipeline.centerline_builder import point_distance_m


FRAGMENT_GAP_REVIEW_M = 1000.0
MIN_CENTERLINE_COVERAGE_RATIO = 0.98

GRADE_ALIASES = {
    "1": "I",
    "Ⅰ": "I",
    "I": "I",
    "一级": "I",
    "2": "II",
    "Ⅱ": "II",
    "II": "II",
    "二级": "II",
    "3": "III",
    "Ⅲ": "III",
    "III": "III",
    "三级": "III",
    "4": "IV",
    "Ⅳ": "IV",
    "IV": "IV",
    "四级": "IV",
    "5": "V",
    "Ⅴ": "V",
    "V": "V",
    "五级": "V",
    "6": "VI",
    "Ⅵ": "VI",
    "VI": "VI",
    "六级": "VI",
    "7": "VII",
    "Ⅶ": "VII",
    "VII": "VII",
    "七级": "VII",
}

GRADE_LIMITS = {
    "I": {"max_allowed_tonnage": 3000.0, "max_allowed_draft_m": 4.0, "min_width_m": 90.0},
    "II": {"max_allowed_tonnage": 2000.0, "max_allowed_draft_m": 3.5, "min_width_m": 70.0},
    "III": {"max_allowed_tonnage": 1000.0, "max_allowed_draft_m": 3.0, "min_width_m": 55.0},
    "IV": {"max_allowed_tonnage": 500.0, "max_allowed_draft_m": 2.5, "min_width_m": 45.0},
    "V": {"max_allowed_tonnage": 300.0, "max_allowed_draft_m": 2.0, "min_width_m": 35.0},
    "VI": {"max_allowed_tonnage": 100.0, "max_allowed_draft_m": 1.5, "min_width_m": 25.0},
    "VII": {"max_allowed_tonnage": 50.0, "max_allowed_draft_m": 1.0, "min_width_m": 18.0},
}


def normalize_technical_grade(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if not text:
        return None
    text = text.replace("航道", "").replace("技术等级", "").replace("级", "级")
    return GRADE_ALIASES.get(text)


def vessel_limit_profile(
    *,
    current_grade_code: Any,
    planned_grade_code: Any,
) -> dict[str, Any]:
    grade = normalize_technical_grade(current_grade_code) or normalize_technical_grade(planned_grade_code)
    if not grade:
        return {
            "technical_grade_code": None,
            "unknown_constraint_flag": True,
            "constraint_data_completeness_code": "UNKNOWN",
            "source_code": "TECHNICAL_GRADE_MISSING",
            "issue_codes": ["NAVIGATION_TECHNICAL_GRADE_UNKNOWN"],
            "note": "航道技术等级缺失，不能对可通行船型/吨级做强保证。",
        }
    limits = GRADE_LIMITS[grade]
    return {
        "technical_grade_code": grade,
        "unknown_constraint_flag": False,
        "constraint_data_completeness_code": "RULE_DERIVED_NEEDS_REVIEW",
        "source_code": "TECHNICAL_GRADE_RULE_DERIVED",
        "issue_codes": ["NAVIGATION_GRADE_LIMIT_RULE_DERIVED"],
        **limits,
        "note": "按航道技术等级保守推导的通行能力，仍需用正式通航尺度资料复核。",
    }


def audit_boundary_integrity(
    *,
    channel: dict[str, Any],
    boundary: dict[str, Any] | None,
    centerline_geometries: Iterable[dict[str, Any]] = (),
    require_centerline: bool = True,
) -> dict[str, Any]:
    issue_codes: list[str] = []
    if not boundary or boundary.get("geometry_status_code") != "AVAILABLE" or not boundary.get("geometry_json"):
        return {
            "trust_code": "FAILED",
            "issue_codes": ["CHANNEL_BOUNDARY_MISSING"],
            "blocking_issue_codes": ["CHANNEL_BOUNDARY_MISSING"],
            "water_system": _water_system_summary(boundary),
            "vessel_limit_profile": vessel_limit_profile(
                current_grade_code=channel.get("technical_grade_current_code"),
                planned_grade_code=channel.get("technical_grade_planned_code"),
            ),
        }

    geometry = _safe_geometry(boundary.get("geometry_json"))
    if geometry is None:
        return {
            "trust_code": "FAILED",
            "issue_codes": ["CHANNEL_BOUNDARY_GEOMETRY_INVALID"],
            "blocking_issue_codes": ["CHANNEL_BOUNDARY_GEOMETRY_INVALID"],
            "water_system": _water_system_summary(boundary),
            "vessel_limit_profile": vessel_limit_profile(
                current_grade_code=channel.get("technical_grade_current_code"),
                planned_grade_code=channel.get("technical_grade_planned_code"),
            ),
        }

    source_trace = boundary.get("source_trace_json") if isinstance(boundary.get("source_trace_json"), dict) else {}
    policy = str(boundary.get("coverage_policy_code") or "")
    if policy == "CHANNEL_CORRIDOR_ENVELOPE":
        issue_codes.append("BOUNDARY_CORRIDOR_ENVELOPE_NEEDS_REAL_WATERWAY_REVIEW")
    if source_trace.get("revier_boundary_policy") == "reuse_current_curated_channel_boundary":
        issue_codes.append("BOUNDARY_REUSED_WITHOUT_SOURCE_REAUDIT")
    if not source_trace.get("basemap_verification"):
        issue_codes.append("BOUNDARY_NOT_INDEPENDENTLY_BASEMAP_VERIFIED")

    parts = _polygon_parts(geometry)
    total_area = sum(max(part.area, 0.0) for part in parts)
    largest_area = max((part.area for part in parts), default=0.0)
    largest_component_ratio = largest_area / total_area if total_area > 0 else 0.0
    gap_stats = _component_gap_stats(parts)
    if len(parts) > 1 and (
        float(gap_stats.get("max_gap_m") or 0.0) > FRAGMENT_GAP_REVIEW_M or largest_component_ratio < 0.95
    ):
        issue_codes.append("SOURCE_GEOMETRY_FRAGMENTED")

    centerline_coverages = _centerline_coverages(geometry, centerline_geometries)
    if require_centerline and not centerline_coverages:
        issue_codes.append("CENTERLINE_MISSING_BOUNDARY_NOT_VERIFIED")
    if any(item["coverage_ratio"] < MIN_CENTERLINE_COVERAGE_RATIO for item in centerline_coverages):
        issue_codes.append("CENTERLINE_NOT_ENCLOSED_BY_BOUNDARY")

    vessel_profile = vessel_limit_profile(
        current_grade_code=channel.get("technical_grade_current_code"),
        planned_grade_code=channel.get("technical_grade_planned_code"),
    )
    issue_codes.extend(vessel_profile.get("issue_codes") or [])

    blocking = sorted(
        {
            code
            for code in issue_codes
            if code
            in {
                "CHANNEL_BOUNDARY_GEOMETRY_INVALID",
                "CHANNEL_BOUNDARY_MISSING",
                "CENTERLINE_NOT_ENCLOSED_BY_BOUNDARY",
            }
        }
    )
    trust_code = "FAILED" if blocking else "NEEDS_REVIEW" if issue_codes else "READY"
    non_blocking_auto_issues = {"NAVIGATION_GRADE_LIMIT_RULE_DERIVED"}
    if source_trace.get("auto_fragment_bridge_verified"):
        non_blocking_auto_issues.add("SOURCE_GEOMETRY_FRAGMENTED")
    if trust_code == "NEEDS_REVIEW" and set(issue_codes) <= non_blocking_auto_issues:
        trust_code = "READY_WITH_WARNING"
    return {
        "trust_code": trust_code,
        "issue_codes": sorted(set(issue_codes)),
        "blocking_issue_codes": blocking,
        "component_count": len(parts),
        "largest_component_ratio": round(largest_component_ratio, 6),
        "component_gap_stats": gap_stats,
        "centerline_coverage": centerline_coverages,
        "water_system": _water_system_summary(boundary),
        "vessel_limit_profile": vessel_profile,
        "verification_rule": "boundary must enclose source waterway components and published centerlines; independent basemap/AIS verification required for HIGH confidence",
    }


def _water_system_summary(boundary: dict[str, Any] | None) -> dict[str, Any]:
    source_trace = boundary.get("source_trace_json") if isinstance(boundary, dict) and isinstance(boundary.get("source_trace_json"), dict) else {}
    selected = source_trace.get("selected_water_areas") if isinstance(source_trace, dict) else None
    water_levels: list[int] = []
    water_types: dict[str, int] = {}
    if isinstance(selected, list):
        for item in selected:
            if not isinstance(item, dict):
                continue
            level = item.get("water_level")
            try:
                if level is not None:
                    water_levels.append(int(level))
            except (TypeError, ValueError):
                pass
            water_type = str(item.get("water_type_code") or "UNKNOWN")
            water_types[water_type] = water_types.get(water_type, 0) + 1
    return {
        "water_level_min": min(water_levels) if water_levels else None,
        "water_level_max": max(water_levels) if water_levels else None,
        "water_type_counts": dict(sorted(water_types.items())),
        "selected_water_area_count": len(selected) if isinstance(selected, list) else None,
        "direct_water_area_count": source_trace.get("direct_water_area_count"),
        "bridge_water_area_count": source_trace.get("bridge_water_area_count"),
    }


def _safe_geometry(geometry_json: Any) -> BaseGeometry | None:
    if not isinstance(geometry_json, dict):
        return None
    try:
        geometry = make_valid(shape(geometry_json))
    except Exception:
        return None
    if geometry.is_empty:
        return None
    return geometry


def _polygon_parts(geometry: BaseGeometry) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        parts: list[Polygon] = []
        for item in geometry.geoms:
            parts.extend(_polygon_parts(item))
        return parts
    return []


def _component_gap_stats(parts: list[Polygon]) -> dict[str, Any]:
    if len(parts) < 2:
        return {"max_gap_m": 0.0, "nearest_gap_m": 0.0}
    gaps: list[float] = []
    max_gap_pair: tuple[int, int] | None = None
    max_gap = 0.0
    for left_index, left in enumerate(parts):
        for right_index, right in enumerate(parts[left_index + 1 :], start=left_index + 1):
            left_point, right_point = nearest_points(left, right)
            gap_m = point_distance_m(left_point, right_point)
            gaps.append(gap_m)
            if gap_m > max_gap:
                max_gap = gap_m
                max_gap_pair = (left_index, right_index)
    return {
        "max_gap_m": round(max(gaps), 3) if gaps else 0.0,
        "nearest_gap_m": round(min(gaps), 3) if gaps else 0.0,
        "max_gap_pair_indexes": list(max_gap_pair) if max_gap_pair else None,
    }


def _centerline_coverages(boundary_geometry: BaseGeometry, centerline_geometries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    tolerance = max(
        max(boundary_geometry.bounds[2] - boundary_geometry.bounds[0], boundary_geometry.bounds[3] - boundary_geometry.bounds[1])
        / 5000.0,
        0.00003,
    )
    buffered = boundary_geometry.buffer(tolerance)
    for index, geometry_json in enumerate(centerline_geometries, start=1):
        try:
            line = shape(geometry_json)
        except Exception:
            output.append({"index": index, "coverage_ratio": 0.0, "status_code": "INVALID_CENTERLINE"})
            continue
        if not isinstance(line, LineString) or line.is_empty or line.length <= 0:
            output.append({"index": index, "coverage_ratio": 0.0, "status_code": "INVALID_CENTERLINE"})
            continue
        try:
            covered = line.intersection(buffered).length
        except Exception:
            covered = 0.0
        ratio = max(0.0, min(1.0, covered / line.length if line.length else 0.0))
        output.append(
            {
                "index": index,
                "coverage_ratio": round(ratio, 6),
                "status_code": "READY" if ratio >= MIN_CENTERLINE_COVERAGE_RATIO else "FAILED",
            }
        )
    return output
