"""audit 模块 schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResponse(BaseModel, Generic[T]):
    total: int
    page: int
    page_size: int
    items: list[T]


class AuditTaskListQuery(BaseModel):
    keyword: str | None = None
    queue_type: str | None = Field(default=None, max_length=32)
    task_type: str | None = None
    status_code: str | None = None
    object_type: str | None = None
    object_type_code: str | None = None
    object_id: int | None = None
    submitter_id: int | None = None
    assignee_user_id: int | None = None
    current_handler_id: int | None = None
    submitted_from: datetime | None = None
    submitted_to: datetime | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class AuditTaskCreateRequest(BaseModel):
    task_no: str | None = Field(default=None, max_length=32)
    task_type: str = Field(min_length=1, max_length=64)
    object_id: int
    object_type: str | None = Field(default=None, max_length=64)
    object_type_code: str | None = Field(default=None, max_length=64)
    object_code: str | None = Field(default=None, max_length=64)
    object_name: str | None = Field(default=None, max_length=256)
    change_type_code: str | None = Field(default="UPDATE", max_length=64)
    source_module_code: str | None = Field(default=None, max_length=64)
    submitter_id: int | None = None
    submitter_name: str | None = Field(default=None, max_length=64)
    assignee_user_id: int | None = None
    current_handler_name: str | None = Field(default=None, max_length=64)
    comment: str | None = Field(default=None, max_length=512)
    before_snapshot_json: dict[str, Any] | None = None
    after_snapshot_json: dict[str, Any] | None = None
    diff_json: list[dict[str, Any]] | None = None
    summary_json: dict[str, Any] | None = None


class AuditTaskAssignRequest(BaseModel):
    assignee_user_id: int


class AuditTaskActionRequest(BaseModel):
    comment: str | None = Field(default=None, max_length=512)


class AuditRecordListQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class AuditRecordResponse(BaseModel):
    id: int
    task_id: int
    action_code: str
    action_name: str
    operator_id: int | None
    operator_name: str | None = None
    from_status_code: str | None
    from_status_name: str | None = None
    to_status_code: str | None
    to_status_name: str | None = None
    remark: str | None
    created_at: datetime


class AuditMetadataOption(BaseModel):
    code: str
    name: str
    color: str | None = None


class AuditMetadataResponse(BaseModel):
    statuses: list[AuditMetadataOption]
    object_types: list[AuditMetadataOption]
    change_types: list[AuditMetadataOption]
    actions: list[AuditMetadataOption]
    source_modules: list[AuditMetadataOption]


class AuditTaskResponse(BaseModel):
    id: int
    task_no: str
    task_type: str
    task_type_name: str | None = None
    object_id: int
    object_type: str | None
    object_type_code: str | None = None
    object_type_name: str | None = None
    object_code: str | None
    object_name: str | None = None
    change_type_code: str | None = None
    change_type_name: str | None = None
    source_module_code: str | None = None
    source_module_name: str | None = None
    submitter_id: int | None
    submitter_name: str | None = None
    assignee_user_id: int | None
    current_handler_id: int | None = None
    current_handler_name: str | None = None
    status_code: str
    status_name: str | None = None
    status_color: str | None = None
    is_actionable: bool = False
    audit_remark: str | None
    submitted_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AuditTaskDetailResponse(BaseModel):
    task: AuditTaskResponse
    object_summary: dict[str, Any] = Field(default_factory=dict)
    before_snapshot: dict[str, Any] = Field(default_factory=dict)
    after_snapshot: dict[str, Any] = Field(default_factory=dict)
    diff_items: list[dict[str, Any]] = Field(default_factory=list)
    snapshot_summary: dict[str, Any] = Field(default_factory=dict)
    records: list[AuditRecordResponse]
    available_actions: list[str] = Field(default_factory=list)


class AuditPendingCountResponse(BaseModel):
    pending_count: int
