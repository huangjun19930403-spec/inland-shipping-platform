"""water systems

Revision ID: 0002_water_systems
Revises: 0001_platform_current_schema
Create Date: 2026-05-10 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import BigInteger


@compiles(BigInteger, "sqlite")
def _compile_bigint_sqlite(_type, _compiler, **_kw):
    return "INTEGER"


# revision identifiers, used by Alembic.
revision: str = "0002_water_systems"
down_revision: Union[str, None] = "0001_platform_current_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "water_system",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("water_system_code", sa.String(length=32), nullable=False),
        sa.Column("water_system_name", sa.String(length=128), nullable=False),
        sa.Column("water_level", sa.SmallInteger(), nullable=False),
        sa.Column("feature_type_code", sa.String(length=32), nullable=False),
        sa.Column("hydrology_period_code", sa.String(length=32), nullable=False),
        sa.Column("salinity_type_code", sa.String(length=32), nullable=False),
        sa.Column("water_boundary_type_code", sa.String(length=32), nullable=False),
        sa.Column("source_remark", sa.String(length=256), nullable=True),
        sa.Column("source_layer_name", sa.String(length=64), nullable=False),
        sa.Column("source_version", sa.String(length=64), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("water_system_code"),
    )
    with op.batch_alter_table("water_system", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_water_system_feature_type_code"), ["feature_type_code"], unique=False)
        batch_op.create_index(batch_op.f("ix_water_system_hydrology_period_code"), ["hydrology_period_code"], unique=False)
        batch_op.create_index(batch_op.f("ix_water_system_is_enabled"), ["is_enabled"], unique=False)
        batch_op.create_index(batch_op.f("ix_water_system_salinity_type_code"), ["salinity_type_code"], unique=False)
        batch_op.create_index(batch_op.f("ix_water_system_source_layer_name"), ["source_layer_name"], unique=False)
        batch_op.create_index(batch_op.f("ix_water_system_source_version"), ["source_version"], unique=False)
        batch_op.create_index(batch_op.f("ix_water_system_water_boundary_type_code"), ["water_boundary_type_code"], unique=False)
        batch_op.create_index(batch_op.f("ix_water_system_water_level"), ["water_level"], unique=False)
        batch_op.create_index(batch_op.f("ix_water_system_water_system_code"), ["water_system_code"], unique=True)
        batch_op.create_index(batch_op.f("ix_water_system_water_system_name"), ["water_system_name"], unique=False)

    op.create_table(
        "water_system_boundary",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("water_system_id", sa.BigInteger(), nullable=False),
        sa.Column("geometry_json", sa.JSON(), nullable=False),
        sa.Column("boundary_paths_low", sa.JSON(), nullable=True),
        sa.Column("boundary_paths_medium", sa.JSON(), nullable=True),
        sa.Column("boundary_paths_high", sa.JSON(), nullable=True),
        sa.Column("center_longitude", sa.Numeric(precision=11, scale=8), nullable=True),
        sa.Column("center_latitude", sa.Numeric(precision=10, scale=8), nullable=True),
        sa.Column("bbox_min_lng", sa.Numeric(precision=11, scale=8), nullable=True),
        sa.Column("bbox_min_lat", sa.Numeric(precision=10, scale=8), nullable=True),
        sa.Column("bbox_max_lng", sa.Numeric(precision=11, scale=8), nullable=True),
        sa.Column("bbox_max_lat", sa.Numeric(precision=10, scale=8), nullable=True),
        sa.Column("source_shape_length_degree", sa.Numeric(precision=24, scale=15), nullable=True),
        sa.Column("source_shape_area_degree", sa.Numeric(precision=24, scale=15), nullable=True),
        sa.Column("ring_count", sa.Integer(), nullable=False),
        sa.Column("point_count", sa.Integer(), nullable=False),
        sa.Column("geometry_status_code", sa.String(length=32), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("imported_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["water_system_id"], ["water_system.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("water_system_boundary", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_water_system_boundary_geometry_status_code"), ["geometry_status_code"], unique=False)
        batch_op.create_index(batch_op.f("ix_water_system_boundary_is_current"), ["is_current"], unique=False)
        batch_op.create_index(batch_op.f("ix_water_system_boundary_water_system_id"), ["water_system_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("water_system_boundary", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_water_system_boundary_water_system_id"))
        batch_op.drop_index(batch_op.f("ix_water_system_boundary_is_current"))
        batch_op.drop_index(batch_op.f("ix_water_system_boundary_geometry_status_code"))
    op.drop_table("water_system_boundary")

    with op.batch_alter_table("water_system", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_water_system_water_system_name"))
        batch_op.drop_index(batch_op.f("ix_water_system_water_system_code"))
        batch_op.drop_index(batch_op.f("ix_water_system_water_level"))
        batch_op.drop_index(batch_op.f("ix_water_system_water_boundary_type_code"))
        batch_op.drop_index(batch_op.f("ix_water_system_source_version"))
        batch_op.drop_index(batch_op.f("ix_water_system_source_layer_name"))
        batch_op.drop_index(batch_op.f("ix_water_system_salinity_type_code"))
        batch_op.drop_index(batch_op.f("ix_water_system_is_enabled"))
        batch_op.drop_index(batch_op.f("ix_water_system_hydrology_period_code"))
        batch_op.drop_index(batch_op.f("ix_water_system_feature_type_code"))
    op.drop_table("water_system")
