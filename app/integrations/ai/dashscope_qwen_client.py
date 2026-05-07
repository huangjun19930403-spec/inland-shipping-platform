"""通义千问货源解析客户端。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from app.core.config import settings
from app.core.exceptions import InternalError, ValidationError
from app.integrations.config_keys import (
    AI_PROVIDER,
    DASHSCOPE_API_KEY,
    DASHSCOPE_BASE_URL,
    DASHSCOPE_CONFIG_PROFILE,
    DASHSCOPE_MODEL,
    DASHSCOPE_TIMEOUT_SECONDS,
)
from app.integrations.http import get_shared_http_client

if TYPE_CHECKING:
    from app.modules.system.runtime_config import RuntimeConfigService


@dataclass(frozen=True)
class QwenFreightParseResult:
    provider: str
    model: str
    prompt_version: str
    raw_response: dict[str, Any]
    parsed_payload: dict[str, Any]
    segments: list[dict[str, Any]]


class DashScopeQwenFreightParserClient:
    """OpenAI-compatible DashScope Chat Completions wrapper."""

    wechat_prompt_version = "freight_wechat_clue_split_v2"
    tms_prompt_version = "freight_tms_waybill_split_v2"
    prompt_version = wechat_prompt_version

    def __init__(
        self,
        *,
        runtime_config: RuntimeConfigService,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.runtime_config = runtime_config
        self._transport = transport

    async def _client(self) -> httpx.AsyncClient:
        return await get_shared_http_client("dashscope-qwen", transport=self._transport)

    async def _config_value(self, key: str, default: str = "") -> str:
        value = await self.runtime_config.get_value(
            key,
            default,
            profile_code=DASHSCOPE_CONFIG_PROFILE,
        )
        return (value or "").strip()

    async def _timeout(self) -> float:
        value = await self.runtime_config.get_float(
            DASHSCOPE_TIMEOUT_SECONDS,
            settings.DASHSCOPE_TIMEOUT_SECONDS,
            profile_code=DASHSCOPE_CONFIG_PROFILE,
        )
        return max(5.0, min(float(value), 180.0))

    @staticmethod
    def _json_from_content(content: str) -> dict[str, Any]:
        text = (content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
            text = re.sub(r"```$", "", text).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValidationError("通义千问返回内容不是合法 JSON", detail={"content": content[:1000]}) from exc
        if not isinstance(payload, dict):
            raise ValidationError("通义千问返回 JSON 根节点必须是对象")
        return payload

    @staticmethod
    def _segments_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_segments = payload.get("segments") or payload.get("candidates") or []
        if not isinstance(raw_segments, list):
            raise ValidationError("通义千问返回 JSON 中 segments 必须是数组")
        segments: list[dict[str, Any]] = []
        for item in raw_segments:
            if isinstance(item, dict):
                segments.append(item)
        if not segments:
            raise ValidationError("通义千问未抽取到候选货源")
        return segments

    @staticmethod
    def _messages(raw_content: str, *, source_type_code: str) -> list[dict[str, str]]:
        schema_hint = {
            "segments": [
                {
                    "raw_text": "原文片段",
                    "context_summary": "线索上下文摘要",
                    "cargo_title": "货源标题",
                    "cargo_description": "补充描述",
                    "commodity_name": "货品名称",
                    "origin_text": "起运地文本",
                    "destination_text": "目的地文本",
                    "estimated_tonnage": 3000,
                    "min_tonnage": 2500,
                    "max_tonnage": 3500,
                    "unit_price": 35,
                    "total_price": None,
                    "price_unit": "元/吨",
                    "loading_time_from": None,
                    "loading_time_to": None,
                    "expired_at": None,
                    "publisher_org_name": "发布方",
                    "contact_name": "联系人",
                    "contact_phone": "手机号",
                    "contact_wechat": "微信号",
                    "confidence_score": 0.86,
                    "evidence": ["依据1", "依据2"],
                }
            ]
        }
        if source_type_code == "TMS":
            system_hint = (
                "你是内河航运 TMS 运单转货源助手。只输出 JSON，不要输出 Markdown。"
                "输入可能是一条消息中包含多条标准化运单、数组或嵌套字段。"
                "请把每条可发布为货源的运单切分为一个 segments 元素，保留运单号、装卸地、货品、吨位、价格等字段。"
                "未知字段使用 null，数字字段只输出数字。"
            )
            user_hint = "请按以下 JSON 结构把 TMS 运单消息转成待确认货源候选："
        else:
            system_hint = (
                "你是内河航运微信群货源线索切分助手。只输出 JSON，不要输出 Markdown。"
                "微信群文本可能包含多段话、多条货源、上下文省略、联系人复用、前后句关联和无效聊天内容。"
                "请先按业务语义切分货源线索，再抽取每条线索中的装货地、卸货地、货品、吨位、价格和联系方式。"
                "不要把闲聊、无效回复或重复转发当作货源；未知字段使用 null，数字字段只输出数字。"
            )
            user_hint = "请按以下 JSON 结构切分并抽取微信群货源候选："
        return [
            {"role": "system", "content": system_hint},
            {
                "role": "user",
                "content": (
                    f"{user_hint}\n"
                    f"{json.dumps(schema_hint, ensure_ascii=False)}\n\n"
                    "待解析原文：\n"
                    f"{raw_content}"
                ),
            },
        ]

    async def parse(self, raw_content: str, *, source_type_code: str = "WECHAT") -> QwenFreightParseResult:
        content = (raw_content or "").strip()
        if not content:
            raise ValidationError("AI 解析原文不能为空")
        normalized_source = (source_type_code or "WECHAT").strip().upper()
        prompt_version = self.tms_prompt_version if normalized_source == "TMS" else self.wechat_prompt_version

        provider = await self._config_value(AI_PROVIDER, settings.AI_PROVIDER)
        base_url = (await self._config_value(DASHSCOPE_BASE_URL, settings.DASHSCOPE_BASE_URL)).rstrip("/")
        model = await self._config_value(DASHSCOPE_MODEL, settings.DASHSCOPE_MODEL)
        api_key = await self._config_value(DASHSCOPE_API_KEY, settings.DASHSCOPE_API_KEY)
        if not api_key:
            raise ValidationError("未配置 DASHSCOPE_API_KEY，无法调用通义千问解析")
        if not base_url:
            raise ValidationError("未配置 DASHSCOPE_BASE_URL，无法调用通义千问解析")
        if not model:
            raise ValidationError("未配置 DASHSCOPE_MODEL，无法调用通义千问解析")

        client = await self._client()
        try:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": self._messages(content, source_type_code=normalized_source),
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                },
                timeout=await self._timeout(),
            )
            response.raise_for_status()
            raw_response = response.json()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else "unknown"
            body = exc.response.text[:300] if exc.response is not None else ""
            raise ValidationError(f"通义千问解析请求失败: HTTP {status_code} {body}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise InternalError(f"通义千问解析请求异常: {exc}") from exc

        choices = raw_response.get("choices") or []
        if not choices:
            raise ValidationError("通义千问响应缺少 choices")
        message = (choices[0] or {}).get("message") or {}
        content_text = message.get("content") or ""
        parsed_payload = self._json_from_content(content_text)
        segments = self._segments_from_payload(parsed_payload)
        return QwenFreightParseResult(
            provider=provider or "DASHSCOPE_QWEN",
            model=model,
            prompt_version=prompt_version,
            raw_response=raw_response,
            parsed_payload=parsed_payload,
            segments=segments,
        )
