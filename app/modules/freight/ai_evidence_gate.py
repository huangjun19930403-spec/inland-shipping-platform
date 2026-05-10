"""Evidence quality gate for WeChat freight AI parsing.

The gate does not split or infer WeChat freight text. It only validates the
AI-provided evidence contract, marks unsafe fields for review, and prepares an
AI repair payload when the output is structurally unsafe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


LOW_ROUTE_RECALL = "LOW_ROUTE_RECALL"
PROMPT_SCHEMA_DRIFT = "PROMPT_SCHEMA_DRIFT"
FIELD_EVIDENCE_MISSING = "FIELD_EVIDENCE_MISSING"
WEAK_INFERENCE_REVIEW_REQUIRED = "WEAK_INFERENCE_REVIEW_REQUIRED"
COMMODITY_SCOPE_UNSAFE = "COMMODITY_SCOPE_UNSAFE"
TONNAGE_SCOPE_UNSAFE = "TONNAGE_SCOPE_UNSAFE"
ROUTE_FIELD_UNSAFE = "ROUTE_FIELD_UNSAFE"
DUPLICATE_ROUTE_POINT = "DUPLICATE_ROUTE_POINT"
CONTEXT_BLOCK_UNSAFE = "CONTEXT_BLOCK_UNSAFE"
FORMAL_TONNAGE_MISSING = "FORMAL_TONNAGE_MISSING"
DIRTY_TONNAGE_DECISION = "DIRTY_TONNAGE_DECISION"
NON_FORMAL_ROUTE_NOT_READY = "NON_FORMAL_ROUTE_NOT_READY"
CROSS_CLUE_REVIEW_MERGE = "CROSS_CLUE_REVIEW_MERGE"
FIELD_EVIDENCE_CROSS_CLUE = "FIELD_EVIDENCE_CROSS_CLUE"
BATCH_ROUTE_COLLAPSE = "BATCH_ROUTE_COLLAPSE"

SAFE_SOURCE_TYPES = {"LOCAL_LINE", "EXPLICIT_SHARED"}
UNSAFE_SOURCE_TYPES = {"WEAK_INFERRED", "UNKNOWN"}
NON_FORMAL_ROUTE_INTENTS = {
    "SEEK_VESSEL",
    "VESSEL_INQUIRY",
    "ASK_SHIP",
    "FIND_SHIP",
    "INQUIRY_SHIP",
    "SHIP_DEMAND",
    "VESSEL_DEMAND",
}


class GateSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"


@dataclass(frozen=True)
class GateIssue:
    code: str
    severity: GateSeverity
    message: str
    clue_ref: str | None = None
    field_name: str | None = None
    line_refs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GateResult:
    issues: list[GateIssue]
    should_repair: bool
    should_review: bool

    @property
    def issue_codes(self) -> list[str]:
        return list(dict.fromkeys(issue.code for issue in self.issues))


def normalize_clue_ref(value: Any) -> str | None:
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


def normalize_line_ref(value: Any) -> str | None:
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


def as_clue_refs(value: Any) -> list[str]:
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
        normalized = normalize_clue_ref(item)
        if normalized:
            refs.append(normalized)
    return list(dict.fromkeys(refs))


def as_line_refs(value: Any) -> list[str]:
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
        normalized = normalize_line_ref(item)
        if normalized:
            refs.append(normalized)
    return list(dict.fromkeys(refs))


def compact_text(value: Any) -> str:
    return "".join(str(value or "").split())


def line_text(indexed_text: Any, line_refs: list[str]) -> str:
    line_map = getattr(indexed_text, "line_map", {}) or {}
    return "\n".join(str(line_map.get(ref, "")) for ref in line_refs)


def line_refs_exist(indexed_text: Any, line_refs: list[str]) -> bool:
    line_map = getattr(indexed_text, "line_map", {}) or {}
    return bool(line_refs) and all(ref in line_map for ref in line_refs)


def text_supported_by_lines(indexed_text: Any, text: Any, line_refs: list[str]) -> bool:
    value = compact_text(text)
    if not value:
        return True
    if not line_refs_exist(indexed_text, line_refs):
        return False
    return value in compact_text(line_text(indexed_text, line_refs))


def append_review_reason(segment: dict[str, Any], reason: str) -> None:
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


def ensure_ai_review_json(segment: dict[str, Any]) -> dict[str, Any]:
    review = segment.get("ai_review_json")
    if not isinstance(review, dict):
        review = {}
        segment["ai_review_json"] = review
    review.setdefault("field_quality_gate", {})
    return review


def add_segment_gate_issue(segment: dict[str, Any], issue: GateIssue) -> None:
    review = ensure_ai_review_json(segment)
    gate = review.setdefault("field_quality_gate", {})
    issues = gate.setdefault("issues", [])
    payload = {
        "code": issue.code,
        "severity": issue.severity.value,
        "message": issue.message,
        "field_name": issue.field_name,
        "line_refs": issue.line_refs,
    }
    if payload not in issues:
        issues.append(payload)
    if issue.severity in {GateSeverity.REVIEW_REQUIRED, GateSeverity.REPAIR_REQUIRED}:
        append_review_reason(segment, f"{issue.code}: {issue.message}")


def route_clues_from(semantic_map: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        clue
        for clue in (
            semantic_map.get("route_clues")
            or semantic_map.get("freight_clues")
            or semantic_map.get("clues")
            or []
        )
        if isinstance(clue, dict)
    ]


def context_notes_from(semantic_map: dict[str, Any]) -> list[dict[str, Any]]:
    return [note for note in semantic_map.get("context_notes") or [] if isinstance(note, dict)]


def context_blocks_from(semantic_map: dict[str, Any]) -> list[dict[str, Any]]:
    return [block for block in semantic_map.get("context_blocks") or [] if isinstance(block, dict)]


def route_clue_by_ref(semantic_map: dict[str, Any]) -> dict[str, dict[str, Any]]:
    clues: dict[str, dict[str, Any]] = {}
    for clue in route_clues_from(semantic_map):
        clue_ref = normalize_clue_ref(clue.get("clue_temp_id") or clue.get("segment_index"))
        if clue_ref:
            clues[clue_ref] = clue
    return clues


def is_non_formal_route(segment: dict[str, Any]) -> bool:
    code = str(segment.get("route_intent_code") or segment.get("intent_code") or "").strip().upper()
    return code in NON_FORMAL_ROUTE_INTENTS


def segment_requires_tonnage(segment: dict[str, Any], default_requires_tonnage: bool) -> bool:
    if str(segment.get("semantic_role_code") or "ROUTE").strip().upper() != "ROUTE":
        return False
    if segment.get("is_freight_candidate") is False or segment.get("drop_reason"):
        return False
    if is_non_formal_route(segment):
        return False
    return default_requires_tonnage


def field_evidence(segment: dict[str, Any], field_name: str) -> dict[str, Any] | None:
    field_map = segment.get("field_evidence")
    if not isinstance(field_map, dict):
        return None
    value = field_map.get(field_name)
    return value if isinstance(value, dict) else None


def field_source_type(segment: dict[str, Any], field_name: str) -> str:
    evidence = field_evidence(segment, field_name)
    if not evidence:
        return "UNKNOWN"
    return str(evidence.get("source_type_code") or evidence.get("source_type") or "UNKNOWN").upper()


def field_line_refs(segment: dict[str, Any], field_name: str) -> list[str]:
    evidence = field_evidence(segment, field_name)
    if not evidence:
        return as_line_refs(segment.get("line_refs"))
    return as_line_refs(evidence.get("line_refs") or evidence.get("evidence_line_refs"))


def safe_shared_line_refs_for_field(semantic_map: dict[str, Any], clue_ref: str | None, field_name: str) -> set[str]:
    if not clue_ref:
        return set()
    wanted_note_types = {
        "commodity_name": {"COMMODITY"},
        "raw_tonnage_text": {"TONNAGE"},
        "unit_price": {"PRICE"},
        "total_price": {"PRICE"},
    }.get(field_name, set())
    wanted_block_fields = {
        "commodity_name": {"shared_commodity_text"},
        "raw_tonnage_text": {"shared_tonnage_text"},
        "unit_price": {"shared_price_text"},
        "total_price": {"shared_price_text"},
    }.get(field_name, set())
    refs: set[str] = set()
    for note in context_notes_from(semantic_map):
        scope_type = str(note.get("scope_type_code") or note.get("scope_type") or "UNKNOWN").upper()
        if scope_type not in SAFE_SOURCE_TYPES:
            continue
        if clue_ref not in as_clue_refs(note.get("applies_to")):
            continue
        note_type = str(note.get("context_type_code") or note.get("type") or "OTHER").upper()
        if note_type in wanted_note_types:
            refs.update(as_line_refs(note.get("line_refs")))
    for block in context_blocks_from(semantic_map):
        scope_type = str(block.get("scope_type_code") or block.get("scope_type") or "UNKNOWN").upper()
        if scope_type not in SAFE_SOURCE_TYPES:
            continue
        if clue_ref not in as_clue_refs(block.get("route_clue_ids") or block.get("applies_to")):
            continue
        if any(block.get(field) for field in wanted_block_fields):
            refs.update(as_line_refs(block.get("line_refs")))
    return refs


def move_unsafe_value_to_suggestion(segment: dict[str, Any], field_name: str) -> None:
    value = segment.get(field_name)
    if value in (None, ""):
        return
    review = ensure_ai_review_json(segment)
    suggested = review.setdefault("suggested_fields", {})
    suggested.setdefault(
        field_name,
        {
            "value": value,
            "source_type_code": field_source_type(segment, field_name),
            "line_refs": field_line_refs(segment, field_name),
            "reason": "字段来自弱推断或未知来源，不能写入顶层候选字段。",
        },
    )
    segment[field_name] = None


def detect_schema_drift(semantic_map: dict[str, Any]) -> list[GateIssue]:
    issues: list[GateIssue] = []
    compat_flags = [str(item) for item in semantic_map.get("_schema_compat_flags") or []]
    if compat_flags:
        issues.append(
            GateIssue(
                code=PROMPT_SCHEMA_DRIFT,
                severity=GateSeverity.REVIEW_REQUIRED,
                message=f"AI 输出触发旧 schema 兼容：{','.join(compat_flags)}。",
            )
        )
    if "route_clues" not in semantic_map and ("freight_clues" in semantic_map or "clues" in semantic_map):
        issues.append(
            GateIssue(
                code=PROMPT_SCHEMA_DRIFT,
                severity=GateSeverity.REVIEW_REQUIRED,
                message="AI 使用旧线索字段 freight_clues/clues，提示词输出发生漂移。",
            )
        )
    for block in context_blocks_from(semantic_map):
        if "route_clue_ids" not in block and any(key in block for key in ("applies_to", "clue_ids", "segment_indices")):
            issues.append(
                GateIssue(
                    code=PROMPT_SCHEMA_DRIFT,
                    severity=GateSeverity.REVIEW_REQUIRED,
                    message="context_block 使用旧作用域字段，不能直接当作稳定输出。",
                )
            )
    return issues


def detect_low_route_recall(indexed_text: Any, semantic_map: dict[str, Any]) -> list[GateIssue]:
    line_map = getattr(indexed_text, "line_map", {}) or {}
    non_empty_lines = sum(1 for text in line_map.values() if str(text or "").strip())
    route_clues = route_clues_from(semantic_map)
    issues: list[GateIssue] = []
    if len(route_clues) <= 1 and non_empty_lines >= 6:
        issues.append(
            GateIssue(
                code=LOW_ROUTE_RECALL,
                severity=GateSeverity.REPAIR_REQUIRED,
                message="第一轮 route_clues 召回过低，疑似把多条连续货源合并为少量线索。",
            )
        )
    if len(route_clues) <= 2:
        max_refs = max((len(as_line_refs(clue.get("line_refs"))) for clue in route_clues), default=0)
        if max_refs >= 6:
            issues.append(
                GateIssue(
                    code=LOW_ROUTE_RECALL,
                    severity=GateSeverity.REPAIR_REQUIRED,
                    message="单条 route_clue 覆盖过多行，疑似混合多条货源。",
                )
            )
    return issues


def validate_semantic_map_contract(indexed_text: Any, semantic_map: dict[str, Any]) -> GateResult:
    issues: list[GateIssue] = []
    issues.extend(detect_schema_drift(semantic_map))
    issues.extend(detect_low_route_recall(indexed_text, semantic_map))

    for clue in route_clues_from(semantic_map):
        clue_ref = normalize_clue_ref(clue.get("clue_temp_id") or clue.get("segment_index"))
        line_refs = as_line_refs(clue.get("line_refs"))
        if not line_refs_exist(indexed_text, line_refs):
            issues.append(
                GateIssue(
                    code=FIELD_EVIDENCE_MISSING,
                    severity=GateSeverity.REPAIR_REQUIRED,
                    clue_ref=clue_ref,
                    field_name="route_clue.line_refs",
                    line_refs=line_refs,
                    message="route_clue 缺少有效 line_refs，无法追溯原文。",
                )
            )
        raw_text = clue.get("raw_text")
        if raw_text and not text_supported_by_lines(indexed_text, raw_text, line_refs):
            issues.append(
                GateIssue(
                    code=FIELD_EVIDENCE_MISSING,
                    severity=GateSeverity.REPAIR_REQUIRED,
                    clue_ref=clue_ref,
                    field_name="route_clue.raw_text",
                    line_refs=line_refs,
                    message="route_clue.raw_text 无法从 line_refs 对应原文追溯。",
                )
            )

    for note in context_notes_from(semantic_map):
        note_type = str(note.get("context_type_code") or "OTHER").upper()
        scope_type = str(note.get("scope_type_code") or note.get("scope_type") or "UNKNOWN").upper()
        applies_to = as_clue_refs(note.get("applies_to"))
        if note_type in {"COMMODITY", "TONNAGE", "PRICE"} and scope_type not in SAFE_SOURCE_TYPES:
            issues.append(
                GateIssue(
                    code=WEAK_INFERENCE_REVIEW_REQUIRED,
                    severity=GateSeverity.REVIEW_REQUIRED,
                    field_name=f"context_note.{note_type}",
                    line_refs=as_line_refs(note.get("line_refs")),
                    message=f"{note_type} 上下文不是 LOCAL_LINE/EXPLICIT_SHARED，不能自动继承给 {','.join(applies_to) or '未知线索'}。",
                )
            )

    for block in context_blocks_from(semantic_map):
        scope_type = str(block.get("scope_type_code") or block.get("scope_type") or "UNKNOWN").upper()
        route_ids = as_clue_refs(block.get("route_clue_ids") or block.get("applies_to"))
        risky_shared_fields = [
            field_name
            for field_name in ("shared_tonnage_text", "shared_commodity_text", "shared_price_text")
            if block.get(field_name)
        ]
        if risky_shared_fields and scope_type not in SAFE_SOURCE_TYPES:
            issues.append(
                GateIssue(
                    code=CONTEXT_BLOCK_UNSAFE,
                    severity=GateSeverity.REVIEW_REQUIRED,
                    field_name=",".join(risky_shared_fields),
                    line_refs=as_line_refs(block.get("line_refs")),
                    message=f"context_block 存在共享字段 {','.join(risky_shared_fields)}，但作用域不是显式共享，不能自动继承给 {','.join(route_ids)}。",
                )
            )

    should_repair = any(issue.severity == GateSeverity.REPAIR_REQUIRED for issue in issues)
    should_review = should_repair or any(issue.severity == GateSeverity.REVIEW_REQUIRED for issue in issues)
    return GateResult(issues=issues, should_repair=should_repair, should_review=should_review)


def validate_field_traceability(
    indexed_text: Any,
    segment: dict[str, Any],
    *,
    clue_ref: str | None,
    field_name: str,
    required: bool,
) -> list[GateIssue]:
    issues: list[GateIssue] = []
    value = segment.get(field_name)
    evidence = field_evidence(segment, field_name)
    if value in (None, ""):
        if required:
            issues.append(
                GateIssue(
                    code=FIELD_EVIDENCE_MISSING,
                    severity=GateSeverity.REVIEW_REQUIRED,
                    clue_ref=clue_ref,
                    field_name=field_name,
                    message=f"{field_name} 缺失，不能直接确认为完整货源。",
                )
            )
        return issues

    refs = field_line_refs(segment, field_name)
    source_type = field_source_type(segment, field_name)
    if evidence is None:
        issues.append(
            GateIssue(
                code=FIELD_EVIDENCE_MISSING,
                severity=GateSeverity.REVIEW_REQUIRED,
                clue_ref=clue_ref,
                field_name=field_name,
                line_refs=refs,
                message=f"{field_name} 缺少字段级 field_evidence。",
            )
        )
    elif source_type in UNSAFE_SOURCE_TYPES:
        issues.append(
            GateIssue(
                code=WEAK_INFERENCE_REVIEW_REQUIRED,
                severity=GateSeverity.REVIEW_REQUIRED,
                clue_ref=clue_ref,
                field_name=field_name,
                line_refs=refs,
                message=f"{field_name} 来源为 {source_type}，不能自动通过。",
            )
        )
    elif source_type in SAFE_SOURCE_TYPES and not text_supported_by_lines(indexed_text, value, refs):
        issues.append(
            GateIssue(
                code=FIELD_EVIDENCE_MISSING,
                severity=GateSeverity.REPAIR_REQUIRED,
                clue_ref=clue_ref,
                field_name=field_name,
                line_refs=refs,
                message=f"{field_name} 的值无法从证据行追溯，疑似 AI 脑补或作用域错误。",
            )
        )
    return issues


def validate_tonnage_decision(
    indexed_text: Any,
    segment: dict[str, Any],
    *,
    clue_ref: str | None,
    formal_requires_tonnage: bool,
) -> list[GateIssue]:
    issues: list[GateIssue] = []
    raw_tonnage = segment.get("raw_tonnage_text")
    decision = segment.get("tonnage_decision")
    if not isinstance(decision, dict):
        if raw_tonnage:
            issues.append(
                GateIssue(
                    code=DIRTY_TONNAGE_DECISION,
                    severity=GateSeverity.REVIEW_REQUIRED,
                    clue_ref=clue_ref,
                    field_name="tonnage_decision",
                    message="存在 raw_tonnage_text 但缺少 tonnage_decision，不能确认吨位归属。",
                )
            )
        elif formal_requires_tonnage:
            issues.append(
                GateIssue(
                    code=FORMAL_TONNAGE_MISSING,
                    severity=GateSeverity.REVIEW_REQUIRED,
                    clue_ref=clue_ref,
                    field_name="raw_tonnage_text",
                    message="正式货源缺少吨位，需人工复核。",
                )
            )
        return issues

    status = str(decision.get("status_code") or "UNKNOWN").upper()
    selected_text = decision.get("selected_text") or raw_tonnage
    source_type = str(
        decision.get("source_type_code") or decision.get("source_type") or field_source_type(segment, "raw_tonnage_text")
    ).upper()
    refs = as_line_refs(decision.get("line_refs") or decision.get("evidence_line_refs") or field_line_refs(segment, "raw_tonnage_text"))
    belongs = decision.get("belongs_to_current_segment")

    if formal_requires_tonnage and not selected_text:
        issues.append(
            GateIssue(
                code=FORMAL_TONNAGE_MISSING,
                severity=GateSeverity.REVIEW_REQUIRED,
                clue_ref=clue_ref,
                field_name="raw_tonnage_text",
                message="正式货源缺少吨位，需人工复核。",
            )
        )

    if selected_text and source_type not in SAFE_SOURCE_TYPES:
        issues.append(
            GateIssue(
                code=TONNAGE_SCOPE_UNSAFE,
                severity=GateSeverity.REVIEW_REQUIRED,
                clue_ref=clue_ref,
                field_name="raw_tonnage_text",
                line_refs=refs,
                message=f"吨位来源为 {source_type}，不能自动继承或确认。",
            )
        )

    if selected_text and belongs is not True:
        issues.append(
            GateIssue(
                code=TONNAGE_SCOPE_UNSAFE,
                severity=GateSeverity.REVIEW_REQUIRED,
                clue_ref=clue_ref,
                field_name="raw_tonnage_text",
                line_refs=refs,
                message="tonnage_decision 未明确 belongs_to_current_segment=True，不能确认吨位归属。",
            )
        )

    if selected_text and not text_supported_by_lines(indexed_text, selected_text, refs):
        issues.append(
            GateIssue(
                code=FIELD_EVIDENCE_MISSING,
                severity=GateSeverity.REPAIR_REQUIRED,
                clue_ref=clue_ref,
                field_name="raw_tonnage_text",
                line_refs=refs,
                message="吨位 selected_text 无法从证据行追溯。",
            )
        )

    if status != "PASS" and selected_text:
        issues.append(
            GateIssue(
                code=DIRTY_TONNAGE_DECISION,
                severity=GateSeverity.REVIEW_REQUIRED,
                clue_ref=clue_ref,
                field_name="tonnage_decision",
                line_refs=refs,
                message=f"tonnage_decision.status_code={status}，不能自动通过。",
            )
        )
    return issues


def validate_segment_identity(
    indexed_text: Any,
    semantic_map: dict[str, Any],
    segment: dict[str, Any],
    *,
    clue_ref: str | None,
) -> list[GateIssue]:
    issues: list[GateIssue] = []
    if not clue_ref:
        issues.append(
            GateIssue(
                code=CROSS_CLUE_REVIEW_MERGE,
                severity=GateSeverity.REVIEW_REQUIRED,
                message="候选缺少 clue_temp_id，无法证明属于哪条 route_clue。",
                field_name="clue_temp_id",
            )
        )
        return issues

    clue = route_clue_by_ref(semantic_map).get(clue_ref)
    if clue is None:
        issues.append(
            GateIssue(
                code=CROSS_CLUE_REVIEW_MERGE,
                severity=GateSeverity.REPAIR_REQUIRED,
                clue_ref=clue_ref,
                field_name="clue_temp_id",
                message=f"候选引用的 route_clue {clue_ref} 不存在，疑似复核结果串线。",
            )
        )
        return issues

    clue_line_refs = set(as_line_refs(clue.get("line_refs")))
    segment_line_refs = set(as_line_refs(segment.get("line_refs") or segment.get("line_refs_json")))
    if segment_line_refs and clue_line_refs and not segment_line_refs.issubset(clue_line_refs):
        issues.append(
            GateIssue(
                code=CROSS_CLUE_REVIEW_MERGE,
                severity=GateSeverity.REPAIR_REQUIRED,
                clue_ref=clue_ref,
                field_name="line_refs",
                line_refs=sorted(segment_line_refs),
                message="候选 line_refs 不属于其 route_clue，疑似强复核或修复阶段跨线索覆盖。",
            )
        )

    raw_text = segment.get("raw_text")
    refs = as_line_refs(segment.get("line_refs") or segment.get("line_refs_json"))
    if raw_text and not text_supported_by_lines(indexed_text, raw_text, refs):
        issues.append(
            GateIssue(
                code=CROSS_CLUE_REVIEW_MERGE,
                severity=GateSeverity.REPAIR_REQUIRED,
                clue_ref=clue_ref,
                field_name="raw_text",
                line_refs=refs,
                message="候选 raw_text 无法从自身 line_refs 追溯，疑似候选身份污染。",
            )
        )
    return issues


def validate_field_evidence_ownership(
    semantic_map: dict[str, Any],
    segment: dict[str, Any],
    *,
    clue_ref: str | None,
    field_name: str,
) -> list[GateIssue]:
    issues: list[GateIssue] = []
    evidence = field_evidence(segment, field_name)
    if evidence is None:
        return issues
    refs = set(field_line_refs(segment, field_name))
    if not refs:
        return issues
    clue = route_clue_by_ref(semantic_map).get(clue_ref or "")
    clue_refs = set(as_line_refs(clue.get("line_refs"))) if clue else set()
    source_type = field_source_type(segment, field_name)
    if source_type == "LOCAL_LINE":
        allowed_refs = clue_refs
    elif source_type == "EXPLICIT_SHARED":
        allowed_refs = clue_refs | safe_shared_line_refs_for_field(semantic_map, clue_ref, field_name)
    else:
        return issues
    if allowed_refs and not refs.issubset(allowed_refs):
        issues.append(
            GateIssue(
                code=FIELD_EVIDENCE_CROSS_CLUE,
                severity=GateSeverity.REPAIR_REQUIRED,
                clue_ref=clue_ref,
                field_name=field_name,
                line_refs=sorted(refs),
                message=f"{field_name} 的证据行不属于当前 route_clue 或显式共享上下文，疑似跨线索继承。",
            )
        )
    return issues


def validate_route_points(segment: dict[str, Any], *, clue_ref: str | None) -> list[GateIssue]:
    issues: list[GateIssue] = []
    origin = compact_text(segment.get("origin_text"))
    destination = compact_text(segment.get("destination_text"))
    if origin and destination and origin == destination:
        issues.append(
            GateIssue(
                code=DUPLICATE_ROUTE_POINT,
                severity=GateSeverity.REPAIR_REQUIRED,
                clue_ref=clue_ref,
                field_name="origin_text,destination_text",
                message="装货地和卸货地完全相同，疑似路线字段抽取错误。",
            )
        )
    route_tokens = ("至", "到", "->", "=>", "—", "——", "--", "一一")
    for field_name in ("origin_text", "destination_text"):
        value = str(segment.get(field_name) or "")
        if any(token in value for token in route_tokens) and len(value) >= 4:
            issues.append(
                GateIssue(
                    code=ROUTE_FIELD_UNSAFE,
                    severity=GateSeverity.REPAIR_REQUIRED,
                    clue_ref=clue_ref,
                    field_name=field_name,
                    message=f"{field_name} 像完整路线表达，不像单一地点字段。",
                )
            )
    return issues


def detect_batch_route_collapse(semantic_map: dict[str, Any], segments: list[dict[str, Any]]) -> list[GateIssue]:
    route_clues = route_clues_from(semantic_map)
    candidate_segments = [
        segment
        for segment in segments
        if isinstance(segment, dict)
        and segment.get("is_freight_candidate") is not False
        and not segment.get("drop_reason")
    ]
    if len(candidate_segments) < 4 or len(route_clues) < 4:
        return []

    clue_route_keys = {
        normalize_clue_ref(clue.get("clue_temp_id") or clue.get("segment_index")): (
            tuple(as_line_refs(clue.get("line_refs"))),
            compact_text(clue.get("raw_text")),
        )
        for clue in route_clues
        if isinstance(clue, dict)
    }
    distinct_clue_routes = {
        key
        for key in clue_route_keys.values()
        if key and (key[0] or key[1])
    }
    if len(distinct_clue_routes) < 4:
        return []

    def duplicate_count(values: list[Any]) -> tuple[Any, int]:
        counts: dict[Any, int] = {}
        for value in values:
            if not value:
                continue
            counts[value] = counts.get(value, 0) + 1
        if not counts:
            return None, 0
        return max(counts.items(), key=lambda item: item[1])

    raw_key, raw_count = duplicate_count([compact_text(segment.get("raw_text")) for segment in candidate_segments])
    line_key, line_count = duplicate_count(
        [tuple(as_line_refs(segment.get("line_refs") or segment.get("line_refs_json"))) for segment in candidate_segments]
    )
    route_key, route_count = duplicate_count(
        [
            (
                compact_text(segment.get("origin_text")),
                compact_text(segment.get("destination_text")),
                compact_text(segment.get("commodity_name")),
            )
            for segment in candidate_segments
        ]
    )
    threshold = max(3, int(len(candidate_segments) * 0.7))
    if max(raw_count, line_count, route_count) < threshold:
        return []
    duplicated = raw_key if raw_count >= line_count and raw_count >= route_count else line_key if line_count >= route_count else route_key
    return [
        GateIssue(
            code=BATCH_ROUTE_COLLAPSE,
            severity=GateSeverity.REPAIR_REQUIRED,
            message=(
                f"批次中 {max(raw_count, line_count, route_count)}/{len(candidate_segments)} 条候选异常共享同一路线证据 "
                f"{duplicated!r}，但语义图包含 {len(distinct_clue_routes)} 条不同路线，疑似整批候选被单条复核结果覆盖。"
            ),
        )
    ]


def apply_segment_evidence_gate(
    indexed_text: Any,
    semantic_map: dict[str, Any],
    segments: list[dict[str, Any]],
    *,
    formal_requires_tonnage: bool = True,
) -> GateResult:
    """Validate and mutate AI segments in-place."""

    issues: list[GateIssue] = []
    semantic_result = validate_semantic_map_contract(indexed_text, semantic_map)
    issues.extend(semantic_result.issues)
    batch_issues = detect_batch_route_collapse(semantic_map, segments)
    issues.extend(batch_issues)
    global_segment_issues = [
        issue
        for issue in [*semantic_result.issues, *batch_issues]
        if issue.severity in {GateSeverity.REVIEW_REQUIRED, GateSeverity.REPAIR_REQUIRED}
    ]

    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            continue
        clue_ref = normalize_clue_ref(segment.get("clue_temp_id") or segment.get("segment_index") or index)
        if clue_ref:
            segment["clue_temp_id"] = clue_ref

        item_requires_tonnage = segment_requires_tonnage(segment, formal_requires_tonnage)
        segment_issues: list[GateIssue] = [
            GateIssue(
                code=issue.code,
                severity=issue.severity,
                message=issue.message,
                clue_ref=clue_ref,
                field_name=issue.field_name,
                line_refs=issue.line_refs,
            )
            for issue in global_segment_issues
        ]
        segment_issues.extend(validate_segment_identity(indexed_text, semantic_map, segment, clue_ref=clue_ref))
        segment_issues.extend(validate_route_points(segment, clue_ref=clue_ref))
        segment_issues.extend(validate_field_traceability(indexed_text, segment, clue_ref=clue_ref, field_name="origin_text", required=True))
        segment_issues.extend(validate_field_traceability(indexed_text, segment, clue_ref=clue_ref, field_name="destination_text", required=True))
        segment_issues.extend(validate_field_traceability(indexed_text, segment, clue_ref=clue_ref, field_name="commodity_name", required=True))
        segment_issues.extend(
            validate_field_traceability(indexed_text, segment, clue_ref=clue_ref, field_name="raw_tonnage_text", required=item_requires_tonnage)
        )
        for field_name in ("origin_text", "destination_text", "commodity_name", "raw_tonnage_text"):
            segment_issues.extend(validate_field_evidence_ownership(semantic_map, segment, clue_ref=clue_ref, field_name=field_name))
        segment_issues.extend(
            validate_tonnage_decision(indexed_text, segment, clue_ref=clue_ref, formal_requires_tonnage=item_requires_tonnage)
        )

        commodity_evidence = field_evidence(segment, "commodity_name")
        commodity_source_type = field_source_type(segment, "commodity_name")
        if segment.get("commodity_name") and commodity_source_type in UNSAFE_SOURCE_TYPES:
            segment_issues.append(
                GateIssue(
                    code=COMMODITY_SCOPE_UNSAFE,
                    severity=GateSeverity.REVIEW_REQUIRED,
                    clue_ref=clue_ref,
                    field_name="commodity_name",
                    line_refs=field_line_refs(segment, "commodity_name"),
                    message="货品来自弱推断或未知来源，不能写入可直接确认候选。",
                )
            )
            if commodity_evidence is not None:
                move_unsafe_value_to_suggestion(segment, "commodity_name")

        tonnage_evidence = field_evidence(segment, "raw_tonnage_text")
        tonnage_source_type = field_source_type(segment, "raw_tonnage_text")
        if segment.get("raw_tonnage_text") and tonnage_source_type in UNSAFE_SOURCE_TYPES and tonnage_evidence is not None:
            move_unsafe_value_to_suggestion(segment, "raw_tonnage_text")
            segment["estimated_tonnage"] = None
            segment["min_tonnage"] = None
            segment["max_tonnage"] = None

        if is_non_formal_route(segment) and not (
            segment.get("raw_tonnage_text") or segment.get("estimated_tonnage") or segment.get("min_tonnage") or segment.get("max_tonnage")
        ):
            if str(segment.get("availability_status_code") or "").upper() == "READY":
                segment_issues.append(
                    GateIssue(
                        code=NON_FORMAL_ROUTE_NOT_READY,
                        severity=GateSeverity.REVIEW_REQUIRED,
                        clue_ref=clue_ref,
                        field_name="availability_status_code",
                        message="寻船/询船类线索缺少吨位时不能标记 READY 或一键确认。",
                    )
                )

        for issue in segment_issues:
            add_segment_gate_issue(segment, issue)
        issues.extend(segment_issues)

        if any(issue.severity in {GateSeverity.REVIEW_REQUIRED, GateSeverity.REPAIR_REQUIRED} for issue in segment_issues):
            if str(segment.get("availability_status_code") or "").upper() == "READY":
                segment["availability_status_code"] = "UNKNOWN"

    should_repair = any(issue.severity == GateSeverity.REPAIR_REQUIRED for issue in issues)
    should_review = should_repair or any(issue.severity == GateSeverity.REVIEW_REQUIRED for issue in issues)
    return GateResult(issues=issues, should_repair=should_repair, should_review=should_review)


def gate_summary_payload(result: GateResult) -> dict[str, Any]:
    return {
        "should_repair": result.should_repair,
        "should_review": result.should_review,
        "issue_codes": result.issue_codes,
        "issues": [
            {
                "code": issue.code,
                "severity": issue.severity.value,
                "message": issue.message,
                "clue_ref": issue.clue_ref,
                "field_name": issue.field_name,
                "line_refs": issue.line_refs,
            }
            for issue in result.issues
        ],
    }


def patch_semantic_map_with_gate_result(semantic_map: dict[str, Any], result: GateResult) -> None:
    semantic_map["quality_gate"] = gate_summary_payload(result)
    warnings = semantic_map.setdefault("warnings", [])
    if isinstance(warnings, list):
        for code in result.issue_codes:
            warning = f"QUALITY_GATE:{code}"
            if warning not in warnings:
                warnings.append(warning)


def should_call_ai_repair(result: GateResult) -> bool:
    return result.should_repair


def should_block_auto_confirm(result: GateResult) -> bool:
    return result.should_review


def evidence_clue_schema_hint() -> dict[str, Any]:
    return {
        "route_clues": [
            {
                "clue_temp_id": "C1",
                "context_block_id": "B1",
                "line_refs": ["L2"],
                "raw_text": "<必须能从 line_refs 原文追溯>",
                "route_type_code": "SINGLE_ROUTE | MULTI_DESTINATION_EXPANDED | INCOMPLETE_ROUTE",
                "route_intent_code": "FORMAL_FREIGHT | SEEK_VESSEL | VESSEL_INQUIRY | OTHER",
                "origin": {
                    "text": "<装货地原文或 null>",
                    "evidence_line_refs": ["L2"],
                    "evidence_text": "<支持装货地的原文片段>",
                    "confidence_score": 0.9,
                },
                "destination": {
                    "text": "<卸货地原文或 null>",
                    "evidence_line_refs": ["L2"],
                    "evidence_text": "<支持卸货地的原文片段>",
                    "confidence_score": 0.9,
                },
                "route_summary": "<只描述本条路线线索，不抽正式候选字段>",
                "shared_field_refs": ["N1"],
                "missing_field_codes": ["COMMODITY", "TONNAGE"],
                "warnings": [],
                "confidence_score": 0.86,
                "evidence": ["<路线线索证据原文>"],
            }
        ],
        "context_notes": [
            {
                "note_id": "N1",
                "note_index": 1,
                "context_type_code": "COMMODITY | TONNAGE | PRICE | CONTACT | LOADING | SETTLEMENT | REMARK | OTHER",
                "raw_text": "<上下文原文>",
                "line_refs": ["L3"],
                "applies_to": ["C1"],
                "scope_type_code": "EXPLICIT_SHARED | LOCAL_LINE | WEAK_INFERRED | UNKNOWN",
                "scope_reason": "<为什么该上下文适用于这些 route_clues>",
                "evidence_text": "<支持该作用域的原文>",
                "evidence": ["<上下文证据原文>"],
                "confidence_score": 0.86,
            }
        ],
        "context_blocks": [
            {
                "context_block_id": "B1",
                "route_clue_ids": ["C1"],
                "line_refs": ["L1", "L2", "L3"],
                "raw_text": "<该公共上下文块覆盖的连续原文片段>",
                "context_summary": "<公共上下文摘要>",
                "scope_type_code": "EXPLICIT_SHARED | LOCAL_LINE | WEAK_INFERRED | UNKNOWN",
                "scope_reason": "<为什么该块没有跨联系人、跨公告、跨独立货源>",
                "shared_contact_phone": "<公共联系电话或 null>",
                "shared_tonnage_text": "<公共吨位原文或 null>",
                "shared_commodity_text": "<公共货品原文或 null>",
                "shared_price_text": "<公共价格原文或 null>",
                "shared_loading_remark": "<公共装卸备注或 null>",
                "evidence": ["<上下文证据原文>"],
                "warnings": [],
                "confidence_score": 0.86,
            }
        ],
        "ignored_notes": [{"raw_text": "<非路线片段>", "line_refs": ["L1"], "drop_reason": "<忽略原因>"}],
        "warnings": [
            "一行多目的地必须展开为多条 route_clues；不能把多个目的地塞进同一个 destination 字段",
            "缺货品可以保留 route_clue，但 commodity 不能脑补为 PASS",
            "吨位、货品、价格只有 EXPLICIT_SHARED 或 LOCAL_LINE 才能自动继承",
        ],
    }


def evidence_detail_schema_hint() -> dict[str, Any]:
    return {
        "segments": [
            {
                "clue_temp_id": "C1",
                "segment_uid": "C1:S1",
                "segment_index": 1,
                "context_block_id": "B1",
                "semantic_role_code": "ROUTE",
                "route_intent_code": "FORMAL_FREIGHT | SEEK_VESSEL | VESSEL_INQUIRY | OTHER",
                "line_refs": ["L2"],
                "raw_text": "<必须来自第一轮 route_clue.raw_text>",
                "field_evidence": {
                    "origin_text": {
                        "value": "<装货地原文>",
                        "source_type_code": "LOCAL_LINE",
                        "line_refs": ["L2"],
                        "evidence_text": "<原文证据>",
                        "confidence_score": 0.9,
                    },
                    "destination_text": {
                        "value": "<卸货地原文>",
                        "source_type_code": "LOCAL_LINE",
                        "line_refs": ["L2"],
                        "evidence_text": "<原文证据>",
                        "confidence_score": 0.9,
                    },
                    "commodity_name": {
                        "value": "<货品原文或 null>",
                        "source_type_code": "LOCAL_LINE | EXPLICIT_SHARED | WEAK_INFERRED | UNKNOWN",
                        "context_note_id": "N1",
                        "line_refs": ["L2"],
                        "evidence_text": "<原文证据>",
                        "confidence_score": 0.9,
                    },
                    "raw_tonnage_text": {
                        "value": "<吨位原文或 null>",
                        "source_type_code": "LOCAL_LINE | EXPLICIT_SHARED | WEAK_INFERRED | UNKNOWN",
                        "context_note_id": "N2",
                        "line_refs": ["L3"],
                        "evidence_text": "<原文证据>",
                        "confidence_score": 0.9,
                    },
                },
                "cargo_title": "<装货地 至 卸货地 货品；不能用缺失字段脑补>",
                "cargo_description": "<只写原文已有或明确共享的信息>",
                "commodity_name": "<仅当 LOCAL_LINE 或 EXPLICIT_SHARED 时直接填；WEAK_INFERRED/UNKNOWN 放 ai_review_json.suggested_fields>",
                "origin_text": "<装货地原文>",
                "destination_text": "<卸货地原文>",
                "raw_tonnage_text": "<吨位原文或 null>",
                "estimated_tonnage": None,
                "min_tonnage": None,
                "max_tonnage": None,
                "quantity_description": "<船长、船数、拖队、档期等非吨位信息>",
                "vessel_description": "<船型、拖队、米数等非吨位信息>",
                "tonnage_decision": {
                    "status_code": "PASS | REVIEW_REQUIRED | NOT_APPLICABLE",
                    "selected_text": "<本条货源自己的吨位原文或 null>",
                    "source_type_code": "LOCAL_LINE | EXPLICIT_SHARED | WEAK_INFERRED | UNKNOWN",
                    "line_refs": ["L3"],
                    "evidence_text": "<原文证据>",
                    "belongs_to_current_segment": True,
                    "reason": "<结论证据>",
                },
                "tonnage_candidates": [
                    {
                        "text": "<候选吨位原文>",
                        "line_ref": "L3",
                        "source_type_code": "LOCAL_LINE | EXPLICIT_SHARED | WEAK_INFERRED | UNKNOWN",
                        "belongs_to_current_segment": True,
                        "reason": "<为什么属于或不属于本条>",
                    }
                ],
                "availability_status_code": "READY | DEFERRED | FULL | UNKNOWN",
                "ai_review_status_code": "PASS | REVIEW_REQUIRED",
                "ai_review_reason": "<缺字段、弱推断、共享范围不清时必须填写>",
                "ai_review_json": {
                    "summary": "<字段完整性和业务确认建议>",
                    "suggested_fields": {},
                    "field_evidence_required": True,
                },
                "confidence_score": 0.86,
                "evidence": ["<路线证据>", "<货品证据>", "<吨位证据>"],
                "needs_strong_review": False,
            }
        ],
        "warnings": [
            "不得从全文自由联想字段；只能使用第一轮 route_clues/context_notes 的证据",
            "WEAK_INFERRED/UNKNOWN 字段必须 REVIEW_REQUIRED，且不能写入顶层字段用于自动确认",
            "正式货源没有吨位时必须 REVIEW_REQUIRED；寻船/询船类可以无吨位但不能 READY",
        ],
    }


def repair_prompt_payload(
    indexed_text: Any,
    semantic_map: dict[str, Any],
    segments: list[dict[str, Any]],
    issues: list[GateIssue],
) -> dict[str, Any]:
    return {
        "task": "REPAIR_WECHAT_FREIGHT_SEMANTIC_OUTPUT",
        "rules": [
            "只根据 indexed_text、semantic_map、segments 和 issues 修复，不得编造原文没有的信息。",
            "必须保留每个输入 segment 的 segment_uid；如拆分新增 segment，segment_uid 使用原 clue_temp_id 下新的 S 序号。",
            "一行多目的地必须展开 route_clues 或 segments。",
            "货品、吨位、价格、联系人只有 LOCAL_LINE 或 EXPLICIT_SHARED 才能自动继承。",
            "WEAK_INFERRED、UNKNOWN 或证据不完整字段必须 REVIEW_REQUIRED，且不要写入可直接确认的顶层字段。",
            "origin_text 与 destination_text 相同必须修复；不能修复则 REVIEW_REQUIRED。",
            "正式货源缺吨位必须 REVIEW_REQUIRED；寻船/询船可无吨位但 availability_status_code 不得 READY。",
        ],
        "expected_schema": {
            "semantic_map": evidence_clue_schema_hint(),
            "segments": evidence_detail_schema_hint()["segments"],
            "repair_summary": "<修复了哪些问题>",
        },
        "indexed_text": getattr(indexed_text, "indexed_text", ""),
        "semantic_map": semantic_map,
        "segments": segments,
        "issues": [
            {
                "code": issue.code,
                "severity": issue.severity.value,
                "message": issue.message,
                "clue_ref": issue.clue_ref,
                "field_name": issue.field_name,
                "line_refs": issue.line_refs,
            }
            for issue in issues
        ],
    }
