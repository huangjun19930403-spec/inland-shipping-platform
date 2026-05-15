"""async_task_run

Revision ID: 002_async_task_run
Revises: 001_initial_schema
Create Date: 2026-05-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import BigInteger


@compiles(BigInteger, "sqlite")
def _compile_bigint_sqlite(_type, _compiler, **_kw):
    return "INTEGER"


revision: str = "002_async_task_run"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "async_task_run",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_name", sa.String(length=128), nullable=False),
        sa.Column("task_title", sa.String(length=128), nullable=False),
        sa.Column("celery_task_id", sa.String(length=128), nullable=True),
        sa.Column("queue_name", sa.String(length=64), nullable=False),
        sa.Column("business_type", sa.String(length=64), nullable=False),
        sa.Column("business_id", sa.BigInteger(), nullable=True),
        sa.Column("business_no", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=256), nullable=True),
        sa.Column("status_code", sa.String(length=64), nullable=False),
        sa.Column("stage_code", sa.String(length=64), nullable=True),
        sa.Column("stage_name", sa.String(length=128), nullable=True),
        sa.Column("stage_message", sa.Text(), nullable=True),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("requested_by", sa.BigInteger(), nullable=True),
        sa.Column("triggered_by", sa.String(length=64), nullable=True),
        sa.Column("queued_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("extra_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("async_task_run", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_async_task_run_business_id"), ["business_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_async_task_run_business_no"), ["business_no"], unique=False)
        batch_op.create_index(batch_op.f("ix_async_task_run_business_type"), ["business_type"], unique=False)
        batch_op.create_index(batch_op.f("ix_async_task_run_celery_task_id"), ["celery_task_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_async_task_run_heartbeat_at"), ["heartbeat_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_async_task_run_idempotency_key"), ["idempotency_key"], unique=False)
        batch_op.create_index(batch_op.f("ix_async_task_run_queue_name"), ["queue_name"], unique=False)
        batch_op.create_index(batch_op.f("ix_async_task_run_requested_by"), ["requested_by"], unique=False)
        batch_op.create_index(batch_op.f("ix_async_task_run_status_code"), ["status_code"], unique=False)
        batch_op.create_index(batch_op.f("ix_async_task_run_task_name"), ["task_name"], unique=False)


def downgrade() -> None:
    op.drop_table("async_task_run")
