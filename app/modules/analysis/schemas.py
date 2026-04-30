"""analysis 模块 schema。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")
DateType = date


class PageResponse(BaseModel, Generic[T]):
    total: int
    page: int
    page_size: int
    items: list[T]


class CargoDailyQuery(BaseModel):
    stat_date_from: date | None = None
    stat_date_to: date | None = None
    source_type: str | None = None
    source_channel: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class CargoCityDailyQuery(BaseModel):
    stat_date_from: date | None = None
    stat_date_to: date | None = None
    city_code: str | None = None
    role_type: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class CargoFlowDailyQuery(BaseModel):
    stat_date_from: date | None = None
    stat_date_to: date | None = None
    origin_city_code: str | None = None
    destination_city_code: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class CargoCommodityDailyQuery(BaseModel):
    stat_date_from: date | None = None
    stat_date_to: date | None = None
    commodity_category_id: int | None = None
    commodity_type_id: int | None = None
    commodity_standard_id: int | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class CargoChannelDailyQuery(BaseModel):
    stat_date_from: date | None = None
    stat_date_to: date | None = None
    source_type: str | None = None
    source_channel: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class CargoDailyResponse(BaseModel):
    id: int
    stat_date: date
    total_freight_count: int
    total_tonnage: Decimal
    total_estimated_amount: Decimal | None
    data_version: str
    generated_at: datetime


class CargoCityDailyResponse(BaseModel):
    id: int
    stat_date: date
    city_code: str
    freight_count: int
    tonnage: Decimal
    loading_count: int
    unloading_count: int
    data_version: str
    generated_at: datetime


class CargoFlowDailyResponse(BaseModel):
    id: int
    stat_date: date
    origin_city_code: str
    destination_city_code: str
    freight_count: int
    tonnage: Decimal
    data_version: str
    generated_at: datetime


class CargoCommodityDailyResponse(BaseModel):
    id: int
    stat_date: date
    commodity_standard_id: int
    freight_count: int
    tonnage: Decimal
    avg_unit_price: Decimal | None
    data_version: str
    generated_at: datetime


class CargoChannelDailyResponse(BaseModel):
    id: int
    stat_date: date
    source_type_code: str
    incoming_count: int
    valid_count: int
    invalid_count: int
    confirmed_count: int
    formalized_count: int
    data_version: str
    generated_at: datetime


class ShipCityDailyQuery(BaseModel):
    stat_date_from: date | None = None
    stat_date_to: date | None = None
    city_code: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class ShipFlowDailyQuery(BaseModel):
    stat_date_from: date | None = None
    stat_date_to: date | None = None
    origin_city_code: str | None = None
    destination_city_code: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class ShipCityDailyResponse(BaseModel):
    id: int
    stat_date: date
    city_code: str
    active_ship_count: int
    total_deadweight_ton: Decimal | None
    data_version: str
    generated_at: datetime


class ShipFlowDailyResponse(BaseModel):
    id: int
    stat_date: date
    origin_city_code: str
    destination_city_code: str
    ship_count: int
    voyage_count: int
    total_deadweight_ton: Decimal | None
    data_version: str
    generated_at: datetime


class StatJobRunListQuery(BaseModel):
    job_type: str | None = None
    status_code: str | None = None
    stat_date_from: date | None = None
    stat_date_to: date | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class StatJobRunResponse(BaseModel):
    id: int
    job_code: str
    stat_date: date
    scope_desc: str | None
    started_at: datetime | None
    finished_at: datetime | None
    status_code: str
    affected_rows: int | None
    error_message: str | None
    triggered_by: str | None
    created_at: datetime


class StatJobRunDetailResponse(BaseModel):
    id: int
    job_code: str
    stat_date: date
    scope_desc: str | None
    started_at: datetime | None
    finished_at: datetime | None
    status_code: str
    affected_rows: int | None
    error_message: str | None
    triggered_by: str | None
    created_at: datetime


class AnalysisDateRangeQuery(BaseModel):
    date_from: date | None = None
    date_to: date | None = None


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
    heat_map: list[HeatMapItem]


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
    started_at: datetime | None
    finished_at: datetime | None
    affected_rows: int | None
    error_message: str | None
    triggered_by: str | None
    created_at: datetime


class AnalysisJobRunDetailResponse(AnalysisJobRunResponse):
    parameters_json: dict | None = None
    result_summary_json: dict | None = None
