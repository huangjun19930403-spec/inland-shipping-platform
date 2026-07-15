"""Resolve waybill repair candidates to segment-level local water context.

The upstream waybill audit works at route-reference level, where one waybill
often lists several water systems. This script re-checks each repair candidate
segment against local water geometry so boundary/seed repair can target the
actual local waterway instead of the full multi-water-system route label.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shapely.geometry import mapping

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from scripts.navigation.audit_waybill_reference_against_current_graph import (
    DEFAULT_CANDIDATES_OUTPUT,
    GEOD,
    GeometryIndex,
    _channel_payload,
    _degree_buffer,
    _extract_lines,
    _line,
    _line_length_km,
    _load_channels,
    _load_water_geometry_refs,
    _name_matches,
    _usable_name,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = PROJECT_ROOT / "runtime/navigation-production/reports"
DEFAULT_OUTPUT = REPORT_DIR / "waybill_segment_level_repair_queue_20260611.json"
DEFAULT_GEOJSON_OUTPUT = REPORT_DIR / "waybill_segment_level_repair_queue_20260611.geojson"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resolve waybill repair candidate segments to local water context.")
    parser.add_argument("--candidate-jsonl", type=Path, default=DEFAULT_CANDIDATES_OUTPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--geojson-output", type=Path, default=DEFAULT_GEOJSON_OUTPUT)
    parser.add_argument("--water-tolerance-m", type=float, default=120.0)
    parser.add_argument("--min-top-water-ratio", type=float, default=0.55)
    parser.add_argument("--ambiguous-ratio-gap", type=float, default=0.12)
    parser.add_argument("--geojson-limit", type=int, default=1000)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    candidates = _read_candidates(args.candidate_jsonl)
    async with AsyncSessionLocal() as session:
        channels = await _load_channels(session)
        water_index = GeometryIndex(await _load_water_geometry_refs(session))
    items = [
        _resolve_candidate(
            candidate,
            channels=channels,
            water_index=water_index,
            water_tolerance_m=float(args.water_tolerance_m),
            min_top_water_ratio=float(args.min_top_water_ratio),
            ambiguous_ratio_gap=float(args.ambiguous_ratio_gap),
        )
        for candidate in candidates
    ]
    report = {
        "report_version": "WAYBILL_SEGMENT_LEVEL_REPAIR_QUEUE_V1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_candidate_jsonl": str(args.candidate_jsonl),
        "args": {
            "water_tolerance_m": float(args.water_tolerance_m),
            "min_top_water_ratio": float(args.min_top_water_ratio),
            "ambiguous_ratio_gap": float(args.ambiguous_ratio_gap),
        },
        "summary": _summary(items),
        "repair_groups": _repair_groups(items),
        "items": [{key: value for key, value in item.items() if key != "buffer_geometry_json"} for item in items],
        "usage_policy": {
            "AUTO_BOUNDARY_REPAIR_READY": "Can feed boundary draft/patch generation for the resolved existing channel.",
            "AUTO_SEED_REPAIR_READY": "Can feed centerline seed creation after boundary coverage is confirmed for the resolved channel.",
            "AUTO_CREATE_CHANNEL_OR_ALIAS_FROM_LOCAL_WATER": (
                "Local water geometry has a usable name but no current NavigationChannel match; create/alias the channel first, "
                "then rerun boundary/graph build."
            ),
            "SPLIT_AMBIGUOUS_LOCAL_WATER": (
                "Segment overlaps multiple local water names without a dominant one; split again at denser geometry or use "
                "shorter candidate pieces before publishing."
            ),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.geojson_output:
        args.geojson_output.parent.mkdir(parents=True, exist_ok=True)
        args.geojson_output.write_text(
            json.dumps(_geojson(items, limit=max(0, int(args.geojson_limit))), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"report_path={args.output}")
    if args.geojson_output:
        print(f"geojson_path={args.geojson_output}")


def _read_candidates(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _resolve_candidate(
    candidate: dict[str, Any],
    *,
    channels,
    water_index: GeometryIndex,
    water_tolerance_m: float,
    min_top_water_ratio: float,
    ambiguous_ratio_gap: float,
) -> dict[str, Any]:
    line = _line(candidate.get("geometry_json"))
    if line is None:
        return {**candidate, "segment_repair_status_code": "BLOCKED_INVALID_CANDIDATE_GEOMETRY"}
    local_context = _segment_local_water_context(line, water_index, tolerance_m=water_tolerance_m)
    top = local_context[0] if local_context else None
    second = local_context[1] if len(local_context) > 1 else None
    resolved_name = top["water_name"] if top else None
    resolved_ratio = float(top["coverage_ratio"]) if top else 0.0
    ambiguous = bool(second and resolved_ratio - float(second["coverage_ratio"]) < ambiguous_ratio_gap)
    matched_channel = _match_channel(resolved_name, channels) if resolved_name else None
    status = _status(candidate, resolved_ratio, ambiguous, matched_channel is not None, min_top_water_ratio)
    output = {
        **candidate,
        "segment_length_km": round(_line_length_km(line), 3),
        "resolved_local_water_name": resolved_name,
        "resolved_local_water_coverage_ratio": round(resolved_ratio, 6),
        "segment_local_water_context": local_context[:8],
        "resolved_channel": _channel_payload(matched_channel) if matched_channel is not None else None,
        "segment_repair_status_code": status,
        "segment_repair_action_code": _action_code(candidate, status),
        "geometry_json": mapping(line),
    }
    return output


def _segment_local_water_context(line, water_index: GeometryIndex, *, tolerance_m: float) -> list[dict[str, Any]]:
    query_geometry = line.buffer(_degree_buffer(tolerance_m), cap_style=2, join_style=2)
    name_parts: dict[str, list[Any]] = defaultdict(list)
    source_counter: dict[str, Counter[str]] = defaultdict(Counter)
    for ref in water_index.query(query_geometry):
        if not ref.geometry.intersects(query_geometry):
            continue
        usable_names = [_usable_name(name) for name in ref.names]
        usable_names = [name for name in usable_names if name]
        if not usable_names:
            continue
        try:
            clipped = line.intersection(ref.geometry.buffer(_degree_buffer(tolerance_m), cap_style=2, join_style=2))
        except Exception:
            continue
        parts = _extract_lines(clipped)
        if not parts:
            continue
        primary_name = usable_names[0]
        name_parts[primary_name].extend(parts)
        source_counter[primary_name].update([ref.source_type_code])
    output: list[dict[str, Any]] = []
    total_length = max(_line_length_km(line), 1e-9)
    for name, parts in name_parts.items():
        length_km = _parts_length_km(parts)
        output.append(
            {
                "water_name": name,
                "covered_length_km": round(length_km, 3),
                "coverage_ratio": round(max(0.0, min(1.0, length_km / total_length)), 6),
                "source_type_counts": dict(sorted(source_counter[name].items())),
            }
        )
    output.sort(key=lambda item: (float(item["coverage_ratio"]), float(item["covered_length_km"])), reverse=True)
    return output


def _parts_length_km(parts: list[Any]) -> float:
    total_m = 0.0
    for line in parts:
        coords = list(line.coords)
        for start, end in zip(coords[:-1], coords[1:]):
            _, _, distance_m = GEOD.inv(float(start[0]), float(start[1]), float(end[0]), float(end[1]))
            total_m += abs(distance_m)
    return total_m / 1000.0


def _match_channel(water_name: str | None, channels) -> Any | None:
    if not water_name:
        return None
    matches = [channel for channel in channels if any(_name_matches(water_name, name) for name in channel.names)]
    if len(matches) == 1:
        return matches[0]
    exact = [channel for channel in matches if any(str(name).strip() == water_name for name in channel.names)]
    if len(exact) == 1:
        return exact[0]
    return None


def _status(
    candidate: dict[str, Any],
    resolved_ratio: float,
    ambiguous: bool,
    has_channel: bool,
    min_top_water_ratio: float,
) -> str:
    if resolved_ratio < min_top_water_ratio:
        return "SPLIT_UNRESOLVED_LOW_LOCAL_WATER_COVERAGE"
    if ambiguous:
        return "SPLIT_AMBIGUOUS_LOCAL_WATER"
    if not has_channel:
        return "AUTO_CREATE_CHANNEL_OR_ALIAS_FROM_LOCAL_WATER"
    if candidate.get("candidate_type_code") == "BOUNDARY_EXPANSION":
        return "AUTO_BOUNDARY_REPAIR_READY"
    if candidate.get("candidate_type_code") == "CENTERLINE_OR_GRAPH_SEED":
        return "AUTO_SEED_REPAIR_READY"
    return "AUTO_SEGMENT_REPAIR_READY"


def _action_code(candidate: dict[str, Any], status: str) -> str:
    if status == "AUTO_BOUNDARY_REPAIR_READY":
        return "CREATE_BOUNDARY_PATCH_DRAFT"
    if status == "AUTO_SEED_REPAIR_READY":
        return "CREATE_CENTERLINE_SEED_DRAFT"
    if status == "AUTO_CREATE_CHANNEL_OR_ALIAS_FROM_LOCAL_WATER":
        return "CREATE_CHANNEL_OR_ALIAS_THEN_REQUEUE"
    if status == "SPLIT_AMBIGUOUS_LOCAL_WATER":
        return "SPLIT_BY_DENSER_LOCAL_WATER_INTERSECTIONS"
    if status == "SPLIT_UNRESOLVED_LOW_LOCAL_WATER_COVERAGE":
        return "KEEP_AS_REFERENCE_ONLY"
    return str(candidate.get("repair_rule") or "KEEP_AS_REFERENCE_ONLY")


def _summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(item.get("segment_repair_status_code") for item in items)
    actions = Counter(item.get("segment_repair_action_code") for item in items)
    candidate_types = Counter(item.get("candidate_type_code") for item in items)
    resolved_names = Counter(item.get("resolved_local_water_name") or "-" for item in items)
    return {
        "segment_candidate_count": len(items),
        "candidate_type_counts": dict(sorted(candidate_types.items())),
        "segment_repair_status_counts": dict(sorted(statuses.items())),
        "segment_repair_action_counts": dict(sorted(actions.items())),
        "total_segment_length_km": round(sum(float(item.get("segment_length_km") or 0) for item in items), 3),
        "ready_boundary_length_km": round(
            sum(float(item.get("segment_length_km") or 0) for item in items if item.get("segment_repair_status_code") == "AUTO_BOUNDARY_REPAIR_READY"),
            3,
        ),
        "ready_seed_length_km": round(
            sum(float(item.get("segment_length_km") or 0) for item in items if item.get("segment_repair_status_code") == "AUTO_SEED_REPAIR_READY"),
            3,
        ),
        "create_channel_or_alias_length_km": round(
            sum(float(item.get("segment_length_km") or 0) for item in items if item.get("segment_repair_status_code") == "AUTO_CREATE_CHANNEL_OR_ALIAS_FROM_LOCAL_WATER"),
            3,
        ),
        "top_resolved_local_water_names": resolved_names.most_common(30),
    }


def _repair_groups(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in items:
        status = str(item.get("segment_repair_status_code") or "-")
        candidate_type = str(item.get("candidate_type_code") or "-")
        water_name = str(item.get("resolved_local_water_name") or "-")
        key = (status, candidate_type, water_name)
        group = groups.setdefault(
            key,
            {
                "segment_repair_status_code": status,
                "candidate_type_code": candidate_type,
                "resolved_local_water_name": water_name,
                "segment_count": 0,
                "segment_length_km": 0.0,
                "waybill_count": set(),
                "route_count": set(),
                "resolved_channel": item.get("resolved_channel"),
                "top_waybill_examples": [],
            },
        )
        group["segment_count"] += 1
        group["segment_length_km"] += float(item.get("segment_length_km") or 0)
        if item.get("waybill_code"):
            group["waybill_count"].add(str(item.get("waybill_code")))
        if item.get("route_code"):
            group["route_count"].add(str(item.get("route_code")))
        if len(group["top_waybill_examples"]) < 8:
            group["top_waybill_examples"].append(
                {
                    "waybill_code": item.get("waybill_code"),
                    "route_code": item.get("route_code"),
                    "segment_length_km": item.get("segment_length_km"),
                    "water_systems": item.get("water_systems"),
                }
            )
    output = []
    for group in groups.values():
        output.append(
            {
                **{key: value for key, value in group.items() if key not in {"waybill_count", "route_count"}},
                "segment_length_km": round(float(group["segment_length_km"]), 3),
                "waybill_count": len(group["waybill_count"]),
                "route_count": len(group["route_count"]),
            }
        )
    output.sort(key=lambda item: (item["segment_count"], item["segment_length_km"]), reverse=True)
    return output


def _geojson(items: list[dict[str, Any]], *, limit: int) -> dict[str, Any]:
    selected = sorted(items, key=lambda item: float(item.get("segment_length_km") or 0), reverse=True)
    if limit:
        selected = selected[:limit]
    features = []
    for item in selected:
        geometry = item.get("geometry_json")
        if not isinstance(geometry, dict):
            continue
        props = {
            key: value
            for key, value in item.items()
            if key
            not in {
                "geometry_json",
                "buffer_geometry_json",
                "origin",
                "destination",
                "segment_local_water_context",
                "observed_constraints",
            }
        }
        features.append({"type": "Feature", "properties": props, "geometry": geometry})
    return {"type": "FeatureCollection", "features": features}


if __name__ == "__main__":
    asyncio.run(main())
