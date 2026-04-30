"""行政区划正式初始化脚本。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.address import AdminRegion, AdminRegionBoundary
from app.modules.address.geometry import normalize_boundary_geometry, normalize_boundary_source_type


ADMIN_REGION_DATA_FILE = (
    Path(__file__).resolve().parent
    / "seed_data"
    / "admin_region"
    / "admin_region_raw.json"
)

ADMIN_REGION_BOUNDARY_FILE = (
    Path(__file__).resolve().parent
    / "seed_data"
    / "admin_region"
    / "admin_region_boundary_city_raw.json"
)


def _load_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _to_status(value) -> int:
    if value is None:
        return 1
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return 1 if value > 0 else 0
    text = str(value).strip().upper()
    if text in {"1", "ACTIVE", "ENABLED", "TRUE", "YES"}:
        return 1
    if text in {"0", "INACTIVE", "DISABLED", "FALSE", "NO"}:
        return 0
    return 1


async def seed_admin_regions() -> None:
    regions = _load_json(ADMIN_REGION_DATA_FILE)
    boundaries = _load_json(ADMIN_REGION_BOUNDARY_FILE)

    level_map = {
        "province": 1,
        "city": 2,
        "district": 3,
        "county": 3,
    }

    async with AsyncSessionLocal() as session:
        id_by_code: dict[str, int] = {}
        for row in regions:
            code = str(row.get("adcode") or row.get("code") or "")
            if not code:
                continue
            existed = await session.scalar(select(AdminRegion).where(AdminRegion.code == code))
            level_raw = row.get("level")
            if isinstance(level_raw, str):
                level_value = level_map.get(level_raw.lower(), 0)
            else:
                try:
                    level_value = int(level_raw or 0)
                except (TypeError, ValueError):
                    level_value = 0

            path_names = row.get("path_names")
            if isinstance(path_names, list):
                full_path = "/".join(str(item) for item in path_names if item)
            else:
                full_path = row.get("full_path")

            short_name = row.get("short_name")
            if short_name is None and row.get("name"):
                short_name = str(row.get("name"))[:32]

            if existed is None:
                existed = AdminRegion(
                    code=code,
                    name=row.get("name") or code,
                    short_name=short_name,
                    pinyin=row.get("pinyin"),
                    level=level_value,
                    parent_code=row.get("parent_code"),
                    full_path=full_path,
                    province_code=row.get("province_code"),
                    city_code=row.get("city_code"),
                    district_code=row.get("county_code") or row.get("district_code"),
                    longitude=row.get("center_lon") or row.get("longitude"),
                    latitude=row.get("center_lat") or row.get("latitude"),
                    center_address=row.get("center_address"),
                    status=_to_status(row.get("status")),
                    sort_order=int(row.get("sort_order") or 0),
                )
                session.add(existed)
                await session.flush()
            id_by_code[code] = existed.id

        for boundary in boundaries:
            code = str(boundary.get("adcode") or boundary.get("code") or "")
            region_id = id_by_code.get(code)
            if region_id is None:
                continue
            version_no = int(boundary.get("version_no") or 1)
            existed_boundary = await session.scalar(
                select(AdminRegionBoundary).where(
                    AdminRegionBoundary.admin_region_id == region_id,
                    AdminRegionBoundary.version_no == version_no,
                )
            )
            geometry_json = boundary.get("geometry_json")
            if geometry_json is None:
                geometry_json = boundary.get("geometry_wkt")
            geometry_json = normalize_boundary_geometry(geometry_json)
            source_type_code = normalize_boundary_source_type(
                boundary.get("source_type_code") or boundary.get("boundary_source_type_code")
            )
            is_current = bool(boundary.get("is_current", True))

            payload = {
                "version_no": version_no,
                "boundary_source_type_code": source_type_code,
                "geometry_json": geometry_json,
                "center_longitude": boundary.get("center_lon") or boundary.get("center_longitude"),
                "center_latitude": boundary.get("center_lat") or boundary.get("center_latitude"),
                "area_km2": boundary.get("area_km2"),
                "is_current": is_current,
                "effective_from": None,
                "effective_to": None,
                "imported_by": None,
                "imported_at": None,
                "remark": boundary.get("remark"),
            }

            if existed_boundary is None:
                existed_boundary = AdminRegionBoundary(
                    admin_region_id=region_id,
                    **payload,
                )
                session.add(existed_boundary)
                await session.flush()
            else:
                for key, value in payload.items():
                    setattr(existed_boundary, key, value)

            if is_current:
                rows = (
                    await session.execute(
                        select(AdminRegionBoundary).where(AdminRegionBoundary.admin_region_id == region_id)
                    )
                ).scalars().all()
                for row in rows:
                    row.is_current = row.id == existed_boundary.id
        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_admin_regions())
