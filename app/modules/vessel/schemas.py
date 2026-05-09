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
    contact_available: bool | None = None
    updated_from: datetime | None = None
    updated_to: datetime | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


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


class VesselPositionMonitorQuery(BaseModel):
    keyword: str | None = None
    ship_type_code: str | None = None
    deadweight_min: Decimal | None = None
    deadweight_max: Decimal | None = None
    draft_max: Decimal | None = None
    contact_available: bool | None = None
    profile_status_code: str | None = None
    reported_within_minutes: int | None = Field(default=1440, ge=5, le=43200)
    max_items: int = Field(default=200, ge=1, le=500)


class VesselAisMonitorQuery(BaseModel):
    keyword: str | None = None
    ship_type_code: str | None = None
    deadweight_min: Decimal | None = None
    deadweight_max: Decimal | None = None
    draft_max: Decimal | None = None
    profile_status_code: str | None = None
    reported_within_minutes: int | None = Field(default=1440, ge=5, le=43200)
    max_items: int = Field(default=200, ge=1, le=500)

    def to_internal_query(self) -> VesselPositionMonitorQuery:
        return VesselPositionMonitorQuery(**self.model_dump(), contact_available=None)


class VesselPositionCitySituationQuery(BaseModel):
    keyword: str | None = None
    ship_type_code: str | None = None
    deadweight_min: Decimal | None = None
    deadweight_max: Decimal | None = None
    draft_max: Decimal | None = None
    contact_available: bool | None = None
    profile_status_code: str | None = None
    reported_within_minutes: int | None = Field(default=1440, ge=5, le=43200)
    include_boundary: bool = True
    boundary_precision: str = Field(default="low", pattern="^(low|medium)$")


class VesselPositionCityVesselsQuery(VesselPositionCitySituationQuery):
    city_code: str | None = None
    city_name: str | None = None
    query_snapshot_id: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class VesselAisCitySituationQuery(BaseModel):
    keyword: str | None = None
    ship_type_code: str | None = None
    deadweight_min: Decimal | None = None
    deadweight_max: Decimal | None = None
    draft_max: Decimal | None = None
    profile_status_code: str | None = None
    reported_within_minutes: int | None = Field(default=1440, ge=5, le=43200)
    include_boundary: bool = True
    boundary_precision: str = Field(default="low", pattern="^(low|medium)$")

    def to_internal_query(self) -> VesselPositionCitySituationQuery:
        return VesselPositionCitySituationQuery(**self.model_dump(), contact_available=None)


class VesselAisCityVesselsQuery(VesselAisCitySituationQuery):
    city_code: str | None = None
    city_name: str | None = None
    query_snapshot_id: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    def to_internal_query(self) -> VesselPositionCityVesselsQuery:
        return VesselPositionCityVesselsQuery(**self.model_dump(), contact_available=None)


class VesselAisCityBoundaryQuery(BaseModel):
    city_code: str | None = None
    city_codes: str | None = None
    precision: str = Field(default="low", pattern="^(low|medium)$")


class VesselAisSnapshotQuery(BaseModel):
    snapshot_id: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class VesselAisNodeSituationQuery(BaseModel):
    node_id: int = Field(ge=1)
    radius_km: Decimal | None = Field(default=None, gt=Decimal("0"), le=Decimal("20"))
    time_window_hours: int = Field(default=24, ge=1, le=168)
    reported_within_minutes: int | None = Field(default=1440, ge=5, le=43200)
    ship_type_code: str | None = None
    deadweight_min: Decimal | None = None
    deadweight_max: Decimal | None = None
    draft_max: Decimal | None = None
    quality_level: str | None = None
    risk_level: str | None = None


class VesselAisNodeVesselsQuery(VesselAisNodeSituationQuery):
    query_snapshot_id: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class VesselAisRouteSituationQuery(BaseModel):
    route_id: int | None = Field(default=None, ge=1)
    line_id: int | None = Field(default=None, ge=1)
    time_window_hours: int = Field(default=24, ge=1, le=168)
    reported_within_minutes: int | None = Field(default=1440, ge=5, le=43200)
    ship_type_code: str | None = None
    deadweight_min: Decimal | None = None
    deadweight_max: Decimal | None = None
    draft_max: Decimal | None = None
    quality_level: str | None = None
    risk_level: str | None = None


class VesselAisRouteSegmentVesselsQuery(BaseModel):
    query_snapshot_id: str | None = None
    segment_id: int = Field(ge=1)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class VesselNavigationConstraintQuery(BaseModel):
    context_type: str = Field(pattern="^(NODE|ROUTE_LINE|ROUTE_SEGMENT)$")
    node_id: int | None = Field(default=None, ge=1)
    line_id: int | None = Field(default=None, ge=1)
    segment_id: int | None = Field(default=None, ge=1)


class VesselCandidateAnalysisTimeWindow(StrictBaseModel):
    start: datetime | None = None
    end: datetime | None = None


class VesselCandidateAnalysisFilters(StrictBaseModel):
    ship_type_codes: list[str] = Field(default_factory=list)
    min_deadweight_ton: Decimal | None = None
    max_deadweight_ton: Decimal | None = None
    max_node_distance_km: Decimal | None = None
    quality_threshold: str | None = None
    risk_threshold: str | None = None


class VesselCandidateAnalysisCreateRequest(StrictBaseModel):
    context_type_code: str = Field(pattern="^(FREIGHT_SAMPLE|FREIGHT_SAMPLE_SET|FREIGHT_CANDIDATE|NODE|ROUTE|REGION|MANUAL)$")
    freight_id: int | None = Field(default=None, ge=1)
    freight_candidate_id: int | None = Field(default=None, ge=1)
    freight_sample_ids: list[int] = Field(default_factory=list)
    origin_node_id: int | None = Field(default=None, ge=1)
    destination_node_id: int | None = Field(default=None, ge=1)
    route_id: int | None = Field(default=None, ge=1)
    line_id: int | None = Field(default=None, ge=1)
    origin_city_code: str | None = None
    destination_city_code: str | None = None
    region_id: int | None = Field(default=None, ge=1)
    cargo_category_code: str | None = None
    tonnage: Decimal | None = None
    time_window: VesselCandidateAnalysisTimeWindow | None = None
    filters: VesselCandidateAnalysisFilters = Field(default_factory=VesselCandidateAnalysisFilters)
    source_ais_snapshot_id: str | None = None
    source_spatial_snapshot_id: str | None = None
    reported_within_minutes: int = Field(default=720, ge=5, le=43200)


class VesselCandidateAnalysisListQuery(BaseModel):
    context_type_code: str | None = None
    status_code: str | None = None
    confidence_level: str | None = None
    source_spatial_snapshot_id: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class VesselCandidateAnalysisAnnotationRequest(StrictBaseModel):
    annotation_type_code: str
    comment: str | None = Field(default=None, max_length=1000)


class VesselRecognitionHistoryQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


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
    address: str | None = Field(default=None, max_length=256)
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = True
    is_primary: bool = True


class VesselRelationUpdateMeta(StrictBaseModel):
    revision: int = Field(ge=1)
    end_date: date | None = None
    reason: str | None = Field(default=None, max_length=500)


class VesselOwnerCreateRequest(VesselOwnerItem):
    verified_status_code: str = Field(default="UNVERIFIED", max_length=32)
    source_type_code: str = Field(default="MANUAL", max_length=64)
    source_trace_id: str | None = Field(default=None, max_length=128)


class VesselOwnerUpdateRequest(StrictBaseModel):
    revision: int = Field(ge=1)
    party_name: str | None = Field(default=None, min_length=1, max_length=128)
    party_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    certificate_no: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=256)
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None
    verified_status_code: str | None = Field(default=None, max_length=32)
    source_type_code: str | None = Field(default=None, max_length=64)
    source_trace_id: str | None = Field(default=None, max_length=128)
    reason: str | None = Field(default=None, max_length=500)


class VesselSetPrimaryRequest(StrictBaseModel):
    revision: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=500)


class VesselOwnerReplaceRequest(StrictBaseModel):
    owners: list[VesselOwnerItem] = Field(default_factory=list)


class VesselOperatorItem(StrictBaseModel):
    operator_name: str = Field(min_length=1, max_length=128)
    party_type_code: str = Field(default="UNKNOWN", min_length=1, max_length=64)
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = True
    is_primary: bool = True


class VesselOperatorCreateRequest(VesselOperatorItem):
    verified_status_code: str = Field(default="UNVERIFIED", max_length=32)
    source_type_code: str = Field(default="MANUAL", max_length=64)
    source_trace_id: str | None = Field(default=None, max_length=128)


class VesselOperatorUpdateRequest(StrictBaseModel):
    revision: int = Field(ge=1)
    operator_name: str | None = Field(default=None, min_length=1, max_length=128)
    party_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None
    verified_status_code: str | None = Field(default=None, max_length=32)
    source_type_code: str | None = Field(default=None, max_length=64)
    source_trace_id: str | None = Field(default=None, max_length=128)
    reason: str | None = Field(default=None, max_length=500)


class VesselOperatorReplaceRequest(StrictBaseModel):
    operators: list[VesselOperatorItem] = Field(default_factory=list)


class VesselContactItem(StrictBaseModel):
    contact_scope_code: str = Field(default="GENERAL", min_length=1, max_length=64)
    owner_period_id: int | None = None
    operator_period_id: int | None = None
    crew_assignment_id: int | None = None
    contact_name: str = Field(min_length=1, max_length=64)
    contact_role_code: str = Field(min_length=1, max_length=64)
    mobile_phone: str | None = Field(default=None, max_length=32)
    wechat: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=128)
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = True
    is_primary: bool = False
    is_available: bool = True
    last_verified_at: datetime | None = None
    remark: str | None = Field(default=None, max_length=512)


class VesselContactCreateRequest(VesselContactItem):
    verified_status_code: str = Field(default="UNVERIFIED", max_length=32)
    source_type_code: str = Field(default="MANUAL", max_length=64)
    source_trace_id: str | None = Field(default=None, max_length=128)


class VesselContactUpdateRequest(StrictBaseModel):
    revision: int = Field(ge=1)
    contact_scope_code: str | None = Field(default=None, min_length=1, max_length=64)
    owner_period_id: int | None = None
    operator_period_id: int | None = None
    crew_assignment_id: int | None = None
    contact_name: str | None = Field(default=None, min_length=1, max_length=64)
    contact_role_code: str | None = Field(default=None, min_length=1, max_length=64)
    mobile_phone: str | None = Field(default=None, max_length=32)
    wechat: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=128)
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None
    is_available: bool | None = None
    last_verified_at: datetime | None = None
    verified_status_code: str | None = Field(default=None, max_length=32)
    source_type_code: str | None = Field(default=None, max_length=64)
    source_trace_id: str | None = Field(default=None, max_length=128)
    remark: str | None = Field(default=None, max_length=512)
    reason: str | None = Field(default=None, max_length=500)


class VesselContactReplaceRequest(StrictBaseModel):
    contacts: list[VesselContactItem] = Field(default_factory=list)


class VesselCrewItem(StrictBaseModel):
    id: int | None = None
    crew_name: str = Field(min_length=1, max_length=64)
    crew_role_code: str = Field(min_length=1, max_length=64)
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = True


class VesselCrewCreateRequest(VesselCrewItem):
    id: int | None = None
    verified_status_code: str = Field(default="UNVERIFIED", max_length=32)
    source_type_code: str = Field(default="MANUAL", max_length=64)
    source_trace_id: str | None = Field(default=None, max_length=128)


class VesselCrewUpdateRequest(StrictBaseModel):
    revision: int = Field(ge=1)
    crew_name: str | None = Field(default=None, min_length=1, max_length=64)
    crew_role_code: str | None = Field(default=None, min_length=1, max_length=64)
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool | None = None
    verified_status_code: str | None = Field(default=None, max_length=32)
    source_type_code: str | None = Field(default=None, max_length=64)
    source_trace_id: str | None = Field(default=None, max_length=128)
    reason: str | None = Field(default=None, max_length=500)


class VesselCrewReplaceRequest(StrictBaseModel):
    crew: list[VesselCrewItem] = Field(default_factory=list)


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


class VesselPersonCertificateImageRecognitionCreateRequest(StrictBaseModel):
    file_id: int = Field(gt=0)


class VesselPersonCertificateImageRecognitionConfirmRequest(StrictBaseModel):
    accepted_payload_json: dict[str, Any] | None = None
    adopt_fields: list[str] | None = None
    reason: str | None = Field(default=None, max_length=500)


class VesselOwnerDocumentImageRecognitionConfirmRequest(StrictBaseModel):
    accepted_payload_json: dict[str, Any] | None = None
    apply_to_owner: bool = True
    adopt_fields: list[str] | None = None
    reason: str | None = Field(default=None, max_length=500)


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
    adopt_fields: list[str] | None = None
    reason: str | None = Field(default=None, max_length=500)


class VesselVoidRequest(StrictBaseModel):
    reason: str | None = Field(default=None, max_length=256)
    revision: int | None = Field(default=None, ge=1)


class VesselRecognitionAdoptionRequest(StrictBaseModel):
    accepted_payload_json: dict[str, Any] | None = None
    adopt_fields: list[str] = Field(default_factory=list)
    adopt_to_profile_fields: list[str] = Field(default_factory=list)
    apply_to_owner: bool = True
    reason: str | None = Field(default=None, max_length=500)


class VesselQualityIssueQuery(BaseModel):
    status_code: str | None = None
    issue_type_code: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)


class VesselQualityIssueGlobalQuery(VesselQualityIssueQuery):
    severity_code: str | None = None
    vessel_id: int | None = Field(default=None, ge=1)
    keyword: str | None = Field(default=None, max_length=64)


class VesselOwnerTransferRequest(StrictBaseModel):
    new_owner_name: str = Field(min_length=1, max_length=128)
    party_type_code: str = Field(default="UNKNOWN", min_length=1, max_length=64)
    transfer_date: date | None = None
    certificate_no: str | None = Field(default=None, max_length=64)
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


class VesselOwnerDocumentImageRecognitionResponse(BaseModel):
    id: int
    vessel_profile_id: int
    vessel_owner_period_id: int
    owner_document_id: int
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


class VesselOwnerDocumentResponse(BaseModel):
    id: int
    vessel_profile_id: int
    vessel_owner_period_id: int
    document_type_code: str
    document_type_name: str | None = None
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
    latest_image_recognition: VesselOwnerDocumentImageRecognitionResponse | None = None
    current_image_recognition: VesselOwnerDocumentImageRecognitionResponse | None = None
    latest_confirmed_image_recognition: VesselOwnerDocumentImageRecognitionResponse | None = None
    has_recognition_history: bool = False


class VesselOwnerDocumentLedgerItemResponse(BaseModel):
    document_type_code: str
    document_type_name: str | None = None
    required: bool = False
    status_code: str
    status_name: str
    document: VesselOwnerDocumentResponse | None = None


class VesselOwnerDocumentCompletenessResponse(BaseModel):
    status_code: str
    status_name: str
    required_count: int
    completed_count: int
    missing_document_type_codes: list[str] = Field(default_factory=list)
    message: str | None = None


class VesselOwnerResponse(VesselOwnerItem):
    id: int
    vessel_profile_id: int
    party_type_name: str | None = None
    revision: int = 1
    verified_status_code: str = "UNVERIFIED"
    verified_status_name: str | None = None
    source_type_code: str = "MANUAL"
    source_type_name: str | None = None
    source_trace_id: str | None = None
    voided_at: datetime | None = None
    voided_by: int | None = None
    void_reason: str | None = None
    change_event_id: int | None = None
    cancelled_primary_ids: list[int] = Field(default_factory=list)
    documents: list[VesselOwnerDocumentResponse] = Field(default_factory=list)
    document_ledger: list[VesselOwnerDocumentLedgerItemResponse] = Field(default_factory=list)
    document_completeness: VesselOwnerDocumentCompletenessResponse | None = None
    created_at: datetime
    updated_at: datetime


class VesselOperatorResponse(VesselOperatorItem):
    id: int
    vessel_profile_id: int
    party_type_name: str | None = None
    revision: int = 1
    verified_status_code: str = "UNVERIFIED"
    verified_status_name: str | None = None
    source_type_code: str = "MANUAL"
    source_type_name: str | None = None
    source_trace_id: str | None = None
    voided_at: datetime | None = None
    voided_by: int | None = None
    void_reason: str | None = None
    change_event_id: int | None = None
    cancelled_primary_ids: list[int] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class VesselContactResponse(VesselContactItem):
    id: int
    vessel_profile_id: int
    contact_scope_name: str | None = None
    contact_role_name: str | None = None
    revision: int = 1
    verified_status_code: str = "UNVERIFIED"
    verified_status_name: str | None = None
    source_type_code: str = "MANUAL"
    source_type_name: str | None = None
    source_trace_id: str | None = None
    voided_at: datetime | None = None
    voided_by: int | None = None
    void_reason: str | None = None
    change_event_id: int | None = None
    cancelled_primary_ids: list[int] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class VesselCrewResponse(VesselCrewItem):
    id: int
    vessel_profile_id: int
    crew_role_name: str | None = None
    revision: int = 1
    verified_status_code: str = "UNVERIFIED"
    verified_status_name: str | None = None
    source_type_code: str = "MANUAL"
    source_type_name: str | None = None
    source_trace_id: str | None = None
    voided_at: datetime | None = None
    voided_by: int | None = None
    void_reason: str | None = None
    change_event_id: int | None = None
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


class VesselQualityIssueResponse(BaseModel):
    id: int
    issue_type_code: str
    issue_type_name: str | None = None
    severity_code: str
    affected_object_type: str
    affected_object_id: str
    vessel_profile_id: int | None = None
    field_name: str | None = None
    fingerprint: str
    evidence_source: str | None = None
    impact_scope_json: list[Any] | None = None
    status_code: str
    status_name: str | None = None
    resolved_at: datetime | None = None
    resolved_by: int | None = None
    resolved_evidence: str | None = None
    created_at: datetime
    updated_at: datetime


class VesselRecognitionFieldDiffResponse(BaseModel):
    id: int
    vessel_profile_id: int
    recognition_object_type: str
    recognition_id: int
    target_object_type: str
    target_object_id: int
    field_name: str
    current_value_text: str | None = None
    recognized_value_text: str | None = None
    confidence_score: int | None = None
    evidence_text: str | None = None
    adopt_status_code: str
    created_at: datetime
    updated_at: datetime


class VesselRecognitionAdoptionRecordResponse(BaseModel):
    id: int
    vessel_profile_id: int
    recognition_object_type: str
    recognition_id: int
    target_object_type: str
    target_object_id: int
    adopted_fields_json: list[Any] | None = None
    skipped_fields_json: list[Any] | None = None
    confirmed_by: int | None = None
    confirmed_at: datetime
    reason: str | None = None
    change_event_id: int | None = None
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


class VesselQualityIssueVesselSummary(BaseModel):
    id: int
    ship_name: str
    current_mmsi: str
    vessel_profile_code: str
    profile_status_code: str
    profile_status_name: str | None = None


class VesselQualityIssueListItemResponse(VesselQualityIssueResponse):
    vessel: VesselQualityIssueVesselSummary | None = None


class VesselGovernanceDashboardMetric(BaseModel):
    code: str
    name: str
    value: Decimal | int | None = None
    unit: str | None = None
    source_layer_code: str = "GOVERNANCE_TASK"
    sample_count: int = 0
    coverage_rate: Decimal | None = None
    confidence_level: str = "UNKNOWN"
    not_computable_reasons: list[str] = Field(default_factory=list)
    source_updated_at: datetime | None = None


class VesselGovernanceDashboardResponse(BaseModel):
    generated_at: datetime
    source_layer_code: str = "GOVERNANCE_TASK"
    coverage_rate: Decimal | None = None
    confidence_level: str = "UNKNOWN"
    latest_success_at: datetime | None = None
    metrics: list[VesselGovernanceDashboardMetric] = Field(default_factory=list)


class VesselGovernanceTaskQuery(BaseModel):
    status_code: str | None = None
    task_type_code: str | None = None
    priority_code: str | None = None
    vessel_id: int | None = Field(default=None, ge=1)
    source_object_type: str | None = None
    assigned_to: int | None = None
    keyword: str | None = Field(default=None, max_length=128)
    auto_sync: bool = True
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class VesselGovernanceTaskActionRequest(StrictBaseModel):
    action_code: str = Field(min_length=1, max_length=32)
    revision: int = Field(ge=1)
    assigned_to: int | None = None
    reason: str | None = Field(default=None, max_length=1000)
    evidence_json: dict[str, Any] | None = None


class VesselGovernanceTaskResponse(BaseModel):
    id: int
    task_no: str
    task_type_code: str
    task_type_name: str | None = None
    priority_code: str
    priority_name: str | None = None
    status_code: str
    status_name: str | None = None
    vessel_profile_id: int | None = None
    source_object_type: str
    source_object_id: str
    source_status_code: str | None = None
    source_fingerprint: str | None = None
    fingerprint: str
    title: str
    description: str | None = None
    evidence_summary: str | None = None
    source_trace_json: list[Any] | None = None
    impact_summary_json: dict[str, Any] | None = None
    confidence_level: str
    confidence_level_name: str | None = None
    coverage_rate: Decimal | None = None
    assigned_to: int | None = None
    assigned_at: datetime | None = None
    started_at: datetime | None = None
    resolved_at: datetime | None = None
    resolved_by: int | None = None
    resolution_reason: str | None = None
    resolution_evidence_json: dict[str, Any] | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    duplicate_count: int
    reopen_count: int
    revision: int
    created_at: datetime
    updated_at: datetime
    vessel: VesselQualityIssueVesselSummary | None = None


class VesselComplianceRiskQuery(BaseModel):
    status_code: str | None = None
    risk_type_code: str | None = None
    risk_level: str | None = None
    rule_code: str | None = None
    vessel_id: int | None = Field(default=None, ge=1)
    keyword: str | None = Field(default=None, max_length=128)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class VesselComplianceRuleQuery(BaseModel):
    status_code: str | None = None
    scope_type_code: str | None = None
    certificate_type_code: str | None = None
    keyword: str | None = Field(default=None, max_length=128)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class VesselCertificateRequirementRulePayload(StrictBaseModel):
    rule_code: str = Field(min_length=1, max_length=96)
    rule_name: str = Field(min_length=1, max_length=128)
    scope_type_code: str = Field(default="GLOBAL", min_length=1, max_length=64)
    ship_type_code: str | None = Field(default=None, max_length=64)
    cargo_category_code: str | None = Field(default=None, max_length=64)
    route_area_code: str | None = Field(default=None, max_length=64)
    required_certificate_type_code: str = Field(min_length=1, max_length=64)
    risk_type_code: str = Field(default="CERTIFICATE_MISSING", min_length=1, max_length=64)
    risk_level_when_missing: str = Field(default="MEDIUM", min_length=1, max_length=32)
    status_code: str = Field(default="ACTIVE", min_length=1, max_length=32)
    condition_json: dict[str, Any] | None = None
    evidence_requirements_json: dict[str, Any] | None = None
    remark: str | None = Field(default=None, max_length=500)


class VesselCertificateRequirementRuleUpdateRequest(StrictBaseModel):
    revision: int = Field(ge=1)
    rule_name: str | None = Field(default=None, min_length=1, max_length=128)
    scope_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    ship_type_code: str | None = Field(default=None, max_length=64)
    cargo_category_code: str | None = Field(default=None, max_length=64)
    route_area_code: str | None = Field(default=None, max_length=64)
    required_certificate_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    risk_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    risk_level_when_missing: str | None = Field(default=None, min_length=1, max_length=32)
    status_code: str | None = Field(default=None, min_length=1, max_length=32)
    condition_json: dict[str, Any] | None = None
    evidence_requirements_json: dict[str, Any] | None = None
    remark: str | None = Field(default=None, max_length=500)


class VesselCertificateRequirementRuleResponse(BaseModel):
    id: int
    rule_code: str
    rule_name: str
    scope_type_code: str
    scope_type_name: str | None = None
    ship_type_code: str | None = None
    ship_type_name: str | None = None
    cargo_category_code: str | None = None
    route_area_code: str | None = None
    required_certificate_type_code: str
    required_certificate_type_name: str | None = None
    risk_type_code: str
    risk_type_name: str | None = None
    risk_level_when_missing: str
    risk_level_when_missing_name: str | None = None
    status_code: str
    status_name: str | None = None
    condition_json: dict[str, Any] | None = None
    evidence_requirements_json: dict[str, Any] | None = None
    revision: int
    remark: str | None = None
    created_at: datetime
    updated_at: datetime


class VesselRiskSignalVesselSummary(BaseModel):
    id: int
    ship_name: str
    current_mmsi: str
    vessel_profile_code: str
    profile_status_code: str
    profile_status_name: str | None = None


class VesselRiskSignalResponse(BaseModel):
    id: int
    vessel_profile_id: int
    risk_type_code: str
    risk_type_name: str | None = None
    risk_level: str
    risk_level_name: str | None = None
    rule_code: str | None = None
    status_code: str
    status_name: str | None = None
    confidence_level: str
    confidence_level_name: str | None = None
    fingerprint: str
    evidence_json: dict[str, Any] | None = None
    source_trace_json: list[Any] | None = None
    uncertainty_notes_json: list[Any] | None = None
    first_detected_at: datetime
    last_detected_at: datetime
    resolved_at: datetime | None = None
    resolved_by: int | None = None
    resolution_reason: str | None = None
    revision: int
    created_at: datetime
    updated_at: datetime
    vessel: VesselRiskSignalVesselSummary | None = None


class VesselRiskSignalUpdateRequest(StrictBaseModel):
    revision: int = Field(ge=1)
    status_code: str = Field(min_length=1, max_length=32)
    resolution_reason: str = Field(min_length=1, max_length=1000)
    evidence_json: dict[str, Any]


class VesselRiskReviewRequest(StrictBaseModel):
    risk_signal_id: int | None = Field(default=None, ge=1)
    governance_task_id: int | None = Field(default=None, ge=1)
    review_action_code: str = Field(min_length=1, max_length=64)
    to_status_code: str | None = Field(default=None, max_length=64)
    risk_level_after: str | None = Field(default=None, max_length=32)
    evidence_json: dict[str, Any] | None = None
    review_reason: str | None = Field(default=None, max_length=1000)


class VesselRiskReviewResponse(BaseModel):
    id: int
    vessel_profile_id: int
    risk_signal_id: int | None = None
    governance_task_id: int | None = None
    review_action_code: str
    from_status_code: str | None = None
    to_status_code: str | None = None
    risk_level_before: str | None = None
    risk_level_after: str | None = None
    evidence_json: dict[str, Any] | None = None
    review_reason: str | None = None
    reviewed_by: int | None = None
    reviewed_at: datetime
    created_at: datetime
    updated_at: datetime


class VesselComplianceRiskResponse(BaseModel):
    vessel_id: int
    generated_at: datetime
    overall_risk_level: str = "UNKNOWN"
    overall_risk_level_name: str | None = None
    engine_status_code: str = "READY"
    risk_signal_count: int = 0
    open_signal_count: int = 0
    high_signal_count: int = 0
    medium_signal_count: int = 0
    rule_coverage_rate: Decimal | None = None
    evidence_gap_count: int = 0
    data_sources: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    rule_summary: list[dict[str, Any]] = Field(default_factory=list)
    signals: list[VesselRiskSignalResponse] = Field(default_factory=list)


class VesselControllerEvidenceCreateRequest(StrictBaseModel):
    party_name: str = Field(min_length=1, max_length=128)
    controller_role_code: str = Field(default="EVIDENCE_PROVIDER", max_length=64)
    confidence_level: str = Field(default="UNKNOWN", max_length=32)
    source_type_code: str = Field(default="MANUAL", max_length=64)
    source_trace_id: str | None = Field(default=None, max_length=128)
    evidence_summary: str | None = Field(default=None, max_length=500)
    evidence_json: dict[str, Any] | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    status_code: str = Field(default="ACTIVE", max_length=32)
    verified_status_code: str = Field(default="DRAFT", max_length=32)


class VesselControllerEvidenceUpdateRequest(StrictBaseModel):
    revision: int = Field(ge=1)
    party_name: str | None = Field(default=None, min_length=1, max_length=128)
    controller_role_code: str | None = Field(default=None, max_length=64)
    confidence_level: str | None = Field(default=None, max_length=32)
    source_type_code: str | None = Field(default=None, max_length=64)
    source_trace_id: str | None = Field(default=None, max_length=128)
    evidence_summary: str | None = Field(default=None, max_length=500)
    evidence_json: dict[str, Any] | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    status_code: str | None = Field(default=None, max_length=32)
    verified_status_code: str | None = Field(default=None, max_length=32)
    reason: str | None = Field(default=None, max_length=500)


class VesselControllerEvidenceResponse(BaseModel):
    id: int
    vessel_profile_id: int
    party_name: str
    controller_role_code: str
    controller_role_name: str | None = None
    confidence_level: str
    confidence_level_name: str | None = None
    source_type_code: str
    source_type_name: str | None = None
    source_trace_id: str | None = None
    evidence_summary: str | None = None
    evidence_json: dict[str, Any] | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    status_code: str
    verified_status_code: str = "DRAFT"
    verified_status_name: str | None = None
    audit_task_id: int | None = None
    verified_at: datetime | None = None
    verified_by: int | None = None
    revision: int
    voided_at: datetime | None = None
    voided_by: int | None = None
    void_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class VesselAffiliationEvidenceCreateRequest(StrictBaseModel):
    owner_period_id: int | None = None
    operator_period_id: int | None = None
    affiliation_type_code: str = Field(default="UNKNOWN", max_length=64)
    subject_name: str | None = Field(default=None, max_length=128)
    counterparty_name: str | None = Field(default=None, max_length=128)
    confidence_level: str = Field(default="UNKNOWN", max_length=32)
    source_type_code: str = Field(default="MANUAL", max_length=64)
    source_trace_id: str | None = Field(default=None, max_length=128)
    evidence_summary: str | None = Field(default=None, max_length=500)
    evidence_json: dict[str, Any] | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    status_code: str = Field(default="ACTIVE", max_length=32)
    verified_status_code: str = Field(default="DRAFT", max_length=32)


class VesselAffiliationEvidenceUpdateRequest(VesselAffiliationEvidenceCreateRequest):
    revision: int = Field(ge=1)
    affiliation_type_code: str | None = Field(default=None, max_length=64)
    confidence_level: str | None = Field(default=None, max_length=32)
    source_type_code: str | None = Field(default=None, max_length=64)
    status_code: str | None = Field(default=None, max_length=32)
    verified_status_code: str | None = Field(default=None, max_length=32)
    reason: str | None = Field(default=None, max_length=500)


class VesselAffiliationEvidenceResponse(BaseModel):
    id: int
    vessel_profile_id: int
    owner_period_id: int | None = None
    operator_period_id: int | None = None
    affiliation_type_code: str
    affiliation_type_name: str | None = None
    subject_name: str | None = None
    counterparty_name: str | None = None
    confidence_level: str
    confidence_level_name: str | None = None
    source_type_code: str
    source_type_name: str | None = None
    source_trace_id: str | None = None
    evidence_summary: str | None = None
    evidence_json: dict[str, Any] | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    status_code: str
    verified_status_code: str = "DRAFT"
    verified_status_name: str | None = None
    audit_task_id: int | None = None
    verified_at: datetime | None = None
    verified_by: int | None = None
    revision: int
    voided_at: datetime | None = None
    voided_by: int | None = None
    void_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class VesselBlacklistSignalCreateRequest(StrictBaseModel):
    list_type_code: str = Field(default="WATCHLIST", max_length=32)
    signal_type_code: str = Field(default="MANUAL_RISK", max_length=64)
    status_code: str = Field(default="ACTIVE", max_length=32)
    risk_level: str = Field(default="HIGH", max_length=32)
    confidence_level: str = Field(default="UNKNOWN", max_length=32)
    source_type_code: str = Field(default="MANUAL", max_length=64)
    source_trace_id: str | None = Field(default=None, max_length=128)
    evidence_summary: str | None = Field(default=None, max_length=1000)
    evidence_json: dict[str, Any] | None = None
    effective_from: date | None = None
    effective_to: date | None = None


class VesselBlacklistSignalUpdateRequest(StrictBaseModel):
    revision: int = Field(ge=1)
    list_type_code: str | None = Field(default=None, max_length=32)
    signal_type_code: str | None = Field(default=None, max_length=64)
    status_code: str | None = Field(default=None, max_length=32)
    risk_level: str | None = Field(default=None, max_length=32)
    confidence_level: str | None = Field(default=None, max_length=32)
    source_type_code: str | None = Field(default=None, max_length=64)
    source_trace_id: str | None = Field(default=None, max_length=128)
    evidence_summary: str | None = Field(default=None, max_length=1000)
    evidence_json: dict[str, Any] | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    reason: str | None = Field(default=None, max_length=1000)


class VesselBlacklistSignalResponse(BaseModel):
    id: int
    vessel_profile_id: int
    list_type_code: str
    list_type_name: str | None = None
    signal_type_code: str
    signal_type_name: str | None = None
    status_code: str
    status_name: str | None = None
    risk_level: str
    risk_level_name: str | None = None
    confidence_level: str
    confidence_level_name: str | None = None
    source_type_code: str
    source_type_name: str | None = None
    source_trace_id: str | None = None
    evidence_summary: str | None = None
    evidence_json: dict[str, Any] | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    voided_at: datetime | None = None
    voided_by: int | None = None
    void_reason: str | None = None
    revision: int
    created_at: datetime
    updated_at: datetime


class VesselRecognitionQueueQuery(BaseModel):
    recognition_type: str | None = Field(default=None, pattern="^(certificate|person-certificate|owner-document)$")
    status_code: str | None = None
    vessel_id: int | None = Field(default=None, ge=1)
    low_confidence: bool | None = None
    keyword: str | None = Field(default=None, max_length=128)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class VesselRecognitionQueueItemResponse(BaseModel):
    id: str
    recognition_type: str
    recognition_object_type: str
    recognition_id: int
    vessel_profile_id: int
    vessel: VesselRiskSignalVesselSummary | None = None
    target_object_type: str
    target_object_id: int
    status_code: str
    status_name: str | None = None
    confidence_score: int | None = None
    low_confidence: bool = False
    pending_diff_count: int = 0
    low_confidence_diff_count: int = 0
    adoption_count: int = 0
    created_at: datetime
    updated_at: datetime


class VesselProfileCardEvidenceQuery(BaseModel):
    section: str = Field(pattern="^(identity|relation|quality|compliance|recognition|trajectory)$")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class VesselProfileCardSourceTrace(BaseModel):
    source_code: str
    source_name: str | None = None
    updated_at: datetime | None = None
    confidence_level: str = "UNKNOWN"
    coverage_rate: Decimal | None = None
    status_code: str | None = None
    note: str | None = None


class VesselProfileCardBaseCard(BaseModel):
    status_code: str = "UNKNOWN"
    confidence_level: str = "UNKNOWN"
    evidence_count: int = 0
    updated_at: datetime | None = None
    source_codes: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)


class VesselProfileCardIssueSummary(BaseModel):
    id: int
    issue_type_code: str
    severity_code: str
    status_code: str
    field_name: str | None = None
    affected_object_type: str | None = None
    affected_object_id: str | None = None
    updated_at: datetime | None = None


class VesselProfileIdentityCard(VesselProfileCardBaseCard):
    ship_name: str | None = None
    current_mmsi: str | None = None
    vessel_profile_code: str | None = None
    ship_type_code: str | None = None
    ship_type_name: str | None = None
    profile_status_code: str | None = None
    profile_status_name: str | None = None
    identity_status_code: str | None = None
    identity_status_name: str | None = None
    registry_city_code: str | None = None
    registry_city_name: str | None = None
    deadweight_ton: Decimal | None = None
    length_m: Decimal | None = None
    width_m: Decimal | None = None
    design_draft_m: Decimal | None = None
    name_history_summary: list[dict[str, Any]] = Field(default_factory=list)
    identifier_history_summary: list[dict[str, Any]] = Field(default_factory=list)
    conflict_warnings: list[str] = Field(default_factory=list)


class VesselProfileRelationCard(VesselProfileCardBaseCard):
    primary_owner_name: str | None = None
    primary_operator_name: str | None = None
    primary_contact_name: str | None = None
    primary_contact_phone_masked: str | None = None
    owner_count: int = 0
    operator_count: int = 0
    contact_count: int = 0
    crew_count: int = 0
    current_relation_count: int = 0
    history_relation_count: int = 0
    voided_relation_count: int = 0
    controller_status_code: str = "UNKNOWN"
    affiliation_status_code: str = "UNKNOWN"
    controller_message: str | None = None
    affiliation_message: str | None = None


class VesselProfileQualityCard(VesselProfileCardBaseCard):
    profile_completeness_rate: Decimal | None = None
    data_quality_score: Decimal | None = None
    quality_level: str = "UNKNOWN"
    open_issue_count: int = 0
    high_issue_count: int = 0
    medium_issue_count: int = 0
    missing_field_count: int = 0
    conflict_count: int = 0
    top_active_issues: list[VesselProfileCardIssueSummary] = Field(default_factory=list)


class VesselProfileComplianceCard(VesselProfileCardBaseCard):
    risk_level: str = "UNKNOWN"
    risk_source: str = "CERTIFICATE_LEDGER_PRE_RULE"
    certificate_missing_count: int = 0
    certificate_expiring_count: int = 0
    certificate_expired_count: int = 0
    risk_evidence_summary: list[Any] = Field(default_factory=list)
    evidence_gap_count: int = 0
    message: str | None = None


class VesselProfileTrajectoryCard(VesselProfileCardBaseCard):
    ais_freshness_level: str = "UNKNOWN"
    latest_position_time: datetime | None = None
    latest_city_code: str | None = None
    latest_city_name: str | None = None
    ais_unavailable_reason: str | None = None
    data_availability_status: str = "UNKNOWN"
    deprecated_alias: bool = False


class VesselProfileRecognitionCard(VesselProfileCardBaseCard):
    pending_diff_count: int = 0
    low_confidence_diff_count: int = 0
    active_task_count: int = 0
    adoption_count: int = 0
    latest_adoption: dict[str, Any] | None = None
    message: str | None = None


class VesselProfileCandidateCard(VesselProfileCardBaseCard):
    round: str = "Round 8"
    message: str = "候选资源适配分析将在 Round 8 接入"
    analysis_history_count: int = 0


class VesselProfileCardEvidenceItem(BaseModel):
    id: str
    section: str
    object_type: str
    object_id: str | None = None
    title: str
    status_code: str | None = None
    severity_code: str | None = None
    source_code: str | None = None
    confidence_score: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class VesselProfileCardEvidenceResponse(PageResponse[VesselProfileCardEvidenceItem]):
    section: str
    source_trace: list[VesselProfileCardSourceTrace] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)


class VesselProfileCardResponse(BaseModel):
    vessel_id: int
    generated_at: datetime
    summary_status_code: str = "MISSING"
    refreshed_at: datetime | None = None
    source_updated_at: datetime | None = None
    refresh_available: bool = False
    stale: bool = False
    data_sources: list[str] = Field(default_factory=list)
    confidence_level: str = "UNKNOWN"
    coverage_rate: Decimal | None = None
    source_trace: list[VesselProfileCardSourceTrace] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    quality_warnings: list[str] = Field(default_factory=list)
    identity_card: VesselProfileIdentityCard = Field(default_factory=VesselProfileIdentityCard)
    relation_card: VesselProfileRelationCard = Field(default_factory=VesselProfileRelationCard)
    quality_card: VesselProfileQualityCard = Field(default_factory=VesselProfileQualityCard)
    compliance_card: VesselProfileComplianceCard = Field(default_factory=VesselProfileComplianceCard)
    trajectory_card: VesselProfileTrajectoryCard = Field(default_factory=VesselProfileTrajectoryCard)
    ais_card: VesselProfileTrajectoryCard = Field(default_factory=VesselProfileTrajectoryCard)
    recognition_card: VesselProfileRecognitionCard = Field(default_factory=VesselProfileRecognitionCard)
    candidate_card: VesselProfileCandidateCard = Field(default_factory=VesselProfileCandidateCard)


class VesselPositionMonitorItemResponse(VesselListItemResponse):
    longitude: Decimal
    latitude: Decimal
    speed_kn: Decimal | None = None
    course_deg: Decimal | None = None
    heading_deg: Decimal | None = None
    position_time: datetime | None = None
    position_age_minutes: int | None = None
    city_code: str | None = None
    city_name: str | None = None
    current_city_code: str | None = None
    current_city_name: str | None = None
    current_city_source: str | None = None
    city_center_longitude: Decimal | None = None
    city_center_latitude: Decimal | None = None
    matched_city_candidates: list[dict[str, Any]] | None = None
    location_text: str | None = None
    position_source_code: str = "ES_REALTIME"
    position_source_name: str | None = None
    source_index: str | None = None
    freshness_level: str = "UNKNOWN"
    match_status_code: str = "MATCHED_PROFILE"


class VesselPositionMonitorSummary(BaseModel):
    matched_profile_count: int
    positioned_count: int
    stale_position_count: int
    contactable_position_count: int
    unmatched_mmsi_count: int = 0
    invalid_position_count: int = 0
    coverage_rate: Decimal | None = None
    freshness_distribution: dict[str, int] = Field(default_factory=dict)


class VesselPositionMonitorResponse(BaseModel):
    source_status: str
    source_status_name: str
    generated_at: datetime
    message: str | None = None
    summary: VesselPositionMonitorSummary
    items: list[VesselPositionMonitorItemResponse] = Field(default_factory=list)


class VesselShipTypeDistributionItemResponse(BaseModel):
    ship_type_code: str | None = None
    ship_type_name: str | None = None
    count: int


class VesselPositionCitySituationItemResponse(BaseModel):
    city_code: str | None = None
    city_name: str
    longitude: Decimal | None = None
    latitude: Decimal | None = None
    city_center_longitude: Decimal | None = None
    city_center_latitude: Decimal | None = None
    heat_center_longitude: Decimal | None = None
    heat_center_latitude: Decimal | None = None
    boundary_paths: list[list[list[float]]] | None = None
    has_boundary: bool = False
    boundary_precision: str | None = None
    positioned_count: int
    contactable_position_count: int
    average_ship_age: Decimal | None = None
    total_deadweight_ton: Decimal | None = None
    ship_type_distribution: list[VesselShipTypeDistributionItemResponse] = Field(default_factory=list)
    stale_position_count: int = 0
    certificate_risk_count: int = 0
    unmatched_mmsi_count: int = 0
    invalid_position_count: int = 0
    freshness_distribution: dict[str, int] = Field(default_factory=dict)
    boundary_status_code: str = "UNKNOWN"
    latest_position_time: datetime | None = None
    mmsi_count: int = 0
    matched_position_count: int = 0
    unpositioned_count: int = 0
    is_partial: bool = False
    error_message: str | None = None


class VesselPositionCitySituationSummary(BaseModel):
    matched_profile_count: int
    scanned_profile_count: int = 0
    unscanned_profile_count: int = 0
    queried_mmsi_count: int
    matched_position_count: int
    unmatched_mmsi_count: int = 0
    unpositioned_count: int
    invalid_position_count: int = 0
    unknown_city_count: int = 0
    positioned_count: int
    stale_position_count: int
    contactable_position_count: int
    certificate_risk_count: int
    city_count: int
    boundary_city_count: int = 0
    missing_boundary_city_count: int = 0
    missing_boundary_cities: list[dict[str, Any]] = Field(default_factory=list)
    query_snapshot_id: str | None = None
    snapshot_status_code: str = "READY"
    snapshot_expires_at: datetime | None = None
    refresh_required: bool = False
    coverage_rate: Decimal | None = None
    freshness_distribution: dict[str, int] = Field(default_factory=dict)
    source_indices: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    failed_batch_count: int = 0
    failed_batches: list[dict[str, Any]] = Field(default_factory=list)
    is_partial: bool = False
    error_message: str | None = None


class VesselPositionCitySituationResponse(BaseModel):
    source_status: str
    source_status_name: str
    generated_at: datetime
    message: str | None = None
    cache_status: str = "MISS"
    cache_generated_at: datetime | None = None
    is_stale_cache: bool = False
    snapshot_backend: str = "memory"
    cache_backend_note: str | None = None
    summary: VesselPositionCitySituationSummary
    cities: list[VesselPositionCitySituationItemResponse] = Field(default_factory=list)


class VesselPositionCityVesselsResponse(PageResponse[VesselPositionMonitorItemResponse]):
    query_snapshot_id: str | None = None
    snapshot_hit: bool = False
    refresh_required: bool = False
    snapshot_status_code: str | None = None
    is_partial: bool = False
    error_message: str | None = None


class VesselAisCityBoundaryItemResponse(BaseModel):
    city_code: str
    city_name: str
    boundary_paths: list[list[list[float]]] = Field(default_factory=list)
    has_boundary: bool = False
    boundary_precision: str = "low"
    boundary_status_code: str = "UNKNOWN"
    city_center_longitude: Decimal | None = None
    city_center_latitude: Decimal | None = None


class VesselAisCityBoundaryResponse(BaseModel):
    generated_at: datetime
    boundary_version_id: int | None = None
    precision: str = "low"
    total: int = 0
    items: list[VesselAisCityBoundaryItemResponse] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)


class VesselAisSnapshotResponse(BaseModel):
    snapshot_id: str
    query_hash: str
    query_params: dict[str, Any] = Field(default_factory=dict)
    status_code: str
    generated_at: datetime
    expires_at: datetime
    cache_backend_code: str
    scanned_profile_count: int
    queried_mmsi_count: int
    matched_profile_count: int
    matched_position_count: int
    unmatched_mmsi_count: int
    invalid_position_count: int
    unknown_city_count: int
    failed_batch_count: int
    failed_batches: list[dict[str, Any]] = Field(default_factory=list)
    coverage_rate: Decimal | None = None
    freshness_distribution: dict[str, int] = Field(default_factory=dict)
    source_indices: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    refresh_error: str | None = None


class VesselAisUnmatchedMmsiResponse(BaseModel):
    snapshot_id: str | None = None
    generated_at: datetime | None = None
    mmsi: str
    longitude: Decimal | None = None
    latitude: Decimal | None = None
    position_time: datetime | None = None
    freshness_level: str = "UNKNOWN"
    source_index: str | None = None
    city_code: str | None = None
    city_name: str | None = None
    match_status_code: str = "UNMATCHED_MMSI"


class VesselSpatialSnapshotMeta(BaseModel):
    snapshot_id: str
    source_snapshot_id: str | None = None
    observation_type_code: str
    status_code: str
    source_status_code: str
    stat_time: datetime | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    generated_at: datetime
    expires_at: datetime
    refresh_required: bool = False
    coverage_rate: Decimal | None = None
    confidence_level: str = "UNKNOWN"
    freshness_distribution: dict[str, int] = Field(default_factory=dict)
    source_indices: list[str] = Field(default_factory=list)
    failed_batch_count: int = 0
    failed_batches: list[dict[str, Any]] = Field(default_factory=list)
    unmatched_mmsi_count: int = 0
    invalid_position_count: int = 0
    stale_position_count: int = 0
    matched_position_count: int = 0
    active_vessel_count: int = 0
    not_computable_reasons: list[str] = Field(default_factory=list)
    quality_warnings: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    refresh_error: str | None = None


class VesselNavigationConstraintEvidenceResponse(BaseModel):
    id: int | None = None
    snapshot_id: str | None = None
    context_type_code: str
    context_id: int
    constraint_point_id: int | None = None
    constraint_name: str | None = None
    constraint_type_code: str | None = None
    status_code: str = "UNKNOWN"
    source_type_code: str = "BASE_DATA"
    source_ref: str | None = None
    observed_at: datetime | None = None
    expires_at: datetime | None = None
    value: dict[str, Any] = Field(default_factory=dict)
    confidence_level: str = "UNKNOWN"
    unavailable_reason: str | None = None


class VesselNodeObservationVesselResponse(BaseModel):
    id: int | None = None
    vessel_profile_id: int | None = None
    mmsi: str
    ship_name: str | None = None
    ship_type_code: str | None = None
    deadweight_ton: Decimal | None = None
    longitude: Decimal | None = None
    latitude: Decimal | None = None
    distance_km: Decimal | None = None
    position_time: datetime | None = None
    source_index: str | None = None
    freshness_level: str = "UNKNOWN"
    match_status_code: str = "NEARBY"
    stay_duration_minutes: int | None = None
    direction_status_code: str = "UNKNOWN"
    risk_level: str | None = None
    quality_level: str | None = None


class VesselNodeSituationSummary(BaseModel):
    node_id: int
    node_name: str
    node_type_code: str | None = None
    city_code: str | None = None
    radius_km: Decimal
    longitude: Decimal | None = None
    latitude: Decimal | None = None
    active_vessel_count: int = 0
    stay_vessel_count: int = 0
    passby_vessel_count: int = 0
    inflow_count: int = 0
    outflow_count: int = 0
    unmatched_mmsi_count: int = 0
    invalid_position_count: int = 0
    stale_position_count: int = 0
    coverage_rate: Decimal | None = None
    confidence_level: str = "UNKNOWN"
    freshness_distribution: dict[str, int] = Field(default_factory=dict)
    ship_type_distribution: list[VesselShipTypeDistributionItemResponse] = Field(default_factory=list)
    risk_distribution: list[VesselAssetDistributionItemResponse] = Field(default_factory=list)
    latest_position_time: datetime | None = None
    not_computable_reasons: list[str] = Field(default_factory=list)


class VesselAisNodeSituationResponse(BaseModel):
    source_status: str
    source_status_name: str
    generated_at: datetime
    message: str | None = None
    snapshot: VesselSpatialSnapshotMeta
    summary: VesselNodeSituationSummary
    vessels: list[VesselNodeObservationVesselResponse] = Field(default_factory=list)
    constraints: list[VesselNavigationConstraintEvidenceResponse] = Field(default_factory=list)


class VesselAisNodeVesselsResponse(PageResponse[VesselNodeObservationVesselResponse]):
    query_snapshot_id: str | None = None
    snapshot_hit: bool = False
    refresh_required: bool = False
    snapshot_status_code: str | None = None
    is_partial: bool = False
    error_message: str | None = None


class VesselRouteSegmentObservationResponse(BaseModel):
    id: int | None = None
    route_id: int | None = None
    line_id: int
    segment_id: int
    segment_no: int
    segment_name: str | None = None
    geometry_status_code: str = "UNKNOWN"
    geometry_source: str | None = None
    geometry_json: dict[str, Any] | None = None
    matched_vessel_count: int = 0
    active_vessel_count: int = 0
    point_count: int = 0
    gap_count: int = 0
    covered_ratio: Decimal | None = None
    average_match_score: Decimal | None = None
    coverage_rate: Decimal | None = None
    confidence_level: str = "UNKNOWN"
    not_computable_reasons: list[str] = Field(default_factory=list)


class VesselRouteSegmentMatchSampleResponse(BaseModel):
    id: int | None = None
    segment_id: int
    vessel_profile_id: int | None = None
    mmsi: str
    ship_name: str | None = None
    ship_type_code: str | None = None
    deadweight_ton: Decimal | None = None
    match_score: Decimal | None = None
    covered_ratio: Decimal | None = None
    direction_consistency: Decimal | None = None
    point_count: int = 0
    gap_count: int = 0
    latest_position_time: datetime | None = None
    source_index: str | None = None
    freshness_level: str = "UNKNOWN"
    confidence_level: str = "UNKNOWN"
    match_status_code: str = "MATCHED"


class VesselRouteSituationSummary(BaseModel):
    route_id: int | None = None
    line_id: int
    line_name: str | None = None
    segment_count: int = 0
    matched_segment_count: int = 0
    matched_vessel_count: int = 0
    active_vessel_count: int = 0
    coverage_rate: Decimal | None = None
    confidence_level: str = "UNKNOWN"
    not_computable_reasons: list[str] = Field(default_factory=list)


class VesselAisRouteSituationResponse(BaseModel):
    source_status: str
    source_status_name: str
    generated_at: datetime
    message: str | None = None
    snapshot: VesselSpatialSnapshotMeta
    summary: VesselRouteSituationSummary
    segments: list[VesselRouteSegmentObservationResponse] = Field(default_factory=list)
    samples: list[VesselRouteSegmentMatchSampleResponse] = Field(default_factory=list)
    constraints: list[VesselNavigationConstraintEvidenceResponse] = Field(default_factory=list)


class VesselAisRouteSegmentVesselsResponse(PageResponse[VesselRouteSegmentMatchSampleResponse]):
    query_snapshot_id: str | None = None
    snapshot_hit: bool = False
    refresh_required: bool = False
    snapshot_status_code: str | None = None
    is_partial: bool = False
    error_message: str | None = None


class VesselSpatialSnapshotResponse(BaseModel):
    snapshot: VesselSpatialSnapshotMeta
    node: VesselNodeSituationSummary | None = None
    route: VesselRouteSituationSummary | None = None
    segments: list[VesselRouteSegmentObservationResponse] = Field(default_factory=list)
    constraints: list[VesselNavigationConstraintEvidenceResponse] = Field(default_factory=list)


class VesselNavigationConstraintResponse(BaseModel):
    generated_at: datetime
    context_type_code: str
    context_id: int
    source_status: str = "AVAILABLE"
    uncertainty_notes: list[str] = Field(default_factory=list)
    items: list[VesselNavigationConstraintEvidenceResponse] = Field(default_factory=list)


class VesselCandidateAnalysisAnnotationResponse(BaseModel):
    id: int
    analysis_id: int
    item_id: int
    annotation_type_code: str
    comment: str | None = None
    created_by: int | None = None
    created_at: datetime
    source_version: dict[str, Any] = Field(default_factory=dict)


class VesselCandidateAnalysisItemResponse(BaseModel):
    id: int
    analysis_id: int
    vessel_profile_id: int | None = None
    mmsi: str | None = None
    ship_name: str | None = None
    ship_type_code: str | None = None
    deadweight_ton: Decimal | None = None
    design_draft_m: Decimal | None = None
    latest_position_time: datetime | None = None
    ais_freshness_level: str = "UNKNOWN"
    risk_level: str = "UNKNOWN"
    quality_level: str = "UNKNOWN"
    fit_score: Decimal = Decimal("0")
    candidate_value_level: str = "LOW"
    confidence_level: str = "UNKNOWN"
    node_distance_km: Decimal | None = None
    route_match_score: Decimal | None = None
    direction_consistency: Decimal | None = None
    constraint_status_code: str | None = None
    score_parts: dict[str, Any] = Field(default_factory=dict)
    risk_reasons: list[str] = Field(default_factory=list)
    uncertainty_reasons: list[str] = Field(default_factory=list)
    not_computable_reasons: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    annotations: list[VesselCandidateAnalysisAnnotationResponse] = Field(default_factory=list)


class VesselCandidateAnalysisResponse(BaseModel):
    id: int
    context_type_code: str
    source_layer_code: str
    freight_id: int | None = None
    freight_candidate_id: int | None = None
    origin_node_id: int | None = None
    destination_node_id: int | None = None
    route_id: int | None = None
    line_id: int | None = None
    origin_city_code: str | None = None
    destination_city_code: str | None = None
    region_id: int | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    filters: dict[str, Any] = Field(default_factory=dict)
    source_ais_snapshot_id: str | None = None
    source_spatial_snapshot_id: str | None = None
    query_hash: str
    status_code: str
    coverage_rate: Decimal | None = None
    confidence_level: str
    candidate_count: int = 0
    low_confidence_count: int = 0
    not_computable_reasons: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    generated_at: datetime
    expires_at: datetime | None = None
    items: list[VesselCandidateAnalysisItemResponse] = Field(default_factory=list)


class VesselBusinessSituationCardResponse(BaseModel):
    vessel_id: int
    generated_at: datetime
    identity: dict[str, Any]
    realtime: dict[str, Any]
    operation: dict[str, Any]
    compliance: dict[str, Any]
    business: dict[str, Any]


class VesselAisSituationCardResponse(BaseModel):
    vessel_id: int
    generated_at: datetime
    data_sources: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    identity: dict[str, Any]
    realtime: dict[str, Any]
    data_availability: dict[str, Any]
    quality: dict[str, Any]


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
