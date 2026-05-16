"""Stable automated-test fixtures layered on top of production seed."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.freight import Freight
from app.models.route import (
    ShippingRoute,
    ShippingRouteLine,
    ShippingRouteLineNode,
    ShippingRouteLineSegment,
    ShippingRouteLineTrack,
    ShippingRoutePlan,
)
from scripts.seeds.demo.experience.shared import (
    NODE_CODES,
    RouteDef,
    _business_region_id,
    _commodity,
    _coord,
    _distance_km,
    _geometry,
    _node,
    _region,
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
TEST_ROUTE = RouteDef(
    key="TEST_TAICANG_WUHU",
    code=str(TEST_ROUTE_CONFIG["code"]),
    name=str(TEST_ROUTE_CONFIG["name"]),
    plan_code=str(TEST_ROUTE_CONFIG["plan_code"]),
    line_code=str(TEST_ROUTE_CONFIG["line_code"]),
    line_name=str(TEST_ROUTE_CONFIG["line_name"]),
    origin_region_code=str(TEST_ROUTE_CONFIG["origin_region_code"]),
    destination_region_code=str(TEST_ROUTE_CONFIG["destination_region_code"]),
    node_codes=tuple(NODE_CODES[key] for key in TEST_ROUTE_CONFIG["node_keys"]),
)


async def _clear_test_fixtures(session) -> None:
    await session.execute(delete(Freight).where(Freight.freight_no.like("TEST-FR-%")))
    await _delete_route_codes(session, [TEST_ROUTE.code])
    await session.flush()


async def _seed_test_route(session, now: datetime) -> None:
    origin_region = await _region(session, TEST_ROUTE.origin_region_code)
    destination_region = await _region(session, TEST_ROUTE.destination_region_code)
    route = ShippingRoute(
        code=TEST_ROUTE.code,
        name=TEST_ROUTE.name,
        transport_org_type_code="DIRECT_WATERWAY",
        multimodal_combination_code="WATERWAY",
        origin_region_id=origin_region.id,
        destination_region_id=destination_region.id,
        description="Automated-test fixture route. Not used by production seed.",
        audit_status="APPROVED",
        audited_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(route)
    await session.flush()

    plan = ShippingRoutePlan(
        route_id=route.id,
        plan_code=TEST_ROUTE.plan_code,
        plan_name=TEST_ROUTE.name,
        plan_type_code=TEST_SOURCE_TYPE,
        description="Automated-test fixture route plan.",
        remark="Generated only by --profile test.",
        created_at=now,
        updated_at=now,
    )
    session.add(plan)
    await session.flush()

    line = ShippingRouteLine(
        plan_id=plan.id,
        line_code=TEST_ROUTE.line_code,
        line_name=TEST_ROUTE.line_name,
        line_role_code="MAIN",
        priority=1,
        trigger_condition="test fixture",
        description="Stable test route line.",
        track_status="READY",
        track_generated_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(line)
    await session.flush()

    line_nodes: list[ShippingRouteLineNode] = []
    coords = []
    for order, node_code in enumerate(TEST_ROUTE.node_codes, start=1):
        node = await _node(session, node_code)
        lng, lat = _coord(node.longitude), _coord(node.latitude)
        row = ShippingRouteLineNode(
            line_id=line.id,
            node_order=order,
            node_type_code="TRANSPORT_NODE",
            transport_node_id=node.id,
            longitude=lng,
            latitude=lat,
            display_name=node.name,
            remark="测试夹具节点",
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        line_nodes.append(row)
        coords.append((lng, lat))
    await session.flush()

    total_distance = Decimal("0.00")
    for index in range(len(line_nodes) - 1):
        start = line_nodes[index]
        end = line_nodes[index + 1]
        distance = _distance_km(coords[index], coords[index + 1])
        total_distance += distance
        session.add(
            ShippingRouteLineSegment(
                line_id=line.id,
                segment_no=index + 1,
                start_line_node_id=start.id,
                end_line_node_id=end.id,
                transport_mode_code="WATER",
                distance_km=distance,
                estimated_duration_hour=(distance / Decimal("9.5")).quantize(Decimal("0.01")),
                segment_track_status="READY",
                geometry_source="MANUAL",
                geometry_json=_geometry(
                    [coords[index], coords[index + 1]],
                    source=TEST_SOURCE_TYPE,
                    name=f"{start.display_name}-{end.display_name}",
                    profile="test",
                ),
                remark="测试夹具航段轨迹。",
                created_at=now,
                updated_at=now,
            )
        )
    await session.flush()

    session.add(
        ShippingRouteLineTrack(
            line_id=line.id,
            track_status="READY",
            geometry_json=_geometry(coords, source=TEST_SOURCE_TYPE, name=TEST_ROUTE.line_name, profile="test"),
            distance_km=total_distance,
            estimated_duration_hour=(total_distance / Decimal("9.5")).quantize(Decimal("0.01")),
            provider_summary_json={"provider": TEST_SOURCE_TYPE, "source": TEST_CONFIG["version"]},
            generated_at=now,
            created_at=now,
            updated_at=now,
        )
    )


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
        await _seed_test_route(session, now)
        await _seed_test_freight(session, now)
        await session.commit()
    result = await seed_analysis_facts_for_profile(profile="test", days=7)
    print(
        "test fixtures seeded: TEST_ROUTE_TAICANG_WUHU, TEST-FR-0001, "
        f"analysis_affected_rows={result.get('affected_rows', 0)}"
    )
