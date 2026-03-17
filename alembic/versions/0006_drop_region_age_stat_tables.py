"""drop cargo_region_stat_daily, ship_capacity_region_daily, ship_age_stat_daily

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-17

删除 3 张冗余统计表：
  cargo_region_stat_daily    — 区域货源分布（与货源热力图重叠）
  ship_capacity_region_daily — 区域运力分布（与船舶热力图重叠）
  ship_age_stat_daily        — 船龄分布（暂无产品需求）
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("cargo_region_stat_daily")
    op.drop_table("ship_capacity_region_daily")
    op.drop_table("ship_age_stat_daily")


def downgrade() -> None:
    op.create_table(
        "cargo_region_stat_daily",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("region_id", sa.BigInteger(), nullable=False),
        sa.Column("region_name", sa.String(64), nullable=False),
        sa.Column("stat_type", sa.String(8), nullable=False),
        sa.Column("cargo_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tonnage", sa.DECIMAL(16, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["region_id"], ["region.id"]),
        sa.UniqueConstraint("stat_date", "region_id", "stat_type", name="uk_cargo_region_stat"),
    )
    op.create_index("ix_cargo_region_stat_date", "cargo_region_stat_daily", ["stat_date"])
    op.create_index("ix_cargo_region_stat_region", "cargo_region_stat_daily", ["region_id"])

    op.create_table(
        "ship_capacity_region_daily",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("region_id", sa.BigInteger(), nullable=False),
        sa.Column("region_name", sa.String(64), nullable=False),
        sa.Column("vessel_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_deadweight", sa.DECIMAL(16, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["region_id"], ["region.id"]),
        sa.UniqueConstraint("stat_date", "region_id", name="uk_ship_capacity_region"),
    )
    op.create_index("ix_ship_capacity_region_date", "ship_capacity_region_daily", ["stat_date"])
    op.create_index("ix_ship_capacity_region_id", "ship_capacity_region_daily", ["region_id"])

    op.create_table(
        "ship_age_stat_daily",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("age_group", sa.String(8), nullable=False),
        sa.Column("vessel_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("stat_date", "age_group", name="uk_ship_age_stat"),
    )
    op.create_index("ix_ship_age_stat_date", "ship_age_stat_daily", ["stat_date"])
