"""通义千问货源解析客户端。

The public class name is kept for compatibility with the freight service and tests,
but the implementation is now a small AI parsing pipeline:

1. Pre-analyze group-chat text and expose context hints to the model.
2. Prefer LangChain's OpenAI-compatible chat client for structured JSON output.
3. Fall back to the existing httpx call path when LangChain is unavailable.
4. Post-process segments with deterministic availability and contact inheritance rules.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import BaseModel, Field

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


class FreightSegmentSchema(BaseModel):
    raw_text: str = Field(description="原文片段，必须可在原文中追溯")
    context_summary: str | None = Field(default=None, description="继承的上下文，如公共联系人、现金结算、装卸说明")
    cargo_title: str | None = None
    cargo_description: str | None = None
    commodity_name: str | None = None
    origin_text: str | None = None
    destination_text: str | None = None
    estimated_tonnage: float | None = None
    min_tonnage: float | None = None
    max_tonnage: float | None = None
    unit_price: float | None = None
    total_price: float | None = None
    price_unit: str | None = None
    settlement_method_code: str | None = None
    loading_time_from: str | None = None
    loading_time_to: str | None = None
    expired_at: str | None = None
    publisher_org_name: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_wechat: str | None = None
    availability_status_code: str = Field(default="UNKNOWN", description="READY/DEFERRED/FULL/UNKNOWN")
    manual_review_reason: str | None = None
    confidence_score: float = 0.5
    evidence: list[str] = Field(default_factory=list)


class FreightParsePayloadSchema(BaseModel):
    segments: list[FreightSegmentSchema]
    warnings: list[str] = Field(default_factory=list)


class FreightWechatPreprocessor:
    route_pattern = re.compile(r"(.{1,24}?)(?:—|--+|-{2,}|到|发)(.{1,30})")
    phone_pattern = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
    ignored_line_pattern = re.compile(r"^@?所有人$|^@.+$")
    shared_note_keywords = ("装卸快", "现金", "下雨", "正常装卸", "随到随装", "随船装", "滚动发")

    @classmethod
    def normalize_text(cls, raw_content: str) -> str:
        text = (raw_content or "").replace("\r\n", "\n").replace("\r", "\n")
        text = text.replace("——", "—").replace("－", "-").replace("–", "-")
        lines = []
        for line in text.splitlines():
            cleaned = re.sub(r"\s+", " ", line).strip()
            if not cleaned or cls.ignored_line_pattern.match(cleaned):
                continue
            lines.append(cleaned)
        return "\n".join(lines)

    @classmethod
    def analyze(cls, raw_content: str) -> dict[str, Any]:
        normalized = cls.normalize_text(raw_content)
        lines = normalized.splitlines()
        phones = [{"phone": match.group(1), "offset": match.start()} for match in cls.phone_pattern.finditer(normalized)]
        route_lines = [line for line in lines if cls.route_pattern.search(line)]
        shared_notes = [line for line in lines if any(keyword in line for keyword in cls.shared_note_keywords) and not cls.route_pattern.search(line)]
        phone_lines = [line for line in lines if cls.phone_pattern.search(line) and not cls.route_pattern.search(line)]
        return {
            "normalized_text": normalized,
            "line_count": len(lines),
            "route_like_count": len(route_lines),
            "phones": phones,
            "phone_lines": phone_lines[-5:],
            "shared_notes": shared_notes[-8:],
            "route_examples": route_lines[:12],
        }


def _json_schema_hint() -> dict[str, Any]:
    return {
        "segments": [
            {
                "raw_text": "必须是可追溯的原文片段",
                "context_summary": "继承的公共上下文说明",
                "cargo_title": "建德 至 平湖 塘渣",
                "cargo_description": "装卸快，现金结算",
                "commodity_name": "塘渣",
                "origin_text": "建德",
                "destination_text": "平湖",
                "estimated_tonnage": None,
                "min_tonnage": None,
                "max_tonnage": None,
                "unit_price": 18,
                "total_price": None,
                "price_unit": "元/吨",
                "settlement_method_code": "CASH",
                "contact_name": "蒋姐",
                "contact_phone": "15381664761",
                "availability_status_code": "READY",
                "manual_review_reason": None,
                "confidence_score": 0.86,
                "evidence": ["原文路线", "公共备注", "联系电话"],
            }
        ],
        "warnings": ["无法确定吨位的线索需人工补充"],
    }


def _availability_from_text(text: str, suggested: str | None = None) -> tuple[str, str | None, list[str]]:
    value = (suggested or "").strip().upper()
    warnings: list[str] = []
    if re.search(r"船.*够|船已经够|暂时不要|已够", text):
        return "FULL", "原文显示船已够或暂不需要，不能一键确认发布", ["船已够"]
    if re.search(r"过几天|改天|晚点|以后要|后面要", text):
        return "DEFERRED", "原文显示稍后才需要，需确认具体发货时间", ["稍后再发"]
    if re.search(r"随船装|滚动发", text):
        warnings.append("滚动/随船装需要业务确认具体装期")
        return "UNKNOWN", "滚动或随船装缺少明确装期，需人工判断", warnings
    if value in {"READY", "DEFERRED", "FULL", "UNKNOWN"}:
        return value, None if value == "READY" else "AI 建议非立即可发，需人工确认", warnings
    return "UNKNOWN", "AI 未明确判断可发状态，需人工确认", warnings


def _nearest_phone(raw_content: str, segment_text: str) -> str | None:
    phones = list(FreightWechatPreprocessor.phone_pattern.finditer(raw_content))
    if not phones:
        return None
    if len(phones) == 1:
        return phones[0].group(1)
    segment_index = raw_content.find(segment_text[:20]) if segment_text else -1
    if segment_index < 0:
        return phones[-1].group(1)
    nearest = min(phones, key=lambda item: abs(item.start() - segment_index))
    return nearest.group(1)


class DashScopeQwenFreightParserClient:
    """OpenAI-compatible DashScope freight parser."""

    wechat_prompt_version = "freight_wechat_clue_split_v3"
    tms_prompt_version = "freight_tms_waybill_split_v3"
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
        value = await self.runtime_config.get_value(key, default, profile_code=DASHSCOPE_CONFIG_PROFILE)
        return (value or "").strip()

    async def _timeout(self) -> float:
        value = await self.runtime_config.get_float(
            DASHSCOPE_TIMEOUT_SECONDS,
            settings.DASHSCOPE_TIMEOUT_SECONDS,
            profile_code=DASHSCOPE_CONFIG_PROFILE,
        )
        return max(15.0, min(float(value), 180.0))

    @staticmethod
    def _json_from_content(content: str) -> dict[str, Any]:
        text = (content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
            text = re.sub(r"```$", "", text).strip()
        text = text.strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.S)
            if not match:
                raise ValidationError("通义千问返回内容不是合法 JSON", detail={"content": content[:1000]})
            try:
                payload = json.loads(match.group(0))
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
        segments = [item for item in raw_segments if isinstance(item, dict)]
        if not segments:
            raise ValidationError("通义千问未抽取到候选货源")
        return segments

    @staticmethod
    def _messages(raw_content: str, *, source_type_code: str) -> list[dict[str, str]]:
        schema_hint = _json_schema_hint()
        if source_type_code == "TMS":
            system_hint = (
                "你是内河航运 TMS 运单转货源助手。只输出 JSON。"
                "输入可能是一条消息内包含多条标准化运单、数组或嵌套字段。"
                "每条可发布运单切分为一个 segments 元素；未知字段必须是 null，不要编造。"
            )
            user_hint = "请把 TMS 运单消息转成待确认货源候选："
            context_hint: dict[str, Any] = {}
        else:
            context_hint = FreightWechatPreprocessor.analyze(raw_content)
            system_hint = (
                "你是内河航运微信群货源线索切分助手。只输出 JSON。"
                "微信群文本常见难点：一段话多条货源、多行共用联系人、多条路线共用货品或备注、"
                "电话在前后文、路线符号混用、无分隔符路线、emoji 和 @所有人。"
                "你必须先按业务线索切分，再抽取装货地、卸货地、货品、吨位、价格、联系人和结算/装卸备注。"
                "公共上下文可以继承，但必须写入 context_summary 和 evidence；不能凭空补充不存在的信息。"
                "船已够、暂时不要、过几天要应标为 FULL 或 DEFERRED；滚动发、随船装缺明确装期时标为 UNKNOWN。"
                "无效聊天、纯 @、纯电话行不得单独成为货源，但可作为上下文。"
            )
            user_hint = "请按 JSON 结构切分并抽取微信群货源候选："
        return [
            {"role": "system", "content": system_hint},
            {
                "role": "user",
                "content": (
                    f"{user_hint}\n"
                    f"JSON 输出结构：{json.dumps(schema_hint, ensure_ascii=False)}\n\n"
                    f"预处理上下文：{json.dumps(context_hint, ensure_ascii=False)}\n\n"
                    "待解析原文：\n"
                    f"{raw_content}"
                ),
            },
        ]

    async def _call_with_langchain(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        messages: list[dict[str, str]],
        timeout: float,
    ) -> dict[str, Any]:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError("LANGCHAIN_NOT_INSTALLED") from exc

        chat = ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=0.1,
            timeout=timeout,
            max_retries=2,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        lc_messages = [
            SystemMessage(content=messages[0]["content"]),
            HumanMessage(content=messages[1]["content"]),
        ]
        response = await chat.ainvoke(lc_messages)
        payload = self._json_from_content(str(response.content or ""))
        return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}], "langchain": True}

    async def _call_with_httpx(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        messages: list[dict[str, str]],
        timeout: float,
    ) -> dict[str, Any]:
        client = await self._client()
        last_error: Exception | None = None
        for attempt in range(1, 3):
            try:
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": 0.1,
                        "response_format": {"type": "json_object"},
                    },
                    timeout=timeout,
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response is not None else "unknown"
                body = exc.response.text[:300] if exc.response is not None else ""
                raise ValidationError(f"通义千问解析请求失败: HTTP {status_code} {body}") from exc
            except (httpx.TimeoutException, httpx.TransportError, ValueError) as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.8 * attempt)
                    continue
        raise InternalError(f"通义千问解析请求异常: {last_error}") from last_error

    @staticmethod
    def _postprocess_segments(raw_content: str, segments: list[dict[str, Any]], *, source_type_code: str) -> list[dict[str, Any]]:
        processed: list[dict[str, Any]] = []
        for segment in segments:
            item = dict(segment)
            raw_text = str(item.get("raw_text") or "").strip()
            if source_type_code == "WECHAT":
                phone = item.get("contact_phone") or _nearest_phone(raw_content, raw_text)
                if phone:
                    item["contact_phone"] = str(phone)
                availability, reason, warnings = _availability_from_text(
                    " ".join([raw_text, str(item.get("context_summary") or ""), str(item.get("cargo_description") or "")]),
                    str(item.get("availability_status_code") or ""),
                )
                item["availability_status_code"] = availability
                item["manual_review_reason"] = item.get("manual_review_reason") or reason
                if warnings:
                    item["ai_warning_json"] = {"warnings": warnings}
                if item.get("settlement_method_code") is None and "现金" in f"{raw_text} {item.get('context_summary') or ''} {item.get('cargo_description') or ''}":
                    item["settlement_method_code"] = "CASH"
            else:
                item["availability_status_code"] = item.get("availability_status_code") or "READY"
            processed.append(item)
        return processed

    async def parse(self, raw_content: str, *, source_type_code: str = "WECHAT") -> QwenFreightParseResult:
        content = FreightWechatPreprocessor.normalize_text(raw_content) if (source_type_code or "").upper() == "WECHAT" else (raw_content or "").strip()
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

        messages = self._messages(content, source_type_code=normalized_source)
        timeout = await self._timeout()
        try:
            raw_response = await self._call_with_langchain(base_url=base_url, model=model, api_key=api_key, messages=messages, timeout=timeout)
        except RuntimeError as exc:
            if str(exc) != "LANGCHAIN_NOT_INSTALLED":
                raise InternalError(f"LangChain 解析请求异常: {exc}") from exc
            raw_response = await self._call_with_httpx(base_url=base_url, model=model, api_key=api_key, messages=messages, timeout=timeout)
        except Exception as exc:
            raise InternalError(f"LangChain 解析请求异常: {exc}") from exc

        choices = raw_response.get("choices") or []
        if not choices:
            raise ValidationError("通义千问响应缺少 choices")
        message = (choices[0] or {}).get("message") or {}
        content_text = message.get("content") or ""
        parsed_payload = self._json_from_content(content_text)
        try:
            validated = FreightParsePayloadSchema.model_validate(parsed_payload)
            parsed_payload = validated.model_dump(exclude_none=True)
        except Exception as exc:
            raise ValidationError("通义千问返回结构不符合货源解析 schema", detail={"error": str(exc), "payload": parsed_payload}) from exc
        segments = self._segments_from_payload(parsed_payload)
        segments = self._postprocess_segments(content, segments, source_type_code=normalized_source)
        parsed_payload["segments"] = segments
        return QwenFreightParseResult(
            provider=provider or "DASHSCOPE_QWEN",
            model=model,
            prompt_version=prompt_version,
            raw_response=raw_response,
            parsed_payload=parsed_payload,
            segments=segments,
        )
