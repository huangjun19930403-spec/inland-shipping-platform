"""一期统计任务主入口。"""

from app.jobs.cargo_stats import run_cargo_stats
from app.jobs.ship_stats import run_ship_dynamic_stats, run_ship_static_stats, run_ship_stats
from app.jobs.region_compute import run_region_compute

__all__ = [
    "run_cargo_stats",
    "run_ship_dynamic_stats",
    "run_ship_static_stats",
    "run_ship_stats",
    "run_region_compute",
]
