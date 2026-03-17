"""refactor route path to three-tier graph structure

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-17

重构航线路径为三层结构：
  shipping_route       — 航线（移除手动 code，改为自动生成）
  shipping_route_path  — 路线方案（重建：增加 code/name/description/status/sort_order，
                          移除 node_id/sequence/distance_from_start/node_role）
  shipping_route_path_node — 新增路线节点表
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 重建 shipping_route_path（直接 drop + create，开发阶段无历史数据需保留）
    op.drop_table("shipping_route_path")

    op.create_table(
        "shipping_route_path",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("route_id", sa.BigInteger(), sa.ForeignKey("shipping_route.id"), nullable=False,
                  comment="所属航线ID"),
        sa.Column("code", sa.String(32), unique=True, nullable=False,
                  comment="路线编码，自动生成 RP-XXXXXXXXXXXX"),
        sa.Column("name", sa.String(128), nullable=False,
                  comment="路线名称，如主航道/运河绕行线"),
        sa.Column("description", sa.String(512), nullable=True, comment="路线描述"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0",
                  comment="排序，数字越小越靠前"),
        sa.Column("status", sa.SmallInteger(), nullable=False, server_default="1",
                  comment="1=启用,0=停用"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    # 2. 新建 shipping_route_path_node
    op.create_table(
        "shipping_route_path_node",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("path_id", sa.BigInteger(), sa.ForeignKey("shipping_route_path.id"),
                  nullable=False, comment="所属路线ID"),
        sa.Column("node_id", sa.BigInteger(), sa.ForeignKey("transport_node.id"),
                  nullable=False, comment="途经节点ID"),
        sa.Column("sequence", sa.Integer(), nullable=False, comment="顺序（从1开始）"),
        sa.Column("distance_from_start", sa.DECIMAL(10, 2), nullable=True,
                  comment="距路线起点距离(km)"),
        sa.Column("node_role", sa.String(32), nullable=True, server_default="WAYPOINT",
                  comment="START/WAYPOINT/END"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade() -> None:
    op.drop_table("shipping_route_path_node")
    op.drop_table("shipping_route_path")

    # 恢复旧结构
    op.create_table(
        "shipping_route_path",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("route_id", sa.BigInteger(), sa.ForeignKey("shipping_route.id"), nullable=False),
        sa.Column("node_id", sa.BigInteger(), sa.ForeignKey("transport_node.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False, comment="序号（从1开始）"),
        sa.Column("distance_from_start", sa.DECIMAL(10, 2), nullable=True,
                  comment="距起点距离(km)"),
        sa.Column("node_role", sa.String(32), nullable=True, server_default="WAYPOINT",
                  comment="START/WAYPOINT/END"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
