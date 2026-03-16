"""
区域工具函数
包含：区域编码自动生成、边界质心计算、点在多边形内判断（自动圈城市）

所有函数均为纯函数（无 I/O），易于单元测试。
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 区域编码前缀
_REGION_CODE_PREFIX = "RG"


# ─────────────────────────────────────────────────────────
# 编码生成
# ─────────────────────────────────────────────────────────

def generate_region_code(max_code: Optional[str]) -> str:
    """
    依据当前最大编码生成下一个区域编码，格式 RG-NNN。

    Args:
        max_code: 已存在的最大编码（如 "RG-007"），None 表示库中尚无记录。

    Returns:
        新编码，如 "RG-008"。
    """
    if max_code is None:
        seq = 1
    else:
        try:
            seq = int(max_code.split("-")[-1]) + 1
        except (ValueError, IndexError, AttributeError):
            logger.warning("无法解析区域编码 %r，序号从 1 开始", max_code)
            seq = 1
    return f"{_REGION_CODE_PREFIX}-{seq:03d}"


# ─────────────────────────────────────────────────────────
# 几何计算
# ─────────────────────────────────────────────────────────

def compute_centroid(coordinates: list) -> tuple[float, float]:
    """
    计算多边形顶点的算术均值作为区域中心坐标。

    Args:
        coordinates: [[lng, lat], ...] 格式的顶点列表。

    Returns:
        (center_longitude, center_latitude) 元组；输入为空时返回 (0.0, 0.0)。
    """
    if not coordinates:
        return 0.0, 0.0
    valid = [(float(pt[0]), float(pt[1])) for pt in coordinates if len(pt) >= 2]
    if not valid:
        return 0.0, 0.0
    center_lng = sum(p[0] for p in valid) / len(valid)
    center_lat = sum(p[1] for p in valid) / len(valid)
    return center_lng, center_lat


def point_in_polygon(lng: float, lat: float, polygon: list) -> bool:
    """
    射线法判断点 (lng, lat) 是否在多边形内部（含边界）。

    Args:
        lng:     待测点经度。
        lat:     待测点纬度。
        polygon: [[lng, lat], ...] 格式的多边形顶点列表（首尾可相同，自动闭合）。

    Returns:
        True 表示点在多边形内或边界上。
    """
    if not polygon or len(polygon) < 3:
        return False

    n = len(polygon)
    inside = False
    px, py = float(lng), float(lat)

    j = n - 1
    for i in range(n):
        xi, yi = float(polygon[i][0]), float(polygon[i][1])
        xj, yj = float(polygon[j][0]), float(polygon[j][1])
        # 射线与边的交点判断
        if ((yi > py) != (yj > py)) and (
            px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi
        ):
            inside = not inside
        j = i

    return inside


def filter_cities_in_polygon(
    cities: list[tuple[int, float, float]],
    polygon: list,
) -> list[int]:
    """
    从城市坐标列表中筛选落在多边形内的城市 ID。

    Args:
        cities:  [(city_id, lng, lat), ...] 列表，来自 AdminRegion level=2 的查询结果。
        polygon: 区域边界坐标 [[lng, lat], ...]。

    Returns:
        落在多边形内的 city_id 列表（顺序保留）。
    """
    if not polygon or len(polygon) < 3:
        return []
    return [
        city_id
        for city_id, city_lng, city_lat in cities
        if city_lng is not None and city_lat is not None
        and point_in_polygon(city_lng, city_lat, polygon)
    ]
