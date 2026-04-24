from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class AuditTask(Base, TimestampMixin):
    __tablename__ = "audit_task"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    biz_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    biz_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    biz_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    submitter_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    current_handler_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    audit_status: Mapped[str] = mapped_column(String(32), nullable=False)
    audit_remark: Mapped[str | None] = mapped_column(String(512), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditRecord(Base):
    __tablename__ = "audit_record"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("audit_task.id"), nullable=False, index=True
    )
    action_code: Mapped[str] = mapped_column(String(64), nullable=False)
    operator_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    from_status_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_status_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
