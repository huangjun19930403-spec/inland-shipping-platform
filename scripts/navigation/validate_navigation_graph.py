"""CLI wrapper for navigation graph validation."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.core.database import AsyncSessionLocal
from app.modules.navigation.services.graph_validation_service import (
    GraphValidationIssue,
    GraphValidationReport,
    validate_navigation_graph,
)

__all__ = ["GraphValidationIssue", "GraphValidationReport", "validate_navigation_graph"]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a navigation graph version.")
    parser.add_argument("--graph-version-id", type=int, default=None)
    parser.add_argument("--version-code", default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--no-update", action="store_true")
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    async with AsyncSessionLocal() as session:
        report = await validate_navigation_graph(
            session=session,
            graph_version_id=args.graph_version_id,
            version_code=args.version_code,
            update_version=not args.no_update,
        )
    payload = report.as_dict()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
