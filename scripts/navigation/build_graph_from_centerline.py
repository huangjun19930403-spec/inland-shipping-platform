"""CLI wrapper for navigation graph building."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.core.database import AsyncSessionLocal, engine
from app.models.base import Base
from app.modules.navigation.services.graph_build_service import (
    GraphBuildConfig,
    GraphBuildIssue,
    GraphBuildSummary,
    build_graph_from_centerlines,
)

__all__ = [
    "GraphBuildConfig",
    "GraphBuildIssue",
    "GraphBuildSummary",
    "build_graph_from_centerlines",
]


async def _prepare_schema() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build navigation graph from published centerlines.")
    parser.add_argument("--version-code", required=True)
    parser.add_argument("--version-name", default=None)
    parser.add_argument("--scope-code", default="REAL-JS-YRD")
    parser.add_argument("--channel-code", action="append", dest="channel_codes")
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    await _prepare_schema()
    async with AsyncSessionLocal() as session:
        summary = await build_graph_from_centerlines(
            session=session,
            version_code=args.version_code,
            version_name=args.version_name,
            scope_code=args.scope_code,
            channel_codes=args.channel_codes,
            activate=args.activate,
        )
    payload = summary.as_dict()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
