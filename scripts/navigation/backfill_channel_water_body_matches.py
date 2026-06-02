"""Backfill channel-water-body matches from legacy channel-water-area matches."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import (
    NavigationChannelWaterAreaMatch,
    NavigationChannelWaterBodyMatch,
    NavigationWaterBody,
    NavigationWaterBodyFeatureLink,
)
from app.models.address import NavigationChannel


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "data_audit" / "navigation_channel_water_body_match_backfill_report.json"
PRODUCTION_BODY_ROLES = {"PRIMARY_HIERARCHY", "RX_FILL_GAP"}


@dataclass(slots=True)
class BackfillReport:
    legacy_match_count: int = 0
    eligible_pair_count: int = 0
    existing_match_count: int = 0
    created_match_count: int = 0
    direct_name_candidate_count: int = 0
    direct_name_created_count: int = 0
    skipped_non_production_body_count: int = 0


def _norm(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    for token in (" ", "\t", "\n", "—", "-", "_", "（", "）", "(", ")", "/", "·"):
        text = text.replace(token, "")
    return text


def _channel_terms(channel: NavigationChannel) -> set[str]:
    terms: set[str] = set()
    for value in (
        channel.channel_name,
        channel.official_name,
        channel.display_name,
        *(channel.alias_names or []),
    ):
        normalized = _norm(value)
        if normalized:
            terms.add(normalized)
    return terms


def _water_body_terms(water_body: NavigationWaterBody) -> set[str]:
    terms: set[str] = set()
    for value in (
        water_body.normalized_water_name,
        water_body.water_body_name,
        water_body.display_name,
        water_body.production_name,
    ):
        normalized = _norm(value)
        if normalized:
            terms.add(normalized)
    return terms


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
            existing.add((channel_id, water_body_id))

        direct_terms_by_channel: dict[int, set[str]] = {}
        channels_by_term: dict[str, list[NavigationChannel]] = defaultdict(list)
        channels = list(
            (
                await session.execute(
                    select(NavigationChannel).where(NavigationChannel.is_enabled.is_(True))
                )
            ).scalars()
        )
        for channel in channels:
            terms = _channel_terms(channel)
            if not terms:
                continue
            direct_terms_by_channel[int(channel.id)] = terms
            for term in terms:
                channels_by_term[term].append(channel)

        all_terms = sorted(channels_by_term)
        if all_terms:
            water_bodies = list(
                (
                    await session.execute(
                        select(NavigationWaterBody).where(
                            NavigationWaterBody.is_enabled.is_(True),
                            NavigationWaterBody.body_role_code.in_(PRODUCTION_BODY_ROLES),
                            or_(
                                NavigationWaterBody.normalized_water_name.in_(all_terms),
                                NavigationWaterBody.water_body_name.in_(all_terms),
                                NavigationWaterBody.display_name.in_(all_terms),
                                NavigationWaterBody.production_name.in_(all_terms),
                            ),
                        )
                    )
                ).scalars()
            )
        else:
            water_bodies = []

        for water_body in water_bodies:
            body_terms = _water_body_terms(water_body)
            if not body_terms:
                continue
            matched_channels: dict[int, tuple[NavigationChannel, str]] = {}
            for term in body_terms:
                for channel in channels_by_term.get(term, []):
                    matched_channels.setdefault(int(channel.id), (channel, term))
            for channel_id, (channel, matched_term) in matched_channels.items():
                key = (channel_id, int(water_body.id))
                report.direct_name_candidate_count += 1
                if key in existing:
                    continue
                session.add(
                    NavigationChannelWaterBodyMatch(
                        channel_id=channel_id,
                        water_body_id=int(water_body.id),
                        match_batch_code="DIRECT-NAME",
                        match_type_code="DIRECT_EXACT_NAME",
                        matched_term=matched_term,
                        score=100,
                        confidence_code="HIGH_CONFIDENCE",
                        issue_codes=[],
                        is_current=True,
                        source_water_area_ids_json=water_body.source_water_area_ids_json or [],
                        source_trace_json={
                            "source": "backfill_channel_water_body_matches",
                            "match_rule": "direct_exact_channel_water_body_name",
                            "channel_code": channel.channel_code,
                            "water_body_code": water_body.water_body_code,
                        },
                    )
                )
                report.direct_name_created_count += 1
                existing.add(key)

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
