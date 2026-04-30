from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuditFlowMixin, Base, SoftDeleteMixin, TimestampMixin


class CommodityCategory(Base, TimestampMixin, SoftDeleteMixin, AuditFlowMixin):
    __tablename__ = "commodity_category"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CommodityType(Base, TimestampMixin, SoftDeleteMixin, AuditFlowMixin):
    __tablename__ = "commodity_type"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("commodity_category.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CommodityStandard(Base, TimestampMixin, SoftDeleteMixin, AuditFlowMixin):
    __tablename__ = "commodity_standard"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("commodity_type.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    english_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    main_unit_code: Mapped[str] = mapped_column(String(32), nullable=False)
    density_range_desc: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dangerous_grade_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CommodityAlias(Base, TimestampMixin):
    __tablename__ = "commodity_alias"
    __table_args__ = (
        UniqueConstraint("commodity_standard_id", "alias_name", name="uk_commodity_alias"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    commodity_standard_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("commodity_standard.id"), nullable=False, index=True
    )
    alias_name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class CommodityStandardAttribute(Base, TimestampMixin):
    __tablename__ = "commodity_standard_attribute"
    __table_args__ = (
        UniqueConstraint(
            "commodity_standard_id",
            "attribute_code",
            name="uk_commodity_attribute_code",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    commodity_standard_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("commodity_standard.id"), nullable=False, index=True
    )
    attribute_code: Mapped[str] = mapped_column(String(64), nullable=False)
    attribute_name: Mapped[str] = mapped_column(String(128), nullable=False)
    attribute_value_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    attribute_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    default_value: Mapped[str | None] = mapped_column(String(128), nullable=True)
    value_range_desc: Mapped[str | None] = mapped_column(String(256), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CommodityPackagingForm(Base):
    __tablename__ = "commodity_packaging_form"
    __table_args__ = (
        UniqueConstraint(
            "commodity_standard_id",
            "packaging_form_code",
            name="uk_commodity_packaging_form",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    commodity_standard_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("commodity_standard.id"), nullable=False, index=True
    )
    packaging_form_code: Mapped[str] = mapped_column(String(64), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CommodityTransportMode(Base):
    __tablename__ = "commodity_transport_mode"
    __table_args__ = (
        UniqueConstraint(
            "commodity_standard_id",
            "transport_mode_element_code",
            name="uk_commodity_transport_mode",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    commodity_standard_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("commodity_standard.id"), nullable=False, index=True
    )
    transport_mode_element_code: Mapped[str] = mapped_column(String(64), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CommodityShipTypeRule(Base):
    __tablename__ = "commodity_ship_type_rule"
    __table_args__ = (
        UniqueConstraint(
            "commodity_standard_id", "ship_type_code", name="uk_commodity_ship_type_rule"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    commodity_standard_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("commodity_standard.id"), nullable=False, index=True
    )
    ship_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    allow_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rule_desc: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CommodityNodeTypeRule(Base):
    __tablename__ = "commodity_node_type_rule"
    __table_args__ = (
        UniqueConstraint(
            "commodity_standard_id", "node_type_code", name="uk_commodity_node_type_rule"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    commodity_standard_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("commodity_standard.id"), nullable=False, index=True
    )
    node_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    allow_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rule_desc: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CommodityHandlingModeRule(Base):
    __tablename__ = "commodity_handling_mode_rule"
    __table_args__ = (
        UniqueConstraint(
            "commodity_standard_id",
            "handling_mode_code",
            name="uk_commodity_handling_mode_rule",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    commodity_standard_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("commodity_standard.id"), nullable=False, index=True
    )
    handling_mode_code: Mapped[str] = mapped_column(String(64), nullable=False)
    allow_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rule_desc: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
