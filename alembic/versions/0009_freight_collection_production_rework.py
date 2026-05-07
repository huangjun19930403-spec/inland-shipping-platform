"""freight_collection_production_rework

Revision ID: 0009_freight_collection_production_rework
Revises: 0008_analysis_task_runtime
Create Date: 2026-05-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009_freight_collection_production_rework"
down_revision: Union[str, None] = "0008_analysis_task_runtime"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_freight_candidate_feedback_action_code", table_name="freight_candidate_feedback")
    op.drop_index("ix_freight_candidate_feedback_candidate_id", table_name="freight_candidate_feedback")
    op.drop_table("freight_candidate_feedback")
    for column in (
        "confirmed_freight_id",
        "status_code",
        "destination_region_id_cache",
        "origin_region_id_cache",
        "destination_node_id",
        "origin_node_id",
        "commodity_standard_id",
        "source_inbound_id",
        "clue_id",
        "parse_task_id",
    ):
        op.drop_index(f"ix_freight_candidate_{column}", table_name="freight_candidate")
    op.drop_table("freight_candidate")
    op.drop_index("ix_freight_clue_status_code", table_name="freight_clue")
    op.drop_index("ix_freight_clue_source_inbound_id", table_name="freight_clue")
    op.drop_index("ix_freight_clue_parse_task_id", table_name="freight_clue")
    op.drop_table("freight_clue")
    op.drop_index("ix_freight_ai_parse_task_status_code", table_name="freight_ai_parse_task")
    op.drop_index("ix_freight_ai_parse_task_source_channel_code", table_name="freight_ai_parse_task")
    op.drop_index("ix_freight_ai_parse_task_source_inbound_id", table_name="freight_ai_parse_task")
    op.drop_table("freight_ai_parse_task")
    op.drop_index("ix_freight_source_inbound_parse_task_id", table_name="freight_source_inbound")
    op.drop_index("ix_freight_source_inbound_status_code", table_name="freight_source_inbound")
    op.drop_index("ix_freight_source_inbound_external_ref_no", table_name="freight_source_inbound")
    op.drop_index("ix_freight_source_inbound_source_channel_code", table_name="freight_source_inbound")
    op.drop_table("freight_source_inbound")

    with op.batch_alter_table("freight", schema=None) as batch_op:
        batch_op.add_column(sa.Column("source_batch_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("source_tms_inbound_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("source_clue_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("hall_status_code", sa.String(length=64), nullable=False, server_default="NOT_LISTED"))
        batch_op.add_column(sa.Column("hall_published_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("hall_unpublished_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("hall_visible_until", sa.DateTime(), nullable=True))
        batch_op.create_index("ix_freight_source_batch_id", ["source_batch_id"], unique=False)
        batch_op.create_index("ix_freight_source_tms_inbound_id", ["source_tms_inbound_id"], unique=False)
        batch_op.create_index("ix_freight_source_clue_id", ["source_clue_id"], unique=False)

    op.create_table(
        "freight_batch_task",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("batch_no", sa.String(length=32), nullable=False),
        sa.Column("source_type_code", sa.String(length=64), nullable=False),
        sa.Column("source_channel_code", sa.String(length=64), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("status_code", sa.String(length=64), nullable=False),
        sa.Column("clue_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("creator_id", sa.BigInteger(), nullable=True),
        sa.Column("remark", sa.String(length=512), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("raw_response_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_no"),
    )
    op.create_index("ix_freight_batch_task_source_channel_code", "freight_batch_task", ["source_channel_code"])
    op.create_index("ix_freight_batch_task_status_code", "freight_batch_task", ["status_code"])
    op.create_index("ix_freight_batch_task_creator_id", "freight_batch_task", ["creator_id"])

    op.create_table(
        "freight_tms_inbound",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inbound_no", sa.String(length=32), nullable=False),
        sa.Column("source_type_code", sa.String(length=64), nullable=False),
        sa.Column("source_channel_code", sa.String(length=64), nullable=False),
        sa.Column("source_trace_id", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("external_ref_no", sa.String(length=128), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column("status_code", sa.String(length=64), nullable=False),
        sa.Column("clue_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("raw_response_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("inbound_no"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_freight_tms_inbound_source_channel_code", "freight_tms_inbound", ["source_channel_code"])
    op.create_index("ix_freight_tms_inbound_source_trace_id", "freight_tms_inbound", ["source_trace_id"])
    op.create_index("ix_freight_tms_inbound_external_ref_no", "freight_tms_inbound", ["external_ref_no"])
    op.create_index("ix_freight_tms_inbound_status_code", "freight_tms_inbound", ["status_code"])

    op.create_table(
        "freight_clue",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("clue_no", sa.String(length=32), nullable=False),
        sa.Column("source_type_code", sa.String(length=64), nullable=False),
        sa.Column("source_channel_code", sa.String(length=64), nullable=False),
        sa.Column("source_batch_id", sa.BigInteger(), nullable=True),
        sa.Column("source_tms_inbound_id", sa.BigInteger(), nullable=True),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("context_summary", sa.String(length=1024), nullable=True),
        sa.Column("extracted_fields_json", sa.JSON(), nullable=True),
        sa.Column("quality_score", sa.Numeric(8, 4), nullable=True),
        sa.Column("status_code", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_batch_id"], ["freight_batch_task.id"]),
        sa.ForeignKeyConstraint(["source_tms_inbound_id"], ["freight_tms_inbound.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("clue_no"),
    )
    for column in ("source_type_code", "source_channel_code", "source_batch_id", "source_tms_inbound_id", "status_code"):
        op.create_index(f"ix_freight_clue_{column}", "freight_clue", [column])

    op.create_table(
        "freight_candidate",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("candidate_no", sa.String(length=32), nullable=False),
        sa.Column("source_type_code", sa.String(length=64), nullable=False),
        sa.Column("source_channel_code", sa.String(length=64), nullable=False),
        sa.Column("source_batch_id", sa.BigInteger(), nullable=True),
        sa.Column("source_tms_inbound_id", sa.BigInteger(), nullable=True),
        sa.Column("clue_id", sa.BigInteger(), nullable=True),
        sa.Column("source_ref_no", sa.String(length=128), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("raw_commodity_name", sa.String(length=128), nullable=True),
        sa.Column("raw_origin_text", sa.String(length=256), nullable=True),
        sa.Column("raw_destination_text", sa.String(length=256), nullable=True),
        sa.Column("cargo_title", sa.String(length=256), nullable=False),
        sa.Column("cargo_description", sa.String(length=1024), nullable=True),
        sa.Column("commodity_standard_id", sa.BigInteger(), nullable=True),
        sa.Column("commodity_match_name", sa.String(length=128), nullable=True),
        sa.Column("commodity_match_score", sa.Numeric(8, 4), nullable=True),
        sa.Column("commodity_match_level_code", sa.String(length=64), nullable=True),
        sa.Column("commodity_options_json", sa.JSON(), nullable=True),
        sa.Column("packaging_form_code", sa.String(length=64), nullable=True),
        sa.Column("estimated_tonnage", sa.Numeric(18, 2), nullable=True),
        sa.Column("min_tonnage", sa.Numeric(18, 2), nullable=True),
        sa.Column("max_tonnage", sa.Numeric(18, 2), nullable=True),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("total_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("price_unit", sa.String(length=32), nullable=True),
        sa.Column("settlement_method_code", sa.String(length=64), nullable=True),
        sa.Column("origin_node_id", sa.BigInteger(), nullable=True),
        sa.Column("destination_node_id", sa.BigInteger(), nullable=True),
        sa.Column("origin_node_match_score", sa.Numeric(8, 4), nullable=True),
        sa.Column("destination_node_match_score", sa.Numeric(8, 4), nullable=True),
        sa.Column("origin_match_level_code", sa.String(length=64), nullable=True),
        sa.Column("destination_match_level_code", sa.String(length=64), nullable=True),
        sa.Column("origin_options_json", sa.JSON(), nullable=True),
        sa.Column("destination_options_json", sa.JSON(), nullable=True),
        sa.Column("origin_province_code", sa.String(length=12), nullable=True),
        sa.Column("origin_city_code", sa.String(length=12), nullable=True),
        sa.Column("origin_district_code", sa.String(length=12), nullable=True),
        sa.Column("destination_province_code", sa.String(length=12), nullable=True),
        sa.Column("destination_city_code", sa.String(length=12), nullable=True),
        sa.Column("destination_district_code", sa.String(length=12), nullable=True),
        sa.Column("origin_region_id_cache", sa.BigInteger(), nullable=True),
        sa.Column("destination_region_id_cache", sa.BigInteger(), nullable=True),
        sa.Column("loading_time_from", sa.DateTime(), nullable=True),
        sa.Column("loading_time_to", sa.DateTime(), nullable=True),
        sa.Column("unloading_time_from", sa.DateTime(), nullable=True),
        sa.Column("unloading_time_to", sa.DateTime(), nullable=True),
        sa.Column("publisher_org_name", sa.String(length=128), nullable=True),
        sa.Column("contact_name", sa.String(length=64), nullable=True),
        sa.Column("contact_phone", sa.String(length=32), nullable=True),
        sa.Column("contact_wechat", sa.String(length=64), nullable=True),
        sa.Column("confidence_score", sa.Numeric(8, 4), nullable=True),
        sa.Column("completeness_score", sa.Numeric(8, 4), nullable=True),
        sa.Column("match_basis_json", sa.JSON(), nullable=True),
        sa.Column("ai_suggestion_json", sa.JSON(), nullable=True),
        sa.Column("manual_overrides_json", sa.JSON(), nullable=True),
        sa.Column("status_code", sa.String(length=64), nullable=False),
        sa.Column("confirmed_freight_id", sa.BigInteger(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_batch_id"], ["freight_batch_task.id"]),
        sa.ForeignKeyConstraint(["source_tms_inbound_id"], ["freight_tms_inbound.id"]),
        sa.ForeignKeyConstraint(["clue_id"], ["freight_clue.id"]),
        sa.ForeignKeyConstraint(["commodity_standard_id"], ["commodity_standard.id"]),
        sa.ForeignKeyConstraint(["origin_node_id"], ["transport_node.id"]),
        sa.ForeignKeyConstraint(["destination_node_id"], ["transport_node.id"]),
        sa.ForeignKeyConstraint(["origin_region_id_cache"], ["region.id"]),
        sa.ForeignKeyConstraint(["destination_region_id_cache"], ["region.id"]),
        sa.ForeignKeyConstraint(["confirmed_freight_id"], ["freight.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_no"),
    )
    for column in (
        "source_type_code",
        "source_channel_code",
        "source_batch_id",
        "source_tms_inbound_id",
        "clue_id",
        "source_ref_no",
        "commodity_standard_id",
        "origin_node_id",
        "destination_node_id",
        "origin_region_id_cache",
        "destination_region_id_cache",
        "status_code",
        "confirmed_freight_id",
    ):
        op.create_index(f"ix_freight_candidate_{column}", "freight_candidate", [column])

    op.create_table(
        "freight_candidate_manual_feedback",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("candidate_id", sa.BigInteger(), nullable=False),
        sa.Column("action_code", sa.String(length=64), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("feedback_remark", sa.String(length=512), nullable=True),
        sa.Column("operator_id", sa.BigInteger(), nullable=True),
        sa.Column("operated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["freight_candidate.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_freight_candidate_manual_feedback_candidate_id", "freight_candidate_manual_feedback", ["candidate_id"])
    op.create_index("ix_freight_candidate_manual_feedback_action_code", "freight_candidate_manual_feedback", ["action_code"])

    op.create_table(
        "fact_freight_node_daily",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("node_id", sa.BigInteger(), nullable=False),
        sa.Column("node_name", sa.String(length=128), nullable=True),
        sa.Column("city_code", sa.String(length=12), nullable=True),
        sa.Column("primary_region_id", sa.BigInteger(), nullable=True),
        sa.Column("freight_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inbound_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outbound_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tonnage", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("avg_unit_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("heat_value", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("data_version", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["node_id"], ["transport_node.id"]),
        sa.ForeignKeyConstraint(["primary_region_id"], ["region.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fact_freight_node_daily_stat_date", "fact_freight_node_daily", ["stat_date"])
    op.create_index("ix_fact_freight_node_daily_node_id", "fact_freight_node_daily", ["node_id"])
    op.create_index("ix_fact_freight_node_daily_city_code", "fact_freight_node_daily", ["city_code"])
    op.create_index("ix_fact_freight_node_daily_primary_region_id", "fact_freight_node_daily", ["primary_region_id"])


def downgrade() -> None:
    op.drop_index("ix_fact_freight_node_daily_primary_region_id", table_name="fact_freight_node_daily")
    op.drop_index("ix_fact_freight_node_daily_city_code", table_name="fact_freight_node_daily")
    op.drop_index("ix_fact_freight_node_daily_node_id", table_name="fact_freight_node_daily")
    op.drop_index("ix_fact_freight_node_daily_stat_date", table_name="fact_freight_node_daily")
    op.drop_table("fact_freight_node_daily")
    op.drop_index("ix_freight_candidate_manual_feedback_action_code", table_name="freight_candidate_manual_feedback")
    op.drop_index("ix_freight_candidate_manual_feedback_candidate_id", table_name="freight_candidate_manual_feedback")
    op.drop_table("freight_candidate_manual_feedback")
    for column in (
        "confirmed_freight_id",
        "status_code",
        "destination_region_id_cache",
        "origin_region_id_cache",
        "destination_node_id",
        "origin_node_id",
        "commodity_standard_id",
        "source_ref_no",
        "clue_id",
        "source_tms_inbound_id",
        "source_batch_id",
        "source_channel_code",
        "source_type_code",
    ):
        op.drop_index(f"ix_freight_candidate_{column}", table_name="freight_candidate")
    op.drop_table("freight_candidate")
    for column in ("status_code", "source_tms_inbound_id", "source_batch_id", "source_channel_code", "source_type_code"):
        op.drop_index(f"ix_freight_clue_{column}", table_name="freight_clue")
    op.drop_table("freight_clue")
    op.drop_index("ix_freight_tms_inbound_status_code", table_name="freight_tms_inbound")
    op.drop_index("ix_freight_tms_inbound_external_ref_no", table_name="freight_tms_inbound")
    op.drop_index("ix_freight_tms_inbound_source_trace_id", table_name="freight_tms_inbound")
    op.drop_index("ix_freight_tms_inbound_source_channel_code", table_name="freight_tms_inbound")
    op.drop_table("freight_tms_inbound")
    op.drop_index("ix_freight_batch_task_creator_id", table_name="freight_batch_task")
    op.drop_index("ix_freight_batch_task_status_code", table_name="freight_batch_task")
    op.drop_index("ix_freight_batch_task_source_channel_code", table_name="freight_batch_task")
    op.drop_table("freight_batch_task")
    with op.batch_alter_table("freight", schema=None) as batch_op:
        batch_op.drop_index("ix_freight_source_clue_id")
        batch_op.drop_index("ix_freight_source_tms_inbound_id")
        batch_op.drop_index("ix_freight_source_batch_id")
        batch_op.drop_column("hall_visible_until")
        batch_op.drop_column("hall_unpublished_at")
        batch_op.drop_column("hall_published_at")
        batch_op.drop_column("hall_status_code")
        batch_op.drop_column("source_clue_id")
        batch_op.drop_column("source_tms_inbound_id")
        batch_op.drop_column("source_batch_id")
