"""DashScope SDK freight parsing client.

The parser deliberately does not split WeChat source text with local rules.
WeChat clue splitting and semantic extraction are AI responsibilities; local
code only validates JSON, runs standard master-data matching later, and records
parse progress.
"""

from __future__ import annotations

import asyncio
import copy
import json
import re
import time
from dataclasses import dataclass, field
from threading import Thread
from typing import TYPE_CHECKING, Any, Awaitable, Callable

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.config import settings
from app.core.exceptions import InternalError, ValidationError
from app.integrations.config_keys import (
    AI_PROVIDER,
    DASHSCOPE_API_KEY,
    DASHSCOPE_CONFIG_PROFILE,
    DASHSCOPE_STREAM_TIMEOUT_SECONDS,
    FREIGHT_AI_DETAIL_BATCH_SIZE,
    FREIGHT_AI_DETAIL_CONCURRENCY,
    FREIGHT_AI_DETAIL_MODEL,
    FREIGHT_AI_REVIEW_CONFIDENCE_THRESHOLD,
    FREIGHT_AI_REVIEW_MODEL,
    FREIGHT_AI_SEMANTIC_MODEL,
    FREIGHT_AI_WARN_RAW_CHARS,
)
from app.modules.freight.ai_semantic_validator import FreightSemanticValidator
from app.modules.freight.ai_evidence_gate import (
    GateIssue,
    apply_segment_evidence_gate,
    evidence_clue_schema_hint,
    evidence_detail_schema_hint,
    patch_semantic_map_with_gate_result,
    repair_prompt_payload,
    should_call_ai_repair,
    validate_semantic_map_contract,
)
from app.modules.freight.ai_text_index import FreightIndexedText, FreightTextIndexer

if TYPE_CHECKING:
    from app.modules.system.runtime_config import RuntimeConfigService

ProgressCallback = Callable[[str, str, str, int], Awaitable[None]]


def _normalize_clue_ref(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    if text.startswith("C") and text[1:].isdigit():
        return f"C{int(text[1:])}"
    if text.isdigit():
        return f"C{int(text)}"
    return text


def _as_clue_refs(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, int)):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        values = []
    refs: list[str] = []
    for item in values:
        normalized = _normalize_clue_ref(item)
        if normalized is not None:
            refs.append(normalized)
    return list(dict.fromkeys(refs))


def _normalize_line_ref(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    if text.startswith("L") and text[1:].isdigit():
        return f"L{int(text[1:])}"
    if text.isdigit():
        return f"L{int(text)}"
    return text


def _as_line_refs(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, int)):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        values = []
    refs: list[str] = []
    for item in values:
        normalized = _normalize_line_ref(item)
        if normalized is not None:
            refs.append(normalized)
    return list(dict.fromkeys(refs))


def _line_sort_key(line_ref: str) -> int:
    normalized = _normalize_line_ref(line_ref) or ""
    if normalized.startswith("L") and normalized[1:].isdigit():
        return int(normalized[1:])
    return 10**9


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
    semantic_map: dict[str, Any] = field(default_factory=dict)
    review_results: list[dict[str, Any]] = field(default_factory=list)


class FreightSemanticRouteClueSchema(BaseModel):
    """Strict first-round route clue schema.

    Extra formal candidate fields are ignored here on purpose. The first round
    must only map evidence and route-clue boundaries; detail extraction happens
    in the second round.
    """

    model_config = ConfigDict(extra="ignore")

    clue_temp_id: str | int | None = None
    line_refs: list[str | int] = Field(default_factory=list)
    context_block_id: str | int | None = None
    raw_text: str
    route_type_code: str | None = None
    route_intent_code: str | None = None
    origin: dict[str, Any] | None = None
    destination: dict[str, Any] | None = None
    route_summary: str | None = None
    shared_field_refs: list[str] = Field(default_factory=list)
    missing_field_codes: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    confidence_score: float = 0.5
    warnings: list[str] = Field(default_factory=list)

    @field_validator("line_refs", "shared_field_refs", "missing_field_codes", "evidence", "warnings", mode="before")
    @classmethod
    def _default_list(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, (str, int)):
            return [value]
        return value

    @field_validator("confidence_score", mode="before")
    @classmethod
    def _default_confidence(cls, value: Any) -> Any:
        return 0.5 if value in (None, "") else value


class FreightClueSplitItemSchema(FreightSemanticRouteClueSchema):
    """Compatibility alias for first-round semantic route clues."""


class FreightContextNoteSchema(BaseModel):
    note_id: str | int | None = None
    note_index: int | None = None
    raw_text: str
    context_type_code: str = Field(default="OTHER", description="COMMODITY/TONNAGE/PRICE/CONTACT/REMARK/SETTLEMENT/LOADING/OTHER")
    line_refs: list[str | int] = Field(default_factory=list)
    applies_to: list[str] = Field(default_factory=list)
    scope_type_code: str | None = None
    scope_reason: str | None = None
    evidence_text: str | None = None
    evidence: list[str] = Field(default_factory=list)
    confidence_score: float = 0.5

    @field_validator("context_type_code", mode="before")
    @classmethod
    def _normalize_context_type(cls, value: Any) -> str:
        code = str(value or "OTHER").strip().upper()
        return code if code in {"COMMODITY", "TONNAGE", "PRICE", "CONTACT", "REMARK", "SETTLEMENT", "LOADING", "OTHER"} else "OTHER"

    @field_validator("line_refs", "evidence", mode="before")
    @classmethod
    def _default_list(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, (str, int)):
            return [value]
        return value

    @field_validator("applies_to", mode="before")
    @classmethod
    def _normalize_applies_to(cls, value: Any) -> list[str]:
        return _as_clue_refs(value)

    @field_validator("confidence_score", mode="before")
    @classmethod
    def _default_confidence(cls, value: Any) -> Any:
        return 0.5 if value in (None, "") else value


class FreightContextBlockSchema(BaseModel):
    context_block_id: str | int
    route_clue_ids: list[str] = Field(default_factory=list)
    line_refs: list[str | int] = Field(default_factory=list)
    raw_text: str | None = None
    context_summary: str | None = None
    scope_type_code: str | None = None
    shared_contact_name: str | None = None
    shared_contact_phone: str | None = None
    shared_contact_wechat: str | None = None
    shared_tonnage_text: str | None = None
    shared_commodity_text: str | None = None
    shared_price_text: str | None = None
    shared_unit_price: float | None = None
    shared_total_price: float | None = None
    shared_price_unit: str | None = None
    shared_settlement_method_code: str | None = None
    shared_loading_remark: str | None = None
    shared_remark: str | None = None
    evidence: list[str] = Field(default_factory=list)
    scope_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
    scope_risk_codes: list[str] = Field(default_factory=list)
    confidence_score: float = 0.5

    @field_validator("line_refs", "evidence", "warnings", "scope_risk_codes", mode="before")
    @classmethod
    def _default_list(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, (str, int)):
            return [value]
        return value

    @field_validator("route_clue_ids", mode="before")
    @classmethod
    def _normalize_route_clue_ids(cls, value: Any) -> list[str]:
        return _as_clue_refs(value)

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


class FreightSemanticMapPayloadSchema(BaseModel):
    route_clues: list[FreightSemanticRouteClueSchema] = Field(default_factory=list)
    context_blocks: list[FreightContextBlockSchema] = Field(default_factory=list)
    context_notes: list[FreightContextNoteSchema] = Field(default_factory=list)
    ignored_notes: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_clue_keys(cls, value: Any) -> Any:
        if isinstance(value, dict) and "route_clues" not in value:
            copied = dict(value)
            copied["route_clues"] = copied.get("freight_clues") or copied.get("clues") or []
            return copied
        return value

    @model_validator(mode="after")
    def _require_route_clues(self) -> "FreightSemanticMapPayloadSchema":
        if not self.route_clues:
            raise ValueError("route_clues 不能为空")
        return self


class FreightSegmentSchema(BaseModel):
    clue_temp_id: str | int | None = None
    segment_index: int | None = None
    context_block_id: str | int | None = None
    semantic_role_code: str | None = Field(default="ROUTE", description="ROUTE/CONTEXT/IGNORED")
    route_intent_code: str | None = Field(default=None, description="FORMAL_FREIGHT/SEEK_VESSEL/VESSEL_INQUIRY/OTHER")
    line_refs: list[str | int] = Field(default_factory=list, description="原文行号或行标识")
    raw_text: str = Field(description="原文片段，必须可在原文中追溯")
    field_evidence: dict[str, Any] | None = Field(default=None, description="字段级 evidence contract")
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


_SEGMENT_NUMERIC_FIELDS = {
    "estimated_tonnage",
    "min_tonnage",
    "max_tonnage",
    "unit_price",
    "total_price",
    "confidence_score",
}
_SEGMENT_PRICE_FIELDS = {"unit_price", "total_price"}
_SEGMENT_TONNAGE_FIELDS = {"estimated_tonnage", "min_tonnage", "max_tonnage"}
_DIRTY_PRICE_TONNAGE_REASON = "AI 将疑似吨位误填为价格"


def _as_float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _looks_like_tonnage_expression(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = re.sub(r"\s+", "", value.strip())
    if not text or not re.search(r"\d", text):
        return False
    if re.search(r"(元|块|价格|单价|运价|运费|报价|¥)", text):
        return False
    if re.search(r"(吨|左右|上下|约|大概|船|档期|装)", text):
        return True
    return bool(re.fullmatch(r"\d{3,6}(?:[/-]\d{3,6})+(?:左右|上下|约)?", text))


def _append_segment_review_reason(segment: dict[str, Any], reason: str) -> None:
    segment["needs_strong_review"] = True
    segment["ai_review_status_code"] = "REVIEW_REQUIRED"
    current = str(segment.get("manual_review_reason") or segment.get("ai_review_reason") or "").strip()
    if current:
        if reason not in current:
            segment["manual_review_reason"] = f"{current}；{reason}"
    else:
        segment["manual_review_reason"] = reason
    ai_reason = str(segment.get("ai_review_reason") or "").strip()
    if reason not in ai_reason:
        segment["ai_review_reason"] = f"{ai_reason}；{reason}" if ai_reason else reason


def _add_tonnage_candidate(segment: dict[str, Any], *, text: str, source_field: str) -> None:
    candidates = segment.get("tonnage_candidates")
    if isinstance(candidates, dict):
        candidates = [candidates]
    elif not isinstance(candidates, list):
        candidates = []
    candidate = {
        "text": text,
        "source_field": source_field,
        "belongs_to_current_segment": None,
        "reason": _DIRTY_PRICE_TONNAGE_REASON,
    }
    if candidate not in candidates:
        candidates.append(candidate)
    segment["tonnage_candidates"] = candidates
    if not segment.get("raw_tonnage_text"):
        segment["raw_tonnage_text"] = text


def _preclean_parse_payload_numbers(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    cleaned = copy.deepcopy(payload)
    warnings: list[str] = []
    segments = cleaned.get("segments")
    if not isinstance(segments, list):
        return cleaned, warnings
    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            continue
        clue_ref = segment.get("clue_temp_id") or segment.get("segment_index") or index
        for field_name in _SEGMENT_NUMERIC_FIELDS:
            if field_name not in segment:
                continue
            value = segment.get(field_name)
            if value in (None, ""):
                segment[field_name] = None
                continue
            if _as_float_or_none(value) is not None:
                continue
            text = str(value).strip()
            if field_name in _SEGMENT_PRICE_FIELDS and _looks_like_tonnage_expression(text):
                _add_tonnage_candidate(segment, text=text, source_field=field_name)
                segment[field_name] = None
                _append_segment_review_reason(segment, _DIRTY_PRICE_TONNAGE_REASON)
                warnings.append(f"{clue_ref}: {_DIRTY_PRICE_TONNAGE_REASON}，已清空 {field_name} 并转入吨位候选")
                continue
            if field_name in _SEGMENT_TONNAGE_FIELDS:
                _add_tonnage_candidate(segment, text=text, source_field=field_name)
            segment[field_name] = 0.5 if field_name == "confidence_score" else None
            reason = f"AI 返回的 {field_name} 不是合法数字，已清空并要求复核"
            _append_segment_review_reason(segment, reason)
            warnings.append(f"{clue_ref}: {reason}")
    if warnings:
        existing_warnings = cleaned.get("warnings")
        if isinstance(existing_warnings, list):
            cleaned["warnings"] = [*existing_warnings, *warnings]
        else:
            cleaned["warnings"] = warnings
    return cleaned, warnings


def _json_schema_hint() -> dict[str, Any]:
    return evidence_detail_schema_hint()


def _clue_schema_hint() -> dict[str, Any]:
    return evidence_clue_schema_hint()


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


def _segment_needs_strong_review(segment: dict[str, Any], *, confidence_threshold: float = 0.65) -> bool:
    if segment.get("is_freight_candidate") is False or segment.get("drop_reason"):
        return True
    if segment.get("scope_risk_codes"):
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
        confidence < confidence_threshold
        or required_missing
        or price_without_price_field
        or inherited_tonnage_missing
        or str(segment.get("availability_status_code") or "").upper() != "READY"
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
    by_clue_ref: dict[str, dict[str, Any]] = {}
    by_segment_index: dict[int, dict[str, Any]] = {}
    for block in context_blocks:
        for raw_index in _as_clue_refs(block.get("route_clue_ids")):
            by_clue_ref[raw_index] = block
            try:
                by_segment_index[int(raw_index[1:] if raw_index.startswith("C") else raw_index)] = block
            except (TypeError, ValueError):
                continue
    warnings: list[str] = []
    patched: list[dict[str, Any]] = []
    for index, segment in enumerate(segments, start=1):
        item = dict(segment)
        block = None
        if item.get("context_block_id") not in (None, ""):
            block = by_block_id.get(str(item.get("context_block_id")))
        clue_ref = _normalize_clue_ref(item.get("clue_temp_id") or item.get("segment_index") or index)
        if clue_ref and item.get("clue_temp_id") not in (None, ""):
            item["clue_temp_id"] = clue_ref
        block = block or by_clue_ref.get(clue_ref or "")
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
        block_risks = set(block.get("scope_risk_codes") or [])
        contact_inheritance_blocked = bool(block_risks & {"CONTACT_SCOPE_CONFLICT", "CONTEXT_BLOCK_CONFLICT", "MULTI_CONTACT_BLOCK"})
        for field_name, keys in field_map.items():
            if contact_inheritance_blocked and field_name in {"contact_name", "contact_phone", "contact_wechat"}:
                item["needs_strong_review"] = True
                item.setdefault("scope_risk_codes", [])
                for risk_code in block_risks:
                    if risk_code not in item["scope_risk_codes"]:
                        item["scope_risk_codes"].append(risk_code)
                _append_review_reason(item, "上下文联系人作用域存在风险，未自动继承联系人")
                continue
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

    async def _config_int(self, key: str, default: int) -> int:
        return await self.runtime_config.get_int(key, default, profile_code=DASHSCOPE_CONFIG_PROFILE)

    async def _config_float(self, key: str, default: float) -> float:
        return await self.runtime_config.get_float(key, default, profile_code=DASHSCOPE_CONFIG_PROFILE)

    @staticmethod
    def _schema_compat_flags(payload: dict[str, Any]) -> list[str]:
        flags: list[str] = []
        if "route_clues" not in payload and "freight_clues" in payload:
            flags.append("freight_clues")
        if "route_clues" not in payload and "clues" in payload:
            flags.append("clues")
        for block in payload.get("context_blocks") or []:
            if isinstance(block, dict) and "route_clue_ids" not in block:
                for key in ("applies_to", "clue_ids", "segment_indices"):
                    if key in block:
                        flags.append(f"context_blocks.{key}")
                        break
        return list(dict.fromkeys(flags))

    @staticmethod
    def _semantic_map_is_complex(
        indexed_text: FreightIndexedText,
        semantic_map: dict[str, Any],
        gate_result: Any | None = None,
    ) -> bool:
        route_clues = [item for item in semantic_map.get("route_clues") or [] if isinstance(item, dict)]
        context_blocks = [item for item in semantic_map.get("context_blocks") or [] if isinstance(item, dict)]
        context_notes = [item for item in semantic_map.get("context_notes") or [] if isinstance(item, dict)]
        if len(indexed_text.line_map) >= 6 or len(route_clues) >= 3:
            return True
        if context_blocks or context_notes:
            return True
        if any(len(_as_clue_refs(block.get("route_clue_ids"))) > 1 for block in context_blocks):
            return True
        if any(str(clue.get("route_type_code") or "").upper() == "MULTI_DESTINATION_EXPANDED" for clue in route_clues):
            return True
        if any(clue.get("missing_field_codes") for clue in route_clues):
            return True
        if semantic_map.get("scope_risk_codes") or semantic_map.get("_schema_compat_flags"):
            return True
        quality_gate = semantic_map.get("quality_gate")
        if isinstance(quality_gate, dict) and (quality_gate.get("should_repair") or quality_gate.get("should_review")):
            return True
        return bool(gate_result and (getattr(gate_result, "should_repair", False) or getattr(gate_result, "should_review", False)))

    @staticmethod
    def _detail_model_for_wechat(
        indexed_text: FreightIndexedText,
        semantic_map: dict[str, Any],
        runtime: dict[str, Any],
        gate_result: Any | None = None,
    ) -> str:
        configured = str(runtime.get("detail_model") or "").strip()
        if not DashScopeQwenFreightParserClient._semantic_map_is_complex(indexed_text, semantic_map, gate_result):
            return configured
        if configured and "turbo" not in configured.lower():
            return configured
        return str(runtime.get("semantic_model") or runtime.get("review_model") or configured or "qwen-plus").strip()

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
    def _semantic_map_messages(indexed_content: str) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "你是内河航运微信群货源语义地图助手。只输出 JSON。"
                    "你必须阅读全文；输入是完整原文加 L1/L2/L3 行号，行号不是业务切分结果。"
                    "第一轮只输出语义地图，不生成正式候选货源，不输出完整候选字段。"
                    "输出必须分为 route_clues、context_blocks、context_notes、ignored_notes 和 warnings。"
                    "每个 route_clue 必须有稳定 clue_temp_id、line_refs、context_block_id、raw_text、evidence 和 confidence_score。"
                    "每个 route_clue 还必须给出 route_type_code、route_intent_code、origin/destination 的 evidence_line_refs/evidence_text；无法确认填 null 并写 missing_field_codes。"
                    "clue_temp_id 必须使用 C1/C2/C3 这类字符串；context_block.route_clue_ids 也必须引用这些字符串，禁止混用 1/2 数字。"
                    "所有 route_clue/context_blocks/context_notes/ignored_notes 都必须带 line_refs；line_refs 只能使用输入中真实存在的 L 行号。"
                    "route_clues 只描述疑似路线线索和上下文关系；严禁输出 origin_text、destination_text、commodity_name、inherited_context、needs_strong_review 等正式候选字段。"
                    "召回优先：宁可多保留疑似路线并在 warnings 标风险，也不能把多条路线合并成一条。"
                    "一行多目的地必须在第一轮展开为多条 route_clues，route_type_code 写 MULTI_DESTINATION_EXPANDED，不要把多个目的地塞到一个 destination。"
                    "公共联系人、货品、吨位、价格、结算、装卸备注必须抽成 context_blocks/context_notes，并用 route_clue_ids 或 applies_to 说明适用范围。"
                    "context_blocks/context_notes 必须给出 scope_type_code：只有 LOCAL_LINE 或 EXPLICIT_SHARED 才是可自动继承；WEAK_INFERRED/UNKNOWN 只能触发人工复核。"
                    "联系人作用域必须谨慎：多个手机号、@所有人、公告边界、相邻联系人块不能合并为一个全局联系人块。"
                    "一行或多行上下文可继承给多个 route_clues，但不能因此新增不存在的货源，不能跨另一个联系人锚点扩大继承范围。"
                    "吨位和货品只能作为带 scope_type_code 的候选上下文记录，不能因为同一公告块就默认继承给所有路线。"
                    "不确定填 null 或空数组；不得编造，不能使用 JSON 结构说明里的占位值。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请读取完整微信群原文，输出语义地图。请召回所有疑似路线线索，但不要生成正式候选货源。"
                    f"JSON 输出结构：{json.dumps(_clue_schema_hint(), ensure_ascii=False)}\n\n"
                    "带行号完整原文：\n"
                    f"{indexed_content}"
                ),
            },
        ]

    @staticmethod
    def _related_context(
        semantic_map: dict[str, Any],
        clues: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        clue_ids = {
            clue_ref
            for clue in clues
            for clue_ref in [_normalize_clue_ref(clue.get("clue_temp_id") or clue.get("segment_index"))]
            if clue_ref
        }
        block_ids = {str(clue.get("context_block_id")) for clue in clues if clue.get("context_block_id") not in (None, "")}
        context_blocks: list[dict[str, Any]] = []
        for block in semantic_map.get("context_blocks") or []:
            if not isinstance(block, dict):
                continue
            refs = set(_as_clue_refs(block.get("route_clue_ids")))
            block_id = str(block.get("context_block_id") or "")
            if refs & clue_ids or (block_id and block_id in block_ids):
                copied = dict(block)
                copied["route_clue_ids"] = _as_clue_refs(copied.get("route_clue_ids"))
                context_blocks.append(copied)

        context_notes: list[dict[str, Any]] = []
        for note in semantic_map.get("context_notes") or []:
            if not isinstance(note, dict):
                continue
            applies_to = set(_as_clue_refs(note.get("applies_to")))
            if applies_to & clue_ids:
                copied = dict(note)
                copied["applies_to"] = _as_clue_refs(copied.get("applies_to"))
                context_notes.append(copied)
        return context_blocks, context_notes

    @staticmethod
    def _build_evidence_payload(
        indexed_text: FreightIndexedText,
        semantic_map: dict[str, Any],
        clues: list[dict[str, Any]],
        *,
        segments: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        context_blocks, context_notes = DashScopeQwenFreightParserClient._related_context(semantic_map, clues)
        line_refs: set[str] = set()
        for item in [*clues, *context_blocks, *context_notes, *(segments or [])]:
            line_refs.update(_as_line_refs(item.get("line_refs") or item.get("line_refs_json")))
        ordered_refs = sorted((ref for ref in line_refs if ref in indexed_text.line_map), key=_line_sort_key)
        evidence_lines = [{"line_ref": ref, "text": indexed_text.line_map[ref]} for ref in ordered_refs]
        payload = {
            "evidence_lines": evidence_lines,
            "route_clues": clues,
            "context_blocks": context_blocks,
            "context_notes": context_notes,
        }
        if segments is not None:
            payload["segments"] = segments
        metrics = {
            "clue_count": len(clues),
            "segment_count": len(segments or []),
            "context_block_count": len(context_blocks),
            "context_note_count": len(context_notes),
            "evidence_line_count": len(evidence_lines),
            "source_line_count": len(indexed_text.line_map),
        }
        return payload, metrics

    @staticmethod
    def _detail_messages(evidence_payload: dict[str, Any]) -> list[dict[str, str]]:
        system_hint = (
            "你是内河航运微信群货源结构化抽取助手。只输出 JSON。"
            "输入 route_clues 已由第一轮完整原文语义地图给出；当前只提供本批 clue 相关 evidence_lines、context_blocks、context_notes。"
            "不得重新切分原文，不得新增 route_clues 之外的货源；只能补全输入中给定 clue_temp_id 的字段。"
            "每个 segment 必须带回 clue_temp_id、line_refs、context_block_id 和 raw_text；字段必须来自 evidence_lines、route_clues 或关联 context_blocks/context_notes。"
            "每个非空核心字段必须写入 field_evidence，包含 value、source_type_code、line_refs、evidence_text、confidence_score。"
            "origin_text/destination_text/commodity_name/raw_tonnage_text 只有 source_type_code 为 LOCAL_LINE 或 EXPLICIT_SHARED 时才能写入顶层字段。"
            "WEAK_INFERRED 或 UNKNOWN 的货品、吨位、地点只放入 ai_review_json.suggested_fields，并把 ai_review_status_code 写 REVIEW_REQUIRED；不能写入顶层字段供自动确认。"
            "普通 route_clue 输出一个 segment；若第一轮 clue 明确包含多目的地，可输出多个同 clue_temp_id 的 segment，但不能创建新的 clue_temp_id。"
            "context_blocks/context_notes 只能用于继承联系人、价格、结算、装卸备注，不能单独输出为 segment。"
            "只有联系人作用域明确、context_block 无风险、且证据行能支撑时，才可继承公共联系人和电话；证据不足填 null 并标记 REVIEW_REQUIRED。"
            "装货地、卸货地、货品、吨位、价格、联系人、结算、装卸备注和可发状态都只能依据当前 evidence package 判断。"
            "有装货地和卸货地但缺货品的 clue 必须输出 segment；若只是相邻上下文推测货品，commodity_name 必须为 null，并在 ai_review_json.suggested_fields 记录建议，不能一键确认。"
            "如果目的地是多个地点，必须拆成多个 segments；不要把多个目的地塞进一个 destination_text。"
            "请保留 clue 中的 context_block_id；origin_match_level_code/destination_match_level_code 只有具体设施才标 NODE，只有城市名或城市简称标 CITY。"
            "吨位原文必须写 raw_tonnage_text；单点吨位填 estimated_tonnage；范围吨位填 min_tonnage 和 max_tonnage。"
            "运输吨位必须只归属当前 freight_clue：同一公告里出现多条线路和多个吨位范围时，每个 segment 只能选择自己这一行或明确绑定上下文里的吨位。"
            "如果你发现多个吨位候选无法判断归属，raw_tonnage_text 填 null，tonnage_candidates 写候选，ai_review_status_code 填 REVIEW_REQUIRED。"
            "50米船、拖队一条、船型、米数、条数不是吨位；写入 quantity_description/vessel_description 或 cargo_description，不得写入 raw_tonnage_text。"
            "1500-2000内 表示 min_tonnage=1500、max_tonnage=2000；2000左右 表示 estimated_tonnage=2000；2000--2500吨 表示 min_tonnage=2000、max_tonnage=2500。"
            "2-3500吨这类微信群简写通常表示 2000-3500吨，若你能从上下文确认就填 min_tonnage=2000、max_tonnage=3500；不能确认则只填 raw_tonnage_text 并写 manual_review_reason。"
            "每个 segment 必须给出 tonnage_decision，说明吨位是否 PASS；无法确认时写 ai_review_reason，不要为了凑字段拼接其它线路的吨位。"
            "正式货源 FORMAL_FREIGHT 没有吨位必须 REVIEW_REQUIRED。寻船/询船 SEEK_VESSEL 或 VESSEL_INQUIRY 可以无吨位，但 availability_status_code 不得 READY。"
            "非空字段必须能从当前 evidence package 中找到证据；没有证据必须填 null，不能凭完整原文记忆补全。"
            "如果某个 freight_clue 复核后不是完整货源线索，输出 is_freight_candidate=false 并写 drop_reason。"
            "船已够、暂时不要、过几天要应标为 FULL 或 DEFERRED；滚动发、随船装缺明确装期时标为 UNKNOWN。"
            "不得使用 JSON 结构说明中的占位值作为真实字段。"
        )
        return [
            {"role": "system", "content": system_hint},
            {
                "role": "user",
                "content": (
                    "请对本批 AI 线索做字段抽取：\n"
                    f"JSON 输出结构：{json.dumps(_json_schema_hint(), ensure_ascii=False)}\n\n"
                    f"{json.dumps(evidence_payload, ensure_ascii=False)}"
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
                "输入 route_clues 已由第一轮 AI 从同一段完整原文语义地图中给出，context_blocks 是公共上下文块，context_notes 是补充上下文。"
                "不得重新切分原文，不得新增 route_clues 之外的货源；只能补全输入中给定 clue_temp_id 的字段。"
                "每个 segment 必须带回 clue_temp_id、line_refs、context_block_id 和 raw_text；字段必须来自原文行、第一轮 route_clues 或 context_blocks/context_notes。"
                "每个非空核心字段必须写入 field_evidence，包含 value、source_type_code、line_refs、evidence_text、confidence_score。"
                "origin_text/destination_text/commodity_name/raw_tonnage_text 只有 source_type_code 为 LOCAL_LINE 或 EXPLICIT_SHARED 时才能写入顶层字段。"
                "WEAK_INFERRED 或 UNKNOWN 的货品、吨位、地点只放入 ai_review_json.suggested_fields，并把 ai_review_status_code 写 REVIEW_REQUIRED。"
                "普通 route_clue 输出一个 segment；若第一轮 clue 明确包含多目的地，可输出多个同 clue_temp_id 的 segment，但不能创建新的 clue_temp_id。"
                "context_blocks/context_notes 只能用于继承联系人、价格、结算、装卸备注，不能单独输出为 segment。"
                "每个 segment 必须保留对应 freight_clue 的 context_block_id；只有作用域明确且证据充分时，才可继承同一 context_block 的公共联系人和电话。"
                "装货地、卸货地、货品、吨位、价格、联系人、结算、装卸备注和可发状态都只能依据原文与 clue 上下文判断。"
                "有装货地和卸货地但缺货品的 clue 必须输出 segment；若只是相邻上下文推测货品，commodity_name 必须为 null，并在 ai_review_json.suggested_fields 记录建议，不能一键确认。"
                "如果目的地是多个地点，必须拆成多个 segments；不要把多个目的地塞进一个 destination_text。"
                "请保留 clue 中的 origin_match_level_code/destination_match_level_code；只有具体设施才标 NODE，只有城市名或城市简称标 CITY。"
                "吨位原文必须写 raw_tonnage_text；单点吨位填 estimated_tonnage；范围吨位填 min_tonnage 和 max_tonnage。"
                "运输吨位必须只归属当前 freight_clue：同一公告里出现多条线路和多个吨位范围时，每个 segment 只能选择自己这一行或明确绑定上下文里的吨位。"
                "如果你发现多个吨位候选无法判断归属，raw_tonnage_text 填 null，tonnage_candidates 写候选，ai_review_status_code 填 REVIEW_REQUIRED。"
                "50米船、拖队一条、船型、米数、条数不是吨位；写入 quantity_description/vessel_description 或 cargo_description，不得写入 raw_tonnage_text。"
                "1500-2000内 表示 min_tonnage=1500、max_tonnage=2000；2000左右 表示 estimated_tonnage=2000；2000--2500吨 表示 min_tonnage=2000、max_tonnage=2500。"
                "2-3500吨这类微信群简写通常表示 2000-3500吨，若你能从上下文确认就填 min_tonnage=2000、max_tonnage=3500；不能确认则只填 raw_tonnage_text 并写 manual_review_reason。"
                "每个 segment 必须给出 tonnage_decision，说明吨位是否 PASS；无法确认时写 ai_review_reason，不要为了凑字段拼接其它线路的吨位。"
                "正式货源 FORMAL_FREIGHT 没有吨位必须 REVIEW_REQUIRED。寻船/询船 SEEK_VESSEL 或 VESSEL_INQUIRY 可以无吨位，但 availability_status_code 不得 READY。"
                "非空字段必须能从原文、freight_clue、context_notes、evidence 或 inherited_context 中找到证据；没有证据必须填 null。"
                "如果某个 freight_clue 复核后不是完整货源线索，输出 is_freight_candidate=false 并写 drop_reason。"
                "船已够、暂时不要、过几天要应标为 FULL 或 DEFERRED；滚动发、随船装缺明确装期时标为 UNKNOWN。"
                "不得使用 JSON 结构说明中的占位值作为真实字段。"
            )
            user_hint = "请对 AI 线索切分结果做字段抽取："
            source_payload = json.dumps(
                {
                    "evidence_lines": [],
                    "route_clues": clues,
                    "context_blocks": context_blocks or [],
                    "context_notes": context_notes or [],
                    "warning": "legacy caller did not provide evidence_lines; do not infer fields without evidence",
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
        evidence_payload: dict[str, Any],
    ) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "你是内河航运微信群货源复核助手。只输出 JSON。"
                    "请复核输入 segments 的字段完整性、吨位归类、可发状态、上下文继承和证据来源。"
                    "不得新增原文中不存在的货源，不得新增输入以外的 clue_temp_id；只能修正输入 segment 的字段、清空无证据字段，或把上下文-only/空线索标记为 is_freight_candidate=false。"
                    "当前只提供风险候选相关 evidence_lines、route_clues、context_blocks、context_notes；不得凭完整原文记忆补字段。"
                    "每个非空核心字段必须保留或补齐 field_evidence；缺证据、WEAK_INFERRED 或 UNKNOWN 的字段必须 REVIEW_REQUIRED，不能作为顶层字段自动确认。"
                    "必须核对 context_blocks 的 route_clue_ids：只有作用域明确、无 CONTACT_SCOPE_CONFLICT/CONTEXT_BLOCK_CONFLICT/MULTI_CONTACT_BLOCK 风险时，公共联系人、电话、装卸备注才可继承到该 block 覆盖的 segment。"
                    "公共吨位不能自动继承；必须根据 route_clue 原文和上下文语义逐条裁决归属，不能把多个线路的吨位范围合并到一个 segment。"
                    "手机号紧跟路线或位于连续公告块末尾时，只有证据行和 context_block scope_reason 明确支撑才可覆盖该块。证据不足则填 null 并标记需人工判断，但不要丢弃路线。"
                    "缺货品但上下文只是弱推断时，不要填 commodity_name；可把建议放在 ai_review_json.suggested_fields.commodity_name。"
                    "正式货源无吨位必须 REVIEW_REQUIRED；寻船、要船、询船无吨位可以保留候选，但不得 READY 或一键确认。"
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
                    f"{json.dumps(evidence_payload, ensure_ascii=False)}"
                ),
            },
        ]

    @staticmethod
    def _repair_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "你是内河航运微信群货源语义修复助手。只输出 JSON。"
                    "你只能根据输入 indexed_text、semantic_map、segments 和 issues 修复结构化结果，不得编造原文没有的信息。"
                    "修复目标是补齐字段级证据、修正线索边界、清空弱推断顶层字段，并把无法确认的候选标记 REVIEW_REQUIRED/UNKNOWN。"
                    "如果无法可靠修复，保留原值或清空不安全字段，并写明 ai_review_reason。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请修复这些 AI 解析结果：\n"
                    f"{json.dumps(payload, ensure_ascii=False)}"
                ),
            },
        ]

    @staticmethod
    def _normalize_semantic_map_payload(payload: dict[str, Any], indexed_text: FreightIndexedText) -> dict[str, Any]:
        validated = FreightSemanticMapPayloadSchema.model_validate(payload)
        route_clues = []
        for index, item in enumerate(validated.route_clues, start=1):
            clue = item.model_dump(exclude_none=True)
            clue["clue_temp_id"] = _normalize_clue_ref(clue.get("clue_temp_id") or index) or f"C{index}"
            clue["line_refs"] = _as_line_refs(clue.get("line_refs"))
            route_clues.append(clue)
        semantic_map = validated.model_dump(exclude_none=True)
        semantic_map["route_clues"] = route_clues
        for block in semantic_map.get("context_blocks") or []:
            if isinstance(block, dict):
                block["route_clue_ids"] = _as_clue_refs(block.get("route_clue_ids"))
                block["line_refs"] = _as_line_refs(block.get("line_refs"))
        for note in semantic_map.get("context_notes") or []:
            if isinstance(note, dict):
                note["applies_to"] = _as_clue_refs(note.get("applies_to"))
                note["line_refs"] = _as_line_refs(note.get("line_refs"))
        semantic_map["indexed_text"] = indexed_text.indexed_text
        semantic_map["line_count"] = len(indexed_text.line_map)
        return semantic_map

    async def repair_semantic_output(
        self,
        indexed_text: FreightIndexedText,
        semantic_map: dict[str, Any],
        segments: list[dict[str, Any]],
        issues: list[GateIssue],
        *,
        runtime: dict[str, Any] | None = None,
        progress_callback: ProgressCallback | None = None,
        stage_code: str = "AI_REPAIR",
        progress_percent: int = 66,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        runtime = runtime or await self._runtime()
        repair_payload, raw = await self._call_json(
            model=runtime["review_model"],
            api_key=runtime["api_key"],
            messages=self._repair_messages(repair_prompt_payload(indexed_text, semantic_map, segments, issues)),
            timeout=runtime["timeout"],
            progress_callback=progress_callback,
            stage_code=stage_code,
            stage_name="AI 证据修复",
            stage_message="强模型正在修复字段证据和上下文归属",
            progress_percent=progress_percent,
        )
        repaired_semantic_payload = repair_payload.get("semantic_map") if isinstance(repair_payload.get("semantic_map"), dict) else None
        repaired_semantic = (
            self._normalize_semantic_map_payload(repaired_semantic_payload, indexed_text)
            if repaired_semantic_payload is not None
            else dict(semantic_map)
        )
        repaired_semantic["_repair_summary"] = repair_payload.get("repair_summary")
        repaired_segments = segments
        if isinstance(repair_payload.get("segments"), list) and repair_payload.get("segments"):
            payload_with_segments = {"segments": repair_payload.get("segments") or []}
            payload_with_segments, _ = _preclean_parse_payload_numbers(payload_with_segments)
            validated = FreightParsePayloadSchema.model_validate(payload_with_segments)
            repaired_segments = self._segments_from_payload(validated.model_dump(exclude_none=True))
        return repaired_semantic, repaired_segments, {"raw_response": raw, "repair_payload": repair_payload}

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

    async def _runtime(self) -> dict[str, Any]:
        provider = await self._config_value(AI_PROVIDER, settings.AI_PROVIDER)
        semantic_model = await self._config_value(FREIGHT_AI_SEMANTIC_MODEL, settings.FREIGHT_AI_SEMANTIC_MODEL)
        detail_model = await self._config_value(FREIGHT_AI_DETAIL_MODEL, settings.FREIGHT_AI_DETAIL_MODEL)
        review_model = await self._config_value(FREIGHT_AI_REVIEW_MODEL, settings.FREIGHT_AI_REVIEW_MODEL)
        api_key = await self._config_value(DASHSCOPE_API_KEY, settings.DASHSCOPE_API_KEY)
        if not api_key:
            raise ValidationError("未配置 DASHSCOPE_API_KEY，无法调用通义千问解析")
        for key, value in {
            FREIGHT_AI_SEMANTIC_MODEL: semantic_model,
            FREIGHT_AI_DETAIL_MODEL: detail_model,
            FREIGHT_AI_REVIEW_MODEL: review_model,
        }.items():
            if not value:
                raise ValidationError(f"未配置 {key}，无法调用货源 AI 解析")
        return {
            "provider": provider or "DASHSCOPE_QWEN",
            "semantic_model": semantic_model,
            "detail_model": detail_model,
            "review_model": review_model,
            "api_key": api_key,
            "timeout": await self._stream_timeout(),
            "detail_batch_size": max(1, min(await self._config_int(FREIGHT_AI_DETAIL_BATCH_SIZE, settings.FREIGHT_AI_DETAIL_BATCH_SIZE), 20)),
            "detail_concurrency": max(1, min(await self._config_int(FREIGHT_AI_DETAIL_CONCURRENCY, settings.FREIGHT_AI_DETAIL_CONCURRENCY), 5)),
            "review_threshold": max(0.0, min(await self._config_float(FREIGHT_AI_REVIEW_CONFIDENCE_THRESHOLD, settings.FREIGHT_AI_REVIEW_CONFIDENCE_THRESHOLD), 1.0)),
            "warn_raw_chars": max(0, await self._config_int(FREIGHT_AI_WARN_RAW_CHARS, settings.FREIGHT_AI_WARN_RAW_CHARS)),
        }

    async def parse_semantic_map(
        self,
        indexed_text: FreightIndexedText,
        *,
        runtime: dict[str, Any] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        runtime = runtime or await self._runtime()
        payload, raw = await self._call_json(
            model=runtime["semantic_model"],
            api_key=runtime["api_key"],
            messages=self._semantic_map_messages(indexed_text.indexed_text),
            timeout=runtime["timeout"],
            progress_callback=progress_callback,
            stage_code="AI_SEMANTIC_MAP",
            stage_name="AI 语义地图",
            stage_message="AI 正在阅读全文并输出语义地图",
            progress_percent=30,
        )
        compat_flags = self._schema_compat_flags(payload)
        try:
            semantic_map = self._normalize_semantic_map_payload(payload, indexed_text)
        except Exception as exc:
            raise ValidationError("通义千问语义地图结构不符合 schema", detail={"error": str(exc), "payload": payload}) from exc
        if not semantic_map.get("route_clues"):
            raise ValidationError("通义千问未输出货源语义线索", detail={"payload": payload})
        if compat_flags:
            semantic_map["_schema_compat_flags"] = compat_flags
        warnings = list(semantic_map.get("warnings") or [])
        warn_raw_chars = int(runtime.get("warn_raw_chars") or 0)
        if warn_raw_chars and len(indexed_text.raw_text) > warn_raw_chars:
            warnings.append(f"原文长度 {len(indexed_text.raw_text)} 超过告警阈值 {warn_raw_chars}，未截断")
        semantic_map["warnings"] = warnings
        return semantic_map, raw

    async def complete_candidate_fields(
        self,
        indexed_text: FreightIndexedText,
        semantic_map: dict[str, Any],
        *,
        runtime: dict[str, Any] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], list[dict[str, Any]]]:
        runtime = runtime or await self._runtime()
        route_clues = [
            clue
            for clue in semantic_map.get("route_clues") or []
            if isinstance(clue, dict) and clue.get("is_freight_candidate") is not False and not clue.get("drop_reason")
        ]
        if not route_clues:
            raise ValidationError("第一轮语义地图未输出可补全 route_clues", detail={"semantic_map": semantic_map})
        batch_size = int(runtime["detail_batch_size"])
        chunks = [route_clues[index : index + batch_size] for index in range(0, len(route_clues), batch_size)]
        semaphore = asyncio.Semaphore(int(runtime["detail_concurrency"]))
        raw_responses: list[dict[str, Any]] = []
        warnings: list[str] = []
        metrics_by_chunk: dict[int, dict[str, Any]] = {}

        async def run_chunk(chunk_index: int, clues: list[dict[str, Any]]) -> list[dict[str, Any]]:
            async with semaphore:
                evidence_payload, evidence_metrics = self._build_evidence_payload(indexed_text, semantic_map, clues)
                evidence_metrics["batch_index"] = chunk_index
                detail_model = self._detail_model_for_wechat(indexed_text, semantic_map, runtime)
                evidence_metrics["detail_model"] = detail_model
                metrics_by_chunk[chunk_index] = evidence_metrics
                payload, raw = await self._call_json(
                    model=detail_model,
                    api_key=runtime["api_key"],
                    messages=self._detail_messages(evidence_payload),
                    timeout=runtime["timeout"],
                    progress_callback=progress_callback,
                    stage_code="AI_DETAIL",
                    stage_name="AI 补全字段",
                    stage_message=f"AI 正在补全候选字段 {chunk_index}/{len(chunks)}",
                    progress_percent=45 + min(20, int(chunk_index / max(len(chunks), 1) * 20)),
                )
                raw_responses.append(raw)
                payload, _ = _preclean_parse_payload_numbers(payload)
                try:
                    validated = FreightParsePayloadSchema.model_validate(payload)
                except Exception as exc:
                    raise ValidationError("通义千问字段补全结构不符合货源解析 schema", detail={"error": str(exc), "payload": payload}) from exc
                data = validated.model_dump(exclude_none=True)
                warnings.extend(str(item) for item in data.get("warnings") or [])
                return self._segments_from_payload(data)

        chunk_results = await asyncio.gather(*(run_chunk(index, chunk) for index, chunk in enumerate(chunks, start=1)))
        segments = [segment for chunk in chunk_results for segment in chunk]
        segments, context_block_warnings = _apply_context_blocks_to_segments(segments, semantic_map.get("context_blocks") or [])
        warnings.extend(context_block_warnings)
        metrics = [metrics_by_chunk[index] for index in sorted(metrics_by_chunk)]
        return segments, raw_responses, warnings, metrics

    async def review_risky_segments(
        self,
        indexed_text: FreightIndexedText,
        semantic_map: dict[str, Any],
        segments: list[dict[str, Any]],
        *,
        runtime: dict[str, Any] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, int, list[dict[str, Any]]]:
        runtime = runtime or await self._runtime()
        threshold = float(runtime["review_threshold"])
        review_targets = [item for item in segments if _segment_needs_strong_review(item, confidence_threshold=threshold)]
        if not review_targets:
            return [], None, 0, []
        clue_by_id = {
            clue_ref: clue
            for clue in semantic_map.get("route_clues") or []
            if isinstance(clue, dict)
            for clue_ref in [_normalize_clue_ref(clue.get("clue_temp_id") or clue.get("segment_index"))]
            if clue_ref
        }
        review_clues: list[dict[str, Any]] = []
        for target in review_targets:
            clue_ref = _normalize_clue_ref(target.get("clue_temp_id") or target.get("segment_index"))
            clue = clue_by_id.get(clue_ref or "")
            if clue is not None:
                review_clues.append(clue)
            else:
                review_clues.append(
                    {
                        "clue_temp_id": clue_ref,
                        "line_refs": target.get("line_refs") or target.get("line_refs_json") or [],
                        "raw_text": target.get("raw_text") or "",
                        "context_block_id": target.get("context_block_id"),
                    }
                )
        evidence_payload, evidence_metrics = self._build_evidence_payload(
            indexed_text,
            semantic_map,
            review_clues,
            segments=review_targets,
        )
        evidence_metrics["batch_index"] = 1
        try:
            review_payload, review_raw = await self._call_json(
                model=runtime["review_model"],
                api_key=runtime["api_key"],
                messages=self._review_messages(evidence_payload),
                timeout=runtime["timeout"],
                progress_callback=progress_callback,
                stage_code="AI_REVIEW",
                stage_name="AI 强复核",
                stage_message="强模型正在复核风险候选",
                progress_percent=76,
            )
            review_payload, _ = _preclean_parse_payload_numbers(review_payload)
            review_validated = FreightParsePayloadSchema.model_validate(review_payload)
            reviewed = self._segments_from_payload(review_validated.model_dump(exclude_none=True))
            return reviewed, review_raw, 0, [evidence_metrics]
        except Exception as exc:  # noqa: BLE001
            for item in review_targets:
                item["availability_status_code"] = "UNKNOWN"
                item["manual_review_reason"] = f"强模型复核失败，需人工判断：{exc}"
                item["needs_strong_review"] = True
            return [], {"error": str(exc)}, len(review_targets), [evidence_metrics]

    def merge_review_results(self, segments: list[dict[str, Any]], review_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        reviewed_by_exact: dict[tuple[str, str], dict[str, Any]] = {}
        reviewed_by_raw: dict[tuple[str, str], dict[str, Any]] = {}
        reviewed_by_segment_index: dict[str, dict[str, Any]] = {}
        reviewed_by_clue: dict[str, list[dict[str, Any]]] = {}
        for index, item in enumerate(review_results, start=1):
            clue_ref = _normalize_clue_ref(item.get("clue_temp_id"))
            segment_index = str(item.get("segment_index") or index)
            raw_text = str(item.get("raw_text") or "")
            if clue_ref:
                reviewed_by_clue.setdefault(clue_ref, []).append(item)
                if segment_index:
                    reviewed_by_exact[(clue_ref, segment_index)] = item
                if raw_text:
                    reviewed_by_raw[(clue_ref, raw_text)] = item
            if segment_index:
                reviewed_by_segment_index[segment_index] = item
        merged: list[dict[str, Any]] = []
        for index, item in enumerate(segments, start=1):
            clue_ref = _normalize_clue_ref(item.get("clue_temp_id"))
            segment_index = str(item.get("segment_index") or index)
            raw_text = str(item.get("raw_text") or "")
            reviewed = None
            if clue_ref:
                reviewed = reviewed_by_exact.get((clue_ref, segment_index)) or reviewed_by_raw.get((clue_ref, raw_text))
                clue_matches = reviewed_by_clue.get(clue_ref) or []
                if reviewed is None and len(clue_matches) == 1:
                    reviewed = clue_matches[0]
            reviewed = reviewed or reviewed_by_segment_index.get(segment_index)
            merged.append({**item, **(reviewed or {})})
        return merged

    async def _parse_tms(
        self,
        content: str,
        *,
        runtime: dict[str, Any],
        progress_callback: ProgressCallback | None = None,
    ) -> QwenFreightParseResult:
        payload, raw = await self._call_json(
            model=runtime["detail_model"],
            api_key=runtime["api_key"],
            messages=self._extract_messages(content, [], source_type_code="TMS"),
            timeout=runtime["timeout"],
            progress_callback=progress_callback,
            stage_code="AI_DETAIL",
            stage_name="AI 抽取字段",
            stage_message="AI 正在抽取 TMS 运单字段",
            progress_percent=55,
        )
        try:
            payload, _ = _preclean_parse_payload_numbers(payload)
            validated = FreightParsePayloadSchema.model_validate(payload)
            parsed_payload = validated.model_dump(exclude_none=True)
        except Exception as exc:
            raise ValidationError("通义千问返回结构不符合货源解析 schema", detail={"error": str(exc), "payload": payload}) from exc
        accepted_segments, ignored_segments, quality_warnings = _prepare_segments(content, self._segments_from_payload(parsed_payload))
        parsed_payload["segments"] = accepted_segments
        parsed_payload["ignored_segments"] = ignored_segments
        parsed_payload["warnings"] = [*(parsed_payload.get("warnings") or []), *quality_warnings]
        return QwenFreightParseResult(
            provider=runtime["provider"],
            model=runtime["detail_model"],
            prompt_version=self.tms_prompt_version,
            raw_response={"provider": runtime["provider"], "pipeline": "dashscope_sdk_stream", "detail": raw},
            parsed_payload=parsed_payload,
            segments=accepted_segments,
            ignored_segments=ignored_segments,
        )

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
        runtime = await self._runtime()
        if normalized_source == "TMS":
            return await self._parse_tms(content, runtime=runtime, progress_callback=progress_callback)

        indexed_text = FreightTextIndexer().index(raw_content or "")
        repair_records: list[dict[str, Any]] = []
        semantic_map, semantic_raw = await self.parse_semantic_map(
            indexed_text,
            runtime=runtime,
            progress_callback=progress_callback,
        )
        semantic_validator = FreightSemanticValidator(indexed_text)
        semantic_validator.validate_semantic_map(semantic_map)
        semantic_gate = validate_semantic_map_contract(indexed_text, semantic_map)
        patch_semantic_map_with_gate_result(semantic_map, semantic_gate)
        if should_call_ai_repair(semantic_gate):
            try:
                repaired_map, _, repair_raw = await self.repair_semantic_output(
                    indexed_text,
                    semantic_map,
                    [],
                    semantic_gate.issues,
                    runtime=runtime,
                    progress_callback=progress_callback,
                    stage_code="AI_SEMANTIC_REPAIR",
                    progress_percent=36,
                )
                repair_records.append({"stage": "semantic", **repair_raw})
                semantic_map = repaired_map
                semantic_validator = FreightSemanticValidator(indexed_text)
                semantic_validator.validate_semantic_map(semantic_map)
                semantic_gate = validate_semantic_map_contract(indexed_text, semantic_map)
                patch_semantic_map_with_gate_result(semantic_map, semantic_gate)
            except Exception as exc:  # noqa: BLE001
                semantic_map.setdefault("warnings", []).append(f"AI_SEMANTIC_REPAIR_FAILED: {exc}")
                patch_semantic_map_with_gate_result(semantic_map, semantic_gate)
        segments, detail_raws, detail_warnings, detail_metrics = await self.complete_candidate_fields(
            indexed_text,
            semantic_map,
            runtime=runtime,
            progress_callback=progress_callback,
        )
        semantic_warnings = semantic_validator.validate_segments(semantic_map, segments)
        detail_gate = apply_segment_evidence_gate(indexed_text, semantic_map, segments, formal_requires_tonnage=True)
        patch_semantic_map_with_gate_result(semantic_map, detail_gate)
        if should_call_ai_repair(detail_gate):
            try:
                repaired_map, repaired_segments, repair_raw = await self.repair_semantic_output(
                    indexed_text,
                    semantic_map,
                    segments,
                    detail_gate.issues,
                    runtime=runtime,
                    progress_callback=progress_callback,
                    stage_code="AI_DETAIL_REPAIR",
                    progress_percent=69,
                )
                repair_records.append({"stage": "detail", **repair_raw})
                semantic_map = repaired_map
                segments = repaired_segments
                semantic_validator = FreightSemanticValidator(indexed_text)
                semantic_validator.validate_semantic_map(semantic_map)
                semantic_warnings.extend(semantic_validator.validate_segments(semantic_map, segments))
                detail_gate = apply_segment_evidence_gate(indexed_text, semantic_map, segments, formal_requires_tonnage=True)
                patch_semantic_map_with_gate_result(semantic_map, detail_gate)
            except Exception as exc:  # noqa: BLE001
                semantic_map.setdefault("warnings", []).append(f"AI_DETAIL_REPAIR_FAILED: {exc}")
                for item in segments:
                    item["availability_status_code"] = "UNKNOWN"
                    item["needs_strong_review"] = True
                    _append_review_reason(item, f"AI 证据修复失败，需人工判断：{exc}")
        review_results, review_raw, review_failed_count, review_metrics = await self.review_risky_segments(
            indexed_text,
            semantic_map,
            segments,
            runtime=runtime,
            progress_callback=progress_callback,
        )
        if review_results:
            segments = self.merge_review_results(segments, review_results)
            semantic_warnings.extend(semantic_validator.validate_segments(semantic_map, segments))
            final_gate = apply_segment_evidence_gate(indexed_text, semantic_map, segments, formal_requires_tonnage=True)
            patch_semantic_map_with_gate_result(semantic_map, final_gate)

        accepted_segments, ignored_segments, quality_warnings = _prepare_segments(content, segments)
        warnings = [
            *(semantic_map.get("warnings") or []),
            *detail_warnings,
            *semantic_warnings,
            *quality_warnings,
        ]
        parsed_payload = {
            "segments": accepted_segments,
            "ignored_segments": ignored_segments,
            "context_blocks": semantic_map.get("context_blocks") or [],
            "context_notes": semantic_map.get("context_notes") or [],
            "warnings": warnings,
        }
        detail_models = [str(item.get("detail_model") or runtime["detail_model"]) for item in detail_metrics]
        used_models = [runtime["semantic_model"], *detail_models]
        if review_raw is not None:
            used_models.append(runtime["review_model"])
        if repair_records:
            used_models.append(runtime["review_model"])
        return QwenFreightParseResult(
            provider=runtime["provider"],
            model=" -> ".join(dict.fromkeys(used_models)),
            prompt_version=self.wechat_prompt_version,
            raw_response={
                "provider": runtime["provider"],
                "pipeline": "freight_ai_semantic_pipeline_v2",
                "semantic_map": semantic_raw,
                "detail": detail_raws,
                "review": review_raw,
                "repair": repair_records,
                "detail_metrics": detail_metrics,
                "review_metrics": review_metrics,
            },
            parsed_payload=parsed_payload,
            segments=accepted_segments,
            ignored_segments=ignored_segments,
            review_failed_count=review_failed_count,
            semantic_map=semantic_map,
            review_results=review_results,
        )
