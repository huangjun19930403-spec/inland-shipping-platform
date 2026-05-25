from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from shapely.geometry import shape

from app.core.exceptions import ValidationError
from app.models import (
    NavigationChannelWaterBodyMatch,
    NavigationRouteQualityIssue,
    NavigationRouteRequest,
    NavigationRouteResult,
    NavigationWaterBody,
)
from app.models.address import NavigationChannelBoundary, NavigationConstraintPoint, TransportNode
from app.modules.navigation.engine.constrained_search import ConstrainedGraphSearch
from app.modules.navigation.engine.graph_loader import NavigationGraphLoader
from app.modules.navigation.engine.path_assembler import PathAssembler
from app.modules.navigation.engine.path_validator import PathValidator
from app.modules.navigation.engine.quality_scoring import QualityScorer
from app.modules.navigation.engine.snapper import GraphSnapper
from app.modules.navigation.engine.types import RouteIssue, RoutePoint, RoutingEngineError, SnapResult
from app.modules.navigation.schemas import (
    NavigationEndpointRequest,
    NavigationRouteGenerateRequest,
    NavigationRouteGenerateResponse,
    NavigationRouteIssueResponse,
    NavigationSnapResponse,
)


class NavigationRoutingEngineService:
    DEFAULT_SPEED_KMH = 10.0
    DEFAULT_LOCK_WAIT_HOUR = 1.0
    RETRYABLE_GRAPH_ERROR_CODES = {
        "NO_ROUTING_EDGE_IN_EXPANDED_BBOX",
        "NO_GRAPH_NEAR_ORIGIN",
        "NO_GRAPH_NEAR_DESTINATION",
        "ORIGIN_TOO_FAR_FROM_GRAPH",
        "DESTINATION_TOO_FAR_FROM_GRAPH",
        "GRAPH_DISCONNECTED",
    }

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.loader = NavigationGraphLoader(session)
        self.snapper = GraphSnapper()
        self.searcher = ConstrainedGraphSearch()
        self.assembler = PathAssembler()
        self.validator = PathValidator()
        self.scorer = QualityScorer()

    async def generate_route(
        self,
        body: NavigationRouteGenerateRequest,
        *,
        created_by: int | None = None,
    ) -> NavigationRouteGenerateResponse:
        origin = await self._resolve_endpoint(body.origin, role="ORIGIN")
        destination = await self._resolve_endpoint(body.destination, role="DESTINATION")
        vessel_profile = self._vessel_profile(body)
        request_row = NavigationRouteRequest(
            request_no=self._request_no(),
            origin_lng=origin.longitude,
            origin_lat=origin.latitude,
            origin_name=origin.name,
            origin_ref_type_code=origin.ref_type_code,
            origin_ref_id=origin.ref_id,
            destination_lng=destination.longitude,
            destination_lat=destination.latitude,
            destination_name=destination.name,
            destination_ref_type_code=destination.ref_type_code,
            destination_ref_id=destination.ref_id,
            vessel_profile_json=vessel_profile,
            routing_preference_code=body.routing_preference_code.upper(),
            graph_version_id=body.graph_version_id,
            status_code="FAILED",
            created_by=created_by,
        )
        self.session.add(request_row)
        await self.session.flush()

        origin_snap: SnapResult | None = None
        destination_snap: SnapResult | None = None
        attempted_graph_version_ids: list[int] = []
        try:
            graph_versions = await self.loader.list_candidate_graph_versions(body.graph_version_id)
            last_error: RoutingEngineError | None = None
            for graph_version in graph_versions:
                request_row.graph_version_id = graph_version.id
                attempted_graph_version_ids.append(int(graph_version.id))
                origin_snap = None
                destination_snap = None
                try:
                    response = await self._generate_with_graph_version(
                        request_row=request_row,
                        graph_version=graph_version,
                        origin=origin,
                        destination=destination,
                        vessel_profile=vessel_profile,
                        attempted_graph_version_ids=attempted_graph_version_ids,
                    )
                    return response
                except RoutingEngineError as exc:
                    last_error = exc
                    if body.graph_version_id is not None or exc.error_code not in self.RETRYABLE_GRAPH_ERROR_CODES:
                        return await self._persist_failure(
                            request_row,
                            exc,
                            origin_snap,
                            destination_snap,
                            attempted_graph_version_ids=attempted_graph_version_ids,
                        )
                    continue
            if last_error is not None:
                message = (
                    f"{last_error.message}; attempted graph versions: {attempted_graph_version_ids}"
                    if attempted_graph_version_ids
                    else last_error.message
                )
                return await self._persist_failure(
                    request_row,
                    RoutingEngineError(last_error.error_code, message, issues=last_error.issues),
                    origin_snap,
                    destination_snap,
                    attempted_graph_version_ids=attempted_graph_version_ids,
                )
            raise RoutingEngineError("NO_ACTIVE_GRAPH_VERSION", "No active READY navigation graph version is available")
        except RoutingEngineError as exc:
            return await self._persist_failure(
                request_row,
                exc,
                origin_snap,
                destination_snap,
                attempted_graph_version_ids=attempted_graph_version_ids,
            )

    async def _generate_with_graph_version(
        self,
        *,
        request_row: NavigationRouteRequest,
        graph_version,
        origin: RoutePoint,
        destination: RoutePoint,
        vessel_profile: dict[str, Any] | None,
        attempted_graph_version_ids: list[int],
    ) -> NavigationRouteGenerateResponse:
        loaded_graph = await self.loader.load_graph(
            graph_version=graph_version,
            origin=(origin.longitude, origin.latitude),
            destination=(destination.longitude, destination.latitude),
        )
        origin_snap = self.snapper.snap(role="ORIGIN", point=origin, graph=loaded_graph)
        destination_snap = self.snapper.snap(role="DESTINATION", point=destination, graph=loaded_graph)
        search_result = self.searcher.search(
            graph=loaded_graph,
            origin_snap=origin_snap,
            destination_snap=destination_snap,
            vessel_profile=vessel_profile,
            routing_preference_code=request_row.routing_preference_code,
        )
        assembled = self.assembler.assemble(search_result)
        validation_issues = [
            *self.validator.validate_geometry(assembled.geometry_json),
            *(await self._validate_spatial_context(assembled.geometry_json, assembled.channel_ids)),
        ]
        quality = self.scorer.score(
            origin_snap=origin_snap,
            destination_snap=destination_snap,
            search_result=search_result,
            validation_issues=validation_issues,
        )
        duration_detail = self._duration_detail(assembled.distance_km, assembled.passed_lock_count)
        request_row.status_code = "SUCCESS" if quality.quality_code != "FAILED" else "FAILED"
        result_row = NavigationRouteResult(
            request_id=request_row.id,
            result_no=1,
            result_type_code="RECOMMENDED",
            status_code=quality.quality_code,
            geometry_json=assembled.geometry_json,
            distance_km=assembled.distance_km,
            estimated_duration_hour=duration_detail["estimated_duration_hour"],
            edge_ids=assembled.edge_ids,
            channel_ids=assembled.channel_ids,
            passed_node_ids=assembled.passed_node_ids,
            passed_lock_count=assembled.passed_lock_count,
            passed_bridge_count=assembled.passed_bridge_count,
            quality_score=quality.quality_score,
            quality_code=quality.quality_code,
            quality_summary_json={
                "engine": "NAVIGATION_ROUTING_ENGINE",
                "origin_snap": origin_snap.as_dict(),
                "destination_snap": destination_snap.as_dict(),
                "issue_count": len(quality.issues),
                "search_cost": search_result.total_cost,
                "graph_load_bbox": loaded_graph.load_bbox,
                "graph_load_margin_degree": loaded_graph.load_margin_degree,
                "loaded_node_count": loaded_graph.loaded_node_count,
                "loaded_edge_count": loaded_graph.loaded_edge_count,
                "attempted_graph_version_ids": list(attempted_graph_version_ids),
                "duration_detail": duration_detail,
            },
            provider_code="NAVIGATION_ENGINE",
            engine_code="NAVIGATION_ROUTING_ENGINE_V1",
        )
        self.session.add(result_row)
        await self.session.flush()
        await self._insert_issues(result_row.id, quality.issues)
        await self.session.commit()
        return self._success_response(request_row, result_row, origin_snap, destination_snap, quality.issues)

    async def _resolve_endpoint(self, endpoint: NavigationEndpointRequest, *, role: str) -> RoutePoint:
        endpoint_type = endpoint.endpoint_type_code.upper()
        if endpoint_type == "CITY":
            raise ValidationError("CITY_ENDPOINT_NOT_ALLOWED")
        if endpoint_type == "TRANSPORT_NODE":
            node_id = endpoint.transport_node_id or endpoint.ref_id
            node = await self.session.scalar(select(TransportNode).where(TransportNode.id == node_id))
            if node is None or node.longitude is None or node.latitude is None:
                raise ValidationError(f"{role}_NOT_RESOLVED")
            return self._checked_point(
                float(node.longitude),
                float(node.latitude),
                name=endpoint.name or node.name,
                ref_type_code="TRANSPORT_NODE",
                ref_id=node.id,
            )
        if endpoint_type == "CONSTRAINT_POINT":
            point_id = endpoint.constraint_point_id or endpoint.ref_id
            point = await self.session.scalar(select(NavigationConstraintPoint).where(NavigationConstraintPoint.id == point_id))
            if point is None:
                raise ValidationError(f"{role}_NOT_RESOLVED")
            return self._checked_point(
                float(point.longitude),
                float(point.latitude),
                name=endpoint.name or point.name,
                ref_type_code="CONSTRAINT_POINT",
                ref_id=point.id,
            )
        if endpoint_type in {"LNG_LAT", "MANUAL_POINT"}:
            if endpoint.longitude is None or endpoint.latitude is None:
                raise ValidationError(f"{role}_NOT_RESOLVED")
            return self._checked_point(
                endpoint.longitude,
                endpoint.latitude,
                name=endpoint.name,
                ref_type_code=endpoint_type,
                ref_id=endpoint.ref_id,
            )
        raise ValidationError(f"{role}_NOT_RESOLVED")

    def _checked_point(
        self,
        longitude: float,
        latitude: float,
        *,
        name: str | None,
        ref_type_code: str | None,
        ref_id: int | None,
    ) -> RoutePoint:
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            raise ValidationError("POINT_COORDINATE_INVALID")
        return RoutePoint(longitude=longitude, latitude=latitude, name=name, ref_type_code=ref_type_code, ref_id=ref_id)

    def _vessel_profile(self, body: NavigationRouteGenerateRequest) -> dict[str, Any] | None:
        if body.vessel_profile_json:
            return body.vessel_profile_json
        if body.vessel_profile:
            return body.vessel_profile.model_dump(exclude_none=True)
        return None

    async def _persist_failure(
        self,
        request_row: NavigationRouteRequest,
        exc: RoutingEngineError,
        origin_snap: SnapResult | None,
        destination_snap: SnapResult | None,
        *,
        attempted_graph_version_ids: list[int] | None = None,
    ) -> NavigationRouteGenerateResponse:
        request_row.status_code = "FAILED"
        request_row.error_code = exc.error_code
        request_row.error_message = exc.message
        result_row = NavigationRouteResult(
            request_id=request_row.id,
            result_no=1,
            result_type_code="RECOMMENDED",
            status_code="FAILED",
            quality_score=0,
            quality_code="FAILED",
            quality_summary_json={
                "engine": "NAVIGATION_ROUTING_ENGINE",
                "origin_snap": origin_snap.as_dict() if origin_snap else None,
                "destination_snap": destination_snap.as_dict() if destination_snap else None,
                "error_code": exc.error_code,
                "attempted_graph_version_ids": list(attempted_graph_version_ids or []),
            },
            provider_code="NAVIGATION_ENGINE",
            engine_code="NAVIGATION_ROUTING_ENGINE_V1",
        )
        self.session.add(result_row)
        await self.session.flush()
        await self._insert_issues(result_row.id, exc.issues)
        await self.session.commit()
        return NavigationRouteGenerateResponse(
            request_id=request_row.id,
            result_id=result_row.id,
            graph_version_id=request_row.graph_version_id,
            status_code="FAILED",
            quality_code="FAILED",
            quality_score=0,
            origin_snap=self._snap_response(origin_snap),
            destination_snap=self._snap_response(destination_snap),
            issues=[self._issue_response(issue) for issue in exc.issues],
            error_code=exc.error_code,
            error_message=exc.message,
        )

    async def _insert_issues(self, route_result_id: int, issues: list[RouteIssue]) -> None:
        seen: set[tuple[str, int | None, int | None, str]] = set()
        for issue in issues:
            key = (issue.issue_type_code, issue.related_edge_id, issue.related_node_id, issue.message)
            if key in seen:
                continue
            seen.add(key)
            self.session.add(
                NavigationRouteQualityIssue(
                    route_result_id=route_result_id,
                    issue_type_code=issue.issue_type_code,
                    severity_code=issue.severity_code,
                    geometry_json=issue.geometry_json,
                    message=issue.message,
                    suggestion=issue.suggestion,
                    related_edge_id=issue.related_edge_id,
                    related_node_id=issue.related_node_id,
                )
            )

    def _success_response(
        self,
        request_row: NavigationRouteRequest,
        result_row: NavigationRouteResult,
        origin_snap: SnapResult,
        destination_snap: SnapResult,
        issues: list[RouteIssue],
    ) -> NavigationRouteGenerateResponse:
        return NavigationRouteGenerateResponse(
            request_id=request_row.id,
            result_id=result_row.id,
            graph_version_id=request_row.graph_version_id,
            status_code=request_row.status_code,
            quality_code=result_row.quality_code,
            quality_score=result_row.quality_score,
            geometry_json=result_row.geometry_json,
            distance_km=float(result_row.distance_km) if result_row.distance_km is not None else None,
            estimated_duration_hour=float(result_row.estimated_duration_hour) if result_row.estimated_duration_hour is not None else None,
            edge_ids=list(result_row.edge_ids or []),
            channel_ids=list(result_row.channel_ids or []),
            passed_node_ids=list(result_row.passed_node_ids or []),
            passed_lock_count=result_row.passed_lock_count,
            passed_bridge_count=result_row.passed_bridge_count,
            origin_snap=self._snap_response(origin_snap),
            destination_snap=self._snap_response(destination_snap),
            issues=[self._issue_response(issue) for issue in issues],
        )

    def _snap_response(self, snap: SnapResult | None) -> NavigationSnapResponse | None:
        if snap is None:
            return None
        return NavigationSnapResponse(**snap.as_dict())

    def _issue_response(self, issue: RouteIssue) -> NavigationRouteIssueResponse:
        return NavigationRouteIssueResponse(
            issue_type_code=issue.issue_type_code,
            severity_code=issue.severity_code,
            message=issue.message,
            suggestion=issue.suggestion,
            related_edge_id=issue.related_edge_id,
            related_node_id=issue.related_node_id,
        )

    def _estimated_duration(self, distance_km: float | None, passed_lock_count: int = 0) -> float | None:
        return self._duration_detail(distance_km, passed_lock_count)["estimated_duration_hour"]

    def _duration_detail(self, distance_km: float | None, passed_lock_count: int = 0) -> dict[str, float | int | None]:
        if distance_km is None:
            return {
                "distance_km": None,
                "default_speed_kmh": self.DEFAULT_SPEED_KMH,
                "base_sailing_hour": None,
                "passed_lock_count": int(passed_lock_count or 0),
                "lock_wait_hour_each": self.DEFAULT_LOCK_WAIT_HOUR,
                "lock_wait_total_hour": None,
                "estimated_duration_hour": None,
            }
        base_sailing_hour = float(distance_km) / self.DEFAULT_SPEED_KMH
        lock_count = int(passed_lock_count or 0)
        lock_wait_total = lock_count * self.DEFAULT_LOCK_WAIT_HOUR
        estimated = base_sailing_hour + lock_wait_total
        return {
            "distance_km": round(float(distance_km), 3),
            "default_speed_kmh": self.DEFAULT_SPEED_KMH,
            "base_sailing_hour": round(base_sailing_hour, 3),
            "passed_lock_count": lock_count,
            "lock_wait_hour_each": self.DEFAULT_LOCK_WAIT_HOUR,
            "lock_wait_total_hour": round(lock_wait_total, 3),
            "estimated_duration_hour": round(estimated, 2),
        }

    def _request_no(self) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        return f"NRR-{timestamp}-{uuid.uuid4().hex[:8].upper()}"

    async def _validate_spatial_context(self, geometry_json: dict, channel_ids: list[int]) -> list[RouteIssue]:
        if not channel_ids:
            return self.validator.validate_spatial_context(
                geometry_json,
                water_geometries=[],
                boundary_geometries=[],
            )
        route_geometry = shape(geometry_json)
        min_lng, min_lat, max_lng, max_lat = route_geometry.bounds
        water_rows = list(
            (
                await self.session.execute(
                    select(NavigationWaterBody)
                    .join(
                        NavigationChannelWaterBodyMatch,
                        NavigationChannelWaterBodyMatch.water_body_id == NavigationWaterBody.id,
                    )
                    .where(
                        NavigationChannelWaterBodyMatch.channel_id.in_(channel_ids),
                        NavigationChannelWaterBodyMatch.is_current.is_(True),
                        NavigationWaterBody.is_enabled.is_(True),
                        NavigationWaterBody.geometry_wgs84_json.is_not(None),
                        NavigationWaterBody.bbox_max_lng >= min_lng,
                        NavigationWaterBody.bbox_min_lng <= max_lng,
                        NavigationWaterBody.bbox_max_lat >= min_lat,
                        NavigationWaterBody.bbox_min_lat <= max_lat,
                    )
                    .distinct()
                    .limit(300)
                )
            ).scalars()
        )
        boundary_rows = list(
            (
                await self.session.execute(
                    select(NavigationChannelBoundary).where(
                        NavigationChannelBoundary.channel_id.in_(channel_ids),
                        NavigationChannelBoundary.is_current.is_(True),
                        NavigationChannelBoundary.geometry_status_code == "AVAILABLE",
                        NavigationChannelBoundary.geometry_json.is_not(None),
                    )
                )
            ).scalars()
        )
        water_geometries = [shape(row.geometry_wgs84_json) for row in water_rows if row.geometry_wgs84_json]
        boundary_geometries = [shape(row.geometry_json) for row in boundary_rows if row.geometry_json]
        return self.validator.validate_spatial_context(
            geometry_json,
            water_geometries=water_geometries,
            boundary_geometries=boundary_geometries,
        )
