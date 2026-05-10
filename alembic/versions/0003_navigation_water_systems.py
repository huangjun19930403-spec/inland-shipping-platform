"""navigation water systems

Revision ID: 0003_navigation_water_systems
Revises: 0002_water_systems
Create Date: 2026-05-10 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003_navigation_water_systems"
down_revision: Union[str, None] = "0002_water_systems"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("water_system", schema=None) as batch_op:
        batch_op.add_column(sa.Column("standard_name", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("display_name", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("navigation_category_code", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("navigation_scope_code", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("ais_situation_scope", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("display_priority", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("match_level_code", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("match_confidence_code", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("review_required", sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column("source_feature_count", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("source_object_ids", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("source_levels", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("source_layer_names", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("source_names", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("source_remarks", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("geometry_union_status", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("business_remark", sa.String(length=512), nullable=True))
        batch_op.create_index(batch_op.f("ix_water_system_standard_name"), ["standard_name"], unique=False)
        batch_op.create_index(batch_op.f("ix_water_system_navigation_category_code"), ["navigation_category_code"], unique=False)
        batch_op.create_index(batch_op.f("ix_water_system_navigation_scope_code"), ["navigation_scope_code"], unique=False)
        batch_op.create_index(batch_op.f("ix_water_system_ais_situation_scope"), ["ais_situation_scope"], unique=False)
        batch_op.create_index(batch_op.f("ix_water_system_match_level_code"), ["match_level_code"], unique=False)
        batch_op.create_index(batch_op.f("ix_water_system_match_confidence_code"), ["match_confidence_code"], unique=False)
        batch_op.create_index(batch_op.f("ix_water_system_review_required"), ["review_required"], unique=False)
        batch_op.create_index(batch_op.f("ix_water_system_geometry_union_status"), ["geometry_union_status"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("water_system", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_water_system_geometry_union_status"))
        batch_op.drop_index(batch_op.f("ix_water_system_review_required"))
        batch_op.drop_index(batch_op.f("ix_water_system_match_confidence_code"))
        batch_op.drop_index(batch_op.f("ix_water_system_match_level_code"))
        batch_op.drop_index(batch_op.f("ix_water_system_ais_situation_scope"))
        batch_op.drop_index(batch_op.f("ix_water_system_navigation_scope_code"))
        batch_op.drop_index(batch_op.f("ix_water_system_navigation_category_code"))
        batch_op.drop_index(batch_op.f("ix_water_system_standard_name"))
        batch_op.drop_column("business_remark")
        batch_op.drop_column("geometry_union_status")
        batch_op.drop_column("source_remarks")
        batch_op.drop_column("source_names")
        batch_op.drop_column("source_layer_names")
        batch_op.drop_column("source_levels")
        batch_op.drop_column("source_object_ids")
        batch_op.drop_column("source_feature_count")
        batch_op.drop_column("review_required")
        batch_op.drop_column("match_confidence_code")
        batch_op.drop_column("match_level_code")
        batch_op.drop_column("display_priority")
        batch_op.drop_column("ais_situation_scope")
        batch_op.drop_column("navigation_scope_code")
        batch_op.drop_column("navigation_category_code")
        batch_op.drop_column("display_name")
        batch_op.drop_column("standard_name")
