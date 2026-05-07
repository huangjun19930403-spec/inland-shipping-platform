"""Traceability and business-scope validation for freight AI outputs."""

from __future__ import annotations

import re
from typing import Any

from app.modules.freight.ai_text_index import FreightIndexedText

CONTACT_SCOPE_CONFLICT = "CONTACT_SCOPE_CONFLICT"
CONTEXT_BLOCK_CONFLICT = "CONTEXT_BLOCK_CONFLICT"
MULTI_CONTACT_BLOCK = "MULTI_CONTACT_BLOCK"
LOW_ROUTE_RECALL = "LOW_ROUTE_RECALL"


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
    return refs


def _compact_text(value: Any) -> str:
    return "".join(str(value or "").split())


def _append_warning(item: dict[str, Any], warning: str) -> None:
    warnings = item.setdefault("warnings", [])
    if isinstance(warnings, list) and warning not in warnings:
        warnings.append(warning)
    item["needs_strong_review"] = True
    current = str(item.get("manual_review_reason") or "").strip()
    item["manual_review_reason"] = warning if not current else current if warning in current else f"{current}；{warning}"


def _append_risk(item: dict[str, Any], risk_code: str, warning: str) -> None:
    codes = item.setdefault("scope_risk_codes", [])
    if isinstance(codes, list) and risk_code not in codes:
        codes.append(risk_code)
    _append_warning(item, f"{risk_code}: {warning}")


def _line_no(line_ref: str) -> int | None:
    normalized = _normalize_line_ref(line_ref)
    if normalized and normalized.startswith("L") and normalized[1:].isdigit():
        return int(normalized[1:])
    return None


def _line_span(line_refs: list[str]) -> tuple[int, int] | None:
    numbers = [_line_no(ref) for ref in line_refs]
    compact = [item for item in numbers if item is not None]
    if not compact:
        return None
    return min(compact), max(compact)


_PHONE_RE = re.compile(r"(?<!\d)(?:1[3-9]\d{9}|\d{7,12})(?!\d)")


def _phones_in_text(value: Any) -> set[str]:
    return {item for item in _PHONE_RE.findall(str(value or "")) if item}


class FreightSemanticValidator:
    """Validate AI line references and contact/context scope."""

    def __init__(self, indexed_text: FreightIndexedText) -> None:
        self.indexed_text = indexed_text
        self._contact_anchor_refs = self._detect_contact_anchor_refs()
        self._announcement_boundary_refs = {
            line_ref
            for line_ref, text in self.indexed_text.line_map.items()
            if "@所有人" in str(text or "") or "@所有" in str(text or "")
        }

    def validate_semantic_map(self, semantic_map: dict[str, Any]) -> list[str]:
        warnings: list[str] = []
        route_clues = semantic_map.get("route_clues") or semantic_map.get("freight_clues") or semantic_map.get("clues") or []
        normalized_clues: list[dict[str, Any]] = []
        for index, clue in enumerate(route_clues, start=1):
            if not isinstance(clue, dict):
                continue
            clue["clue_temp_id"] = _normalize_clue_ref(clue.get("clue_temp_id") or index) or f"C{index}"
            normalized_clues.append(clue)
            warnings.extend(self._validate_traceable_item(clue, label=f"clue {clue.get('clue_temp_id') or clue.get('segment_index') or '-'}"))
        semantic_map["route_clues"] = normalized_clues
        clue_by_id = {str(clue.get("clue_temp_id")): clue for clue in normalized_clues}

        if self._looks_like_low_route_recall(normalized_clues):
            warning = "第一轮 route_clues 召回过低，疑似把多条连续货源合并为少量线索"
            semantic_map.setdefault("scope_risk_codes", [])
            if LOW_ROUTE_RECALL not in semantic_map["scope_risk_codes"]:
                semantic_map["scope_risk_codes"].append(LOW_ROUTE_RECALL)
            warnings.append(f"{LOW_ROUTE_RECALL}: {warning}")
            for clue in normalized_clues:
                _append_risk(clue, LOW_ROUTE_RECALL, warning)

        for block in semantic_map.get("context_blocks") or []:
            if not isinstance(block, dict):
                continue
            block["route_clue_ids"] = _as_clue_refs(block.get("route_clue_ids") or block.get("applies_to") or block.get("clue_ids") or [])
            warnings.extend(self._validate_traceable_item(block, label=f"context_block {block.get('context_block_id') or '-'}"))
            warnings.extend(self._validate_context_block_scope(block, clue_by_id))
        for note in [*(semantic_map.get("context_notes") or []), *(semantic_map.get("ignored_notes") or [])]:
            if not isinstance(note, dict):
                continue
            if "applies_to" in note:
                note["applies_to"] = _as_clue_refs(note.get("applies_to"))
            warnings.extend(self._validate_traceable_item(note, label=f"note {note.get('note_index') or '-'}"))
        if warnings:
            semantic_map.setdefault("warnings", []).extend(warnings)
        return warnings

    def validate_segments(self, semantic_map: dict[str, Any], segments: list[dict[str, Any]]) -> list[str]:
        route_clues = [
            clue
            for clue in semantic_map.get("route_clues") or semantic_map.get("freight_clues") or semantic_map.get("clues") or []
            if isinstance(clue, dict)
        ]
        allowed_ids = {
            clue_ref
            for clue in route_clues
            for clue_ref in [_normalize_clue_ref(clue.get("clue_temp_id") or clue.get("segment_index"))]
            if clue_ref
        }
        clue_by_id = {
            clue_ref: clue
            for clue in route_clues
            for clue_ref in [_normalize_clue_ref(clue.get("clue_temp_id") or clue.get("segment_index"))]
            if clue_ref
        }
        warnings: list[str] = []
        for index, segment in enumerate(segments, start=1):
            label = f"segment {segment.get('clue_temp_id') or segment.get('segment_index') or index}"
            clue_ref = _normalize_clue_ref(segment.get("clue_temp_id") or segment.get("segment_index") or index)
            if clue_ref:
                segment["clue_temp_id"] = clue_ref
            if clue_ref not in (None, "") and allowed_ids and clue_ref not in allowed_ids:
                warning = f"{label}: clue_temp_id 不存在于第一轮语义地图"
                _append_warning(segment, warning)
                warnings.append(warning)
            warnings.extend(self._validate_traceable_item(segment, label=label))
            warnings.extend(self._validate_segment_contact_scope(segment, semantic_map, clue_by_id))
        if warnings:
            semantic_map.setdefault("warnings", []).extend(warnings)
        return warnings

    def _validate_traceable_item(self, item: dict[str, Any], *, label: str) -> list[str]:
        warnings: list[str] = []
        refs = _as_line_refs(item.get("line_refs") or item.get("line_refs_json"))
        item["line_refs"] = refs
        missing_refs = [line_ref for line_ref in refs if line_ref not in self.indexed_text.line_map]
        if not refs:
            warning = f"{label}: 缺少 line_refs"
            _append_warning(item, warning)
            warnings.append(warning)
        elif missing_refs:
            warning = f"{label}: line_refs 不存在 {','.join(missing_refs)}"
            _append_warning(item, warning)
            warnings.append(warning)

        raw_text = str(item.get("raw_text") or "").strip()
        if raw_text and refs and not missing_refs:
            referenced_text = "\n".join(self.indexed_text.line_map[line_ref] for line_ref in refs)
            if _compact_text(raw_text) not in _compact_text(referenced_text):
                warning = f"{label}: raw_text 无法从 line_refs 对应原文追溯"
                _append_warning(item, warning)
                warnings.append(warning)
        return warnings

    def _detect_contact_anchor_refs(self) -> set[str]:
        anchors: set[str] = set()
        for line_ref, text in self.indexed_text.line_map.items():
            if _phones_in_text(text):
                anchors.add(line_ref)
        return anchors

    def _looks_like_low_route_recall(self, route_clues: list[dict[str, Any]]) -> bool:
        non_empty_lines = sum(1 for text in self.indexed_text.line_map.values() if str(text or "").strip())
        if len(route_clues) <= 1 and non_empty_lines >= 6:
            return True
        if len(route_clues) <= 2:
            max_refs = max((len(_as_line_refs(clue.get("line_refs"))) for clue in route_clues), default=0)
            return max_refs >= 6
        return False

    def _validate_context_block_scope(self, block: dict[str, Any], clue_by_id: dict[str, dict[str, Any]]) -> list[str]:
        warnings: list[str] = []
        block_label = f"context_block {block.get('context_block_id') or '-'}"
        route_clue_ids = _as_clue_refs(block.get("route_clue_ids"))
        if route_clue_ids:
            missing = [clue_ref for clue_ref in route_clue_ids if clue_ref not in clue_by_id]
            if missing:
                warning = f"{block_label}: route_clue_ids 引用了不存在的线索 {','.join(missing)}"
                _append_risk(block, CONTEXT_BLOCK_CONFLICT, warning)
                warnings.append(f"{CONTEXT_BLOCK_CONFLICT}: {warning}")

        collected_refs = set(_as_line_refs(block.get("line_refs") or block.get("line_refs_json")))
        for clue_ref in route_clue_ids:
            collected_refs.update(_as_line_refs((clue_by_id.get(clue_ref) or {}).get("line_refs")))
        refs = sorted(collected_refs, key=lambda item: _line_no(item) or 0)
        span = _line_span(refs)
        if span:
            start, end = span
            contact_anchors = [
                line_ref
                for line_ref in self._contact_anchor_refs
                if (line_no := _line_no(line_ref)) is not None and start <= line_no <= end
            ]
            if len(contact_anchors) > 1:
                warning = f"{block_label}: 上下文块跨越多个联系人锚点 {','.join(sorted(contact_anchors))}"
                _append_risk(block, MULTI_CONTACT_BLOCK, warning)
                warnings.append(f"{MULTI_CONTACT_BLOCK}: {warning}")
            boundary_refs = [
                line_ref
                for line_ref in self._announcement_boundary_refs
                if (line_no := _line_no(line_ref)) is not None and start <= line_no <= end
            ]
            if boundary_refs:
                warning = f"{block_label}: 上下文块跨越公告边界 {','.join(sorted(boundary_refs))}"
                _append_risk(block, CONTEXT_BLOCK_CONFLICT, warning)
                warnings.append(f"{CONTEXT_BLOCK_CONFLICT}: {warning}")

        block_phones = _phones_in_text(block.get("raw_text")) | _phones_in_text(block.get("shared_contact_phone"))
        for item in block.get("evidence") or []:
            block_phones.update(_phones_in_text(item))
        if len(block_phones) > 1:
            warning = f"{block_label}: 公共联系人字段包含多个联系电话"
            _append_risk(block, MULTI_CONTACT_BLOCK, warning)
            warnings.append(f"{MULTI_CONTACT_BLOCK}: {warning}")
        return warnings

    def _validate_segment_contact_scope(
        self,
        segment: dict[str, Any],
        semantic_map: dict[str, Any],
        clue_by_id: dict[str, dict[str, Any]],
    ) -> list[str]:
        contact_phone = str(segment.get("contact_phone") or "").strip()
        if not contact_phone:
            return []
        clue_ref = _normalize_clue_ref(segment.get("clue_temp_id") or segment.get("segment_index"))
        allowed_refs = set(_as_line_refs(segment.get("line_refs") or segment.get("line_refs_json")))
        if clue_ref and clue_ref in clue_by_id:
            allowed_refs.update(_as_line_refs(clue_by_id[clue_ref].get("line_refs")))

        context_block_id = str(segment.get("context_block_id") or "").strip()
        related_blocks: list[dict[str, Any]] = []
        own_support_parts = [self.indexed_text.line_map.get(ref, "") for ref in sorted(allowed_refs, key=lambda item: _line_no(item) or 0)]
        own_support_parts.extend(str(segment.get(key) or "") for key in ("raw_text", "context_summary"))
        own_support_parts.extend(str(item or "") for item in segment.get("evidence") or [])
        contact_supported_by_own_evidence = contact_phone in "\n".join(own_support_parts)
        for block in semantic_map.get("context_blocks") or []:
            if not isinstance(block, dict):
                continue
            block_refs = _as_clue_refs(block.get("route_clue_ids"))
            if clue_ref in block_refs or (context_block_id and str(block.get("context_block_id") or "") == context_block_id):
                related_blocks.append(block)
                allowed_refs.update(_as_line_refs(block.get("line_refs") or block.get("line_refs_json")))

        for note in semantic_map.get("context_notes") or []:
            if not isinstance(note, dict):
                continue
            if clue_ref and clue_ref in _as_clue_refs(note.get("applies_to")):
                allowed_refs.update(_as_line_refs(note.get("line_refs") or note.get("line_refs_json")))

        support_parts = [self.indexed_text.line_map.get(ref, "") for ref in sorted(allowed_refs, key=lambda item: _line_no(item) or 0)]
        support_parts.extend(str(segment.get(key) or "") for key in ("raw_text", "context_summary"))
        support_parts.extend(str(item or "") for item in segment.get("evidence") or [])
        for block in related_blocks:
            support_parts.extend(
                str(block.get(key) or "")
                for key in ("raw_text", "context_summary", "shared_contact_name", "shared_contact_phone", "scope_reason")
            )
            support_parts.extend(str(item or "") for item in block.get("evidence") or [])
            if set(block.get("scope_risk_codes") or []) and not contact_supported_by_own_evidence:
                warning = "候选联系人所在 context_block 已标记作用域风险，不能直接继承联系人"
                _append_risk(segment, CONTACT_SCOPE_CONFLICT, warning)
                segment["contact_phone"] = None
                segment["contact_name"] = None
                segment["contact_wechat"] = None
                return [f"{CONTACT_SCOPE_CONFLICT}: {warning}"]

        support_text = "\n".join(support_parts)
        if contact_phone not in support_text:
            warning = "候选联系人电话不在该候选 evidence lines 或关联上下文证据内"
            _append_risk(segment, CONTACT_SCOPE_CONFLICT, warning)
            segment["contact_phone"] = None
            segment["contact_name"] = None
            segment["contact_wechat"] = None
            return [f"{CONTACT_SCOPE_CONFLICT}: {warning}"]
        return []
