from __future__ import annotations

from decimal import Decimal
from typing import Any

import networkx as nx
from shapely.geometry import LineString, Point, mapping, shape

from app.models import NavigationGraphEdge
from app.modules.navigation.engine.geo import line_length_km, line_segment_between, reverse_line
from app.modules.navigation.engine.types import LoadedGraph, RouteIssue, RoutingEngineError, SearchResult, SearchSegment, SnapResult


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


def _constraint_block_reason(edge: NavigationGraphEdge, vessel_profile: dict[str, Any] | None) -> str | None:
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


def _edge_cost(edge: NavigationGraphEdge, routing_preference_code: str) -> float:
    length_km = float(edge.length_km or 0.001)
    grade_factor = 1.0
    if edge.technical_grade_code in {"I", "II", "III", "1", "2", "3"}:
        grade_factor = 0.85
    elif edge.technical_grade_code in {"V", "5"}:
        grade_factor = 1.2
    elif edge.technical_grade_code in {"VI", "VII", "6", "7"}:
        grade_factor = 1.5

    quality_factor = {
        "READY": 1.0,
        "READY_WITH_WARNING": 1.08,
        "LOW_CONFIDENCE": 1.4,
        "NEED_REVIEW": 1.7,
        "SHORT_EDGE_REVIEW": 1.5,
    }.get(edge.quality_code, 1.2)
    confidence_factor = 1.0 + max(0, 80 - int(edge.confidence_score or 0)) / 100
    lock_penalty = 8.0 if edge.lock_required and routing_preference_code == "AVOID_LOCKS" else (3.0 if edge.lock_required else 0.0)
    bridge_penalty = float(edge.bridge_count or 0) * 0.2
    unknown_penalty = 2.0 if edge.unknown_constraint_flag else 0.0
    review_penalty = 3.0 if edge.quality_code in {"NEED_REVIEW", "LOW_CONFIDENCE", "SHORT_EDGE_REVIEW"} else 0.0
    return length_km * grade_factor * quality_factor * confidence_factor + lock_penalty + bridge_penalty + unknown_penalty + review_penalty


def _segment_payload(
    *,
    from_key: str,
    to_key: str,
    edge: NavigationGraphEdge,
    geometry: LineString,
    cost: float,
    direction_code: str,
    virtual: bool = False,
) -> SearchSegment:
    return SearchSegment(
        from_key=from_key,
        to_key=to_key,
        edge_id=edge.id,
        channel_id=edge.channel_id,
        from_node_id=edge.from_node_id,
        to_node_id=edge.to_node_id,
        geometry_json=mapping(geometry),
        length_km=line_length_km(geometry),
        cost=cost,
        direction_code=direction_code,
        quality_code=edge.quality_code,
        lock_required=bool(edge.lock_required),
        bridge_count=int(edge.bridge_count or 0),
        unknown_constraint_flag=bool(edge.unknown_constraint_flag),
        virtual=virtual,
    )


class ConstrainedGraphSearch:
    def search(
        self,
        *,
        graph: LoadedGraph,
        origin_snap: SnapResult,
        destination_snap: SnapResult,
        vessel_profile: dict[str, Any] | None,
        routing_preference_code: str,
    ) -> SearchResult:
        nx_graph = nx.DiGraph()
        blocked_edge_ids: list[int] = []
        blocked_issues: list[RouteIssue] = []

        def add_segment(segment: SearchSegment) -> None:
            existing = nx_graph.get_edge_data(segment.from_key, segment.to_key)
            if existing is None or segment.cost < existing["segment"].cost:
                nx_graph.add_edge(segment.from_key, segment.to_key, weight=segment.cost, segment=segment)

        for node in graph.nodes.values():
            nx_graph.add_node(f"N:{node.id}")

        usable_edge_count = 0
        for edge in graph.edges.values():
            if not edge.routing_enabled:
                continue
            closed_constraints = [
                constraint for constraint in graph.constraints_by_edge_id.get(edge.id, [])
                if constraint.constraint_type_code == "CLOSED" and constraint.is_blocking
            ]
            block_reason = "EDGE_CLOSED" if closed_constraints else _constraint_block_reason(edge, vessel_profile)
            if block_reason:
                blocked_edge_ids.append(edge.id)
                blocked_issues.append(
                    RouteIssue(
                        block_reason,
                        "WARNING",
                        f"Edge {edge.edge_code} was excluded by vessel or closure constraint",
                        related_edge_id=edge.id,
                    )
                )
                continue
            geometry = shape(edge.geometry_json)
            if not isinstance(geometry, LineString) or geometry.is_empty:
                continue
            usable_edge_count += 1
            base_cost = _edge_cost(edge, routing_preference_code)
            forward = _segment_payload(
                from_key=f"N:{edge.from_node_id}",
                to_key=f"N:{edge.to_node_id}",
                edge=edge,
                geometry=geometry,
                cost=base_cost,
                direction_code="FORWARD",
            )
            if edge.direction_code in {"BIDIRECTIONAL", "FORWARD_ONLY"}:
                add_segment(forward)
            if edge.direction_code in {"BIDIRECTIONAL", "REVERSE_ONLY"}:
                add_segment(
                    _segment_payload(
                        from_key=f"N:{edge.to_node_id}",
                        to_key=f"N:{edge.from_node_id}",
                        edge=edge,
                        geometry=reverse_line(geometry),
                        cost=base_cost,
                        direction_code="REVERSE",
                    )
                )

        if usable_edge_count == 0:
            code = "VESSEL_CONSTRAINT_BLOCKED" if blocked_edge_ids else "NO_ROUTING_EDGE_IN_BBOX"
            raise RoutingEngineError(
                code,
                "No usable graph edge is available after constraints",
                issues=[
                    RouteIssue(code, "ERROR", "No usable graph edge is available after constraints"),
                    *blocked_issues,
                ],
            )

        start_key = self._attach_snap_node(nx_graph, graph, origin_snap, "ORIGIN", routing_preference_code)
        end_key = self._attach_snap_node(nx_graph, graph, destination_snap, "DESTINATION", routing_preference_code)
        self._attach_direct_same_edge(nx_graph, graph, origin_snap, destination_snap, routing_preference_code)

        try:
            node_path = nx.shortest_path(nx_graph, start_key, end_key, weight="weight")
        except nx.NetworkXNoPath as exc:
            raise RoutingEngineError(
                "GRAPH_DISCONNECTED",
                "No connected graph path between snapped endpoints",
                issues=[
                    RouteIssue("GRAPH_DISCONNECTED", "ERROR", "No connected graph path between snapped endpoints"),
                    *blocked_issues,
                ],
            ) from exc
        except nx.NodeNotFound as exc:
            raise RoutingEngineError(
                "NO_PATH_FOUND",
                "Snapped endpoint is not present in loaded graph",
                issues=[
                    RouteIssue("NO_PATH_FOUND", "ERROR", "Snapped endpoint is not present in loaded graph"),
                    *blocked_issues,
                ],
            ) from exc

        segments: list[SearchSegment] = []
        total_cost = 0.0
        for from_key, to_key in zip(node_path[:-1], node_path[1:]):
            data = nx_graph.get_edge_data(from_key, to_key)
            if not data:
                raise RoutingEngineError("PATH_SEARCH_FAILED", "Path edge payload is missing")
            segment: SearchSegment = data["segment"]
            segments.append(segment)
            total_cost += segment.cost

        return SearchResult(
            node_path=node_path,
            segments=segments,
            total_cost=total_cost,
            blocked_edge_ids=blocked_edge_ids,
            issues=blocked_issues,
        )

    def _attach_snap_node(
        self,
        nx_graph: nx.DiGraph,
        graph: LoadedGraph,
        snap: SnapResult,
        prefix: str,
        routing_preference_code: str,
    ) -> str:
        if snap.graph_node_id is not None:
            return f"N:{snap.graph_node_id}"
        if snap.graph_edge_id is None:
            raise RoutingEngineError(f"NO_GRAPH_NEAR_{prefix}", f"{prefix.title()} endpoint was not snapped to graph")
        edge = graph.edges.get(snap.graph_edge_id)
        if edge is None:
            raise RoutingEngineError(f"NO_GRAPH_NEAR_{prefix}", f"{prefix.title()} snapped edge is not loaded")
        edge_geometry = shape(edge.geometry_json)
        if not isinstance(edge_geometry, LineString):
            raise RoutingEngineError("EDGE_GEOMETRY_MISSING", "Snapped edge geometry is missing")
        temp_key = f"T:{prefix}"
        nx_graph.add_node(temp_key)
        snap_point = Point(snap.snap_point[0], snap.snap_point[1])
        from_node = graph.nodes[edge.from_node_id]
        to_node = graph.nodes[edge.to_node_id]
        from_point = Point(float(from_node.longitude), float(from_node.latitude))
        to_point = Point(float(to_node.longitude), float(to_node.latitude))
        base_cost = _edge_cost(edge, routing_preference_code)
        edge_length = max(float(edge.length_km or 0.001), 0.001)

        def add_virtual(a_key: str, b_key: str, a_point: Point, b_point: Point, direction: str) -> None:
            segment_geometry = line_segment_between(edge_geometry, a_point, b_point)
            segment_length = line_length_km(segment_geometry)
            cost = max(0.001, base_cost * (segment_length / edge_length))
            segment = _segment_payload(
                from_key=a_key,
                to_key=b_key,
                edge=edge,
                geometry=segment_geometry,
                cost=cost,
                direction_code=direction,
                virtual=True,
            )
            existing = nx_graph.get_edge_data(a_key, b_key)
            if existing is None or cost < existing["segment"].cost:
                nx_graph.add_edge(a_key, b_key, weight=cost, segment=segment)

        if edge.direction_code in {"BIDIRECTIONAL", "FORWARD_ONLY"}:
            add_virtual(f"N:{edge.from_node_id}", temp_key, from_point, snap_point, "FORWARD")
            add_virtual(temp_key, f"N:{edge.to_node_id}", snap_point, to_point, "FORWARD")
        if edge.direction_code in {"BIDIRECTIONAL", "REVERSE_ONLY"}:
            add_virtual(f"N:{edge.to_node_id}", temp_key, to_point, snap_point, "REVERSE")
            add_virtual(temp_key, f"N:{edge.from_node_id}", snap_point, from_point, "REVERSE")
        return temp_key

    def _attach_direct_same_edge(
        self,
        nx_graph: nx.DiGraph,
        graph: LoadedGraph,
        origin_snap: SnapResult,
        destination_snap: SnapResult,
        routing_preference_code: str,
    ) -> None:
        if not origin_snap.graph_edge_id or origin_snap.graph_edge_id != destination_snap.graph_edge_id:
            return
        edge = graph.edges.get(origin_snap.graph_edge_id)
        if edge is None:
            return
        edge_geometry = shape(edge.geometry_json)
        if not isinstance(edge_geometry, LineString):
            return
        origin_point = Point(origin_snap.snap_point[0], origin_snap.snap_point[1])
        destination_point = Point(destination_snap.snap_point[0], destination_snap.snap_point[1])
        origin_distance = edge_geometry.project(origin_point)
        destination_distance = edge_geometry.project(destination_point)
        if origin_distance == destination_distance:
            return
        base_cost = _edge_cost(edge, routing_preference_code)
        edge_length = max(float(edge.length_km or 0.001), 0.001)
        segment_geometry = line_segment_between(edge_geometry, origin_point, destination_point)
        if destination_distance < origin_distance:
            segment_geometry = reverse_line(segment_geometry)
        segment_length = line_length_km(segment_geometry)
        cost = max(0.001, base_cost * (segment_length / edge_length))
        if edge.direction_code in {"BIDIRECTIONAL", "FORWARD_ONLY"} and destination_distance > origin_distance:
            nx_graph.add_edge(
                "T:ORIGIN",
                "T:DESTINATION",
                weight=cost,
                segment=_segment_payload(
                    from_key="T:ORIGIN",
                    to_key="T:DESTINATION",
                    edge=edge,
                    geometry=segment_geometry,
                    cost=cost,
                    direction_code="FORWARD",
                    virtual=True,
                ),
            )
        if edge.direction_code in {"BIDIRECTIONAL", "REVERSE_ONLY"} and destination_distance < origin_distance:
            nx_graph.add_edge(
                "T:ORIGIN",
                "T:DESTINATION",
                weight=cost,
                segment=_segment_payload(
                    from_key="T:ORIGIN",
                    to_key="T:DESTINATION",
                    edge=edge,
                    geometry=segment_geometry,
                    cost=cost,
                    direction_code="REVERSE",
                    virtual=True,
                ),
            )
