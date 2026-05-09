"""vessel_data_trust_foundation

Revision ID: 0026_vessel_data_trust_foundation
Revises: 0025_vessel_certificate_ledger_refactor
Create Date: 2026-05-09 10:30:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import BigInteger


@compiles(BigInteger, "sqlite")
def _compile_bigint_sqlite(_type, _compiler, **_kw):
    return "INTEGER"


revision: str = "0026_vessel_data_trust_foundation"
down_revision: Union[str, None] = "0025_vessel_certificate_ledger_refactor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return column in {item["name"] for item in inspect(op.get_bind()).get_columns(table)}


def _has_index(table: str, index_name: str) -> bool:
    if not _has_table(table):
        return False
    return index_name in {item["name"] for item in inspect(op.get_bind()).get_indexes(table)}


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if not _has_table(table) or _has_column(table, column.name):
        return
    with op.batch_alter_table(table) as batch_op:
        batch_op.add_column(column)


def _drop_column_if_exists(table: str, column: str) -> None:
    if not _has_table(table) or not _has_column(table, column):
        return
    with op.batch_alter_table(table) as batch_op:
        batch_op.drop_column(column)


def _create_index_if_missing(table: str, index_name: str, columns: list[str]) -> None:
    if _has_table(table) and not _has_index(table, index_name):
        op.create_index(index_name, table, columns)


def _drop_index_if_exists(table: str, index_name: str) -> None:
    if _has_index(table, index_name):
        op.drop_index(index_name, table_name=table)


def _add_trust_columns(table: str, *, include_primary: bool = True, include_current: bool = False) -> None:
    if include_current:
        _add_column_if_missing(table, sa.Column("start_date", sa.Date(), nullable=True))
        _add_column_if_missing(table, sa.Column("end_date", sa.Date(), nullable=True))
        _add_column_if_missing(table, sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()))
    if include_primary:
        _create_index_if_missing(table, f"idx_{table}_profile_primary", ["vessel_profile_id", "is_current", "is_primary"])
    _add_column_if_missing(table, sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    _add_column_if_missing(table, sa.Column("verified_status_code", sa.String(length=32), nullable=False, server_default="UNVERIFIED"))
    _add_column_if_missing(table, sa.Column("source_type_code", sa.String(length=64), nullable=False, server_default="MANUAL"))
    _add_column_if_missing(table, sa.Column("source_trace_id", sa.String(length=128), nullable=True))
    _add_column_if_missing(table, sa.Column("voided_at", sa.DateTime(), nullable=True))
    _add_column_if_missing(table, sa.Column("voided_by", BigInteger(), nullable=True))
    _add_column_if_missing(table, sa.Column("void_reason", sa.String(length=500), nullable=True))
    _create_index_if_missing(table, f"idx_{table}_profile_current", ["vessel_profile_id", "is_current"])
    _create_index_if_missing(table, f"idx_{table}_revision", ["id", "revision"])


def upgrade() -> None:
    _add_trust_columns("vessel_owner_period")
    _add_trust_columns("vessel_operator_period")
    _add_trust_columns("vessel_contact", include_current=True)
    _add_trust_columns("vessel_crew_assignment", include_primary=False)

    _add_column_if_missing("vessel_person_certificate", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
    _add_column_if_missing("vessel_person_certificate", sa.Column("source_type_code", sa.String(length=64), nullable=False, server_default="MANUAL"))
    _add_column_if_missing("vessel_person_certificate", sa.Column("source_trace_id", sa.String(length=128), nullable=True))
    _create_index_if_missing("vessel_person_certificate", "idx_vessel_person_certificate_revision", ["id", "revision"])

    _add_column_if_missing("vessel_identifier_history", sa.Column("source_trace_id", sa.String(length=128), nullable=True))
    _add_column_if_missing("vessel_identifier_history", sa.Column("status_code", sa.String(length=32), nullable=False, server_default="ACTIVE"))
    _add_column_if_missing("vessel_identifier_history", sa.Column("confidence_score", sa.Integer(), nullable=False, server_default="100"))
    _create_index_if_missing("vessel_identifier_history", "idx_vessel_identifier_history_status", ["identifier_type_code", "identifier_value", "status_code"])

    _add_column_if_missing("vessel_change_event", sa.Column("object_type", sa.String(length=64), nullable=True))
    _add_column_if_missing("vessel_change_event", sa.Column("object_id", sa.String(length=64), nullable=True))
    _add_column_if_missing("vessel_change_event", sa.Column("changed_fields_json", sa.JSON(), nullable=True))
    _add_column_if_missing("vessel_change_event", sa.Column("reason", sa.String(length=500), nullable=True))

    if not _has_table("vessel_data_quality_issue"):
        op.create_table(
            "vessel_data_quality_issue",
            sa.Column("id", BigInteger(), autoincrement=True, nullable=False),
            sa.Column("issue_type_code", sa.String(length=64), nullable=False),
            sa.Column("severity_code", sa.String(length=32), nullable=False, server_default="MEDIUM"),
            sa.Column("affected_object_type", sa.String(length=64), nullable=False),
            sa.Column("affected_object_id", sa.String(length=64), nullable=False),
            sa.Column("vessel_profile_id", BigInteger(), nullable=True),
            sa.Column("field_name", sa.String(length=128), nullable=True),
            sa.Column("fingerprint", sa.String(length=64), nullable=False),
            sa.Column("evidence_source", sa.String(length=64), nullable=True),
            sa.Column("impact_scope_json", sa.JSON(), nullable=True),
            sa.Column("status_code", sa.String(length=32), nullable=False, server_default="OPEN"),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.Column("resolved_by", BigInteger(), nullable=True),
            sa.Column("resolved_evidence", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["vessel_profile_id"], ["vessel_profile.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("vessel_data_quality_issue", "idx_vessel_quality_issue_fingerprint", ["fingerprint"])
    _create_index_if_missing("vessel_data_quality_issue", "idx_vessel_quality_issue_profile_status", ["vessel_profile_id", "status_code"])
    _create_index_if_missing("vessel_data_quality_issue", "idx_vessel_quality_issue_type_status", ["issue_type_code", "status_code"])

    if not _has_table("vessel_recognition_field_diff"):
        op.create_table(
            "vessel_recognition_field_diff",
            sa.Column("id", BigInteger(), autoincrement=True, nullable=False),
            sa.Column("vessel_profile_id", BigInteger(), nullable=False),
            sa.Column("recognition_object_type", sa.String(length=64), nullable=False),
            sa.Column("recognition_id", BigInteger(), nullable=False),
            sa.Column("target_object_type", sa.String(length=64), nullable=False),
            sa.Column("target_object_id", BigInteger(), nullable=False),
            sa.Column("field_name", sa.String(length=128), nullable=False),
            sa.Column("current_value_text", sa.Text(), nullable=True),
            sa.Column("recognized_value_text", sa.Text(), nullable=True),
            sa.Column("confidence_score", sa.Integer(), nullable=True),
            sa.Column("evidence_text", sa.Text(), nullable=True),
            sa.Column("adopt_status_code", sa.String(length=32), nullable=False, server_default="REVIEW_REQUIRED"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["vessel_profile_id"], ["vessel_profile.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("vessel_recognition_field_diff", "idx_vessel_recognition_field_diff_recognition", ["recognition_object_type", "recognition_id"])
    _create_index_if_missing("vessel_recognition_field_diff", "idx_vessel_recognition_field_diff_profile", ["vessel_profile_id"])

    if not _has_table("vessel_recognition_adoption_record"):
        op.create_table(
            "vessel_recognition_adoption_record",
            sa.Column("id", BigInteger(), autoincrement=True, nullable=False),
            sa.Column("vessel_profile_id", BigInteger(), nullable=False),
            sa.Column("recognition_object_type", sa.String(length=64), nullable=False),
            sa.Column("recognition_id", BigInteger(), nullable=False),
            sa.Column("target_object_type", sa.String(length=64), nullable=False),
            sa.Column("target_object_id", BigInteger(), nullable=False),
            sa.Column("adopted_fields_json", sa.JSON(), nullable=True),
            sa.Column("skipped_fields_json", sa.JSON(), nullable=True),
            sa.Column("confirmed_by", BigInteger(), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(), nullable=False),
            sa.Column("reason", sa.String(length=500), nullable=True),
            sa.Column("change_event_id", BigInteger(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["change_event_id"], ["vessel_change_event.id"]),
            sa.ForeignKeyConstraint(["vessel_profile_id"], ["vessel_profile.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("vessel_recognition_adoption_record", "idx_vessel_recognition_adoption_record_recognition", ["recognition_object_type", "recognition_id"])
    _create_index_if_missing("vessel_recognition_adoption_record", "idx_vessel_recognition_adoption_record_profile", ["vessel_profile_id"])


def downgrade() -> None:
    if _has_table("vessel_recognition_adoption_record"):
        _drop_index_if_exists("vessel_recognition_adoption_record", "idx_vessel_recognition_adoption_record_profile")
        _drop_index_if_exists("vessel_recognition_adoption_record", "idx_vessel_recognition_adoption_record_recognition")
        op.drop_table("vessel_recognition_adoption_record")
    if _has_table("vessel_recognition_field_diff"):
        _drop_index_if_exists("vessel_recognition_field_diff", "idx_vessel_recognition_field_diff_profile")
        _drop_index_if_exists("vessel_recognition_field_diff", "idx_vessel_recognition_field_diff_recognition")
        op.drop_table("vessel_recognition_field_diff")
    if _has_table("vessel_data_quality_issue"):
        _drop_index_if_exists("vessel_data_quality_issue", "idx_vessel_quality_issue_type_status")
        _drop_index_if_exists("vessel_data_quality_issue", "idx_vessel_quality_issue_profile_status")
        _drop_index_if_exists("vessel_data_quality_issue", "idx_vessel_quality_issue_fingerprint")
        op.drop_table("vessel_data_quality_issue")

    for column in ["reason", "changed_fields_json", "object_id", "object_type"]:
        _drop_column_if_exists("vessel_change_event", column)
    _drop_index_if_exists("vessel_identifier_history", "idx_vessel_identifier_history_status")
    for column in ["confidence_score", "status_code", "source_trace_id"]:
        _drop_column_if_exists("vessel_identifier_history", column)
    _drop_index_if_exists("vessel_person_certificate", "idx_vessel_person_certificate_revision")
    for column in ["source_trace_id", "source_type_code", "revision"]:
        _drop_column_if_exists("vessel_person_certificate", column)
    for table, include_current in [
        ("vessel_crew_assignment", False),
        ("vessel_contact", True),
        ("vessel_operator_period", False),
        ("vessel_owner_period", False),
    ]:
        _drop_index_if_exists(table, f"idx_{table}_revision")
        _drop_index_if_exists(table, f"idx_{table}_profile_primary")
        _drop_index_if_exists(table, f"idx_{table}_profile_current")
        for column in ["void_reason", "voided_by", "voided_at", "source_trace_id", "source_type_code", "verified_status_code", "revision"]:
            _drop_column_if_exists(table, column)
        if include_current:
            for column in ["is_current", "end_date", "start_date"]:
                _drop_column_if_exists(table, column)
