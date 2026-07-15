"""Resolve missing water-name waybill gap segments with spatial evidence.

This report is intentionally non-mutating. Route-level water-system labels are
not segment names; each gap segment must be checked against local water coverage,
existing channel geometry, and endpoint/route-name hints before it can become
seed data.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points
from shapely.validation import make_valid
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models import NavigationChannelCenterline
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.modules.navigation.engine.geo import point_distance_m


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VALIDATION_REPORT = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_seed_gap_validation_graph51_fixed_20260608.json"
DEFAULT_CANDIDATE_REPORT = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_seed_candidate_report_graph51_fixed_20260608.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_missing_water_context_resolution_20260608.json"
DEFAULT_GEOJSON_OUTPUT = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_missing_water_context_resolution_20260608.geojson"
WATER_NAME_RE = re.compile(r"([\u4e00-\u9fa5]{1,10}(?:江|河|湖|港|运河|塘|泾))")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resolve missing water context for waybill-derived gap segments.")
    parser.add_argument("--validation-report", type=Path, default=DEFAULT_VALIDATION_REPORT)
    parser.add_argument("--candidate-report", type=Path, default=DEFAULT_CANDIDATE_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--geojson-output", type=Path, default=DEFAULT_GEOJSON_OUTPUT)
    parser.add_argument("--strict-coverage-threshold", type=float, default=0.98)
    parser.add_argument("--spatial-centerline-threshold-m", type=float, default=250.0)
    parser.add_argument("--nearest-limit", type=int, default=5)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    validation = json.loads(args.validation_report.read_text(encoding="utf-8"))
    candidate_lookup = _candidate_lookup(json.loads(args.candidate_report.read_text(encoding="utf-8")))
    rows = [
        item
        for item in validation.get("items") or []
        if any(action.get("action_code") == "CREATE_MISSING_WATER_SYSTEM_SEED" for action in item.get("water_system_actions") or [])
    ]
    async with AsyncSessionLocal() as session:
        channels = await _load_channels(session)
        centerlines = await _load_centerlines(session)
        boundaries = await _load_boundaries(session)
        items = []
        features = []
        for row in rows:
            item = _resolve_row(
                row,
                candidate_lookup=candidate_lookup,
                channels=channels,
                centerlines=centerlines,
                boundaries=boundaries,
                strict_coverage_threshold=float(args.strict_coverage_threshold),
                spatial_centerline_threshold_m=float(args.spatial_centerline_threshold_m),
                nearest_limit=max(1, int(args.nearest_limit or 1)),
            )
            items.append(item)
            geometry = item.get("geometry_json")
            if isinstance(geometry, dict):
                features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            key: value
                            for key, value in item.items()
                            if key
                            not in {
                                "geometry_json",
                                "nearest_centerlines",
                                "nearest_boundaries",
                                "water_system_actions",
                                "candidate_source",
                            }
                        },
                        "geometry": geometry,
                    }
                )
    report = {
        "report_version": "WAYBILL_MISSING_WATER_CONTEXT_RESOLUTION_V1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_validation_report": str(args.validation_report),
        "source_candidate_report": str(args.candidate_report),
        "args": {
            "strict_coverage_threshold": float(args.strict_coverage_threshold),
            "spatial_centerline_threshold_m": float(args.spatial_centerline_threshold_m),
            "nearest_limit": max(1, int(args.nearest_limit or 1)),
        },
        "summary": _summary(items),
        "items": items,
        "guardrails": [
            "Route-level water-system labels are not promoted as segment names.",
            "Endpoint or route-name hints such as 大蒸港 only create name candidates; they do not publish channels by themselves.",
            "Existing-channel spatial candidates require unique near-centerline evidence and downstream graph/OD audit before publication.",
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
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"report_path={args.output}")
    if args.geojson_output:
        print(f"geojson_path={args.geojson_output}")


async def _load_channels(session) -> dict[int, NavigationChannel]:
    rows = (await session.execute(select(NavigationChannel).where(NavigationChannel.is_enabled.is_(True)))).scalars()
    return {int(row.id): row for row in rows}


async def _load_centerlines(session) -> list[tuple[NavigationChannelCenterline, BaseGeometry]]:
    rows = (
        await session.execute(
            select(NavigationChannelCenterline).where(
                NavigationChannelCenterline.is_current.is_(True),
                NavigationChannelCenterline.geometry_json.is_not(None),
            )
        )
    ).scalars()
    return [(row, geometry) for row in rows if (geometry := _geometry(row.geometry_json)) is not None]


async def _load_boundaries(session) -> list[tuple[NavigationChannelBoundary, BaseGeometry]]:
    rows = (
        await session.execute(
            select(NavigationChannelBoundary).where(
                NavigationChannelBoundary.is_current.is_(True),
                NavigationChannelBoundary.geometry_json.is_not(None),
            )
        )
    ).scalars()
    return [(row, geometry) for row in rows if (geometry := _geometry(row.geometry_json)) is not None]


def _resolve_row(
    row: dict[str, Any],
    *,
    candidate_lookup: dict[tuple[str, int], dict[str, Any]],
    channels: dict[int, NavigationChannel],
    centerlines: list[tuple[NavigationChannelCenterline, BaseGeometry]],
    boundaries: list[tuple[NavigationChannelBoundary, BaseGeometry]],
    strict_coverage_threshold: float,
    spatial_centerline_threshold_m: float,
    nearest_limit: int,
) -> dict[str, Any]:
    line = _line(row.get("geometry_json"))
    candidate = candidate_lookup.get((str(row.get("target_code") or ""), int(row.get("trajectory_cache_id") or 0))) or {}
    context_names = _context_names(row)
    route_label_names = [
        str(action.get("water_system_name") or "")
        for action in row.get("water_system_actions") or []
        if action.get("action_code") == "CREATE_MISSING_WATER_SYSTEM_SEED"
    ]
    hint_names = _hint_names(candidate)
    nearest_centerlines = _nearest(line, centerlines, channels=channels, limit=nearest_limit) if line is not None else []
    nearest_boundaries = _nearest(line, boundaries, channels=channels, limit=nearest_limit) if line is not None else []
    coverage = float(row.get("local_water_coverage_ratio") or 0.0)
    issue_codes: list[str] = []
    if route_label_names and any(name not in context_names and name not in hint_names for name in route_label_names):
        issue_codes.append("ROUTE_LABEL_NOT_SEGMENT_LEVEL")
    if coverage < strict_coverage_threshold:
        status = "BLOCKED_LOW_LOCAL_WATER_COVERAGE"
    elif context_names:
        status = _spatial_status(nearest_centerlines, threshold_m=spatial_centerline_threshold_m)
    elif hint_names:
        status = "MISSING_WATER_NAME_CANDIDATE_FROM_ENDPOINT_OR_ROUTE_HINT"
    else:
        status = "NEEDS_EXTERNAL_MAP_NAME_EVIDENCE"
    return {
        "target_code": row.get("target_code"),
        "target_name": row.get("target_name"),
        "segment_role_code": row.get("segment_role_code"),
        "segment_no": row.get("segment_no"),
        "length_km": row.get("length_km"),
        "local_water_coverage_ratio": row.get("local_water_coverage_ratio"),
        "resolution_status_code": status,
        "issue_codes": sorted(set(issue_codes)),
        "route_label_missing_names": route_label_names,
        "local_context_names": context_names,
        "hint_name_candidates": hint_names,
        "candidate_source": {
            "route_name": candidate.get("route_name"),
            "target_name": candidate.get("target_name"),
            "waybill_code": candidate.get("waybill_code"),
            "route_code": candidate.get("route_code"),
        },
        "nearest_centerlines": nearest_centerlines,
        "nearest_boundaries": nearest_boundaries,
        "water_system_actions": row.get("water_system_actions") or [],
        "geometry_json": mapping(line) if line is not None else row.get("geometry_json"),
    }


def _spatial_status(nearest_centerlines: list[dict[str, Any]], *, threshold_m: float) -> str:
    near = [item for item in nearest_centerlines if float(item.get("distance_m") or 1e18) <= threshold_m]
    channel_codes = {item.get("channel_code") for item in near if item.get("channel_code")}
    if len(channel_codes) == 1:
        return "SPATIAL_EXISTING_CHANNEL_CANDIDATE"
    if len(channel_codes) > 1:
        return "AMBIGUOUS_EXISTING_CHANNEL_CONTEXT"
    return "LOCAL_NAMED_WATER_WITHOUT_NEAR_CHANNEL"


def _nearest(
    line: LineString,
    rows: list[tuple[Any, BaseGeometry]],
    *,
    channels: dict[int, NavigationChannel],
    limit: int,
) -> list[dict[str, Any]]:
    candidates = []
    for row, geometry in rows:
        channel_id = int(row.channel_id)
        channel = channels.get(channel_id)
        candidates.append(
            {
                "distance_m": round(_distance_m(line, geometry), 1),
                "channel_id": channel_id,
                "channel_code": channel.channel_code if channel else None,
                "channel_name": channel.channel_name if channel else None,
                "object_id": int(row.id),
            }
        )
    return sorted(candidates, key=lambda item: float(item["distance_m"]))[:limit]


def _candidate_lookup(report: dict[str, Any]) -> dict[tuple[str, int], dict[str, Any]]:
    output = {}
    for item in report.get("candidates") or []:
        key = (str(item.get("target_code") or ""), int(item.get("trajectory_cache_id") or 0))
        output[key] = item
    return output


def _hint_names(candidate: dict[str, Any]) -> list[str]:
    texts = " ".join(str(candidate.get(key) or "") for key in ("target_name", "route_name"))
    names: list[str] = []
    if "大蒸港" in texts:
        names.append("大蒸港")
    for match in WATER_NAME_RE.finditer(texts):
        name = match.group(1)
        if name.startswith("上海") and len(name) > 3:
            name = name[2:]
        if name not in names:
            names.append(name)
    return names[:5]


def _context_names(row: dict[str, Any]) -> list[str]:
    context = row.get("matched_water_context") if isinstance(row.get("matched_water_context"), dict) else {}
    names: list[str] = []
    for key in ("named_water_areas", "named_water_bodies"):
        for item in context.get(key) or []:
            name = str((item or [None])[0] or "").strip()
            if name and not name.startswith("未命名") and name not in names:
                names.append(name)
    return names


def _line(value: Any) -> LineString | None:
    geometry = _geometry(value)
    return geometry if isinstance(geometry, LineString) and len(geometry.coords) >= 2 else None


def _geometry(value: Any) -> BaseGeometry | None:
    if not isinstance(value, dict):
        return None
    try:
        geometry = make_valid(shape(value))
    except Exception:
        return None
    return None if geometry.is_empty else geometry


def _distance_m(left: BaseGeometry, right: BaseGeometry) -> float:
    try:
        left_point, right_point = nearest_points(left, right)
        return float(point_distance_m(left_point, right_point))
    except Exception:
        return 1e18


def _summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "segment_count": len(items),
        "status_counts": dict(sorted(Counter(item.get("resolution_status_code") for item in items).items())),
        "issue_counts": dict(sorted(Counter(code for item in items for code in item.get("issue_codes") or []).items())),
        "route_label_missing_names": sorted({name for item in items for name in item.get("route_label_missing_names") or []}),
        "hint_name_candidates": sorted({name for item in items for name in item.get("hint_name_candidates") or []}),
        "local_context_names": sorted({name for item in items for name in item.get("local_context_names") or []}),
    }


if __name__ == "__main__":
    asyncio.run(main())
