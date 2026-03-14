"""
数据分析Agent
职责：基于历史数据生成AI驱动的市场分析报告
"""
import logging
from typing import Any

from app.ai.base import BaseAgent, AgentResult
from app.ai.llm_client import json_completion
from app.ai.prompt_templates import get_template

logger = logging.getLogger(__name__)


class AnalysisAgent(BaseAgent):
    """
    数据分析Agent

    输入：数据摘要（由Service层准备好后传入）
    输出：结构化分析报告

    注意：此Agent接收已聚合的数据，不直接访问数据库。
    """

    name = "analysis_agent"
    description = "基于货运数据生成AI市场趋势分析报告"
    tools = []

    async def run(self, input_data: dict[str, Any]) -> AgentResult:
        """
        Args:
            input_data: {
                "days": int,
                "data_summary": str  # 已格式化的数据摘要
            }
        """
        days = input_data.get("days", 7)
        data_summary = input_data.get("data_summary", "")
        steps = []

        if not data_summary:
            return AgentResult(
                success=False,
                error="No data summary provided",
            )

        steps.append(f"analysis: generating {days}-day trend report")
        template = get_template("cargo_trend_analysis")
        user_message = template.format_user(
            days=days,
            data_summary=data_summary,
        )

        try:
            result = await json_completion(
                system_prompt=template.system,
                user_message=user_message,
                max_tokens=1024,
            )
            logger.info(f"[AnalysisAgent] generated report for {days} days")
            return AgentResult(success=True, output=result, steps=steps)

        except Exception as e:
            logger.error(f"[AnalysisAgent] Error: {e}")
            return AgentResult(success=False, error=str(e), steps=steps)
