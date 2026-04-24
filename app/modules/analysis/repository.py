"""analysis 模块 repository。"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import (
    CargoChannelDaily,
    StatCargoCityDaily,
    StatCargoCommodityDaily,
    StatCargoDaily,
    StatCargoFlowDaily,
    StatJobRun,
    StatShipCityDaily,
    StatShipFlowDaily,
)
from app.models.commodity import CommodityStandard, CommodityType


class CargoAnalysisRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_cargo_daily(
        self,
        stat_date_from: date | None,
        stat_date_to: date | None,
        source_type: str | None,
        source_channel: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[StatCargoDaily], int]:
        stmt = select(StatCargoDaily)
        if stat_date_from:
            stmt = stmt.where(StatCargoDaily.stat_date >= stat_date_from)
        if stat_date_to:
            stmt = stmt.where(StatCargoDaily.stat_date <= stat_date_to)
        # 当前 StatCargoDaily ORM 未落地 source_type/source_channel 字段；参数保留用于后续演进。
        _ = (source_type, source_channel)

        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(StatCargoDaily.stat_date.desc(), StatCargoDaily.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def list_cargo_city_daily(
        self,
        stat_date_from: date | None,
        stat_date_to: date | None,
        city_code: str | None,
        role_type: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[StatCargoCityDaily], int]:
        stmt = select(StatCargoCityDaily)
        if stat_date_from:
            stmt = stmt.where(StatCargoCityDaily.stat_date >= stat_date_from)
        if stat_date_to:
            stmt = stmt.where(StatCargoCityDaily.stat_date <= stat_date_to)
        if city_code:
            stmt = stmt.where(StatCargoCityDaily.city_code == city_code)
        if role_type:
            role = role_type.strip().upper()
            if role == "LOADING":
                stmt = stmt.where(StatCargoCityDaily.loading_count > 0)
            elif role == "UNLOADING":
                stmt = stmt.where(StatCargoCityDaily.unloading_count > 0)

        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(StatCargoCityDaily.stat_date.desc(), StatCargoCityDaily.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def list_cargo_flow_daily(
        self,
        stat_date_from: date | None,
        stat_date_to: date | None,
        origin_city_code: str | None,
        destination_city_code: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[StatCargoFlowDaily], int]:
        stmt = select(StatCargoFlowDaily)
        if stat_date_from:
            stmt = stmt.where(StatCargoFlowDaily.stat_date >= stat_date_from)
        if stat_date_to:
            stmt = stmt.where(StatCargoFlowDaily.stat_date <= stat_date_to)
        if origin_city_code:
            stmt = stmt.where(StatCargoFlowDaily.origin_city_code == origin_city_code)
        if destination_city_code:
            stmt = stmt.where(StatCargoFlowDaily.destination_city_code == destination_city_code)

        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(StatCargoFlowDaily.stat_date.desc(), StatCargoFlowDaily.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def list_cargo_commodity_daily(
        self,
        stat_date_from: date | None,
        stat_date_to: date | None,
        commodity_category_id: int | None,
        commodity_type_id: int | None,
        commodity_standard_id: int | None,
        page: int,
        page_size: int,
    ) -> tuple[list[StatCargoCommodityDaily], int]:
        stmt = select(StatCargoCommodityDaily)
        if stat_date_from:
            stmt = stmt.where(StatCargoCommodityDaily.stat_date >= stat_date_from)
        if stat_date_to:
            stmt = stmt.where(StatCargoCommodityDaily.stat_date <= stat_date_to)
        if commodity_standard_id is not None:
            stmt = stmt.where(StatCargoCommodityDaily.commodity_standard_id == commodity_standard_id)
        if commodity_type_id is not None or commodity_category_id is not None:
            stmt = stmt.join(
                CommodityStandard,
                CommodityStandard.id == StatCargoCommodityDaily.commodity_standard_id,
            )
        if commodity_type_id is not None:
            stmt = stmt.where(CommodityStandard.type_id == commodity_type_id)
        if commodity_category_id is not None:
            stmt = stmt.join(CommodityType, CommodityType.id == CommodityStandard.type_id).where(
                CommodityType.category_id == commodity_category_id
            )

        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(StatCargoCommodityDaily.stat_date.desc(), StatCargoCommodityDaily.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def list_cargo_channel_daily(
        self,
        stat_date_from: date | None,
        stat_date_to: date | None,
        source_type: str | None,
        source_channel: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[CargoChannelDaily], int]:
        stmt = select(CargoChannelDaily)
        if stat_date_from:
            stmt = stmt.where(CargoChannelDaily.stat_date >= stat_date_from)
        if stat_date_to:
            stmt = stmt.where(CargoChannelDaily.stat_date <= stat_date_to)
        if source_type:
            stmt = stmt.where(CargoChannelDaily.source_type_code == source_type)
        # 当前 CargoChannelDaily ORM 未落地 source_channel 字段；参数保留用于后续演进。
        _ = source_channel

        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(CargoChannelDaily.stat_date.desc(), CargoChannelDaily.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(rows), total


class ShipAnalysisRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_ship_city_daily(
        self,
        stat_date_from: date | None,
        stat_date_to: date | None,
        city_code: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[StatShipCityDaily], int]:
        stmt = select(StatShipCityDaily)
        if stat_date_from:
            stmt = stmt.where(StatShipCityDaily.stat_date >= stat_date_from)
        if stat_date_to:
            stmt = stmt.where(StatShipCityDaily.stat_date <= stat_date_to)
        if city_code:
            stmt = stmt.where(StatShipCityDaily.city_code == city_code)

        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(StatShipCityDaily.stat_date.desc(), StatShipCityDaily.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def list_ship_flow_daily(
        self,
        stat_date_from: date | None,
        stat_date_to: date | None,
        origin_city_code: str | None,
        destination_city_code: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[StatShipFlowDaily], int]:
        stmt = select(StatShipFlowDaily)
        if stat_date_from:
            stmt = stmt.where(StatShipFlowDaily.stat_date >= stat_date_from)
        if stat_date_to:
            stmt = stmt.where(StatShipFlowDaily.stat_date <= stat_date_to)
        if origin_city_code:
            stmt = stmt.where(StatShipFlowDaily.origin_city_code == origin_city_code)
        if destination_city_code:
            stmt = stmt.where(StatShipFlowDaily.destination_city_code == destination_city_code)

        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(StatShipFlowDaily.stat_date.desc(), StatShipFlowDaily.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(rows), total


class StatJobRunRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_job_runs(
        self,
        job_type: str | None,
        status_code: str | None,
        stat_date_from: date | None,
        stat_date_to: date | None,
        page: int,
        page_size: int,
    ) -> tuple[list[StatJobRun], int]:
        stmt = select(StatJobRun)
        if job_type:
            stmt = stmt.where(StatJobRun.job_code == job_type)
        if status_code:
            stmt = stmt.where(StatJobRun.status_code == status_code)
        if stat_date_from:
            stmt = stmt.where(StatJobRun.stat_date >= stat_date_from)
        if stat_date_to:
            stmt = stmt.where(StatJobRun.stat_date <= stat_date_to)

        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(StatJobRun.stat_date.desc(), StatJobRun.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def get_job_run(self, job_run_id: int) -> StatJobRun | None:
        return await self.db.scalar(select(StatJobRun).where(StatJobRun.id == job_run_id))
