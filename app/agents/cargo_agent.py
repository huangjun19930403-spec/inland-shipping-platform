"""
货源解析Agent
职责：协调多个Tool完成货运文本的完整解析流程
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import BaseAgent, AgentResult
from app.ai.entity_cache import get_nodes, get_commodities
from app.ai.providers.base import LLMCallResult
from app.tools.cargo_tools import CargoParseTextTool
from app.tools.entity_match_tools import EntityMatchTool, MatchCandidate

logger = logging.getLogger(__name__)


@dataclass
class CargoParseOutput:
    """货源解析输出结构"""
    # 原始AI提取结果
    origin_text: Optional[str]
    destination_text: Optional[str]
    commodity_text: Optional[str]
    tonnage: Optional[float]
    loading_date: Optional[str]
    freight_price: Optional[float]
    contact: Optional[str]
    remarks: str

    # 实体匹配结果
    origin_node_id: Optional[int]
    origin_node_name: Optional[str]
    origin_confidence: int

    dest_node_id: Optional[int]
    dest_node_name: Optional[str]
    dest_confidence: int

    commodity_standard_id: Optional[int]
    commodity_standard_name: Optional[str]
    commodity_confidence: int

    # 候选列表（用于人工确认）
    origin_candidates: list[MatchCandidate]
    dest_candidates: list[MatchCandidate]
    commodity_candidates: list[MatchCandidate]

    # 整体置信度（各字段平均）
    overall_confidence: int

    # LLM调用元数据（用于写 AiCallLog）
    template_id: Optional[int] = None
    template_version: Optional[int] = None
    call_result: Optional[LLMCallResult] = None


class CargoAgent(BaseAgent):
    """
    货源解析Agent

    执行流程：
    1. [cargo_parse_text] 调用LLM提取结构化字段（使用DB提示词 + TTL缓存）
    2. 从实体缓存获取节点和商品数据（TTL 10分钟，避免每次全量查询）
    3. [entity_match] 分别匹配起点、终点、商品实体
    4. 组装最终结构化结果，携带LLM调用元数据
    """

    name = "cargo_agent"
    description = "解析原始货运文本，提取并匹配结构化信息"

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._parse_tool = CargoParseTextTool(db)
        self._match_tool = EntityMatchTool()
        self.tools = [self._parse_tool, self._match_tool]

    async def run(self, input_data: dict[str, Any]) -> AgentResult:
        """
        Args:
            input_data: {"raw_text": str}

        Returns:
            AgentResult.output = CargoParseOutput
        """
        raw_text = input_data.get("raw_text", "")
        steps = []

        # Step 1: 文本解析（LLM）
        steps.append("cargo_parse_text: extracting fields from raw text")
        parse_result = await self._parse_tool.execute(raw_text=raw_text)

        if not parse_result.success and not parse_result.data:
            return AgentResult(
                success=False,
                error=f"Text parsing failed: {parse_result.error}",
                steps=steps,
            )

        tool_data = parse_result.data or {}
        parsed = tool_data.get("fields", {})
        template_id: Optional[int] = tool_data.get("template_id")
        template_version: Optional[int] = tool_data.get("template_version")
        call_result: Optional[LLMCallResult] = tool_data.get("call_result")

        origin_text = parsed.get("origin", {}).get("value")
        dest_text = parsed.get("destination", {}).get("value")
        commodity_text = parsed.get("commodity", {}).get("value")
        tonnage_data = parsed.get("tonnage", {})
        price_data = parsed.get("freight_price", {})

        # Step 2: 从缓存获取基础数据（避免每次全量 SELECT）
        steps.append("entity_cache: loading nodes and commodities")
        nodes = await get_nodes(self._db)
        commodities = await get_commodities(self._db)

        # Step 3: 实体匹配
        steps.append(f"entity_match: matching origin '{origin_text}'")
        origin_match = await self._match_entity(origin_text, nodes)

        steps.append(f"entity_match: matching destination '{dest_text}'")
        dest_match = await self._match_entity(dest_text, nodes)

        steps.append(f"entity_match: matching commodity '{commodity_text}'")
        commodity_match = await self._match_entity(commodity_text, commodities)

        # Step 4: 计算综合置信度
        confidences = [
            origin_match["match_confidence"],
            dest_match["match_confidence"],
            commodity_match["match_confidence"],
        ]
        overall_confidence = int(sum(confidences) / len(confidences))

        # Step 5: 组装输出
        output = CargoParseOutput(
            origin_text=origin_text,
            destination_text=dest_text,
            commodity_text=commodity_text,
            tonnage=tonnage_data.get("value"),
            loading_date=parsed.get("loading_date", {}).get("value"),
            freight_price=price_data.get("value"),
            contact=parsed.get("contact", {}).get("value"),
            remarks=parsed.get("remarks", ""),
            origin_node_id=origin_match["best_match"].entity_id if origin_match["best_match"] else None,
            origin_node_name=origin_match["best_match"].entity_name if origin_match["best_match"] else None,
            origin_confidence=origin_match["match_confidence"],
            dest_node_id=dest_match["best_match"].entity_id if dest_match["best_match"] else None,
            dest_node_name=dest_match["best_match"].entity_name if dest_match["best_match"] else None,
            dest_confidence=dest_match["match_confidence"],
            commodity_standard_id=commodity_match["best_match"].entity_id if commodity_match["best_match"] else None,
            commodity_standard_name=commodity_match["best_match"].entity_name if commodity_match["best_match"] else None,
            commodity_confidence=commodity_match["match_confidence"],
            origin_candidates=origin_match["candidates"],
            dest_candidates=dest_match["candidates"],
            commodity_candidates=commodity_match["candidates"],
            overall_confidence=overall_confidence,
            template_id=template_id,
            template_version=template_version,
            call_result=call_result,
        )

        logger.info(
            "[CargoAgent] complete origin=%s→%s(%d) dest=%s→%s(%d) commodity=%s→%s(%d)",
            output.origin_text, output.origin_node_name, output.origin_confidence,
            output.destination_text, output.dest_node_name, output.dest_confidence,
            output.commodity_text, output.commodity_standard_name, output.commodity_confidence,
        )

        return AgentResult(success=True, output=output, steps=steps)

    async def _match_entity(self, text: Optional[str], entities: list[dict]) -> dict:
        """匹配单个实体，text为None时返回空结果"""
        if not text:
            return {"best_match": None, "candidates": [], "match_confidence": 0}

        result = await self._match_tool.execute(text=text, entities=entities)
        return result.data or {"best_match": None, "candidates": [], "match_confidence": 0}
