"""
数据分析访问层

规则：
  - 本 Repository 只查询统计表（analysis 模块）
  - 禁止直接查询业务表（cargo_freight / vessel / vessel_dynamic 等）
  - ETL 逻辑（业务表 → 统计表）集中在 app/tasks/stat_tasks.py
"""
from datetime import date, timedelta
from typing import Optional, Sequence

from sqlalchemy import select, and_, func, desc
from sqlalchemy.orm import joinedload

from app.models.analysis import (
    CargoCityHeatmap,
    ShipHeatmapDaily,
    CargoStatDaily,
    CargoCommodityStatDaily,
    CargoOdDaily,
    CargoChannelDaily,
    ShipTypeStatDaily,
)
from app.repositories.base import BaseRepository


class AnalysisRepository(BaseRepository):
    model_class = CargoStatDaily

    # ─────────────────────────────────────────────────
    # CargoCityHeatmap — 货源城市热力统计
    # ─────────────────────────────────────────────────

    async def get_cargo_city_heatmap(
        self,
        stat_date: date,
        stat_type: Optional[str] = None,
    ) -> Sequence[CargoCityHeatmap]:
        filters = [CargoCityHeatmap.stat_date == stat_date]
        if stat_type:
            filters.append(CargoCityHeatmap.stat_type == stat_type)
        result = await self._db.execute(
            select(CargoCityHeatmap)
            .where(and_(*filters))
            .order_by(desc(CargoCityHeatmap.cargo_count))
        )
        return result.scalars().all()

    async def upsert_cargo_city_heatmap(
        self,
        stat_date: date,
        city_code: str,
        city_name: str,
        stat_type: str,
        cargo_count: int,
        total_tonnage: float,
        city_longitude: Optional[float] = None,
        city_latitude: Optional[float] = None,
    ) -> None:
        result = await self._db.execute(
            select(CargoCityHeatmap).where(
                and_(
                    CargoCityHeatmap.stat_date == stat_date,
                    CargoCityHeatmap.city_code == city_code,
                    CargoCityHeatmap.stat_type == stat_type,
                )
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.cargo_count = cargo_count
            row.total_tonnage = total_tonnage
            row.city_name = city_name
            if city_longitude is not None:
                row.city_longitude = city_longitude
            if city_latitude is not None:
                row.city_latitude = city_latitude
        else:
            self._db.add(CargoCityHeatmap(
                stat_date=stat_date,
                city_code=city_code,
                city_name=city_name,
                stat_type=stat_type,
                cargo_count=cargo_count,
                total_tonnage=total_tonnage,
                city_longitude=city_longitude,
                city_latitude=city_latitude,
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
    # CargoStatDaily — 货源每日汇总（趋势图 + 仪表盘）
    # ─────────────────────────────────────────────────

    async def get_cargo_trend(
        self,
        days: int = 30,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Sequence[CargoStatDaily]:
        if start_date is None:
            start_date = date.today() - timedelta(days=days - 1)
        filters = [CargoStatDaily.stat_date >= start_date]
        if end_date:
            filters.append(CargoStatDaily.stat_date <= end_date)
        result = await self._db.execute(
            select(CargoStatDaily)
            .where(and_(*filters))
            .order_by(CargoStatDaily.stat_date)
        )
        return result.scalars().all()

    async def upsert_cargo_stat(
        self,
        stat_date: date,
        total_count: int,
        confirmed_count: int,
        pending_count: int,
        total_tonnage: float,
        avg_tonnage: float,
    ) -> None:
        result = await self._db.execute(
            select(CargoStatDaily).where(CargoStatDaily.stat_date == stat_date)
        )
        row = result.scalar_one_or_none()
        if row:
            row.total_count = total_count
            row.confirmed_count = confirmed_count
            row.pending_count = pending_count
            row.total_tonnage = total_tonnage
            row.avg_tonnage = avg_tonnage
        else:
            self._db.add(CargoStatDaily(
                stat_date=stat_date,
                total_count=total_count,
                confirmed_count=confirmed_count,
                pending_count=pending_count,
                total_tonnage=total_tonnage,
                avg_tonnage=avg_tonnage,
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
    # CargoOdDaily — 起终点城市OD流量矩阵
    # ─────────────────────────────────────────────────

    async def get_cargo_od_stat(
        self,
        stat_date: date,
        top_n: int = 20,
    ) -> Sequence[CargoOdDaily]:
        result = await self._db.execute(
            select(CargoOdDaily)
            .where(CargoOdDaily.stat_date == stat_date)
            .order_by(desc(CargoOdDaily.cargo_count))
            .limit(top_n)
        )
        return result.scalars().all()

    async def get_cargo_od_range(
        self,
        start_date: date,
        end_date: date,
        top_n: int = 20,
    ) -> Sequence:
        """按日期范围聚合OD流量，返回 (origin, dest, sum_count, sum_tonnage)"""
        result = await self._db.execute(
            select(
                CargoOdDaily.origin_city_code,
                CargoOdDaily.origin_city_name,
                CargoOdDaily.dest_city_code,
                CargoOdDaily.dest_city_name,
                func.sum(CargoOdDaily.cargo_count).label("cargo_count"),
                func.sum(CargoOdDaily.total_tonnage).label("total_tonnage"),
            )
            .where(
                and_(
                    CargoOdDaily.stat_date >= start_date,
                    CargoOdDaily.stat_date <= end_date,
                )
            )
            .group_by(
                CargoOdDaily.origin_city_code,
                CargoOdDaily.origin_city_name,
                CargoOdDaily.dest_city_code,
                CargoOdDaily.dest_city_name,
            )
            .order_by(desc("cargo_count"))
            .limit(top_n)
        )
        return result.all()

    async def upsert_cargo_od_stat(
        self,
        stat_date: date,
        origin_city_code: str,
        origin_city_name: str,
        dest_city_code: str,
        dest_city_name: str,
        cargo_count: int,
        total_tonnage: float,
    ) -> None:
        result = await self._db.execute(
            select(CargoOdDaily).where(
                and_(
                    CargoOdDaily.stat_date == stat_date,
                    CargoOdDaily.origin_city_code == origin_city_code,
                    CargoOdDaily.dest_city_code == dest_city_code,
                )
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.cargo_count = cargo_count
            row.total_tonnage = total_tonnage
            row.origin_city_name = origin_city_name
            row.dest_city_name = dest_city_name
        else:
            self._db.add(CargoOdDaily(
                stat_date=stat_date,
                origin_city_code=origin_city_code,
                origin_city_name=origin_city_name,
                dest_city_code=dest_city_code,
                dest_city_name=dest_city_name,
                cargo_count=cargo_count,
                total_tonnage=total_tonnage,
            ))
        await self._db.flush()

    # ─────────────────────────────────────────────────
    # CargoChannelDaily — 渠道质量统计
    # ─────────────────────────────────────────────────

    async def get_cargo_channel_stat(
        self,
        stat_date: date,
    ) -> Sequence[CargoChannelDaily]:
        result = await self._db.execute(
            select(CargoChannelDaily)
            .where(CargoChannelDaily.stat_date == stat_date)
            .order_by(desc(CargoChannelDaily.confirmed_count))
        )
        return result.scalars().all()

    async def get_cargo_channel_trend(
        self,
        days: int = 30,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Sequence[CargoChannelDaily]:
        if start_date is None:
            start_date = date.today() - timedelta(days=days - 1)
        filters = [CargoChannelDaily.stat_date >= start_date]
        if end_date:
            filters.append(CargoChannelDaily.stat_date <= end_date)
        result = await self._db.execute(
            select(CargoChannelDaily)
            .where(and_(*filters))
            .order_by(CargoChannelDaily.stat_date, CargoChannelDaily.source_type)
        )
        return result.scalars().all()

    async def upsert_cargo_channel_stat(
        self,
        stat_date: date,
        source_type: str,
        raw_msg_count: int,
        parse_success_count: int,
        confirmed_count: int,
        total_tonnage: float,
    ) -> None:
        result = await self._db.execute(
            select(CargoChannelDaily).where(
                and_(
                    CargoChannelDaily.stat_date == stat_date,
                    CargoChannelDaily.source_type == source_type,
                )
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.raw_msg_count = raw_msg_count
            row.parse_success_count = parse_success_count
            row.confirmed_count = confirmed_count
            row.total_tonnage = total_tonnage
        else:
            self._db.add(CargoChannelDaily(
                stat_date=stat_date,
                source_type=source_type,
                raw_msg_count=raw_msg_count,
                parse_success_count=parse_success_count,
                confirmed_count=confirmed_count,
                total_tonnage=total_tonnage,
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
    # 仪表盘汇总
    # ─────────────────────────────────────────────────

    async def get_latest_cargo_stat(self) -> Optional[CargoStatDaily]:
        """获取最新一天的货源汇总"""
        result = await self._db.execute(
            select(CargoStatDaily).order_by(desc(CargoStatDaily.stat_date)).limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_ship_total(self) -> dict:
        """获取最新一天的全国船舶合计（从 ship_heatmap_daily 汇总节点数据）"""
        result = await self._db.execute(
            select(func.max(ShipHeatmapDaily.stat_date).label("latest_date"))
        )
        latest_date = result.scalar_one_or_none()
        if not latest_date:
            return {"vessel_count": 0, "total_deadweight": 0}
        result2 = await self._db.execute(
            select(
                func.sum(ShipHeatmapDaily.vessel_count).label("vessel_count"),
                func.sum(ShipHeatmapDaily.total_deadweight).label("total_deadweight"),
            ).where(ShipHeatmapDaily.stat_date == latest_date)
        )
        row = result2.one()
        return {
            "vessel_count": int(row.vessel_count or 0),
            "total_deadweight": float(row.total_deadweight or 0),
        }
