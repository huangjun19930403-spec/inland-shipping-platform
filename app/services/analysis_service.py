"""
数据分析业务服务层

职责：
  - 从统计表读取数据并组装为 API 所需结构
  - 禁止直接查询业务表（统计数据由 stat_tasks.py ETL 写入统计表）
  - AI 趋势分析编排（可选功能）

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
    # 仪表盘（从统计表读取，不查业务表）
    # ─────────────────────────────────────────────────

    async def get_dashboard_stats(self) -> dict:
        cargo_stat = await self._analysis.get_latest_cargo_stat()
        ship_stat = await self._analysis.get_latest_ship_total()
        trend = await self._analysis.get_cargo_trend(days=7)
        return {
            "cargo_total": cargo_stat.total_count if cargo_stat else 0,
            "cargo_active": cargo_stat.active_count if cargo_stat else 0,
            "cargo_pending": cargo_stat.pending_count if cargo_stat else 0,
            "active_vessels": ship_stat["vessel_count"],
            "daily_trend": [
                {"date": str(r.stat_date), "total": r.total_count}
                for r in trend
            ],
        }

    # 别名，保持向后兼容
    async def get_dashboard_summary(self) -> dict:
        return await self.get_dashboard_stats()

    # ─────────────────────────────────────────────────
    # 货源热力图
    # ─────────────────────────────────────────────────

    async def get_cargo_heatmap(
        self,
        stat_date: Optional[date] = None,
        stat_type: str = "ORIGIN",
        region_id: Optional[int] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list:
        target = stat_date or end_date or date.today()
        rows = await self._analysis.get_cargo_heatmap(stat_date=target, stat_type=stat_type)
        result = []
        for r in rows:
            node = r.node
            item = {
                "node_id": r.node_id,
                "cargo_count": r.cargo_count,
                "total_tonnage": float(r.total_tonnage or 0),
                "stat_type": r.stat_type,
                "stat_date": str(r.stat_date),
                "longitude": float(node.longitude) if node and node.longitude else None,
                "latitude": float(node.latitude) if node and node.latitude else None,
                "node_name": node.name if node else None,
            }
            # 可选区域过滤
            if region_id and node and node.region_id != region_id:
                continue
            result.append(item)
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

    # 旧接口别名
    async def get_cargo_trends(self, days: int = 7) -> dict:
        return await self.get_cargo_trend(days=days)

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
    # 区域货源分布占比 + 排名
    # ─────────────────────────────────────────────────

    async def get_cargo_region_distribution(
        self,
        stat_date: Optional[date] = None,
        stat_type: str = "ORIGIN",
    ) -> dict:
        target = stat_date or date.today()
        rows = await self._analysis.get_cargo_region_stat(stat_date=target, stat_type=stat_type)
        total = sum(r.cargo_count for r in rows) or 1
        items = [
            {
                "rank": idx + 1,
                "region_id": r.region_id,
                "region_name": r.region_name,
                "cargo_count": r.cargo_count,
                "total_tonnage": float(r.total_tonnage or 0),
                "ratio": round(r.cargo_count / total * 100, 2),
            }
            for idx, r in enumerate(rows)
        ]
        return {
            "stat_type": stat_type,
            "stat_date": str(target),
            "total": sum(r.cargo_count for r in rows),
            "items": items,
        }

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

    # 旧接口别名（兼容 analysis/router.py）
    async def get_vessel_heatmap(self, region_id: Optional[int] = None) -> list:
        return await self.get_ship_heatmap(region_id=region_id)

    # ─────────────────────────────────────────────────
    # 船舶类型数量占比
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
    # 船龄分布直方图
    # ─────────────────────────────────────────────────

    async def get_ship_age_distribution(self, stat_date: Optional[date] = None) -> list:
        target = stat_date or date.today()
        rows = await self._analysis.get_ship_age_stat(stat_date=target)
        return [
            {
                "age_group": r.age_group,
                "vessel_count": r.vessel_count,
            }
            for r in rows
        ]

    # ─────────────────────────────────────────────────
    # 区域运力分布（船舶数量 + 总载重吨）
    # ─────────────────────────────────────────────────

    async def get_ship_capacity_region(self, stat_date: Optional[date] = None) -> list:
        target = stat_date or date.today()
        rows = await self._analysis.get_ship_capacity_region(stat_date=target)
        return [
            {
                "region_id": r.region_id,
                "region_name": r.region_name,
                "vessel_count": r.vessel_count,
                "total_deadweight": float(r.total_deadweight or 0),
            }
            for r in rows
        ]

    # ─────────────────────────────────────────────────
    # 旧接口 Top节点（兼容）
    # ─────────────────────────────────────────────────

    async def get_top_nodes(self, stat_type: str = "CARGO_ORIGIN", limit: int = 10) -> dict:
        target = date.today()
        # 映射到新接口
        new_type = "ORIGIN" if "ORIGIN" in stat_type else ("DEST" if "DEST" in stat_type else None)
        if stat_type == "VESSEL":
            rows = await self._analysis.get_ship_heatmap(stat_date=target)
            nodes = [
                {"node_id": r.node_id, "stat_value": r.vessel_count}
                for r in rows[:limit]
            ]
        else:
            rows = await self._analysis.get_cargo_heatmap(stat_date=target, stat_type=new_type)
            nodes = [
                {"node_id": r.node_id, "stat_value": r.cargo_count}
                for r in rows[:limit]
            ]
        return {"stat_type": stat_type, "nodes": nodes}

    # ─────────────────────────────────────────────────
    # 手动触发统计（管理员接口调用，委托 stat_tasks）
    # ─────────────────────────────────────────────────

    async def run_daily_stats(self, target_date: Optional[date] = None) -> dict:
        """手动触发每日统计聚合（管理员接口）"""
        from app.tasks.stat_tasks import daily_stat_job
        result = await daily_stat_job(target_date=target_date)
        return result

    # ─────────────────────────────────────────────────
    # AI分析（可选）
    # ─────────────────────────────────────────────────

    async def generate_ai_analysis(self, days: int = 7) -> dict:
        cargo_stat = await self._analysis.get_latest_cargo_stat()
        return {
            "trend_summary": f"最近{days}天数据汇总",
            "cargo_highlights": [f"活跃货源{cargo_stat.active_count if cargo_stat else 0}条"],
            "route_highlights": [],
            "risk_factors": [],
            "recommendation": "AI趋势分析功能待实现",
        }

    def _format_summary(self, trend, cargo_stat, days: int) -> str:
        lines = [f"统计周期：近{days}天"]
        if cargo_stat:
            lines.append(
                f"货源状态：总量={cargo_stat.total_count}，"
                f"已确认={cargo_stat.active_count}，"
                f"待确认={cargo_stat.pending_count}"
            )
        if trend:
            trend_str = ", ".join(
                f"{str(r.stat_date)}({r.total_count})" for r in trend[-5:]
            )
            lines.append(f"最近货量趋势：{trend_str}")
        return "\n".join(lines)
