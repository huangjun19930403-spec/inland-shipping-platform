from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.modules.navigation.annotation_service import NavigationAnnotationTaskService
from app.modules.navigation.map_layer_service import NavigationMapLayerService
from app.modules.navigation.routing_service import NavigationRoutingEngineService
from app.modules.navigation.schemas import (
    NavigationAnnotationSuggestionResponse,
    NavigationAnnotationTaskBatchCreateResponse,
    NavigationAnnotationTaskListResponse,
    NavigationAnnotationTaskResolveRequest,
    NavigationAnnotationTaskResponse,
    NavigationMapLayerResponse,
    NavigationRouteGenerateRequest,
    NavigationRouteGenerateResponse,
)

router = APIRouter()


@router.post("/routes/generate", response_model=NavigationRouteGenerateResponse)
async def generate_navigation_route(
    body: NavigationRouteGenerateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationRoutingEngineService(db).generate_route(
        body,
        created_by=getattr(current_user, "id", None),
    )


@router.get("/map-layers", response_model=NavigationMapLayerResponse)
async def get_navigation_map_layers(
    min_lng: float | None = None,
    min_lat: float | None = None,
    max_lng: float | None = None,
    max_lat: float | None = None,
    route_result_id: int | None = None,
    include_water_area: bool = True,
    include_boundary: bool = True,
    include_centerline: bool = True,
    include_graph_edge: bool = True,
    limit: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await NavigationMapLayerService(db).get_layers(
        min_lng=min_lng,
        min_lat=min_lat,
        max_lng=max_lng,
        max_lat=max_lat,
        route_result_id=route_result_id,
        include_water_area=include_water_area,
        include_boundary=include_boundary,
        include_centerline=include_centerline,
        include_graph_edge=include_graph_edge,
        limit=limit,
    )


@router.get("/annotation-tasks", response_model=NavigationAnnotationTaskListResponse)
async def list_navigation_annotation_tasks(
    status_code: str | None = None,
    task_type_code: str | None = None,
    target_type_code: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
):
    return await NavigationAnnotationTaskService(db).list_tasks(
        status_code=status_code,
        task_type_code=task_type_code,
        target_type_code=target_type_code,
        page=page,
        page_size=page_size,
    )


@router.post("/annotation-tasks/from-route-result/{route_result_id}", response_model=NavigationAnnotationTaskBatchCreateResponse)
async def create_navigation_annotation_tasks_from_route_result(
    route_result_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationAnnotationTaskService(db).create_from_route_result(
        route_result_id,
        created_by=getattr(current_user, "id", None),
    )


@router.post("/annotation-tasks/from-graph-version/{graph_version_id}", response_model=NavigationAnnotationTaskBatchCreateResponse)
async def create_navigation_annotation_tasks_from_graph_version(
    graph_version_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationAnnotationTaskService(db).create_from_graph_version(
        graph_version_id,
        created_by=getattr(current_user, "id", None),
    )


@router.post("/annotation-tasks/from-centerlines", response_model=NavigationAnnotationTaskBatchCreateResponse)
async def create_navigation_annotation_tasks_from_centerlines(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationAnnotationTaskService(db).create_from_centerline_quality(
        created_by=getattr(current_user, "id", None),
    )


@router.post("/annotation-tasks/{task_id}/suggestion", response_model=NavigationAnnotationSuggestionResponse)
async def generate_navigation_annotation_task_suggestion(
    task_id: int,
    db: AsyncSession = Depends(get_db),
):
    return await NavigationAnnotationTaskService(db).generate_suggestion(task_id)


@router.post("/annotation-tasks/{task_id}/resolve", response_model=NavigationAnnotationTaskResponse)
async def resolve_navigation_annotation_task(
    task_id: int,
    body: NavigationAnnotationTaskResolveRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationAnnotationTaskService(db).resolve_task(
        task_id,
        body,
        reviewed_by=getattr(current_user, "id", None),
    )


@router.get("/annotation-tasks/{task_id}", response_model=NavigationAnnotationTaskResponse)
async def get_navigation_annotation_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
):
    return await NavigationAnnotationTaskService(db).get_task(task_id)
