"""航线路由"""
from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_roles, require_roles
from app.schemas.route import (
    ShippingRouteCreate, ShippingRouteUpdate, ShippingRouteResponse,
    ShippingRoutePathCreate, ShippingRoutePathResponse,
)
from app.schemas.common import success
from app.services import route_service

router = APIRouter()


@router.get("/route", summary="获取航线列表")
async def list_routes(
    origin_region_id: Optional[int] = None,
    dest_region_id: Optional[int] = None,
    status: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    result = await route_service.get_routes(db, origin_region_id, dest_region_id, status, page, page_size)
    return success(data={
        "total": result.total,
        "items": [ShippingRouteResponse.model_validate(i) for i in result.items],
        "page": result.page,
        "page_size": result.page_size,
    })


@router.post("/route", summary="创建航线（管理员直接创建，无需审核）")
async def create_route(
    data: ShippingRouteCreate,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    user, roles = user_roles
    obj = await route_service.create_route(db, data, creator_id=user.id)
    await db.commit()
    await db.refresh(obj)
    return success(data=ShippingRouteResponse.model_validate(obj))


@router.get("/route/{route_id}", summary="获取航线详情")
async def get_route(
    route_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    obj = await route_service.get_route(db, route_id)
    return success(data=ShippingRouteResponse.model_validate(obj))


@router.put("/route/{route_id}", summary="更新航线")
async def update_route(
    route_id: int,
    data: ShippingRouteUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    obj = await route_service.update_route(db, route_id, data)
    await db.commit()
    await db.refresh(obj)
    return success(data=ShippingRouteResponse.model_validate(obj))


@router.delete("/route/{route_id}", summary="删除航线")
async def delete_route(
    route_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    await route_service.delete_route(db, route_id)
    await db.commit()
    return success(message="删除成功")


@router.get("/route/{route_id}/path", summary="获取航线路径节点")
async def get_route_path(
    route_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    items = await route_service.get_route_path(db, route_id)
    return success(data=[ShippingRoutePathResponse.model_validate(i) for i in items])


@router.post("/route/{route_id}/path", summary="添加航线路径节点")
async def add_route_path(
    route_id: int,
    data: ShippingRoutePathCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    obj = await route_service.add_route_path(db, route_id, data)
    await db.commit()
    await db.refresh(obj)
    return success(data=ShippingRoutePathResponse.model_validate(obj))


@router.delete("/route/{route_id}/path/{path_id}", summary="删除航线路径节点")
async def delete_route_path(
    route_id: int,
    path_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    await route_service.delete_route_path(db, route_id, path_id)
    await db.commit()
    return success(message="删除成功")
