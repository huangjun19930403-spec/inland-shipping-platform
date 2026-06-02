from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any, Callable

from pyproj import CRS

from app.modules.navigation.production_pipeline.constants import REVIER_SOURCE_CODE, SOURCE_LAYERS
from app.modules.navigation.production_pipeline.types import LayerSourceStats
from app.modules.navigation.production_pipeline.water_area_normalizer import normalize_water_area_payload
from scripts.navigation.import_river_shapefile import (
    _index_zip_shapefiles,
    _zip_component,
    iter_zip_layer_rows,
)


WaterAreaSink = Callable[[dict[str, Any]], None]


def _crs_summary(archive: zipfile.ZipFile, shp_entry: str) -> tuple[str, bool]:
    names = set(archive.namelist())
    prj_entry = _zip_component(names, shp_entry[:-4], "prj")
    if not prj_entry:
        return "EPSG:4326", True
    try:
        crs = CRS.from_wkt(archive.read(prj_entry).decode("utf-8", errors="ignore"))
        epsg = crs.to_epsg()
        return (f"EPSG:{epsg}" if epsg else crs.to_string(), False)
    except Exception:
        return "EPSG:4326", True


def read_revier_zip_to_sink(
    *,
    source_zip: Path,
    sink: WaterAreaSink,
    source_code: str = REVIER_SOURCE_CODE,
    layers: tuple[str, ...] = SOURCE_LAYERS,
    limit_per_layer: int | None = None,
    low_value_area_km2: float = 0.001,
) -> dict[str, Any]:
    if not source_zip.exists():
        raise FileNotFoundError(f"revier.zip not found: {source_zip}")
    layer_stats: list[LayerSourceStats] = []
    with zipfile.ZipFile(source_zip) as archive:
        shapefiles = _index_zip_shapefiles(archive)
        for layer_name in layers:
            shp_entry = shapefiles.get(layer_name)
            stats = LayerSourceStats(layer_name=layer_name)
            layer_stats.append(stats)
            if shp_entry is None:
                continue
            stats.source_file_name = Path(shp_entry).name
            stats.crs_code, stats.crs_missing = _crs_summary(archive, shp_entry)
            for row in iter_zip_layer_rows(
                archive=archive,
                shp_entry=shp_entry,
                source_code=source_code,
                layer_name=layer_name,
                limit=limit_per_layer,
                low_value_area_km2=low_value_area_km2,
            ):
                payload = normalize_water_area_payload(row)
                geometry_type = str((payload.get("geometry_json") or {}).get("type") or "UNKNOWN")
                stats.geometry_type_counts[geometry_type] = stats.geometry_type_counts.get(geometry_type, 0) + 1
                stats.feature_count += 1
                if payload.get("geometry_status_code") == "REPAIRED":
                    stats.repaired_count += 1
                elif payload.get("geometry_status_code") == "INVALID":
                    stats.invalid_count += 1
                else:
                    stats.valid_count += 1
                if payload.get("is_low_value"):
                    stats.low_value_count += 1
                stats.include_bbox(
                    min_lng=payload.get("bbox_min_lng"),
                    min_lat=payload.get("bbox_min_lat"),
                    max_lng=payload.get("bbox_max_lng"),
                    max_lat=payload.get("bbox_max_lat"),
                )
                sink(payload)
    return {
        "source_zip": str(source_zip),
        "source_code": source_code,
        "layers": [item.as_dict() for item in layer_stats],
        "totals": {
            "layer_count": len(layer_stats),
            "feature_count": sum(item.feature_count for item in layer_stats),
            "valid_count": sum(item.valid_count for item in layer_stats),
            "repaired_count": sum(item.repaired_count for item in layer_stats),
            "invalid_count": sum(item.invalid_count for item in layer_stats),
            "low_value_count": sum(item.low_value_count for item in layer_stats),
            "crs_missing_layer_count": sum(1 for item in layer_stats if item.crs_missing),
        },
    }
