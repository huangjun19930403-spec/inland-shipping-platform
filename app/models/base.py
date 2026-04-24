from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditFlowMixin:
    audit_status: Mapped[str] = mapped_column(nullable=False, default="PENDING")
    submitter_id: Mapped[int | None] = mapped_column(nullable=True)
    auditor_id: Mapped[int | None] = mapped_column(nullable=True)
    audited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
