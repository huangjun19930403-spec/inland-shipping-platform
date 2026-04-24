"""analysis 模块 router。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.modules.analysis.schemas import (
    CargoChannelDailyQuery,
    CargoChannelDailyResponse,
    CargoCityDailyQuery,
    CargoCityDailyResponse,
    CargoCommodityDailyQuery,
    CargoCommodityDailyResponse,
    CargoDailyQuery,
    CargoDailyResponse,
    CargoFlowDailyQuery,
    CargoFlowDailyResponse,
    PageResponse,
    ShipCityDailyQuery,
    ShipCityDailyResponse,
    ShipFlowDailyQuery,
    ShipFlowDailyResponse,
    StatJobRunDetailResponse,
    StatJobRunListQuery,
    StatJobRunResponse,
)
from app.modules.analysis.service import CargoAnalysisService, ShipAnalysisService, StatJobRunService

router = APIRouter()


@router.get("/cargo/daily", response_model=PageResponse[CargoDailyResponse])
async def list_cargo_daily(
    query: CargoDailyQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = CargoAnalysisService(db)
    return await service.list_cargo_daily(
        stat_date_from=query.stat_date_from,
        stat_date_to=query.stat_date_to,
        source_type=query.source_type,
        source_channel=query.source_channel,
        page=query.page,
        page_size=query.page_size,
    )


@router.get("/cargo/cities", response_model=PageResponse[CargoCityDailyResponse])
async def list_cargo_city_daily(
    query: CargoCityDailyQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = CargoAnalysisService(db)
    return await service.list_cargo_city_daily(
        stat_date_from=query.stat_date_from,
        stat_date_to=query.stat_date_to,
        city_code=query.city_code,
        role_type=query.role_type,
        page=query.page,
        page_size=query.page_size,
    )


@router.get("/cargo/flows", response_model=PageResponse[CargoFlowDailyResponse])
async def list_cargo_flow_daily(
    query: CargoFlowDailyQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = CargoAnalysisService(db)
    return await service.list_cargo_flow_daily(
        stat_date_from=query.stat_date_from,
        stat_date_to=query.stat_date_to,
        origin_city_code=query.origin_city_code,
        destination_city_code=query.destination_city_code,
        page=query.page,
        page_size=query.page_size,
    )


@router.get("/cargo/commodities", response_model=PageResponse[CargoCommodityDailyResponse])
async def list_cargo_commodity_daily(
    query: CargoCommodityDailyQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = CargoAnalysisService(db)
    return await service.list_cargo_commodity_daily(
        stat_date_from=query.stat_date_from,
        stat_date_to=query.stat_date_to,
        commodity_category_id=query.commodity_category_id,
        commodity_type_id=query.commodity_type_id,
        commodity_standard_id=query.commodity_standard_id,
        page=query.page,
        page_size=query.page_size,
    )


@router.get("/cargo/channels", response_model=PageResponse[CargoChannelDailyResponse])
async def list_cargo_channel_daily(
    query: CargoChannelDailyQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = CargoAnalysisService(db)
    return await service.list_cargo_channel_daily(
        stat_date_from=query.stat_date_from,
        stat_date_to=query.stat_date_to,
        source_type=query.source_type,
        source_channel=query.source_channel,
        page=query.page,
        page_size=query.page_size,
    )


@router.get("/ships/cities", response_model=PageResponse[ShipCityDailyResponse])
async def list_ship_city_daily(
    query: ShipCityDailyQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipAnalysisService(db)
    return await service.list_ship_city_daily(
        stat_date_from=query.stat_date_from,
        stat_date_to=query.stat_date_to,
        city_code=query.city_code,
        page=query.page,
        page_size=query.page_size,
    )


@router.get("/ships/flows", response_model=PageResponse[ShipFlowDailyResponse])
async def list_ship_flow_daily(
    query: ShipFlowDailyQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipAnalysisService(db)
    return await service.list_ship_flow_daily(
        stat_date_from=query.stat_date_from,
        stat_date_to=query.stat_date_to,
        origin_city_code=query.origin_city_code,
        destination_city_code=query.destination_city_code,
        page=query.page,
        page_size=query.page_size,
    )


@router.get("/jobs", response_model=PageResponse[StatJobRunResponse])
async def list_job_runs(
    query: StatJobRunListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = StatJobRunService(db)
    return await service.list_job_runs(
        job_type=query.job_type,
        status_code=query.status_code,
        stat_date_from=query.stat_date_from,
        stat_date_to=query.stat_date_to,
        page=query.page,
        page_size=query.page_size,
    )


@router.get("/jobs/{job_run_id}", response_model=StatJobRunDetailResponse)
async def get_job_run_detail(
    job_run_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = StatJobRunService(db)
    return await service.get_job_run_detail(job_run_id)
