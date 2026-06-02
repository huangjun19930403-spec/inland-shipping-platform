from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.modules.navigation.production_pipeline.constants import (
    DEFAULT_SEED_DIR,
    REVIER_SEED_PREFIX,
    REVIER_SOURCE_CODE,
)
from app.modules.navigation.production_pipeline.source_reader import read_revier_zip_to_sink


WATER_AREA_SEED_FIELDS = {
    "source_code",
    "source_layer_name",
    "source_layer_code",
    "source_layer_display_name",
    "source_layer_role_code",
    "source_layer_order",
    "source_file_name",
    "source_object_id",
    "has_attributes",
    "raw_properties_json",
    "water_name",
    "normalized_water_name",
    "alias_names",
    "water_level",
    "water_type_code",
    "remark",
    "geometry_json",
    "geometry_status_code",
    "simplified_geometry_low_json",
    "simplified_geometry_mid_json",
    "simplified_geometry_high_json",
    "bbox_min_lng",
    "bbox_min_lat",
    "bbox_max_lng",
    "bbox_max_lat",
    "center_lng",
    "center_lat",
    "shape_length_degree",
    "shape_area_degree",
    "area_km2",
    "is_low_value",
    "is_enabled",
}


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _water_area_seed_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: payload.get(key) for key in WATER_AREA_SEED_FIELDS}


def export_revier_water_area_seed(
    *,
    source_zip: Path,
    seed_dir: Path = DEFAULT_SEED_DIR,
    source_code: str = REVIER_SOURCE_CODE,
    limit_per_layer: int | None = None,
) -> dict[str, Any]:
    seed_dir.mkdir(parents=True, exist_ok=True)
    prod_path = seed_dir / f"navigation_water_areas.{REVIER_SEED_PREFIX}.jsonl.gz"
    default_path = seed_dir / "navigation_water_areas.jsonl.gz"
    manifest_path = seed_dir / "navigation_water_areas_manifest.json"
    prod_manifest_path = seed_dir / f"navigation_water_areas.{REVIER_SEED_PREFIX}.manifest.json"

    row_count = 0
    routing_candidate_count = 0
    with gzip.open(prod_path, "wt", encoding="utf-8") as prod_handle, gzip.open(default_path, "wt", encoding="utf-8") as default_handle:
        def sink(payload: dict[str, Any]) -> None:
            nonlocal row_count, routing_candidate_count
            row_count += 1
            if payload.get("routing_candidate_flag"):
                routing_candidate_count += 1
            text = json.dumps(_water_area_seed_payload(payload), ensure_ascii=False, separators=(",", ":"))
            prod_handle.write(text)
            prod_handle.write("\n")
            default_handle.write(text)
            default_handle.write("\n")

        source_report = read_revier_zip_to_sink(
            source_zip=source_zip,
            source_code=source_code,
            sink=sink,
            limit_per_layer=limit_per_layer,
        )

    manifest = {
        "version": "navigation_water_areas_revier_prod_v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_code": source_code,
        "artifact": str(default_path.relative_to(seed_dir.parents[2])),
        "production_artifact": str(prod_path.relative_to(seed_dir.parents[2])),
        "record_count": row_count,
        "routing_candidate_count": routing_candidate_count,
        "layer_counts": {
            item["layer_name"]: item["feature_count"]
            for item in source_report["layers"]
        },
        "enabled_layer_counts": {
            item["layer_name"]: item["valid_count"] + item["repaired_count"]
            for item in source_report["layers"]
        },
        "invalid_layer_counts": {
            item["layer_name"]: item["invalid_count"]
            for item in source_report["layers"]
        },
        "bbox": _bbox_from_source_report(source_report),
        "notes": [
            "Generated from revier.zip by scripts.navigation.build_revier_production_seed.",
            "Raw revier.zip is not part of production seed.",
            "routing_candidate_flag is retained inside raw_properties_json for audit but not stored as a navigation_water_area column.",
        ],
    }
    write_json(manifest_path, manifest)
    write_json(prod_manifest_path, manifest)
    source_report["water_area_seed_path"] = str(prod_path)
    source_report["default_water_area_seed_path"] = str(default_path)
    source_report["routing_candidate_count"] = routing_candidate_count
    return source_report


def _bbox_from_source_report(source_report: dict[str, Any]) -> dict[str, float | None]:
    boxes = [item.get("bbox") or {} for item in source_report.get("layers") or []]
    min_lng_values = [box["min_lng"] for box in boxes if box.get("min_lng") is not None]
    min_lat_values = [box["min_lat"] for box in boxes if box.get("min_lat") is not None]
    max_lng_values = [box["max_lng"] for box in boxes if box.get("max_lng") is not None]
    max_lat_values = [box["max_lat"] for box in boxes if box.get("max_lat") is not None]
    return {
        "min_lng": min(min_lng_values) if min_lng_values else None,
        "min_lat": min(min_lat_values) if min_lat_values else None,
        "max_lng": max(max_lng_values) if max_lng_values else None,
        "max_lat": max(max_lat_values) if max_lat_values else None,
    }
