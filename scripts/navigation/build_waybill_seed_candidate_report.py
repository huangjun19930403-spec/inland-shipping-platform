"""Build seed and boundary candidates from imported waybill references."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.validation import make_valid
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models import NavigationRouteTrajectoryCache


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CROSS_REFERENCE = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_repair_queue_cross_reference_20260608.json"
DEFAULT_ANALYSIS = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_route_reference_analysis_20260608.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_seed_candidate_report_20260608.json"
DEFAULT_GEOJSON_OUTPUT = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_seed_candidate_report_20260608.geojson"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build seed/boundary repair candidates from waybill reference cache.")
    parser.add_argument("--cross-reference", type=Path, default=DEFAULT_CROSS_REFERENCE)
    parser.add_argument("--analysis", type=Path, default=DEFAULT_ANALYSIS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--geojson-output", type=Path, default=DEFAULT_GEOJSON_OUTPUT)
    parser.add_argument("--buffer-m", type=float, default=350.0)
    parser.add_argument("--limit", type=int, default=50)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    cross = json.loads(args.cross_reference.read_text(encoding="utf-8"))
    analysis = json.loads(args.analysis.read_text(encoding="utf-8"))
    water_matches = _water_match_index(analysis)
    seed_queue = list(cross.get("seed_usage_queue") or [])[: max(0, int(args.limit))]
    waybill_codes = [((item.get("best_reference") or {}).get("waybill_code")) for item in seed_queue]
    async with AsyncSessionLocal() as session:
        cache_by_waybill = await _load_waybill_caches(session, [str(code) for code in waybill_codes if code])
    candidates: list[dict[str, Any]] = []
    features: list[dict[str, Any]] = []
    for item in seed_queue:
        candidate, candidate_features = _candidate_from_queue_item(
            item,
            cache_by_waybill=cache_by_waybill,
            water_matches=water_matches,
            buffer_m=float(args.buffer_m),
        )
        candidates.append(candidate)
        features.extend(candidate_features)
    summary = _summary(candidates, analysis)
    report = {
        "report_version": "WAYBILL_SEED_CANDIDATE_REPORT_V1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_cross_reference": str(args.cross_reference),
        "source_analysis": str(args.analysis),
        "args": {"buffer_m": float(args.buffer_m), "limit": int(args.limit)},
        "summary": summary,
        "candidates": candidates,
        "guardrails": [
            "Candidates come from REAL_WAYBILL REFERENCE_ONLY cache rows and are not user-returnable routes.",
            "Centerline candidates must pass water coverage, endpoint snap, foldback, long-jump, and boundary coverage validation before publish.",
            "Boundary buffers are repair patches, not authoritative water polygons; promote only after local water body or map-label evidence agrees.",
            "Missing water systems must be created with observed vessel constraints and conservative grade until official/source grade is available.",
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
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"report_path={args.output}")
    if args.geojson_output:
        print(f"geojson_path={args.geojson_output}")


async def _load_waybill_caches(session, waybill_codes: list[str]) -> dict[str, NavigationRouteTrajectoryCache]:
    if not waybill_codes:
        return {}
    keys = [f"WAYBILL_ROUTE_REFERENCE_V1|{code}" for code in waybill_codes]
    rows = list(
        (
            await session.execute(
                select(NavigationRouteTrajectoryCache)
                .where(
                    NavigationRouteTrajectoryCache.route_key.in_(keys),
                    NavigationRouteTrajectoryCache.provider_code == "REAL_WAYBILL",
                    NavigationRouteTrajectoryCache.cache_status_code == "REFERENCE_ONLY",
                    NavigationRouteTrajectoryCache.geometry_json.is_not(None),
                )
                .order_by(NavigationRouteTrajectoryCache.id)
            )
        ).scalars()
    )
    output: dict[str, NavigationRouteTrajectoryCache] = {}
    for row in rows:
        summary = row.validation_summary_json if isinstance(row.validation_summary_json, dict) else {}
        waybill_code = str(summary.get("waybill_code") or row.route_key.rsplit("|", 1)[-1])
        output[waybill_code] = row
    return output


def _candidate_from_queue_item(
    item: dict[str, Any],
    *,
    cache_by_waybill: dict[str, NavigationRouteTrajectoryCache],
    water_matches: dict[str, dict[str, Any]],
    buffer_m: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    reference = item.get("best_reference") or {}
    waybill_code = str(reference.get("waybill_code") or "")
    cache = cache_by_waybill.get(waybill_code)
    line = _line(cache.geometry_json if cache else None)
    buffer_geometry = _buffer(line, buffer_m=buffer_m) if line is not None else None
    water_systems = list(reference.get("water_systems") or [])
    actions = [_water_system_action(name, water_matches.get(name)) for name in water_systems]
    candidate = {
        "target_type_code": item.get("target_type_code"),
        "target_code": item.get("target_code"),
        "target_name": item.get("target_name"),
        "seed_use_code": item.get("seed_use_code"),
        "priority_code": _priority_code(item, actions),
        "trajectory_cache_id": int(cache.id) if cache else None,
        "waybill_code": waybill_code or None,
        "route_code": reference.get("route_code"),
        "route_name": reference.get("route_name"),
        "geometry_reference_count": item.get("geometry_reference_count"),
        "reference_quality_score": reference.get("quality_score"),
        "track_metrics": reference.get("track_metrics"),
        "water_system_actions": actions,
        "centerline_candidate": {
            "source_type_code": "WAYBILL_ROUTE_REFERENCE_CENTERLINE_CANDIDATE",
            "point_count": len(line.coords) if line is not None else 0,
            "bbox": [round(float(value), 7) for value in line.bounds] if line is not None else None,
            "publish_allowed": False,
        },
        "boundary_candidate": {
            "source_type_code": "WAYBILL_ROUTE_REFERENCE_BOUNDARY_BUFFER_CANDIDATE",
            "buffer_m": buffer_m,
            "bbox": [round(float(value), 7) for value in buffer_geometry.bounds] if buffer_geometry is not None else None,
            "publish_allowed": False,
        },
        "next_action_codes": _next_actions(item, actions),
    }
    return candidate, _features(candidate, line=line, buffer_geometry=buffer_geometry)


def _water_system_action(name: str, match: dict[str, Any] | None) -> dict[str, Any]:
    if not match or match.get("match_status_code") != "MATCHED":
        return {
            "water_system_name": name,
            "action_code": "CREATE_MISSING_WATER_SYSTEM_SEED",
            "matched_channel": None,
            "matched_water_body": None,
            "matched_water_area": None,
            "grade_source_code": "OBSERVED_WAYBILL_CONSTRAINT_ONLY",
        }
    channel_match = next((item for item in match.get("matches") or [] if item.get("source_type_code") == "NAVIGATION_CHANNEL"), None)
    body_match = next((item for item in match.get("matches") or [] if item.get("source_type_code") == "WATER_BODY"), None)
    area_match = next((item for item in match.get("matches") or [] if item.get("source_type_code") == "WATER_AREA"), None)
    if channel_match:
        action_code = "USE_EXISTING_CHANNEL_SEED"
    elif body_match or area_match:
        action_code = "CREATE_OR_LINK_CHANNEL_FROM_MATCHED_WATER"
    else:
        action_code = "REVIEW_WATER_SYSTEM_MATCH"
    return {
        "water_system_name": name,
        "action_code": action_code,
        "matched_channel": channel_match,
        "matched_water_body": body_match,
        "matched_water_area": area_match,
        "grade_source_code": "LOCAL_CHANNEL_OR_WAYBILL_OBSERVED_CONSTRAINT",
    }


def _priority_code(item: dict[str, Any], actions: list[dict[str, Any]]) -> str:
    if any(action.get("action_code") == "CREATE_MISSING_WATER_SYSTEM_SEED" for action in actions):
        return "P0_MISSING_WATER_SYSTEM_AND_WAYBILL_GEOMETRY"
    if item.get("seed_use_code") == "WAYBILL_ACCESS_SEED_PRIORITY":
        return "P0_ENDPOINT_ACCESS_REPAIR"
    if item.get("seed_use_code") == "WAYBILL_CONNECTIVITY_REPAIR_PRIORITY":
        return "P1_GRAPH_CONNECTIVITY_REPAIR"
    return "P2_REFERENCE_AVAILABLE"


def _next_actions(item: dict[str, Any], actions: list[dict[str, Any]]) -> list[str]:
    output = []
    if any(action.get("action_code") == "CREATE_MISSING_WATER_SYSTEM_SEED" for action in actions):
        output.append("CREATE_WATER_SYSTEM_CHANNEL_AND_BOUNDARY_FROM_REFERENCE_CORRIDOR")
    if item.get("seed_use_code") == "WAYBILL_ACCESS_SEED_PRIORITY":
        output.append("EXTRACT_ENDPOINT_ACCESS_CENTERLINE_FROM_REFERENCE")
    if item.get("seed_use_code") == "WAYBILL_CONNECTIVITY_REPAIR_PRIORITY":
        output.append("REPAIR_GRAPH_COMPONENT_CONNECTOR_WITH_REFERENCE")
    output.append("RUN_BOUNDARY_COVERAGE_AND_GRAPH_REBUILD_VALIDATION")
    return output


def _features(candidate: dict[str, Any], *, line: LineString | None, buffer_geometry: BaseGeometry | None) -> list[dict[str, Any]]:
    props = {
        "target_type_code": candidate.get("target_type_code"),
        "target_code": candidate.get("target_code"),
        "target_name": candidate.get("target_name"),
        "seed_use_code": candidate.get("seed_use_code"),
        "priority_code": candidate.get("priority_code"),
        "trajectory_cache_id": candidate.get("trajectory_cache_id"),
        "waybill_code": candidate.get("waybill_code"),
        "route_code": candidate.get("route_code"),
    }
    features: list[dict[str, Any]] = []
    if line is not None:
        features.append({"type": "Feature", "properties": {**props, "feature_role": "centerline_candidate"}, "geometry": mapping(line)})
    if buffer_geometry is not None:
        features.append({"type": "Feature", "properties": {**props, "feature_role": "boundary_buffer_candidate"}, "geometry": mapping(buffer_geometry)})
    return features


def _water_match_index(analysis: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("water_name")): item for item in analysis.get("water_system_matches") or []}


def _summary(candidates: list[dict[str, Any]], analysis: dict[str, Any]) -> dict[str, Any]:
    priorities = Counter(item.get("priority_code") for item in candidates)
    water_actions = Counter(
        action.get("action_code")
        for item in candidates
        for action in item.get("water_system_actions") or []
    )
    missing_names = sorted(
        {
            action.get("water_system_name")
            for item in candidates
            for action in item.get("water_system_actions") or []
            if action.get("action_code") == "CREATE_MISSING_WATER_SYSTEM_SEED"
        }
    )
    return {
        "candidate_count": len(candidates),
        "with_trajectory_cache_count": sum(1 for item in candidates if item.get("trajectory_cache_id")),
        "priority_counts": dict(sorted(priorities.items())),
        "water_system_action_counts": dict(sorted(water_actions.items())),
        "missing_water_system_names": missing_names,
        "source_waybill_geometry_reference_count": (analysis.get("summary") or {}).get("geometry_reference_count"),
        "source_water_system_unmatched_count": (analysis.get("water_system_match_summary") or {}).get("unmatched_count"),
    }


def _line(value: Any) -> LineString | None:
    if not isinstance(value, dict):
        return None
    try:
        geometry = shape(value)
    except Exception:
        return None
    if isinstance(geometry, LineString) and len(geometry.coords) >= 2:
        return geometry
    return None


def _buffer(line: LineString, *, buffer_m: float) -> BaseGeometry | None:
    try:
        return make_valid(line.buffer(float(buffer_m) / 111_320.0, cap_style=2, join_style=2))
    except Exception:
        return None


if __name__ == "__main__":
    asyncio.run(main())
