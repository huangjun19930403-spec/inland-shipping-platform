from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.modules.navigation.engine.types import RouteIssue, RoutingEngineError, SearchResult, SnapResult


class RouteExplainer:
    def cost_breakdown_summary(self, search_result: SearchResult) -> dict[str, float]:
        totals: defaultdict[str, float] = defaultdict(float)
        for breakdown in self.edge_cost_breakdowns(search_result):
            for key in (
                "distance_cost",
                "quality_penalty",
                "unknown_constraint_penalty",
                "lock_penalty",
                "bridge_penalty",
                "vessel_constraint_penalty",
                "direction_penalty",
                "total_cost",
            ):
                totals[key] += float(breakdown.get(key) or 0)
        return {key: round(value, 6) for key, value in totals.items()}

    def edge_cost_breakdowns(self, search_result: SearchResult) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for segment in search_result.segments:
            if segment.cost_breakdown:
                output.append(dict(segment.cost_breakdown))
        return output

    def explain_success(
        self,
        *,
        search_result: SearchResult,
        issues: list[RouteIssue],
        alternative_rank: int,
        alternative_count: int,
    ) -> dict[str, Any]:
        cost_summary = self.cost_breakdown_summary(search_result)
        why_selected = [
            f"{search_result.planning_mode_code} mode optimized {search_result.algorithm_code} cost",
            f"Total route cost {search_result.total_cost:.3f}",
        ]
        if search_result.blocked_edge_summary:
            why_selected.append("Hard constraints excluded unavailable graph edges before route search")
        warnings = sorted({issue.issue_type_code for issue in issues if issue.severity_code != "ERROR"})[:8]
        if warnings:
            why_selected.append(f"Quality review required for: {', '.join(warnings)}")
        return {
            "planning_mode_code": search_result.planning_mode_code,
            "algorithm_code": search_result.algorithm_code,
            "cost_total": round(search_result.total_cost, 6),
            "cost_breakdown_summary": cost_summary,
            "edge_cost_breakdowns": self.edge_cost_breakdowns(search_result),
            "why_selected": why_selected,
            "blocked_edge_summary": dict(search_result.blocked_edge_summary),
            "search_summary": dict(search_result.search_summary),
            "alternative_rank": alternative_rank,
            "alternative_count": alternative_count,
        }

    def explain_failure(
        self,
        *,
        exc: RoutingEngineError,
        origin_snap: SnapResult | None,
        destination_snap: SnapResult | None,
        attempted_graph_version_ids: list[int] | None,
    ) -> dict[str, Any]:
        explain = dict(exc.explain or {})
        blocked_summary = dict(explain.get("blocked_edge_summary") or {})
        search_summary = dict(explain.get("search_summary") or {})
        snap_summary = dict(explain.get("snap_summary") or {})
        snap_summary.setdefault("origin_snap", origin_snap.as_dict() if origin_snap else None)
        snap_summary.setdefault("destination_snap", destination_snap.as_dict() if destination_snap else None)
        explain.update(
            {
                "attempted_graph_version_ids": list(attempted_graph_version_ids or []),
                "snap_summary": snap_summary,
                "blocked_edge_summary": blocked_summary,
                "search_summary": {
                    "loaded_node_count": search_summary.get("loaded_node_count", 0),
                    "loaded_edge_count": search_summary.get("loaded_edge_count", 0),
                    "usable_edge_count": search_summary.get("usable_edge_count", 0),
                },
                "next_actions": self.next_actions(exc.error_code, blocked_summary),
            }
        )
        return explain

    def next_actions(self, error_code: str, blocked_edge_summary: dict[str, int]) -> list[str]:
        if error_code == "NO_ACTIVE_GRAPH_VERSION":
            return ["Publish centerlines, then build and activate a navigation Graph."]
        if error_code in {"NO_ROUTING_EDGE_IN_EXPANDED_BBOX", "NO_ROUTING_EDGE_IN_BBOX"}:
            return ["Check whether endpoints are close to published centerlines.", "Build a Graph covering the endpoint area."]
        if error_code in {"ORIGIN_TOO_FAR_FROM_GRAPH", "DESTINATION_TOO_FAR_FROM_GRAPH"}:
            return ["Check whether endpoints can snap near the navigation channel."]
        if error_code == "GRAPH_DISCONNECTED":
            return ["Repair centerline gaps.", "Rebuild and activate the Graph."]
        if error_code == "VESSEL_CONSTRAINT_BLOCKED" or blocked_edge_summary:
            actions = ["Relax vessel parameters or complete channel constraint data."]
            if any(key.startswith("VSL_") for key in blocked_edge_summary):
                actions.append("Check beam, length, draft, air draft, and tonnage against channel limits.")
            if blocked_edge_summary.get("EDGE_CLOSED"):
                actions.append("Check closed edges or temporary closure constraints.")
            return actions
        return ["Check endpoints, Graph activation, and centerline connectivity."]
