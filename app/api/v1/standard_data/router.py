"""一期标准数据域 API 聚合入口"""
from fastapi import APIRouter

from app.api.v1.address.router import router as address_router
from app.api.v1.cargo.router import router as commodity_router
from app.api.v1.vessel.router import router as vessel_router
from app.api.v1.route.router import router as route_router

router = APIRouter()

router.include_router(address_router, prefix="/address", tags=["标准数据-地址"]) 
router.include_router(commodity_router, prefix="/commodity", tags=["标准数据-货品"]) 
router.include_router(vessel_router, prefix="/vessel", tags=["标准数据-船舶"]) 
router.include_router(route_router, prefix="/route", tags=["标准数据-航线"]) 
