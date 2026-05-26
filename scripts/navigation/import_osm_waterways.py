"""CLI wrapper for importing real OSM waterway GeoJSON."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.core.database import AsyncSessionLocal
from app.modules.navigation.services.osm_import_service import (
    DEFAULT_ALIAS_CONFIG,
    OsmWaterwayImportSummary,
    import_osm_waterways,
)

__all__ = ["DEFAULT_ALIAS_CONFIG", "OsmWaterwayImportSummary", "import_osm_waterways"]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import real OSM waterway GeoJSON as navigation centerline candidates.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--scope-code", default="REAL-JS-YRD")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    async with AsyncSessionLocal() as session:
        summary = await import_osm_waterways(
            session=session,
            source_path=args.input,
            scope_code=args.scope_code,
            dry_run=args.dry_run,
        )
    print(json.dumps(summary.as_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
