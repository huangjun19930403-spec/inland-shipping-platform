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


class AnalysisOverviewResponse(BaseModel):
    date_from: date
    date_to: date
    metrics: list[MetricCard]
    recent_jobs: list["AnalysisJobRunResponse"]


class FreightAnalysisOverviewResponse(BaseModel):
    date_from: date
    date_to: date
    metrics: list[MetricCard]
    trend: list[ChartPoint]
    node_ranking: list[HeatMapItem] = Field(default_factory=list)
    commodity_structure: list[ChartPoint]
    price_distribution: list[ChartPoint]
    hot_routes: list[FlowMapItem]


class ShipAnalysisOverviewResponse(BaseModel):
    date_from: date
    date_to: date
    metrics: list[MetricCard]
    type_distribution: list[ChartPoint]
    age_distribution: list[ChartPoint]
    deadweight_distribution: list[ChartPoint]
    active_trend: list[ChartPoint]


class RegionAnalysisOverviewResponse(BaseModel):
    date_from: date
    date_to: date
    metrics: list[MetricCard]
    region_ranking: list[ChartPoint]
    heat_map: list[BoundaryHeatMapItem]


class FlowAnalysisOverviewResponse(BaseModel):
    date_from: date
    date_to: date
    metrics: list[MetricCard]
    freight_flows: list[FlowMapItem]
    ship_flows: list[FlowMapItem]


class PriceAnalysisOverviewResponse(BaseModel):
    date_from: date
    date_to: date
    metrics: list[MetricCard]
    price_trend: list[ChartPoint]
    price_distribution: list[ChartPoint]
    commodity_prices: list[ChartPoint]
    route_prices: list[FlowMapItem]


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
    force_rebuild: bool = True
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
