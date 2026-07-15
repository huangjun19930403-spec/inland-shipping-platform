"""Unified route trajectory cache for navigation-generated tracks."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession
from shapely.geometry import Point

from app.models import NavigationRouteQualityIssue, NavigationRouteRequest, NavigationRouteResult, NavigationRouteTrajectoryCache
from app.modules.navigation.engine.graph_loader import NavigationGraphLoader
from app.modules.navigation.engine.geo import point_distance_m
from app.modules.navigation.engine.types import RoutePoint
from app.modules.navigation.schemas import (
    NavigationRouteGenerateRequest,
    NavigationRouteGenerateResponse,
    NavigationRouteIssueResponse,
)


RETURNABLE_CACHE_STATUSES = {"VALID"}
HARD_ROUTE_ISSUE_CODES = {
    "PATH_OUT_OF_WATER",
    "PATH_WATER_COVERAGE_WARNING",
    "PATH_OUT_OF_CHANNEL_BOUNDARY",
    "PATH_CHANNEL_BOUNDARY_WARNING",
    "ROUTE_STRAIGHT_LINE_FALLBACK",
    "ROUTE_LONG_STRAIGHT_SEGMENT_REVIEW",
    "ROUTE_FOLDBACK_REVIEW",
    "ROUTE_SELF_INTERSECTION_REVIEW",
    "GRAPH_DISCONNECTED",
    "NO_PATH_FOUND",
    "NO_ACTIVE_GRAPH_VERSION",
    "NO_ROUTING_EDGE_IN_BBOX",
    "NO_ROUTING_EDGE_IN_EXPANDED_BBOX",
    "ORIGIN_TOO_FAR_FROM_GRAPH",
    "DESTINATION_TOO_FAR_FROM_GRAPH",
}


class NavigationTrajectoryCacheService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_returnable(
        self,
        *,
        origin: RoutePoint,
        destination: RoutePoint,
        body: NavigationRouteGenerateRequest,
        planning_mode_code: str,
        vessel_profile: dict[str, Any] | None,
    ) -> NavigationRouteTrajectoryCache | None:
        graph_version_context_id = await self._graph_version_context_id(body, response_graph_version_id=None)
        keys = self.route_keys(
            origin=origin,
            destination=destination,
            body=body,
            planning_mode_code=planning_mode_code,
            vessel_profile=vessel_profile,
            graph_version_context_id=graph_version_context_id,
        )
        row = await self.session.scalar(
            (
                select(NavigationRouteTrajectoryCache)
                .where(
                    NavigationRouteTrajectoryCache.route_key == keys["route_key"],
                    NavigationRouteTrajectoryCache.cache_status_code.in_(RETURNABLE_CACHE_STATUSES),
                    NavigationRouteTrajectoryCache.geometry_json.is_not(None),
                )
                .order_by(
                    case((NavigationRouteTrajectoryCache.cache_status_code == "VALID", 0), else_=1),
                    NavigationRouteTrajectoryCache.quality_score.desc().nullslast(),
                    NavigationRouteTrajectoryCache.generated_at.desc().nullslast(),
                    NavigationRouteTrajectoryCache.id.desc(),
                )
            )
        )
        if row is None:
            return None
        row.last_used_at = datetime.now(UTC).replace(tzinfo=None)
        row.use_count = int(row.use_count or 0) + 1
        await self.session.flush()
        return row

    async def persist_cache_hit_response(
        self,
        *,
        request_row: NavigationRouteRequest,
        cache_row: NavigationRouteTrajectoryCache,
        include_explain: bool,
    ) -> NavigationRouteGenerateResponse:
        source_type = self._cached_source_type(cache_row)
        summary = {
            **(cache_row.validation_summary_json or {}),
            "engine": cache_row.engine_code or source_type or cache_row.provider_code,
            "provider_code": cache_row.provider_code,
            "source_type_code": source_type,
            "cache_hit": True,
            "trajectory_cache_id": cache_row.id,
            "hifleet_cache_id": cache_row.hifleet_cache_id,
            "cached_from_route_result_id": cache_row.original_route_result_id,
            "cache_status_code": cache_row.cache_status_code,
            "own_algorithm_summary": cache_row.own_algorithm_summary_json,
        }
        result_row = NavigationRouteResult(
            request_id=request_row.id,
            result_no=1,
            result_type_code=cache_row.planning_mode_code or "RECOMMENDED",
            status_code="SUCCESS",
            geometry_json=cache_row.geometry_json,
            distance_km=cache_row.distance_km,
            estimated_duration_hour=cache_row.estimated_duration_hour,
            edge_ids=list(cache_row.edge_ids or []),
            channel_ids=list(cache_row.channel_ids or []),
            passed_node_ids=list(cache_row.passed_node_ids or []),
            passed_lock_count=int(cache_row.passed_lock_count or 0),
            passed_bridge_count=int(cache_row.passed_bridge_count or 0),
            quality_score=cache_row.quality_score,
            quality_code=cache_row.quality_code,
            quality_summary_json=summary,
            provider_code=cache_row.provider_code,
            engine_code=cache_row.engine_code or source_type,
            reference_result_id=cache_row.original_route_result_id,
        )
        self.session.add(result_row)
        request_row.status_code = "SUCCESS"
        request_row.graph_version_id = cache_row.graph_version_id
        request_row.error_code = None
        request_row.error_message = None
        await self.session.flush()
        issues = self._issue_responses(cache_row.issue_summary_json)
        for issue in issues:
            self.session.add(
                NavigationRouteQualityIssue(
                    route_result_id=result_row.id,
                    issue_type_code=issue.issue_type_code,
                    severity_code=issue.severity_code,
                    geometry_json=None,
                    message=issue.message,
                    suggestion=issue.suggestion,
                    related_edge_id=issue.related_edge_id,
                    related_node_id=issue.related_node_id,
                )
            )
        await self.session.commit()
        explain = {
            "engine": result_row.engine_code,
            "provider_code": result_row.provider_code,
            "source_type_code": source_type,
            "cache_hit": True,
            "trajectory_cache_id": cache_row.id,
            "hifleet_cache_id": cache_row.hifleet_cache_id,
            "cache_status_code": cache_row.cache_status_code,
            "cached_from_route_result_id": cache_row.original_route_result_id,
            "own_algorithm_summary": cache_row.own_algorithm_summary_json,
        }
        return NavigationRouteGenerateResponse(
            request_id=request_row.id,
            result_id=result_row.id,
            graph_version_id=request_row.graph_version_id,
            status_code="SUCCESS",
            provider_code=result_row.provider_code,
            source_type_code=source_type,
            cache_hit=True,
            hifleet_cache_id=cache_row.hifleet_cache_id,
            trajectory_cache_id=cache_row.id,
            quality_code=result_row.quality_code,
            quality_score=result_row.quality_score,
            geometry_json=result_row.geometry_json,
            distance_km=float(result_row.distance_km) if result_row.distance_km is not None else None,
            estimated_duration_hour=float(result_row.estimated_duration_hour)
            if result_row.estimated_duration_hour is not None
            else None,
            edge_ids=list(result_row.edge_ids or []),
            channel_ids=list(result_row.channel_ids or []),
            passed_node_ids=list(result_row.passed_node_ids or []),
            passed_lock_count=result_row.passed_lock_count,
            passed_bridge_count=result_row.passed_bridge_count,
            issues=issues,
            explain=explain if include_explain else None,
        )

    async def store_response(
        self,
        *,
        origin: RoutePoint,
        destination: RoutePoint,
        body: NavigationRouteGenerateRequest,
        planning_mode_code: str,
        vessel_profile: dict[str, Any] | None,
        response: NavigationRouteGenerateResponse,
        request_row: NavigationRouteRequest,
    ) -> NavigationRouteTrajectoryCache:
        graph_version_context_id = await self._graph_version_context_id(body, response_graph_version_id=response.graph_version_id)
        keys = self.route_keys(
            origin=origin,
            destination=destination,
            body=body,
            planning_mode_code=planning_mode_code,
            vessel_profile=vessel_profile,
            graph_version_context_id=graph_version_context_id,
        )
        row = await self.session.scalar(
            select(NavigationRouteTrajectoryCache).where(NavigationRouteTrajectoryCache.route_key == keys["route_key"])
        )
        if row is None:
            row = NavigationRouteTrajectoryCache(route_key=keys["route_key"], normalized_pair_key=keys["normalized_pair_key"])
            self.session.add(row)
        now = datetime.now(UTC).replace(tzinfo=None)
        source_type = response.source_type_code or response.provider_code
        geometry = _valid_line_string_or_none(response.geometry_json)
        issues = [issue.model_dump() for issue in response.issues]
        validation_summary = {
            "issue_codes": [issue.issue_type_code for issue in response.issues],
            "hard_issue_codes": sorted(
                {issue.issue_type_code for issue in response.issues if issue.issue_type_code in HARD_ROUTE_ISSUE_CODES}
            ),
            "point_count": len(_line_points(geometry)),
            "max_segment_km": _max_segment_km(geometry),
        }
        row.normalized_pair_key = keys["normalized_pair_key"]
        row.transport_mode_code = "WATER"
        row.planning_mode_code = planning_mode_code
        row.graph_version_id = response.graph_version_id
        row.graph_context_code = (
            "EXPLICIT"
            if body.graph_version_id is not None
            else f"AUTO_ACTIVE:{graph_version_context_id}" if graph_version_context_id is not None else "AUTO_ACTIVE"
        )
        row.vessel_profile_hash = _payload_hash(vessel_profile)
        row.origin_ref_type_code = origin.ref_type_code
        row.origin_ref_id = origin.ref_id
        row.origin_name = origin.name
        row.origin_lng = origin.longitude
        row.origin_lat = origin.latitude
        row.destination_ref_type_code = destination.ref_type_code
        row.destination_ref_id = destination.ref_id
        row.destination_name = destination.name
        row.destination_lng = destination.longitude
        row.destination_lat = destination.latitude
        row.provider_code = response.provider_code
        row.source_type_code = source_type
        row.engine_code = source_type
        row.cache_status_code = self._cache_status(response)
        row.status_code = response.status_code
        row.quality_code = response.quality_code
        row.quality_score = response.quality_score
        row.geometry_json = geometry
        row.geometry_hash = _payload_hash(geometry)
        row.distance_km = response.distance_km
        row.estimated_duration_hour = response.estimated_duration_hour
        row.point_count = len(_line_points(geometry))
        row.max_segment_km = validation_summary["max_segment_km"]
        row.edge_ids = list(response.edge_ids or [])
        row.channel_ids = list(response.channel_ids or [])
        row.passed_node_ids = list(response.passed_node_ids or [])
        row.passed_lock_count = int(response.passed_lock_count or 0)
        row.passed_bridge_count = int(response.passed_bridge_count or 0)
        row.issue_summary_json = issues
        row.validation_summary_json = validation_summary
        row.own_algorithm_summary_json = self._own_summary(response)
        row.hifleet_summary_json = self._hifleet_summary(response)
        row.hifleet_cache_id = response.hifleet_cache_id
        row.original_route_request_id = response.request_id
        row.original_route_result_id = response.result_id
        row.error_code = response.error_code
        row.error_message = response.error_message
        row.raw_request_json = body.model_dump(mode="json")
        row.raw_response_json = response.model_dump(mode="json")
        row.generated_at = now
        await self.session.flush()
        return row

    def route_keys(
        self,
        *,
        origin: RoutePoint,
        destination: RoutePoint,
        body: NavigationRouteGenerateRequest,
        planning_mode_code: str,
        vessel_profile: dict[str, Any] | None,
        graph_version_context_id: int | None = None,
    ) -> dict[str, str]:
        origin_key = _point_key(origin.longitude, origin.latitude)
        destination_key = _point_key(destination.longitude, destination.latitude)
        resolved_graph_version_id = body.graph_version_id if body.graph_version_id is not None else graph_version_context_id
        graph_key = f"GRAPH:{resolved_graph_version_id}" if resolved_graph_version_id is not None else "GRAPH:AUTO_ACTIVE"
        vessel_key = f"VESSEL:{_payload_hash(vessel_profile) or 'NONE'}"
        parts = ["NAV_TRAJECTORY_V1", "WATER", planning_mode_code, graph_key, vessel_key, origin_key, destination_key]
        pair = "||".join(sorted([origin_key, destination_key]))
        pair_parts = ["NAV_TRAJECTORY_V1", "WATER", planning_mode_code, graph_key, vessel_key, pair]
        return {
            "route_key": "|".join(parts),
            "normalized_pair_key": "|".join(pair_parts),
        }

    async def _graph_version_context_id(
        self,
        body: NavigationRouteGenerateRequest,
        *,
        response_graph_version_id: int | None,
    ) -> int | None:
        if body.graph_version_id is not None:
            return int(body.graph_version_id)
        if response_graph_version_id is not None:
            return int(response_graph_version_id)
        try:
            graph_version = await NavigationGraphLoader(self.session).select_graph_version(None)
        except Exception:  # noqa: BLE001
            return None
        return int(graph_version.id)

    def _cache_status(self, response: NavigationRouteGenerateResponse) -> str:
        if response.status_code != "SUCCESS" or not response.geometry_json:
            return "FAILED"
        if response.source_type_code == "CENTERLINE_SEED_FALLBACK":
            return "NEED_REVIEW"
        if response.provider_code == "HIFLEET" or response.source_type_code in {"HIFLEET_CACHE", "HIFLEET_API"}:
            return "REFERENCE_READY"
        hard_codes = {issue.issue_type_code for issue in response.issues if issue.issue_type_code in HARD_ROUTE_ISSUE_CODES}
        if hard_codes:
            return "NEED_REVIEW"
        if response.quality_code in {"READY", "READY_WITH_WARNING"}:
            return "VALID"
        return "NEED_REVIEW"

    def _cached_source_type(self, cache_row: NavigationRouteTrajectoryCache) -> str | None:
        if cache_row.provider_code == "HIFLEET":
            return "HIFLEET_CACHE"
        return cache_row.source_type_code or cache_row.engine_code

    def _issue_responses(self, payload: list | None) -> list[NavigationRouteIssueResponse]:
        issues: list[NavigationRouteIssueResponse] = []
        for item in payload or []:
            if not isinstance(item, dict):
                continue
            try:
                issues.append(NavigationRouteIssueResponse(**item))
            except Exception:  # noqa: BLE001
                continue
        return issues

    def _own_summary(self, response: NavigationRouteGenerateResponse) -> dict[str, Any] | None:
        if response.provider_code != "NAVIGATION_ENGINE":
            explain = response.explain if isinstance(response.explain, dict) else {}
            original = {
                key: explain.get(key)
                for key in (
                    "original_result_id",
                    "original_error_code",
                    "original_quality_code",
                    "original_issue_codes",
                    "original_hard_issue_codes",
                )
                if explain.get(key) is not None
            }
            return original or None
        return {
            "route_request_id": response.request_id,
            "route_result_id": response.result_id,
            "graph_version_id": response.graph_version_id,
            "quality_code": response.quality_code,
            "quality_score": response.quality_score,
        }

    def _hifleet_summary(self, response: NavigationRouteGenerateResponse) -> dict[str, Any] | None:
        if response.provider_code != "HIFLEET" and response.source_type_code not in {"HIFLEET_CACHE", "HIFLEET_API"}:
            return None
        return {
            "hifleet_cache_id": response.hifleet_cache_id,
            "source_type_code": response.source_type_code,
            "cache_hit": response.cache_hit,
        }


def _point_key(lng: float, lat: float) -> str:
    return f"POINT:{float(lng):.6f},{float(lat):.6f}"


def _payload_hash(payload: Any) -> str | None:
    if payload is None:
        return None
    normalized = _normalize_payload(payload)
    raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def _normalize_payload(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, float):
        return round(value, 8)
    if isinstance(value, dict):
        return {str(key): _normalize_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_payload(item) for item in value]
    return value


def _valid_line_string_or_none(geometry: dict | None) -> dict[str, Any] | None:
    points = _line_points(geometry)
    if len(points) < 2:
        return None
    return {"type": "LineString", "coordinates": points}


def _line_points(geometry: dict | None) -> list[list[float]]:
    if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
        return []
    points: list[list[float]] = []
    for item in geometry.get("coordinates") or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            lng = float(item[0])
            lat = float(item[1])
        except (TypeError, ValueError):
            continue
        if -180 <= lng <= 180 and -90 <= lat <= 90 and (not points or points[-1] != [lng, lat]):
            points.append([lng, lat])
    return points


def _max_segment_km(geometry: dict | None) -> float | None:
    points = _line_points(geometry)
    if len(points) < 2:
        return None
    longest = 0.0
    for start, end in zip(points[:-1], points[1:]):
        distance_km = point_distance_m(Point(start), Point(end)) / 1000.0
        longest = max(longest, distance_km)
    if not math.isfinite(longest):
        return None
    return round(longest, 4)
