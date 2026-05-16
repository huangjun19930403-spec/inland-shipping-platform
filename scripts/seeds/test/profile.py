"""Automated-test seed profile entrypoint."""

from __future__ import annotations

import app.models  # noqa: F401
from app.core.database import engine
from app.models.base import Base


async def ensure_test_schema() -> None:
    """Create missing tables for an isolated test database."""

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def seed_test_fixtures() -> None:
    """Seed the stable base layer used by automated tests.

    This profile starts from production presets and appends only TEST_* fixtures.
    """

    from scripts.seeds.production import seed_production_preset
    from scripts.seeds.test.fixtures import seed_test_fixture_overlay

    await ensure_test_schema()
    await seed_production_preset()
    await seed_test_fixture_overlay()
