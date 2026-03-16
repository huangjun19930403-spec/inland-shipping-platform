"""航线路由 — 使用 DI 模式调用 RouteService"""
from typing import Optional
from fastapi import APIRouter, Depends

from app.core.dependencies import get_route_service
from app.core.security import get_current_user_roles, require_roles
from app.schemas.route import (
    ShippingRouteCreate, ShippingRouteUpdate, ShippingRouteResponse,
    ShippingRoutePathCreate, ShippingRoutePathResponse,
)
from app.schemas.common import success
from app.services.route_service import RouteService

router = APIRouter()


@router.get("/route", summary="获取航线列表")
async def list_routes(
    origin_region_id: Optional[int] = None,
    dest_region_id: Optional[int] = None,
    status: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
    service: RouteService = Depends(get_route_service),
    _=Depends(get_current_user_roles),
):
    result = await service.list_routes(
        origin_region_id=origin_region_id,
        dest_region_id=dest_region_id,
        status=status,
        page=page,
        page_size=page_size,
    )
    return success(data={
        "total": result["total"],
        "items": [ShippingRouteResponse.model_validate(i) for i in result["items"]],
        "page": result["page"],
        "page_size": result["page_size"],
    })


@router.post("/route", summary="创建航线（管理员）")
async def create_route(
    data: ShippingRouteCreate,
    service: RouteService = Depends(get_route_service),
    user_roles=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    user, _ = user_roles
    extra = data.model_dump(
        exclude={"name", "origin_region_id", "dest_region_id", "description", "path_nodes"},
        exclude_none=True,
    )
    obj = await service.create_route(
        name=data.name,
        origin_region_id=data.origin_region_id,
        dest_region_id=data.dest_region_id,
        description=getattr(data, "description", None),
        path_nodes=getattr(data, "path_nodes", None),
        **extra,
    )
    return success(data=ShippingRouteResponse.model_validate(obj))


@router.get("/route/{route_id}", summary="获取航线详情")
async def get_route(
    route_id: int,
    service: RouteService = Depends(get_route_service),
    _=Depends(get_current_user_roles),
):
    obj = await service.get_route(route_id)
    return success(data=ShippingRouteResponse.model_validate(obj))


@router.put("/route/{route_id}", summary="更新航线")
async def update_route(
    route_id: int,
    data: ShippingRouteUpdate,
    service: RouteService = Depends(get_route_service),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    obj = await service.update_route(route_id=route_id, **data.model_dump(exclude_none=True))
    return success(data=ShippingRouteResponse.model_validate(obj))


@router.delete("/route/{route_id}", summary="删除航线")
async def delete_route(
    route_id: int,
    service: RouteService = Depends(get_route_service),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    await service.delete_route(route_id)
    return success(message="删除成功")


@router.get("/route/{route_id}/path", summary="获取航线路径节点")
async def get_route_path(
    route_id: int,
    service: RouteService = Depends(get_route_service),
    _=Depends(get_current_user_roles),
):
    items = await service.get_route_path(route_id)
    return success(data=[ShippingRoutePathResponse.model_validate(i) for i in items])


@router.post("/route/{route_id}/path", summary="添加路径节点")
async def add_route_path(
    route_id: int,
    data: ShippingRoutePathCreate,
    service: RouteService = Depends(get_route_service),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    obj = await service.add_route_path(
        route_id=route_id,
        node_id=data.node_id,
        sequence=data.sequence,
        distance_km=getattr(data, "distance_km", None),
    )
    return success(data=ShippingRoutePathResponse.model_validate(obj))


@router.delete("/route/{route_id}/path/{path_id}", summary="删除路径节点")
async def delete_route_path(
    route_id: int,
    path_id: int,
    service: RouteService = Depends(get_route_service),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    await service.delete_route_path(route_id=route_id, path_id=path_id)
    return success(message="删除成功")
