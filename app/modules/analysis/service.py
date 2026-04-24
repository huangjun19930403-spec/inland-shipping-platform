"""analysis 模块 service。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.modules.analysis.repository import (
    CargoAnalysisRepository,
    ShipAnalysisRepository,
    StatJobRunRepository,
)
from app.modules.analysis.schemas import (
    CargoChannelDailyResponse,
    CargoCityDailyResponse,
    CargoCommodityDailyResponse,
    CargoDailyResponse,
    CargoFlowDailyResponse,
    PageResponse,
    ShipCityDailyResponse,
    ShipFlowDailyResponse,
    StatJobRunDetailResponse,
    StatJobRunResponse,
)


def _to_cargo_daily_response(entity) -> CargoDailyResponse:
    return CargoDailyResponse(
        id=entity.id,
        stat_date=entity.stat_date,
        total_freight_count=entity.total_freight_count,
        total_tonnage=entity.total_tonnage,
        total_estimated_amount=entity.total_estimated_amount,
        data_version=entity.data_version,
        generated_at=entity.generated_at,
    )


def _to_cargo_city_daily_response(entity) -> CargoCityDailyResponse:
    return CargoCityDailyResponse(
        id=entity.id,
        stat_date=entity.stat_date,
        city_code=entity.city_code,
        freight_count=entity.freight_count,
        tonnage=entity.tonnage,
        loading_count=entity.loading_count,
        unloading_count=entity.unloading_count,
        data_version=entity.data_version,
        generated_at=entity.generated_at,
    )


def _to_cargo_flow_daily_response(entity) -> CargoFlowDailyResponse:
    return CargoFlowDailyResponse(
        id=entity.id,
        stat_date=entity.stat_date,
        origin_city_code=entity.origin_city_code,
        destination_city_code=entity.destination_city_code,
        freight_count=entity.freight_count,
        tonnage=entity.tonnage,
        data_version=entity.data_version,
        generated_at=entity.generated_at,
    )


def _to_cargo_commodity_daily_response(entity) -> CargoCommodityDailyResponse:
    return CargoCommodityDailyResponse(
        id=entity.id,
        stat_date=entity.stat_date,
        commodity_standard_id=entity.commodity_standard_id,
        freight_count=entity.freight_count,
        tonnage=entity.tonnage,
        avg_unit_price=entity.avg_unit_price,
        data_version=entity.data_version,
        generated_at=entity.generated_at,
    )


def _to_cargo_channel_daily_response(entity) -> CargoChannelDailyResponse:
    return CargoChannelDailyResponse(
        id=entity.id,
        stat_date=entity.stat_date,
        source_type_code=entity.source_type_code,
        incoming_count=entity.incoming_count,
        valid_count=entity.valid_count,
        invalid_count=entity.invalid_count,
        confirmed_count=entity.confirmed_count,
        formalized_count=entity.formalized_count,
        data_version=entity.data_version,
        generated_at=entity.generated_at,
    )


def _to_ship_city_daily_response(entity) -> ShipCityDailyResponse:
    return ShipCityDailyResponse(
        id=entity.id,
        stat_date=entity.stat_date,
        city_code=entity.city_code,
        active_ship_count=entity.active_ship_count,
        total_deadweight_ton=entity.total_deadweight_ton,
        data_version=entity.data_version,
        generated_at=entity.generated_at,
    )


def _to_ship_flow_daily_response(entity) -> ShipFlowDailyResponse:
    return ShipFlowDailyResponse(
        id=entity.id,
        stat_date=entity.stat_date,
        origin_city_code=entity.origin_city_code,
        destination_city_code=entity.destination_city_code,
        ship_count=entity.ship_count,
        voyage_count=entity.voyage_count,
        total_deadweight_ton=entity.total_deadweight_ton,
        data_version=entity.data_version,
        generated_at=entity.generated_at,
    )


def _to_stat_job_run_response(entity) -> StatJobRunResponse:
    return StatJobRunResponse(
        id=entity.id,
        job_code=entity.job_code,
        stat_date=entity.stat_date,
        scope_desc=entity.scope_desc,
        started_at=entity.started_at,
        finished_at=entity.finished_at,
        status_code=entity.status_code,
        affected_rows=entity.affected_rows,
        error_message=entity.error_message,
        triggered_by=entity.triggered_by,
        created_at=entity.created_at,
    )


class CargoAnalysisService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = CargoAnalysisRepository(db)

    async def list_cargo_daily(
        self,
        stat_date_from,
        stat_date_to,
        source_type,
        source_channel,
        page: int,
        page_size: int,
    ) -> PageResponse[CargoDailyResponse]:
        rows, total = await self.repo.list_cargo_daily(
            stat_date_from,
            stat_date_to,
            source_type,
            source_channel,
            page,
            page_size,
        )
        return PageResponse[CargoDailyResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_cargo_daily_response(item) for item in rows],
        )

    async def list_cargo_city_daily(
        self,
        stat_date_from,
        stat_date_to,
        city_code,
        role_type,
        page: int,
        page_size: int,
    ) -> PageResponse[CargoCityDailyResponse]:
        rows, total = await self.repo.list_cargo_city_daily(
            stat_date_from,
            stat_date_to,
            city_code,
            role_type,
            page,
            page_size,
        )
        return PageResponse[CargoCityDailyResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_cargo_city_daily_response(item) for item in rows],
        )

    async def list_cargo_flow_daily(
        self,
        stat_date_from,
        stat_date_to,
        origin_city_code,
        destination_city_code,
        page: int,
        page_size: int,
    ) -> PageResponse[CargoFlowDailyResponse]:
        rows, total = await self.repo.list_cargo_flow_daily(
            stat_date_from,
            stat_date_to,
            origin_city_code,
            destination_city_code,
            page,
            page_size,
        )
        return PageResponse[CargoFlowDailyResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_cargo_flow_daily_response(item) for item in rows],
        )

    async def list_cargo_commodity_daily(
        self,
        stat_date_from,
        stat_date_to,
        commodity_category_id,
        commodity_type_id,
        commodity_standard_id,
        page: int,
        page_size: int,
    ) -> PageResponse[CargoCommodityDailyResponse]:
        rows, total = await self.repo.list_cargo_commodity_daily(
            stat_date_from,
            stat_date_to,
            commodity_category_id,
            commodity_type_id,
            commodity_standard_id,
            page,
            page_size,
        )
        return PageResponse[CargoCommodityDailyResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_cargo_commodity_daily_response(item) for item in rows],
        )

    async def list_cargo_channel_daily(
        self,
        stat_date_from,
        stat_date_to,
        source_type,
        source_channel,
        page: int,
        page_size: int,
    ) -> PageResponse[CargoChannelDailyResponse]:
        rows, total = await self.repo.list_cargo_channel_daily(
            stat_date_from,
            stat_date_to,
            source_type,
            source_channel,
            page,
            page_size,
        )
        return PageResponse[CargoChannelDailyResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_cargo_channel_daily_response(item) for item in rows],
        )


class ShipAnalysisService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = ShipAnalysisRepository(db)

    async def list_ship_city_daily(
        self,
        stat_date_from,
        stat_date_to,
        city_code,
        page: int,
        page_size: int,
    ) -> PageResponse[ShipCityDailyResponse]:
        rows, total = await self.repo.list_ship_city_daily(
            stat_date_from,
            stat_date_to,
            city_code,
            page,
            page_size,
        )
        return PageResponse[ShipCityDailyResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_ship_city_daily_response(item) for item in rows],
        )

    async def list_ship_flow_daily(
        self,
        stat_date_from,
        stat_date_to,
        origin_city_code,
        destination_city_code,
        page: int,
        page_size: int,
    ) -> PageResponse[ShipFlowDailyResponse]:
        rows, total = await self.repo.list_ship_flow_daily(
            stat_date_from,
            stat_date_to,
            origin_city_code,
            destination_city_code,
            page,
            page_size,
        )
        return PageResponse[ShipFlowDailyResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_ship_flow_daily_response(item) for item in rows],
        )


class StatJobRunService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = StatJobRunRepository(db)

    async def list_job_runs(
        self,
        job_type,
        status_code,
        stat_date_from,
        stat_date_to,
        page: int,
        page_size: int,
    ) -> PageResponse[StatJobRunResponse]:
        rows, total = await self.repo.list_job_runs(
            job_type,
            status_code,
            stat_date_from,
            stat_date_to,
            page,
            page_size,
        )
        return PageResponse[StatJobRunResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_stat_job_run_response(item) for item in rows],
        )

    async def get_job_run_detail(self, job_run_id: int) -> StatJobRunDetailResponse:
        entity = await self.repo.get_job_run(job_run_id)
        if entity is None:
            raise NotFoundError("StatJobRun", job_run_id)
        return StatJobRunDetailResponse(**_to_stat_job_run_response(entity).model_dump())
