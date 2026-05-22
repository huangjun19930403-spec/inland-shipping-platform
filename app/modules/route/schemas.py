"""route 模块 schema。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from app.modules.tasks.schemas import AsyncTaskRunResponse

T = TypeVar("T")


class PageResponse(BaseModel, Generic[T]):
    total: int
    page: int
    page_size: int
    items: list[T]


class RouteListQuery(BaseModel):
    keyword: str | None = None
    origin_endpoint_type_code: str | None = None
    origin_region_id: int | None = None
    origin_city_code: str | None = None
    origin_node_id: int | None = None
    destination_endpoint_type_code: str | None = None
    destination_region_id: int | None = None
    destination_city_code: str | None = None
    destination_node_id: int | None = None
    transport_org_type_code: str | None = None
    plan_type_code: str | None = None
    has_plan: bool | None = None
    has_default_plan: bool | None = None
    track_status: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class RouteEndpointMixin(BaseModel):
    origin_endpoint_type_code: str = Field(default="REGION", max_length=32)
    origin_region_id: int | None = None
    origin_city_code: str | None = Field(default=None, max_length=12)
    origin_node_id: int | None = None
    destination_endpoint_type_code: str = Field(default="REGION", max_length=32)
    destination_region_id: int | None = None
    destination_city_code: str | None = Field(default=None, max_length=12)
    destination_node_id: int | None = None


class RouteCreateRequest(RouteEndpointMixin):
    code: str | None = Field(default=None, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    transport_org_type_code: str = Field(min_length=1, max_length=64)
    multimodal_combination_code: str | None = Field(default=None, max_length=64)
    status_code: str = Field(default="ACTIVE", max_length=32)
    description: str | None = Field(default=None, max_length=512)


class RouteUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    origin_endpoint_type_code: str | None = Field(default=None, max_length=32)
    origin_region_id: int | None = None
    origin_city_code: str | None = Field(default=None, max_length=12)
    origin_node_id: int | None = None
    destination_endpoint_type_code: str | None = Field(default=None, max_length=32)
    destination_region_id: int | None = None
    destination_city_code: str | None = Field(default=None, max_length=12)
    destination_node_id: int | None = None
    transport_org_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    multimodal_combination_code: str | None = Field(default=None, max_length=64)
    status_code: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=512)


class RouteResponse(BaseModel):
    id: int
    code: str
    name: str
    origin_endpoint_type_code: str
    origin_region_id: int | None
    origin_city_code: str | None
    origin_node_id: int | None
    destination_endpoint_type_code: str
    destination_region_id: int | None
    destination_city_code: str | None
    destination_node_id: int | None
    transport_org_type_code: str
    multimodal_combination_code: str | None
    status_code: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    plan_count: int = 0
    point_count: int = 0
    segment_count: int = 0
    selected_result_count: int = 0
    current_track_version_id: int | None = None
    current_track_version_no: int | None = None
    current_track_source_type_code: str | None = None
    track_version_count: int = 0
    default_plan_id: int | None = None
    default_plan_name: str | None = None
    track_status: str = "NOT_GENERATED"
    track_error_message: str | None = None
    track_generated_at: datetime | None = None
    active_track_generation_task: AsyncTaskRunResponse | None = None


class RoutePlanResponse(BaseModel):
    id: int
    route_id: int
    plan_code: str
    plan_name: str
    plan_type_code: str
    is_default: bool
    status_code: str
    display_order: int
    structure_revision: int = 1
    applicable_condition: str | None
    remark: str | None
    created_at: datetime
    updated_at: datetime
    point_count: int = 0
    segment_count: int = 0
    selected_result_count: int = 0
    current_track_version_id: int | None = None
    current_track_version_no: int | None = None
    current_track_source_type_code: str | None = None
    track_version_count: int = 0
    track_status: str = "NOT_GENERATED"
    active_track_generation_task: AsyncTaskRunResponse | None = None


class RouteDetailResponse(BaseModel):
    route: RouteResponse
    plans: list[RoutePlanResponse]


class RoutePlanListQuery(BaseModel):
    plan_type_code: str | None = None
    status_code: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class RoutePlanCreateRequest(BaseModel):
    plan_code: str | None = Field(default=None, max_length=32)
    plan_name: str = Field(min_length=1, max_length=128)
    plan_type_code: str = Field(min_length=1, max_length=64)
    is_default: bool = False
    status_code: str = Field(default="DRAFT", max_length=32)
    display_order: int = Field(default=1, ge=1)
    applicable_condition: str | None = Field(default=None, max_length=512)
    remark: str | None = Field(default=None, max_length=512)


class RoutePlanUpdateRequest(BaseModel):
    plan_name: str | None = Field(default=None, min_length=1, max_length=128)
    plan_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    is_default: bool | None = None
    status_code: str | None = Field(default=None, max_length=32)
    display_order: int | None = Field(default=None, ge=1)
    applicable_condition: str | None = Field(default=None, max_length=512)
    remark: str | None = Field(default=None, max_length=512)


class RoutePlanPointResponse(BaseModel):
    id: int
    plan_id: int
    point_order: int
    point_type_code: str
    transport_node_id: int | None
    constraint_point_id: int | None
    manual_name: str | None
    longitude: Decimal | None
    latitude: Decimal | None
    display_name: str
    transport_mode_after_code: str | None
    resolved_name: str | None = None
    resolved_code: str | None = None
    resolved_node_type_code: str | None = None
    resolved_address: str | None = None
    remark: str | None
    created_at: datetime
    updated_at: datetime


class RoutePlanPointUpsertItem(BaseModel):
    point_order: int | None = Field(default=None, ge=1)
    point_type_code: str = Field(min_length=1, max_length=64)
    transport_node_id: int | None = None
    constraint_point_id: int | None = None
    manual_name: str | None = Field(default=None, max_length=128)
    longitude: Decimal | None = None
    latitude: Decimal | None = None
    display_name: str = Field(min_length=1, max_length=128)
    transport_mode_after_code: str | None = Field(default=None, max_length=64)
    remark: str | None = Field(default=None, max_length=512)


class RoutePlanSegmentResponse(BaseModel):
    id: int
    plan_id: int
    segment_no: int
    start_plan_point_id: int
    end_plan_point_id: int
    start_point_order: int | None = None
    end_point_order: int | None = None
    transport_mode_code: str
    generation_status_code: str
    error_message: str | None
    generated_at: datetime | None
    remark: str | None
    created_at: datetime
    updated_at: datetime


class RoutePlanStructureResponse(BaseModel):
    plan: RoutePlanResponse
    points: list[RoutePlanPointResponse]
    segments: list[RoutePlanSegmentResponse]


class RoutePlanStructureReplaceRequest(BaseModel):
    points: list[RoutePlanPointUpsertItem] = Field(default_factory=list)


class RouteTrackGenerateRequest(BaseModel):
    provider_code: str | None = Field(default=None, max_length=64)


class RoutePlanTrackVersionSegmentResponse(BaseModel):
    id: int
    version_id: int
    segment_id: int
    segment_no: int
    geometry_json: dict[str, Any]
    distance_km: Decimal | None
    estimated_duration_hour: Decimal | None
    point_count: int
    edit_status_code: str
    created_at: datetime
    updated_at: datetime


class RoutePlanTrackVersionResponse(BaseModel):
    id: int
    plan_id: int
    structure_revision: int = 1
    version_no: int
    version_name: str | None
    source_type_code: str
    provider_type_code: str | None
    parent_version_id: int | None
    is_current: bool
    version_status_code: str
    distance_km: Decimal | None
    estimated_duration_hour: Decimal | None
    point_count: int
    segment_count: int
    summary_json: dict[str, Any] | None
    error_message: str | None
    generated_at: datetime | None
    created_at: datetime
    updated_at: datetime
    is_compatible_with_current_structure: bool = True
    segments: list[RoutePlanTrackVersionSegmentResponse] = Field(default_factory=list)


class RouteTrackVersionGenerateResponse(BaseModel):
    plan_id: int
    status: str
    message: str
    version: RoutePlanTrackVersionResponse | None = None


class RouteTrackVersionSegmentSaveItem(BaseModel):
    segment_id: int
    geometry_json: dict[str, Any]
    distance_km: Decimal | None = None
    estimated_duration_hour: Decimal | None = None
    edit_status_code: str = Field(default="EDITED", max_length=64)


class RouteTrackVersionSaveRequest(BaseModel):
    parent_version_id: int | None = None
    version_name: str | None = Field(default=None, max_length=128)
    summary_json: dict[str, Any] | None = None
    segments: list[RouteTrackVersionSegmentSaveItem] = Field(default_factory=list)
