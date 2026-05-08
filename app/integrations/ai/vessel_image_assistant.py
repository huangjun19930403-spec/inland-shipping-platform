"""Standalone vessel certificate image recognition assistant."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.integrations.config_keys import (
    VESSEL_IMAGE_AI_API_KEY,
    VESSEL_IMAGE_AI_BASE_URL,
    VESSEL_IMAGE_AI_CONFIG_PROFILE,
    VESSEL_IMAGE_AI_MODEL,
    VESSEL_IMAGE_AI_PROVIDER,
    VESSEL_IMAGE_AI_TIMEOUT_SECONDS,
)

if TYPE_CHECKING:
    from app.modules.system.runtime_config import RuntimeConfigService


@dataclass(frozen=True)
class VesselCertificateImageAssistantResult:
    provider: str
    model: str
    candidate_payload: dict[str, Any]
    raw_text: str | None
    raw_response: dict[str, Any]
    confidence_score: int | None = None


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValidationError("图片识别助手未返回内容")
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if match is None:
            raise ValidationError("图片识别助手未返回 JSON 结构") from None
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValidationError("图片识别助手返回结构必须是 JSON 对象")
    return parsed


def _confidence(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 1:
        number *= 100
    return max(0, min(int(round(number)), 100))


class VesselCertificateImageAssistant:
    """Independent image-only assistant for vessel certificate OCR.

    This class intentionally does not import or reuse the freight AI parser.
    """

    def __init__(self, runtime_config: RuntimeConfigService) -> None:
        self.runtime_config = runtime_config

    async def _config_value(self, key: str, default: Any = None) -> str | None:
        value = await self.runtime_config.get_value(
            key,
            str(default) if default is not None else None,
            profile_code=VESSEL_IMAGE_AI_CONFIG_PROFILE,
        )
        return (value or "").strip() or None

    async def recognize(
        self,
        *,
        content: bytes,
        content_type: str,
        file_name: str | None = None,
    ) -> VesselCertificateImageAssistantResult:
        if not content:
            raise ValidationError("证件图片内容为空")
        if not (content_type or "").lower().startswith("image/"):
            raise ValidationError("图片识别助手仅支持图片附件，PDF 可归档预览但不能识别")

        provider = await self._config_value(VESSEL_IMAGE_AI_PROVIDER, settings.VESSEL_IMAGE_AI_PROVIDER)
        base_url = await self._config_value(VESSEL_IMAGE_AI_BASE_URL, settings.VESSEL_IMAGE_AI_BASE_URL)
        api_key = await self._config_value(VESSEL_IMAGE_AI_API_KEY, settings.VESSEL_IMAGE_AI_API_KEY)
        model = await self._config_value(VESSEL_IMAGE_AI_MODEL, settings.VESSEL_IMAGE_AI_MODEL)
        timeout_raw = await self._config_value(
            VESSEL_IMAGE_AI_TIMEOUT_SECONDS,
            settings.VESSEL_IMAGE_AI_TIMEOUT_SECONDS,
        )

        if not api_key:
            raise ValidationError("未配置 VESSEL_IMAGE_AI_API_KEY，无法调用船舶证件图片识别助手")
        if not base_url or not model:
            raise ValidationError("船舶证件图片识别助手配置不完整")

        try:
            timeout_seconds = float(timeout_raw or settings.VESSEL_IMAGE_AI_TIMEOUT_SECONDS)
        except (TypeError, ValueError):
            timeout_seconds = settings.VESSEL_IMAGE_AI_TIMEOUT_SECONDS

        image_data = base64.b64encode(content).decode("ascii")
        data_url = f"data:{content_type};base64,{image_data}"
        prompt = (
            "你是船舶证件图片识别助手，只处理单张内河船舶证件图片。"
            "请从图片中提取候选字段，必须只返回 JSON 对象。字段包括："
            "certificate_type_code, certificate_type_text, certificate_no, ship_name, mmsi, "
            "ship_registry_no, issuing_authority, valid_from, valid_to, is_long_term_valid, "
            "validity_text_raw, deadweight_ton, total_tonnage, net_tonnage, length_m, width_m, "
            "depth_m, design_draft_m, confidence_score, raw_text, warnings。"
            "日期使用 YYYY-MM-DD；无法识别的字段返回 null；不要编造。"
        )
        payload = {
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "你只输出合法 JSON，不输出 Markdown。"},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"{prompt}\n文件名：{file_name or '-'}"},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
        }
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            raw_response = response.json()

        content_text = (
            raw_response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        candidate = _extract_json_object(str(content_text))
        raw_text = candidate.get("raw_text")
        return VesselCertificateImageAssistantResult(
            provider=provider or "DASHSCOPE_QWEN",
            model=model,
            candidate_payload=candidate,
            raw_text=str(raw_text) if raw_text not in (None, "") else None,
            raw_response=raw_response,
            confidence_score=_confidence(candidate.get("confidence_score")),
        )
