"""Production preset seed entrypoint."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.database import AsyncSessionLocal
from app.modules.analysis.statistics import seed_analysis_job_definitions
from scripts.seeds.loaders.admin_regions import seed_admin_regions
from scripts.seeds.loaders.approval_base import seed_approval_base
from scripts.seeds.loaders.business_regions import seed_business_regions
from scripts.seeds.loaders.builtin_dicts import seed_builtin_dicts
from scripts.seeds.loaders.code_sequences import seed_code_sequences
from scripts.seeds.loaders.commodity_standards import seed_commodity_standards
from scripts.seeds.loaders.commodity_taxonomy import seed_commodity_taxonomy
from scripts.seeds.loaders.navigation_channels import seed_navigation_channels
from scripts.seeds.loaders.navigation_constraints import seed_navigation_constraints
from scripts.seeds.loaders.navigation_revier_production import (
    delete_existing_revier_graph_payload,
    seed_navigation_revier_production,
)
from scripts.seeds.loaders.navigation_water_areas import seed_navigation_water_areas
from scripts.seeds.loaders.production_freights import seed_production_freights
from scripts.seeds.loaders.production_vessels import seed_production_vessels
from scripts.seeds.loaders.system_base import seed_system_base
from scripts.seeds.loaders.transport_nodes import seed_transport_nodes
from scripts.seeds.manifest import validate_seed_manifest
from scripts.navigation.refresh_postgis_geometry_columns import refresh_postgis_geometry_columns
from scripts.navigation.build_water_bodies import build_navigation_water_bodies
from scripts.navigation.backfill_channel_water_body_matches import backfill_channel_water_body_matches


SeedStep = Callable[[], Awaitable[Any]]


async def _seed_analysis_definitions() -> None:
    async with AsyncSessionLocal() as session:
        await seed_analysis_job_definitions(session)
        await session.commit()


async def _reset_navigation_revier_production_payload() -> None:
    async with AsyncSessionLocal() as session:
        await delete_existing_revier_graph_payload(session)
        await session.commit()


PRODUCTION_SEED_STEPS: tuple[tuple[str, SeedStep], ...] = (
    ("builtin_dicts", seed_builtin_dicts),
    ("code_sequences", seed_code_sequences),
    ("admin_regions", seed_admin_regions),
    ("navigation_revier_production_reset", _reset_navigation_revier_production_payload),
    ("navigation_channels", seed_navigation_channels),
    ("navigation_water_areas", seed_navigation_water_areas),
    ("navigation_water_bodies", build_navigation_water_bodies),
    ("navigation_water_body_matches", backfill_channel_water_body_matches),
    ("navigation_constraints", seed_navigation_constraints),
    ("commodity_taxonomy", seed_commodity_taxonomy),
    ("commodity_standards", seed_commodity_standards),
    ("business_regions", seed_business_regions),
    ("transport_nodes", seed_transport_nodes),
    ("navigation_revier_production", seed_navigation_revier_production),
    ("production_vessels", seed_production_vessels),
    ("production_freights", seed_production_freights),
    ("analysis_definitions", _seed_analysis_definitions),
)


async def seed_production_preset() -> None:
    validate_seed_manifest()
    for _, step in PRODUCTION_SEED_STEPS:
        await step()
    await seed_system_base(preserve_existing_config_values=True)
    await seed_approval_base()
    await refresh_postgis_geometry_columns()


if __name__ == "__main__":
    asyncio.run(seed_production_preset())
