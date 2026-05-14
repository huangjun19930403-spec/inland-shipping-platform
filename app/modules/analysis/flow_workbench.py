"""Flow-analysis workbench builders.

This module keeps Round 15 relationship enrichment out of the already-large
analysis dashboard service.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.modules.analysis.schemas import AnalysisActionBlock, ChartPoint, FlowCorridorItem, FlowMapItem, FlowStructureLink


def ratio(value: float, total: float) -> float | None:
    if not total:
        return None
    return round(value / total, 4)


def confidence_from_rate(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value >= 0.75:
        return "HIGH"
    if value >= 0.45:
        return "MEDIUM"
    return "LOW"


def flow_pair_key(item: FlowMapItem, *, reverse: bool = False) -> tuple[str, str]:
    left = str(item.origin_id or item.origin_name)
    right = str(item.destination_id or item.destination_name)
    return (right, left) if reverse else (left, right)


def flow_city_pair_key(item: FlowMapItem, *, reverse: bool = False) -> tuple[str | None, str | None]:
    left = item.origin_city_code
    right = item.destination_city_code
    return (right, left) if reverse else (left, right)


def risk_level_for_flow(item: FlowMapItem) -> str:
    status = str(item.route_status_code or "").upper()
    if status in {"FAILED", "NOT_COMPUTABLE"}:
        return "HIGH"
    if item.ais_freshness_rate is not None and item.ais_freshness_rate < 0.45:
        return "MEDIUM"
    if item.confidence_level in {"LOW", "UNKNOWN"}:
        return "MEDIUM"
    return "LOW"


def flow_action_query(item: FlowMapItem) -> dict[str, Any]:
    return {
        "origin_node_id": item.origin_id,
        "destination_node_id": item.destination_id,
        "keyword": f"{item.origin_name} {item.destination_name}",
        "origin_name": item.origin_name,
        "destination_name": item.destination_name,
    }


def enrich_flow_relationships(freight_flows: list[FlowMapItem], ship_flows: list[FlowMapItem]) -> None:
    freight_by_key = {flow_pair_key(item): item for item in freight_flows}
    freight_by_city_key = {
        flow_city_pair_key(item): item
        for item in freight_flows
        if item.origin_city_code or item.destination_city_code
    }
    freight_outbound_by_origin_city: dict[str, int] = defaultdict(int)
    for item in freight_flows:
        if item.origin_city_code:
            freight_outbound_by_origin_city[item.origin_city_code] += item.freight_count or 0

    ship_by_key = {flow_pair_key(item): item for item in ship_flows}
    ship_outbound_by_origin: dict[str, int] = defaultdict(int)
    ship_inbound_by_destination: dict[str, int] = defaultdict(int)
    ship_voyage_outbound_by_origin: dict[str, int] = defaultdict(int)
    for item in ship_flows:
        origin_key, destination_key = flow_pair_key(item)
        ship_outbound_by_origin[origin_key] += item.ship_count or item.active_ship_count or 0
        ship_inbound_by_destination[destination_key] += item.ship_count or item.active_ship_count or 0
        ship_voyage_outbound_by_origin[origin_key] += item.voyage_count or 0
    max_voyage = max([item.voyage_count or 0 for item in ship_flows] or [1])

    for freight in freight_flows:
        same_ship = ship_by_key.get(flow_pair_key(freight))
        reverse_ship = ship_by_key.get(flow_pair_key(freight, reverse=True))
        origin_key, destination_key = flow_pair_key(freight)
        area_capacity = round((ship_outbound_by_origin.get(origin_key, 0) + ship_inbound_by_destination.get(destination_key, 0)) / 2)
        freight.active_ship_count = same_ship.ship_count if same_ship else int(area_capacity or freight.active_ship_count or 0)
        freight.avg_deadweight_ton = same_ship.avg_deadweight_ton if same_ship else None
        freight.ais_freshness_rate = same_ship.ais_freshness_rate if same_ship else None
        freight.ais_freshness_level = same_ship.ais_freshness_level if same_ship else "UNKNOWN"
        freight.return_opportunity_count = reverse_ship.voyage_count if reverse_ship else ship_voyage_outbound_by_origin.get(destination_key, 0)
        freight.route_occupancy_rate = round(min(1.0, (freight.active_ship_count or 0) / max(1, freight.freight_count or 1)), 4)
        freight.empty_return_score = round(min(100.0, ((freight.return_opportunity_count or 0) / max(1, freight.freight_count or 1)) * 100), 2)
        freight.confidence_level = confidence_from_rate(freight.route_occupancy_rate)
        freight.risk_level_code = risk_level_for_flow(freight)
        query = flow_action_query(freight)
        freight.recommended_actions = [
            AnalysisActionBlock(action_code="OPEN_FREIGHT_LIST", title="下钻机会样本", target_route="/freight/list", query=query),
            AnalysisActionBlock(action_code="OPEN_SUPPLY_DEMAND_FIT", title="查看供需适配", target_route="/freight/supply-demand-fit", query=query),
            AnalysisActionBlock(action_code="OPEN_RATE_ESTIMATE", title="运价预估", target_route="/analysis/rate-estimator", query=query),
            AnalysisActionBlock(action_code="OPEN_NORMALIZATION", title="质量治理与回算", target_route="/freight/normalization", query=query),
        ]

    for ship in ship_flows:
        reverse_freight = freight_by_key.get(flow_pair_key(ship, reverse=True))
        reverse_city_freight = freight_by_city_key.get(flow_city_pair_key(ship, reverse=True))
        ship.return_opportunity_count = (
            reverse_freight.freight_count
            if reverse_freight
            else (reverse_city_freight.freight_count if reverse_city_freight else freight_outbound_by_origin_city.get(ship.destination_city_code or "", 0))
        )
        ship.route_occupancy_rate = round((ship.voyage_count or 0) / max(1, max_voyage), 4)
        ship.empty_return_score = round(min(100.0, ((ship.return_opportunity_count or 0) / max(1, ship.voyage_count or 1)) * 100), 2)
        ship.risk_level_code = risk_level_for_flow(ship)
        query = flow_action_query(ship)
        ship.recommended_actions = [
            AnalysisActionBlock(action_code="OPEN_CAPACITY_POOL", title="查看运力池", target_route="/vessels/assets", query=query),
            AnalysisActionBlock(action_code="OPEN_AIS_SITUATION", title="查看 AIS 态势", target_route="/vessels/ais-situation", query=query),
            AnalysisActionBlock(action_code="OPEN_RETURN_FREIGHT", title="查找返程货源", target_route="/freight/list", query=query),
        ]


def flow_corridor_items(items: list[FlowMapItem], *, subject: str, limit: int = 8) -> list[FlowCorridorItem]:
    corridors: list[FlowCorridorItem] = []
    for item in items[:limit]:
        route_status = str(item.route_status_code or item.route_cache_status or "UNKNOWN").upper()
        if subject == "ship":
            summary = (
                f"{item.voyage_count or 0} 航次，{item.active_ship_count or item.ship_count or 0} 艘活跃船，"
                f"AIS 新鲜率 {round((item.ais_freshness_rate or 0) * 100)}%，返程机会 {item.return_opportunity_count or 0} 条"
            )
        else:
            summary = (
                f"{item.freight_count or 0} 条货源，{round(item.tonnage or 0)} 吨，"
                f"适配运力 {item.active_ship_count or 0} 艘，路线状态 {route_status}"
            )
        corridors.append(
            FlowCorridorItem(
                origin_name=item.origin_name,
                destination_name=item.destination_name,
                value=item.value,
                freight_count=item.freight_count,
                ship_count=item.ship_count,
                voyage_count=item.voyage_count,
                tonnage=item.tonnage,
                avg_unit_price=item.avg_unit_price,
                active_ship_count=item.active_ship_count,
                avg_deadweight_ton=item.avg_deadweight_ton,
                ais_freshness_rate=item.ais_freshness_rate,
                route_distance_km=item.route_distance_km,
                route_status_code=item.route_status_code,
                route_occupancy_rate=item.route_occupancy_rate,
                empty_return_score=item.empty_return_score,
                return_opportunity_count=item.return_opportunity_count,
                confidence_level=item.confidence_level,
                risk_level_code=item.risk_level_code,
                summary=summary,
                actions=item.recommended_actions,
            )
        )
    return corridors


def freight_structure_links(freight_flows: list[FlowMapItem], limit: int = 12) -> list[FlowStructureLink]:
    links: list[FlowStructureLink] = []
    for item in freight_flows[:limit]:
        value = item.freight_count or item.value
        links.append(
            FlowStructureLink(
                source=item.origin_name,
                target=item.destination_name,
                value=value,
                source_level_code="ORIGIN_NODE",
                target_level_code="DESTINATION_NODE",
                extra={"tonnage": item.tonnage, "avg_unit_price": item.avg_unit_price},
            )
        )
        if item.commodity_name:
            links.append(
                FlowStructureLink(
                    source=item.destination_name,
                    target=item.commodity_name,
                    value=value,
                    source_level_code="DESTINATION_NODE",
                    target_level_code="COMMODITY",
                    extra={"tonnage": item.tonnage},
                )
            )
    return links


def ship_quality_points(ship_flows: list[FlowMapItem]) -> list[ChartPoint]:
    totals: dict[str, int] = defaultdict(int)
    for item in ship_flows:
        level = item.ais_freshness_level or "UNKNOWN"
        totals[level] += item.active_ship_count or item.ship_count or 0
    labels = {"FRESH": "24h 内新鲜", "RECENT": "1-3 天", "STALE": "3 天以上", "UNKNOWN": "无轨迹/未知"}
    total = sum(totals.values())
    return [
        ChartPoint(name=labels.get(key, key), value=value, ratio=ratio(value, total))
        for key, value in totals.items()
        if value > 0
    ]
