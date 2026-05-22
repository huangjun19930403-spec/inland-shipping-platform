from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.models import (
    NavigationRouteQualityIssue,
    NavigationRouteRequest,
    NavigationRouteResult,
)
from app.models.address import NavigationConstraintPoint, TransportNode
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
        try:
            graph_version = await self.loader.select_graph_version(body.graph_version_id)
            request_row.graph_version_id = graph_version.id
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
            validation_issues = self.validator.validate_geometry(assembled.geometry_json)
            quality = self.scorer.score(
                origin_snap=origin_snap,
                destination_snap=destination_snap,
                search_result=search_result,
                validation_issues=validation_issues,
            )
            request_row.status_code = "SUCCESS" if quality.quality_code != "FAILED" else "FAILED"
            result_row = NavigationRouteResult(
                request_id=request_row.id,
                result_no=1,
                result_type_code="RECOMMENDED",
                status_code=quality.quality_code,
                geometry_json=assembled.geometry_json,
                distance_km=assembled.distance_km,
                estimated_duration_hour=self._estimated_duration(assembled.distance_km),
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
                },
                provider_code="NAVIGATION_ENGINE",
                engine_code="NAVIGATION_ROUTING_ENGINE_V1",
            )
            self.session.add(result_row)
            await self.session.flush()
            await self._insert_issues(result_row.id, quality.issues)
            await self.session.commit()
            return self._success_response(request_row, result_row, origin_snap, destination_snap, quality.issues)
        except RoutingEngineError as exc:
            return await self._persist_failure(request_row, exc, origin_snap, destination_snap)

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

    def _estimated_duration(self, distance_km: float | None) -> float | None:
        if distance_km is None:
            return None
        return round(distance_km / 10.0, 2)

    def _request_no(self) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        return f"NRR-{timestamp}-{uuid.uuid4().hex[:8].upper()}"
