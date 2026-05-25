"""Seed final navigation channel base data.

The seed is intentionally self-contained: it reads curated JSON result data and
does not read revier.zip or any long-running cleaning source at runtime.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from datetime import timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from sqlalchemy import delete, text

from app.core.database import AsyncSessionLocal, engine
from app.models import NavigationChannelWaterAreaMatch
from app.models.address import (
    NavigationChannel,
    NavigationChannelBoundary,
    NavigationChannelSegment,
    NavigationChannelSourceAudit,
)
from app.models.base import Base

PROJECT_ROOT = Path(__file__).resolve().parents[3]
NAVIGATION_CHANNEL_DATA_FILE = PROJECT_ROOT / "scripts" / "seed_data" / "navigation" / "navigation_channels.json"
COORDINATE_SCALE = Decimal("0.000000000000001")
DEGREE_MEASURE_SCALE = Decimal("0.000000000000000001")


def load_navigation_channel_seed(path: Path = NAVIGATION_CHANNEL_DATA_FILE) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


_NAVIGATION_METADATA = load_navigation_channel_seed()
DATA_VERSION = str(_NAVIGATION_METADATA["data_version"])
CHANNEL_COUNT = int(_NAVIGATION_METADATA["metadata"]["channel_count"])
BOUNDARY_COUNT = int(_NAVIGATION_METADATA["metadata"]["boundary_count"])
SEGMENT_COUNT = int(_NAVIGATION_METADATA["metadata"]["segment_count"])
SOURCE_AUDIT_COUNT = int(_NAVIGATION_METADATA["metadata"]["source_audit_count"])
EXCLUDED_TOP_LEVEL_NATURAL_WATER_AREA_COUNT = int(
    _NAVIGATION_METADATA["metadata"]["excluded_top_level_natural_water_area_count"]
)
CHANNEL_TYPE_COUNTS = dict(_NAVIGATION_METADATA["metadata"]["channel_type_counts"])
PLANNING_LEVEL_COUNTS = dict(_NAVIGATION_METADATA["metadata"]["planning_level_counts"])
BOUNDARY_STATUS_COUNTS = dict(_NAVIGATION_METADATA["metadata"]["boundary_status_counts"])
LABELS = dict(_NAVIGATION_METADATA["metadata"]["labels"])


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _quantize_decimal(value: Any, scale: Decimal) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value)).quantize(scale, rounding=ROUND_HALF_UP)


def _normalize_boundary_numeric_fields(payload: dict[str, Any]) -> dict[str, Any]:
    for field in (
        "center_longitude",
        "center_latitude",
        "display_center_longitude",
        "display_center_latitude",
        "bbox_min_lng",
        "bbox_min_lat",
        "bbox_max_lng",
        "bbox_max_lat",
    ):
        payload[field] = _quantize_decimal(payload.get(field), COORDINATE_SCALE)
    for field in ("source_shape_length_degree", "source_shape_area_degree"):
        payload[field] = _quantize_decimal(payload.get(field), DEGREE_MEASURE_SCALE)
    return payload


async def _prepare_schema(drop_legacy: bool) -> None:
    async with engine.begin() as conn:
        if drop_legacy:
            await _drop_legacy_table_if_exists(conn, "water_system_boundary")
            await _drop_legacy_table_if_exists(conn, "water_system")
        await conn.run_sync(Base.metadata.create_all)


async def _drop_legacy_table_if_exists(conn: Any, table_name: str) -> None:
    if conn.dialect.name == "mysql":
        exists = await conn.scalar(
            text(
                """
                SELECT COUNT(*)
                  FROM information_schema.tables
                 WHERE table_schema = DATABASE()
                   AND table_name = :table_name
                """
            ),
            {"table_name": table_name},
        )
        if not exists:
            return
        await conn.execute(text(f"DROP TABLE `{table_name}`"))
        return

    await conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))


async def seed_navigation_channels(*, drop_legacy: bool = True) -> dict[str, int]:
    await _prepare_schema(drop_legacy)
    payload = load_navigation_channel_seed()
    records = payload["records"]
    excluded_source_audit = payload["excluded_source_audit"]

    async with AsyncSessionLocal() as session:
        await session.execute(delete(NavigationChannelSourceAudit))
        await session.execute(delete(NavigationChannelWaterAreaMatch))
        await session.execute(delete(NavigationChannelSegment))
        await session.execute(delete(NavigationChannelBoundary))
        await session.execute(delete(NavigationChannel))
        await session.flush()

        channel_by_code: dict[str, NavigationChannel] = {}
        segment_by_code: dict[str, NavigationChannelSegment] = {}

        for record in records:
            channel = NavigationChannel(**record["channel"])
            session.add(channel)
            await session.flush()
            channel_by_code[channel.channel_code] = channel

            boundary_payload = dict(record["boundary"])
            boundary_payload["imported_at"] = _parse_datetime(boundary_payload.get("imported_at"))
            boundary_payload = _normalize_boundary_numeric_fields(boundary_payload)
            session.add(NavigationChannelBoundary(channel_id=channel.id, **boundary_payload))

            for segment_payload in record["segments"]:
                segment = NavigationChannelSegment(channel_id=channel.id, **segment_payload)
                session.add(segment)
                await session.flush()
                segment_by_code[segment.segment_code] = segment

        await session.flush()

        for record in records:
            channel = channel_by_code[record["channel"]["channel_code"]]
            for audit_payload in record["source_audit"]:
                payload_for_db = dict(audit_payload)
                payload_for_db.setdefault("channel_code", channel.channel_code)
                segment_code = payload_for_db.get("segment_code")
                segment = segment_by_code.get(segment_code) if segment_code else None
                session.add(
                    NavigationChannelSourceAudit(
                        channel_id=channel.id,
                        segment_id=segment.id if segment else None,
                        **payload_for_db,
                    )
                )

        for audit_payload in excluded_source_audit:
            session.add(NavigationChannelSourceAudit(**audit_payload))

        await session.commit()

    return {
        "version": DATA_VERSION,
        "channels": len(records),
        "boundaries": sum(1 for item in records if item["boundary"]["geometry_status_code"] == "AVAILABLE"),
        "segments": sum(len(item["segments"]) for item in records),
        "source_audits": sum(len(item["source_audit"]) for item in records) + len(excluded_source_audit),
    }


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Seed final navigation channel base data.")
    parser.add_argument(
        "--keep-legacy",
        action="store_true",
        help="Keep legacy water_system tables if they still exist.",
    )
    args = parser.parse_args()
    result = await seed_navigation_channels(drop_legacy=not args.keep_legacy)
    print(result)


if __name__ == "__main__":
    asyncio.run(_main())
