"""货源统计任务主实现（一期）.

统计口径：
1. 仅统计 `cargo_freight` 中当日有效记录：
   - `deleted_at IS NULL`
   - `record_status = ACTIVE`
   - `analysis_status = READY`
   - `is_test_data = 0`
   - `status IN (PENDING, CONFIRMED)`
2. 分析接口只读取统计表，业务表到统计表的写入在本模块完成。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Optional

from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.address import AdminRegion
from app.models.analysis import (
    CargoChannelDaily,
    CargoCityHeatmap,
    CargoCommodityStatDaily,
    CargoOdDaily,
)
from app.models.cargo import (
    CargoFreight,
    CargoRawMessage,
    CommodityCategory,
    CommodityStandard,
    CommodityType,
)
from app.repositories.analysis_repository import AnalysisRepository

try:
    from celery import shared_task
except Exception:  # pragma: no cover - celery 未安装时降级
    def shared_task(*_args, **_kwargs):  # type: ignore
        def _decorator(func):
            return func
        return _decorator

logger = logging.getLogger("inland.jobs.cargo_stats")


def _cargo_base_filters(stat_date: date) -> list:
    """一期货源统计统一口径过滤条件。"""
    return [
        CargoFreight.deleted_at.is_(None),
        CargoFreight.record_status == "ACTIVE",
        CargoFreight.analysis_status == "READY",
        CargoFreight.is_test_data == 0,
        CargoFreight.status.in_(("PENDING", "CONFIRMED")),
        func.date(CargoFreight.created_at) == stat_date,
    ]


async def _reset_cargo_stat_rows(db: AsyncSession, stat_date: date) -> None:
    """先清理当日分区，再重算，避免历史脏行残留。"""
    await db.execute(
        delete(CargoCityHeatmap).where(CargoCityHeatmap.stat_date == stat_date)
    )
    await db.execute(
        delete(CargoCommodityStatDaily).where(
            CargoCommodityStatDaily.stat_date == stat_date
        )
    )
    await db.execute(delete(CargoOdDaily).where(CargoOdDaily.stat_date == stat_date))
    await db.execute(
        delete(CargoChannelDaily).where(CargoChannelDaily.stat_date == stat_date)
    )
    await db.flush()


async def _stat_cargo_city_heatmap(db: AsyncSession, stat_date: date) -> int:
    """货源城市热力统计（装货+卸货）。"""
    repo = AnalysisRepository(db)
    count = 0

    for stat_type, code_col, name_col in (
        ("ORIGIN", CargoFreight.origin_admin_code, CargoFreight.origin_admin_name),
        ("DEST", CargoFreight.dest_admin_code, CargoFreight.dest_admin_name),
    ):
        rows = (
            await db.execute(
                select(
                    code_col.label("city_code"),
                    func.coalesce(name_col, AdminRegion.name, "").label("city_name"),
                    AdminRegion.longitude.label("longitude"),
                    AdminRegion.latitude.label("latitude"),
                    func.count(CargoFreight.id).label("cargo_count"),
                    func.coalesce(func.sum(CargoFreight.tonnage), 0).label(
                        "total_tonnage"
                    ),
                )
                .outerjoin(AdminRegion, AdminRegion.code == code_col)
                .where(and_(code_col.isnot(None), *_cargo_base_filters(stat_date)))
                .group_by(
                    code_col,
                    name_col,
                    AdminRegion.name,
                    AdminRegion.longitude,
                    AdminRegion.latitude,
                )
            )
        ).all()

        for row in rows:
            await repo.upsert_cargo_city_heatmap(
                stat_date=stat_date,
                city_code=row.city_code,
                city_name=row.city_name,
                stat_type=stat_type,
                cargo_count=int(row.cargo_count or 0),
                total_tonnage=float(row.total_tonnage or 0),
                city_longitude=float(row.longitude) if row.longitude is not None else None,
                city_latitude=float(row.latitude) if row.latitude is not None else None,
            )
            count += 1

    return count


async def _stat_cargo_daily(db: AsyncSession, stat_date: date) -> None:
    """货源趋势主表统计。"""
    rows = (
        await db.execute(
            select(
                CargoFreight.status,
                func.count(CargoFreight.id).label("cargo_count"),
                func.coalesce(func.sum(CargoFreight.tonnage), 0).label("total_tonnage"),
            )
            .where(and_(*_cargo_base_filters(stat_date)))
            .group_by(CargoFreight.status)
        )
    ).all()

    total_count = sum(int(r.cargo_count or 0) for r in rows)
    confirmed_count = sum(
        int(r.cargo_count or 0) for r in rows if r.status == "CONFIRMED"
    )
    pending_count = sum(int(r.cargo_count or 0) for r in rows if r.status == "PENDING")
    total_tonnage = sum(float(r.total_tonnage or 0) for r in rows)
    avg_tonnage = round(total_tonnage / total_count, 2) if total_count else 0.0

    await AnalysisRepository(db).upsert_cargo_stat(
        stat_date=stat_date,
        total_count=total_count,
        confirmed_count=confirmed_count,
        pending_count=pending_count,
        total_tonnage=total_tonnage,
        avg_tonnage=avg_tonnage,
    )


async def _stat_cargo_commodity(db: AsyncSession, stat_date: date) -> int:
    """货品分类排行统计。"""
    rows = (
        await db.execute(
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
                and_(CargoFreight.commodity_id.isnot(None), *_cargo_base_filters(stat_date))
            )
            .group_by(CommodityCategory.id, CommodityCategory.name)
        )
    ).all()

    repo = AnalysisRepository(db)
    for row in rows:
        await repo.upsert_cargo_commodity_stat(
            stat_date=stat_date,
            commodity_category_id=int(row.category_id),
            category_name=row.category_name,
            cargo_count=int(row.cargo_count or 0),
            total_tonnage=float(row.total_tonnage or 0),
        )
    return len(rows)


async def _stat_cargo_od(db: AsyncSession, stat_date: date) -> int:
    """OD 流向统计。"""
    rows = (
        await db.execute(
            select(
                CargoFreight.origin_admin_code.label("origin_city_code"),
                func.coalesce(CargoFreight.origin_admin_name, "").label("origin_city_name"),
                CargoFreight.dest_admin_code.label("dest_city_code"),
                func.coalesce(CargoFreight.dest_admin_name, "").label("dest_city_name"),
                func.count(CargoFreight.id).label("cargo_count"),
                func.coalesce(func.sum(CargoFreight.tonnage), 0).label("total_tonnage"),
            )
            .where(
                and_(
                    CargoFreight.origin_admin_code.isnot(None),
                    CargoFreight.dest_admin_code.isnot(None),
                    *_cargo_base_filters(stat_date),
                )
            )
            .group_by(
                CargoFreight.origin_admin_code,
                CargoFreight.origin_admin_name,
                CargoFreight.dest_admin_code,
                CargoFreight.dest_admin_name,
            )
        )
    ).all()

    repo = AnalysisRepository(db)
    for row in rows:
        await repo.upsert_cargo_od_stat(
            stat_date=stat_date,
            origin_city_code=row.origin_city_code,
            origin_city_name=row.origin_city_name,
            dest_city_code=row.dest_city_code,
            dest_city_name=row.dest_city_name,
            cargo_count=int(row.cargo_count or 0),
            total_tonnage=float(row.total_tonnage or 0),
        )
    return len(rows)


async def _stat_cargo_channel(db: AsyncSession, stat_date: date) -> int:
    """渠道质量统计（TMS / WECHAT_AI / MANUAL）。"""
    repo = AnalysisRepository(db)

    freight_rows = (
        await db.execute(
            select(
                CargoFreight.source_type,
                func.count(CargoFreight.id).label("confirmed_count"),
                func.coalesce(func.sum(CargoFreight.tonnage), 0).label("total_tonnage"),
            )
            .where(
                and_(
                    *_cargo_base_filters(stat_date),
                    CargoFreight.status == "CONFIRMED",
                )
            )
            .group_by(CargoFreight.source_type)
        )
    ).all()
    freight_map = {row.source_type: row for row in freight_rows}

    raw_total = (
        await db.execute(
            select(func.count(CargoRawMessage.id)).where(
                func.date(CargoRawMessage.created_at) == stat_date
            )
        )
    ).scalar_one() or 0

    parsed_total = (
        await db.execute(
            select(func.count(CargoRawMessage.id)).where(
                and_(
                    func.date(CargoRawMessage.created_at) == stat_date,
                    CargoRawMessage.status == "PARSED",
                )
            )
        )
    ).scalar_one() or 0

    channels = sorted(set(freight_map.keys()) | {"WECHAT_AI", "TMS", "MANUAL"})
    for source_type in channels:
        freight = freight_map.get(source_type)
        await repo.upsert_cargo_channel_stat(
            stat_date=stat_date,
            source_type=source_type,
            raw_msg_count=int(raw_total) if source_type == "WECHAT_AI" else 0,
            parse_success_count=int(parsed_total) if source_type == "WECHAT_AI" else 0,
            confirmed_count=int(freight.confirmed_count or 0) if freight else 0,
            total_tonnage=float(freight.total_tonnage or 0) if freight else 0.0,
        )

    return len(channels)


async def run_cargo_stats(stat_date: Optional[date] = None) -> dict:
    """重算指定日期货源统计（默认当天）。"""
    target = stat_date or date.today()
    logger.info("[jobs.cargo_stats] start stat_date=%s", target)
    result: dict[str, object] = {"stat_date": str(target)}

    async with AsyncSessionLocal() as db:
        try:
            await _reset_cargo_stat_rows(db, target)
            result["cargo_heatmap_rows"] = await _stat_cargo_city_heatmap(db, target)
            await _stat_cargo_daily(db, target)
            result["cargo_trend"] = "ok"
            result["cargo_commodity_rows"] = await _stat_cargo_commodity(db, target)
            result["cargo_od_rows"] = await _stat_cargo_od(db, target)
            result["cargo_channel_rows"] = await _stat_cargo_channel(db, target)
            await db.commit()
            logger.info("[jobs.cargo_stats] done stat_date=%s result=%s", target, result)
        except Exception:
            await db.rollback()
            logger.exception("[jobs.cargo_stats] failed stat_date=%s", target)
            raise

    return result


@shared_task(name="app.jobs.cargo_stats.run_cargo_stats_task")
def run_cargo_stats_task(stat_date: Optional[str] = None) -> dict:
    """Celery 同步入口：触发指定日期货源统计。"""
    parsed = date.fromisoformat(stat_date) if stat_date else None
    return asyncio.run(run_cargo_stats(parsed))


@shared_task(name="app.jobs.cargo_stats.daily_stats_job")
def daily_stats_job(stat_date: Optional[str] = None) -> dict:
    """Celery 同步入口：触发货源日报 + 船舶快照。"""
    from app.jobs.ship_stats import run_ship_stats

    parsed = date.fromisoformat(stat_date) if stat_date else None

    async def _run() -> dict:
        cargo = await run_cargo_stats(parsed)
        ship = await run_ship_stats()
        return {"stat_date": str(parsed or date.today()), "cargo": cargo, "ship": ship}

    return asyncio.run(_run())


__all__ = [
    "run_cargo_stats",
    "run_cargo_stats_task",
    "daily_stats_job",
]
