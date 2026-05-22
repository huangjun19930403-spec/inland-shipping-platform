from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shapely.geometry import LineString, shape

from app.modules.navigation.engine.geo import merge_coordinates
from app.modules.navigation.engine.types import RoutingEngineError, SearchResult


@dataclass(slots=True)
class AssembledPath:
    geometry_json: dict[str, Any]
    distance_km: float
    edge_ids: list[int]
    channel_ids: list[int]
    passed_node_ids: list[int]
    passed_lock_count: int
    passed_bridge_count: int


class PathAssembler:
    def assemble(self, search_result: SearchResult) -> AssembledPath:
        if not search_result.segments:
            raise RoutingEngineError("PATH_ASSEMBLY_FAILED", "Path search returned no edge segments")

        lines: list[LineString] = []
        edge_ids: list[int] = []
        channel_ids: list[int] = []
        passed_node_ids: list[int] = []
        lock_edge_ids: set[int] = set()
        bridge_count = 0
        distance_km = 0.0

        for segment in search_result.segments:
            geometry = shape(segment.geometry_json)
            if not isinstance(geometry, LineString) or geometry.is_empty:
                raise RoutingEngineError("EDGE_GEOMETRY_MISSING", "Path segment geometry is missing")
            lines.append(geometry)
            distance_km += segment.length_km
            if segment.edge_id is not None and segment.edge_id not in edge_ids:
                edge_ids.append(segment.edge_id)
            if segment.channel_id is not None and segment.channel_id not in channel_ids:
                channel_ids.append(segment.channel_id)
            for node_id in (segment.from_node_id, segment.to_node_id):
                if node_id is not None and node_id not in passed_node_ids:
                    passed_node_ids.append(node_id)
            if segment.lock_required and segment.edge_id is not None:
                lock_edge_ids.add(segment.edge_id)
            bridge_count += segment.bridge_count

        coordinates = merge_coordinates(lines)
        if len(coordinates) < 2:
            raise RoutingEngineError("PATH_ASSEMBLY_FAILED", "Assembled path has fewer than two coordinates")
        return AssembledPath(
            geometry_json={"type": "LineString", "coordinates": coordinates},
            distance_km=round(distance_km, 4),
            edge_ids=edge_ids,
            channel_ids=channel_ids,
            passed_node_ids=passed_node_ids,
            passed_lock_count=len(lock_edge_ids),
            passed_bridge_count=bridge_count,
        )
