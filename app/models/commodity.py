from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class CommodityCategory(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "commodity_category"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CommodityType(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "commodity_type"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("commodity_category.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CommodityStandard(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "commodity_standard"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    category_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("commodity_category.id"), nullable=True, index=True
    )
    type_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("commodity_type.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    english_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    main_unit_code: Mapped[str] = mapped_column(String(32), nullable=False)
    specification: Mapped[str | None] = mapped_column(String(256), nullable=True)
    cargo_form_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    density_range_desc: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dangerous_grade_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_bulk_cargo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_container_suitable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_hazardous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pollution_risk_level_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    loading_requirement: Mapped[str | None] = mapped_column(Text, nullable=True)
    unloading_requirement: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_requirement: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="MANUAL")
    recognition_priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    alias_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="COMMON_NAME")
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    match_weight: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)


class CommodityRecognitionRecord(Base, TimestampMixin):
    __tablename__ = "commodity_recognition_record"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    raw_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    normalized_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    context_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_hint_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("commodity_category.id"), nullable=True, index=True
    )
    type_hint_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("commodity_type.id"), nullable=True, index=True
    )
    request_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    deterministic_result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ai_result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    suggestion_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="COMPLETED", index=True)
    ai_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="SKIPPED")
    ai_error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    adopted_action_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    adopted_standard_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("commodity_standard.id"), nullable=True, index=True
    )
    adopted_alias_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("commodity_alias.id"), nullable=True, index=True
    )
    adopted_by_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("sys_user.id"), nullable=True, index=True)
    adopted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CommodityAttributeDefinition(Base, TimestampMixin):
    __tablename__ = "commodity_attribute_definition"
    __table_args__ = (
        UniqueConstraint("attribute_code", name="uk_commodity_attribute_definition_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    attribute_code: Mapped[str] = mapped_column(String(64), nullable=False)
    attribute_name: Mapped[str] = mapped_column(String(128), nullable=False)
    attribute_group_code: Mapped[str] = mapped_column(String(64), nullable=False)
    value_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    unit_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    option_dict_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_required_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


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
    attribute_definition_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("commodity_attribute_definition.id"), nullable=True, index=True
    )
    attribute_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attribute_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attribute_value_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attribute_value: Mapped[str | None] = mapped_column(String(512), nullable=True)
    attribute_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    default_value: Mapped[str | None] = mapped_column(String(128), nullable=True)
    value_range_desc: Mapped[str | None] = mapped_column(String(256), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CommodityStandardImage(Base, TimestampMixin):
    __tablename__ = "commodity_standard_image"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    commodity_standard_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("commodity_standard.id"), nullable=False, index=True
    )
    file_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("storage_file.id"), nullable=False, index=True)
    image_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    image_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)
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
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)
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
    rule_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="ALLOWED")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
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
    operation_side_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rule_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="ALLOWED")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
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
    rule_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="ALLOWED")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rule_desc: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
