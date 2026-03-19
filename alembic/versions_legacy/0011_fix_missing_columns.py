"""fix missing columns: cargo_ai_parse_result admin fields + vessel_dynamic mmsi

Revision ID: 0011
Revises: 0010
Create Date: 2026-03-18

变更内容：
  1. cargo_ai_parse_result 表新增 6 个行政区划字段
     （ORM 模型已定义，但之前未生成对应 migration）
  2. vessel_dynamic 表新增 mmsi 字段
     （ORM 模型已定义，但之前未生成对应 migration）
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cargo_ai_parse_result: 补齐行政区划字段 ────────────────────────────
    with op.batch_alter_table("cargo_ai_parse_result") as batch_op:
        batch_op.add_column(sa.Column("origin_admin_code", sa.String(12), nullable=True,
                                      comment="起点城市行政区划代码"))
        batch_op.add_column(sa.Column("origin_admin_name", sa.String(50), nullable=True,
                                      comment="起点城市名称（冗余）"))
        batch_op.add_column(sa.Column("origin_location_type", sa.String(20), nullable=True,
                                      server_default="UNKNOWN",
                                      comment="起点定位精度：NODE/CITY/UNKNOWN"))
        batch_op.add_column(sa.Column("dest_admin_code", sa.String(12), nullable=True,
                                      comment="终点城市行政区划代码"))
        batch_op.add_column(sa.Column("dest_admin_name", sa.String(50), nullable=True,
                                      comment="终点城市名称（冗余）"))
        batch_op.add_column(sa.Column("dest_location_type", sa.String(20), nullable=True,
                                      server_default="UNKNOWN",
                                      comment="终点定位精度：NODE/CITY/UNKNOWN"))

    # ── vessel_dynamic: 补齐 mmsi 字段 ────────────────────────────────────
    with op.batch_alter_table("vessel_dynamic") as batch_op:
        batch_op.add_column(sa.Column("mmsi", sa.String(20), nullable=True,
                                      comment="MMSI号（动态更新的唯一键）"))


def downgrade() -> None:
    with op.batch_alter_table("vessel_dynamic") as batch_op:
        batch_op.drop_column("mmsi")

    with op.batch_alter_table("cargo_ai_parse_result") as batch_op:
        batch_op.drop_column("dest_location_type")
        batch_op.drop_column("dest_admin_name")
        batch_op.drop_column("dest_admin_code")
        batch_op.drop_column("origin_location_type")
        batch_op.drop_column("origin_admin_name")
        batch_op.drop_column("origin_admin_code")
