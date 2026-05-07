"""freight_ai_async_and_availability

Revision ID: 0010_freight_ai_async_and_availability
Revises: 0009_freight_collection_production_rework
Create Date: 2026-05-07 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010_freight_ai_async_and_availability"
down_revision: Union[str, None] = "0009_freight_collection_production_rework"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("freight_candidate", schema=None) as batch_op:
        batch_op.add_column(sa.Column("availability_status_code", sa.String(length=64), nullable=False, server_default="UNKNOWN"))
        batch_op.add_column(sa.Column("manual_review_reason", sa.String(length=512), nullable=True))
        batch_op.add_column(sa.Column("ai_warning_json", sa.JSON(), nullable=True))
        batch_op.create_index("ix_freight_candidate_availability_status_code", ["availability_status_code"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("freight_candidate", schema=None) as batch_op:
        batch_op.drop_index("ix_freight_candidate_availability_status_code")
        batch_op.drop_column("ai_warning_json")
        batch_op.drop_column("manual_review_reason")
        batch_op.drop_column("availability_status_code")
