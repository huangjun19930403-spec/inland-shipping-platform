"""analysis_task_runtime

Revision ID: 0008_analysis_task_runtime
Revises: 0007_foundation_dictionary_codes
Create Date: 2026-05-06 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008_analysis_task_runtime"
down_revision: Union[str, None] = "0007_foundation_dictionary_codes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analysis_job_definition",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_code", sa.String(length=64), nullable=False),
        sa.Column("job_name", sa.String(length=128), nullable=False),
        sa.Column("module_code", sa.String(length=64), nullable=False),
        sa.Column("module_name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("source_tables_json", sa.JSON(), nullable=True),
        sa.Column("target_tables_json", sa.JSON(), nullable=True),
        sa.Column("default_parameters_json", sa.JSON(), nullable=True),
        sa.Column("schedule_cron", sa.String(length=128), nullable=True),
        sa.Column("schedule_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_run_id", sa.BigInteger(), nullable=True),
        sa.Column("last_status_code", sa.String(length=64), nullable=True),
        sa.Column("last_finished_at", sa.DateTime(), nullable=True),
        sa.Column("last_result_summary_json", sa.JSON(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_code"),
    )
    op.create_index("ix_analysis_job_definition_enabled", "analysis_job_definition", ["enabled"])
    op.create_index("ix_analysis_job_definition_job_code", "analysis_job_definition", ["job_code"])
    op.create_index("ix_analysis_job_definition_last_run_id", "analysis_job_definition", ["last_run_id"])
    op.create_index("ix_analysis_job_definition_module_code", "analysis_job_definition", ["module_code"])

    with op.batch_alter_table("analysis_job_run") as batch_op:
        batch_op.add_column(sa.Column("celery_task_id", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("queued_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("duration_ms", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("input_rows", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("output_rows", sa.Integer(), nullable=True))
        batch_op.create_index("ix_analysis_job_run_celery_task_id", ["celery_task_id"])

    op.create_table(
        "fact_freight_city_daily",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("city_code", sa.String(length=12), nullable=False),
        sa.Column("city_name", sa.String(length=128), nullable=True),
        sa.Column("primary_region_id", sa.BigInteger(), nullable=True),
        sa.Column("freight_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inbound_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outbound_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tonnage", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("avg_unit_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("heat_value", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["primary_region_id"], ["region.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fact_freight_city_daily_city_code", "fact_freight_city_daily", ["city_code"])
    op.create_index("ix_fact_freight_city_daily_primary_region_id", "fact_freight_city_daily", ["primary_region_id"])
    op.create_index("ix_fact_freight_city_daily_stat_date", "fact_freight_city_daily", ["stat_date"])

    op.create_table(
        "fact_ship_city_daily",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("city_code", sa.String(length=12), nullable=False),
        sa.Column("city_name", sa.String(length=128), nullable=True),
        sa.Column("primary_region_id", sa.BigInteger(), nullable=True),
        sa.Column("ship_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_ship_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_deadweight_ton", sa.Numeric(18, 2), nullable=True),
        sa.Column("heat_value", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["primary_region_id"], ["region.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fact_ship_city_daily_city_code", "fact_ship_city_daily", ["city_code"])
    op.create_index("ix_fact_ship_city_daily_primary_region_id", "fact_ship_city_daily", ["primary_region_id"])
    op.create_index("ix_fact_ship_city_daily_stat_date", "fact_ship_city_daily", ["stat_date"])


def downgrade() -> None:
    op.drop_index("ix_fact_ship_city_daily_stat_date", table_name="fact_ship_city_daily")
    op.drop_index("ix_fact_ship_city_daily_primary_region_id", table_name="fact_ship_city_daily")
    op.drop_index("ix_fact_ship_city_daily_city_code", table_name="fact_ship_city_daily")
    op.drop_table("fact_ship_city_daily")

    op.drop_index("ix_fact_freight_city_daily_stat_date", table_name="fact_freight_city_daily")
    op.drop_index("ix_fact_freight_city_daily_primary_region_id", table_name="fact_freight_city_daily")
    op.drop_index("ix_fact_freight_city_daily_city_code", table_name="fact_freight_city_daily")
    op.drop_table("fact_freight_city_daily")

    with op.batch_alter_table("analysis_job_run") as batch_op:
        batch_op.drop_index("ix_analysis_job_run_celery_task_id")
        batch_op.drop_column("output_rows")
        batch_op.drop_column("input_rows")
        batch_op.drop_column("duration_ms")
        batch_op.drop_column("queued_at")
        batch_op.drop_column("celery_task_id")

    op.drop_index("ix_analysis_job_definition_module_code", table_name="analysis_job_definition")
    op.drop_index("ix_analysis_job_definition_last_run_id", table_name="analysis_job_definition")
    op.drop_index("ix_analysis_job_definition_job_code", table_name="analysis_job_definition")
    op.drop_index("ix_analysis_job_definition_enabled", table_name="analysis_job_definition")
    op.drop_table("analysis_job_definition")
