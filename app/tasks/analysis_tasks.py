"""
数据分析异步任务
负责每日统计聚合等定时任务
"""
import asyncio
import logging
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)


async def _run_daily_stats(target_date: Optional[str] = None) -> dict:
    """执行每日统计聚合"""
    from app.core.database import AsyncSessionLocal
    from app.repositories.analysis_repository import AnalysisRepository
    from app.repositories.cargo_repository import CargoRepository
    from app.repositories.address_repository import AddressRepository
    from app.services.analysis_service import AnalysisService

    async with AsyncSessionLocal() as db:
        service = AnalysisService(
            analysis_repo=AnalysisRepository(db),
            cargo_repo=CargoRepository(db),
            address_repo=AddressRepository(db),
        )

        stat_date = None
        if target_date:
            stat_date = date.fromisoformat(target_date)

        count = await service.compute_daily_stats(target_date=stat_date)
        return {"updated_nodes": count, "date": str(stat_date or date.today())}


def compute_daily_stats(target_date: Optional[str] = None) -> dict:
    """
    Celery任务：计算每日统计数据
    由Beat调度器每天凌晨2点触发
    """
    logger.info(f"[analysis_tasks] compute_daily_stats start date={target_date}")
    result = asyncio.run(_run_daily_stats(target_date))
    logger.info(f"[analysis_tasks] compute_daily_stats done {result}")
    return result


# Celery任务注册
try:
    from app.tasks.celery_app import celery_app

    @celery_app.task(name="app.tasks.analysis_tasks.compute_daily_stats")
    def compute_daily_stats_task(target_date: Optional[str] = None) -> dict:
        return compute_daily_stats(target_date)

except ImportError:
    pass
