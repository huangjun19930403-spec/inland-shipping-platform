"""dictionary 模块 schema。"""

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


class DictListQuery(BaseModel):
    keyword: str | None = None
    is_enabled: bool | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class DictCreateRequest(BaseModel):
    dict_code: str = Field(min_length=1, max_length=64)
    dict_name: str = Field(min_length=1, max_length=128)
    dict_name_en: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=512)
    is_system: bool = False
    is_enabled: bool = True
    sort_order: int = 0


class DictUpdateRequest(BaseModel):
    dict_name: str | None = Field(default=None, min_length=1, max_length=128)
    dict_name_en: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=512)
    is_enabled: bool | None = None
    sort_order: int | None = None


class DictResponse(BaseModel):
    id: int
    dict_code: str
    dict_name: str
    dict_name_en: str | None
    description: str | None
    is_system: bool
    status: int
    is_enabled: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


class DictItemListQuery(BaseModel):
    keyword: str | None = None
    is_enabled: bool | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=500)


class DictItemCreateRequest(BaseModel):
    item_code: str = Field(min_length=1, max_length=64)
    item_name: str = Field(min_length=1, max_length=128)
    item_name_en: str | None = Field(default=None, max_length=256)
    parent_item_id: int | None = None
    item_value: str | None = Field(default=None, max_length=128)
    color: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=512)
    ext_json: dict | None = None
    is_default: bool = False
    is_system: bool = False
    is_enabled: bool = True
    sort_order: int = 0


class DictItemUpdateRequest(BaseModel):
    item_name: str | None = Field(default=None, min_length=1, max_length=128)
    item_name_en: str | None = Field(default=None, max_length=256)
    parent_item_id: int | None = None
    item_value: str | None = Field(default=None, max_length=128)
    color: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=512)
    ext_json: dict | None = None
    is_default: bool | None = None
    is_enabled: bool | None = None
    sort_order: int | None = None


class DictItemResponse(BaseModel):
    id: int
    dict_id: int
    item_code: str
    item_name: str
    item_name_en: str | None
    parent_item_id: int | None
    item_value: str | None
    color: str | None
    description: str | None
    ext_json: dict | None
    is_default: bool
    is_system: bool
    status: int
    is_enabled: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


class DictOptionItemResponse(BaseModel):
    dict_code: str
    item_code: str
    item_name: str
    item_name_en: str | None
    item_value: str | None
    color: str | None
    description: str | None
    is_default: bool
    sort_order: int


class DictOptionsResponse(BaseModel):
    dict_code: str
    dict_name: str
    items: list[DictOptionItemResponse]


class DictItemOrderRequest(BaseModel):
    ordered_ids: list[int] = Field(default_factory=list)


class CodeSequenceResponse(BaseModel):
    id: int
    business_code: str
    business_name: str
    target_table: str
    target_column: str
    prefix: str
    date_format: str | None
    separator: str | None
    current_value: int
    value_length: int
    step: int
    reset_rule: str
    is_enabled: bool
    remark: str | None
    created_at: datetime
    updated_at: datetime


class CodeSequenceCreateRequest(BaseModel):
    business_code: str = Field(min_length=1, max_length=64)
    business_name: str = Field(min_length=1, max_length=128)
    target_table: str = Field(min_length=1, max_length=64)
    target_column: str = Field(min_length=1, max_length=64)
    prefix: str = Field(default="", max_length=32)
    date_format: str | None = Field(default=None, max_length=32)
    separator: str | None = Field(default=None, max_length=8)
    current_value: int = 0
    value_length: int = Field(default=6, ge=1, le=20)
    step: int = Field(default=1, ge=1, le=1000000)
    reset_rule: str = Field(default="NONE", min_length=1, max_length=32)
    is_enabled: bool = True
    remark: str | None = Field(default=None, max_length=512)


class CodeSequenceUpdateRequest(BaseModel):
    business_name: str | None = Field(default=None, min_length=1, max_length=128)
    target_table: str | None = Field(default=None, min_length=1, max_length=64)
    target_column: str | None = Field(default=None, min_length=1, max_length=64)
    prefix: str | None = Field(default=None, max_length=32)
    date_format: str | None = Field(default=None, max_length=32)
    separator: str | None = Field(default=None, max_length=8)
    current_value: int | None = None
    value_length: int | None = Field(default=None, ge=1, le=20)
    step: int | None = Field(default=None, ge=1, le=1000000)
    reset_rule: str | None = Field(default=None, min_length=1, max_length=32)
    is_enabled: bool | None = None
    remark: str | None = Field(default=None, max_length=512)
