"""
统计分析路由聚合入口

子路由：
  /analysis/cargo/*  — 货源分析（cargo_analysis.py）
  /analysis/ship/*   — 船舶分析（ship_analysis.py）
  /analysis/*        — 旧接口兼容（仪表盘、热力图、趋势、Top节点）
"""
from typing import Optional
from datetime import date

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_analysis_service
from app.core.security import get_current_user_roles, require_roles
from app.schemas.common import success
from app.services.analysis_service import AnalysisService

# ── 新增子路由 ────────────────────────────────────────────
from app.api.v1.analysis.cargo_analysis import router as cargo_router
from app.api.v1.analysis.ship_analysis import router as ship_router

router = APIRouter()

# 货源分析子路由：/analysis/cargo/*
router.include_router(cargo_router, prefix="/cargo", tags=["货源分析"])
# 船舶分析子路由：/analysis/ship/*
router.include_router(ship_router, prefix="/ship", tags=["船舶分析"])


# ── 旧接口保持兼容 ────────────────────────────────────────

@router.get("/dashboard", summary="仪表盘统计数据", tags=["数据分析"])
async def get_dashboard(
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(get_current_user_roles),
):
    data = await service.get_dashboard_stats()
    return success(data=data)


@router.get("/cargo-heatmap", summary="货源热力图数据（旧接口）", tags=["数据分析"])
async def get_cargo_heatmap(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    stat_type: str = Query("CARGO_ORIGIN", description="CARGO_ORIGIN or CARGO_DEST"),
    region_id: Optional[int] = None,
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(get_current_user_roles),
):
    new_type = "DEST" if stat_type == "CARGO_DEST" else "ORIGIN"
    items = await service.get_cargo_heatmap(
        stat_date=end_date or start_date,
        stat_type=new_type,
        region_id=region_id,
    )
    return success(data=items)


@router.get("/vessel-heatmap", summary="船舶分布热力图数据（旧接口）", tags=["数据分析"])
async def get_vessel_heatmap(
    region_id: Optional[int] = None,
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(get_current_user_roles),
):
    items = await service.get_vessel_heatmap(region_id=region_id)
    return success(data=items)


@router.get("/cargo-trends", summary="货源趋势数据（旧接口）", tags=["数据分析"])
async def get_cargo_trends(
    days: int = Query(7, ge=1, le=90, description="统计天数"),
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(get_current_user_roles),
):
    data = await service.get_cargo_trends(days=days)
    return success(data=data)


@router.get("/top-nodes", summary="Top节点排行（旧接口）", tags=["数据分析"])
async def get_top_nodes(
    stat_type: str = Query("CARGO_ORIGIN", description="CARGO_ORIGIN/CARGO_DEST/VESSEL"),
    limit: int = Query(10, ge=1, le=50),
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(get_current_user_roles),
):
    data = await service.get_top_nodes(stat_type=stat_type, limit=limit)
    return success(data=data)


@router.post("/run-stats", summary="手动触发每日统计聚合（管理员）", tags=["数据分析"])
async def run_daily_stats(
    target_date: Optional[date] = None,
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    result = await service.run_daily_stats(target_date=target_date)
    return success(data=result, message="统计聚合完成")
