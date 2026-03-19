"""船舶统计任务（一期）"""
from app.tasks.stat_tasks import refresh_all_vessel_stats as run_ship_stats

__all__ = ["run_ship_stats"]
