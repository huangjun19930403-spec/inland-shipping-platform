"""Route graph seed for Round 11 experience scenarios."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import delete, select

from app.models.route import (
    ShippingRoute,
    ShippingRouteLine,
    ShippingRouteLineNode,
    ShippingRouteLineSegment,
    ShippingRouteLineTrack,
    ShippingRoutePlan,
)
from scripts.seeds.demo.experience.shared import (
    ROUTES,
    SCENARIO_VERSION,
    RouteDef,
    RouteInfo,
    _constraint,
    _coord,
    _distance_km,
    _geometry,
    _node,
    _region,
)

async def _replace_route_graph(session, route_def: RouteDef, now: datetime) -> RouteInfo:
    origin_region = await _region(session, route_def.origin_region_code)
    destination_region = await _region(session, route_def.destination_region_code)
    route = await session.scalar(select(ShippingRoute).where(ShippingRoute.code == route_def.code))
    route_payload = {
        "code": route_def.code,
        "name": route_def.name,
        "transport_org_type_code": "DIRECT_WATERWAY",
        "multimodal_combination_code": "WATERWAY",
        "origin_region_id": origin_region.id,
        "destination_region_id": destination_region.id,
        "description": "Round 11 local-demo scenario route with explicit segment geometry and evidence.",
        "audit_status": "APPROVED",
        "audited_at": now,
        "deleted_at": None,
        "updated_at": now,
    }
    if route is None:
        route = ShippingRoute(created_at=now, **route_payload)
        session.add(route)
        await session.flush()
    else:
        for key, value in route_payload.items():
            setattr(route, key, value)
        await session.flush()

    plan_ids = (
        await session.execute(select(ShippingRoutePlan.id).where(ShippingRoutePlan.route_id == route.id))
    ).scalars().all()
    if plan_ids:
        line_ids = (
            await session.execute(select(ShippingRouteLine.id).where(ShippingRouteLine.plan_id.in_(plan_ids)))
        ).scalars().all()
        if line_ids:
            await session.execute(delete(ShippingRouteLineTrack).where(ShippingRouteLineTrack.line_id.in_(line_ids)))
            await session.execute(delete(ShippingRouteLineSegment).where(ShippingRouteLineSegment.line_id.in_(line_ids)))
            await session.execute(delete(ShippingRouteLineNode).where(ShippingRouteLineNode.line_id.in_(line_ids)))
            await session.execute(delete(ShippingRouteLine).where(ShippingRouteLine.id.in_(line_ids)))
        await session.execute(delete(ShippingRoutePlan).where(ShippingRoutePlan.id.in_(plan_ids)))
        await session.flush()

    plan = ShippingRoutePlan(
        route_id=route.id,
        plan_code=route_def.plan_code,
        plan_name=route_def.name,
        plan_type_code="LOCAL_DEMO",
        description="Round 11 场景化体验航线方案。",
        remark="仅用于 local-demo 体验，不进入 production 分析口径。",
        created_at=now,
        updated_at=now,
    )
    session.add(plan)
    await session.flush()
    line = ShippingRouteLine(
        plan_id=plan.id,
        line_code=route_def.line_code,
        line_name=route_def.line_name,
        line_role_code="MAIN",
        priority=1,
        trigger_condition="local-demo scenario route",
        description="Round 11 场景化体验航线主线。",
        track_status="READY",
        track_generated_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(line)
    await session.flush()

    line_nodes: list[ShippingRouteLineNode] = []
    coords: list[tuple[Decimal, Decimal]] = []
    for order, code in enumerate(route_def.node_codes, start=1):
        if code.startswith("NC_"):
            constraint = await _constraint(session, code)
            lng, lat = _coord(constraint.longitude), _coord(constraint.latitude)
            row = ShippingRouteLineNode(
                line_id=line.id,
                node_order=order,
                node_type_code="CONSTRAINT_POINT",
                constraint_point_id=constraint.id,
                longitude=lng,
                latitude=lat,
                display_name=constraint.name,
                remark="通航约束复核点",
                created_at=now,
                updated_at=now,
            )
        else:
            node = await _node(session, code)
            lng, lat = _coord(node.longitude), _coord(node.latitude)
            row = ShippingRouteLineNode(
                line_id=line.id,
                node_order=order,
                node_type_code="TRANSPORT_NODE",
                transport_node_id=node.id,
                longitude=lng,
                latitude=lat,
                display_name=node.name,
                remark="运输节点",
                created_at=now,
                updated_at=now,
            )
        coords.append((lng, lat))
        session.add(row)
        line_nodes.append(row)
    await session.flush()

    segments: list[ShippingRouteLineSegment] = []
    total_distance = Decimal("0.00")
    for index in range(len(line_nodes) - 1):
        start = line_nodes[index]
        end = line_nodes[index + 1]
        distance = _distance_km(coords[index], coords[index + 1])
        total_distance += distance
        segment = ShippingRouteLineSegment(
            line_id=line.id,
            segment_no=index + 1,
            start_line_node_id=start.id,
            end_line_node_id=end.id,
            transport_mode_code="WATER",
            distance_km=distance,
            estimated_duration_hour=(distance / Decimal("9.5")).quantize(Decimal("0.01")),
            segment_track_status="READY",
            geometry_source="MANUAL",
            geometry_json=_geometry([coords[index], coords[index + 1]], source="LOCAL_DEMO", name=f"{start.display_name}-{end.display_name}"),
            remark="Round 11 local-demo 预制航段轨迹，用于体验航线段匹配。",
            created_at=now,
            updated_at=now,
        )
        session.add(segment)
        segments.append(segment)
    await session.flush()
    session.add(
        ShippingRouteLineTrack(
            line_id=line.id,
            track_status="READY",
            geometry_json=_geometry(coords, source="LOCAL_DEMO", name=line.line_name),
            distance_km=total_distance,
            estimated_duration_hour=(total_distance / Decimal("9.5")).quantize(Decimal("0.01")),
            provider_summary_json={
                "provider": "LOCAL_DEMO",
                "source": SCENARIO_VERSION,
                "real_route_note": "production route evidence must come from configured provider, not this demo geometry",
            },
            generated_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    await session.flush()
    return RouteInfo(key=route_def.key, route=route, line=line, segments=segments)


async def _seed_routes(session, now: datetime) -> dict[str, RouteInfo]:
    routes: dict[str, RouteInfo] = {}
    for route_def in ROUTES:
        routes[route_def.key] = await _replace_route_graph(session, route_def, now)
    return routes
