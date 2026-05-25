"""navigation_water_area_layer_metadata

Revision ID: 007_navigation_water_area_layer_metadata
Revises: 006_database_numeric_compatibility
Create Date: 2026-05-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "007_navigation_water_area_layer_metadata"
down_revision: Union[str, None] = "006_database_numeric_compatibility"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("navigation_water_area", sa.Column("source_layer_code", sa.String(length=64), nullable=True))
    op.add_column("navigation_water_area", sa.Column("source_layer_display_name", sa.String(length=128), nullable=True))
    op.add_column("navigation_water_area", sa.Column("source_layer_role_code", sa.String(length=64), nullable=True))
    op.add_column("navigation_water_area", sa.Column("source_layer_order", sa.Integer(), nullable=True))
    op.add_column("navigation_water_area", sa.Column("source_file_name", sa.String(length=256), nullable=True))
    op.add_column(
        "navigation_water_area",
        sa.Column("has_attributes", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("navigation_water_area", sa.Column("raw_properties_json", sa.JSON(), nullable=True))

    op.create_index("ix_navigation_water_area_source_layer_code", "navigation_water_area", ["source_layer_code"])
    op.create_index("ix_navigation_water_area_source_layer_role_code", "navigation_water_area", ["source_layer_role_code"])
    op.create_index("ix_navigation_water_area_source_layer_order", "navigation_water_area", ["source_layer_order"])
    op.create_index("ix_navigation_water_area_has_attributes", "navigation_water_area", ["has_attributes"])


def downgrade() -> None:
    op.drop_index("ix_navigation_water_area_has_attributes", table_name="navigation_water_area")
    op.drop_index("ix_navigation_water_area_source_layer_order", table_name="navigation_water_area")
    op.drop_index("ix_navigation_water_area_source_layer_role_code", table_name="navigation_water_area")
    op.drop_index("ix_navigation_water_area_source_layer_code", table_name="navigation_water_area")

    op.drop_column("navigation_water_area", "raw_properties_json")
    op.drop_column("navigation_water_area", "has_attributes")
    op.drop_column("navigation_water_area", "source_file_name")
    op.drop_column("navigation_water_area", "source_layer_order")
    op.drop_column("navigation_water_area", "source_layer_role_code")
    op.drop_column("navigation_water_area", "source_layer_display_name")
    op.drop_column("navigation_water_area", "source_layer_code")
