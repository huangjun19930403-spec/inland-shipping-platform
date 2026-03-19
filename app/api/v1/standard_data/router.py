"""一期标准数据域主入口（Phase 2 cutover）"""
from fastapi import APIRouter

from app.api.v1.standard_data.address import router as address_router
from app.api.v1.standard_data.commodity import router as commodity_router
from app.api.v1.standard_data.vessel import router as vessel_router
from app.api.v1.standard_data.route import router as route_router

router = APIRouter()

router.include_router(address_router, prefix="/address", tags=["标准数据-地址"])
router.include_router(commodity_router, prefix="/commodity", tags=["标准数据-货品"])
router.include_router(vessel_router, prefix="/vessel", tags=["标准数据-船舶"])
router.include_router(route_router, prefix="/route", tags=["标准数据-航线"])
