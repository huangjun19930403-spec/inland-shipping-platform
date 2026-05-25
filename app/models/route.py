from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, JSON, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class ShippingRoute(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "shipping_route"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    origin_endpoint_type_code: Mapped[str] = mapped_column(String(32), nullable=False, default="REGION")
    origin_region_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("region.id"), nullable=True, index=True)
    origin_city_code: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    origin_node_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("transport_node.id"), nullable=True, index=True)
    destination_endpoint_type_code: Mapped[str] = mapped_column(String(32), nullable=False, default="REGION")
    destination_region_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("region.id"), nullable=True, index=True)
    destination_city_code: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    destination_node_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("transport_node.id"), nullable=True, index=True)
    transport_org_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    multimodal_combination_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE", index=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)


class ShippingRoutePlan(Base, TimestampMixin):
    __tablename__ = "shipping_route_plan"
    __table_args__ = (
        UniqueConstraint("route_id", "display_order", name="uk_route_plan_display_order"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    route_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shipping_route.id"), nullable=False, index=True)
    plan_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    plan_name: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT", index=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    structure_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, index=True)
    current_track_version_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    applicable_condition: Mapped[str | None] = mapped_column(String(512), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)


class ShippingRoutePlanPoint(Base, TimestampMixin):
    __tablename__ = "shipping_route_plan_point"
    __table_args__ = (
        UniqueConstraint("plan_id", "structure_revision", "point_order", name="uk_route_plan_point_order"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shipping_route_plan.id"), nullable=False, index=True)
    structure_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, index=True)
    point_order: Mapped[int] = mapped_column(Integer, nullable=False)
    point_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    transport_node_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("transport_node.id"), nullable=True, index=True)
    constraint_point_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("navigation_constraint_point.id"), nullable=True, index=True)
    manual_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(24, 15), nullable=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    transport_mode_after_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)


class ShippingRoutePlanSegment(Base, TimestampMixin):
    __tablename__ = "shipping_route_plan_segment"
    __table_args__ = (
        UniqueConstraint("plan_id", "structure_revision", "segment_no", name="uk_route_plan_segment_no"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shipping_route_plan.id"), nullable=False, index=True)
    structure_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, index=True)
    segment_no: Mapped[int] = mapped_column(Integer, nullable=False)
    start_plan_point_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shipping_route_plan_point.id"), nullable=False, index=True)
    end_plan_point_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shipping_route_plan_point.id"), nullable=False, index=True)
    transport_mode_code: Mapped[str] = mapped_column(String(64), nullable=False)
    generation_status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="NOT_GENERATED", index=True)
    selected_result_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)


class ShippingRoutePlanSegmentResult(Base, TimestampMixin):
    __tablename__ = "shipping_route_plan_segment_result"
    __table_args__ = (
        UniqueConstraint("segment_id", "result_no", name="uk_route_segment_result_no"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    segment_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shipping_route_plan_segment.id"), nullable=False, index=True)
    result_no: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_route_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result_status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="READY", index=True)
    is_selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    geometry_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    distance_km: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    estimated_duration_hour: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    raw_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ShippingRoutePlanTrackVersion(Base, TimestampMixin):
    __tablename__ = "shipping_route_plan_track_version"
    __table_args__ = (
        UniqueConstraint("plan_id", "version_no", name="uk_route_plan_track_version_no"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shipping_route_plan.id"), nullable=False, index=True)
    structure_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    version_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_version_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    version_status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="READY", index=True)
    distance_km: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    estimated_duration_hour: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    point_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    segment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ShippingRoutePlanTrackVersionSegment(Base, TimestampMixin):
    __tablename__ = "shipping_route_plan_track_version_segment"
    __table_args__ = (
        UniqueConstraint("version_id", "segment_id", name="uk_route_track_version_segment"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    version_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shipping_route_plan_track_version.id"), nullable=False, index=True)
    segment_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shipping_route_plan_segment.id"), nullable=False, index=True)
    segment_no: Mapped[int] = mapped_column(Integer, nullable=False)
    geometry_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    distance_km: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    estimated_duration_hour: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    point_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edit_status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="ORIGINAL", index=True)
