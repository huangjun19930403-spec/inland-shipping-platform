from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from shapely.geometry import shape

from app.models import NavigationAnnotationTask, NavigationGraphEdge, NavigationGraphEdgeConstraint, NavigationGraphVersion
from app.modules.navigation.schemas import NavigationGraphIssueEdgeListResponse, NavigationGraphIssueEdgeResponse


EDGE_REVIEW_QUALITY_CODES = {"NEED_REVIEW", "LOW_CONFIDENCE", "SHORT_EDGE_REVIEW", "READY_WITH_WARNING"}
OPEN_TASK_STATUSES = {"OPEN", "IN_PROGRESS", "NEED_REVIEW"}


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


async def list_graph_issue_edges(
    session: AsyncSession,
    *,
    graph_version_id: int,
    issue_code: str | None = None,
    channel_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
    include_geometry: bool = True,
) -> NavigationGraphIssueEdgeListResponse:
    graph_version = await session.get(NavigationGraphVersion, graph_version_id)
    if graph_version is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError("NavigationGraphVersion", graph_version_id)

    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), 100))
    normalized_issue_code = issue_code.upper() if issue_code else None

    stmt = select(NavigationGraphEdge).where(NavigationGraphEdge.graph_version_id == graph_version_id)
    stmt = stmt.where(
        (NavigationGraphEdge.unknown_constraint_flag.is_(True))
        | (NavigationGraphEdge.routing_enabled.is_(False))
        | (NavigationGraphEdge.quality_code.in_(EDGE_REVIEW_QUALITY_CODES))
    )
    if channel_id:
        stmt = stmt.where(NavigationGraphEdge.channel_id == channel_id)

    all_rows = list((await session.execute(stmt.order_by(NavigationGraphEdge.id))).scalars())
    if normalized_issue_code:
        all_rows = [row for row in all_rows if normalized_issue_code in edge_issue_codes(row)]

    total = len(all_rows)
    page_rows = all_rows[(page - 1) * page_size : page * page_size]
    edge_ids = [int(row.id) for row in page_rows]
    task_by_edge_id = await _open_task_ids_by_edge(session, graph_version_id=graph_version_id, edge_ids=edge_ids)
    constraint_count_by_edge_id = await _constraint_counts_by_edge(session, edge_ids=edge_ids)

    return NavigationGraphIssueEdgeListResponse(
        graph_version_id=graph_version_id,
        version_code=graph_version.version_code,
        issue_code=normalized_issue_code,
        total=total,
        page=page,
        page_size=page_size,
        items=[
            edge_issue_response(
                row,
                include_geometry=include_geometry,
                open_task_id=task_by_edge_id.get(int(row.id)),
                constraint_count=constraint_count_by_edge_id.get(int(row.id), 0),
            )
            for row in page_rows
        ],
    )


def edge_issue_codes(edge: NavigationGraphEdge) -> list[str]:
    codes: list[str] = []
    if edge.unknown_constraint_flag:
        codes.append("UNKNOWN_CONSTRAINT_DATA")
    if not edge.routing_enabled:
        codes.append("ROUTING_DISABLED")
    if edge.quality_code in EDGE_REVIEW_QUALITY_CODES:
        codes.append(str(edge.quality_code))
    summary = edge.validation_summary_json if isinstance(edge.validation_summary_json, dict) else {}
    raw_issue_codes = summary.get("issue_codes")
    if isinstance(raw_issue_codes, list):
        for code in raw_issue_codes:
            if code:
                codes.append(str(code).upper())
    return sorted(set(codes))


def edge_issue_response(
    edge: NavigationGraphEdge,
    *,
    include_geometry: bool,
    open_task_id: int | None,
    constraint_count: int,
) -> NavigationGraphIssueEdgeResponse:
    geometry = edge.geometry_json if isinstance(edge.geometry_json, dict) else None
    bbox, center = _geometry_bbox_and_center(geometry)
    issue_codes = edge_issue_codes(edge)
    return NavigationGraphIssueEdgeResponse(
        id=int(edge.id),
        graph_version_id=int(edge.graph_version_id),
        edge_code=edge.edge_code,
        channel_id=int(edge.channel_id) if edge.channel_id is not None else None,
        centerline_id=int(edge.centerline_id) if edge.centerline_id is not None else None,
        from_node_id=int(edge.from_node_id),
        to_node_id=int(edge.to_node_id),
        length_km=float(edge.length_km or 0),
        routing_enabled=bool(edge.routing_enabled),
        quality_code=edge.quality_code,
        unknown_constraint_flag=bool(edge.unknown_constraint_flag),
        issue_codes=issue_codes,
        constraint_count=constraint_count,
        open_annotation_task_id=open_task_id,
        bbox=bbox,
        center=center,
        geometry_json=geometry if include_geometry else None,
        repair_hint=_repair_hint(issue_codes),
    )


async def _open_task_ids_by_edge(
    session: AsyncSession,
    *,
    graph_version_id: int,
    edge_ids: list[int],
) -> dict[int, int]:
    if not edge_ids:
        return {}
    rows = list(
        (
            await session.execute(
                select(NavigationAnnotationTask)
                .where(
                    NavigationAnnotationTask.graph_version_id == graph_version_id,
                    NavigationAnnotationTask.target_type_code == "GRAPH_EDGE",
                    NavigationAnnotationTask.target_id.in_(edge_ids),
                    NavigationAnnotationTask.status_code.in_(OPEN_TASK_STATUSES),
                )
                .order_by(NavigationAnnotationTask.id)
            )
        ).scalars()
    )
    output: dict[int, int] = {}
    for row in rows:
        if row.target_id is not None and int(row.target_id) not in output:
            output[int(row.target_id)] = int(row.id)
    return output


async def _constraint_counts_by_edge(session: AsyncSession, *, edge_ids: list[int]) -> dict[int, int]:
    if not edge_ids:
        return {}
    rows = list(
        await session.execute(
            select(NavigationGraphEdgeConstraint.edge_id, func.count())
            .where(NavigationGraphEdgeConstraint.edge_id.in_(edge_ids))
            .group_by(NavigationGraphEdgeConstraint.edge_id)
        )
    )
    return {int(edge_id): int(count or 0) for edge_id, count in rows}


def _geometry_bbox_and_center(geometry: dict[str, Any] | None) -> tuple[dict[str, float | None], dict[str, float | None]]:
    empty_bbox = {"min_lng": None, "min_lat": None, "max_lng": None, "max_lat": None}
    empty_center = {"lng": None, "lat": None}
    if not geometry:
        return empty_bbox, empty_center
    try:
        parsed = shape(geometry)
    except Exception:
        return empty_bbox, empty_center
    if parsed.is_empty:
        return empty_bbox, empty_center
    min_lng, min_lat, max_lng, max_lat = parsed.bounds
    representative = parsed.interpolate(0.5, normalized=True) if hasattr(parsed, "interpolate") else parsed.representative_point()
    return (
        {
            "min_lng": float(min_lng),
            "min_lat": float(min_lat),
            "max_lng": float(max_lng),
            "max_lat": float(max_lat),
        },
        {"lng": float(representative.x), "lat": float(representative.y)},
    )


def _repair_hint(issue_codes: list[str]) -> str:
    if "UNKNOWN_CONSTRAINT_DATA" in issue_codes:
        return "补齐该图边关联桥梁、船闸、吃水、吨级等通航约束资料，完成后重建并激活 Graph。"
    if "ROUTING_DISABLED" in issue_codes:
        return "检查该图边为何不可路由，修复中心线区段或约束后重建 Graph。"
    return "检查图边质量问题，必要时回到中心线区段修复并重建 Graph。"
