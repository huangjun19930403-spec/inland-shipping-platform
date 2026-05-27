from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models import NavigationGraphVersion
from app.modules.navigation.schemas import (
    NavigationGraphActivateResponse,
    NavigationGraphBuildRequest,
    NavigationGraphBuildResponse,
)
from app.modules.navigation.services.graph_build_service import build_graph_from_centerlines
from app.modules.navigation.services.graph_diagnostics_service import build_graph_diagnostics


DEFAULT_REAL_GRAPH_SCOPE = "REAL-JS-YRD"


class NavigationGraphWorkbenchService:
    """Graph build and activation workflow used by the navigation workbench."""

    def __init__(self, session: AsyncSession, helpers: Any) -> None:
        self.session = session
        self.helpers = helpers

    async def build_graph_version(
        self,
        body: NavigationGraphBuildRequest,
        *,
        created_by: int | None,
    ) -> NavigationGraphBuildResponse:
        scope_code = (body.scope_code or DEFAULT_REAL_GRAPH_SCOPE).upper()
        version_code = body.version_code or f"{scope_code}-GRAPH-{self.helpers._now().strftime('%Y%m%d%H%M%S')}"
        try:
            summary = await build_graph_from_centerlines(
                session=self.session,
                version_code=version_code,
                version_name=body.version_name,
                scope_code=scope_code,
                channel_codes=body.channel_codes,
                activate=body.activate,
            )
        except ValueError as exc:
            raise ConflictError(str(exc)) from exc
        graph_version = await self.session.get(NavigationGraphVersion, summary.graph_version_id)
        if graph_version is not None:
            graph_version.created_by = created_by
            await self.session.commit()
        diagnostics = await build_graph_diagnostics(self.session, graph_version)
        return NavigationGraphBuildResponse(
            version_code=summary.version_code,
            graph_version_id=summary.graph_version_id,
            status_code=summary.status_code,
            node_count=summary.node_count,
            edge_count=summary.edge_count,
            channel_count=summary.channel_count,
            quality_score=summary.quality_score,
            centerline_count=summary.centerline_count,
            connector_edge_count=summary.connector_edge_count,
            constraint_count=summary.constraint_count,
            validation_report=summary.validation_report,
            diagnostics=diagnostics,
        )

    async def activate_graph_version(self, graph_version_id: int) -> NavigationGraphActivateResponse:
        graph_version = await self.session.get(NavigationGraphVersion, graph_version_id)
        if graph_version is None:
            raise NotFoundError("NavigationGraphVersion", graph_version_id)
        diagnostics = await build_graph_diagnostics(self.session, graph_version)
        if graph_version.status_code != "READY":
            raise ConflictError("只有 READY graph version 可以激活", detail={"diagnostics": diagnostics})
        blockers = list((diagnostics or {}).get("activation_blockers") or [])
        if blockers:
            raise ConflictError(
                "Graph 诊断未通过，不能激活",
                detail={"activation_blockers": blockers, "diagnostics": diagnostics},
            )
        active_versions = list(
            (
                await self.session.execute(
                    select(NavigationGraphVersion).where(
                        NavigationGraphVersion.scope_code == graph_version.scope_code,
                        NavigationGraphVersion.is_active.is_(True),
                        NavigationGraphVersion.id != graph_version.id,
                    )
                )
            ).scalars()
        )
        for row in active_versions:
            row.is_active = False
        graph_version.is_active = True
        await self.session.commit()
        diagnostics = await build_graph_diagnostics(self.session, graph_version)
        return NavigationGraphActivateResponse(
            graph_version_id=graph_version.id,
            version_code=graph_version.version_code,
            scope_code=graph_version.scope_code,
            status_code=graph_version.status_code,
            is_active=True,
            diagnostics=diagnostics,
        )
