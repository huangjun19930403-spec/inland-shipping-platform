"""add region audit fields

Revision ID: 0001
Revises:
Create Date: 2026-03-16
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 新增 region 表的审核相关字段
    with op.batch_alter_table("region", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("audit_status", sa.SmallInteger(), nullable=False,
                      server_default="0",
                      comment="0=待审核,1=已通过,2=已驳回")
        )
        batch_op.add_column(
            sa.Column("audit_remark", sa.String(512), nullable=True,
                      comment="审核意见")
        )
        batch_op.add_column(
            sa.Column("submitter_id", sa.BigInteger(), nullable=True,
                      comment="提交人ID")
        )
        batch_op.add_column(
            sa.Column("auditor_id", sa.BigInteger(), nullable=True,
                      comment="审核人ID")
        )
        # status 默认值改为 0（停用，等待审核通过后再启用）
        batch_op.alter_column(
            "status",
            existing_type=sa.SmallInteger(),
            server_default="0",
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("region", schema=None) as batch_op:
        batch_op.drop_column("auditor_id")
        batch_op.drop_column("submitter_id")
        batch_op.drop_column("audit_remark")
        batch_op.drop_column("audit_status")
        batch_op.alter_column(
            "status",
            existing_type=sa.SmallInteger(),
            server_default="1",
            existing_nullable=False,
        )
