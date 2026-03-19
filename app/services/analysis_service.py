"""
数据分析业务服务层

职责：
  - 从统计表读取数据并组装为 API 所需结构
  - 禁止直接查询业务表（统计数据由 stat_tasks.py 写入统计表）

依赖：
  AnalysisRepository — 所有数据读取均通过统计表
"""
import logging
from datetime import date, timedelta
from typing import Optional

from app.repositories.analysis_repository import AnalysisRepository

logger = logging.getLogger(__name__)


class AnalysisService:
    """数据分析业务服务"""

    def __init__(self, analysis_repo: AnalysisRepository) -> None:
        self._analysis = analysis_repo

    # ─────────────────────────────────────────────────
    # 仪表盘
    # ─────────────────────────────────────────────────

    async def get_dashboard_stats(self) -> dict:
        cargo_stat = await self._analysis.get_latest_cargo_stat()
        # 从区域快照汇总船舶总数和总运力
        region_rows = await self._analysis.get_ship_stat_region()
        vessel_count = sum(r.vessel_count for r in region_rows)
        total_deadweight = sum(float(r.total_deadweight or 0) for r in region_rows)
        return {
            "cargo_total": cargo_stat.total_count if cargo_stat else 0,
            "cargo_confirmed": cargo_stat.confirmed_count if cargo_stat else 0,
            "cargo_pending": cargo_stat.pending_count if cargo_stat else 0,
            "cargo_tonnage": float(cargo_stat.total_tonnage or 0) if cargo_stat else 0,
            "active_vessels": vessel_count,
            "vessel_deadweight": total_deadweight,
            "stat_date": str(cargo_stat.stat_date) if cargo_stat else None,
        }

    # ─────────────────────────────────────────────────
    # 货源城市热力图
    # ─────────────────────────────────────────────────

    async def get_cargo_heatmap(
        self,
        stat_date: Optional[date] = None,
        stat_type: str = "ORIGIN",
    ) -> list:
        """返回城市级货源热力数据，含城市经纬度，用于热力地图渲染"""
        target = stat_date or date.today()
        rows = await self._analysis.get_cargo_city_heatmap(
            stat_date=target, stat_type=stat_type
        )
        return [
            {
                "city_code": r.city_code,
                "city_name": r.city_name,
                "cargo_count": r.cargo_count,
                "total_tonnage": float(r.total_tonnage or 0),
                "stat_type": r.stat_type,
                "stat_date": str(r.stat_date),
                "longitude": float(r.city_longitude) if r.city_longitude else None,
                "latitude": float(r.city_latitude) if r.city_latitude else None,
            }
            for r in rows
        ]

    # ─────────────────────────────────────────────────
    # 货源趋势图
    # ─────────────────────────────────────────────────

    async def get_cargo_trend(
        self,
        days: int = 30,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> dict:
        rows = await self._analysis.get_cargo_trend(
            days=days, start_date=start_date, end_date=end_date
        )
        return {
            "days": days,
            "trend": [
                {
                    "date": str(r.stat_date),
                    "total": r.total_count,
                    "confirmed": r.confirmed_count,
                    "pending": r.pending_count,
                    "tonnage": float(r.total_tonnage or 0),
                    "avg_tonnage": float(r.avg_tonnage or 0),
                }
                for r in rows
            ],
        }

    # ─────────────────────────────────────────────────
    # 货品分类货源排名
    # ─────────────────────────────────────────────────

    async def get_cargo_commodity_rank(self, stat_date: Optional[date] = None) -> list:
        target = stat_date or date.today()
        rows = await self._analysis.get_cargo_commodity_stat(stat_date=target)
        total = sum(r.cargo_count for r in rows) or 1
        return [
            {
                "rank": idx + 1,
                "commodity_category_id": r.commodity_category_id,
                "category_name": r.category_name,
                "cargo_count": r.cargo_count,
                "total_tonnage": float(r.total_tonnage or 0),
                "ratio": round(r.cargo_count / total * 100, 2),
            }
            for idx, r in enumerate(rows)
        ]

    # ─────────────────────────────────────────────────
    # 起终点城市OD流量矩阵
    # ─────────────────────────────────────────────────

    async def get_cargo_od_stats(
        self,
        stat_date: Optional[date] = None,
        days: int = 7,
        top_n: int = 20,
    ) -> dict:
        """返回Top N OD流量，用于 Sankey 图或路线排行

        当 stat_date 指定时返回单日数据，否则返回最近 days 天聚合数据。
        """
        if stat_date:
            rows = await self._analysis.get_cargo_od_stat(
                stat_date=stat_date, top_n=top_n
            )
            items = [
                {
                    "origin_city_code": r.origin_city_code,
                    "origin_city_name": r.origin_city_name,
                    "dest_city_code": r.dest_city_code,
                    "dest_city_name": r.dest_city_name,
                    "cargo_count": r.cargo_count,
                    "total_tonnage": float(r.total_tonnage or 0),
                }
                for r in rows
            ]
        else:
            end = date.today()
            start = end - timedelta(days=days - 1)
            rows = await self._analysis.get_cargo_od_range(
                start_date=start, end_date=end, top_n=top_n
            )
            items = [
                {
                    "origin_city_code": r.origin_city_code,
                    "origin_city_name": r.origin_city_name,
                    "dest_city_code": r.dest_city_code,
                    "dest_city_name": r.dest_city_name,
                    "cargo_count": int(r.cargo_count or 0),
                    "total_tonnage": float(r.total_tonnage or 0),
                }
                for r in rows
            ]

        return {
            "stat_date": str(stat_date) if stat_date else None,
            "days": None if stat_date else days,
            "top_n": top_n,
            "items": items,
        }

    # ─────────────────────────────────────────────────
    # 渠道质量统计
    # ─────────────────────────────────────────────────

    async def get_cargo_channel_stats(
        self,
        stat_date: Optional[date] = None,
        days: int = 30,
    ) -> dict:
        """返回各录入渠道的质量统计数据，用于堆叠面积图或数据质量卡片"""
        if stat_date:
            rows = await self._analysis.get_cargo_channel_stat(stat_date=stat_date)
            items = [
                {
                    "source_type": r.source_type,
                    "raw_msg_count": r.raw_msg_count,
                    "parse_success_count": r.parse_success_count,
                    "confirmed_count": r.confirmed_count,
                    "total_tonnage": float(r.total_tonnage or 0),
                    "parse_rate": (
                        round(r.parse_success_count / r.raw_msg_count * 100, 1)
                        if r.raw_msg_count else None
                    ),
                    "stat_date": str(r.stat_date),
                }
                for r in rows
            ]
            return {"stat_date": str(stat_date), "items": items}
        else:
            rows = await self._analysis.get_cargo_channel_trend(days=days)
            grouped: dict[str, list] = {}
            for r in rows:
                grouped.setdefault(r.source_type, []).append({
                    "date": str(r.stat_date),
                    "raw_msg_count": r.raw_msg_count,
                    "parse_success_count": r.parse_success_count,
                    "confirmed_count": r.confirmed_count,
                    "total_tonnage": float(r.total_tonnage or 0),
                })
            return {"days": days, "channels": grouped}

    # ─────────────────────────────────────────────────
    # 船舶区域热力图（快照）
    # ─────────────────────────────────────────────────

    async def get_ship_region_heatmap(self) -> dict:
        """返回各商业区域的船舶数量和运力快照，含多边形边界坐标供前端绘图"""
        rows = await self._analysis.get_ship_stat_region()
        items = [
            {
                "region_id": r.region_id,
                "region_name": r.region_name,
                "center_longitude": float(r.center_longitude) if r.center_longitude else None,
                "center_latitude": float(r.center_latitude) if r.center_latitude else None,
                "boundary_coordinates": r.boundary_coordinates,
                "vessel_count": r.vessel_count,
                "total_deadweight": float(r.total_deadweight or 0),
                "ratio": float(r.ratio or 0),
                "refreshed_at": r.refreshed_at.isoformat() if r.refreshed_at else None,
            }
            for r in rows
        ]
        return {
            "total_vessels": sum(r["vessel_count"] for r in items),
            "items": items,
        }

    # ─────────────────────────────────────────────────
    # 船舶城市热力图（快照）
    # ─────────────────────────────────────────────────

    async def get_ship_city_heatmap(
        self,
        level: str = "city",
        province_name: Optional[str] = None,
    ) -> dict:
        """返回城市/省份级船舶分布热力数据

        level='city'     — 返回各城市的 vessel_count / total_deadweight / 经纬度
        level='province' — 在服务层按 province_name 聚合（无需额外DB查询）
        province_name    — 过滤指定省份（city模式下生效）
        """
        rows = await self._analysis.get_ship_stat_city(
            province_name=province_name if level == "city" else None
        )

        if level == "province":
            # 省级聚合
            prov: dict[str, dict] = {}
            for r in rows:
                pn = r.province_name or "未知"
                if pn not in prov:
                    prov[pn] = {"province_name": pn, "vessel_count": 0, "total_deadweight": 0.0}
                prov[pn]["vessel_count"] += r.vessel_count
                prov[pn]["total_deadweight"] += float(r.total_deadweight or 0)
            total = sum(p["vessel_count"] for p in prov.values()) or 1
            items = sorted(prov.values(), key=lambda x: x["vessel_count"], reverse=True)
            for item in items:
                item["ratio"] = round(item["vessel_count"] / total * 100, 2)
            return {"level": "province", "total_vessels": total, "items": items}

        # 城市级
        total = sum(r.vessel_count for r in rows) or 1
        items = [
            {
                "city_code": r.city_code,
                "city_name": r.city_name,
                "province_name": r.province_name,
                "longitude": float(r.longitude) if r.longitude else None,
                "latitude": float(r.latitude) if r.latitude else None,
                "vessel_count": r.vessel_count,
                "total_deadweight": float(r.total_deadweight or 0),
                "ratio": float(r.ratio or 0),
                "refreshed_at": r.refreshed_at.isoformat() if r.refreshed_at else None,
            }
            for r in rows
        ]
        return {
            "level": "city",
            "province_name": province_name,
            "total_vessels": total,
            "items": items,
        }

    # ─────────────────────────────────────────────────
    # 载重吨分布
    # ─────────────────────────────────────────────────

    async def get_ship_dwt_distribution(self) -> dict:
        """返回船舶载重吨区间分布快照"""
        rows = await self._analysis.get_ship_stat_dwt()
        total = sum(r.vessel_count for r in rows) or 1
        items = [
            {
                "segment_label": r.segment_label,
                "min_dwt": r.min_dwt,
                "max_dwt": r.max_dwt,
                "vessel_count": r.vessel_count,
                "ratio": float(r.ratio or 0),
                "refreshed_at": r.refreshed_at.isoformat() if r.refreshed_at else None,
            }
            for r in rows
        ]
        return {
            "total_vessels": total,
            "items": items,
        }

    # ─────────────────────────────────────────────────
    # 船龄分布
    # ─────────────────────────────────────────────────

    async def get_ship_age_distribution(self) -> dict:
        """返回船舶船龄区间分布快照"""
        rows = await self._analysis.get_ship_stat_age()
        total = sum(r.vessel_count for r in rows) or 1
        items = [
            {
                "age_range_label": r.age_range_label,
                "min_age": r.min_age,
                "max_age": r.max_age,
                "vessel_count": r.vessel_count,
                "ratio": float(r.ratio or 0),
                "refreshed_at": r.refreshed_at.isoformat() if r.refreshed_at else None,
            }
            for r in rows
        ]
        return {
            "total_vessels": total,
            "items": items,
        }

    # ─────────────────────────────────────────────────
    # 手动触发统计（管理员）
    # ─────────────────────────────────────────────────

    async def run_daily_stats(self, target_date: Optional[date] = None) -> dict:
        from app.tasks.stat_tasks import daily_stat_job
        return await daily_stat_job(target_date=target_date)

    async def run_ship_stats(self) -> dict:
        """手动触发全量船舶统计刷新（管理员，忽略节流）"""
        from app.tasks.stat_tasks import refresh_all_vessel_stats
        return await refresh_all_vessel_stats()
