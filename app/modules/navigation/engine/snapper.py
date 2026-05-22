from __future__ import annotations

from decimal import Decimal

from shapely.geometry import LineString, Point, shape

from app.modules.navigation.engine.geo import nearest_point_on_line, point_distance_m
from app.modules.navigation.engine.types import LoadedGraph, RoutePoint, RoutingEngineError, SnapResult

PORT_NODE_TYPES = {"PORT", "TERMINAL", "ANCHORAGE"}


def _float(value: float | Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _quality(distance_m: float) -> tuple[str, int]:
    if distance_m <= 200:
        return "HIGH", 95
    if distance_m <= 500:
        return "MEDIUM", 80
    if distance_m <= 2000:
        return "LOW", 50
    return "FAILED", 0


class GraphSnapper:
    def __init__(self, *, max_auto_snap_m: float = 2000.0) -> None:
        self.max_auto_snap_m = max_auto_snap_m

    def snap(self, *, role: str, point: RoutePoint, graph: LoadedGraph) -> SnapResult:
        source = Point(point.longitude, point.latitude)
        nearest_port: tuple[int, Point, float] | None = None
        for node in graph.nodes.values():
            if node.node_type_code not in PORT_NODE_TYPES:
                continue
            node_lng = _float(node.longitude)
            node_lat = _float(node.latitude)
            if node_lng is None or node_lat is None:
                continue
            node_point = Point(node_lng, node_lat)
            distance_m = point_distance_m(source, node_point)
            if nearest_port is None or distance_m < nearest_port[2]:
                nearest_port = (node.id, node_point, distance_m)

        if nearest_port is not None and nearest_port[2] <= 200:
            quality, confidence = _quality(nearest_port[2])
            return SnapResult(
                role=role,
                snap_type="GRAPH_NODE",
                snap_distance_m=nearest_port[2],
                snap_confidence=confidence,
                snap_point=(nearest_port[1].x, nearest_port[1].y),
                graph_node_id=nearest_port[0],
                quality_code=quality,
            )

        nearest_edge: tuple[int, Point, float] | None = None
        for edge in graph.edges.values():
            if not edge.routing_enabled or not edge.geometry_json:
                continue
            geometry = shape(edge.geometry_json)
            if not isinstance(geometry, LineString) or geometry.is_empty:
                continue
            projected = nearest_point_on_line(geometry, source)
            distance_m = point_distance_m(source, projected)
            if nearest_edge is None or distance_m < nearest_edge[2]:
                nearest_edge = (edge.id, projected, distance_m)

        if nearest_edge is None:
            raise RoutingEngineError(f"NO_GRAPH_NEAR_{role}", f"No graph edge near {role.lower()} endpoint")

        quality, confidence = _quality(nearest_edge[2])
        if nearest_edge[2] > self.max_auto_snap_m:
            raise RoutingEngineError(
                f"{role}_TOO_FAR_FROM_GRAPH",
                f"{role.title()} endpoint is too far from graph: {nearest_edge[2]:.1f}m",
            )
        return SnapResult(
            role=role,
            snap_type="GRAPH_EDGE",
            snap_distance_m=nearest_edge[2],
            snap_confidence=confidence,
            snap_point=(nearest_edge[1].x, nearest_edge[1].y),
            graph_edge_id=nearest_edge[0],
            quality_code=quality,
        )
