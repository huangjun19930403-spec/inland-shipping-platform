from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuditFlowMixin, Base, SoftDeleteMixin, TimestampMixin


class AdminRegion(Base, TimestampMixin):
    __tablename__ = "admin_region"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(12), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pinyin: Mapped[str | None] = mapped_column(String(128), nullable=True)
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    parent_code: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    full_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    province_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    city_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    district_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(11, 8), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 8), nullable=True)
    center_address: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AdminRegionBoundary(Base, TimestampMixin):
    __tablename__ = "admin_region_boundary"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    admin_region_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("admin_region.id"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    boundary_source_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    geometry_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    center_longitude: Mapped[float | None] = mapped_column(Numeric(11, 8), nullable=True)
    center_latitude: Mapped[float | None] = mapped_column(Numeric(10, 8), nullable=True)
    area_km2: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    effective_from: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    effective_to: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    imported_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    imported_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)


class Region(Base, TimestampMixin, SoftDeleteMixin, AuditFlowMixin):
    __tablename__ = "region"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    region_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    current_boundary_version_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )


class RegionBoundaryVersion(Base, TimestampMixin):
    __tablename__ = "region_boundary_version"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    region_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("region.id"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    boundary_source_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    geometry_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    center_longitude: Mapped[float | None] = mapped_column(Numeric(11, 8), nullable=True)
    center_latitude: Mapped[float | None] = mapped_column(Numeric(10, 8), nullable=True)
    area_km2: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    effective_from: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    effective_to: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    approved_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    approved_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)


class RegionCityRelation(Base, TimestampMixin):
    __tablename__ = "region_city_relation"
    __table_args__ = (
        UniqueConstraint("region_id", "city_region_id", name="uk_region_city"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    region_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("region.id"), nullable=False, index=True
    )
    city_region_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("admin_region.id"), nullable=False, index=True
    )
    relation_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TransportNode(Base, TimestampMixin, SoftDeleteMixin, AuditFlowMixin):
    __tablename__ = "transport_node"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    node_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    province_code: Mapped[str] = mapped_column(String(12), nullable=False)
    city_code: Mapped[str] = mapped_column(String(12), nullable=False)
    district_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    city_region_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("admin_region.id"), nullable=False, index=True
    )
    address: Mapped[str | None] = mapped_column(String(256), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(11, 8), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 8), nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    lifecycle_status_code: Mapped[str] = mapped_column(String(64), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_hot_node: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class TransportNodeProfile(Base):
    __tablename__ = "transport_node_profile"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("transport_node.id"), unique=True, nullable=False
    )
    business_nature_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    channel_depth_m: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    max_draft_m: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    berth_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    annual_throughput_ton: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    open_hours_desc: Mapped[str | None] = mapped_column(String(128), nullable=True)
    contact_person: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ext_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[DateTime] = mapped_column(DateTime, nullable=False)


class NodeAlias(Base, TimestampMixin):
    __tablename__ = "node_alias"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("transport_node.id"), nullable=False, index=True
    )
    alias_name: Mapped[str] = mapped_column(String(128), nullable=False)
    alias_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class TransportNodeBusinessCategory(Base):
    __tablename__ = "transport_node_business_category"
    __table_args__ = (
        UniqueConstraint("node_id", "business_category_code", name="uk_node_biz_cat"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("transport_node.id"), nullable=False, index=True
    )
    business_category_code: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, nullable=False)


class TransportNodePackagingForm(Base):
    __tablename__ = "transport_node_packaging_form"
    __table_args__ = (
        UniqueConstraint("node_id", "packaging_form_code", name="uk_node_packaging"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("transport_node.id"), nullable=False, index=True
    )
    packaging_form_code: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, nullable=False)


class TransportNodeHandlingMode(Base):
    __tablename__ = "transport_node_handling_mode"
    __table_args__ = (
        UniqueConstraint("node_id", "handling_mode_code", name="uk_node_handling"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("transport_node.id"), nullable=False, index=True
    )
    handling_mode_code: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, nullable=False)


class NavigationConstraintPoint(Base, TimestampMixin):
    __tablename__ = "navigation_constraint_point"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    constraint_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    province_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    city_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    longitude: Mapped[float] = mapped_column(Numeric(11, 8), nullable=False)
    latitude: Mapped[float] = mapped_column(Numeric(10, 8), nullable=False)
    valid_from: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    valid_to: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    severity_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
