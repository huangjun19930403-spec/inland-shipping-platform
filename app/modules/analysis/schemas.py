"""analysis 模块 schema。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")
DateType = date


class PageResponse(BaseModel, Generic[T]):
    total: int
    page: int
    page_size: int
    items: list[T]


class AnalysisDateRangeQuery(BaseModel):
    date_from: date | None = None
    date_to: date | None = None


class FlowRouteCachePrecomputeRequest(AnalysisDateRangeQuery):
    flow_types: list[str] = Field(default_factory=lambda: ["freight", "ship"])
    limit: int = Field(default=20, ge=1, le=80)
    force_refresh: bool = False


class FlowRouteCachePrecomputeResponse(BaseModel):
    status_code: str
    message: str
    celery_task_id: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    total_count: int = 0
    cached_count: int = 0
    generated_count: int = 0
    pending_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0


class RegionAnalysisQuery(AnalysisDateRangeQuery):
    include_boundary: bool = False
    boundary_precision: str = Field(default="low", pattern="^(low|medium)$")


class MetricCard(BaseModel):
    code: str
    title: str
    value: float | int
    unit: str | None = None
    delta: float | None = None
    description: str | None = None


class MetricEvidence(BaseModel):
    metric_code: str
    value: float | int | None
    unit: str | None = None
    stat_date: date | None = None
    date_from: date | None = None
    date_to: date | None = None
    source_layer_code: str | None = None
    sample_count: int | None = None
    coverage_rate: float | None = None
    confidence_level: str | None = None
    not_computable_reasons: list[str] = Field(default_factory=list)
    uncertainty_reasons: list[str] = Field(default_factory=list)
    generated_at: datetime | None = None
    source_updated_at: datetime | None = None
    last_successful_run_at: datetime | None = None
    extra: dict | None = None


class AnalysisContextBlock(BaseModel):
    date_from: date
    date_to: date
    filters: dict = Field(default_factory=dict)


class AnalysisLineageBlock(BaseModel):
    source_tables: list[str] = Field(default_factory=list)
    data_versions: list[str] = Field(default_factory=list)
    sample_count: int = 0
    generated_at: datetime | None = None


class AnalysisQualityBlock(BaseModel):
    coverage_rate: float | None = None
    confidence_level: str = "UNKNOWN"
    not_computable_reasons: list[str] = Field(default_factory=list)
    uncertainty_reasons: list[str] = Field(default_factory=list)


class AnalysisActionBlock(BaseModel):
    action_code: str
    title: str
    target_route: str | None = None
    query: dict = Field(default_factory=dict)
    disabled_reason: str | None = None


class AnalysisWorkbenchMeta(BaseModel):
    context: AnalysisContextBlock
    lineage: AnalysisLineageBlock
    quality: AnalysisQualityBlock
    actions: list[AnalysisActionBlock] = Field(default_factory=list)


class ChartPoint(BaseModel):
    name: str
    value: float | int
    date: DateType | None = None
    ratio: float | None = None
    extra: dict | None = None


class FlowMapItem(BaseModel):
    origin_id: int | None = None
    origin_name: str
    origin_longitude: float | None = None
    origin_latitude: float | None = None
    destination_id: int | None = None
    destination_name: str
    destination_longitude: float | None = None
    destination_latitude: float | None = None
    value: float | int
    freight_count: int | None = None
    ship_count: int | None = None
    voyage_count: int | None = None
    tonnage: float | None = None
    avg_unit_price: float | None = None
    commodity_name: str | None = None
    geometry_json: dict | None = None
    geometry_source: str | None = None
    route_status_code: str | None = None
    route_cache_status: str | None = None
    route_generated_at: datetime | None = None
    route_distance_km: float | None = None
    route_point_count: int | None = None
    route_not_computable_reasons: list[str] = Field(default_factory=list)


class HeatMapItem(BaseModel):
    id: int | None = None
    name: str
    longitude: float | None = None
    latitude: float | None = None
    value: float
    level: str | None = None
    region_id: int | None = None
    node_id: int | None = None
    freight_count: int | None = None
    tonnage: float | None = None
    ship_count: int | None = None
    active_ship_count: int | None = None
    inbound_count: int | None = None
    outbound_count: int | None = None


class BoundaryHeatMapItem(BaseModel):
    id: int | None = None
    city_code: str | None = None
    name: str
    region_id: int | None = None
    value: float
    level: str | None = None
    boundary_paths: list[list[list[float]]] | None = None
    has_boundary: bool = False
    boundary_precision: str | None = None
    center_longitude: float | None = None
    center_latitude: float | None = None
    freight_count: int | None = None
    tonnage: float | None = None
    inbound_count: int | None = None
    outbound_count: int | None = None
    avg_unit_price: float | None = None


class AnalysisOverviewResponse(AnalysisWorkbenchMeta):
    date_from: date
    date_to: date
    metrics: list[MetricCard]
    recent_jobs: list["AnalysisJobRunResponse"]


class FreightAnalysisOverviewResponse(AnalysisWorkbenchMeta):
    date_from: date
    date_to: date
    metrics: list[MetricCard]
    trend: list[ChartPoint]
    node_ranking: list[HeatMapItem] = Field(default_factory=list)
    commodity_structure: list[ChartPoint]
    price_distribution: list[ChartPoint]
    hot_routes: list[FlowMapItem]


class ShipAnalysisOverviewResponse(AnalysisWorkbenchMeta):
    date_from: date
    date_to: date
    metrics: list[MetricCard]
    type_distribution: list[ChartPoint]
    age_distribution: list[ChartPoint]
    deadweight_distribution: list[ChartPoint]
    active_trend: list[ChartPoint]


class RegionAnalysisOverviewResponse(AnalysisWorkbenchMeta):
    date_from: date
    date_to: date
    metrics: list[MetricCard]
    region_ranking: list[ChartPoint]
    heat_map: list[BoundaryHeatMapItem]


class FlowAnalysisOverviewResponse(AnalysisWorkbenchMeta):
    date_from: date
    date_to: date
    metrics: list[MetricCard]
    freight_flows: list[FlowMapItem]
    ship_flows: list[FlowMapItem]


class PriceAnalysisOverviewResponse(AnalysisWorkbenchMeta):
    date_from: date
    date_to: date
    metrics: list[MetricCard]
    price_trend: list[ChartPoint]
    price_distribution: list[ChartPoint]
    commodity_prices: list[ChartPoint]
    route_prices: list[FlowMapItem]


class VesselAssetAnalysisResponse(BaseModel):
    date_from: date
    date_to: date
    metrics: list[MetricEvidence]
    quality_distribution: list[ChartPoint]
    risk_distribution: list[ChartPoint]
    source_status: list[MetricEvidence] = Field(default_factory=list)


class VesselTrajectoryAnalysisResponse(BaseModel):
    date_from: date
    date_to: date
    metrics: list[MetricEvidence]
    coverage_trend: list[ChartPoint]
    gap_distribution: list[ChartPoint]
    source_status: list[MetricEvidence] = Field(default_factory=list)


class VesselQualityAnalysisResponse(BaseModel):
    date_from: date
    date_to: date
    metrics: list[MetricEvidence]
    issue_distribution: list[ChartPoint]
    severity_distribution: list[ChartPoint]
    source_status: list[MetricEvidence] = Field(default_factory=list)


class VesselRiskAnalysisResponse(BaseModel):
    date_from: date
    date_to: date
    metrics: list[MetricEvidence]
    risk_level_distribution: list[ChartPoint]
    risk_type_distribution: list[ChartPoint]
    source_status: list[MetricEvidence] = Field(default_factory=list)


class VesselCandidateFitAnalysisResponse(BaseModel):
    date_from: date
    date_to: date
    metrics: list[MetricEvidence]
    value_distribution: list[ChartPoint]
    annotation_distribution: list[ChartPoint]
    source_status: list[MetricEvidence] = Field(default_factory=list)


class RegionSupplyDemandAnalysisResponse(BaseModel):
    date_from: date
    date_to: date
    metrics: list[MetricEvidence]
    tension_distribution: list[ChartPoint]
    not_computable_distribution: list[ChartPoint]
    source_status: list[MetricEvidence] = Field(default_factory=list)


class QuoteRouteEstimateRequest(BaseModel):
    origin_node_id: int
    destination_node_id: int
    provider_code: str | None = Field(default="auto", pattern="^(auto|hifleet|AUTO|HIFLEET)$")


class QuoteRouteEstimateNode(BaseModel):
    id: int
    code: str
    name: str
    node_type_code: str
    city_code: str
    city_name: str | None = None
    longitude: float | None = None
    latitude: float | None = None


class QuoteRouteEstimateResponse(BaseModel):
    status_code: str
    origin_node: QuoteRouteEstimateNode | None = None
    destination_node: QuoteRouteEstimateNode | None = None
    distance_km: float | None = None
    geometry_json: dict | None = None
    geometry_source: str | None = None
    provider_trace_id: str | None = None
    point_count: int | None = None
    not_computable_reasons: list[str] = Field(default_factory=list)
    generated_at: datetime


class AnalysisJobRunQuery(BaseModel):
    module_code: str | None = None
    status_code: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class AnalysisTaskQuery(BaseModel):
    module_code: str | None = None
    enabled: bool | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class AnalysisTaskTriggerRequest(BaseModel):
    date_from: date
    date_to: date
    force_rebuild: bool = False
    parameters_json: dict | None = None


class AnalysisTaskResponse(BaseModel):
    id: int
    job_code: str
    job_name: str
    module_code: str
    module_name: str
    description: str | None
    source_tables_json: list | None
    target_tables_json: list | None
    default_parameters_json: dict | None
    schedule_cron: str | None
    schedule_enabled: bool
    enabled: bool
    last_run_id: int | None
    last_status_code: str | None
    last_finished_at: datetime | None
    last_result_summary_json: dict | None
    sort_order: int
    created_at: datetime
    updated_at: datetime


class AnalysisTaskDetailResponse(AnalysisTaskResponse):
    recent_runs: list["AnalysisJobRunResponse"] = Field(default_factory=list)


class AnalysisJobRunResponse(BaseModel):
    id: int
    job_code: str
    job_name: str
    module_code: str
    module_name: str
    stat_date_from: date | None
    stat_date_to: date | None
    status_code: str
    status_name: str
    celery_task_id: str | None = None
    queued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None = None
    input_rows: int | None = None
    output_rows: int | None = None
    affected_rows: int | None
    error_message: str | None
    triggered_by: str | None
    created_at: datetime


class AnalysisJobRunDetailResponse(AnalysisJobRunResponse):
    parameters_json: dict | None = None
    result_summary_json: dict | None = None
