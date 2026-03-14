"""
实体模糊匹配工具
职责：将AI提取的文本与数据库中的节点/商品实体进行模糊匹配
这是原 ai_engine/parser.py 中模糊匹配逻辑的独立化重构
"""
import logging
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Optional

from app.ai.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 60  # 最低置信度阈值


@dataclass
class MatchCandidate:
    """匹配候选项"""
    entity_id: int
    entity_name: str
    match_score: int  # 0-100
    matched_via: str  # "exact" | "alias" | "fuzzy"


class EntityMatchTool(BaseTool):
    """
    实体匹配工具

    将文本描述匹配到系统中的标准实体（节点/商品）。
    支持精确匹配、别名匹配、模糊匹配三级降级策略。

    Tool不直接访问数据库，数据由调用方（Agent/Workflow）注入。
    """

    name = "entity_match"
    description = "将文本与数据库实体进行模糊匹配，返回最佳候选列表"

    async def execute(
        self,
        text: str,
        entities: list[dict],  # [{"id": int, "name": str, "aliases": list[str]}]
        top_k: int = 3,
        threshold: int = CONFIDENCE_THRESHOLD,
        **kwargs: Any,
    ) -> ToolResult:
        """
        Args:
            text: 待匹配的文本
            entities: 候选实体列表（由调用方从数据库预加载并注入）
            top_k: 返回最佳候选数量
            threshold: 最低匹配置信度

        Returns:
            ToolResult.data = {
                "best_match": MatchCandidate | None,
                "candidates": list[MatchCandidate],
                "match_confidence": int
            }
        """
        if not text:
            return ToolResult(
                success=True,
                data={"best_match": None, "candidates": [], "match_confidence": 0},
            )

        candidates = []

        for entity in entities:
            score, method = self._score_entity(text, entity)
            if score >= threshold:
                candidates.append(
                    MatchCandidate(
                        entity_id=entity["id"],
                        entity_name=entity["name"],
                        match_score=score,
                        matched_via=method,
                    )
                )

        candidates.sort(key=lambda c: c.match_score, reverse=True)
        top_candidates = candidates[:top_k]

        best = top_candidates[0] if top_candidates else None

        return ToolResult(
            success=True,
            data={
                "best_match": best,
                "candidates": top_candidates,
                "match_confidence": best.match_score if best else 0,
            },
        )

    def _score_entity(
        self, text: str, entity: dict
    ) -> tuple[int, str]:
        """
        对单个实体进行评分

        策略：精确匹配(100) > 别名精确匹配(95) > 模糊匹配
        """
        text_clean = text.strip().lower()
        name = entity.get("name", "").lower()
        aliases = [a.lower() for a in entity.get("aliases", [])]

        # 精确匹配
        if text_clean == name:
            return 100, "exact"

        # 别名精确匹配
        if text_clean in aliases:
            return 95, "alias_exact"

        # 包含匹配
        if text_clean in name or name in text_clean:
            return 85, "contains"

        for alias in aliases:
            if text_clean in alias or alias in text_clean:
                return 80, "alias_contains"

        # 模糊匹配（Levenshtein相似度）
        name_score = self._fuzzy_score(text_clean, name)
        best_score = name_score
        best_method = "fuzzy"

        for alias in aliases:
            alias_score = self._fuzzy_score(text_clean, alias)
            if alias_score > best_score:
                best_score = alias_score
                best_method = "alias_fuzzy"

        return best_score, best_method

    @staticmethod
    def _fuzzy_score(a: str, b: str) -> int:
        """计算两个字符串的相似度 (0-100)"""
        if not a or not b:
            return 0
        ratio = SequenceMatcher(None, a, b).ratio()
        return int(ratio * 100)
