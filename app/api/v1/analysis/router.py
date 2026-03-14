"""统计分析路由"""
from typing import Optional
from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_roles, require_roles
from app.schemas.analysis import (
    DashboardStatsResponse, HeatmapStatResponse,
    CargoTrendResponse, TopNodesResponse,
)
from app.schemas.common import success
from app.services import analysis_service

router = APIRouter()


@router.get("/dashboard", summary="仪表盘统计数据")
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    data = await analysis_service.get_dashboard_stats(db)
    return success(data=DashboardStatsResponse(**data))


@router.get("/cargo-heatmap", summary="货源热力图数据")
async def get_cargo_heatmap(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    stat_type: str = Query("CARGO_ORIGIN", description="CARGO_ORIGIN or CARGO_DEST"),
    region_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    items = await analysis_service.get_cargo_heatmap(db, start_date, end_date, stat_type, region_id)
    return success(data=items)


@router.get("/vessel-heatmap", summary="船舶分布热力图数据")
async def get_vessel_heatmap(
    region_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    items = await analysis_service.get_vessel_heatmap(db, region_id)
    return success(data=items)


@router.get("/cargo-trends", summary="货源趋势数据")
async def get_cargo_trends(
    days: int = Query(7, ge=1, le=90, description="统计天数"),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    data = await analysis_service.get_cargo_trends(db, days)
    return success(data=CargoTrendResponse(**data))


@router.get("/top-nodes", summary="Top节点排行")
async def get_top_nodes(
    stat_type: str = Query("CARGO_ORIGIN", description="CARGO_ORIGIN/CARGO_DEST/VESSEL"),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    data = await analysis_service.get_top_nodes(db, stat_type, limit)
    return success(data=TopNodesResponse(**data))


@router.post("/run-stats", summary="手动触发每日统计聚合（管理员）")
async def run_daily_stats(
    target_date: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    result = await analysis_service.run_daily_stats(db, target_date)
    await db.commit()
    return success(data=result, message="统计聚合完成")
