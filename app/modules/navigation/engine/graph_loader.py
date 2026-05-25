from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NavigationGraphEdge, NavigationGraphEdgeConstraint, NavigationGraphNode, NavigationGraphVersion
from app.modules.navigation.engine.geo import bbox_for_points
from app.modules.navigation.engine.types import LoadedGraph, RoutingEngineError


class NavigationGraphLoader:
    def __init__(
        self,
        session: AsyncSession,
        *,
        bbox_margin_degree: float = 1.0,
        bbox_margin_degrees: tuple[float, ...] | None = None,
        max_node_count: int = 50_000,
        max_edge_count: int = 50_000,
    ) -> None:
        self.session = session
        self.bbox_margin_degree = bbox_margin_degree
        self.bbox_margin_degrees = bbox_margin_degrees or (0.5, 1.0, 2.0, 4.0, 8.0)
        self.max_node_count = max_node_count
        self.max_edge_count = max_edge_count

    async def select_graph_version(self, graph_version_id: int | None) -> NavigationGraphVersion:
        if graph_version_id is not None:
            version = await self.session.scalar(
                select(NavigationGraphVersion).where(
                NavigationGraphVersion.id == graph_version_id,
                NavigationGraphVersion.status_code == "READY",
                NavigationGraphVersion.edge_count > 0,
                NavigationGraphVersion.scope_code.not_like("MVP%"),
            )
            )
            if version is None:
                raise RoutingEngineError("GRAPH_VERSION_NOT_READY", "Requested graph version is not READY")
            return version

        version = await self.session.scalar(
            select(NavigationGraphVersion)
            .where(
                NavigationGraphVersion.status_code == "READY",
                NavigationGraphVersion.is_active.is_(True),
                NavigationGraphVersion.edge_count > 0,
                NavigationGraphVersion.scope_code.not_like("MVP%"),
            )
            .order_by(NavigationGraphVersion.id.desc())
        )
        if version is None:
            raise RoutingEngineError("NO_ACTIVE_GRAPH_VERSION", "No active READY navigation graph version is available")
        return version

    async def load_graph(
        self,
        *,
        graph_version: NavigationGraphVersion,
        origin: tuple[float, float],
        destination: tuple[float, float],
    ) -> LoadedGraph:
        last_bbox: dict[str, float] | None = None
        for margin_degree in self._load_margins():
            bbox = bbox_for_points([origin, destination], margin_degree)
            last_bbox = bbox
            loaded = await self._load_graph_in_bbox(
                graph_version=graph_version,
                bbox=bbox,
                margin_degree=margin_degree,
            )
            if loaded is not None:
                return loaded
        raise RoutingEngineError(
            "NO_ROUTING_EDGE_IN_EXPANDED_BBOX",
            f"No routing-enabled graph edge found after expanding bbox to {self._load_margins()[-1]} degrees",
            issues=[],
        )

    def _load_margins(self) -> tuple[float, ...]:
        margins = tuple(float(item) for item in self.bbox_margin_degrees if float(item) > 0)
        if not margins:
            return (float(self.bbox_margin_degree),)
        return tuple(dict.fromkeys(margins))

    async def _load_graph_in_bbox(
        self,
        *,
        graph_version: NavigationGraphVersion,
        bbox: dict[str, float],
        margin_degree: float,
    ) -> LoadedGraph | None:
        node_rows = list(
            (
                await self.session.execute(
                    select(NavigationGraphNode)
                    .where(
                        NavigationGraphNode.graph_version_id == graph_version.id,
                        NavigationGraphNode.is_enabled.is_(True),
                        NavigationGraphNode.longitude >= bbox["min_lng"],
                        NavigationGraphNode.longitude <= bbox["max_lng"],
                        NavigationGraphNode.latitude >= bbox["min_lat"],
                        NavigationGraphNode.latitude <= bbox["max_lat"],
                    )
                    .order_by(NavigationGraphNode.id)
                    .limit(self.max_node_count + 1)
                )
            ).scalars()
        )
        if len(node_rows) > self.max_node_count:
            raise RoutingEngineError(
                "GRAPH_LOAD_TOO_LARGE",
                f"Graph node load exceeds configured limit at bbox margin {margin_degree}",
            )

        node_ids = {node.id for node in node_rows}
        if not node_ids:
            return None

        edge_rows = list(
            (
                await self.session.execute(
                    select(NavigationGraphEdge)
                    .where(
                        NavigationGraphEdge.graph_version_id == graph_version.id,
                        NavigationGraphEdge.from_node_id.in_(node_ids),
                        NavigationGraphEdge.to_node_id.in_(node_ids),
                    )
                    .order_by(NavigationGraphEdge.id)
                    .limit(self.max_edge_count + 1)
                )
            ).scalars()
        )
        if len(edge_rows) > self.max_edge_count:
            raise RoutingEngineError(
                "GRAPH_LOAD_TOO_LARGE",
                f"Graph edge load exceeds configured limit at bbox margin {margin_degree}",
            )
        if not any(edge.routing_enabled for edge in edge_rows):
            return None

        edge_ids = {edge.id for edge in edge_rows}
        constraints_by_edge_id: dict[int, list[NavigationGraphEdgeConstraint]] = {edge_id: [] for edge_id in edge_ids}
        if edge_ids:
            constraint_rows = list(
                (
                    await self.session.execute(
                        select(NavigationGraphEdgeConstraint).where(
                            NavigationGraphEdgeConstraint.edge_id.in_(edge_ids),
                            NavigationGraphEdgeConstraint.is_enabled.is_(True),
                        )
                    )
                ).scalars()
            )
            for constraint in constraint_rows:
                constraints_by_edge_id.setdefault(constraint.edge_id, []).append(constraint)

        return LoadedGraph(
            graph_version=graph_version,
            nodes={node.id: node for node in node_rows},
            edges={edge.id: edge for edge in edge_rows},
            constraints_by_edge_id=constraints_by_edge_id,
            load_bbox=bbox,
            load_margin_degree=margin_degree,
            loaded_node_count=len(node_rows),
            loaded_edge_count=len(edge_rows),
        )
