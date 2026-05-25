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

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


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
    longitude: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
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
    center_longitude: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    center_latitude: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    area_km2: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    effective_from: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    effective_to: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    imported_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    imported_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)


class NavigationChannel(Base, TimestampMixin):
    __tablename__ = "navigation_channel"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    channel_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    channel_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    official_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    alias_names: Mapped[list | None] = mapped_column(JSON, nullable=True)
    parent_channel_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    channel_type_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    planning_level_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    planning_basis_code: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    start_place: Mapped[str | None] = mapped_column(String(128), nullable=True)
    end_place: Mapped[str | None] = mapped_column(String(128), nullable=True)
    via_city_names: Mapped[list | None] = mapped_column(JSON, nullable=True)
    via_port_names: Mapped[list | None] = mapped_column(JSON, nullable=True)
    technical_grade_current_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    technical_grade_planned_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    ais_scope_code: Mapped[str] = mapped_column(String(32), nullable=False, default="INCLUDED", index=True)
    display_priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    segment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_summary: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_audit_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class NavigationChannelBoundary(Base, TimestampMixin):
    __tablename__ = "navigation_channel_boundary"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("navigation_channel.id"), nullable=False, index=True
    )
    geometry_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    boundary_paths_low: Mapped[list | None] = mapped_column(JSON, nullable=True)
    boundary_paths_medium: Mapped[list | None] = mapped_column(JSON, nullable=True)
    boundary_paths_high: Mapped[list | None] = mapped_column(JSON, nullable=True)
    center_longitude: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    center_latitude: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    display_center_longitude: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    display_center_latitude: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    bbox_min_lng: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    bbox_min_lat: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    bbox_max_lng: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    bbox_max_lat: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    source_shape_length_degree: Mapped[float | None] = mapped_column(Numeric(30, 18), nullable=True)
    source_shape_area_degree: Mapped[float | None] = mapped_column(Numeric(30, 18), nullable=True)
    ring_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    point_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    geometry_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="AVAILABLE", index=True)
    boundary_quality_code: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    connectivity_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    repair_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="NONE", index=True)
    coverage_policy_code: Mapped[str] = mapped_column(String(64), nullable=False, default="CHANNEL_CORRIDOR_ENVELOPE")
    geometry_coordinate_system_code: Mapped[str] = mapped_column(String(16), nullable=False, default="WGS84")
    boundary_coordinate_system_code: Mapped[str] = mapped_column(String(16), nullable=False, default="GCJ02")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    imported_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)


class NavigationChannelSegment(Base, TimestampMixin):
    __tablename__ = "navigation_channel_segment"
    __table_args__ = (
        UniqueConstraint("channel_id", "segment_code", name="uk_navigation_channel_segment_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("navigation_channel.id"), nullable=False, index=True
    )
    segment_code: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    segment_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    segment_kind_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    start_place: Mapped[str | None] = mapped_column(String(128), nullable=True)
    end_place: Mapped[str | None] = mapped_column(String(128), nullable=True)
    via_city_names: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_water_names: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_summary: Mapped[str | None] = mapped_column(String(512), nullable=True)
    geometry_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    boundary_quality_code: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    connectivity_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    repair_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="NONE", index=True)
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class NavigationChannelSourceAudit(Base, TimestampMixin):
    __tablename__ = "navigation_channel_source_audit"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    channel_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("navigation_channel.id"), nullable=True, index=True
    )
    segment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("navigation_channel_segment.id"), nullable=True, index=True
    )
    channel_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    segment_code: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    source_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    source_layer_name: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    source_object_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_level: Mapped[int | None] = mapped_column(SmallInteger, nullable=True, index=True)
    decision_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    role_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reason_code: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    source_remark: Mapped[str | None] = mapped_column(String(512), nullable=True)
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)


class Region(Base, TimestampMixin, SoftDeleteMixin):
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
    center_longitude: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    center_latitude: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
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


class TransportNode(Base, TimestampMixin, SoftDeleteMixin):
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
    longitude: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
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
    ext_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[DateTime] = mapped_column(DateTime, nullable=False)


class TransportNodeContact(Base, TimestampMixin):
    __tablename__ = "transport_node_contact"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("transport_node.id"), nullable=False, index=True
    )
    contact_name: Mapped[str] = mapped_column(String(64), nullable=False)
    contact_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    mobile_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    wechat: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)


class TransportNodePhoto(Base, TimestampMixin):
    __tablename__ = "transport_node_photo"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("transport_node.id"), nullable=False, index=True
    )
    file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("storage_file.id"), nullable=False, index=True
    )
    photo_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    photo_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


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
    longitude: Mapped[float] = mapped_column(Numeric(24, 15), nullable=False)
    latitude: Mapped[float] = mapped_column(Numeric(24, 15), nullable=False)
    valid_from: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    valid_to: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    severity_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)


class NavigationConstraintProfile(Base, TimestampMixin):
    __tablename__ = "navigation_constraint_profile"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    constraint_point_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("navigation_constraint_point.id"), unique=True, nullable=False, index=True
    )
    max_tonnage: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    max_allowed_draft_m: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    min_water_depth_m: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    under_keel_clearance_m: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    max_air_draft_m: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    max_beam_m: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    max_length_m: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    allowed_time_window: Mapped[str | None] = mapped_column(String(256), nullable=True)
    restriction_rule_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rule_description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    warning_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
