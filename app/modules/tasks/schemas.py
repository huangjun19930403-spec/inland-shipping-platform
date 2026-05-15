"""后台任务运行账本 schema。"""

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


class AsyncTaskRunQuery(BaseModel):
    keyword: str | None = None
    task_name: str | None = None
    queue_name: str | None = None
    business_type: str | None = None
    status_code: str | None = None
    include_analysis_runs: bool = True
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class AsyncTaskRunResponse(BaseModel):
    id: int
    source_type_code: str = "CELERY"
    task_name: str
    task_title: str
    celery_task_id: str | None = None
    queue_name: str
    business_type: str
    business_id: int | None = None
    business_no: str | None = None
    idempotency_key: str | None = None
    status_code: str
    status_name: str
    stage_code: str | None = None
    stage_name: str | None = None
    stage_message: str | None = None
    progress_percent: int = 0
    attempt: int = 0
    max_retries: int = 0
    requested_by: int | None = None
    triggered_by: str | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    heartbeat_at: datetime | None = None
    error_message: str | None = None
    result_json: dict | None = None
    extra_json: dict | None = None
    retryable: bool = False
    created_at: datetime
    updated_at: datetime | None = None


class TaskRetryRequest(BaseModel):
    reason: str | None = None


class TaskRecoverStaleResponse(BaseModel):
    recovered_count: int
    stale_seconds: int
