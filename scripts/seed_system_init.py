"""Explicit seed profile wrapper."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.seed_local_demo import seed_local_demo
from scripts.seed_production_preset import seed_production_preset

SUPPORTED_SEED_PROFILES = {"production", "local-demo"}


def resolve_seed_profile(profile: str | None = None) -> str:
    profile_clean = (profile or os.getenv("SEED_PROFILE") or "").strip().lower()
    if profile_clean not in SUPPORTED_SEED_PROFILES:
        raise RuntimeError(
            "SEED_PROFILE must be set explicitly to production or local-demo"
        )
    return profile_clean


async def seed_system_init(*, profile: str | None = None) -> None:
    profile_clean = resolve_seed_profile(profile)
    if profile_clean == "production":
        await seed_production_preset()
        return
    if profile_clean == "local-demo":
        await seed_local_demo()
        return
    raise RuntimeError(f"unsupported SEED_PROFILE: {profile_clean}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an explicit seed profile")
    parser.add_argument("--profile", choices=sorted(SUPPORTED_SEED_PROFILES))
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(seed_system_init(profile=args.profile))
