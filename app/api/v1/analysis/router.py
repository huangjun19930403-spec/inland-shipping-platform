"""
统计分析路由

接口列表：
  GET  /analysis/dashboard             — 仪表盘统计数据
  POST /analysis/run-stats             — 手动触发货源+船舶全量统计（管理员）
  POST /analysis/run-stats/ship        — 手动触发船舶统计刷新（管理员）
  GET  /analysis/cargo/heatmap         — 货源城市热力图
  GET  /analysis/cargo/trend           — 货源趋势图
  GET  /analysis/cargo/commodity_rank  — 货品分类货源数量排名
  GET  /analysis/cargo/od_flow         — 起终点城市OD流量矩阵
  GET  /analysis/cargo/channel_stats   — 各录入渠道质量统计
  GET  /analysis/ship/region_heatmap   — 船舶区域热力图（快照）
  GET  /analysis/ship/city_heatmap     — 船舶城市热力图（快照，支持省级聚合）
  GET  /analysis/ship/dwt_dist         — 船舶载重吨区间分布
  GET  /analysis/ship/age_dist         — 船舶船龄区间分布

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
from app.domain.analysis.service import AnalysisService

router = APIRouter()


@router.get("/dashboard", summary="仪表盘统计数据", tags=["数据分析"])
async def get_dashboard(
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(get_current_user_roles),
):
    data = await service.get_dashboard_stats()
    return success(data=data)


@router.post("/run-stats", summary="手动触发货源+船舶全量统计聚合（管理员）", tags=["数据分析"])
async def run_daily_stats(
    target_date: Optional[date] = None,
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    result = await service.run_daily_stats(target_date=target_date)
    return success(data=result, message="统计聚合完成")


@router.post("/run-stats/ship", summary="手动触发船舶统计全量刷新（管理员）", tags=["数据分析"])
async def run_ship_stats(
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    """
    强制触发四张船舶统计快照的全量重算（忽略 Kafka 节流限制）。
    适用于初始化数据、数据修正、手动校验等场景。
    """
    result = await service.run_ship_stats()
    return success(data=result, message="船舶统计刷新完成")


@router.get("/cargo/heatmap", summary="货源城市热力图", tags=["数据分析"])
async def get_cargo_heatmap(
    stat_date: Optional[date] = Query(None, description="统计日期，默认今天"),
    stat_type: str = Query("ORIGIN", description="ORIGIN=装货热力 | DEST=卸货热力"),
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(get_current_user_roles),
):
    """
    返回指定日期各城市的货源热力数据（含城市经纬度），用于前端城市级热力地图渲染。
    数据来源：`cargo_city_heatmap` 统计表（货源写入后事件驱动更新）。

    前端建议：使用经纬度渲染 Leaflet/AMap 热力图，按 cargo_count 设置半径权重。
    """
    items = await service.get_cargo_heatmap(stat_date=stat_date, stat_type=stat_type)
    return success(data={"stat_date": str(stat_date or date.today()), "items": items})


@router.get("/cargo/trend", summary="货源趋势图", tags=["数据分析"])
async def get_cargo_trend(
    days: int = Query(30, ge=1, le=365, description="统计天数，最多365天"),
    start_date: Optional[date] = Query(None, description="起始日期（与days二选一）"),
    end_date: Optional[date] = Query(None, description="结束日期"),
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(get_current_user_roles),
):
    """
    返回最近 N 天每日货源数量趋势，用于折线图渲染。
    数据来源：`cargo_stat_daily` 统计表（事件驱动更新）。

    前端建议：折线图，X轴日期，Y轴 total/confirmed/pending 三条线，次Y轴 tonnage。
    """
    data = await service.get_cargo_trend(
        days=days, start_date=start_date, end_date=end_date
    )
    return success(data=data)


@router.get("/cargo/commodity_rank", summary="货品分类货源数量排名", tags=["数据分析"])
async def get_cargo_commodity_rank(
    stat_date: Optional[date] = Query(None, description="统计日期，默认今天"),
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(get_current_user_roles),
):
    """
    返回货品分类货源数量排名（降序），含占比。
    数据来源：`cargo_commodity_stat_daily` 统计表（事件驱动更新）。

    前端建议：横向柱状图或饼图，展示各分类货源数占比。
    """
    items = await service.get_cargo_commodity_rank(stat_date=stat_date)
    return success(data={"stat_date": str(stat_date or date.today()), "items": items})


@router.get("/cargo/od_flow", summary="起终点城市OD流量矩阵", tags=["数据分析"])
async def get_cargo_od_flow(
    stat_date: Optional[date] = Query(
        None, description="统计日期（不填则返回最近 days 天聚合）"
    ),
    days: int = Query(7, ge=1, le=90, description="聚合天数，stat_date为空时生效"),
    top_n: int = Query(20, ge=5, le=100, description="返回流量最大的 Top N 路线"),
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(get_current_user_roles),
):
    """
    返回起终点城市 OD 流量 Top N，用于 Sankey 桑基图或路线排行榜渲染。
    数据来源：`cargo_od_daily` 统计表（事件驱动更新）。

    前端建议：
    - Sankey 图：origin_city_name → dest_city_name，节点宽度按 cargo_count
    - 表格排行：显示路线名、货源数、总吨位
    """
    data = await service.get_cargo_od_stats(
        stat_date=stat_date, days=days, top_n=top_n
    )
    return success(data=data)


@router.get("/cargo/channel_stats", summary="各录入渠道质量统计", tags=["数据分析"])
async def get_cargo_channel_stats(
    stat_date: Optional[date] = Query(
        None, description="统计日期（不填则返回最近 days 天趋势）"
    ),
    days: int = Query(30, ge=1, le=365, description="趋势天数，stat_date为空时生效"),
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(get_current_user_roles),
):
    """
    返回 TMS / WECHAT_AI / MANUAL 三个渠道的质量统计数据。
    数据来源：`cargo_channel_daily` 统计表（事件驱动更新）。

    单日模式（stat_date 指定）：返回各渠道的 items 列表，含解析率
    趋势模式（days 指定）：返回按渠道分组的时间序列，用于堆叠面积图

    前端建议：
    - 数据质量卡片：今日三渠道各项指标对比
    - 堆叠面积图：X轴日期，Y轴按渠道堆叠 confirmed_count
    """
    data = await service.get_cargo_channel_stats(stat_date=stat_date, days=days)
    return success(data=data)


@router.get("/ship/region_heatmap", summary="船舶区域热力图（快照）", tags=["数据分析"])
async def get_ship_region_heatmap(
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(get_current_user_roles),
):
    """
    返回各商业区域（Region）的船舶数量和运力快照，含多边形边界坐标。
    数据来源：`ship_stat_region` 快照表（Kafka AIS 更新触发 30s 节流刷新）。

    前端建议：
    - 多边形热力地图：用 boundary_coordinates 绘制区域边界，按 vessel_count 着色
    - 区域运力气泡：以 center_longitude/center_latitude 为圆心，total_deadweight 控制圆半径
    """
    data = await service.get_ship_region_heatmap()
    return success(data=data)


@router.get("/ship/city_heatmap", summary="船舶城市热力图（快照）", tags=["数据分析"])
async def get_ship_city_heatmap(
    level: str = Query("city", description="聚合粒度：city=城市级 | province=省级"),
    province_name: Optional[str] = Query(None, description="按省份过滤（city级别时生效）"),
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(get_current_user_roles),
):
    """
    返回城市或省级别的船舶分布热力数据。
    数据来源：`ship_stat_city` 快照表（Kafka AIS 更新触发 30s 节流刷新）。

    city 模式：每条数据含城市经纬度，可渲染气泡热力地图
    province 模式：按省份聚合，适合全国大图概览

    前端建议：
    - city 级：气泡地图，以 longitude/latitude 定位，vessel_count 控制气泡大小
    - province 级：省级 choropleth 地图（需配合省级 GeoJSON 边界）
    """
    data = await service.get_ship_city_heatmap(
        level=level, province_name=province_name
    )
    return success(data=data)


@router.get("/ship/dwt_dist", summary="船舶载重吨区间分布", tags=["数据分析"])
async def get_ship_dwt_distribution(
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(get_current_user_roles),
):
    """
    返回船舶载重吨区间分布快照（6个档位）。
    数据来源：`ship_stat_dwt` 快照表（vessel CRUD/批量导入后触发刷新）。

    档位：500吨以下 / 500-1000吨 / 1000-2000吨 / 2000-5000吨 / 5000吨以上 / 未录入

    前端建议：柱状图或直方图，X轴档位标签，Y轴船舶数量，可叠加比例标注。
    """
    data = await service.get_ship_dwt_distribution()
    return success(data=data)


@router.get("/ship/age_dist", summary="船舶船龄区间分布", tags=["数据分析"])
async def get_ship_age_distribution(
    service: AnalysisService = Depends(get_analysis_service),
    _=Depends(get_current_user_roles),
):
    """
    返回船舶船龄区间分布快照（6个档位，基于 vessel.build_year 实时计算）。
    数据来源：`ship_stat_age` 快照表（vessel CRUD/批量导入后触发刷新）。

    档位：5年以内 / 6-10年 / 11-15年 / 16-20年 / 20年以上 / 未知

    前端建议：柱状图，X轴船龄档位，Y轴船舶数量，可配合 ratio 显示占比饼图。
    """
    data = await service.get_ship_age_distribution()
    return success(data=data)
