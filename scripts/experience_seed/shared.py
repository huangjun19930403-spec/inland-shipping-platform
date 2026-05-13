"""Shared constants and helpers for Round 11 experience seed."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.models.address import NavigationConstraintPoint, Region, RegionCityRelation, TransportNode
from app.models.commodity import CommodityStandard
from app.models.route import ShippingRoute, ShippingRouteLine, ShippingRouteLineSegment
from app.models.vessel import VesselProfileSummary

AIS_SNAPSHOT_ID = "DEMO_AIS_EXPERIENCE_CURRENT"
NODE_SNAPSHOT_IDS = {
    "TAICANG": "DEMO_NODE_TAICANG_CURRENT",
    "JIANGYIN": "DEMO_NODE_JIANGYIN_CURRENT",
    "NANJING": "DEMO_NODE_NANJING_CURRENT",
    "WUHU": "DEMO_NODE_WUHU_CURRENT",
}
ROUTE_SNAPSHOT_IDS = {
    "TAICANG_WUHU": "DEMO_ROUTE_TAICANG_WUHU_CURRENT",
    "SUZHOU_NANJING": "DEMO_ROUTE_SUZHOU_NANJING_CURRENT",
    "HUZHOU_WUHU": "DEMO_ROUTE_HUZHOU_WUHU_CURRENT",
}
DEMO_SOURCE_INDEX = "DEMO_ES_MIRROR"
SCENARIO_VERSION = "round11_experience_seed_v1"


@dataclass(frozen=True)
class ScenarioDef:
    code: str
    route_key: str | None
    count: int
    origin_node_code: str
    destination_node_code: str | None
    commodity_codes: tuple[str, ...]
    cargo_label: str
    tonnage_start: int
    tonnage_step: int
    shipper_price_start: int
    owner_price_delta: int
    publisher_prefix: str
    risk_mode: str = "NORMAL"


@dataclass(frozen=True)
class RouteDef:
    key: str
    code: str
    name: str
    plan_code: str
    line_code: str
    line_name: str
    origin_region_code: str
    destination_region_code: str
    node_codes: tuple[str, ...]


@dataclass
class RouteInfo:
    key: str
    route: ShippingRoute
    line: ShippingRouteLine
    segments: list[ShippingRouteLineSegment]


@dataclass
class DemoPosition:
    summary: VesselProfileSummary
    longitude: Decimal
    latitude: Decimal
    city_code: str | None
    city_name: str | None
    position_time: datetime
    freshness_level: str
    source_index: str
    speed_kn: Decimal
    course_deg: Decimal
    heading_deg: Decimal


SCENARIOS = (
    ScenarioDef(
        code="SCN_TCWUHU_AGG",
        route_key="TAICANG_WUHU",
        count=12,
        origin_node_code="NODE_SUZHOU_TAICANG_PORT",
        destination_node_code="NODE_WUHU_ZHUJIAQIAO_PORT",
        commodity_codes=("STD_SAND_STONE_AGGREGATE", "STD_MACHINE_SAND", "STD_RIVER_SAND"),
        cargo_label="砂石/机制砂/矿建材料",
        tonnage_start=2600,
        tonnage_step=180,
        shipper_price_start=39,
        owner_price_delta=4,
        publisher_prefix="太仓港矿建材料集配",
    ),
    ScenarioDef(
        code="SCN_SUZHOU_NANJING_STEEL",
        route_key="SUZHOU_NANJING",
        count=10,
        origin_node_code="NODE_SUZHOU_TAICANG_PORT",
        destination_node_code="NODE_NJ_LONGTAN_PORT",
        commodity_codes=("STD_STEEL", "STD_REBAR"),
        cargo_label="钢材/螺纹钢",
        tonnage_start=900,
        tonnage_step=120,
        shipper_price_start=58,
        owner_price_delta=5,
        publisher_prefix="苏州钢材贸易",
    ),
    ScenarioDef(
        code="SCN_HUZHOU_WUHU_CEMENT",
        route_key="HUZHOU_WUHU",
        count=10,
        origin_node_code="NODE_HUZHOU_CHANGXING_PORT",
        destination_node_code="NODE_WUHU_ZHUJIAQIAO_PORT",
        commodity_codes=("STD_BULK_CEMENT_PO425", "STD_LIMESTONE_POWDER", "STD_CEMENT_CLINKER"),
        cargo_label="水泥/石灰石粉",
        tonnage_start=1500,
        tonnage_step=160,
        shipper_price_start=45,
        owner_price_delta=4,
        publisher_prefix="湖州长兴建材供应链",
    ),
    ScenarioDef(
        code="SCN_RISK_NOT_COMPUTABLE",
        route_key="TAICANG_WUHU",
        count=10,
        origin_node_code="NODE_SUZHOU_TAICANG_PORT",
        destination_node_code="NODE_WUHU_ZHUJIAQIAO_PORT",
        commodity_codes=("STD_MACHINE_SAND", "STD_REBAR", "STD_LIMESTONE"),
        cargo_label="风险/不可计算样例",
        tonnage_start=3200,
        tonnage_step=220,
        shipper_price_start=42,
        owner_price_delta=8,
        publisher_prefix="风险复核样例货主",
        risk_mode="RISK",
    ),
)

ROUTES = (
    RouteDef(
        key="TAICANG_WUHU",
        code="ROUTE_TAICANG_WUHU",
        name="太仓港至芜湖矿建材料航线",
        plan_code="PLAN_TAICANG_WUHU_STD",
        line_code="LINE_TAICANG_WUHU_MAIN",
        line_name="太仓-江阴-龙潭-芜湖主线",
        origin_region_code="REGION_YANGTZE_DELTA",
        destination_region_code="REGION_WANJIANG",
        node_codes=(
            "NODE_SUZHOU_TAICANG_PORT",
            "NC_JIANGYIN_BRIDGE_CLEARANCE",
            "NODE_WX_JIANGYIN_PORT",
            "NODE_NJ_LONGTAN_PORT",
            "NODE_WUHU_ZHUJIAQIAO_PORT",
        ),
    ),
    RouteDef(
        key="SUZHOU_NANJING",
        code="ROUTE_SUZHOU_NANJING_STEEL",
        name="苏州太仓至南京龙潭钢材航线",
        plan_code="PLAN_SUZHOU_NANJING_STEEL",
        line_code="LINE_SUZHOU_NANJING_STEEL",
        line_name="太仓-江阴桥区-南京龙潭钢材线",
        origin_region_code="REGION_YANGTZE_DELTA",
        destination_region_code="REGION_YANGTZE_DELTA",
        node_codes=(
            "NODE_SUZHOU_TAICANG_PORT",
            "NC_JIANGYIN_BRIDGE_CLEARANCE",
            "NODE_NJ_LONGTAN_PORT",
        ),
    ),
    RouteDef(
        key="HUZHOU_WUHU",
        code="ROUTE_HUZHOU_WUHU_CEMENT",
        name="湖州长兴至芜湖水泥熟料航线",
        plan_code="PLAN_HUZHOU_WUHU_CEMENT",
        line_code="LINE_HUZHOU_WUHU_CEMENT",
        line_name="长兴-奔牛船闸-龙潭-芜湖水泥线",
        origin_region_code="REGION_YANGTZE_DELTA",
        destination_region_code="REGION_WANJIANG",
        node_codes=(
            "NODE_HUZHOU_CHANGXING_PORT",
            "NC_CHANGZHOU_BENNIU_LOCK",
            "NODE_NJ_LONGTAN_PORT",
            "NODE_WUHU_ZHUJIAQIAO_PORT",
        ),
    ),
)


def _money(value: int | float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _coord(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.000001"))


def _hash(text: str) -> str:
    return text[:64]


def _geometry(coords: list[tuple[Decimal, Decimal]], *, source: str, name: str) -> dict[str, Any]:
    return {
        "type": "LineString",
        "coordinates": [[float(lng), float(lat)] for lng, lat in coords],
        "properties": {"source": source, "name": name, "profile": "local-demo"},
    }


def _distance_km(a: tuple[Decimal, Decimal], b: tuple[Decimal, Decimal]) -> Decimal:
    lon1, lat1 = float(a[0]), float(a[1])
    lon2, lat2 = float(b[0]), float(b[1])
    radius_km = 6371.0088
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    h = math.sin(d_lat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(d_lon / 2) ** 2
    return Decimal(str(radius_km * 2 * math.asin(math.sqrt(h)))).quantize(Decimal("0.01"))


def _offset(base_lng: Any, base_lat: Any, index: int, radius: Decimal = Decimal("0.015")) -> tuple[Decimal, Decimal]:
    angle = (index % 12) * (math.pi / 6)
    ring = Decimal("0.45") + Decimal(str((index % 4) * 0.15))
    lng = _coord(base_lng) + (radius * ring * Decimal(str(math.cos(angle)))).quantize(Decimal("0.000001"))
    lat = _coord(base_lat) + (radius * ring * Decimal(str(math.sin(angle)))).quantize(Decimal("0.000001"))
    return _coord(lng), _coord(lat)


def _interpolate(
    a: tuple[Decimal, Decimal],
    b: tuple[Decimal, Decimal],
    ratio: Decimal,
    index: int,
) -> tuple[Decimal, Decimal]:
    lng = a[0] + (b[0] - a[0]) * ratio
    lat = a[1] + (b[1] - a[1]) * ratio
    wiggle = Decimal(str(((index % 5) - 2) * 0.003))
    return _coord(lng + wiggle), _coord(lat - wiggle)


async def _region(session, code: str) -> Region:
    row = await session.scalar(select(Region).where(Region.code == code))
    if row is None:
        raise RuntimeError(f"region seed not found: {code}")
    return row


async def _node(session, code: str) -> TransportNode:
    row = await session.scalar(select(TransportNode).where(TransportNode.code == code))
    if row is None:
        raise RuntimeError(f"transport node seed not found: {code}")
    return row


async def _constraint(session, code: str) -> NavigationConstraintPoint:
    row = await session.scalar(select(NavigationConstraintPoint).where(NavigationConstraintPoint.code == code))
    if row is None:
        raise RuntimeError(f"navigation constraint seed not found: {code}")
    return row


async def _commodity(session, codes: tuple[str, ...], index: int) -> CommodityStandard:
    code = codes[index % len(codes)]
    row = await session.scalar(select(CommodityStandard).where(CommodityStandard.code == code))
    if row is not None:
        return row
    fallback = await session.scalar(select(CommodityStandard).where(CommodityStandard.is_active.is_(True)).order_by(CommodityStandard.id))
    if fallback is None:
        raise RuntimeError("commodity seed not found")
    return fallback


async def _business_region_id(session, node: TransportNode | None) -> int | None:
    if node is None:
        return None
    relation = await session.scalar(
        select(RegionCityRelation)
        .where(RegionCityRelation.city_region_id == node.city_region_id)
        .order_by(RegionCityRelation.is_primary.desc(), RegionCityRelation.sort_order.asc())
    )
    return int(relation.region_id) if relation is not None else None
