from __future__ import annotations

from itertools import islice

import networkx as nx

from app.modules.navigation.engine.route_cost import normalize_planning_mode
from app.modules.navigation.engine.route_search import PreparedRouteGraph, RouteSearch
from app.modules.navigation.engine.types import RoutingEngineError, SearchResult


class RouteAlternativesGenerator:
    def __init__(self, search: RouteSearch, *, candidate_limit: int = 30) -> None:
        self.search = search
        self.candidate_limit = candidate_limit

    def generate(
        self,
        *,
        prepared: PreparedRouteGraph,
        planning_mode_code: str,
        requested_count: int,
    ) -> list[SearchResult]:
        count = max(1, min(int(requested_count or 1), 5))
        mode = normalize_planning_mode(planning_mode_code)
        algorithm = "DIJKSTRA" if mode == "SHORTEST" else "A_STAR"
        results: list[SearchResult] = []
        seen_edge_paths: list[tuple[int, ...]] = []

        try:
            path_iter = nx.shortest_simple_paths(
                prepared.nx_graph,
                prepared.start_key,
                prepared.end_key,
                weight="weight",
            )
            for node_path in islice(path_iter, self.candidate_limit):
                result = self.search.result_from_node_path(
                    prepared=prepared,
                    node_path=list(node_path),
                    planning_mode_code=mode,
                    algorithm_code=algorithm,
                )
                edge_path = tuple(segment.edge_id for segment in result.segments if segment.edge_id is not None)
                if not edge_path:
                    continue
                if edge_path in seen_edge_paths:
                    continue
                if any(_jaccard(edge_path, existing) > 0.9 for existing in seen_edge_paths):
                    continue
                seen_edge_paths.append(edge_path)
                results.append(result)
                if len(results) >= count:
                    break
        except nx.NetworkXNoPath as exc:
            raise self.search.no_path_error(prepared) from exc
        except nx.NodeNotFound as exc:
            raise RoutingEngineError("NO_PATH_FOUND", "Snapped endpoint is not present in loaded graph") from exc

        if not results:
            raise self.search.no_path_error(prepared)
        return results


def _jaccard(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    left = set(a)
    right = set(b)
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)
