"""database_numeric_compatibility

Revision ID: 006_database_numeric_compatibility
Revises: 005_navigation_postgis_spatial_columns
Create Date: 2026-05-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "006_database_numeric_compatibility"
down_revision: Union[str, None] = "005_navigation_postgis_spatial_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


COORDINATE_COLUMNS: dict[str, tuple[str, ...]] = {
    "admin_region": (
        "longitude",
        "latitude",
    ),
    "admin_region_boundary": (
        "center_longitude",
        "center_latitude",
    ),
    "region_boundary_version": (
        "center_longitude",
        "center_latitude",
    ),
    "transport_node": (
        "longitude",
        "latitude",
    ),
    "navigation_constraint_point": (
        "longitude",
        "latitude",
    ),
    "shipping_route_plan_point": (
        "longitude",
        "latitude",
    ),
    "navigation_channel_boundary": (
        "center_longitude",
        "center_latitude",
        "display_center_longitude",
        "display_center_latitude",
        "bbox_min_lng",
        "bbox_min_lat",
        "bbox_max_lng",
        "bbox_max_lat",
    ),
    "navigation_water_area": (
        "bbox_min_lng",
        "bbox_min_lat",
        "bbox_max_lng",
        "bbox_max_lat",
        "center_lng",
        "center_lat",
    ),
    "navigation_channel_centerline": (
        "bbox_min_lng",
        "bbox_min_lat",
        "bbox_max_lng",
        "bbox_max_lat",
    ),
    "navigation_geometry_draft": (
        "bbox_min_lng",
        "bbox_min_lat",
        "bbox_max_lng",
        "bbox_max_lat",
    ),
    "navigation_graph_node": (
        "longitude",
        "latitude",
    ),
    "navigation_route_request": (
        "origin_lng",
        "origin_lat",
        "destination_lng",
        "destination_lat",
    ),
}

REQUIRED_COORDINATE_COLUMNS = {
    ("navigation_constraint_point", "longitude"),
    ("navigation_constraint_point", "latitude"),
    ("navigation_graph_node", "longitude"),
    ("navigation_graph_node", "latitude"),
    ("navigation_route_request", "origin_lng"),
    ("navigation_route_request", "origin_lat"),
    ("navigation_route_request", "destination_lng"),
    ("navigation_route_request", "destination_lat"),
}

DEGREE_MEASURE_COLUMNS: dict[str, tuple[str, ...]] = {
    "navigation_channel_boundary": (
        "source_shape_length_degree",
        "source_shape_area_degree",
    ),
    "navigation_water_area": (
        "shape_length_degree",
        "shape_area_degree",
    ),
}


def _alter_columns(columns_by_table: dict[str, tuple[str, ...]], *, type_: sa.Numeric, existing_type: sa.Numeric) -> None:
    for table_name, column_names in columns_by_table.items():
        for column_name in column_names:
            op.alter_column(
                table_name,
                column_name,
                existing_type=existing_type,
                type_=type_,
                existing_nullable=(table_name, column_name) not in REQUIRED_COORDINATE_COLUMNS,
            )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    _alter_columns(
        COORDINATE_COLUMNS,
        existing_type=sa.Numeric(11, 8),
        type_=sa.Numeric(24, 15),
    )
    _alter_columns(
        DEGREE_MEASURE_COLUMNS,
        existing_type=sa.Numeric(24, 15),
        type_=sa.Numeric(30, 18),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    _alter_columns(
        DEGREE_MEASURE_COLUMNS,
        existing_type=sa.Numeric(30, 18),
        type_=sa.Numeric(24, 15),
    )
    _alter_columns(
        COORDINATE_COLUMNS,
        existing_type=sa.Numeric(24, 15),
        type_=sa.Numeric(11, 8),
    )
