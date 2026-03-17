"""
统计分析路由

接口列表：
  GET  /analysis/dashboard          — 仪表盘统计数据
  POST /analysis/run-stats          — 手动触发每日统计聚合（管理员）
  GET  /analysis/cargo/heatmap      — 货源热力图
  GET  /analysis/cargo/trend        — 货源趋势图
  GET  /analysis/cargo/commodity_rank — 货品分类货源数量排名
  GET  /analysis/ship/heatmap       — 船舶分布热力图
  GET  /analysis/ship/type_ratio    — 船舶类型数量占比

规则：
  - 所有查询接口只读统计表，响应时间目标 < 200ms
  - 禁止在接口层写任何 SQL
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_analysis_service
from app.core.security import get_current_user_roles, require_roles
from app.schemas.common import success
from app.services.analysis_service import AnalysisService

router = APIRouter()


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


@router.get("/cargo/heatmap", summary="货源热力图", tags=["货源分析"])
async def get_cargo_heatmap(
    stat_date: Optional[date] = Query(None, description="统计日期，默认今天"),
    stat_type: str = Query("ORIGIN", description="ORIGIN=装货热力 | DEST=卸货热力"),
    region_id: Optional[int] = Query(None, description="按区域过滤（可选）"),
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(get_current_user_roles),
):
    """
    返回指定日期各节点的货源热力数据，可用于前端热力地图渲染。
    数据来源：`cargo_heatmap_daily` 统计表（每日 02:00 由 ETL 更新）。
    """
    items = await service.get_cargo_heatmap(
        stat_date=stat_date, stat_type=stat_type, region_id=region_id
    )
    return success(data={"stat_date": str(stat_date or date.today()), "items": items})


@router.get("/cargo/trend", summary="货源趋势图", tags=["货源分析"])
async def get_cargo_trend(
    days: int = Query(30, ge=1, le=365, description="统计天数，最多365天"),
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(get_current_user_roles),
):
    """
    返回最近 N 天每日货源新增量趋势，用于折线图渲染。
    数据来源：`cargo_stat_daily` 统计表（每日 02:00 由 ETL 更新）。
    """
    data = await service.get_cargo_trend(days=days)
    return success(data=data)


@router.get("/cargo/commodity_rank", summary="货品分类货源数量排名", tags=["货源分析"])
async def get_cargo_commodity_rank(
    stat_date: Optional[date] = Query(None, description="统计日期，默认今天"),
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(get_current_user_roles),
):
    """
    返回货品分类货源数量排名（降序），含占比。
    数据来源：`cargo_commodity_stat_daily` 统计表（每日 02:00 由 ETL 更新）。
    """
    items = await service.get_cargo_commodity_rank(stat_date=stat_date)
    return success(data={"stat_date": str(stat_date or date.today()), "items": items})


@router.get("/ship/heatmap", summary="船舶分布热力图", tags=["船舶分析"])
async def get_ship_heatmap(
    stat_date: Optional[date] = Query(None, description="统计日期，默认今天"),
    region_id: Optional[int] = Query(None, description="按区域过滤（可选）"),
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(get_current_user_roles),
):
    """
    返回指定日期各节点的船舶分布热力数据，用于船舶位置热力地图渲染。
    数据来源：`ship_heatmap_daily` 统计表（每日 02:00 由 ETL 更新）。
    """
    items = await service.get_ship_heatmap(stat_date=stat_date, region_id=region_id)
    return success(data={"stat_date": str(stat_date or date.today()), "items": items})


@router.get("/ship/type_ratio", summary="船舶类型数量占比", tags=["船舶分析"])
async def get_ship_type_ratio(
    stat_date: Optional[date] = Query(None, description="统计日期，默认今天"),
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(get_current_user_roles),
):
    """
    返回各船型数量占比，用于饼图渲染。
    数据来源：`ship_type_stat_daily` 统计表（每日 02:00 由 ETL 更新）。
    """
    items = await service.get_ship_type_ratio(stat_date=stat_date)
    return success(data={"stat_date": str(stat_date or date.today()), "items": items})
