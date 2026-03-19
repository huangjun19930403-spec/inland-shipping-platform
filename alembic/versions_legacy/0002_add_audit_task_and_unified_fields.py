"""add audit_task table and unify audit fields across business tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. 新建 audit_task 表 ──────────────────────────────────────────────
    op.create_table(
        "audit_task",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("target_type", sa.String(64), nullable=False,
                  comment="审核对象类型"),
        sa.Column("target_id", sa.BigInteger(), nullable=False,
                  comment="被审核对象ID"),
        sa.Column("target_name", sa.String(256), nullable=True,
                  comment="被审核对象名称（快照）"),
        sa.Column("action", sa.String(32), nullable=False,
                  comment="CREATE/UPDATE"),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default="pending",
                  comment="pending=待审核,approved=已通过,rejected=已驳回"),
        sa.Column("submitter_id", sa.BigInteger(), nullable=False,
                  comment="提交人ID"),
        sa.Column("submit_time", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
                  comment="提交时间"),
        sa.Column("auditor_id", sa.BigInteger(), nullable=True,
                  comment="审核人ID"),
        sa.Column("audit_time", sa.DateTime(), nullable=True,
                  comment="审核时间"),
        sa.Column("remark", sa.String(512), nullable=True,
                  comment="审核意见"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_audit_task_target_type", "audit_task", ["target_type"])
    op.create_index("ix_audit_task_target_id", "audit_task", ["target_id"])
    op.create_index("ix_audit_task_status", "audit_task", ["status"])

    # ── 2. waterway：新增 audit_status / submitter_id / audited_at ─────────
    with op.batch_alter_table("waterway", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("audit_status", sa.SmallInteger(), nullable=False,
                      server_default="0", comment="0=待审核,1=已通过,2=已驳回")
        )
        batch_op.add_column(
            sa.Column("submitter_id", sa.BigInteger(), nullable=True,
                      comment="提交人ID")
        )
        batch_op.add_column(
            sa.Column("audited_at", sa.DateTime(), nullable=True,
                      comment="审核时间")
        )

    # ── 3. node_type：新增 audit_status / submitter_id / audited_at ────────
    with op.batch_alter_table("node_type", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("audit_status", sa.SmallInteger(), nullable=False,
                      server_default="0", comment="0=待审核,1=已通过,2=已驳回")
        )
        batch_op.add_column(
            sa.Column("submitter_id", sa.BigInteger(), nullable=True,
                      comment="提交人ID")
        )
        batch_op.add_column(
            sa.Column("audited_at", sa.DateTime(), nullable=True,
                      comment="审核时间")
        )

    # ── 4. region：新增 audited_at ─────────────────────────────────────────
    with op.batch_alter_table("region", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("audited_at", sa.DateTime(), nullable=True,
                      comment="审核时间")
        )

    # ── 5. transport_node：新增 audited_at；audit_status 默认值改为 0 ───────
    with op.batch_alter_table("transport_node", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("audited_at", sa.DateTime(), nullable=True,
                      comment="审核时间")
        )
        batch_op.alter_column(
            "audit_status",
            existing_type=sa.SmallInteger(),
            server_default="0",
            existing_nullable=True,
        )

    # ── 6. commodity_category：新增 audited_at；audit_status 默认值改为 0 ──
    with op.batch_alter_table("commodity_category", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("audited_at", sa.DateTime(), nullable=True,
                      comment="审核时间")
        )
        batch_op.alter_column(
            "audit_status",
            existing_type=sa.SmallInteger(),
            server_default="0",
            existing_nullable=True,
        )

    # ── 7. commodity_type：新增 audited_at；audit_status 默认值改为 0 ───────
    with op.batch_alter_table("commodity_type", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("audited_at", sa.DateTime(), nullable=True,
                      comment="审核时间")
        )
        batch_op.alter_column(
            "audit_status",
            existing_type=sa.SmallInteger(),
            server_default="0",
            existing_nullable=True,
        )

    # ── 8. commodity_standard：新增 audited_at；audit_status 默认值改为 0 ──
    with op.batch_alter_table("commodity_standard", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("audited_at", sa.DateTime(), nullable=True,
                      comment="审核时间")
        )
        batch_op.alter_column(
            "audit_status",
            existing_type=sa.SmallInteger(),
            server_default="0",
            existing_nullable=True,
        )

    # ── 9. vessel_type_dict：新增 audited_at；audit_status 默认值改为 0 ─────
    with op.batch_alter_table("vessel_type_dict", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("audited_at", sa.DateTime(), nullable=True,
                      comment="审核时间")
        )
        batch_op.alter_column(
            "audit_status",
            existing_type=sa.SmallInteger(),
            server_default="0",
            existing_nullable=True,
        )

    # ── 10. vessel：新增 audited_at；audit_status 默认值改为 0 ───────────────
    with op.batch_alter_table("vessel", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("audited_at", sa.DateTime(), nullable=True,
                      comment="审核时间")
        )
        batch_op.alter_column(
            "audit_status",
            existing_type=sa.SmallInteger(),
            server_default="0",
            existing_nullable=True,
        )

    # ── 11. cargo_opportunity：新增 audit_status / submitter_id / audited_at
    with op.batch_alter_table("cargo_opportunity", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("audit_status", sa.SmallInteger(), nullable=False,
                      server_default="0", comment="0=待审核,1=已通过,2=已驳回")
        )
        batch_op.add_column(
            sa.Column("submitter_id", sa.BigInteger(), nullable=True,
                      comment="提交人ID")
        )
        batch_op.add_column(
            sa.Column("audited_at", sa.DateTime(), nullable=True,
                      comment="审核时间")
        )


def downgrade() -> None:
    with op.batch_alter_table("cargo_opportunity", schema=None) as batch_op:
        batch_op.drop_column("audited_at")
        batch_op.drop_column("submitter_id")
        batch_op.drop_column("audit_status")

    with op.batch_alter_table("vessel", schema=None) as batch_op:
        batch_op.drop_column("audited_at")

    with op.batch_alter_table("vessel_type_dict", schema=None) as batch_op:
        batch_op.drop_column("audited_at")

    with op.batch_alter_table("commodity_standard", schema=None) as batch_op:
        batch_op.drop_column("audited_at")

    with op.batch_alter_table("commodity_type", schema=None) as batch_op:
        batch_op.drop_column("audited_at")

    with op.batch_alter_table("commodity_category", schema=None) as batch_op:
        batch_op.drop_column("audited_at")

    with op.batch_alter_table("transport_node", schema=None) as batch_op:
        batch_op.drop_column("audited_at")

    with op.batch_alter_table("region", schema=None) as batch_op:
        batch_op.drop_column("audited_at")

    with op.batch_alter_table("node_type", schema=None) as batch_op:
        batch_op.drop_column("audited_at")
        batch_op.drop_column("submitter_id")
        batch_op.drop_column("audit_status")

    with op.batch_alter_table("waterway", schema=None) as batch_op:
        batch_op.drop_column("audited_at")
        batch_op.drop_column("submitter_id")
        batch_op.drop_column("audit_status")

    op.drop_index("ix_audit_task_status", table_name="audit_task")
    op.drop_index("ix_audit_task_target_id", table_name="audit_task")
    op.drop_index("ix_audit_task_target_type", table_name="audit_task")
    op.drop_table("audit_task")
