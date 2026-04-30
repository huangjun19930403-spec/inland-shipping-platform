from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, JSON, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuditFlowMixin, Base, SoftDeleteMixin, TimestampMixin


class ShippingRoute(Base, TimestampMixin, SoftDeleteMixin, AuditFlowMixin):
    __tablename__ = "shipping_route"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    transport_org_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    multimodal_combination_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    origin_region_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("region.id"), nullable=False, index=True)
    destination_region_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("region.id"), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)


class ShippingRoutePlan(Base, TimestampMixin):
    __tablename__ = "shipping_route_plan"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    route_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shipping_route.id"), nullable=False, index=True)
    plan_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    plan_name: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)


class ShippingRouteLine(Base, TimestampMixin):
    __tablename__ = "shipping_route_line"
    __table_args__ = (
        UniqueConstraint("plan_id", "line_code", name="uk_route_line_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shipping_route_plan.id"), nullable=False, index=True)
    line_code: Mapped[str] = mapped_column(String(32), nullable=False)
    line_name: Mapped[str] = mapped_column(String(128), nullable=False)
    line_role_code: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trigger_condition: Mapped[str | None] = mapped_column(String(256), nullable=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    track_status: Mapped[str] = mapped_column(String(64), nullable=False, default="NOT_GENERATED")
    track_generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ShippingRouteLineNode(Base, TimestampMixin):
    __tablename__ = "shipping_route_line_node"
    __table_args__ = (
        UniqueConstraint("line_id", "node_order", name="uk_route_line_node_order"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    line_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shipping_route_line.id"), nullable=False, index=True)
    node_order: Mapped[int] = mapped_column(Integer, nullable=False)
    node_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    transport_node_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("transport_node.id"), nullable=True, index=True)
    constraint_point_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("navigation_constraint_point.id"), nullable=True, index=True)
    manual_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(11, 8), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 8), nullable=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)


class ShippingRouteLineSegment(Base, TimestampMixin):
    __tablename__ = "shipping_route_line_segment"
    __table_args__ = (
        UniqueConstraint("line_id", "segment_no", name="uk_route_line_segment_no"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    line_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shipping_route_line.id"), nullable=False, index=True)
    segment_no: Mapped[int] = mapped_column(Integer, nullable=False)
    start_line_node_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shipping_route_line_node.id"), nullable=False, index=True)
    end_line_node_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shipping_route_line_node.id"), nullable=False, index=True)
    transport_mode_code: Mapped[str] = mapped_column(String(64), nullable=False)
    distance_km: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    estimated_duration_hour: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    segment_track_status: Mapped[str] = mapped_column(String(64), nullable=False, default="NOT_GENERATED")
    geometry_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    geometry_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)


class ShippingRouteLineTrack(Base, TimestampMixin):
    __tablename__ = "shipping_route_line_track"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    line_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shipping_route_line.id"), unique=True, nullable=False, index=True)
    track_status: Mapped[str] = mapped_column(String(64), nullable=False)
    geometry_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    distance_km: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    estimated_duration_hour: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    provider_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
