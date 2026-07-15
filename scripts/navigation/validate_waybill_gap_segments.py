"""Validate waybill-derived gap segments against local water geometry."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from shapely.geometry import LineString, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.navigation import NavigationWaterArea, NavigationWaterBody


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GAP_REPORT = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_seed_gap_segments_20260608.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_seed_gap_validation_20260608.json"
DEFAULT_GEOJSON_OUTPUT = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_seed_gap_validation_20260608.geojson"
PROMOTABLE_ROLES = {"ENDPOINT_ACCESS_SEGMENT", "GRAPH_GAP_SEGMENT"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate waybill gap segments against local water-body and water-area geometry.")
    parser.add_argument("--gap-report", type=Path, default=DEFAULT_GAP_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--geojson-output", type=Path, default=DEFAULT_GEOJSON_OUTPUT)
    parser.add_argument("--water-buffer-m", type=float, default=120.0)
    parser.add_argument("--coverage-threshold", type=float, default=0.90)
    parser.add_argument("--strict-coverage-threshold", type=float, default=0.98)
    parser.add_argument("--max-step-km", type=float, default=15.0)
    parser.add_argument("--min-length-km", type=float, default=0.5)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    gap_report = json.loads(args.gap_report.read_text(encoding="utf-8"))
    rows = _segment_rows(gap_report)
    async with AsyncSessionLocal() as session:
        validated = []
        features = []
        for row in rows:
            item = await _validate_row(
                session,
                row,
                water_buffer_m=float(args.water_buffer_m),
                coverage_threshold=float(args.coverage_threshold),
                strict_coverage_threshold=float(args.strict_coverage_threshold),
                max_step_km=float(args.max_step_km),
                min_length_km=float(args.min_length_km),
            )
            validated.append(item)
            features.extend(_features(item))
    report = {
        "report_version": "WAYBILL_SEED_GAP_VALIDATION_V1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_gap_report": str(args.gap_report),
        "args": {
            "water_buffer_m": float(args.water_buffer_m),
            "coverage_threshold": float(args.coverage_threshold),
            "strict_coverage_threshold": float(args.strict_coverage_threshold),
            "max_step_km": float(args.max_step_km),
            "min_length_km": float(args.min_length_km),
        },
        "summary": _summary(validated),
        "items": validated,
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


def _segment_rows(gap_report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in gap_report.get("items") or []:
        for segment in item.get("segments") or []:
            geometry = segment.get("geometry_json")
            if not isinstance(geometry, dict):
                continue
            rows.append(
                {
                    "target_code": item.get("target_code"),
                    "target_name": item.get("target_name"),
                    "seed_use_code": item.get("seed_use_code"),
                    "gap_priority_code": item.get("gap_priority_code"),
                    "trajectory_cache_id": item.get("trajectory_cache_id"),
                    "waybill_code": item.get("waybill_code"),
                    "route_code": item.get("route_code"),
                    "origin_code": item.get("origin_code"),
                    "destination_code": item.get("destination_code"),
                    "water_system_actions": item.get("water_system_actions") or [],
                    "segment_role_code": segment.get("segment_role_code"),
                    "segment_no": segment.get("segment_no"),
                    "length_km": segment.get("length_km"),
                    "geometry_json": geometry,
                    "buffer_geometry_json": segment.get("buffer_geometry_json"),
                }
            )
    return rows


async def _validate_row(
    session,
    row: dict[str, Any],
    *,
    water_buffer_m: float,
    coverage_threshold: float,
    strict_coverage_threshold: float,
    max_step_km: float,
    min_length_km: float,
) -> dict[str, Any]:
    line = _line(row.get("geometry_json"))
    if line is None:
        return {**row, "validation_status_code": "BLOCKED", "blocking_issue_codes": ["SEGMENT_GEOMETRY_INVALID"]}
    water_context = await _water_context(session, line, buffer_m=water_buffer_m)
    water_union = water_context.get("geometry")
    coverage = _coverage_ratio(line, water_union, tolerance_m=water_buffer_m)
    max_step = _max_step_km(line)
    length_km = _line_length_km(line)
    issues = []
    if length_km < min_length_km:
        issues.append("SEGMENT_TOO_SHORT")
    if max_step > max_step_km:
        issues.append("SEGMENT_LONG_SAMPLE_GAP")
    if not line.is_simple:
        issues.append("SEGMENT_SELF_INTERSECTION")
    if coverage < coverage_threshold:
        issues.append("LOW_LOCAL_WATER_COVERAGE")
    if row.get("segment_role_code") not in PROMOTABLE_ROLES:
        issues.append("SEGMENT_ROLE_NOT_CENTERLINE_PROMOTABLE")
    missing_water = any(
        action.get("action_code") == "CREATE_MISSING_WATER_SYSTEM_SEED"
        for action in row.get("water_system_actions") or []
    )
    if missing_water and coverage < strict_coverage_threshold:
        issues.append("MISSING_WATER_SYSTEM_NEEDS_STRICT_COVERAGE")
    status = "READY_FOR_SEED_CANDIDATE" if not issues else "NEED_REVIEW"
    return {
        **{key: value for key, value in row.items() if key not in {"buffer_geometry_json"}},
        "length_km": round(length_km, 3),
        "max_step_km": round(max_step, 3),
        "line_is_simple": bool(line.is_simple),
        "local_water_coverage_ratio": round(coverage, 6),
        "validation_status_code": status,
        "blocking_issue_codes": sorted(set(issues)),
        "promote_allowed": status == "READY_FOR_SEED_CANDIDATE",
        "matched_water_context": {
            "water_area_count": water_context["water_area_count"],
            "water_body_count": water_context["water_body_count"],
            "named_water_areas": water_context["named_water_areas"],
            "named_water_bodies": water_context["named_water_bodies"],
        },
        "candidate_publish_guardrails": [
            "Only promote as seed after graph rebuild and route matrix validation passes.",
            "Do not turn this reference into VALID route cache directly.",
            "Boundary buffers remain candidates until water coverage and route audits pass.",
        ],
    }


async def _water_context(session, line: LineString, *, buffer_m: float) -> dict[str, Any]:
    minx, miny, maxx, maxy = line.bounds
    margin = max(0.001, float(buffer_m) / 111_320.0 + 0.01)
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
    geometries = []
    named_areas = Counter()
    named_bodies = Counter()
    for row in area_rows:
        geometry = _geometry(row.geometry_json)
        if geometry is None:
            continue
        if geometry.intersects(line.buffer(margin)):
            geometries.append(geometry)
            name = _usable_name(row.water_name)
            if name:
                named_areas[name] += 1
    for row in body_rows:
        geometry = _geometry(row.geometry_wgs84_json)
        if geometry is None:
            continue
        if geometry.intersects(line.buffer(margin)):
            geometries.append(geometry)
            name = _usable_name(row.production_name or row.display_name or row.water_body_name)
            if name:
                named_bodies[name] += 1
    return {
        "geometry": make_valid(unary_union(geometries)) if geometries else None,
        "water_area_count": len(area_rows),
        "water_body_count": len(body_rows),
        "named_water_areas": named_areas.most_common(10),
        "named_water_bodies": named_bodies.most_common(10),
    }


def _coverage_ratio(line: LineString, geometry: BaseGeometry | None, *, tolerance_m: float) -> float:
    if geometry is None or geometry.is_empty:
        return 0.0
    try:
        covered = line.intersection(geometry.buffer(float(tolerance_m) / 111_320.0)).length
    except Exception:
        return 0.0
    return max(0.0, min(1.0, covered / max(line.length, 1e-12)))


def _features(items: dict[str, Any]) -> list[dict[str, Any]]:
    geometry = items.get("geometry_json")
    if not isinstance(geometry, dict):
        return []
    props = {
        "target_code": items.get("target_code"),
        "target_name": items.get("target_name"),
        "segment_role_code": items.get("segment_role_code"),
        "validation_status_code": items.get("validation_status_code"),
        "promote_allowed": items.get("promote_allowed"),
        "coverage": items.get("local_water_coverage_ratio"),
        "issues": ",".join(items.get("blocking_issue_codes") or []),
        "waybill_code": items.get("waybill_code"),
        "trajectory_cache_id": items.get("trajectory_cache_id"),
    }
    features = [{"type": "Feature", "properties": props, "geometry": geometry}]
    buffer_geometry = items.get("buffer_geometry_json")
    if isinstance(buffer_geometry, dict):
        features.append({"type": "Feature", "properties": {**props, "feature_role": "segment_buffer"}, "geometry": buffer_geometry})
    return features


def _summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(item.get("validation_status_code") for item in items)
    roles = Counter(item.get("segment_role_code") for item in items)
    issues = Counter(code for item in items for code in item.get("blocking_issue_codes") or [])
    promotable = [item for item in items if item.get("promote_allowed")]
    return {
        "segment_count": len(items),
        "promote_allowed_count": len(promotable),
        "status_counts": dict(sorted(statuses.items())),
        "segment_role_counts": dict(sorted(roles.items())),
        "blocking_issue_counts": dict(sorted(issues.items())),
        "promote_allowed_length_km": round(sum(float(item.get("length_km") or 0) for item in promotable), 3),
        "avg_water_coverage_ratio": round(
            sum(float(item.get("local_water_coverage_ratio") or 0) for item in items) / len(items),
            6,
        )
        if items
        else None,
    }


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


def _usable_name(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text.startswith("未命名"):
        return None
    return text


def _line_length_km(line: LineString) -> float:
    coords = list(line.coords)
    return sum(_haversine_km(start, end) for start, end in zip(coords[:-1], coords[1:]))


def _max_step_km(line: LineString) -> float:
    coords = list(line.coords)
    return max((_haversine_km(start, end) for start, end in zip(coords[:-1], coords[1:])), default=0.0)


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
