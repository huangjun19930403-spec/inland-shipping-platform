"""analysis 模块 router。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.modules.analysis.schemas import (
    AnalysisDateRangeQuery,
    AnalysisJobRunDetailResponse,
    AnalysisJobRunQuery,
    AnalysisJobRunResponse,
    AnalysisOverviewResponse,
    ChartPoint,
    FlowAnalysisOverviewResponse,
    FlowMapItem,
    FreightAnalysisOverviewResponse,
    HeatMapItem,
    PageResponse,
    PriceAnalysisOverviewResponse,
    RegionAnalysisOverviewResponse,
    ShipAnalysisOverviewResponse,
)
from app.modules.analysis.service import AnalysisDashboardService

router = APIRouter()


@router.get("/overview", response_model=AnalysisOverviewResponse)
async def get_analysis_overview(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    return await service.get_overview(query.date_from, query.date_to)


@router.get("/freight/overview", response_model=FreightAnalysisOverviewResponse)
async def get_freight_analysis_overview(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    return await service.freight_overview(query.date_from, query.date_to)


@router.get("/freight/trend", response_model=list[ChartPoint])
async def get_freight_trend(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    start, end = await service._date_range(query.date_from, query.date_to)
    return await service.freight_trend(start, end)


@router.get("/freight/commodity-structure", response_model=list[ChartPoint])
async def get_freight_commodity_structure(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    start, end = await service._date_range(query.date_from, query.date_to)
    return await service.freight_commodity_structure(start, end)


@router.get("/freight/tonnage-distribution", response_model=list[ChartPoint])
async def get_freight_tonnage_distribution(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    start, end = await service._date_range(query.date_from, query.date_to)
    return await service.freight_tonnage_distribution(start, end)


@router.get("/freight/price-distribution", response_model=list[ChartPoint])
async def get_freight_price_distribution(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    start, end = await service._date_range(query.date_from, query.date_to)
    return await service.freight_price_distribution(start, end)


@router.get("/freight/hot-routes", response_model=list[FlowMapItem])
async def get_freight_hot_routes(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    start, end = await service._date_range(query.date_from, query.date_to)
    return await service.freight_hot_routes(start, end, 20)


@router.get("/freight/flow-map", response_model=list[FlowMapItem])
async def get_freight_flow_map(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    start, end = await service._date_range(query.date_from, query.date_to)
    return await service.freight_hot_routes(start, end, 40)


@router.get("/ships/overview", response_model=ShipAnalysisOverviewResponse)
async def get_ship_analysis_overview(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    return await service.ship_overview(query.date_from, query.date_to)


@router.get("/ships/type-distribution", response_model=list[ChartPoint])
async def get_ship_type_distribution(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    start, end = await service._date_range(query.date_from, query.date_to)
    return await service.ship_type_distribution(start, end)


@router.get("/ships/age-distribution", response_model=list[ChartPoint])
async def get_ship_age_distribution(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    start, end = await service._date_range(query.date_from, query.date_to)
    return await service.ship_age_distribution(start, end)


@router.get("/ships/deadweight-distribution", response_model=list[ChartPoint])
async def get_ship_deadweight_distribution(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    start, end = await service._date_range(query.date_from, query.date_to)
    return await service.ship_deadweight_distribution(start, end)


@router.get("/ships/active-trend", response_model=list[ChartPoint])
async def get_ship_active_trend(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    start, end = await service._date_range(query.date_from, query.date_to)
    return await service.ship_active_trend(start, end)


@router.get("/ships/flow-map", response_model=list[FlowMapItem])
async def get_ship_flow_map(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    start, end = await service._date_range(query.date_from, query.date_to)
    return await service.ship_flow_map(start, end, 40)


@router.get("/regions/overview", response_model=RegionAnalysisOverviewResponse)
async def get_region_analysis_overview(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    return await service.region_overview(query.date_from, query.date_to)


@router.get("/regions/heat-map", response_model=list[HeatMapItem])
async def get_region_heat_map(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    start, end = await service._date_range(query.date_from, query.date_to)
    return await service.region_heat_map(start, end)


@router.get("/flows/overview", response_model=FlowAnalysisOverviewResponse)
async def get_flow_analysis_overview(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    return await service.flow_overview(query.date_from, query.date_to)


@router.get("/flows/map", response_model=FlowAnalysisOverviewResponse)
async def get_flow_map(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    return await service.flow_overview(query.date_from, query.date_to)


@router.get("/prices/overview", response_model=PriceAnalysisOverviewResponse)
async def get_price_analysis_overview(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    return await service.price_overview(query.date_from, query.date_to)


@router.get("/jobs", response_model=PageResponse[AnalysisJobRunResponse])
async def list_job_runs(
    query: AnalysisJobRunQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    return await service.list_jobs(
        module_code=query.module_code,
        status_code=query.status_code,
        date_from=query.date_from,
        date_to=query.date_to,
        page=query.page,
        page_size=query.page_size,
    )


@router.get("/jobs/{job_run_id}", response_model=AnalysisJobRunDetailResponse)
async def get_job_run_detail(
    job_run_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    return await service.get_job_detail(job_run_id)
