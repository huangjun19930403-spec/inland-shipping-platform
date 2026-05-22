"""route 模块 router。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.modules.route.schemas import (
    PageResponse,
    RouteCreateRequest,
    RouteDetailResponse,
    RouteListQuery,
    RoutePlanCreateRequest,
    RoutePlanListQuery,
    RoutePlanResponse,
    RoutePlanStructureReplaceRequest,
    RoutePlanStructureResponse,
    RoutePlanTrackVersionResponse,
    RoutePlanUpdateRequest,
    RouteResponse,
    RouteTrackGenerateRequest,
    RouteTrackVersionSaveRequest,
    RouteUpdateRequest,
)
from app.modules.route.service import ShippingRoutePlanService, ShippingRoutePlanStructureService, ShippingRouteService
from app.modules.tasks.schemas import AsyncTaskRunResponse
from app.modules.tasks.service import AsyncTaskRunService

router = APIRouter()


@router.get("", response_model=PageResponse[RouteResponse])
async def list_routes(
    query: RouteListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await ShippingRouteService(db).list_routes(query)


@router.post("", response_model=RouteResponse)
async def create_route(
    body: RouteCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await ShippingRouteService(db).create_route(body)


@router.get("/{route_id}", response_model=RouteDetailResponse)
async def get_route_detail(
    route_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await ShippingRouteService(db).get_route_detail(route_id)


@router.put("/{route_id}", response_model=RouteResponse)
async def update_route(
    route_id: int,
    body: RouteUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await ShippingRouteService(db).update_route(route_id, body)


@router.delete("/{route_id}")
async def delete_route(
    route_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    await ShippingRouteService(db).delete_route(route_id)
    return {"ok": True}


@router.get("/{route_id}/plans", response_model=PageResponse[RoutePlanResponse])
async def list_route_plans(
    route_id: int,
    query: RoutePlanListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await ShippingRoutePlanService(db).list_plans(route_id, query)


@router.post("/{route_id}/plans", response_model=RoutePlanResponse)
async def create_route_plan(
    route_id: int,
    body: RoutePlanCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await ShippingRoutePlanService(db).create_plan(route_id, body)


@router.put("/plans/{plan_id}", response_model=RoutePlanResponse)
async def update_route_plan(
    plan_id: int,
    body: RoutePlanUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await ShippingRoutePlanService(db).update_plan(plan_id, body)


@router.delete("/plans/{plan_id}")
async def delete_route_plan(
    plan_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    await ShippingRoutePlanService(db).delete_plan(plan_id)
    return {"ok": True}


@router.get("/plans/{plan_id}/structure", response_model=RoutePlanStructureResponse)
async def get_route_plan_structure(
    plan_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await ShippingRoutePlanStructureService(db).get_structure(plan_id)


@router.put("/plans/{plan_id}/structure", response_model=RoutePlanStructureResponse)
async def replace_route_plan_structure(
    plan_id: int,
    body: RoutePlanStructureReplaceRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await ShippingRoutePlanStructureService(db).replace_structure(plan_id, body)


@router.get("/plans/{plan_id}/track-versions", response_model=list[RoutePlanTrackVersionResponse])
async def list_route_plan_track_versions(
    plan_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await ShippingRoutePlanStructureService(db).list_track_versions(plan_id)


@router.post("/plans/{plan_id}/track-versions/generate", response_model=AsyncTaskRunResponse)
async def generate_route_plan_track_version(
    plan_id: int,
    body: RouteTrackGenerateRequest | None = None,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    requested_by = getattr(current_user, "id", None)
    return await ShippingRoutePlanStructureService(db).enqueue_generate_track_version(
        plan_id,
        body or RouteTrackGenerateRequest(),
        requested_by=requested_by,
    )


@router.get("/plans/{plan_id}/track-generation-tasks/latest", response_model=AsyncTaskRunResponse | None)
async def get_latest_route_plan_track_generation_task(
    plan_id: int,
    provider_code: str | None = Query(default="AUTO"),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await ShippingRoutePlanStructureService(db).get_latest_track_generation_task(
        plan_id,
        provider_code=provider_code,
    )


@router.get("/track-generation-tasks/{task_run_id}", response_model=AsyncTaskRunResponse)
async def get_route_track_generation_task(
    task_run_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    row = await AsyncTaskRunService(db).get_run(task_run_id)
    if row.business_type != "ROUTE_PLAN_TRACK_VERSION":
        from app.core.exceptions import NotFoundError

        raise NotFoundError("AsyncTaskRun", task_run_id)
    return row


@router.get("/plans/{plan_id}/track-versions/{version_id}", response_model=RoutePlanTrackVersionResponse)
async def get_route_plan_track_version(
    plan_id: int,
    version_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await ShippingRoutePlanStructureService(db).get_track_version(plan_id, version_id)


@router.post("/plans/{plan_id}/track-versions", response_model=RoutePlanTrackVersionResponse)
async def save_route_plan_track_version(
    plan_id: int,
    body: RouteTrackVersionSaveRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await ShippingRoutePlanStructureService(db).save_track_version(plan_id, body)


@router.put("/plans/{plan_id}/track-versions/{version_id}/current", response_model=RoutePlanTrackVersionResponse)
async def set_current_route_plan_track_version(
    plan_id: int,
    version_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await ShippingRoutePlanStructureService(db).set_current_track_version(plan_id, version_id)


@router.delete("/plans/{plan_id}/track-versions/{version_id}")
async def delete_route_plan_track_version(
    plan_id: int,
    version_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    await ShippingRoutePlanStructureService(db).delete_track_version(plan_id, version_id)
    return {"ok": True}
