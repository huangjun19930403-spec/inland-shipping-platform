"""water system display and quality fields

Revision ID: 0004_water_system_display_quality
Revises: 0003_navigation_water_systems
Create Date: 2026-05-10 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0004_water_system_display_quality"
down_revision: Union[str, None] = "0003_navigation_water_systems"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("water_system", schema=None) as batch_op:
        batch_op.add_column(sa.Column("parent_water_system_code", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("display_center_longitude", sa.Numeric(precision=11, scale=8), nullable=True))
        batch_op.add_column(sa.Column("display_center_latitude", sa.Numeric(precision=10, scale=8), nullable=True))
        batch_op.create_index(batch_op.f("ix_water_system_parent_water_system_code"), ["parent_water_system_code"], unique=False)

    with op.batch_alter_table("water_system_boundary", schema=None) as batch_op:
        batch_op.add_column(sa.Column("boundary_quality_code", sa.String(length=32), server_default="UNKNOWN", nullable=False))
        batch_op.create_index(batch_op.f("ix_water_system_boundary_boundary_quality_code"), ["boundary_quality_code"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("water_system_boundary", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_water_system_boundary_boundary_quality_code"))
        batch_op.drop_column("boundary_quality_code")

    with op.batch_alter_table("water_system", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_water_system_parent_water_system_code"))
        batch_op.drop_column("display_center_latitude")
        batch_op.drop_column("display_center_longitude")
        batch_op.drop_column("parent_water_system_code")
