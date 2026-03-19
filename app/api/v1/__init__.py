from fastapi import APIRouter

from app.api.v1.auth.router import router as auth_router
from app.api.v1.address.router import router as address_router
from app.api.v1.cargo.router import router as cargo_router
from app.api.v1.freight.router import router as freight_router
from app.api.v1.vessel.router import router as vessel_router
from app.api.v1.route.router import router as route_router
from app.api.v1.analysis.router import router as analysis_router
from app.api.v1.ai.router import router as ai_router
from app.api.v1.audit.router import router as audit_router
from app.api.v1.system.router import router as system_router

api_router = APIRouter()

api_router.include_router(auth_router,     prefix="/auth",     tags=["认证"])
api_router.include_router(address_router,  prefix="/address",  tags=["地址管理"])
api_router.include_router(cargo_router,    prefix="/cargo",    tags=["货品管理"])
api_router.include_router(freight_router,  prefix="/freight",  tags=["货源管理"])
api_router.include_router(vessel_router,   prefix="/vessel",   tags=["船舶管理"])
api_router.include_router(route_router,    prefix="/route",    tags=["航线管理"])
api_router.include_router(analysis_router, prefix="/analysis", tags=["数据分析"])
api_router.include_router(ai_router,       prefix="/ai",       tags=["AI解析"])
api_router.include_router(audit_router,    prefix="/audit",    tags=["审核中心"])
api_router.include_router(system_router,   prefix="/system",   tags=["系统管理"])
