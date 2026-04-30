"""freight_candidate_chain

Revision ID: 0003_freight_candidate_chain
Revises: 0002_ship_profile_business_fields
Create Date: 2026-04-30 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003_freight_candidate_chain"
down_revision: Union[str, None] = "0002_ship_profile_business_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "freight_source_inbound",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("inbound_no", sa.String(length=32), nullable=False),
        sa.Column("source_type_code", sa.String(length=64), nullable=False),
        sa.Column("source_channel_code", sa.String(length=64), nullable=False),
        sa.Column("external_ref_no", sa.String(length=128), nullable=True),
        sa.Column("sender_name", sa.String(length=128), nullable=True),
        sa.Column("sender_contact", sa.String(length=64), nullable=True),
        sa.Column("raw_title", sa.String(length=256), nullable=True),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.Column("status_code", sa.String(length=64), nullable=False),
        sa.Column("parse_task_id", sa.BigInteger(), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("inbound_no"),
    )
    op.create_index("ix_freight_source_inbound_source_channel_code", "freight_source_inbound", ["source_channel_code"])
    op.create_index("ix_freight_source_inbound_external_ref_no", "freight_source_inbound", ["external_ref_no"])
    op.create_index("ix_freight_source_inbound_status_code", "freight_source_inbound", ["status_code"])
    op.create_index("ix_freight_source_inbound_parse_task_id", "freight_source_inbound", ["parse_task_id"])

    op.create_table(
        "freight_ai_parse_task",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_no", sa.String(length=32), nullable=False),
        sa.Column("source_inbound_id", sa.BigInteger(), nullable=True),
        sa.Column("source_type_code", sa.String(length=64), nullable=False),
        sa.Column("source_channel_code", sa.String(length=64), nullable=False),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column("status_code", sa.String(length=64), nullable=False),
        sa.Column("ai_provider_code", sa.String(length=64), nullable=True),
        sa.Column("ai_model", sa.String(length=128), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("requested_by", sa.BigInteger(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("raw_response_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["source_inbound_id"], ["freight_source_inbound.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_no"),
    )
    op.create_index("ix_freight_ai_parse_task_source_inbound_id", "freight_ai_parse_task", ["source_inbound_id"])
    op.create_index("ix_freight_ai_parse_task_source_channel_code", "freight_ai_parse_task", ["source_channel_code"])
    op.create_index("ix_freight_ai_parse_task_status_code", "freight_ai_parse_task", ["status_code"])

    op.create_table(
        "freight_clue",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("clue_no", sa.String(length=32), nullable=False),
        sa.Column("parse_task_id", sa.BigInteger(), nullable=False),
        sa.Column("source_inbound_id", sa.BigInteger(), nullable=True),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("status_code", sa.String(length=64), nullable=False),
        sa.Column("parse_result_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["parse_task_id"], ["freight_ai_parse_task.id"]),
        sa.ForeignKeyConstraint(["source_inbound_id"], ["freight_source_inbound.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("clue_no"),
    )
    op.create_index("ix_freight_clue_parse_task_id", "freight_clue", ["parse_task_id"])
    op.create_index("ix_freight_clue_source_inbound_id", "freight_clue", ["source_inbound_id"])
    op.create_index("ix_freight_clue_status_code", "freight_clue", ["status_code"])

    op.create_table(
        "freight_candidate",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("candidate_no", sa.String(length=32), nullable=False),
        sa.Column("parse_task_id", sa.BigInteger(), nullable=False),
        sa.Column("clue_id", sa.BigInteger(), nullable=True),
        sa.Column("source_inbound_id", sa.BigInteger(), nullable=True),
        sa.Column("cargo_title", sa.String(length=256), nullable=False),
        sa.Column("cargo_description", sa.String(length=1024), nullable=True),
        sa.Column("commodity_standard_id", sa.BigInteger(), nullable=True),
        sa.Column("commodity_match_name", sa.String(length=128), nullable=True),
        sa.Column("commodity_match_score", sa.Numeric(8, 4), nullable=True),
        sa.Column("packaging_form_code", sa.String(length=64), nullable=True),
        sa.Column("estimated_tonnage", sa.Numeric(18, 2), nullable=True),
        sa.Column("min_tonnage", sa.Numeric(18, 2), nullable=True),
        sa.Column("max_tonnage", sa.Numeric(18, 2), nullable=True),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("total_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("price_unit", sa.String(length=32), nullable=True),
        sa.Column("settlement_method_code", sa.String(length=64), nullable=True),
        sa.Column("origin_text", sa.String(length=256), nullable=True),
        sa.Column("destination_text", sa.String(length=256), nullable=True),
        sa.Column("origin_node_id", sa.BigInteger(), nullable=True),
        sa.Column("destination_node_id", sa.BigInteger(), nullable=True),
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
        sa.Column("match_basis_json", sa.JSON(), nullable=True),
        sa.Column("status_code", sa.String(length=64), nullable=False),
        sa.Column("confirmed_freight_id", sa.BigInteger(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["parse_task_id"], ["freight_ai_parse_task.id"]),
        sa.ForeignKeyConstraint(["clue_id"], ["freight_clue.id"]),
        sa.ForeignKeyConstraint(["source_inbound_id"], ["freight_source_inbound.id"]),
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
        "parse_task_id",
        "clue_id",
        "source_inbound_id",
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
        "freight_candidate_feedback",
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
    op.create_index("ix_freight_candidate_feedback_candidate_id", "freight_candidate_feedback", ["candidate_id"])
    op.create_index("ix_freight_candidate_feedback_action_code", "freight_candidate_feedback", ["action_code"])

    with op.batch_alter_table("freight", schema=None) as batch_op:
        batch_op.add_column(sa.Column("source_channel_code", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("source_ref_no", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("source_candidate_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("confirmed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("confirmed_by", sa.BigInteger(), nullable=True))
        batch_op.create_index("ix_freight_source_channel_code", ["source_channel_code"], unique=False)
        batch_op.create_index("ix_freight_source_ref_no", ["source_ref_no"], unique=False)
        batch_op.create_index("ix_freight_source_candidate_id", ["source_candidate_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("freight", schema=None) as batch_op:
        batch_op.drop_index("ix_freight_source_candidate_id")
        batch_op.drop_index("ix_freight_source_ref_no")
        batch_op.drop_index("ix_freight_source_channel_code")
        batch_op.drop_column("confirmed_by")
        batch_op.drop_column("confirmed_at")
        batch_op.drop_column("source_candidate_id")
        batch_op.drop_column("source_ref_no")
        batch_op.drop_column("source_channel_code")

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
