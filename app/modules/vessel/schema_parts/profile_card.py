"""Vessel profile_card schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.modules.vessel.schema_parts.base import *  # noqa: F401,F403
from app.modules.vessel.schema_parts.governance import *  # noqa: F401,F403


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
    message: str = "候选船舶分析将在 Round 8 接入"
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
    display_fields: list[dict[str, Any]] = Field(default_factory=list)
    recommended_actions: list[VesselRecommendedAction] = Field(default_factory=list)
    evidence_completeness: str | None = None
    missing_required_fields: list[str] = Field(default_factory=list)
    attachment_refs: list[Any] = Field(default_factory=list)
    audit_history: list[dict[str, Any]] = Field(default_factory=list)
    conclusion_refs: list[dict[str, Any]] = Field(default_factory=list)

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
    pending_work_items: list[VesselWorkbenchItemResponse] = Field(default_factory=list)
