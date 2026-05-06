"""route 模块 schema。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResponse(BaseModel, Generic[T]):
    total: int
    page: int
    page_size: int
    items: list[T]


class RouteListQuery(BaseModel):
    keyword: str | None = None
    origin_region_id: int | None = None
    destination_region_id: int | None = None
    transport_org_type_code: str | None = None
    plan_type_code: str | None = None
    has_plan: bool | None = None
    has_main_line: bool | None = None
    track_status: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class RouteCreateRequest(BaseModel):
    code: str | None = Field(default=None, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    transport_org_type_code: str = Field(min_length=1, max_length=64)
    multimodal_combination_code: str | None = Field(default=None, max_length=64)
    origin_region_id: int
    destination_region_id: int
    description: str | None = Field(default=None, max_length=512)


class RouteUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    transport_org_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    multimodal_combination_code: str | None = Field(default=None, max_length=64)
    origin_region_id: int | None = None
    destination_region_id: int | None = None
    description: str | None = Field(default=None, max_length=512)


class RouteResponse(BaseModel):
    id: int
    code: str
    name: str
    transport_org_type_code: str
    multimodal_combination_code: str | None
    origin_region_id: int
    destination_region_id: int
    description: str | None
    audit_status: str
    submitter_id: int | None
    auditor_id: int | None
    audited_at: datetime | None
    created_at: datetime
    updated_at: datetime
    plan_count: int = 0
    line_count: int = 0
    main_line_name: str | None = None
    track_status: str = "NOT_GENERATED"


class RoutePlanResponse(BaseModel):
    id: int
    route_id: int
    plan_code: str
    plan_name: str
    plan_type_code: str
    description: str | None
    remark: str | None
    created_at: datetime
    updated_at: datetime
    line_count: int = 0
    main_line_name: str | None = None


class RouteDetailResponse(BaseModel):
    route: RouteResponse
    plans: list[RoutePlanResponse]


class RoutePlanListQuery(BaseModel):
    plan_type_code: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class RoutePlanCreateRequest(BaseModel):
    plan_code: str | None = Field(default=None, max_length=32)
    plan_name: str = Field(min_length=1, max_length=128)
    plan_type_code: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=512)
    remark: str | None = Field(default=None, max_length=512)


class RoutePlanUpdateRequest(BaseModel):
    plan_name: str | None = Field(default=None, min_length=1, max_length=128)
    plan_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=512)
    remark: str | None = Field(default=None, max_length=512)


class RouteLineResponse(BaseModel):
    id: int
    plan_id: int
    line_code: str
    line_name: str
    line_role_code: str
    priority: int
    trigger_condition: str | None
    description: str | None
    track_status: str
    track_generated_at: datetime | None
    created_at: datetime
    updated_at: datetime
    segment_count: int = 0


class RouteLineCreateRequest(BaseModel):
    line_code: str | None = Field(default=None, max_length=32)
    line_name: str = Field(min_length=1, max_length=128)
    line_role_code: str = Field(min_length=1, max_length=64)
    priority: int = 0
    trigger_condition: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=512)


class RouteLineUpdateRequest(BaseModel):
    line_name: str | None = Field(default=None, min_length=1, max_length=128)
    line_role_code: str | None = Field(default=None, min_length=1, max_length=64)
    priority: int | None = None
    trigger_condition: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=512)


class RouteLineNodeResponse(BaseModel):
    id: int
    line_id: int
    node_order: int
    node_type_code: str
    transport_node_id: int | None
    constraint_point_id: int | None
    manual_name: str | None
    longitude: Decimal | None
    latitude: Decimal | None
    display_name: str
    resolved_name: str | None = None
    resolved_code: str | None = None
    resolved_node_type_code: str | None = None
    resolved_address: str | None = None
    remark: str | None
    created_at: datetime
    updated_at: datetime


class RouteLineNodeUpsertItem(BaseModel):
    node_order: int = Field(ge=1)
    node_type_code: str = Field(min_length=1, max_length=64)
    transport_node_id: int | None = None
    constraint_point_id: int | None = None
    manual_name: str | None = Field(default=None, max_length=128)
    longitude: Decimal | None = None
    latitude: Decimal | None = None
    display_name: str = Field(min_length=1, max_length=128)
    remark: str | None = Field(default=None, max_length=512)


class RouteLineSegmentResponse(BaseModel):
    id: int
    line_id: int
    segment_no: int
    start_line_node_id: int
    end_line_node_id: int
    transport_mode_code: str
    distance_km: Decimal | None
    estimated_duration_hour: Decimal | None
    segment_track_status: str
    geometry_source: str | None
    geometry_json: dict | None
    remark: str | None
    created_at: datetime
    updated_at: datetime


class RouteLineSegmentUpsertItem(BaseModel):
    segment_no: int = Field(ge=1)
    start_node_order: int = Field(ge=1)
    end_node_order: int = Field(ge=1)
    transport_mode_code: str = Field(min_length=1, max_length=64)
    distance_km: Decimal | None = None
    estimated_duration_hour: Decimal | None = None
    segment_track_status: str | None = Field(default=None, max_length=64)
    geometry_source: str | None = Field(default=None, max_length=64)
    geometry_json: dict | None = None
    remark: str | None = Field(default=None, max_length=512)


class RouteLineTrackResponse(BaseModel):
    id: int
    line_id: int
    track_status: str
    geometry_json: dict | None
    distance_km: Decimal | None
    estimated_duration_hour: Decimal | None
    provider_summary_json: dict | None
    error_message: str | None
    generated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RouteLineStructureResponse(BaseModel):
    line: RouteLineResponse
    nodes: list[RouteLineNodeResponse]
    segments: list[RouteLineSegmentResponse]
    track: RouteLineTrackResponse | None


class RouteLineStructureReplaceRequest(BaseModel):
    nodes: list[RouteLineNodeUpsertItem] = Field(min_length=2)
    segments: list[RouteLineSegmentUpsertItem] = Field(min_length=1)


class RouteLineTrackGenerateRequest(BaseModel):
    provider_code: str | None = Field(default=None, max_length=64)


class RouteLineTrackGenerateResponse(BaseModel):
    line_id: int
    status: str
    message: str
    track: RouteLineTrackResponse | None = None
