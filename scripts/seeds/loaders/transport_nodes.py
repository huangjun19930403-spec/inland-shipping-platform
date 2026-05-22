"""Seed curated production transport nodes."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.address import (
    AdminRegion,
    NodeAlias,
    TransportNode,
    TransportNodeBusinessCategory,
    TransportNodeHandlingMode,
    TransportNodePackagingForm,
    TransportNodeProfile,
)


TRANSPORT_NODE_FILE = (
    Path(__file__).resolve().parents[2]
    / "seed_data"
    / "address"
    / "transport_nodes.json"
)


def _load_json(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


async def _replace_code_relations(
    session,
    *,
    node_id: int,
    business_categories: list[str],
    packaging_forms: list[str],
    handling_modes: list[str],
) -> None:
    now = datetime.utcnow()
    await session.execute(
        delete(TransportNodeBusinessCategory).where(
            TransportNodeBusinessCategory.node_id == node_id
        )
    )
    for code in business_categories:
        session.add(
            TransportNodeBusinessCategory(
                node_id=node_id,
                business_category_code=code,
                created_at=now,
            )
        )

    await session.execute(
        delete(TransportNodePackagingForm).where(
            TransportNodePackagingForm.node_id == node_id
        )
    )
    for code in packaging_forms:
        session.add(
            TransportNodePackagingForm(
                node_id=node_id,
                packaging_form_code=code,
                created_at=now,
            )
        )

    await session.execute(
        delete(TransportNodeHandlingMode).where(
            TransportNodeHandlingMode.node_id == node_id
        )
    )
    for code in handling_modes:
        session.add(
            TransportNodeHandlingMode(
                node_id=node_id,
                handling_mode_code=code,
                created_at=now,
            )
        )


async def seed_transport_nodes() -> None:
    rows = _load_json(TRANSPORT_NODE_FILE)
    if not rows:
        return

    async with AsyncSessionLocal() as session:
        city_codes = sorted({str(row["city_region_code"]) for row in rows})
        cities = (
            await session.execute(select(AdminRegion).where(AdminRegion.code.in_(city_codes)))
        ).scalars().all()
        city_by_code = {city.code: city for city in cities}
        missing_city_codes = sorted(set(city_codes) - set(city_by_code))
        if missing_city_codes:
            raise RuntimeError(
                "transport node seed references missing admin regions: "
                + ", ".join(missing_city_codes)
            )

        for index, row in enumerate(rows, start=1):
            code = str(row.get("code") or "").strip()
            if not code:
                continue
            city = city_by_code[str(row["city_region_code"])]
            entity = await session.scalar(select(TransportNode).where(TransportNode.code == code))
            payload = {
                "code": code,
                "name": row.get("name") or code,
                "short_name": row.get("short_name"),
                "node_type_code": row.get("node_type_code") or "OTHER",
                "province_code": row.get("province_code") or city.province_code,
                "city_code": row.get("city_code") or city.code,
                "district_code": row.get("district_code"),
                "city_region_id": city.id,
                "address": row.get("address"),
                "longitude": _decimal(row.get("longitude")),
                "latitude": _decimal(row.get("latitude")),
                "status": int(row.get("status") or 1),
                "lifecycle_status_code": row.get("lifecycle_status_code") or "ACTIVE",
                "sort_order": int(row.get("sort_order") or index),
                "is_hot_node": bool(row.get("is_hot_node", False)),
            }
            if entity is None:
                entity = TransportNode(**payload)
                session.add(entity)
            else:
                for key, value in payload.items():
                    setattr(entity, key, value)
                entity.deleted_at = None
            await session.flush()

            profile = await session.scalar(
                select(TransportNodeProfile).where(TransportNodeProfile.node_id == entity.id)
            )
            profile_payload = {
                "business_nature_code": (row.get("profile") or {}).get("business_nature_code"),
                "channel_depth_m": _decimal((row.get("profile") or {}).get("channel_depth_m")),
                "max_draft_m": _decimal((row.get("profile") or {}).get("max_draft_m")),
                "berth_count": (row.get("profile") or {}).get("berth_count"),
                "annual_throughput_ton": _decimal(
                    (row.get("profile") or {}).get("annual_throughput_ton")
                ),
                "open_hours_desc": (row.get("profile") or {}).get("open_hours_desc"),
                "ext_json": (row.get("profile") or {}).get("ext_json"),
                "updated_at": datetime.utcnow(),
            }
            if profile is None:
                session.add(TransportNodeProfile(node_id=entity.id, **profile_payload))
            else:
                for key, value in profile_payload.items():
                    setattr(profile, key, value)

            await session.execute(
                delete(NodeAlias).where(
                    NodeAlias.node_id == entity.id,
                    NodeAlias.source_type_code == "TMS",
                )
            )
            seen_aliases: set[str] = set()
            for alias in row.get("aliases") or []:
                alias_name = str(alias.get("alias_name") or "").strip()
                normalized = "".join(alias_name.split()).lower()
                if not alias_name or normalized in seen_aliases:
                    continue
                seen_aliases.add(normalized)
                session.add(
                    NodeAlias(
                        node_id=entity.id,
                        alias_name=alias_name,
                        alias_type_code=alias.get("alias_type_code") or "COMMON_ALIAS",
                        source_type_code=alias.get("source_type_code") or "TMS",
                        is_primary=bool(alias.get("is_primary", False)),
                    )
                )

            await _replace_code_relations(
                session,
                node_id=entity.id,
                business_categories=[str(code) for code in row.get("business_categories") or []],
                packaging_forms=[str(code) for code in row.get("packaging_forms") or []],
                handling_modes=[str(code) for code in row.get("handling_modes") or []],
            )
        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_transport_nodes())
