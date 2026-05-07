"""freight_ai_progress

Revision ID: 0011_freight_ai_progress
Revises: 0010_freight_ai_async_and_availability
Create Date: 2026-05-07 20:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011_freight_ai_progress"
down_revision: Union[str, None] = "0010_freight_ai_async_and_availability"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("freight_batch_task", schema=None) as batch_op:
        batch_op.add_column(sa.Column("parse_stage_code", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("parse_stage_name", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("parse_stage_message", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("parse_progress_percent", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("parse_heartbeat_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("ai_elapsed_seconds", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("freight_batch_task", schema=None) as batch_op:
        batch_op.drop_column("ai_elapsed_seconds")
        batch_op.drop_column("parse_heartbeat_at")
        batch_op.drop_column("parse_progress_percent")
        batch_op.drop_column("parse_stage_message")
        batch_op.drop_column("parse_stage_name")
        batch_op.drop_column("parse_stage_code")
