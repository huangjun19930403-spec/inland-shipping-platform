"""区域热力快照任务（一期）.

一期仅承担船舶区域/城市归属推断与热力快照生成，不做路线推演引擎。
"""
from app.jobs.ship_stats import run_ship_dynamic_stats


async def run_region_compute() -> dict:
    """重算区域+城市热力快照。"""
    result = await run_ship_dynamic_stats()
    result["job"] = "region_compute"
    return result


__all__ = ["run_region_compute"]
