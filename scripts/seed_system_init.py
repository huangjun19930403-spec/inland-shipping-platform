"""系统初始化脚本骨架（非 AI 版本）。"""

from __future__ import annotations

import asyncio

from scripts.seed_admin_regions import seed_admin_regions
from scripts.seed_builtin_dicts import seed_builtin_dicts
from scripts.seed_code_sequences import seed_code_sequences
from scripts.seed_commodity_standards import seed_commodity_standards
from scripts.seed_commodity_taxonomy import seed_commodity_taxonomy
from scripts.seed_route_map_e2e import seed_route_map_e2e
from scripts.seed_system_base import seed_system_base


async def seed_system_init() -> None:
    await seed_builtin_dicts()
    await seed_code_sequences()
    await seed_admin_regions()
    await seed_commodity_taxonomy()
    await seed_commodity_standards()
    await seed_system_base()
    await seed_route_map_e2e()


if __name__ == "__main__":
    asyncio.run(seed_system_init())
