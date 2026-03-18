"""
区域工具函数
包含：区域边界质心计算、点在多边形内判断（自动圈城市）

所有函数均为纯函数（无 I/O），易于单元测试。

说明：
- 区域编码（RG-NNN）生成逻辑已移至 address_service，通过
  数据库原子序列（code_sequence 表）保证并发安全，不再在此处定义。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# 几何计算
# ─────────────────────────────────────────────────────────

def compute_centroid(coordinates: list) -> tuple[float, float]:
    """
    用多边形质心公式（Shoelace / 面积加权）计算区域中心坐标。

    相比顶点算术均值，面积加权质心能正确处理形状不规则的多边形，
    不会因顶点分布不均而产生偏差。

    Args:
        coordinates: [[lng, lat], ...] 格式的顶点列表（首尾可相同，自动处理闭合）。

    Returns:
        (center_longitude, center_latitude) 元组。
        输入为空或退化多边形（< 3 个不重复点 / 面积为 0）时回退为算术均值；
        完全无效时返回 (0.0, 0.0)。
    """
    if not coordinates:
        return 0.0, 0.0

    pts = [(float(pt[0]), float(pt[1])) for pt in coordinates if len(pt) >= 2]
    if len(pts) < 3:
        if pts:
            return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        return 0.0, 0.0

    # 若首尾点相同（闭合多边形），去掉尾点避免重复计算
    if pts[0] == pts[-1]:
        pts = pts[:-1]

    n = len(pts)
    if n < 3:
        return sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n

    # Shoelace 公式：计算有向面积和质心
    signed_area = 0.0
    cx = 0.0
    cy = 0.0
    for i in range(n):
        j = (i + 1) % n
        cross = pts[i][0] * pts[j][1] - pts[j][0] * pts[i][1]
        signed_area += cross
        cx += (pts[i][0] + pts[j][0]) * cross
        cy += (pts[i][1] + pts[j][1]) * cross

    signed_area *= 0.5

    if abs(signed_area) < 1e-12:
        # 面积为 0（所有点共线），退化为算术均值
        logger.warning("compute_centroid: 多边形面积近似为 0，退化为算术均值计算")
        return sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n

    cx /= (6.0 * signed_area)
    cy /= (6.0 * signed_area)
    return cx, cy


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
