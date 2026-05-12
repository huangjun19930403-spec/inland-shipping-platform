"""add permission code binding to system menus

Revision ID: 0006_sys_menu_permission_code
Revises: 0005_water_system_boundary_coordinate_system
Create Date: 2026-05-12 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_sys_menu_permission_code"
down_revision = "0005_water_system_boundary_coordinate_system"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sys_menu") as batch_op:
        batch_op.add_column(sa.Column("permission_code", sa.String(length=128), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sys_menu") as batch_op:
        batch_op.drop_column("permission_code")
