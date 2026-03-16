"""
货源分析路由

接口列表：
  GET /api/v1/analysis/cargo/heatmap         — 货源热力图
  GET /api/v1/analysis/cargo/trend           — 货源趋势图
  GET /api/v1/analysis/cargo/commodity_rank  — 货品分类排名
  GET /api/v1/analysis/cargo/region_ratio    — 区域货源分布占比 + 排名

规则：
  - 所有接口只读统计表，响应时间目标 < 200ms
  - 禁止在接口层写任何 SQL
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_analysis_service
from app.core.security import get_current_user_roles
from app.schemas.common import success
from app.services.analysis_service import AnalysisService

router = APIRouter()


@router.get(
    "/heatmap",
    summary="货源热力图",
    description="""
从 `cargo_heatmap_daily` 统计表读取数据。

**字段说明：**
- `node_id` / `node_name`：运输节点
- `longitude` / `latitude`：节点坐标（用于地图渲染）
- `cargo_count`：该节点装/卸货数量
- `total_tonnage`：该节点总吨位(吨)
- `stat_type`：`ORIGIN`=装货点, `DEST`=卸货点

**性能：** 仅查询统计表，响应时间 < 200ms
    """,
)
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


@router.get(
    "/trend",
    summary="货源趋势图",
    description="""
从 `cargo_stat_daily` 统计表读取最近 N 天的货源量趋势。

**字段说明：**
- `date`：日期
- `total`：当日新增货源数量
- `active`：已确认货源数量
- `pending`：待确认货源数量
- `tonnage`：当日新增总吨位(吨)

**性能：** 仅查询统计表，响应时间 < 200ms
    """,
)
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


@router.get(
    "/commodity_rank",
    summary="货品分类货源数量排名",
    description="""
从 `cargo_commodity_stat_daily` 统计表读取各货品大类的货源数量。

**字段说明：**
- `rank`：排名
- `category_name`：货品大类名称
- `cargo_count`：货源数量
- `total_tonnage`：总吨位(吨)
- `ratio`：占总量的百分比（%）

**性能：** 仅查询统计表，响应时间 < 200ms
    """,
)
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


@router.get(
    "/region_ratio",
    summary="区域货源分布占比与排名",
    description="""
从 `cargo_region_stat_daily` 统计表读取各区域货源分布数据。

**字段说明：**
- `rank`：排名
- `region_name`：区域名称
- `cargo_count`：货源数量
- `total_tonnage`：总吨位(吨)
- `ratio`：占总量的百分比（%）
- `stat_type`：`ORIGIN`=货源发出地 | `DEST`=货源到达地

**性能：** 仅查询统计表，响应时间 < 200ms
    """,
)
async def get_cargo_region_ratio(
    stat_date: Optional[date] = Query(None, description="统计日期，默认今天"),
    stat_type: str = Query("ORIGIN", description="ORIGIN=发货区域 | DEST=到货区域"),
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(get_current_user_roles),
):
    """
    返回区域货源分布占比，包含各区域货量排名及百分比，可用于饼图/柱状图。
    数据来源：`cargo_region_stat_daily` 统计表（每日 02:00 由 ETL 更新）。
    """
    data = await service.get_cargo_region_distribution(
        stat_date=stat_date, stat_type=stat_type
    )
    return success(data=data)
