"""drop heatmap_stat_daily

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-17

删除旧混合热力统计表 heatmap_stat_daily。
该表已被 cargo_heatmap_daily 和 ship_heatmap_daily 取代，ETL 不再双写。
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("heatmap_stat_daily")


def downgrade() -> None:
    import sqlalchemy as sa
    op.create_table(
        "heatmap_stat_daily",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stat_date", sa.Date(), nullable=False, comment="统计日期"),
        sa.Column("node_id", sa.BigInteger(), nullable=False, comment="运输节点ID"),
        sa.Column("stat_type", sa.String(32), nullable=False,
                  comment="CARGO_ORIGIN / CARGO_DEST / VESSEL"),
        sa.Column("cargo_count", sa.Integer(), server_default="0", comment="货源数量"),
        sa.Column("total_tonnage", sa.DECIMAL(16, 2), server_default="0", comment="总吨位(吨)"),
        sa.Column("vessel_count", sa.Integer(), server_default="0", comment="船舶数量"),
        sa.Column("total_deadweight", sa.DECIMAL(16, 2), server_default="0", comment="总载重吨(DWT)"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["node_id"], ["transport_node.id"]),
        sa.UniqueConstraint("stat_date", "node_id", "stat_type", name="uk_heatmap_daily"),
    )
