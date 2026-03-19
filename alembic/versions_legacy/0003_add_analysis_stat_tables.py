"""add analysis stat tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-16

新增8张统计分析表，支持航运数据分析模块：
  cargo_heatmap_daily        — 货源热力统计日表
  ship_heatmap_daily         — 船舶热力统计日表
  cargo_stat_daily           — 货源每日汇总统计
  cargo_commodity_stat_daily — 货品分类货源统计
  cargo_region_stat_daily    — 区域货源分布统计
  ship_capacity_region_daily — 区域运力分布统计
  ship_type_stat_daily       — 船舶类型统计
  ship_age_stat_daily        — 船龄分布统计

注意：UniqueConstraint 和 Index 均内联在 create_table 中（SQLite 兼容）
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cargo_heatmap_daily ───────────────────────────────────────────────
    op.create_table(
        "cargo_heatmap_daily",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stat_date", sa.Date(), nullable=False, comment="统计日期"),
        sa.Column("node_id", sa.BigInteger(), nullable=False, comment="运输节点ID"),
        sa.Column("stat_type", sa.String(16), nullable=False,
                  comment="ORIGIN=装货节点, DEST=卸货节点"),
        sa.Column("cargo_count", sa.Integer(), nullable=False,
                  server_default="0", comment="货源数量"),
        sa.Column("total_tonnage", sa.DECIMAL(16, 2), nullable=False,
                  server_default="0", comment="总吨位(吨)"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["node_id"], ["transport_node.id"]),
        sa.UniqueConstraint("stat_date", "node_id", "stat_type",
                            name="uk_cargo_heatmap_daily"),
    )
    op.create_index("ix_cargo_heatmap_date", "cargo_heatmap_daily", ["stat_date"])
    op.create_index("ix_cargo_heatmap_node", "cargo_heatmap_daily", ["node_id"])

    # ── ship_heatmap_daily ────────────────────────────────────────────────
    op.create_table(
        "ship_heatmap_daily",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stat_date", sa.Date(), nullable=False, comment="统计日期"),
        sa.Column("node_id", sa.BigInteger(), nullable=False, comment="运输节点ID"),
        sa.Column("vessel_count", sa.Integer(), nullable=False,
                  server_default="0", comment="在港/在途船舶数量"),
        sa.Column("total_deadweight", sa.DECIMAL(16, 2), nullable=False,
                  server_default="0", comment="总载重吨(DWT)"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["node_id"], ["transport_node.id"]),
        sa.UniqueConstraint("stat_date", "node_id", name="uk_ship_heatmap_daily"),
    )
    op.create_index("ix_ship_heatmap_date", "ship_heatmap_daily", ["stat_date"])
    op.create_index("ix_ship_heatmap_node", "ship_heatmap_daily", ["node_id"])

    # ── cargo_stat_daily ──────────────────────────────────────────────────
    op.create_table(
        "cargo_stat_daily",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stat_date", sa.Date(), nullable=False, unique=True,
                  comment="统计日期"),
        sa.Column("total_count", sa.Integer(), nullable=False,
                  server_default="0", comment="当日新增货源总量"),
        sa.Column("active_count", sa.Integer(), nullable=False,
                  server_default="0", comment="CONFIRMED状态货源数量"),
        sa.Column("pending_count", sa.Integer(), nullable=False,
                  server_default="0", comment="PENDING状态货源数量"),
        sa.Column("total_tonnage", sa.DECIMAL(18, 2), nullable=False,
                  server_default="0", comment="当日新增总吨位(吨)"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_cargo_stat_date", "cargo_stat_daily", ["stat_date"])

    # ── cargo_commodity_stat_daily ────────────────────────────────────────
    op.create_table(
        "cargo_commodity_stat_daily",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stat_date", sa.Date(), nullable=False, comment="统计日期"),
        sa.Column("commodity_category_id", sa.BigInteger(), nullable=False,
                  comment="货品大类ID"),
        sa.Column("category_name", sa.String(64), nullable=False,
                  comment="货品大类名称"),
        sa.Column("cargo_count", sa.Integer(), nullable=False,
                  server_default="0", comment="货源数量"),
        sa.Column("total_tonnage", sa.DECIMAL(16, 2), nullable=False,
                  server_default="0", comment="总吨位(吨)"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["commodity_category_id"], ["commodity_category.id"]),
        sa.UniqueConstraint("stat_date", "commodity_category_id",
                            name="uk_cargo_commodity_stat"),
    )
    op.create_index("ix_cargo_commodity_stat_date", "cargo_commodity_stat_daily",
                    ["stat_date"])
    op.create_index("ix_cargo_commodity_stat_cat", "cargo_commodity_stat_daily",
                    ["commodity_category_id"])

    # ── cargo_region_stat_daily ───────────────────────────────────────────
    op.create_table(
        "cargo_region_stat_daily",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stat_date", sa.Date(), nullable=False, comment="统计日期"),
        sa.Column("region_id", sa.BigInteger(), nullable=False, comment="区域ID"),
        sa.Column("region_name", sa.String(64), nullable=False, comment="区域名称"),
        sa.Column("stat_type", sa.String(8), nullable=False,
                  comment="ORIGIN=货源发出, DEST=货源到达"),
        sa.Column("cargo_count", sa.Integer(), nullable=False,
                  server_default="0", comment="货源数量"),
        sa.Column("total_tonnage", sa.DECIMAL(16, 2), nullable=False,
                  server_default="0", comment="总吨位(吨)"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["region_id"], ["region.id"]),
        sa.UniqueConstraint("stat_date", "region_id", "stat_type",
                            name="uk_cargo_region_stat"),
    )
    op.create_index("ix_cargo_region_stat_date", "cargo_region_stat_daily", ["stat_date"])
    op.create_index("ix_cargo_region_stat_region", "cargo_region_stat_daily", ["region_id"])

    # ── ship_capacity_region_daily ────────────────────────────────────────
    op.create_table(
        "ship_capacity_region_daily",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stat_date", sa.Date(), nullable=False, comment="统计日期"),
        sa.Column("region_id", sa.BigInteger(), nullable=False, comment="区域ID"),
        sa.Column("region_name", sa.String(64), nullable=False, comment="区域名称"),
        sa.Column("vessel_count", sa.Integer(), nullable=False,
                  server_default="0", comment="船舶数量"),
        sa.Column("total_deadweight", sa.DECIMAL(16, 2), nullable=False,
                  server_default="0", comment="总载重吨(DWT)"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["region_id"], ["region.id"]),
        sa.UniqueConstraint("stat_date", "region_id", name="uk_ship_capacity_region"),
    )
    op.create_index("ix_ship_capacity_region_date", "ship_capacity_region_daily",
                    ["stat_date"])
    op.create_index("ix_ship_capacity_region_id", "ship_capacity_region_daily",
                    ["region_id"])

    # ── ship_type_stat_daily ──────────────────────────────────────────────
    op.create_table(
        "ship_type_stat_daily",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stat_date", sa.Date(), nullable=False, comment="统计日期"),
        sa.Column("vessel_type_id", sa.BigInteger(), nullable=False,
                  comment="船舶类型ID"),
        sa.Column("type_name", sa.String(64), nullable=False, comment="船舶类型名称"),
        sa.Column("vessel_count", sa.Integer(), nullable=False,
                  server_default="0", comment="船舶数量"),
        sa.Column("total_deadweight", sa.DECIMAL(16, 2), nullable=False,
                  server_default="0", comment="总载重吨(DWT)"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["vessel_type_id"], ["vessel_type_dict.id"]),
        sa.UniqueConstraint("stat_date", "vessel_type_id", name="uk_ship_type_stat"),
    )
    op.create_index("ix_ship_type_stat_date", "ship_type_stat_daily", ["stat_date"])

    # ── ship_age_stat_daily ───────────────────────────────────────────────
    op.create_table(
        "ship_age_stat_daily",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stat_date", sa.Date(), nullable=False, comment="统计日期"),
        sa.Column("age_group", sa.String(8), nullable=False,
                  comment="船龄分组：0-5 / 5-10 / 10-15 / 15-20 / 20+"),
        sa.Column("vessel_count", sa.Integer(), nullable=False,
                  server_default="0", comment="该船龄段船舶数量"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("stat_date", "age_group", name="uk_ship_age_stat"),
    )
    op.create_index("ix_ship_age_stat_date", "ship_age_stat_daily", ["stat_date"])


def downgrade() -> None:
    op.drop_table("ship_age_stat_daily")
    op.drop_table("ship_type_stat_daily")
    op.drop_table("ship_capacity_region_daily")
    op.drop_table("cargo_region_stat_daily")
    op.drop_table("cargo_commodity_stat_daily")
    op.drop_table("cargo_stat_daily")
    op.drop_table("ship_heatmap_daily")
    op.drop_table("cargo_heatmap_daily")
