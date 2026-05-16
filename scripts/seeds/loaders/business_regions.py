"""Seed curated production business regions."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.address import AdminRegion, Region, RegionBoundaryVersion, RegionCityRelation


BUSINESS_REGION_FILE = (
    Path(__file__).resolve().parents[2]
    / "seed_data"
    / "address"
    / "business_regions.json"
)


def _load_json(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _center_from_bbox(bbox: list[float] | None) -> tuple[Decimal | None, Decimal | None]:
    if not bbox or len(bbox) != 4:
        return None, None
    min_lng, min_lat, max_lng, max_lat = bbox
    return _decimal((min_lng + max_lng) / 2), _decimal((min_lat + max_lat) / 2)


async def seed_business_regions() -> None:
    rows = _load_json(BUSINESS_REGION_FILE)
    if not rows:
        return

    async with AsyncSessionLocal() as session:
        city_codes = sorted(
            {
                str(code)
                for row in rows
                for code in row.get("city_region_codes", [])
                if str(code or "").strip()
            }
        )
        cities = (
            await session.execute(select(AdminRegion).where(AdminRegion.code.in_(city_codes)))
        ).scalars().all()
        city_by_code = {city.code: city for city in cities}

        missing_city_codes = sorted(set(city_codes) - set(city_by_code))
        if missing_city_codes:
            raise RuntimeError(
                "business region seed references missing admin regions: "
                + ", ".join(missing_city_codes)
            )

        for index, row in enumerate(rows, start=1):
            code = str(row.get("code") or "").strip()
            if not code:
                continue
            entity = await session.scalar(select(Region).where(Region.code == code))
            payload = {
                "code": code,
                "name": row.get("name") or code,
                "short_name": row.get("short_name"),
                "region_type_code": row.get("region_type_code") or "SHIPPING_ANALYSIS_REGION",
                "description": row.get("description"),
                "sort_order": int(row.get("sort_order") or index),
                "status": int(row.get("status") or 1),
            }
            if entity is None:
                entity = Region(**payload)
                session.add(entity)
            else:
                for key, value in payload.items():
                    setattr(entity, key, value)
                entity.deleted_at = None
            entity.audit_status = "APPROVED"
            entity.audited_at = datetime.utcnow()
            await session.flush()

            boundary = await session.scalar(
                select(RegionBoundaryVersion).where(
                    RegionBoundaryVersion.region_id == entity.id,
                    RegionBoundaryVersion.version_no == 1,
                )
            )
            center_lng, center_lat = _center_from_bbox(row.get("bbox"))
            boundary_payload = {
                "boundary_source_type_code": row.get("boundary_source_type_code") or "PLATFORM_DEFINED",
                "geometry_json": row.get("geometry_json") or {},
                "center_longitude": center_lng,
                "center_latitude": center_lat,
                "area_km2": _decimal(0),
                "is_current": True,
                "approved_by": None,
                "approved_at": datetime.utcnow(),
                "remark": "Round 4 production curated business region boundary.",
            }
            if boundary is None:
                boundary = RegionBoundaryVersion(
                    region_id=entity.id,
                    version_no=1,
                    **boundary_payload,
                )
                session.add(boundary)
            else:
                for key, value in boundary_payload.items():
                    setattr(boundary, key, value)
            await session.flush()
            entity.current_boundary_version_id = boundary.id

            await session.execute(
                delete(RegionCityRelation).where(RegionCityRelation.region_id == entity.id)
            )
            for relation_index, city_code in enumerate(row.get("city_region_codes", []), start=1):
                city = city_by_code[str(city_code)]
                session.add(
                    RegionCityRelation(
                        region_id=entity.id,
                        city_region_id=city.id,
                        relation_type_code="INCLUDED",
                        is_primary=relation_index == 1,
                        sort_order=relation_index,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                    )
                )
        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_business_regions())
