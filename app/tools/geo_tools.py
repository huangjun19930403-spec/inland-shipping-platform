"""
地理计算工具
职责：提供内河航运相关的地理距离和位置计算能力
"""
import math
import logging
from typing import Any, Optional

from app.ai.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class GeoDistanceTool(BaseTool):
    """
    地理距离计算工具

    使用Haversine公式计算两点间大圆距离。
    内河实际航程通常为直线距离的1.3-1.8倍，
    本工具提供直线距离估算，实际航线距离由航线路径节点累加。
    """

    name = "geo_distance"
    description = "计算两地理坐标点之间的球面距离（公里）"

    async def execute(
        self,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Args:
            origin_lat: 起点纬度
            origin_lng: 起点经度
            dest_lat: 终点纬度
            dest_lng: 终点经度

        Returns:
            ToolResult.data = {
                "distance_km": float,  # 球面直线距离
                "estimated_waterway_km": float,  # 估算内河航程
            }
        """
        try:
            distance = haversine(origin_lat, origin_lng, dest_lat, dest_lng)
            estimated_waterway = distance * 1.5  # 内河弯曲系数估算

            return ToolResult(
                success=True,
                data={
                    "distance_km": round(distance, 2),
                    "estimated_waterway_km": round(estimated_waterway, 2),
                },
            )
        except Exception as e:
            logger.error(f"[GeoDistanceTool] Error: {e}")
            return ToolResult(success=False, error=str(e))


def haversine(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """
    Haversine公式计算球面距离（公里）
    """
    R = 6371.0  # 地球半径（km）

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c
