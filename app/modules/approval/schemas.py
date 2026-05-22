"""Approval center schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResponse(BaseModel, Generic[T]):
    total: int
    page: int
    page_size: int
    items: list[T]


class ApprovalSubjectDefinitionBase(BaseModel):
    subject_type: str = Field(min_length=1, max_length=96)
    subject_name: str = Field(min_length=1, max_length=128)
    module_code: str = Field(min_length=1, max_length=64)
    detail_path_template: str | None = Field(default=None, max_length=256)
    read_permission_code: str | None = Field(default=None, max_length=96)
    submit_permission_code: str | None = Field(default=None, max_length=96)
    status_code: str = Field(default="ACTIVE", max_length=32)
    summary_schema_json: dict | None = None


class ApprovalSubjectDefinitionCreateRequest(ApprovalSubjectDefinitionBase):
    pass


class ApprovalSubjectDefinitionUpdateRequest(BaseModel):
    subject_name: str | None = Field(default=None, min_length=1, max_length=128)
    module_code: str | None = Field(default=None, min_length=1, max_length=64)
    detail_path_template: str | None = Field(default=None, max_length=256)
    read_permission_code: str | None = Field(default=None, max_length=96)
    submit_permission_code: str | None = Field(default=None, max_length=96)
    status_code: str | None = Field(default=None, max_length=32)
    summary_schema_json: dict | None = None


class ApprovalSubjectDefinitionResponse(ApprovalSubjectDefinitionBase):
    id: int
    created_at: datetime
    updated_at: datetime


class ApprovalStepDefinitionPayload(BaseModel):
    step_key: str = Field(min_length=1, max_length=96)
    step_order: int = Field(ge=1)
    step_name: str = Field(min_length=1, max_length=128)
    step_type: str = Field(default="HUMAN", max_length=32)
    assignment_type: str = Field(default="PERMISSION", max_length=64)
    assignee_user_id: int | None = None
    assignee_role_code: str | None = Field(default=None, max_length=96)
    assignee_permission_code: str | None = Field(default=None, max_length=96)
    action_policy: str = Field(default="ANY_ONE", max_length=32)
    condition_json: dict | None = None
    sla_hours: int | None = Field(default=None, ge=1)


class ApprovalStepDefinitionResponse(ApprovalStepDefinitionPayload):
    id: int
    flow_id: int
    created_at: datetime
    updated_at: datetime


class ApprovalFlowDefinitionBase(BaseModel):
    flow_code: str = Field(min_length=1, max_length=96)
    flow_name: str = Field(min_length=1, max_length=128)
    subject_type: str = Field(min_length=1, max_length=96)
    trigger_action_code: str = Field(min_length=1, max_length=64)
    engine_type: str = Field(default="CONFIG", max_length=32)
    approval_mode: str = Field(default="SINGLE", max_length=32)
    status_code: str = Field(default="DRAFT", max_length=32)
    spiff_spec_id: str | None = Field(default=None, max_length=128)
    config_json: dict | None = None


class ApprovalFlowDefinitionCreateRequest(ApprovalFlowDefinitionBase):
    steps: list[ApprovalStepDefinitionPayload] = Field(default_factory=list)


class ApprovalFlowDefinitionUpdateRequest(BaseModel):
    flow_name: str | None = Field(default=None, min_length=1, max_length=128)
    subject_type: str | None = Field(default=None, min_length=1, max_length=96)
    trigger_action_code: str | None = Field(default=None, min_length=1, max_length=64)
    engine_type: str | None = Field(default=None, max_length=32)
    approval_mode: str | None = Field(default=None, max_length=32)
    status_code: str | None = Field(default=None, max_length=32)
    spiff_spec_id: str | None = Field(default=None, max_length=128)
    config_json: dict | None = None
    steps: list[ApprovalStepDefinitionPayload] | None = None


class ApprovalFlowDefinitionResponse(ApprovalFlowDefinitionBase):
    id: int
    created_at: datetime
    updated_at: datetime
    steps: list[ApprovalStepDefinitionResponse] = Field(default_factory=list)


class ApprovalFlowDefinitionListQuery(BaseModel):
    subject_type: str | None = None
    trigger_action_code: str | None = None
    engine_type: str | None = None
    status_code: str | None = None
    keyword: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class ApprovalInstanceSubmitRequest(BaseModel):
    subject_type: str = Field(min_length=1, max_length=96)
    trigger_action_code: str = Field(min_length=1, max_length=64)
    subject_id: int | None = None
    subject_ref: str | None = Field(default=None, max_length=128)
    subject_code: str | None = Field(default=None, max_length=128)
    subject_name: str = Field(min_length=1, max_length=256)
    subject_path: str | None = Field(default=None, max_length=256)
    before_snapshot_json: dict | None = None
    after_snapshot_json: dict | None = None
    diff_json: dict | None = None
    summary_json: dict | None = None
    submit_payload_json: dict | None = None
    idempotency_key: str = Field(min_length=1, max_length=256)


class ApprovalInstanceListQuery(BaseModel):
    tab: str | None = None
    subject_type: str | None = None
    flow_code: str | None = None
    status_code: str | None = None
    submitter_id: int | None = None
    actor_id: int | None = None
    submitted_from: datetime | None = None
    submitted_to: datetime | None = None
    keyword: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class ApprovalActionRequest(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)
    request_id: str | None = Field(default=None, max_length=128)


class ApprovalAssignRequest(BaseModel):
    assignee_user_id: int | None = None
    assignee_role_code: str | None = Field(default=None, max_length=96)
    assignee_permission_code: str | None = Field(default=None, max_length=96)
    comment: str | None = Field(default=None, max_length=2000)
    request_id: str | None = Field(default=None, max_length=128)


class ApprovalStepInstanceResponse(BaseModel):
    id: int
    instance_id: int
    step_key: str
    step_order: int
    step_name: str
    status_code: str
    candidate_user_id: int | None = None
    candidate_role_code: str | None = None
    candidate_permission_code: str | None = None
    actor_id: int | None = None
    comment: str | None = None
    started_at: datetime | None = None
    acted_at: datetime | None = None
    sla_hours: int | None = None


class ApprovalActionLogResponse(BaseModel):
    id: int
    instance_id: int
    step_instance_id: int | None = None
    action_code: str
    operator_id: int | None = None
    from_status_code: str | None = None
    to_status_code: str | None = None
    comment: str | None = None
    request_id: str | None = None
    created_at: datetime


class ApprovalSnapshotResponse(BaseModel):
    before_snapshot_json: dict | None = None
    after_snapshot_json: dict | None = None
    diff_json: dict | None = None
    summary_json: dict | None = None
    submit_payload_json: dict | None = None


class ApprovalCandidateResponse(BaseModel):
    user_id: int | None = None
    role_code: str | None = None
    permission_code: str | None = None
    display_name: str


class ApprovalInstanceResponse(BaseModel):
    id: int
    instance_no: str
    flow_id: int
    flow_code: str
    flow_name: str | None = None
    subject_type: str
    subject_id: int | None = None
    subject_ref: str | None = None
    subject_code: str | None = None
    subject_name: str
    subject_path: str | None = None
    trigger_action_code: str
    status_code: str
    current_step_instance_id: int | None = None
    current_step_name: str | None = None
    submitter_id: int | None = None
    submitted_at: datetime
    completed_at: datetime | None = None
    engine_type: str
    lock_version: int
    created_at: datetime
    updated_at: datetime
    available_actions: list[str] = Field(default_factory=list)
    current_candidates: list[ApprovalCandidateResponse] = Field(default_factory=list)


class ApprovalInstanceDetailResponse(BaseModel):
    instance: ApprovalInstanceResponse
    snapshot: ApprovalSnapshotResponse | None = None
    steps: list[ApprovalStepInstanceResponse] = Field(default_factory=list)
    action_logs: list[ApprovalActionLogResponse] = Field(default_factory=list)
    flow_definition: ApprovalFlowDefinitionResponse | None = None


class ApprovalPendingCountResponse(BaseModel):
    pending_count: int


class ApprovalMetadataResponse(BaseModel):
    statuses: list[dict]
    actions: list[dict]
    engines: list[dict]
    assignment_types: list[dict]
    step_types: list[dict]
    action_policies: list[dict]
    subject_definitions: list[ApprovalSubjectDefinitionResponse] = Field(default_factory=list)
    flow_definitions: list[ApprovalFlowDefinitionResponse] = Field(default_factory=list)
