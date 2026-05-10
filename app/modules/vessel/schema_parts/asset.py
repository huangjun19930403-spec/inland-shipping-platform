"""Vessel asset schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.modules.vessel.schema_parts.base import *  # noqa: F401,F403
from app.modules.vessel.schema_parts.recognition import *  # noqa: F401,F403
from app.modules.vessel.schema_parts.relation import *  # noqa: F401,F403


class VesselAssetListQuery(VesselListQuery):
    quality_level: str | None = None
    risk_level: str | None = None
    ais_freshness_level: str | None = None
    freshness_level: str | None = None
    analysis_sample_tag: str | None = None
    sample_tag: str | None = None
    summary_status_code: str | None = None
    source_layer: str | None = None
    region_code: str | None = None
    sort: str | None = None

class VesselCreateRequest(StrictBaseModel):
    mmsi: str = Field(validation_alias=AliasChoices("mmsi", "current_mmsi"), min_length=9, max_length=9)
    ship_name: str = Field(min_length=1, max_length=128)
    source_type_code: str = Field(default="MANUAL", min_length=1, max_length=64)

    @field_validator("mmsi")
    @classmethod
    def validate_mmsi(cls, value: str) -> str:
        cleaned = _validate_mmsi(value)
        assert cleaned is not None
        return cleaned

class VesselProfileUpdateRequest(StrictBaseModel):
    ship_name: str | None = Field(default=None, min_length=1, max_length=128)
    ship_name_en: str | None = Field(default=None, max_length=256)
    current_mmsi: str | None = Field(default=None, max_length=16)
    ship_type_code: str | None = Field(default=None, max_length=64)
    profile_status_code: str | None = Field(default=None, max_length=64)
    identity_status_code: str | None = Field(default=None, max_length=64)
    operation_status_code: str | None = Field(default=None, max_length=64)
    home_port_code: str | None = Field(default=None, max_length=12)
    home_port_name: str | None = Field(default=None, max_length=128)
    registry_city_code: str | None = Field(default=None, max_length=12)
    business_region_id: int | None = None
    source_type_code: str | None = Field(default=None, max_length=64)
    remark: str | None = Field(default=None, max_length=512)

    @field_validator("current_mmsi")
    @classmethod
    def validate_current_mmsi(cls, value: str | None) -> str | None:
        return _validate_mmsi(value)

class VesselRegistrationUpsertRequest(StrictBaseModel):
    registry_city_code: str | None = Field(default=None, max_length=12)
    ship_registry_no: str | None = Field(default=None, max_length=64)
    home_port_code: str | None = Field(default=None, max_length=12)
    home_port_name: str | None = Field(default=None, max_length=128)
    flag_code: str | None = Field(default=None, max_length=32)
    mmsi_issuing_authority: str | None = Field(default=None, max_length=128)
    inspection_org: str | None = Field(default=None, max_length=128)
    remark: str | None = Field(default=None, max_length=512)

class VesselCapacityUpsertRequest(StrictBaseModel):
    deadweight_ton: Decimal | None = None
    reference_load_ton: Decimal | None = None
    total_tonnage: Decimal | None = None
    net_tonnage: Decimal | None = None
    length_m: Decimal | None = None
    width_m: Decimal | None = None
    depth_m: Decimal | None = None
    design_draft_m: Decimal | None = None
    max_draft_m: Decimal | None = None
    design_speed_kn: Decimal | None = None
    hold_count: int | None = Field(default=None, ge=0)
    teu_capacity: int | None = Field(default=None, ge=0)
    capacity_remark: str | None = Field(default=None, max_length=512)

class VesselBuildInfoUpsertRequest(StrictBaseModel):
    building_year: int | None = Field(default=None, ge=1800, le=2100)
    builder_name: str | None = Field(default=None, max_length=128)
    build_place: str | None = Field(default=None, max_length=128)
    hull_material_code: str | None = Field(default=None, max_length=64)
    engine_power_kw: Decimal | None = None
    remark: str | None = Field(default=None, max_length=512)

class VesselPersonCertificateItem(StrictBaseModel):
    crew_assignment_id: int | None = None
    holder_name: str = Field(default="待补录", min_length=1, max_length=64)
    certificate_type_code: str = Field(default="CREW_COMPETENCY_CERT", min_length=1, max_length=64)
    certificate_no: str | None = Field(default=None, max_length=128)
    valid_from: date | None = None
    valid_to: date | None = None
    is_long_term_valid: bool = False
    validity_text_raw: str | None = Field(default=None, max_length=256)
    verify_status_code: str = Field(default="PENDING", min_length=1, max_length=64)
    structured_payload_json: dict[str, Any] | None = None
    source_type_code: str = Field(default="MANUAL", max_length=64)
    source_trace_id: str | None = Field(default=None, max_length=128)
    remark: str | None = Field(default=None, max_length=512)

class VesselPersonCertificateReplaceRequest(StrictBaseModel):
    person_certificates: list[VesselPersonCertificateItem] = Field(default_factory=list)

class VesselPersonCertificateUpdateRequest(VesselPersonCertificateItem):
    revision: int | None = Field(default=None, ge=1)
    holder_name: str | None = Field(default=None, min_length=1, max_length=64)
    certificate_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    verify_status_code: str | None = Field(default=None, min_length=1, max_length=64)
    source_type_code: str | None = Field(default=None, max_length=64)

class VesselCertificateCreateRequest(StrictBaseModel):
    certificate_type_code: str = Field(default="UNKNOWN", min_length=1, max_length=64)
    certificate_no: str | None = Field(default=None, max_length=128)
    issuing_authority: str | None = Field(default=None, max_length=128)
    valid_from: date | None = None
    valid_to: date | None = None
    is_long_term_valid: bool = False
    validity_text_raw: str | None = Field(default=None, max_length=256)
    verify_status_code: str = Field(default="PENDING", min_length=1, max_length=64)
    structured_payload_json: dict[str, Any] | None = None
    remark: str | None = Field(default=None, max_length=512)

class VesselCertificateUpdateRequest(StrictBaseModel):
    certificate_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    certificate_no: str | None = Field(default=None, max_length=128)
    issuing_authority: str | None = Field(default=None, max_length=128)
    valid_from: date | None = None
    valid_to: date | None = None
    is_long_term_valid: bool | None = None
    validity_text_raw: str | None = Field(default=None, max_length=256)
    verify_status_code: str | None = Field(default=None, min_length=1, max_length=64)
    structured_payload_json: dict[str, Any] | None = None
    remark: str | None = Field(default=None, max_length=512)

class VesselCertificateFileUploadRequest(BaseModel):
    certificate_type_code: str = Field(default="UNKNOWN", max_length=64)

class VesselProfileResponse(BaseModel):
    id: int
    vessel_profile_code: str
    vessel_identity_id: int | None
    ship_name: str
    ship_name_en: str | None
    current_mmsi: str
    ship_type_code: str | None
    ship_type_name: str | None = None
    profile_status_code: str
    profile_status_name: str | None = None
    identity_status_code: str
    identity_status_name: str | None = None
    operation_status_code: str | None
    operation_status_name: str | None = None
    home_port_code: str | None
    home_port_name: str | None
    registry_city_code: str | None
    registry_city_name: str | None = None
    business_region_id: int | None
    business_region_name: str | None = None
    source_type_code: str
    source_type_name: str | None = None
    audit_status: str
    audit_status_name: str | None = None
    remark: str | None
    created_at: datetime
    updated_at: datetime

class VesselCapacityResponse(BaseModel):
    id: int
    vessel_profile_id: int
    deadweight_ton: Decimal | None
    reference_load_ton: Decimal | None
    total_tonnage: Decimal | None
    net_tonnage: Decimal | None
    length_m: Decimal | None
    width_m: Decimal | None
    depth_m: Decimal | None
    design_draft_m: Decimal | None
    max_draft_m: Decimal | None
    design_speed_kn: Decimal | None
    hold_count: int | None
    teu_capacity: int | None
    capacity_remark: str | None
    updated_at: datetime

class VesselRegistrationResponse(BaseModel):
    id: int
    vessel_profile_id: int
    registry_city_code: str | None
    ship_registry_no: str | None
    home_port_code: str | None
    home_port_name: str | None
    flag_code: str | None
    mmsi_issuing_authority: str | None
    inspection_org: str | None
    remark: str | None
    updated_at: datetime

class VesselBuildInfoResponse(BaseModel):
    id: int
    vessel_profile_id: int
    building_year: int | None
    builder_name: str | None
    build_place: str | None
    hull_material_code: str | None
    engine_power_kw: Decimal | None
    remark: str | None
    updated_at: datetime

class VesselCertificateFileResponse(BaseModel):
    id: int
    vessel_certificate_id: int
    storage_file_id: int
    file_name: str
    content_type: str
    file_size: int
    uploaded_by: int | None
    uploaded_at: datetime
    created_at: datetime
    voided_at: datetime | None = None
    voided_by: int | None = None
    void_reason: str | None = None
    download_url: str | None = None

class VesselPersonCertificateFileResponse(BaseModel):
    id: int
    vessel_person_certificate_id: int
    storage_file_id: int
    file_name: str
    content_type: str
    file_size: int
    uploaded_by: int | None
    uploaded_at: datetime
    created_at: datetime
    voided_at: datetime | None = None
    voided_by: int | None = None
    void_reason: str | None = None
    download_url: str | None = None

class VesselPersonCertificateResponse(VesselPersonCertificateItem):
    id: int
    vessel_profile_id: int
    certificate_type_name: str | None = None
    verify_status_name: str | None = None
    revision: int = 1
    source_type_name: str | None = None
    change_event_id: int | None = None
    files: list[VesselPersonCertificateFileResponse] = Field(default_factory=list)
    latest_image_recognition: VesselPersonCertificateImageRecognitionResponse | None = None
    current_image_recognition: VesselPersonCertificateImageRecognitionResponse | None = None
    latest_confirmed_image_recognition: VesselPersonCertificateImageRecognitionResponse | None = None
    has_recognition_history: bool = False
    created_at: datetime
    updated_at: datetime
    voided_at: datetime | None = None
    voided_by: int | None = None
    void_reason: str | None = None

class VesselCertificateResponse(BaseModel):
    id: int
    vessel_profile_id: int
    certificate_type_code: str
    certificate_no: str | None
    issuing_authority: str | None
    valid_from: date | None
    valid_to: date | None
    is_long_term_valid: bool
    validity_text_raw: str | None
    verify_status_code: str
    certificate_type_name: str | None = None
    verify_status_name: str | None = None
    recognition_status_code: str = "NOT_STARTED"
    recognition_status_name: str | None = None
    confirmation_status_code: str = "UNCONFIRMED"
    confirmation_status_name: str | None = None
    structured_payload_json: dict[str, Any] | None
    remark: str | None
    files: list[VesselCertificateFileResponse] = Field(default_factory=list)
    latest_image_recognition: VesselCertificateImageRecognitionResponse | None = None
    current_image_recognition: VesselCertificateImageRecognitionResponse | None = None
    latest_confirmed_image_recognition: VesselCertificateImageRecognitionResponse | None = None
    has_recognition_history: bool = False
    created_at: datetime
    updated_at: datetime
    voided_at: datetime | None = None
    voided_by: int | None = None
    void_reason: str | None = None

class VesselCertificateLedgerItemResponse(BaseModel):
    certificate_type_code: str
    certificate_type_name: str | None = None
    required: bool = True
    status_code: str
    status_name: str
    certificate: VesselCertificateResponse | None = None

class VesselNameHistoryResponse(BaseModel):
    id: int
    vessel_profile_id: int
    ship_name: str
    start_date: date | None
    end_date: date | None
    source_type_code: str
    source_type_name: str | None = None
    created_at: datetime

class VesselIdentifierHistoryResponse(BaseModel):
    id: int
    vessel_profile_id: int
    identifier_type_code: str
    identifier_value: str
    start_date: date | None
    end_date: date | None
    source_type_code: str
    source_type_name: str | None = None
    source_trace_id: str | None = None
    status_code: str = "ACTIVE"
    confidence_score: int = 100
    created_at: datetime

class VesselChangeEventResponse(BaseModel):
    id: int
    vessel_profile_id: int
    event_type_code: str
    event_type_name: str | None = None
    event_title: str
    object_type: str | None = None
    object_id: str | None = None
    before_json: dict[str, Any] | None
    after_json: dict[str, Any] | None
    changed_fields_json: list[Any] | None = None
    reason: str | None = None
    operator_id: int | None
    created_at: datetime

class VesselListItemResponse(VesselProfileResponse):
    building_year: int | None = None
    ship_age: int | None = None
    deadweight_ton: Decimal | None = None
    length_m: Decimal | None = None
    width_m: Decimal | None = None
    design_draft_m: Decimal | None = None
    size_text: str | None = None
    primary_owner_name: str | None = None
    primary_operator_name: str | None = None
    primary_contact_name: str | None = None
    primary_contact_phone: str | None = None
    contact_available: bool | None = None

class VesselAssetListItemResponse(VesselListItemResponse):
    profile_completeness_rate: Decimal | None = None
    data_quality_score: Decimal | None = None
    data_quality_level: str = "UNKNOWN"
    identity_confidence_level: str = "UNKNOWN"
    contact_trust_level: str = "UNKNOWN"
    subject_consistency_level: str = "UNKNOWN"
    quality_level: str = "UNKNOWN"
    risk_level: str = "UNKNOWN"
    ais_freshness_level: str = "UNKNOWN"
    quality_issue_count: int = 0
    missing_field_count: int = 0
    conflict_count: int = 0
    certificate_missing_count: int = 0
    certificate_expiring_count: int = 0
    certificate_expired_count: int = 0
    latest_position_time: datetime | None = None
    latest_city_code: str | None = None
    latest_city_name: str | None = None
    analysis_sample_tags: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    risk_evidence_summary: list[Any] = Field(default_factory=list)
    summary_status_code: str = "MISSING"
    summary_status_name: str | None = None
    summary_version: str | None = None
    source_layer: str | None = None
    coverage_rate: Decimal | None = None
    refreshed_at: datetime | None = None
    source_updated_at: datetime | None = None
    refresh_error: str | None = None
    evidence_updated_at: datetime | None = None
    explain_reason: str | None = None
    next_actions: list[VesselRecommendedAction] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    source_object_anchor: str | None = None
    workbench_group: str | None = None

class VesselSummaryRefreshBatchRequest(StrictBaseModel):
    vessel_ids: list[int] = Field(default_factory=list, min_length=1, max_length=100)

class VesselSummaryRefreshDiffResponse(BaseModel):
    field_name: str
    before: str | None = None
    after: str | None = None
    message: str | None = None

class VesselSummaryRefreshBatchItemResponse(BaseModel):
    vessel_id: int
    ship_name: str | None = None
    success: bool
    summary_diff: list[VesselSummaryRefreshDiffResponse] = Field(default_factory=list)
    refresh_failure_reason: str | None = None
    item: VesselAssetListItemResponse | None = None

class VesselSummaryRefreshBatchResponse(BaseModel):
    total: int
    success_count: int
    failed_count: int
    items: list[VesselSummaryRefreshBatchItemResponse] = Field(default_factory=list)

class VesselAssetDistributionItemResponse(BaseModel):
    code: str
    name: str | None = None
    count: int

class VesselAssetSummaryResponse(BaseModel):
    total_profiles: int
    summarized_count: int
    missing_summary_count: int
    failed_summary_count: int
    stale_summary_count: int
    coverage_rate: Decimal
    confidence_level: str
    generated_at: datetime
    quality_distribution: list[VesselAssetDistributionItemResponse] = Field(default_factory=list)
    risk_distribution: list[VesselAssetDistributionItemResponse] = Field(default_factory=list)
    ais_freshness_distribution: list[VesselAssetDistributionItemResponse] = Field(default_factory=list)
    summary_status_distribution: list[VesselAssetDistributionItemResponse] = Field(default_factory=list)

class VesselAssetPageResponse(PageResponse[VesselAssetListItemResponse]):
    coverage_rate: Decimal
    confidence_level: str
    generated_at: datetime
    summary_status_counts: dict[str, int] = Field(default_factory=dict)
    summarized_count: int = 0
    missing_summary_count: int = 0
    failed_summary_count: int = 0
    stale_summary_count: int = 0
    source_updated_at: datetime | None = None
    uncertainty_reasons: list[str] = Field(default_factory=list)

class VesselDetailResponse(BaseModel):
    profile: VesselProfileResponse
    registration: VesselRegistrationResponse | None = None
    capacity: VesselCapacityResponse | None = None
    build_info: VesselBuildInfoResponse | None = None
    owners: list[VesselOwnerResponse] = Field(default_factory=list)
    operators: list[VesselOperatorResponse] = Field(default_factory=list)
    contacts: list[VesselContactResponse] = Field(default_factory=list)
    crew: list[VesselCrewResponse] = Field(default_factory=list)
    person_certificates: list[VesselPersonCertificateResponse] = Field(default_factory=list)
    certificates: list[VesselCertificateResponse] = Field(default_factory=list)
    name_history: list[VesselNameHistoryResponse] = Field(default_factory=list)
    identifier_history: list[VesselIdentifierHistoryResponse] = Field(default_factory=list)
    change_events: list[VesselChangeEventResponse] = Field(default_factory=list)
