from fastapi import APIRouter

from app.api.v1.standard_data.router import router as standard_data_router
from app.api.v1.ingestion.router import router as ingestion_router
from app.api.v1.analysis.router import router as analysis_router
from app.api.v1.ai.router import router as ai_router
from app.api.v1.system_domain.router import router as system_domain_router

api_router = APIRouter()

api_router.include_router(standard_data_router, prefix="/standard-data", tags=["标准数据"])
api_router.include_router(ingestion_router, prefix="/ingestion", tags=["数据接入"])
api_router.include_router(analysis_router, prefix="/analysis", tags=["分析能力"])
api_router.include_router(ai_router, prefix="/ai", tags=["AI能力"])
api_router.include_router(system_domain_router, prefix="/system", tags=["系统"])
