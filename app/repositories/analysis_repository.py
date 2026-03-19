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

from app.models.analysis import (
    CargoCityHeatmap,
    CargoStatDaily,
    CargoCommodityStatDaily,
    CargoOdDaily,
    CargoChannelDaily,
    ShipStatRegion,
    ShipStatCity,
    ShipStatDwt,
    ShipStatAge,
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
    # 仪表盘汇总
    # ─────────────────────────────────────────────────

    async def get_latest_cargo_stat(self) -> Optional[CargoStatDaily]:
        """获取最新一天的货源汇总"""
        result = await self._db.execute(
            select(CargoStatDaily).order_by(desc(CargoStatDaily.stat_date)).limit(1)
        )
        return result.scalar_one_or_none()

    # ─────────────────────────────────────────────────
    # ShipStatRegion — 区域热力快照（只读）
    # ─────────────────────────────────────────────────

    async def get_ship_stat_region(self) -> Sequence[ShipStatRegion]:
        """返回全部区域热力快照，按 vessel_count 降序"""
        result = await self._db.execute(
            select(ShipStatRegion).order_by(desc(ShipStatRegion.vessel_count))
        )
        return result.scalars().all()

    # ─────────────────────────────────────────────────
    # ShipStatCity — 城市热力快照（只读）
    # ─────────────────────────────────────────────────

    async def get_ship_stat_city(
        self, province_name: Optional[str] = None
    ) -> Sequence[ShipStatCity]:
        """返回城市热力快照，可按省份过滤，按 vessel_count 降序"""
        filters = []
        if province_name:
            filters.append(ShipStatCity.province_name == province_name)
        stmt = select(ShipStatCity).order_by(desc(ShipStatCity.vessel_count))
        if filters:
            stmt = stmt.where(and_(*filters))
        result = await self._db.execute(stmt)
        return result.scalars().all()

    # ─────────────────────────────────────────────────
    # ShipStatDwt — 载重吨分布快照（只读）
    # ─────────────────────────────────────────────────

    async def get_ship_stat_dwt(self) -> Sequence[ShipStatDwt]:
        """返回全部载重吨区间分布快照，按 min_dwt 排序（NULL 排末尾）"""
        result = await self._db.execute(
            select(ShipStatDwt).order_by(
                ShipStatDwt.min_dwt.is_(None),
                ShipStatDwt.min_dwt,
            )
        )
        return result.scalars().all()

    # ─────────────────────────────────────────────────
    # ShipStatAge — 船龄分布快照（只读）
    # ─────────────────────────────────────────────────

    async def get_ship_stat_age(self) -> Sequence[ShipStatAge]:
        """返回全部船龄区间分布快照，按 min_age 排序（NULL 排末尾）"""
        result = await self._db.execute(
            select(ShipStatAge).order_by(
                ShipStatAge.min_age.is_(None),
                ShipStatAge.min_age,
            )
        )
        return result.scalars().all()
