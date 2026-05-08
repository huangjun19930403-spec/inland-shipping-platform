"""船舶主数据模块本地验证样例 seed。"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select, update

from app.core.database import AsyncSessionLocal
from app.models.address import AdminRegion, Region
from app.models.common import CodeSequence
from app.models.vessel import (
    VesselBehaviorProfile,
    VesselBuildInfo,
    VesselCapacityDimension,
    VesselCargoCapability,
    VesselCertificate,
    VesselCertificateFile,
    VesselChangeEvent,
    VesselContact,
    VesselIdentifierHistory,
    VesselIdentity,
    VesselIdentityCandidate,
    VesselIdentityLink,
    VesselManualPreference,
    VesselNameHistory,
    VesselOperatorPeriod,
    VesselOwnerPeriod,
    VesselProfile,
    VesselQualityIssue,
    VesselQualitySnapshot,
    VesselRegistrationInfo,
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
    ("DRY_BULK", 24),
    ("GENERAL_CARGO", 20),
    ("SELF_UNLOADING_SAND", 16),
    ("CONTAINER", 12),
    ("MULTI_PURPOSE", 12),
    ("BULK_CEMENT", 8),
    ("OIL_TANKER", 8),
    ("CHEMICAL_TANKER", 8),
    ("ENGINEERING", 6),
    ("TUG", 6),
]

TYPE_PROFILE: dict[str, dict[str, Any]] = {
    "DRY_BULK": {"short": "散货", "dwt": (1800, 9800), "length": (58, 118), "width": (11, 20), "draft": (2.6, 5.2), "holds": 4},
    "SELF_UNLOADING_SAND": {"short": "自卸", "dwt": (2500, 12000), "length": (68, 128), "width": (12, 22), "draft": (2.8, 5.6), "holds": 5},
    "GENERAL_CARGO": {"short": "普货", "dwt": (900, 5200), "length": (45, 92), "width": (9, 17), "draft": (1.8, 4.2), "holds": 3},
    "CONTAINER": {"short": "集装箱", "dwt": (2600, 9000), "length": (72, 130), "width": (14, 24), "draft": (2.8, 5.4), "holds": 2, "teu": 180},
    "MULTI_PURPOSE": {"short": "多用", "dwt": (1600, 7600), "length": (56, 108), "width": (11, 19), "draft": (2.4, 4.9), "holds": 3},
    "BULK_CEMENT": {"short": "水泥", "dwt": (1200, 6800), "length": (52, 102), "width": (10, 18), "draft": (2.2, 4.7), "holds": 3},
    "OIL_TANKER": {"short": "油", "dwt": (1200, 6200), "length": (52, 105), "width": (10, 18), "draft": (2.2, 4.8), "holds": 4},
    "CHEMICAL_TANKER": {"short": "化学品", "dwt": (1000, 5600), "length": (50, 98), "width": (10, 17), "draft": (2.1, 4.6), "holds": 4},
    "ENGINEERING": {"short": "工程", "dwt": (600, 2600), "length": (36, 78), "width": (9, 17), "draft": (1.6, 3.8), "holds": 1},
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


async def _clear_vessels(session) -> None:
    for model in (
        VesselChangeEvent,
        VesselIdentityCandidate,
        VesselQualityIssue,
        VesselQualitySnapshot,
        VesselBehaviorProfile,
        VesselManualPreference,
        VesselCertificateFile,
        VesselCertificate,
        VesselContact,
        VesselOperatorPeriod,
        VesselOwnerPeriod,
        VesselCargoCapability,
        VesselBuildInfo,
        VesselCapacityDimension,
        VesselRegistrationInfo,
        VesselIdentifierHistory,
        VesselNameHistory,
        VesselIdentityLink,
        VesselProfile,
        VesselIdentity,
    ):
        await session.execute(delete(model))


async def seed_vessel_samples() -> None:
    async with AsyncSessionLocal() as session:
        cities = await _load_cities(session)
        regions = await _load_regions(session)
        if not cities or not regions:
            raise RuntimeError("seed_vessel_samples requires seeded cities and business regions")

        await _clear_vessels(session)
        now = datetime.utcnow()
        for idx, ship_type_code in enumerate(_type_codes(), start=1):
            profile = TYPE_PROFILE[ship_type_code]
            city = cities[(idx * 3) % len(cities)]
            region = regions[(idx * 5) % len(regions)]
            name = f"{NAME_PREFIXES[idx % len(NAME_PREFIXES)]}{profile['short']}{idx:03d}"
            building_year = 1996 + ((idx * 7) % 29)
            duplicate_anchor = idx - 1 if idx % 12 == 0 else idx
            mmsi = str(413800000 + duplicate_anchor)
            vessel = VesselProfile(
                vessel_profile_code=f"VP{idx:06d}",
                vessel_identity_id=idx,
                ais_id=f"AISCNINLAND{idx:04d}",
                ship_name=name,
                ship_name_en=f"CN INLAND {idx:04d}",
                current_mmsi=mmsi,
                ship_type_code=ship_type_code,
                navigation_power_type_code="NON_SELF_PROPELLED" if ship_type_code == "TUG" else "SELF_PROPELLED",
                profile_status_code="ACTIVE" if idx % 17 else "INACTIVE",
                identity_status_code="LINKED" if idx % 12 else "CONFLICT",
                quality_level_code="HIGH" if idx % 9 else "MEDIUM",
                operation_status_code=STATUS_CODES[idx % len(STATUS_CODES)],
                home_port_code=city.code,
                home_port_name=f"{city.name}港",
                owner_name=OWNER_NAMES[idx % len(OWNER_NAMES)],
                building_year=building_year,
                registry_city_code=city.code,
                business_region_id=region.id,
                source_type_code="SYSTEM",
                audit_status="APPROVED",
                audited_at=now,
            )
            session.add(VesselIdentity(
                id=idx,
                identity_code=f"VID{idx:06d}",
                identity_status_code="VERIFIED" if idx % 12 else "CONFLICT",
                canonical_mmsi=mmsi,
                canonical_ship_name=name,
                confidence_score=92,
                source_type_code="SYSTEM",
            ))
            session.add(vessel)
            await session.flush()
            session.add(VesselIdentityLink(vessel_identity_id=idx, vessel_profile_id=vessel.id, link_type_code="PROFILE", confidence_score=92, is_primary=True, start_at=now))
            session.add(VesselNameHistory(vessel_profile_id=vessel.id, ship_name=name, source_type_code="SYSTEM", created_at=now))
            session.add(VesselIdentifierHistory(vessel_profile_id=vessel.id, identifier_type_code="MMSI", identifier_value=mmsi, source_type_code="SYSTEM", created_at=now))
            session.add(VesselIdentifierHistory(vessel_profile_id=vessel.id, identifier_type_code="AIS", identifier_value=vessel.ais_id or "", source_type_code="SYSTEM", created_at=now))
            if idx % 4 == 0:
                session.add(VesselNameHistory(vessel_profile_id=vessel.id, ship_name=f"{NAME_PREFIXES[(idx + 3) % len(NAME_PREFIXES)]}旧名{idx:03d}", start_date=date(max(building_year, 1996), 1, 1), end_date=date(2021, 12, 31), source_type_code="SYSTEM", created_at=now))
            if idx % 5 == 0:
                session.add(VesselIdentifierHistory(vessel_profile_id=vessel.id, identifier_type_code="MMSI", identifier_value=str(412700000 + idx), start_date=date(max(building_year + 1, 1997), 1, 1), end_date=date(2022, 12, 31), source_type_code="SYSTEM", created_at=now))

            deadweight = _scaled(profile["dwt"][0], profile["dwt"][1], idx, 137)
            length = _scaled(profile["length"][0], profile["length"][1], idx, 89)
            width = _scaled(profile["width"][0], profile["width"][1], idx, 31)
            draft = _scaled(profile["draft"][0], profile["draft"][1], idx, 17)
            session.add(VesselRegistrationInfo(vessel_profile_id=vessel.id, registry_city_code=city.code, ship_registry_no=f"REG-{city.code}-{idx:04d}", home_port_code=city.code, home_port_name=f"{city.name}港", flag_code="CN", mmsi_issuing_authority=f"{city.name}海事机构", inspection_org=f"{city.name}船检中心", updated_at=now))
            session.add(VesselCapacityDimension(vessel_profile_id=vessel.id, deadweight_ton=deadweight, reference_load_ton=(deadweight * Decimal("0.92")).quantize(Decimal("0.01")), total_tonnage=(deadweight * Decimal("0.68")).quantize(Decimal("0.01")), net_tonnage=(deadweight * Decimal("0.44")).quantize(Decimal("0.01")), length_m=length, width_m=width, depth_m=(draft + Decimal("1.20")).quantize(Decimal("0.01")), design_draft_m=draft, max_draft_m=(draft + Decimal("0.40")).quantize(Decimal("0.01")), design_speed_kn=_scaled(8, 14, idx, 23), hold_count=profile["holds"], teu_capacity=profile.get("teu"), capacity_remark="本地验证预制船舶尺度载重数据", updated_at=now))
            session.add(VesselBuildInfo(vessel_profile_id=vessel.id, building_year=building_year, builder_name=f"{city.name}船舶制造厂", build_place=city.name, hull_material_code="STEEL", engine_power_kw=_scaled(420, 1800, idx, 11), updated_at=now))
            session.add(VesselCargoCapability(vessel_profile_id=vessel.id, capability_tags_json=[profile["short"], "内河"], commodity_type_codes_json=["BULK"] if ship_type_code in {"DRY_BULK", "SELF_UNLOADING_SAND"} else None, preferred_cargo_json=[{"name": "矿建材料"}] if ship_type_code == "SELF_UNLOADING_SAND" else None, has_self_unloading=ship_type_code == "SELF_UNLOADING_SAND", has_container_fittings=ship_type_code == "CONTAINER", can_carry_dangerous=ship_type_code in {"CHEMICAL_TANKER", "OIL_TANKER"}, temperature_control=False, cargo_handling_notes=f"{profile['short']}典型货运能力", updated_at=now))
            session.add(VesselOwnerPeriod(vessel_profile_id=vessel.id, party_name=OWNER_NAMES[idx % len(OWNER_NAMES)], party_relation_type_code="OWNER", certificate_no=f"VESSEL-OWNER-{idx:04d}", mobile_phone=f"18{idx % 10}{(idx * 19):08d}"[:11], address=f"{city.name}港航服务中心", start_date=date(2020, 1, 1), is_current=True, is_primary=True))
            session.add(VesselOperatorPeriod(vessel_profile_id=vessel.id, operator_name=OWNER_NAMES[(idx + 1) % len(OWNER_NAMES)], operator_role_code="OPERATOR", manager_name=OWNER_NAMES[idx % len(OWNER_NAMES)], main_navigation_area_desc=region.short_name or region.name, usual_route_desc=f"{city.name} - {region.short_name or region.name}", contact_phone=f"13{idx % 10}{idx:08d}"[:11], dispatch_contact_name=f"调度{idx:03d}", dispatch_contact_phone=f"15{idx % 10}{(idx * 37):08d}"[:11], risk_level_code="LOW" if idx % 11 else "MEDIUM", start_date=date(2020, 1, 1), is_current=True, is_primary=True, last_active_at=now))
            session.add(VesselContact(vessel_profile_id=vessel.id, contact_name=f"船务联系人{idx:03d}", contact_role_code="DISPATCH_CONTACT", mobile_phone=f"17{idx % 10}{(idx * 29):08d}"[:11], wechat=f"ship{idx:04d}", is_primary=True, is_available=idx % 13 != 0, last_verified_at=now, remark="本地验证预制联系人"))
            if idx <= 92:
                session.add(VesselCertificate(vessel_profile_id=vessel.id, certificate_type_code="TRANSPORT_LICENSE", certificate_no=f"WL-{city.code}-{idx:04d}", issuing_authority=f"{city.name}交通运输主管部门", valid_from=date(2024, 1, 1), valid_to=date(2028, 12, 31) if idx % 10 else date(2025, 12, 31), is_long_term_valid=False, validity_text_raw="2024-01-01 至 2028-12-31", verify_status_code="VERIFIED", structured_payload_json={"seed": True}, remark="本地验证预制证照"))
            session.add(VesselManualPreference(vessel_profile_id=vessel.id, preferred_cargo_json=[{"name": "砂石"}] if ship_type_code == "SELF_UNLOADING_SAND" else None, avoided_cargo_json=None, preferred_route_json=[{"text": f"{city.name} - {region.short_name or region.name}"}], unavailable_period_json=None, freight_preference_text="优先接固定线路货源", risk_note=None, updated_at=now))
            session.add(VesselBehaviorProfile(vessel_profile_id=vessel.id, active_city_codes_json=[city.code], usual_route_json=[{"text": f"{city.name} - {region.short_name or region.name}"}], cargo_preference_json=[{"ship_type": ship_type_code}], contactability_score=85 if idx % 13 else 35, activity_score=80, last_active_at=now, generated_at=now, source_type_code="LOCAL_SAMPLE", updated_at=now))

            issue_count = 0
            if idx % 6 == 0:
                issue_count += 1
                session.add(VesselQualityIssue(vessel_profile_id=vessel.id, issue_type_code="MISSING_CONTACT", severity_code="HIGH", issue_title="联系人近期不可用", status_code="OPEN"))
            if idx % 10 == 0:
                issue_count += 1
                session.add(VesselQualityIssue(vessel_profile_id=vessel.id, issue_type_code="MISSING_CERTIFICATE", severity_code="MEDIUM", issue_title="证件有效期需复核", status_code="OPEN"))
            if idx % 12 == 0:
                issue_count += 1
                session.add(VesselQualityIssue(vessel_profile_id=vessel.id, issue_type_code="DUPLICATE_MMSI", severity_code="HIGH", issue_title="MMSI 与相邻档案重复", status_code="OPEN"))
                session.add(VesselIdentityCandidate(source_profile_id=idx - 1, target_profile_id=idx, candidate_type_code="SAME_MMSI", confidence_score=90, evidence_json={"mmsi": mmsi}, status_code="PENDING"))
            session.add(VesselQualitySnapshot(vessel_profile_id=vessel.id, quality_level_code="LOW" if issue_count >= 2 else ("MEDIUM" if issue_count else "HIGH"), completeness_score=90, contact_score=35 if idx % 13 == 0 else 85, certificate_score=60 if idx % 10 == 0 else 90, identity_score=40 if idx % 12 == 0 else 85, issue_count=issue_count, generated_at=now))
            session.add(VesselChangeEvent(vessel_profile_id=vessel.id, event_type_code="SEED_CREATE", event_title="本地样例生成", before_json=None, after_json={"vessel_profile_code": vessel.vessel_profile_code}, operator_id=None, created_at=now))

        await session.execute(
            update(CodeSequence)
            .where(CodeSequence.biz_code == "VESSEL_PROFILE_CODE")
            .values(current_value=len(_type_codes()), updated_at=now)
        )
        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_vessel_samples())
