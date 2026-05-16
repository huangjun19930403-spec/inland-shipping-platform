"""Optional AI assistant for standard commodity recognition."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import ValidationError as PydanticValidationError

from app.core.config import settings
from app.integrations.config_keys import (
    AI_PROVIDER,
    COMMODITY_RECOGNITION_AI_MODEL,
    DASHSCOPE_API_KEY,
    DASHSCOPE_BASE_URL,
    DASHSCOPE_CONFIG_PROFILE,
    DASHSCOPE_TIMEOUT_SECONDS,
)
from app.modules.commodity.recognition.context_builder import CommodityRecognitionContext
from app.modules.commodity.recognition.schemas import CommodityRecognitionStandardSuggestion
from app.modules.system.runtime_config import RuntimeConfigService


@dataclass(frozen=True)
class CommodityRecognitionAIResult:
    status_code: str
    suggestion: CommodityRecognitionStandardSuggestion | None = None
    raw_payload: dict[str, Any] | None = None
    error_message: str | None = None
    provider: str | None = None
    model: str | None = None


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if match is None:
            raise ValueError("AI 未返回 JSON 对象") from None
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("AI 返回结构必须是 JSON 对象")
    return parsed


class CommodityRecognitionAIAssistant:
    """Independent assistant for commodity suggestions.

    It only reads runtime configuration and never imports freight, vessel, or
    analysis AI flows.
    """

    def __init__(self, runtime_config: RuntimeConfigService) -> None:
        self.runtime_config = runtime_config

    async def suggest(
        self,
        *,
        raw_name: str,
        normalized_name: str,
        context_note: str | None,
        context: CommodityRecognitionContext,
        deterministic_candidates: list[dict[str, Any]],
        category_hint_id: int | None,
        type_hint_id: int | None,
    ) -> CommodityRecognitionAIResult:
        provider = await self._config_value(AI_PROVIDER, settings.AI_PROVIDER)
        if provider != "DASHSCOPE_QWEN":
            return CommodityRecognitionAIResult(status_code="SKIPPED", error_message="AI 提供方不是 DASHSCOPE_QWEN")

        api_key = await self._config_value(DASHSCOPE_API_KEY, settings.DASHSCOPE_API_KEY)
        if not api_key:
            return CommodityRecognitionAIResult(status_code="SKIPPED", error_message="未配置 DASHSCOPE_API_KEY")

        base_url = await self._config_value(DASHSCOPE_BASE_URL, settings.DASHSCOPE_BASE_URL)
        model = await self._config_value(COMMODITY_RECOGNITION_AI_MODEL, settings.COMMODITY_RECOGNITION_AI_MODEL)
        timeout_text = await self._config_value(DASHSCOPE_TIMEOUT_SECONDS, str(settings.DASHSCOPE_TIMEOUT_SECONDS))
        if not base_url or not model:
            return CommodityRecognitionAIResult(status_code="SKIPPED", error_message="标准货品识别 AI 配置不完整")
        try:
            timeout_seconds = float(timeout_text or settings.DASHSCOPE_TIMEOUT_SECONDS)
        except (TypeError, ValueError):
            timeout_seconds = settings.DASHSCOPE_TIMEOUT_SECONDS

        prompt = self._build_prompt(
            raw_name=raw_name,
            normalized_name=normalized_name,
            context_note=context_note,
            context=context,
            deterministic_candidates=deterministic_candidates,
            category_hint_id=category_hint_id,
            type_hint_id=type_hint_id,
        )
        payload = {
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "你是标准货品主数据识别助手。只输出合法 JSON，不输出 Markdown。"},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=payload,
                )
                response.raise_for_status()
                raw_response = response.json()
            content = raw_response.get("choices", [{}])[0].get("message", {}).get("content", "")
            parsed = _extract_json_object(str(content))
            suggestion_payload = parsed.get("standard_suggestion") if isinstance(parsed.get("standard_suggestion"), dict) else parsed
            suggestion = CommodityRecognitionStandardSuggestion.model_validate(suggestion_payload)
            return CommodityRecognitionAIResult(
                status_code="SUCCEEDED",
                suggestion=suggestion,
                raw_payload={"response": raw_response, "parsed": parsed},
                provider=provider,
                model=model,
            )
        except (httpx.HTTPError, ValueError, PydanticValidationError) as exc:
            return CommodityRecognitionAIResult(status_code="FAILED", error_message=str(exc)[:512], provider=provider, model=model)

    async def _config_value(self, key: str, default: Any = None) -> str | None:
        value = await self.runtime_config.get_value(
            key,
            str(default) if default is not None else None,
            profile_code=DASHSCOPE_CONFIG_PROFILE,
        )
        return (value or "").strip() or None

    @staticmethod
    def _build_prompt(
        *,
        raw_name: str,
        normalized_name: str,
        context_note: str | None,
        context: CommodityRecognitionContext,
        deterministic_candidates: list[dict[str, Any]],
        category_hint_id: int | None,
        type_hint_id: int | None,
    ) -> str:
        data = {
            "raw_name": raw_name,
            "normalized_name": normalized_name,
            "context_note": context_note,
            "category_hint_id": category_hint_id,
            "type_hint_id": type_hint_id,
            "deterministic_candidates": deterministic_candidates[:8],
            "master_data_context": context.compact_for_ai(
                category_hint_id=category_hint_id,
                type_hint_id=type_hint_id,
            ),
            "output_schema": {
                "standard_suggestion": {
                    "name": "建议标准货品名",
                    "category_id": "必须来自 master_data_context.categories，无法判断则 null",
                    "type_id": "必须来自 master_data_context.types，无法判断则 null",
                    "main_unit_code": "必须来自 COMMODITY_UNIT，默认 TON",
                    "cargo_form_code": "可来自 COMMODITY_CARGO_FORM",
                    "aliases": ["建议纳入的别名"],
                    "attributes": [
                        {
                            "attribute_definition_id": "来自 attribute_definitions",
                            "attribute_value": "建议值",
                            "confidence_score": 0,
                            "reason": "理由",
                        }
                    ],
                    "confidence_score": 0,
                    "reasons": ["判断依据"],
                    "warnings": ["不确定项"],
                }
            },
        }
        return (
            "请判断用户输入是否更适合纳入已有标准货品别名，或建议新建标准货品。"
            "已有候选优先，不要为包装词（如吨袋、吨包）新建标准货品。"
            "所有分类、类型、字典项、属性定义只能从 master_data_context 中选择。"
            "只输出 JSON 对象。\n"
            f"{json.dumps(data, ensure_ascii=False)}"
        )
