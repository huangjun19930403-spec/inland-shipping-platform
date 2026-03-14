"""航线服务"""
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from fastapi import HTTPException

from app.models.route import ShippingRoute, ShippingRoutePath
from app.schemas.route import ShippingRouteCreate, ShippingRouteUpdate, ShippingRoutePathCreate
from app.schemas.common import PageResult


async def get_routes(
    db: AsyncSession,
    origin_region_id: Optional[int] = None,
    dest_region_id: Optional[int] = None,
    status: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    from sqlalchemy import func
    query = select(ShippingRoute)
    count_query = select(func.count(ShippingRoute.id))
    conditions = []
    if origin_region_id:
        conditions.append(ShippingRoute.origin_region_id == origin_region_id)
    if dest_region_id:
        conditions.append(ShippingRoute.dest_region_id == dest_region_id)
    if status is not None:
        conditions.append(ShippingRoute.status == status)
    if conditions:
        query = query.where(and_(*conditions))
        count_query = count_query.where(and_(*conditions))

    total_res = await db.execute(count_query)
    total = total_res.scalar_one()
    query = query.order_by(ShippingRoute.sort_order, ShippingRoute.id)
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return PageResult(total=total, items=list(result.scalars().all()), page=page, page_size=page_size)


async def get_route(db: AsyncSession, route_id: int) -> ShippingRoute:
    result = await db.execute(select(ShippingRoute).where(ShippingRoute.id == route_id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="航线不存在")
    return obj


async def create_route(
    db: AsyncSession, data: ShippingRouteCreate, creator_id: int
) -> ShippingRoute:
    # Validate origin != dest
    if data.origin_region_id == data.dest_region_id:
        raise HTTPException(status_code=400, detail="起始区域和目的区域不能相同")

    # Check code uniqueness
    res = await db.execute(select(ShippingRoute).where(ShippingRoute.code == data.code))
    if res.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="航线编码已存在")

    # Check route uniqueness by region pair
    res = await db.execute(
        select(ShippingRoute).where(
            and_(
                ShippingRoute.origin_region_id == data.origin_region_id,
                ShippingRoute.dest_region_id == data.dest_region_id,
            )
        )
    )
    if res.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该起终点区域对的航线已存在")

    path_nodes_data = data.path_nodes or []
    route_data = data.model_dump(exclude={"path_nodes"})
    route = ShippingRoute(**route_data, created_by=creator_id)
    db.add(route)
    await db.flush()

    for path_item in path_nodes_data:
        path = ShippingRoutePath(
            route_id=route.id,
            node_id=path_item.node_id,
            sequence=path_item.sequence,
            distance_from_start=path_item.distance_from_start,
            node_role=path_item.node_role,
        )
        db.add(path)

    await db.flush()
    return route


async def update_route(
    db: AsyncSession, route_id: int, data: ShippingRouteUpdate
) -> ShippingRoute:
    route = await get_route(db, route_id)
    updates = data.model_dump(exclude_none=True)
    if "origin_region_id" in updates and "dest_region_id" in updates:
        if updates["origin_region_id"] == updates["dest_region_id"]:
            raise HTTPException(status_code=400, detail="起始区域和目的区域不能相同")
    for field, value in updates.items():
        setattr(route, field, value)
    await db.flush()
    return route


async def delete_route(db: AsyncSession, route_id: int) -> None:
    route = await get_route(db, route_id)
    # Delete path nodes first
    path_res = await db.execute(
        select(ShippingRoutePath).where(ShippingRoutePath.route_id == route_id)
    )
    for path in path_res.scalars().all():
        await db.delete(path)
    await db.delete(route)
    await db.flush()


async def add_route_path(
    db: AsyncSession, route_id: int, data: ShippingRoutePathCreate
) -> ShippingRoutePath:
    await get_route(db, route_id)
    path = ShippingRoutePath(
        route_id=route_id,
        node_id=data.node_id,
        sequence=data.sequence,
        distance_from_start=data.distance_from_start,
        node_role=data.node_role,
    )
    db.add(path)
    await db.flush()
    return path


async def delete_route_path(db: AsyncSession, route_id: int, path_id: int) -> None:
    result = await db.execute(
        select(ShippingRoutePath).where(
            and_(ShippingRoutePath.id == path_id, ShippingRoutePath.route_id == route_id)
        )
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="路径节点不存在")
    await db.delete(obj)
    await db.flush()


async def get_route_path(db: AsyncSession, route_id: int) -> List[ShippingRoutePath]:
    result = await db.execute(
        select(ShippingRoutePath)
        .where(ShippingRoutePath.route_id == route_id)
        .order_by(ShippingRoutePath.sequence)
    )
    return list(result.scalars().all())


async def match_route_by_regions(
    db: AsyncSession, origin_region_id: int, dest_region_id: int
) -> Optional[ShippingRoute]:
    result = await db.execute(
        select(ShippingRoute).where(
            and_(
                ShippingRoute.origin_region_id == origin_region_id,
                ShippingRoute.dest_region_id == dest_region_id,
                ShippingRoute.status == 1,
            )
        )
    )
    return result.scalar_one_or_none()
