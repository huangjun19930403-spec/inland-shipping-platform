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
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import AuditFlowMixin, Base, SoftDeleteMixin, TimestampMixin


class Freight(Base, TimestampMixin, SoftDeleteMixin, AuditFlowMixin):
    __tablename__ = "freight"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    freight_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    source_channel_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_ref_no: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    source_candidate_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
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
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class FreightSourceInbound(Base, TimestampMixin):
    __tablename__ = "freight_source_inbound"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    inbound_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    source_channel_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_ref_no: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    sender_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sender_contact: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    parse_task_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)


class FreightAiParseTask(Base, TimestampMixin):
    __tablename__ = "freight_ai_parse_task"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    source_inbound_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("freight_source_inbound.id"), nullable=True, index=True
    )
    source_type_code: Mapped[str] = mapped_column(String(64), nullable=False)
    source_channel_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ai_provider_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class FreightClue(Base, TimestampMixin):
    __tablename__ = "freight_clue"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    clue_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    parse_task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("freight_ai_parse_task.id"), nullable=False, index=True
    )
    source_inbound_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("freight_source_inbound.id"), nullable=True, index=True
    )
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    status_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    parse_result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class FreightCandidate(Base, TimestampMixin):
    __tablename__ = "freight_candidate"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    candidate_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    parse_task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("freight_ai_parse_task.id"), nullable=False, index=True
    )
    clue_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("freight_clue.id"), nullable=True, index=True
    )
    source_inbound_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("freight_source_inbound.id"), nullable=True, index=True
    )
    cargo_title: Mapped[str] = mapped_column(String(256), nullable=False)
    cargo_description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    commodity_standard_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("commodity_standard.id"), nullable=True, index=True
    )
    commodity_match_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    commodity_match_score: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    packaging_form_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    estimated_tonnage: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    min_tonnage: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    max_tonnage: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    unit_price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    total_price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    price_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    settlement_method_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    origin_text: Mapped[str | None] = mapped_column(String(256), nullable=True)
    destination_text: Mapped[str | None] = mapped_column(String(256), nullable=True)
    origin_node_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("transport_node.id"), nullable=True, index=True
    )
    destination_node_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("transport_node.id"), nullable=True, index=True
    )
    origin_province_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    origin_city_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    origin_district_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    destination_province_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
    destination_city_code: Mapped[str | None] = mapped_column(String(12), nullable=True)
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
    contact_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    contact_wechat: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    match_basis_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    confirmed_freight_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("freight.id"), nullable=True, index=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class FreightCandidateFeedback(Base):
    __tablename__ = "freight_candidate_feedback"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("freight_candidate.id"), nullable=False, index=True
    )
    action_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    before_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    feedback_remark: Mapped[str | None] = mapped_column(String(512), nullable=True)
    operator_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    operated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


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
