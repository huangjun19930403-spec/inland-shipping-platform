from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from typing import Any

from app.models import NavigationGraphEdge, NavigationGraphEdgeConstraint

PLANNING_MODES = {"RECOMMENDED", "SHORTEST", "SAFEST", "LOCK_AVOIDING"}
HARD_BLOCK_REASON_LABELS = {
    "EDGE_DISABLED": "Edge is disabled for routing",
    "EDGE_CLOSED": "Edge is closed by an active blocking constraint",
    "VSL_DRAFT_EXCEEDS_LIMIT": "Vessel draft exceeds edge limit",
    "VSL_TONNAGE_EXCEEDS_LIMIT": "Vessel tonnage exceeds edge limit",
    "VSL_AIR_DRAFT_EXCEEDS_LIMIT": "Vessel air draft exceeds edge limit",
    "VSL_BEAM_EXCEEDS_LIMIT": "Vessel beam exceeds edge limit",
    "VSL_LENGTH_EXCEEDS_LIMIT": "Vessel length exceeds edge limit",
}


@dataclass(slots=True)
class RouteEdgeCostBreakdown:
    edge_id: int
    distance_cost: float
    quality_penalty: float
    unknown_constraint_penalty: float
    lock_penalty: float
    bridge_penalty: float
    vessel_constraint_penalty: float
    direction_penalty: float
    total_cost: float
    reason_codes: list[str]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in list(payload.items()):
            if isinstance(value, float):
                payload[key] = round(value, 6)
        return payload

    def scaled(self, ratio: float, *, length_km: float | None = None) -> "RouteEdgeCostBreakdown":
        scale = max(0.0, min(1.0, float(ratio)))
        distance_cost = float(length_km) if length_km is not None else self.distance_cost * scale
        quality_penalty = self.quality_penalty * scale
        unknown_constraint_penalty = self.unknown_constraint_penalty * scale
        lock_penalty = self.lock_penalty * scale
        bridge_penalty = self.bridge_penalty * scale
        vessel_constraint_penalty = self.vessel_constraint_penalty * scale
        direction_penalty = self.direction_penalty * scale
        total_cost = (
            distance_cost
            + quality_penalty
            + unknown_constraint_penalty
            + lock_penalty
            + bridge_penalty
            + vessel_constraint_penalty
            + direction_penalty
        )
        return replace(
            self,
            distance_cost=distance_cost,
            quality_penalty=quality_penalty,
            unknown_constraint_penalty=unknown_constraint_penalty,
            lock_penalty=lock_penalty,
            bridge_penalty=bridge_penalty,
            vessel_constraint_penalty=vessel_constraint_penalty,
            direction_penalty=direction_penalty,
            total_cost=max(0.001, total_cost),
        )


def normalize_planning_mode(value: str | None) -> str:
    mode = (value or "RECOMMENDED").upper()
    if mode == "AVOID_LOCKS":
        return "LOCK_AVOIDING"
    if mode not in PLANNING_MODES:
        return "RECOMMENDED"
    return mode


def _float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _vessel_value(vessel_profile: dict[str, Any] | None, key: str) -> float | None:
    if not vessel_profile:
        return None
    return _float(vessel_profile.get(key))


def hard_block_reason(
    edge: NavigationGraphEdge,
    *,
    constraints: list[NavigationGraphEdgeConstraint] | None = None,
    vessel_profile: dict[str, Any] | None = None,
) -> str | None:
    if not edge.routing_enabled:
        return "EDGE_DISABLED"
    if any(
        constraint.constraint_type_code == "CLOSED" and constraint.is_blocking
        for constraint in (constraints or [])
    ):
        return "EDGE_CLOSED"
    draft = _vessel_value(vessel_profile, "draft_m")
    tonnage = _vessel_value(vessel_profile, "deadweight_ton")
    air_draft = _vessel_value(vessel_profile, "air_draft_m")
    beam = _vessel_value(vessel_profile, "beam_m")
    length = _vessel_value(vessel_profile, "length_m")
    if draft is not None and edge.max_allowed_draft_m is not None and draft > float(edge.max_allowed_draft_m):
        return "VSL_DRAFT_EXCEEDS_LIMIT"
    if tonnage is not None and edge.max_allowed_tonnage is not None and tonnage > float(edge.max_allowed_tonnage):
        return "VSL_TONNAGE_EXCEEDS_LIMIT"
    if air_draft is not None and edge.max_air_draft_m is not None and air_draft > float(edge.max_air_draft_m):
        return "VSL_AIR_DRAFT_EXCEEDS_LIMIT"
    if beam is not None and edge.max_beam_m is not None and beam > float(edge.max_beam_m):
        return "VSL_BEAM_EXCEEDS_LIMIT"
    if length is not None and edge.max_length_m is not None and length > float(edge.max_length_m):
        return "VSL_LENGTH_EXCEEDS_LIMIT"
    return None


class RouteCostCalculator:
    def calculate(
        self,
        edge: NavigationGraphEdge,
        *,
        planning_mode_code: str,
        length_km: float | None = None,
        direction_code: str = "FORWARD",
    ) -> RouteEdgeCostBreakdown:
        mode = normalize_planning_mode(planning_mode_code)
        distance_cost = max(float(length_km if length_km is not None else edge.length_km or 0.001), 0.001)
        reason_codes: list[str] = []

        quality_code = edge.quality_code or "UNKNOWN"
        quality_penalty = 0.0
        if mode == "SHORTEST":
            quality_penalty = 0.0
        elif mode == "SAFEST":
            quality_penalty = {
                "READY": 0.0,
                "READY_WITH_WARNING": 0.8,
                "LOW_CONFIDENCE": 2.0,
                "NEED_REVIEW": 3.0,
                "SHORT_EDGE_REVIEW": 2.5,
            }.get(quality_code, 1.2) * distance_cost
        else:
            quality_penalty = {
                "READY": 0.0,
                "READY_WITH_WARNING": 0.2,
                "LOW_CONFIDENCE": 0.5,
                "NEED_REVIEW": 1.0,
                "SHORT_EDGE_REVIEW": 1.0,
            }.get(quality_code, 0.3) * distance_cost
        if quality_penalty > 0:
            reason_codes.append(f"QUALITY_{quality_code}")

        unknown_constraint_penalty = 0.0
        if edge.unknown_constraint_flag and mode != "SHORTEST":
            unknown_constraint_penalty = (1.5 if mode == "SAFEST" else 0.3) * distance_cost
            reason_codes.append("UNKNOWN_CONSTRAINT_DATA")

        lock_penalty = 0.0
        if edge.lock_required:
            lock_penalty = 8.0 if mode == "LOCK_AVOIDING" else (4.0 if mode == "SAFEST" else 2.0)
            if mode == "SHORTEST":
                lock_penalty = 0.0
            if lock_penalty > 0:
                reason_codes.append("LOCK_REQUIRED")

        bridge_count = int(edge.bridge_count or 0)
        bridge_penalty = 0.0 if mode == "SHORTEST" else bridge_count * (0.5 if mode == "SAFEST" else 0.2)
        if bridge_penalty > 0:
            reason_codes.append("BRIDGE_PRESENT")

        confidence_score = int(edge.confidence_score or 0)
        vessel_constraint_penalty = 0.0
        if mode in {"RECOMMENDED", "SAFEST", "LOCK_AVOIDING"} and confidence_score < 80:
            vessel_constraint_penalty = ((80 - confidence_score) / 100.0) * distance_cost
            if mode == "SAFEST":
                vessel_constraint_penalty *= 2
            reason_codes.append("LOW_EDGE_CONFIDENCE")

        direction_penalty = 0.0
        if direction_code == "REVERSE" and edge.direction_code == "BIDIRECTIONAL" and mode == "SAFEST":
            direction_penalty = 0.05 * distance_cost

        total_cost = (
            distance_cost
            + quality_penalty
            + unknown_constraint_penalty
            + lock_penalty
            + bridge_penalty
            + vessel_constraint_penalty
            + direction_penalty
        )
        return RouteEdgeCostBreakdown(
            edge_id=int(edge.id),
            distance_cost=distance_cost,
            quality_penalty=quality_penalty,
            unknown_constraint_penalty=unknown_constraint_penalty,
            lock_penalty=lock_penalty,
            bridge_penalty=bridge_penalty,
            vessel_constraint_penalty=vessel_constraint_penalty,
            direction_penalty=direction_penalty,
            total_cost=max(0.001, total_cost),
            reason_codes=reason_codes,
        )
