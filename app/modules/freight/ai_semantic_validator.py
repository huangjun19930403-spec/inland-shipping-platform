"""Traceability validation for freight AI semantic outputs."""

from __future__ import annotations

from typing import Any

from app.modules.freight.ai_text_index import FreightIndexedText


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


class FreightSemanticValidator:
    """Validate AI line references against indexed source text."""

    def __init__(self, indexed_text: FreightIndexedText) -> None:
        self.indexed_text = indexed_text

    def validate_semantic_map(self, semantic_map: dict[str, Any]) -> list[str]:
        warnings: list[str] = []
        for clue in semantic_map.get("route_clues") or semantic_map.get("freight_clues") or semantic_map.get("clues") or []:
            if not isinstance(clue, dict):
                continue
            warnings.extend(self._validate_traceable_item(clue, label=f"clue {clue.get('clue_temp_id') or clue.get('segment_index') or '-'}"))
        for block in semantic_map.get("context_blocks") or []:
            if not isinstance(block, dict):
                continue
            warnings.extend(self._validate_traceable_item(block, label=f"context_block {block.get('context_block_id') or '-'}"))
        for note in [*(semantic_map.get("context_notes") or []), *(semantic_map.get("ignored_notes") or [])]:
            if not isinstance(note, dict):
                continue
            warnings.extend(self._validate_traceable_item(note, label=f"note {note.get('note_index') or '-'}"))
        if warnings:
            semantic_map.setdefault("warnings", []).extend(warnings)
        return warnings

    def validate_segments(self, semantic_map: dict[str, Any], segments: list[dict[str, Any]]) -> list[str]:
        allowed_ids = {
            str(clue.get("clue_temp_id") or clue.get("segment_index"))
            for clue in semantic_map.get("route_clues") or semantic_map.get("freight_clues") or semantic_map.get("clues") or []
            if isinstance(clue, dict) and (clue.get("clue_temp_id") not in (None, "") or clue.get("segment_index") not in (None, ""))
        }
        warnings: list[str] = []
        for index, segment in enumerate(segments, start=1):
            label = f"segment {segment.get('clue_temp_id') or segment.get('segment_index') or index}"
            clue_temp_id = segment.get("clue_temp_id")
            if clue_temp_id not in (None, "") and allowed_ids and str(clue_temp_id) not in allowed_ids:
                warning = f"{label}: clue_temp_id 不存在于第一轮语义地图"
                _append_warning(segment, warning)
                warnings.append(warning)
            warnings.extend(self._validate_traceable_item(segment, label=label))
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
