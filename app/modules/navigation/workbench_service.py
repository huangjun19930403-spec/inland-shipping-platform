from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import (
    NavigationAnnotationTask,
    NavigationChannelCenterline,
    NavigationGeometryDraft,
    NavigationGraphEdge,
    NavigationGraphVersion,
    NavigationWaterArea,
)
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.modules.navigation.schemas import (
    NavigationBoundaryListItemResponse,
    NavigationCenterlineListItemResponse,
    NavigationGeometryDraftApproveRequest,
    NavigationGeometryDraftCreateRequest,
    NavigationGeometryDraftResponse,
    NavigationGeometryDraftUpdateRequest,
    NavigationGraphActivateResponse,
    NavigationGraphBuildRequest,
    NavigationGraphBuildResponse,
    NavigationGraphVersionListItemResponse,
    NavigationWaterAreaListItemResponse,
    NavigationWorkbenchChannelResponse,
    NavigationWorkbenchSummaryResponse,
)
from scripts.navigation.build_graph_from_centerline import build_graph_from_centerlines


DRAFT_GEOMETRY_TYPES = {
    "CENTERLINE": {"LINESTRING"},
    "BOUNDARY": {"POLYGON", "MULTIPOLYGON"},
    "WATER_AREA": {"POLYGON", "MULTIPOLYGON"},
}
FINAL_DRAFT_STATUSES = {"PUBLISHED", "REJECTED"}
REAL_WATER_SOURCE_CODE = "RIVER_SHAPEFILE_2026"
DEFAULT_REAL_GRAPH_SCOPE = "REAL-JS-YRD"


class NavigationWorkbenchService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def summary(self) -> NavigationWorkbenchSummaryResponse:
        channels = list(
            (
                await self.session.execute(
                    select(NavigationChannel)
                    .where(NavigationChannel.is_enabled.is_(True))
                    .order_by(NavigationChannel.display_priority.desc(), NavigationChannel.sort_order, NavigationChannel.id)
                )
            ).scalars()
        )
        channel_ids = [row.id for row in channels]
        boundary_counts = await self._counts_by_channel(
            NavigationChannelBoundary.channel_id,
            select(NavigationChannelBoundary.channel_id, func.count()).where(
                NavigationChannelBoundary.channel_id.in_(channel_ids)
            ),
        )
        current_boundary_counts = await self._counts_by_channel(
            NavigationChannelBoundary.channel_id,
            select(NavigationChannelBoundary.channel_id, func.count()).where(
                NavigationChannelBoundary.channel_id.in_(channel_ids),
                NavigationChannelBoundary.is_current.is_(True),
                NavigationChannelBoundary.geometry_status_code == "AVAILABLE",
            ),
        )
        centerline_counts = await self._counts_by_channel(
            NavigationChannelCenterline.channel_id,
            select(NavigationChannelCenterline.channel_id, func.count()).where(
                NavigationChannelCenterline.channel_id.in_(channel_ids)
            ),
        )
        approved_centerline_counts = await self._counts_by_channel(
            NavigationChannelCenterline.channel_id,
            select(NavigationChannelCenterline.channel_id, func.count()).where(
                NavigationChannelCenterline.channel_id.in_(channel_ids),
                NavigationChannelCenterline.is_current.is_(True),
                NavigationChannelCenterline.review_status_code == "APPROVED",
                NavigationChannelCenterline.quality_code.in_({"READY", "READY_WITH_WARNING"}),
            ),
        )
        active_graph_version = await self._active_graph_version()
        active_edge_counts: dict[int, int] = {}
        if active_graph_version is not None:
            active_edge_counts = await self._counts_by_channel(
                NavigationGraphEdge.channel_id,
                select(NavigationGraphEdge.channel_id, func.count()).where(
                    NavigationGraphEdge.graph_version_id == active_graph_version.id,
                    NavigationGraphEdge.channel_id.in_(channel_ids),
                    NavigationGraphEdge.routing_enabled.is_(True),
                ),
            )

        channel_rows = [
            NavigationWorkbenchChannelResponse(
                id=channel.id,
                channel_code=channel.channel_code,
                channel_name=channel.channel_name,
                display_name=channel.display_name,
                planning_level_code=channel.planning_level_code,
                channel_type_code=channel.channel_type_code,
                review_required=channel.review_required,
                boundary_count=boundary_counts.get(channel.id, 0),
                current_boundary_count=current_boundary_counts.get(channel.id, 0),
                centerline_count=centerline_counts.get(channel.id, 0),
                approved_current_centerline_count=approved_centerline_counts.get(channel.id, 0),
                active_graph_edge_count=active_edge_counts.get(channel.id, 0),
                boundary_status_code="READY" if current_boundary_counts.get(channel.id, 0) else "MISSING",
                centerline_status_code="READY" if approved_centerline_counts.get(channel.id, 0) else "MISSING",
                graph_status_code="READY" if active_edge_counts.get(channel.id, 0) else "MISSING",
            )
            for channel in channels
        ]
        stats = {
            "channel_count": len(channels),
            "water_area_count": int(await self.session.scalar(select(func.count()).select_from(NavigationWaterArea)) or 0),
            "real_water_area_count": int(
                await self.session.scalar(
                    select(func.count()).select_from(NavigationWaterArea).where(
                        NavigationWaterArea.source_code == REAL_WATER_SOURCE_CODE,
                        NavigationWaterArea.is_enabled.is_(True),
                    )
                )
                or 0
            ),
            "current_boundary_channel_count": sum(1 for row in channel_rows if row.current_boundary_count > 0),
            "approved_centerline_channel_count": sum(1 for row in channel_rows if row.approved_current_centerline_count > 0),
            "active_graph_channel_count": sum(1 for row in channel_rows if row.active_graph_edge_count > 0),
            "draft_count": int(await self.session.scalar(select(func.count()).select_from(NavigationGeometryDraft)) or 0),
            "open_annotation_task_count": int(
                await self.session.scalar(
                    select(func.count()).select_from(NavigationAnnotationTask).where(
                        NavigationAnnotationTask.status_code.in_({"OPEN", "IN_PROGRESS", "NEED_REVIEW"})
                    )
                )
                or 0
            ),
        }
        return NavigationWorkbenchSummaryResponse(
            stats=stats,
            active_graph_version=self._graph_version_dict(active_graph_version) if active_graph_version else None,
            channels=channel_rows,
            warnings=[
                "生产体验默认使用真实 revier 水系资产和清洗 seed 数据；MVP/示例数据不得作为 active graph。",
                "READY 只代表业务路径图和几何结果可用，不代表官方安全通航确认。",
                "无 approved/current centerline 的航道不会进入 graph，polygon/boundary 不能替代路径搜索。",
            ],
        )

    async def list_water_areas(
        self,
        *,
        keyword: str | None = None,
        limit: int = 50,
    ) -> list[NavigationWaterAreaListItemResponse]:
        stmt = select(NavigationWaterArea).where(NavigationWaterArea.is_enabled.is_(True))
        if keyword:
            like = f"%{keyword.strip()}%"
            stmt = stmt.where(
                (NavigationWaterArea.water_name.like(like)) | (NavigationWaterArea.normalized_water_name.like(like))
            )
        rows = list(
            (
                await self.session.execute(
                    stmt.order_by(NavigationWaterArea.id).limit(self._limit(limit, default=50, max_value=200))
                )
            ).scalars()
        )
        return [
            NavigationWaterAreaListItemResponse(
                id=row.id,
                source_code=row.source_code,
                source_layer_name=row.source_layer_name,
                water_name=row.water_name,
                water_type_code=row.water_type_code,
                geometry_status_code=row.geometry_status_code,
                bbox=self._bbox_dict(row),
                area_km2=self._float(row.area_km2),
            )
            for row in rows
        ]

    async def list_centerlines(
        self,
        *,
        channel_id: int | None = None,
        limit: int = 50,
    ) -> list[NavigationCenterlineListItemResponse]:
        stmt = select(NavigationChannelCenterline, NavigationChannel).join(
            NavigationChannel, NavigationChannel.id == NavigationChannelCenterline.channel_id
        )
        if channel_id:
            stmt = stmt.where(NavigationChannelCenterline.channel_id == channel_id)
        rows = list(
            (
                await self.session.execute(
                    stmt.order_by(
                        NavigationChannelCenterline.is_current.desc(),
                        NavigationChannelCenterline.id.desc(),
                    ).limit(self._limit(limit, default=50, max_value=200))
                )
            ).all()
        )
        return [
            NavigationCenterlineListItemResponse(
                id=centerline.id,
                channel_id=centerline.channel_id,
                channel_code=channel.channel_code,
                channel_name=channel.channel_name,
                centerline_code=centerline.centerline_code,
                centerline_name=centerline.centerline_name,
                source_type_code=centerline.source_type_code,
                quality_code=centerline.quality_code,
                review_status_code=centerline.review_status_code,
                confidence_score=centerline.confidence_score,
                is_current=centerline.is_current,
                geometry_json=centerline.geometry_json,
            )
            for centerline, channel in rows
        ]

    async def list_boundaries(
        self,
        *,
        channel_id: int | None = None,
        limit: int = 50,
    ) -> list[NavigationBoundaryListItemResponse]:
        stmt = select(NavigationChannelBoundary, NavigationChannel).join(
            NavigationChannel, NavigationChannel.id == NavigationChannelBoundary.channel_id
        )
        if channel_id:
            stmt = stmt.where(NavigationChannelBoundary.channel_id == channel_id)
        rows = list(
            (
                await self.session.execute(
                    stmt.order_by(
                        NavigationChannelBoundary.is_current.desc(),
                        NavigationChannelBoundary.id.desc(),
                    ).limit(self._limit(limit, default=50, max_value=200))
                )
            ).all()
        )
        return [
            NavigationBoundaryListItemResponse(
                id=boundary.id,
                channel_id=boundary.channel_id,
                channel_code=channel.channel_code,
                channel_name=channel.channel_name,
                boundary_quality_code=boundary.boundary_quality_code,
                geometry_status_code=boundary.geometry_status_code,
                connectivity_status_code=boundary.connectivity_status_code,
                repair_status_code=boundary.repair_status_code,
                coverage_policy_code=boundary.coverage_policy_code,
                is_current=boundary.is_current,
                geometry_json=boundary.geometry_json,
            )
            for boundary, channel in rows
        ]

    async def list_graph_versions(self, *, limit: int = 30) -> list[NavigationGraphVersionListItemResponse]:
        rows = list(
            (
                await self.session.execute(
                    select(NavigationGraphVersion)
                    .order_by(NavigationGraphVersion.is_active.desc(), NavigationGraphVersion.id.desc())
                    .limit(self._limit(limit, default=30, max_value=100))
                )
            ).scalars()
        )
        return [self._graph_version_response(row) for row in rows]

    async def list_geometry_drafts(
        self,
        *,
        status_code: str | None = None,
        channel_id: int | None = None,
        limit: int = 50,
    ) -> list[NavigationGeometryDraftResponse]:
        stmt = select(NavigationGeometryDraft, NavigationChannel).outerjoin(
            NavigationChannel, NavigationChannel.id == NavigationGeometryDraft.channel_id
        )
        if status_code:
            stmt = stmt.where(NavigationGeometryDraft.status_code == status_code.upper())
        if channel_id:
            stmt = stmt.where(NavigationGeometryDraft.channel_id == channel_id)
        rows = list(
            (
                await self.session.execute(
                    stmt.order_by(NavigationGeometryDraft.id.desc()).limit(self._limit(limit, default=50, max_value=200))
                )
            ).all()
        )
        return [self._draft_response(draft, channel) for draft, channel in rows]

    async def create_geometry_draft(
        self,
        body: NavigationGeometryDraftCreateRequest,
        *,
        created_by: int | None,
    ) -> NavigationGeometryDraftResponse:
        draft_type = body.draft_type_code.upper()
        geometry = self._normalized_geometry(body.geometry_json)
        geometry_type = self._validate_geometry_for_draft(draft_type, geometry, body.channel_id)
        bbox = self._geometry_bbox(geometry)
        if body.channel_id is not None:
            await self._ensure_channel(body.channel_id)
        draft = NavigationGeometryDraft(
            draft_no=self._draft_no(),
            draft_name=body.draft_name,
            draft_type_code=draft_type,
            geometry_type_code=geometry_type,
            channel_id=body.channel_id,
            target_type_code=body.target_type_code.upper() if body.target_type_code else None,
            target_id=body.target_id,
            geometry_json=geometry,
            source_type_code=body.source_type_code.upper(),
            status_code="DRAFT",
            quality_code="NEED_REVIEW",
            source_trace_json=body.source_trace_json,
            created_by=created_by,
            **bbox,
        )
        self.session.add(draft)
        await self.session.commit()
        return await self._draft_response_by_id(draft.id)

    async def update_geometry_draft(
        self,
        draft_id: int,
        body: NavigationGeometryDraftUpdateRequest,
    ) -> NavigationGeometryDraftResponse:
        draft = await self._draft(draft_id)
        if draft.status_code in FINAL_DRAFT_STATUSES:
            raise ConflictError("已发布或已驳回的草稿不能继续编辑")
        if body.channel_id is not None:
            await self._ensure_channel(body.channel_id)
            draft.channel_id = body.channel_id
        if body.draft_name is not None:
            draft.draft_name = body.draft_name
        if body.target_type_code is not None:
            draft.target_type_code = body.target_type_code.upper()
        if body.target_id is not None:
            draft.target_id = body.target_id
        if body.source_type_code is not None:
            draft.source_type_code = body.source_type_code.upper()
        if body.source_trace_json is not None:
            draft.source_trace_json = body.source_trace_json
        if body.review_comment is not None:
            draft.review_comment = body.review_comment
        if body.geometry_json is not None:
            geometry = self._normalized_geometry(body.geometry_json)
            draft.geometry_type_code = self._validate_geometry_for_draft(draft.draft_type_code, geometry, draft.channel_id)
            draft.geometry_json = geometry
            for key, value in self._geometry_bbox(geometry).items():
                setattr(draft, key, value)
        await self.session.commit()
        return await self._draft_response_by_id(draft.id)

    async def submit_geometry_draft(
        self,
        draft_id: int,
        *,
        submitted_by: int | None,
    ) -> NavigationGeometryDraftResponse:
        draft = await self._draft(draft_id)
        if draft.status_code != "DRAFT":
            raise ConflictError("只有 DRAFT 草稿可以提交")
        draft.status_code = "SUBMITTED"
        draft.submitted_by = submitted_by
        draft.submitted_at = self._now()
        await self.session.commit()
        return await self._draft_response_by_id(draft.id)

    async def approve_geometry_draft(
        self,
        draft_id: int,
        body: NavigationGeometryDraftApproveRequest,
        *,
        reviewed_by: int | None,
    ) -> NavigationGeometryDraftResponse:
        draft = await self._draft(draft_id)
        if draft.status_code not in {"SUBMITTED", "DRAFT"}:
            raise ConflictError("只有 DRAFT 或 SUBMITTED 草稿可以审核通过")
        draft.status_code = "APPROVED"
        draft.quality_code = "READY"
        draft.review_comment = body.review_comment
        draft.reviewed_by = reviewed_by
        draft.reviewed_at = self._now()
        await self.session.commit()
        return await self._draft_response_by_id(draft.id)

    async def publish_geometry_draft(
        self,
        draft_id: int,
        *,
        published_by: int | None,
    ) -> NavigationGeometryDraftResponse:
        draft = await self._draft(draft_id)
        if draft.status_code != "APPROVED":
            raise ConflictError("只有 APPROVED 草稿可以发布")
        if draft.draft_type_code == "CENTERLINE":
            target_id = await self._publish_centerline(draft, published_by=published_by)
            draft.publish_target_type_code = "CENTERLINE"
        elif draft.draft_type_code == "BOUNDARY":
            target_id = await self._publish_boundary(draft, published_by=published_by)
            draft.publish_target_type_code = "BOUNDARY"
        elif draft.draft_type_code == "WATER_AREA":
            target_id = await self._publish_water_area(draft)
            draft.publish_target_type_code = "WATER_AREA"
        else:
            raise ValidationError(f"Unsupported draft_type_code: {draft.draft_type_code}")
        draft.publish_target_id = target_id
        draft.status_code = "PUBLISHED"
        draft.published_by = published_by
        draft.published_at = self._now()
        await self.session.commit()
        return await self._draft_response_by_id(draft.id)

    async def build_graph_version(
        self,
        body: NavigationGraphBuildRequest,
        *,
        created_by: int | None,
    ) -> NavigationGraphBuildResponse:
        scope_code = (body.scope_code or DEFAULT_REAL_GRAPH_SCOPE).upper()
        version_code = body.version_code or f"{scope_code}-GRAPH-{self._now().strftime('%Y%m%d%H%M%S')}"
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
        )

    async def activate_graph_version(self, graph_version_id: int) -> NavigationGraphActivateResponse:
        graph_version = await self.session.get(NavigationGraphVersion, graph_version_id)
        if graph_version is None:
            raise NotFoundError("NavigationGraphVersion", graph_version_id)
        if graph_version.status_code != "READY":
            raise ConflictError("只有 READY graph version 可以激活")
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
        return NavigationGraphActivateResponse(
            graph_version_id=graph_version.id,
            version_code=graph_version.version_code,
            scope_code=graph_version.scope_code,
            status_code=graph_version.status_code,
            is_active=True,
        )

    async def _publish_centerline(self, draft: NavigationGeometryDraft, *, published_by: int | None) -> int:
        if draft.channel_id is None:
            raise ValidationError("发布中心线草稿必须选择航道")
        await self._ensure_channel(draft.channel_id)
        rows = list(
            (
                await self.session.execute(
                    select(NavigationChannelCenterline).where(
                        NavigationChannelCenterline.channel_id == draft.channel_id,
                        NavigationChannelCenterline.is_current.is_(True),
                        NavigationChannelCenterline.is_main_line.is_(True),
                    )
                )
            ).scalars()
        )
        for row in rows:
            row.is_current = False
        centerline = NavigationChannelCenterline(
            channel_id=draft.channel_id,
            centerline_code=f"MANUAL-CL-{draft.id}-{self._now().strftime('%Y%m%d%H%M%S')}",
            centerline_name=draft.draft_name,
            geometry_json=draft.geometry_json,
            source_type_code="MANUAL",
            direction_code="BIDIRECTIONAL",
            is_main_line=True,
            confidence_score=90,
            quality_code="READY",
            review_status_code="APPROVED",
            version_no=1,
            is_current=True,
            source_trace_json={"navigation_geometry_draft_id": draft.id, **(draft.source_trace_json or {})},
            approved_by=published_by,
            approved_at=self._now(),
            bbox_min_lng=draft.bbox_min_lng,
            bbox_min_lat=draft.bbox_min_lat,
            bbox_max_lng=draft.bbox_max_lng,
            bbox_max_lat=draft.bbox_max_lat,
        )
        self.session.add(centerline)
        await self.session.flush()
        return int(centerline.id)

    async def _publish_boundary(self, draft: NavigationGeometryDraft, *, published_by: int | None) -> int:
        if draft.channel_id is None:
            raise ValidationError("发布航道边界草稿必须选择航道")
        await self._ensure_channel(draft.channel_id)
        rows = list(
            (
                await self.session.execute(
                    select(NavigationChannelBoundary).where(
                        NavigationChannelBoundary.channel_id == draft.channel_id,
                        NavigationChannelBoundary.is_current.is_(True),
                    )
                )
            ).scalars()
        )
        for row in rows:
            row.is_current = False
        bbox = self._bbox_from_model(draft)
        boundary = NavigationChannelBoundary(
            channel_id=draft.channel_id,
            geometry_json=draft.geometry_json,
            boundary_paths_low=self._polygon_paths(draft.geometry_json),
            boundary_paths_medium=self._polygon_paths(draft.geometry_json),
            boundary_paths_high=self._polygon_paths(draft.geometry_json),
            center_longitude=self._center_lng(bbox),
            center_latitude=self._center_lat(bbox),
            display_center_longitude=self._center_lng(bbox),
            display_center_latitude=self._center_lat(bbox),
            bbox_min_lng=draft.bbox_min_lng,
            bbox_min_lat=draft.bbox_min_lat,
            bbox_max_lng=draft.bbox_max_lng,
            bbox_max_lat=draft.bbox_max_lat,
            ring_count=self._ring_count(draft.geometry_json),
            point_count=self._point_count(draft.geometry_json),
            geometry_status_code="AVAILABLE",
            boundary_quality_code="MANUAL_APPROVED",
            connectivity_status_code="NEED_REVIEW",
            repair_status_code="NONE",
            coverage_policy_code="MANUAL_DRAW",
            geometry_coordinate_system_code="WGS84",
            boundary_coordinate_system_code="WGS84",
            is_current=True,
            imported_at=self._now(),
        )
        self.session.add(boundary)
        await self.session.flush()
        return int(boundary.id)

    async def _publish_water_area(self, draft: NavigationGeometryDraft) -> int:
        water_area = NavigationWaterArea(
            source_code="MANUAL_DRAFT",
            source_layer_name="navigation_geometry_draft",
            source_object_id=draft.draft_no,
            water_name=draft.draft_name,
            normalized_water_name=draft.draft_name,
            water_type_code="UNKNOWN",
            geometry_json=draft.geometry_json,
            geometry_status_code="VALID",
            bbox_min_lng=draft.bbox_min_lng,
            bbox_min_lat=draft.bbox_min_lat,
            bbox_max_lng=draft.bbox_max_lng,
            bbox_max_lat=draft.bbox_max_lat,
            center_lng=self._center_lng(self._bbox_from_model(draft)),
            center_lat=self._center_lat(self._bbox_from_model(draft)),
            is_low_value=False,
            is_enabled=True,
        )
        self.session.add(water_area)
        await self.session.flush()
        return int(water_area.id)

    async def _counts_by_channel(self, _column, stmt) -> dict[int, int]:
        rows = (await self.session.execute(stmt.group_by(_column))).all()
        return {int(channel_id): int(count or 0) for channel_id, count in rows if channel_id is not None}

    async def _active_graph_version(self) -> NavigationGraphVersion | None:
        return (
            await self.session.execute(
                select(NavigationGraphVersion)
                .where(NavigationGraphVersion.is_active.is_(True))
                .order_by(NavigationGraphVersion.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _ensure_channel(self, channel_id: int) -> NavigationChannel:
        channel = await self.session.get(NavigationChannel, channel_id)
        if channel is None:
            raise NotFoundError("NavigationChannel", channel_id)
        return channel

    async def _draft(self, draft_id: int) -> NavigationGeometryDraft:
        draft = await self.session.get(NavigationGeometryDraft, draft_id)
        if draft is None:
            raise NotFoundError("NavigationGeometryDraft", draft_id)
        return draft

    async def _draft_response_by_id(self, draft_id: int) -> NavigationGeometryDraftResponse:
        row = (
            await self.session.execute(
                select(NavigationGeometryDraft, NavigationChannel)
                .outerjoin(NavigationChannel, NavigationChannel.id == NavigationGeometryDraft.channel_id)
                .where(NavigationGeometryDraft.id == draft_id)
            )
        ).one()
        return self._draft_response(row[0], row[1])

    def _draft_response(
        self,
        draft: NavigationGeometryDraft,
        channel: NavigationChannel | None,
    ) -> NavigationGeometryDraftResponse:
        return NavigationGeometryDraftResponse(
            id=draft.id,
            draft_no=draft.draft_no,
            draft_name=draft.draft_name,
            draft_type_code=draft.draft_type_code,
            geometry_type_code=draft.geometry_type_code,
            channel_id=draft.channel_id,
            channel_code=channel.channel_code if channel else None,
            channel_name=channel.channel_name if channel else None,
            target_type_code=draft.target_type_code,
            target_id=draft.target_id,
            geometry_json=draft.geometry_json,
            source_type_code=draft.source_type_code,
            status_code=draft.status_code,
            quality_code=draft.quality_code,
            review_comment=draft.review_comment,
            publish_target_type_code=draft.publish_target_type_code,
            publish_target_id=draft.publish_target_id,
            bbox=self._bbox_dict(draft),
        )

    def _graph_version_response(self, row: NavigationGraphVersion) -> NavigationGraphVersionListItemResponse:
        return NavigationGraphVersionListItemResponse(
            id=row.id,
            version_code=row.version_code,
            version_name=row.version_name,
            scope_code=row.scope_code,
            status_code=row.status_code,
            is_active=row.is_active,
            node_count=row.node_count,
            edge_count=row.edge_count,
            channel_count=row.channel_count,
            quality_score=row.quality_score,
            built_at=row.built_at.isoformat() if row.built_at else None,
            validation_report_json=row.validation_report_json,
        )

    def _graph_version_dict(self, row: NavigationGraphVersion | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return self._graph_version_response(row).model_dump()

    def _normalized_geometry(self, geometry: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(geometry, dict):
            raise ValidationError("geometry_json 必须是 GeoJSON 对象")
        geometry_type = str(geometry.get("type") or "").strip()
        if geometry_type == "Feature":
            inner = geometry.get("geometry")
            if not isinstance(inner, dict):
                raise ValidationError("Feature.geometry 必须是 GeoJSON 几何对象")
            return inner
        if geometry_type not in {"LineString", "Polygon", "MultiPolygon"}:
            raise ValidationError("当前草稿只支持 LineString、Polygon、MultiPolygon")
        return geometry

    def _validate_geometry_for_draft(
        self,
        draft_type: str,
        geometry: dict[str, Any],
        channel_id: int | None,
    ) -> str:
        draft_type = draft_type.upper()
        allowed = DRAFT_GEOMETRY_TYPES.get(draft_type)
        if not allowed:
            raise ValidationError(f"Unsupported draft_type_code: {draft_type}")
        geometry_type = str(geometry.get("type") or "").upper()
        if geometry_type not in allowed:
            raise ValidationError(f"{draft_type} 草稿不支持 {geometry_type} 几何")
        if draft_type in {"CENTERLINE", "BOUNDARY"} and channel_id is None:
            raise ValidationError(f"{draft_type} 草稿必须选择 channel_id")
        coords = self._coordinate_pairs(geometry.get("coordinates"))
        if geometry_type == "LINESTRING" and len(coords) < 2:
            raise ValidationError("LineString 至少需要两个坐标点")
        if geometry_type in {"POLYGON", "MULTIPOLYGON"} and len(coords) < 4:
            raise ValidationError("Polygon/MultiPolygon 至少需要一个闭合面")
        return geometry_type

    def _geometry_bbox(self, geometry: dict[str, Any]) -> dict[str, float | None]:
        coords = self._coordinate_pairs(geometry.get("coordinates"))
        if not coords:
            return {"bbox_min_lng": None, "bbox_min_lat": None, "bbox_max_lng": None, "bbox_max_lat": None}
        lngs = [point[0] for point in coords]
        lats = [point[1] for point in coords]
        return {
            "bbox_min_lng": min(lngs),
            "bbox_min_lat": min(lats),
            "bbox_max_lng": max(lngs),
            "bbox_max_lat": max(lats),
        }

    def _coordinate_pairs(self, value: Any) -> list[tuple[float, float]]:
        pairs: list[tuple[float, float]] = []

        def walk(item: Any) -> None:
            if not isinstance(item, list):
                return
            if len(item) >= 2 and all(isinstance(item[index], (int, float)) for index in (0, 1)):
                lng = float(item[0])
                lat = float(item[1])
                if -180 <= lng <= 180 and -90 <= lat <= 90:
                    pairs.append((lng, lat))
                return
            for child in item:
                walk(child)

        walk(value)
        return pairs

    def _polygon_paths(self, geometry: dict[str, Any]) -> list:
        geometry_type = geometry.get("type")
        coordinates = geometry.get("coordinates")
        if geometry_type == "Polygon" and isinstance(coordinates, list):
            return coordinates
        if geometry_type == "MultiPolygon" and isinstance(coordinates, list):
            return [ring for polygon in coordinates if isinstance(polygon, list) for ring in polygon if isinstance(ring, list)]
        return []

    def _ring_count(self, geometry: dict[str, Any]) -> int:
        return len(self._polygon_paths(geometry))

    def _point_count(self, geometry: dict[str, Any]) -> int:
        return len(self._coordinate_pairs(geometry.get("coordinates")))

    def _bbox_dict(self, row: Any) -> dict[str, float | None]:
        return {
            "min_lng": self._float(getattr(row, "bbox_min_lng", None)),
            "min_lat": self._float(getattr(row, "bbox_min_lat", None)),
            "max_lng": self._float(getattr(row, "bbox_max_lng", None)),
            "max_lat": self._float(getattr(row, "bbox_max_lat", None)),
        }

    def _bbox_from_model(self, row: Any) -> dict[str, float | None]:
        return self._bbox_dict(row)

    def _center_lng(self, bbox: dict[str, float | None]) -> float | None:
        if bbox["min_lng"] is None or bbox["max_lng"] is None:
            return None
        return (bbox["min_lng"] + bbox["max_lng"]) / 2

    def _center_lat(self, bbox: dict[str, float | None]) -> float | None:
        if bbox["min_lat"] is None or bbox["max_lat"] is None:
            return None
        return (bbox["min_lat"] + bbox["max_lat"]) / 2

    def _float(self, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return float(value)
        return float(value)

    def _limit(self, value: int, *, default: int, max_value: int) -> int:
        return max(1, min(int(value or default), max_value))

    def _draft_no(self) -> str:
        return f"NGD-{self._now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8].upper()}"

    def _now(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)
