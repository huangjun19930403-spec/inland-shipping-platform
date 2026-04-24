"""freight 模块 schema。"""

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


class FreightListQuery(BaseModel):
    keyword: str | None = None
    status_code: str | None = None
    source_type: str | None = None
    source_channel: str | None = None
    origin_city_code: str | None = None
    destination_city_code: str | None = None
    commodity_id: int | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class FreightCreateRequest(BaseModel):
    freight_no: str | None = Field(default=None, max_length=32)
    source_type_code: str = Field(min_length=1, max_length=64)
    cargo_title: str = Field(min_length=1, max_length=256)
    cargo_description: str | None = Field(default=None, max_length=1024)
    commodity_standard_id: int
    packaging_form_code: str | None = Field(default=None, max_length=64)
    estimated_tonnage: Decimal | None = None
    min_tonnage: Decimal | None = None
    max_tonnage: Decimal | None = None
    unit_price: Decimal | None = None
    total_price: Decimal | None = None
    price_unit: str | None = Field(default=None, max_length=32)
    settlement_method_code: str | None = Field(default=None, max_length=64)
    origin_node_id: int | None = None
    destination_node_id: int | None = None
    origin_province_code: str = Field(min_length=1, max_length=12)
    origin_city_code: str = Field(min_length=1, max_length=12)
    origin_district_code: str | None = Field(default=None, max_length=12)
    destination_province_code: str = Field(min_length=1, max_length=12)
    destination_city_code: str = Field(min_length=1, max_length=12)
    destination_district_code: str | None = Field(default=None, max_length=12)
    origin_region_id_cache: int | None = None
    destination_region_id_cache: int | None = None
    loading_time_from: datetime | None = None
    loading_time_to: datetime | None = None
    unloading_time_from: datetime | None = None
    unloading_time_to: datetime | None = None
    publisher_org_name: str | None = Field(default=None, max_length=128)
    status_code: str = Field(default="DRAFT", min_length=1, max_length=64)
    published_at: datetime | None = None
    expired_at: datetime | None = None


class FreightUpdateRequest(BaseModel):
    cargo_title: str | None = Field(default=None, min_length=1, max_length=256)
    cargo_description: str | None = Field(default=None, max_length=1024)
    commodity_standard_id: int | None = None
    packaging_form_code: str | None = Field(default=None, max_length=64)
    estimated_tonnage: Decimal | None = None
    min_tonnage: Decimal | None = None
    max_tonnage: Decimal | None = None
    unit_price: Decimal | None = None
    total_price: Decimal | None = None
    price_unit: str | None = Field(default=None, max_length=32)
    settlement_method_code: str | None = Field(default=None, max_length=64)
    origin_node_id: int | None = None
    destination_node_id: int | None = None
    origin_province_code: str | None = Field(default=None, min_length=1, max_length=12)
    origin_city_code: str | None = Field(default=None, min_length=1, max_length=12)
    origin_district_code: str | None = Field(default=None, max_length=12)
    destination_province_code: str | None = Field(default=None, min_length=1, max_length=12)
    destination_city_code: str | None = Field(default=None, min_length=1, max_length=12)
    destination_district_code: str | None = Field(default=None, max_length=12)
    origin_region_id_cache: int | None = None
    destination_region_id_cache: int | None = None
    loading_time_from: datetime | None = None
    loading_time_to: datetime | None = None
    unloading_time_from: datetime | None = None
    unloading_time_to: datetime | None = None
    publisher_org_name: str | None = Field(default=None, max_length=128)
    published_at: datetime | None = None
    expired_at: datetime | None = None


class FreightStatusChangeRequest(BaseModel):
    status_code: str = Field(min_length=1, max_length=64)


class FreightResponse(BaseModel):
    id: int
    freight_no: str
    source_type_code: str
    cargo_title: str
    cargo_description: str | None
    commodity_standard_id: int
    packaging_form_code: str | None
    estimated_tonnage: Decimal | None
    min_tonnage: Decimal | None
    max_tonnage: Decimal | None
    unit_price: Decimal | None
    total_price: Decimal | None
    price_unit: str | None
    settlement_method_code: str | None
    origin_node_id: int | None
    destination_node_id: int | None
    origin_province_code: str
    origin_city_code: str
    origin_district_code: str | None
    destination_province_code: str
    destination_city_code: str
    destination_district_code: str | None
    origin_region_id_cache: int | None
    destination_region_id_cache: int | None
    loading_time_from: datetime | None
    loading_time_to: datetime | None
    unloading_time_from: datetime | None
    unloading_time_to: datetime | None
    publisher_org_name: str | None
    status_code: str
    published_at: datetime | None
    expired_at: datetime | None
    audit_status: str
    submitter_id: int | None
    auditor_id: int | None
    audited_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FreightContactItem(BaseModel):
    contact_name: str = Field(min_length=1, max_length=64)
    contact_role_code: str = Field(min_length=1, max_length=64)
    mobile_phone: str | None = Field(default=None, max_length=32)
    landline_phone: str | None = Field(default=None, max_length=32)
    wechat: str | None = Field(default=None, max_length=64)
    is_primary: bool = False


class FreightContactReplaceRequest(BaseModel):
    contacts: list[FreightContactItem] = Field(default_factory=list)


class FreightContactResponse(BaseModel):
    id: int
    freight_id: int
    contact_name: str
    contact_role_code: str
    mobile_phone: str | None
    landline_phone: str | None
    wechat: str | None
    is_primary: bool
    created_at: datetime
    updated_at: datetime


class FreightAttachmentCreateRequest(BaseModel):
    storage_provider_code: str = Field(min_length=1, max_length=64)
    file_url: str = Field(min_length=1, max_length=512)
    file_name: str = Field(min_length=1, max_length=256)
    file_ext: str | None = Field(default=None, max_length=32)
    file_size: int | None = None
    source_type_code: str = Field(min_length=1, max_length=64)
    uploaded_by: int | None = None
    uploaded_at: datetime | None = None


class FreightAttachmentUpdateRequest(BaseModel):
    storage_provider_code: str | None = Field(default=None, min_length=1, max_length=64)
    file_url: str | None = Field(default=None, min_length=1, max_length=512)
    file_name: str | None = Field(default=None, min_length=1, max_length=256)
    file_ext: str | None = Field(default=None, max_length=32)
    file_size: int | None = None
    source_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    uploaded_by: int | None = None
    uploaded_at: datetime | None = None


class FreightAttachmentResponse(BaseModel):
    id: int
    freight_id: int
    storage_provider_code: str
    file_url: str
    file_name: str
    file_ext: str | None
    file_size: int | None
    source_type_code: str
    uploaded_by: int | None
    uploaded_at: datetime | None
    created_at: datetime


class FreightTagReplaceRequest(BaseModel):
    tags: list[str] = Field(default_factory=list)


class FreightTagRelationResponse(BaseModel):
    id: int
    freight_id: int
    tag_code: str
    created_at: datetime


class FreightDetailResponse(BaseModel):
    profile: FreightResponse
    contacts: list[FreightContactResponse]
    attachments: list[FreightAttachmentResponse]
    tags: list[FreightTagRelationResponse]
