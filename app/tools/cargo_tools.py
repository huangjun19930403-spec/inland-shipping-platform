"""
货源解析工具
职责：调用LLM从原始文本中提取结构化货运字段
"""
import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import BaseTool, ToolResult
from app.ai.llm_registry import json_completion
from app.ai.prompt_manager import get_template, PromptTemplate
from app.ai.providers.base import LLMCallResult
from app.core.exceptions import AIServiceError

logger = logging.getLogger(__name__)


class CargoParseTextTool(BaseTool):
    """
    货运文本解析工具

    输入：原始货运文本（微信群消息等）
    输出：结构化字段 + 每字段置信度 + LLM调用元数据
    """

    name = "cargo_parse_text"
    description = "从原始货运文本中提取结构化字段"

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def execute(self, raw_text: str, **kwargs: Any) -> ToolResult:
        """
        Args:
            raw_text: 待解析的原始文本

        Returns:
            ToolResult.data = {
                "fields": {
                    "origin": {"value": str|None, "confidence": int},
                    "destination": {"value": str|None, "confidence": int},
                    "commodity": {"value": str|None, "confidence": int},
                    "tonnage": {"value": float|None, "unit": str, "confidence": int},
                    "loading_date": {"value": str|None, "confidence": int},
                    "freight_price": {"value": float|None, "unit": str, "confidence": int},
                    "contact": {"value": str|None, "confidence": int},
                    "remarks": str
                },
                "template_id": int,
                "template_version": int,
                "call_result": LLMCallResult,
            }
        """
        if not raw_text or not raw_text.strip():
            return ToolResult(success=False, error="Empty input text")

        try:
            template: PromptTemplate = await get_template("cargo_parse", self._db)
        except KeyError as e:
            logger.error("[CargoParseTextTool] prompt template not found: %s", e)
            return ToolResult(success=False, error=str(e))

        user_message = template.format_user(raw_text=raw_text.strip())

        try:
            parsed, call_result = await json_completion(
                system_prompt=template.system_prompt,
                user_message=user_message,
            )
            logger.info(
                "[CargoParseTextTool] parsed successfully origin=%s provider=%s model=%s",
                parsed.get("origin", {}).get("value"),
                call_result.provider,
                call_result.model,
            )
            return ToolResult(
                success=True,
                data={
                    "fields": parsed,
                    "template_id": template.id,
                    "template_version": template.version,
                    "call_result": call_result,
                },
            )
        except AIServiceError as e:
            logger.warning("[CargoParseTextTool] AI service error: %s", e)
            return ToolResult(
                success=False,
                error=str(e),
                data={
                    "fields": _empty_parse_result(),
                    "template_id": template.id,
                    "template_version": template.version,
                    "call_result": None,
                },
            )
        except Exception as e:
            # Provider 未配置/运行时异常统一走降级返回，避免链路中断
            logger.error("[CargoParseTextTool] Unexpected error: %s", e)
            return ToolResult(
                success=False,
                error=str(e),
                data={
                    "fields": _empty_parse_result(),
                    "template_id": template.id,
                    "template_version": template.version,
                    "call_result": None,
                },
            )


def _empty_parse_result() -> dict:
    """返回空解析结果（AI服务不可用时的降级方案）"""
    empty_field = {"value": None, "confidence": 0}
    return {
        "origin": empty_field,
        "destination": empty_field,
        "commodity": empty_field,
        "tonnage": {**empty_field, "unit": "吨"},
        "loading_date": empty_field,
        "freight_price": {**empty_field, "unit": "元/吨"},
        "contact": empty_field,
        "remarks": "",
    }
