"""Stable automated-test fixtures layered on top of production seed."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.freight import Freight
from scripts.seeds.demo.experience.shared import (
    NODE_CODES,
    _business_region_id,
    _commodity,
    _node,
)
from scripts.seeds.demo.experience.cleanup import _delete_route_codes
from scripts.seeds.demo.experience.analysis import seed_analysis_facts_for_profile


TEST_SCENARIO_FILE = Path(__file__).resolve().parents[2] / "seed_data" / "test" / "test_scenarios.json"


def load_test_seed_config() -> dict:
    return json.loads(TEST_SCENARIO_FILE.read_text(encoding="utf-8"))


TEST_CONFIG = load_test_seed_config()
TEST_SOURCE_TYPE = str(TEST_CONFIG.get("source_type_code") or "TEST_FIXTURE")
TEST_ROUTE_CONFIG = TEST_CONFIG["route"]
TEST_FREIGHT_CONFIG = TEST_CONFIG["freight"]
TEST_ROUTE_CODE = str(TEST_ROUTE_CONFIG["code"])


async def _clear_test_fixtures(session) -> None:
    await session.execute(delete(Freight).where(Freight.freight_no.like("TEST-FR-%")))
    await _delete_route_codes(session, [TEST_ROUTE_CODE])
    await session.flush()


async def _seed_test_freight(session, now: datetime) -> None:
    origin = await _node(session, NODE_CODES[TEST_FREIGHT_CONFIG["origin_node_key"]])
    destination = await _node(session, NODE_CODES[TEST_FREIGHT_CONFIG["destination_node_key"]])
    commodity = await _commodity(session, tuple(TEST_FREIGHT_CONFIG["commodity_codes"]), 0)
    origin_region_id = await _business_region_id(session, origin)
    destination_region_id = await _business_region_id(session, destination)
    loading_from = now + timedelta(days=2)
    session.add(
        Freight(
            freight_no=str(TEST_FREIGHT_CONFIG["freight_no"]),
            source_type_code=TEST_SOURCE_TYPE,
            source_channel_code="SYSTEM_SYNC",
            source_ref_no=str(TEST_FREIGHT_CONFIG["source_ref_no"]),
            raw_commodity_name=commodity.name,
            raw_tonnage_text=f"{TEST_FREIGHT_CONFIG['tonnage']}吨",
            raw_origin_text=origin.name,
            raw_destination_text=destination.name,
            cargo_title=f"{origin.short_name or origin.name}至{destination.short_name or destination.name}测试夹具货源",
            cargo_description="仅由 --profile test 生成，用于自动化测试稳定引用。",
            commodity_standard_id=commodity.id,
            commodity_match_level_code="STANDARD",
            packaging_form_code="BULK",
            estimated_tonnage=Decimal(str(TEST_FREIGHT_CONFIG["tonnage"])),
            min_tonnage=Decimal(str(TEST_FREIGHT_CONFIG["tonnage"])) - Decimal("100.00"),
            max_tonnage=Decimal(str(TEST_FREIGHT_CONFIG["tonnage"])) + Decimal("100.00"),
            unit_price=Decimal(str(TEST_FREIGHT_CONFIG["unit_price"])),
            total_price=Decimal(str(TEST_FREIGHT_CONFIG["tonnage"])) * Decimal(str(TEST_FREIGHT_CONFIG["unit_price"])),
            price_unit="元/吨",
            settlement_method_code="BY_TON",
            origin_node_id=origin.id,
            destination_node_id=destination.id,
            origin_match_level_code="NODE",
            destination_match_level_code="NODE",
            origin_province_code=origin.province_code,
            origin_city_code=origin.city_code,
            origin_district_code=origin.district_code,
            destination_province_code=destination.province_code,
            destination_city_code=destination.city_code,
            destination_district_code=destination.district_code,
            origin_region_id_cache=origin_region_id,
            destination_region_id_cache=destination_region_id,
            loading_time_from=loading_from,
            loading_time_to=loading_from + timedelta(hours=8),
            publisher_org_name=str(TEST_FREIGHT_CONFIG["publisher_org_name"]),
            status_code="PUBLISHED",
            published_at=now,
            expired_at=now + timedelta(days=10),
            confirmed_at=now,
            hall_status_code="LISTED",
            hall_published_at=now,
            hall_visible_until=now + timedelta(days=10),
            audit_status="APPROVED",
            audited_at=now,
            created_at=now,
            updated_at=now,
        )
    )


async def seed_test_fixture_overlay() -> None:
    async with AsyncSessionLocal() as session:
        now = datetime.utcnow()
        await _clear_test_fixtures(session)
        await _seed_test_freight(session, now)
        await session.commit()
    result = await seed_analysis_facts_for_profile(profile="test", days=7)
    print(
        "test fixtures seeded: TEST-FR-0001, route fixtures intentionally skipped, "
        f"analysis_affected_rows={result.get('affected_rows', 0)}"
    )
