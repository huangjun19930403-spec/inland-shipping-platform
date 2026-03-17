"""
数据分析访问层

规则：
  - 本 Repository 只查询统计表（analysis 模块）
  - 禁止直接查询业务表（cargo_opportunity / vessel / vessel_dynamic 等）
  - ETL 逻辑（业务表 → 统计表）集中在 app/tasks/stat_tasks.py
"""
from datetime import date, timedelta
from typing import Optional, Sequence, List

from sqlalchemy import select, and_, func, desc, delete
from sqlalchemy.orm import joinedload

from app.models.analysis import (
    CargoHeatmapDaily,
    ShipHeatmapDaily,
    CargoStatDaily,
    CargoCommodityStatDaily,
    CargoRegionStatDaily,
    ShipCapacityRegionDaily,
    ShipTypeStatDaily,
    ShipAgeStatDaily,
)
from app.repositories.base import BaseRepository


class AnalysisRepository(BaseRepository):
    model_class = CargoStatDaily

    # ─────────────────────────────────────────────────
    # CargoHeatmapDaily — 货源热力统计
    # ─────────────────────────────────────────────────

    async def get_cargo_heatmap(
        self,
        stat_date: date,
        stat_type: Optional[str] = None,
    ) -> Sequence[CargoHeatmapDaily]:
        filters = [CargoHeatmapDaily.stat_date == stat_date]
        if stat_type:
            filters.append(CargoHeatmapDaily.stat_type == stat_type)
        result = await self._db.execute(
            select(CargoHeatmapDaily)
            .options(joinedload(CargoHeatmapDaily.node))
            .where(and_(*filters))
            .order_by(desc(CargoHeatmapDaily.cargo_count))
        )
        return result.unique().scalars().all()

    async def upsert_cargo_heatmap(
        self,
        stat_date: date,
        node_id: int,
        stat_type: str,
        cargo_count: int,
        total_tonnage: float,
    ) -> None:
        result = await self._db.execute(
            select(CargoHeatmapDaily).where(
                and_(
                    CargoHeatmapDaily.stat_date == stat_date,
                    CargoHeatmapDaily.node_id == node_id,
                    CargoHeatmapDaily.stat_type == stat_type,
                )
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.cargo_count = cargo_count
            row.total_tonnage = total_tonnage
        else:
            self._db.add(CargoHeatmapDaily(
                stat_date=stat_date, node_id=node_id, stat_type=stat_type,
                cargo_count=cargo_count, total_tonnage=total_tonnage,
            ))
        await self._db.flush()

    # ─────────────────────────────────────────────────
    # ShipHeatmapDaily — 船舶热力统计
    # ─────────────────────────────────────────────────

    async def get_ship_heatmap(self, stat_date: date) -> Sequence[ShipHeatmapDaily]:
        result = await self._db.execute(
            select(ShipHeatmapDaily)
            .options(joinedload(ShipHeatmapDaily.node))
            .where(ShipHeatmapDaily.stat_date == stat_date)
            .order_by(desc(ShipHeatmapDaily.vessel_count))
        )
        return result.unique().scalars().all()

    async def upsert_ship_heatmap(
        self,
        stat_date: date,
        node_id: int,
        vessel_count: int,
        total_deadweight: float,
    ) -> None:
        result = await self._db.execute(
            select(ShipHeatmapDaily).where(
                and_(
                    ShipHeatmapDaily.stat_date == stat_date,
                    ShipHeatmapDaily.node_id == node_id,
                )
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.vessel_count = vessel_count
            row.total_deadweight = total_deadweight
        else:
            self._db.add(ShipHeatmapDaily(
                stat_date=stat_date, node_id=node_id,
                vessel_count=vessel_count, total_deadweight=total_deadweight,
            ))
        await self._db.flush()

    # ─────────────────────────────────────────────────
    # CargoStatDaily — 货源每日汇总（用于趋势图 + 仪表盘）
    # ─────────────────────────────────────────────────

    async def get_cargo_stat_daily(self, stat_date: date) -> Optional[CargoStatDaily]:
        result = await self._db.execute(
            select(CargoStatDaily).where(CargoStatDaily.stat_date == stat_date)
        )
        return result.scalar_one_or_none()

    async def get_cargo_trend(self, days: int = 30) -> Sequence[CargoStatDaily]:
        """获取最近 days 天的货源趋势"""
        start = date.today() - timedelta(days=days - 1)
        result = await self._db.execute(
            select(CargoStatDaily)
            .where(CargoStatDaily.stat_date >= start)
            .order_by(CargoStatDaily.stat_date)
        )
        return result.scalars().all()

    async def upsert_cargo_stat(
        self,
        stat_date: date,
        total_count: int,
        active_count: int,
        pending_count: int,
        total_tonnage: float,
    ) -> None:
        result = await self._db.execute(
            select(CargoStatDaily).where(CargoStatDaily.stat_date == stat_date)
        )
        row = result.scalar_one_or_none()
        if row:
            row.total_count = total_count
            row.active_count = active_count
            row.pending_count = pending_count
            row.total_tonnage = total_tonnage
        else:
            self._db.add(CargoStatDaily(
                stat_date=stat_date, total_count=total_count,
                active_count=active_count, pending_count=pending_count,
                total_tonnage=total_tonnage,
            ))
        await self._db.flush()

    # ─────────────────────────────────────────────────
    # CargoCommodityStatDaily — 货品分类排名
    # ─────────────────────────────────────────────────

    async def get_cargo_commodity_stat(
        self, stat_date: date
    ) -> Sequence[CargoCommodityStatDaily]:
        result = await self._db.execute(
            select(CargoCommodityStatDaily)
            .where(CargoCommodityStatDaily.stat_date == stat_date)
            .order_by(desc(CargoCommodityStatDaily.cargo_count))
        )
        return result.scalars().all()

    async def upsert_cargo_commodity_stat(
        self,
        stat_date: date,
        commodity_category_id: int,
        category_name: str,
        cargo_count: int,
        total_tonnage: float,
    ) -> None:
        result = await self._db.execute(
            select(CargoCommodityStatDaily).where(
                and_(
                    CargoCommodityStatDaily.stat_date == stat_date,
                    CargoCommodityStatDaily.commodity_category_id == commodity_category_id,
                )
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.cargo_count = cargo_count
            row.total_tonnage = total_tonnage
            row.category_name = category_name
        else:
            self._db.add(CargoCommodityStatDaily(
                stat_date=stat_date,
                commodity_category_id=commodity_category_id,
                category_name=category_name,
                cargo_count=cargo_count,
                total_tonnage=total_tonnage,
            ))
        await self._db.flush()

    # ─────────────────────────────────────────────────
    # CargoRegionStatDaily — 区域货源分布
    # ─────────────────────────────────────────────────

    async def get_cargo_region_stat(
        self,
        stat_date: date,
        stat_type: Optional[str] = None,
    ) -> Sequence[CargoRegionStatDaily]:
        filters = [CargoRegionStatDaily.stat_date == stat_date]
        if stat_type:
            filters.append(CargoRegionStatDaily.stat_type == stat_type)
        result = await self._db.execute(
            select(CargoRegionStatDaily)
            .where(and_(*filters))
            .order_by(desc(CargoRegionStatDaily.cargo_count))
        )
        return result.scalars().all()

    async def upsert_cargo_region_stat(
        self,
        stat_date: date,
        region_id: int,
        region_name: str,
        stat_type: str,
        cargo_count: int,
        total_tonnage: float,
    ) -> None:
        result = await self._db.execute(
            select(CargoRegionStatDaily).where(
                and_(
                    CargoRegionStatDaily.stat_date == stat_date,
                    CargoRegionStatDaily.region_id == region_id,
                    CargoRegionStatDaily.stat_type == stat_type,
                )
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.cargo_count = cargo_count
            row.total_tonnage = total_tonnage
            row.region_name = region_name
        else:
            self._db.add(CargoRegionStatDaily(
                stat_date=stat_date, region_id=region_id, region_name=region_name,
                stat_type=stat_type, cargo_count=cargo_count, total_tonnage=total_tonnage,
            ))
        await self._db.flush()

    # ─────────────────────────────────────────────────
    # ShipCapacityRegionDaily — 区域运力分布
    # ─────────────────────────────────────────────────

    async def get_ship_capacity_region(
        self, stat_date: date
    ) -> Sequence[ShipCapacityRegionDaily]:
        result = await self._db.execute(
            select(ShipCapacityRegionDaily)
            .where(ShipCapacityRegionDaily.stat_date == stat_date)
            .order_by(desc(ShipCapacityRegionDaily.vessel_count))
        )
        return result.scalars().all()

    async def upsert_ship_capacity_region(
        self,
        stat_date: date,
        region_id: int,
        region_name: str,
        vessel_count: int,
        total_deadweight: float,
    ) -> None:
        result = await self._db.execute(
            select(ShipCapacityRegionDaily).where(
                and_(
                    ShipCapacityRegionDaily.stat_date == stat_date,
                    ShipCapacityRegionDaily.region_id == region_id,
                )
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.vessel_count = vessel_count
            row.total_deadweight = total_deadweight
            row.region_name = region_name
        else:
            self._db.add(ShipCapacityRegionDaily(
                stat_date=stat_date, region_id=region_id, region_name=region_name,
                vessel_count=vessel_count, total_deadweight=total_deadweight,
            ))
        await self._db.flush()

    # ─────────────────────────────────────────────────
    # ShipTypeStatDaily — 船舶类型统计
    # ─────────────────────────────────────────────────

    async def get_ship_type_stat(self, stat_date: date) -> Sequence[ShipTypeStatDaily]:
        result = await self._db.execute(
            select(ShipTypeStatDaily)
            .where(ShipTypeStatDaily.stat_date == stat_date)
            .order_by(desc(ShipTypeStatDaily.vessel_count))
        )
        return result.scalars().all()

    async def upsert_ship_type_stat(
        self,
        stat_date: date,
        vessel_type_id: int,
        type_name: str,
        vessel_count: int,
        total_deadweight: float,
    ) -> None:
        result = await self._db.execute(
            select(ShipTypeStatDaily).where(
                and_(
                    ShipTypeStatDaily.stat_date == stat_date,
                    ShipTypeStatDaily.vessel_type_id == vessel_type_id,
                )
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.vessel_count = vessel_count
            row.total_deadweight = total_deadweight
            row.type_name = type_name
        else:
            self._db.add(ShipTypeStatDaily(
                stat_date=stat_date, vessel_type_id=vessel_type_id,
                type_name=type_name, vessel_count=vessel_count,
                total_deadweight=total_deadweight,
            ))
        await self._db.flush()

    # ─────────────────────────────────────────────────
    # ShipAgeStatDaily — 船龄分布
    # ─────────────────────────────────────────────────

    async def get_ship_age_stat(self, stat_date: date) -> Sequence[ShipAgeStatDaily]:
        _ORDER = ["0-5", "5-10", "10-15", "15-20", "20+"]
        result = await self._db.execute(
            select(ShipAgeStatDaily).where(ShipAgeStatDaily.stat_date == stat_date)
        )
        rows = result.scalars().all()
        return sorted(rows, key=lambda r: _ORDER.index(r.age_group) if r.age_group in _ORDER else 99)

    async def upsert_ship_age_stat(
        self,
        stat_date: date,
        age_group: str,
        vessel_count: int,
    ) -> None:
        result = await self._db.execute(
            select(ShipAgeStatDaily).where(
                and_(
                    ShipAgeStatDaily.stat_date == stat_date,
                    ShipAgeStatDaily.age_group == age_group,
                )
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.vessel_count = vessel_count
        else:
            self._db.add(ShipAgeStatDaily(
                stat_date=stat_date, age_group=age_group, vessel_count=vessel_count,
            ))
        await self._db.flush()

    # ─────────────────────────────────────────────────
    # 仪表盘汇总（从统计表读取，避免查业务表）
    # ─────────────────────────────────────────────────

    async def get_latest_cargo_stat(self) -> Optional[CargoStatDaily]:
        """获取最新一天的货源汇总"""
        result = await self._db.execute(
            select(CargoStatDaily).order_by(desc(CargoStatDaily.stat_date)).limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_ship_total(self) -> dict:
        """获取最新一天的全国船舶合计"""
        result = await self._db.execute(
            select(
                func.max(ShipCapacityRegionDaily.stat_date).label("latest_date"),
            )
        )
        latest_date = result.scalar_one_or_none()
        if not latest_date:
            return {"vessel_count": 0, "total_deadweight": 0}
        result2 = await self._db.execute(
            select(
                func.sum(ShipCapacityRegionDaily.vessel_count).label("vessel_count"),
                func.sum(ShipCapacityRegionDaily.total_deadweight).label("total_deadweight"),
            ).where(ShipCapacityRegionDaily.stat_date == latest_date)
        )
        row = result2.one()
        return {
            "vessel_count": int(row.vessel_count or 0),
            "total_deadweight": float(row.total_deadweight or 0),
        }
