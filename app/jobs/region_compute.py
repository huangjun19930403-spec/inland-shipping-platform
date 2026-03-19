"""区域归属计算任务（一期）"""
from app.tasks.stat_tasks import refresh_all_vessel_stats as run_region_compute

__all__ = ["run_region_compute"]
