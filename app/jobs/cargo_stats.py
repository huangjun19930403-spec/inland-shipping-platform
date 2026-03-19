"""货源统计任务（一期）"""
from app.tasks.stat_tasks import refresh_cargo_stats as run_cargo_stats

__all__ = ["run_cargo_stats"]
