"""航线路由 — 三层结构：航线 / 路线方案 / 路径段（一期主表达）"""
from typing import Optional

from fastapi import APIRouter, Depends

from app.core.dependencies import get_route_service
from app.core.security import get_current_user_roles, require_roles
from app.schemas.common import success
from app.schemas.route import (
    ShippingRouteCreate,
    ShippingRoutePathCreate,
    ShippingRoutePathNodeCreate,
    ShippingRoutePathNodeResponse,
    ShippingRoutePathNodesBatchSet,
    ShippingRoutePathResponse,
    ShippingRoutePathSegmentCreate,
    ShippingRoutePathSegmentResponse,
    ShippingRoutePathSegmentsBatchSet,
    ShippingRoutePathSegmentUpdate,
    ShippingRoutePathUpdate,
    ShippingRouteResponse,
    ShippingRouteUpdate,
)
from app.services.route_service import RouteService

router = APIRouter()


# ─────────────────────────────────────────────────
# 航线（ShippingRoute）
# ─────────────────────────────────────────────────


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
    return success(
        data={
            "total": result["total"],
            "items": [ShippingRouteResponse.model_validate(i) for i in result["items"]],
            "page": result["page"],
            "page_size": result["page_size"],
        }
    )


@router.post("/route", summary="创建航线（自动生成编码，同时创建默认路线方案）")
async def create_route(
    data: ShippingRouteCreate,
    service: RouteService = Depends(get_route_service),
    user_roles=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    user, _ = user_roles
    obj = await service.create_route(
        name=data.name,
        origin_region_id=data.origin_region_id,
        dest_region_id=data.dest_region_id,
        created_by=user.id,
        **data.model_dump(
            exclude={"name", "origin_region_id", "dest_region_id"},
            exclude_none=True,
        ),
    )
    return success(data=ShippingRouteResponse.model_validate(obj))


@router.get("/route/{route_id}", summary="获取航线详情（含路线方案）")
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


@router.delete("/route/{route_id}", summary="删除航线（级联删除路线方案/节点/路径段）")
async def delete_route(
    route_id: int,
    service: RouteService = Depends(get_route_service),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    await service.delete_route(route_id)
    return success(message="删除成功")


# ─────────────────────────────────────────────────
# 路线方案（ShippingRoutePath）
# ─────────────────────────────────────────────────


@router.get("/route/{route_id}/path", summary="获取航线下所有路线方案")
async def list_route_paths(
    route_id: int,
    service: RouteService = Depends(get_route_service),
    _=Depends(get_current_user_roles),
):
    items = await service.list_route_paths(route_id)
    return success(data=[ShippingRoutePathResponse.model_validate(i) for i in items])


@router.post("/route/{route_id}/path", summary="在航线下新增路线方案")
async def create_route_path(
    route_id: int,
    data: ShippingRoutePathCreate,
    service: RouteService = Depends(get_route_service),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    obj = await service.create_route_path(
        route_id=route_id,
        name=data.name,
        description=data.description,
        sort_order=data.sort_order,
        status=data.status,
    )
    return success(data=ShippingRoutePathResponse.model_validate(obj))


@router.get("/route/{route_id}/path/{path_id}", summary="获取路线方案详情（含节点与路径段）")
async def get_route_path(
    route_id: int,
    path_id: int,
    service: RouteService = Depends(get_route_service),
    _=Depends(get_current_user_roles),
):
    obj = await service.get_route_path(route_id, path_id)
    return success(data=ShippingRoutePathResponse.model_validate(obj))


@router.put("/route/{route_id}/path/{path_id}", summary="更新路线方案")
async def update_route_path(
    route_id: int,
    path_id: int,
    data: ShippingRoutePathUpdate,
    service: RouteService = Depends(get_route_service),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    obj = await service.update_route_path(
        route_id=route_id,
        path_id=path_id,
        **data.model_dump(exclude_none=True),
    )
    return success(data=ShippingRoutePathResponse.model_validate(obj))


@router.delete("/route/{route_id}/path/{path_id}", summary="删除路线方案（级联删除节点与路径段）")
async def delete_route_path(
    route_id: int,
    path_id: int,
    service: RouteService = Depends(get_route_service),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    await service.delete_route_path(route_id=route_id, path_id=path_id)
    return success(message="删除成功")


# ─────────────────────────────────────────────────
# 路径节点（兼容保留）
# ─────────────────────────────────────────────────


@router.post("/route/{route_id}/path/{path_id}/node", summary="向路线方案添加节点")
async def add_path_node(
    route_id: int,
    path_id: int,
    data: ShippingRoutePathNodeCreate,
    service: RouteService = Depends(get_route_service),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    obj = await service.add_path_node(
        route_id=route_id,
        path_id=path_id,
        node_id=data.node_id,
        sequence=data.sequence,
        distance_from_start=data.distance_from_start,
        node_role=data.node_role,
    )
    return success(data=ShippingRoutePathNodeResponse.model_validate(obj))


@router.put("/route/{route_id}/path/{path_id}/nodes", summary="批量替换路线方案的所有节点")
async def set_path_nodes(
    route_id: int,
    path_id: int,
    data: ShippingRoutePathNodesBatchSet,
    service: RouteService = Depends(get_route_service),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    obj = await service.set_path_nodes(
        route_id=route_id,
        path_id=path_id,
        nodes=[n.model_dump() for n in data.nodes],
    )
    return success(data=ShippingRoutePathResponse.model_validate(obj))


@router.delete("/route/{route_id}/path/{path_id}/node/{node_id}", summary="删除路线方案中的节点")
async def delete_path_node(
    route_id: int,
    path_id: int,
    node_id: int,
    service: RouteService = Depends(get_route_service),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    await service.delete_path_node(route_id=route_id, path_id=path_id, node_id=node_id)
    return success(message="删除成功")


# ─────────────────────────────────────────────────
# 路径段（一期主表达）
# ─────────────────────────────────────────────────


@router.get("/route/{route_id}/path/{path_id}/segment", summary="获取路线方案路径段列表")
async def list_path_segments(
    route_id: int,
    path_id: int,
    service: RouteService = Depends(get_route_service),
    _=Depends(get_current_user_roles),
):
    items = await service.list_path_segments(route_id, path_id)
    return success(data=[ShippingRoutePathSegmentResponse.model_validate(i) for i in items])


@router.post("/route/{route_id}/path/{path_id}/segment", summary="新增路径段")
async def add_path_segment(
    route_id: int,
    path_id: int,
    data: ShippingRoutePathSegmentCreate,
    service: RouteService = Depends(get_route_service),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    obj = await service.add_path_segment(route_id=route_id, path_id=path_id, **data.model_dump())
    return success(data=ShippingRoutePathSegmentResponse.model_validate(obj))


@router.put("/route/{route_id}/path/{path_id}/segments", summary="批量替换路径段")
async def set_path_segments(
    route_id: int,
    path_id: int,
    data: ShippingRoutePathSegmentsBatchSet,
    service: RouteService = Depends(get_route_service),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    obj = await service.set_path_segments(
        route_id=route_id,
        path_id=path_id,
        segments=[s.model_dump() for s in data.segments],
    )
    return success(data=ShippingRoutePathResponse.model_validate(obj))


@router.put("/route/{route_id}/path/{path_id}/segment/{segment_id}", summary="更新路径段")
async def update_path_segment(
    route_id: int,
    path_id: int,
    segment_id: int,
    data: ShippingRoutePathSegmentUpdate,
    service: RouteService = Depends(get_route_service),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    obj = await service.update_path_segment(
        route_id=route_id,
        path_id=path_id,
        segment_id=segment_id,
        **data.model_dump(exclude_none=True),
    )
    return success(data=ShippingRoutePathSegmentResponse.model_validate(obj))


@router.delete("/route/{route_id}/path/{path_id}/segment/{segment_id}", summary="删除路径段")
async def delete_path_segment(
    route_id: int,
    path_id: int,
    segment_id: int,
    service: RouteService = Depends(get_route_service),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    await service.delete_path_segment(route_id=route_id, path_id=path_id, segment_id=segment_id)
    return success(message="删除成功")
