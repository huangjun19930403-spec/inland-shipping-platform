from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import networkx as nx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from shapely.geometry import shape

from app.core.exceptions import ValidationError
from app.models import (
    NavigationChannelWaterBodyMatch,
    NavigationGraphEdge,
    NavigationRouteQualityIssue,
    NavigationRouteRequest,
    NavigationRouteResult,
    NavigationWaterBody,
)
from app.models.address import NavigationChannelBoundary, NavigationConstraintPoint, TransportNode
from app.modules.navigation.engine.graph_loader import NavigationGraphLoader
from app.modules.navigation.engine.path_assembler import PathAssembler
from app.modules.navigation.engine.path_validator import PathValidator
from app.modules.navigation.engine.quality_scoring import QualityScorer
from app.modules.navigation.engine.route_alternatives import RouteAlternativesGenerator
from app.modules.navigation.engine.route_cost import normalize_planning_mode
from app.modules.navigation.engine.route_explainer import RouteExplainer
from app.modules.navigation.engine.route_post_processor import RoutePostProcessor
from app.modules.navigation.engine.route_search import PreparedRouteGraph, RouteSearch
from app.modules.navigation.engine.snapper import GraphSnapper
from app.modules.navigation.engine.types import RouteIssue, RoutePoint, RoutingEngineError, SnapResult
from app.modules.navigation.schemas import (
    NavigationEndpointRequest,
    NavigationRouteAlternativeResponse,
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
        self.searcher = RouteSearch()
        self.alternatives = RouteAlternativesGenerator(self.searcher)
        self.assembler = PathAssembler()
        self.validator = PathValidator()
        self.post_processor = RoutePostProcessor()
        self.scorer = QualityScorer()
        self.explainer = RouteExplainer()

    async def generate_route(
        self,
        body: NavigationRouteGenerateRequest,
        *,
        created_by: int | None = None,
    ) -> NavigationRouteGenerateResponse:
        origin = await self._resolve_endpoint(body.origin, role="ORIGIN")
        destination = await self._resolve_endpoint(body.destination, role="DESTINATION")
        vessel_profile = self._vessel_profile(body)
        planning_mode_code = self._planning_mode(body)
        requested_path_count = max(1, min(int(body.alternative_count or 1), 5)) if body.include_alternatives else 1
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
            routing_preference_code=planning_mode_code,
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
                        planning_mode_code=planning_mode_code,
                        requested_path_count=requested_path_count,
                        include_explain=body.include_explain,
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
                            planning_mode_code=planning_mode_code,
                            include_explain=body.include_explain,
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
                    RoutingEngineError(last_error.error_code, message, issues=last_error.issues, explain=last_error.explain),
                    origin_snap,
                    destination_snap,
                    attempted_graph_version_ids=attempted_graph_version_ids,
                    planning_mode_code=planning_mode_code,
                    include_explain=body.include_explain,
                )
            raise RoutingEngineError("NO_ACTIVE_GRAPH_VERSION", "No active READY navigation graph version is available")
        except RoutingEngineError as exc:
            return await self._persist_failure(
                request_row,
                exc,
                origin_snap,
                destination_snap,
                attempted_graph_version_ids=attempted_graph_version_ids,
                planning_mode_code=planning_mode_code,
                include_explain=body.include_explain,
            )

    async def _generate_with_graph_version(
        self,
        *,
        request_row: NavigationRouteRequest,
        graph_version,
        origin: RoutePoint,
        destination: RoutePoint,
        vessel_profile: dict[str, Any] | None,
        planning_mode_code: str,
        requested_path_count: int,
        include_explain: bool,
        attempted_graph_version_ids: list[int],
    ) -> NavigationRouteGenerateResponse:
        loaded_graph = await self.loader.load_graph(
            graph_version=graph_version,
            origin=(origin.longitude, origin.latitude),
            destination=(destination.longitude, destination.latitude),
        )
        origin_snap = self.snapper.snap(role="ORIGIN", point=origin, graph=loaded_graph)
        destination_snap = self.snapper.snap(role="DESTINATION", point=destination, graph=loaded_graph)
        try:
            prepared_graph = self.searcher.prepare_graph(
                graph=loaded_graph,
                origin_snap=origin_snap,
                destination_snap=destination_snap,
                vessel_profile=vessel_profile,
                planning_mode_code=planning_mode_code,
            )

            if requested_path_count > 1:
                search_results = self.alternatives.generate(
                    prepared=prepared_graph,
                    planning_mode_code=planning_mode_code,
                    requested_count=requested_path_count,
                )
            else:
                search_results = [
                    self.searcher.result_from_node_path(
                        prepared=prepared_graph,
                        node_path=self._primary_node_path(prepared_graph, planning_mode_code),
                        planning_mode_code=planning_mode_code,
                        algorithm_code="DIJKSTRA" if planning_mode_code == "SHORTEST" else "A_STAR",
                    )
                ]
        except RoutingEngineError as exc:
            exc.explain.setdefault(
                "snap_summary",
                {
                    "origin_snap": origin_snap.as_dict(),
                    "destination_snap": destination_snap.as_dict(),
                },
            )
            raise

        persisted: list[tuple[NavigationRouteResult, list[RouteIssue], dict[str, Any]]] = []
        main_result_row: NavigationRouteResult | None = None
        for index, search_result in enumerate(search_results, start=1):
            assembled = self.assembler.assemble(search_result)
            validation_issues = [
                *self.validator.validate_geometry(assembled.geometry_json),
                *self.post_processor.validate(assembled.geometry_json, origin_snap=origin_snap, destination_snap=destination_snap),
                *(await self._validate_spatial_context(assembled.geometry_json, assembled.channel_ids, assembled.edge_ids)),
            ]
            quality = self.scorer.score(
                origin_snap=origin_snap,
                destination_snap=destination_snap,
                search_result=search_result,
                validation_issues=validation_issues,
            )
            result_issues = [*quality.issues, *search_result.issues]
            duration_detail = self._duration_detail(assembled.distance_km, assembled.passed_lock_count)
            explain = self.explainer.explain_success(
                search_result=search_result,
                issues=result_issues,
                alternative_rank=index,
                alternative_count=len(search_results),
            )
            result_row = NavigationRouteResult(
                request_id=request_row.id,
                result_no=index,
                result_type_code=planning_mode_code if index == 1 else "ALTERNATIVE",
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
                    "issue_count": len(result_issues),
                    "search_cost": search_result.total_cost,
                    "graph_load_bbox": loaded_graph.load_bbox,
                    "graph_load_margin_degree": loaded_graph.load_margin_degree,
                    "loaded_node_count": loaded_graph.loaded_node_count,
                    "loaded_edge_count": loaded_graph.loaded_edge_count,
                    "attempted_graph_version_ids": list(attempted_graph_version_ids),
                    "duration_detail": duration_detail,
                    "planning_mode_code": planning_mode_code,
                    "cost_total": explain["cost_total"],
                    "cost_breakdown_summary": explain["cost_breakdown_summary"],
                    "edge_cost_breakdowns": explain["edge_cost_breakdowns"],
                    "why_selected": explain["why_selected"],
                    "blocked_edge_summary": explain["blocked_edge_summary"],
                    "search_summary": explain["search_summary"],
                    "alternative_rank": index,
                    "alternative_count": len(search_results),
                },
                provider_code="NAVIGATION_ENGINE",
                engine_code="NAVIGATION_ROUTING_ENGINE_V2",
            )
            self.session.add(result_row)
            await self.session.flush()
            if index == 1:
                main_result_row = result_row
            elif main_result_row is not None:
                result_row.reference_result_id = main_result_row.id
            await self._insert_issues(result_row.id, result_issues)
            persisted.append((result_row, result_issues, explain))

        if main_result_row is None:
            raise RoutingEngineError("NO_PATH_FOUND", "Path search did not return a primary result")
        request_row.status_code = "SUCCESS" if main_result_row.quality_code != "FAILED" else "FAILED"
        await self.session.commit()
        return self._success_response(
            request_row,
            main_result_row,
            origin_snap,
            destination_snap,
            persisted[0][1],
            alternatives=persisted[1:],
            explain=persisted[0][2] if include_explain else None,
            include_explain=include_explain,
        )

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

    def _planning_mode(self, body: NavigationRouteGenerateRequest) -> str:
        if body.planning_mode_code == "RECOMMENDED" and body.routing_preference_code.upper() == "AVOID_LOCKS":
            return "LOCK_AVOIDING"
        return normalize_planning_mode(body.planning_mode_code)

    def _primary_node_path(self, prepared_graph: PreparedRouteGraph, planning_mode_code: str) -> list[str]:
        try:
            if planning_mode_code == "SHORTEST":
                return nx.dijkstra_path(
                    prepared_graph.nx_graph,
                    prepared_graph.start_key,
                    prepared_graph.end_key,
                    weight="weight",
                )
            return nx.astar_path(
                prepared_graph.nx_graph,
                prepared_graph.start_key,
                prepared_graph.end_key,
                heuristic=lambda a, b: self.searcher.heuristic_km(prepared_graph.nx_graph, a, b),
                weight="weight",
            )
        except nx.NetworkXNoPath as exc:
            raise self.searcher.no_path_error(prepared_graph) from exc
        except nx.NodeNotFound as exc:
            raise RoutingEngineError(
                "NO_PATH_FOUND",
                "Snapped endpoint is not present in loaded graph",
                explain={
                    "blocked_edge_summary": prepared_graph.blocked_edge_summary,
                    "search_summary": {
                        "loaded_node_count": prepared_graph.nx_graph.number_of_nodes(),
                        "loaded_edge_count": prepared_graph.nx_graph.number_of_edges(),
                        "usable_edge_count": prepared_graph.usable_edge_count,
                    },
                },
            ) from exc

    async def _persist_failure(
        self,
        request_row: NavigationRouteRequest,
        exc: RoutingEngineError,
        origin_snap: SnapResult | None,
        destination_snap: SnapResult | None,
        *,
        attempted_graph_version_ids: list[int] | None = None,
        planning_mode_code: str = "RECOMMENDED",
        include_explain: bool = True,
    ) -> NavigationRouteGenerateResponse:
        request_row.status_code = "FAILED"
        request_row.error_code = exc.error_code
        request_row.error_message = exc.message
        failure_explain = self.explainer.explain_failure(
            exc=exc,
            origin_snap=origin_snap,
            destination_snap=destination_snap,
            attempted_graph_version_ids=attempted_graph_version_ids,
        )
        result_row = NavigationRouteResult(
            request_id=request_row.id,
            result_no=1,
            result_type_code=planning_mode_code,
            status_code="FAILED",
            quality_score=0,
            quality_code="FAILED",
            quality_summary_json={
                "engine": "NAVIGATION_ROUTING_ENGINE",
                "origin_snap": origin_snap.as_dict() if origin_snap else None,
                "destination_snap": destination_snap.as_dict() if destination_snap else None,
                "error_code": exc.error_code,
                "attempted_graph_version_ids": list(attempted_graph_version_ids or []),
                "planning_mode_code": planning_mode_code,
                "failure_explain": failure_explain,
            },
            provider_code="NAVIGATION_ENGINE",
            engine_code="NAVIGATION_ROUTING_ENGINE_V2",
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
            explain=failure_explain if include_explain else None,
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
        *,
        alternatives: list[tuple[NavigationRouteResult, list[RouteIssue], dict[str, Any]]] | None = None,
        explain: dict[str, Any] | None = None,
        include_explain: bool = True,
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
            alternatives=[
                self._alternative_response(row, alt_issues, alt_explain if include_explain else None)
                for row, alt_issues, alt_explain in (alternatives or [])
            ],
            explain=explain,
        )

    def _alternative_response(
        self,
        result_row: NavigationRouteResult,
        issues: list[RouteIssue],
        explain: dict[str, Any] | None,
    ) -> NavigationRouteAlternativeResponse:
        return NavigationRouteAlternativeResponse(
            result_id=result_row.id,
            result_no=result_row.result_no,
            result_type_code=result_row.result_type_code,
            quality_code=result_row.quality_code,
            quality_score=result_row.quality_score,
            distance_km=float(result_row.distance_km) if result_row.distance_km is not None else None,
            estimated_duration_hour=float(result_row.estimated_duration_hour) if result_row.estimated_duration_hour is not None else None,
            edge_ids=list(result_row.edge_ids or []),
            channel_ids=list(result_row.channel_ids or []),
            passed_lock_count=result_row.passed_lock_count,
            passed_bridge_count=result_row.passed_bridge_count,
            issues=[self._issue_response(issue) for issue in issues],
            explain=explain,
            geometry_json=result_row.geometry_json,
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

    async def _validate_spatial_context(self, geometry_json: dict, channel_ids: list[int], edge_ids: list[int]) -> list[RouteIssue]:
        if not channel_ids:
            return self.validator.validate_spatial_context(
                geometry_json,
                water_geometries=[],
                boundary_geometries=[],
            )
        route_geometry = shape(geometry_json)
        min_lng, min_lat, max_lng, max_lat = route_geometry.bounds
        water_body_ids = (
            select(NavigationWaterBody.id)
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
            .subquery()
        )
        water_rows = list(
            (
                await self.session.execute(
                    select(NavigationWaterBody).where(NavigationWaterBody.id.in_(select(water_body_ids.c.id)))
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
        water_geometries.extend(
            shape(row.geometry_json)
            for row in boundary_rows
            if row.geometry_json and str(row.coverage_policy_code or "").startswith("REVIER_WATER_BODY_UNION")
        )
        issues = self.validator.validate_spatial_context(
            geometry_json,
            water_geometries=water_geometries,
            boundary_geometries=boundary_geometries,
        )
        if await self._route_allows_boundary_review(edge_ids):
            issues = [
                RouteIssue(
                    "PATH_CHANNEL_BOUNDARY_WARNING",
                    "WARNING",
                    issue.message.replace(
                        "Route channel-boundary coverage is too low",
                        "Route channel-boundary coverage requires seed boundary review",
                    ),
                    suggestion="Seed-derived guide is outside the published boundary in places; review boundary and centerline alignment before safety use.",
                )
                if issue.issue_type_code == "PATH_OUT_OF_CHANNEL_BOUNDARY"
                else issue
                for issue in issues
            ]
        return issues

    async def _route_allows_boundary_review(self, edge_ids: list[int]) -> bool:
        if not edge_ids:
            return False
        rows = list(
            (
                await self.session.execute(
                    select(NavigationGraphEdge.source_type_code, NavigationGraphEdge.validation_summary_json).where(
                        NavigationGraphEdge.id.in_(edge_ids)
                    )
                )
            ).all()
        )
        if not rows:
            return False
        review_codes = {
            "GUIDE_PASSTHROUGH_BOUNDARY_REVIEW",
            "BOUNDARY_DERIVED_NEEDS_OPERATOR_REVIEW",
            "REVIER_DERIVED_NEEDS_OPERATOR_REVIEW",
            "REVIER_BRIDGE_WATER_AREA_NEEDS_REVIEW",
            "REVIER_COMPONENT_CONNECTOR_NEEDS_REVIEW",
        }
        review_edge_seen = False
        for source_type_code, summary in rows:
            if source_type_code == "TRANSPORT_NODE_CONNECTOR":
                continue
            issue_codes = summary.get("issue_codes") if isinstance(summary, dict) else None
            if not review_codes.intersection(issue_codes or []):
                return False
            review_edge_seen = True
        return review_edge_seen
