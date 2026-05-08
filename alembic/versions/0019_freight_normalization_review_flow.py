"""freight_normalization_review_flow

Revision ID: 0019_freight_normalization_review_flow
Revises: 0018_commodity_master_refactor
Create Date: 2026-05-08 08:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0019_freight_normalization_review_flow"
down_revision: Union[str, None] = "0018_commodity_master_refactor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("freight_normalization_task") as batch_op:
        batch_op.add_column(
            sa.Column("review_status_code", sa.String(length=64), nullable=False, server_default="NOT_REQUIRED")
        )
        batch_op.add_column(sa.Column("review_completed_at", sa.DateTime(), nullable=True))
        batch_op.create_index(batch_op.f("ix_freight_normalization_task_review_status_code"), ["review_status_code"])


def downgrade() -> None:
    with op.batch_alter_table("freight_normalization_task") as batch_op:
        batch_op.drop_index(batch_op.f("ix_freight_normalization_task_review_status_code"))
        batch_op.drop_column("review_completed_at")
        batch_op.drop_column("review_status_code")
