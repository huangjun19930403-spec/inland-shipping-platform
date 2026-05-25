from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class NavigationWaterArea(Base, TimestampMixin):
    __tablename__ = "navigation_water_area"
    __table_args__ = (
        UniqueConstraint(
            "source_code",
            "source_layer_name",
            "source_object_id",
            name="uk_navigation_water_area_source_object",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_layer_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_layer_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_layer_display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_layer_role_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_layer_order: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    source_file_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_object_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    has_attributes: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    raw_properties_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    water_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    normalized_water_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    alias_names: Mapped[list | None] = mapped_column(JSON, nullable=True)
    water_level: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    water_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="UNKNOWN", index=True)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)
    geometry_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    geometry_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="RAW", index=True)
    simplified_geometry_low_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    simplified_geometry_mid_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    simplified_geometry_high_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    bbox_min_lng: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True, index=True)
    bbox_min_lat: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True, index=True)
    bbox_max_lng: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True, index=True)
    bbox_max_lat: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True, index=True)
    center_lng: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    center_lat: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    shape_length_degree: Mapped[float | None] = mapped_column(Numeric(30, 18), nullable=True)
    shape_area_degree: Mapped[float | None] = mapped_column(Numeric(30, 18), nullable=True)
    area_km2: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    is_low_value: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)


class NavigationChannelWaterAreaMatch(Base, TimestampMixin):
    __tablename__ = "navigation_channel_water_area_match"
    __table_args__ = (
        UniqueConstraint(
            "match_batch_code",
            "channel_id",
            "water_area_id",
            name="uk_navigation_channel_water_area_match_batch_channel_area",
        ),
        Index("ix_navigation_channel_water_area_match_channel_current", "channel_id", "is_current"),
        Index("ix_navigation_channel_water_area_match_area_current", "water_area_id", "is_current"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("navigation_channel.id"), nullable=False, index=True)
    water_area_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("navigation_water_area.id"), nullable=False, index=True)
    match_batch_code: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    match_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    matched_term: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    confidence_code: Mapped[str] = mapped_column(String(64), nullable=False, default="LOW_CONFIDENCE", index=True)
    review_status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="NEED_REVIEW", index=True)
    issue_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    source_trace_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class NavigationWaterBody(Base, TimestampMixin):
    __tablename__ = "navigation_water_body"
    __table_args__ = (
        UniqueConstraint("water_body_code", name="uk_navigation_water_body_code"),
        Index("ix_navigation_water_body_role_enabled", "body_role_code", "is_enabled"),
        Index("ix_navigation_water_body_layer_order", "source_layer_order"),
        Index("ix_navigation_water_body_name", "normalized_water_name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    water_body_code: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    water_body_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    normalized_water_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    production_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    name_status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="RAW_NAMED", index=True)
    name_source_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    name_note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    body_role_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    dedupe_status_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_layer_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_layer_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    source_layer_display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_layer_role_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_layer_order: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    water_level_min: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    water_level_max: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    water_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="UNKNOWN", index=True)
    geometry_wgs84_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    geometry_gcj02_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    bbox_min_lng: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True, index=True)
    bbox_min_lat: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True, index=True)
    bbox_max_lng: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True, index=True)
    bbox_max_lat: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True, index=True)
    display_bbox_min_lng: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    display_bbox_min_lat: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    display_bbox_max_lng: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    display_bbox_max_lat: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    center_lng: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    center_lat: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    display_center_lng: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    display_center_lat: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    area_km2: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    feature_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled_feature_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repaired_feature_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_feature_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_layer_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_water_area_ids_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    quality_code: Mapped[str] = mapped_column(String(64), nullable=False, default="READY", index=True)
    coordinate_system_code: Mapped[str] = mapped_column(String(32), nullable=False, default="WGS84")
    display_coordinate_system_code: Mapped[str] = mapped_column(String(32), nullable=False, default="GCJ02_AMAP")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)


class NavigationChannelWaterBodyMatch(Base, TimestampMixin):
    __tablename__ = "navigation_channel_water_body_match"
    __table_args__ = (
        UniqueConstraint(
            "match_batch_code",
            "channel_id",
            "water_body_id",
            name="uk_navigation_channel_water_body_match_batch_channel_body",
        ),
        Index("ix_navigation_channel_water_body_match_channel_current", "channel_id", "is_current"),
        Index("ix_navigation_channel_water_body_match_body_current", "water_body_id", "is_current"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("navigation_channel.id"), nullable=False, index=True)
    water_body_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("navigation_water_body.id"), nullable=False, index=True)
    match_batch_code: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    match_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    matched_term: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    confidence_code: Mapped[str] = mapped_column(String(64), nullable=False, default="LOW_CONFIDENCE", index=True)
    issue_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    source_water_area_ids_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_trace_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class NavigationWaterBodyFeatureLink(Base, TimestampMixin):
    __tablename__ = "navigation_water_body_feature_link"
    __table_args__ = (
        UniqueConstraint("water_body_id", "water_area_id", name="uk_navigation_water_body_feature_link_body_area"),
        Index("ix_navigation_water_body_feature_link_area", "water_area_id"),
        Index("ix_navigation_water_body_feature_link_role", "link_role_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    water_body_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("navigation_water_body.id"), nullable=False, index=True)
    water_area_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("navigation_water_area.id"), nullable=False, index=True)
    link_role_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_layer_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    source_layer_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    overlap_ratio: Mapped[float | None] = mapped_column(Numeric(8, 6), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    source_trace_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class NavigationChannelCenterline(Base, TimestampMixin):
    __tablename__ = "navigation_channel_centerline"
    __table_args__ = (
        UniqueConstraint("centerline_code", name="uk_navigation_channel_centerline_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("navigation_channel.id"), nullable=False, index=True)
    segment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("navigation_channel_segment.id"), nullable=True, index=True
    )
    centerline_code: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    centerline_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    geometry_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    direction_code: Mapped[str] = mapped_column(String(32), nullable=False, default="BIDIRECTIONAL", index=True)
    is_main_line: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    quality_code: Mapped[str] = mapped_column(String(64), nullable=False, default="NEED_REVIEW", index=True)
    review_status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="NEED_REVIEW", index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_centerline_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("navigation_channel_centerline.id"), nullable=True, index=True
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    source_trace_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    approved_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    bbox_min_lng: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True, index=True)
    bbox_min_lat: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True, index=True)
    bbox_max_lng: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True, index=True)
    bbox_max_lat: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True, index=True)


class NavigationGeometryDraft(Base, TimestampMixin):
    __tablename__ = "navigation_geometry_draft"
    __table_args__ = (
        UniqueConstraint("draft_no", name="uk_navigation_geometry_draft_no"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    draft_no: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    draft_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    draft_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    geometry_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("navigation_channel.id"), nullable=True, index=True)
    target_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    geometry_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="MANUAL_DRAW", index=True)
    status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="DRAFT", index=True)
    quality_code: Mapped[str] = mapped_column(String(64), nullable=False, default="NEED_REVIEW", index=True)
    review_comment: Mapped[str | None] = mapped_column(String(512), nullable=True)
    publish_target_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    publish_target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    bbox_min_lng: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True, index=True)
    bbox_min_lat: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True, index=True)
    bbox_max_lng: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True, index=True)
    bbox_max_lat: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True, index=True)
    source_trace_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    submitted_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    published_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class NavigationGraphVersion(Base, TimestampMixin):
    __tablename__ = "navigation_graph_version"
    __table_args__ = (
        UniqueConstraint("version_code", name="uk_navigation_graph_version_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    version_code: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    version_name: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    channel_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="BUILDING", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    built_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    build_scope_bbox_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    build_config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    validation_report_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class NavigationGraphNode(Base, TimestampMixin):
    __tablename__ = "navigation_graph_node"
    __table_args__ = (
        UniqueConstraint("graph_version_id", "node_code", name="uk_navigation_graph_node_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    graph_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("navigation_graph_version.id"), nullable=False, index=True
    )
    node_code: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    node_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    node_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    longitude: Mapped[float] = mapped_column(Numeric(24, 15), nullable=False, index=True)
    latitude: Mapped[float] = mapped_column(Numeric(24, 15), nullable=False, index=True)
    geometry_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("navigation_channel.id"), nullable=True, index=True)
    related_transport_node_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("transport_node.id"), nullable=True, index=True
    )
    related_constraint_point_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("navigation_constraint_point.id"), nullable=True, index=True
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    quality_code: Mapped[str] = mapped_column(String(64), nullable=False, default="READY", index=True)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="CENTERLINE_VERTEX", index=True)
    snap_distance_m: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    snap_confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)


class NavigationGraphEdge(Base, TimestampMixin):
    __tablename__ = "navigation_graph_edge"
    __table_args__ = (
        UniqueConstraint("graph_version_id", "edge_code", name="uk_navigation_graph_edge_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    graph_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("navigation_graph_version.id"), nullable=False, index=True
    )
    edge_code: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    from_node_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("navigation_graph_node.id"), nullable=False, index=True)
    to_node_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("navigation_graph_node.id"), nullable=False, index=True)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("navigation_channel.id"), nullable=True, index=True)
    centerline_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("navigation_channel_centerline.id"), nullable=True, index=True
    )
    geometry_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    length_km: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    direction_code: Mapped[str] = mapped_column(String(32), nullable=False, default="BIDIRECTIONAL", index=True)
    technical_grade_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    min_depth_m: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    min_width_m: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    max_allowed_draft_m: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    max_allowed_tonnage: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    max_air_draft_m: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    max_beam_m: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    max_length_m: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    lock_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    bridge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    base_cost: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    routing_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    quality_code: Mapped[str] = mapped_column(String(64), nullable=False, default="READY", index=True)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unknown_constraint_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    validation_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class NavigationGraphEdgeConstraint(Base, TimestampMixin):
    __tablename__ = "navigation_graph_edge_constraint"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    edge_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("navigation_graph_edge.id"), nullable=False, index=True)
    constraint_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    constraint_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    rule_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    severity_level: Mapped[str] = mapped_column(String(32), nullable=False, default="WARNING", index=True)
    warning_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    data_completeness_code: Mapped[str] = mapped_column(String(64), nullable=False, default="UNKNOWN", index=True)
    source_trace_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class NavigationRouteRequest(Base):
    __tablename__ = "navigation_route_request"
    __table_args__ = (
        UniqueConstraint("request_no", name="uk_navigation_route_request_no"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_no: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    origin_lng: Mapped[float] = mapped_column(Numeric(24, 15), nullable=False)
    origin_lat: Mapped[float] = mapped_column(Numeric(24, 15), nullable=False)
    origin_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    origin_ref_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    origin_ref_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    destination_lng: Mapped[float] = mapped_column(Numeric(24, 15), nullable=False)
    destination_lat: Mapped[float] = mapped_column(Numeric(24, 15), nullable=False)
    destination_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    destination_ref_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    destination_ref_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    vessel_profile_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    routing_preference_code: Mapped[str] = mapped_column(String(64), nullable=False, default="RECOMMENDED", index=True)
    graph_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("navigation_graph_version.id"), nullable=True, index=True
    )
    status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="FAILED", index=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class NavigationRouteResult(Base, TimestampMixin):
    __tablename__ = "navigation_route_result"
    __table_args__ = (
        UniqueConstraint("request_id", "result_no", name="uk_navigation_route_result_no"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("navigation_route_request.id"), nullable=False, index=True)
    result_no: Mapped[int] = mapped_column(Integer, nullable=False)
    result_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="RECOMMENDED", index=True)
    status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="FAILED", index=True)
    geometry_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    distance_km: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    estimated_duration_hour: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    edge_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    channel_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    passed_node_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    passed_lock_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_bridge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    quality_code: Mapped[str] = mapped_column(String(64), nullable=False, default="FAILED", index=True)
    quality_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    provider_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    engine_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    reference_result_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("navigation_route_result.id"), nullable=True, index=True
    )


class NavigationAnnotationTask(Base, TimestampMixin):
    __tablename__ = "navigation_annotation_task"
    __table_args__ = (
        UniqueConstraint("task_no", name="uk_navigation_annotation_task_no"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_no: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    task_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("navigation_channel.id"), nullable=True, index=True)
    graph_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("navigation_graph_version.id"), nullable=True, index=True
    )
    geometry_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    priority_code: Mapped[str] = mapped_column(String(32), nullable=False, default="MEDIUM", index=True)
    status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="OPEN", index=True)
    issue_summary: Mapped[str] = mapped_column(Text, nullable=False)
    suggestion_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    assigned_to: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolution_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    resolution_target_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution_target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class NavigationRouteQualityIssue(Base):
    __tablename__ = "navigation_route_quality_issue"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    route_result_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("navigation_route_result.id"), nullable=False, index=True
    )
    issue_type_code: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    severity_code: Mapped[str] = mapped_column(String(32), nullable=False, default="WARNING", index=True)
    geometry_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    message: Mapped[str] = mapped_column(String(512), nullable=False)
    suggestion: Mapped[str | None] = mapped_column(String(512), nullable=True)
    related_edge_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("navigation_graph_edge.id"), nullable=True, index=True)
    related_node_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("navigation_graph_node.id"), nullable=True, index=True)
    related_annotation_task_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("navigation_annotation_task.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
