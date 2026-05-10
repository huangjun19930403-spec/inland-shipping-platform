"""Vessel relation schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.modules.vessel.schema_parts.base import *  # noqa: F401,F403
from app.modules.vessel.schema_parts.recognition import *  # noqa: F401,F403


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

class VesselOwnerTransferRequest(StrictBaseModel):
    new_owner_name: str = Field(min_length=1, max_length=128)
    party_type_code: str = Field(default="UNKNOWN", min_length=1, max_length=64)
    transfer_date: date | None = None
    certificate_no: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=256)
    remark: str | None = Field(default=None, max_length=512)

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

class VesselEvidenceConclusionRefResponse(BaseModel):
    conclusion_id: int
    conclusion_type: str
    conclusion_status_code: str
    conclusion_status_name: str | None = None
    role: str = "REFERENCED"
    display_name: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None

class VesselRelationEvidenceAttachmentResponse(BaseModel):
    id: int
    vessel_profile_id: int
    evidence_type_code: str
    evidence_id: int
    storage_file_id: int
    file_name: str
    content_type: str
    file_size: int
    uploaded_by: int | None = None
    uploaded_at: datetime
    created_at: datetime
    voided_at: datetime | None = None
    voided_by: int | None = None
    void_reason: str | None = None
    download_url: str | None = None

class VesselRelationConclusionConflictResolveRequest(StrictBaseModel):
    accepted_conclusion_id: int | None = None
    conflict_reason: str = Field(min_length=1, max_length=500)
    mark_unaccepted_as: str = Field(default="CONFLICTED", max_length=32)

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
    conclusion_refs: list[VesselEvidenceConclusionRefResponse] = Field(default_factory=list)
    evidence_completeness: str = "PARTIAL"
    missing_required_fields: list[str] = Field(default_factory=list)
    attachments: list[VesselRelationEvidenceAttachmentResponse] = Field(default_factory=list)
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
    conclusion_refs: list[VesselEvidenceConclusionRefResponse] = Field(default_factory=list)
    evidence_completeness: str = "PARTIAL"
    missing_required_fields: list[str] = Field(default_factory=list)
    attachments: list[VesselRelationEvidenceAttachmentResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

class VesselControllerConclusionResponse(BaseModel):
    id: int
    vessel_profile_id: int
    conclusion_status_code: str
    conclusion_status_name: str | None = None
    party_name: str
    controller_role_code: str
    controller_role_name: str | None = None
    confidence_level: str
    confidence_level_name: str | None = None
    evidence_ids_json: list[Any] | None = None
    evidence_count: int = 0
    conflict_reason: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    confirmed_at: datetime | None = None
    confirmed_by: int | None = None
    voided_at: datetime | None = None
    voided_by: int | None = None
    void_reason: str | None = None
    revision: int
    created_at: datetime
    updated_at: datetime

class VesselAffiliationConclusionResponse(BaseModel):
    id: int
    vessel_profile_id: int
    conclusion_status_code: str
    conclusion_status_name: str | None = None
    affiliation_type_code: str
    affiliation_type_name: str | None = None
    subject_name: str | None = None
    counterparty_name: str | None = None
    confidence_level: str
    confidence_level_name: str | None = None
    evidence_ids_json: list[Any] | None = None
    evidence_count: int = 0
    conflict_reason: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    confirmed_at: datetime | None = None
    confirmed_by: int | None = None
    voided_at: datetime | None = None
    voided_by: int | None = None
    void_reason: str | None = None
    revision: int
    created_at: datetime
    updated_at: datetime

class VesselRelationConclusionSummaryResponse(BaseModel):
    vessel_profile_id: int
    controller_conclusions: list[VesselControllerConclusionResponse] = Field(default_factory=list)
    affiliation_conclusions: list[VesselAffiliationConclusionResponse] = Field(default_factory=list)
