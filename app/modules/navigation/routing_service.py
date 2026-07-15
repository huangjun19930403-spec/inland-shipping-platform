from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import networkx as nx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from shapely.geometry import LineString, Point, shape

from app.core.exceptions import ValidationError
from app.integrations.http.route_geometry_types import RouteGeometryQuery
from app.models import (
    NavigationChannelCenterline,
    NavigationChannelWaterBodyMatch,
    NavigationGraphEdge,
    NavigationRouteQualityIssue,
    NavigationRouteRequest,
    NavigationRouteResult,
    NavigationWaterBody,
)
from app.models.address import NavigationChannelBoundary, NavigationConstraintPoint, TransportNode
from app.modules.navigation.engine.graph_loader import NavigationGraphLoader
from app.modules.navigation.engine.geo import line_length_km, line_segment_between, nearest_point_on_line, point_distance_m
from app.modules.navigation.engine.path_assembler import PathAssembler
from app.modules.navigation.engine.path_validator import PathValidator
from app.modules.navigation.engine.quality_scoring import QualityScorer
from app.modules.navigation.engine.route_alternatives import RouteAlternativesGenerator
from app.modules.navigation.engine.route_cost import normalize_planning_mode
from app.modules.navigation.engine.route_explainer import RouteExplainer
from app.modules.navigation.engine.route_post_processor import RoutePostProcessor
from app.modules.navigation.engine.route_search import PreparedRouteGraph, RouteSearch
from app.modules.navigation.engine.snapper import GraphSnapper
from app.modules.navigation.engine.types import RouteIssue, RoutePoint, RoutingEngineError, SearchResult, SnapResult
from app.modules.navigation.schemas import (
    NavigationEndpointRequest,
    NavigationRouteAlternativeResponse,
    NavigationRouteGenerateRequest,
    NavigationRouteGenerateResponse,
    NavigationRouteIssueResponse,
    NavigationSnapResponse,
)
from app.modules.navigation.services.hifleet_route_cache_service import HifleetRouteCacheService
from app.modules.navigation.services.trajectory_cache_service import HARD_ROUTE_ISSUE_CODES, NavigationTrajectoryCacheService
from app.modules.system.runtime_config import RuntimeConfigService


class NavigationRoutingEngineService:
    DEFAULT_SPEED_KMH = 10.0
    DEFAULT_LOCK_WAIT_HOUR = 1.0
    CENTERLINE_SEED_MAX_SNAP_M = 1000.0
    CENTERLINE_SEED_BBOX_MARGIN_DEGREE = 0.25
    CENTERLINE_SEED_CANDIDATE_LIMIT = 80
    HIFLEET_FALLBACK_MAX_SEGMENT_KM = RoutePostProcessor.LONG_SEGMENT_REVIEW_KM
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
            graph_version_id=None,
            status_code="FAILED",
            created_by=created_by,
        )
        self.session.add(request_row)
        await self.session.flush()

        trajectory_cache = NavigationTrajectoryCacheService(self.session)
        if not body.include_alternatives:
            cached = await trajectory_cache.get_returnable(
                origin=origin,
                destination=destination,
                body=body,
                planning_mode_code=planning_mode_code,
                vessel_profile=vessel_profile,
            )
            if cached is not None:
                return await trajectory_cache.persist_cache_hit_response(
                    request_row=request_row,
                    cache_row=cached,
                    include_explain=body.include_explain,
                )

        origin_snap: SnapResult | None = None
        destination_snap: SnapResult | None = None
        attempted_graph_version_ids: list[int] = []
        try:
            graph_versions = await self.loader.list_candidate_graph_versions(body.graph_version_id)
            preferred_graph_version_id = int(graph_versions[0].id) if graph_versions else None
            last_error: RoutingEngineError | None = None
            preferred_error: RoutingEngineError | None = None
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
                    return await self._finalize_response_with_cache(
                        response,
                        body=body,
                        request_row=request_row,
                        origin=origin,
                        destination=destination,
                        vessel_profile=vessel_profile,
                        planning_mode_code=planning_mode_code,
                        include_explain=body.include_explain,
                    )
                except RoutingEngineError as exc:
                    last_error = exc
                    if preferred_error is None:
                        preferred_error = exc
                    if body.graph_version_id is not None or exc.error_code not in self.RETRYABLE_GRAPH_ERROR_CODES:
                        failure_response = await self._persist_failure(
                            request_row,
                            exc,
                            origin_snap,
                            destination_snap,
                            attempted_graph_version_ids=attempted_graph_version_ids,
                            planning_mode_code=planning_mode_code,
                            include_explain=body.include_explain,
                        )
                        return await self._finalize_response_with_cache(
                            failure_response,
                            body=body,
                            request_row=request_row,
                            origin=origin,
                            destination=destination,
                            vessel_profile=vessel_profile,
                            planning_mode_code=planning_mode_code,
                            include_explain=body.include_explain,
                        )
                    continue
            if last_error is not None:
                if body.graph_version_id is None and preferred_graph_version_id is not None:
                    request_row.graph_version_id = preferred_graph_version_id
                selected_error = preferred_error or last_error
                message = (
                    self._multi_graph_failure_message(
                        selected_error=selected_error,
                        last_error=last_error,
                        attempted_graph_version_ids=attempted_graph_version_ids,
                    )
                    if attempted_graph_version_ids
                    else selected_error.message
                )
                explain = dict(selected_error.explain or {})
                if last_error is not selected_error:
                    explain["last_attempt_error_code"] = last_error.error_code
                    explain["last_attempt_error_message"] = last_error.message
                failure_response = await self._persist_failure(
                    request_row,
                    RoutingEngineError(selected_error.error_code, message, issues=selected_error.issues, explain=explain),
                    origin_snap,
                    destination_snap,
                    attempted_graph_version_ids=attempted_graph_version_ids,
                    planning_mode_code=planning_mode_code,
                    include_explain=body.include_explain,
                )
                return await self._finalize_response_with_cache(
                    failure_response,
                    body=body,
                    request_row=request_row,
                    origin=origin,
                    destination=destination,
                    vessel_profile=vessel_profile,
                    planning_mode_code=planning_mode_code,
                    include_explain=body.include_explain,
                )
            raise RoutingEngineError("NO_ACTIVE_GRAPH_VERSION", "No active READY navigation graph version is available")
        except RoutingEngineError as exc:
            failure_response = await self._persist_failure(
                request_row,
                exc,
                origin_snap,
                destination_snap,
                attempted_graph_version_ids=attempted_graph_version_ids,
                planning_mode_code=planning_mode_code,
                include_explain=body.include_explain,
            )
            return await self._finalize_response_with_cache(
                failure_response,
                body=body,
                request_row=request_row,
                origin=origin,
                destination=destination,
                vessel_profile=vessel_profile,
                planning_mode_code=planning_mode_code,
                include_explain=body.include_explain,
            )

    def _multi_graph_failure_message(
        self,
        *,
        selected_error: RoutingEngineError,
        last_error: RoutingEngineError,
        attempted_graph_version_ids: list[int],
    ) -> str:
        message = selected_error.message
        if last_error is not selected_error:
            message = (
                f"{message}; later graph attempt ended with {last_error.error_code}: {last_error.message}"
            )
        return f"{message}; attempted graph versions: {attempted_graph_version_ids}"

    async def _finalize_response_with_cache(
        self,
        response: NavigationRouteGenerateResponse,
        *,
        body: NavigationRouteGenerateRequest,
        request_row: NavigationRouteRequest,
        origin: RoutePoint,
        destination: RoutePoint,
        vessel_profile: dict[str, Any] | None,
        planning_mode_code: str,
        include_explain: bool,
    ) -> NavigationRouteGenerateResponse:
        local_response = await self._maybe_centerline_seed_fallback(
            response,
            request_row=request_row,
            origin=origin,
            destination=destination,
            planning_mode_code=planning_mode_code,
            include_explain=include_explain,
        )
        final_response = await self._maybe_hifleet_fallback(
            local_response,
            request_row=request_row,
            origin=origin,
            destination=destination,
            planning_mode_code=planning_mode_code,
            include_explain=include_explain,
        )
        try:
            cache_row = await NavigationTrajectoryCacheService(self.session).store_response(
                origin=origin,
                destination=destination,
                body=body,
                planning_mode_code=planning_mode_code,
                vessel_profile=vessel_profile,
                response=final_response,
                request_row=request_row,
            )
            await self.session.commit()
            final_response.trajectory_cache_id = cache_row.id
        except Exception:  # noqa: BLE001
            await self.session.rollback()
        return final_response

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
            self._attach_issue_edge_context(validation_issues, search_result)
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

    async def _maybe_hifleet_fallback(
        self,
        response: NavigationRouteGenerateResponse,
        *,
        request_row: NavigationRouteRequest,
        origin: RoutePoint,
        destination: RoutePoint,
        planning_mode_code: str,
        include_explain: bool,
    ) -> NavigationRouteGenerateResponse:
        if not self._requires_hifleet_fallback(response):
            return response
        try:
            query = RouteGeometryQuery(
                origin_lon=origin.longitude,
                origin_lat=origin.latitude,
                dest_lon=destination.longitude,
                dest_lat=destination.latitude,
                transport_mode="WATER",
                segment_type="NAVIGATION_ROUTE_FALLBACK",
            )
            hifleet = await HifleetRouteCacheService(
                self.session,
                runtime_config=RuntimeConfigService(self.session),
            ).get_or_generate(
                query,
                **self._route_point_cache_refs(origin, prefix="origin"),
                **self._route_point_cache_refs(destination, prefix="destination"),
            )
            return await self._persist_hifleet_fallback(
                request_row=request_row,
                original_response=response,
                hifleet=hifleet,
                planning_mode_code=planning_mode_code,
                include_explain=include_explain,
            )
        except Exception:  # noqa: BLE001
            await self.session.rollback()
            return response

    def _requires_hifleet_fallback(self, response: NavigationRouteGenerateResponse) -> bool:
        if response.status_code != "SUCCESS" or response.quality_code == "FAILED" or not response.geometry_json:
            return True
        return any(issue.issue_type_code in HARD_ROUTE_ISSUE_CODES for issue in response.issues)

    async def _maybe_centerline_seed_fallback(
        self,
        response: NavigationRouteGenerateResponse,
        *,
        request_row: NavigationRouteRequest,
        origin: RoutePoint,
        destination: RoutePoint,
        planning_mode_code: str,
        include_explain: bool,
    ) -> NavigationRouteGenerateResponse:
        if not self._requires_hifleet_fallback(response):
            return response
        try:
            candidate = await self._best_centerline_seed_route(
                origin=origin,
                destination=destination,
                planning_mode_code=planning_mode_code,
            )
            if candidate is None:
                return response
            return await self._persist_centerline_seed_fallback(
                request_row=request_row,
                original_response=response,
                candidate=candidate,
                planning_mode_code=planning_mode_code,
                include_explain=include_explain,
            )
        except Exception:  # noqa: BLE001
            await self.session.rollback()
            return response

    async def _best_centerline_seed_route(
        self,
        *,
        origin: RoutePoint,
        destination: RoutePoint,
        planning_mode_code: str,
    ) -> dict[str, Any] | None:
        rows = await self._candidate_centerlines(origin=origin, destination=destination)
        best: dict[str, Any] | None = None
        best_score: tuple[float, float] | None = None
        for row in rows:
            candidate = await self._centerline_seed_route_candidate(
                centerline=row,
                origin=origin,
                destination=destination,
                planning_mode_code=planning_mode_code,
            )
            if candidate is None:
                continue
            score = (
                float(candidate["origin_snap"].snap_distance_m) + float(candidate["destination_snap"].snap_distance_m),
                -float(candidate["quality_score"] or 0),
            )
            if best_score is None or score < best_score:
                best = candidate
                best_score = score
        return best

    async def _candidate_centerlines(
        self,
        *,
        origin: RoutePoint,
        destination: RoutePoint,
    ) -> list[NavigationChannelCenterline]:
        min_lng = min(origin.longitude, destination.longitude) - self.CENTERLINE_SEED_BBOX_MARGIN_DEGREE
        max_lng = max(origin.longitude, destination.longitude) + self.CENTERLINE_SEED_BBOX_MARGIN_DEGREE
        min_lat = min(origin.latitude, destination.latitude) - self.CENTERLINE_SEED_BBOX_MARGIN_DEGREE
        max_lat = max(origin.latitude, destination.latitude) + self.CENTERLINE_SEED_BBOX_MARGIN_DEGREE
        return list(
            (
                await self.session.execute(
                    select(NavigationChannelCenterline)
                    .where(
                        NavigationChannelCenterline.is_current.is_(True),
                        NavigationChannelCenterline.review_status_code == "PUBLISHED",
                        NavigationChannelCenterline.quality_code.in_({"READY", "READY_WITH_WARNING"}),
                        NavigationChannelCenterline.geometry_json.is_not(None),
                        NavigationChannelCenterline.bbox_max_lng >= min_lng,
                        NavigationChannelCenterline.bbox_min_lng <= max_lng,
                        NavigationChannelCenterline.bbox_max_lat >= min_lat,
                        NavigationChannelCenterline.bbox_min_lat <= max_lat,
                    )
                    .order_by(NavigationChannelCenterline.id.desc())
                    .limit(self.CENTERLINE_SEED_CANDIDATE_LIMIT)
                )
            ).scalars()
        )

    async def _centerline_seed_route_candidate(
        self,
        *,
        centerline: NavigationChannelCenterline,
        origin: RoutePoint,
        destination: RoutePoint,
        planning_mode_code: str,
    ) -> dict[str, Any] | None:
        try:
            line = shape(centerline.geometry_json)
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(line, LineString) or line.is_empty or len(line.coords) < 2:
            return None
        origin_point = Point(origin.longitude, origin.latitude)
        destination_point = Point(destination.longitude, destination.latitude)
        origin_snap_point = nearest_point_on_line(line, origin_point)
        destination_snap_point = nearest_point_on_line(line, destination_point)
        origin_snap_distance_m = point_distance_m(origin_point, origin_snap_point)
        destination_snap_distance_m = point_distance_m(destination_point, destination_snap_point)
        if (
            origin_snap_distance_m > self.CENTERLINE_SEED_MAX_SNAP_M
            or destination_snap_distance_m > self.CENTERLINE_SEED_MAX_SNAP_M
        ):
            return None

        centerline_segment = line_segment_between(line, origin_snap_point, destination_snap_point)
        route_line = self._line_with_endpoint_access(
            origin=origin_point,
            destination=destination_point,
            origin_snap=origin_snap_point,
            destination_snap=destination_snap_point,
            centerline_segment=centerline_segment,
        )
        if route_line.is_empty or len(route_line.coords) < 2:
            return None
        geometry_json = {"type": "LineString", "coordinates": [[float(lng), float(lat)] for lng, lat, *_ in route_line.coords]}
        origin_snap = SnapResult(
            role="ORIGIN",
            snap_type="CENTERLINE_SEED",
            snap_distance_m=origin_snap_distance_m,
            snap_confidence=self._snap_confidence(origin_snap_distance_m),
            snap_point=(float(origin_snap_point.x), float(origin_snap_point.y)),
            quality_code=self._snap_quality_code(origin_snap_distance_m),
        )
        destination_snap = SnapResult(
            role="DESTINATION",
            snap_type="CENTERLINE_SEED",
            snap_distance_m=destination_snap_distance_m,
            snap_confidence=self._snap_confidence(destination_snap_distance_m),
            snap_point=(float(destination_snap_point.x), float(destination_snap_point.y)),
            quality_code=self._snap_quality_code(destination_snap_distance_m),
        )
        validation_issues = [
            *self.validator.validate_geometry(geometry_json),
            *self.post_processor.validate(geometry_json, origin_snap=origin_snap, destination_snap=destination_snap),
            *(await self._validate_spatial_context(geometry_json, [int(centerline.channel_id)], [])),
        ]
        search_result = SearchResult(
            node_path=[],
            segments=[],
            total_cost=line_length_km(route_line),
            algorithm_code="CENTERLINE_SEED_PROJECT",
            planning_mode_code=planning_mode_code,
        )
        quality = self.scorer.score(
            origin_snap=origin_snap,
            destination_snap=destination_snap,
            search_result=search_result,
            validation_issues=validation_issues,
        )
        issue_codes = {issue.issue_type_code for issue in quality.issues}
        if quality.quality_code == "FAILED" or issue_codes.intersection(HARD_ROUTE_ISSUE_CODES):
            return None
        return {
            "centerline": centerline,
            "geometry_json": geometry_json,
            "distance_km": round(line_length_km(route_line), 3),
            "origin_snap": origin_snap,
            "destination_snap": destination_snap,
            "quality_score": quality.quality_score,
            "quality_code": quality.quality_code,
            "issues": quality.issues,
        }

    def _line_with_endpoint_access(
        self,
        *,
        origin: Point,
        destination: Point,
        origin_snap: Point,
        destination_snap: Point,
        centerline_segment: LineString,
    ) -> LineString:
        coords: list[tuple[float, float]] = []
        self._append_route_coord(coords, (origin.x, origin.y))
        if point_distance_m(origin, origin_snap) > 1:
            self._append_route_coord(coords, (origin_snap.x, origin_snap.y))
        for lng, lat, *_ in centerline_segment.coords:
            self._append_route_coord(coords, (float(lng), float(lat)))
        if point_distance_m(destination, destination_snap) > 1:
            self._append_route_coord(coords, (destination_snap.x, destination_snap.y))
        self._append_route_coord(coords, (destination.x, destination.y))
        return LineString(coords)

    def _append_route_coord(self, coords: list[tuple[float, float]], coord: tuple[float, float]) -> None:
        if coords and point_distance_m(Point(coords[-1]), Point(coord)) <= 1:
            return
        coords.append((float(coord[0]), float(coord[1])))

    async def _persist_centerline_seed_fallback(
        self,
        *,
        request_row: NavigationRouteRequest,
        original_response: NavigationRouteGenerateResponse,
        candidate: dict[str, Any],
        planning_mode_code: str,
        include_explain: bool,
    ) -> NavigationRouteGenerateResponse:
        centerline: NavigationChannelCenterline = candidate["centerline"]
        fallback_issue = RouteIssue(
            "CENTERLINE_SEED_NOT_GRAPH_VALIDATED",
            "ERROR",
            "自研 Graph 未能接入；已定位到本地已发布中心线 seed，但该 seed 尚未通过 active Graph 连通验证，不能作为可用路径返回。",
            suggestion="先把该 seed 并入生产 Graph 并重建验证，确认边界、中心线、节点和约束均可用后再返回用户路径。",
            geometry_json=candidate["geometry_json"],
        )
        result_issues = [*candidate["issues"], fallback_issue]
        max_result_no = await self.session.scalar(
            select(func.max(NavigationRouteResult.result_no)).where(NavigationRouteResult.request_id == request_row.id)
        )
        duration_detail = self._duration_detail(candidate["distance_km"], 0)
        result_row = NavigationRouteResult(
            request_id=request_row.id,
            result_no=int(max_result_no or 0) + 1,
            result_type_code="CENTERLINE_SEED_FALLBACK",
            status_code="FAILED",
            geometry_json=None,
            distance_km=None,
            estimated_duration_hour=None,
            edge_ids=[],
            channel_ids=[int(centerline.channel_id)],
            passed_node_ids=[],
            passed_lock_count=0,
            passed_bridge_count=0,
            quality_score=0,
            quality_code="FAILED",
            quality_summary_json={
                "engine": "CENTERLINE_SEED_ROUTING",
                "provider_code": "NAVIGATION_ENGINE",
                "source_type_code": "CENTERLINE_SEED_FALLBACK",
                "centerline_id": int(centerline.id),
                "centerline_code": centerline.centerline_code,
                "channel_id": int(centerline.channel_id),
                "candidate_geometry_json": candidate["geometry_json"],
                "candidate_distance_km": candidate["distance_km"],
                "candidate_quality_score": candidate["quality_score"],
                "candidate_quality_code": candidate["quality_code"],
                "origin_snap": candidate["origin_snap"].as_dict(),
                "destination_snap": candidate["destination_snap"].as_dict(),
                "original_status_code": original_response.status_code,
                "original_quality_code": original_response.quality_code,
                "original_error_code": original_response.error_code,
                "original_error_message": original_response.error_message,
                "original_issue_codes": [issue.issue_type_code for issue in original_response.issues],
                "planning_mode_code": planning_mode_code,
                "duration_detail": duration_detail,
                "cache_hit": False,
            },
            provider_code="NAVIGATION_ENGINE",
            engine_code="CENTERLINE_SEED_ROUTING_V1",
            reference_result_id=original_response.result_id,
        )
        self.session.add(result_row)
        request_row.status_code = "FAILED"
        request_row.error_code = "CENTERLINE_SEED_NOT_GRAPH_VALIDATED"
        request_row.error_message = fallback_issue.message
        await self.session.flush()
        await self._insert_issues(result_row.id, result_issues)
        await self.session.commit()
        explain = {
            "engine": "CENTERLINE_SEED_ROUTING",
            "provider_code": "NAVIGATION_ENGINE",
            "source_type_code": "CENTERLINE_SEED_FALLBACK",
            "centerline_id": int(centerline.id),
            "channel_id": int(centerline.channel_id),
            "original_result_id": original_response.result_id,
            "original_error_code": original_response.error_code,
            "original_quality_code": original_response.quality_code,
            "centerline_seed_returnable": False,
            "next_actions": [
                "Merge this published access seed into the production Graph without reducing active graph coverage.",
                "Rebuild the graph and rerun OD route audit before allowing this geometry to be returned.",
            ],
        }
        return NavigationRouteGenerateResponse(
            request_id=request_row.id,
            result_id=result_row.id,
            graph_version_id=request_row.graph_version_id,
            status_code="FAILED",
            provider_code="NAVIGATION_ENGINE",
            source_type_code="CENTERLINE_SEED_FALLBACK",
            cache_hit=False,
            hifleet_cache_id=None,
            trajectory_cache_id=None,
            quality_code="FAILED",
            quality_score=0,
            geometry_json=None,
            distance_km=None,
            estimated_duration_hour=None,
            edge_ids=[],
            channel_ids=[int(centerline.channel_id)],
            passed_node_ids=[],
            passed_lock_count=0,
            passed_bridge_count=0,
            origin_snap=self._snap_response(candidate["origin_snap"]),
            destination_snap=self._snap_response(candidate["destination_snap"]),
            issues=[self._issue_response(issue) for issue in result_issues],
            alternatives=[],
            explain=explain if include_explain else None,
            error_code="CENTERLINE_SEED_NOT_GRAPH_VALIDATED",
            error_message=fallback_issue.message,
        )

    def _snap_confidence(self, distance_m: float) -> int:
        if distance_m <= 50:
            return 95
        if distance_m <= 200:
            return 85
        if distance_m <= 500:
            return 70
        return 55

    def _snap_quality_code(self, distance_m: float) -> str:
        if distance_m <= 200:
            return "HIGH"
        if distance_m <= 500:
            return "MEDIUM"
        return "LOW"

    def _route_point_cache_refs(self, point: RoutePoint, *, prefix: str) -> dict[str, object | None]:
        return {
            f"{prefix}_ref_type_code": point.ref_type_code,
            f"{prefix}_ref_id": point.ref_id,
            f"{prefix}_name": point.name,
        }

    async def _persist_hifleet_fallback(
        self,
        *,
        request_row: NavigationRouteRequest,
        original_response: NavigationRouteGenerateResponse,
        hifleet,
        planning_mode_code: str,
        include_explain: bool,
    ) -> NavigationRouteGenerateResponse:
        raw_summary = hifleet.raw_summary if isinstance(hifleet.raw_summary, dict) else {}
        source_type_code = "HIFLEET_CACHE" if raw_summary.get("cache_hit") else "HIFLEET_API"
        original_issue_codes = [issue.issue_type_code for issue in original_response.issues]
        original_hard_issue_codes = sorted({code for code in original_issue_codes if code in HARD_ROUTE_ISSUE_CODES})
        geometry_quality = self._hifleet_fallback_geometry_quality(hifleet.geometry)
        is_returnable = bool(geometry_quality["returnable"])
        max_result_no = await self.session.scalar(
            select(func.max(NavigationRouteResult.result_no)).where(NavigationRouteResult.request_id == request_row.id)
        )
        issue = RouteIssue(
            "HIFLEET_FALLBACK_ROUTE",
            "WARNING",
            "自研航道引擎未生成可用路径，已检查 HiFleet 本地缓存/接口参考轨迹。",
            suggestion="继续用该 OD 与 HiFleet 对比修复 seed；该结果不作为中心线发布依据。",
        )
        result_issues = [issue]
        if not is_returnable:
            result_issues.append(
                RouteIssue(
                    str(geometry_quality["issue_code"]),
                    "ERROR",
                    str(geometry_quality["message"]),
                    suggestion="该 HiFleet 轨迹只能作为 seed 缺口定位证据；先补齐缺失航道/中心线并重建本地图，再返回可用路径。",
                    geometry_json=geometry_quality.get("issue_geometry_json"),
                )
            )
        status_code = "SUCCESS" if is_returnable else "FAILED"
        quality_code = "READY_WITH_WARNING" if is_returnable else "FAILED"
        quality_score = 75 if is_returnable else 0
        geometry_json = hifleet.geometry if is_returnable else None
        distance_km = hifleet.distance_km if is_returnable else None
        estimated_duration_hour = hifleet.estimated_duration_hour if is_returnable else None
        result_row = NavigationRouteResult(
            request_id=request_row.id,
            result_no=int(max_result_no or 0) + 1,
            result_type_code="HIFLEET_FALLBACK" if is_returnable else "HIFLEET_REFERENCE_REJECTED",
            status_code=status_code,
            geometry_json=geometry_json,
            distance_km=distance_km,
            estimated_duration_hour=estimated_duration_hour,
            edge_ids=[],
            channel_ids=[],
            passed_node_ids=[],
            passed_lock_count=0,
            passed_bridge_count=0,
            quality_score=quality_score,
            quality_code=quality_code,
            quality_summary_json={
                "engine": "HIFLEET_CACHE_FALLBACK",
                "provider_code": "HIFLEET",
                "source_type_code": source_type_code,
                "cache_hit": bool(raw_summary.get("cache_hit")),
                "hifleet_cache_id": raw_summary.get("hifleet_cache_id"),
                "route_key": raw_summary.get("route_key"),
                "normalized_pair_key": raw_summary.get("normalized_pair_key"),
                "cache_direction": raw_summary.get("cache_direction"),
                "reference_only": True,
                "centerline_publish_allowed": False,
                "hifleet_geometry_returnable": is_returnable,
                "hifleet_geometry_quality": geometry_quality,
                "hifleet_reference_distance_km": hifleet.distance_km,
                "hifleet_reference_estimated_duration_hour": hifleet.estimated_duration_hour,
                "original_status_code": original_response.status_code,
                "original_quality_code": original_response.quality_code,
                "original_error_code": original_response.error_code,
                "original_error_message": original_response.error_message,
                "original_issue_codes": original_issue_codes,
                "original_hard_issue_codes": original_hard_issue_codes,
                "planning_mode_code": planning_mode_code,
                "point_count": raw_summary.get("point_count"),
            },
            provider_code="HIFLEET",
            engine_code="HIFLEET_CACHE_FALLBACK",
            reference_result_id=original_response.result_id,
        )
        self.session.add(result_row)
        request_row.status_code = status_code
        request_row.error_code = None if is_returnable else str(geometry_quality["issue_code"])
        request_row.error_message = None if is_returnable else str(geometry_quality["message"])
        await self.session.flush()
        await self._insert_issues(result_row.id, result_issues)
        await self.session.commit()
        explain = {
            "engine": "HIFLEET_CACHE_FALLBACK",
            "provider_code": "HIFLEET",
            "source_type_code": source_type_code,
            "cache_hit": bool(raw_summary.get("cache_hit")),
            "hifleet_cache_id": raw_summary.get("hifleet_cache_id"),
            "route_key": raw_summary.get("route_key"),
            "hifleet_geometry_returnable": is_returnable,
            "hifleet_geometry_quality": geometry_quality,
            "original_result_id": original_response.result_id,
            "original_error_code": original_response.error_code,
            "original_quality_code": original_response.quality_code,
            "original_issue_codes": original_issue_codes,
            "original_hard_issue_codes": original_hard_issue_codes,
            "next_actions": [
                "Use this HiFleet reference route to identify missing or bad seed centerlines.",
                "Do not publish this provider geometry as a production centerline without deterministic GIS cleaning.",
            ],
        }
        return NavigationRouteGenerateResponse(
            request_id=request_row.id,
            result_id=result_row.id,
            graph_version_id=request_row.graph_version_id,
            status_code=status_code,
            provider_code="HIFLEET",
            source_type_code=source_type_code,
            cache_hit=bool(raw_summary.get("cache_hit")),
            hifleet_cache_id=raw_summary.get("hifleet_cache_id"),
            trajectory_cache_id=None,
            quality_code=quality_code,
            quality_score=quality_score,
            geometry_json=geometry_json,
            distance_km=distance_km,
            estimated_duration_hour=estimated_duration_hour,
            edge_ids=[],
            channel_ids=[],
            passed_node_ids=[],
            passed_lock_count=0,
            passed_bridge_count=0,
            issues=[self._issue_response(item) for item in result_issues],
            alternatives=[],
            explain=explain if include_explain else None,
            error_code=None if is_returnable else str(geometry_quality["issue_code"]),
            error_message=None if is_returnable else str(geometry_quality["message"]),
        )

    def _hifleet_fallback_geometry_quality(self, geometry_json: dict[str, Any] | None) -> dict[str, Any]:
        points = self._line_string_points(geometry_json)
        if len(points) < 2:
            return {
                "returnable": False,
                "issue_code": "HIFLEET_REFERENCE_GEOMETRY_INVALID",
                "message": "HiFleet 参考轨迹不是有效 LineString，已拒绝返回给前端。",
                "point_count": len(points),
                "max_segment_km": None,
                "max_segment_threshold_km": self.HIFLEET_FALLBACK_MAX_SEGMENT_KM,
            }
        longest_segment: tuple[float, list[float], list[float]] | None = None
        for start, end in zip(points[:-1], points[1:]):
            distance_km = point_distance_m(Point(start), Point(end)) / 1000.0
            if longest_segment is None or distance_km > longest_segment[0]:
                longest_segment = (distance_km, start, end)
        max_segment_km = round(longest_segment[0], 4) if longest_segment else None
        if max_segment_km is not None and max_segment_km >= self.HIFLEET_FALLBACK_MAX_SEGMENT_KM:
            start = longest_segment[1]
            end = longest_segment[2]
            return {
                "returnable": False,
                "issue_code": "HIFLEET_REFERENCE_LONG_JUMP",
                "message": (
                    f"HiFleet 参考轨迹存在 {max_segment_km:.1f}km 相邻点跳线，已拒绝返回给前端。"
                ),
                "point_count": len(points),
                "max_segment_km": max_segment_km,
                "max_segment_threshold_km": self.HIFLEET_FALLBACK_MAX_SEGMENT_KM,
                "issue_geometry_json": {"type": "LineString", "coordinates": [start, end]},
            }
        return {
            "returnable": True,
            "issue_code": None,
            "message": None,
            "point_count": len(points),
            "max_segment_km": max_segment_km,
            "max_segment_threshold_km": self.HIFLEET_FALLBACK_MAX_SEGMENT_KM,
        }

    def _line_string_points(self, geometry_json: dict[str, Any] | None) -> list[list[float]]:
        if not isinstance(geometry_json, dict) or geometry_json.get("type") != "LineString":
            return []
        points: list[list[float]] = []
        for item in geometry_json.get("coordinates") or []:
            if not isinstance(item, list | tuple) or len(item) < 2:
                continue
            try:
                lng = float(item[0])
                lat = float(item[1])
            except (TypeError, ValueError):
                continue
            if -180 <= lng <= 180 and -90 <= lat <= 90 and (not points or points[-1] != [lng, lat]):
                points.append([lng, lat])
        return points

    async def _insert_issues(self, route_result_id: int, issues: list[RouteIssue]) -> None:
        result_row = await self.session.get(NavigationRouteResult, route_result_id)
        route_geometry = result_row.geometry_json if result_row is not None else None
        seen: set[tuple[str, int | None, int | None, str]] = set()
        for issue in issues:
            key = (issue.issue_type_code, issue.related_edge_id, issue.related_node_id, issue.message)
            if key in seen:
                continue
            seen.add(key)
            issue_geometry = issue.geometry_json
            if issue_geometry is None and issue.issue_type_code in {
                "PATH_OUT_OF_WATER",
                "PATH_WATER_COVERAGE_WARNING",
                "PATH_OUT_OF_CHANNEL_BOUNDARY",
                "PATH_CHANNEL_BOUNDARY_WARNING",
            }:
                issue_geometry = route_geometry
            self.session.add(
                NavigationRouteQualityIssue(
                    route_result_id=route_result_id,
                    issue_type_code=issue.issue_type_code,
                    severity_code=issue.severity_code,
                    geometry_json=issue_geometry,
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
            provider_code=result_row.provider_code,
            source_type_code=self._result_source_type(result_row),
            cache_hit=self._result_cache_hit(result_row),
            hifleet_cache_id=self._result_hifleet_cache_id(result_row),
            trajectory_cache_id=self._result_trajectory_cache_id(result_row),
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
            provider_code=result_row.provider_code,
            source_type_code=self._result_source_type(result_row),
            cache_hit=self._result_cache_hit(result_row),
            hifleet_cache_id=self._result_hifleet_cache_id(result_row),
            trajectory_cache_id=self._result_trajectory_cache_id(result_row),
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

    def _attach_issue_edge_context(self, issues: list[RouteIssue], search_result: SearchResult) -> None:
        for issue in issues:
            if issue.related_edge_id is not None or not issue.geometry_json:
                continue
            if issue.issue_type_code not in {
                "ROUTE_LONG_STRAIGHT_SEGMENT_REVIEW",
                "ROUTE_FOLDBACK_REVIEW",
                "ROUTE_SELF_INTERSECTION_REVIEW",
                "ROUTE_STRAIGHT_LINE_FALLBACK",
            }:
                continue
            edge_id = self._nearest_search_segment_edge_id(issue.geometry_json, search_result)
            if edge_id is not None:
                issue.related_edge_id = edge_id

    def _nearest_search_segment_edge_id(self, issue_geometry_json: dict[str, Any], search_result: SearchResult) -> int | None:
        try:
            issue_geometry = shape(issue_geometry_json)
        except Exception:  # noqa: BLE001
            return None
        issue_points: list[Point] = []
        if isinstance(issue_geometry, Point):
            issue_points = [issue_geometry]
        elif isinstance(issue_geometry, LineString):
            coords = list(issue_geometry.coords)
            if coords:
                issue_points = [Point(coords[0]), Point(coords[-1])]
        if not issue_points:
            return None
        best_edge_id: int | None = None
        best_score_m: float | None = None
        for segment in search_result.segments:
            if segment.edge_id is None:
                continue
            try:
                segment_geometry = shape(segment.geometry_json)
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(segment_geometry, LineString) or segment_geometry.is_empty:
                continue
            coords = list(segment_geometry.coords)
            if not coords:
                continue
            segment_points = [Point(coords[0]), Point(coords[-1])]
            score_m = min(point_distance_m(issue_point, segment_point) for issue_point in issue_points for segment_point in segment_points)
            if best_score_m is None or score_m < best_score_m:
                best_score_m = score_m
                best_edge_id = int(segment.edge_id)
        return best_edge_id

    def _result_source_type(self, result_row: NavigationRouteResult) -> str | None:
        summary = result_row.quality_summary_json if isinstance(result_row.quality_summary_json, dict) else {}
        value = summary.get("source_type_code")
        if value:
            return str(value)
        return result_row.engine_code or result_row.provider_code

    def _result_cache_hit(self, result_row: NavigationRouteResult) -> bool | None:
        summary = result_row.quality_summary_json if isinstance(result_row.quality_summary_json, dict) else {}
        value = summary.get("cache_hit")
        return bool(value) if value is not None else None

    def _result_hifleet_cache_id(self, result_row: NavigationRouteResult) -> int | None:
        summary = result_row.quality_summary_json if isinstance(result_row.quality_summary_json, dict) else {}
        value = summary.get("hifleet_cache_id")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _result_trajectory_cache_id(self, result_row: NavigationRouteResult) -> int | None:
        summary = result_row.quality_summary_json if isinstance(result_row.quality_summary_json, dict) else {}
        value = summary.get("trajectory_cache_id")
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

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
            if row.geometry_json and self._boundary_counts_as_water_context(row)
        )
        issues = self.validator.validate_spatial_context(
            geometry_json,
            water_geometries=water_geometries,
            boundary_geometries=boundary_geometries,
        )
        issues.extend(self._boundary_source_trust_issues(boundary_rows))
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

    def _boundary_counts_as_water_context(self, boundary: NavigationChannelBoundary) -> bool:
        policy = str(boundary.coverage_policy_code or "")
        if policy.startswith("REVIER_WATER_BODY_UNION"):
            return True
        source_trace = boundary.source_trace_json if isinstance(boundary.source_trace_json, dict) else {}
        audit = source_trace.get("boundary_integrity_audit") if isinstance(source_trace, dict) else None
        if policy == "OSM_WATERWAY_CORRIDOR":
            return isinstance(audit, dict) and str(audit.get("trust_code") or "") in {"READY", "READY_WITH_WARNING"}
        if policy == "MIXED_LOCAL_OSM_WATERWAY_CORRIDOR":
            validation = source_trace.get("validation") if isinstance(source_trace, dict) else None
            if not isinstance(validation, dict):
                return False
            try:
                coverage_ratio = float(validation.get("boundary_coverage_ratio") or 0)
            except (TypeError, ValueError):
                coverage_ratio = 0.0
            return (
                bool(validation.get("line_is_simple"))
                and coverage_ratio >= 0.98
                and not validation.get("blockers")
            )
        if policy not in {"AUTO_WATER_BODY_UNION", "AUTO_BOUNDARY_MERGE"}:
            return False
        if not isinstance(audit, dict) or str(audit.get("trust_code") or "") not in {"READY", "READY_WITH_WARNING"}:
            return False
        verification = source_trace.get("basemap_verification") if isinstance(source_trace, dict) else None
        if not isinstance(verification, dict) or not verification.get("status_code"):
            return False
        return bool(source_trace.get("selected_water_bodies") or source_trace.get("selected_water_areas"))

    def _boundary_source_trust_issues(self, boundary_rows: list[NavigationChannelBoundary]) -> list[RouteIssue]:
        issues: list[RouteIssue] = []
        emitted: set[str] = set()
        for boundary in boundary_rows:
            source_trace = boundary.source_trace_json if isinstance(boundary.source_trace_json, dict) else {}
            audit = source_trace.get("boundary_integrity_audit") if isinstance(source_trace, dict) else None
            if not isinstance(audit, dict):
                if boundary.coverage_policy_code == "CHANNEL_CORRIDOR_ENVELOPE":
                    code = "CHANNEL_BOUNDARY_SOURCE_NOT_VERIFIED"
                    if code not in emitted:
                        issues.append(
                            RouteIssue(
                                code,
                                "WARNING",
                                "当前航道边界是通道包络/旧 seed 边界，缺少独立底图或轨迹校验，不能作为高置信路径验收依据。",
                                suggestion="补充边界完整性审计，确认边界真实包住水道、中心线和轨迹后再发布高置信图网络。",
                            )
                        )
                        emitted.add(code)
                continue
            trust_code = str(audit.get("trust_code") or "")
            issue_codes = set(audit.get("issue_codes") or [])
            if trust_code in {"FAILED", "NEEDS_REVIEW"} and "CHANNEL_BOUNDARY_TRUST_NEEDS_REVIEW" not in emitted:
                issues.append(
                    RouteIssue(
                        "CHANNEL_BOUNDARY_TRUST_NEEDS_REVIEW",
                        "WARNING",
                        "当前路径经过的航道边界完整性未达高置信标准。",
                        suggestion="先修复/扩大/重建航道边界，并验证其包住水道、中心线和轨迹。",
                    )
                )
                emitted.add("CHANNEL_BOUNDARY_TRUST_NEEDS_REVIEW")
            if "SOURCE_GEOMETRY_FRAGMENTED" in issue_codes and "CHANNEL_BOUNDARY_SOURCE_FRAGMENTED" not in emitted:
                issues.append(
                    RouteIssue(
                        "CHANNEL_BOUNDARY_SOURCE_FRAGMENTED",
                        "WARNING",
                        "航道边界由分散水域碎面组成，可能没有覆盖连续真实水道。",
                        suggestion="用原始水系、底图和 HiFleet/轨迹参考补齐连续水道边界，再重建中心线和图边。",
                    )
                )
                emitted.add("CHANNEL_BOUNDARY_SOURCE_FRAGMENTED")
            if "BOUNDARY_NOT_INDEPENDENTLY_BASEMAP_VERIFIED" in issue_codes and "CHANNEL_BOUNDARY_BASEMAP_NOT_VERIFIED" not in emitted:
                issues.append(
                    RouteIssue(
                        "CHANNEL_BOUNDARY_BASEMAP_NOT_VERIFIED",
                        "WARNING",
                        "航道边界尚未通过独立底图/轨迹参照验证。",
                        suggestion="不能只用本地水系面互相覆盖来验收边界；需要独立参照确认真实水道范围。",
                    )
                )
                emitted.add("CHANNEL_BOUNDARY_BASEMAP_NOT_VERIFIED")
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
            "SOURCE_GEOMETRY_FRAGMENTED",
            "BOUNDARY_NOT_INDEPENDENTLY_BASEMAP_VERIFIED",
            "BOUNDARY_CORRIDOR_ENVELOPE_NEEDS_REAL_WATERWAY_REVIEW",
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
