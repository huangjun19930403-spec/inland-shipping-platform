"""freight_batch_review_flow

Revision ID: 0014_freight_batch_review_flow
Revises: 0013_freight_raw_tonnage_text
Create Date: 2026-05-07 23:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014_freight_batch_review_flow"
down_revision: Union[str, None] = "0013_freight_raw_tonnage_text"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("freight_batch_task", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "review_flow_status_code",
                sa.String(length=64),
                nullable=False,
                server_default="REVIEWING",
            )
        )
        batch_op.create_index(
            batch_op.f("ix_freight_batch_task_review_flow_status_code"),
            ["review_flow_status_code"],
            unique=False,
        )
    with op.batch_alter_table("freight_batch_task", schema=None) as batch_op:
        batch_op.alter_column("review_flow_status_code", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("freight_batch_task", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_freight_batch_task_review_flow_status_code"))
        batch_op.drop_column("review_flow_status_code")
