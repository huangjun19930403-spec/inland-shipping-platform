"""freight 模块 schema。"""

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
    source_type_code: str = Field(default="MANUAL", min_length=1, max_length=64)
    source_channel_code: str | None = Field(default="MANUAL_FORM", max_length=64)
    source_ref_no: str | None = Field(default=None, max_length=128)
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
    status_code: str = Field(default="PUBLISHED", min_length=1, max_length=64)
    published_at: datetime | None = None
    expired_at: datetime | None = None


class FreightUpdateRequest(BaseModel):
    source_channel_code: str | None = Field(default=None, max_length=64)
    source_ref_no: str | None = Field(default=None, max_length=128)
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
    source_type_name: str | None = None
    source_channel_code: str | None = None
    source_channel_name: str | None = None
    source_ref_no: str | None = None
    source_candidate_id: int | None = None
    cargo_title: str
    cargo_description: str | None
    commodity_standard_id: int
    commodity_standard_code: str | None = None
    commodity_standard_name: str | None = None
    packaging_form_code: str | None
    packaging_form_name: str | None = None
    estimated_tonnage: Decimal | None
    min_tonnage: Decimal | None
    max_tonnage: Decimal | None
    unit_price: Decimal | None
    total_price: Decimal | None
    price_unit: str | None
    settlement_method_code: str | None
    settlement_method_name: str | None = None
    origin_node_id: int | None
    origin_node_name: str | None = None
    destination_node_id: int | None
    destination_node_name: str | None = None
    origin_province_code: str
    origin_city_code: str
    origin_city_name: str | None = None
    origin_district_code: str | None
    destination_province_code: str
    destination_city_code: str
    destination_city_name: str | None = None
    destination_district_code: str | None
    origin_region_id_cache: int | None
    origin_region_name: str | None = None
    destination_region_id_cache: int | None
    destination_region_name: str | None = None
    loading_time_from: datetime | None
    loading_time_to: datetime | None
    unloading_time_from: datetime | None
    unloading_time_to: datetime | None
    publisher_org_name: str | None
    status_code: str
    status_name: str | None = None
    published_at: datetime | None
    expired_at: datetime | None
    confirmed_at: datetime | None = None
    confirmed_by: int | None = None
    audit_status: str
    audit_status_name: str | None = None
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


class FreightAiTraceResponse(BaseModel):
    parse_task_id: int | None = None
    task_no: str | None = None
    status_code: str | None = None
    status_name: str | None = None
    raw_content: str | None = None
    source_inbound_id: int | None = None
    candidate_id: int | None = None
    candidate_no: str | None = None
    confidence_score: Decimal | None = None
    match_basis_json: dict[str, Any] | None = None


class FreightConfirmationResponse(BaseModel):
    candidate_id: int
    candidate_no: str
    action_code: str
    action_name: str | None = None
    operator_id: int | None
    operated_at: datetime
    feedback_remark: str | None
    before_json: dict[str, Any] | None
    after_json: dict[str, Any] | None


class FreightDetailResponse(BaseModel):
    profile: FreightResponse
    contacts: list[FreightContactResponse]
    attachments: list[FreightAttachmentResponse]
    tags: list[FreightTagRelationResponse]
    ai_parse_records: list[FreightAiTraceResponse] = Field(default_factory=list)
    confirmation_records: list[FreightConfirmationResponse] = Field(default_factory=list)


class FreightSourceInboundListQuery(BaseModel):
    keyword: str | None = None
    status_code: str | None = None
    source_channel_code: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class FreightSourceInboundCreateRequest(BaseModel):
    inbound_no: str | None = Field(default=None, max_length=32)
    source_type_code: str = Field(default="WECHAT", max_length=64)
    source_channel_code: str = Field(default="WECHAT_TEXT", max_length=64)
    external_ref_no: str | None = Field(default=None, max_length=128)
    sender_name: str | None = Field(default=None, max_length=128)
    sender_contact: str | None = Field(default=None, max_length=64)
    raw_title: str | None = Field(default=None, max_length=256)
    raw_content: str = Field(min_length=1)
    received_at: datetime | None = None


class FreightSourceInboundResponse(BaseModel):
    id: int
    inbound_no: str
    source_type_code: str
    source_type_name: str | None = None
    source_channel_code: str
    source_channel_name: str | None = None
    external_ref_no: str | None
    sender_name: str | None
    sender_contact: str | None
    raw_title: str | None
    raw_content: str
    received_at: datetime | None
    status_code: str
    status_name: str | None = None
    parse_task_id: int | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class FreightAiParseTaskListQuery(BaseModel):
    keyword: str | None = None
    status_code: str | None = None
    source_channel_code: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class FreightAiParseTaskCreateRequest(BaseModel):
    task_no: str | None = Field(default=None, max_length=32)
    source_inbound_id: int | None = None
    source_type_code: str = Field(default="WECHAT", max_length=64)
    source_channel_code: str = Field(default="WECHAT_TEXT", max_length=64)
    raw_content: str | None = None


class FreightClueResponse(BaseModel):
    id: int
    clue_no: str
    parse_task_id: int
    source_inbound_id: int | None
    segment_index: int
    raw_text: str
    status_code: str
    status_name: str | None = None
    parse_result_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class FreightCandidateUpdateRequest(BaseModel):
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
    origin_province_code: str | None = Field(default=None, max_length=12)
    origin_city_code: str | None = Field(default=None, max_length=12)
    origin_district_code: str | None = Field(default=None, max_length=12)
    destination_province_code: str | None = Field(default=None, max_length=12)
    destination_city_code: str | None = Field(default=None, max_length=12)
    destination_district_code: str | None = Field(default=None, max_length=12)
    origin_region_id_cache: int | None = None
    destination_region_id_cache: int | None = None
    publisher_org_name: str | None = Field(default=None, max_length=128)
    contact_name: str | None = Field(default=None, max_length=64)
    contact_phone: str | None = Field(default=None, max_length=32)
    contact_wechat: str | None = Field(default=None, max_length=64)


class FreightCandidateConfirmRequest(BaseModel):
    remark: str | None = Field(default=None, max_length=512)
    overrides: FreightCandidateUpdateRequest | None = None


class FreightCandidateRejectRequest(BaseModel):
    remark: str = Field(min_length=1, max_length=512)


class FreightCandidateResponse(BaseModel):
    id: int
    candidate_no: str
    parse_task_id: int
    clue_id: int | None
    source_inbound_id: int | None
    cargo_title: str
    cargo_description: str | None
    commodity_standard_id: int | None
    commodity_standard_name: str | None = None
    commodity_match_name: str | None
    commodity_match_score: Decimal | None
    packaging_form_code: str | None
    estimated_tonnage: Decimal | None
    min_tonnage: Decimal | None
    max_tonnage: Decimal | None
    unit_price: Decimal | None
    total_price: Decimal | None
    price_unit: str | None
    settlement_method_code: str | None
    origin_text: str | None
    destination_text: str | None
    origin_node_id: int | None
    origin_node_name: str | None = None
    destination_node_id: int | None
    destination_node_name: str | None = None
    origin_province_code: str | None
    origin_city_code: str | None
    origin_city_name: str | None = None
    origin_district_code: str | None
    destination_province_code: str | None
    destination_city_code: str | None
    destination_city_name: str | None = None
    destination_district_code: str | None
    origin_region_id_cache: int | None
    destination_region_id_cache: int | None
    publisher_org_name: str | None
    contact_name: str | None
    contact_phone: str | None
    contact_wechat: str | None
    confidence_score: Decimal | None
    match_basis_json: dict[str, Any] | None
    status_code: str
    status_name: str | None = None
    confirmed_freight_id: int | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FreightAiParseTaskResponse(BaseModel):
    id: int
    task_no: str
    source_inbound_id: int | None
    source_type_code: str
    source_type_name: str | None = None
    source_channel_code: str
    source_channel_name: str | None = None
    raw_content: str
    status_code: str
    status_name: str | None = None
    ai_provider_code: str | None
    ai_model: str | None
    prompt_version: str | None
    requested_by: int | None
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    raw_response_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class FreightAiParseTaskDetailResponse(BaseModel):
    task: FreightAiParseTaskResponse
    source_inbound: FreightSourceInboundResponse | None = None
    clues: list[FreightClueResponse] = Field(default_factory=list)
    candidates: list[FreightCandidateResponse] = Field(default_factory=list)
    feedback: list[FreightConfirmationResponse] = Field(default_factory=list)
