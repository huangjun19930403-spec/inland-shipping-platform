"""Audit revier.zip, navigation_water_area, and compressed water-area seed.

This script is read-only for databases. It writes only the requested JSON
audit report and never changes channel boundaries, matches, centerlines, graph
data, route results, or system configuration.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import io
import json
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import shapefile
from sqlalchemy import String, case, func, select

from app.core.database import AsyncSessionLocal
from app.models import NavigationWaterArea
from app.modules.navigation.water_area_layers import water_area_layer_meta, water_area_layer_order

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REVIER_ZIP = Path("/Users/hj/Documents/河道数据/revier.zip")
DEFAULT_SEED = PROJECT_ROOT / "scripts" / "seed_data" / "navigation" / "navigation_water_areas.jsonl.gz"
DEFAULT_MANIFEST = PROJECT_ROOT / "scripts" / "seed_data" / "navigation" / "navigation_water_areas_manifest.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "data_audit" / "navigation_water_area_asset_audit.json"
DEFAULT_SOURCE_CODE = "RIVER_SHAPEFILE_2026"


def _component(names: set[str], base: str, suffix: str) -> str | None:
    suffix = suffix.lstrip(".")
    candidates = (f"{base}.{suffix}", f"{base}..{suffix}")
    for candidate in candidates:
        if candidate in names:
            return candidate
    return None


def _zip_layers(zip_path: Path) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        for shp_name in sorted(name for name in names if name.lower().endswith(".shp")):
            base = shp_name[:-4]
            layer_name = Path(base).name
            shx_name = _component(names, base, "shx")
            dbf_name = _component(names, base, "dbf")
            reader_kwargs: dict[str, Any] = {"shp": io.BytesIO(archive.read(shp_name))}
            if shx_name:
                reader_kwargs["shx"] = io.BytesIO(archive.read(shx_name))
            if dbf_name:
                reader_kwargs["dbf"] = io.BytesIO(archive.read(dbf_name))
            try:
                reader = shapefile.Reader(**reader_kwargs, encoding="utf-8")
                fields = [field[0] for field in reader.fields[1:]]
                named_count = 0
                geom_counts: Counter[str] = Counter()
                if dbf_name:
                    iterator = reader.iterShapeRecords()
                    for item in iterator:
                        geom_counts[item.shape.shapeTypeName] += 1
                        value = item.record.as_dict().get("NAME")
                        if value not in (None, ""):
                            named_count += 1
                else:
                    for item in reader.iterShapes():
                        geom_counts[item.shapeTypeName] += 1
                output[layer_name] = {
                    "source_file": shp_name,
                    "records": len(reader),
                    "named_count": named_count,
                    "fields": fields,
                    "has_dbf": bool(dbf_name),
                    "dbf_file": dbf_name,
                    "bbox": list(reader.bbox),
                    "geometry_counts": dict(geom_counts),
                }
            except Exception as exc:
                output[layer_name] = {"source_file": shp_name, "error": str(exc)}
    return dict(sorted(output.items(), key=lambda item: water_area_layer_order(item[0])))


async def _db_layers(source_code: str) -> dict[str, dict[str, Any]]:
    name_text = func.coalesce(NavigationWaterArea.water_name, "")
    canal_name = (
        name_text.like("%运河%")
        | name_text.like("%漕河%")
        | name_text.like("%渠道%")
        | name_text.like("%干渠%")
        | name_text.like("%支渠%")
    )
    double_line_natural_misclass = (
        NavigationWaterArea.remark.like("%双线河%")
        & (NavigationWaterArea.water_type_code == "CANAL")
        & ~canal_name
    )
    recoverable_geometry_collection = (
        (NavigationWaterArea.geometry_status_code == "INVALID")
        & (NavigationWaterArea.geometry_json.cast(String).like('%"type": "GeometryCollection"%'))
        & (NavigationWaterArea.geometry_json.cast(String).like("%Polygon%"))
    )
    async with AsyncSessionLocal() as session:
        rows = list(
            (
                await session.execute(
                    select(
                        NavigationWaterArea.source_layer_name,
                        func.count(),
                        func.sum(case((NavigationWaterArea.is_enabled.is_(True), 1), else_=0)),
                        func.sum(case((NavigationWaterArea.is_enabled.is_(False), 1), else_=0)),
                        func.sum(case((NavigationWaterArea.water_name.is_not(None), 1), else_=0)),
                        func.sum(case((NavigationWaterArea.remark.like("%双线河%"), 1), else_=0)),
                        func.sum(case((double_line_natural_misclass, 1), else_=0)),
                        func.sum(case((recoverable_geometry_collection, 1), else_=0)),
                    )
                    .where(NavigationWaterArea.source_code == source_code)
                    .group_by(NavigationWaterArea.source_layer_name)
                )
            ).all()
        )
    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        layer_name = str(row[0])
        meta = water_area_layer_meta(layer_name)
        output[layer_name] = {
            "count": int(row[1] or 0),
            "enabled_count": int(row[2] or 0),
            "invalid_count": int(row[3] or 0),
            "named_count": int(row[4] or 0),
            "double_line_river_count": int(row[5] or 0),
            "double_line_river_as_canal_count": int(row[6] or 0),
            "recoverable_geometry_collection_count": int(row[7] or 0),
            "source_layer_display_name": meta.source_layer_display_name,
            "source_layer_role_code": meta.source_layer_role_code,
            "source_layer_order": meta.source_layer_order,
        }
    return dict(sorted(output.items(), key=lambda item: water_area_layer_order(item[0])))


async def _major_water_status(source_code: str) -> list[dict[str, Any]]:
    major_names = ["长江", "金沙江", "澜沧江", "黄河", "西江", "乌江", "红水河"]
    async with AsyncSessionLocal() as session:
        rows = list(
            (
                await session.execute(
                    select(
                        NavigationWaterArea.water_name,
                        NavigationWaterArea.source_layer_name,
                        func.count(),
                        func.sum(case((NavigationWaterArea.is_enabled.is_(True), 1), else_=0)),
                        func.sum(case((NavigationWaterArea.geometry_status_code == "REPAIRED", 1), else_=0)),
                        func.sum(case((NavigationWaterArea.geometry_status_code == "INVALID", 1), else_=0)),
                        func.min(NavigationWaterArea.bbox_min_lng),
                        func.min(NavigationWaterArea.bbox_min_lat),
                        func.max(NavigationWaterArea.bbox_max_lng),
                        func.max(NavigationWaterArea.bbox_max_lat),
                    )
                    .where(
                        NavigationWaterArea.source_code == source_code,
                        NavigationWaterArea.water_name.in_(major_names),
                    )
                    .group_by(NavigationWaterArea.water_name, NavigationWaterArea.source_layer_name)
                    .order_by(NavigationWaterArea.water_name, func.min(NavigationWaterArea.source_layer_order))
                )
            ).all()
        )
    return [
        {
            "water_name": str(row[0]),
            "source_layer_name": str(row[1]),
            "record_count": int(row[2] or 0),
            "enabled_count": int(row[3] or 0),
            "repaired_count": int(row[4] or 0),
            "invalid_count": int(row[5] or 0),
            "bbox": {
                "min_lng": float(row[6]) if row[6] is not None else None,
                "min_lat": float(row[7]) if row[7] is not None else None,
                "max_lng": float(row[8]) if row[8] is not None else None,
                "max_lat": float(row[9]) if row[9] is not None else None,
            },
        }
        for row in rows
    ]


def _seed_layers(seed_path: Path, manifest_path: Path) -> dict[str, Any]:
    layer_counts: Counter[str] = Counter()
    if seed_path.exists():
        with gzip.open(seed_path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    payload = json.loads(line)
                    layer_counts[str(payload.get("source_layer_name"))] += 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    return {
        "artifact": str(seed_path),
        "manifest": manifest,
        "layer_counts_from_jsonl": dict(sorted(layer_counts.items(), key=lambda item: water_area_layer_order(item[0]))),
    }


async def audit_water_area_assets(
    *,
    revier_zip: Path = DEFAULT_REVIER_ZIP,
    seed_path: Path = DEFAULT_SEED,
    manifest_path: Path = DEFAULT_MANIFEST,
    output_path: Path = DEFAULT_OUTPUT,
    source_code: str = DEFAULT_SOURCE_CODE,
) -> dict[str, Any]:
    zip_layers = _zip_layers(revier_zip)
    db_layers = await _db_layers(source_code)
    major_water_status = await _major_water_status(source_code)
    seed_layers = _seed_layers(seed_path, manifest_path)
    layer_names = sorted(set(zip_layers) | set(db_layers), key=water_area_layer_order)
    layer_comparison = []
    issues: list[str] = []
    for layer_name in layer_names:
        zip_count = int(zip_layers.get(layer_name, {}).get("records") or 0)
        db_count = int(db_layers.get(layer_name, {}).get("count") or 0)
        missing_count = max(zip_count - db_count, 0)
        if missing_count:
            issues.append(f"{layer_name}: DB 缺失 {missing_count} 条")
        if db_layers.get(layer_name, {}).get("double_line_river_as_canal_count"):
            issues.append(f"{layer_name}: 存在双线河误判为 CANAL")
        if db_layers.get(layer_name, {}).get("recoverable_geometry_collection_count"):
            issues.append(f"{layer_name}: 存在可恢复 GeometryCollection 未提取面")
        layer_comparison.append(
            {
                "layer_name": layer_name,
                "display_name": water_area_layer_meta(layer_name).source_layer_display_name,
                "zip_count": zip_count,
                "db_count": db_count,
                "db_enabled_count": int(db_layers.get(layer_name, {}).get("enabled_count") or 0),
                "db_invalid_count": int(db_layers.get(layer_name, {}).get("invalid_count") or 0),
                "zip_named_count": int(zip_layers.get(layer_name, {}).get("named_count") or 0),
                "db_named_count": int(db_layers.get(layer_name, {}).get("named_count") or 0),
                "missing_count": missing_count,
                "double_line_river_as_canal_count": int(db_layers.get(layer_name, {}).get("double_line_river_as_canal_count") or 0),
                "recoverable_geometry_collection_count": int(db_layers.get(layer_name, {}).get("recoverable_geometry_collection_count") or 0),
            }
        )
    named_major_water_disabled_count = sum(
        int(item["invalid_count"])
        for item in major_water_status
        if item["water_name"] in {"长江", "金沙江", "澜沧江", "黄河"}
    )
    if named_major_water_disabled_count:
        issues.append(f"主干水系仍有 {named_major_water_disabled_count} 条禁用/invalid 记录")
    report = {
        "source_code": source_code,
        "revier_zip": str(revier_zip),
        "seed": seed_layers,
        "layers": layer_comparison,
        "summary": {
            "recoverable_geometry_collection_count": sum(
                int(layer.get("recoverable_geometry_collection_count") or 0) for layer in db_layers.values()
            ),
            "remaining_invalid_count": sum(int(layer.get("invalid_count") or 0) for layer in db_layers.values()),
            "named_major_water_disabled_count": named_major_water_disabled_count,
        },
        "major_water_status": major_water_status,
        "issues": issues,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit revier.zip against navigation_water_area and seed artifact.")
    parser.add_argument("--input", type=Path, default=DEFAULT_REVIER_ZIP)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source-code", default=DEFAULT_SOURCE_CODE)
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    report = await audit_water_area_assets(
        revier_zip=args.input,
        seed_path=args.seed,
        manifest_path=args.manifest,
        output_path=args.output,
        source_code=args.source_code,
    )
    print(json.dumps({"layers": len(report["layers"]), "issues": report["issues"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
