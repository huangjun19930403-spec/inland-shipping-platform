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
from dataclasses import dataclass, field
from threading import Thread
from typing import TYPE_CHECKING, Any, Awaitable, Callable

import httpx
from pydantic import BaseModel, Field, field_validator, model_validator

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
    ignored_segments: list[dict[str, Any]] = field(default_factory=list)
    review_failed_count: int = 0


class FreightClueSplitItemSchema(BaseModel):
    segment_index: int | None = None
    context_block_id: str | int | None = None
    semantic_role_code: str | None = Field(default="ROUTE", description="ROUTE/CONTEXT/IGNORED")
    line_refs: list[str | int] = Field(default_factory=list, description="原文行号或行标识")
    raw_text: str = Field(description="AI 切分出的可追溯原文片段")
    origin_text: str | None = Field(default=None, description="路线中出现的装货地原文，未知填 null")
    destination_text: str | None = Field(default=None, description="路线中出现的卸货地原文，未知填 null")
    commodity_name: str | None = Field(default=None, description="线索中出现的货品原文，未知填 null")
    origin_match_level_code: str | None = Field(default=None, description="AI 对装货地粒度的判断：NODE/CITY/RAW")
    destination_match_level_code: str | None = Field(default=None, description="AI 对卸货地粒度的判断：NODE/CITY/RAW")
    missing_field_codes: list[str] = Field(default_factory=list, description="缺失字段：COMMODITY/ORIGIN/DESTINATION")
    context_summary: str | None = Field(default=None, description="AI 判断需要继承的公共上下文")
    inherited_context: dict[str, Any] | None = Field(default=None, description="从 context_notes 继承的联系人、价格、备注等上下文")
    is_freight_candidate: bool = True
    drop_reason: str | None = None
    confidence_score: float = 0.5
    evidence: list[str] = Field(default_factory=list)
    needs_strong_review: bool = False

    @field_validator("origin_match_level_code", "destination_match_level_code", mode="before")
    @classmethod
    def _normalize_match_level(cls, value: Any) -> str | None:
        if value in (None, ""):
            return None
        code = str(value).strip().upper()
        return code if code in {"NODE", "CITY", "RAW"} else None

    @field_validator("missing_field_codes", mode="before")
    @classmethod
    def _default_missing_codes(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value

    @field_validator("line_refs", mode="before")
    @classmethod
    def _default_line_refs(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, (str, int)):
            return [value]
        return value

    @field_validator("confidence_score", mode="before")
    @classmethod
    def _default_confidence(cls, value: Any) -> Any:
        return 0.5 if value in (None, "") else value

    @field_validator("evidence", mode="before")
    @classmethod
    def _default_evidence(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value

    @field_validator("needs_strong_review", mode="before")
    @classmethod
    def _default_review_flag(cls, value: Any) -> bool:
        return bool(value) if value is not None else False

    @field_validator("is_freight_candidate", mode="before")
    @classmethod
    def _default_candidate_flag(cls, value: Any) -> bool:
        return bool(value) if value is not None else True


class FreightContextNoteSchema(BaseModel):
    note_index: int | None = None
    raw_text: str
    context_type_code: str = Field(default="OTHER", description="TONNAGE/PRICE/CONTACT/REMARK/SETTLEMENT/LOADING/OTHER")
    applies_to: list[int] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    confidence_score: float = 0.5

    @field_validator("context_type_code", mode="before")
    @classmethod
    def _normalize_context_type(cls, value: Any) -> str:
        code = str(value or "OTHER").strip().upper()
        return code if code in {"TONNAGE", "PRICE", "CONTACT", "REMARK", "SETTLEMENT", "LOADING", "OTHER"} else "OTHER"

    @field_validator("applies_to", "evidence", mode="before")
    @classmethod
    def _default_list(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value

    @field_validator("confidence_score", mode="before")
    @classmethod
    def _default_confidence(cls, value: Any) -> Any:
        return 0.5 if value in (None, "") else value


class FreightContextBlockSchema(BaseModel):
    context_block_id: str | int
    route_clue_ids: list[int] = Field(default_factory=list)
    raw_text: str | None = None
    context_summary: str | None = None
    shared_contact_name: str | None = None
    shared_contact_phone: str | None = None
    shared_contact_wechat: str | None = None
    shared_tonnage_text: str | None = None
    shared_price_text: str | None = None
    shared_unit_price: float | None = None
    shared_total_price: float | None = None
    shared_price_unit: str | None = None
    shared_settlement_method_code: str | None = None
    shared_loading_remark: str | None = None
    shared_remark: str | None = None
    evidence: list[str] = Field(default_factory=list)
    scope_reason: str | None = None
    confidence_score: float = 0.5

    @field_validator("route_clue_ids", "evidence", mode="before")
    @classmethod
    def _default_list(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value

    @field_validator("confidence_score", mode="before")
    @classmethod
    def _default_confidence(cls, value: Any) -> Any:
        return 0.5 if value in (None, "") else value

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_scope_keys(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        copied = dict(value)
        if "route_clue_ids" not in copied:
            copied["route_clue_ids"] = copied.get("applies_to") or copied.get("clue_ids") or copied.get("segment_indices") or []
        if "context_block_id" not in copied:
            copied["context_block_id"] = copied.get("block_id") or copied.get("id") or 1
        return copied


class FreightClueSplitPayloadSchema(BaseModel):
    freight_clues: list[FreightClueSplitItemSchema] = Field(default_factory=list)
    context_blocks: list[FreightContextBlockSchema] = Field(default_factory=list)
    context_notes: list[FreightContextNoteSchema] = Field(default_factory=list)
    ignored_notes: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_clues(cls, value: Any) -> Any:
        if isinstance(value, dict) and "freight_clues" not in value and "clues" in value:
            copied = dict(value)
            copied["freight_clues"] = copied.get("clues")
            return copied
        if isinstance(value, dict) and "freight_clues" not in value and "route_clues" in value:
            copied = dict(value)
            copied["freight_clues"] = copied.get("route_clues")
            return copied
        return value

    @model_validator(mode="after")
    def _require_freight_clues(self) -> "FreightClueSplitPayloadSchema":
        if not self.freight_clues:
            raise ValueError("freight_clues 不能为空")
        return self


class FreightSegmentSchema(BaseModel):
    segment_index: int | None = None
    context_block_id: str | int | None = None
    semantic_role_code: str | None = Field(default="ROUTE", description="ROUTE/CONTEXT/IGNORED")
    line_refs: list[str | int] = Field(default_factory=list, description="原文行号或行标识")
    raw_text: str = Field(description="原文片段，必须可在原文中追溯")
    context_summary: str | None = Field(default=None, description="AI 判断的上下文继承说明")
    inherited_context: dict[str, Any] | None = Field(default=None, description="从公共上下文继承到该货源的价格、联系人、备注等信息")
    is_freight_candidate: bool = True
    drop_reason: str | None = None
    cargo_title: str | None = None
    cargo_description: str | None = None
    commodity_name: str | None = None
    origin_text: str | None = None
    destination_text: str | None = None
    origin_match_level_code: str | None = None
    destination_match_level_code: str | None = None
    raw_tonnage_text: str | None = None
    estimated_tonnage: float | None = None
    min_tonnage: float | None = None
    max_tonnage: float | None = None
    quantity_description: str | None = Field(default=None, description="数量/船型/拖队等非吨位原文说明")
    vessel_description: str | None = Field(default=None, description="船型、拖队、米数等非吨位信息")
    tonnage_decision: dict[str, Any] | None = Field(default=None, description="AI 对本条吨位归属的裁决")
    tonnage_candidates: list[dict[str, Any]] = Field(default_factory=list, description="AI 在本条上下文中考虑过的吨位候选")
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
    ai_review_status_code: str | None = Field(default=None, description="PASS/REVIEW_REQUIRED")
    ai_review_reason: str | None = None
    ai_review_json: dict[str, Any] | None = None
    confidence_score: float = 0.5
    evidence: list[str] = Field(default_factory=list)
    needs_strong_review: bool = False

    @field_validator("origin_match_level_code", "destination_match_level_code", mode="before")
    @classmethod
    def _normalize_match_level(cls, value: Any) -> str | None:
        if value in (None, ""):
            return None
        code = str(value or "").strip().upper()
        return code if code in {"NODE", "CITY", "RAW"} else None

    @field_validator("availability_status_code", mode="before")
    @classmethod
    def _normalize_availability(cls, value: Any) -> str:
        code = str(value or "UNKNOWN").strip().upper()
        return code if code in {"READY", "DEFERRED", "FULL", "UNKNOWN"} else "UNKNOWN"

    @field_validator("confidence_score", mode="before")
    @classmethod
    def _default_confidence(cls, value: Any) -> Any:
        return 0.5 if value in (None, "") else value

    @field_validator("evidence", mode="before")
    @classmethod
    def _default_evidence(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value

    @field_validator("line_refs", mode="before")
    @classmethod
    def _default_line_refs(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, (str, int)):
            return [value]
        return value

    @field_validator("tonnage_candidates", mode="before")
    @classmethod
    def _default_tonnage_candidates(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, dict):
            return [value]
        return value

    @field_validator("needs_strong_review", mode="before")
    @classmethod
    def _default_review_flag(cls, value: Any) -> bool:
        return bool(value) if value is not None else False

    @field_validator("is_freight_candidate", mode="before")
    @classmethod
    def _default_candidate_flag(cls, value: Any) -> bool:
        return bool(value) if value is not None else True


class FreightParsePayloadSchema(BaseModel):
    segments: list[FreightSegmentSchema]
    warnings: list[str] = Field(default_factory=list)


def _json_schema_hint() -> dict[str, Any]:
    return {
        "segments": [
            {
                "segment_index": 1,
                "context_block_id": "<继承上下文块 ID，未知填 null>",
                "semantic_role_code": "ROUTE",
                "line_refs": ["<原文行号或行标识>"],
                "raw_text": "<完整货源线索原文片段>",
                "context_summary": "<继承的公共上下文摘要，不能写未在原文或 context_notes 中出现的信息>",
                "inherited_context": {
                    "price": "<继承的价格原文或 null>",
                    "tonnage": "<仅当 AI 已裁决该吨位明确归属本条线索时填写，否则 null>",
                    "contact": "<继承的联系人原文或 null>",
                    "remark": "<继承的装卸/结算/天气备注原文或 null>",
                    "evidence": ["<上下文证据片段>"],
                },
                "is_freight_candidate": True,
                "drop_reason": None,
                "cargo_title": "<装货地 至 卸货地 货品>",
                "cargo_description": "<装卸、结算、备注等原文信息>",
                "commodity_name": "<货品原文；若由上下文强推断，填推断货品并在 ai_review_json 标明>",
                "origin_text": "<装货地原文>",
                "destination_text": "<卸货地原文>",
                "origin_match_level_code": "<AI 判断装货地是 NODE/CITY/RAW，未知填 null>",
                "destination_match_level_code": "<AI 判断卸货地是 NODE/CITY/RAW，未知填 null>",
                "raw_tonnage_text": "<吨位原文，例如 2000左右 或 1500-2000内>",
                "estimated_tonnage": None,
                "min_tonnage": None,
                "max_tonnage": None,
                "quantity_description": "<50米船、拖队一条等数量/船型描述；不是吨位时写这里>",
                "vessel_description": "<船型、拖队、米数等非吨位信息>",
                "tonnage_decision": {
                    "status_code": "PASS",
                    "selected_text": "<本条货源自己的吨位原文或 null>",
                    "reason": "<为什么这个吨位属于本条货源；不输出思考过程，只输出结论证据>",
                },
                "tonnage_candidates": [
                    {"text": "<候选吨位原文>", "line_ref": "<来源行>", "belongs_to_current_segment": True}
                ],
                "unit_price": None,
                "total_price": None,
                "price_unit": "<价格单位原文或 null>",
                "settlement_method_code": "<CASH/MONTHLY/TRANSFER/OTHER 或 null>",
                "contact_name": "<联系人原文或 null>",
                "contact_phone": "<手机号原文或 null>",
                "availability_status_code": "READY",
                "manual_review_reason": None,
                "ai_review_status_code": "PASS",
                "ai_review_reason": None,
                "ai_review_json": {"summary": "<业务复核结论>"},
                "confidence_score": 0.86,
                "evidence": ["<路线证据>", "<货品证据>", "<继承上下文证据>"],
                "needs_strong_review": False,
            }
        ],
        "warnings": ["无法确定吨位的线索需人工补充"],
    }


def _clue_schema_hint() -> dict[str, Any]:
    return {
        "route_clues": [
            {
                "segment_index": 1,
                "context_block_id": "<该线索所属上下文块 ID，未知填 null>",
                "semantic_role_code": "ROUTE",
                "line_refs": ["<原文行号或行标识>"],
                "raw_text": "<包含装货地和卸货地的单条路线线索；缺货品也要保留；多目的地拆分时可重复同一原文>",
                "origin_text": "<装货地原文，未知填 null>",
                "destination_text": "<卸货地原文，未知填 null>",
                "commodity_name": "<货品原文；若由上下文强推断，填推断货品并在 missing_field_codes 写 INFERRED_COMMODITY>",
                "origin_match_level_code": "<NODE/CITY/RAW 或 null>",
                "destination_match_level_code": "<NODE/CITY/RAW 或 null>",
                "missing_field_codes": ["<缺货品时写 COMMODITY；上下文推断货品写 INFERRED_COMMODITY；缺起讫地写 ORIGIN/DESTINATION>"],
                "context_summary": "<该线索继承了哪些公共备注、价格、联系人>",
                "inherited_context": {
                    "price": "<继承的价格原文或 null>",
                    "tonnage": "<继承的吨位原文或 null>",
                    "contact": "<继承的联系人原文或 null>",
                    "remark": "<继承的装卸/结算/天气备注原文或 null>",
                    "evidence": ["<继承依据原文片段>"],
                },
                "is_freight_candidate": True,
                "drop_reason": None,
                "confidence_score": 0.86,
                "evidence": ["<路线原文>", "<货品原文>", "<上下文证据>"],
                "needs_strong_review": False,
            }
        ],
        "context_blocks": [
            {
                "context_block_id": "B1",
                "route_clue_ids": [1],
                "raw_text": "<该公共上下文块覆盖的连续原文片段>",
                "context_summary": "<联系人、电话、价格、吨位、装卸、结算等公共上下文摘要>",
                "shared_contact_name": "<公共联系人姓名或 null>",
                "shared_contact_phone": "<公共联系电话或 null>",
                "shared_contact_wechat": "<公共微信号或 null>",
                "shared_tonnage_text": "<公共吨位原文或 null>",
                "shared_price_text": "<公共价格原文或 null>",
                "shared_unit_price": None,
                "shared_total_price": None,
                "shared_price_unit": "<价格单位原文或 null>",
                "shared_settlement_method_code": "<CASH/MONTHLY/TRANSFER/OTHER 或 null>",
                "shared_loading_remark": "<公共装卸备注或 null>",
                "shared_remark": "<其它公共备注或 null>",
                "evidence": ["<上下文证据原文>"],
                "scope_reason": "<为什么这些上下文适用于 route_clue_ids>",
                "confidence_score": 0.86,
            }
        ],
        "context_notes": [
            {
                "note_index": 1,
                "raw_text": "<公告、联系人、吨位、价格、装卸、结算或天气等上下文原文>",
                "context_type_code": "TONNAGE",
                "applies_to": [1],
                "evidence": ["<该上下文可继承给哪些货源线索的判断依据>"],
                "confidence_score": 0.86,
            }
        ],
        "ignored_notes": [
            {
                "note_index": 1,
                "raw_text": "<公告标题、问候语或完全不能形成路线的片段>",
                "drop_reason": "<忽略原因>",
            }
        ],
        "warnings": ["有起讫地但缺货品的路线必须进入 route_clues，并写 missing_field_codes"],
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


def _segment_core_missing(segment: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not str(segment.get("origin_text") or "").strip():
        missing.append("装货地")
    if not str(segment.get("destination_text") or "").strip():
        missing.append("卸货地")
    if not str(segment.get("commodity_name") or "").strip():
        missing.append("货品")
    return missing


def _append_review_reason(segment: dict[str, Any], reason: str) -> None:
    current = str(segment.get("manual_review_reason") or "").strip()
    if current:
        if reason not in current:
            segment["manual_review_reason"] = f"{current}；{reason}"
    else:
        segment["manual_review_reason"] = reason


def _support_text(raw_content: str, segment: dict[str, Any]) -> str:
    pieces = [
        segment.get("raw_text"),
        segment.get("context_summary"),
        json.dumps(segment.get("evidence") or [], ensure_ascii=False),
        json.dumps(segment.get("inherited_context") or {}, ensure_ascii=False),
    ]
    return "\n".join(str(item) for item in pieces if item not in (None, ""))


def _value_supported(value: Any, support_text: str) -> bool:
    if value in (None, ""):
        return True
    text = str(value).strip()
    if not text:
        return True
    if text in support_text:
        return True
    try:
        number = float(text)
    except (TypeError, ValueError):
        return False
    if number.is_integer() and str(int(number)) in support_text:
        return True
    return text.rstrip("0").rstrip(".") in support_text


def _drop_unsupported_fields(segment: dict[str, Any], raw_content: str) -> list[str]:
    support = _support_text(raw_content, segment)
    labels = {
        "origin_text": "装货地",
        "destination_text": "卸货地",
        "commodity_name": "货品",
        "raw_tonnage_text": "吨位原文",
        "unit_price": "运价",
        "total_price": "总价",
        "contact_name": "联系人",
        "contact_phone": "联系电话",
        "contact_wechat": "微信号",
        "publisher_org_name": "发布单位",
    }
    warnings: list[str] = []
    for field_name, label in labels.items():
        value = segment.get(field_name)
        if value in (None, ""):
            continue
        if _value_supported(value, support):
            continue
        segment[field_name] = None
        warnings.append(f"{label}缺少原文证据，已清空")
        _append_review_reason(segment, f"{label}缺少原文证据")
        segment["needs_strong_review"] = True
    return warnings


def _normalize_segment_quality(segment: dict[str, Any], raw_content: str) -> tuple[dict[str, Any], list[str]]:
    normalized = dict(segment)
    warnings = _drop_unsupported_fields(normalized, raw_content)
    if normalized.get("is_freight_candidate") is None:
        normalized["is_freight_candidate"] = True
    explicit_drop = normalized.get("is_freight_candidate") is False or bool(normalized.get("drop_reason"))
    route_missing = [
        item
        for item in ("装货地", "卸货地")
        if item in _segment_core_missing(normalized)
    ]
    core_missing = _segment_core_missing(normalized)
    semantic_role = str(normalized.get("semantic_role_code") or "ROUTE").strip().upper()
    if route_missing and semantic_role != "ROUTE":
        reason = f"AI 输出不是可追溯路线线索，缺少{','.join(route_missing)}"
        normalized["availability_status_code"] = "UNKNOWN"
        normalized["is_freight_candidate"] = False
        normalized["drop_reason"] = normalized.get("drop_reason") or reason
        _append_review_reason(normalized, reason)
        warnings.append(reason)
    elif route_missing:
        reason = f"路线字段不完整，需人工判断：缺少{','.join(route_missing)}"
        normalized["availability_status_code"] = "UNKNOWN"
        normalized["needs_strong_review"] = True
        _append_review_reason(normalized, reason)
        warnings.append(reason)
    elif "货品" in core_missing:
        reason = "缺少货品，需业务人员补充后确认"
        normalized["availability_status_code"] = "UNKNOWN"
        normalized["needs_strong_review"] = True
        _append_review_reason(normalized, reason)
        warnings.append(reason)
    elif normalized.get("needs_strong_review") or normalized.get("manual_review_reason") or normalized.get("ai_review_reason"):
        normalized["availability_status_code"] = "UNKNOWN"
        normalized["needs_strong_review"] = True
        if normalized.get("ai_review_reason"):
            _append_review_reason(normalized, str(normalized.get("ai_review_reason")))
        warnings.append(str(normalized.get("manual_review_reason") or normalized.get("ai_review_reason") or "AI 复核需人工判断"))
    elif str(normalized.get("availability_status_code") or "").upper() == "READY":
        normalized["availability_status_code"] = "READY"
    if explicit_drop:
        normalized["is_freight_candidate"] = False
        normalized["drop_reason"] = normalized.get("drop_reason") or "AI 复核判断该片段不是完整货源线索"
        normalized["availability_status_code"] = "UNKNOWN"
    return normalized, warnings


def _segment_needs_strong_review(segment: dict[str, Any]) -> bool:
    if segment.get("is_freight_candidate") is False or segment.get("drop_reason"):
        return True
    if bool(segment.get("needs_strong_review")):
        return True
    if segment.get("manual_review_reason") or segment.get("ai_review_reason"):
        return True
    review_status = str(segment.get("ai_review_status_code") or segment.get("review_status_code") or "").upper()
    if review_status and review_status != "PASS":
        return True
    try:
        confidence = float(segment.get("confidence_score") or 0)
    except (TypeError, ValueError):
        confidence = 0
    required_missing = not segment.get("raw_text") or not segment.get("origin_text") or not segment.get("destination_text") or not segment.get("commodity_name")
    inherited = segment.get("inherited_context") if isinstance(segment.get("inherited_context"), dict) else {}
    has_tonnage_fields = bool(segment.get("raw_tonnage_text") or segment.get("estimated_tonnage") or segment.get("min_tonnage") or segment.get("max_tonnage"))
    price_without_price_field = bool(inherited.get("price")) and not segment.get("unit_price") and not segment.get("total_price") and not has_tonnage_fields
    inherited_tonnage_missing = bool(inherited.get("tonnage")) and not has_tonnage_fields
    return (
        confidence < 0.65
        or required_missing
        or price_without_price_field
        or inherited_tonnage_missing
        or str(segment.get("availability_status_code") or "").upper() == "UNKNOWN"
    )


def _prepare_segments(raw_content: str, segments: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    accepted: list[dict[str, Any]] = []
    ignored: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, segment in enumerate(segments, start=1):
        normalized, item_warnings = _normalize_segment_quality(segment, raw_content)
        normalized["segment_index"] = int(normalized.get("segment_index") or index)
        warnings.extend([f"segment {normalized['segment_index']}: {item}" for item in item_warnings])
        if normalized.get("is_freight_candidate") is False:
            ignored.append(normalized)
        else:
            accepted.append(normalized)
    return accepted, ignored, warnings


def _context_value(block: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = block.get(key)
        if value not in (None, ""):
            return value
    return None


def _append_text(value: str | None, addition: str | None) -> str | None:
    base = str(value or "").strip()
    extra = str(addition or "").strip()
    if not extra:
        return base or None
    if not base:
        return extra
    if extra in base:
        return base
    return f"{base}；{extra}"


def _apply_context_blocks_to_segments(
    segments: list[dict[str, Any]], context_blocks: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    if not context_blocks:
        return segments, []
    by_block_id = {str(block.get("context_block_id")): block for block in context_blocks if block.get("context_block_id") not in (None, "")}
    by_segment_index: dict[int, dict[str, Any]] = {}
    for block in context_blocks:
        for raw_index in block.get("route_clue_ids") or []:
            try:
                by_segment_index[int(raw_index)] = block
            except (TypeError, ValueError):
                continue
    warnings: list[str] = []
    patched: list[dict[str, Any]] = []
    for index, segment in enumerate(segments, start=1):
        item = dict(segment)
        block = None
        if item.get("context_block_id") not in (None, ""):
            block = by_block_id.get(str(item.get("context_block_id")))
        block = block or by_segment_index.get(int(item.get("segment_index") or index))
        if not block:
            patched.append(item)
            continue

        inherited = dict(item.get("inherited_context") or {})
        evidence = list(item.get("evidence") or [])
        block_evidence = [str(value) for value in (block.get("evidence") or []) if value]
        for value in block_evidence:
            if value not in evidence:
                evidence.append(value)
        summary = _context_value(block, "context_summary", "scope_reason")
        item["context_summary"] = _append_text(item.get("context_summary"), summary)
        if block.get("context_block_id") not in (None, ""):
            item["context_block_id"] = block.get("context_block_id")
            inherited["context_block_id"] = block.get("context_block_id")
        if block_evidence:
            inherited_evidence = inherited.get("evidence") or []
            if isinstance(inherited_evidence, str):
                inherited_evidence = [inherited_evidence]
            inherited["evidence"] = list(dict.fromkeys([*inherited_evidence, *block_evidence]))

        field_map = {
            "contact_name": ("shared_contact_name", "contact_name"),
            "contact_phone": ("shared_contact_phone", "contact_phone", "phone"),
            "contact_wechat": ("shared_contact_wechat", "contact_wechat"),
            "unit_price": ("shared_unit_price", "unit_price"),
            "total_price": ("shared_total_price", "total_price"),
            "price_unit": ("shared_price_unit", "price_unit"),
            "settlement_method_code": ("shared_settlement_method_code", "settlement_method_code"),
        }
        for field_name, keys in field_map.items():
            if item.get(field_name) in (None, ""):
                value = _context_value(block, *keys)
                if value not in (None, ""):
                    item[field_name] = value
                    warnings.append(f"segment {item.get('segment_index') or index}: 已按 AI 上下文块继承{field_name}")
        shared_tonnage = _context_value(block, "shared_tonnage_text", "tonnage", "raw_tonnage_text")
        if shared_tonnage and item.get("raw_tonnage_text") in (None, ""):
            warnings.append(
                f"segment {item.get('segment_index') or index}: AI 上下文块存在公共吨位，但未自动继承，需由 segment 吨位裁决明确归属"
            )
        remark = _append_text(_context_value(block, "shared_loading_remark"), _context_value(block, "shared_remark"))
        if remark:
            item["cargo_description"] = _append_text(item.get("cargo_description"), remark)
            inherited["remark"] = _append_text(inherited.get("remark"), remark)
        contact_bits = [item.get("contact_name"), item.get("contact_phone"), item.get("contact_wechat")]
        if any(contact_bits):
            inherited["contact"] = " ".join(str(value) for value in contact_bits if value)
        if item.get("raw_tonnage_text"):
            inherited["tonnage"] = item.get("raw_tonnage_text")
        price_text = _context_value(block, "shared_price_text")
        if price_text:
            inherited["price"] = price_text
        item["inherited_context"] = inherited
        item["evidence"] = evidence
        patched.append(item)
    return patched, warnings


class DashScopeQwenFreightParserClient:
    """DashScope SDK freight parser."""

    wechat_prompt_version = "freight_wechat_humanized_semantic_v10"
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
        raw_clues = payload.get("freight_clues") or payload.get("clues") or []
        if not isinstance(raw_clues, list):
            raise ValidationError("通义千问返回 JSON 中 freight_clues 必须是数组")
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
                    "输出必须分为 route_clues、context_blocks、context_notes 和 ignored_notes。"
                    "先建立语义地图：逐行判断哪些是线路、哪些是公共联系人/备注/吨位候选、哪些不是货源；每条 route_clue 写 line_refs。"
                    "route_clues 采用召回优先：只要有装货地和卸货地，就必须保留为路线线索；缺货品时优先根据同一连续公告块上下文判断，能强推断则填 commodity_name 并写 missing_field_codes=['INFERRED_COMMODITY']，不能强推断才填 null 和 COMMODITY。"
                    "同一行出现多个目的地时，必须拆成多条 route_clues：共同装货地、货品、联系人和备注保留，每个目的地单独一条；可重复同一 raw_text，但 destination_text 必须分别填写。"
                    "公告、天气、联系人、价格、结算、装卸备注等上下文行不能单独成为 route_clues，只能放入 context_notes。"
                    "公共联系人、吨位、价格、结算、装卸备注必须抽成 context_blocks；每个 block 写 route_clue_ids、证据和 scope_reason。"
                    "手机号或联系人紧跟某条路线下方时，必须归属该路线；若位于一组连续路线末尾，默认覆盖该连续公告块内所有未出现其它联系人的 route_clues；若不适用必须说明证据。"
                    "横线、省略号、空行通常只是分隔，不应自动切断手机号对紧邻上方路线的归属；若同一发布人的多组路线之间没有新联系人，末尾电话可覆盖上方连续块。"
                    "每条 route_clue 必须写 context_block_id，并在 inherited_context、context_summary 和 evidence 中说明继承内容。"
                    "一行或多行上下文可继承给多个 route_clues，但不能因此新增不存在的货源。"
                    "吨位只能作为候选上下文记录，不能因为同一公告块就默认继承给所有路线；只有语义上明确属于某条路线时，后续结构化阶段才写入该 segment。"
                    "请判断装卸地粒度：明确港口、码头、闸口、厂矿、装卸点等具体设施才是 NODE；只有城市名或城市简称时是 CITY；无法判断是 RAW。"
                    "微信群货源里靠近路线和货品的 1500-2000内、2000左右、7500左右、2-3500吨通常是吨位，不是价格；只有出现元、运费、价格、现金等价格语义时才按价格处理。"
                    "不得使用 JSON 结构说明中的占位值作为真实字段。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请读取完整微信群原文，完成货源线索切分。"
                    "如果一段内容只有联系人、价格、公告、天气、结算或装卸说明，没有装货地和卸货地，必须输出到 context_blocks/context_notes 或 ignored_notes，不能输出为 route_clues。"
                    "如果一段内容有装货地和卸货地但缺货品，也必须输出到 route_clues；能从同一连续公告块强推断货品时填推断值并标记 INFERRED_COMMODITY，后续进入人工判断。"
                    f"JSON 输出结构：{json.dumps(_clue_schema_hint(), ensure_ascii=False)}\n\n"
                    "微信群原文：\n"
                    f"{raw_content}"
                ),
            },
        ]

    @staticmethod
    def _extract_messages(
        raw_content: str,
        clues: list[dict[str, Any]],
        *,
        source_type_code: str,
        context_notes: list[dict[str, Any]] | None = None,
        context_blocks: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
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
                "输入 freight_clues 已由 AI 从同一段原文中切分得到，context_blocks 是公共上下文块，context_notes 是补充上下文。"
                "不得新增 freight_clues 之外的货源；普通 freight_clue 输出一个 segment，多目的地 freight_clue 可输出多个 segment，但每个 segment 必须保留同一 line_refs/raw_text 并分别填写 destination_text。"
                "context_blocks/context_notes 只能用于继承联系人、价格、结算、装卸备注，不能单独输出为 segment。"
                "每个 segment 必须保留对应 freight_clue 的 context_block_id；属于同一 context_block 的公共联系人和电话必须继承到所有 segment。"
                "装货地、卸货地、货品、吨位、价格、联系人、结算、装卸备注和可发状态都只能依据原文与 clue 上下文判断。"
                "有装货地和卸货地但缺货品的 clue 必须输出 segment；若上下文强相关，可填推断货品，但 ai_review_status_code 必须 REVIEW_REQUIRED，manual_review_reason 写明 AI 根据上下文推断货品，不能一键确认。"
                "如果目的地是多个地点，必须拆成多个 segments；不要把多个目的地塞进一个 destination_text。"
                "请保留 clue 中的 origin_match_level_code/destination_match_level_code；只有具体设施才标 NODE，只有城市名或城市简称标 CITY。"
                "吨位原文必须写 raw_tonnage_text；单点吨位填 estimated_tonnage；范围吨位填 min_tonnage 和 max_tonnage。"
                "运输吨位必须只归属当前 freight_clue：同一公告里出现多条线路和多个吨位范围时，每个 segment 只能选择自己这一行或明确绑定上下文里的吨位。"
                "如果你发现多个吨位候选无法判断归属，raw_tonnage_text 填 null，tonnage_candidates 写候选，ai_review_status_code 填 REVIEW_REQUIRED。"
                "50米船、拖队一条、船型、米数、条数不是吨位；写入 quantity_description/vessel_description 或 cargo_description，不得写入 raw_tonnage_text。"
                "1500-2000内 表示 min_tonnage=1500、max_tonnage=2000；2000左右 表示 estimated_tonnage=2000；2000--2500吨 表示 min_tonnage=2000、max_tonnage=2500。"
                "2-3500吨这类微信群简写通常表示 2000-3500吨，若你能从上下文确认就填 min_tonnage=2000、max_tonnage=3500；不能确认则只填 raw_tonnage_text 并写 manual_review_reason。"
                "每个 segment 必须给出 tonnage_decision，说明吨位是否 PASS；无法确认时写 ai_review_reason，不要为了凑字段拼接其它线路的吨位。"
                "寻船、要船、现货类公告没有吨位是常见情况；只要路线、货品、联系人和可发状态可信，不要仅因为无吨位标记 REVIEW_REQUIRED。"
                "非空字段必须能从原文、freight_clue、context_notes、evidence 或 inherited_context 中找到证据；没有证据必须填 null。"
                "如果某个 freight_clue 复核后不是完整货源线索，输出 is_freight_candidate=false 并写 drop_reason。"
                "船已够、暂时不要、过几天要应标为 FULL 或 DEFERRED；滚动发、随船装缺明确装期时标为 UNKNOWN。"
                "不得使用 JSON 结构说明中的占位值作为真实字段。"
            )
            user_hint = "请对 AI 线索切分结果做字段抽取："
            source_payload = json.dumps(
                {
                    "source_text": raw_content,
                    "freight_clues": clues,
                    "context_blocks": context_blocks or [],
                    "context_notes": context_notes or [],
                },
                ensure_ascii=False,
            )
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
    def _review_messages(
        raw_content: str,
        segments: list[dict[str, Any]],
        *,
        clues: list[dict[str, Any]] | None = None,
        context_blocks: list[dict[str, Any]] | None = None,
        context_notes: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "你是内河航运微信群货源复核助手。只输出 JSON。"
                    "请复核输入 segments 的字段完整性、吨位归类、可发状态、上下文继承和证据来源。"
                    "不得新增原文中不存在的货源；多目的地输入可拆成多个 segments，除此之外只能修正输入 segment 的字段、清空无证据字段，或把上下文-only/空线索标记为 is_freight_candidate=false。"
                    "必须核对 context_blocks 的 route_clue_ids：公共联系人、电话、装卸备注可继承到该 block 覆盖的所有 segment。"
                    "公共吨位不能自动继承；必须根据 route_clue 原文和上下文语义逐条裁决归属，不能把多个线路的吨位范围合并到一个 segment。"
                    "如果同一 context_block 内只有部分 segment 继承联系人，应补齐其它 segment；手机号紧跟路线或位于连续公告块末尾时，优先认为覆盖该块。证据不足则标记需人工判断，但不要丢弃路线。"
                    "缺货品但上下文能强推断时，填推断货品并标记 REVIEW_REQUIRED；不要让采集人员从空白货品开始补。"
                    "寻船、要船、现货类公告无吨位不应单独触发 REVIEW_REQUIRED。"
                    "如果 inherited_context.price 中实际是吨位表达，应移入 raw_tonnage_text 和 estimated_tonnage/min_tonnage/max_tonnage，并清空价格字段。"
                    "复核 2-3500吨 等简写时按微信群货源吨位语境处理，不能确认时保留 raw_tonnage_text 并要求人工判断。"
                    "发现字段来自 JSON 占位示例而非原文证据时必须清空，并写 manual_review_reason。"
                    "无法确定的字段保持 null 并给出 manual_review_reason。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请复核这些低置信度候选：\n"
                    f"JSON 输出结构：{json.dumps(_json_schema_hint(), ensure_ascii=False)}\n\n"
                    f"{json.dumps({'source_text': raw_content, 'freight_clues': clues or [], 'context_blocks': context_blocks or [], 'context_notes': context_notes or [], 'segments': segments}, ensure_ascii=False)}"
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
        context_notes: list[dict[str, Any]] = []
        context_blocks: list[dict[str, Any]] = []

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
                clues = [
                    item.model_dump(exclude_none=True)
                    for item in split_validated.freight_clues
                    if item.is_freight_candidate and not item.drop_reason
                ]
                context_blocks = [item.model_dump(exclude_none=True) for item in split_validated.context_blocks]
                context_notes = [item.model_dump(exclude_none=True) for item in split_validated.context_notes]
            except Exception as exc:
                raise ValidationError("通义千问线索切分结构不符合 schema", detail={"error": str(exc), "payload": split_payload}) from exc
            if not clues:
                raise ValidationError("通义千问未切分出完整货源线索", detail={"payload": split_payload})
            raw_response["split"] = split_raw
            raw_response["split_payload"] = split_validated.model_dump(exclude_none=True)
            extract_messages = self._extract_messages(
                content,
                clues,
                source_type_code=normalized_source,
                context_notes=context_notes,
                context_blocks=context_blocks,
            )
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
        if normalized_source == "WECHAT":
            segments, context_block_warnings = _apply_context_blocks_to_segments(segments, context_blocks)
            if context_block_warnings:
                parsed_payload.setdefault("warnings", [])
                parsed_payload["warnings"].extend(context_block_warnings)

        review_enabled = normalized_source == "WECHAT" and await self._config_bool(DASHSCOPE_STRONG_REVIEW_ENABLED, settings.DASHSCOPE_STRONG_REVIEW_ENABLED)
        review_targets = [item for item in segments if _segment_needs_strong_review(item)]
        if review_enabled and review_targets:
            try:
                used_models.append(strong_model)
                review_payload, review_raw = await self._call_json(
                    model=strong_model,
                    api_key=api_key,
                    messages=self._review_messages(
                        content,
                        review_targets,
                        clues=clues,
                        context_blocks=context_blocks,
                        context_notes=context_notes,
                    ),
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

        accepted_segments, ignored_segments, quality_warnings = _prepare_segments(content, segments)
        warnings = list(parsed_payload.get("warnings") or [])
        warnings.extend(quality_warnings)
        parsed_payload["segments"] = accepted_segments
        parsed_payload["ignored_segments"] = ignored_segments
        parsed_payload["context_blocks"] = context_blocks
        parsed_payload["context_notes"] = context_notes
        parsed_payload["warnings"] = warnings
        return QwenFreightParseResult(
            provider=provider or "DASHSCOPE_QWEN",
            model=" -> ".join(dict.fromkeys(used_models)),
            prompt_version=prompt_version,
            raw_response=raw_response,
            parsed_payload=parsed_payload,
            segments=accepted_segments,
            ignored_segments=ignored_segments,
            review_failed_count=review_failed_count,
        )
