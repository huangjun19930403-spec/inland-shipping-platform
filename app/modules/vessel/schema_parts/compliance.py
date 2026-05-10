"""Vessel compliance schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.modules.vessel.schema_parts.base import *  # noqa: F401,F403


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

class VesselRiskSignalResponse(VesselGovernanceContextMixin):
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
    recommended_actions: list[VesselRecommendedAction] = Field(default_factory=list)
    verification_status_code: str = "NOT_VERIFIED"
    verification_message: str | None = None
    proof_chain: list[dict[str, Any]] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    review_action_path: str | None = None
    validation_entrypoint: str | None = None

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
    audit_task_id: int | None = None
    audit_task_no: str | None = None
    audit_status_code: str | None = None
    audit_action_path: str | None = None

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
    proof_chain: list[dict[str, Any]] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    review_action_path: str | None = None
