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


class AdminRegionBoundaryResponse(BaseModel):
    id: int
    admin_region_id: int
    admin_code: str
    admin_name: str
    version_no: int
    boundary_source_type_code: str
    boundary_source_type_name: str | None
    geometry_json: dict
    center_longitude: Decimal | None
    center_latitude: Decimal | None
    area_km2: Decimal | None
    is_current: bool
    effective_from: datetime | None
    effective_to: datetime | None
    imported_by: int | None
    imported_at: datetime | None
    remark: str | None
    created_at: datetime
    updated_at: datetime


class WaterSystemQuery(BaseModel):
    keyword: str | None = None
    water_level: int | None = Field(default=None, ge=0, le=4)
    feature_type_code: str | None = None
    hydrology_period_code: str | None = None
    salinity_type_code: str | None = None
    navigation_category_code: str | None = None
    navigation_scope_code: str | None = None
    ais_situation_scope: str | None = None
    geometry_status_code: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=500)


class WaterSystemSummaryResponse(BaseModel):
    total_count: int
    boundary_count: int
    enabled_count: int
    level_counts: dict[str, int] = Field(default_factory=dict)
    navigation_scope_counts: dict[str, int] = Field(default_factory=dict)
    navigation_category_counts: dict[str, int] = Field(default_factory=dict)
    ais_situation_scope_counts: dict[str, int] = Field(default_factory=dict)
    current_source_version: str | None = None


class WaterSystemResponse(BaseModel):
    id: int
    water_system_code: str
    water_system_name: str
    standard_name: str | None = None
    display_name: str | None = None
    parent_water_system_code: str | None = None
    water_level: int
    water_level_name: str
    feature_type_code: str
    feature_type_name: str
    hydrology_period_code: str
    hydrology_period_name: str
    salinity_type_code: str
    salinity_type_name: str
    water_boundary_type_code: str
    water_boundary_type_name: str
    navigation_category_code: str | None = None
    navigation_category_name: str | None = None
    navigation_scope_code: str | None = None
    navigation_scope_name: str | None = None
    ais_situation_scope: str | None = None
    ais_situation_scope_name: str | None = None
    display_priority: int = 0
    match_level_code: str | None = None
    match_level_name: str | None = None
    match_confidence_code: str | None = None
    match_confidence_name: str | None = None
    review_required: bool = False
    source_feature_count: int = 0
    source_object_ids: list[int] = Field(default_factory=list)
    source_levels: list[int] = Field(default_factory=list)
    source_level_names: list[str] = Field(default_factory=list)
    source_layer_names: list[str] = Field(default_factory=list)
    source_names: list[str] = Field(default_factory=list)
    source_remarks: list[str] = Field(default_factory=list)
    geometry_union_status: str | None = None
    geometry_union_status_name: str | None = None
    business_remark: str | None = None
    source_remark: str | None
    source_layer_name: str
    source_version: str
    is_enabled: bool
    has_boundary: bool = False
    geometry_status_code: str = "UNKNOWN"
    geometry_status_name: str = "未知"
    imported_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class WaterSystemDetailResponse(WaterSystemResponse):
    center_longitude: Decimal | None = None
    center_latitude: Decimal | None = None
    display_center_longitude: Decimal | None = None
    display_center_latitude: Decimal | None = None
    ring_count: int = 0
    point_count: int = 0
    boundary_quality_code: str = "UNKNOWN"
    boundary_quality_name: str = "未知"


class WaterSystemBoundaryResponse(BaseModel):
    water_system_code: str
    water_system_name: str
    water_level: int
    water_level_name: str
    navigation_category_code: str | None = None
    navigation_category_name: str | None = None
    navigation_scope_code: str | None = None
    navigation_scope_name: str | None = None
    parent_water_system_code: str | None = None
    precision: str
    boundary_paths: list[list[list[float]]] = Field(default_factory=list)
    has_boundary: bool = False
    geometry_status_code: str = "UNKNOWN"
    geometry_status_name: str = "未知"
    boundary_quality_code: str = "UNKNOWN"
    boundary_quality_name: str = "未知"
    center_longitude: Decimal | None = None
    center_latitude: Decimal | None = None
    display_center_longitude: Decimal | None = None
    display_center_latitude: Decimal | None = None


class BusinessRegionListQuery(BaseModel):
    keyword: str | None = None
    status: int | None = Field(default=None, ge=0, le=1)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=500)


class BusinessRegionCreateRequest(BaseModel):
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
    region_type_name: str | None
    description: str | None
    sort_order: int
    status: int
    status_name: str | None
    current_boundary_version_id: int | None
    audit_status: str
    audit_status_name: str | None
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
    boundary_source_type_name: str | None
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


class AddressMapGeocodeQuery(BaseModel):
    keyword: str = Field(min_length=1, max_length=256)
    city_code: str | None = Field(default=None, max_length=12)


class AddressMapReverseGeocodeQuery(BaseModel):
    longitude: Decimal = Field(ge=-180, le=180)
    latitude: Decimal = Field(ge=-90, le=90)


class AddressMapCandidate(BaseModel):
    longitude: Decimal
    latitude: Decimal
    formatted_address: str | None
    province_name: str | None
    province_code: str | None
    city_name: str | None
    city_code: str | None
    district_name: str | None
    district_code: str | None
    adcode: str | None
    city_region_id: int | None
    provider: str
    confidence: float | None
    level: str | None


class AddressMapGeocodeResponse(BaseModel):
    items: list[AddressMapCandidate]


class TransportNodeListQuery(BaseModel):
    keyword: str | None = None
    city_code: str | None = None
    status: int | None = Field(default=None, ge=0, le=1)
    category_code: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=500)


class TransportNodeCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    short_name: str | None = Field(default=None, max_length=64)
    node_type_code: str = Field(min_length=1, max_length=64)
    province_code: str = Field(min_length=1, max_length=12)
    city_code: str = Field(min_length=1, max_length=12)
    district_code: str | None = Field(default=None, max_length=12)
    city_region_id: int | None = None
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
    ext_json: dict | None = None


class TransportNodeContactItem(BaseModel):
    contact_name: str = Field(min_length=1, max_length=64)
    contact_type_code: str = Field(min_length=1, max_length=64)
    mobile_phone: str | None = Field(default=None, max_length=32)
    wechat: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=128)
    is_primary: bool = False
    remark: str | None = Field(default=None, max_length=512)


class TransportNodeContactReplaceRequest(BaseModel):
    contacts: list[TransportNodeContactItem] = Field(default_factory=list)


class TransportNodeContactResponse(BaseModel):
    id: int
    node_id: int
    contact_name: str
    contact_type_code: str
    contact_type_name: str | None
    mobile_phone: str | None
    wechat: str | None
    email: str | None
    is_primary: bool
    remark: str | None
    created_at: datetime
    updated_at: datetime


class TransportNodePhotoUpdateRequest(BaseModel):
    photo_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    photo_name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    is_primary: bool | None = None
    sort_order: int | None = None


class TransportNodePhotoResponse(BaseModel):
    id: int
    node_id: int
    file_id: int
    photo_type_code: str
    photo_type_name: str | None
    photo_name: str
    description: str | None
    is_primary: bool
    sort_order: int
    content_url: str
    original_file_name: str
    content_type: str
    file_size: int
    created_at: datetime
    updated_at: datetime


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
    node_type_name: str | None
    province_code: str
    province_name: str | None
    city_code: str
    city_name: str | None
    district_code: str | None
    district_name: str | None
    city_region_id: int
    address: str | None
    longitude: Decimal | None
    latitude: Decimal | None
    status: int
    status_name: str | None
    lifecycle_status_code: str
    lifecycle_status_name: str | None
    sort_order: int
    is_hot_node: bool
    audit_status: str
    audit_status_name: str | None
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
    ext_json: dict | None
    updated_at: datetime


class NodeAliasResponse(BaseModel):
    id: int
    alias_name: str
    alias_type_code: str
    source_type_code: str
    is_primary: bool


class TransportNodeDetailResponse(BaseModel):
    node: TransportNodeResponse
    profile: TransportNodeProfileResponse | None
    contacts: list[TransportNodeContactResponse] = Field(default_factory=list)
    photos: list[TransportNodePhotoResponse] = Field(default_factory=list)
    aliases: list[str]
    aliases_meta: list[NodeAliasResponse] = Field(default_factory=list)
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
    constraint_type_name: str | None
    province_code: str | None
    province_name: str | None
    city_code: str | None
    city_name: str | None
    longitude: Decimal
    latitude: Decimal
    valid_from: datetime | None
    valid_to: datetime | None
    severity_level: int | None
    description: str | None
    status: int
    status_name: str | None
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
