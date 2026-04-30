"""航线规划 E2E 基线数据初始化脚本。"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Iterable

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.address import AdminRegion, NavigationConstraintPoint, Region, RegionBoundaryVersion, TransportNode
from app.models.route import (
    ShippingRoute,
    ShippingRouteLine,
    ShippingRouteLineNode,
    ShippingRouteLineSegment,
    ShippingRouteLineTrack,
    ShippingRoutePlan,
)

E2E_ORIGIN_REGION_CODE = "E2E_ROUTE_ORIGIN"
E2E_DEST_REGION_CODE = "E2E_ROUTE_DEST"
E2E_ROUTE_CODE = "E2E_ROUTE_MAP"
E2E_PLAN_CODE = "E2E_ROUTE_PLAN_MAP"
E2E_LOW_WATER_PLAN_CODE = "E2E_ROUTE_PLAN_LOW_WATER"
E2E_MAIN_LINE_CODE = "E2E_ROUTE_LINE_MAIN"
E2E_DETOUR_LINE_CODE = "E2E_ROUTE_LINE_DETOUR"
E2E_CONSTRAINT_BRIDGE_CODE = "E2E_CONSTRAINT_BRIDGE"
E2E_CONSTRAINT_SHALLOW_CODE = "E2E_CONSTRAINT_SHALLOW"
E2E_LOAD_NODE_CODE = "E2E_ROUTE_LOAD_NODE"
E2E_UNLOAD_NODE_CODE = "E2E_ROUTE_UNLOAD_NODE"


def _polygon_geometry(points: list[list[float]]) -> dict:
    return {"type": "Polygon", "coordinates": [points]}


def _line_geometry(points: list[list[float]]) -> dict:
    return {"type": "LineString", "coordinates": points}


def _as_decimal(value: float | int | str) -> Decimal:
    return Decimal(str(value))


def _center_of_points(points: Iterable[list[float]]) -> tuple[Decimal, Decimal]:
    lng_sum = Decimal("0")
    lat_sum = Decimal("0")
    count = Decimal("0")
    for lng, lat in points:
        lng_sum += _as_decimal(float(lng))
        lat_sum += _as_decimal(float(lat))
        count += Decimal("1")
    if count == 0:
        return Decimal("0"), Decimal("0")
    return lng_sum / count, lat_sum / count


async def _upsert_region(session, *, code: str, name: str, short_name: str, description: str) -> Region:
    row = await session.scalar(select(Region).where(Region.code == code))
    payload = {
        "code": code,
        "name": name,
        "short_name": short_name,
        "region_type_code": "OPERATION_REGION",
        "description": description,
        "sort_order": 9000,
        "status": 1,
    }
    if row is None:
        row = Region(**payload)
        row.audit_status = "APPROVED"
        session.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)
        row.deleted_at = None
        row.audit_status = "APPROVED"
    await session.flush()
    return row


async def _upsert_region_boundary(session, *, region: Region, version_no: int, geometry_json: dict, remark: str) -> None:
    boundary = await session.scalar(
        select(RegionBoundaryVersion).where(
            RegionBoundaryVersion.region_id == region.id,
            RegionBoundaryVersion.version_no == version_no,
        )
    )
    ring = geometry_json.get("coordinates", [[]])[0]
    center_lng, center_lat = _center_of_points(ring[:-1] if len(ring) > 1 else ring)
    payload = {
        "version_no": version_no,
        "boundary_source_type_code": "PLATFORM_DEFINED",
        "geometry_json": geometry_json,
        "center_longitude": center_lng,
        "center_latitude": center_lat,
        "area_km2": Decimal("0"),
        "is_current": True,
        "effective_from": None,
        "effective_to": None,
        "approved_by": None,
        "approved_at": None,
        "remark": remark,
    }
    if boundary is None:
        boundary = RegionBoundaryVersion(region_id=region.id, **payload)
        session.add(boundary)
    else:
        for key, value in payload.items():
            setattr(boundary, key, value)
    await session.flush()
    for item in (await session.execute(select(RegionBoundaryVersion).where(RegionBoundaryVersion.region_id == region.id))).scalars().all():
        item.is_current = item.id == boundary.id
    region.current_boundary_version_id = boundary.id
    await session.flush()


async def _upsert_route(session, *, origin_region_id: int, destination_region_id: int) -> ShippingRoute:
    row = await session.scalar(select(ShippingRoute).where(ShippingRoute.code == E2E_ROUTE_CODE))
    payload = {
        "code": E2E_ROUTE_CODE,
        "name": "E2E测试航线-苏州至靖江",
        "transport_org_type_code": "SINGLE_MODE",
        "multimodal_combination_code": None,
        "origin_region_id": origin_region_id,
        "destination_region_id": destination_region_id,
        "description": "E2E 航线规划与路线设计测试基线数据",
    }
    if row is None:
        row = ShippingRoute(**payload)
        row.audit_status = "APPROVED"
        session.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)
        row.deleted_at = None
        row.audit_status = "APPROVED"
    await session.flush()
    return row


async def _seed_city_region(session) -> AdminRegion:
    row = await session.scalar(select(AdminRegion).where(AdminRegion.level == 2).order_by(AdminRegion.id.asc()))
    if row is None:
        raise RuntimeError("admin_region city data not found, run seed_admin_regions first")
    return row


async def _upsert_transport_node(
    session,
    *,
    code: str,
    name: str,
    longitude: Decimal,
    latitude: Decimal,
) -> TransportNode:
    city = await _seed_city_region(session)
    row = await session.scalar(select(TransportNode).where(TransportNode.code == code))
    payload = {
        "code": code,
        "name": name,
        "short_name": name,
        "node_type_code": "PORT",
        "province_code": city.province_code or "410000",
        "city_code": city.city_code or city.code,
        "district_code": None,
        "city_region_id": city.id,
        "address": "E2E 航线规划测试运输节点",
        "longitude": longitude,
        "latitude": latitude,
        "status": 1,
        "lifecycle_status_code": "ACTIVE",
        "sort_order": 9000,
        "is_hot_node": True,
    }
    if row is None:
        row = TransportNode(**payload)
        row.audit_status = "APPROVED"
        session.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)
        row.deleted_at = None
        row.audit_status = "APPROVED"
    await session.flush()
    return row


async def _upsert_plan(session, *, route_id: int, code: str, name: str, plan_type: str, remark: str) -> ShippingRoutePlan:
    row = await session.scalar(select(ShippingRoutePlan).where(ShippingRoutePlan.plan_code == code))
    payload = {
        "route_id": route_id,
        "plan_code": code,
        "plan_name": name,
        "plan_type_code": plan_type,
        "description": remark,
        "remark": remark,
    }
    if row is None:
        row = ShippingRoutePlan(**payload)
        session.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)
    await session.flush()
    return row


async def _upsert_line(session, *, plan_id: int, code: str, name: str, role: str, priority: int, trigger: str | None) -> ShippingRouteLine:
    row = await session.scalar(select(ShippingRouteLine).where(ShippingRouteLine.plan_id == plan_id, ShippingRouteLine.line_code == code))
    payload = {
        "line_code": code,
        "line_name": name,
        "line_role_code": role,
        "priority": priority,
        "trigger_condition": trigger,
        "description": trigger,
        "track_status": "READY",
        "track_generated_at": None,
    }
    if row is None:
        row = ShippingRouteLine(plan_id=plan_id, **payload)
        session.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)
    await session.flush()
    return row


async def _replace_line_structure(session, *, line: ShippingRouteLine, nodes_payload: list[dict], segment_modes: list[str], track_points: list[list[float]]) -> None:
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
    for idx, mode in enumerate(segment_modes, start=1):
        session.add(
            ShippingRouteLineSegment(
                line_id=line.id,
                segment_no=idx,
                start_line_node_id=nodes[idx - 1].id,
                end_line_node_id=nodes[idx].id,
                transport_mode_code=mode,
                distance_km=Decimal("0"),
                estimated_duration_hour=Decimal("0"),
                segment_track_status="READY",
                geometry_source="FALLBACK",
                geometry_json=_line_geometry([track_points[idx - 1], track_points[idx]]),
                remark="E2E 路线段轨迹快照",
            )
        )
    session.add(
        ShippingRouteLineTrack(
            line_id=line.id,
            track_status="READY",
            geometry_json=_line_geometry(track_points),
            distance_km=Decimal("0"),
            estimated_duration_hour=Decimal("0"),
            provider_summary_json={"seed": "E2E_READY_TRACK", "source": "FALLBACK"},
            error_message=None,
            generated_at=None,
        )
    )
    line.track_status = "READY"
    await session.flush()


async def seed_route_map_e2e() -> None:
    origin_polygon = _polygon_geometry([[120.50, 31.25], [120.70, 31.25], [120.70, 31.40], [120.50, 31.40], [120.50, 31.25]])
    dest_polygon = _polygon_geometry([[120.15, 31.45], [120.40, 31.45], [120.40, 31.65], [120.15, 31.65], [120.15, 31.45]])
    async with AsyncSessionLocal() as session:
        origin_region = await _upsert_region(session, code=E2E_ORIGIN_REGION_CODE, name="E2E测试起点区域", short_name="E2E起点", description="E2E 航线起点区域")
        dest_region = await _upsert_region(session, code=E2E_DEST_REGION_CODE, name="E2E测试终点区域", short_name="E2E终点", description="E2E 航线终点区域")
        await _upsert_region_boundary(session, region=origin_region, version_no=1, geometry_json=origin_polygon, remark="E2E 起点区域边界")
        await _upsert_region_boundary(session, region=dest_region, version_no=1, geometry_json=dest_polygon, remark="E2E 终点区域边界")
        bridge = await session.scalar(select(NavigationConstraintPoint).where(NavigationConstraintPoint.code == E2E_CONSTRAINT_BRIDGE_CODE))
        shallow = await session.scalar(select(NavigationConstraintPoint).where(NavigationConstraintPoint.code == E2E_CONSTRAINT_SHALLOW_CODE))
        if bridge is None or shallow is None:
            raise RuntimeError("E2E constraint points not found, run seed_navigation_constraints first")
        load_node = await _upsert_transport_node(
            session,
            code=E2E_LOAD_NODE_CODE,
            name="E2E装货运输节点A",
            longitude=_as_decimal(120.58),
            latitude=_as_decimal(31.30),
        )
        unload_node = await _upsert_transport_node(
            session,
            code=E2E_UNLOAD_NODE_CODE,
            name="E2E卸货运输节点C",
            longitude=_as_decimal(120.28),
            latitude=_as_decimal(31.56),
        )
        route = await _upsert_route(session, origin_region_id=origin_region.id, destination_region_id=dest_region.id)
        standard_plan = await _upsert_plan(session, route_id=route.id, code=E2E_PLAN_CODE, name="E2E标准运输方案", plan_type="STANDARD", remark="E2E 标准路线方案")
        low_water_plan = await _upsert_plan(session, route_id=route.id, code=E2E_LOW_WATER_PLAN_CODE, name="E2E低水位绕行方案", plan_type="SEASONAL", remark="E2E 低水位绕行路线方案")
        main_line = await _upsert_line(session, plan_id=standard_plan.id, code=E2E_MAIN_LINE_CODE, name="E2E主路线", role="MAIN", priority=1, trigger="正常水位通行")
        detour_line = await _upsert_line(session, plan_id=low_water_plan.id, code=E2E_DETOUR_LINE_CODE, name="E2E低水位绕行路线", role="DETOUR", priority=1, trigger="低水位或闸口封航时使用")
        await _replace_line_structure(
            session,
            line=main_line,
            nodes_payload=[
                {"node_type_code": "TRANSPORT_NODE", "transport_node_id": load_node.id, "display_name": "E2E装货运输节点A", "remark": "E2E 起点运输节点"},
                {"node_type_code": "CONSTRAINT_POINT", "constraint_point_id": bridge.id, "display_name": "E2E桥梁约束点", "remark": "E2E 桥梁约束"},
                {"node_type_code": "TRANSPORT_NODE", "transport_node_id": unload_node.id, "display_name": "E2E卸货运输节点C", "remark": "E2E 终点运输节点"},
            ],
            segment_modes=["WATER", "WATER"],
            track_points=[[120.58, 31.30], [120.44, 31.42], [120.28, 31.56]],
        )
        await _replace_line_structure(
            session,
            line=detour_line,
            nodes_payload=[
                {"node_type_code": "MANUAL_POINT", "manual_name": "E2E备用装货点A", "longitude": _as_decimal(120.57), "latitude": _as_decimal(31.29), "display_name": "E2E备用装货点A", "remark": "E2E 备用手工起点"},
                {"node_type_code": "CONSTRAINT_POINT", "constraint_point_id": shallow.id, "display_name": "E2E浅滩水深约束点", "remark": "E2E 浅滩约束"},
                {"node_type_code": "MANUAL_POINT", "manual_name": "E2E绕行卸货点C", "longitude": _as_decimal(120.30), "latitude": _as_decimal(31.60), "display_name": "E2E绕行卸货点C", "remark": "E2E 绕行手工终点"},
            ],
            segment_modes=["WATER", "WATER"],
            track_points=[[120.57, 31.29], [120.34, 31.50], [120.30, 31.60]],
        )
        await session.commit()
        print("[seed_route_map_e2e] route_code=%s plans=2 lines=2" % route.code)


if __name__ == "__main__":
    asyncio.run(seed_route_map_e2e())
