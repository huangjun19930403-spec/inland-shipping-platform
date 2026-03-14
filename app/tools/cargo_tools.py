"""
货源解析工具
职责：调用LLM从原始文本中提取结构化货运字段
"""
import logging
from typing import Any

from app.ai.base import BaseTool, ToolResult
from app.ai.llm_client import json_completion
from app.ai.prompt_templates import get_template
from app.core.exceptions import AIServiceError

logger = logging.getLogger(__name__)


class CargoParseTextTool(BaseTool):
    """
    货运文本解析工具

    输入：原始货运文本（微信群消息等）
    输出：结构化字段 + 每字段置信度
    """

    name = "cargo_parse_text"
    description = "从原始货运文本中提取结构化字段"

    async def execute(self, raw_text: str, **kwargs: Any) -> ToolResult:
        """
        Args:
            raw_text: 待解析的原始文本

        Returns:
            ToolResult.data = {
                "origin": {"value": str|None, "confidence": int},
                "destination": {"value": str|None, "confidence": int},
                "commodity": {"value": str|None, "confidence": int},
                "tonnage": {"value": float|None, "unit": str, "confidence": int},
                "loading_date": {"value": str|None, "confidence": int},
                "freight_price": {"value": float|None, "unit": str, "confidence": int},
                "contact": {"value": str|None, "confidence": int},
                "remarks": str
            }
        """
        if not raw_text or not raw_text.strip():
            return ToolResult(
                success=False,
                error="Empty input text",
            )

        template = get_template("cargo_parse")
        user_message = template.format_user(raw_text=raw_text.strip())

        try:
            result = await json_completion(
                system_prompt=template.system,
                user_message=user_message,
                max_tokens=1024,
            )
            logger.info(
                f"[CargoParseTextTool] parsed successfully "
                f"origin={result.get('origin', {}).get('value')}"
            )
            return ToolResult(success=True, data=result)

        except AIServiceError as e:
            logger.warning(f"[CargoParseTextTool] AI service error: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                data=_empty_parse_result(),
            )
        except Exception as e:
            logger.error(f"[CargoParseTextTool] Unexpected error: {e}")
            return ToolResult(success=False, error=str(e))


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
