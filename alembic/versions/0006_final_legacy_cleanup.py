"""final_legacy_cleanup

Revision ID: 0006_final_legacy_cleanup
Revises: 0005_audit_governance_system_config
Create Date: 2026-04-30 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_final_legacy_cleanup"
down_revision: Union[str, None] = "0005_audit_governance_system_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table_name in (
        "ship_import_record",
        "ship_import_raw",
        "ship_import_batch",
        "stat_cargo_commodity_daily",
        "stat_ship_flow_daily",
        "stat_ship_city_daily",
        "stat_cargo_flow_daily",
        "stat_cargo_daily",
        "stat_cargo_city_daily",
        "cargo_channel_daily",
        "stat_job_run",
    ):
        op.drop_table(table_name)

    op.execute(
        "DELETE FROM code_sequence WHERE biz_code IN "
        "('COMMODITY_CATEGORY_CODE', 'COMMODITY_TYPE_CODE', 'SHIP_IMPORT_BATCH_NO')"
    )


def downgrade() -> None:
    op.create_table(
        "stat_job_run",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_code", sa.String(length=64), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("scope_desc", sa.String(length=256), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status_code", sa.String(length=64), nullable=False),
        sa.Column("affected_rows", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.Column("triggered_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stat_job_run_job_code", "stat_job_run", ["job_code"])
    op.create_index("ix_stat_job_run_stat_date", "stat_job_run", ["stat_date"])

    op.create_table(
        "cargo_channel_daily",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("source_type_code", sa.String(length=64), nullable=False),
        sa.Column("incoming_count", sa.Integer(), nullable=False),
        sa.Column("valid_count", sa.Integer(), nullable=False),
        sa.Column("invalid_count", sa.Integer(), nullable=False),
        sa.Column("confirmed_count", sa.Integer(), nullable=False),
        sa.Column("formalized_count", sa.Integer(), nullable=False),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cargo_channel_daily_source_type_code", "cargo_channel_daily", ["source_type_code"])
    op.create_index("ix_cargo_channel_daily_stat_date", "cargo_channel_daily", ["stat_date"])

    op.create_table(
        "stat_cargo_city_daily",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("city_code", sa.String(length=12), nullable=False),
        sa.Column("freight_count", sa.Integer(), nullable=False),
        sa.Column("tonnage", sa.Numeric(18, 2), nullable=False),
        sa.Column("loading_count", sa.Integer(), nullable=False),
        sa.Column("unloading_count", sa.Integer(), nullable=False),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stat_cargo_city_daily_city_code", "stat_cargo_city_daily", ["city_code"])
    op.create_index("ix_stat_cargo_city_daily_stat_date", "stat_cargo_city_daily", ["stat_date"])

    op.create_table(
        "stat_cargo_daily",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("total_freight_count", sa.Integer(), nullable=False),
        sa.Column("total_tonnage", sa.Numeric(18, 2), nullable=False),
        sa.Column("total_estimated_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stat_cargo_daily_stat_date", "stat_cargo_daily", ["stat_date"])

    op.create_table(
        "stat_cargo_flow_daily",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("origin_city_code", sa.String(length=12), nullable=False),
        sa.Column("destination_city_code", sa.String(length=12), nullable=False),
        sa.Column("freight_count", sa.Integer(), nullable=False),
        sa.Column("tonnage", sa.Numeric(18, 2), nullable=False),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stat_cargo_flow_daily_destination_city_code", "stat_cargo_flow_daily", ["destination_city_code"])
    op.create_index("ix_stat_cargo_flow_daily_origin_city_code", "stat_cargo_flow_daily", ["origin_city_code"])
    op.create_index("ix_stat_cargo_flow_daily_stat_date", "stat_cargo_flow_daily", ["stat_date"])

    op.create_table(
        "stat_ship_city_daily",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("city_code", sa.String(length=12), nullable=False),
        sa.Column("active_ship_count", sa.Integer(), nullable=False),
        sa.Column("total_deadweight_ton", sa.Numeric(18, 2), nullable=True),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stat_ship_city_daily_city_code", "stat_ship_city_daily", ["city_code"])
    op.create_index("ix_stat_ship_city_daily_stat_date", "stat_ship_city_daily", ["stat_date"])

    op.create_table(
        "stat_ship_flow_daily",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("origin_city_code", sa.String(length=12), nullable=False),
        sa.Column("destination_city_code", sa.String(length=12), nullable=False),
        sa.Column("ship_count", sa.Integer(), nullable=False),
        sa.Column("voyage_count", sa.Integer(), nullable=False),
        sa.Column("total_deadweight_ton", sa.Numeric(18, 2), nullable=True),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stat_ship_flow_daily_destination_city_code", "stat_ship_flow_daily", ["destination_city_code"])
    op.create_index("ix_stat_ship_flow_daily_origin_city_code", "stat_ship_flow_daily", ["origin_city_code"])
    op.create_index("ix_stat_ship_flow_daily_stat_date", "stat_ship_flow_daily", ["stat_date"])

    op.create_table(
        "stat_cargo_commodity_daily",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("commodity_standard_id", sa.BigInteger(), nullable=False),
        sa.Column("freight_count", sa.Integer(), nullable=False),
        sa.Column("tonnage", sa.Numeric(18, 2), nullable=False),
        sa.Column("avg_unit_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["commodity_standard_id"], ["commodity_standard.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stat_cargo_commodity_daily_commodity_standard_id", "stat_cargo_commodity_daily", ["commodity_standard_id"])
    op.create_index("ix_stat_cargo_commodity_daily_stat_date", "stat_cargo_commodity_daily", ["stat_date"])

    op.create_table(
        "ship_import_batch",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("batch_no", sa.String(length=32), nullable=False),
        sa.Column("source_type_code", sa.String(length=64), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("status_code", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("operator_id", sa.BigInteger(), nullable=True),
        sa.Column("remark", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_no"),
    )
    op.create_table(
        "ship_import_raw",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.BigInteger(), nullable=False),
        sa.Column("row_no", sa.Integer(), nullable=False),
        sa.Column("raw_payload_json", sa.JSON(), nullable=False),
        sa.Column("parse_status_code", sa.String(length=64), nullable=False),
        sa.Column("parse_message", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["ship_import_batch.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "row_no", name="uk_ship_import_raw_row"),
    )
    op.create_index("ix_ship_import_raw_batch_id", "ship_import_raw", ["batch_id"])
    op.create_table(
        "ship_import_record",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("batch_id", sa.BigInteger(), nullable=False),
        sa.Column("raw_id", sa.BigInteger(), nullable=False),
        sa.Column("ship_id", sa.BigInteger(), nullable=True),
        sa.Column("action_type_code", sa.String(length=64), nullable=False),
        sa.Column("result_code", sa.String(length=64), nullable=False),
        sa.Column("message", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["ship_import_batch.id"]),
        sa.ForeignKeyConstraint(["raw_id"], ["ship_import_raw.id"]),
        sa.ForeignKeyConstraint(["ship_id"], ["ship_profile.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ship_import_record_batch_id", "ship_import_record", ["batch_id"])
    op.create_index("ix_ship_import_record_raw_id", "ship_import_record", ["raw_id"])
    op.create_index("ix_ship_import_record_ship_id", "ship_import_record", ["ship_id"])
