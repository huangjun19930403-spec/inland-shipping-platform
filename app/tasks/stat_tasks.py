"""
航运数据统计任务

货源统计：写入事件驱动（refresh_cargo_stats），货源创建/状态变更后立即调用
船舶统计：每日 02:00 定时任务（daily_ship_stat_job），AIS数据按日更新

规则：
  - 本模块是唯一被允许读取业务表并写入统计表的代码路径
  - 所有分析接口只读统计表
"""
import asyncio
import logging
from datetime import date
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("inland.stat_tasks")


# ─────────────────────────────────────────────────
# 货源统计（事件驱动）
# ─────────────────────────────────────────────────

async def _stat_cargo_city_heatmap(db: AsyncSession, stat_date: date) -> int:
    """cargo_freight → cargo_city_heatmap
    按装货/卸货城市统计当日货源数量及总吨位
    """
    from app.models.cargo import CargoFreight
    from app.repositories.analysis_repository import AnalysisRepository

    repo = AnalysisRepository(db)
    count = 0

    for stat_type, code_col, name_col in (
        ("ORIGIN", CargoFreight.origin_admin_code, CargoFreight.origin_admin_name),
        ("DEST",   CargoFreight.dest_admin_code,   CargoFreight.dest_admin_name),
    ):
        result = await db.execute(
            select(
                code_col.label("city_code"),
                name_col.label("city_name"),
                func.count(CargoFreight.id).label("cargo_count"),
                func.coalesce(func.sum(CargoFreight.tonnage), 0).label("total_tonnage"),
            )
            .where(
                and_(
                    code_col.isnot(None),
                    CargoFreight.deleted_at.is_(None),
                    func.date(CargoFreight.created_at) == stat_date,
                )
            )
            .group_by(code_col, name_col)
        )
        rows = result.all()
        for row in rows:
            await repo.upsert_cargo_city_heatmap(
                stat_date=stat_date,
                city_code=row.city_code,
                city_name=row.city_name or "",
                stat_type=stat_type,
                cargo_count=row.cargo_count,
                total_tonnage=float(row.total_tonnage or 0),
            )
            count += 1

    return count


async def _stat_cargo_daily(db: AsyncSession, stat_date: date) -> None:
    """cargo_freight → cargo_stat_daily
    统计当日货源总量、各状态数量及总吨位
    """
    from app.models.cargo import CargoFreight
    from app.repositories.analysis_repository import AnalysisRepository

    result = await db.execute(
        select(
            CargoFreight.status,
            func.count(CargoFreight.id).label("cnt"),
            func.coalesce(func.sum(CargoFreight.tonnage), 0).label("tonnage"),
        )
        .where(
            and_(
                CargoFreight.deleted_at.is_(None),
                func.date(CargoFreight.created_at) == stat_date,
            )
        )
        .group_by(CargoFreight.status)
    )
    rows = result.all()

    total_count = sum(r.cnt for r in rows)
    confirmed_count = next((r.cnt for r in rows if r.status == "CONFIRMED"), 0)
    pending_count = next((r.cnt for r in rows if r.status == "PENDING"), 0)
    total_tonnage = sum(float(r.tonnage or 0) for r in rows)
    avg_tonnage = round(total_tonnage / total_count, 2) if total_count else 0.0

    repo = AnalysisRepository(db)
    await repo.upsert_cargo_stat(
        stat_date=stat_date,
        total_count=total_count,
        confirmed_count=confirmed_count,
        pending_count=pending_count,
        total_tonnage=total_tonnage,
        avg_tonnage=avg_tonnage,
    )


async def _stat_cargo_commodity(db: AsyncSession, stat_date: date) -> None:
    """cargo_freight → cargo_commodity_stat_daily
    按货品大类统计当日货源数量及总吨位
    """
    from app.models.cargo import CargoFreight, CommodityStandard, CommodityType, CommodityCategory
    from app.repositories.analysis_repository import AnalysisRepository

    result = await db.execute(
        select(
            CommodityCategory.id.label("category_id"),
            CommodityCategory.name.label("category_name"),
            func.count(CargoFreight.id).label("cargo_count"),
            func.coalesce(func.sum(CargoFreight.tonnage), 0).label("total_tonnage"),
        )
        .join(CommodityStandard, CommodityStandard.id == CargoFreight.commodity_id)
        .join(CommodityType, CommodityType.id == CommodityStandard.type_id)
        .join(CommodityCategory, CommodityCategory.id == CommodityType.category_id)
        .where(
            and_(
                CargoFreight.commodity_id.isnot(None),
                CargoFreight.deleted_at.is_(None),
                func.date(CargoFreight.created_at) == stat_date,
            )
        )
        .group_by(CommodityCategory.id, CommodityCategory.name)
    )

    repo = AnalysisRepository(db)
    for row in result.all():
        await repo.upsert_cargo_commodity_stat(
            stat_date=stat_date,
            commodity_category_id=row.category_id,
            category_name=row.category_name,
            cargo_count=row.cargo_count,
            total_tonnage=float(row.total_tonnage or 0),
        )


async def _stat_cargo_od(db: AsyncSession, stat_date: date) -> None:
    """cargo_freight → cargo_od_daily
    按起终点城市对统计当日OD流量
    """
    from app.models.cargo import CargoFreight
    from app.repositories.analysis_repository import AnalysisRepository

    result = await db.execute(
        select(
            CargoFreight.origin_admin_code.label("origin_city_code"),
            CargoFreight.origin_admin_name.label("origin_city_name"),
            CargoFreight.dest_admin_code.label("dest_city_code"),
            CargoFreight.dest_admin_name.label("dest_city_name"),
            func.count(CargoFreight.id).label("cargo_count"),
            func.coalesce(func.sum(CargoFreight.tonnage), 0).label("total_tonnage"),
        )
        .where(
            and_(
                CargoFreight.origin_admin_code.isnot(None),
                CargoFreight.dest_admin_code.isnot(None),
                CargoFreight.deleted_at.is_(None),
                func.date(CargoFreight.created_at) == stat_date,
            )
        )
        .group_by(
            CargoFreight.origin_admin_code,
            CargoFreight.origin_admin_name,
            CargoFreight.dest_admin_code,
            CargoFreight.dest_admin_name,
        )
    )

    repo = AnalysisRepository(db)
    for row in result.all():
        await repo.upsert_cargo_od_stat(
            stat_date=stat_date,
            origin_city_code=row.origin_city_code,
            origin_city_name=row.origin_city_name or "",
            dest_city_code=row.dest_city_code,
            dest_city_name=row.dest_city_name or "",
            cargo_count=row.cargo_count,
            total_tonnage=float(row.total_tonnage or 0),
        )


async def _stat_cargo_channel(db: AsyncSession, stat_date: date) -> None:
    """cargo_freight + cargo_raw_message → cargo_channel_daily
    按录入渠道统计数量、解析成功数、确认数及总吨位
    """
    from app.models.cargo import CargoFreight, CargoRawMessage
    from app.repositories.analysis_repository import AnalysisRepository

    # 各渠道已确认货源数及总吨位
    freight_result = await db.execute(
        select(
            CargoFreight.source_type,
            func.count(CargoFreight.id).label("confirmed_count"),
            func.coalesce(func.sum(CargoFreight.tonnage), 0).label("total_tonnage"),
        )
        .where(
            and_(
                CargoFreight.deleted_at.is_(None),
                func.date(CargoFreight.created_at) == stat_date,
            )
        )
        .group_by(CargoFreight.source_type)
    )
    freight_rows = {r.source_type: r for r in freight_result.all()}

    # WECHAT_AI 渠道原始消息数及解析成功数
    msg_result = await db.execute(
        select(
            func.count(CargoRawMessage.id).label("raw_count"),
            func.sum(
                func.cast(CargoRawMessage.status == "PARSED", db.bind.dialect.type_compiler.__class__)
                if False else 1
            ).label("_unused"),
        )
        .where(func.date(CargoRawMessage.created_at) == stat_date)
    )
    # 简化实现：单独统计 WECHAT_AI 原始消息总数和成功数
    raw_total_result = await db.execute(
        select(func.count(CargoRawMessage.id))
        .where(func.date(CargoRawMessage.created_at) == stat_date)
    )
    raw_total = raw_total_result.scalar_one() or 0

    parsed_result = await db.execute(
        select(func.count(CargoRawMessage.id))
        .where(
            and_(
                CargoRawMessage.status == "PARSED",
                func.date(CargoRawMessage.created_at) == stat_date,
            )
        )
    )
    parsed_count = parsed_result.scalar_one() or 0

    # 汇总写入各渠道统计
    repo = AnalysisRepository(db)
    all_source_types = set(freight_rows.keys()) | {"WECHAT_AI", "TMS", "MANUAL"}
    for source_type in all_source_types:
        fr = freight_rows.get(source_type)
        raw_msg_count = raw_total if source_type == "WECHAT_AI" else 0
        parse_success = parsed_count if source_type == "WECHAT_AI" else 0
        await repo.upsert_cargo_channel_stat(
            stat_date=stat_date,
            source_type=source_type,
            raw_msg_count=raw_msg_count,
            parse_success_count=parse_success,
            confirmed_count=fr.confirmed_count if fr else 0,
            total_tonnage=float(fr.total_tonnage or 0) if fr else 0.0,
        )


# ─────────────────────────────────────────────────
# 事件驱动入口（货源写入时触发）
# ─────────────────────────────────────────────────

async def refresh_cargo_stats(stat_date: Optional[date] = None) -> None:
    """事件驱动统计刷新 — 货源创建/状态变更后触发，刷新当日所有货源统计表

    使用方式：
        from app.tasks.stat_tasks import refresh_cargo_stats
        background_tasks.add_task(refresh_cargo_stats, date.today())
    """
    from app.core.database import AsyncSessionLocal

    target = stat_date or date.today()
    logger.info(f"[stat_tasks] refresh_cargo_stats date={target}")

    async with AsyncSessionLocal() as db:
        try:
            await _stat_cargo_city_heatmap(db, target)
            await _stat_cargo_daily(db, target)
            await _stat_cargo_commodity(db, target)
            await _stat_cargo_od(db, target)
            await _stat_cargo_channel(db, target)
            await db.commit()
            logger.info(f"[stat_tasks] refresh_cargo_stats done date={target}")
        except Exception as exc:
            await db.rollback()
            logger.error(
                f"[stat_tasks] refresh_cargo_stats failed date={target}: {exc}",
                exc_info=True,
            )


# ─────────────────────────────────────────────────
# 船舶统计 ETL（保持每日 02:00 定时任务）
# ─────────────────────────────────────────────────

async def _stat_ship_type(db: AsyncSession, stat_date: date) -> None:
    """vessel → ship_type_stat_daily"""
    from app.models.vessel import Vessel, VesselTypeDict
    from app.repositories.analysis_repository import AnalysisRepository

    result = await db.execute(
        select(
            VesselTypeDict.id.label("type_id"),
            VesselTypeDict.name.label("type_name"),
            func.count(Vessel.id).label("vessel_count"),
            func.coalesce(func.sum(Vessel.deadweight), 0).label("total_deadweight"),
        )
        .join(VesselTypeDict, VesselTypeDict.id == Vessel.vessel_type_id)
        .where(
            and_(
                Vessel.data_status == 1,
                Vessel.is_deleted == 0,
            )
        )
        .group_by(VesselTypeDict.id, VesselTypeDict.name)
    )

    repo = AnalysisRepository(db)
    for row in result.all():
        await repo.upsert_ship_type_stat(
            stat_date=stat_date,
            vessel_type_id=row.type_id,
            type_name=row.type_name,
            vessel_count=row.vessel_count,
            total_deadweight=float(row.total_deadweight or 0),
        )


async def _stat_ship_heatmap(db: AsyncSession, stat_date: date) -> None:
    """vessel_dynamic (AIS当前位置) → ship_heatmap_daily"""
    from app.models.vessel import Vessel, VesselDynamic
    from app.repositories.analysis_repository import AnalysisRepository

    result = await db.execute(
        select(
            VesselDynamic.current_node_id.label("node_id"),
            func.count(Vessel.id).label("vessel_count"),
            func.coalesce(func.sum(Vessel.deadweight), 0).label("total_deadweight"),
        )
        .join(Vessel, Vessel.id == VesselDynamic.vessel_id)
        .where(
            and_(
                Vessel.data_status == 1,
                Vessel.is_deleted == 0,
                VesselDynamic.current_node_id.isnot(None),
            )
        )
        .group_by(VesselDynamic.current_node_id)
    )

    repo = AnalysisRepository(db)
    for row in result.all():
        await repo.upsert_ship_heatmap(
            stat_date=stat_date,
            node_id=row.node_id,
            vessel_count=row.vessel_count,
            total_deadweight=float(row.total_deadweight or 0),
        )


async def _run_daily_ship_stat_job(target_date: Optional[date] = None) -> dict:
    """执行船舶每日统计聚合（每天 02:00 触发）"""
    from app.core.database import AsyncSessionLocal

    stat_date = target_date or date.today()
    logger.info(f"[stat_tasks] 开始船舶每日统计 date={stat_date}")

    results: dict = {}
    async with AsyncSessionLocal() as db:
        try:
            await _stat_ship_type(db, stat_date)
            results["ship_type_stat"] = True

            await _stat_ship_heatmap(db, stat_date)
            results["ship_heatmap"] = True

            await db.commit()
            logger.info(f"[stat_tasks] 船舶每日统计完成 date={stat_date}")
        except Exception as exc:
            await db.rollback()
            logger.error(f"[stat_tasks] 船舶每日统计失败 date={stat_date}: {exc}", exc_info=True)
            raise

    results["stat_date"] = str(stat_date)
    return results


async def daily_ship_stat_job(target_date: Optional[date] = None) -> dict:
    """协程入口，供 APScheduler 异步调度直接调用"""
    return await _run_daily_ship_stat_job(target_date)


def run_daily_ship_stat_job_sync(target_date_str: Optional[str] = None) -> dict:
    """同步入口，供 Celery Task 调用"""
    td = date.fromisoformat(target_date_str) if target_date_str else None
    return asyncio.run(_run_daily_ship_stat_job(td))


# ─────────────────────────────────────────────────
# 管理员手动全量重跑接口（同时刷新货源+船舶）
# ─────────────────────────────────────────────────

async def daily_stat_job(target_date: Optional[date] = None) -> dict:
    """手动触发全量统计（管理员使用）"""
    from app.core.database import AsyncSessionLocal

    stat_date = target_date or date.today()
    logger.info(f"[stat_tasks] 全量统计 date={stat_date}")

    results: dict = {}
    async with AsyncSessionLocal() as db:
        try:
            results["city_heatmap_rows"] = await _stat_cargo_city_heatmap(db, stat_date)
            await _stat_cargo_daily(db, stat_date)
            results["cargo_stat_daily"] = True
            await _stat_cargo_commodity(db, stat_date)
            results["cargo_commodity_stat"] = True
            await _stat_cargo_od(db, stat_date)
            results["cargo_od_stat"] = True
            await _stat_cargo_channel(db, stat_date)
            results["cargo_channel_stat"] = True
            await _stat_ship_type(db, stat_date)
            results["ship_type_stat"] = True
            await _stat_ship_heatmap(db, stat_date)
            results["ship_heatmap"] = True
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.error(f"[stat_tasks] 全量统计失败 date={stat_date}: {exc}", exc_info=True)
            raise

    results["stat_date"] = str(stat_date)
    return results


# ─────────────────────────────────────────────────
# Celery Task 注册（可选，生产环境用）
# ─────────────────────────────────────────────────

try:
    from app.tasks.celery_app import celery_app

    @celery_app.task(name="app.tasks.stat_tasks.daily_ship_stat_job")
    def daily_ship_stat_job_task(target_date: Optional[str] = None) -> dict:
        """Celery Task：船舶每日统计"""
        return run_daily_ship_stat_job_sync(target_date)

except ImportError:
    pass
