"""freight_normalization_task

Revision ID: 0015_freight_normalization_task
Revises: 0014_freight_batch_review_flow
Create Date: 2026-05-07 16:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015_freight_normalization_task"
down_revision: Union[str, None] = "0014_freight_batch_review_flow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "freight_normalization_task",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_no", sa.String(length=32), nullable=False),
        sa.Column("celery_task_id", sa.String(length=128), nullable=True),
        sa.Column("status_code", sa.String(length=64), nullable=False),
        sa.Column("stage_code", sa.String(length=64), nullable=True),
        sa.Column("stage_name", sa.String(length=128), nullable=True),
        sa.Column("stage_message", sa.Text(), nullable=True),
        sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scanned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("suggestion_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("auto_applied_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pending_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requested_by", sa.BigInteger(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_no"),
    )
    op.create_index("ix_freight_normalization_task_celery_task_id", "freight_normalization_task", ["celery_task_id"])
    op.create_index("ix_freight_normalization_task_requested_by", "freight_normalization_task", ["requested_by"])
    op.create_index("ix_freight_normalization_task_status_code", "freight_normalization_task", ["status_code"])
    with op.batch_alter_table("freight_normalization_suggestion", schema=None) as batch_op:
        batch_op.add_column(sa.Column("clean_task_id", sa.BigInteger(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_freight_normalization_suggestion_clean_task_id_freight_normalization_task"),
            "freight_normalization_task",
            ["clean_task_id"],
            ["id"],
        )
        batch_op.create_index(batch_op.f("ix_freight_normalization_suggestion_clean_task_id"), ["clean_task_id"])


def downgrade() -> None:
    with op.batch_alter_table("freight_normalization_suggestion", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_freight_normalization_suggestion_clean_task_id"))
        batch_op.drop_constraint(
            batch_op.f("fk_freight_normalization_suggestion_clean_task_id_freight_normalization_task"),
            type_="foreignkey",
        )
        batch_op.drop_column("clean_task_id")
    op.drop_index("ix_freight_normalization_task_status_code", table_name="freight_normalization_task")
    op.drop_index("ix_freight_normalization_task_requested_by", table_name="freight_normalization_task")
    op.drop_index("ix_freight_normalization_task_celery_task_id", table_name="freight_normalization_task")
    op.drop_table("freight_normalization_task")
