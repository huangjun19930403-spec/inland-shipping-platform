from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WaterAreaLayerMeta:
    source_layer_code: str
    source_layer_display_name: str
    source_layer_role_code: str
    source_layer_order: int
    water_level: int | None


LAYER_META_BY_NAME: dict[str, WaterAreaLayerMeta] = {
    "一级水系": WaterAreaLayerMeta("LEVEL_1", "一级水系", "HIERARCHY_LEVEL", 1, 1),
    "二级水系": WaterAreaLayerMeta("LEVEL_2", "二级水系", "HIERARCHY_LEVEL", 2, 2),
    "三级水系": WaterAreaLayerMeta("LEVEL_3", "三级水系", "HIERARCHY_LEVEL", 3, 3),
    "四级水系": WaterAreaLayerMeta("LEVEL_4", "四级水系", "HIERARCHY_LEVEL", 4, 4),
    "五级水系": WaterAreaLayerMeta("LEVEL_5", "五级水系", "HIERARCHY_LEVEL", 5, 5),
    "六级水系": WaterAreaLayerMeta("LEVEL_6", "六级水系", "HIERARCHY_LEVEL", 6, 6),
    "七级水系": WaterAreaLayerMeta("LEVEL_7", "七级水系", "HIERARCHY_LEVEL", 7, 7),
    "rx": WaterAreaLayerMeta("RX", "全量水域面（rx）", "FULL_WATER_AREA", 80, None),
    "rx8": WaterAreaLayerMeta("RX8", "备用水域面（rx8）", "BACKUP_WATER_AREA", 90, 8),
}


def water_area_layer_meta(layer_name: str | None) -> WaterAreaLayerMeta:
    if layer_name in LAYER_META_BY_NAME:
        return LAYER_META_BY_NAME[str(layer_name)]
    return WaterAreaLayerMeta("UNKNOWN", str(layer_name or "未知图层"), "UNKNOWN", 999, None)


def water_area_layer_order(layer_name: str | None) -> int:
    return water_area_layer_meta(layer_name).source_layer_order


def water_area_layer_options() -> list[WaterAreaLayerMeta]:
    return sorted(LAYER_META_BY_NAME.values(), key=lambda item: item.source_layer_order)
