from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.modules.navigation.map_layer_service import NavigationMapLayerService
from app.modules.navigation.routing_service import NavigationRoutingEngineService
from app.modules.navigation.schemas import (
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
