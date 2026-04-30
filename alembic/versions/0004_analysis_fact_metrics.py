"""analysis_fact_metrics

Revision ID: 0004_analysis_fact_metrics
Revises: 0003_freight_candidate_chain
Create Date: 2026-04-30 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_analysis_fact_metrics"
down_revision: Union[str, None] = "0003_freight_candidate_chain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analysis_indicator_definition",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("module_code", sa.String(length=64), nullable=False),
        sa.Column("indicator_code", sa.String(length=64), nullable=False),
        sa.Column("indicator_name", sa.String(length=128), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("chart_type_code", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("indicator_code"),
    )
    op.create_index("ix_analysis_indicator_definition_module_code", "analysis_indicator_definition", ["module_code"])

    op.create_table(
        "analysis_bucket_definition",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("bucket_group_code", sa.String(length=64), nullable=False),
        sa.Column("bucket_code", sa.String(length=64), nullable=False),
        sa.Column("bucket_name", sa.String(length=128), nullable=False),
        sa.Column("min_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("max_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analysis_bucket_definition_bucket_group_code", "analysis_bucket_definition", ["bucket_group_code"])
    op.create_index("ix_analysis_bucket_definition_bucket_code", "analysis_bucket_definition", ["bucket_code"])

    op.create_table(
        "analysis_job_run",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_code", sa.String(length=64), nullable=False),
        sa.Column("job_name", sa.String(length=128), nullable=False),
        sa.Column("module_code", sa.String(length=64), nullable=False),
        sa.Column("module_name", sa.String(length=128), nullable=False),
        sa.Column("stat_date_from", sa.Date(), nullable=True),
        sa.Column("stat_date_to", sa.Date(), nullable=True),
        sa.Column("status_code", sa.String(length=64), nullable=False),
        sa.Column("status_name", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("affected_rows", sa.Integer(), nullable=True),
        sa.Column("parameters_json", sa.JSON(), nullable=True),
        sa.Column("result_summary_json", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("triggered_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("job_code", "module_code", "status_code", "stat_date_from", "stat_date_to"):
        op.create_index(f"ix_analysis_job_run_{column}", "analysis_job_run", [column])

    op.create_table(
        "analysis_snapshot",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("snapshot_code", sa.String(length=64), nullable=False),
        sa.Column("module_code", sa.String(length=64), nullable=False),
        sa.Column("snapshot_name", sa.String(length=128), nullable=False),
        sa.Column("stat_date_from", sa.Date(), nullable=True),
        sa.Column("stat_date_to", sa.Date(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("generated_by_job_id", sa.BigInteger(), nullable=True),
        sa.Column("generated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["generated_by_job_id"], ["analysis_job_run.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_code"),
    )
    op.create_index("ix_analysis_snapshot_module_code", "analysis_snapshot", ["module_code"])
    op.create_index("ix_analysis_snapshot_generated_by_job_id", "analysis_snapshot", ["generated_by_job_id"])

    op.create_table(
        "fact_freight_daily",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("freight_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confirmed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_inbound_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tonnage", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("total_estimated_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("avg_unit_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fact_freight_daily_stat_date", "fact_freight_daily", ["stat_date"])

    op.create_table(
        "fact_freight_flow_daily",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("origin_node_id", sa.BigInteger(), nullable=True),
        sa.Column("destination_node_id", sa.BigInteger(), nullable=True),
        sa.Column("origin_region_id", sa.BigInteger(), nullable=True),
        sa.Column("destination_region_id", sa.BigInteger(), nullable=True),
        sa.Column("origin_city_code", sa.String(length=12), nullable=True),
        sa.Column("destination_city_code", sa.String(length=12), nullable=True),
        sa.Column("commodity_standard_id", sa.BigInteger(), nullable=True),
        sa.Column("freight_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tonnage", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("avg_unit_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("min_unit_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("max_unit_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["commodity_standard_id"], ["commodity_standard.id"]),
        sa.ForeignKeyConstraint(["destination_node_id"], ["transport_node.id"]),
        sa.ForeignKeyConstraint(["destination_region_id"], ["region.id"]),
        sa.ForeignKeyConstraint(["origin_node_id"], ["transport_node.id"]),
        sa.ForeignKeyConstraint(["origin_region_id"], ["region.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("stat_date", "origin_node_id", "destination_node_id", "origin_region_id", "destination_region_id", "origin_city_code", "destination_city_code", "commodity_standard_id"):
        op.create_index(f"ix_fact_freight_flow_daily_{column}", "fact_freight_flow_daily", [column])

    op.create_table(
        "fact_freight_commodity_daily",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("commodity_standard_id", sa.BigInteger(), nullable=False),
        sa.Column("commodity_category_id", sa.BigInteger(), nullable=True),
        sa.Column("commodity_type_id", sa.BigInteger(), nullable=True),
        sa.Column("freight_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tonnage", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("avg_unit_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["commodity_category_id"], ["commodity_category.id"]),
        sa.ForeignKeyConstraint(["commodity_standard_id"], ["commodity_standard.id"]),
        sa.ForeignKeyConstraint(["commodity_type_id"], ["commodity_type.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("stat_date", "commodity_standard_id", "commodity_category_id", "commodity_type_id"):
        op.create_index(f"ix_fact_freight_commodity_daily_{column}", "fact_freight_commodity_daily", [column])

    op.create_table(
        "fact_freight_price_daily",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("price_bucket_code", sa.String(length=64), nullable=False),
        sa.Column("price_bucket_name", sa.String(length=128), nullable=False),
        sa.Column("min_unit_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("max_unit_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("freight_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tonnage", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("avg_unit_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fact_freight_price_daily_stat_date", "fact_freight_price_daily", ["stat_date"])
    op.create_index("ix_fact_freight_price_daily_price_bucket_code", "fact_freight_price_daily", ["price_bucket_code"])

    op.create_table(
        "fact_ship_daily",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("ship_type_code", sa.String(length=64), nullable=True),
        sa.Column("registry_city_code", sa.String(length=12), nullable=True),
        sa.Column("business_region_id", sa.BigInteger(), nullable=True),
        sa.Column("operation_status_code", sa.String(length=64), nullable=True),
        sa.Column("age_bucket_code", sa.String(length=64), nullable=True),
        sa.Column("age_bucket_name", sa.String(length=128), nullable=True),
        sa.Column("deadweight_bucket_code", sa.String(length=64), nullable=True),
        sa.Column("deadweight_bucket_name", sa.String(length=128), nullable=True),
        sa.Column("ship_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_ship_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_deadweight_ton", sa.Numeric(18, 2), nullable=True),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["business_region_id"], ["region.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("stat_date", "ship_type_code", "registry_city_code", "business_region_id", "operation_status_code", "age_bucket_code", "deadweight_bucket_code"):
        op.create_index(f"ix_fact_ship_daily_{column}", "fact_ship_daily", [column])

    op.create_table(
        "fact_ship_flow_daily",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("origin_node_id", sa.BigInteger(), nullable=True),
        sa.Column("destination_node_id", sa.BigInteger(), nullable=True),
        sa.Column("origin_region_id", sa.BigInteger(), nullable=True),
        sa.Column("destination_region_id", sa.BigInteger(), nullable=True),
        sa.Column("origin_city_code", sa.String(length=12), nullable=True),
        sa.Column("destination_city_code", sa.String(length=12), nullable=True),
        sa.Column("ship_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("voyage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_deadweight_ton", sa.Numeric(18, 2), nullable=True),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["destination_node_id"], ["transport_node.id"]),
        sa.ForeignKeyConstraint(["destination_region_id"], ["region.id"]),
        sa.ForeignKeyConstraint(["origin_node_id"], ["transport_node.id"]),
        sa.ForeignKeyConstraint(["origin_region_id"], ["region.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("stat_date", "origin_node_id", "destination_node_id", "origin_region_id", "destination_region_id", "origin_city_code", "destination_city_code"):
        op.create_index(f"ix_fact_ship_flow_daily_{column}", "fact_ship_flow_daily", [column])

    op.create_table(
        "fact_region_daily",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("region_id", sa.BigInteger(), nullable=True),
        sa.Column("node_id", sa.BigInteger(), nullable=True),
        sa.Column("freight_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inbound_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outbound_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tonnage", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("ship_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_unit_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("heat_value", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["node_id"], ["transport_node.id"]),
        sa.ForeignKeyConstraint(["region_id"], ["region.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("stat_date", "region_id", "node_id"):
        op.create_index(f"ix_fact_region_daily_{column}", "fact_region_daily", [column])


def downgrade() -> None:
    for column in ("stat_date", "region_id", "node_id"):
        op.drop_index(f"ix_fact_region_daily_{column}", table_name="fact_region_daily")
    op.drop_table("fact_region_daily")

    for column in ("stat_date", "origin_node_id", "destination_node_id", "origin_region_id", "destination_region_id", "origin_city_code", "destination_city_code"):
        op.drop_index(f"ix_fact_ship_flow_daily_{column}", table_name="fact_ship_flow_daily")
    op.drop_table("fact_ship_flow_daily")

    for column in ("stat_date", "ship_type_code", "registry_city_code", "business_region_id", "operation_status_code", "age_bucket_code", "deadweight_bucket_code"):
        op.drop_index(f"ix_fact_ship_daily_{column}", table_name="fact_ship_daily")
    op.drop_table("fact_ship_daily")

    op.drop_index("ix_fact_freight_price_daily_price_bucket_code", table_name="fact_freight_price_daily")
    op.drop_index("ix_fact_freight_price_daily_stat_date", table_name="fact_freight_price_daily")
    op.drop_table("fact_freight_price_daily")

    for column in ("stat_date", "commodity_standard_id", "commodity_category_id", "commodity_type_id"):
        op.drop_index(f"ix_fact_freight_commodity_daily_{column}", table_name="fact_freight_commodity_daily")
    op.drop_table("fact_freight_commodity_daily")

    for column in ("stat_date", "origin_node_id", "destination_node_id", "origin_region_id", "destination_region_id", "origin_city_code", "destination_city_code", "commodity_standard_id"):
        op.drop_index(f"ix_fact_freight_flow_daily_{column}", table_name="fact_freight_flow_daily")
    op.drop_table("fact_freight_flow_daily")

    op.drop_index("ix_fact_freight_daily_stat_date", table_name="fact_freight_daily")
    op.drop_table("fact_freight_daily")

    op.drop_index("ix_analysis_snapshot_generated_by_job_id", table_name="analysis_snapshot")
    op.drop_index("ix_analysis_snapshot_module_code", table_name="analysis_snapshot")
    op.drop_table("analysis_snapshot")

    for column in ("job_code", "module_code", "status_code", "stat_date_from", "stat_date_to"):
        op.drop_index(f"ix_analysis_job_run_{column}", table_name="analysis_job_run")
    op.drop_table("analysis_job_run")

    op.drop_index("ix_analysis_bucket_definition_bucket_code", table_name="analysis_bucket_definition")
    op.drop_index("ix_analysis_bucket_definition_bucket_group_code", table_name="analysis_bucket_definition")
    op.drop_table("analysis_bucket_definition")

    op.drop_index("ix_analysis_indicator_definition_module_code", table_name="analysis_indicator_definition")
    op.drop_table("analysis_indicator_definition")
