"""Production-safe preset seed entrypoint."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.seed_admin_regions import seed_admin_regions
from scripts.seed_builtin_dicts import seed_builtin_dicts
from scripts.seed_code_sequences import seed_code_sequences
from scripts.seed_commodity_standards import seed_commodity_standards
from scripts.seed_commodity_taxonomy import seed_commodity_taxonomy
from scripts.seed_navigation_constraints import seed_navigation_constraints
from scripts.seed_system_base import seed_system_base
from scripts.seed_water_systems import seed_water_systems


async def seed_production_preset() -> None:
    await seed_builtin_dicts()
    await seed_code_sequences()
    await seed_admin_regions()
    await seed_water_systems()
    await seed_commodity_taxonomy()
    await seed_commodity_standards()
    await seed_navigation_constraints()
    await seed_system_base(preserve_existing_config_values=True)


if __name__ == "__main__":
    asyncio.run(seed_production_preset())
