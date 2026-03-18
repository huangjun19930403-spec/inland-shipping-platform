"""add cargo_freight and fix cargo stat tables

Revision ID: 0008
Revises: 0007
Create Date: 2026-03-18

变更内容：
  1. 新建 cargo_freight 表（替换废弃的 cargo_opportunity）
  2. 新建 cargo_city_heatmap 表（替换旧节点级 cargo_heatmap_daily）
  3. 新建 cargo_od_daily 表（起终点城市OD流量矩阵）
  4. 新建 cargo_channel_daily 表（各录入渠道质量统计）
  5. 修复 cargo_stat_daily 表：
     - active_count  → confirmed_count（字段重命名，与 ORM 对齐）
     - 新增 avg_tonnage DECIMAL(12,2) 列

说明：
  - cargo_stat_daily 重命名列使用 Alembic batch_alter_table，
    在 SQLite 下会自动重建表，在 PostgreSQL 下直接 ALTER COLUMN。
  - 所有新表 SQL 使用 SQLite / PostgreSQL 通用写法。
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. cargo_freight ───────────────────────────────────────────────────
    op.create_table(
        "cargo_freight",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("freight_no", sa.String(32), unique=True, nullable=False,
                  comment="货源编号，格式 CS-YYYYMMDD-XXXXXXXX"),
        sa.Column("source_type", sa.String(20), nullable=False, server_default="MANUAL",
                  comment="TMS/WECHAT_AI/MANUAL"),
        sa.Column("status", sa.String(20), nullable=False, server_default="CONFIRMED",
                  comment="PENDING/CONFIRMED/CANCELLED/EXPIRED"),

        # 装货地
        sa.Column("origin_node_id", sa.BigInteger(), nullable=True,
                  comment="装货节点ID，可空"),
        sa.Column("origin_admin_code", sa.String(12), nullable=True,
                  comment="装货城市行政区划代码"),
        sa.Column("origin_admin_name", sa.String(50), nullable=True,
                  comment="装货城市名称（冗余）"),
        sa.Column("origin_region_id", sa.BigInteger(), nullable=True,
                  comment="装货商业区域"),
        sa.Column("origin_longitude", sa.DECIMAL(11, 8), nullable=True,
                  comment="装货地经度"),
        sa.Column("origin_latitude", sa.DECIMAL(10, 8), nullable=True,
                  comment="装货地纬度"),
        sa.Column("origin_raw_text", sa.String(200), nullable=True,
                  comment="装货地原始文本"),
        sa.Column("origin_precision", sa.String(12), nullable=False, server_default="UNKNOWN",
                  comment="NODE/CITY/COORDINATE/UNKNOWN"),

        # 卸货地
        sa.Column("dest_node_id", sa.BigInteger(), nullable=True,
                  comment="卸货节点ID，可空"),
        sa.Column("dest_admin_code", sa.String(12), nullable=True,
                  comment="卸货城市行政区划代码"),
        sa.Column("dest_admin_name", sa.String(50), nullable=True,
                  comment="卸货城市名称（冗余）"),
        sa.Column("dest_region_id", sa.BigInteger(), nullable=True,
                  comment="卸货商业区域"),
        sa.Column("dest_longitude", sa.DECIMAL(11, 8), nullable=True,
                  comment="卸货地经度"),
        sa.Column("dest_latitude", sa.DECIMAL(10, 8), nullable=True,
                  comment="卸货地纬度"),
        sa.Column("dest_raw_text", sa.String(200), nullable=True,
                  comment="卸货地原始文本"),
        sa.Column("dest_precision", sa.String(12), nullable=False, server_default="UNKNOWN",
                  comment="NODE/CITY/COORDINATE/UNKNOWN"),

        # 货物信息
        sa.Column("commodity_id", sa.BigInteger(), nullable=True),
        sa.Column("commodity_text", sa.String(100), nullable=True,
                  comment="原始货品描述"),
        sa.Column("tonnage", sa.DECIMAL(12, 2), nullable=True,
                  comment="货物吨位(吨)"),
        sa.Column("volume", sa.DECIMAL(12, 2), nullable=True,
                  comment="货物方数(m³)"),
        sa.Column("loading_date", sa.Date(), nullable=True,
                  comment="装货日期"),
        sa.Column("expire_date", sa.Date(), nullable=True,
                  comment="货源有效截止日"),

        # 价格与联系方式
        sa.Column("freight_price", sa.DECIMAL(12, 2), nullable=True,
                  comment="运价"),
        sa.Column("price_type", sa.SmallInteger(), nullable=True,
                  comment="1=按吨,2=按方,3=包干,4=按箱,5=面议"),
        sa.Column("price_unit", sa.String(32), nullable=True,
                  comment="计价单位"),
        sa.Column("contact_person", sa.String(64), nullable=True,
                  comment="联系人"),
        sa.Column("contact_phone", sa.String(32), nullable=True,
                  comment="联系电话"),
        sa.Column("remark", sa.Text(), nullable=True,
                  comment="备注"),

        # 来源追踪
        sa.Column("raw_message_id", sa.BigInteger(), nullable=True,
                  comment="原始文本ID（WECHAT_AI渠道）"),
        sa.Column("parse_result_id", sa.BigInteger(), nullable=True,
                  comment="AI解析结果ID（WECHAT_AI渠道）"),
        sa.Column("tms_external_id", sa.String(100), unique=True, nullable=True,
                  comment="TMS系统原始单号"),
        sa.Column("tms_raw_data", sa.JSON(), nullable=True,
                  comment="TMS原始报文快照"),
        sa.Column("collector_id", sa.BigInteger(), nullable=True,
                  comment="采集员/录入员ID"),

        # 审核流程
        sa.Column("audit_status", sa.SmallInteger(), nullable=False, server_default="0",
                  comment="0=待审核,1=已通过,2=已驳回"),
        sa.Column("submitter_id", sa.BigInteger(), nullable=True,
                  comment="提交人ID"),
        sa.Column("auditor_id", sa.BigInteger(), nullable=True,
                  comment="审核人ID"),
        sa.Column("audited_at", sa.DateTime(), nullable=True,
                  comment="审核时间"),
        sa.Column("audit_remark", sa.String(500), nullable=True,
                  comment="审核意见"),

        sa.Column("deleted_at", sa.DateTime(), nullable=True,
                  comment="软删时间，NULL=未删除"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),

        # 外键
        sa.ForeignKeyConstraint(["origin_node_id"], ["transport_node.id"]),
        sa.ForeignKeyConstraint(["dest_node_id"], ["transport_node.id"]),
        sa.ForeignKeyConstraint(["origin_region_id"], ["region.id"]),
        sa.ForeignKeyConstraint(["dest_region_id"], ["region.id"]),
        sa.ForeignKeyConstraint(["commodity_id"], ["commodity_standard.id"]),
        sa.ForeignKeyConstraint(["raw_message_id"], ["cargo_raw_message.id"]),
        sa.ForeignKeyConstraint(["parse_result_id"], ["cargo_ai_parse_result.id"]),
    )
    op.create_index("ix_cargo_freight_origin_city", "cargo_freight", ["origin_admin_code"])
    op.create_index("ix_cargo_freight_dest_city",   "cargo_freight", ["dest_admin_code"])
    op.create_index("ix_cargo_freight_source",      "cargo_freight", ["source_type"])
    op.create_index("ix_cargo_freight_status",      "cargo_freight", ["status"])
    op.create_index("ix_cargo_freight_created",     "cargo_freight", ["created_at"])

    # ── 2. cargo_city_heatmap ─────────────────────────────────────────────
    op.create_table(
        "cargo_city_heatmap",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stat_date", sa.Date(), nullable=False,
                  comment="统计日期"),
        sa.Column("city_code", sa.String(12), nullable=False,
                  comment="城市行政区划代码"),
        sa.Column("city_name", sa.String(50), nullable=False,
                  comment="城市名称（冗余）"),
        sa.Column("city_longitude", sa.DECIMAL(11, 8), nullable=True,
                  comment="城市中心经度"),
        sa.Column("city_latitude", sa.DECIMAL(10, 8), nullable=True,
                  comment="城市中心纬度"),
        sa.Column("stat_type", sa.String(8), nullable=False,
                  comment="ORIGIN=装货城市热力, DEST=卸货城市热力"),
        sa.Column("cargo_count", sa.Integer(), nullable=False, server_default="0",
                  comment="货源数量"),
        sa.Column("total_tonnage", sa.DECIMAL(16, 2), nullable=False, server_default="0",
                  comment="总吨位(吨)"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("stat_date", "city_code", "stat_type",
                            name="uk_cargo_city_heatmap"),
    )
    op.create_index("ix_cargo_city_heatmap_date", "cargo_city_heatmap", ["stat_date"])
    op.create_index("ix_cargo_city_heatmap_city", "cargo_city_heatmap", ["city_code"])

    # ── 3. cargo_od_daily ─────────────────────────────────────────────────
    op.create_table(
        "cargo_od_daily",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stat_date", sa.Date(), nullable=False,
                  comment="统计日期"),
        sa.Column("origin_city_code", sa.String(12), nullable=False,
                  comment="起点城市行政区划代码"),
        sa.Column("origin_city_name", sa.String(50), nullable=False,
                  comment="起点城市名称（冗余）"),
        sa.Column("dest_city_code", sa.String(12), nullable=False,
                  comment="终点城市行政区划代码"),
        sa.Column("dest_city_name", sa.String(50), nullable=False,
                  comment="终点城市名称（冗余）"),
        sa.Column("cargo_count", sa.Integer(), nullable=False, server_default="0",
                  comment="货源数量"),
        sa.Column("total_tonnage", sa.DECIMAL(16, 2), nullable=False, server_default="0",
                  comment="总吨位(吨)"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("stat_date", "origin_city_code", "dest_city_code",
                            name="uk_cargo_od_daily"),
    )
    op.create_index("ix_cargo_od_date",   "cargo_od_daily", ["stat_date"])
    op.create_index("ix_cargo_od_origin", "cargo_od_daily", ["origin_city_code"])

    # ── 4. cargo_channel_daily ────────────────────────────────────────────
    op.create_table(
        "cargo_channel_daily",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stat_date", sa.Date(), nullable=False,
                  comment="统计日期"),
        sa.Column("source_type", sa.String(20), nullable=False,
                  comment="TMS/WECHAT_AI/MANUAL"),
        sa.Column("raw_msg_count", sa.Integer(), nullable=False, server_default="0",
                  comment="原始消息/消费数量"),
        sa.Column("parse_success_count", sa.Integer(), nullable=False, server_default="0",
                  comment="AI解析成功数量（WECHAT_AI专用）"),
        sa.Column("confirmed_count", sa.Integer(), nullable=False, server_default="0",
                  comment="最终确认货源数量"),
        sa.Column("total_tonnage", sa.DECIMAL(16, 2), nullable=False, server_default="0",
                  comment="确认货源总吨位(吨)"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("stat_date", "source_type", name="uk_cargo_channel_daily"),
    )
    op.create_index("ix_cargo_channel_date", "cargo_channel_daily", ["stat_date"])

    # ── 5. 修复 cargo_stat_daily：重命名 active_count → confirmed_count，新增 avg_tonnage ──
    # batch_alter_table 在 SQLite 下通过重建表实现，在 PostgreSQL 下直接 ALTER COLUMN
    with op.batch_alter_table("cargo_stat_daily") as batch_op:
        batch_op.alter_column(
            "active_count",
            new_column_name="confirmed_count",
            existing_type=sa.Integer(),
            existing_nullable=False,
            existing_server_default="0",
        )
        batch_op.add_column(
            sa.Column("avg_tonnage", sa.DECIMAL(12, 2), nullable=False,
                      server_default="0", comment="平均吨位(吨)")
        )


def downgrade() -> None:
    # 恢复 cargo_stat_daily
    with op.batch_alter_table("cargo_stat_daily") as batch_op:
        batch_op.drop_column("avg_tonnage")
        batch_op.alter_column(
            "confirmed_count",
            new_column_name="active_count",
            existing_type=sa.Integer(),
            existing_nullable=False,
            existing_server_default="0",
        )

    op.drop_index("ix_cargo_channel_date",      table_name="cargo_channel_daily")
    op.drop_table("cargo_channel_daily")

    op.drop_index("ix_cargo_od_origin", table_name="cargo_od_daily")
    op.drop_index("ix_cargo_od_date",   table_name="cargo_od_daily")
    op.drop_table("cargo_od_daily")

    op.drop_index("ix_cargo_city_heatmap_city", table_name="cargo_city_heatmap")
    op.drop_index("ix_cargo_city_heatmap_date", table_name="cargo_city_heatmap")
    op.drop_table("cargo_city_heatmap")

    op.drop_index("ix_cargo_freight_created",   table_name="cargo_freight")
    op.drop_index("ix_cargo_freight_status",    table_name="cargo_freight")
    op.drop_index("ix_cargo_freight_source",    table_name="cargo_freight")
    op.drop_index("ix_cargo_freight_dest_city", table_name="cargo_freight")
    op.drop_index("ix_cargo_freight_origin_city", table_name="cargo_freight")
    op.drop_table("cargo_freight")
