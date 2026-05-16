"""commodity 模块 schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResponse(BaseModel, Generic[T]):
    total: int
    page: int
    page_size: int
    items: list[T]


class CommodityCategoryResponse(BaseModel):
    id: int
    code: str
    name: str
    description: str | None
    sort_order: int
    audit_status: str
    created_at: datetime
    updated_at: datetime


class CommodityTypeResponse(BaseModel):
    id: int
    category_id: int
    code: str
    name: str
    description: str | None
    sort_order: int
    audit_status: str
    created_at: datetime
    updated_at: datetime


class CommodityAttributeDefinitionResponse(BaseModel):
    id: int
    attribute_code: str
    attribute_name: str
    attribute_group_code: str
    attribute_group_name: str | None = None
    value_type_code: str
    value_type_name: str | None = None
    unit_code: str | None = None
    unit_name: str | None = None
    option_dict_code: str | None = None
    description: str | None = None
    is_required_default: bool
    is_enabled: bool
    sort_order: int


class CommodityMetadataResponse(BaseModel):
    categories: list[CommodityCategoryResponse]
    types: list[CommodityTypeResponse]
    attribute_definitions: list[CommodityAttributeDefinitionResponse] = Field(default_factory=list)


class CommodityStandardListQuery(BaseModel):
    category_id: int | None = None
    type_id: int | None = None
    keyword: str | None = None
    status: int | None = Field(default=None, ge=0, le=1)
    main_unit_code: str | None = None
    cargo_form_code: str | None = None
    is_bulk_cargo: bool | None = None
    is_container_suitable: bool | None = None
    is_hazardous: bool | None = None
    source_type_code: str | None = None
    has_alias: bool | None = None
    has_image: bool | None = None
    used_by_freight: bool | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=500)


class CommodityStandardCreateRequest(BaseModel):
    category_id: int
    type_id: int
    name: str = Field(min_length=1, max_length=128)
    short_name: str | None = Field(default=None, max_length=64)
    english_name: str | None = Field(default=None, max_length=256)
    main_unit_code: str = Field(min_length=1, max_length=32)
    specification: str | None = Field(default=None, max_length=256)
    cargo_form_code: str | None = Field(default=None, max_length=64)
    density_range_desc: str | None = Field(default=None, max_length=128)
    dangerous_grade_code: str | None = Field(default=None, max_length=64)
    is_bulk_cargo: bool = True
    is_container_suitable: bool = False
    is_hazardous: bool = False
    pollution_risk_level_code: str | None = Field(default=None, max_length=64)
    loading_requirement: str | None = None
    unloading_requirement: str | None = None
    storage_requirement: str | None = None
    source_type_code: str = Field(default="MANUAL", min_length=1, max_length=64)
    recognition_priority: int = Field(default=50, ge=0, le=999)
    remark: str | None = None
    is_active: bool = True


class CommodityStandardUpdateRequest(BaseModel):
    category_id: int | None = None
    type_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=128)
    short_name: str | None = Field(default=None, max_length=64)
    english_name: str | None = Field(default=None, max_length=256)
    main_unit_code: str | None = Field(default=None, min_length=1, max_length=32)
    specification: str | None = Field(default=None, max_length=256)
    cargo_form_code: str | None = Field(default=None, max_length=64)
    density_range_desc: str | None = Field(default=None, max_length=128)
    dangerous_grade_code: str | None = Field(default=None, max_length=64)
    is_bulk_cargo: bool | None = None
    is_container_suitable: bool | None = None
    is_hazardous: bool | None = None
    pollution_risk_level_code: str | None = Field(default=None, max_length=64)
    loading_requirement: str | None = None
    unloading_requirement: str | None = None
    storage_requirement: str | None = None
    source_type_code: str | None = Field(default=None, max_length=64)
    recognition_priority: int | None = Field(default=None, ge=0, le=999)
    remark: str | None = None
    is_active: bool | None = None
    audit_status: str | None = None


class CommodityAliasItem(BaseModel):
    alias_name: str = Field(min_length=1, max_length=128)
    alias_type_code: str = Field(default="COMMON_NAME", min_length=1, max_length=64)
    source_type_code: str = Field(default="MANUAL", min_length=1, max_length=64)
    is_primary: bool = False
    is_enabled: bool = True
    match_weight: int = Field(default=80, ge=0, le=100)
    remark: str | None = Field(default=None, max_length=512)


class CommodityAliasReplaceRequest(BaseModel):
    aliases: list[CommodityAliasItem | str] = Field(default_factory=list)


class CommodityAliasResponse(CommodityAliasItem):
    id: int
    alias_type_name: str | None = None
    source_type_name: str | None = None


class CommodityAttributeItem(BaseModel):
    attribute_definition_id: int | None = None
    attribute_value: str | None = Field(default=None, max_length=512)
    is_required: bool = False
    sort_order: int = 0
    # Backward-compatible fields accepted from old callers; new UI uses definition_id.
    attribute_code: str | None = Field(default=None, max_length=64)
    attribute_name: str | None = Field(default=None, max_length=128)
    attribute_value_type_code: str | None = Field(default=None, max_length=64)
    attribute_unit: str | None = Field(default=None, max_length=32)
    default_value: str | None = Field(default=None, max_length=128)
    value_range_desc: str | None = Field(default=None, max_length=256)


class CommodityAttributeReplaceRequest(BaseModel):
    attributes: list[CommodityAttributeItem] = Field(default_factory=list)


class CommodityAttributeResponse(BaseModel):
    id: int
    attribute_definition_id: int | None
    attribute_code: str | None
    attribute_name: str | None
    attribute_group_code: str | None = None
    attribute_group_name: str | None = None
    value_type_code: str | None
    value_type_name: str | None = None
    unit_code: str | None = None
    unit_name: str | None = None
    attribute_value: str | None
    is_required: bool
    sort_order: int


class CommodityDefaultRuleItem(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    is_default: bool = False
    is_enabled: bool = True
    remark: str | None = Field(default=None, max_length=512)


class CommodityDefaultRuleReplaceRequest(BaseModel):
    items: list[CommodityDefaultRuleItem] = Field(default_factory=list)


class CommodityDecisionRuleItem(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    rule_type_code: str = Field(default="ALLOWED", min_length=1, max_length=64)
    priority: int = Field(default=50, ge=0, le=999)
    operation_side_code: str | None = Field(default=None, max_length=64)
    is_enabled: bool = True
    rule_desc: str | None = Field(default=None, max_length=256)
    allow_flag: bool | None = None


class CommodityDecisionRuleReplaceRequest(BaseModel):
    items: list[CommodityDecisionRuleItem] = Field(default_factory=list)


class CommodityDefaultRuleResponse(BaseModel):
    code: str
    name: str | None
    is_default: bool
    is_enabled: bool
    remark: str | None = None


class CommodityDecisionRuleResponse(BaseModel):
    code: str
    name: str | None
    rule_type_code: str
    rule_type_name: str | None = None
    priority: int
    operation_side_code: str | None = None
    operation_side_name: str | None = None
    is_enabled: bool
    allow_flag: bool
    rule_desc: str | None


class CommodityStandardImageUpdateRequest(BaseModel):
    image_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    image_name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    is_primary: bool | None = None
    sort_order: int | None = None


class CommodityStandardImageResponse(BaseModel):
    id: int
    commodity_standard_id: int
    file_id: int
    image_type_code: str
    image_type_name: str | None
    image_name: str
    description: str | None
    is_primary: bool
    sort_order: int
    content_url: str
    original_file_name: str
    content_type: str
    file_size: int
    created_at: datetime
    updated_at: datetime


class CommodityFreightUsageItem(BaseModel):
    freight_id: int
    freight_no: str
    cargo_title: str | None = None
    status_code: str | None = None
    updated_at: datetime | None = None


class CommodityStandardUsageSummary(BaseModel):
    freight_count: int = 0
    raw_pending_count: int = 0
    latest_freight_at: datetime | None = None
    recent_freights: list[CommodityFreightUsageItem] = Field(default_factory=list)


class CommodityStandardResponse(BaseModel):
    id: int
    category_id: int | None
    category_code: str | None = None
    category_name: str | None = None
    type_id: int
    type_code: str | None = None
    type_name: str | None = None
    code: str
    name: str
    short_name: str | None
    english_name: str | None
    main_unit_code: str
    main_unit_name: str | None
    specification: str | None
    cargo_form_code: str | None
    cargo_form_name: str | None
    density_range_desc: str | None
    dangerous_grade_code: str | None
    dangerous_grade_name: str | None
    is_bulk_cargo: bool
    is_container_suitable: bool
    is_hazardous: bool
    pollution_risk_level_code: str | None
    pollution_risk_level_name: str | None
    loading_requirement: str | None
    unloading_requirement: str | None
    storage_requirement: str | None
    source_type_code: str
    source_type_name: str | None
    recognition_priority: int
    remark: str | None
    is_active: bool
    audit_status: str
    audit_status_name: str | None
    alias_count: int = 0
    attribute_count: int = 0
    image_count: int = 0
    freight_count: int = 0
    capability_summary: str | None = None
    primary_image: CommodityStandardImageResponse | None = None
    created_at: datetime
    updated_at: datetime


class CommodityStandardDetailResponse(BaseModel):
    standard: CommodityStandardResponse
    images: list[CommodityStandardImageResponse]
    aliases: list[CommodityAliasResponse]
    attributes: list[CommodityAttributeResponse]
    packaging_forms: list[CommodityDefaultRuleResponse]
    transport_modes: list[CommodityDefaultRuleResponse]
    ship_type_rules: list[CommodityDecisionRuleResponse]
    node_type_rules: list[CommodityDecisionRuleResponse]
    handling_mode_rules: list[CommodityDecisionRuleResponse]
    usage_summary: CommodityStandardUsageSummary
