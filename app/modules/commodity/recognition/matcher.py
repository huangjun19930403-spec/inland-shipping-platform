"""Deterministic standard commodity matcher."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from app.modules.commodity.recognition.repository import CommodityStandardMatchRow
from app.modules.commodity.recognition.schemas import CommodityRecognitionCandidate

_SEPARATOR_RE = re.compile(r"[\s\u3000,，、/\\|;；:：()（）\[\]【】{}<>《》\"'`~!！?？._\-+*]+")
_PACKAGING_SUFFIXES = ("吨包", "吨袋", "袋装", "散装", "集装箱", "箱装", "桶装", "罐装", "件杂", "件装")


def normalize_commodity_text(value: str | None) -> str:
    """Normalize user and master-data names for matching."""

    text = unicodedata.normalize("NFKC", value or "").strip().lower()
    return _SEPARATOR_RE.sub("", text)


def strip_packaging_suffix(value: str) -> str:
    text = normalize_commodity_text(value)
    changed = True
    while changed:
        changed = False
        for suffix in _PACKAGING_SUFFIXES:
            normalized_suffix = normalize_commodity_text(suffix)
            if text.endswith(normalized_suffix) and len(text) > len(normalized_suffix):
                text = text[: -len(normalized_suffix)]
                changed = True
    return text


def is_packaging_only_text(value: str, packaging_terms: set[str] | None = None) -> bool:
    text = normalize_commodity_text(value)
    if not text:
        return False
    terms = {normalize_commodity_text(item) for item in _PACKAGING_SUFFIXES}
    terms.update({normalize_commodity_text(item) for item in packaging_terms or set()})
    return text in {item for item in terms if item}


class CommodityDeterministicMatcher:
    def __init__(
        self,
        standards: list[CommodityStandardMatchRow],
        *,
        packaging_terms: set[str] | None = None,
    ) -> None:
        self.standards = standards
        self.packaging_terms = packaging_terms or set()

    def match(
        self,
        raw_name: str,
        *,
        category_hint_id: int | None = None,
        type_hint_id: int | None = None,
        limit: int = 8,
    ) -> list[CommodityRecognitionCandidate]:
        text = normalize_commodity_text(raw_name)
        if not text or is_packaging_only_text(raw_name, self.packaging_terms):
            return []
        stripped_text = strip_packaging_suffix(raw_name)
        candidates: dict[int, CommodityRecognitionCandidate] = {}

        for standard in self.standards:
            for field_name, field_value, alias_id, alias_weight in self._matchable_values(standard):
                normalized_value = normalize_commodity_text(field_value)
                if not normalized_value:
                    continue
                score, level = self._score(text, stripped_text, normalized_value, field_name)
                if score <= 0:
                    continue
                score = self._boost(score, standard, category_hint_id, type_hint_id, alias_weight)
                candidate = CommodityRecognitionCandidate(
                    standard_id=standard.id,
                    standard_code=standard.code,
                    standard_name=standard.name,
                    category_id=standard.category_id,
                    category_name=standard.category_name,
                    type_id=standard.type_id,
                    type_name=standard.type_name,
                    matched_text=field_value,
                    match_field=field_name,
                    match_level_code=level,
                    basis=f"{self._field_label(field_name)}命中：{field_value}",
                    confidence_score=score,
                    already_alias=alias_id is not None and text == normalized_value,
                )
                previous = candidates.get(standard.id)
                if previous is None or candidate.confidence_score > previous.confidence_score:
                    candidates[standard.id] = candidate

        return sorted(
            candidates.values(),
            key=lambda item: (item.confidence_score, item.standard_id * -1),
            reverse=True,
        )[:limit]

    @staticmethod
    def _matchable_values(standard: CommodityStandardMatchRow):
        yield "code", standard.code, None, 100
        yield "name", standard.name, None, 100
        if standard.short_name:
            yield "short_name", standard.short_name, None, 96
        if standard.english_name:
            yield "english_name", standard.english_name, None, 94
        for alias in standard.aliases:
            if alias.is_enabled:
                yield "alias", alias.alias_name, alias.id, alias.match_weight

    @staticmethod
    def _score(text: str, stripped_text: str, normalized_value: str, field_name: str) -> tuple[int, str]:
        if text == normalized_value:
            return (100 if field_name != "alias" else 98), "EXACT"
        if stripped_text and stripped_text == normalized_value:
            return 92, "PACKAGING_STRIPPED"
        if len(normalized_value) >= 2 and normalized_value in text:
            return 88, "MASTER_IN_TEXT"
        if len(text) >= 2 and text in normalized_value:
            return 82, "TEXT_IN_MASTER"
        if stripped_text and len(stripped_text) >= 2 and stripped_text in normalized_value:
            return 78, "PACKAGING_STRIPPED_FUZZY"
        ratio = SequenceMatcher(None, text, normalized_value).ratio()
        if ratio >= 0.82:
            return int(round(ratio * 86)), "FUZZY"
        return 0, "NONE"

    @staticmethod
    def _boost(
        score: int,
        standard: CommodityStandardMatchRow,
        category_hint_id: int | None,
        type_hint_id: int | None,
        alias_weight: int,
    ) -> int:
        if type_hint_id and int(type_hint_id) == int(standard.type_id):
            score += 3
        elif category_hint_id and standard.category_id and int(category_hint_id) == int(standard.category_id):
            score += 2
        score += min(max(int(alias_weight or 0), 0), 100) // 50
        score += min(max(int(standard.recognition_priority or 0), 0), 100) // 50
        return max(0, min(score, 100))

    @staticmethod
    def _field_label(field_name: str) -> str:
        labels = {
            "code": "标准编码",
            "name": "标准名称",
            "short_name": "简称",
            "english_name": "英文名",
            "alias": "启用别名",
        }
        return labels.get(field_name, field_name)
