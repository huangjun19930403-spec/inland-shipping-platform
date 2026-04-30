"""audit_governance_system_config

Revision ID: 0005_audit_governance_system_config
Revises: 0004_analysis_fact_metrics
Create Date: 2026-04-30 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_audit_governance_system_config"
down_revision: Union[str, None] = "0004_analysis_fact_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audit_task", sa.Column("object_type_code", sa.String(length=64), nullable=True))
    op.add_column("audit_task", sa.Column("object_code", sa.String(length=128), nullable=True))
    op.add_column("audit_task", sa.Column("object_name", sa.String(length=256), nullable=True))
    op.add_column("audit_task", sa.Column("change_type_code", sa.String(length=64), nullable=True))
    op.add_column("audit_task", sa.Column("source_module_code", sa.String(length=64), nullable=True))
    op.add_column("audit_task", sa.Column("submitter_name", sa.String(length=64), nullable=True))
    op.add_column("audit_task", sa.Column("current_handler_name", sa.String(length=64), nullable=True))
    op.create_index("ix_audit_task_object_type_code", "audit_task", ["object_type_code"])
    op.create_index("ix_audit_task_object_code", "audit_task", ["object_code"])
    op.create_index("ix_audit_task_change_type_code", "audit_task", ["change_type_code"])
    op.create_index("ix_audit_task_source_module_code", "audit_task", ["source_module_code"])

    op.create_table(
        "audit_task_snapshot",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.BigInteger(), nullable=False),
        sa.Column("before_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("after_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("diff_json", sa.JSON(), nullable=True),
        sa.Column("summary_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["audit_task.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
    )
    op.create_index("ix_audit_task_snapshot_task_id", "audit_task_snapshot", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_task_snapshot_task_id", table_name="audit_task_snapshot")
    op.drop_table("audit_task_snapshot")
    op.drop_index("ix_audit_task_source_module_code", table_name="audit_task")
    op.drop_index("ix_audit_task_change_type_code", table_name="audit_task")
    op.drop_index("ix_audit_task_object_code", table_name="audit_task")
    op.drop_index("ix_audit_task_object_type_code", table_name="audit_task")
    op.drop_column("audit_task", "current_handler_name")
    op.drop_column("audit_task", "submitter_name")
    op.drop_column("audit_task", "source_module_code")
    op.drop_column("audit_task", "change_type_code")
    op.drop_column("audit_task", "object_name")
    op.drop_column("audit_task", "object_code")
    op.drop_column("audit_task", "object_type_code")
