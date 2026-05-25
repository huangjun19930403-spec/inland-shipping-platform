"""Refresh PostGIS geometry columns from GeoJSON payload columns.

Run this after production seeds or geometry draft publishing on a PostgreSQL /
PostGIS database. It is intentionally a no-op for SQLite/MySQL.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass

from sqlalchemy import text

from app.core.database import engine


SPATIAL_TABLES = (
    "navigation_water_area",
    "navigation_channel_boundary",
    "navigation_channel_centerline",
    "navigation_graph_edge",
    "navigation_geometry_draft",
)


@dataclass(slots=True)
class GeometryRefreshRow:
    table_name: str
    total_count: int
    geometry_count: int


async def refresh_postgis_geometry_columns() -> dict[str, object]:
    async with engine.begin() as conn:
        if conn.dialect.name != "postgresql":
            return {"skipped": True, "dialect": conn.dialect.name, "tables": []}
        for table_name in SPATIAL_TABLES:
            await conn.execute(
                text(
                    f"""
                    UPDATE {table_name}
                       SET geom = CASE
                            WHEN geometry_json IS NULL THEN NULL
                            ELSE ST_SetSRID(ST_GeomFromGeoJSON(geometry_json::text), 4326)
                           END
                    """
                )
            )

    rows: list[GeometryRefreshRow] = []
    async with engine.connect() as conn:
        for table_name in SPATIAL_TABLES:
            total_count = await conn.scalar(text(f"SELECT COUNT(*) FROM {table_name}"))
            geometry_count = await conn.scalar(text(f"SELECT COUNT(*) FROM {table_name} WHERE geom IS NOT NULL"))
            rows.append(
                GeometryRefreshRow(
                    table_name=table_name,
                    total_count=int(total_count or 0),
                    geometry_count=int(geometry_count or 0),
                )
            )
    return {"skipped": False, "dialect": "postgresql", "tables": [asdict(row) for row in rows]}


async def _main() -> None:
    result = await refresh_postgis_geometry_columns()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
