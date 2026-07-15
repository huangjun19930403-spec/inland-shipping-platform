"""Build missing-channel candidates from waybill reference rows.

This is intentionally non-publishing. Some route labels contain multiple water
systems, so candidate geometry must be split before it can become channel seed.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, mapping, shape


REPORT_DIR = Path("runtime/navigation-production/reports")
DEFAULT_JSONL = REPORT_DIR / "waybill_route_reference_candidates_constraints_20260608.jsonl"
DEFAULT_CONSTRAINTS = REPORT_DIR / "waybill_observed_channel_constraints_applied_20260608.json"


def _line(geometry_json: dict[str, Any] | None) -> LineString | None:
    if not isinstance(geometry_json, dict):
        return None
    try:
        geometry = shape(geometry_json)
    except Exception:
        return None
    return geometry if isinstance(geometry, LineString) and len(geometry.coords) >= 2 else None


def _bbox(lines: list[LineString]) -> dict[str, float] | None:
    if not lines:
        return None
    minx = min(line.bounds[0] for line in lines)
    miny = min(line.bounds[1] for line in lines)
    maxx = max(line.bounds[2] for line in lines)
    maxy = max(line.bounds[3] for line in lines)
    return {"min_lng": round(minx, 8), "min_lat": round(miny, 8), "max_lng": round(maxx, 8), "max_lat": round(maxy, 8)}


def _read_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _feature(row: dict[str, Any], water_name: str, line: LineString) -> dict[str, Any]:
    metrics = row.get("track_metrics") or {}
    return {
        "type": "Feature",
        "geometry": mapping(line),
        "properties": {
            "water_system_name": water_name,
            "waybill_code": row.get("waybill_code"),
            "route_code": row.get("route_code"),
            "route_name": row.get("route_name"),
            "quality_code": row.get("quality_code"),
            "quality_score": row.get("quality_score"),
            "line_length_km": metrics.get("line_length_km"),
            "max_segment_km": metrics.get("max_segment_km"),
            "endpoint_max_offset_km": metrics.get("endpoint_max_offset_km"),
            "water_systems": row.get("water_systems") or [],
            "candidate_status_code": "NEEDS_SEGMENT_LEVEL_SPLIT",
        },
    }


def build(*, jsonl: Path, constraints: Path, output: Path, geojson_output: Path) -> dict[str, Any]:
    rows = _read_rows(jsonl)
    constraints_report = json.loads(constraints.read_text(encoding="utf-8"))
    blocked_names = [item["water_system_name"] for item in constraints_report.get("blocked_water_systems", [])]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        water_systems = row.get("water_systems") or []
        for water_name in blocked_names:
            if water_name in water_systems:
                grouped[water_name].append(row)

    candidates = []
    features = []
    for water_name in blocked_names:
        water_rows = grouped.get(water_name, [])
        geometry_rows = []
        lines = []
        for row in water_rows:
            metrics = row.get("track_metrics") or {}
            line = _line(row.get("geometry_json"))
            if line is None or not metrics.get("usable_as_geometry_reference"):
                continue
            geometry_rows.append(row)
            lines.append(line)
            features.append(_feature(row, water_name, line))
        combo_counter = Counter(" + ".join(row.get("water_systems") or []) for row in water_rows)
        route_counter = Counter(row.get("route_name") or "-" for row in geometry_rows)
        candidate_status = "NEEDS_SEGMENT_LEVEL_SPLIT" if any(len(row.get("water_systems") or []) > 1 for row in geometry_rows) else "MISSING_CHANNEL_GEOMETRY_REFERENCE_READY"
        candidates.append(
            {
                "water_system_name": water_name,
                "candidate_status_code": candidate_status,
                "row_count": len(water_rows),
                "geometry_reference_count": len(geometry_rows),
                "condition_reference_count": sum(1 for row in water_rows if (row.get("track_metrics") or {}).get("usable_as_condition_reference")),
                "bbox": _bbox(lines),
                "water_system_combo_counts": combo_counter.most_common(8),
                "top_geometry_routes": route_counter.most_common(8),
                "observed_max_tonnage": max((row.get("tonnage_max") or 0 for row in water_rows), default=0),
                "observed_max_ship_width_m": max((row.get("ship_width_max_m") or 0 for row in water_rows), default=0),
                "observed_max_ship_length_m": max((row.get("ship_length_max_m") or 0 for row in water_rows), default=0),
                "recommended_next_actions": [
                    "Split route-level tracks into segment-level water-system sections before creating centerline seed.",
                    "Create or extend the missing NavigationChannel only after segment-level geometry is isolated.",
                    "Build boundary buffer candidates from isolated segment geometry and validate against local water polygons before graph publish.",
                ],
            }
        )

    report = {
        "report_version": "waybill-missing-channel-candidates-v1",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "source_jsonl": str(jsonl),
        "source_constraints_report": str(constraints),
        "summary": {
            "blocked_water_system_count": len(blocked_names),
            "candidate_count": len(candidates),
            "geojson_feature_count": len(features),
        },
        "candidates": candidates,
        "guardrails": [
            "Do not publish route-level multi-water-system geometry as one channel centerline.",
            "Observed waybill constraints are not official grade/capacity.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    geojson_output.parent.mkdir(parents=True, exist_ok=True)
    geojson_output.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jsonl", type=Path, default=DEFAULT_JSONL)
    parser.add_argument("--constraints", type=Path, default=DEFAULT_CONSTRAINTS)
    parser.add_argument("--output", type=Path, default=REPORT_DIR / "waybill_missing_channel_candidates_20260608.json")
    parser.add_argument("--geojson-output", type=Path, default=REPORT_DIR / "waybill_missing_channel_candidates_20260608.geojson")
    args = parser.parse_args()
    report = build(jsonl=args.jsonl, constraints=args.constraints, output=args.output, geojson_output=args.geojson_output)
    print(json.dumps(report["summary"], ensure_ascii=False))
    print(args.output)
    print(args.geojson_output)


if __name__ == "__main__":
    main()
