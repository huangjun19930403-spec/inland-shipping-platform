"""航线地图 E2E 基线数据初始化脚本。"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Iterable

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.address import Region, RegionBoundaryVersion
from app.models.route import (
    ShippingRoute,
    ShippingRoutePlan,
    ShippingRoutePlanSegment,
    ShippingRoutePlanSegmentPoint,
)

E2E_ORIGIN_REGION_CODE = "E2E_ROUTE_ORIGIN"
E2E_DEST_REGION_CODE = "E2E_ROUTE_DEST"
E2E_ROUTE_CODE = "E2E_ROUTE_MAP"
E2E_PLAN_CODE = "E2E_ROUTE_PLAN_MAP"


def _polygon_geometry(points: list[list[float]]) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [points],
    }


def _line_geometry(points: list[list[float]]) -> dict:
    return {
        "type": "LineString",
        "coordinates": points,
    }


def _as_decimal(value: float) -> Decimal:
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
    return (lng_sum / count, lat_sum / count)


async def _upsert_region(
    session,
    *,
    code: str,
    name: str,
    short_name: str,
    description: str,
) -> Region:
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
        row.submitter_id = None
        row.auditor_id = None
        row.audited_at = None
        session.add(row)
        await session.flush()
    else:
        for key, value in payload.items():
            setattr(row, key, value)
        row.deleted_at = None
        row.audit_status = "APPROVED"
        row.submitter_id = None
        row.auditor_id = None
        row.audited_at = None
        await session.flush()
    return row


async def _upsert_region_boundary(
    session,
    *,
    region: Region,
    version_no: int,
    geometry_json: dict,
    remark: str,
) -> RegionBoundaryVersion:
    boundary = await session.scalar(
        select(RegionBoundaryVersion).where(
            RegionBoundaryVersion.region_id == region.id,
            RegionBoundaryVersion.version_no == version_no,
        )
    )

    coordinates = geometry_json.get("coordinates")
    ring = coordinates[0] if isinstance(coordinates, list) and coordinates else []
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
        await session.flush()
    else:
        for key, value in payload.items():
            setattr(boundary, key, value)
        await session.flush()

    boundaries = (
        (
            await session.execute(
                select(RegionBoundaryVersion).where(RegionBoundaryVersion.region_id == region.id)
            )
        )
        .scalars()
        .all()
    )
    for item in boundaries:
        item.is_current = item.id == boundary.id

    region.current_boundary_version_id = boundary.id
    await session.flush()
    return boundary


async def _upsert_route(
    session,
    *,
    origin_region_id: int,
    destination_region_id: int,
) -> ShippingRoute:
    row = await session.scalar(select(ShippingRoute).where(ShippingRoute.code == E2E_ROUTE_CODE))
    payload = {
        "code": E2E_ROUTE_CODE,
        "name": "E2E测试航线-苏州至无锡",
        "transport_org_type_code": "SINGLE_MODE",
        "multimodal_combination_code": None,
        "origin_region_id": origin_region_id,
        "destination_region_id": destination_region_id,
        "description": "E2E 航线地图联动测试基线数据",
        "status": 1,
        "sort_order": 9000,
    }
    if row is None:
        row = ShippingRoute(**payload)
        row.audit_status = "APPROVED"
        row.submitter_id = None
        row.auditor_id = None
        row.audited_at = None
        session.add(row)
        await session.flush()
    else:
        for key, value in payload.items():
            setattr(row, key, value)
        row.deleted_at = None
        row.audit_status = "APPROVED"
        row.submitter_id = None
        row.auditor_id = None
        row.audited_at = None
        await session.flush()
    return row


async def _upsert_plan(session, *, route_id: int) -> ShippingRoutePlan:
    row = await session.scalar(select(ShippingRoutePlan).where(ShippingRoutePlan.plan_code == E2E_PLAN_CODE))
    payload = {
        "route_id": route_id,
        "plan_code": E2E_PLAN_CODE,
        "plan_name": "E2E测试路径方案",
        "version_no": 1,
        "plan_type_code": "STANDARD",
        "total_distance_km": Decimal("0"),
        "estimated_duration_hour": Decimal("0"),
        "effective_from": None,
        "effective_to": None,
        "status": 1,
        "is_default": True,
        "remark": "E2E 航线地图联动测试基线方案",
    }
    if row is None:
        row = ShippingRoutePlan(**payload)
        session.add(row)
        await session.flush()
    else:
        for key, value in payload.items():
            setattr(row, key, value)
        await session.flush()

    plans = (
        (
            await session.execute(
                select(ShippingRoutePlan).where(ShippingRoutePlan.route_id == route_id)
            )
        )
        .scalars()
        .all()
    )
    for item in plans:
        item.is_default = item.id == row.id
    await session.flush()
    return row


async def _upsert_segment(
    session,
    *,
    plan_id: int,
    segment_no: int,
    geometry_json: dict | None,
    sort_order: int,
    remark: str,
) -> ShippingRoutePlanSegment:
    row = await session.scalar(
        select(ShippingRoutePlanSegment).where(
            ShippingRoutePlanSegment.plan_id == plan_id,
            ShippingRoutePlanSegment.segment_no == segment_no,
        )
    )
    payload = {
        "segment_no": segment_no,
        "segment_type_code": "NAVIGATION_SEGMENT",
        "start_node_id": None,
        "end_node_id": None,
        "start_constraint_point_id": None,
        "end_constraint_point_id": None,
        "distance_km": Decimal("0"),
        "estimated_duration_hour": Decimal("0"),
        "geometry_json": geometry_json,
        "sort_order": sort_order,
        "remark": remark,
    }
    if row is None:
        row = ShippingRoutePlanSegment(plan_id=plan_id, **payload)
        session.add(row)
        await session.flush()
    else:
        for key, value in payload.items():
            setattr(row, key, value)
        await session.flush()
    return row


async def _upsert_point(
    session,
    *,
    segment_id: int,
    point_no: int,
    longitude: float,
    latitude: float,
    remark: str,
) -> ShippingRoutePlanSegmentPoint:
    row = await session.scalar(
        select(ShippingRoutePlanSegmentPoint).where(
            ShippingRoutePlanSegmentPoint.segment_id == segment_id,
            ShippingRoutePlanSegmentPoint.point_no == point_no,
        )
    )
    payload = {
        "point_no": point_no,
        "point_type_code": "NODE",
        "related_node_id": None,
        "related_constraint_point_id": None,
        "longitude": _as_decimal(longitude),
        "latitude": _as_decimal(latitude),
        "stay_minutes": 0,
        "remark": remark,
    }
    if row is None:
        row = ShippingRoutePlanSegmentPoint(segment_id=segment_id, **payload)
        session.add(row)
        await session.flush()
    else:
        for key, value in payload.items():
            setattr(row, key, value)
        await session.flush()
    return row


async def seed_route_map_e2e() -> None:
    origin_polygon = _polygon_geometry(
        [
            [120.50, 31.25],
            [120.70, 31.25],
            [120.70, 31.40],
            [120.50, 31.40],
            [120.50, 31.25],
        ]
    )
    destination_polygon = _polygon_geometry(
        [
            [120.15, 31.45],
            [120.40, 31.45],
            [120.40, 31.65],
            [120.15, 31.65],
            [120.15, 31.45],
        ]
    )

    segment1_line = _line_geometry(
        [
            [120.58, 31.30],
            [120.52, 31.36],
            [120.44, 31.42],
        ]
    )

    segment1_points = [
        (1, 120.58, 31.30),
        (2, 120.52, 31.36),
        (3, 120.44, 31.42),
    ]
    segment2_points = [
        (1, 120.44, 31.42),
        (2, 120.34, 31.50),
        (3, 120.28, 31.56),
    ]

    async with AsyncSessionLocal() as session:
        origin_region = await _upsert_region(
            session,
            code=E2E_ORIGIN_REGION_CODE,
            name="E2E测试起点区域",
            short_name="E2E起点",
            description="E2E 航线地图联动测试起点区域",
        )
        dest_region = await _upsert_region(
            session,
            code=E2E_DEST_REGION_CODE,
            name="E2E测试终点区域",
            short_name="E2E终点",
            description="E2E 航线地图联动测试终点区域",
        )

        await _upsert_region_boundary(
            session,
            region=origin_region,
            version_no=1,
            geometry_json=origin_polygon,
            remark="E2E 起点区域边界",
        )
        await _upsert_region_boundary(
            session,
            region=dest_region,
            version_no=1,
            geometry_json=destination_polygon,
            remark="E2E 终点区域边界",
        )

        route = await _upsert_route(
            session,
            origin_region_id=origin_region.id,
            destination_region_id=dest_region.id,
        )
        plan = await _upsert_plan(session, route_id=route.id)

        segment1 = await _upsert_segment(
            session,
            plan_id=plan.id,
            segment_no=1,
            geometry_json=segment1_line,
            sort_order=1,
            remark="E2E 航段1（含 geometry）",
        )
        segment2 = await _upsert_segment(
            session,
            plan_id=plan.id,
            segment_no=2,
            geometry_json=None,
            sort_order=2,
            remark="E2E 航段2（点位 fallback）",
        )

        for point_no, lng, lat in segment1_points:
            await _upsert_point(
                session,
                segment_id=segment1.id,
                point_no=point_no,
                longitude=lng,
                latitude=lat,
                remark="E2E 航段1 点位",
            )
        for point_no, lng, lat in segment2_points:
            await _upsert_point(
                session,
                segment_id=segment2.id,
                point_no=point_no,
                longitude=lng,
                latitude=lat,
                remark="E2E 航段2 点位",
            )

        await session.commit()

        segment_rows = (
            (
                await session.execute(
                    select(ShippingRoutePlanSegment).where(ShippingRoutePlanSegment.plan_id == plan.id)
                )
            )
            .scalars()
            .all()
        )
        point_count = 0
        for item in segment_rows:
            point_count += len(
                (
                    (
                        await session.execute(
                            select(ShippingRoutePlanSegmentPoint).where(
                                ShippingRoutePlanSegmentPoint.segment_id == item.id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            )

        print(
            "[seed_route_map_e2e] "
            f"route_code={route.code} plan_code={plan.plan_code} "
            f"segment_count={len(segment_rows)} point_count={point_count}"
        )


if __name__ == "__main__":
    asyncio.run(seed_route_map_e2e())
