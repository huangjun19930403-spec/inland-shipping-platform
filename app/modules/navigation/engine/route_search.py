from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import networkx as nx
from shapely.geometry import LineString, Point, mapping, shape

from app.models import NavigationGraphEdge
from app.modules.navigation.engine.geo import line_length_km, line_segment_between, point_distance_m, reverse_line
from app.modules.navigation.engine.route_cost import (
    HARD_BLOCK_REASON_LABELS,
    RouteCostCalculator,
    RouteEdgeCostBreakdown,
    hard_block_reason,
    normalize_planning_mode,
)
from app.modules.navigation.engine.types import LoadedGraph, RouteIssue, RoutingEngineError, SearchResult, SearchSegment, SnapResult


@dataclass(slots=True)
class PreparedRouteGraph:
    nx_graph: nx.DiGraph
    start_key: str
    end_key: str
    blocked_edge_ids: list[int] = field(default_factory=list)
    blocked_edge_summary: dict[str, int] = field(default_factory=dict)
    blocked_issues: list[RouteIssue] = field(default_factory=list)
    usable_edge_count: int = 0


class RouteSearch:
    def __init__(self, *, cost_calculator: RouteCostCalculator | None = None, alternative_candidate_limit: int = 30) -> None:
        self.cost_calculator = cost_calculator or RouteCostCalculator()
        self.alternative_candidate_limit = alternative_candidate_limit

    def search(
        self,
        *,
        graph: LoadedGraph,
        origin_snap: SnapResult,
        destination_snap: SnapResult,
        vessel_profile: dict[str, Any] | None,
        planning_mode_code: str,
    ) -> SearchResult:
        prepared = self.prepare_graph(
            graph=graph,
            origin_snap=origin_snap,
            destination_snap=destination_snap,
            vessel_profile=vessel_profile,
            planning_mode_code=planning_mode_code,
        )
        mode = normalize_planning_mode(planning_mode_code)
        algorithm = "DIJKSTRA" if mode == "SHORTEST" else "A_STAR"
        try:
            if algorithm == "A_STAR":
                node_path = nx.astar_path(
                    prepared.nx_graph,
                    prepared.start_key,
                    prepared.end_key,
                    heuristic=lambda a, b: self.heuristic_km(prepared.nx_graph, a, b),
                    weight="weight",
                )
            else:
                node_path = nx.dijkstra_path(prepared.nx_graph, prepared.start_key, prepared.end_key, weight="weight")
        except nx.NetworkXNoPath as exc:
            raise self.no_path_error(prepared) from exc
        except nx.NodeNotFound as exc:
            raise RoutingEngineError(
                "NO_PATH_FOUND",
                "Snapped endpoint is not present in loaded graph",
                issues=[RouteIssue("NO_PATH_FOUND", "ERROR", "Snapped endpoint is not present in loaded graph"), *prepared.blocked_issues],
                explain=self._failure_explain(prepared),
            ) from exc
        return self._result_from_node_path(
            prepared=prepared,
            node_path=node_path,
            planning_mode_code=mode,
            algorithm_code=algorithm,
        )

    def prepare_graph(
        self,
        *,
        graph: LoadedGraph,
        origin_snap: SnapResult,
        destination_snap: SnapResult,
        vessel_profile: dict[str, Any] | None,
        planning_mode_code: str,
    ) -> PreparedRouteGraph:
        nx_graph = nx.DiGraph()
        blocked_edge_ids: list[int] = []
        blocked_edge_summary: dict[str, int] = {}
        blocked_issues: list[RouteIssue] = []
        mode = normalize_planning_mode(planning_mode_code)

        def add_segment(segment: SearchSegment) -> None:
            existing = nx_graph.get_edge_data(segment.from_key, segment.to_key)
            if existing is None or segment.cost < existing["segment"].cost:
                nx_graph.add_edge(segment.from_key, segment.to_key, weight=segment.cost, segment=segment)

        for node in graph.nodes.values():
            nx_graph.add_node(f"N:{node.id}", lng=float(node.longitude), lat=float(node.latitude))

        usable_edge_count = 0
        for edge in graph.edges.values():
            constraints = graph.constraints_by_edge_id.get(edge.id, [])
            block_reason = hard_block_reason(edge, constraints=constraints, vessel_profile=vessel_profile)
            if block_reason:
                blocked_edge_ids.append(edge.id)
                blocked_edge_summary[block_reason] = blocked_edge_summary.get(block_reason, 0) + 1
                blocked_issues.append(
                    RouteIssue(
                        block_reason,
                        "WARNING",
                        HARD_BLOCK_REASON_LABELS.get(block_reason, f"Edge {edge.edge_code} was excluded from route search"),
                        related_edge_id=edge.id,
                    )
                )
                continue
            geometry = shape(edge.geometry_json)
            if not isinstance(geometry, LineString) or geometry.is_empty:
                blocked_edge_summary["EDGE_GEOMETRY_MISSING"] = blocked_edge_summary.get("EDGE_GEOMETRY_MISSING", 0) + 1
                continue
            usable_edge_count += 1
            if edge.direction_code in {"BIDIRECTIONAL", "FORWARD_ONLY"}:
                add_segment(
                    self._segment_payload(
                        from_key=f"N:{edge.from_node_id}",
                        to_key=f"N:{edge.to_node_id}",
                        edge=edge,
                        geometry=geometry,
                        direction_code="FORWARD",
                        planning_mode_code=mode,
                    )
                )
            if edge.direction_code in {"BIDIRECTIONAL", "REVERSE_ONLY"}:
                add_segment(
                    self._segment_payload(
                        from_key=f"N:{edge.to_node_id}",
                        to_key=f"N:{edge.from_node_id}",
                        edge=edge,
                        geometry=reverse_line(geometry),
                        direction_code="REVERSE",
                        planning_mode_code=mode,
                    )
                )

        if usable_edge_count == 0:
            code = "VESSEL_CONSTRAINT_BLOCKED" if blocked_edge_ids else "NO_ROUTING_EDGE_IN_BBOX"
            prepared = PreparedRouteGraph(
                nx_graph=nx_graph,
                start_key="",
                end_key="",
                blocked_edge_ids=blocked_edge_ids,
                blocked_edge_summary=blocked_edge_summary,
                blocked_issues=blocked_issues,
                usable_edge_count=usable_edge_count,
            )
            raise RoutingEngineError(
                code,
                "No usable graph edge is available after constraints",
                issues=[RouteIssue(code, "ERROR", "No usable graph edge is available after constraints"), *blocked_issues],
                explain=self._failure_explain(prepared),
            )

        start_key = self._attach_snap_node(nx_graph, graph, origin_snap, "ORIGIN", mode)
        end_key = self._attach_snap_node(nx_graph, graph, destination_snap, "DESTINATION", mode)
        self._attach_direct_same_edge(nx_graph, graph, origin_snap, destination_snap, mode)
        return PreparedRouteGraph(
            nx_graph=nx_graph,
            start_key=start_key,
            end_key=end_key,
            blocked_edge_ids=blocked_edge_ids,
            blocked_edge_summary=blocked_edge_summary,
            blocked_issues=blocked_issues,
            usable_edge_count=usable_edge_count,
        )

    def result_from_node_path(
        self,
        *,
        prepared: PreparedRouteGraph,
        node_path: list[str],
        planning_mode_code: str,
        algorithm_code: str,
    ) -> SearchResult:
        return self._result_from_node_path(
            prepared=prepared,
            node_path=node_path,
            planning_mode_code=planning_mode_code,
            algorithm_code=algorithm_code,
        )

    def _result_from_node_path(
        self,
        *,
        prepared: PreparedRouteGraph,
        node_path: list[str],
        planning_mode_code: str,
        algorithm_code: str,
    ) -> SearchResult:
        segments: list[SearchSegment] = []
        total_cost = 0.0
        for from_key, to_key in zip(node_path[:-1], node_path[1:]):
            data = prepared.nx_graph.get_edge_data(from_key, to_key)
            if not data:
                raise RoutingEngineError("PATH_SEARCH_FAILED", "Path edge payload is missing")
            segment: SearchSegment = data["segment"]
            segments.append(segment)
            total_cost += segment.cost
        return SearchResult(
            node_path=node_path,
            segments=segments,
            total_cost=round(total_cost, 6),
            blocked_edge_ids=list(prepared.blocked_edge_ids),
            blocked_edge_summary=dict(prepared.blocked_edge_summary),
            search_summary=self._search_summary(prepared),
            issues=list(prepared.blocked_issues),
            algorithm_code=algorithm_code,
            planning_mode_code=normalize_planning_mode(planning_mode_code),
        )

    def _segment_payload(
        self,
        *,
        from_key: str,
        to_key: str,
        edge: NavigationGraphEdge,
        geometry: LineString,
        direction_code: str,
        planning_mode_code: str,
        virtual: bool = False,
        cost_breakdown: RouteEdgeCostBreakdown | None = None,
    ) -> SearchSegment:
        length_km = line_length_km(geometry)
        breakdown = cost_breakdown or self.cost_calculator.calculate(
            edge,
            planning_mode_code=planning_mode_code,
            length_km=length_km,
            direction_code=direction_code,
        )
        return SearchSegment(
            from_key=from_key,
            to_key=to_key,
            edge_id=edge.id,
            channel_id=edge.channel_id,
            from_node_id=edge.from_node_id,
            to_node_id=edge.to_node_id,
            geometry_json=mapping(geometry),
            length_km=length_km,
            cost=breakdown.total_cost,
            direction_code=direction_code,
            quality_code=edge.quality_code,
            lock_required=bool(edge.lock_required),
            bridge_count=int(edge.bridge_count or 0),
            unknown_constraint_flag=bool(edge.unknown_constraint_flag),
            virtual=virtual,
            cost_breakdown=breakdown.as_dict(),
        )

    def _attach_snap_node(
        self,
        nx_graph: nx.DiGraph,
        graph: LoadedGraph,
        snap: SnapResult,
        prefix: str,
        planning_mode_code: str,
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
        nx_graph.add_node(temp_key, lng=float(snap.snap_point[0]), lat=float(snap.snap_point[1]))
        snap_point = Point(snap.snap_point[0], snap.snap_point[1])
        from_node = graph.nodes[edge.from_node_id]
        to_node = graph.nodes[edge.to_node_id]
        from_point = Point(float(from_node.longitude), float(from_node.latitude))
        to_point = Point(float(to_node.longitude), float(to_node.latitude))
        full_breakdown = self.cost_calculator.calculate(edge, planning_mode_code=planning_mode_code)
        edge_length = max(float(edge.length_km or 0.001), 0.001)

        def add_virtual(a_key: str, b_key: str, a_point: Point, b_point: Point, direction: str) -> None:
            segment_geometry = line_segment_between(edge_geometry, a_point, b_point)
            segment_length = line_length_km(segment_geometry)
            breakdown = full_breakdown.scaled(segment_length / edge_length, length_km=segment_length)
            segment = self._segment_payload(
                from_key=a_key,
                to_key=b_key,
                edge=edge,
                geometry=segment_geometry,
                direction_code=direction,
                planning_mode_code=planning_mode_code,
                virtual=True,
                cost_breakdown=breakdown,
            )
            existing = nx_graph.get_edge_data(a_key, b_key)
            if existing is None or segment.cost < existing["segment"].cost:
                nx_graph.add_edge(a_key, b_key, weight=segment.cost, segment=segment)

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
        planning_mode_code: str,
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
        segment_geometry = line_segment_between(edge_geometry, origin_point, destination_point)
        if destination_distance < origin_distance:
            segment_geometry = reverse_line(segment_geometry)
        segment_length = line_length_km(segment_geometry)
        full_breakdown = self.cost_calculator.calculate(edge, planning_mode_code=planning_mode_code)
        edge_length = max(float(edge.length_km or 0.001), 0.001)
        breakdown = full_breakdown.scaled(segment_length / edge_length, length_km=segment_length)
        if edge.direction_code in {"BIDIRECTIONAL", "FORWARD_ONLY"} and destination_distance > origin_distance:
            nx_graph.add_edge(
                "T:ORIGIN",
                "T:DESTINATION",
                weight=breakdown.total_cost,
                segment=self._segment_payload(
                    from_key="T:ORIGIN",
                    to_key="T:DESTINATION",
                    edge=edge,
                    geometry=segment_geometry,
                    direction_code="FORWARD",
                    planning_mode_code=planning_mode_code,
                    virtual=True,
                    cost_breakdown=breakdown,
                ),
            )
        if edge.direction_code in {"BIDIRECTIONAL", "REVERSE_ONLY"} and destination_distance < origin_distance:
            nx_graph.add_edge(
                "T:ORIGIN",
                "T:DESTINATION",
                weight=breakdown.total_cost,
                segment=self._segment_payload(
                    from_key="T:ORIGIN",
                    to_key="T:DESTINATION",
                    edge=edge,
                    geometry=segment_geometry,
                    direction_code="REVERSE",
                    planning_mode_code=planning_mode_code,
                    virtual=True,
                    cost_breakdown=breakdown,
                ),
            )

    def heuristic_km(self, nx_graph: nx.DiGraph, a_key: str, b_key: str) -> float:
        a = nx_graph.nodes.get(a_key, {})
        b = nx_graph.nodes.get(b_key, {})
        if a.get("lng") is None or a.get("lat") is None or b.get("lng") is None or b.get("lat") is None:
            return 0.0
        return point_distance_m(Point(float(a["lng"]), float(a["lat"])), Point(float(b["lng"]), float(b["lat"]))) / 1000.0 * 0.8

    def no_path_error(self, prepared: PreparedRouteGraph) -> RoutingEngineError:
        return RoutingEngineError(
            "GRAPH_DISCONNECTED",
            "No connected graph path between snapped endpoints",
            issues=[RouteIssue("GRAPH_DISCONNECTED", "ERROR", "No connected graph path between snapped endpoints"), *prepared.blocked_issues],
            explain=self._failure_explain(prepared),
        )

    def _search_summary(self, prepared: PreparedRouteGraph) -> dict[str, Any]:
        return {
            "loaded_node_count": prepared.nx_graph.number_of_nodes(),
            "loaded_edge_count": prepared.nx_graph.number_of_edges(),
            "usable_edge_count": prepared.usable_edge_count,
        }

    def _failure_explain(self, prepared: PreparedRouteGraph) -> dict[str, Any]:
        return {
            "blocked_edge_summary": dict(prepared.blocked_edge_summary),
            "search_summary": self._search_summary(prepared),
        }
