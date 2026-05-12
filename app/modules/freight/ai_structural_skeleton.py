"""Deterministic freight text skeletons and evidence support helpers.

The skeleton builder is intentionally conservative: it only creates route
units from text that contains an explicit route connector or a route-like
backhaul phrase. AI still decides semantic completeness, but the local skeleton
prevents silent recall loss and provides cheap fallbacks when model stages time
out.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from app.modules.freight.ai_text_index import FreightIndexedText

AI_SEGMENT_MISSING = "AI_SEGMENT_MISSING"
LOCAL_SKELETON_FALLBACK = "LOCAL_SKELETON_FALLBACK"
MULTI_POINT_EXPANDED = "MULTI_POINT_EXPANDED"
ROUTE_COVERAGE_GAP = "ROUTE_COVERAGE_GAP"

_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_ROUTE_RE = re.compile(r"(.+?)(?:——+|—+|-{2,}|一{1,3}|～～+|~~+|～+|->|=>|到|至)(.+)")
_BOUNDARY_RE = re.compile(r"^\s*(?:@所有人|@所有|[.。…—\-_=～~*＊·、，,\s]{4,})\s*$")
_MULTI_SPLIT_RE = re.compile(r"[\/／、;；]+")
_COMMA_SPLIT_RE = re.compile(r"[,，]+")
_COMMODITY_WORDS = (
    "沙子",
    "石子",
    "石粉",
    "沙石",
    "砂石",
    "煤炭",
    "煤矸石",
    "矸石",
    "煤渣",
    "小麦",
    "大麦",
    "钢材",
    "板坯",
    "冷卷",
    "热卷",
    "水渣",
    "机制砂",
    "砖",
    "货源",
)
_NON_DEST_WORDS = (
    "装卸",
    "现金",
    "高价",
    "运价",
    "运费",
    "单价",
    "定金",
    "电话",
    "联系",
    "吨",
    "左右",
    "以内",
    "以上",
    "船",
    "随船",
    "滚动",
    "装",
)


class EvidenceSupportMatcher:
    """Normalized evidence matching used by both gates and final cleanup."""

    @staticmethod
    def normalize(value: Any) -> str:
        text = unicodedata.normalize("NFKC", str(value or ""))
        replacements = {
            "﹣": "-",
            "－": "-",
            "–": "-",
            "—": "-",
            "一一一": "-",
            "一一": "-",
            "～": "~",
            "〜": "~",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        return "".join(text.split()).lower()

    @classmethod
    def supports(cls, value: Any, support_text: Any) -> bool:
        needle = cls.normalize(value)
        if not needle:
            return True
        haystack = cls.normalize(support_text)
        if needle in haystack:
            return True
        try:
            number = float(str(value).strip())
        except (TypeError, ValueError):
            return False
        number_text = str(int(number)) if number.is_integer() else str(number).rstrip("0").rstrip(".")
        return number_text and number_text in haystack


@dataclass
class FreightParseBudget:
    total_seconds: float = 300.0
    semantic_seconds: float = 60.0
    detail_seconds: float = 150.0
    detail_chunk_seconds: float = 90.0
    repair_seconds: float = 30.0
    review_seconds: float = 60.0
    review_chunk_seconds: float = 45.0
    started_monotonic: float = field(default_factory=time.monotonic)

    def remaining(self) -> float:
        return max(1.0, self.total_seconds - (time.monotonic() - self.started_monotonic))

    def timeout_for(self, stage_code: str) -> float:
        stage = stage_code.upper()
        if "SEMANTIC" in stage:
            budget = self.semantic_seconds
        elif "DETAIL" in stage and "REPAIR" not in stage:
            budget = self.detail_chunk_seconds
        elif "REPAIR" in stage:
            budget = self.repair_seconds
        elif "REVIEW" in stage:
            budget = self.review_chunk_seconds
        else:
            budget = self.remaining()
        return max(1.0, min(budget, self.remaining()))

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_seconds": self.total_seconds,
            "semantic_seconds": self.semantic_seconds,
            "detail_seconds": self.detail_seconds,
            "detail_chunk_seconds": self.detail_chunk_seconds,
            "repair_seconds": self.repair_seconds,
            "review_seconds": self.review_seconds,
            "review_chunk_seconds": self.review_chunk_seconds,
            "remaining_seconds": round(self.remaining(), 3),
        }


@dataclass(frozen=True)
class FreightSkeletonResult:
    skeleton_units: list[dict[str, Any]]
    context_anchors: list[dict[str, Any]]
    context_blocks: list[dict[str, Any]]
    context_notes: list[dict[str, Any]]
    coverage_audit: dict[str, Any]
    expansion_audit: dict[str, Any]
    context_scope_audit: dict[str, Any]

    def as_semantic_payload(self) -> dict[str, Any]:
        return {
            "skeleton_units": self.skeleton_units,
            "context_anchors": self.context_anchors,
            "coverage_audit": self.coverage_audit,
            "expansion_audit": self.expansion_audit,
            "context_scope_audit": self.context_scope_audit,
        }


def _compact(value: Any) -> str:
    return EvidenceSupportMatcher.normalize(value)


def _line_no(line_ref: str) -> int:
    text = str(line_ref or "").upper()
    return int(text[1:]) if text.startswith("L") and text[1:].isdigit() else 10**9


def _clean_route_side(value: str) -> str:
    text = re.sub(r"^[\s⭐️🌹💥☎电话联系:：,，。]+", "", value or "")
    text = re.sub(r"^\d{1,2}(?:-\d{1,2})?号?", "", text.strip())
    return text.strip(" \t,，。:：")


def _split_points(value: str, *, allow_comma: bool) -> list[str]:
    text = _clean_route_side(value)
    if allow_comma:
        text = _COMMA_SPLIT_RE.sub("/", text)
    text = _MULTI_SPLIT_RE.sub("/", text)
    points = [item.strip(" \t,，。:：") for item in text.split("/") if item.strip(" \t,，。:：")]
    return list(dict.fromkeys(points)) or ([text] if text else [])


def _looks_like_context_token(token: str) -> bool:
    compact = _compact(token)
    if not compact:
        return True
    if any(word in compact for word in _COMMODITY_WORDS):
        return True
    return any(word in compact for word in _NON_DEST_WORDS) or bool(re.search(r"\d", compact))


def _extract_destinations_and_tail(value: str) -> tuple[list[str], str]:
    text = _clean_route_side(value)
    if not text:
        return [], ""
    tokens = [item.strip() for item in _COMMA_SPLIT_RE.split(text) if item.strip()]
    if len(tokens) > 1:
        dest_tokens: list[str] = []
        tail_tokens: list[str] = []
        for token in tokens:
            if tail_tokens or _looks_like_context_token(token):
                tail_tokens.append(token)
            else:
                dest_tokens.append(token)
        if dest_tokens:
            return _split_points("/".join(dest_tokens), allow_comma=False), "，".join(tail_tokens)

    first = tokens[0] if tokens else text
    tail = "，".join(tokens[1:]) if len(tokens) > 1 else ""
    for word in sorted(_COMMODITY_WORDS, key=len, reverse=True):
        if first.endswith(word) and len(first) > len(word) + 1:
            first = first[: -len(word)].strip()
            tail = word if not tail else f"{word}，{tail}"
            break
    if " " in first:
        pieces = [item for item in first.split() if item]
        if len(pieces) > 1 and not any(_looks_like_context_token(item) for item in pieces[:-1]):
            return pieces, tail
    return _split_points(first, allow_comma=False), tail


def _extract_context_fields(text: str) -> dict[str, Any]:
    compact = _compact(text)
    commodity = next((word for word in _COMMODITY_WORDS if word in compact), None)
    tonnage = None
    tonnage_match = re.search(r"\d{3,6}(?:\s*[-—–]\s*\d{3,6})?(?:吨|左右|以内|以上)?", text or "")
    if tonnage_match and not re.search(r"(元|运费|运价|单价|报价)", text or ""):
        tonnage = tonnage_match.group(0)
    return {"commodity_name": commodity, "raw_tonnage_text": tonnage}


def _parse_contact(line_ref: str, text: str) -> dict[str, Any] | None:
    phones = _PHONE_RE.findall(text or "")
    if not phones:
        return None
    phone = phones[-1]
    after = (text or "").split(phone, 1)[-1]
    before = (text or "").split(phone, 1)[0]
    name_text = after if re.search(r"[\u4e00-\u9fff]", after or "") else before
    name_match = re.search(r"([\u4e00-\u9fff]{1,4}(?:姐|哥|总|经理)?)", name_text or "")
    name = name_match.group(1) if name_match else None
    if name in {"电话", "联系", "微信", "同号"}:
        name = None
    wechat = phone if "微信同号" in text or "微信" in text and "同号" in text else None
    return {
        "anchor_id": f"A{line_ref[1:] if line_ref.startswith('L') else line_ref}",
        "line_refs": [line_ref],
        "raw_text": text,
        "phone": phone,
        "name": name,
        "wechat": wechat,
        "anchor_type_code": "CONTACT",
    }


class FreightStructuralSkeletonBuilder:
    """Build route units from explicit route expressions."""

    def build(self, indexed_text: FreightIndexedText) -> FreightSkeletonResult:
        units: list[dict[str, Any]] = []
        anchors: list[dict[str, Any]] = []
        route_line_refs: list[str] = []
        expansion_groups = 0
        unit_index = 1

        for line_ref, text in indexed_text.line_map.items():
            stripped = str(text or "").strip()
            if not stripped:
                continue
            contact = _parse_contact(line_ref, stripped)
            if contact:
                anchors.append(contact)
            route_match = _ROUTE_RE.search(stripped)
            backhaul = "卸完货" in stripped and "装" in stripped and route_match is not None
            if not route_match:
                continue
            origin_raw = _clean_route_side(route_match.group(1))
            rest = route_match.group(2)
            if len(_compact(origin_raw)) < 2 or len(_compact(rest)) < 2:
                continue
            if _compact(origin_raw).startswith(("需要", "寻船", "要船")):
                continue
            route_line_refs.append(line_ref)
            origins = _split_points(origin_raw, allow_comma=True)
            destinations, tail = _extract_destinations_and_tail(rest)
            if not origins or not destinations:
                continue
            context = _extract_context_fields(tail or stripped)
            group_id = f"EG{expansion_groups + 1}"
            if len(origins) * len(destinations) > 1:
                expansion_groups += 1
            for origin in origins:
                for destination in destinations:
                    unit_id = f"RU{unit_index}"
                    unit_index += 1
                    issue_codes = []
                    if len(origins) > 1 or len(destinations) > 1:
                        issue_codes.append(MULTI_POINT_EXPANDED)
                    if backhaul:
                        issue_codes.append("BACKHAUL_REVIEW_REQUIRED")
                    units.append(
                        {
                            "route_unit_id": unit_id,
                            "skeleton_id": unit_id,
                            "expansion_group_id": group_id if len(origins) * len(destinations) > 1 else None,
                            "line_refs": [line_ref],
                            "raw_text": stripped,
                            "origin_text": origin,
                            "destination_text": destination,
                            "commodity_name": context.get("commodity_name"),
                            "raw_tonnage_text": context.get("raw_tonnage_text"),
                            "fallback_review_reason": "回程装货表达需人工确认" if backhaul else "AI 未返回该路线候选，系统按本地骨架生成待复核候选",
                            "quality_issue_codes": issue_codes,
                        }
                    )

        context_blocks, context_notes = self._build_context(units, anchors, indexed_text)
        covered_refs = sorted({ref for unit in units for ref in unit.get("line_refs", [])}, key=_line_no)
        coverage_audit = {
            "route_line_refs": route_line_refs,
            "covered_line_refs": covered_refs,
            "missing_line_refs": [ref for ref in route_line_refs if ref not in covered_refs],
            "route_unit_count": len(units),
        }
        expansion_audit = {
            "expanded_group_count": expansion_groups,
            "expanded_unit_count": sum(1 for item in units if item.get("expansion_group_id")),
        }
        context_scope_audit = {
            "contact_anchor_count": len(anchors),
            "context_block_count": len(context_blocks),
            "context_note_count": len(context_notes),
        }
        return FreightSkeletonResult(
            skeleton_units=units,
            context_anchors=anchors,
            context_blocks=context_blocks,
            context_notes=context_notes,
            coverage_audit=coverage_audit,
            expansion_audit=expansion_audit,
            context_scope_audit=context_scope_audit,
        )

    def _build_context(
        self,
        units: list[dict[str, Any]],
        anchors: list[dict[str, Any]],
        indexed_text: FreightIndexedText,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        blocks: list[dict[str, Any]] = []
        notes: list[dict[str, Any]] = []
        if not units:
            return blocks, notes

        route_units_by_line = {unit["line_refs"][0]: unit for unit in units if unit.get("line_refs")}
        boundary_lines = {ref for ref, text in indexed_text.line_map.items() if _BOUNDARY_RE.match(str(text or ""))}

        for anchor in anchors:
            anchor_no = _line_no(anchor["line_refs"][0])
            candidate_units = [
                unit
                for unit in units
                if _line_no(unit["line_refs"][0]) < anchor_no
                and not any(_line_no(unit["line_refs"][0]) < _line_no(boundary) < anchor_no for boundary in boundary_lines)
            ]
            if not candidate_units:
                continue
            block_id = f"SB{len(blocks) + 1}"
            route_ids = [unit["route_unit_id"] for unit in candidate_units]
            line_refs = sorted({ref for unit in candidate_units for ref in unit["line_refs"]} | set(anchor["line_refs"]), key=_line_no)
            blocks.append(
                {
                    "context_block_id": block_id,
                    "route_unit_ids": route_ids,
                    "route_clue_ids": [],
                    "line_refs": line_refs,
                    "raw_text": "\n".join(indexed_text.line_map.get(ref, "") for ref in line_refs),
                    "shared_contact_name": anchor.get("name"),
                    "shared_contact_phone": anchor.get("phone"),
                    "shared_contact_wechat": anchor.get("wechat"),
                    "evidence": [anchor.get("raw_text")],
                    "scope_type_code": "EXPLICIT_SHARED",
                    "scope_reason": "联系人位于连续路线块末尾，覆盖该块内路线。",
                    "scope_risk_codes": [],
                }
            )

        for line_ref, text in indexed_text.line_map.items():
            stripped = str(text or "").strip()
            if not stripped or line_ref in route_units_by_line or _parse_contact(line_ref, stripped):
                continue
            context = _extract_context_fields(stripped)
            if not context.get("commodity_name") and not context.get("raw_tonnage_text"):
                continue
            line_no = _line_no(line_ref)
            previous_units = [unit for unit in units if _line_no(unit["line_refs"][0]) < line_no]
            if not previous_units:
                continue
            recent_units = previous_units[-4:]
            note_type = "COMMODITY" if context.get("commodity_name") else "TONNAGE"
            notes.append(
                {
                    "note_id": f"SN{len(notes) + 1}",
                    "raw_text": stripped,
                    "context_type_code": note_type,
                    "line_refs": [line_ref],
                    "route_unit_ids": [unit["route_unit_id"] for unit in recent_units],
                    "applies_to": [],
                    "scope_type_code": "WEAK_INFERRED",
                    "scope_reason": "后置共享字段紧跟路线组，需人工确认作用域。",
                    "evidence": [stripped],
                    "confidence_score": 0.6,
                }
            )
        return blocks, notes


def _route_key(origin: Any, destination: Any) -> tuple[str, str]:
    return (_compact(origin), _compact(destination))


def _clue_route_key(clue: dict[str, Any]) -> tuple[str, str]:
    origin = clue.get("origin")
    destination = clue.get("destination")
    origin_text = origin.get("text") if isinstance(origin, dict) else clue.get("origin_text")
    destination_text = destination.get("text") if isinstance(destination, dict) else clue.get("destination_text")
    return _route_key(origin_text, destination_text)


def _active_route_clues(semantic_map: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        clue
        for clue in semantic_map.get("route_clues") or []
        if isinstance(clue, dict) and clue.get("is_freight_candidate") is not False and not clue.get("drop_reason")
    ]


def apply_skeleton_to_semantic_map(semantic_map: dict[str, Any], skeleton: FreightSkeletonResult) -> dict[str, Any]:
    semantic_map.setdefault("route_clues", [])
    route_clues = [clue for clue in semantic_map.get("route_clues") or [] if isinstance(clue, dict)]
    semantic_map["route_clues"] = route_clues
    warnings = semantic_map.setdefault("warnings", [])
    if isinstance(warnings, list):
        warnings.append("LOCAL_SKELETON:已生成本地可追溯路线骨架并执行覆盖率验收")
    semantic_map.update(skeleton.as_semantic_payload())

    units = skeleton.skeleton_units
    route_key_to_unit = {_route_key(unit.get("origin_text"), unit.get("destination_text")): unit for unit in units}
    line_to_multi_units: dict[str, list[dict[str, Any]]] = {}
    for unit in units:
        if unit.get("line_refs"):
            line_to_multi_units.setdefault(unit["line_refs"][0], []).append(unit)

    for clue in route_clues:
        key = _clue_route_key(clue)
        matched = route_key_to_unit.get(key)
        if matched:
            clue.setdefault("route_unit_id", matched["route_unit_id"])
            clue.setdefault("skeleton_id", matched["skeleton_id"])
            clue.setdefault("expansion_group_id", matched.get("expansion_group_id"))
            continue
        refs = clue.get("line_refs") or []
        first_ref = refs[0] if refs else None
        expanded_units = line_to_multi_units.get(first_ref or "")
        origin_text = (clue.get("origin") or {}).get("text") if isinstance(clue.get("origin"), dict) else ""
        destination_text = (clue.get("destination") or {}).get("text") if isinstance(clue.get("destination"), dict) else ""
        if expanded_units and len(expanded_units) > 1 and ("/" in str(origin_text) or "／" in str(origin_text) or "/" in str(destination_text)):
            clue["is_freight_candidate"] = False
            clue["drop_reason"] = "本地骨架已展开多装卸地，停用合并线索避免少生成候选。"
        elif len(refs) > 1 and sum(1 for ref in refs if ref in line_to_multi_units) > 1:
            clue["is_freight_candidate"] = False
            clue["drop_reason"] = "本地骨架已按多行路线补齐召回，停用跨多行合并线索。"

    active_keys = {_clue_route_key(clue) for clue in _active_route_clues(semantic_map)}
    existing_ids = {
        str(clue.get("clue_temp_id"))
        for clue in route_clues
        if clue.get("clue_temp_id") not in (None, "")
    }
    next_index = 1
    for unit in units:
        key = _route_key(unit.get("origin_text"), unit.get("destination_text"))
        if key in active_keys:
            continue
        while f"C{next_index}" in existing_ids:
            next_index += 1
        clue_id = f"C{next_index}"
        next_index += 1
        existing_ids.add(clue_id)
        active_keys.add(key)
        route_clues.append(
            {
                "clue_temp_id": clue_id,
                "route_unit_id": unit["route_unit_id"],
                "skeleton_id": unit["skeleton_id"],
                "expansion_group_id": unit.get("expansion_group_id"),
                "line_refs": unit.get("line_refs") or [],
                "context_block_id": None,
                "raw_text": unit.get("raw_text") or "",
                "route_type_code": "LOCAL_SKELETON_EXPANDED" if unit.get("expansion_group_id") else "LOCAL_SKELETON_ROUTE",
                "route_intent_code": "FORMAL_FREIGHT",
                "origin": {"text": unit.get("origin_text"), "source_type_code": "LOCAL_LINE", "evidence_line_refs": unit.get("line_refs") or []},
                "destination": {"text": unit.get("destination_text"), "source_type_code": "LOCAL_LINE", "evidence_line_refs": unit.get("line_refs") or []},
                "route_summary": "本地骨架召回的可追溯路线，AI 字段缺失时生成待复核候选。",
                "missing_field_codes": ["COMMODITY"] if not unit.get("commodity_name") else [],
                "warnings": [LOCAL_SKELETON_FALLBACK, *unit.get("quality_issue_codes", [])],
                "confidence_score": 0.62,
                "evidence": [unit.get("raw_text") or ""],
                "local_skeleton_generated": True,
            }
        )

    clue_by_unit: dict[str, str] = {}
    for clue in _active_route_clues(semantic_map):
        unit_id = str(clue.get("route_unit_id") or "")
        if unit_id:
            clue_by_unit[unit_id] = str(clue.get("clue_temp_id"))

    context_blocks = semantic_map.setdefault("context_blocks", [])
    for block in skeleton.context_blocks:
        copied = dict(block)
        copied["route_clue_ids"] = [clue_by_unit[unit_id] for unit_id in copied.get("route_unit_ids") or [] if unit_id in clue_by_unit]
        if copied["route_clue_ids"]:
            context_blocks.append(copied)
    context_notes = semantic_map.setdefault("context_notes", [])
    for note in skeleton.context_notes:
        copied = dict(note)
        copied["applies_to"] = [clue_by_unit[unit_id] for unit_id in copied.get("route_unit_ids") or [] if unit_id in clue_by_unit]
        if copied["applies_to"]:
            context_notes.append(copied)
    return semantic_map


def fallback_segment_from_clue(clue: dict[str, Any], reason: str | None = None) -> dict[str, Any]:
    origin = clue.get("origin")
    destination = clue.get("destination")
    origin_text = origin.get("text") if isinstance(origin, dict) else clue.get("origin_text")
    destination_text = destination.get("text") if isinstance(destination, dict) else clue.get("destination_text")
    issue_codes = [AI_SEGMENT_MISSING, LOCAL_SKELETON_FALLBACK]
    issue_codes.extend(str(item) for item in clue.get("warnings") or [] if item not in issue_codes)
    return {
        "clue_temp_id": clue.get("clue_temp_id"),
        "route_unit_id": clue.get("route_unit_id"),
        "skeleton_id": clue.get("skeleton_id"),
        "expansion_group_id": clue.get("expansion_group_id"),
        "line_refs": clue.get("line_refs") or [],
        "context_block_id": clue.get("context_block_id"),
        "raw_text": clue.get("raw_text") or "",
        "origin_text": origin_text,
        "destination_text": destination_text,
        "commodity_name": clue.get("commodity_name"),
        "raw_tonnage_text": clue.get("raw_tonnage_text"),
        "availability_status_code": "UNKNOWN",
        "ai_review_status_code": "REVIEW_REQUIRED",
        "manual_review_reason": reason or "AI 未返回该路线候选，系统按本地骨架生成待复核候选",
        "ai_review_reason": reason or "AI 未返回该路线候选，系统按本地骨架生成待复核候选",
        "needs_strong_review": True,
        "fallback_generated": True,
        "quality_issue_codes": issue_codes,
        "confidence_score": 0.5,
        "evidence": [clue.get("raw_text") or ""],
        "field_support": {"source": "LOCAL_SKELETON"},
    }


def ensure_segments_for_route_clues(semantic_map: dict[str, Any], segments: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    active_clues = _active_route_clues(semantic_map)
    clue_by_id = {str(clue.get("clue_temp_id")): clue for clue in active_clues if clue.get("clue_temp_id") not in (None, "")}
    all_clue_ids = {
        str(clue.get("clue_temp_id"))
        for clue in semantic_map.get("route_clues") or []
        if isinstance(clue, dict) and clue.get("clue_temp_id") not in (None, "")
    }
    existing_refs: set[str] = set()
    for segment in segments:
        clue_ref = str(segment.get("clue_temp_id") or "")
        if clue_ref and clue_ref in all_clue_ids and clue_ref not in clue_by_id:
            segment["is_freight_candidate"] = False
            segment["drop_reason"] = segment.get("drop_reason") or "该 AI segment 对应的合并线索已被本地骨架展开替代。"
            warnings.append(f"{LOCAL_SKELETON_FALLBACK}: {clue_ref} 对应合并线索已停用，丢弃该 segment")
            continue
        if clue_ref:
            existing_refs.add(clue_ref)
            clue = clue_by_id.get(clue_ref)
            if clue:
                for field_name in ("route_unit_id", "skeleton_id", "expansion_group_id"):
                    if clue.get(field_name) and not segment.get(field_name):
                        segment[field_name] = clue.get(field_name)
    for clue in active_clues:
        clue_ref = str(clue.get("clue_temp_id") or "")
        if not clue_ref or clue_ref in existing_refs:
            continue
        fallback = fallback_segment_from_clue(clue)
        segments.append(fallback)
        warnings.append(f"{AI_SEGMENT_MISSING}: {clue_ref} 未形成 AI segment，已生成待复核骨架候选")
    return segments, warnings
