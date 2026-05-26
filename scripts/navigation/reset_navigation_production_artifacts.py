"""Reset navigation production artifacts and reload channel seed.

This script deliberately limits itself to navigation map production tables:
drafts, centerlines, graph versions, route validation records, and navigation
channel base records. It does not touch users, roles, permissions, system
configuration, AI providers, API keys, or map provider keys.
"""

from __future__ import annotations

import asyncio
import argparse

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models import (
    NavigationAnnotationTask,
    NavigationCenterlineSegment,
    NavigationChannelCenterline,
    NavigationGeometryDraft,
    NavigationGraphEdge,
    NavigationGraphEdgeConstraint,
    NavigationGraphNode,
    NavigationGraphVersion,
    NavigationRouteQualityIssue,
    NavigationRouteRequest,
    NavigationRouteResult,
)
from app.models.address import NavigationChannel, NavigationChannelBoundary, NavigationChannelSegment
from scripts.seeds.loaders.navigation_channels import (
    _normalize_boundary_numeric_fields,
    _parse_datetime,
    _segment_payload_with_guide,
    load_navigation_channel_seed,
)


async def reset_navigation_production_artifacts(channel_codes: set[str] | None = None) -> dict[str, int]:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(NavigationRouteQualityIssue))
        await session.execute(delete(NavigationRouteResult))
        await session.execute(delete(NavigationRouteRequest))
        await session.execute(delete(NavigationAnnotationTask))
        await session.execute(delete(NavigationGraphEdgeConstraint))
        await session.execute(delete(NavigationGraphEdge))
        await session.execute(delete(NavigationGraphNode))
        await session.execute(delete(NavigationGraphVersion))
        await session.execute(delete(NavigationCenterlineSegment))
        await session.execute(delete(NavigationChannelCenterline))
        await session.execute(delete(NavigationGeometryDraft))
        await session.commit()

    return await _reload_current_boundaries_and_guides_from_seed(channel_codes=channel_codes)


async def _reload_current_boundaries_and_guides_from_seed(channel_codes: set[str] | None = None) -> dict[str, int]:
    payload = load_navigation_channel_seed()
    records = [
        record
        for record in payload["records"]
        if not channel_codes or record["channel"]["channel_code"] in channel_codes
    ]
    boundary_count = 0
    segment_count = 0
    async with AsyncSessionLocal() as session:
        for record in records:
            channel_payload = dict(record["channel"])
            channel = (
                await session.execute(
                    select(NavigationChannel).where(NavigationChannel.channel_code == channel_payload["channel_code"])
                )
            ).scalar_one_or_none()
            if channel is None:
                channel = NavigationChannel(**channel_payload)
                session.add(channel)
                await session.flush()
            else:
                for key, value in channel_payload.items():
                    setattr(channel, key, value)

            previous_current = list(
                (
                    await session.execute(
                        select(NavigationChannelBoundary).where(
                            NavigationChannelBoundary.channel_id == channel.id,
                            NavigationChannelBoundary.is_current.is_(True),
                        )
                    )
                ).scalars()
            )
            previous_ids = [int(item.id) for item in previous_current]
            for item in previous_current:
                item.is_current = False

            boundary_payload = dict(record["boundary"])
            boundary_payload["imported_at"] = _parse_datetime(boundary_payload.get("imported_at"))
            boundary_payload = _normalize_boundary_numeric_fields(boundary_payload)
            boundary_payload["boundary_quality_code"] = "MANUAL_PUBLISHED"
            trace = dict(boundary_payload.get("source_trace_json") or {})
            trace.update(
                {
                    "source": "navigation_production_seed_reset",
                    "previous_boundary_ids": previous_ids,
                    "caused_downstream_stale": True,
                    "no_sensitive_config_modified": True,
                }
            )
            boundary_payload["source_trace_json"] = trace
            boundary_payload["is_current"] = True
            session.add(NavigationChannelBoundary(channel_id=channel.id, **boundary_payload))
            boundary_count += 1

            for raw_segment in record["segments"]:
                segment_payload = _segment_payload_with_guide(raw_segment, boundary_payload)
                segment = (
                    await session.execute(
                        select(NavigationChannelSegment).where(
                            NavigationChannelSegment.channel_id == channel.id,
                            NavigationChannelSegment.segment_code == segment_payload["segment_code"],
                        )
                    )
                ).scalar_one_or_none()
                if segment is None:
                    session.add(NavigationChannelSegment(channel_id=channel.id, **segment_payload))
                else:
                    for key, value in segment_payload.items():
                        setattr(segment, key, value)
                segment_count += 1

        await session.commit()
    return {
        "channels": len(records),
        "new_current_boundaries": boundary_count,
        "segments_upserted": segment_count,
    }


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Reset navigation production artifacts and reload selected channel seed.")
    parser.add_argument(
        "--channel-code",
        action="append",
        default=[],
        help="Navigation channel code to reload. May be passed more than once. Omit to reload all channels.",
    )
    args = parser.parse_args()
    channel_codes = set(args.channel_code) if args.channel_code else None
    result = await reset_navigation_production_artifacts(channel_codes=channel_codes)
    print(result)


if __name__ == "__main__":
    asyncio.run(_main())
