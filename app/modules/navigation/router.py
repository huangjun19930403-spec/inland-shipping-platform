from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.modules.navigation.routing_service import NavigationRoutingEngineService
from app.modules.navigation.schemas import NavigationRouteGenerateRequest, NavigationRouteGenerateResponse

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
