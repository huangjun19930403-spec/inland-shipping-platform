from __future__ import annotations

from app.modules.analysis.flow_workbench import enrich_flow_relationships, flow_corridor_items
from app.modules.analysis.schemas import FlowMapItem


def test_flow_relationships_add_capacity_return_actions_and_risk() -> None:
    freight = [
        FlowMapItem(
            origin_id=1,
            origin_name="太仓港",
            destination_id=2,
            destination_name="芜湖朱家桥",
            value=12,
            freight_count=12,
            tonnage=36000,
            route_status_code="READY",
        )
    ]
    ship = [
        FlowMapItem(
            origin_id=1,
            origin_name="太仓港",
            destination_id=2,
            destination_name="芜湖朱家桥",
            value=20,
            ship_count=8,
            active_ship_count=8,
            voyage_count=20,
            avg_deadweight_ton=3200,
            ais_freshness_rate=0.9,
            ais_freshness_level="FRESH",
            confidence_level="HIGH",
            route_status_code="READY",
        ),
        FlowMapItem(
            origin_id=2,
            origin_name="芜湖朱家桥",
            destination_id=1,
            destination_name="太仓港",
            value=10,
            ship_count=5,
            active_ship_count=5,
            voyage_count=10,
            avg_deadweight_ton=2800,
            ais_freshness_rate=0.7,
            ais_freshness_level="RECENT",
            confidence_level="MEDIUM",
            route_status_code="READY",
        ),
    ]

    enrich_flow_relationships(freight, ship)

    assert freight[0].active_ship_count == 8
    assert freight[0].return_opportunity_count == 10
    assert freight[0].route_occupancy_rate is not None
    assert {action.action_code for action in freight[0].recommended_actions} >= {
        "OPEN_FREIGHT_LIST",
        "OPEN_SUPPLY_DEMAND_FIT",
        "OPEN_RATE_ESTIMATE",
    }
    assert ship[0].return_opportunity_count == 0
    assert ship[1].route_occupancy_rate == 0.5
    assert ship[0].risk_level_code == "LOW"


def test_flow_corridor_items_surface_vessel_decision_metrics() -> None:
    items = [
        FlowMapItem(
            origin_name="南京龙潭",
            destination_name="苏州太仓",
            value=18,
            ship_count=7,
            active_ship_count=7,
            voyage_count=18,
            avg_deadweight_ton=2600,
            ais_freshness_rate=0.62,
            return_opportunity_count=9,
            route_occupancy_rate=0.8,
            confidence_level="MEDIUM",
            risk_level_code="MEDIUM",
        )
    ]

    corridors = flow_corridor_items(items, subject="ship")

    assert corridors[0].origin_name == "南京龙潭"
    assert corridors[0].avg_deadweight_ton == 2600
    assert corridors[0].ais_freshness_rate == 0.62
    assert corridors[0].return_opportunity_count == 9
    assert "AIS 新鲜率" in corridors[0].summary
