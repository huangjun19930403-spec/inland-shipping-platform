from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import (
    NavigationChannelCenterline,
    NavigationChannelWaterAreaMatch,
    NavigationGraphEdge,
    NavigationGraphNode,
    NavigationRouteQualityIssue,
    NavigationRouteResult,
    NavigationWaterArea,
)
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.modules.navigation.schemas import NavigationMapLayerFeatureResponse, NavigationMapLayerResponse


class NavigationMapLayerService:
    def __init__(self, session: AsyncSession, *, default_limit: int = 200, max_limit: int = 500) -> None:
        self.session = session
        self.default_limit = default_limit
        self.max_limit = max_limit

    async def get_layers(
        self,
        *,
        min_lng: float | None,
        min_lat: float | None,
        max_lng: float | None,
        max_lat: float | None,
        channel_id: int | None,
        route_result_id: int | None,
        include_water_area: bool,
        include_boundary: bool,
        include_centerline: bool,
        include_graph_edge: bool,
        limit: int | None,
    ) -> NavigationMapLayerResponse:
        warnings: list[str] = []
        truncated_layers: list[str] = []
        layer_limit = max(1, min(int(limit or self.default_limit), self.max_limit))
        bbox = self._bbox(min_lng=min_lng, min_lat=min_lat, max_lng=max_lng, max_lat=max_lat)

        route_results: list[NavigationMapLayerFeatureResponse] = []
        quality_issues: list[NavigationMapLayerFeatureResponse] = []
        if route_result_id is not None:
            route_results, quality_issues = await self._route_layers(route_result_id)
            if bbox is None and route_results:
                bbox = self._expanded_geometry_bbox(route_results[0].geometry_json, margin_degree=0.35)

        if channel_id is not None:
            channel_bbox = await self._channel_layer_bbox(channel_id)
            if channel_bbox is not None:
                bbox = channel_bbox if bbox is None else self._merge_bbox(bbox, channel_bbox)
            else:
                warnings.append("CHANNEL_HAS_NO_MATCHED_WATER_OR_BOUNDARY")

        if bbox is None:
            warnings.append("MAP_LAYER_BBOX_REQUIRED")
            return NavigationMapLayerResponse(
                route_results=route_results,
                quality_issues=quality_issues,
                warnings=warnings,
            )

        water_areas: list[NavigationMapLayerFeatureResponse] = []
        channel_boundaries: list[NavigationMapLayerFeatureResponse] = []
        centerlines: list[NavigationMapLayerFeatureResponse] = []
        graph_edges: list[NavigationMapLayerFeatureResponse] = []

        if include_water_area:
            water_areas = await self._water_area_layers(bbox, layer_limit, truncated_layers, channel_id=channel_id)
        if include_boundary:
            channel_boundaries = await self._boundary_layers(bbox, layer_limit, truncated_layers, channel_id=channel_id)
        if include_centerline:
            centerlines = await self._centerline_layers(bbox, layer_limit, truncated_layers, channel_id=channel_id)
        if include_graph_edge:
            graph_edges = await self._graph_edge_layers(bbox, layer_limit, truncated_layers, channel_id=channel_id)

        return NavigationMapLayerResponse(
            bbox=bbox,
            water_areas=water_areas,
            channel_boundaries=channel_boundaries,
            centerlines=centerlines,
            graph_edges=graph_edges,
            route_results=route_results,
            quality_issues=quality_issues,
            truncated_layers=truncated_layers,
            warnings=warnings,
        )

    def _bbox(
        self,
        *,
        min_lng: float | None,
        min_lat: float | None,
        max_lng: float | None,
        max_lat: float | None,
    ) -> dict[str, float] | None:
        values = [min_lng, min_lat, max_lng, max_lat]
        if any(value is None for value in values):
            return None
        assert min_lng is not None and min_lat is not None and max_lng is not None and max_lat is not None
        left = max(-180.0, min(float(min_lng), float(max_lng)))
        right = min(180.0, max(float(min_lng), float(max_lng)))
        bottom = max(-90.0, min(float(min_lat), float(max_lat)))
        top = min(90.0, max(float(min_lat), float(max_lat)))
        if right <= left or top <= bottom:
            return None
        return {"min_lng": left, "min_lat": bottom, "max_lng": right, "max_lat": top}

    def _bbox_intersects(self, model, bbox: dict[str, float]):
        return (
            model.bbox_min_lng.is_not(None),
            model.bbox_min_lat.is_not(None),
            model.bbox_max_lng.is_not(None),
            model.bbox_max_lat.is_not(None),
            model.bbox_min_lng <= bbox["max_lng"],
            model.bbox_max_lng >= bbox["min_lng"],
            model.bbox_min_lat <= bbox["max_lat"],
            model.bbox_max_lat >= bbox["min_lat"],
        )

    async def _water_area_layers(
        self,
        bbox: dict[str, float],
        limit: int,
        truncated_layers: list[str],
        *,
        channel_id: int | None,
    ) -> list[NavigationMapLayerFeatureResponse]:
        if channel_id is not None:
            rows = list(
                (
                    await self.session.execute(
                        select(NavigationWaterArea, NavigationChannelWaterAreaMatch)
                        .join(
                            NavigationChannelWaterAreaMatch,
                            NavigationChannelWaterAreaMatch.water_area_id == NavigationWaterArea.id,
                        )
                        .where(
                            NavigationWaterArea.is_enabled.is_(True),
                            NavigationChannelWaterAreaMatch.channel_id == channel_id,
                            NavigationChannelWaterAreaMatch.is_current.is_(True),
                        )
                        .order_by(NavigationChannelWaterAreaMatch.score.desc(), NavigationWaterArea.id)
                        .limit(limit + 1)
                    )
                ).all()
            )
            if len(rows) > limit:
                truncated_layers.append("WATER_AREA")
                rows = rows[:limit]
            return [
                NavigationMapLayerFeatureResponse(
                    id=row.id,
                    layer_type_code="MATCHED_WATER_AREA",
                    name=row.water_name,
                    geometry_json=row.simplified_geometry_low_json or row.geometry_json,
                    properties={
                        "source_code": row.source_code,
                        "source_layer_name": row.source_layer_name,
                        "water_type_code": row.water_type_code,
                        "water_level": row.water_level,
                        "geometry_status_code": row.geometry_status_code,
                        "match_id": match.id,
                        "match_batch_code": match.match_batch_code,
                        "match_type_code": match.match_type_code,
                        "matched_term": match.matched_term,
                        "score": match.score,
                        "confidence_code": match.confidence_code,
                        "review_status_code": match.review_status_code,
                        "issue_codes": match.issue_codes or [],
                    },
                )
                for row, match in rows
            ]

        rows = list(
            (
                await self.session.execute(
                    select(NavigationWaterArea)
                    .where(
                        NavigationWaterArea.is_enabled.is_(True),
                        *self._bbox_intersects(NavigationWaterArea, bbox),
                    )
                    .order_by(NavigationWaterArea.id)
                    .limit(limit + 1)
                )
            ).scalars()
        )
        if len(rows) > limit:
            truncated_layers.append("WATER_AREA")
            rows = rows[:limit]
        return [
            NavigationMapLayerFeatureResponse(
                id=row.id,
                layer_type_code="WATER_AREA",
                name=row.water_name,
                geometry_json=row.simplified_geometry_low_json or row.geometry_json,
                properties={
                    "source_code": row.source_code,
                    "source_layer_name": row.source_layer_name,
                    "water_type_code": row.water_type_code,
                    "water_level": row.water_level,
                    "geometry_status_code": row.geometry_status_code,
                },
            )
            for row in rows
        ]

    async def _boundary_layers(
        self,
        bbox: dict[str, float],
        limit: int,
        truncated_layers: list[str],
        *,
        channel_id: int | None,
    ) -> list[NavigationMapLayerFeatureResponse]:
        clauses = [
            NavigationChannel.is_enabled.is_(True),
            NavigationChannelBoundary.geometry_status_code == "AVAILABLE",
            *self._bbox_intersects(NavigationChannelBoundary, bbox),
        ]
        if channel_id is not None:
            clauses.append(NavigationChannelBoundary.channel_id == channel_id)
            clauses.append(
                or_(
                    NavigationChannelBoundary.is_current.is_(True),
                    NavigationChannelBoundary.coverage_policy_code == "RIVER_MATCH_CANDIDATE",
                )
            )
        else:
            clauses.append(NavigationChannelBoundary.is_current.is_(True))
        rows = list(
            (
                await self.session.execute(
                    select(NavigationChannelBoundary, NavigationChannel)
                    .join(NavigationChannel, NavigationChannel.id == NavigationChannelBoundary.channel_id)
                    .where(*clauses)
                    .order_by(NavigationChannelBoundary.is_current.desc(), NavigationChannel.display_priority.desc(), NavigationChannelBoundary.id)
                    .limit(limit + 1)
                )
            ).all()
        )
        if len(rows) > limit:
            truncated_layers.append("CHANNEL_BOUNDARY")
            rows = rows[:limit]
        return [
            NavigationMapLayerFeatureResponse(
                id=boundary.id,
                layer_type_code="CHANNEL_BOUNDARY",
                name=channel.channel_name,
                geometry_json=self._boundary_geometry(boundary),
                properties={
                    "channel_id": channel.id,
                    "channel_code": channel.channel_code,
                    "planning_level_code": channel.planning_level_code,
                    "boundary_role_code": "CURRENT" if boundary.is_current else "CANDIDATE",
                    "is_current": boundary.is_current,
                    "coverage_policy_code": boundary.coverage_policy_code,
                    "boundary_quality_code": boundary.boundary_quality_code,
                    "connectivity_status_code": boundary.connectivity_status_code,
                    "repair_status_code": boundary.repair_status_code,
                },
            )
            for boundary, channel in rows
        ]

    async def _centerline_layers(
        self,
        bbox: dict[str, float],
        limit: int,
        truncated_layers: list[str],
        *,
        channel_id: int | None,
    ) -> list[NavigationMapLayerFeatureResponse]:
        clauses = [
            NavigationChannel.is_enabled.is_(True),
            NavigationChannelCenterline.is_current.is_(True),
            *self._bbox_intersects(NavigationChannelCenterline, bbox),
        ]
        if channel_id is not None:
            clauses.append(NavigationChannelCenterline.channel_id == channel_id)
        rows = list(
            (
                await self.session.execute(
                    select(NavigationChannelCenterline, NavigationChannel)
                    .join(NavigationChannel, NavigationChannel.id == NavigationChannelCenterline.channel_id)
                    .where(*clauses)
                    .order_by(NavigationChannelCenterline.id)
                    .limit(limit + 1)
                )
            ).all()
        )
        if len(rows) > limit:
            truncated_layers.append("CENTERLINE")
            rows = rows[:limit]
        return [
            NavigationMapLayerFeatureResponse(
                id=centerline.id,
                layer_type_code="CENTERLINE",
                name=centerline.centerline_name or channel.channel_name,
                geometry_json=centerline.geometry_json,
                properties={
                    "channel_id": channel.id,
                    "channel_code": channel.channel_code,
                    "centerline_code": centerline.centerline_code,
                    "source_type_code": centerline.source_type_code,
                    "quality_code": centerline.quality_code,
                    "review_status_code": centerline.review_status_code,
                    "confidence_score": centerline.confidence_score,
                },
            )
            for centerline, channel in rows
        ]

    async def _graph_edge_layers(
        self,
        bbox: dict[str, float],
        limit: int,
        truncated_layers: list[str],
        *,
        channel_id: int | None,
    ) -> list[NavigationMapLayerFeatureResponse]:
        from_node = aliased(NavigationGraphNode)
        to_node = aliased(NavigationGraphNode)
        clauses = [
            NavigationGraphEdge.routing_enabled.is_(True),
            or_(
                self._node_in_bbox(from_node, bbox),
                self._node_in_bbox(to_node, bbox),
            ),
        ]
        if channel_id is not None:
            clauses.append(NavigationGraphEdge.channel_id == channel_id)
        rows = list(
            (
                await self.session.execute(
                    select(NavigationGraphEdge, from_node, to_node)
                    .join(from_node, from_node.id == NavigationGraphEdge.from_node_id)
                    .join(to_node, to_node.id == NavigationGraphEdge.to_node_id)
                    .where(*clauses)
                    .order_by(NavigationGraphEdge.graph_version_id.desc(), NavigationGraphEdge.id)
                    .limit(limit + 1)
                )
            ).all()
        )
        if len(rows) > limit:
            truncated_layers.append("GRAPH_EDGE")
            rows = rows[:limit]
        return [
            NavigationMapLayerFeatureResponse(
                id=edge.id,
                layer_type_code="GRAPH_EDGE",
                name=edge.edge_code,
                geometry_json=edge.geometry_json,
                properties={
                    "graph_version_id": edge.graph_version_id,
                    "from_node_id": edge.from_node_id,
                    "to_node_id": edge.to_node_id,
                    "channel_id": edge.channel_id,
                    "length_km": float(edge.length_km) if edge.length_km is not None else None,
                    "quality_code": edge.quality_code,
                    "source_type_code": edge.source_type_code,
                    "unknown_constraint_flag": edge.unknown_constraint_flag,
                },
            )
            for edge, _from_node, _to_node in rows
        ]

    def _node_in_bbox(self, node, bbox: dict[str, float]):
        return (
            (node.longitude >= bbox["min_lng"])
            & (node.longitude <= bbox["max_lng"])
            & (node.latitude >= bbox["min_lat"])
            & (node.latitude <= bbox["max_lat"])
        )

    async def _route_layers(
        self,
        route_result_id: int,
    ) -> tuple[list[NavigationMapLayerFeatureResponse], list[NavigationMapLayerFeatureResponse]]:
        result = await self.session.get(NavigationRouteResult, route_result_id)
        if result is None:
            return [], []
        result_feature = NavigationMapLayerFeatureResponse(
            id=result.id,
            layer_type_code="ROUTE_RESULT",
            name=f"Route result {result.id}",
            geometry_json=result.geometry_json,
            properties={
                "request_id": result.request_id,
                "status_code": result.status_code,
                "quality_code": result.quality_code,
                "quality_score": result.quality_score,
                "distance_km": float(result.distance_km) if result.distance_km is not None else None,
                "edge_ids": result.edge_ids or [],
                "channel_ids": result.channel_ids or [],
            },
        )
        issues = list(
            (
                await self.session.execute(
                    select(NavigationRouteQualityIssue)
                    .where(NavigationRouteQualityIssue.route_result_id == route_result_id)
                    .order_by(NavigationRouteQualityIssue.id)
                    .limit(self.max_limit)
                )
            ).scalars()
        )
        issue_features = [
            NavigationMapLayerFeatureResponse(
                id=issue.id,
                layer_type_code="QUALITY_ISSUE",
                name=issue.issue_type_code,
                geometry_json=issue.geometry_json,
                properties={
                    "issue_type_code": issue.issue_type_code,
                    "severity_code": issue.severity_code,
                    "message": issue.message,
                    "suggestion": issue.suggestion,
                    "related_edge_id": issue.related_edge_id,
                    "related_node_id": issue.related_node_id,
                },
            )
            for issue in issues
        ]
        return [result_feature], issue_features

    async def _channel_layer_bbox(self, channel_id: int) -> dict[str, float] | None:
        boxes: list[dict[str, float]] = []
        water_rows = list(
            (
                await self.session.execute(
                    select(NavigationWaterArea)
                    .join(NavigationChannelWaterAreaMatch, NavigationChannelWaterAreaMatch.water_area_id == NavigationWaterArea.id)
                    .where(
                        NavigationChannelWaterAreaMatch.channel_id == channel_id,
                        NavigationChannelWaterAreaMatch.is_current.is_(True),
                        NavigationWaterArea.is_enabled.is_(True),
                    )
                )
            ).scalars()
        )
        for row in water_rows:
            box = self._model_bbox(row)
            if box:
                boxes.append(box)
        boundary_rows = list(
            (
                await self.session.execute(
                    select(NavigationChannelBoundary).where(
                        NavigationChannelBoundary.channel_id == channel_id,
                        or_(
                            NavigationChannelBoundary.is_current.is_(True),
                            NavigationChannelBoundary.coverage_policy_code == "RIVER_MATCH_CANDIDATE",
                        ),
                    )
                )
            ).scalars()
        )
        for row in boundary_rows:
            box = self._model_bbox(row)
            if box:
                boxes.append(box)
        centerline_rows = list(
            (
                await self.session.execute(
                    select(NavigationChannelCenterline).where(
                        NavigationChannelCenterline.channel_id == channel_id,
                        NavigationChannelCenterline.is_current.is_(True),
                    )
                )
            ).scalars()
        )
        for row in centerline_rows:
            box = self._model_bbox(row)
            if box:
                boxes.append(box)
        if not boxes:
            return None
        merged = boxes[0]
        for box in boxes[1:]:
            merged = self._merge_bbox(merged, box)
        return self._expand_bbox(merged, margin_degree=0.08)

    def _boundary_geometry(self, boundary: NavigationChannelBoundary) -> dict[str, Any] | None:
        if boundary.boundary_paths_low:
            return {
                "type": "MultiPolygon",
                "coordinates": [[ring] for ring in boundary.boundary_paths_low if isinstance(ring, list) and len(ring) >= 3],
            }
        return boundary.geometry_json

    def _model_bbox(self, row: Any) -> dict[str, float] | None:
        values = (
            getattr(row, "bbox_min_lng", None),
            getattr(row, "bbox_min_lat", None),
            getattr(row, "bbox_max_lng", None),
            getattr(row, "bbox_max_lat", None),
        )
        if any(value is None for value in values):
            return None
        return {
            "min_lng": float(values[0]),
            "min_lat": float(values[1]),
            "max_lng": float(values[2]),
            "max_lat": float(values[3]),
        }

    def _merge_bbox(self, left: dict[str, float], right: dict[str, float]) -> dict[str, float]:
        return {
            "min_lng": min(left["min_lng"], right["min_lng"]),
            "min_lat": min(left["min_lat"], right["min_lat"]),
            "max_lng": max(left["max_lng"], right["max_lng"]),
            "max_lat": max(left["max_lat"], right["max_lat"]),
        }

    def _expand_bbox(self, bbox: dict[str, float], *, margin_degree: float) -> dict[str, float]:
        return {
            "min_lng": max(-180.0, bbox["min_lng"] - margin_degree),
            "min_lat": max(-90.0, bbox["min_lat"] - margin_degree),
            "max_lng": min(180.0, bbox["max_lng"] + margin_degree),
            "max_lat": min(90.0, bbox["max_lat"] + margin_degree),
        }

    def _expanded_geometry_bbox(self, geometry: dict[str, Any] | None, *, margin_degree: float) -> dict[str, float] | None:
        points: list[tuple[float, float]] = []
        self._collect_geometry_points(geometry, points)
        if not points:
            return None
        lng_values = [point[0] for point in points]
        lat_values = [point[1] for point in points]
        return {
            "min_lng": max(-180.0, min(lng_values) - margin_degree),
            "min_lat": max(-90.0, min(lat_values) - margin_degree),
            "max_lng": min(180.0, max(lng_values) + margin_degree),
            "max_lat": min(90.0, max(lat_values) + margin_degree),
        }

    def _collect_geometry_points(self, geometry: Any, output: list[tuple[float, float]]) -> None:
        if not isinstance(geometry, dict):
            return
        geometry_type = geometry.get("type")
        coordinates = geometry.get("coordinates")
        if geometry_type == "Point":
            self._append_point(coordinates, output)
        elif geometry_type in {"LineString", "MultiPoint"}:
            self._append_points(coordinates, output)
        elif geometry_type in {"Polygon", "MultiLineString"}:
            for part in coordinates or []:
                self._append_points(part, output)
        elif geometry_type == "MultiPolygon":
            for polygon in coordinates or []:
                for ring in polygon or []:
                    self._append_points(ring, output)

    def _append_points(self, value: Any, output: list[tuple[float, float]]) -> None:
        if not isinstance(value, list):
            return
        for item in value:
            self._append_point(item, output)

    def _append_point(self, value: Any, output: list[tuple[float, float]]) -> None:
        if not isinstance(value, list | tuple) or len(value) < 2:
            return
        try:
            lng = float(value[0])
            lat = float(value[1])
        except (TypeError, ValueError):
            return
        if -180 <= lng <= 180 and -90 <= lat <= 90:
            output.append((lng, lat))
