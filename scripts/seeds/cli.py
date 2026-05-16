"""Unified seed profile CLI."""

from __future__ import annotations

import argparse
import asyncio

from scripts.seeds.profiles import (
    SUPPORTED_SEED_PROFILES,
    resolve_seed_profile,
    seed_system_init,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an explicit seed profile")
    parser.add_argument("--profile", choices=sorted(SUPPORTED_SEED_PROFILES))
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(seed_system_init(profile=args.profile))
