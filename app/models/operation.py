from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OperationLog(Base):
    __tablename__ = "operation_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    module_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    operation_code: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    subject_type: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    subject_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    subject_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    operator_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    before_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    detail_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
