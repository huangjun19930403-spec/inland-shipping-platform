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


class FreightBasePayload(BaseModel):
    raw_commodity_name: str | None = Field(default=None, max_length=128)
    raw_tonnage_text: str | None = Field(default=None, max_length=128)
    raw_origin_text: str | None = Field(default=None, max_length=256)
    raw_destination_text: str | None = Field(default=None, max_length=256)
    cargo_title: str = Field(min_length=1, max_length=256)
    cargo_description: str | None = Field(default=None, max_length=1024)
    commodity_standard_id: int | None = None
    commodity_match_level_code: str | None = Field(default=None, max_length=64)
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
    origin_match_level_code: str | None = Field(default=None, max_length=64)
    destination_match_level_code: str | None = Field(default=None, max_length=64)
    origin_province_code: str | None = Field(default=None, max_length=12)
    origin_city_code: str | None = Field(default=None, max_length=12)
    origin_district_code: str | None = Field(default=None, max_length=12)
    destination_province_code: str | None = Field(default=None, max_length=12)
    destination_city_code: str | None = Field(default=None, max_length=12)
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


class FreightManualCreateRequest(FreightBasePayload):
    freight_no: str | None = Field(default=None, max_length=32)
    source_ref_no: str | None = Field(default=None, max_length=128)
    status_code: str = Field(default="PUBLISHED", min_length=1, max_length=64)
    hall_status_code: str = Field(default="NOT_LISTED", min_length=1, max_length=64)
    hall_visible_until: datetime | None = None


class FreightUpdateRequest(BaseModel):
    source_ref_no: str | None = Field(default=None, max_length=128)
    raw_commodity_name: str | None = Field(default=None, max_length=128)
    raw_tonnage_text: str | None = Field(default=None, max_length=128)
    raw_origin_text: str | None = Field(default=None, max_length=256)
    raw_destination_text: str | None = Field(default=None, max_length=256)
    cargo_title: str | None = Field(default=None, min_length=1, max_length=256)
    cargo_description: str | None = Field(default=None, max_length=1024)
    commodity_standard_id: int | None = None
    commodity_match_level_code: str | None = Field(default=None, max_length=64)
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
    origin_match_level_code: str | None = Field(default=None, max_length=64)
    destination_match_level_code: str | None = Field(default=None, max_length=64)
    origin_province_code: str | None = Field(default=None, max_length=12)
    origin_city_code: str | None = Field(default=None, max_length=12)
    origin_district_code: str | None = Field(default=None, max_length=12)
    destination_province_code: str | None = Field(default=None, max_length=12)
    destination_city_code: str | None = Field(default=None, max_length=12)
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
    hall_status_code: str | None = Field(default=None, max_length=64)
    hall_visible_until: datetime | None = None


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
    source_batch_id: int | None = None
    source_tms_inbound_id: int | None = None
    source_clue_id: int | None = None
    source_candidate_id: int | None = None
    raw_commodity_name: str | None = None
    raw_tonnage_text: str | None = None
    raw_origin_text: str | None = None
    raw_destination_text: str | None = None
    cargo_title: str
    cargo_description: str | None
    commodity_standard_id: int | None
    commodity_standard_code: str | None = None
    commodity_standard_name: str | None = None
    commodity_match_level_code: str | None = None
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
    origin_match_level_code: str | None = None
    destination_match_level_code: str | None = None
    origin_province_code: str | None
    origin_city_code: str | None
    origin_city_name: str | None = None
    origin_district_code: str | None
    destination_province_code: str | None
    destination_city_code: str | None
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
    hall_status_code: str
    hall_status_name: str | None = None
    hall_published_at: datetime | None = None
    hall_unpublished_at: datetime | None = None
    hall_visible_until: datetime | None = None
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


class FreightClueResponse(BaseModel):
    id: int
    clue_no: str
    source_type_code: str
    source_channel_code: str
    source_batch_id: int | None
    source_tms_inbound_id: int | None
    segment_index: int
    raw_text: str
    context_summary: str | None
    extracted_fields_json: dict[str, Any] | None
    quality_score: Decimal | None
    status_code: str
    status_name: str | None = None
    created_at: datetime
    updated_at: datetime


class FreightBatchCreateRequest(BaseModel):
    batch_no: str | None = Field(default=None, max_length=32)
    raw_text: str = Field(min_length=1)
    remark: str | None = Field(default=None, max_length=512)


class FreightBatchListQuery(BaseModel):
    keyword: str | None = None
    status_code: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class FreightBatchResponse(BaseModel):
    id: int
    batch_no: str
    source_type_code: str
    source_type_name: str | None = None
    source_channel_code: str
    source_channel_name: str | None = None
    raw_text: str
    status_code: str
    status_name: str | None = None
    review_flow_status_code: str = "REVIEWING"
    review_flow_status_name: str | None = None
    clue_count: int
    candidate_count: int
    success_count: int
    failed_count: int
    pending_count: int = 0
    confirmed_count: int = 0
    rejected_count: int = 0
    ready_count: int = 0
    review_count: int = 0
    route_summary: str | None = None
    contact_summary: str | None = None
    creator_id: int | None
    remark: str | None
    error_message: str | None
    prompt_version: str | None
    parse_stage_code: str | None = None
    parse_stage_name: str | None = None
    parse_stage_message: str | None = None
    parse_progress_percent: int = 0
    parse_heartbeat_at: datetime | None = None
    parse_is_stale: bool = False
    parse_heartbeat_age_seconds: int | None = None
    next_action_code: str | None = None
    next_action_name: str | None = None
    ai_elapsed_seconds: int = 0
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FreightBatchDetailResponse(BaseModel):
    batch: FreightBatchResponse
    clues: list[FreightClueResponse] = Field(default_factory=list)
    candidates: list["FreightCandidateResponse"] = Field(default_factory=list)


class FreightTmsInboundCreateRequest(BaseModel):
    inbound_no: str | None = Field(default=None, max_length=32)
    source_channel_code: str = Field(default="TMS_API", max_length=64)
    source_trace_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=256)
    external_ref_no: str | None = Field(default=None, max_length=128)
    payload_json: dict[str, Any]
    raw_content: str | None = None


class FreightTmsInboundListQuery(BaseModel):
    keyword: str | None = None
    status_code: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class FreightTmsInboundResponse(BaseModel):
    id: int
    inbound_no: str
    source_type_code: str
    source_type_name: str | None = None
    source_channel_code: str
    source_channel_name: str | None = None
    source_trace_id: str | None
    idempotency_key: str
    external_ref_no: str | None
    payload_json: dict[str, Any]
    raw_content: str
    status_code: str
    status_name: str | None = None
    clue_count: int
    candidate_count: int
    processed_at: datetime | None
    error_message: str | None
    prompt_version: str | None
    created_at: datetime
    updated_at: datetime


class FreightTmsInboundDetailResponse(BaseModel):
    inbound: FreightTmsInboundResponse
    clues: list[FreightClueResponse] = Field(default_factory=list)
    candidates: list["FreightCandidateResponse"] = Field(default_factory=list)


class FreightCandidateUpdateRequest(BaseModel):
    raw_commodity_name: str | None = Field(default=None, max_length=128)
    raw_tonnage_text: str | None = Field(default=None, max_length=128)
    raw_origin_text: str | None = Field(default=None, max_length=256)
    raw_destination_text: str | None = Field(default=None, max_length=256)
    cargo_title: str | None = Field(default=None, min_length=1, max_length=256)
    cargo_description: str | None = Field(default=None, max_length=1024)
    commodity_standard_id: int | None = None
    commodity_match_level_code: str | None = Field(default=None, max_length=64)
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
    origin_match_level_code: str | None = Field(default=None, max_length=64)
    destination_match_level_code: str | None = Field(default=None, max_length=64)
    publisher_org_name: str | None = Field(default=None, max_length=128)
    contact_name: str | None = Field(default=None, max_length=64)
    contact_phone: str | None = Field(default=None, max_length=32)
    contact_wechat: str | None = Field(default=None, max_length=64)
    availability_status_code: str | None = Field(default=None, max_length=64)
    manual_review_reason: str | None = Field(default=None, max_length=512)


class FreightCandidateConfirmRequest(BaseModel):
    remark: str | None = Field(default=None, max_length=512)
    overrides: FreightCandidateUpdateRequest | None = None


class FreightCandidateRejectRequest(BaseModel):
    remark: str = Field(min_length=1, max_length=512)


class FreightCandidateResponse(BaseModel):
    id: int
    candidate_no: str
    source_type_code: str
    source_type_name: str | None = None
    source_channel_code: str
    source_channel_name: str | None = None
    source_batch_id: int | None
    source_tms_inbound_id: int | None
    clue_id: int | None
    source_ref_no: str | None
    raw_text: str | None
    raw_commodity_name: str | None
    raw_tonnage_text: str | None = None
    raw_origin_text: str | None
    raw_destination_text: str | None
    cargo_title: str
    cargo_description: str | None
    commodity_standard_id: int | None
    commodity_standard_name: str | None = None
    commodity_match_name: str | None
    commodity_match_score: Decimal | None
    commodity_match_level_code: str | None
    commodity_options_json: list[dict[str, Any]] | None = None
    packaging_form_code: str | None
    estimated_tonnage: Decimal | None
    min_tonnage: Decimal | None
    max_tonnage: Decimal | None
    unit_price: Decimal | None
    total_price: Decimal | None
    price_unit: str | None
    settlement_method_code: str | None
    origin_node_id: int | None
    origin_node_name: str | None = None
    destination_node_id: int | None
    destination_node_name: str | None = None
    origin_node_match_score: Decimal | None
    destination_node_match_score: Decimal | None
    origin_match_level_code: str | None
    destination_match_level_code: str | None
    origin_options_json: list[dict[str, Any]] | None = None
    destination_options_json: list[dict[str, Any]] | None = None
    origin_province_code: str | None
    origin_city_code: str | None
    origin_city_name: str | None = None
    origin_district_code: str | None
    destination_province_code: str | None
    destination_city_code: str | None
    destination_city_name: str | None = None
    destination_district_code: str | None
    origin_region_id_cache: int | None
    origin_region_name: str | None = None
    destination_region_id_cache: int | None
    destination_region_name: str | None = None
    publisher_org_name: str | None
    contact_name: str | None
    contact_phone: str | None
    contact_wechat: str | None
    confidence_score: Decimal | None
    completeness_score: Decimal | None
    match_basis_json: dict[str, Any] | None
    ai_suggestion_json: dict[str, Any] | None
    availability_status_code: str
    availability_status_name: str | None = None
    manual_review_reason: str | None
    ai_warning_json: dict[str, Any] | None
    status_code: str
    status_name: str | None = None
    confirmed_freight_id: int | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


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
    source_batch: FreightBatchResponse | None = None
    source_tms_inbound: FreightTmsInboundResponse | None = None
    source_clue: FreightClueResponse | None = None
    source_candidate: FreightCandidateResponse | None = None
    confirmation_records: list[FreightConfirmationResponse] = Field(default_factory=list)


class FreightCandidateBulkConfirmResponse(BaseModel):
    batch_id: int
    confirmed_count: int
    skipped_count: int
    freight_ids: list[int] = Field(default_factory=list)
    skipped: list[dict[str, Any]] = Field(default_factory=list)


class FreightBatchHandoffResponse(BaseModel):
    batch_id: int
    handoff_count: int
    review_flow_status_code: str
    message: str


class FreightNormalizationSuggestionListQuery(BaseModel):
    keyword: str | None = None
    status_code: str | None = None
    suggestion_type_code: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class FreightNormalizationSuggestionResponse(BaseModel):
    id: int
    freight_id: int
    freight_no: str | None = None
    cargo_title: str | None = None
    suggestion_type_code: str
    raw_text: str | None
    current_level_code: str | None
    suggested_level_code: str
    suggested_node_id: int | None
    suggested_node_name: str | None = None
    suggested_commodity_standard_id: int | None
    suggested_commodity_standard_name: str | None = None
    suggested_province_code: str | None
    suggested_city_code: str | None
    suggested_city_name: str | None = None
    suggested_district_code: str | None
    suggested_region_id: int | None
    suggested_region_name: str | None = None
    confidence_score: Decimal | None
    status_code: str
    auto_apply_flag: bool
    match_basis_json: dict[str, Any] | None
    before_json: dict[str, Any] | None
    after_json: dict[str, Any] | None
    applied_at: datetime | None
    applied_by: int | None
    rejected_at: datetime | None
    rejected_by: int | None
    created_at: datetime
    updated_at: datetime


class FreightNormalizationCleanResponse(BaseModel):
    scanned_count: int
    suggestion_count: int
    auto_applied_count: int
    pending_count: int
    affected_date_from: datetime | None = None
    affected_date_to: datetime | None = None


class FreightNormalizationQualityResponse(BaseModel):
    freight_count: int
    raw_origin_count: int
    raw_destination_count: int
    raw_commodity_count: int
    pending_suggestion_count: int
    auto_applied_suggestion_count: int
