"""Seed curated production TMS historical freights."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.address import Region, TransportNode
from app.models.commodity import CommodityStandard
from app.models.freight import Freight


TMS_FREIGHT_FILE = (
    Path(__file__).resolve().parents[2]
    / "seed_data"
    / "freight"
    / "tms_freights.json"
)


def _load_json(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _datetime(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value))


async def seed_production_freights() -> None:
    rows = _load_json(TMS_FREIGHT_FILE)
    if not rows:
        return

    async with AsyncSessionLocal() as session:
        commodity_codes = sorted({str(row["commodity_standard_code"]) for row in rows})
        node_codes = sorted(
            {
                str(row[key])
                for row in rows
                for key in ("origin_node_code", "destination_node_code")
            }
        )
        region_codes = sorted(
            {
                str(row[key])
                for row in rows
                for key in ("origin_region_code", "destination_region_code")
            }
        )

        standards = (
            await session.execute(
                select(CommodityStandard).where(CommodityStandard.code.in_(commodity_codes))
            )
        ).scalars().all()
        nodes = (
            await session.execute(select(TransportNode).where(TransportNode.code.in_(node_codes)))
        ).scalars().all()
        regions = (
            await session.execute(select(Region).where(Region.code.in_(region_codes)))
        ).scalars().all()

        standard_by_code = {row.code: row for row in standards}
        node_by_code = {row.code: row for row in nodes}
        region_by_code = {row.code: row for row in regions}

        missing_standards = sorted(set(commodity_codes) - set(standard_by_code))
        missing_nodes = sorted(set(node_codes) - set(node_by_code))
        missing_regions = sorted(set(region_codes) - set(region_by_code))
        missing_messages = []
        if missing_standards:
            missing_messages.append("commodity standards: " + ", ".join(missing_standards[:20]))
        if missing_nodes:
            missing_messages.append("nodes: " + ", ".join(missing_nodes[:20]))
        if missing_regions:
            missing_messages.append("regions: " + ", ".join(missing_regions[:20]))
        if missing_messages:
            raise RuntimeError("freight seed references missing data: " + "; ".join(missing_messages))

        for row in rows:
            freight_no = str(row.get("freight_no") or "").strip()
            if not freight_no:
                continue
            origin_node = node_by_code[str(row["origin_node_code"])]
            destination_node = node_by_code[str(row["destination_node_code"])]
            entity = await session.scalar(select(Freight).where(Freight.freight_no == freight_no))
            payload = {
                "freight_no": freight_no,
                "source_type_code": row.get("source_type_code") or "TMS",
                "source_channel_code": row.get("source_channel_code") or "TMS_API",
                "source_ref_no": row.get("source_ref_no"),
                "source_batch_id": None,
                "source_tms_inbound_id": None,
                "source_clue_id": None,
                "source_candidate_id": None,
                "raw_commodity_name": row.get("raw_commodity_name"),
                "raw_tonnage_text": row.get("raw_tonnage_text"),
                "raw_origin_text": row.get("raw_origin_text"),
                "raw_destination_text": row.get("raw_destination_text"),
                "cargo_title": row.get("cargo_title") or freight_no,
                "cargo_description": row.get("cargo_description"),
                "commodity_standard_id": standard_by_code[str(row["commodity_standard_code"])].id,
                "commodity_match_level_code": row.get("commodity_match_level_code") or "STANDARD",
                "packaging_form_code": row.get("packaging_form_code"),
                "estimated_tonnage": _decimal(row.get("estimated_tonnage")),
                "min_tonnage": _decimal(row.get("min_tonnage")),
                "max_tonnage": _decimal(row.get("max_tonnage")),
                "unit_price": _decimal(row.get("unit_price")),
                "total_price": _decimal(row.get("total_price")),
                "price_unit": row.get("price_unit"),
                "settlement_method_code": row.get("settlement_method_code"),
                "origin_node_id": origin_node.id,
                "destination_node_id": destination_node.id,
                "origin_match_level_code": row.get("origin_match_level_code") or "NODE",
                "destination_match_level_code": row.get("destination_match_level_code") or "NODE",
                "origin_province_code": row.get("origin_province_code"),
                "origin_city_code": row.get("origin_city_code"),
                "origin_district_code": row.get("origin_district_code"),
                "destination_province_code": row.get("destination_province_code"),
                "destination_city_code": row.get("destination_city_code"),
                "destination_district_code": row.get("destination_district_code"),
                "origin_region_id_cache": region_by_code[str(row["origin_region_code"])].id,
                "destination_region_id_cache": region_by_code[str(row["destination_region_code"])].id,
                "loading_time_from": _datetime(row.get("loading_time_from")),
                "loading_time_to": _datetime(row.get("loading_time_to")),
                "unloading_time_from": _datetime(row.get("unloading_time_from")),
                "unloading_time_to": _datetime(row.get("unloading_time_to")),
                "publisher_org_name": row.get("publisher_org_name"),
                "status_code": row.get("status_code") or "CLOSED",
                "published_at": _datetime(row.get("published_at")),
                "expired_at": _datetime(row.get("expired_at")),
                "confirmed_at": _datetime(row.get("confirmed_at")),
                "confirmed_by": None,
                "hall_status_code": row.get("hall_status_code") or "NOT_LISTED",
                "hall_published_at": _datetime(row.get("hall_published_at")),
                "hall_unpublished_at": _datetime(row.get("hall_unpublished_at")),
                "hall_visible_until": _datetime(row.get("hall_visible_until")),
            }
            if entity is None:
                entity = Freight(**payload)
                session.add(entity)
            else:
                for key, value in payload.items():
                    setattr(entity, key, value)
                entity.deleted_at = None
            entity.audit_status = "APPROVED"
            entity.audited_at = datetime.utcnow()
        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_production_freights())
