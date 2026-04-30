"""船舶模块本地验证样例 seed。"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.address import AdminRegion, Region
from app.models.ship import (
    ShipCapacity,
    ShipCertificate,
    ShipContact,
    ShipMmsiHistory,
    ShipNameHistory,
    ShipOperation,
    ShipOwner,
    ShipProfile,
)


CITY_NAMES = [
    "南京市",
    "镇江市",
    "扬州市",
    "泰州市",
    "苏州市",
    "无锡市",
    "南通市",
    "杭州市",
    "湖州市",
    "芜湖市",
    "马鞍山市",
    "铜陵市",
    "武汉市",
    "黄石市",
    "岳阳市",
    "九江市",
    "广州市",
    "佛山市",
]

REGION_CODES = [
    "REGION_YANGTZE_DELTA",
    "REGION_WANJIANG",
    "REGION_MIDDLE_YANGTZE",
    "REGION_UPPER_YANGTZE",
    "REGION_PEARL_RIVER",
    "REGION_CANAL_JIANGNAN",
    "REGION_LOWER_YANGTZE_PORTS",
    "REGION_EAST_CHINA_BULK",
]

TYPE_PLAN: list[tuple[str, int]] = [
    ("BULK_CARRIER", 26),
    ("SELF_UNLOADING_BULK", 16),
    ("GENERAL_CARGO_SHIP", 22),
    ("CONTAINER_SHIP", 12),
    ("MULTIPURPOSE", 12),
    ("BARGE", 10),
    ("OIL_TANKER", 8),
    ("CHEMICAL_TANKER", 8),
    ("TUG", 6),
]

TYPE_PROFILE: dict[str, dict[str, Any]] = {
    "BULK_CARRIER": {"short": "散货", "dwt": (1800, 9800), "length": (58, 118), "width": (11, 20), "draft": (2.6, 5.2), "holds": 4},
    "SELF_UNLOADING_BULK": {"short": "自卸", "dwt": (2500, 12000), "length": (68, 128), "width": (12, 22), "draft": (2.8, 5.6), "holds": 5},
    "GENERAL_CARGO_SHIP": {"short": "普货", "dwt": (900, 5200), "length": (45, 92), "width": (9, 17), "draft": (1.8, 4.2), "holds": 3},
    "CONTAINER_SHIP": {"short": "集装箱", "dwt": (2600, 9000), "length": (72, 130), "width": (14, 24), "draft": (2.8, 5.4), "holds": 2},
    "MULTIPURPOSE": {"short": "多用", "dwt": (1600, 7600), "length": (56, 108), "width": (11, 19), "draft": (2.4, 4.9), "holds": 3},
    "BARGE": {"short": "驳", "dwt": (800, 4200), "length": (42, 86), "width": (9, 16), "draft": (1.6, 3.8), "holds": 2, "power": "NON_SELF_PROPELLED"},
    "OIL_TANKER": {"short": "油化", "dwt": (1200, 6200), "length": (52, 105), "width": (10, 18), "draft": (2.2, 4.8), "holds": 4},
    "CHEMICAL_TANKER": {"short": "化学品", "dwt": (1000, 5600), "length": (50, 98), "width": (10, 17), "draft": (2.1, 4.6), "holds": 4},
    "TUG": {"short": "拖", "dwt": (180, 900), "length": (24, 46), "width": (7, 12), "draft": (1.2, 2.8), "holds": 0},
}

NAME_PREFIXES = ["江海", "长航", "皖航", "楚江", "吴越", "运河", "珠航", "三江", "华东", "川江"]
OWNER_NAMES = ["南京江海航运有限公司", "苏南联运船务有限公司", "皖江港航物流有限公司", "湖北长江航运服务有限公司", "珠江内河运输有限公司"]
STATUS_CODES = ["OPERATING", "OPERATING", "OPERATING", "IN_PORT", "MAINTENANCE", "SUSPENDED"]


def _scaled(low: float, high: float, seed: int, step: int) -> Decimal:
    low_i = int(low * 100)
    high_i = int(high * 100)
    value = low_i + ((seed * step * 1000) % max(high_i - low_i, 1))
    return (Decimal(value) / Decimal("100")).quantize(Decimal("0.01"))


def _type_codes() -> list[str]:
    codes: list[str] = []
    for code, count in TYPE_PLAN:
        codes.extend([code] * count)
    return codes


async def _load_cities(session) -> list[AdminRegion]:
    rows = (
        await session.execute(
            select(AdminRegion)
            .where(AdminRegion.name.in_(CITY_NAMES), AdminRegion.level == 2)
            .order_by(AdminRegion.code.asc())
        )
    ).scalars().all()
    return list(rows)


async def _load_regions(session) -> list[Region]:
    rows = (
        await session.execute(
            select(Region)
            .where(Region.code.in_(REGION_CODES), Region.deleted_at.is_(None))
            .order_by(Region.sort_order.asc(), Region.id.asc())
        )
    ).scalars().all()
    return list(rows)


async def _upsert_ship(session, payload: dict[str, Any]) -> ShipProfile:
    ship = await session.scalar(select(ShipProfile).where(ShipProfile.ais_id == payload["ais_id"]))
    if ship is None:
        ship = ShipProfile(**payload)
        session.add(ship)
    else:
        for key, value in payload.items():
            setattr(ship, key, value)
    await session.flush()
    return ship


async def _replace_one(session, model, ship_id: int, payload: dict[str, Any]) -> None:
    await session.execute(delete(model).where(model.ship_id == ship_id))
    session.add(model(ship_id=ship_id, **payload))


async def _replace_many(session, model, ship_id: int, payloads: list[dict[str, Any]]) -> None:
    await session.execute(delete(model).where(model.ship_id == ship_id))
    for payload in payloads:
        session.add(model(ship_id=ship_id, **payload))


async def seed_ship_samples() -> None:
    async with AsyncSessionLocal() as session:
        cities = await _load_cities(session)
        regions = await _load_regions(session)
        if not cities or not regions:
            raise RuntimeError("seed_ship_samples requires seeded cities and business regions")

        now = datetime.utcnow()
        ship_ids: list[int] = []
        for idx, ship_type_code in enumerate(_type_codes(), start=1):
            profile = TYPE_PROFILE[ship_type_code]
            city = cities[(idx * 3) % len(cities)]
            region = regions[(idx * 5) % len(regions)]
            name = f"{NAME_PREFIXES[idx % len(NAME_PREFIXES)]}{profile['short']}{idx:03d}"
            building_year = 1996 + ((idx * 7) % 29)
            mmsi = str(413800000 + idx)
            ship = await _upsert_ship(
                session,
                {
                    "ais_id": f"AISCNINLAND{idx:04d}",
                    "ship_name": name,
                    "ship_name_en": f"CN INLAND {idx:04d}",
                    "current_mmsi": mmsi,
                    "ship_type_code": ship_type_code,
                    "navigation_power_type_code": profile.get("power", "SELF_PROPELLED"),
                    "home_port_code": city.code,
                    "home_port_name": f"{city.name}港",
                    "owner_name": OWNER_NAMES[idx % len(OWNER_NAMES)],
                    "building_year": building_year,
                    "registry_city_code": city.code,
                    "business_region_id": region.id,
                    "operation_status_code": STATUS_CODES[idx % len(STATUS_CODES)],
                    "profile_status_code": "ACTIVE" if idx % 17 else "INACTIVE",
                    "source_type_code": "SYSTEM",
                    "audit_status": "APPROVED",
                    "audited_at": now,
                },
            )
            ship_ids.append(ship.id)

            deadweight = _scaled(profile["dwt"][0], profile["dwt"][1], idx, 137)
            length = _scaled(profile["length"][0], profile["length"][1], idx, 89)
            width = _scaled(profile["width"][0], profile["width"][1], idx, 31)
            draft = _scaled(profile["draft"][0], profile["draft"][1], idx, 17)
            await _replace_one(
                session,
                ShipCapacity,
                ship.id,
                {
                    "deadweight_ton": deadweight,
                    "reference_load_ton": (deadweight * Decimal("0.92")).quantize(Decimal("0.01")),
                    "total_tonnage": (deadweight * Decimal("0.68")).quantize(Decimal("0.01")),
                    "net_tonnage": (deadweight * Decimal("0.44")).quantize(Decimal("0.01")),
                    "length_m": length,
                    "width_m": width,
                    "depth_m": (draft + Decimal("1.20")).quantize(Decimal("0.01")),
                    "design_draft_m": draft,
                    "design_speed_kn": _scaled(8, 14, idx, 23),
                    "hold_count": profile["holds"],
                    "capacity_remark": "本地验证预制船舶尺度载重数据",
                    "updated_at": now,
                },
            )
            await _replace_one(
                session,
                ShipOperation,
                ship.id,
                {
                    "operator_name": OWNER_NAMES[(idx + 1) % len(OWNER_NAMES)],
                    "manager_name": OWNER_NAMES[idx % len(OWNER_NAMES)],
                    "main_navigation_area_desc": region.short_name or region.name,
                    "usual_route_desc": f"{city.name} - {region.short_name or region.name}",
                    "contact_phone": f"13{idx % 10}{idx:08d}"[:11],
                    "dispatch_contact_name": f"调度{idx:03d}",
                    "dispatch_contact_phone": f"15{idx % 10}{(idx * 37):08d}"[:11],
                    "risk_level_code": "LOW" if idx % 11 else "MEDIUM",
                    "last_active_at": now,
                    "ext_json": {"seed_region": region.code, "registry_city": city.name},
                    "updated_at": now,
                },
            )
            await _replace_many(
                session,
                ShipOwner,
                ship.id,
                [
                    {
                        "party_name": OWNER_NAMES[idx % len(OWNER_NAMES)],
                        "party_relation_type_code": "OWNER",
                        "certificate_no": f"SHIP-OWNER-{idx:04d}",
                        "mobile_phone": f"18{idx % 10}{(idx * 19):08d}"[:11],
                        "address": f"{city.name}港航服务中心",
                        "is_primary": True,
                    }
                ],
            )
            await _replace_many(
                session,
                ShipContact,
                ship.id,
                [
                    {
                        "contact_name": f"船务联系人{idx:03d}",
                        "contact_role_code": "DISPATCH_CONTACT",
                        "mobile_phone": f"17{idx % 10}{(idx * 29):08d}"[:11],
                        "wechat": f"ship{idx:04d}",
                        "email": None,
                        "is_primary": True,
                        "remark": "本地验证预制联系人",
                    }
                ],
            )
            await _replace_many(
                session,
                ShipCertificate,
                ship.id,
                [
                    {
                        "certificate_type_code": "TRANSPORT_LICENSE",
                        "certificate_no": f"WL-{city.code}-{idx:04d}",
                        "issuing_authority": f"{city.name}交通运输主管部门",
                        "valid_from": date(2024, 1, 1),
                        "valid_to": date(2028, 12, 31),
                        "is_long_term_valid": False,
                        "validity_text_raw": "2024-01-01 至 2028-12-31",
                        "verify_status_code": "VERIFIED",
                        "structured_payload_json": {"seed": True},
                        "source_file_id": None,
                        "remark": "本地验证预制证照",
                    }
                ],
            )
            name_payloads = []
            if idx % 4 == 0:
                name_payloads.append(
                    {
                        "ship_name": f"{NAME_PREFIXES[(idx + 3) % len(NAME_PREFIXES)]}旧名{idx:03d}",
                        "start_date": date(max(building_year, 1996), 1, 1),
                        "end_date": date(2021, 12, 31),
                        "source_type_code": "SYSTEM",
                        "created_at": now,
                    }
                )
            await _replace_many(session, ShipNameHistory, ship.id, name_payloads)

            mmsi_payloads = []
            if idx % 5 == 0:
                mmsi_payloads.append(
                    {
                        "mmsi": str(412700000 + idx),
                        "start_date": date(max(building_year + 1, 1997), 1, 1),
                        "end_date": date(2022, 12, 31),
                        "source_type_code": "SYSTEM",
                        "created_at": now,
                    }
                )
            await _replace_many(session, ShipMmsiHistory, ship.id, mmsi_payloads)

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_ship_samples())
