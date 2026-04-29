"""address 模块 schema。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResponse(BaseModel, Generic[T]):
    total: int
    page: int
    page_size: int
    items: list[T]


class AdminRegionQuery(BaseModel):
    level: int | None = Field(default=None, ge=1, le=3)
    parent_code: str | None = None
    keyword: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=500)


class AdminRegionResponse(BaseModel):
    id: int
    code: str
    name: str
    short_name: str | None
    level: int
    parent_code: str | None
    province_code: str | None
    city_code: str | None
    district_code: str | None
    longitude: Decimal | None
    latitude: Decimal | None
    status: int


class BusinessRegionListQuery(BaseModel):
    keyword: str | None = None
    status: int | None = Field(default=None, ge=0, le=1)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=500)


class BusinessRegionCreateRequest(BaseModel):
    code: str | None = Field(default=None, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    short_name: str | None = Field(default=None, max_length=64)
    region_type_code: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=512)
    sort_order: int = 0
    status: int = Field(default=1, ge=0, le=1)


class BusinessRegionUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    short_name: str | None = Field(default=None, max_length=64)
    region_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=512)
    sort_order: int | None = None
    status: int | None = Field(default=None, ge=0, le=1)


class BusinessRegionResponse(BaseModel):
    id: int
    code: str
    name: str
    short_name: str | None
    region_type_code: str
    description: str | None
    sort_order: int
    status: int
    current_boundary_version_id: int | None
    audit_status: str
    submitter_id: int | None
    auditor_id: int | None
    audited_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RegionBoundaryVersionCreateRequest(BaseModel):
    version_no: int = Field(default=1, ge=1)
    boundary_source_type_code: str = Field(min_length=1, max_length=64)
    geometry_json: dict
    center_longitude: Decimal | None = None
    center_latitude: Decimal | None = None
    area_km2: Decimal | None = None
    is_current: bool = False
    remark: str | None = Field(default=None, max_length=512)


class RegionBoundaryVersionResponse(BaseModel):
    id: int
    region_id: int
    version_no: int
    boundary_source_type_code: str
    geometry_json: dict
    center_longitude: Decimal | None
    center_latitude: Decimal | None
    area_km2: Decimal | None
    is_current: bool
    effective_from: datetime | None
    effective_to: datetime | None
    approved_by: int | None
    approved_at: datetime | None
    remark: str | None
    created_at: datetime
    updated_at: datetime


class RegionCityRelationReplaceRequest(BaseModel):
    city_codes: list[str] = Field(default_factory=list)


class RegionCityRelationResponse(BaseModel):
    id: int
    region_id: int
    city_region_id: int
    city_code: str
    city_name: str
    relation_type_code: str
    is_primary: bool
    sort_order: int


class TransportNodeListQuery(BaseModel):
    keyword: str | None = None
    city_code: str | None = None
    status: int | None = Field(default=None, ge=0, le=1)
    category_code: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=500)


class TransportNodeCreateRequest(BaseModel):
    code: str | None = Field(default=None, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    short_name: str | None = Field(default=None, max_length=64)
    node_type_code: str = Field(min_length=1, max_length=64)
    province_code: str = Field(min_length=1, max_length=12)
    city_code: str = Field(min_length=1, max_length=12)
    district_code: str | None = Field(default=None, max_length=12)
    city_region_id: int
    address: str | None = Field(default=None, max_length=256)
    longitude: Decimal | None = None
    latitude: Decimal | None = None
    status: int = Field(default=1, ge=0, le=1)
    lifecycle_status_code: str = Field(min_length=1, max_length=64)
    sort_order: int = 0
    is_hot_node: bool = False


class TransportNodeUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    short_name: str | None = Field(default=None, max_length=64)
    node_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    province_code: str | None = Field(default=None, min_length=1, max_length=12)
    city_code: str | None = Field(default=None, min_length=1, max_length=12)
    district_code: str | None = Field(default=None, max_length=12)
    city_region_id: int | None = None
    address: str | None = Field(default=None, max_length=256)
    longitude: Decimal | None = None
    latitude: Decimal | None = None
    status: int | None = Field(default=None, ge=0, le=1)
    lifecycle_status_code: str | None = Field(default=None, min_length=1, max_length=64)
    sort_order: int | None = None
    is_hot_node: bool | None = None


class TransportNodeProfileUpsertRequest(BaseModel):
    business_nature_code: str | None = Field(default=None, max_length=64)
    channel_depth_m: Decimal | None = None
    max_draft_m: Decimal | None = None
    berth_count: int | None = None
    annual_throughput_ton: Decimal | None = None
    open_hours_desc: str | None = Field(default=None, max_length=128)
    contact_person: str | None = Field(default=None, max_length=64)
    contact_phone: str | None = Field(default=None, max_length=32)
    ext_json: dict | None = None


class NodeAliasReplaceRequest(BaseModel):
    aliases: list[str] = Field(default_factory=list)


class NodeCodeListReplaceRequest(BaseModel):
    codes: list[str] = Field(default_factory=list)


class TransportNodeResponse(BaseModel):
    id: int
    code: str
    name: str
    short_name: str | None
    node_type_code: str
    province_code: str
    city_code: str
    district_code: str | None
    city_region_id: int
    address: str | None
    longitude: Decimal | None
    latitude: Decimal | None
    status: int
    lifecycle_status_code: str
    sort_order: int
    is_hot_node: bool
    audit_status: str
    created_at: datetime
    updated_at: datetime


class TransportNodeProfileResponse(BaseModel):
    id: int
    node_id: int
    business_nature_code: str | None
    channel_depth_m: Decimal | None
    max_draft_m: Decimal | None
    berth_count: int | None
    annual_throughput_ton: Decimal | None
    open_hours_desc: str | None
    contact_person: str | None
    contact_phone: str | None
    ext_json: dict | None
    updated_at: datetime


class TransportNodeDetailResponse(BaseModel):
    node: TransportNodeResponse
    profile: TransportNodeProfileResponse | None
    aliases: list[str]
    business_category_codes: list[str]
    packaging_form_codes: list[str]
    handling_mode_codes: list[str]


class NavigationConstraintPointListQuery(BaseModel):
    keyword: str | None = None
    constraint_type_code: str | None = Field(default=None, max_length=64)
    city_code: str | None = Field(default=None, max_length=12)
    status: int | None = Field(default=None, ge=0, le=1)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=500)


class NavigationConstraintPointCreateRequest(BaseModel):
    code: str | None = Field(default=None, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    constraint_type_code: str = Field(min_length=1, max_length=64)
    province_code: str | None = Field(default=None, max_length=12)
    city_code: str | None = Field(default=None, max_length=12)
    longitude: Decimal
    latitude: Decimal
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    severity_level: int | None = None
    description: str | None = Field(default=None, max_length=512)
    status: int = Field(default=1, ge=0, le=1)


class NavigationConstraintPointUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    constraint_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    province_code: str | None = Field(default=None, max_length=12)
    city_code: str | None = Field(default=None, max_length=12)
    longitude: Decimal | None = None
    latitude: Decimal | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    severity_level: int | None = None
    description: str | None = Field(default=None, max_length=512)
    status: int | None = Field(default=None, ge=0, le=1)


class NavigationConstraintPointResponse(BaseModel):
    id: int
    code: str
    name: str
    constraint_type_code: str
    province_code: str | None
    city_code: str | None
    longitude: Decimal
    latitude: Decimal
    valid_from: datetime | None
    valid_to: datetime | None
    severity_level: int | None
    description: str | None
    status: int
    created_at: datetime
    updated_at: datetime


class NavigationConstraintProfileUpsertRequest(BaseModel):
    max_tonnage: Decimal | None = None
    max_allowed_draft_m: Decimal | None = None
    min_water_depth_m: Decimal | None = None
    under_keel_clearance_m: Decimal | None = None
    max_air_draft_m: Decimal | None = None
    max_beam_m: Decimal | None = None
    max_length_m: Decimal | None = None
    allowed_time_window: str | None = Field(default=None, max_length=256)
    restriction_rule_json: dict[str, Any] | None = None
    rule_description: str | None = Field(default=None, max_length=512)
    warning_message: str | None = Field(default=None, max_length=512)


class NavigationConstraintProfileResponse(BaseModel):
    id: int
    constraint_point_id: int
    max_tonnage: Decimal | None
    max_allowed_draft_m: Decimal | None
    min_water_depth_m: Decimal | None
    under_keel_clearance_m: Decimal | None
    max_air_draft_m: Decimal | None
    max_beam_m: Decimal | None
    max_length_m: Decimal | None
    allowed_time_window: str | None
    restriction_rule_json: dict[str, Any] | None
    rule_description: str | None
    warning_message: str | None
    created_at: datetime
    updated_at: datetime


class NavigationConstraintPointDetailResponse(BaseModel):
    point: NavigationConstraintPointResponse
    profile: NavigationConstraintProfileResponse | None


class NavigationConstraintPointStatusChangeRequest(BaseModel):
    status: int = Field(ge=0, le=1)
