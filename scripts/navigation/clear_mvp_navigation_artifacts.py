"""Remove historical MVP navigation artifacts from the local production database.

This cleanup keeps seed channels, seed boundaries, transport nodes, and real
river water areas intact. It only removes the controlled MVP graph, route
results, MVP centerlines, and generated MVP water-area corridors.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import (
    NavigationChannelCenterline,
    NavigationGraphEdge,
    NavigationGraphEdgeConstraint,
    NavigationGraphNode,
    NavigationGraphVersion,
    NavigationRouteQualityIssue,
    NavigationRouteRequest,
    NavigationRouteResult,
    NavigationWaterArea,
)


MVP_WATER_SOURCE_CODE = "MVP_JS_YRD_2026"
MVP_SCOPE_CODES = {"MVP", "YANGTZE_DELTA_MVP"}


@dataclass(slots=True)
class MvpCleanupSummary:
    dry_run: bool
    graph_versions: int
    graph_nodes: int
    graph_edges: int
    graph_edge_constraints: int
    route_requests: int
    route_results: int
    route_quality_issues: int
    centerlines: int
    water_areas: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_mvp_graph(row: NavigationGraphVersion) -> bool:
    version_code = (row.version_code or "").upper()
    scope_code = (row.scope_code or "").upper()
    source_summary = row.source_summary_json or {}
    return (
        version_code.startswith("MVP-")
        or scope_code in MVP_SCOPE_CODES
        or str(source_summary.get("source_code") or "").upper() == MVP_WATER_SOURCE_CODE
    )


async def clear_mvp_navigation_artifacts(
    *,
    session: AsyncSession,
    dry_run: bool = False,
) -> MvpCleanupSummary:
    graph_versions = [row for row in (await session.execute(select(NavigationGraphVersion))).scalars() if _is_mvp_graph(row)]
    graph_version_ids = [row.id for row in graph_versions]

    graph_edges = []
    graph_nodes = []
    route_requests = []
    route_results = []
    route_quality_issues = []
    graph_edge_constraints = []
    if graph_version_ids:
        graph_edges = list(
            (
                await session.execute(
                    select(NavigationGraphEdge).where(NavigationGraphEdge.graph_version_id.in_(graph_version_ids))
                )
            ).scalars()
        )
        graph_nodes = list(
            (
                await session.execute(
                    select(NavigationGraphNode).where(NavigationGraphNode.graph_version_id.in_(graph_version_ids))
                )
            ).scalars()
        )
        route_requests = list(
            (
                await session.execute(
                    select(NavigationRouteRequest).where(NavigationRouteRequest.graph_version_id.in_(graph_version_ids))
                )
            ).scalars()
        )
    edge_ids = [row.id for row in graph_edges]
    request_ids = [row.id for row in route_requests]
    if edge_ids:
        graph_edge_constraints = list(
            (
                await session.execute(
                    select(NavigationGraphEdgeConstraint).where(NavigationGraphEdgeConstraint.edge_id.in_(edge_ids))
                )
            ).scalars()
        )
    if request_ids:
        route_results = list(
            (
                await session.execute(
                    select(NavigationRouteResult).where(NavigationRouteResult.request_id.in_(request_ids))
                )
            ).scalars()
        )
    result_ids = [row.id for row in route_results]
    if result_ids:
        route_quality_issues = list(
            (
                await session.execute(
                    select(NavigationRouteQualityIssue).where(
                        NavigationRouteQualityIssue.route_result_id.in_(result_ids)
                    )
                )
            ).scalars()
        )

    centerlines = [
        row
        for row in (await session.execute(select(NavigationChannelCenterline))).scalars()
        if (row.centerline_code or "").upper().startswith("MVP-CL-")
        or (row.source_trace_json or {}).get("round") == "ROUND_12_MVP_ACCEPTANCE"
    ]
    water_areas = list(
        (
            await session.execute(
                select(NavigationWaterArea).where(NavigationWaterArea.source_code == MVP_WATER_SOURCE_CODE)
            )
        ).scalars()
    )

    summary = MvpCleanupSummary(
        dry_run=dry_run,
        graph_versions=len(graph_versions),
        graph_nodes=len(graph_nodes),
        graph_edges=len(graph_edges),
        graph_edge_constraints=len(graph_edge_constraints),
        route_requests=len(route_requests),
        route_results=len(route_results),
        route_quality_issues=len(route_quality_issues),
        centerlines=len(centerlines),
        water_areas=len(water_areas),
    )
    if dry_run:
        return summary

    if result_ids:
        await session.execute(
            delete(NavigationRouteQualityIssue).where(NavigationRouteQualityIssue.route_result_id.in_(result_ids))
        )
        await session.execute(delete(NavigationRouteResult).where(NavigationRouteResult.id.in_(result_ids)))
    if request_ids:
        await session.execute(delete(NavigationRouteRequest).where(NavigationRouteRequest.id.in_(request_ids)))
    if edge_ids:
        await session.execute(delete(NavigationGraphEdgeConstraint).where(NavigationGraphEdgeConstraint.edge_id.in_(edge_ids)))
        await session.execute(delete(NavigationGraphEdge).where(NavigationGraphEdge.id.in_(edge_ids)))
    if graph_nodes:
        await session.execute(delete(NavigationGraphNode).where(NavigationGraphNode.graph_version_id.in_(graph_version_ids)))
    if graph_version_ids:
        await session.execute(delete(NavigationGraphVersion).where(NavigationGraphVersion.id.in_(graph_version_ids)))
    if centerlines:
        await session.execute(delete(NavigationChannelCenterline).where(NavigationChannelCenterline.id.in_([row.id for row in centerlines])))
    if water_areas:
        await session.execute(delete(NavigationWaterArea).where(NavigationWaterArea.id.in_([row.id for row in water_areas])))
    await session.commit()
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clear local MVP navigation artifacts.")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    async with AsyncSessionLocal() as session:
        summary = await clear_mvp_navigation_artifacts(session=session, dry_run=args.dry_run)
    print(json.dumps(summary.as_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
