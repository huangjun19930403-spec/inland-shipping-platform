from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class VesselIdentity(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "vessel_identity"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    identity_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    identity_status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="UNVERIFIED")
    canonical_mmsi: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    canonical_ship_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="SYSTEM")
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)


class VesselProfile(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "vessel_profile"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    vessel_identity_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("vessel_identity.id"), nullable=True, index=True
    )
    ship_name: Mapped[str] = mapped_column(String(128), nullable=False)
    ship_name_en: Mapped[str | None] = mapped_column(String(256), nullable=True)
    current_mmsi: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    ship_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    profile_status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="ACTIVE")
    identity_status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="UNLINKED")
    operation_status_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    home_port_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    home_port_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    registry_city_code: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    business_region_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="MANUAL")
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)


class VesselIdentityLink(Base, TimestampMixin):
    __tablename__ = "vessel_identity_link"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_identity_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_identity.id"), nullable=False, index=True
    )
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    link_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="PROFILE")
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class VesselIdentifierHistory(Base):
    __tablename__ = "vessel_identifier_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    identifier_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    identifier_value: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="MANUAL")
    source_trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselNameHistory(Base):
    __tablename__ = "vessel_name_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    ship_name: Mapped[str] = mapped_column(String(128), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="MANUAL")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselRegistrationInfo(Base):
    __tablename__ = "vessel_registration_info"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), unique=True, nullable=False
    )
    registry_city_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    ship_registry_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    home_port_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    home_port_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    flag_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mmsi_issuing_authority: Mapped[str | None] = mapped_column(String(128), nullable=True)
    inspection_org: Mapped[str | None] = mapped_column(String(128), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselCapacityDimension(Base):
    __tablename__ = "vessel_capacity_dimension"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), unique=True, nullable=False
    )
    deadweight_ton: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    reference_load_ton: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    total_tonnage: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    net_tonnage: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    length_m: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    width_m: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    depth_m: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    design_draft_m: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    max_draft_m: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    design_speed_kn: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    hold_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    teu_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    capacity_remark: Mapped[str | None] = mapped_column(String(512), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselBuildInfo(Base):
    __tablename__ = "vessel_build_info"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), unique=True, nullable=False
    )
    building_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    builder_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    build_place: Mapped[str | None] = mapped_column(String(128), nullable=True)
    hull_material_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    engine_power_kw: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselOwnerPeriod(Base, TimestampMixin):
    __tablename__ = "vessel_owner_period"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    party_name: Mapped[str] = mapped_column(String(128), nullable=False)
    party_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="UNKNOWN")
    certificate_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    address: Mapped[str | None] = mapped_column(String(256), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    verified_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="UNVERIFIED")
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="MANUAL")
    source_trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    voided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class VesselOwnerDocument(Base):
    __tablename__ = "vessel_owner_document"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    vessel_owner_period_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_owner_period.id"), nullable=False, index=True
    )
    document_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("storage_file.id"), nullable=False, index=True
    )
    file_name: Mapped[str] = mapped_column(String(256), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uploaded_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    voided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)


class VesselOwnerDocumentImageRecognition(Base, TimestampMixin):
    __tablename__ = "vessel_owner_document_image_recognition"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    vessel_owner_period_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_owner_period.id"), nullable=False, index=True
    )
    owner_document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_owner_document.id"), nullable=False, index=True
    )
    storage_file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("storage_file.id"), nullable=False, index=True
    )
    status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="PENDING")
    provider_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    candidate_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confirmed_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    confirmed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class VesselOperatorPeriod(Base, TimestampMixin):
    __tablename__ = "vessel_operator_period"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    operator_name: Mapped[str] = mapped_column(String(128), nullable=False)
    party_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="UNKNOWN")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    verified_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="UNVERIFIED")
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="MANUAL")
    source_trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    voided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class VesselContact(Base, TimestampMixin):
    __tablename__ = "vessel_contact"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    contact_scope_code: Mapped[str] = mapped_column(String(64), nullable=False, default="GENERAL")
    owner_period_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("vessel_owner_period.id"), nullable=True, index=True
    )
    operator_period_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("vessel_operator_period.id"), nullable=True, index=True
    )
    crew_assignment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("vessel_crew_assignment.id"), nullable=True, index=True
    )
    contact_name: Mapped[str] = mapped_column(String(64), nullable=False)
    contact_role_code: Mapped[str] = mapped_column(String(64), nullable=False)
    mobile_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    wechat: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    verified_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="UNVERIFIED")
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="MANUAL")
    source_trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    voided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)


class VesselCrewAssignment(Base, TimestampMixin):
    __tablename__ = "vessel_crew_assignment"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    crew_name: Mapped[str] = mapped_column(String(64), nullable=False)
    crew_role_code: Mapped[str] = mapped_column(String(64), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    verified_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="UNVERIFIED")
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="MANUAL")
    source_trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    voided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class VesselPersonCertificate(Base, TimestampMixin):
    __tablename__ = "vessel_person_certificate"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    crew_assignment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("vessel_crew_assignment.id"), nullable=True, index=True
    )
    holder_name: Mapped[str] = mapped_column(String(64), nullable=False)
    certificate_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    certificate_no: Mapped[str | None] = mapped_column(String(128), nullable=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_long_term_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    validity_text_raw: Mapped[str | None] = mapped_column(String(256), nullable=True)
    verify_status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="PENDING")
    structured_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="MANUAL")
    source_trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    voided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)


class VesselPersonCertificateFile(Base):
    __tablename__ = "vessel_person_certificate_file"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_person_certificate_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_person_certificate.id"), nullable=False, index=True
    )
    storage_file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("storage_file.id"), nullable=False, index=True
    )
    file_name: Mapped[str] = mapped_column(String(256), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uploaded_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    voided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)


class VesselPersonCertificateImageRecognition(Base, TimestampMixin):
    __tablename__ = "vessel_person_certificate_image_recognition"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    vessel_person_certificate_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_person_certificate.id"), nullable=False, index=True
    )
    person_certificate_file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_person_certificate_file.id"), nullable=False, index=True
    )
    storage_file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("storage_file.id"), nullable=False, index=True
    )
    status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="PENDING")
    provider_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    candidate_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confirmed_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    confirmed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class VesselCertificate(Base, TimestampMixin):
    __tablename__ = "vessel_certificate"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    certificate_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    certificate_no: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    issuing_authority: Mapped[str | None] = mapped_column(String(128), nullable=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_long_term_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    validity_text_raw: Mapped[str | None] = mapped_column(String(256), nullable=True)
    verify_status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="PENDING")
    structured_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    voided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)


class VesselCertificateFile(Base):
    __tablename__ = "vessel_certificate_file"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_certificate_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_certificate.id"), nullable=False, index=True
    )
    storage_file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("storage_file.id"), nullable=False, index=True
    )
    file_name: Mapped[str] = mapped_column(String(256), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uploaded_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    voided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)


class VesselCertificateImageRecognition(Base, TimestampMixin):
    __tablename__ = "vessel_certificate_image_recognition"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    vessel_certificate_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_certificate.id"), nullable=False, index=True
    )
    certificate_file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_certificate_file.id"), nullable=False, index=True
    )
    storage_file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("storage_file.id"), nullable=False, index=True
    )
    status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="PENDING")
    provider_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    candidate_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confirmed_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    confirmed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class VesselChangeEvent(Base):
    __tablename__ = "vessel_change_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    event_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_title: Mapped[str] = mapped_column(String(128), nullable=False)
    object_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    object_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    before_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    changed_fields_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    operator_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselDataQualityIssue(Base, TimestampMixin):
    __tablename__ = "vessel_data_quality_issue"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    issue_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity_code: Mapped[str] = mapped_column(String(32), nullable=False, default="MEDIUM")
    affected_object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    affected_object_id: Mapped[str] = mapped_column(String(64), nullable=False)
    vessel_profile_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("vessel_profile.id"), nullable=True, index=True)
    field_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    evidence_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    impact_scope_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN", index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    resolved_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_rechecked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_recheck_status_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_recheck_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class VesselProfileSummary(Base):
    __tablename__ = "vessel_profile_summary"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), unique=True, nullable=False, index=True
    )
    ship_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    current_mmsi: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    ship_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    ship_type_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    deadweight_ton: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    length_m: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    width_m: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    design_draft_m: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    building_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ship_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    primary_owner_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    primary_operator_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    primary_contact_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    primary_contact_phone_masked: Mapped[str | None] = mapped_column(String(32), nullable=True)
    contact_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    profile_completeness_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    data_quality_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    data_quality_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    identity_confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    contact_trust_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")
    subject_consistency_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")
    quality_issue_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_field_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conflict_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    risk_evidence_summary_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    certificate_missing_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    certificate_expiring_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    certificate_expired_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latest_position_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    latest_city_code: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    latest_city_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ais_freshness_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    ais_unavailable_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    analysis_sample_tags_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    analysis_sample_tags_key: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    data_sources_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    uncertainty_notes_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_layer: Mapped[str] = mapped_column(String(64), nullable=False, default="PROFILE_SUMMARY", index=True)
    coverage_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    summary_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="READY", index=True)
    summary_version: Mapped[str] = mapped_column(String(32), nullable=False, default="ROUND_3_V1")
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    refresh_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselAisSnapshot(Base):
    __tablename__ = "vessel_ais_snapshot"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    query_params_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="READY", index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    cache_backend_code: Mapped[str] = mapped_column(String(32), nullable=False, default="memory")
    scanned_profile_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queried_mmsi_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_profile_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_position_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unmatched_mmsi_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_position_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unknown_city_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_batch_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_batches_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    coverage_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    freshness_distribution_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_indices_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    uncertainty_notes_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    boundary_version_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    refresh_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselAisCitySnapshotItem(Base):
    __tablename__ = "vessel_ais_city_snapshot_item"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[str] = mapped_column(String(64), ForeignKey("vessel_ais_snapshot.snapshot_id"), nullable=False, index=True)
    city_code: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    city_name: Mapped[str] = mapped_column(String(128), nullable=False)
    positioned_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_position_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unmatched_mmsi_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_position_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stale_position_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    freshness_distribution_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    boundary_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")
    has_boundary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    boundary_precision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    latest_position_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselLatestPositionSnapshot(Base):
    __tablename__ = "vessel_latest_position_snapshot"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[str] = mapped_column(String(64), ForeignKey("vessel_ais_snapshot.snapshot_id"), nullable=False, index=True)
    vessel_profile_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("vessel_profile.id"), nullable=True, index=True)
    mmsi: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    speed_kn: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    course_deg: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    heading_deg: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    position_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    source_index: Mapped[str | None] = mapped_column(String(128), nullable=True)
    freshness_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    match_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="MATCHED_PROFILE", index=True)
    city_code: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    city_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    current_channel_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_channel_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    current_channel_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    channel_match_distance_m: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    valid_position_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselSpatialObservationSnapshot(Base):
    __tablename__ = "vessel_spatial_observation_snapshot"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    source_snapshot_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("vessel_ais_snapshot.snapshot_id"), nullable=True, index=True
    )
    observation_type_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    query_params_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="READY", index=True)
    source_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="AVAILABLE")
    stat_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    window_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    coverage_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    freshness_distribution_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_indices_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    failed_batch_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_batches_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    unmatched_mmsi_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_position_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stale_position_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_position_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_vessel_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    not_computable_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    quality_warnings_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    uncertainty_notes_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    refresh_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselNodeObservationItem(Base):
    __tablename__ = "vessel_node_observation_item"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("vessel_spatial_observation_snapshot.snapshot_id"), nullable=False, index=True
    )
    node_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("transport_node.id"), nullable=False, index=True)
    node_name: Mapped[str] = mapped_column(String(128), nullable=False)
    node_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    city_code: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    radius_km: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    longitude: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    active_vessel_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stay_vessel_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passby_vessel_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inflow_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outflow_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unmatched_mmsi_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_position_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stale_position_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coverage_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")
    freshness_distribution_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ship_type_distribution_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    risk_distribution_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    latest_position_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    not_computable_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselNodeObservationVessel(Base):
    __tablename__ = "vessel_node_observation_vessel"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("vessel_spatial_observation_snapshot.snapshot_id"), nullable=False, index=True
    )
    node_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("transport_node.id"), nullable=False, index=True)
    vessel_profile_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("vessel_profile.id"), nullable=True, index=True)
    mmsi: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    ship_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ship_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    deadweight_ton: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    distance_km: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    position_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    source_index: Mapped[str | None] = mapped_column(String(128), nullable=True)
    freshness_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    match_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="NEARBY", index=True)
    stay_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    direction_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")
    risk_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    quality_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselRouteSegmentObservationItem(Base):
    __tablename__ = "vessel_route_segment_observation_item"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("vessel_spatial_observation_snapshot.snapshot_id"), nullable=False, index=True
    )
    route_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("shipping_route.id"), nullable=True, index=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shipping_route_plan.id"), nullable=False, index=True)
    segment_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shipping_route_plan_segment.id"), nullable=False, index=True)
    segment_no: Mapped[int] = mapped_column(Integer, nullable=False)
    segment_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    geometry_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")
    geometry_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    geometry_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    matched_vessel_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_vessel_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    point_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gap_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    covered_ratio: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    average_match_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    coverage_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")
    not_computable_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselRouteSegmentMatchSample(Base):
    __tablename__ = "vessel_route_segment_match_sample"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("vessel_spatial_observation_snapshot.snapshot_id"), nullable=False, index=True
    )
    segment_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shipping_route_plan_segment.id"), nullable=False, index=True)
    vessel_profile_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("vessel_profile.id"), nullable=True, index=True)
    mmsi: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    ship_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ship_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deadweight_ton: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    match_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    covered_ratio: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    direction_consistency: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    point_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gap_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latest_position_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_index: Mapped[str | None] = mapped_column(String(128), nullable=True)
    freshness_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")
    match_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="MATCHED", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselNavigationConstraintEvidence(Base):
    __tablename__ = "vessel_navigation_constraint_evidence"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("vessel_spatial_observation_snapshot.snapshot_id"), nullable=True, index=True
    )
    context_type_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    context_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    constraint_point_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("navigation_constraint_point.id"), nullable=True, index=True)
    constraint_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    constraint_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="BASE_DATA")
    source_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    value_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")
    unavailable_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselCandidateAnalysis(Base):
    __tablename__ = "vessel_candidate_analysis"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    context_type_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_layer_code: Mapped[str] = mapped_column(String(64), nullable=False, default="MANUAL", index=True)
    freight_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("freight.id"), nullable=True, index=True)
    freight_candidate_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("freight_candidate.id"), nullable=True, index=True
    )
    origin_node_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("transport_node.id"), nullable=True, index=True)
    destination_node_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("transport_node.id"), nullable=True, index=True
    )
    route_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("shipping_route.id"), nullable=True, index=True)
    plan_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("shipping_route_plan.id"), nullable=True, index=True)
    origin_city_code: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    destination_city_code: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    region_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("region.id"), nullable=True, index=True)
    context_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    filters_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_ais_snapshot_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("vessel_ais_snapshot.snapshot_id"), nullable=True, index=True
    )
    source_spatial_snapshot_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("vessel_spatial_observation_snapshot.snapshot_id"), nullable=True, index=True
    )
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="READY", index=True)
    coverage_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    low_confidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    not_computable_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    uncertainty_notes_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    data_sources_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselCandidateAnalysisItem(Base):
    __tablename__ = "vessel_candidate_analysis_item"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    analysis_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_candidate_analysis.id"), nullable=False, index=True
    )
    vessel_profile_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("vessel_profile.id"), nullable=True, index=True)
    mmsi: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    ship_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ship_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    deadweight_ton: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    design_draft_m: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    latest_position_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    ais_freshness_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    quality_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    fit_score: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False, default=0)
    candidate_value_level: Mapped[str] = mapped_column(String(32), nullable=False, default="LOW", index=True)
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    node_distance_km: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    route_match_score: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    direction_consistency: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    constraint_status_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    score_parts_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    risk_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    uncertainty_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    not_computable_reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    data_sources_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselCandidateAnalysisAnnotation(Base):
    __tablename__ = "vessel_candidate_analysis_annotation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    analysis_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_candidate_analysis.id"), nullable=False, index=True
    )
    item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_candidate_analysis_item.id"), nullable=False, index=True
    )
    annotation_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source_version_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class VesselRecognitionFieldDiff(Base):
    __tablename__ = "vessel_recognition_field_diff"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True)
    recognition_object_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    recognition_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    target_object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_object_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    current_value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    recognized_value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    adopt_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="REVIEW_REQUIRED")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselRecognitionAdoptionRecord(Base):
    __tablename__ = "vessel_recognition_adoption_record"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True)
    recognition_object_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    recognition_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    target_object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_object_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    adopted_fields_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    skipped_fields_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    confirmed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    change_event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("vessel_change_event.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselCertificateRequirementRule(Base, TimestampMixin):
    __tablename__ = "vessel_certificate_requirement_rule"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rule_code: Mapped[str] = mapped_column(String(96), unique=True, nullable=False, index=True)
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="GLOBAL", index=True)
    ship_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    cargo_category_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    route_area_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    required_certificate_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    risk_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="CERTIFICATE_MISSING")
    risk_level_when_missing: Mapped[str] = mapped_column(String(32), nullable=False, default="MEDIUM")
    status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE", index=True)
    condition_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    evidence_requirements_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    remark: Mapped[str | None] = mapped_column(String(500), nullable=True)


class VesselRiskSignal(Base, TimestampMixin):
    __tablename__ = "vessel_risk_signal"
    __table_args__ = (
        Index(
            "uq_vessel_risk_signal_active_fingerprint",
            "fingerprint",
            unique=True,
            sqlite_where=text("status_code IN ('OPEN', 'IN_REVIEW', 'EVIDENCE_ADDED')"),
            postgresql_where=text("status_code IN ('OPEN', 'IN_REVIEW', 'EVIDENCE_ADDED')"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    risk_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    rule_code: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN", index=True)
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_trace_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    uncertainty_notes_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    first_detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    resolution_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class VesselGovernanceSyncBatch(Base, TimestampMixin):
    __tablename__ = "vessel_governance_sync_batch"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    trigger_type_code: Mapped[str] = mapped_column(String(32), nullable=False, default="MANUAL", index=True)
    triggered_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="RUNNING", index=True)
    source_rules_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    rule_result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    affected_scope_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    touched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_task_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reopened_task_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)


class VesselGovernanceTask(Base, TimestampMixin):
    __tablename__ = "vessel_governance_task"
    __table_args__ = (
        Index(
            "uq_vessel_governance_task_active_fingerprint",
            "fingerprint",
            unique=True,
            sqlite_where=text("status_code IN ('OPEN', 'ASSIGNED', 'IN_PROGRESS', 'REOPENED')"),
            postgresql_where=text("status_code IN ('OPEN', 'ASSIGNED', 'IN_PROGRESS', 'REOPENED')"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    task_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    priority_code: Mapped[str] = mapped_column(String(32), nullable=False, default="MEDIUM", index=True)
    status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN", index=True)
    vessel_profile_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("vessel_profile.id"), nullable=True, index=True)
    source_batch_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("vessel_governance_sync_batch.id"), nullable=True, index=True)
    source_rule_code: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    source_object_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_object_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_status_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_trace_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    generation_reason_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    impact_summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    coverage_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    assigned_to: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    resolution_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reopen_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class VesselRiskReview(Base, TimestampMixin):
    __tablename__ = "vessel_risk_review"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True)
    risk_signal_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("vessel_risk_signal.id"), nullable=True, index=True)
    governance_task_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("vessel_governance_task.id"), nullable=True, index=True)
    review_action_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    from_status_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_status_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    risk_level_before: Mapped[str | None] = mapped_column(String(32), nullable=True)
    risk_level_after: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselBlacklistSignal(Base, TimestampMixin):
    __tablename__ = "vessel_blacklist_signal"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True)
    list_type_code: Mapped[str] = mapped_column(String(32), nullable=False, default="WATCHLIST", index=True)
    signal_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE", index=True)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="HIGH", index=True)
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="MANUAL")
    source_trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    evidence_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    voided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class VesselControllerEvidence(Base, TimestampMixin):
    __tablename__ = "vessel_controller_evidence"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    party_name: Mapped[str] = mapped_column(String(128), nullable=False)
    controller_role_code: Mapped[str] = mapped_column(String(64), nullable=False, default="EVIDENCE_PROVIDER")
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="MANUAL")
    source_trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    evidence_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE", index=True)
    verified_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT", index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    verified_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    voided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class VesselControllerConclusion(Base, TimestampMixin):
    __tablename__ = "vessel_controller_conclusion"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True)
    conclusion_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="CANDIDATE", index=True)
    party_name: Mapped[str] = mapped_column(String(128), nullable=False)
    controller_role_code: Mapped[str] = mapped_column(String(64), nullable=False, default="ACTUAL_CONTROLLER")
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    evidence_ids_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conflict_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    voided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class VesselAffiliationEvidence(Base, TimestampMixin):
    __tablename__ = "vessel_affiliation_evidence"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    owner_period_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("vessel_owner_period.id"), nullable=True, index=True)
    operator_period_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("vessel_operator_period.id"), nullable=True, index=True)
    affiliation_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="UNKNOWN")
    subject_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    counterparty_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN")
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="MANUAL")
    source_trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    evidence_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE", index=True)
    verified_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT", index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    verified_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    voided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class VesselRelationEvidenceAttachment(Base):
    __tablename__ = "vessel_relation_evidence_attachment"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True)
    evidence_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    evidence_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    storage_file_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("storage_file.id"), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(256), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uploaded_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    voided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)

    __table_args__ = (
        Index("ix_vessel_relation_evidence_attachment_object", "evidence_type_code", "evidence_id"),
        Index("ux_vessel_relation_evidence_attachment_file", "evidence_type_code", "evidence_id", "storage_file_id", unique=True),
    )


class VesselAffiliationConclusion(Base, TimestampMixin):
    __tablename__ = "vessel_affiliation_conclusion"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True)
    conclusion_status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="CANDIDATE", index=True)
    affiliation_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="UNKNOWN")
    subject_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    counterparty_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence_level: Mapped[str] = mapped_column(String(32), nullable=False, default="UNKNOWN", index=True)
    evidence_ids_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conflict_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    voided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
