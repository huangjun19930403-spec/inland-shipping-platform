"""Vessel recognition schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.modules.vessel.schema_parts.base import *  # noqa: F401,F403
from app.modules.vessel.schema_parts.compliance import *  # noqa: F401,F403


class VesselRecognitionHistoryQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

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

class VesselCertificateImageRecognitionCreateRequest(StrictBaseModel):
    file_id: int = Field(gt=0, description="已上传证件附件对应的 storage_file_id")

class VesselCertificateImageRecognitionConfirmRequest(StrictBaseModel):
    accepted_payload_json: dict[str, Any] | None = None
    adopt_to_profile_fields: list[str] = Field(default_factory=list)
    adopt_fields: list[str] | None = None
    reason: str | None = Field(default=None, max_length=500)

class VesselRecognitionAdoptionRequest(StrictBaseModel):
    accepted_payload_json: dict[str, Any] | None = None
    adopt_fields: list[str] = Field(default_factory=list)
    adopt_to_profile_fields: list[str] = Field(default_factory=list)
    apply_to_owner: bool = True
    reason: str | None = Field(default=None, max_length=500)

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
