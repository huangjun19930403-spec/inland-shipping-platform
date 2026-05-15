from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class AsyncTaskRun(Base, TimestampMixin):
    __tablename__ = "async_task_run"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    task_title: Mapped[str] = mapped_column(String(128), nullable=False)
    celery_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    queue_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    business_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    business_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    business_no: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    status_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    stage_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stage_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    stage_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requested_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    triggered_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    extra_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
