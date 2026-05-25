"""Backfill channel-water-body matches from legacy channel-water-area matches."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import (
    NavigationChannelWaterAreaMatch,
    NavigationChannelWaterBodyMatch,
    NavigationWaterBody,
    NavigationWaterBodyFeatureLink,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "data_audit" / "navigation_channel_water_body_match_backfill_report.json"
PRODUCTION_BODY_ROLES = {"PRIMARY_HIERARCHY", "RX_FILL_GAP"}


@dataclass(slots=True)
class BackfillReport:
    legacy_match_count: int = 0
    eligible_pair_count: int = 0
    existing_match_count: int = 0
    created_match_count: int = 0
    skipped_non_production_body_count: int = 0


async def backfill_channel_water_body_matches(
    *,
    output_path: Path | None = DEFAULT_OUTPUT,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    owns_session = session is None
    if session is None:
        session = AsyncSessionLocal()
    try:
        report = BackfillReport()
        rows = list(
            (
                await session.execute(
                    select(NavigationChannelWaterAreaMatch, NavigationWaterBodyFeatureLink, NavigationWaterBody)
                    .join(
                        NavigationWaterBodyFeatureLink,
                        NavigationWaterBodyFeatureLink.water_area_id == NavigationChannelWaterAreaMatch.water_area_id,
                    )
                    .join(NavigationWaterBody, NavigationWaterBody.id == NavigationWaterBodyFeatureLink.water_body_id)
                    .where(NavigationChannelWaterAreaMatch.is_current.is_(True))
                )
            ).all()
        )
        report.legacy_match_count = len(rows)
        grouped: dict[tuple[int, int], dict[str, Any]] = {}
        for legacy_match, link, water_body in rows:
            if water_body.body_role_code not in PRODUCTION_BODY_ROLES or not water_body.is_enabled:
                report.skipped_non_production_body_count += 1
                continue
            key = (int(legacy_match.channel_id), int(water_body.id))
            item = grouped.setdefault(
                key,
                {
                    "best": legacy_match,
                    "water_body": water_body,
                    "water_area_ids": set(),
                    "issue_codes": set(),
                },
            )
            item["water_area_ids"].add(int(link.water_area_id))
            item["issue_codes"].update(legacy_match.issue_codes or [])
            if int(legacy_match.score or 0) > int(item["best"].score or 0):
                item["best"] = legacy_match

        report.eligible_pair_count = len(grouped)
        existing_rows = list(
            (
                await session.execute(
                    select(NavigationChannelWaterBodyMatch.channel_id, NavigationChannelWaterBodyMatch.water_body_id)
                    .where(NavigationChannelWaterBodyMatch.is_current.is_(True))
                )
            ).all()
        )
        existing = {(int(channel_id), int(water_body_id)) for channel_id, water_body_id in existing_rows}
        report.existing_match_count = len(existing)

        for (channel_id, water_body_id), item in grouped.items():
            if (channel_id, water_body_id) in existing:
                continue
            best: NavigationChannelWaterAreaMatch = item["best"]
            water_body: NavigationWaterBody = item["water_body"]
            water_area_ids = sorted(item["water_area_ids"])
            session.add(
                NavigationChannelWaterBodyMatch(
                    channel_id=channel_id,
                    water_body_id=water_body_id,
                    match_batch_code="BACKFILL-FROM-WATER-AREA",
                    match_type_code=f"BACKFILL_{best.match_type_code}",
                    matched_term=best.matched_term or water_body.production_name or water_body.display_name or water_body.water_body_name,
                    score=int(best.score or 0),
                    confidence_code=best.confidence_code,
                    issue_codes=sorted(item["issue_codes"]),
                    is_current=True,
                    source_water_area_ids_json=water_area_ids,
                    source_trace_json={
                        "source": "backfill_channel_water_body_matches",
                        "legacy_match_id": int(best.id),
                        "legacy_water_area_id": int(best.water_area_id),
                        "source_water_area_ids": water_area_ids[:100],
                    },
                )
            )
            report.created_match_count += 1

        if owns_session:
            await session.commit()
        else:
            await session.flush()
        result = asdict(report)
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    finally:
        if owns_session:
            await session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill channel-water-body matches from legacy area matches.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(backfill_channel_water_body_matches(output_path=args.output)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
