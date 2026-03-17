"""
统计分析路由聚合入口

子路由：
  /analysis/cargo/*  — 货源分析（cargo_analysis.py）
  /analysis/ship/*   — 船舶分析（ship_analysis.py）
"""
from typing import Optional
from datetime import date

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_analysis_service
from app.core.security import get_current_user_roles, require_roles
from app.schemas.common import success
from app.services.analysis_service import AnalysisService

from app.api.v1.analysis.cargo_analysis import router as cargo_router
from app.api.v1.analysis.ship_analysis import router as ship_router

router = APIRouter()

router.include_router(cargo_router, prefix="/cargo", tags=["货源分析"])
router.include_router(ship_router, prefix="/ship", tags=["船舶分析"])


@router.get("/dashboard", summary="仪表盘统计数据", tags=["数据分析"])
async def get_dashboard(
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(get_current_user_roles),
):
    data = await service.get_dashboard_stats()
    return success(data=data)


@router.post("/run-stats", summary="手动触发每日统计聚合（管理员）", tags=["数据分析"])
async def run_daily_stats(
    target_date: Optional[date] = None,
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    result = await service.run_daily_stats(target_date=target_date)
    return success(data=result, message="统计聚合完成")
