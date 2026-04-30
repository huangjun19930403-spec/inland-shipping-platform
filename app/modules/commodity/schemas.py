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


class CommodityMetadataResponse(BaseModel):
    categories: list[CommodityCategoryResponse]
    types: list[CommodityTypeResponse]


class CommodityStandardListQuery(BaseModel):
    category_id: int | None = None
    type_id: int | None = None
    keyword: str | None = None
    status: int | None = Field(default=None, ge=0, le=1)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=500)


class CommodityStandardCreateRequest(BaseModel):
    type_id: int
    name: str = Field(min_length=1, max_length=128)
    short_name: str | None = Field(default=None, max_length=64)
    main_unit_code: str = Field(min_length=1, max_length=32)
    is_active: bool = True


class CommodityStandardUpdateRequest(BaseModel):
    type_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=128)
    short_name: str | None = Field(default=None, max_length=64)
    english_name: str | None = Field(default=None, max_length=256)
    main_unit_code: str | None = Field(default=None, min_length=1, max_length=32)
    density_range_desc: str | None = Field(default=None, max_length=128)
    dangerous_grade_code: str | None = Field(default=None, max_length=64)
    is_active: bool | None = None
    audit_status: str | None = None


class CommodityAliasReplaceRequest(BaseModel):
    aliases: list[str] = Field(default_factory=list)


class CommodityAttributeItem(BaseModel):
    attribute_code: str = Field(min_length=1, max_length=64)
    attribute_name: str = Field(min_length=1, max_length=128)
    attribute_value_type_code: str = Field(min_length=1, max_length=64)
    attribute_unit: str | None = Field(default=None, max_length=32)
    is_required: bool = False
    default_value: str | None = Field(default=None, max_length=128)
    value_range_desc: str | None = Field(default=None, max_length=256)
    sort_order: int = 0


class CommodityAttributeReplaceRequest(BaseModel):
    attributes: list[CommodityAttributeItem] = Field(default_factory=list)


class CommodityRuleCodeReplaceRequest(BaseModel):
    codes: list[str] = Field(default_factory=list)


class CommodityStandardResponse(BaseModel):
    id: int
    type_id: int
    code: str
    name: str
    short_name: str | None
    english_name: str | None
    main_unit_code: str
    main_unit_name: str | None
    density_range_desc: str | None
    dangerous_grade_code: str | None
    dangerous_grade_name: str | None
    is_active: bool
    audit_status: str
    audit_status_name: str | None
    created_at: datetime
    updated_at: datetime


class CommodityStandardDetailResponse(BaseModel):
    standard: CommodityStandardResponse
    aliases: list[str]
    attributes: list[CommodityAttributeItem]
    packaging_form_codes: list[str]
    transport_mode_codes: list[str]
    ship_type_codes: list[str]
    node_type_codes: list[str]
    handling_mode_codes: list[str]
