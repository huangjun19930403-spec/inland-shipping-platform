from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuditFlowMixin, Base, SoftDeleteMixin, TimestampMixin


class Freight(Base, TimestampMixin, SoftDeleteMixin, AuditFlowMixin):
    __tablename__ = "freight"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    freight_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    cargo_title: Mapped[str] = mapped_column(String(256), nullable=False)
    cargo_description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    commodity_standard_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("commodity_standard.id"), nullable=False, index=True
    )
    packaging_form_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    estimated_tonnage: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    min_tonnage: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    max_tonnage: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    unit_price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    total_price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    price_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    settlement_method_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    origin_node_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("transport_node.id"), nullable=True, index=True
    )
    destination_node_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("transport_node.id"), nullable=True, index=True
    )
    origin_province_code: Mapped[str] = mapped_column(String(12), nullable=False)
    origin_city_code: Mapped[str] = mapped_column(String(12), nullable=False)
    origin_district_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    destination_province_code: Mapped[str] = mapped_column(String(12), nullable=False)
    destination_city_code: Mapped[str] = mapped_column(String(12), nullable=False)
    destination_district_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    origin_region_id_cache: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("region.id"), nullable=True, index=True
    )
    destination_region_id_cache: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("region.id"), nullable=True, index=True
    )
    loading_time_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    loading_time_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    unloading_time_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    unloading_time_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    publisher_org_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status_code: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class FreightContact(Base, TimestampMixin):
    __tablename__ = "freight_contact"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    freight_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("freight.id"), nullable=False, index=True
    )
    contact_name: Mapped[str] = mapped_column(String(64), nullable=False)
    contact_role_code: Mapped[str] = mapped_column(String(64), nullable=False)
    mobile_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    landline_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    wechat: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class FreightSourceAttachment(Base):
    __tablename__ = "freight_source_attachment"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    freight_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("freight.id"), nullable=False, index=True
    )
    storage_provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    file_url: Mapped[str] = mapped_column(String(512), nullable=False)
    file_name: Mapped[str] = mapped_column(String(256), nullable=False)
    file_ext: Mapped[str | None] = mapped_column(String(32), nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class FreightTagRelation(Base):
    __tablename__ = "freight_tag_relation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    freight_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("freight.id"), nullable=False, index=True
    )
    tag_code: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
