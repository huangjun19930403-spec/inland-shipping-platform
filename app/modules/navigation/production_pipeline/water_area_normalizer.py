from __future__ import annotations

from typing import Any

from app.modules.navigation.production_pipeline.constants import (
    LAYER_CODE_OVERRIDES,
    RIVER_TYPES_ROUTING_ENABLED,
)
from scripts.navigation.import_river_shapefile import WaterAreaRow


def classify_water_type(name: str | None, remark: str | None, source_layer_name: str | None = None) -> str:
    text = f"{name or ''} {remark or ''} {source_layer_name or ''}"
    if "常年双线河" in text or "双线河" in text:
        return "PERENNIAL_DOUBLE_LINE_RIVER"
    if "常年单线河" in text or "单线河" in text:
        return "PERENNIAL_SINGLE_LINE_RIVER"
    if any(token in text for token in ("运河", "漕河", "渠道", "灌渠", "干渠", "支渠")):
        return "CANAL"
    if any(token in text for token in ("水库", "库区")):
        return "RESERVOIR"
    if any(token in text for token in ("湖", "荡", "淀", "泡", "海子", "淖尔")):
        return "LAKE"
    if any(token in text for token in ("季节", "时令", "间歇")):
        return "SEASONAL_RIVER"
    if any(token in text for token in ("海岸", "岸线")):
        return "COASTLINE"
    if any(token in text for token in ("养殖", "鱼塘", "虾塘")):
        return "AQUACULTURE"
    if any(token in text for token in ("江", "河", "溪", "水道", "涌", "港")):
        return "PERENNIAL_DOUBLE_LINE_RIVER"
    return "UNKNOWN"


def routing_candidate_flag(payload: dict[str, Any]) -> bool:
    if payload.get("geometry_status_code") == "INVALID":
        return False
    if bool(payload.get("is_low_value")):
        return False
    water_type = str(payload.get("water_type_code") or "UNKNOWN").upper()
    if water_type not in RIVER_TYPES_ROUTING_ENABLED:
        return False
    area_km2 = payload.get("area_km2")
    try:
        if area_km2 is not None and float(area_km2) < 0.001:
            return False
    except (TypeError, ValueError):
        return False
    return True


def normalize_water_area_payload(row: WaterAreaRow) -> dict[str, Any]:
    payload = row.model_payload()
    source_layer_name = str(payload.get("source_layer_name") or "")
    payload["source_layer_code"] = LAYER_CODE_OVERRIDES.get(source_layer_name, payload.get("source_layer_code"))
    payload["source_file_name"] = payload.get("source_file_name") or f"{source_layer_name}.shp"
    payload["water_type_code"] = classify_water_type(
        payload.get("water_name"),
        payload.get("remark"),
        source_layer_name,
    )
    payload["routing_candidate_flag"] = routing_candidate_flag(payload)
    raw = dict(payload.get("raw_properties_json") or {})
    raw.setdefault("source_layer_name", source_layer_name)
    raw.setdefault("source_file_name", payload.get("source_file_name"))
    raw.setdefault("routing_candidate_flag", payload["routing_candidate_flag"])
    raw.setdefault("normalizer", "navigation_revier_production_pipeline")
    payload["raw_properties_json"] = raw
    return payload

