"""
航运数据统计 ETL 任务

规则：
  - 本模块是唯一被允许读取业务表并写入统计表的代码路径
  - 统计表 (analysis.*) 由本任务每日写入，所有分析接口只读统计表
  - 任务执行时间：每天凌晨 02:00（由 APScheduler / Celery Beat 调度）

任务列表：
  daily_stat_job()   — 全量每日统计聚合，涵盖货源 + 船舶 6 张统计表
"""
import asyncio
import logging
from datetime import date, datetime
from typing import Optional

from sqlalchemy import select, func, and_, case, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("inland.stat_tasks")

# 船龄分组区间（左闭右开）
_AGE_GROUPS = [
    ("0-5",   0,  5),
    ("5-10",  5,  10),
    ("10-15", 10, 15),
    ("15-20", 15, 20),
    ("20+",   20, 9999),
]


# ─────────────────────────────────────────────────
# 货源统计 ETL
# ─────────────────────────────────────────────────

async def _stat_cargo_heatmap(db: AsyncSession, stat_date: date) -> int:
    """cargo_opportunity → cargo_heatmap_daily
    按装货/卸货节点统计当日货源数量及总吨位
    """
    from app.models.cargo import CargoOpportunity
    from app.repositories.analysis_repository import AnalysisRepository

    repo = AnalysisRepository(db)
    count = 0

    for stat_type, node_col in (
        ("ORIGIN", CargoOpportunity.origin_node_id),
        ("DEST",   CargoOpportunity.dest_node_id),
    ):
        result = await db.execute(
            select(
                node_col.label("node_id"),
                func.count(CargoOpportunity.id).label("cargo_count"),
                func.coalesce(func.sum(CargoOpportunity.tonnage), 0).label("total_tonnage"),
            )
            .where(
                and_(
                    node_col.isnot(None),
                    func.date(CargoOpportunity.created_at) == stat_date,
                )
            )
            .group_by(node_col)
        )
        rows = result.all()
        for row in rows:
            await repo.upsert_cargo_heatmap(
                stat_date=stat_date,
                node_id=row.node_id,
                stat_type=stat_type,
                cargo_count=row.cargo_count,
                total_tonnage=float(row.total_tonnage or 0),
            )
            count += 1

    return count


async def _stat_cargo_daily(db: AsyncSession, stat_date: date) -> None:
    """cargo_opportunity → cargo_stat_daily
    统计当日货源总量、各状态数量及总吨位
    """
    from app.models.cargo import CargoOpportunity
    from app.repositories.analysis_repository import AnalysisRepository

    result = await db.execute(
        select(
            CargoOpportunity.status,
            func.count(CargoOpportunity.id).label("cnt"),
            func.coalesce(func.sum(CargoOpportunity.tonnage), 0).label("tonnage"),
        )
        .where(func.date(CargoOpportunity.created_at) == stat_date)
        .group_by(CargoOpportunity.status)
    )
    rows = result.all()

    total_count = sum(r.cnt for r in rows)
    active_count = next((r.cnt for r in rows if r.status == "CONFIRMED"), 0)
    pending_count = next((r.cnt for r in rows if r.status == "PENDING_CONFIRM"), 0)
    total_tonnage = sum(float(r.tonnage or 0) for r in rows)

    repo = AnalysisRepository(db)
    await repo.upsert_cargo_stat(
        stat_date=stat_date,
        total_count=total_count,
        active_count=active_count,
        pending_count=pending_count,
        total_tonnage=total_tonnage,
    )


async def _stat_cargo_region(db: AsyncSession, stat_date: date) -> None:
    """cargo_opportunity → cargo_region_stat_daily
    按装货/卸货区域统计货源数量及总吨位
    """
    from app.models.cargo import CargoOpportunity
    from app.models.address import Region
    from app.repositories.analysis_repository import AnalysisRepository

    repo = AnalysisRepository(db)

    for stat_type, region_col in (
        ("ORIGIN", CargoOpportunity.origin_region_id),
        ("DEST",   CargoOpportunity.dest_region_id),
    ):
        result = await db.execute(
            select(
                region_col.label("region_id"),
                Region.name.label("region_name"),
                func.count(CargoOpportunity.id).label("cargo_count"),
                func.coalesce(func.sum(CargoOpportunity.tonnage), 0).label("total_tonnage"),
            )
            .join(Region, Region.id == region_col)
            .where(
                and_(
                    region_col.isnot(None),
                    func.date(CargoOpportunity.created_at) == stat_date,
                )
            )
            .group_by(region_col, Region.name)
        )
        for row in result.all():
            await repo.upsert_cargo_region_stat(
                stat_date=stat_date,
                region_id=row.region_id,
                region_name=row.region_name,
                stat_type=stat_type,
                cargo_count=row.cargo_count,
                total_tonnage=float(row.total_tonnage or 0),
            )


async def _stat_cargo_commodity(db: AsyncSession, stat_date: date) -> None:
    """cargo_opportunity → cargo_commodity_stat_daily
    按货品大类统计当日货源数量及总吨位
    """
    from app.models.cargo import CargoOpportunity, CommodityStandard, CommodityType, CommodityCategory
    from app.repositories.analysis_repository import AnalysisRepository

    result = await db.execute(
        select(
            CommodityCategory.id.label("category_id"),
            CommodityCategory.name.label("category_name"),
            func.count(CargoOpportunity.id).label("cargo_count"),
            func.coalesce(func.sum(CargoOpportunity.tonnage), 0).label("total_tonnage"),
        )
        .join(CommodityStandard, CommodityStandard.id == CargoOpportunity.commodity_id)
        .join(CommodityType, CommodityType.id == CommodityStandard.type_id)
        .join(CommodityCategory, CommodityCategory.id == CommodityType.category_id)
        .where(
            and_(
                CargoOpportunity.commodity_id.isnot(None),
                func.date(CargoOpportunity.created_at) == stat_date,
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


# ─────────────────────────────────────────────────
# 船舶统计 ETL
# ─────────────────────────────────────────────────

async def _stat_ship_type(db: AsyncSession, stat_date: date) -> None:
    """vessel → ship_type_stat_daily
    按船舶类型统计数量与总载重（当日快照，所有有效船舶）
    """
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


async def _stat_ship_capacity_region(db: AsyncSession, stat_date: date) -> None:
    """vessel + vessel_dynamic → ship_capacity_region_daily
    按当前所在区域（vessel_dynamic.current_node_id → transport_node.region_id）统计
    """
    from app.models.vessel import Vessel, VesselDynamic
    from app.models.address import TransportNode, Region
    from app.repositories.analysis_repository import AnalysisRepository

    result = await db.execute(
        select(
            Region.id.label("region_id"),
            Region.name.label("region_name"),
            func.count(Vessel.id).label("vessel_count"),
            func.coalesce(func.sum(Vessel.deadweight), 0).label("total_deadweight"),
        )
        .join(VesselDynamic, VesselDynamic.vessel_id == Vessel.id)
        .join(TransportNode, TransportNode.id == VesselDynamic.current_node_id)
        .join(Region, Region.id == TransportNode.region_id)
        .where(
            and_(
                Vessel.data_status == 1,
                Vessel.is_deleted == 0,
                VesselDynamic.current_node_id.isnot(None),
                TransportNode.region_id.isnot(None),
            )
        )
        .group_by(Region.id, Region.name)
    )

    repo = AnalysisRepository(db)
    for row in result.all():
        await repo.upsert_ship_capacity_region(
            stat_date=stat_date,
            region_id=row.region_id,
            region_name=row.region_name,
            vessel_count=row.vessel_count,
            total_deadweight=float(row.total_deadweight or 0),
        )


async def _stat_ship_age(db: AsyncSession, stat_date: date) -> None:
    """vessel → ship_age_stat_daily
    船龄 = stat_date.year - build_year，按分组区间聚合
    """
    from app.models.vessel import Vessel
    from app.repositories.analysis_repository import AnalysisRepository

    current_year = stat_date.year
    result = await db.execute(
        select(Vessel.build_year, func.count(Vessel.id).label("cnt"))
        .where(
            and_(
                Vessel.data_status == 1,
                Vessel.is_deleted == 0,
                Vessel.build_year.isnot(None),
            )
        )
        .group_by(Vessel.build_year)
    )
    rows = result.all()

    # 按区间聚合
    buckets: dict[str, int] = {g[0]: 0 for g in _AGE_GROUPS}
    for row in rows:
        age = current_year - row.build_year
        for group_name, lo, hi in _AGE_GROUPS:
            if lo <= age < hi:
                buckets[group_name] += row.cnt
                break

    repo = AnalysisRepository(db)
    for age_group, vessel_count in buckets.items():
        await repo.upsert_ship_age_stat(
            stat_date=stat_date,
            age_group=age_group,
            vessel_count=vessel_count,
        )


async def _stat_ship_heatmap(db: AsyncSession, stat_date: date) -> None:
    """vessel_dynamic (AIS当前位置) → ship_heatmap_daily
    按当前所在节点统计在港/在途船舶数量与总载重
    """
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


# ─────────────────────────────────────────────────
# 主任务入口
# ─────────────────────────────────────────────────

async def _run_daily_stat_job(target_date: Optional[date] = None) -> dict:
    """执行全量每日统计聚合（每天 02:00 触发）"""
    from app.core.database import AsyncSessionLocal

    stat_date = target_date or date.today()
    logger.info(f"[stat_tasks] 开始每日统计聚合 date={stat_date}")

    results = {}

    async with AsyncSessionLocal() as db:
        try:
            # 货源统计
            heatmap_nodes = await _stat_cargo_heatmap(db, stat_date)
            results["cargo_heatmap_nodes"] = heatmap_nodes

            await _stat_cargo_daily(db, stat_date)
            results["cargo_stat_daily"] = True

            await _stat_cargo_region(db, stat_date)
            results["cargo_region_stat"] = True

            await _stat_cargo_commodity(db, stat_date)
            results["cargo_commodity_stat"] = True

            # 船舶统计
            await _stat_ship_type(db, stat_date)
            results["ship_type_stat"] = True

            await _stat_ship_capacity_region(db, stat_date)
            results["ship_capacity_region"] = True

            await _stat_ship_age(db, stat_date)
            results["ship_age_stat"] = True

            await _stat_ship_heatmap(db, stat_date)
            results["ship_heatmap"] = True

            await db.commit()
            logger.info(f"[stat_tasks] 每日统计聚合完成 date={stat_date} results={results}")
        except Exception as exc:
            await db.rollback()
            logger.error(f"[stat_tasks] 每日统计聚合失败 date={stat_date}: {exc}", exc_info=True)
            raise

    results["stat_date"] = str(stat_date)
    return results


async def daily_stat_job(target_date: Optional[date] = None) -> dict:
    """协程入口，供 APScheduler 异步调度直接调用"""
    return await _run_daily_stat_job(target_date)


def run_daily_stat_job_sync(target_date_str: Optional[str] = None) -> dict:
    """同步入口，供 Celery Task 调用"""
    td = date.fromisoformat(target_date_str) if target_date_str else None
    return asyncio.run(_run_daily_stat_job(td))


# ─────────────────────────────────────────────────
# Celery Task 注册（可选，生产环境用）
# ─────────────────────────────────────────────────

try:
    from app.tasks.celery_app import celery_app

    @celery_app.task(name="app.tasks.stat_tasks.daily_stat_job")
    def daily_stat_job_task(target_date: Optional[str] = None) -> dict:
        """Celery Task：每日统计聚合"""
        return run_daily_stat_job_sync(target_date)

except ImportError:
    pass
