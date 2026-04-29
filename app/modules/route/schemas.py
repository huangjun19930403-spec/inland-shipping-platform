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
    status_code: int | None = None
    origin_region_id: int | None = None
    destination_region_id: int | None = None
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
    status: int = 1
    sort_order: int = 0


class RouteUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    transport_org_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    multimodal_combination_code: str | None = Field(default=None, max_length=64)
    origin_region_id: int | None = None
    destination_region_id: int | None = None
    description: str | None = Field(default=None, max_length=512)
    sort_order: int | None = None


class RouteStatusChangeRequest(BaseModel):
    status_code: int


class RouteResponse(BaseModel):
    id: int
    code: str
    name: str
    transport_org_type_code: str
    multimodal_combination_code: str | None
    origin_region_id: int
    destination_region_id: int
    description: str | None
    status: int
    sort_order: int
    audit_status: str
    submitter_id: int | None
    auditor_id: int | None
    audited_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RoutePlanSummaryResponse(BaseModel):
    id: int
    route_id: int
    plan_code: str
    plan_name: str
    version_no: int
    plan_type_code: str
    total_distance_km: Decimal | None
    estimated_duration_hour: Decimal | None
    effective_from: datetime | None
    effective_to: datetime | None
    status: int
    is_default: bool
    remark: str | None
    created_at: datetime
    updated_at: datetime


class RouteDetailResponse(BaseModel):
    route: RouteResponse
    current_plan: RoutePlanSummaryResponse | None
    plans: list[RoutePlanSummaryResponse]


class RoutePlanListQuery(BaseModel):
    status_code: int | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class RoutePlanCreateRequest(BaseModel):
    plan_code: str | None = Field(default=None, max_length=32)
    plan_name: str = Field(min_length=1, max_length=128)
    version_no: int = 1
    plan_type_code: str = Field(min_length=1, max_length=64)
    total_distance_km: Decimal | None = None
    estimated_duration_hour: Decimal | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    status: int = 1
    is_default: bool = False
    remark: str | None = Field(default=None, max_length=512)


class RoutePlanUpdateRequest(BaseModel):
    plan_name: str | None = Field(default=None, min_length=1, max_length=128)
    version_no: int | None = None
    plan_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    total_distance_km: Decimal | None = None
    estimated_duration_hour: Decimal | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    is_default: bool | None = None
    remark: str | None = Field(default=None, max_length=512)


class RoutePlanStatusChangeRequest(BaseModel):
    status_code: int


class RoutePlanActivateRequest(BaseModel):
    is_default: bool = True


class RoutePlanResponse(BaseModel):
    id: int
    route_id: int
    plan_code: str
    plan_name: str
    version_no: int
    plan_type_code: str
    total_distance_km: Decimal | None
    estimated_duration_hour: Decimal | None
    effective_from: datetime | None
    effective_to: datetime | None
    status: int
    is_default: bool
    remark: str | None
    created_at: datetime
    updated_at: datetime


class RoutePlanNodeResponse(BaseModel):
    id: int
    plan_id: int
    node_order: int
    node_kind_code: str
    transport_node_id: int | None
    constraint_point_id: int | None
    region_id: int | None
    longitude: Decimal | None
    latitude: Decimal | None
    display_name: str
    role_code: str | None
    next_transport_mode_code: str | None
    remark: str | None
    created_at: datetime
    updated_at: datetime


class RoutePlanNodeUpsertItem(BaseModel):
    node_order: int = Field(ge=1)
    node_kind_code: str = Field(min_length=1, max_length=64)
    transport_node_id: int | None = None
    constraint_point_id: int | None = None
    region_id: int | None = None
    longitude: Decimal | None = None
    latitude: Decimal | None = None
    display_name: str = Field(min_length=1, max_length=128)
    role_code: str | None = Field(default=None, max_length=64)
    next_transport_mode_code: str | None = Field(default=None, max_length=64)
    remark: str | None = Field(default=None, max_length=512)


class RoutePlanNodeReplaceRequest(BaseModel):
    nodes: list[RoutePlanNodeUpsertItem] = Field(min_length=2)


class RoutePlanPreviewSegmentResponse(BaseModel):
    segment_no: int
    start_node_order: int
    end_node_order: int
    start_display_name: str
    end_display_name: str
    transport_mode_code: str | None
    can_generate: bool
    message: str | None = None


class RouteSegmentCreateRequest(BaseModel):
    segment_no: int = Field(ge=1)
    segment_type_code: str = Field(min_length=1, max_length=64)
    start_node_id: int | None = None
    end_node_id: int | None = None
    start_constraint_point_id: int | None = None
    end_constraint_point_id: int | None = None
    distance_km: Decimal | None = None
    estimated_duration_hour: Decimal | None = None
    geometry_json: dict | None = None
    sort_order: int = 0
    remark: str | None = Field(default=None, max_length=512)


class RouteSegmentUpdateRequest(BaseModel):
    segment_no: int | None = Field(default=None, ge=1)
    segment_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    start_node_id: int | None = None
    end_node_id: int | None = None
    start_constraint_point_id: int | None = None
    end_constraint_point_id: int | None = None
    distance_km: Decimal | None = None
    estimated_duration_hour: Decimal | None = None
    geometry_json: dict | None = None
    sort_order: int | None = None
    remark: str | None = Field(default=None, max_length=512)


class RouteSegmentResponse(BaseModel):
    id: int
    plan_id: int
    segment_no: int
    segment_type_code: str
    start_node_id: int | None
    end_node_id: int | None
    start_constraint_point_id: int | None
    end_constraint_point_id: int | None
    distance_km: Decimal | None
    estimated_duration_hour: Decimal | None
    geometry_json: dict | None
    sort_order: int
    remark: str | None
    created_at: datetime
    updated_at: datetime


class RouteSegmentOrderRequest(BaseModel):
    ordered_ids: list[int] = Field(default_factory=list)


class RouteSegmentPointCreateRequest(BaseModel):
    point_no: int = Field(ge=1)
    point_type_code: str = Field(min_length=1, max_length=64)
    related_node_id: int | None = None
    related_constraint_point_id: int | None = None
    longitude: Decimal | None = None
    latitude: Decimal | None = None
    stay_minutes: int | None = None
    remark: str | None = Field(default=None, max_length=512)


class RouteSegmentPointUpdateRequest(BaseModel):
    point_no: int | None = Field(default=None, ge=1)
    point_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    related_node_id: int | None = None
    related_constraint_point_id: int | None = None
    longitude: Decimal | None = None
    latitude: Decimal | None = None
    stay_minutes: int | None = None
    remark: str | None = Field(default=None, max_length=512)


class RouteSegmentPointResponse(BaseModel):
    id: int
    segment_id: int
    point_no: int
    point_type_code: str
    related_node_id: int | None
    related_constraint_point_id: int | None
    longitude: Decimal | None
    latitude: Decimal | None
    stay_minutes: int | None
    remark: str | None
    created_at: datetime
    updated_at: datetime


class RouteSegmentPointOrderRequest(BaseModel):
    ordered_ids: list[int] = Field(default_factory=list)


class RoutePlanDetailResponse(BaseModel):
    plan: RoutePlanResponse
    segments: list[RouteSegmentResponse]
    points_by_segment: dict[int, list[RouteSegmentPointResponse]]


class RouteGeometryRefreshRequest(BaseModel):
    provider_code: str = Field(min_length=1, max_length=32)
    force_refresh: bool = False


class RouteGeometryRefreshResponse(BaseModel):
    target_type: str
    target_id: int
    provider_code: str
    status: str
    message: str
    updated_plan_id: int | None = None
    updated_segment_id: int | None = None
