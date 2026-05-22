"""API v1 聚合装配（由 modules 接管）。"""

from fastapi import APIRouter, Depends

from app.core.security import require_permission

from app.modules.address.router import router as address_router
from app.modules.analysis.router import router as analysis_router
from app.modules.approval.router import router as approval_router
from app.modules.commodity.router import router as commodity_router
from app.modules.dictionary.router import router as dictionary_router
from app.modules.freight.router import router as freight_router
from app.modules.navigation.router import router as navigation_router
from app.modules.route.router import router as route_router
from app.modules.storage.router import router as storage_router
from app.modules.system.router import router as system_router
from app.modules.tasks.router import router as tasks_router
from app.modules.vessel.router import router as vessel_router

api_router = APIRouter()
api_router.include_router(
    dictionary_router,
    prefix="/dictionary",
    tags=["dictionary"],
    dependencies=[Depends(require_permission("DICTIONARY:READ"))],
)
api_router.include_router(
    address_router,
    prefix="/address",
    tags=["address"],
    dependencies=[Depends(require_permission("ADDRESS:READ"))],
)
api_router.include_router(
    commodity_router,
    prefix="/commodity",
    tags=["commodity"],
    dependencies=[Depends(require_permission("COMMODITY:READ"))],
)
api_router.include_router(
    vessel_router,
    prefix="/vessels",
    tags=["vessels"],
    dependencies=[Depends(require_permission("VESSEL:READ"))],
)
api_router.include_router(
    freight_router,
    prefix="/freight",
    tags=["freight"],
    dependencies=[Depends(require_permission("FREIGHT:READ"))],
)
api_router.include_router(
    route_router,
    prefix="/route",
    tags=["route"],
    dependencies=[Depends(require_permission("ROUTE:READ"))],
)
api_router.include_router(
    navigation_router,
    prefix="/navigation",
    tags=["navigation"],
    dependencies=[Depends(require_permission("ROUTE:READ"))],
)
api_router.include_router(
    analysis_router,
    prefix="/analysis",
    tags=["analysis"],
    dependencies=[Depends(require_permission("ANALYSIS:READ"))],
)
api_router.include_router(
    tasks_router,
    prefix="/tasks",
    tags=["tasks"],
    dependencies=[Depends(require_permission("ANALYSIS:READ"))],
)
api_router.include_router(
    approval_router,
    prefix="/approvals",
    tags=["approvals"],
)
api_router.include_router(
    storage_router,
    prefix="/files",
    tags=["files"],
    dependencies=[Depends(require_permission("STORAGE:READ"))],
)
api_router.include_router(system_router)
