"""Scoring rules for vessel candidate fit analysis."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from app.models.vessel import (
    VesselCandidateAnalysisItem,
    VesselLatestPositionSnapshot,
    VesselNodeObservationVessel,
    VesselProfileSummary,
    VesselRouteSegmentMatchSample,
)
from app.modules.vessel.schemas import VesselCandidateAnalysisCreateRequest


CONFIDENCE_ORDER = {"UNKNOWN": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
QUALITY_LEVELS_BY_THRESHOLD = {
    "HIGH": ["HIGH", "GOOD"],
    "MEDIUM": ["HIGH", "MEDIUM", "GOOD", "REVIEW"],
}


class VesselCandidateScoringMixin:
    """Candidate scoring, confidence, and value classification rules."""

    def _score_summary(
        self,
        summary: VesselProfileSummary,
        *,
        payload: VesselCandidateAnalysisCreateRequest,
        context: Any,
        latest_position: VesselLatestPositionSnapshot | None,
        node_sample: VesselNodeObservationVessel | None,
        route_sample: VesselRouteSegmentMatchSample | None,
        constraint_status: str,
        coverage_rate: Decimal | None,
    ) -> VesselCandidateAnalysisItem | None:
        risk_reasons: list[str] = []
        uncertainty: list[str] = []
        not_computable: list[str] = []
        data_sources = ["VESSEL_SUMMARY"]
        spatial_score, node_distance = self._spatial_score(context, payload, latest_position, node_sample, uncertainty, not_computable)
        route_score, route_match_score, direction_consistency = self._route_score(context, route_sample, uncertainty, not_computable)
        if node_sample is not None:
            data_sources.append("VESSEL_NODE_OBSERVATION")
        if latest_position is not None:
            data_sources.append("AIS_LATEST_POSITION")
        if route_sample is not None:
            data_sources.append("VESSEL_ROUTE_SEGMENT_OBSERVATION")
        score_parts = {
            "SPATIAL_DISTANCE": spatial_score,
            "ROUTE_TRAJECTORY": route_score,
            "DEADWEIGHT": self._deadweight_score(summary, context, payload, not_computable),
            "SHIP_TYPE_CARGO": self._ship_type_score(summary, payload, not_computable),
            "DRAFT_NAVIGATION": self._navigation_score(constraint_status, uncertainty, not_computable),
            "RISK_COMPLIANCE": self._risk_score(summary, risk_reasons, not_computable),
            "DATA_QUALITY": self._level_score(summary.data_quality_level, {"HIGH": "10", "MEDIUM": "7", "LOW": "3"}, "4"),
            "CONTACT_TRUST": self._level_score(summary.contact_trust_level, {"HIGH": "5", "MEDIUM": "3"}, "1"),
        }
        freshness = (latest_position.freshness_level if latest_position is not None else summary.ais_freshness_level) or "UNKNOWN"
        cap = self._confidence_cap(freshness, summary.risk_level, constraint_status, coverage_rate, uncertainty)
        fit_score = sum(score_parts.values(), Decimal("0"))
        confidence_level = self._item_confidence(cap, summary, not_computable, uncertainty)
        value_level = self._candidate_value(fit_score, confidence_level, freshness, summary.risk_level, constraint_status, not_computable)
        return VesselCandidateAnalysisItem(
            analysis_id=0,
            vessel_profile_id=summary.vessel_profile_id,
            mmsi=summary.current_mmsi,
            ship_name=summary.ship_name,
            ship_type_code=summary.ship_type_code,
            deadweight_ton=summary.deadweight_ton,
            design_draft_m=summary.design_draft_m,
            latest_position_time=latest_position.position_time if latest_position is not None else summary.latest_position_time,
            ais_freshness_level=freshness,
            risk_level=summary.risk_level,
            quality_level=summary.data_quality_level,
            fit_score=fit_score.quantize(Decimal("0.01")),
            candidate_value_level=value_level,
            confidence_level=confidence_level,
            node_distance_km=node_distance,
            route_match_score=route_match_score,
            direction_consistency=direction_consistency,
            constraint_status_code=constraint_status,
            score_parts_json={key: float(value) for key, value in score_parts.items()},
            risk_reasons_json=self._dedupe(risk_reasons),
            uncertainty_reasons_json=self._dedupe(uncertainty),
            not_computable_reasons_json=self._dedupe(not_computable),
            data_sources_json=self._dedupe(data_sources),
            created_at=datetime.utcnow(),
        )

    def _spatial_score(
        self,
        context: Any,
        payload: VesselCandidateAnalysisCreateRequest,
        latest_position: VesselLatestPositionSnapshot | None,
        node_sample: VesselNodeObservationVessel | None,
        uncertainty: list[str],
        not_computable: list[str],
    ) -> tuple[Decimal, Decimal | None]:
        if context.origin_node_id is None and context.region_id is None:
            return Decimal("25"), None
        max_distance = payload.filters.max_node_distance_km or Decimal("50")
        if node_sample is not None and node_sample.distance_km is not None:
            distance = Decimal(str(node_sample.distance_km))
            freshness = node_sample.freshness_level or "UNKNOWN"
            if freshness in {"STALE", "EXPIRED", "UNKNOWN"}:
                uncertainty.append(f"NODE_SAMPLE_{freshness}")
                return Decimal("6"), distance
            return (Decimal("10") + max(Decimal("0"), Decimal("1") - distance / max_distance) * Decimal("15")).quantize(Decimal("0.01")), distance
        if latest_position is not None:
            uncertainty.append("SPATIAL_ONLY_LATEST_POSITION")
            return Decimal("8"), None
        not_computable.append("SPATIAL_SNAPSHOT_MISSING")
        return Decimal("0"), None

    def _route_score(
        self,
        context: Any,
        route_sample: VesselRouteSegmentMatchSample | None,
        uncertainty: list[str],
        not_computable: list[str],
    ) -> tuple[Decimal, Decimal | None, Decimal | None]:
        if context.route_id is None and context.plan_id is None:
            return Decimal("15"), None, None
        if route_sample is None:
            not_computable.append("TRACK_COVERAGE_INSUFFICIENT")
            return Decimal("0"), None, None
        match = Decimal(str(route_sample.match_score or 0))
        direction = Decimal(str(route_sample.direction_consistency)) if route_sample.direction_consistency is not None else None
        score = match / Decimal("100") * Decimal("15")
        if route_sample.confidence_level in {"LOW", "UNKNOWN"} or route_sample.match_status_code == "LOW_CONFIDENCE":
            uncertainty.append("ROUTE_MATCH_LOW_CONFIDENCE")
            score = min(Decimal("6"), score)
        return score.quantize(Decimal("0.01")), match, direction

    def _deadweight_score(
        self,
        summary: VesselProfileSummary,
        context: Any,
        payload: VesselCandidateAnalysisCreateRequest,
        not_computable: list[str],
    ) -> Decimal:
        deadweight = Decimal(str(summary.deadweight_ton)) if summary.deadweight_ton is not None else None
        target = context.tonnage or payload.filters.min_deadweight_ton
        if deadweight is None:
            not_computable.append("DEADWEIGHT_MISSING")
            return Decimal("0")
        return Decimal("15") if target is None or deadweight >= target else (max(Decimal("0"), deadweight / target) * Decimal("15")).quantize(Decimal("0.01"))

    def _ship_type_score(self, summary: VesselProfileSummary, payload: VesselCandidateAnalysisCreateRequest, not_computable: list[str]) -> Decimal:
        if not summary.ship_type_code:
            not_computable.append("SHIP_TYPE_MISSING")
            return Decimal("0")
        return Decimal("3") if payload.filters.ship_type_codes and summary.ship_type_code not in payload.filters.ship_type_codes else Decimal("10")

    def _navigation_score(self, status: str, uncertainty: list[str], not_computable: list[str]) -> Decimal:
        scores = {"AVAILABLE": "10", "WARNING": "6", "BLOCKED": "0", "NOT_APPLICABLE": "8", "STALE": "4", "UNKNOWN": "2", "MISSING_SOURCE": "2"}
        markers = {
            "WARNING": (uncertainty, "NAVIGATION_CONSTRAINT_WARNING"),
            "BLOCKED": (not_computable, "NAVIGATION_CONSTRAINT_BLOCKED"),
            "STALE": (uncertainty, "NAVIGATION_CONSTRAINT_STALE"),
            "UNKNOWN": (not_computable, "CONSTRAINT_SOURCE_MISSING"),
            "MISSING_SOURCE": (not_computable, "CONSTRAINT_SOURCE_MISSING"),
        }
        if status in markers:
            markers[status][0].append(markers[status][1])
        return Decimal(scores.get(status, "6"))

    def _risk_score(self, summary: VesselProfileSummary, risk_reasons: list[str], not_computable: list[str]) -> Decimal:
        risk = summary.risk_level or "UNKNOWN"
        if risk in {"MEDIUM", "HIGH"}:
            risk_reasons.append(f"RISK_{risk}")
        if risk == "UNKNOWN":
            not_computable.append("RISK_UNKNOWN")
        return self._level_score(risk, {"LOW": "10", "MEDIUM": "5", "HIGH": "0"}, "3")

    def _confidence_cap(
        self,
        freshness: str,
        risk_level: str,
        constraint_status: str,
        coverage_rate: Decimal | None,
        uncertainty: list[str],
    ) -> str:
        cap = "HIGH"
        if freshness in {"STALE", "EXPIRED", "UNKNOWN"}:
            uncertainty.append(f"AIS_{freshness}")
            cap = self._min_confidence(cap, "LOW" if freshness in {"EXPIRED", "UNKNOWN"} else "MEDIUM")
        for enabled, level in (
            (risk_level == "HIGH", "LOW"),
            (constraint_status in {"UNKNOWN", "MISSING_SOURCE"}, "MEDIUM"),
            (coverage_rate is not None and coverage_rate < Decimal("50"), "LOW"),
        ):
            if enabled:
                cap = self._min_confidence(cap, level)
        return cap

    def _candidate_value(
        self,
        fit_score: Decimal,
        confidence_level: str,
        freshness: str,
        risk_level: str,
        constraint_status: str,
        not_computable: list[str],
    ) -> str:
        high_blocked = (
            CONFIDENCE_ORDER.get(confidence_level, 0) < CONFIDENCE_ORDER["MEDIUM"]
            or freshness in {"STALE", "EXPIRED", "UNKNOWN"}
            or risk_level in {"HIGH", "UNKNOWN"}
            or constraint_status in {"UNKNOWN", "MISSING_SOURCE"}
            or bool(not_computable)
        )
        if fit_score >= Decimal("80") and not high_blocked:
            return "HIGH"
        return "MEDIUM" if fit_score >= Decimal("60") else "LOW"

    def _item_confidence(self, cap: str, summary: VesselProfileSummary, not_computable: list[str], uncertainty: list[str]) -> str:
        level = "HIGH"
        for enabled, candidate in (
            (summary.data_quality_level in {"MEDIUM", "UNKNOWN"}, "MEDIUM"),
            (summary.data_quality_level == "LOW" or summary.risk_level == "UNKNOWN", "LOW"),
            (bool(not_computable), "LOW"),
            (bool(uncertainty), "MEDIUM"),
            (True, cap),
        ):
            if enabled:
                level = self._min_confidence(level, candidate)
        return level

    def _aggregate_confidence(self, levels: list[str], coverage_rate: Decimal | None) -> str:
        if not levels:
            return "UNKNOWN"
        if coverage_rate is not None and coverage_rate < Decimal("50"):
            return "LOW"
        if any(level == "HIGH" for level in levels) and not any(level in {"LOW", "UNKNOWN"} for level in levels):
            return "HIGH"
        return "MEDIUM" if any(level in {"MEDIUM", "HIGH"} for level in levels) else "LOW"

    @staticmethod
    def _level_score(value: str | None, scores: dict[str, str], default: str) -> Decimal:
        return Decimal(scores.get(value or "UNKNOWN", default))

    def _allowed_quality_levels(self, threshold: str) -> list[str]:
        return QUALITY_LEVELS_BY_THRESHOLD.get(threshold, ["HIGH", "MEDIUM", "GOOD", "REVIEW", "LOW", "UNKNOWN"])

    def _min_confidence(self, left: str, right: str) -> str:
        return left if CONFIDENCE_ORDER.get(left, 0) <= CONFIDENCE_ORDER.get(right, 0) else right

    def _dedupe(self, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value for value in values if value))
