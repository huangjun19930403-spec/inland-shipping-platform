"""route 模块 router。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.modules.route.schemas import (
    PageResponse,
    RouteCreateRequest,
    RouteDetailResponse,
    RouteGeometryRefreshRequest,
    RouteGeometryRefreshResponse,
    RouteListQuery,
    RoutePlanActivateRequest,
    RoutePlanCreateRequest,
    RoutePlanDetailResponse,
    RoutePlanListQuery,
    RoutePlanResponse,
    RoutePlanStatusChangeRequest,
    RoutePlanUpdateRequest,
    RouteResponse,
    RouteSegmentCreateRequest,
    RouteSegmentOrderRequest,
    RouteSegmentPointCreateRequest,
    RouteSegmentPointOrderRequest,
    RouteSegmentPointResponse,
    RouteSegmentPointUpdateRequest,
    RouteSegmentResponse,
    RouteSegmentUpdateRequest,
    RouteStatusChangeRequest,
    RouteUpdateRequest,
)
from app.modules.route.service import (
    RouteGeometryService,
    ShippingRoutePlanService,
    ShippingRoutePointService,
    ShippingRouteSegmentService,
    ShippingRouteService,
)

router = APIRouter()


@router.get("", response_model=PageResponse[RouteResponse])
async def list_routes(
    query: RouteListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRouteService(db)
    return await service.list_routes(
        keyword=query.keyword,
        status_code=query.status_code,
        origin_region_id=query.origin_region_id,
        destination_region_id=query.destination_region_id,
        page=query.page,
        page_size=query.page_size,
    )


@router.get("/{route_id}", response_model=RouteDetailResponse)
async def get_route_detail(
    route_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRouteService(db)
    return await service.get_route_detail(route_id)


@router.post("", response_model=RouteResponse)
async def create_route(
    body: RouteCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRouteService(db)
    return await service.create_route(body)


@router.put("/{route_id}", response_model=RouteResponse)
async def update_route(
    route_id: int,
    body: RouteUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRouteService(db)
    return await service.update_route(route_id, body)


@router.put("/{route_id}/status")
async def change_route_status(
    route_id: int,
    body: RouteStatusChangeRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRouteService(db)
    await service.change_route_status(route_id, body.status_code)
    return {"ok": True}


@router.get("/{route_id}/plans", response_model=PageResponse[RoutePlanResponse])
async def list_route_plans(
    route_id: int,
    query: RoutePlanListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRoutePlanService(db)
    return await service.list_plans(
        route_id=route_id,
        status_code=query.status_code,
        page=query.page,
        page_size=query.page_size,
    )


@router.post("/{route_id}/plans", response_model=RoutePlanResponse)
async def create_route_plan(
    route_id: int,
    body: RoutePlanCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRoutePlanService(db)
    return await service.create_plan(route_id, body)


@router.get("/plans/{plan_id}", response_model=RoutePlanDetailResponse)
async def get_plan_detail(
    plan_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRoutePlanService(db)
    return await service.get_plan_detail(plan_id)


@router.put("/plans/{plan_id}", response_model=RoutePlanResponse)
async def update_plan(
    plan_id: int,
    body: RoutePlanUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRoutePlanService(db)
    return await service.update_plan(plan_id, body)


@router.put("/plans/{plan_id}/status")
async def change_plan_status(
    plan_id: int,
    body: RoutePlanStatusChangeRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRoutePlanService(db)
    await service.change_plan_status(plan_id, body.status_code)
    return {"ok": True}


@router.put("/{route_id}/plans/{plan_id}/activate")
async def activate_plan(
    route_id: int,
    plan_id: int,
    body: RoutePlanActivateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = (current_user, body)
    service = ShippingRoutePlanService(db)
    await service.activate_plan(route_id, plan_id)
    return {"ok": True}


@router.get("/plans/{plan_id}/segments", response_model=list[RouteSegmentResponse])
async def list_segments(
    plan_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRouteSegmentService(db)
    return await service.list_segments(plan_id)


@router.post("/plans/{plan_id}/segments", response_model=RouteSegmentResponse)
async def create_segment(
    plan_id: int,
    body: RouteSegmentCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRouteSegmentService(db)
    return await service.create_segment(plan_id, body)


@router.put("/segments/{segment_id}", response_model=RouteSegmentResponse)
async def update_segment(
    segment_id: int,
    body: RouteSegmentUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRouteSegmentService(db)
    return await service.update_segment(segment_id, body)


@router.delete("/segments/{segment_id}")
async def delete_segment(
    segment_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRouteSegmentService(db)
    await service.delete_segment(segment_id)
    return {"ok": True}


@router.put("/plans/{plan_id}/segments/order")
async def reorder_segments(
    plan_id: int,
    body: RouteSegmentOrderRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRouteSegmentService(db)
    count = await service.reorder_segments(plan_id, body.ordered_ids)
    return {"ok": True, "sorted_count": count}


@router.get("/segments/{segment_id}/points", response_model=list[RouteSegmentPointResponse])
async def list_points(
    segment_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRoutePointService(db)
    return await service.list_points(segment_id)


@router.post("/segments/{segment_id}/points", response_model=RouteSegmentPointResponse)
async def create_point(
    segment_id: int,
    body: RouteSegmentPointCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRoutePointService(db)
    return await service.create_point(segment_id, body)


@router.put("/points/{point_id}", response_model=RouteSegmentPointResponse)
async def update_point(
    point_id: int,
    body: RouteSegmentPointUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRoutePointService(db)
    return await service.update_point(point_id, body)


@router.delete("/points/{point_id}")
async def delete_point(
    point_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRoutePointService(db)
    await service.delete_point(point_id)
    return {"ok": True}


@router.put("/segments/{segment_id}/points/order")
async def reorder_points(
    segment_id: int,
    body: RouteSegmentPointOrderRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRoutePointService(db)
    count = await service.reorder_points(segment_id, body.ordered_ids)
    return {"ok": True, "sorted_count": count}


@router.post("/plans/{plan_id}/geometry/refresh", response_model=RouteGeometryRefreshResponse)
async def refresh_plan_geometry(
    plan_id: int,
    body: RouteGeometryRefreshRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = RouteGeometryService(db)
    return await service.refresh_plan_geometry(
        plan_id=plan_id,
        provider_code=body.provider_code,
        force_refresh=body.force_refresh,
    )


@router.post("/segments/{segment_id}/geometry/refresh", response_model=RouteGeometryRefreshResponse)
async def refresh_segment_geometry(
    segment_id: int,
    body: RouteGeometryRefreshRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = RouteGeometryService(db)
    return await service.refresh_segment_geometry(
        segment_id=segment_id,
        provider_code=body.provider_code,
        force_refresh=body.force_refresh,
    )
