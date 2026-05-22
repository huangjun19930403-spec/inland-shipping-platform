"""analysis 模块 router。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.modules.analysis.schemas import (
    AnalysisDateRangeQuery,
    AnalysisJobRunDetailResponse,
    AnalysisJobRunQuery,
    AnalysisJobRunResponse,
    AnalysisOverviewResponse,
    AnalysisTaskDetailResponse,
    AnalysisTaskQuery,
    AnalysisTaskResponse,
    AnalysisTaskTriggerRequest,
    BoundaryHeatMapItem,
    ChartPoint,
    FlowAnalysisOverviewResponse,
    FlowAnalysisQuery,
    FlowMapItem,
    FlowRouteCachePrecomputeRequest,
    FlowRouteCachePrecomputeResponse,
    FreightAnalysisOverviewResponse,
    HeatMapItem,
    PageResponse,
    PriceAnalysisOverviewResponse,
    PricingDecisionResponse,
    QuoteDecisionRequest,
    QuoteRouteEstimateRequest,
    QuoteRouteEstimateResponse,
    QuoteSimulatorContextResponse,
    RateEstimateRequest,
    RegionAnalysisQuery,
    RegionAnalysisOverviewResponse,
    RegionSupplyDemandAnalysisResponse,
    ShipAnalysisOverviewResponse,
    VesselAssetAnalysisResponse,
    VesselCandidateFitAnalysisResponse,
    VesselQualityAnalysisResponse,
    VesselRiskAnalysisResponse,
    VesselTrajectoryAnalysisResponse,
)
from app.modules.analysis.service import AnalysisDashboardService, QuoteRouteEstimateService
from app.modules.analysis.pricing_decision_service import PricingDecisionService

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


@router.get("/freight/node-ranking", response_model=list[HeatMapItem])
async def get_freight_node_ranking(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    start, end = await service._date_range(query.date_from, query.date_to)
    return await service.freight_node_ranking(start, end, 20)


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


@router.get("/vessels/assets", response_model=VesselAssetAnalysisResponse)
async def get_vessel_asset_analysis(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    return await service.vessel_asset_analysis(query.date_from, query.date_to)


@router.get("/vessels/trajectory", response_model=VesselTrajectoryAnalysisResponse)
async def get_vessel_trajectory_analysis(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    return await service.vessel_trajectory_analysis(query.date_from, query.date_to)


@router.get("/vessels/quality", response_model=VesselQualityAnalysisResponse)
async def get_vessel_quality_analysis(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    return await service.vessel_quality_analysis(query.date_from, query.date_to)


@router.get("/vessels/risks", response_model=VesselRiskAnalysisResponse)
async def get_vessel_risk_analysis(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    return await service.vessel_risk_analysis(query.date_from, query.date_to)


@router.get("/vessels/candidate-fit", response_model=VesselCandidateFitAnalysisResponse)
async def get_vessel_candidate_fit_analysis(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    return await service.vessel_candidate_fit_analysis(query.date_from, query.date_to)


@router.get("/regions/overview", response_model=RegionAnalysisOverviewResponse)
async def get_region_analysis_overview(
    query: RegionAnalysisQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    return await service.region_overview(
        query.date_from,
        query.date_to,
        include_boundary=query.include_boundary,
        boundary_precision=query.boundary_precision,
    )


@router.get("/regions/heat-map", response_model=list[BoundaryHeatMapItem])
async def get_region_heat_map(
    query: RegionAnalysisQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    start, end = await service._date_range(query.date_from, query.date_to)
    return await service.region_heat_map(
        start,
        end,
        include_boundary=query.include_boundary,
        boundary_precision=query.boundary_precision,
    )


@router.get("/regions/supply-demand", response_model=RegionSupplyDemandAnalysisResponse)
async def get_region_supply_demand_analysis(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    return await service.region_supply_demand_analysis(query.date_from, query.date_to)


@router.get("/flows/overview", response_model=FlowAnalysisOverviewResponse)
async def get_flow_analysis_overview(
    query: FlowAnalysisQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    return await service.flow_overview(query)


@router.get("/flows/map", response_model=FlowAnalysisOverviewResponse)
async def get_flow_map(
    query: FlowAnalysisQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    return await service.flow_overview(query)


@router.post("/flows/route-cache/precompute", response_model=FlowRouteCachePrecomputeResponse)
async def precompute_flow_route_cache(
    payload: FlowRouteCachePrecomputeRequest,
    current_user=Depends(get_current_user),
):
    _ = current_user
    from app.tasks.analysis_tasks import precompute_flow_route_cache_task

    async_result = precompute_flow_route_cache_task.apply_async(
        args=(
            payload.date_from.isoformat() if payload.date_from else None,
            payload.date_to.isoformat() if payload.date_to else None,
            payload.flow_types,
            payload.limit,
            payload.force_refresh,
        ),
        queue="analysis",
    )
    return FlowRouteCachePrecomputeResponse(
        status_code="QUEUED",
        message="已提交 AMMS 流向轨迹缓存生成任务",
        celery_task_id=async_result.id,
        date_from=payload.date_from,
        date_to=payload.date_to,
    )


@router.get("/prices/overview", response_model=PriceAnalysisOverviewResponse)
async def get_price_analysis_overview(
    query: AnalysisDateRangeQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    return await service.price_overview(query.date_from, query.date_to)


@router.post("/quote-simulator/route-estimate", response_model=QuoteRouteEstimateResponse)
async def estimate_quote_route(
    body: QuoteRouteEstimateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = QuoteRouteEstimateService(db)
    return await service.estimate_route(body)


@router.get("/quote-simulator/context", response_model=QuoteSimulatorContextResponse)
async def get_quote_simulator_context(
    freight_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    try:
        return await PricingDecisionService(db).quote_context(freight_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/quote-simulator/decision", response_model=PricingDecisionResponse)
async def create_quote_decision(
    body: QuoteDecisionRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await PricingDecisionService(db).decide_quote(body, created_by=getattr(current_user, "id", None))


@router.post("/rate-estimator/estimate", response_model=PricingDecisionResponse)
async def estimate_freight_rate(
    body: RateEstimateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await PricingDecisionService(db).estimate_rate(body, created_by=getattr(current_user, "id", None))


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


@router.get("/tasks", response_model=PageResponse[AnalysisTaskResponse])
async def list_analysis_tasks(
    query: AnalysisTaskQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    return await service.list_tasks(
        module_code=query.module_code,
        enabled=query.enabled,
        page=query.page,
        page_size=query.page_size,
    )


@router.get("/tasks/{job_code}", response_model=AnalysisTaskDetailResponse)
async def get_analysis_task_detail(
    job_code: str,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    return await service.get_task_detail(job_code)


@router.post("/tasks/{job_code}/trigger", response_model=AnalysisJobRunResponse)
async def trigger_analysis_task(
    job_code: str,
    body: AnalysisTaskTriggerRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AnalysisDashboardService(db)
    return await service.trigger_task(job_code, body, triggered_by=str(getattr(current_user, "id", "manual")))


@router.get("/tasks/{job_code}/runs", response_model=PageResponse[AnalysisJobRunResponse])
async def list_analysis_task_runs(
    job_code: str,
    query: AnalysisJobRunQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AnalysisDashboardService(db)
    return await service.list_task_runs(
        job_code=job_code,
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
