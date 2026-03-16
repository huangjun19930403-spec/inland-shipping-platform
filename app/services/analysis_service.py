"""
数据分析业务服务层
职责：统计聚合、仪表盘数据、AI趋势分析编排
规则：通过Repository访问数据，通过Agent调用AI
"""
import logging
from datetime import date, timedelta
from typing import Optional

from app.repositories.analysis_repository import AnalysisRepository
from app.repositories.cargo_repository import CargoRepository
from app.repositories.address_repository import AddressRepository

logger = logging.getLogger(__name__)


class AnalysisService:
    """数据分析业务服务"""

    def __init__(
        self,
        analysis_repo: AnalysisRepository,
        cargo_repo: CargoRepository,
        address_repo: AddressRepository,
    ) -> None:
        self._analysis = analysis_repo
        self._cargo = cargo_repo
        self._address = address_repo

    # ─────────────────────────────────────────────────
    # 仪表盘
    # ─────────────────────────────────────────────────

    async def get_dashboard_summary(self) -> dict:
        cargo_by_status = await self._analysis.count_opportunities_by_status()
        active_vessels = await self._analysis.count_active_vessels()
        daily_trend = await self._analysis.get_daily_cargo_trend(days=7)
        return {
            "cargo_total": sum(cargo_by_status.values()),
            "cargo_active": cargo_by_status.get("ACTIVE", 0),
            "cargo_pending": cargo_by_status.get("PENDING", 0),
            "active_vessels": active_vessels,
            "daily_trend": [
                {"date": str(row.stat_date), "total": row.total}
                for row in daily_trend
            ],
        }

    # 别名，兼容 router
    async def get_dashboard_stats(self) -> dict:
        return await self.get_dashboard_summary()

    # ─────────────────────────────────────────────────
    # 热力图
    # ─────────────────────────────────────────────────

    async def get_cargo_heatmap(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        stat_type: str = "CARGO_ORIGIN",
        region_id: Optional[int] = None,
    ) -> list:
        target_date = start_date or date.today()
        stats = await self._analysis.get_heatmap_stats(
            stat_date=target_date, stat_type=stat_type
        )
        return [
            {
                "node_id": s.node_id,
                "stat_value": s.stat_value,
                "stat_type": s.stat_type,
                "stat_date": str(s.stat_date),
            }
            for s in stats
        ]

    async def get_vessel_heatmap(self, region_id: Optional[int] = None) -> list:
        stats = await self._analysis.get_heatmap_stats(
            stat_date=date.today(), stat_type="VESSEL"
        )
        return [
            {
                "node_id": s.node_id,
                "stat_value": s.stat_value,
                "stat_type": s.stat_type,
            }
            for s in stats
        ]

    # ─────────────────────────────────────────────────
    # 趋势
    # ─────────────────────────────────────────────────

    async def get_cargo_trends(self, days: int = 7) -> dict:
        trend = await self._analysis.get_daily_cargo_trend(days=days)
        return {
            "days": days,
            "trend": [
                {"date": str(row.stat_date), "total": int(row.total)}
                for row in trend
            ],
        }

    # ─────────────────────────────────────────────────
    # Top节点
    # ─────────────────────────────────────────────────

    async def get_top_nodes(self, stat_type: str = "CARGO_ORIGIN", limit: int = 10) -> dict:
        stats = await self._analysis.get_heatmap_stats(
            stat_date=date.today(), stat_type=stat_type
        )
        sorted_stats = sorted(stats, key=lambda s: s.stat_value, reverse=True)[:limit]
        return {
            "stat_type": stat_type,
            "nodes": [
                {"node_id": s.node_id, "stat_value": s.stat_value}
                for s in sorted_stats
            ],
        }

    # ─────────────────────────────────────────────────
    # AI分析
    # ─────────────────────────────────────────────────

    async def generate_ai_analysis(self, days: int = 7) -> dict:
        end = date.today()
        start = end - timedelta(days=days)
        stats = await self._analysis.get_heatmap_range(start, end)
        cargo_status = await self._analysis.count_opportunities_by_status()
        trend = await self._analysis.get_daily_cargo_trend(days=days)
        data_summary = self._format_data_summary(stats, cargo_status, trend, days)
        try:
            from app.agents.analysis_agent import AnalysisAgent
            agent = AnalysisAgent()
            result = await agent.run({"days": days, "data_summary": data_summary})
            if result.success:
                return result.output
        except Exception as e:
            logger.warning(f"[AnalysisService] AI analysis failed: {e}")
        return {
            "trend_summary": f"最近{days}天数据汇总",
            "cargo_highlights": [f"活跃货源{cargo_status.get('ACTIVE', 0)}条"],
            "route_highlights": [],
            "risk_factors": [],
            "recommendation": "数据分析功能需要AI服务支持",
        }

    def _format_data_summary(self, stats, cargo_status, trend, days: int) -> str:
        lines = [f"统计周期：近{days}天"]
        lines.append(f"货源状态分布：{dict(cargo_status)}")
        if trend:
            trend_str = ", ".join(f"{str(r.stat_date)}({int(r.total)})" for r in trend[-5:])
            lines.append(f"最近货量趋势：{trend_str}")
        if stats:
            top_nodes = sorted(stats, key=lambda s: s.stat_value, reverse=True)[:5]
            node_str = ", ".join(f"节点{s.node_id}({s.stat_value})" for s in top_nodes)
            lines.append(f"热门节点（TOP5）：{node_str}")
        return "\n".join(lines)

    # ─────────────────────────────────────────────────
    # 统计聚合（Celery Task 调用）
    # ─────────────────────────────────────────────────

    async def run_daily_stats(self, target_date: Optional[date] = None) -> dict:
        count = await self.compute_daily_stats(target_date)
        return {"updated_nodes": count, "target_date": str(target_date or date.today())}

    async def compute_daily_stats(self, target_date: Optional[date] = None) -> int:
        target_date = target_date or date.today()
        nodes, _ = await self._address.list_nodes(offset=0, limit=10000)
        updated_count = 0
        for node in nodes:
            _, cargo_count = await self._cargo.list_opportunities(
                origin_node_id=node.id, offset=0, limit=0
            )
            if cargo_count > 0:
                await self._analysis.upsert_heatmap_stat(
                    stat_date=target_date,
                    node_id=node.id,
                    stat_type="CARGO",
                    stat_value=cargo_count,
                )
                updated_count += 1
        await self._analysis.save()
        logger.info(f"[AnalysisService] daily stats computed date={target_date} nodes={updated_count}")
        return updated_count
