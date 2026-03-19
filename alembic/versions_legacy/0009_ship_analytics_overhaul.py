"""ship analytics overhaul - drop old daily tables, create snapshot tables

Revision ID: 0009
Revises: 0008
Create Date: 2026-03-18

变更内容：
  1. 删除 ship_heatmap_daily（节点级热力日表，废弃）
  2. 删除 ship_type_stat_daily（船型统计日表，废弃）
  3. 新建 ship_stat_region  — 航运商业区域热力快照
  4. 新建 ship_stat_city    — 城市级热力快照
  5. 新建 ship_stat_dwt     — 载重吨区间分布快照
  6. 新建 ship_stat_age     — 船龄区间分布快照

说明：
  - 新统计表全部采用快照模式（无日期主键），事件驱动刷新
  - 不建跨表 FK 约束，统计表独立存储冗余字段
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 删除旧船舶统计表 ──────────────────────────────────
    op.drop_table("ship_type_stat_daily")
    op.drop_table("ship_heatmap_daily")

    # ── 新建 ship_stat_region（区域热力快照）────────────────
    op.create_table(
        "ship_stat_region",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("region_id", sa.BigInteger(), nullable=False, comment="Region.id（冗余，无FK约束）"),
        sa.Column("region_name", sa.String(64), nullable=False, comment="区域名称（冗余）"),
        sa.Column("center_longitude", sa.DECIMAL(11, 8), nullable=True, comment="区域中心经度"),
        sa.Column("center_latitude", sa.DECIMAL(10, 8), nullable=True, comment="区域中心纬度"),
        sa.Column("boundary_coordinates", sa.JSON(), nullable=True, comment="边界坐标 [[lng,lat],...]，冗余供前端绘图"),
        sa.Column("vessel_count", sa.Integer(), nullable=False, default=0, comment="区域内船舶总数"),
        sa.Column("total_deadweight", sa.DECIMAL(16, 2), nullable=False, default=0, comment="区域内总载重吨(DWT)"),
        sa.Column("ratio", sa.DECIMAL(6, 3), nullable=False, default=0, comment="占全部有位置船舶的百分比"),
        sa.Column("refreshed_at", sa.DateTime(), nullable=True, comment="最近刷新时间"),
    )
    op.create_index("ix_ship_stat_region_id", "ship_stat_region", ["region_id"], unique=True)

    # ── 新建 ship_stat_city（城市级热力快照）────────────────
    op.create_table(
        "ship_stat_city",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("city_code", sa.String(12), nullable=False, comment="admin_region.code（冗余，无FK约束）"),
        sa.Column("city_name", sa.String(64), nullable=False, comment="城市名称（冗余）"),
        sa.Column("province_name", sa.String(64), nullable=True, comment="省份名称（冗余，方便省级聚合）"),
        sa.Column("longitude", sa.DECIMAL(11, 8), nullable=True, comment="城市行政中心经度（来自admin_region）"),
        sa.Column("latitude", sa.DECIMAL(10, 8), nullable=True, comment="城市行政中心纬度（来自admin_region）"),
        sa.Column("vessel_count", sa.Integer(), nullable=False, default=0, comment="该城市范围内船舶数量"),
        sa.Column("total_deadweight", sa.DECIMAL(16, 2), nullable=False, default=0, comment="城市运力：合计载重吨(DWT)"),
        sa.Column("ratio", sa.DECIMAL(6, 3), nullable=False, default=0, comment="占全部有位置船舶的百分比"),
        sa.Column("refreshed_at", sa.DateTime(), nullable=True, comment="最近刷新时间"),
    )
    op.create_index("ix_ship_stat_city_code", "ship_stat_city", ["city_code"], unique=True)

    # ── 新建 ship_stat_dwt（载重吨分布快照）─────────────────
    op.create_table(
        "ship_stat_dwt",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("segment_label", sa.String(32), nullable=False, comment="档位标签，如 '500-1000吨'"),
        sa.Column("min_dwt", sa.Integer(), nullable=True, comment="区间下限（NULL=无下限）"),
        sa.Column("max_dwt", sa.Integer(), nullable=True, comment="区间上限（NULL=无上限）"),
        sa.Column("vessel_count", sa.Integer(), nullable=False, default=0, comment="该区间船舶数量"),
        sa.Column("ratio", sa.DECIMAL(6, 3), nullable=False, default=0, comment="占全部有效船舶的百分比"),
        sa.Column("refreshed_at", sa.DateTime(), nullable=True, comment="最近刷新时间"),
    )
    op.create_index("ix_ship_stat_dwt_label", "ship_stat_dwt", ["segment_label"], unique=True)

    # ── 新建 ship_stat_age（船龄分布快照）───────────────────
    op.create_table(
        "ship_stat_age",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("age_range_label", sa.String(32), nullable=False, comment="船龄档位，如 '6-10年'"),
        sa.Column("min_age", sa.Integer(), nullable=True, comment="区间下限（NULL=无下限）"),
        sa.Column("max_age", sa.Integer(), nullable=True, comment="区间上限（NULL=无上限）"),
        sa.Column("vessel_count", sa.Integer(), nullable=False, default=0, comment="该区间船舶数量"),
        sa.Column("ratio", sa.DECIMAL(6, 3), nullable=False, default=0, comment="占全部有效船舶的百分比"),
        sa.Column("refreshed_at", sa.DateTime(), nullable=True, comment="最近刷新时间"),
    )
    op.create_index("ix_ship_stat_age_label", "ship_stat_age", ["age_range_label"], unique=True)


def downgrade() -> None:
    op.drop_table("ship_stat_age")
    op.drop_table("ship_stat_dwt")
    op.drop_table("ship_stat_city")
    op.drop_table("ship_stat_region")

    # 恢复旧表（最小结构，仅保证 downgrade 不报错）
    op.create_table(
        "ship_heatmap_daily",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("node_id", sa.BigInteger(), nullable=False),
        sa.Column("vessel_count", sa.Integer(), nullable=False, default=0),
        sa.Column("total_deadweight", sa.DECIMAL(16, 2), nullable=False, default=0),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "ship_type_stat_daily",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("vessel_type_id", sa.BigInteger(), nullable=False),
        sa.Column("type_name", sa.String(64), nullable=False),
        sa.Column("vessel_count", sa.Integer(), nullable=False, default=0),
        sa.Column("total_deadweight", sa.DECIMAL(16, 2), nullable=False, default=0),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
