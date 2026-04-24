from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class CodeSequence(Base, TimestampMixin):
    __tablename__ = "code_sequence"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    biz_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    biz_name: Mapped[str] = mapped_column(String(128), nullable=False)
    target_table: Mapped[str] = mapped_column(String(64), nullable=False)
    target_column: Mapped[str] = mapped_column(String(64), nullable=False)
    prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    date_format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    separator: Mapped[str | None] = mapped_column(String(8), nullable=True)
    current_value: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    value_length: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    step: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reset_rule: Mapped[str] = mapped_column(String(32), nullable=False, default="NONE")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)
