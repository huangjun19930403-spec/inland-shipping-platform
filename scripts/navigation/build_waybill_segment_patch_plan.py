"""Build grouped patch plans from segment-level waybill repair queue.

This is the bridge between evidence and mutation. It groups resolved repair
segments by target channel or missing local water name and deduplicates repeated
waybill observations into corridor-level patch plans. It does not write to the
database.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid

from scripts.navigation.audit_waybill_reference_against_current_graph import _degree_buffer, _line, _line_length_km


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = PROJECT_ROOT / "runtime/navigation-production/reports"
DEFAULT_QUEUE = REPORT_DIR / "waybill_segment_level_repair_queue_20260611.json"
DEFAULT_OUTPUT = REPORT_DIR / "waybill_segment_patch_plan_20260611.json"
DEFAULT_GEOJSON_OUTPUT = REPORT_DIR / "waybill_segment_patch_plan_20260611.geojson"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build grouped waybill boundary/seed patch plans.")
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--geojson-output", type=Path, default=DEFAULT_GEOJSON_OUTPUT)
    parser.add_argument("--boundary-buffer-m", type=float, default=220.0)
    parser.add_argument("--seed-buffer-m", type=float, default=80.0)
    parser.add_argument("--min-support-waybills", type=int, default=2)
    parser.add_argument("--geojson-line-limit-per-group", type=int, default=8)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = json.loads(args.queue.read_text(encoding="utf-8"))
    items = source.get("items") or []
    groups = _build_groups(
        items,
        boundary_buffer_m=float(args.boundary_buffer_m),
        seed_buffer_m=float(args.seed_buffer_m),
        min_support_waybills=int(args.min_support_waybills),
    )
    report = {
        "report_version": "WAYBILL_SEGMENT_PATCH_PLAN_V1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_queue": str(args.queue),
        "args": {
            "boundary_buffer_m": float(args.boundary_buffer_m),
            "seed_buffer_m": float(args.seed_buffer_m),
            "min_support_waybills": int(args.min_support_waybills),
        },
        "summary": _summary(groups),
        "boundary_patch_groups": [
            _strip_geometry(group) for group in groups["boundary_patch_groups"]
        ],
        "seed_patch_groups": [_strip_geometry(group) for group in groups["seed_patch_groups"]],
        "channel_or_alias_groups": [_strip_geometry(group) for group in groups["channel_or_alias_groups"]],
        "guardrails": [
            "Patch groups are evidence-only until DB mutation script runs with graph regression audit.",
            "Repeated waybill observations are grouped into corridor geometry before boundary mutation.",
            "Groups below the support threshold stay CANDIDATE_LOW_SUPPORT unless they target an already known channel and are short.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.geojson_output:
        args.geojson_output.parent.mkdir(parents=True, exist_ok=True)
        args.geojson_output.write_text(
            json.dumps(_geojson(groups, line_limit_per_group=max(0, int(args.geojson_line_limit_per_group))), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"report_path={args.output}")
    if args.geojson_output:
        print(f"geojson_path={args.geojson_output}")


def _build_groups(
    items: list[dict[str, Any]],
    *,
    boundary_buffer_m: float,
    seed_buffer_m: float,
    min_support_waybills: int,
) -> dict[str, list[dict[str, Any]]]:
    boundary_items = [item for item in items if item.get("segment_repair_status_code") == "AUTO_BOUNDARY_REPAIR_READY"]
    seed_items = [item for item in items if item.get("segment_repair_status_code") == "AUTO_SEED_REPAIR_READY"]
    create_items = [
        item for item in items if item.get("segment_repair_status_code") == "AUTO_CREATE_CHANNEL_OR_ALIAS_FROM_LOCAL_WATER"
    ]
    return {
        "boundary_patch_groups": _groups_by_channel(
            boundary_items,
            patch_type_code="BOUNDARY_PATCH",
            buffer_m=boundary_buffer_m,
            min_support_waybills=min_support_waybills,
        ),
        "seed_patch_groups": _groups_by_channel(
            seed_items,
            patch_type_code="CENTERLINE_SEED",
            buffer_m=seed_buffer_m,
            min_support_waybills=min_support_waybills,
        ),
        "channel_or_alias_groups": _groups_by_water_name(
            create_items,
            buffer_m=boundary_buffer_m,
            min_support_waybills=min_support_waybills,
        ),
    }


def _groups_by_channel(
    items: list[dict[str, Any]],
    *,
    patch_type_code: str,
    buffer_m: float,
    min_support_waybills: int,
) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        channel = item.get("resolved_channel") if isinstance(item.get("resolved_channel"), dict) else None
        if channel and channel.get("id") is not None:
            grouped[int(channel["id"])].append(item)
    output = []
    for _, rows in grouped.items():
        channel = rows[0].get("resolved_channel") or {}
        output.append(
            _patch_group(
                rows,
                patch_type_code=patch_type_code,
                target_type_code="EXISTING_CHANNEL",
                target_key=str(channel.get("id")),
                target_name=str(channel.get("channel_name") or ""),
                target_payload=channel,
                buffer_m=buffer_m,
                min_support_waybills=min_support_waybills,
            )
        )
    output.sort(key=lambda item: (item["patch_status_code"], item["segment_count"], item["raw_segment_length_km"]), reverse=True)
    return output


def _groups_by_water_name(
    items: list[dict[str, Any]],
    *,
    buffer_m: float,
    min_support_waybills: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        name = str(item.get("resolved_local_water_name") or "").strip()
        if name:
            grouped[name].append(item)
    output = []
    for name, rows in grouped.items():
        output.append(
            _patch_group(
                rows,
                patch_type_code="CREATE_CHANNEL_OR_ALIAS",
                target_type_code="LOCAL_WATER_NAME",
                target_key=name,
                target_name=name,
                target_payload={"water_name": name},
                buffer_m=buffer_m,
                min_support_waybills=min_support_waybills,
            )
        )
    output.sort(key=lambda item: (item["patch_status_code"], item["segment_count"], item["raw_segment_length_km"]), reverse=True)
    return output


def _patch_group(
    rows: list[dict[str, Any]],
    *,
    patch_type_code: str,
    target_type_code: str,
    target_key: str,
    target_name: str,
    target_payload: dict[str, Any],
    buffer_m: float,
    min_support_waybills: int,
) -> dict[str, Any]:
    lines = [_line(row.get("geometry_json")) for row in rows]
    lines = [line for line in lines if line is not None]
    line_hashes = {_line_hash(line) for line in lines}
    waybill_codes = {str(row.get("waybill_code")) for row in rows if row.get("waybill_code")}
    route_codes = {str(row.get("route_code")) for row in rows if row.get("route_code")}
    corridor = _corridor(lines, buffer_m=buffer_m)
    status = "PATCH_READY"
    if len(waybill_codes) < min_support_waybills:
        status = "CANDIDATE_LOW_SUPPORT"
    if not lines or corridor is None:
        status = "BLOCKED_EMPTY_GEOMETRY"
    return {
        "patch_type_code": patch_type_code,
        "patch_status_code": status,
        "target_type_code": target_type_code,
        "target_key": target_key,
        "target_name": target_name,
        "target_payload": target_payload,
        "segment_count": len(rows),
        "unique_line_count": len(line_hashes),
        "waybill_count": len(waybill_codes),
        "route_count": len(route_codes),
        "raw_segment_length_km": round(sum(float(row.get("segment_length_km") or 0) for row in rows), 3),
        "deduped_line_length_km": round(sum(_line_length_km(line) for line in _unique_lines(lines)), 3),
        "bbox": _bbox(corridor),
        "corridor_geometry_json": mapping(corridor) if corridor is not None else None,
        "sample_line_geometries_json": [mapping(line) for line in _unique_lines(lines)[:12]],
        "source_waybill_examples": _examples(rows),
        "water_system_counts": Counter(
            name for row in rows for name in row.get("water_systems") or []
        ).most_common(12),
        "action_code": _action_code(patch_type_code, target_type_code),
    }


def _corridor(lines: list[Any], *, buffer_m: float) -> BaseGeometry | None:
    if not lines:
        return None
    try:
        return make_valid(unary_union([line.buffer(_degree_buffer(buffer_m), cap_style=2, join_style=2) for line in lines]))
    except Exception:
        return None


def _unique_lines(lines: list[Any]) -> list[Any]:
    output = []
    seen = set()
    for line in lines:
        key = _line_hash(line)
        if key in seen:
            continue
        seen.add(key)
        output.append(line)
    return output


def _line_hash(line: Any) -> str:
    coords = [(round(float(x), 5), round(float(y), 5)) for x, y in line.coords]
    return json.dumps(coords, separators=(",", ":"))


def _bbox(geometry: BaseGeometry | None) -> dict[str, float] | None:
    if geometry is None or geometry.is_empty:
        return None
    minx, miny, maxx, maxy = geometry.bounds
    return {"min_lng": round(minx, 8), "min_lat": round(miny, 8), "max_lng": round(maxx, 8), "max_lat": round(maxy, 8)}


def _examples(rows: list[dict[str, Any]], *, limit: int = 10) -> list[dict[str, Any]]:
    output = []
    seen = set()
    for row in sorted(rows, key=lambda item: float(item.get("segment_length_km") or 0), reverse=True):
        key = (row.get("waybill_code"), row.get("route_code"))
        if key in seen:
            continue
        seen.add(key)
        output.append(
            {
                "waybill_code": row.get("waybill_code"),
                "route_code": row.get("route_code"),
                "segment_length_km": row.get("segment_length_km"),
                "water_systems": row.get("water_systems") or [],
                "resolved_local_water_name": row.get("resolved_local_water_name"),
            }
        )
        if len(output) >= limit:
            break
    return output


def _action_code(patch_type_code: str, target_type_code: str) -> str:
    if patch_type_code == "BOUNDARY_PATCH":
        return "CREATE_GROUPED_BOUNDARY_PATCH_DRAFT"
    if patch_type_code == "CENTERLINE_SEED":
        return "CREATE_GROUPED_CENTERLINE_SEED_DRAFT"
    if target_type_code == "LOCAL_WATER_NAME":
        return "CREATE_OR_ALIAS_NAVIGATION_CHANNEL_THEN_REQUEUE"
    return "KEEP_AS_PATCH_EVIDENCE"


def _summary(groups: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    flat = [group for rows in groups.values() for group in rows]
    status_counts = Counter(group["patch_status_code"] for group in flat)
    return {
        "boundary_patch_group_count": len(groups["boundary_patch_groups"]),
        "seed_patch_group_count": len(groups["seed_patch_groups"]),
        "channel_or_alias_group_count": len(groups["channel_or_alias_groups"]),
        "patch_status_counts": dict(sorted(status_counts.items())),
        "ready_boundary_group_count": sum(1 for group in groups["boundary_patch_groups"] if group["patch_status_code"] == "PATCH_READY"),
        "ready_seed_group_count": sum(1 for group in groups["seed_patch_groups"] if group["patch_status_code"] == "PATCH_READY"),
        "ready_channel_or_alias_group_count": sum(
            1 for group in groups["channel_or_alias_groups"] if group["patch_status_code"] == "PATCH_READY"
        ),
        "ready_boundary_raw_segment_length_km": round(
            sum(group["raw_segment_length_km"] for group in groups["boundary_patch_groups"] if group["patch_status_code"] == "PATCH_READY"),
            3,
        ),
        "ready_seed_raw_segment_length_km": round(
            sum(group["raw_segment_length_km"] for group in groups["seed_patch_groups"] if group["patch_status_code"] == "PATCH_READY"),
            3,
        ),
        "ready_channel_or_alias_raw_segment_length_km": round(
            sum(group["raw_segment_length_km"] for group in groups["channel_or_alias_groups"] if group["patch_status_code"] == "PATCH_READY"),
            3,
        ),
    }


def _strip_geometry(group: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in group.items()
        if key not in {"corridor_geometry_json", "sample_line_geometries_json"}
    }


def _geojson(groups: dict[str, list[dict[str, Any]]], *, line_limit_per_group: int) -> dict[str, Any]:
    features = []
    for group_type, rows in groups.items():
        for group in rows:
            props = {
                key: value
                for key, value in _strip_geometry(group).items()
                if key not in {"target_payload", "source_waybill_examples", "water_system_counts"}
            }
            corridor = group.get("corridor_geometry_json")
            if isinstance(corridor, dict):
                features.append(
                    {
                        "type": "Feature",
                        "properties": {**props, "feature_role": "patch_corridor", "group_type": group_type},
                        "geometry": corridor,
                    }
                )
            for line in (group.get("sample_line_geometries_json") or [])[:line_limit_per_group]:
                if isinstance(line, dict):
                    features.append(
                        {
                            "type": "Feature",
                            "properties": {**props, "feature_role": "sample_line", "group_type": group_type},
                            "geometry": line,
                        }
                    )
    return {"type": "FeatureCollection", "features": features}


if __name__ == "__main__":
    main()
