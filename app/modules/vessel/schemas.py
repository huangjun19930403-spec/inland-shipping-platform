"""vessel 模块 schema。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

T = TypeVar("T")


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PageResponse(BaseModel, Generic[T]):
    total: int
    page: int
    page_size: int
    items: list[T]


def _validate_mmsi(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if len(cleaned) != 9 or not cleaned.isdigit():
        raise ValueError("MMSI 必须为 9 位数字")
    return cleaned


class VesselListQuery(BaseModel):
    keyword: str | None = None
    mmsi: str | None = None
    ship_name: str | None = None
    ship_type_code: str | None = None
    profile_status_code: str | None = None
    city_code: str | None = None
    registry_city_code: str | None = None
    business_region_id: int | None = None
    deadweight_min: Decimal | None = None
    deadweight_max: Decimal | None = None
    ship_age_min: int | None = Field(default=None, ge=0, le=200)
    ship_age_max: int | None = Field(default=None, ge=0, le=200)
    length_min: Decimal | None = None
    length_max: Decimal | None = None
    draft_min: Decimal | None = None
    draft_max: Decimal | None = None
    owner_name: str | None = None
    operator_name: str | None = None
    certificate_risk: str | None = None
    contact_available: bool | None = None
    updated_from: datetime | None = None
    updated_to: datetime | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class VesselPositionMonitorQuery(BaseModel):
    keyword: str | None = None
    ship_type_code: str | None = None
    deadweight_min: Decimal | None = None
    deadweight_max: Decimal | None = None
    draft_max: Decimal | None = None
    contact_available: bool | None = None
    profile_status_code: str | None = None
    certificate_risk: str | None = None
    reported_within_minutes: int | None = Field(default=1440, ge=5, le=43200)
    max_items: int = Field(default=200, ge=1, le=500)


class VesselCreateRequest(StrictBaseModel):
    mmsi: str = Field(validation_alias=AliasChoices("mmsi", "current_mmsi"), min_length=9, max_length=9)
    ship_name: str = Field(min_length=1, max_length=128)

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


class VesselOwnerItem(StrictBaseModel):
    party_name: str = Field(min_length=1, max_length=128)
    party_type_code: str = Field(default="UNKNOWN", min_length=1, max_length=64)
    certificate_no: str | None = Field(default=None, max_length=64)
    mobile_phone: str | None = Field(default=None, max_length=32)
    landline_phone: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=256)
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = True
    is_primary: bool = True


class VesselOwnerReplaceRequest(StrictBaseModel):
    owners: list[VesselOwnerItem] = Field(default_factory=list)


class VesselOperatorItem(StrictBaseModel):
    operator_name: str = Field(min_length=1, max_length=128)
    party_type_code: str = Field(default="UNKNOWN", min_length=1, max_length=64)
    contact_phone: str | None = Field(default=None, max_length=32)
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = True
    is_primary: bool = True


class VesselOperatorReplaceRequest(StrictBaseModel):
    operators: list[VesselOperatorItem] = Field(default_factory=list)


class VesselContactItem(StrictBaseModel):
    contact_name: str = Field(min_length=1, max_length=64)
    contact_role_code: str = Field(min_length=1, max_length=64)
    mobile_phone: str | None = Field(default=None, max_length=32)
    wechat: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=128)
    is_primary: bool = False
    is_available: bool = True
    last_verified_at: datetime | None = None
    remark: str | None = Field(default=None, max_length=512)


class VesselContactReplaceRequest(StrictBaseModel):
    contacts: list[VesselContactItem] = Field(default_factory=list)


class VesselCrewItem(StrictBaseModel):
    crew_name: str = Field(min_length=1, max_length=64)
    crew_role_code: str = Field(min_length=1, max_length=64)
    certificate_no: str | None = Field(default=None, max_length=64)
    mobile_phone: str | None = Field(default=None, max_length=32)
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = True


class VesselCrewReplaceRequest(StrictBaseModel):
    crew: list[VesselCrewItem] = Field(default_factory=list)


class VesselPersonCertificateItem(StrictBaseModel):
    crew_assignment_id: int | None = None
    holder_name: str = Field(default="待补录", min_length=1, max_length=64)
    certificate_type_code: str = Field(default="CREW_LICENSE", min_length=1, max_length=64)
    certificate_no: str | None = Field(default=None, max_length=128)
    valid_from: date | None = None
    valid_to: date | None = None
    is_long_term_valid: bool = False
    validity_text_raw: str | None = Field(default=None, max_length=256)
    verify_status_code: str = Field(default="PENDING", min_length=1, max_length=64)
    structured_payload_json: dict[str, Any] | None = None
    remark: str | None = Field(default=None, max_length=512)


class VesselPersonCertificateReplaceRequest(StrictBaseModel):
    person_certificates: list[VesselPersonCertificateItem] = Field(default_factory=list)


class VesselPersonCertificateUpdateRequest(VesselPersonCertificateItem):
    holder_name: str | None = Field(default=None, min_length=1, max_length=64)
    certificate_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    verify_status_code: str | None = Field(default=None, min_length=1, max_length=64)


class VesselPersonCertificateImageRecognitionCreateRequest(StrictBaseModel):
    file_id: int = Field(gt=0)


class VesselPersonCertificateImageRecognitionConfirmRequest(StrictBaseModel):
    accepted_payload_json: dict[str, Any] | None = None


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


class VesselCertificateImageRecognitionCreateRequest(StrictBaseModel):
    file_id: int = Field(gt=0, description="已上传证件附件对应的 storage_file_id")


class VesselCertificateImageRecognitionConfirmRequest(StrictBaseModel):
    accepted_payload_json: dict[str, Any] | None = None
    adopt_to_profile_fields: list[str] = Field(default_factory=list)


class VesselOwnerTransferRequest(StrictBaseModel):
    new_owner_name: str = Field(min_length=1, max_length=128)
    party_type_code: str = Field(default="UNKNOWN", min_length=1, max_length=64)
    transfer_date: date | None = None
    certificate_no: str | None = Field(default=None, max_length=64)
    mobile_phone: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=256)
    remark: str | None = Field(default=None, max_length=512)


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


class VesselOwnerResponse(VesselOwnerItem):
    id: int
    vessel_profile_id: int
    party_type_name: str | None = None
    created_at: datetime
    updated_at: datetime


class VesselOperatorResponse(VesselOperatorItem):
    id: int
    vessel_profile_id: int
    party_type_name: str | None = None
    created_at: datetime
    updated_at: datetime


class VesselContactResponse(VesselContactItem):
    id: int
    vessel_profile_id: int
    contact_role_name: str | None = None
    created_at: datetime
    updated_at: datetime


class VesselCrewResponse(VesselCrewItem):
    id: int
    vessel_profile_id: int
    crew_role_name: str | None = None
    created_at: datetime
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
    download_url: str | None = None


class VesselCertificateImageRecognitionResponse(BaseModel):
    id: int
    vessel_profile_id: int
    vessel_certificate_id: int
    certificate_file_id: int
    storage_file_id: int
    status_code: str
    status_name: str | None = None
    provider_code: str | None
    model_name: str | None
    candidate_payload_json: dict[str, Any] | None
    confirmed_payload_json: dict[str, Any] | None
    raw_text: str | None
    raw_response_json: dict[str, Any] | None
    confidence_score: int | None
    error_message: str | None
    created_by: int | None
    confirmed_by: int | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class VesselPersonCertificateImageRecognitionResponse(BaseModel):
    id: int
    vessel_profile_id: int
    vessel_person_certificate_id: int
    person_certificate_file_id: int
    storage_file_id: int
    status_code: str
    status_name: str | None = None
    provider_code: str | None
    model_name: str | None
    candidate_payload_json: dict[str, Any] | None
    confirmed_payload_json: dict[str, Any] | None
    raw_text: str | None
    raw_response_json: dict[str, Any] | None
    confidence_score: int | None
    error_message: str | None
    created_by: int | None
    confirmed_by: int | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class VesselPersonCertificateResponse(VesselPersonCertificateItem):
    id: int
    vessel_profile_id: int
    certificate_type_name: str | None = None
    verify_status_name: str | None = None
    files: list[VesselPersonCertificateFileResponse] = Field(default_factory=list)
    latest_image_recognition: VesselPersonCertificateImageRecognitionResponse | None = None
    created_at: datetime
    updated_at: datetime


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
    created_at: datetime
    updated_at: datetime


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
    created_at: datetime


class VesselChangeEventResponse(BaseModel):
    id: int
    vessel_profile_id: int
    event_type_code: str
    event_type_name: str | None = None
    event_title: str
    before_json: dict[str, Any] | None
    after_json: dict[str, Any] | None
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
    certificate_risk: str | None = None
    certificate_risk_name: str | None = None


class VesselPositionMonitorItemResponse(VesselListItemResponse):
    longitude: Decimal
    latitude: Decimal
    speed_kn: Decimal | None = None
    course_deg: Decimal | None = None
    heading_deg: Decimal | None = None
    position_time: datetime | None = None
    position_age_minutes: int | None = None
    location_text: str | None = None
    position_source_code: str = "ES_REALTIME"
    position_source_name: str | None = None


class VesselPositionMonitorSummary(BaseModel):
    matched_profile_count: int
    positioned_count: int
    stale_position_count: int
    contactable_position_count: int
    risk_position_count: int


class VesselPositionMonitorResponse(BaseModel):
    source_status: str
    source_status_name: str
    generated_at: datetime
    message: str | None = None
    summary: VesselPositionMonitorSummary
    items: list[VesselPositionMonitorItemResponse] = Field(default_factory=list)


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
