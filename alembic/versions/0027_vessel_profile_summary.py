"""vessel profile summary

Revision ID: 0027_vessel_profile_summary
Revises: 0026_vessel_data_trust_foundation
Create Date: 2026-05-09 15:00:00.000000

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


revision: str = "0027_vessel_profile_summary"
down_revision: Union[str, None] = "0026_vessel_data_trust_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _has_index(table: str, index_name: str) -> bool:
    if not _has_table(table):
        return False
    return index_name in {item["name"] for item in inspect(op.get_bind()).get_indexes(table)}


def _create_index_if_missing(table: str, index_name: str, columns: list[str], *, unique: bool = False) -> None:
    if _has_table(table) and not _has_index(table, index_name):
        op.create_index(index_name, table, columns, unique=unique)


def _drop_index_if_exists(table: str, index_name: str) -> None:
    if _has_index(table, index_name):
        op.drop_index(index_name, table_name=table)


def upgrade() -> None:
    if not _has_table("vessel_profile_summary"):
        op.create_table(
            "vessel_profile_summary",
            sa.Column("id", BigInteger(), autoincrement=True, nullable=False),
            sa.Column("vessel_profile_id", BigInteger(), nullable=False),
            sa.Column("ship_name", sa.String(length=128), nullable=True),
            sa.Column("current_mmsi", sa.String(length=16), nullable=True),
            sa.Column("ship_type_code", sa.String(length=64), nullable=True),
            sa.Column("ship_type_name", sa.String(length=128), nullable=True),
            sa.Column("deadweight_ton", sa.Numeric(18, 2), nullable=True),
            sa.Column("length_m", sa.Numeric(10, 2), nullable=True),
            sa.Column("width_m", sa.Numeric(10, 2), nullable=True),
            sa.Column("design_draft_m", sa.Numeric(10, 2), nullable=True),
            sa.Column("building_year", sa.Integer(), nullable=True),
            sa.Column("ship_age", sa.Integer(), nullable=True),
            sa.Column("primary_owner_name", sa.String(length=128), nullable=True),
            sa.Column("primary_operator_name", sa.String(length=128), nullable=True),
            sa.Column("primary_contact_name", sa.String(length=64), nullable=True),
            sa.Column("primary_contact_phone_masked", sa.String(length=32), nullable=True),
            sa.Column("contact_available", sa.Boolean(), nullable=True),
            sa.Column("profile_completeness_rate", sa.Numeric(5, 2), nullable=True),
            sa.Column("data_quality_score", sa.Numeric(5, 2), nullable=True),
            sa.Column("data_quality_level", sa.String(length=32), nullable=False, server_default="UNKNOWN"),
            sa.Column("identity_confidence_level", sa.String(length=32), nullable=False, server_default="UNKNOWN"),
            sa.Column("contact_trust_level", sa.String(length=32), nullable=False, server_default="UNKNOWN"),
            sa.Column("subject_consistency_level", sa.String(length=32), nullable=False, server_default="UNKNOWN"),
            sa.Column("quality_issue_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("missing_field_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("conflict_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("risk_level", sa.String(length=32), nullable=False, server_default="UNKNOWN"),
            sa.Column("risk_evidence_summary_json", sa.JSON(), nullable=True),
            sa.Column("certificate_missing_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("certificate_expiring_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("certificate_expired_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("latest_position_time", sa.DateTime(), nullable=True),
            sa.Column("latest_city_code", sa.String(length=12), nullable=True),
            sa.Column("latest_city_name", sa.String(length=128), nullable=True),
            sa.Column("ais_freshness_level", sa.String(length=32), nullable=False, server_default="UNKNOWN"),
            sa.Column("ais_unavailable_reason", sa.String(length=512), nullable=True),
            sa.Column("analysis_sample_tags_json", sa.JSON(), nullable=True),
            sa.Column("analysis_sample_tags_key", sa.String(length=512), nullable=True),
            sa.Column("data_sources_json", sa.JSON(), nullable=True),
            sa.Column("uncertainty_notes_json", sa.JSON(), nullable=True),
            sa.Column("source_layer", sa.String(length=64), nullable=False, server_default="PROFILE_SUMMARY"),
            sa.Column("coverage_rate", sa.Numeric(5, 2), nullable=True),
            sa.Column("summary_status_code", sa.String(length=32), nullable=False, server_default="READY"),
            sa.Column("summary_version", sa.String(length=32), nullable=False, server_default="ROUND_3_V1"),
            sa.Column("refreshed_at", sa.DateTime(), nullable=True),
            sa.Column("source_updated_at", sa.DateTime(), nullable=True),
            sa.Column("last_verified_at", sa.DateTime(), nullable=True),
            sa.Column("refresh_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["vessel_profile_id"], ["vessel_profile.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("vessel_profile_id", name="uq_vessel_profile_summary_profile"),
        )
    _create_index_if_missing("vessel_profile_summary", "idx_vessel_profile_summary_profile", ["vessel_profile_id"], unique=True)
    _create_index_if_missing("vessel_profile_summary", "idx_vessel_profile_summary_quality", ["data_quality_level"])
    _create_index_if_missing("vessel_profile_summary", "idx_vessel_profile_summary_risk", ["risk_level"])
    _create_index_if_missing("vessel_profile_summary", "idx_vessel_profile_summary_ais", ["ais_freshness_level"])
    _create_index_if_missing("vessel_profile_summary", "idx_vessel_profile_summary_city", ["latest_city_code"])
    _create_index_if_missing("vessel_profile_summary", "idx_vessel_profile_summary_status", ["summary_status_code"])
    _create_index_if_missing("vessel_profile_summary", "idx_vessel_profile_summary_tags", ["analysis_sample_tags_key"])
    _create_index_if_missing("vessel_profile_summary", "idx_vessel_profile_summary_source", ["source_layer"])


def downgrade() -> None:
    if _has_table("vessel_profile_summary"):
        for index_name in [
            "idx_vessel_profile_summary_source",
            "idx_vessel_profile_summary_tags",
            "idx_vessel_profile_summary_status",
            "idx_vessel_profile_summary_city",
            "idx_vessel_profile_summary_ais",
            "idx_vessel_profile_summary_risk",
            "idx_vessel_profile_summary_quality",
            "idx_vessel_profile_summary_profile",
        ]:
            _drop_index_if_exists("vessel_profile_summary", index_name)
        op.drop_table("vessel_profile_summary")
