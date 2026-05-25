"""Seed real navigation water areas from compressed JSONL artifact.

This loader intentionally upserts only navigation_water_area rows. It does not
read revier.zip, does not touch seed channel boundaries, and does not create
centerlines or graph data.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, engine
from app.models import NavigationWaterArea
from app.models.base import Base
from app.modules.navigation.water_area_layers import water_area_layer_meta

PROJECT_ROOT = Path(__file__).resolve().parents[3]
NAVIGATION_WATER_AREA_SEED_FILE = PROJECT_ROOT / "scripts" / "seed_data" / "navigation" / "navigation_water_areas.jsonl.gz"
COORDINATE_SCALE = Decimal("0.000000000000001")
DEGREE_MEASURE_SCALE = Decimal("0.000000000000000001")
AREA_KM2_SCALE = Decimal("0.0001")

UPSERT_FIELDS = (
    "source_layer_code",
    "source_layer_display_name",
    "source_layer_role_code",
    "source_layer_order",
    "source_file_name",
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
)


def _iter_seed_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                rows.append(json.loads(text))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}") from exc
    return rows


def _quantize_decimal(value: Any, scale: Decimal) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value)).quantize(scale, rounding=ROUND_HALF_UP)


def _normalize_numeric_fields(payload: dict[str, Any]) -> dict[str, Any]:
    for field in (
        "bbox_min_lng",
        "bbox_min_lat",
        "bbox_max_lng",
        "bbox_max_lat",
        "center_lng",
        "center_lat",
    ):
        payload[field] = _quantize_decimal(payload.get(field), COORDINATE_SCALE)
    for field in ("shape_length_degree", "shape_area_degree"):
        payload[field] = _quantize_decimal(payload.get(field), DEGREE_MEASURE_SCALE)
    payload["area_km2"] = _quantize_decimal(payload.get("area_km2"), AREA_KM2_SCALE)
    return payload


def _normalize_layer_fields(payload: dict[str, Any]) -> dict[str, Any]:
    meta = water_area_layer_meta(payload.get("source_layer_name"))
    payload.setdefault("source_layer_code", meta.source_layer_code)
    payload.setdefault("source_layer_display_name", meta.source_layer_display_name)
    payload.setdefault("source_layer_role_code", meta.source_layer_role_code)
    payload.setdefault("source_layer_order", meta.source_layer_order)
    payload.setdefault("source_file_name", None)
    payload.setdefault("has_attributes", True)
    payload.setdefault("raw_properties_json", None)
    return payload


async def _prepare_schema() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def seed_navigation_water_areas(
    path: Path = NAVIGATION_WATER_AREA_SEED_FILE,
    *,
    session_factory: Callable[[], AsyncIterator[AsyncSession]] = AsyncSessionLocal,
    prepare_schema: bool = True,
) -> dict[str, int]:
    if prepare_schema:
        await _prepare_schema()
    rows = _iter_seed_rows(path)
    source_codes = sorted({str(row["source_code"]) for row in rows})
    async with session_factory() as session:
        existing_rows = list(
            (
                await session.execute(
                    select(NavigationWaterArea).where(NavigationWaterArea.source_code.in_(source_codes))
                )
            ).scalars()
        )
        existing = {
            (row.source_code, row.source_layer_name, row.source_object_id): row
            for row in existing_rows
        }
        created = 0
        updated = 0
        for payload in rows:
            payload = _normalize_layer_fields(payload)
            payload = _normalize_numeric_fields(payload)
            key = (payload["source_code"], payload["source_layer_name"], str(payload["source_object_id"]))
            record = existing.get(key)
            if record is None:
                session.add(NavigationWaterArea(**payload))
                created += 1
                continue
            for field in UPSERT_FIELDS:
                setattr(record, field, payload.get(field))
            updated += 1
        await session.commit()
    return {"created": created, "updated": updated, "total": len(rows)}


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Seed navigation water areas from compressed JSONL.")
    parser.add_argument("--input", type=Path, default=NAVIGATION_WATER_AREA_SEED_FILE)
    args = parser.parse_args()
    result = await seed_navigation_water_areas(args.input)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
