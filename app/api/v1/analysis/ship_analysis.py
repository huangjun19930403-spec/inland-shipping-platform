"""
船舶分析路由

接口列表：
  GET /api/v1/analysis/ship/heatmap           — 船舶热力图
  GET /api/v1/analysis/ship/type_ratio        — 船舶类型数量占比
  GET /api/v1/analysis/ship/age_distribution  — 船龄分布直方图
  GET /api/v1/analysis/ship/capacity_region   — 区域运力分布

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
    summary="船舶分布热力图",
    description="""
从 `ship_heatmap_daily` 统计表读取数据。
数据来源：`vessel_dynamic`（AIS 当前位置）→ ETL 按节点聚合。

**字段说明：**
- `node_id` / `node_name`：运输节点
- `longitude` / `latitude`：节点坐标（用于地图渲染）
- `vessel_count`：在港/在途船舶数量
- `total_deadweight`：总载重吨(DWT)

**性能：** 仅查询统计表，响应时间 < 200ms
    """,
)
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


@router.get(
    "/type_ratio",
    summary="船舶类型数量占比",
    description="""
从 `ship_type_stat_daily` 统计表读取各类型船舶数量分布。

**字段说明：**
- `vessel_type_id`：船型ID
- `type_name`：船型名称
- `vessel_count`：该类型船舶数量
- `total_deadweight`：总载重吨(DWT)
- `ratio`：占总数的百分比（%）

**性能：** 仅查询统计表，响应时间 < 200ms
    """,
)
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


@router.get(
    "/age_distribution",
    summary="船龄分布直方图",
    description="""
从 `ship_age_stat_daily` 统计表读取船龄分布数据。

**船龄分组：**
| 分组  | 含义       |
|-------|------------|
| 0-5   | 0～5年     |
| 5-10  | 5～10年    |
| 10-15 | 10～15年   |
| 15-20 | 15～20年   |
| 20+   | 20年及以上 |

**字段说明：**
- `age_group`：船龄分组标识
- `vessel_count`：该船龄段的船舶数量

**性能：** 仅查询统计表，响应时间 < 200ms
    """,
)
async def get_ship_age_distribution(
    stat_date: Optional[date] = Query(None, description="统计日期，默认今天"),
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(get_current_user_roles),
):
    """
    返回船龄分布统计，用于直方图渲染。船龄 = 当前年份 - 建造年份。
    数据来源：`ship_age_stat_daily` 统计表（每日 02:00 由 ETL 更新）。
    """
    items = await service.get_ship_age_distribution(stat_date=stat_date)
    return success(data={"stat_date": str(stat_date or date.today()), "items": items})


@router.get(
    "/capacity_region",
    summary="区域运力分布",
    description="""
从 `ship_capacity_region_daily` 统计表读取各区域运力数据。
数据来源：`vessel_dynamic` 当前位置 → `transport_node.region_id` → 按区域聚合。

**字段说明：**
- `region_id` / `region_name`：区域
- `vessel_count`：该区域船舶数量
- `total_deadweight`：该区域总载重吨(DWT)

**性能：** 仅查询统计表，响应时间 < 200ms
    """,
)
async def get_ship_capacity_region(
    stat_date: Optional[date] = Query(None, description="统计日期，默认今天"),
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(get_current_user_roles),
):
    """
    返回各区域运力分布（船舶数量 + 总载重吨位），用于柱状图/地图渲染。
    数据来源：`ship_capacity_region_daily` 统计表（每日 02:00 由 ETL 更新）。
    """
    items = await service.get_ship_capacity_region(stat_date=stat_date)
    return success(data={"stat_date": str(stat_date or date.today()), "items": items})
