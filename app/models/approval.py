from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ApprovalSubjectDefinition(Base, TimestampMixin):
    __tablename__ = "approval_subject_definition"
    __table_args__ = (
        UniqueConstraint("subject_type", name="uk_approval_subject_definition_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    subject_type: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    subject_name: Mapped[str] = mapped_column(String(128), nullable=False)
    module_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detail_path_template: Mapped[str | None] = mapped_column(String(256), nullable=True)
    read_permission_code: Mapped[str | None] = mapped_column(String(96), nullable=True)
    submit_permission_code: Mapped[str | None] = mapped_column(String(96), nullable=True)
    status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE", index=True)
    summary_schema_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ApprovalFlowDefinition(Base, TimestampMixin):
    __tablename__ = "approval_flow_definition"
    __table_args__ = (
        UniqueConstraint("flow_code", name="uk_approval_flow_definition_code"),
        Index("ix_approval_flow_definition_trigger", "subject_type", "trigger_action_code", "status_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    flow_code: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    flow_name: Mapped[str] = mapped_column(String(128), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    trigger_action_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    engine_type: Mapped[str] = mapped_column(String(32), nullable=False, default="CONFIG", index=True)
    approval_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="SINGLE")
    status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT", index=True)
    spiff_spec_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ApprovalStepDefinition(Base, TimestampMixin):
    __tablename__ = "approval_step_definition"
    __table_args__ = (
        UniqueConstraint("flow_id", "step_key", name="uk_approval_step_definition_key"),
        UniqueConstraint("flow_id", "step_order", name="uk_approval_step_definition_order"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    flow_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("approval_flow_definition.id"), nullable=False, index=True
    )
    step_key: Mapped[str] = mapped_column(String(96), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    step_name: Mapped[str] = mapped_column(String(128), nullable=False)
    step_type: Mapped[str] = mapped_column(String(32), nullable=False, default="HUMAN")
    assignment_type: Mapped[str] = mapped_column(String(64), nullable=False, default="PERMISSION")
    assignee_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    assignee_role_code: Mapped[str | None] = mapped_column(String(96), nullable=True)
    assignee_permission_code: Mapped[str | None] = mapped_column(String(96), nullable=True)
    action_policy: Mapped[str] = mapped_column(String(32), nullable=False, default="ANY_ONE")
    condition_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sla_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ApprovalInstance(Base, TimestampMixin):
    __tablename__ = "approval_instance"
    __table_args__ = (
        UniqueConstraint("instance_no", name="uk_approval_instance_no"),
        UniqueConstraint("idempotency_key", name="uk_approval_instance_idempotency"),
        Index("ix_approval_instance_subject", "subject_type", "subject_id", "subject_ref"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instance_no: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    flow_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("approval_flow_definition.id"), nullable=False)
    flow_code: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    subject_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    subject_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    subject_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    subject_name: Mapped[str] = mapped_column(String(256), nullable=False)
    subject_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    trigger_action_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="RUNNING", index=True)
    current_step_instance_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    submitter_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    engine_type: Mapped[str] = mapped_column(String(32), nullable=False, default="CONFIG")
    engine_state_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ApprovalStepInstance(Base, TimestampMixin):
    __tablename__ = "approval_step_instance"
    __table_args__ = (
        UniqueConstraint("instance_id", "step_key", name="uk_approval_step_instance_key"),
        UniqueConstraint("instance_id", "step_order", name="uk_approval_step_instance_order"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instance_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("approval_instance.id"), nullable=False, index=True
    )
    step_key: Mapped[str] = mapped_column(String(96), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    step_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", index=True)
    candidate_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    candidate_role_code: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    candidate_permission_code: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    acted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ApprovalSnapshot(Base, TimestampMixin):
    __tablename__ = "approval_snapshot"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instance_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("approval_instance.id"), nullable=False, unique=True, index=True
    )
    before_snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    diff_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    submit_payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ApprovalActionLog(Base):
    __tablename__ = "approval_action_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instance_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("approval_instance.id"), nullable=False, index=True
    )
    step_instance_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("approval_step_instance.id"), nullable=True, index=True
    )
    action_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    operator_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    from_status_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ApprovalOutbox(Base, TimestampMixin):
    __tablename__ = "approval_outbox"
    __table_args__ = (
        Index("ix_approval_outbox_dispatch", "status_code", "next_retry_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    instance_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("approval_instance.id"), nullable=False, index=True
    )
    subject_type: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    subject_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    decision_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status_code: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING", index=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
