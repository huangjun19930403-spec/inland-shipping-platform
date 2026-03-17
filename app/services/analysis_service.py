"""
数据分析业务服务层

职责：
  - 从统计表读取数据并组装为 API 所需结构
  - 禁止直接查询业务表（统计数据由 stat_tasks.py ETL 写入统计表）

依赖：
  AnalysisRepository — 所有数据读取均通过统计表
"""
import logging
from datetime import date
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
        ship_stat = await self._analysis.get_latest_ship_total()
        return {
            "cargo_total": cargo_stat.total_count if cargo_stat else 0,
            "cargo_active": cargo_stat.active_count if cargo_stat else 0,
            "cargo_pending": cargo_stat.pending_count if cargo_stat else 0,
            "active_vessels": ship_stat["vessel_count"],
        }

    # ─────────────────────────────────────────────────
    # 货源热力图
    # ─────────────────────────────────────────────────

    async def get_cargo_heatmap(
        self,
        stat_date: Optional[date] = None,
        stat_type: str = "ORIGIN",
        region_id: Optional[int] = None,
    ) -> list:
        target = stat_date or date.today()
        rows = await self._analysis.get_cargo_heatmap(stat_date=target, stat_type=stat_type)
        result = []
        for r in rows:
            node = r.node
            if region_id and node and node.region_id != region_id:
                continue
            result.append({
                "node_id": r.node_id,
                "cargo_count": r.cargo_count,
                "total_tonnage": float(r.total_tonnage or 0),
                "stat_type": r.stat_type,
                "stat_date": str(r.stat_date),
                "longitude": float(node.longitude) if node and node.longitude else None,
                "latitude": float(node.latitude) if node and node.latitude else None,
                "node_name": node.name if node else None,
            })
        return result

    # ─────────────────────────────────────────────────
    # 货源趋势图
    # ─────────────────────────────────────────────────

    async def get_cargo_trend(self, days: int = 30) -> dict:
        rows = await self._analysis.get_cargo_trend(days=days)
        return {
            "days": days,
            "trend": [
                {
                    "date": str(r.stat_date),
                    "total": r.total_count,
                    "active": r.active_count,
                    "pending": r.pending_count,
                    "tonnage": float(r.total_tonnage or 0),
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
    # 船舶热力图
    # ─────────────────────────────────────────────────

    async def get_ship_heatmap(
        self,
        stat_date: Optional[date] = None,
        region_id: Optional[int] = None,
    ) -> list:
        target = stat_date or date.today()
        rows = await self._analysis.get_ship_heatmap(stat_date=target)
        result = []
        for r in rows:
            node = r.node
            if region_id and node and node.region_id != region_id:
                continue
            result.append({
                "node_id": r.node_id,
                "vessel_count": r.vessel_count,
                "total_deadweight": float(r.total_deadweight or 0),
                "stat_date": str(r.stat_date),
                "longitude": float(node.longitude) if node and node.longitude else None,
                "latitude": float(node.latitude) if node and node.latitude else None,
                "node_name": node.name if node else None,
            })
        return result

    # ─────────────────────────────────────────────────
    # 船型占比
    # ─────────────────────────────────────────────────

    async def get_ship_type_ratio(self, stat_date: Optional[date] = None) -> list:
        target = stat_date or date.today()
        rows = await self._analysis.get_ship_type_stat(stat_date=target)
        total = sum(r.vessel_count for r in rows) or 1
        return [
            {
                "vessel_type_id": r.vessel_type_id,
                "type_name": r.type_name,
                "vessel_count": r.vessel_count,
                "total_deadweight": float(r.total_deadweight or 0),
                "ratio": round(r.vessel_count / total * 100, 2),
            }
            for r in rows
        ]

    # ─────────────────────────────────────────────────
    # 手动触发统计（管理员）
    # ─────────────────────────────────────────────────

    async def run_daily_stats(self, target_date: Optional[date] = None) -> dict:
        from app.tasks.stat_tasks import daily_stat_job
        return await daily_stat_job(target_date=target_date)
