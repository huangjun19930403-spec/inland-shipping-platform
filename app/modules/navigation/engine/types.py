from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models import NavigationGraphEdge, NavigationGraphEdgeConstraint, NavigationGraphNode, NavigationGraphVersion


@dataclass(slots=True)
class RoutePoint:
    longitude: float
    latitude: float
    name: str | None = None
    ref_type_code: str | None = None
    ref_id: int | None = None


@dataclass(slots=True)
class RouteIssue:
    issue_type_code: str
    severity_code: str
    message: str
    suggestion: str | None = None
    geometry_json: dict[str, Any] | None = None
    related_edge_id: int | None = None
    related_node_id: int | None = None


@dataclass(slots=True)
class SnapResult:
    role: str
    snap_type: str
    snap_distance_m: float
    snap_confidence: int
    snap_point: tuple[float, float]
    graph_node_id: int | None = None
    graph_edge_id: int | None = None
    quality_code: str = "HIGH"

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "snap_type": self.snap_type,
            "snap_distance_m": round(self.snap_distance_m, 3),
            "snap_confidence": self.snap_confidence,
            "snap_point": [self.snap_point[0], self.snap_point[1]],
            "graph_node_id": self.graph_node_id,
            "graph_edge_id": self.graph_edge_id,
            "quality_code": self.quality_code,
        }


@dataclass(slots=True)
class LoadedGraph:
    graph_version: NavigationGraphVersion
    nodes: dict[int, NavigationGraphNode]
    edges: dict[int, NavigationGraphEdge]
    constraints_by_edge_id: dict[int, list[NavigationGraphEdgeConstraint]] = field(default_factory=dict)
    load_bbox: dict[str, float] | None = None
    load_margin_degree: float | None = None
    loaded_node_count: int = 0
    loaded_edge_count: int = 0


@dataclass(slots=True)
class SearchSegment:
    from_key: str
    to_key: str
    edge_id: int | None
    channel_id: int | None
    from_node_id: int | None
    to_node_id: int | None
    geometry_json: dict[str, Any]
    length_km: float
    cost: float
    direction_code: str
    quality_code: str
    lock_required: bool
    bridge_count: int
    unknown_constraint_flag: bool
    virtual: bool = False


@dataclass(slots=True)
class SearchResult:
    node_path: list[str]
    segments: list[SearchSegment]
    total_cost: float
    blocked_edge_ids: list[int] = field(default_factory=list)
    issues: list[RouteIssue] = field(default_factory=list)


class RoutingEngineError(Exception):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        issues: list[RouteIssue] | None = None,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.issues = issues or [RouteIssue(error_code, "ERROR", message)]
        super().__init__(message)
