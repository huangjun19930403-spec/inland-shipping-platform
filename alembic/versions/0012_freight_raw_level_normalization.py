"""freight_raw_level_normalization

Revision ID: 0012_freight_raw_level_normalization
Revises: 0011_freight_ai_progress
Create Date: 2026-05-07 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012_freight_raw_level_normalization"
down_revision: Union[str, None] = "0011_freight_ai_progress"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("freight", schema=None) as batch_op:
        batch_op.add_column(sa.Column("raw_commodity_name", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("raw_origin_text", sa.String(length=256), nullable=True))
        batch_op.add_column(sa.Column("raw_destination_text", sa.String(length=256), nullable=True))
        batch_op.add_column(sa.Column("commodity_match_level_code", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("origin_match_level_code", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("destination_match_level_code", sa.String(length=64), nullable=True))
        batch_op.alter_column("commodity_standard_id", existing_type=sa.BigInteger(), nullable=True)
        batch_op.alter_column("origin_province_code", existing_type=sa.String(length=12), nullable=True)
        batch_op.alter_column("origin_city_code", existing_type=sa.String(length=12), nullable=True)
        batch_op.alter_column("destination_province_code", existing_type=sa.String(length=12), nullable=True)
        batch_op.alter_column("destination_city_code", existing_type=sa.String(length=12), nullable=True)
        batch_op.create_index("ix_freight_commodity_match_level_code", ["commodity_match_level_code"], unique=False)
        batch_op.create_index("ix_freight_origin_match_level_code", ["origin_match_level_code"], unique=False)
        batch_op.create_index("ix_freight_destination_match_level_code", ["destination_match_level_code"], unique=False)

    op.create_table(
        "freight_normalization_suggestion",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("freight_id", sa.BigInteger(), nullable=False),
        sa.Column("suggestion_type_code", sa.String(length=64), nullable=False),
        sa.Column("raw_text", sa.String(length=256), nullable=True),
        sa.Column("current_level_code", sa.String(length=64), nullable=True),
        sa.Column("suggested_level_code", sa.String(length=64), nullable=False),
        sa.Column("suggested_node_id", sa.BigInteger(), nullable=True),
        sa.Column("suggested_commodity_standard_id", sa.BigInteger(), nullable=True),
        sa.Column("suggested_province_code", sa.String(length=12), nullable=True),
        sa.Column("suggested_city_code", sa.String(length=12), nullable=True),
        sa.Column("suggested_district_code", sa.String(length=12), nullable=True),
        sa.Column("suggested_region_id", sa.BigInteger(), nullable=True),
        sa.Column("confidence_score", sa.Numeric(8, 4), nullable=True),
        sa.Column("status_code", sa.String(length=64), nullable=False),
        sa.Column("auto_apply_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("match_basis_json", sa.JSON(), nullable=True),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.Column("applied_by", sa.BigInteger(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["freight_id"], ["freight.id"]),
        sa.ForeignKeyConstraint(["suggested_node_id"], ["transport_node.id"]),
        sa.ForeignKeyConstraint(["suggested_commodity_standard_id"], ["commodity_standard.id"]),
        sa.ForeignKeyConstraint(["suggested_region_id"], ["region.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "freight_id",
        "suggestion_type_code",
        "suggested_level_code",
        "suggested_node_id",
        "suggested_commodity_standard_id",
        "suggested_city_code",
        "suggested_region_id",
        "status_code",
    ):
        op.create_index(f"ix_freight_normalization_suggestion_{column}", "freight_normalization_suggestion", [column])


def downgrade() -> None:
    op.drop_table("freight_normalization_suggestion")
    with op.batch_alter_table("freight", schema=None) as batch_op:
        batch_op.drop_index("ix_freight_destination_match_level_code")
        batch_op.drop_index("ix_freight_origin_match_level_code")
        batch_op.drop_index("ix_freight_commodity_match_level_code")
        batch_op.alter_column("destination_city_code", existing_type=sa.String(length=12), nullable=False)
        batch_op.alter_column("destination_province_code", existing_type=sa.String(length=12), nullable=False)
        batch_op.alter_column("origin_city_code", existing_type=sa.String(length=12), nullable=False)
        batch_op.alter_column("origin_province_code", existing_type=sa.String(length=12), nullable=False)
        batch_op.alter_column("commodity_standard_id", existing_type=sa.BigInteger(), nullable=False)
        batch_op.drop_column("destination_match_level_code")
        batch_op.drop_column("origin_match_level_code")
        batch_op.drop_column("commodity_match_level_code")
        batch_op.drop_column("raw_destination_text")
        batch_op.drop_column("raw_origin_text")
        batch_op.drop_column("raw_commodity_name")
