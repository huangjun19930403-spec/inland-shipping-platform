"""Application service for standard commodity recognition."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.modules.commodity.recognition.adoption_service import CommodityRecognitionAdoptionService
from app.modules.commodity.recognition.ai_assistant import CommodityRecognitionAIAssistant
from app.modules.commodity.recognition.context_builder import CommodityRecognitionContext, CommodityRecognitionContextBuilder
from app.modules.commodity.recognition.matcher import (
    CommodityDeterministicMatcher,
    is_packaging_only_text,
    normalize_commodity_text,
)
from app.modules.commodity.recognition.repository import CommodityRecognitionRepository
from app.modules.commodity.recognition.schemas import (
    CommodityRecognitionAdoptionResponse,
    CommodityRecognitionAliasAdoptRequest,
    CommodityRecognitionAttributeSuggestion,
    CommodityRecognitionCandidate,
    CommodityRecognitionCreateRequest,
    CommodityRecognitionDefaultRuleSuggestion,
    CommodityRecognitionDecisionRuleSuggestion,
    CommodityRecognitionResponse,
    CommodityRecognitionStandardAdoptRequest,
    CommodityRecognitionStandardSuggestion,
)
from app.modules.system.runtime_config import RuntimeConfigService


class CommodityRecognitionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = CommodityRecognitionRepository(db)
        self.context_builder = CommodityRecognitionContextBuilder(db)

    async def create_recognition(self, payload: CommodityRecognitionCreateRequest) -> CommodityRecognitionResponse:
        raw_name = payload.raw_name.strip()
        normalized_name = normalize_commodity_text(raw_name)
        context = await self.context_builder.build()
        standards = await self.repo.list_match_rows()
        matcher = CommodityDeterministicMatcher(standards, packaging_terms=context.packaging_terms())
        deterministic_candidates = matcher.match(
            raw_name,
            category_hint_id=payload.category_hint_id,
            type_hint_id=payload.type_hint_id,
        )
        await self._enrich_candidates(deterministic_candidates)

        ai_result = None
        if payload.enable_ai:
            ai_result = await CommodityRecognitionAIAssistant(RuntimeConfigService(self.db)).suggest(
                raw_name=raw_name,
                normalized_name=normalized_name,
                context_note=payload.context_note,
                context=context,
                deterministic_candidates=[item.model_dump(mode="json") for item in deterministic_candidates],
                category_hint_id=payload.category_hint_id,
                type_hint_id=payload.type_hint_id,
            )

        packaging_only = is_packaging_only_text(raw_name, context.packaging_terms())
        standard_suggestion = self._standard_suggestion(
            raw_name=raw_name,
            context=context,
            deterministic_candidates=deterministic_candidates,
            ai_suggestion=ai_result.suggestion if ai_result else None,
            category_hint_id=payload.category_hint_id,
            type_hint_id=payload.type_hint_id,
            packaging_only=packaging_only,
        )
        warnings = self._warnings(
            raw_name=raw_name,
            packaging_only=packaging_only,
            ai_error=ai_result.error_message if ai_result else None,
            enable_ai=payload.enable_ai,
            has_candidates=bool(deterministic_candidates),
        )
        suggestion_payload = {
            "suggested_action_code": self._suggested_action(deterministic_candidates, packaging_only),
            "standard_suggestion": standard_suggestion.model_dump(mode="json") if standard_suggestion else None,
            "warnings": warnings,
        }
        record = await self.repo.create_record(
            {
                "raw_name": raw_name,
                "normalized_name": normalized_name,
                "context_note": payload.context_note.strip() if payload.context_note else None,
                "category_hint_id": payload.category_hint_id,
                "type_hint_id": payload.type_hint_id,
                "request_payload_json": payload.model_dump(mode="json"),
                "deterministic_result_json": {
                    "candidates": [item.model_dump(mode="json") for item in deterministic_candidates]
                },
                "ai_result_json": self._ai_payload(ai_result),
                "suggestion_json": suggestion_payload,
                "status_code": "COMPLETED",
                "ai_status_code": ai_result.status_code if ai_result else "DISABLED",
                "ai_error_message": ai_result.error_message if ai_result else None,
            }
        )
        await self.db.commit()
        return self._to_response(record)

    async def get_recognition(self, recognition_id: int) -> CommodityRecognitionResponse:
        record = await self.repo.get_record(recognition_id)
        if record is None:
            raise NotFoundError("CommodityRecognitionRecord", recognition_id)
        return self._to_response(record)

    async def adopt_alias(
        self,
        recognition_id: int,
        payload: CommodityRecognitionAliasAdoptRequest,
        *,
        operator_id: int | None,
    ) -> CommodityRecognitionAdoptionResponse:
        adoption = CommodityRecognitionAdoptionService(self.db)
        standard_id, alias_id = await adoption.adopt_alias(recognition_id, payload, operator_id=operator_id)
        snapshot = await self.repo.get_standard_snapshot(standard_id)
        if snapshot is None:
            raise NotFoundError("CommodityStandard", standard_id)
        record = await self.repo.get_record(recognition_id)
        if record is None:
            raise NotFoundError("CommodityRecognitionRecord", recognition_id)
        return CommodityRecognitionAdoptionResponse(
            action_code="ADOPT_ALIAS",
            standard_id=standard_id,
            standard_code=snapshot["code"],
            standard_name=snapshot["name"],
            alias_id=alias_id,
            recognition=self._to_response(record),
        )

    async def adopt_standard(
        self,
        recognition_id: int,
        payload: CommodityRecognitionStandardAdoptRequest,
        *,
        operator_id: int | None,
    ) -> CommodityRecognitionAdoptionResponse:
        adoption = CommodityRecognitionAdoptionService(self.db)
        standard_id = await adoption.adopt_standard(recognition_id, payload, operator_id=operator_id)
        snapshot = await self.repo.get_standard_snapshot(standard_id)
        if snapshot is None:
            raise NotFoundError("CommodityStandard", standard_id)
        record = await self.repo.get_record(recognition_id)
        if record is None:
            raise NotFoundError("CommodityRecognitionRecord", recognition_id)
        return CommodityRecognitionAdoptionResponse(
            action_code="ADOPT_STANDARD",
            standard_id=standard_id,
            standard_code=snapshot["code"],
            standard_name=snapshot["name"],
            recognition=self._to_response(record),
        )

    async def _enrich_candidates(self, candidates: list[CommodityRecognitionCandidate]) -> None:
        ids = [item.standard_id for item in candidates]
        attr_map = await self.repo.attribute_suggestions(ids)
        count_map = await self.repo.capability_counts(ids)
        for candidate in candidates:
            candidate.attributes = [
                CommodityRecognitionAttributeSuggestion.model_validate(item)
                for item in attr_map.get(candidate.standard_id, [])[:6]
            ]
            candidate.capability_summary = self._capability_summary(count_map.get(candidate.standard_id, {}))

    def _standard_suggestion(
        self,
        *,
        raw_name: str,
        context: CommodityRecognitionContext,
        deterministic_candidates: list[CommodityRecognitionCandidate],
        ai_suggestion: CommodityRecognitionStandardSuggestion | None,
        category_hint_id: int | None,
        type_hint_id: int | None,
        packaging_only: bool,
    ) -> CommodityRecognitionStandardSuggestion | None:
        if ai_suggestion is not None:
            return self._complete_standard_suggestion(ai_suggestion, context, raw_name)
        if deterministic_candidates or packaging_only:
            return None
        type_item = context.type_by_id(type_hint_id) or (context.types[0] if context.types else None)
        category_id = category_hint_id or (type_item.get("category_id") if type_item else None)
        category = context.category_by_id(category_id)
        return CommodityRecognitionStandardSuggestion(
            name=raw_name,
            category_id=int(category["id"]) if category else None,
            category_name=category.get("name") if category else None,
            type_id=int(type_item["id"]) if type_item else None,
            type_name=type_item.get("name") if type_item else None,
            main_unit_code=context.default_code("COMMODITY_UNIT", "TON"),
            main_unit_name=context.label("COMMODITY_UNIT", context.default_code("COMMODITY_UNIT", "TON")),
            cargo_form_code=context.default_code("COMMODITY_CARGO_FORM", "BULK"),
            cargo_form_name=context.label("COMMODITY_CARGO_FORM", context.default_code("COMMODITY_CARGO_FORM", "BULK")),
            recognition_priority=50,
            aliases=[raw_name],
            confidence_score=45,
            reasons=["未命中当前标准货品和启用别名，提供人工新建降级建议"],
            warnings=["请人工确认分类、类型和属性后再采纳"],
        )

    def _complete_standard_suggestion(
        self,
        suggestion: CommodityRecognitionStandardSuggestion,
        context: CommodityRecognitionContext,
        raw_name: str,
    ) -> CommodityRecognitionStandardSuggestion:
        category = context.category_by_id(suggestion.category_id)
        type_item = context.type_by_id(suggestion.type_id)
        unit_code = suggestion.main_unit_code or context.default_code("COMMODITY_UNIT", "TON")
        cargo_form_code = suggestion.cargo_form_code or context.default_code("COMMODITY_CARGO_FORM", "BULK")
        aliases = list(dict.fromkeys([raw_name, *suggestion.aliases]))
        return suggestion.model_copy(
            update={
                "category_name": category.get("name") if category else suggestion.category_name,
                "type_name": type_item.get("name") if type_item else suggestion.type_name,
                "main_unit_code": unit_code,
                "main_unit_name": context.label("COMMODITY_UNIT", unit_code),
                "cargo_form_code": cargo_form_code,
                "cargo_form_name": context.label("COMMODITY_CARGO_FORM", cargo_form_code),
                "dangerous_grade_name": context.label("DANGEROUS_GOODS_LEVEL", suggestion.dangerous_grade_code),
                "pollution_risk_level_name": context.label("POLLUTION_RISK_LEVEL", suggestion.pollution_risk_level_code),
                "aliases": aliases,
            }
        )

    @staticmethod
    def _suggested_action(candidates: list[CommodityRecognitionCandidate], packaging_only: bool) -> str:
        if packaging_only:
            return "MANUAL_REVIEW"
        if candidates and candidates[0].confidence_score >= 78:
            return "ADOPT_ALIAS"
        return "ADOPT_STANDARD"

    @staticmethod
    def _warnings(
        *,
        raw_name: str,
        packaging_only: bool,
        ai_error: str | None,
        enable_ai: bool,
        has_candidates: bool,
    ) -> list[str]:
        warnings: list[str] = []
        if packaging_only:
            warnings.append(f"{raw_name} 看起来是包装形式，不建议创建为标准货品")
        if enable_ai and ai_error:
            warnings.append(f"AI 建议不可用，已返回确定性候选：{ai_error}")
        if not has_candidates and not packaging_only:
            warnings.append("未命中现有标准货品，请人工确认是否确需新建")
        return warnings

    @staticmethod
    def _capability_summary(counts: dict[str, int]) -> str:
        parts = []
        labels = {
            "packaging": "包装",
            "transport": "运输",
            "ship": "船型",
            "node": "节点",
            "handling": "作业",
        }
        for key, label in labels.items():
            value = int(counts.get(key) or 0)
            if value:
                parts.append(f"{label}{value}")
        return " / ".join(parts) if parts else "未维护"

    @staticmethod
    def _ai_payload(ai_result) -> dict[str, Any] | None:
        if ai_result is None:
            return None
        return {
            "status_code": ai_result.status_code,
            "provider": ai_result.provider,
            "model": ai_result.model,
            "suggestion": ai_result.suggestion.model_dump(mode="json") if ai_result.suggestion else None,
            "raw_payload": ai_result.raw_payload,
            "error_message": ai_result.error_message,
        }

    @staticmethod
    def _to_response(record) -> CommodityRecognitionResponse:
        deterministic_json = record.deterministic_result_json or {}
        suggestion_json = record.suggestion_json or {}
        ai_json = record.ai_result_json or {}
        candidates = [
            CommodityRecognitionCandidate.model_validate(item)
            for item in deterministic_json.get("candidates", [])
        ]
        standard_suggestion = suggestion_json.get("standard_suggestion")
        return CommodityRecognitionResponse(
            id=int(record.id),
            raw_name=record.raw_name,
            normalized_name=record.normalized_name,
            context_note=record.context_note,
            category_hint_id=record.category_hint_id,
            type_hint_id=record.type_hint_id,
            status_code=record.status_code,
            suggested_action_code=suggestion_json.get("suggested_action_code") or "MANUAL_REVIEW",
            ai_status_code=record.ai_status_code,
            ai_error_message=record.ai_error_message,
            deterministic_candidates=candidates,
            ai_suggestion=ai_json.get("suggestion") if isinstance(ai_json, dict) else None,
            standard_suggestion=(
                CommodityRecognitionStandardSuggestion.model_validate(standard_suggestion)
                if isinstance(standard_suggestion, dict)
                else None
            ),
            warnings=list(suggestion_json.get("warnings") or []),
            adopted_action_code=record.adopted_action_code,
            adopted_standard_id=record.adopted_standard_id,
            adopted_alias_id=record.adopted_alias_id,
            adopted_at=record.adopted_at,
            created_at=record.created_at or datetime.utcnow(),
            updated_at=record.updated_at or datetime.utcnow(),
        )
