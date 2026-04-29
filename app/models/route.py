from __future__ import annotations

from datetime import datetime

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


class ShippingRoute(Base, TimestampMixin, SoftDeleteMixin, AuditFlowMixin):
    __tablename__ = "shipping_route"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    transport_org_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    multimodal_combination_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    origin_region_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("region.id"), nullable=False, index=True
    )
    destination_region_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("region.id"), nullable=False, index=True
    )
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ShippingRoutePlan(Base, TimestampMixin):
    __tablename__ = "shipping_route_plan"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    route_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shipping_route.id"), nullable=False, index=True
    )
    plan_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    plan_name: Mapped[str] = mapped_column(String(128), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    plan_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    total_distance_km: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    estimated_duration_hour: Mapped[float | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    effective_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)


class ShippingRoutePlanNode(Base, TimestampMixin):
    __tablename__ = "shipping_route_plan_node"
    __table_args__ = (
        UniqueConstraint("plan_id", "node_order", name="uk_route_plan_node_order"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shipping_route_plan.id"), nullable=False, index=True
    )
    node_order: Mapped[int] = mapped_column(Integer, nullable=False)
    node_kind_code: Mapped[str] = mapped_column(String(64), nullable=False)
    transport_node_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("transport_node.id"), nullable=True, index=True
    )
    constraint_point_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("navigation_constraint_point.id"), nullable=True, index=True
    )
    region_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("region.id"), nullable=True, index=True
    )
    longitude: Mapped[float | None] = mapped_column(Numeric(11, 8), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 8), nullable=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    role_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    next_transport_mode_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)


class ShippingRoutePlanSegment(Base, TimestampMixin):
    __tablename__ = "shipping_route_plan_segment"
    __table_args__ = (
        UniqueConstraint("plan_id", "segment_no", name="uk_route_plan_segment_no"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shipping_route_plan.id"), nullable=False, index=True
    )
    segment_no: Mapped[int] = mapped_column(Integer, nullable=False)
    segment_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    start_node_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("transport_node.id"), nullable=True
    )
    end_node_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("transport_node.id"), nullable=True
    )
    start_constraint_point_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("navigation_constraint_point.id"), nullable=True
    )
    end_constraint_point_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("navigation_constraint_point.id"), nullable=True
    )
    distance_km: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    estimated_duration_hour: Mapped[float | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    geometry_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)


class ShippingRoutePlanSegmentPoint(Base, TimestampMixin):
    __tablename__ = "shipping_route_plan_segment_point"
    __table_args__ = (
        UniqueConstraint("segment_id", "point_no", name="uk_route_segment_point_no"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    segment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shipping_route_plan_segment.id"), nullable=False, index=True
    )
    point_no: Mapped[int] = mapped_column(Integer, nullable=False)
    point_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    related_node_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("transport_node.id"), nullable=True
    )
    related_constraint_point_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("navigation_constraint_point.id"), nullable=True
    )
    longitude: Mapped[float | None] = mapped_column(Numeric(11, 8), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 8), nullable=True)
    stay_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)
