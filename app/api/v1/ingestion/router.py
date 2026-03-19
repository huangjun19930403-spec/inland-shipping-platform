"""一期数据接入域主入口（Phase 2 cutover）"""
from fastapi import APIRouter

from app.api.v1.ingestion.cargo import router as cargo_router
from app.api.v1.ingestion.tms import router as tms_router
from app.api.v1.ingestion.vessel import router as vessel_router

router = APIRouter()

router.include_router(cargo_router, prefix="/cargo", tags=["数据接入-货源"])
router.include_router(tms_router, tags=["数据接入-TMS"])
router.include_router(vessel_router, tags=["数据接入-船舶"])
