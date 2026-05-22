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
        max_node_count: int = 50_000,
        max_edge_count: int = 50_000,
    ) -> None:
        self.session = session
        self.bbox_margin_degree = bbox_margin_degree
        self.max_node_count = max_node_count
        self.max_edge_count = max_edge_count

    async def select_graph_version(self, graph_version_id: int | None) -> NavigationGraphVersion:
        if graph_version_id is not None:
            version = await self.session.scalar(
                select(NavigationGraphVersion).where(
                    NavigationGraphVersion.id == graph_version_id,
                    NavigationGraphVersion.status_code == "READY",
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
        bbox = bbox_for_points([origin, destination], self.bbox_margin_degree)
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
            raise RoutingEngineError("GRAPH_LOAD_TOO_LARGE", "Graph node load exceeds configured limit")

        node_ids = {node.id for node in node_rows}
        if not node_ids:
            raise RoutingEngineError("NO_ROUTING_EDGE_IN_BBOX", "No graph nodes found near route endpoints")

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
            raise RoutingEngineError("GRAPH_LOAD_TOO_LARGE", "Graph edge load exceeds configured limit")
        if not any(edge.routing_enabled for edge in edge_rows):
            raise RoutingEngineError("NO_ROUTING_EDGE_IN_BBOX", "No routing-enabled graph edge found near route endpoints")

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
        )
