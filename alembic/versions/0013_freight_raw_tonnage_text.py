"""freight_raw_tonnage_text

Revision ID: 0013_freight_raw_tonnage_text
Revises: 0012_freight_raw_level_normalization
Create Date: 2026-05-07 23:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013_freight_raw_tonnage_text"
down_revision: Union[str, None] = "0012_freight_raw_level_normalization"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("freight", schema=None) as batch_op:
        batch_op.add_column(sa.Column("raw_tonnage_text", sa.String(length=128), nullable=True))
    with op.batch_alter_table("freight_candidate", schema=None) as batch_op:
        batch_op.add_column(sa.Column("raw_tonnage_text", sa.String(length=128), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("freight_candidate", schema=None) as batch_op:
        batch_op.drop_column("raw_tonnage_text")
    with op.batch_alter_table("freight", schema=None) as batch_op:
        batch_op.drop_column("raw_tonnage_text")
