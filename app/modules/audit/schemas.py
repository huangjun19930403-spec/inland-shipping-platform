"""audit 模块 schema。"""

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


class AuditTaskListQuery(BaseModel):
    keyword: str | None = None
    task_type: str | None = None
    status_code: str | None = None
    object_type: str | None = None
    object_id: int | None = None
    assignee_user_id: int | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class AuditTaskCreateRequest(BaseModel):
    task_no: str | None = Field(default=None, max_length=32)
    task_type: str = Field(min_length=1, max_length=64)
    object_id: int
    object_type: str | None = Field(default=None, max_length=64)
    object_code: str | None = Field(default=None, max_length=64)
    submitter_id: int | None = None
    assignee_user_id: int | None = None
    comment: str | None = Field(default=None, max_length=512)


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
    operator_id: int | None
    from_status_code: str | None
    to_status_code: str | None
    remark: str | None
    created_at: datetime


class AuditTaskResponse(BaseModel):
    id: int
    task_no: str
    task_type: str
    object_id: int
    object_type: str | None
    object_code: str | None
    submitter_id: int | None
    assignee_user_id: int | None
    status_code: str
    audit_remark: str | None
    submitted_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AuditTaskDetailResponse(BaseModel):
    task: AuditTaskResponse
    records: list[AuditRecordResponse]


class AuditPendingCountResponse(BaseModel):
    pending_count: int
