from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuditFlowMixin, Base, SoftDeleteMixin, TimestampMixin


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


class VesselProfile(Base, TimestampMixin, SoftDeleteMixin, AuditFlowMixin):
    __tablename__ = "vessel_profile"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    vessel_identity_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("vessel_identity.id"), nullable=True, index=True
    )
    ais_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    ship_name: Mapped[str] = mapped_column(String(128), nullable=False)
    ship_name_en: Mapped[str | None] = mapped_column(String(256), nullable=True)
    current_mmsi: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    ship_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    navigation_power_type_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    profile_status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="NEED_GOVERNANCE")
    identity_status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="UNLINKED")
    quality_level_code: Mapped[str] = mapped_column(String(64), nullable=False, default="LOW")
    operation_status_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    home_port_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    home_port_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    owner_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    building_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
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


class VesselCargoCapability(Base):
    __tablename__ = "vessel_cargo_capability"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), unique=True, nullable=False
    )
    capability_tags_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    commodity_type_codes_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    preferred_cargo_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    has_self_unloading: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_container_fittings: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_carry_dangerous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    temperature_control: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cargo_handling_notes: Mapped[str | None] = mapped_column(String(512), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselOwnerPeriod(Base, TimestampMixin):
    __tablename__ = "vessel_owner_period"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    party_name: Mapped[str] = mapped_column(String(128), nullable=False)
    party_relation_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="OWNER")
    certificate_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mobile_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    landline_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    address: Mapped[str | None] = mapped_column(String(256), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class VesselOperatorPeriod(Base, TimestampMixin):
    __tablename__ = "vessel_operator_period"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    operator_name: Mapped[str] = mapped_column(String(128), nullable=False)
    operator_role_code: Mapped[str] = mapped_column(String(64), nullable=False, default="OPERATOR")
    manager_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    main_navigation_area_desc: Mapped[str | None] = mapped_column(String(256), nullable=True)
    usual_route_desc: Mapped[str | None] = mapped_column(String(256), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dispatch_contact_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dispatch_contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    risk_level_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class VesselContact(Base, TimestampMixin):
    __tablename__ = "vessel_contact"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    contact_name: Mapped[str] = mapped_column(String(64), nullable=False)
    contact_role_code: Mapped[str] = mapped_column(String(64), nullable=False)
    mobile_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    wechat: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)


class VesselCrewAssignment(Base, TimestampMixin):
    __tablename__ = "vessel_crew_assignment"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    crew_name: Mapped[str] = mapped_column(String(64), nullable=False)
    crew_role_code: Mapped[str] = mapped_column(String(64), nullable=False)
    certificate_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mobile_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


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
    verify_status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="PENDING")
    remark: Mapped[str | None] = mapped_column(String(512), nullable=True)


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


class VesselManualPreference(Base):
    __tablename__ = "vessel_manual_preference"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), unique=True, nullable=False
    )
    preferred_cargo_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    avoided_cargo_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    preferred_route_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    unavailable_period_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    freight_preference_text: Mapped[str | None] = mapped_column(String(512), nullable=True)
    risk_note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselBehaviorProfile(Base):
    __tablename__ = "vessel_behavior_profile"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), unique=True, nullable=False
    )
    active_city_codes_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    usual_route_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    cargo_preference_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    contactability_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    activity_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False, default="LOCAL_SAMPLE")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselQualitySnapshot(Base):
    __tablename__ = "vessel_quality_snapshot"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), unique=True, nullable=False
    )
    quality_level_code: Mapped[str] = mapped_column(String(64), nullable=False)
    completeness_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    contact_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    certificate_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    identity_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    issue_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VesselQualityIssue(Base, TimestampMixin):
    __tablename__ = "vessel_quality_issue"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    issue_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity_code: Mapped[str] = mapped_column(String(64), nullable=False, default="MEDIUM")
    issue_title: Mapped[str] = mapped_column(String(128), nullable=False)
    issue_desc: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="OPEN", index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class VesselIdentityCandidate(Base, TimestampMixin):
    __tablename__ = "vessel_identity_candidate"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    target_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    candidate_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status_code: Mapped[str] = mapped_column(String(64), nullable=False, default="PENDING", index=True)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class VesselChangeEvent(Base):
    __tablename__ = "vessel_change_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    vessel_profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("vessel_profile.id"), nullable=False, index=True
    )
    event_type_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_title: Mapped[str] = mapped_column(String(128), nullable=False)
    before_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    operator_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
