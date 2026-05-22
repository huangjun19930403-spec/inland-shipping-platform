"""Export imported real water areas as compressed production seed artifact."""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import NavigationWaterArea

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "scripts" / "seed_data" / "navigation" / "navigation_water_areas.jsonl.gz"
DEFAULT_MANIFEST = PROJECT_ROOT / "scripts" / "seed_data" / "navigation" / "navigation_water_areas_manifest.json"
DEFAULT_SOURCE_CODE = "RIVER_SHAPEFILE_2026"

LAYER_ORDER = {
    "rx": 0,
    "一级水系": 1,
    "二级水系": 2,
    "三级水系": 3,
    "四级水系": 4,
    "五级水系": 5,
    "六级水系": 6,
    "七级水系": 7,
    "rx8": 8,
}


def _float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _layer_order(name: str | None) -> int:
    return LAYER_ORDER.get(str(name or ""), 99)


def _row_payload(row: NavigationWaterArea) -> dict[str, Any]:
    return {
        "source_code": row.source_code,
        "source_layer_name": row.source_layer_name,
        "source_object_id": row.source_object_id,
        "water_name": row.water_name,
        "normalized_water_name": row.normalized_water_name,
        "alias_names": row.alias_names,
        "water_level": row.water_level,
        "water_type_code": row.water_type_code,
        "remark": row.remark,
        "geometry_json": row.geometry_json,
        "geometry_status_code": row.geometry_status_code,
        "simplified_geometry_low_json": row.simplified_geometry_low_json,
        "simplified_geometry_mid_json": row.simplified_geometry_mid_json,
        "simplified_geometry_high_json": row.simplified_geometry_high_json,
        "bbox_min_lng": _float(row.bbox_min_lng),
        "bbox_min_lat": _float(row.bbox_min_lat),
        "bbox_max_lng": _float(row.bbox_max_lng),
        "bbox_max_lat": _float(row.bbox_max_lat),
        "center_lng": _float(row.center_lng),
        "center_lat": _float(row.center_lat),
        "shape_length_degree": _float(row.shape_length_degree),
        "shape_area_degree": _float(row.shape_area_degree),
        "area_km2": _float(row.area_km2),
        "is_low_value": bool(row.is_low_value),
        "is_enabled": bool(row.is_enabled),
    }


async def export_navigation_water_area_seed(
    *,
    source_code: str = DEFAULT_SOURCE_CODE,
    output_path: Path = DEFAULT_OUTPUT,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        rows = list(
            (
                await session.execute(
                    select(NavigationWaterArea)
                    .where(NavigationWaterArea.source_code == source_code)
                    .order_by(NavigationWaterArea.source_layer_name, NavigationWaterArea.source_object_id)
                )
            ).scalars()
        )

    rows.sort(key=lambda row: (_layer_order(row.source_layer_name), row.source_layer_name, row.source_object_id, row.id))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    layer_counts: Counter[str] = Counter()
    named_count = 0
    bbox = {"min_lng": None, "min_lat": None, "max_lng": None, "max_lat": None}

    with gzip.open(output_path, "wt", encoding="utf-8") as handle:
        for row in rows:
            payload = _row_payload(row)
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
            layer_counts[row.source_layer_name] += 1
            if row.water_name:
                named_count += 1
            if row.bbox_min_lng is not None:
                bbox["min_lng"] = _float(row.bbox_min_lng) if bbox["min_lng"] is None else min(float(bbox["min_lng"]), float(row.bbox_min_lng))
                bbox["min_lat"] = _float(row.bbox_min_lat) if bbox["min_lat"] is None else min(float(bbox["min_lat"]), float(row.bbox_min_lat))
                bbox["max_lng"] = _float(row.bbox_max_lng) if bbox["max_lng"] is None else max(float(bbox["max_lng"]), float(row.bbox_max_lng))
                bbox["max_lat"] = _float(row.bbox_max_lat) if bbox["max_lat"] is None else max(float(bbox["max_lat"]), float(row.bbox_max_lat))

    manifest = {
        "version": "navigation_water_areas_seed_v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_code": source_code,
        "artifact": str(output_path.relative_to(PROJECT_ROOT)),
        "record_count": len(rows),
        "named_record_count": named_count,
        "layer_counts": dict(sorted(layer_counts.items(), key=lambda item: _layer_order(item[0]))),
        "bbox": bbox,
        "notes": [
            "This seed artifact is produced from navigation_water_area and replaces runtime revier.zip extraction for local/production seeding.",
            "It contains raw water-area assets only; it must not overwrite seed channel boundaries or create centerlines/graph edges.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export navigation_water_area rows into compressed seed JSONL.")
    parser.add_argument("--source-code", default=DEFAULT_SOURCE_CODE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    manifest = await export_navigation_water_area_seed(
        source_code=args.source_code,
        output_path=args.output,
        manifest_path=args.manifest,
    )
    print(json.dumps({"record_count": manifest["record_count"], "artifact": manifest["artifact"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
