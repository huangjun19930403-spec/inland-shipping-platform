"""
定时任务调度器
——使用 APScheduler 驱动每日统计聚合——

已配置任务：
1. daily_stat_job    — 每日凌晨2:00 执行全量统计 ETL（货源 + 船舶 8 张统计表）
2. cleanup_stale_parsing — 每小时清理超时「解析中」的原始消息（>1小时未完成）
"""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings

logger = logging.getLogger("inland.scheduler")

scheduler = AsyncIOScheduler()


async def daily_stats_job():
    """每日统计 ETL 任务（委托给 stat_tasks.daily_stat_job）"""
    from app.tasks.stat_tasks import daily_stat_job

    logger.info("[Scheduler] 开始执行每日统计聚合任务...")
    try:
        result = await daily_stat_job()
        logger.info(f"[Scheduler] 每日统计聚合完成 {result}")
    except Exception as e:
        logger.error(f"[Scheduler] 每日统计聚合失败: {e}", exc_info=True)


async def cleanup_stale_parsing_job():
    """清理超时的「解析中」状态消息（防止卡死）"""
    from app.core.database import AsyncSessionLocal
    from app.models.cargo import CargoRawMessage
    from sqlalchemy import select, and_
    from datetime import datetime, timedelta

    logger.info("[Scheduler] 清理超时解析消息...")
    async with AsyncSessionLocal() as db:
        try:
            cutoff = datetime.utcnow() - timedelta(hours=1)
            result = await db.execute(
                select(CargoRawMessage).where(
                    and_(
                        CargoRawMessage.status == "PARSING",
                        CargoRawMessage.updated_at < cutoff,
                    )
                )
            )
            stale = result.scalars().all()
            for msg in stale:
                msg.status = "PENDING"
            await db.commit()
            if stale:
                logger.warning(f"[Scheduler] 重置了 {len(stale)} 条超时解析消息")
        except Exception as e:
            logger.error(f"[Scheduler] 清理超时消息失败: {e}")


def setup_scheduler():
    """注册所有定时任务并启动调度器"""
    scheduler.add_job(
        daily_stats_job,
        trigger=CronTrigger(
            hour=settings.STATS_CRON_HOUR,
            minute=settings.STATS_CRON_MINUTE,
        ),
        id="daily_stats",
        name="每日统计 ETL（货源 + 船舶）",
        replace_existing=True,
        misfire_grace_time=300,  # 允许延迟5分钟
    )

    scheduler.add_job(
        cleanup_stale_parsing_job,
        trigger=IntervalTrigger(hours=1),
        id="cleanup_stale_parsing",
        name="清理超时解析消息",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("[Scheduler] 定时任务调度器已启动")


def shutdown_scheduler():
    """关闭调度器"""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[Scheduler] 调度器已关闭")
