"""navigation_postgis_spatial_columns

Revision ID: 005_navigation_postgis_spatial_columns
Revises: 004_navigation_channel_water_area_match
Create Date: 2026-05-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "005_navigation_postgis_spatial_columns"
down_revision: Union[str, None] = "004_navigation_channel_water_area_match"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SPATIAL_TABLES = {
    "navigation_water_area": "geom",
    "navigation_channel_boundary": "geom",
    "navigation_channel_centerline": "geom",
    "navigation_graph_edge": "geom",
    "navigation_geometry_draft": "geom",
}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    for table_name, column_name in SPATIAL_TABLES.items():
        op.execute(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_name} geometry(Geometry, 4326)")
        op.execute(
            f"""
            UPDATE {table_name}
               SET {column_name} = ST_SetSRID(ST_GeomFromGeoJSON(geometry_json::text), 4326)
             WHERE geometry_json IS NOT NULL
               AND {column_name} IS NULL
            """
        )
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table_name}_{column_name}_gist ON {table_name} USING GIST ({column_name})")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table_name, column_name in reversed(SPATIAL_TABLES.items()):
        op.execute(f"DROP INDEX IF EXISTS ix_{table_name}_{column_name}_gist")
        op.execute(f"ALTER TABLE {table_name} DROP COLUMN IF EXISTS {column_name}")
