"""Vessel governance schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.modules.vessel.schema_parts.base import *  # noqa: F401,F403
from app.modules.vessel.schema_parts.quality import *  # noqa: F401,F403


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
    target_path: str | None = None
    target_query: dict[str, Any] = Field(default_factory=dict)
    recommended_actions: list[VesselRecommendedAction] = Field(default_factory=list)

class VesselWorkbenchItemResponse(BaseModel):
    code: str
    title: str
    count: int = 0
    priority_code: str = "MEDIUM"
    target_path: str | None = None
    target_query: dict[str, Any] = Field(default_factory=dict)
    explain_reason: str | None = None
    evidence_gaps: list[str] = Field(default_factory=list)
    source_object_anchor: str | None = None
    workbench_group: str | None = None
    recommended_actions: list[VesselRecommendedAction] = Field(default_factory=list)
    sla_due_at: datetime | None = None
    overdue_level: str | None = None
    assignee_load: int | None = None
    today_priority_score: int | None = None

class VesselGovernanceDashboardResponse(BaseModel):
    generated_at: datetime
    source_layer_code: str = "GOVERNANCE_TASK"
    coverage_rate: Decimal | None = None
    confidence_level: str = "UNKNOWN"
    latest_success_at: datetime | None = None
    metrics: list[VesselGovernanceDashboardMetric] = Field(default_factory=list)
    work_items: list[VesselWorkbenchItemResponse] = Field(default_factory=list)

class VesselGovernanceTaskSyncResponse(BaseModel):
    batch_id: int | None = None
    batch_no: str | None = None
    synced_at: datetime
    touched_count: int
    created_task_count: int = 0
    reopened_task_count: int = 0
    skipped_count: int = 0
    source_rules: list[str] = Field(default_factory=list)
    rule_results: dict[str, Any] = Field(default_factory=dict)
    affected_scope: dict[str, Any] = Field(default_factory=dict)
    message: str

class VesselGovernanceSyncBatchResponse(BaseModel):
    id: int
    batch_no: str
    trigger_type_code: str
    triggered_by: int | None = None
    status_code: str
    source_rules_json: list[Any] | None = None
    rule_result_json: dict[str, Any] | None = None
    affected_scope_json: dict[str, Any] | None = None
    touched_count: int = 0
    created_task_count: int = 0
    reopened_task_count: int = 0
    skipped_count: int = 0
    started_at: datetime
    finished_at: datetime | None = None
    message: str | None = None
    created_at: datetime
    updated_at: datetime

class VesselGovernanceRuleResponse(BaseModel):
    rule_code: str
    rule_name: str
    source_object_type: str
    task_type_code: str
    default_priority_code: str
    generation_reason: str
    validation_entrypoint: str | None = None
    close_policy: str
    target_path: str
    evidence_requirements: list[str] = Field(default_factory=list)

class VesselGovernanceTaskQuery(BaseModel):
    status_code: str | None = None
    task_type_code: str | None = None
    priority_code: str | None = None
    vessel_id: int | None = Field(default=None, ge=1)
    source_object_type: str | None = None
    assigned_to: int | None = None
    keyword: str | None = Field(default=None, max_length=128)
    auto_sync: bool = False
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

class VesselGovernanceTaskActionRequest(StrictBaseModel):
    action_code: str = Field(min_length=1, max_length=32)
    revision: int = Field(ge=1)
    assigned_to: int | None = None
    reason: str | None = Field(default=None, max_length=1000)
    evidence_json: dict[str, Any] | None = None

class VesselGovernanceTaskResponse(VesselGovernanceContextMixin):
    id: int
    task_no: str
    task_type_code: str
    task_type_name: str | None = None
    priority_code: str
    priority_name: str | None = None
    status_code: str
    status_name: str | None = None
    vessel_profile_id: int | None = None
    source_batch_id: int | None = None
    source_rule_code: str | None = None
    source_object_type: str
    source_object_id: str
    source_status_code: str | None = None
    source_fingerprint: str | None = None
    fingerprint: str
    title: str
    description: str | None = None
    evidence_summary: str | None = None
    source_trace_json: list[Any] | None = None
    generation_reason_json: dict[str, Any] | None = None
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
    action_path: str | None = None
    field_anchor: str | None = None
    recommended_actions: list[VesselRecommendedAction] = Field(default_factory=list)
    verification_status_code: str = "NOT_VERIFIED"
    verification_message: str | None = None
    approval_instance_id: int | None = None
    approval_instance_no: str | None = None
    approval_status_code: str | None = None
    approval_status_name: str | None = None
    approval_action_path: str | None = None
    business_sync_status_code: str | None = None
    business_sync_message: str | None = None
    sla_due_at: datetime | None = None
    overdue_level: str | None = None
    assignee_load: int | None = None
    today_priority_score: int | None = None
    validation_entrypoint: str | None = None

class VesselBlacklistSignalGlobalQuery(BaseModel):
    signal_id: int | None = Field(default=None, ge=1)
    vessel_id: int | None = Field(default=None, ge=1)
    list_type_code: str | None = None
    status_code: str | None = None
    risk_level: str | None = None
    keyword: str | None = Field(default=None, max_length=128)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

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

class VesselBlacklistSignalListItemResponse(VesselBlacklistSignalResponse):
    vessel: VesselQualityIssueVesselSummary | None = None
    governance_task_id: int | None = None
    governance_task_no: str | None = None
    governance_task_status_code: str | None = None
    governance_task_assigned_to: int | None = None
    risk_signal_id: int | None = None
    risk_signal_status_code: str | None = None
    risk_signal_level: str | None = None
