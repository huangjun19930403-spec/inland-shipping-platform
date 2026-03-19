"""Deprecated 统计任务桥接层。

说明：
- 本文件不再承载一期统计主实现；主实现已迁移至 `app/jobs/*`。
- 保留仅用于兼容历史脚本/调用方，后续版本将删除。
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional
from warnings import warn

from app.jobs.cargo_stats import run_cargo_stats
from app.jobs.ship_stats import (
    run_ship_dynamic_stats,
    run_ship_static_stats,
    run_ship_stats,
)

logger = logging.getLogger("inland.tasks.stat_tasks")


def _deprecated(name: str, replacement: str) -> None:
    msg = f"[DEPRECATED] app.tasks.stat_tasks.{name} 已迁移，请改用 {replacement}"
    logger.warning(msg)
    warn(msg, DeprecationWarning, stacklevel=2)


async def refresh_cargo_stats(stat_date: Optional[date] = None) -> dict:
    _deprecated("refresh_cargo_stats", "app.jobs.cargo_stats.run_cargo_stats")
    return await run_cargo_stats(stat_date=stat_date)


async def refresh_vessel_static_stats() -> dict:
    _deprecated(
        "refresh_vessel_static_stats",
        "app.jobs.ship_stats.run_ship_static_stats",
    )
    return await run_ship_static_stats()


async def refresh_vessel_dynamic_stats() -> dict:
    _deprecated(
        "refresh_vessel_dynamic_stats",
        "app.jobs.ship_stats.run_ship_dynamic_stats",
    )
    return await run_ship_dynamic_stats()


async def refresh_all_vessel_stats() -> dict:
    _deprecated("refresh_all_vessel_stats", "app.jobs.ship_stats.run_ship_stats")
    return await run_ship_stats()


async def daily_stat_job(target_date: Optional[date] = None) -> dict:
    _deprecated("daily_stat_job", "app.jobs.cargo_stats.daily_stats_job")
    cargo = await run_cargo_stats(stat_date=target_date)
    ship = await run_ship_stats()
    return {
        "stat_date": str(target_date or date.today()),
        "cargo": cargo,
        "ship": ship,
    }


__all__ = [
    "refresh_cargo_stats",
    "refresh_vessel_static_stats",
    "refresh_vessel_dynamic_stats",
    "refresh_all_vessel_stats",
    "daily_stat_job",
]
