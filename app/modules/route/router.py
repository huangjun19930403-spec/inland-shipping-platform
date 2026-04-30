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
    RouteLineCreateRequest,
    RouteLineResponse,
    RouteLineStructureReplaceRequest,
    RouteLineStructureResponse,
    RouteLineTrackGenerateRequest,
    RouteLineTrackGenerateResponse,
    RouteLineTrackResponse,
    RouteLineUpdateRequest,
    RouteListQuery,
    RoutePlanCreateRequest,
    RoutePlanListQuery,
    RoutePlanResponse,
    RoutePlanUpdateRequest,
    RouteResponse,
    RouteUpdateRequest,
)
from app.modules.route.service import ShippingRouteLineService, ShippingRoutePlanService, ShippingRouteService

router = APIRouter()


@router.get("", response_model=PageResponse[RouteResponse])
async def list_routes(
    query: RouteListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRouteService(db)
    return await service.list_routes(query)


@router.post("", response_model=RouteResponse)
async def create_route(
    body: RouteCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRouteService(db)
    return await service.create_route(body)


@router.get("/{route_id}", response_model=RouteDetailResponse)
async def get_route_detail(
    route_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRouteService(db)
    return await service.get_route_detail(route_id)


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


@router.delete("/{route_id}")
async def delete_route(
    route_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRouteService(db)
    await service.delete_route(route_id)
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
    return await service.list_plans(route_id, query)


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


@router.put("/plans/{plan_id}", response_model=RoutePlanResponse)
async def update_route_plan(
    plan_id: int,
    body: RoutePlanUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRoutePlanService(db)
    return await service.update_plan(plan_id, body)


@router.delete("/plans/{plan_id}")
async def delete_route_plan(
    plan_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRoutePlanService(db)
    await service.delete_plan(plan_id)
    return {"ok": True}


@router.get("/plans/{plan_id}/lines", response_model=list[RouteLineResponse])
async def list_route_lines(
    plan_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRouteLineService(db)
    return await service.list_lines(plan_id)


@router.post("/plans/{plan_id}/lines", response_model=RouteLineResponse)
async def create_route_line(
    plan_id: int,
    body: RouteLineCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRouteLineService(db)
    return await service.create_line(plan_id, body)


@router.get("/lines/{line_id}", response_model=RouteLineResponse)
async def get_route_line(
    line_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRouteLineService(db)
    structure = await service.get_structure(line_id)
    return structure.line


@router.put("/lines/{line_id}", response_model=RouteLineResponse)
async def update_route_line(
    line_id: int,
    body: RouteLineUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRouteLineService(db)
    return await service.update_line(line_id, body)


@router.delete("/lines/{line_id}")
async def delete_route_line(
    line_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRouteLineService(db)
    await service.delete_line(line_id)
    return {"ok": True}


@router.get("/lines/{line_id}/structure", response_model=RouteLineStructureResponse)
async def get_route_line_structure(
    line_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRouteLineService(db)
    return await service.get_structure(line_id)


@router.put("/lines/{line_id}/structure", response_model=RouteLineStructureResponse)
async def replace_route_line_structure(
    line_id: int,
    body: RouteLineStructureReplaceRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRouteLineService(db)
    return await service.replace_structure(line_id, body)


@router.get("/lines/{line_id}/track", response_model=RouteLineTrackResponse | None)
async def get_route_line_track(
    line_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRouteLineService(db)
    return await service.get_track(line_id)


@router.post("/lines/{line_id}/track/generate", response_model=RouteLineTrackGenerateResponse)
async def generate_route_line_track(
    line_id: int,
    body: RouteLineTrackGenerateRequest | None = None,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShippingRouteLineService(db)
    return await service.generate_track(line_id, body or RouteLineTrackGenerateRequest())
