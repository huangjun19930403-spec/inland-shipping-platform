"""DashScope SDK freight parsing client.

The parser deliberately does not split WeChat source text with local rules.
WeChat clue splitting and semantic extraction are AI responsibilities; local
code only validates JSON, runs standard master-data matching later, and records
parse progress.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from threading import Thread
from typing import TYPE_CHECKING, Any, Awaitable, Callable

import httpx
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.exceptions import InternalError, ValidationError
from app.integrations.config_keys import (
    AI_PROVIDER,
    DASHSCOPE_API_KEY,
    DASHSCOPE_CONFIG_PROFILE,
    DASHSCOPE_FAST_MODEL,
    DASHSCOPE_MODEL,
    DASHSCOPE_STREAM_TIMEOUT_SECONDS,
    DASHSCOPE_STRONG_REVIEW_ENABLED,
)

if TYPE_CHECKING:
    from app.modules.system.runtime_config import RuntimeConfigService

ProgressCallback = Callable[[str, str, str, int], Awaitable[None]]


@dataclass(frozen=True)
class QwenFreightParseResult:
    provider: str
    model: str
    prompt_version: str
    raw_response: dict[str, Any]
    parsed_payload: dict[str, Any]
    segments: list[dict[str, Any]]
    review_failed_count: int = 0


class FreightClueSplitItemSchema(BaseModel):
    segment_index: int | None = None
    raw_text: str = Field(description="AI 切分出的可追溯原文片段")
    context_summary: str | None = Field(default=None, description="AI 判断需要继承的公共上下文")
    confidence_score: float = 0.5
    evidence: list[str] = Field(default_factory=list)
    needs_strong_review: bool = False


class FreightClueSplitPayloadSchema(BaseModel):
    clues: list[FreightClueSplitItemSchema]
    warnings: list[str] = Field(default_factory=list)


class FreightSegmentSchema(BaseModel):
    segment_index: int | None = None
    raw_text: str = Field(description="原文片段，必须可在原文中追溯")
    context_summary: str | None = Field(default=None, description="AI 判断的上下文继承说明")
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
    needs_strong_review: bool = False


class FreightParsePayloadSchema(BaseModel):
    segments: list[FreightSegmentSchema]
    warnings: list[str] = Field(default_factory=list)


def _json_schema_hint() -> dict[str, Any]:
    return {
        "segments": [
            {
                "segment_index": 1,
                "raw_text": "必须是 AI 从原文中切分出的完整货源片段",
                "context_summary": "AI 判断继承的公共上下文，例如联系人、结算、装卸备注",
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
                "needs_strong_review": False,
            }
        ],
        "warnings": ["无法确定吨位的线索需人工补充"],
    }


def _clue_schema_hint() -> dict[str, Any]:
    return {
        "clues": [
            {
                "segment_index": 1,
                "raw_text": "AI 从原文中切分出的单条货源片段",
                "context_summary": "AI 判断该片段继承的公共上下文",
                "confidence_score": 0.86,
                "evidence": ["路线原文", "联系人原文"],
                "needs_strong_review": False,
            }
        ],
        "warnings": ["不确定是否为货源的内容不要输出为 clue"],
    }


def _normalize_json_text(content: str) -> str:
    text = (content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def _response_to_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _nested_get(data: Any, *keys: str) -> Any:
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            current = getattr(current, key, None)
        if current is None:
            return None
    return current


def _chunk_content(chunk: Any) -> str:
    data = _response_to_mapping(chunk)
    choices = _nested_get(data, "output", "choices") or _nested_get(chunk, "output", "choices") or []
    if choices:
        first = choices[0]
        content = _nested_get(first, "message", "content")
        if content:
            return str(content)
    text = _nested_get(data, "output", "text") or _nested_get(chunk, "output", "text")
    return str(text or "")


def _chunk_error(chunk: Any) -> str | None:
    data = _response_to_mapping(chunk)
    status_code = data.get("status_code") or getattr(chunk, "status_code", None)
    if status_code in (None, 200, "200", "OK"):
        return None
    code = data.get("code") or getattr(chunk, "code", None) or status_code
    message = data.get("message") or getattr(chunk, "message", None) or "DashScope SDK 调用失败"
    return f"{code}: {message}"


def _segment_needs_strong_review(segment: dict[str, Any]) -> bool:
    if bool(segment.get("needs_strong_review")):
        return True
    try:
        confidence = float(segment.get("confidence_score") or 0)
    except (TypeError, ValueError):
        confidence = 0
    required_missing = not segment.get("raw_text") or not segment.get("origin_text") or not segment.get("destination_text") or not segment.get("commodity_name")
    return confidence < 0.65 or required_missing or str(segment.get("availability_status_code") or "").upper() == "UNKNOWN"


class DashScopeQwenFreightParserClient:
    """DashScope SDK freight parser."""

    wechat_prompt_version = "freight_wechat_dashscope_stream_v4"
    tms_prompt_version = "freight_tms_dashscope_stream_v4"
    prompt_version = wechat_prompt_version

    def __init__(
        self,
        *,
        runtime_config: RuntimeConfigService,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.runtime_config = runtime_config
        self._transport = transport

    async def _config_value(self, key: str, default: str = "") -> str:
        value = await self.runtime_config.get_value(key, default, profile_code=DASHSCOPE_CONFIG_PROFILE)
        return (value or "").strip()

    async def _config_bool(self, key: str, default: bool = False) -> bool:
        return await self.runtime_config.get_bool(key, default, profile_code=DASHSCOPE_CONFIG_PROFILE)

    async def _stream_timeout(self) -> float:
        value = await self.runtime_config.get_float(
            DASHSCOPE_STREAM_TIMEOUT_SECONDS,
            settings.DASHSCOPE_STREAM_TIMEOUT_SECONDS,
            profile_code=DASHSCOPE_CONFIG_PROFILE,
        )
        return max(15.0, min(float(value), 240.0))

    @staticmethod
    def _json_from_content(content: str) -> dict[str, Any]:
        text = _normalize_json_text(content)
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
        segments = [item for item in raw_segments if isinstance(item, dict)]
        if not segments:
            raise ValidationError("通义千问未抽取到候选货源")
        for index, item in enumerate(segments, start=1):
            item["segment_index"] = int(item.get("segment_index") or index)
            item["availability_status_code"] = str(item.get("availability_status_code") or "UNKNOWN").upper()
        return segments

    @staticmethod
    def _clues_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_clues = payload.get("clues") or []
        if not isinstance(raw_clues, list):
            raise ValidationError("通义千问返回 JSON 中 clues 必须是数组")
        clues = [item for item in raw_clues if isinstance(item, dict)]
        if not clues:
            raise ValidationError("通义千问未切分出货源线索")
        for index, item in enumerate(clues, start=1):
            item["segment_index"] = int(item.get("segment_index") or index)
        return clues

    @staticmethod
    def _split_messages(raw_content: str) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "你是内河航运微信群货源线索切分助手。只输出 JSON。"
                    "必须由你阅读完整原文并切分货源线索；不要依赖用户或系统预切分。"
                    "一条 clue 必须是一条业务上可追溯的货源线索。"
                    "公共联系人、公共备注、上下文继承必须由你判断，并写入 context_summary 和 evidence。"
                    "无法确定是货源的聊天内容不要输出为 clue。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请读取完整微信群原文，完成货源线索切分。"
                    f"JSON 输出结构：{json.dumps(_clue_schema_hint(), ensure_ascii=False)}\n\n"
                    "微信群原文：\n"
                    f"{raw_content}"
                ),
            },
        ]

    @staticmethod
    def _extract_messages(raw_content: str, clues: list[dict[str, Any]], *, source_type_code: str) -> list[dict[str, str]]:
        if source_type_code == "TMS":
            system_hint = (
                "你是内河航运 TMS 运单转货源助手。只输出 JSON。"
                "输入可能是一条消息内包含多条标准化运单、数组或嵌套字段。"
                "每条可发布运单输出为一个 segments 元素；未知字段必须是 null，不要编造。"
            )
            user_hint = "请把 TMS 运单消息转成待确认货源候选："
            source_payload = raw_content
        else:
            system_hint = (
                "你是内河航运微信群货源结构化抽取助手。只输出 JSON。"
                "输入 clues 已由 AI 从同一段原文中切分得到。"
                "不得新增 clues 之外的货源；每个 clue 输出一个 segment。"
                "装货地、卸货地、货品、吨位、价格、联系人、结算、装卸备注和可发状态都只能依据原文与 clue 上下文判断。"
                "船已够、暂时不要、过几天要应标为 FULL 或 DEFERRED；滚动发、随船装缺明确装期时标为 UNKNOWN。"
            )
            user_hint = "请对 AI 线索切分结果做字段抽取："
            source_payload = json.dumps({"source_text": raw_content, "clues": clues}, ensure_ascii=False)
        return [
            {"role": "system", "content": system_hint},
            {
                "role": "user",
                "content": (
                    f"{user_hint}\n"
                    f"JSON 输出结构：{json.dumps(_json_schema_hint(), ensure_ascii=False)}\n\n"
                    f"{source_payload}"
                ),
            },
        ]

    @staticmethod
    def _review_messages(segments: list[dict[str, Any]]) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "你是内河航运微信群货源复核助手。只输出 JSON。"
                    "请复核输入 segments 的字段完整性、可发状态和上下文继承。"
                    "不得新增货源，只能修正输入 segment 的字段；无法确定的字段保持 null 并给出 manual_review_reason。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请复核这些低置信度候选：\n"
                    f"JSON 输出结构：{json.dumps(_json_schema_hint(), ensure_ascii=False)}\n\n"
                    f"{json.dumps({'segments': segments}, ensure_ascii=False)}"
                ),
            },
        ]

    async def _call_dashscope_stream(
        self,
        *,
        model: str,
        api_key: str,
        messages: list[dict[str, str]],
        timeout: float,
        progress_callback: ProgressCallback | None,
        stage_code: str,
        stage_name: str,
        stage_message: str,
        progress_percent: int,
    ) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        def worker() -> None:
            try:
                import dashscope
                from dashscope import Generation

                dashscope.api_key = api_key
                responses = Generation.call(
                    model=model,
                    messages=messages,
                    result_format="message",
                    stream=True,
                    incremental_output=True,
                    temperature=0.1,
                    response_format={"type": "json_object"},
                )
                for chunk in responses:
                    error = _chunk_error(chunk)
                    if error:
                        raise RuntimeError(error)
                    content = _chunk_content(chunk)
                    if content:
                        loop.call_soon_threadsafe(queue.put_nowait, ("delta", content))
                loop.call_soon_threadsafe(queue.put_nowait, ("done", None))
            except BaseException as exc:  # noqa: BLE001
                loop.call_soon_threadsafe(queue.put_nowait, ("error", exc))

        Thread(target=worker, daemon=True).start()
        parts: list[str] = []
        last_heartbeat = 0.0
        while True:
            try:
                kind, payload = await asyncio.wait_for(queue.get(), timeout=timeout)
            except TimeoutError as exc:
                raise InternalError(f"DashScope SDK 流式解析超时，阶段：{stage_name}") from exc
            if kind == "error":
                raise InternalError(f"DashScope SDK 解析请求异常: {payload}") from payload
            if kind == "done":
                break
            parts.append(str(payload))
            now = time.monotonic()
            if progress_callback is not None and now - last_heartbeat >= 3:
                last_heartbeat = now
                await progress_callback(stage_code, stage_name, stage_message, progress_percent)
        content = "".join(parts).strip()
        if progress_callback is not None:
            await progress_callback(stage_code, stage_name, stage_message, progress_percent)
        return {
            "choices": [{"message": {"content": content}}],
            "dashscope_sdk": True,
            "streamed": True,
            "model": model,
        }

    async def _call_json(
        self,
        *,
        model: str,
        api_key: str,
        messages: list[dict[str, str]],
        timeout: float,
        progress_callback: ProgressCallback | None,
        stage_code: str,
        stage_name: str,
        stage_message: str,
        progress_percent: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        raw_response = await self._call_dashscope_stream(
            model=model,
            api_key=api_key,
            messages=messages,
            timeout=timeout,
            progress_callback=progress_callback,
            stage_code=stage_code,
            stage_name=stage_name,
            stage_message=stage_message,
            progress_percent=progress_percent,
        )
        content = ((raw_response.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        return self._json_from_content(content), raw_response

    async def parse(
        self,
        raw_content: str,
        *,
        source_type_code: str = "WECHAT",
        progress_callback: ProgressCallback | None = None,
    ) -> QwenFreightParseResult:
        content = (raw_content or "").strip()
        if not content:
            raise ValidationError("AI 解析原文不能为空")
        normalized_source = (source_type_code or "WECHAT").strip().upper()
        prompt_version = self.tms_prompt_version if normalized_source == "TMS" else self.wechat_prompt_version

        provider = await self._config_value(AI_PROVIDER, settings.AI_PROVIDER)
        strong_model = await self._config_value(DASHSCOPE_MODEL, settings.DASHSCOPE_MODEL)
        fast_model = await self._config_value(DASHSCOPE_FAST_MODEL, settings.DASHSCOPE_FAST_MODEL)
        api_key = await self._config_value(DASHSCOPE_API_KEY, settings.DASHSCOPE_API_KEY)
        if not api_key:
            raise ValidationError("未配置 DASHSCOPE_API_KEY，无法调用通义千问解析")
        if not strong_model:
            raise ValidationError("未配置 DASHSCOPE_MODEL，无法调用通义千问解析")
        if not fast_model:
            fast_model = strong_model

        timeout = await self._stream_timeout()
        raw_response: dict[str, Any] = {"provider": provider, "pipeline": "dashscope_sdk_stream"}
        review_failed_count = 0
        used_models = [fast_model]

        if normalized_source == "WECHAT":
            split_payload, split_raw = await self._call_json(
                model=fast_model,
                api_key=api_key,
                messages=self._split_messages(content),
                timeout=timeout,
                progress_callback=progress_callback,
                stage_code="AI_SPLIT",
                stage_name="AI 切分线索",
                stage_message="快模型正在阅读完整微信群原文并切分货源线索",
                progress_percent=30,
            )
            try:
                split_validated = FreightClueSplitPayloadSchema.model_validate(split_payload)
                clues = [item.model_dump(exclude_none=True) for item in split_validated.clues]
            except Exception as exc:
                raise ValidationError("通义千问线索切分结构不符合 schema", detail={"error": str(exc), "payload": split_payload}) from exc
            raw_response["split"] = split_raw
            extract_messages = self._extract_messages(content, clues, source_type_code=normalized_source)
            extract_progress = 62
        else:
            clues = []
            extract_messages = self._extract_messages(content, clues, source_type_code=normalized_source)
            extract_progress = 55

        parsed_payload, extract_raw = await self._call_json(
            model=fast_model if normalized_source == "WECHAT" else strong_model,
            api_key=api_key,
            messages=extract_messages,
            timeout=timeout,
            progress_callback=progress_callback,
            stage_code="AI_EXTRACT",
            stage_name="AI 抽取字段",
            stage_message="AI 正在抽取装卸地、货品、价格、联系人和可发状态",
            progress_percent=extract_progress,
        )
        raw_response["extract"] = extract_raw
        try:
            validated = FreightParsePayloadSchema.model_validate(parsed_payload)
            parsed_payload = validated.model_dump(exclude_none=True)
        except Exception as exc:
            raise ValidationError("通义千问返回结构不符合货源解析 schema", detail={"error": str(exc), "payload": parsed_payload}) from exc
        segments = self._segments_from_payload(parsed_payload)

        review_enabled = normalized_source == "WECHAT" and await self._config_bool(DASHSCOPE_STRONG_REVIEW_ENABLED, settings.DASHSCOPE_STRONG_REVIEW_ENABLED)
        review_targets = [item for item in segments if _segment_needs_strong_review(item)]
        if review_enabled and review_targets:
            try:
                used_models.append(strong_model)
                review_payload, review_raw = await self._call_json(
                    model=strong_model,
                    api_key=api_key,
                    messages=self._review_messages(review_targets),
                    timeout=timeout,
                    progress_callback=progress_callback,
                    stage_code="AI_REVIEW",
                    stage_name="强模型复核",
                    stage_message="强模型正在复核低置信度或字段缺失的候选",
                    progress_percent=76,
                )
                review_validated = FreightParsePayloadSchema.model_validate(review_payload)
                reviewed = self._segments_from_payload(review_validated.model_dump(exclude_none=True))
                reviewed_by_index = {int(item.get("segment_index") or index): item for index, item in enumerate(reviewed, start=1)}
                segments = [
                    {**item, **reviewed_by_index.get(int(item.get("segment_index") or index), {})}
                    for index, item in enumerate(segments, start=1)
                ]
                raw_response["review"] = review_raw
            except Exception as exc:  # noqa: BLE001
                review_failed_count = len(review_targets)
                for item in review_targets:
                    item["availability_status_code"] = "UNKNOWN"
                    item["manual_review_reason"] = f"强模型复核失败，需人工判断：{exc}"
                    item["needs_strong_review"] = True
                raw_response["review_error"] = str(exc)

        parsed_payload["segments"] = segments
        parsed_payload["warnings"] = parsed_payload.get("warnings") or []
        return QwenFreightParseResult(
            provider=provider or "DASHSCOPE_QWEN",
            model=" -> ".join(dict.fromkeys(used_models)),
            prompt_version=prompt_version,
            raw_response=raw_response,
            parsed_payload=parsed_payload,
            segments=segments,
            review_failed_count=review_failed_count,
        )
