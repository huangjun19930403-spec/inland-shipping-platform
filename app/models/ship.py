from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuditFlowMixin, Base, SoftDeleteMixin, TimestampMixin


class ShipProfile(Base, TimestampMixin, SoftDeleteMixin, AuditFlowMixin):
    __tablename__ = "ship_profile"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ais_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    ship_name: Mapped[str] = mapped_column(String(128), nullable=False)
    ship_name_en: Mapped[str | None] = mapped_column(String(256), nullable=True)
    current_mmsi: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ship_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    navigation_power_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    home_port_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    home_port_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    owner_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    building_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    registry_city_code: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    business_region_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    operation_status_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    profile_status_code: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False)


class ShipCapacity(Base):
    __tablename__ = "ship_capacity"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ship_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ship_profile.id"), unique=True, nullable=False
    )
    deadweight_ton: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    reference_load_ton: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    total_tonnage: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    net_tonnage: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    length_m: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    width_m: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    depth_m: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    design_draft_m: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    design_speed_kn: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    hold_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    capacity_remark: Mapped[str | None] = mapped_column(String(512), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ShipOperation(Base):
    __tablename__ = "ship_operation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ship_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ship_profile.id"), unique=True, nullable=False
    )
    operator_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    manager_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    main_navigation_area_desc: Mapped[str | None] = mapped_column(String(256), nullable=True)
    usual_route_desc: Mapped[str | None] = mapped_column(String(256), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dispatch_contact_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dispatch_contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    risk_level_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ext_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ShipOwner(Base, TimestampMixin):
    __tablename__ = "ship_owner"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ship_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ship_profile.id"), nullable=False, index=True
    )
    party_name: Mapped[str] = mapped_column(String(128), nullable=False)
    party_relation_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    certificate_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mobile_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    landline_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    address: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ShipContact(Base, TimestampMixin):
    __tablename__ = "ship_contact"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ship_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ship_profile.id"), nullable=False, index=True
    )
    contact_name: Mapped[str] = mapped_column(String(64), nullable=False)
    contact_role_code: Mapped[str] = mapped_column(String(64), nullable=False)
    mobile_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    wechat: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)


class ShipCertificate(Base, TimestampMixin):
    __tablename__ = "ship_certificate"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ship_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ship_profile.id"), nullable=False, index=True
    )
    certificate_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    certificate_no: Mapped[str | None] = mapped_column(String(128), nullable=True)
    issuing_authority: Mapped[str | None] = mapped_column(String(128), nullable=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_long_term_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    validity_text_raw: Mapped[str | None] = mapped_column(String(256), nullable=True)
    verify_status_code: Mapped[str] = mapped_column(String(64), nullable=False)
    structured_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_file_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)


class ShipCertificateFile(Base):
    __tablename__ = "ship_certificate_file"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ship_certificate_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("ship_certificate.id"), nullable=True, index=True
    )
    storage_provider_code: Mapped[str] = mapped_column(String(64), nullable=False)
    file_url: Mapped[str] = mapped_column(String(512), nullable=False)
    file_name: Mapped[str] = mapped_column(String(256), nullable=False)
    file_ext: Mapped[str | None] = mapped_column(String(32), nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    uploaded_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ShipNameHistory(Base):
    __tablename__ = "ship_name_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ship_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ship_profile.id"), nullable=False, index=True
    )
    ship_name: Mapped[str] = mapped_column(String(128), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ShipMmsiHistory(Base):
    __tablename__ = "ship_mmsi_history"
    __table_args__ = (
        UniqueConstraint("ship_id", "mmsi", "start_date", name="uk_ship_mmsi_history"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ship_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ship_profile.id"), nullable=False, index=True
    )
    mmsi: Mapped[str] = mapped_column(String(16), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ShipDynamic(Base, TimestampMixin):
    __tablename__ = "ship_dynamic"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ship_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ship_profile.id"), unique=True, nullable=False
    )
    stat_date: Mapped[date] = mapped_column(Date, nullable=False)
    city_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(11, 8), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 8), nullable=True)
    speed_kn: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    heading: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    dynamic_status_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_ais_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False)

