"""Vessel quality schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.modules.vessel.schema_parts.base import *  # noqa: F401,F403


class VesselQualityIssueQuery(BaseModel):
    status_code: str | None = None
    issue_type_code: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)

class VesselQualityIssueGlobalQuery(VesselQualityIssueQuery):
    severity_code: str | None = None
    vessel_id: int | None = Field(default=None, ge=1)
    keyword: str | None = Field(default=None, max_length=64)

class VesselQualityIssueResponse(VesselGovernanceContextMixin):
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
    governance_task_id: int | None = None
    governance_task_no: str | None = None
    governance_task_status_code: str | None = None
    governance_task_assigned_to: int | None = None
    action_path: str | None = None
    field_anchor: str | None = None
    recommended_actions: list["VesselRecommendedAction"] = Field(default_factory=list)
    verification_status_code: str = "NOT_VERIFIED"
    verification_message: str | None = None
    last_rechecked_at: datetime | None = None
    last_recheck_status_code: str | None = None
    last_recheck_message: str | None = None

class VesselQualityIssueRecheckResponse(BaseModel):
    issue_id: int
    status_code: str
    recheck_status_code: str
    recheck_message: str
    resolved: bool = False
    rechecked_at: datetime
    governance_task_id: int | None = None
    governance_task_status_code: str | None = None

class VesselQualityIssueBatchRecheckRequest(StrictBaseModel):
    issue_ids: list[int] = Field(default_factory=list, max_length=200)
    vessel_id: int | None = Field(default=None, ge=1)
    status_code: str | None = Field(default="OPEN", max_length=32)

class VesselQualityIssueBatchRecheckResponse(BaseModel):
    total_count: int
    passed_count: int
    failed_count: int
    resolved_count: int
    results: list[VesselQualityIssueRecheckResponse] = Field(default_factory=list)

class VesselQualityIssueVesselSummary(BaseModel):
    id: int
    ship_name: str
    current_mmsi: str
    vessel_profile_code: str
    profile_status_code: str
    profile_status_name: str | None = None

class VesselQualityIssueListItemResponse(VesselQualityIssueResponse):
    vessel: VesselQualityIssueVesselSummary | None = None
