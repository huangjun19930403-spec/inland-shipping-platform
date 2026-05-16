"""Explicit seed profile dispatcher."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from contextlib import contextmanager


SeedRunner = Callable[[], Awaitable[None]]

SUPPORTED_SEED_PROFILES = {"production", "demo", "local-demo", "test"}
PROFILE_ALIASES = {
    "demo": "local-demo",
}


async def _run_production_seed() -> None:
    from scripts.seeds.production import seed_production_preset

    await seed_production_preset()


async def _run_demo_seed() -> None:
    from scripts.seeds.demo import seed_demo

    await seed_demo()


async def _run_test_seed() -> None:
    from scripts.seeds.test.profile import seed_test_fixtures

    await seed_test_fixtures()


PROFILE_RUNNERS: dict[str, SeedRunner] = {
    "production": _run_production_seed,
    "local-demo": _run_demo_seed,
    "test": _run_test_seed,
}


@contextmanager
def _seed_profile_env(profile: str):
    previous = os.environ.get("SEED_PROFILE")
    os.environ["SEED_PROFILE"] = profile
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("SEED_PROFILE", None)
        else:
            os.environ["SEED_PROFILE"] = previous


def resolve_seed_profile(profile: str | None = None) -> str:
    profile_clean = (profile or os.getenv("SEED_PROFILE") or "").strip().lower()
    profile_clean = PROFILE_ALIASES.get(profile_clean, profile_clean)
    if profile_clean not in PROFILE_RUNNERS:
        raise RuntimeError(
            "SEED_PROFILE must be set explicitly to production, demo, local-demo or test"
        )
    return profile_clean


async def seed_system_init(*, profile: str | None = None) -> None:
    profile_clean = resolve_seed_profile(profile)
    with _seed_profile_env(profile_clean):
        await PROFILE_RUNNERS[profile_clean]()
