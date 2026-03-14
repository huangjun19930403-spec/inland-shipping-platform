"""
数据分析访问层
"""
from datetime import date
from typing import Optional, Sequence

from sqlalchemy import select, and_, func, desc

from app.models.analysis import HeatmapStatDaily
from app.models.cargo import CargoOpportunity
from app.models.vessel import VesselDynamic
from app.repositories.base import BaseRepository


class AnalysisRepository(BaseRepository):
    model_class = HeatmapStatDaily

    # ─────────────────────────────────────────────────
    # HeatmapStatDaily
    # ─────────────────────────────────────────────────

    async def get_heatmap_stats(
        self,
        stat_date: date,
        stat_type: Optional[str] = None,
    ) -> Sequence[HeatmapStatDaily]:
        filters = [HeatmapStatDaily.stat_date == stat_date]
        if stat_type:
            filters.append(HeatmapStatDaily.stat_type == stat_type)

        result = await self._db.execute(
            select(HeatmapStatDaily).where(and_(*filters))
        )
        return result.scalars().all()

    async def get_heatmap_range(
        self,
        start_date: date,
        end_date: date,
        node_id: Optional[int] = None,
    ) -> Sequence[HeatmapStatDaily]:
        filters = [
            HeatmapStatDaily.stat_date >= start_date,
            HeatmapStatDaily.stat_date <= end_date,
        ]
        if node_id:
            filters.append(HeatmapStatDaily.node_id == node_id)

        result = await self._db.execute(
            select(HeatmapStatDaily)
            .where(and_(*filters))
            .order_by(HeatmapStatDaily.stat_date)
        )
        return result.scalars().all()

    async def upsert_heatmap_stat(
        self,
        stat_date: date,
        node_id: int,
        stat_type: str,
        stat_value: int,
    ) -> HeatmapStatDaily:
        result = await self._db.execute(
            select(HeatmapStatDaily).where(
                and_(
                    HeatmapStatDaily.stat_date == stat_date,
                    HeatmapStatDaily.node_id == node_id,
                    HeatmapStatDaily.stat_type == stat_type,
                )
            )
        )
        stat = result.scalar_one_or_none()
        if stat:
            stat.stat_value = stat_value
        else:
            stat = HeatmapStatDaily(
                stat_date=stat_date,
                node_id=node_id,
                stat_type=stat_type,
                stat_value=stat_value,
            )
            self._db.add(stat)
        await self._db.flush()
        return stat

    # ─────────────────────────────────────────────────
    # Dashboard聚合查询
    # ─────────────────────────────────────────────────

    async def count_opportunities_by_status(self) -> dict:
        result = await self._db.execute(
            select(
                CargoOpportunity.status,
                func.count(CargoOpportunity.id).label("count"),
            ).group_by(CargoOpportunity.status)
        )
        return {row.status: row.count for row in result.all()}

    async def count_active_vessels(self) -> int:
        result = await self._db.execute(
            select(func.count(VesselDynamic.id))
        )
        return result.scalar_one()

    async def get_daily_cargo_trend(
        self, days: int = 7
    ) -> Sequence[HeatmapStatDaily]:
        from datetime import timedelta, date as date_type
        end = date_type.today()
        start = end - timedelta(days=days)

        result = await self._db.execute(
            select(
                HeatmapStatDaily.stat_date,
                func.sum(HeatmapStatDaily.stat_value).label("total"),
            )
            .where(
                and_(
                    HeatmapStatDaily.stat_date >= start,
                    HeatmapStatDaily.stat_date <= end,
                    HeatmapStatDaily.stat_type == "CARGO",
                )
            )
            .group_by(HeatmapStatDaily.stat_date)
            .order_by(HeatmapStatDaily.stat_date)
        )
        return result.all()
