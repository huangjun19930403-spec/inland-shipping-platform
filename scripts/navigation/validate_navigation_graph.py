"""Validate navigation graph versions.

Round 7 validation reads graph nodes/edges and writes a quality report. It does
not create route requests, route results, or fallback geometries.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import NavigationGraphEdge, NavigationGraphNode, NavigationGraphVersion


@dataclass(slots=True)
class GraphValidationIssue:
    issue_code: str
    severity_code: str
    message: str
    node_id: int | None = None
    edge_id: int | None = None
    annotation_candidate: dict[str, Any] | None = None


@dataclass(slots=True)
class GraphValidationReport:
    graph_version_id: int
    version_code: str
    status_code: str
    quality_score: int
    node_count: int
    edge_count: int
    routing_edge_count: int
    component_count: int
    blocking_issue_count: int
    warning_issue_count: int
    issues: list[GraphValidationIssue] = field(default_factory=list)
    annotation_task_candidates: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["issues"] = [asdict(issue) for issue in self.issues]
        return payload


def _components(nodes: list[NavigationGraphNode], edges: list[NavigationGraphEdge]) -> list[set[int]]:
    adjacency: dict[int, set[int]] = defaultdict(set)
    for node in nodes:
        adjacency[node.id] = set()
    for edge in edges:
        if not edge.routing_enabled:
            continue
        adjacency[edge.from_node_id].add(edge.to_node_id)
        adjacency[edge.to_node_id].add(edge.from_node_id)

    seen: set[int] = set()
    components: list[set[int]] = []
    for node_id in adjacency:
        if node_id in seen:
            continue
        queue: deque[int] = deque([node_id])
        component: set[int] = set()
        seen.add(node_id)
        while queue:
            current = queue.popleft()
            component.add(current)
            for neighbor in adjacency[current]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        components.append(component)
    return components


def _candidate(issue_code: str, target_type: str, target_id: int | None, message: str) -> dict[str, Any]:
    return {
        "task_type_code": "GRAPH_QUALITY_REVIEW",
        "target_type_code": target_type,
        "target_id": target_id,
        "issue_code": issue_code,
        "issue_summary": message,
        "priority_code": "HIGH" if issue_code in {"GRAPH_DISCONNECTED", "EDGE_OUT_OF_BOUNDARY"} else "MEDIUM",
    }


async def validate_navigation_graph(
    *,
    session: AsyncSession,
    graph_version_id: int | None = None,
    version_code: str | None = None,
    update_version: bool = True,
) -> GraphValidationReport:
    if graph_version_id is None and version_code is None:
        raise ValueError("graph_version_id or version_code is required")

    stmt = select(NavigationGraphVersion)
    if graph_version_id is not None:
        stmt = stmt.where(NavigationGraphVersion.id == graph_version_id)
    else:
        stmt = stmt.where(NavigationGraphVersion.version_code == version_code)
    graph_version = (await session.execute(stmt)).scalar_one_or_none()
    if graph_version is None:
        raise ValueError("Graph version was not found")

    nodes = list(
        (
            await session.execute(
                select(NavigationGraphNode)
                .where(NavigationGraphNode.graph_version_id == graph_version.id)
                .order_by(NavigationGraphNode.id)
            )
        ).scalars()
    )
    edges = list(
        (
            await session.execute(
                select(NavigationGraphEdge)
                .where(NavigationGraphEdge.graph_version_id == graph_version.id)
                .order_by(NavigationGraphEdge.id)
            )
        ).scalars()
    )
    routing_edges = [edge for edge in edges if edge.routing_enabled]
    issues: list[GraphValidationIssue] = []

    if not nodes:
        issues.append(GraphValidationIssue("NO_GRAPH_NODE", "BLOCKING", "Graph version has no nodes"))
    if not edges:
        issues.append(GraphValidationIssue("NO_GRAPH_EDGE", "BLOCKING", "Graph version has no edges"))

    endpoint_ids: set[int] = set()
    for edge in routing_edges:
        endpoint_ids.add(edge.from_node_id)
        endpoint_ids.add(edge.to_node_id)
        if edge.quality_code in {"OUT_OF_BOUNDARY", "BROKEN", "DISABLED"}:
            message = f"Edge {edge.edge_code} is not routable quality: {edge.quality_code}"
            issues.append(
                GraphValidationIssue(
                    "EDGE_OUT_OF_BOUNDARY" if edge.quality_code == "OUT_OF_BOUNDARY" else "EDGE_NOT_ROUTABLE",
                    "BLOCKING",
                    message,
                    edge_id=edge.id,
                    annotation_candidate=_candidate("EDGE_OUT_OF_BOUNDARY", "GRAPH_EDGE", edge.id, message),
                )
            )
        if edge.quality_code in {"NEED_REVIEW", "LOW_CONFIDENCE", "SHORT_EDGE_REVIEW", "READY_WITH_WARNING"}:
            issues.append(
                GraphValidationIssue(
                    edge.quality_code,
                    "WARNING",
                    f"Edge {edge.edge_code} requires review: {edge.quality_code}",
                    edge_id=edge.id,
                    annotation_candidate=_candidate(edge.quality_code, "GRAPH_EDGE", edge.id, f"Review edge {edge.edge_code}"),
                )
            )
        if edge.unknown_constraint_flag:
            issues.append(
                GraphValidationIssue(
                    "UNKNOWN_CONSTRAINT_DATA",
                    "WARNING",
                    f"Edge {edge.edge_code} has incomplete navigation constraint data",
                    edge_id=edge.id,
                )
            )

    for node in nodes:
        if node.id not in endpoint_ids:
            message = f"Node {node.node_code} is not connected to an enabled edge"
            issues.append(
                GraphValidationIssue(
                    "ISOLATED_NODE",
                    "BLOCKING",
                    message,
                    node_id=node.id,
                    annotation_candidate=_candidate("ISOLATED_NODE", "GRAPH_NODE", node.id, message),
                )
            )

    components = _components(nodes, routing_edges) if nodes else []
    non_empty_components = [component for component in components if component]
    if len(non_empty_components) > 1:
        message = f"Graph has {len(non_empty_components)} disconnected components"
        issues.append(
            GraphValidationIssue(
                "GRAPH_DISCONNECTED",
                "BLOCKING",
                message,
                annotation_candidate=_candidate("GRAPH_DISCONNECTED", "GRAPH_VERSION", graph_version.id, message),
            )
        )

    blocking_count = sum(1 for issue in issues if issue.severity_code == "BLOCKING")
    warning_count = sum(1 for issue in issues if issue.severity_code == "WARNING")
    score = 100
    score -= min(60, blocking_count * 25)
    score -= min(35, warning_count * 3)
    if not edges:
        score = 0
    score = max(0, min(100, score))
    status_code = "READY" if blocking_count == 0 and bool(edges) else "FAILED"
    annotation_candidates = [issue.annotation_candidate for issue in issues if issue.annotation_candidate]

    report = GraphValidationReport(
        graph_version_id=graph_version.id,
        version_code=graph_version.version_code,
        status_code=status_code,
        quality_score=score,
        node_count=len(nodes),
        edge_count=len(edges),
        routing_edge_count=len(routing_edges),
        component_count=len(non_empty_components),
        blocking_issue_count=blocking_count,
        warning_issue_count=warning_count,
        issues=issues,
        annotation_task_candidates=annotation_candidates,
    )

    if update_version:
        graph_version.node_count = len(nodes)
        graph_version.edge_count = len(edges)
        graph_version.quality_score = score
        graph_version.status_code = status_code
        graph_version.is_active = bool(graph_version.is_active and status_code == "READY")
        graph_version.validation_report_json = report.as_dict()
        await session.commit()

    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a navigation graph version.")
    parser.add_argument("--graph-version-id", type=int, default=None)
    parser.add_argument("--version-code", default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--no-update", action="store_true")
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    async with AsyncSessionLocal() as session:
        report = await validate_navigation_graph(
            session=session,
            graph_version_id=args.graph_version_id,
            version_code=args.version_code,
            update_version=not args.no_update,
        )
    payload = report.as_dict()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
