from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class StdDict(Base, TimestampMixin):
    __tablename__ = "std_dict"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dict_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    dict_name: Mapped[str] = mapped_column(String(128), nullable=False)
    dict_name_en: Mapped[str | None] = mapped_column(String(256), nullable=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class StdDictItem(Base, TimestampMixin):
    __tablename__ = "std_dict_item"
    __table_args__ = (UniqueConstraint("dict_id", "item_code", name="uk_dict_item"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dict_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("std_dict.id"), nullable=False, index=True
    )
    item_code: Mapped[str] = mapped_column(String(64), nullable=False)
    item_name: Mapped[str] = mapped_column(String(128), nullable=False)
    item_name_en: Mapped[str | None] = mapped_column(String(256), nullable=True)
    parent_item_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("std_dict_item.id"), nullable=True
    )
    item_value: Mapped[str | None] = mapped_column(String(128), nullable=True)
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ext_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
