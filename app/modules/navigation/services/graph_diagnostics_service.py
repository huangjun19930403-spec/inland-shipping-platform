from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NavigationGraphEdge, NavigationGraphEdgeConstraint, NavigationGraphVersion


def graph_issue_counts(report: dict[str, Any]) -> dict[str, int]:
    issues: list[Any] = []
    for key in ("issues", "build_issues"):
        value = report.get(key)
        if isinstance(value, list):
            issues.extend(value)

    counts: Counter[str] = Counter()
    for item in issues:
        if not isinstance(item, dict):
            continue
        code = item.get("issue_code") or item.get("issue_type_code") or item.get("code")
        if code:
            counts[str(code)] += 1
    return dict(sorted(counts.items()))


def report_int(report: dict[str, Any], key: str) -> int | None:
    value = report.get(key)
    return int(value) if isinstance(value, int) else None


def activation_blockers(diagnostics: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if diagnostics.get("status_code") != "READY":
        blockers.append("GRAPH_NOT_READY")
    if int(diagnostics.get("edge_count") or 0) <= 0:
        blockers.append("NO_GRAPH_EDGE")
    if int(diagnostics.get("routing_edge_count") or 0) <= 0:
        blockers.append("NO_ROUTING_EDGE")
    if int(diagnostics.get("blocking_issue_count") or 0) > 0:
        blockers.append("HAS_BLOCKING_ISSUES")
    component_count = diagnostics.get("component_count")
    if isinstance(component_count, int) and component_count > 1:
        blockers.append("GRAPH_DISCONNECTED")
    return blockers


def activation_warnings(diagnostics: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if int(diagnostics.get("unknown_constraint_edge_count") or 0) > 0:
        warnings.append("UNKNOWN_CONSTRAINT_DATA")
    if int(diagnostics.get("warning_issue_count") or 0) > 0:
        warnings.append("HAS_WARNING_ISSUES")
    quality_score = diagnostics.get("quality_score")
    if isinstance(quality_score, int) and quality_score < 80:
        warnings.append("LOW_QUALITY_SCORE")
    return warnings


async def build_graph_diagnostics(
    session: AsyncSession,
    graph_version: NavigationGraphVersion | None,
) -> dict[str, Any] | None:
    if graph_version is None:
        return None

    graph_version_id = int(graph_version.id)
    routing_edge_count = int(
        await session.scalar(
            select(func.count())
            .select_from(NavigationGraphEdge)
            .where(
                NavigationGraphEdge.graph_version_id == graph_version_id,
                NavigationGraphEdge.routing_enabled.is_(True),
            )
        )
        or 0
    )
    unknown_constraint_edge_count = int(
        await session.scalar(
            select(func.count())
            .select_from(NavigationGraphEdge)
            .where(
                NavigationGraphEdge.graph_version_id == graph_version_id,
                NavigationGraphEdge.unknown_constraint_flag.is_(True),
            )
        )
        or 0
    )
    constraint_edge_count = int(
        await session.scalar(
            select(func.count(func.distinct(NavigationGraphEdgeConstraint.edge_id)))
            .select_from(NavigationGraphEdgeConstraint)
            .join(NavigationGraphEdge, NavigationGraphEdge.id == NavigationGraphEdgeConstraint.edge_id)
            .where(NavigationGraphEdge.graph_version_id == graph_version_id)
        )
        or 0
    )

    report = graph_version.validation_report_json if isinstance(graph_version.validation_report_json, dict) else {}
    edge_count = int(graph_version.edge_count or 0)
    known_constraint_edges = max(edge_count - unknown_constraint_edge_count, 0)
    constraint_completeness_ratio = round(known_constraint_edges / edge_count, 4) if edge_count else None
    source_summary = graph_version.source_summary_json if isinstance(graph_version.source_summary_json, dict) else {}

    diagnostics: dict[str, Any] = {
        "graph_version_id": graph_version_id,
        "version_code": graph_version.version_code,
        "status_code": graph_version.status_code,
        "is_active": bool(graph_version.is_active),
        "quality_score": graph_version.quality_score,
        "node_count": int(graph_version.node_count or 0),
        "edge_count": edge_count,
        "routing_edge_count": routing_edge_count,
        "unknown_constraint_edge_count": unknown_constraint_edge_count,
        "constraint_edge_count": constraint_edge_count,
        "constraint_completeness_ratio": constraint_completeness_ratio,
        "component_count": report_int(report, "component_count"),
        "blocking_issue_count": report_int(report, "blocking_issue_count"),
        "warning_issue_count": report_int(report, "warning_issue_count"),
        "issue_counts": graph_issue_counts(report),
        "source_boundary_ids": source_summary.get("source_boundary_ids") or [],
        "source_centerline_ids": source_summary.get("centerline_ids") or [],
        "source_segment_ids": source_summary.get("centerline_segment_ids") or [],
        "source_channel_ids": source_summary.get("channel_ids") or [],
        "source_segment_topology_preserved": bool(source_summary.get("source_segment_topology_preserved")),
    }
    blockers = activation_blockers(diagnostics)
    warnings = activation_warnings(diagnostics)
    diagnostics["activation_blockers"] = blockers
    diagnostics["activation_warnings"] = warnings
    diagnostics["can_activate"] = len(blockers) == 0
    return diagnostics
