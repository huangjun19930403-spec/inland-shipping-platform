"""analysis 模块 schema。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


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
