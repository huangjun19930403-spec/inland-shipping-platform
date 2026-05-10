"""add water system boundary coordinate system metadata

Revision ID: 0005_water_system_boundary_coordinate_system
Revises: 0004_water_system_display_quality
Create Date: 2026-05-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_water_system_boundary_coordinate_system"
down_revision = "0004_water_system_display_quality"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("water_system_boundary") as batch_op:
        batch_op.add_column(
            sa.Column(
                "geometry_coordinate_system_code",
                sa.String(length=16),
                nullable=False,
                server_default="WGS84",
            )
        )
        batch_op.add_column(
            sa.Column(
                "boundary_coordinate_system_code",
                sa.String(length=16),
                nullable=False,
                server_default="WGS84",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("water_system_boundary") as batch_op:
        batch_op.drop_column("boundary_coordinate_system_code")
        batch_op.drop_column("geometry_coordinate_system_code")
