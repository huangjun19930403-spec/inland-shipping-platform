"""航线规划真实感样例 seed。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.address import NavigationConstraintPoint, Region, TransportNode
from app.models.route import (
    ShippingRoute,
    ShippingRouteLine,
    ShippingRouteLineNode,
    ShippingRouteLineSegment,
    ShippingRouteLineTrack,
    ShippingRoutePlan,
)


def _decimal(value: str | float) -> Decimal:
    return Decimal(str(value))


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


async def _upsert_route(session, payload: dict[str, Any]) -> ShippingRoute:
    row = await session.scalar(select(ShippingRoute).where(ShippingRoute.code == payload["code"]))
    if row is None:
        row = ShippingRoute(**payload)
        session.add(row)
        await session.flush()
    else:
        for key, value in payload.items():
            setattr(row, key, value)
        await session.flush()
    return row


async def _upsert_plan(session, payload: dict[str, Any]) -> ShippingRoutePlan:
    row = await session.scalar(select(ShippingRoutePlan).where(ShippingRoutePlan.plan_code == payload["plan_code"]))
    if row is None:
        row = ShippingRoutePlan(**payload)
        session.add(row)
        await session.flush()
    else:
        for key, value in payload.items():
            setattr(row, key, value)
        await session.flush()
    return row


async def _upsert_line(session, payload: dict[str, Any]) -> ShippingRouteLine:
    row = await session.scalar(
        select(ShippingRouteLine).where(
            ShippingRouteLine.plan_id == payload["plan_id"],
            ShippingRouteLine.line_code == payload["line_code"],
        )
    )
    if row is None:
        row = ShippingRouteLine(**payload)
        session.add(row)
        await session.flush()
    else:
        for key, value in payload.items():
            setattr(row, key, value)
        await session.flush()
    return row


async def _replace_line_structure(
    session,
    *,
    line: ShippingRouteLine,
    nodes_payload: list[dict[str, Any]],
    tracks: list[list[float]],
) -> None:
    await session.execute(delete(ShippingRouteLineTrack).where(ShippingRouteLineTrack.line_id == line.id))
    await session.execute(delete(ShippingRouteLineSegment).where(ShippingRouteLineSegment.line_id == line.id))
    await session.execute(delete(ShippingRouteLineNode).where(ShippingRouteLineNode.line_id == line.id))
    await session.flush()

    nodes: list[ShippingRouteLineNode] = []
    for idx, payload in enumerate(nodes_payload, start=1):
        row = ShippingRouteLineNode(line_id=line.id, node_order=idx, **payload)
        session.add(row)
        nodes.append(row)
    await session.flush()

    for idx in range(len(nodes) - 1):
        start = nodes[idx]
        end = nodes[idx + 1]
        session.add(
            ShippingRouteLineSegment(
                line_id=line.id,
                segment_no=idx + 1,
                start_line_node_id=start.id,
                end_line_node_id=end.id,
                transport_mode_code="WATERWAY",
                distance_km=Decimal("78.00") + Decimal(idx * 32),
                estimated_duration_hour=Decimal("7.50") + Decimal(idx * 2),
                segment_track_status="GENERATED",
                geometry_source="LOCAL_SAMPLE",
                geometry_json={"type": "LineString", "coordinates": [tracks[idx], tracks[idx + 1]]},
                remark="本地验证预制航段",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )

    session.add(
        ShippingRouteLineTrack(
            line_id=line.id,
            track_status="GENERATED",
            geometry_json={"type": "LineString", "coordinates": tracks},
            distance_km=Decimal("315.00"),
            estimated_duration_hour=Decimal("31.00"),
            provider_summary_json={"seed": "LOCAL_ROUTE_SAMPLE", "source": "FOUNDATION_DATA"},
            error_message=None,
            generated_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )
    line.track_status = "GENERATED"
    line.track_generated_at = datetime.utcnow()
    await session.flush()


async def seed_route_samples() -> None:
    async with AsyncSessionLocal() as session:
        origin_region = await _region(session, "REGION_YANGTZE_DELTA")
        destination_region = await _region(session, "REGION_WANJIANG")
        taicang = await _node(session, "NODE_SUZHOU_TAICANG_PORT")
        jiangyin = await _node(session, "NODE_WX_JIANGYIN_PORT")
        longtan = await _node(session, "NODE_NJ_LONGTAN_PORT")
        wuhu = await _node(session, "NODE_WUHU_ZHUJIAQIAO_PORT")
        bridge = await _constraint(session, "NC_JIANGYIN_BRIDGE_CLEARANCE")

        route = await _upsert_route(
            session,
            {
                "code": "ROUTE_TAICANG_WUHU",
                "name": "太仓港至芜湖矿建材料航线",
                "transport_org_type_code": "DIRECT_WATERWAY",
                "multimodal_combination_code": "WATERWAY",
                "origin_region_id": origin_region.id,
                "destination_region_id": destination_region.id,
                "description": "长江下游至皖江矿建材料常用内河运输线路。",
                "audit_status": "APPROVED",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            },
        )
        plan = await _upsert_plan(
            session,
            {
                "route_id": route.id,
                "plan_code": "PLAN_TAICANG_WUHU_STD",
                "plan_name": "太仓至芜湖标准水运方案",
                "plan_type_code": "MANUAL",
                "description": "经江阴、南京龙潭至芜湖朱家桥。",
                "remark": "本地验证预制方案",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            },
        )
        line = await _upsert_line(
            session,
            {
                "plan_id": plan.id,
                "line_code": "LINE_TAICANG_WUHU_MAIN",
                "line_name": "太仓-江阴-龙潭-芜湖主线",
                "line_role_code": "MAIN",
                "priority": 1,
                "trigger_condition": "常水位和常规船型默认使用",
                "description": "本地验证预制主路线。",
                "track_status": "GENERATED",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            },
        )
        nodes_payload = [
            {
                "node_type_code": "TRANSPORT_NODE",
                "transport_node_id": taicang.id,
                "display_name": taicang.name,
                "remark": "装货港",
            },
            {
                "node_type_code": "CONSTRAINT_POINT",
                "constraint_point_id": bridge.id,
                "display_name": bridge.name,
                "remark": "桥区净空复核",
            },
            {
                "node_type_code": "TRANSPORT_NODE",
                "transport_node_id": jiangyin.id,
                "display_name": jiangyin.name,
                "remark": "中转/候泊节点",
            },
            {
                "node_type_code": "TRANSPORT_NODE",
                "transport_node_id": longtan.id,
                "display_name": longtan.name,
                "remark": "下游港口节点",
            },
            {
                "node_type_code": "TRANSPORT_NODE",
                "transport_node_id": wuhu.id,
                "display_name": wuhu.name,
                "remark": "卸货港",
            },
        ]
        tracks = [
            [float(taicang.longitude), float(taicang.latitude)],
            [float(bridge.longitude), float(bridge.latitude)],
            [float(jiangyin.longitude), float(jiangyin.latitude)],
            [float(longtan.longitude), float(longtan.latitude)],
            [float(wuhu.longitude), float(wuhu.latitude)],
        ]
        await _replace_line_structure(session, line=line, nodes_payload=nodes_payload, tracks=tracks)
        await session.commit()

    print("seed_route_samples completed: route_code=ROUTE_TAICANG_WUHU")


if __name__ == "__main__":
    asyncio.run(seed_route_samples())
