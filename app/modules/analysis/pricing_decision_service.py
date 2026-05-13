"""Pricing decision and freight-rate estimate services."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import PricingDecisionRecord
from app.models.freight import Freight, FreightBatchTask, FreightCandidate, FreightClue, FreightTmsInbound
from app.modules.analysis.rate_estimation import (
    RateSampleEstimator,
    confidence_level,
    is_demo_freight,
    weighted_percentile,
)
from app.modules.analysis.schemas import (
    PricingDecisionMetric,
    PricingDecisionResponse,
    PricingRecommendedAction,
    QuoteDecisionRequest,
    QuoteSimulatorContextResponse,
    RateEstimateRequest,
)


QUOTE_RE = re.compile(r"(?:船主|船户|船东)[^0-9]{0,8}([0-9]+(?:\.[0-9]+)?)\s*(?:元|块)?\s*/?\s*吨")
SHIPPER_QUOTE_RE = re.compile(r"(?:货主|当前货主)?(?:报价|运价)[^0-9]{0,8}([0-9]+(?:\.[0-9]+)?)\s*(?:元|块)?\s*/?\s*吨")
ADVANCED_CONFIG_RE = re.compile(r"高级配置[:：]?\s*([^。；\n]*(?:[；;][^。\n]*)?)")


@dataclass
class PricingContext:
    freight: Freight | None
    origin_node_id: int | None
    destination_node_id: int | None
    commodity_standard_id: int | None
    tonnage: float | None
    current_quote: float | None
    expected_loading_time: datetime | None
    source_evidence: list[dict[str, Any]]


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _round(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None and math.isfinite(value) else None


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _num(value)
        if number is not None and number > 0:
            return number
    return None


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _record_no(record_type_code: str) -> str:
    return f"PR-{record_type_code}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"


def _parse_owner_quote(text: str | None) -> tuple[float | None, str | None]:
    if not text:
        return None, None
    match = QUOTE_RE.search(text)
    if not match:
        return None, None
    return _num(match.group(1)), match.group(0)


def _parse_shipper_quote(text: str | None) -> float | None:
    if not text:
        return None
    match = SHIPPER_QUOTE_RE.search(text)
    return _num(match.group(1)) if match else None


def _parse_advanced_text(text: str | None) -> str | None:
    if not text:
        return None
    match = ADVANCED_CONFIG_RE.search(text)
    return match.group(1).strip(" ；;。") if match else None


def _parse_advanced_config_values(text: str | None) -> dict[str, float | int] | None:
    if not text:
        return None
    result: dict[str, float | int] = {}
    credit_match = re.search(r"账期\s*([0-9]+)\s*天", text)
    if credit_match:
        result["credit_days"] = int(credit_match.group(1))
    insurance_match = re.search(r"保险\s*([0-9]+(?:\.[0-9]+)?)\s*元?\s*/?\s*吨", text)
    if insurance_match:
        result["insurance_fee_per_ton"] = float(insurance_match.group(1))
    service_match = re.search(r"服务费\s*([0-9]+(?:\.[0-9]+)?)\s*%", text)
    if service_match:
        result["service_fee_rate"] = float(service_match.group(1)) / 100
    lock_match = re.search(r"(?:过闸|船闸|锁费)[^0-9]{0,6}([0-9]+(?:\.[0-9]+)?)\s*元?\s*/?\s*吨", text)
    if lock_match:
        result["lock_fee_per_ton"] = float(lock_match.group(1))
    return result or None


class PricingDecisionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def quote_context(self, freight_id: int) -> QuoteSimulatorContextResponse:
        freight = await self.db.get(Freight, freight_id)
        if freight is None:
            raise ValueError(f"freight not found: {freight_id}")

        context = await self._context_from_freight(freight)
        owner_quote, owner_quote_text, advanced_text = self._quote_evidence_from_sources(context.source_evidence)
        reasons = self._base_missing_reasons(
            context,
            require_current_quote=True,
            require_owner_quote=False,
        )
        if owner_quote is None:
            reasons.append("OWNER_QUOTE_MISSING")
        return QuoteSimulatorContextResponse(
            freight_id=int(freight.id),
            freight_no=freight.freight_no,
            origin_node_id=context.origin_node_id,
            destination_node_id=context.destination_node_id,
            commodity_standard_id=context.commodity_standard_id,
            tonnage=context.tonnage,
            current_quote=context.current_quote,
            owner_quote=owner_quote,
            owner_quote_min=owner_quote,
            owner_quote_max=owner_quote,
            owner_quote_text=owner_quote_text,
            advanced_config_text=advanced_text,
            advanced_config=_parse_advanced_config_values(advanced_text),
            expected_loading_time=context.expected_loading_time,
            source_evidence=context.source_evidence,
            not_computable_reasons=reasons,
        )

    async def decide_quote(self, payload: QuoteDecisionRequest, *, created_by: int | None = None) -> PricingDecisionResponse:
        context = await self._context_from_payload(payload)
        owner_quote = _first_number(payload.owner_quote, payload.owner_quote_max, payload.owner_quote_min)
        reasons = self._base_missing_reasons(context, require_current_quote=True, require_owner_quote=False)
        if owner_quote is None:
            reasons.append("OWNER_QUOTE_MISSING")
        route_distance = _num(payload.route_distance_km)
        if payload.route_status_code and payload.route_status_code != "READY":
            reasons.extend(payload.route_not_computable_reasons or ["ROUTE_NOT_READY"])
        if route_distance is None or route_distance <= 0:
            reasons.append("ROUTE_DISTANCE_MISSING")

        if reasons:
            return await self._persist_response(
                record_type_code="QUOTE_DECISION",
                status_code="NOT_COMPUTABLE",
                decision_code="NOT_COMPUTABLE",
                conclusion="缺少关键报价要素，不能生成智能报价决策。",
                context=context,
                payload=payload.model_dump(mode="json"),
                route_evidence=self._route_evidence(payload),
                sample_evidence={},
                result={},
                reasons=list(dict.fromkeys(reasons)),
                actions=self._quote_actions(can_estimate=True, can_quote=False),
                created_by=created_by,
            )

        assert context.current_quote is not None and context.tonnage is not None and route_distance is not None
        assert owner_quote is not None
        risk_cfg = {
            "STEADY": {"margin": 0.12, "reserve": 0.08},
            "STANDARD": {"margin": 0.10, "reserve": 0.06},
            "COMPETITIVE": {"margin": 0.07, "reserve": 0.04},
        }[payload.risk_profile]
        cfg = payload.advanced_config
        current_quote = context.current_quote
        distance_cost = route_distance * cfg.fuel_cost_per_ton_km * (1 + cfg.empty_sailing_rate)
        fixed_cost = cfg.handling_fee_per_ton + cfg.insurance_fee_per_ton + cfg.lock_fee_per_ton
        percentage_cost = current_quote * (cfg.service_fee_rate + cfg.tax_rate + risk_cfg["reserve"])
        capital_cost = current_quote * cfg.credit_days * cfg.daily_capital_cost_rate
        non_owner_cost = distance_cost + fixed_cost + percentage_cost + capital_cost
        target_profit = current_quote * risk_cfg["margin"]
        owner_ceiling = max(0.0, current_quote - non_owner_cost - target_profit)
        cost_floor = non_owner_cost + owner_quote
        gross_profit = current_quote - cost_floor
        gross_margin_rate = gross_profit / current_quote if current_quote else 0

        if gross_profit < 0:
            decision_code = "REJECT"
            conclusion = "船主报价已高于货主报价可覆盖空间，建议拒绝或重新议价。"
        elif owner_quote > owner_ceiling:
            decision_code = "NEGOTIATE"
            conclusion = "船主报价压缩目标毛利，建议按推荐上限议价。"
        else:
            decision_code = "ACCEPT"
            conclusion = "船主报价低于推荐上限，可进入报价确认。"

        result = {
            "decision_code": decision_code,
            "non_owner_cost": _round(non_owner_cost),
            "distance_cost": _round(distance_cost),
            "fixed_cost": _round(fixed_cost),
            "percentage_cost": _round(percentage_cost),
            "capital_cost": _round(capital_cost),
            "target_profit": _round(target_profit),
            "owner_quote": _round(owner_quote),
            "owner_ceiling": _round(owner_ceiling),
        }
        metrics = [
            PricingDecisionMetric(code="current_quote", title="货主报价", value=_round(current_quote), unit="元/吨"),
            PricingDecisionMetric(code="owner_quote", title="船主报价", value=_round(owner_quote), unit="元/吨"),
            PricingDecisionMetric(code="owner_ceiling", title="推荐船主价上限", value=_round(owner_ceiling), unit="元/吨"),
            PricingDecisionMetric(code="gross_profit", title="预计毛利", value=_round(gross_profit), unit="元/吨"),
        ]
        return await self._persist_response(
            record_type_code="QUOTE_DECISION",
            status_code=decision_code,
            decision_code=decision_code,
            conclusion=conclusion,
            context=context,
            payload=payload.model_dump(mode="json"),
            route_evidence=self._route_evidence(payload),
            sample_evidence={"sample_size": 1, "source": "direct_owner_quote"},
            result=result,
            metrics=metrics,
            cost_floor=cost_floor,
            recommended_quote=owner_ceiling,
            gross_profit=gross_profit,
            gross_margin_rate=gross_margin_rate,
            sample_size=1,
            coverage_rate=100,
            confidence_level="HIGH",
            actions=self._quote_actions(can_estimate=True, can_quote=True),
            created_by=created_by,
        )

    async def estimate_rate(self, payload: RateEstimateRequest, *, created_by: int | None = None) -> PricingDecisionResponse:
        context = await self._context_from_payload(payload)
        reasons = self._base_missing_reasons(context, require_current_quote=False, require_owner_quote=False)
        route_warnings = []
        if payload.route_status_code and payload.route_status_code != "READY":
            route_warnings.extend(payload.route_not_computable_reasons or ["ROUTE_NOT_READY"])

        if reasons:
            return await self._persist_response(
                record_type_code="RATE_ESTIMATE",
                status_code="NOT_COMPUTABLE",
                decision_code="NOT_COMPUTABLE",
                conclusion="缺少装卸地、货品或吨位，不能生成运价预估。",
                context=context,
                payload=payload.model_dump(mode="json"),
                route_evidence=self._route_evidence(payload),
                sample_evidence={},
                result={},
                reasons=list(dict.fromkeys(reasons)),
                actions=self._estimate_actions(False),
                created_by=created_by,
            )

        route_distance_km = _num(payload.route_distance_km)
        estimator = RateSampleEstimator(self.db)
        sample_rows, fallback_level, fallback_trace = await estimator.rate_samples(context, route_distance_km)
        if not sample_rows:
            return await self._persist_response(
                record_type_code="RATE_ESTIMATE",
                status_code="NOT_COMPUTABLE",
                decision_code="NOT_COMPUTABLE",
                conclusion="当前筛选层级下没有可用历史运价样本。",
                context=context,
                payload=payload.model_dump(mode="json"),
                route_evidence=self._route_evidence(payload),
                sample_evidence={"fallback_level_code": "NO_SAMPLE", "sample_size": 0},
                result={},
                reasons=["PRICE_SAMPLE_MISSING"],
                actions=self._estimate_actions(False),
                fallback_trace=fallback_trace,
                quality_warnings=["PRICE_SAMPLE_MISSING"],
                created_by=created_by,
            )

        weighted_samples = await estimator.weighted_rate_samples(sample_rows, context, fallback_level, route_distance_km, payload.route_status_code)
        filtered_samples, outlier_count = estimator.exclude_price_outliers(weighted_samples)
        if not filtered_samples:
            filtered_samples = weighted_samples
        prices = [item.price for item in filtered_samples]
        weight_total = sum(item.weight for item in filtered_samples)
        recommended = sum(item.price * item.weight for item in filtered_samples) / weight_total if weight_total else sum(prices) / len(prices)
        low = weighted_percentile(filtered_samples, 0.2)
        high = weighted_percentile(filtered_samples, 0.8)
        avg = sum(prices) / len(prices)
        spread = ((max(prices) - min(prices)) / avg) if avg else 1
        effective_size = estimator.effective_sample_size(filtered_samples)
        factor_breakdown = estimator.aggregate_factor_breakdown(filtered_samples)
        quality_warnings = estimator.rate_quality_warnings(
            filtered_samples,
            fallback_level=fallback_level,
            route_warnings=route_warnings,
            outlier_count=outlier_count,
            effective_sample_size=effective_size,
        )
        coverage = {
            "EXACT_NODE_COMMODITY": 95,
            "CITY_COMMODITY": 80,
            "FLOW_COMMODITY_TYPE": 70,
            "COMMODITY": 62,
            "DISTANCE_BAND": 55,
            "GLOBAL_PRICE": 45,
        }.get(fallback_level, 30)
        if route_warnings:
            coverage = max(20, coverage - 15)
        if outlier_count:
            coverage = max(20, coverage - min(12, outlier_count * 3))
        confidence = confidence_level(
            len(prices),
            fallback_level,
            coverage,
            spread,
            effective_sample_size=effective_size,
            quality_warnings=quality_warnings,
        )
        result = {
            "recommended_quote": _round(recommended),
            "estimated_low_quote": _round(low),
            "estimated_high_quote": _round(high),
            "price_spread": _round(spread, 4),
            "fallback_level_code": fallback_level,
            "route_warnings": route_warnings,
            "effective_sample_size": _round(effective_size, 2),
            "outlier_count": outlier_count,
        }
        sample_evidence = {
            "sample_size": len(prices),
            "raw_sample_size": len(weighted_samples),
            "fallback_level_code": fallback_level,
            "sample_freight_nos": [item.row.freight_no for item in filtered_samples[:12]],
            "includes_demo_data": any(is_demo_freight(row) for row in sample_rows),
        }
        metrics = [
            PricingDecisionMetric(code="recommended_quote", title="推荐预估价", value=_round(recommended), unit="元/吨"),
            PricingDecisionMetric(code="estimated_low_quote", title="低位价格", value=_round(low), unit="元/吨"),
            PricingDecisionMetric(code="estimated_high_quote", title="高位价格", value=_round(high), unit="元/吨"),
            PricingDecisionMetric(code="sample_size", title="样本量", value=len(prices), unit="条"),
        ]
        return await self._persist_response(
            record_type_code="RATE_ESTIMATE",
            status_code="READY",
            decision_code="ESTIMATED",
            conclusion="已基于历史样本和当前上下文生成运价预估区间。",
            context=context,
            payload=payload.model_dump(mode="json"),
            route_evidence=self._route_evidence(payload),
            sample_evidence=sample_evidence,
            result=result,
            metrics=metrics,
            recommended_quote=recommended,
            estimated_low_quote=low,
            estimated_high_quote=high,
            sample_size=len(prices),
            coverage_rate=coverage,
            confidence_level=confidence,
            fallback_level_code=fallback_level,
            factor_breakdown=factor_breakdown,
            comparable_samples=estimator.comparable_sample_payload(filtered_samples),
            fallback_trace=fallback_trace,
            quality_warnings=quality_warnings,
            actions=self._estimate_actions(True),
            created_by=created_by,
        )

    async def _context_from_payload(self, payload: QuoteDecisionRequest | RateEstimateRequest) -> PricingContext:
        freight = await self.db.get(Freight, payload.freight_id) if payload.freight_id else None
        base = await self._context_from_freight(freight) if freight is not None else PricingContext(None, None, None, None, None, None, None, [])
        return PricingContext(
            freight=freight,
            origin_node_id=payload.origin_node_id or base.origin_node_id,
            destination_node_id=payload.destination_node_id or base.destination_node_id,
            commodity_standard_id=payload.commodity_standard_id or base.commodity_standard_id,
            tonnage=_first_number(payload.tonnage, base.tonnage),
            current_quote=_first_number(getattr(payload, "current_quote", None), base.current_quote),
            expected_loading_time=getattr(payload, "expected_loading_time", None) or base.expected_loading_time,
            source_evidence=base.source_evidence,
        )

    async def _context_from_freight(self, freight: Freight | None) -> PricingContext:
        if freight is None:
            return PricingContext(None, None, None, None, None, None, None, [])
        evidence: list[dict[str, Any]] = []
        candidate = await self.db.get(FreightCandidate, freight.source_candidate_id) if freight.source_candidate_id else None
        clue = await self.db.get(FreightClue, freight.source_clue_id) if freight.source_clue_id else None
        batch = await self.db.get(FreightBatchTask, freight.source_batch_id) if freight.source_batch_id else None
        inbound = await self.db.get(FreightTmsInbound, freight.source_tms_inbound_id) if freight.source_tms_inbound_id else None
        for source_type, row in (("FREIGHT", freight), ("CANDIDATE", candidate), ("CLUE", clue), ("BATCH", batch), ("TMS", inbound)):
            if row is None:
                continue
            raw_text = getattr(row, "raw_text", None) or getattr(row, "raw_content", None) or getattr(row, "cargo_description", None)
            payload = (
                getattr(row, "extracted_fields_json", None)
                or getattr(row, "ai_semantic_map_json", None)
                or getattr(row, "payload_json", None)
                or getattr(row, "match_basis_json", None)
            )
            evidence.append({"source_type": source_type, "raw_text": raw_text, "payload": payload})
        current_quote = _first_number(freight.unit_price, candidate.unit_price if candidate is not None else None)
        if current_quote is None:
            current_quote = _parse_shipper_quote(" ".join(str(item.get("raw_text") or "") for item in evidence))
        return PricingContext(
            freight=freight,
            origin_node_id=freight.origin_node_id,
            destination_node_id=freight.destination_node_id,
            commodity_standard_id=freight.commodity_standard_id,
            tonnage=_first_number(freight.estimated_tonnage, freight.max_tonnage, freight.min_tonnage),
            current_quote=current_quote,
            expected_loading_time=freight.loading_time_from,
            source_evidence=evidence,
        )

    def _quote_evidence_from_sources(self, evidence: list[dict[str, Any]]) -> tuple[float | None, str | None, str | None]:
        fallback_advanced_text = self._advanced_text_from_sources(evidence)
        for item in evidence:
            payload = item.get("payload")
            if isinstance(payload, dict):
                owner_quote = _first_number(payload.get("shipowner_quote"), payload.get("owner_quote"))
                owner_text = _first_text(payload.get("shipowner_quote_text"), payload.get("owner_quote_text"), payload.get("owner_quote_evidence"))
                advanced_text = _first_text(payload.get("advanced_config_text"), payload.get("advanced_config"))
                if owner_quote is not None:
                    parsed_advanced = advanced_text or _parse_advanced_text(item.get("raw_text")) or fallback_advanced_text
                    return owner_quote, owner_text or f"{owner_quote}元/吨", str(parsed_advanced) if parsed_advanced is not None else None
                parsed_from_payload, parsed_text = _parse_owner_quote(owner_text)
                if parsed_from_payload is not None:
                    parsed_advanced = advanced_text or _parse_advanced_text(item.get("raw_text")) or fallback_advanced_text
                    return parsed_from_payload, parsed_text or owner_text, str(parsed_advanced) if parsed_advanced is not None else None
            raw_text = item.get("raw_text")
            owner_quote, owner_text = _parse_owner_quote(raw_text)
            if owner_quote is not None:
                return owner_quote, owner_text, _parse_advanced_text(raw_text) or fallback_advanced_text
        return None, None, fallback_advanced_text

    @staticmethod
    def _advanced_text_from_sources(evidence: list[dict[str, Any]]) -> str | None:
        for item in evidence:
            parsed = _parse_advanced_text(item.get("raw_text"))
            if parsed:
                return parsed
        for item in evidence:
            payload = item.get("payload")
            if isinstance(payload, dict):
                value = _first_text(payload.get("advanced_config_text"), payload.get("advanced_config"))
                if value:
                    return value
        return None

    @staticmethod
    def _base_missing_reasons(context: PricingContext, *, require_current_quote: bool, require_owner_quote: bool) -> list[str]:
        reasons: list[str] = []
        if not context.origin_node_id:
            reasons.append("ORIGIN_NODE_MISSING")
        if not context.destination_node_id:
            reasons.append("DESTINATION_NODE_MISSING")
        if not context.commodity_standard_id:
            reasons.append("COMMODITY_STANDARD_MISSING")
        if not context.tonnage or context.tonnage <= 0:
            reasons.append("TONNAGE_MISSING")
        if require_current_quote and (not context.current_quote or context.current_quote <= 0):
            reasons.append("CURRENT_QUOTE_MISSING")
        if require_owner_quote:
            reasons.append("OWNER_QUOTE_MISSING")
        return reasons

    @staticmethod
    def _route_evidence(payload: QuoteDecisionRequest | RateEstimateRequest) -> dict[str, Any]:
        return {
            "status_code": payload.route_status_code,
            "distance_km": payload.route_distance_km,
            "geometry_source": payload.route_geometry_source,
            "not_computable_reasons": payload.route_not_computable_reasons,
        }

    async def _persist_response(
        self,
        *,
        record_type_code: str,
        status_code: str,
        decision_code: str,
        conclusion: str,
        context: PricingContext,
        payload: dict[str, Any],
        route_evidence: dict[str, Any],
        sample_evidence: dict[str, Any],
        result: dict[str, Any],
        metrics: list[PricingDecisionMetric] | None = None,
        reasons: list[str] | None = None,
        actions: list[PricingRecommendedAction] | None = None,
        cost_floor: float | None = None,
        recommended_quote: float | None = None,
        estimated_low_quote: float | None = None,
        estimated_high_quote: float | None = None,
        gross_profit: float | None = None,
        gross_margin_rate: float | None = None,
        sample_size: int = 0,
        coverage_rate: float | None = None,
        confidence_level: str = "UNKNOWN",
        fallback_level_code: str | None = None,
        factor_breakdown: list[dict[str, Any]] | None = None,
        comparable_samples: list[dict[str, Any]] | None = None,
        fallback_trace: list[dict[str, Any]] | None = None,
        quality_warnings: list[str] | None = None,
        created_by: int | None = None,
    ) -> PricingDecisionResponse:
        now = datetime.now(UTC).replace(tzinfo=None)
        reasons = reasons or []
        actions = actions or []
        lineage = [
            {"source_table": "freight", "source_id": int(context.freight.id)} if context.freight is not None else None,
            {"source_table": "pricing_decision_record", "record_type_code": record_type_code},
        ]
        lineage = [item for item in lineage if item is not None]
        result_payload = {
            "decision_code": decision_code,
            "conclusion": conclusion,
            **result,
            "factor_breakdown": factor_breakdown or [],
            "comparable_samples": comparable_samples or [],
            "fallback_trace": fallback_trace or [],
            "quality_warnings": quality_warnings or [],
        }
        record = PricingDecisionRecord(
            record_no=_record_no(record_type_code),
            record_type_code=record_type_code,
            status_code=status_code,
            freight_id=int(context.freight.id) if context.freight is not None else None,
            origin_node_id=context.origin_node_id,
            destination_node_id=context.destination_node_id,
            commodity_standard_id=context.commodity_standard_id,
            expected_loading_time=context.expected_loading_time,
            tonnage=context.tonnage,
            current_quote=context.current_quote,
            owner_quote_min=_num(payload.get("owner_quote_min") or payload.get("owner_quote")),
            owner_quote_max=_num(payload.get("owner_quote_max") or payload.get("owner_quote")),
            recommended_quote=_round(recommended_quote),
            estimated_low_quote=_round(estimated_low_quote),
            estimated_high_quote=_round(estimated_high_quote),
            cost_floor=_round(cost_floor),
            gross_profit=_round(gross_profit),
            gross_margin_rate=_round(gross_margin_rate, 4),
            sample_size=sample_size,
            coverage_rate=_round(coverage_rate),
            confidence_level=confidence_level,
            fallback_level_code=fallback_level_code,
            context_json={
                "freight_no": context.freight.freight_no if context.freight is not None else None,
                "source_evidence_count": len(context.source_evidence),
            },
            input_json=payload,
            advanced_config_json=payload.get("advanced_config"),
            route_evidence_json=route_evidence,
            sample_evidence_json=sample_evidence,
            result_json=result_payload,
            lineage_json=lineage,
            not_computable_reasons_json=reasons,
            recommended_actions_json=[item.model_dump(mode="json") for item in actions],
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        self.db.add(record)
        await self.db.flush()
        response = PricingDecisionResponse(
            record_id=int(record.id),
            record_no=record.record_no,
            record_type_code=record_type_code,
            status_code=status_code,
            computable=status_code != "NOT_COMPUTABLE",
            decision_code=decision_code,
            conclusion=conclusion,
            metrics=metrics or [],
            cost_floor=_round(cost_floor),
            recommended_quote=_round(recommended_quote),
            estimated_low_quote=_round(estimated_low_quote),
            estimated_high_quote=_round(estimated_high_quote),
            gross_profit=_round(gross_profit),
            gross_margin_rate=_round(gross_margin_rate, 4),
            sample_size=sample_size,
            coverage_rate=_round(coverage_rate),
            confidence_level=confidence_level,
            fallback_level_code=fallback_level_code,
            route_evidence=route_evidence,
            sample_evidence=sample_evidence,
            factor_breakdown=factor_breakdown or [],
            comparable_samples=comparable_samples or [],
            fallback_trace=fallback_trace or [],
            quality_warnings=quality_warnings or [],
            lineage=lineage,
            not_computable_reasons=reasons,
            recommended_actions=actions,
            generated_at=now,
        )
        await self.db.commit()
        return response

    @staticmethod
    def _quote_actions(*, can_estimate: bool, can_quote: bool) -> list[PricingRecommendedAction]:
        return [
            PricingRecommendedAction(action_code="ADJUST_OWNER_QUOTE", title="按推荐船主价上限议价", enabled=can_quote),
            PricingRecommendedAction(
                action_code="OPEN_RATE_ESTIMATOR",
                title="转入运价预估测算",
                target_route="/analysis/rate-estimator",
                enabled=can_estimate,
            ),
        ]

    @staticmethod
    def _estimate_actions(enabled: bool) -> list[PricingRecommendedAction]:
        return [
            PricingRecommendedAction(
                action_code="OPEN_QUOTE_SIMULATOR",
                title="带入智能报价测算",
                target_route="/analysis/quote-simulator",
                enabled=enabled,
            )
        ]
