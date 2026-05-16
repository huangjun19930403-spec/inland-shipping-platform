"""Shared constants and helpers for demo/test experience seed."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
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
    "TAICANG_NANJING": "DEMO_ROUTE_TAICANG_NANJING_CURRENT",
    "CHANGXING_WUHU": "DEMO_ROUTE_CHANGXING_WUHU_CURRENT",
}
DEMO_SOURCE_INDEX = "DEMO_ES_MIRROR"
SCENARIO_VERSION = "round6_demo_test_seed_v1"


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


DEMO_SCENARIO_FILE = Path(__file__).resolve().parents[3] / "seed_data" / "demo" / "demo_scenarios.json"


def load_demo_seed_config() -> dict[str, Any]:
    return json.loads(DEMO_SCENARIO_FILE.read_text(encoding="utf-8"))


def _scenario_from_config(row: dict[str, Any]) -> ScenarioDef:
    return ScenarioDef(
        code=str(row["code"]),
        route_key=row.get("route_key"),
        count=int(row["count"]),
        origin_node_code=str(row["origin_node_code"]),
        destination_node_code=str(row["destination_node_code"]) if row.get("destination_node_code") else None,
        commodity_codes=tuple(str(code) for code in row["commodity_codes"]),
        cargo_label=str(row["cargo_label"]),
        tonnage_start=int(row["tonnage_start"]),
        tonnage_step=int(row["tonnage_step"]),
        shipper_price_start=int(row["shipper_price_start"]),
        owner_price_delta=int(row["owner_price_delta"]),
        publisher_prefix=str(row["publisher_prefix"]),
        risk_mode=str(row.get("risk_mode") or "NORMAL"),
    )


def _route_from_config(row: dict[str, Any]) -> RouteDef:
    return RouteDef(
        key=str(row["key"]),
        code=str(row["code"]),
        name=str(row["name"]),
        plan_code=str(row["plan_code"]),
        line_code=str(row["line_code"]),
        line_name=str(row["line_name"]),
        origin_region_code=str(row["origin_region_code"]),
        destination_region_code=str(row["destination_region_code"]),
        node_codes=tuple(str(code) for code in row["node_codes"]),
    )


DEMO_CONFIG = load_demo_seed_config()
DEMO_SOURCE_LAYER_CODE = str(DEMO_CONFIG.get("source_layer_code") or "LOCAL_DEMO")
NODE_CODES: dict[str, str] = {str(key): str(value) for key, value in DEMO_CONFIG["nodes"].items()}
CONSTRAINT_CODES: dict[str, str] = {str(key): str(value) for key, value in DEMO_CONFIG["constraints"].items()}
SCENARIOS = tuple(_scenario_from_config(row) for row in DEMO_CONFIG["scenarios"])
ROUTES = tuple(_route_from_config(row) for row in DEMO_CONFIG["routes"])


def _money(value: int | float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _coord(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.000001"))


def _hash(text: str) -> str:
    return text[:64]


def _geometry(
    coords: list[tuple[Decimal, Decimal]],
    *,
    source: str,
    name: str,
    profile: str = "local-demo",
) -> dict[str, Any]:
    return {
        "type": "LineString",
        "coordinates": [[float(lng), float(lat)] for lng, lat in coords],
        "properties": {"source": source, "name": name, "profile": profile},
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
