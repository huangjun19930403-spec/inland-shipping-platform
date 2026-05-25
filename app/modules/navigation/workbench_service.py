from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pyproj import Geod
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from shapely.geometry import LineString, MultiPolygon, Polygon, shape

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import (
    NavigationAnnotationTask,
    NavigationChannelCenterline,
    NavigationChannelWaterBodyMatch,
    NavigationGeometryDraft,
    NavigationGraphEdge,
    NavigationGraphVersion,
    NavigationWaterArea,
    NavigationWaterBody,
    NavigationWaterBodyFeatureLink,
)
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.modules.navigation.schemas import (
    NavigationBoundaryListItemResponse,
    NavigationCenterlineListItemResponse,
    NavigationChannelWaterBodyMatchItemResponse,
    NavigationChannelWaterBodyMatchListResponse,
    NavigationGeometryDraftCreateRequest,
    NavigationGeometryDraftResponse,
    NavigationGeometryDraftUpdateRequest,
    NavigationGraphActivateResponse,
    NavigationGraphBuildRequest,
    NavigationGraphBuildResponse,
    NavigationGraphVersionListItemResponse,
    NavigationMapLayerResponse,
    NavigationWaterBodyListItemResponse,
    NavigationWaterBodyListResponse,
    NavigationWaterBodyMatchCreateRequest,
    NavigationWaterBodyNameUpdateRequest,
    NavigationWaterAreaListResponse,
    NavigationWaterAreaListItemResponse,
    NavigationWaterAreaLayerSummaryResponse,
    NavigationWaterAreaSummaryResponse,
    NavigationWorkbenchChannelResponse,
    NavigationWorkbenchSummaryResponse,
)
from app.modules.navigation.water_area_layers import water_area_layer_meta
from scripts.navigation.build_graph_from_centerline import build_graph_from_centerlines


DRAFT_GEOMETRY_TYPES = {
    "CENTERLINE": {"LINESTRING"},
    "BOUNDARY": {"POLYGON", "MULTIPOLYGON"},
    "WATER_AREA": {"POLYGON", "MULTIPOLYGON"},
}
FINAL_DRAFT_STATUSES = {"PUBLISHED", "REJECTED"}
ARCHIVED_DRAFT_STATUSES = {"ARCHIVED", "DELETED"}
REAL_WATER_SOURCE_CODE = "RIVER_SHAPEFILE_2026"
DEFAULT_REAL_GRAPH_SCOPE = "REAL-JS-YRD"
GEOD = Geod(ellps="WGS84")
MIN_CENTERLINE_LENGTH_M = 20.0
MIN_BOUNDARY_AREA_M2 = 100.0
PUBLISH_BOUNDARY_TOLERANCE_DEGREE = 0.0002


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
        published_centerline_counts = await self._counts_by_channel(
            NavigationChannelCenterline.channel_id,
            select(NavigationChannelCenterline.channel_id, func.count()).where(
                NavigationChannelCenterline.channel_id.in_(channel_ids),
                NavigationChannelCenterline.is_current.is_(True),
                NavigationChannelCenterline.review_status_code == "PUBLISHED",
                NavigationChannelCenterline.quality_code.in_({"READY", "READY_WITH_WARNING"}),
            ),
        )
        current_match_counts = await self._counts_by_channel(
            NavigationChannelWaterBodyMatch.channel_id,
            select(NavigationChannelWaterBodyMatch.channel_id, func.count()).where(
                NavigationChannelWaterBodyMatch.channel_id.in_(channel_ids),
                NavigationChannelWaterBodyMatch.is_current.is_(True),
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
                published_current_centerline_count=published_centerline_counts.get(channel.id, 0),
                active_graph_edge_count=active_edge_counts.get(channel.id, 0),
                current_water_body_match_count=current_match_counts.get(channel.id, 0),
                boundary_status_code="READY" if current_boundary_counts.get(channel.id, 0) else "MISSING",
                centerline_status_code="READY" if published_centerline_counts.get(channel.id, 0) else "MISSING",
                graph_status_code="READY" if active_edge_counts.get(channel.id, 0) else "MISSING",
                water_body_match_status_code="READY" if current_match_counts.get(channel.id, 0) else "MISSING",
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
            "water_body_matched_channel_count": sum(1 for row in channel_rows if row.current_water_body_match_count > 0),
            "published_centerline_channel_count": sum(1 for row in channel_rows if row.published_current_centerline_count > 0),
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
                "生产体验默认使用真实 revier 水系资产和清洗预置数据；MVP/示例数据不得作为当前可用图网络。",
                "READY 只代表业务路径图和几何结果可用，不代表官方安全通航确认。",
                "无已发布 current centerline 的航道不会进入 graph，polygon/boundary 不能替代路径搜索。",
            ],
        )

    async def list_water_areas(
        self,
        *,
        keyword: str | None = None,
        channel_id: int | None = None,
        source_layer_name: str | None = None,
        source_layer_code: str | None = None,
        layer_role_code: str | None = None,
        water_type_code: str | None = None,
        geometry_status_code: str | None = None,
        only_unmatched: bool = False,
        include_invalid: bool = False,
        sort: str = "layer_order",
        page: int = 1,
        page_size: int = 50,
    ) -> NavigationWaterAreaListResponse:
        page = max(1, int(page or 1))
        page_size = self._limit(page_size, default=50, max_value=200)
        stmt = select(NavigationWaterArea)
        if not include_invalid:
            stmt = stmt.where(NavigationWaterArea.is_enabled.is_(True))
        if channel_id:
            matched_area_scores = (
                select(
                    NavigationWaterBodyFeatureLink.water_area_id.label("water_area_id"),
                    func.max(NavigationChannelWaterBodyMatch.score).label("match_score"),
                )
                .join(
                    NavigationChannelWaterBodyMatch,
                    NavigationChannelWaterBodyMatch.water_body_id == NavigationWaterBodyFeatureLink.water_body_id,
                )
                .where(
                    NavigationChannelWaterBodyMatch.channel_id == channel_id,
                    NavigationChannelWaterBodyMatch.is_current.is_(True),
                )
                .group_by(NavigationWaterBodyFeatureLink.water_area_id)
                .subquery()
            )
            stmt = (
                stmt.join(matched_area_scores, matched_area_scores.c.water_area_id == NavigationWaterArea.id)
                .add_columns(matched_area_scores.c.match_score)
            )
        if only_unmatched:
            matched_area_ids = (
                select(NavigationWaterBodyFeatureLink.water_area_id)
                .join(
                    NavigationChannelWaterBodyMatch,
                    NavigationChannelWaterBodyMatch.water_body_id == NavigationWaterBodyFeatureLink.water_body_id,
                )
                .where(NavigationChannelWaterBodyMatch.is_current.is_(True))
            )
            stmt = stmt.where(NavigationWaterArea.id.not_in(matched_area_ids))
        if source_layer_name:
            stmt = stmt.where(NavigationWaterArea.source_layer_name == source_layer_name)
        if source_layer_code:
            stmt = stmt.where(NavigationWaterArea.source_layer_code == source_layer_code.upper())
        if layer_role_code:
            stmt = stmt.where(NavigationWaterArea.source_layer_role_code == layer_role_code.upper())
        if water_type_code:
            stmt = stmt.where(NavigationWaterArea.water_type_code == water_type_code.upper())
        if geometry_status_code:
            stmt = stmt.where(NavigationWaterArea.geometry_status_code == geometry_status_code.upper())
        if keyword:
            like = f"%{keyword.strip()}%"
            stmt = stmt.where(
                (NavigationWaterArea.water_name.like(like)) | (NavigationWaterArea.normalized_water_name.like(like))
            )
        if channel_id:
            stmt = stmt.order_by(matched_area_scores.c.match_score.desc(), func.coalesce(NavigationWaterArea.source_layer_order, 999), NavigationWaterArea.id)
        elif keyword and sort == "layer_order":
            text = keyword.strip()
            exact_rank = case(
                ((NavigationWaterArea.water_name == text) | (NavigationWaterArea.normalized_water_name == text), 0),
                else_=1,
            )
            stmt = stmt.order_by(
                exact_rank,
                func.coalesce(NavigationWaterArea.source_layer_order, 999),
                NavigationWaterArea.area_km2.desc(),
                NavigationWaterArea.id,
            )
        elif sort == "area_desc":
            stmt = stmt.order_by(NavigationWaterArea.area_km2.desc(), NavigationWaterArea.id)
        else:
            stmt = stmt.order_by(func.coalesce(NavigationWaterArea.source_layer_order, 999), NavigationWaterArea.id)
        total = int((await self.session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one() or 0)
        result = await self.session.execute(stmt.offset((page - 1) * page_size).limit(page_size))
        rows = [row[0] for row in result.all()] if channel_id else list(result.scalars())
        matched_channels_by_area = await self._matched_channels_by_water_area([row.id for row in rows])
        return NavigationWaterAreaListResponse(
            items=[self._water_area_response(row, matched_channels_by_area.get(row.id, [])) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def list_water_bodies(
        self,
        *,
        keyword: str | None = None,
        channel_id: int | None = None,
        body_role_code: str | None = None,
        dedupe_status_code: str | None = None,
        source_layer_code: str | None = None,
        layer_role_code: str | None = None,
        water_type_code: str | None = None,
        geometry_status_code: str | None = None,
        name_status_code: str | None = None,
        only_matched: bool = False,
        only_unmatched: bool = False,
        include_invalid: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> NavigationWaterBodyListResponse:
        page = max(1, int(page or 1))
        page_size = self._limit(page_size, default=50, max_value=100)
        stmt = self._water_body_asset_stmt(
            keyword=keyword,
            channel_id=channel_id,
            body_role_code=body_role_code,
            dedupe_status_code=dedupe_status_code,
            source_layer_code=source_layer_code,
            layer_role_code=layer_role_code,
            water_type_code=water_type_code,
            geometry_status_code=geometry_status_code,
            name_status_code=name_status_code,
            only_matched=only_matched,
            only_unmatched=only_unmatched,
            include_invalid=include_invalid,
        )
        total = int((await self.session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one() or 0)
        if total == 0:
            body_table_count = int(await self.session.scalar(select(func.count()).select_from(NavigationWaterBody)) or 0)
            if body_table_count == 0:
                return await self._list_water_bodies_from_raw(
                    keyword=keyword,
                    channel_id=channel_id,
                    source_layer_code=source_layer_code,
                    layer_role_code=layer_role_code,
                    water_type_code=water_type_code,
                    geometry_status_code=geometry_status_code,
                    name_status_code=name_status_code,
                    only_matched=only_matched,
                    only_unmatched=only_unmatched,
                    include_invalid=include_invalid,
                    page=page,
                    page_size=page_size,
                )
        rows = list((await self.session.execute(stmt.offset((page - 1) * page_size).limit(page_size))).scalars())
        items: list[NavigationWaterBodyListItemResponse] = []
        for body in rows:
            items.append(await self._water_body_asset_response(body))
        return NavigationWaterBodyListResponse(items=items, total=total, page=page, page_size=page_size)

    async def _list_water_bodies_from_raw(
        self,
        *,
        keyword: str | None,
        channel_id: int | None,
        source_layer_code: str | None,
        layer_role_code: str | None,
        water_type_code: str | None,
        geometry_status_code: str | None,
        name_status_code: str | None,
        only_matched: bool,
        only_unmatched: bool,
        include_invalid: bool,
        page: int,
        page_size: int,
    ) -> NavigationWaterBodyListResponse:
        stmt = self._water_body_base_stmt(
            keyword=keyword,
            channel_id=channel_id,
            source_layer_code=source_layer_code,
            layer_role_code=layer_role_code,
            water_type_code=water_type_code,
            geometry_status_code=geometry_status_code,
            name_status_code=name_status_code,
            only_matched=only_matched,
            only_unmatched=only_unmatched,
            include_invalid=include_invalid,
        )
        total = int((await self.session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one() or 0)
        rows = list((await self.session.execute(stmt.offset((page - 1) * page_size).limit(page_size))).all())
        items: list[NavigationWaterBodyListItemResponse] = []
        for row in rows:
            source_code = str(row.source_code)
            source_layer_code_value = str(row.source_layer_code) if row.source_layer_code else None
            normalized_name = str(row.normalized_water_name)
            water_type = str(row.water_type_code)
            water_area_ids = await self._water_body_ids(
                source_code=source_code,
                source_layer_code=source_layer_code_value,
                normalized_water_name=normalized_name,
                water_type_code=water_type,
                include_invalid=include_invalid,
                limit=500,
            )
            matched_channels = await self._matched_channels_for_water_ids(water_area_ids)
            group_key = self._encode_water_body_key(
                {
                    "source_code": source_code,
                    "source_layer_code": source_layer_code_value,
                    "normalized_water_name": normalized_name,
                    "water_type_code": water_type,
                }
            )
            items.append(
                NavigationWaterBodyListItemResponse(
                    group_key=group_key,
                    source_code=source_code,
                    source_layer_code=source_layer_code_value,
                    source_layer_name=str(row.source_layer_name) if row.source_layer_name else None,
                    source_layer_display_name=str(row.source_layer_display_name) if row.source_layer_display_name else None,
                    source_layer_role_code=str(row.source_layer_role_code) if row.source_layer_role_code else None,
                    source_layer_order=int(row.source_layer_order) if row.source_layer_order is not None else None,
                    water_name=str(row.water_name) if row.water_name else normalized_name,
                    normalized_water_name=normalized_name,
                    display_name=str(row.water_name) if row.water_name else normalized_name,
                    production_name=str(row.water_name) if row.water_name else normalized_name,
                    name_status_code="RAW_NAMED",
                    name_source_code="REVIER_RAW",
                    name_note=None,
                    water_type_code=water_type,
                    feature_count=int(row.feature_count or 0),
                    enabled_count=int(row.enabled_count or 0),
                    repaired_count=int(row.repaired_count or 0),
                    invalid_count=int(row.invalid_count or 0),
                    total_area_km2=self._float(row.total_area_km2),
                    quality_code="REPAIRED" if int(row.repaired_count or 0) else "READY",
                    bbox={
                        "min_lng": self._float(row.bbox_min_lng),
                        "min_lat": self._float(row.bbox_min_lat),
                        "max_lng": self._float(row.bbox_max_lng),
                        "max_lat": self._float(row.bbox_max_lat),
                    },
                    display_bbox={},
                    match_count=len(matched_channels),
                    is_matched=bool(matched_channels),
                    matched_channels=matched_channels,
                    representative_water_area_ids=water_area_ids,
                )
            )
        return NavigationWaterBodyListResponse(items=items, total=total, page=page, page_size=page_size)

    async def list_water_body_features(
        self,
        *,
        group_key: str,
        page: int = 1,
        page_size: int = 100,
    ) -> NavigationWaterAreaListResponse:
        payload = self._decode_water_body_key(group_key)
        page = max(1, int(page or 1))
        page_size = self._limit(page_size, default=100, max_value=500)
        stmt = self._water_body_feature_stmt(payload)
        total = int((await self.session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one() or 0)
        rows = list((await self.session.execute(stmt.offset((page - 1) * page_size).limit(page_size))).scalars())
        matched_channels_by_area = await self._matched_channels_by_water_area([row.id for row in rows])
        return NavigationWaterAreaListResponse(
            items=[self._water_area_response(row, matched_channels_by_area.get(row.id, [])) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def water_body_map_layers(self, *, group_key: str, limit: int = 500) -> NavigationMapLayerResponse:
        from app.modules.navigation.map_layer_service import NavigationMapLayerService

        payload = self._decode_water_body_key(group_key)
        rows = list((await self.session.execute(self._water_body_feature_stmt(payload).limit(500))).scalars())
        water_area_ids = [row.id for row in rows]
        return await NavigationMapLayerService(self.session, default_limit=limit, max_limit=max(limit, 500)).get_layers(
            min_lng=None,
            min_lat=None,
            max_lng=None,
            max_lat=None,
            channel_id=None,
            route_result_id=None,
            include_water_area=True,
            include_boundary=False,
            include_centerline=False,
            include_graph_edge=False,
            limit=limit,
            water_area_ids=water_area_ids,
        )

    async def water_area_summary(self) -> NavigationWaterAreaSummaryResponse:
        raw_total_count = int(
            await self.session.scalar(
                select(func.count()).select_from(NavigationWaterArea).where(NavigationWaterArea.source_code == REAL_WATER_SOURCE_CODE)
            )
            or 0
        )
        enabled_count = int(
            await self.session.scalar(
                select(func.count()).select_from(NavigationWaterArea).where(
                    NavigationWaterArea.source_code == REAL_WATER_SOURCE_CODE,
                    NavigationWaterArea.is_enabled.is_(True),
                )
            )
            or 0
        )
        invalid_count = max(raw_total_count - enabled_count, 0)
        real_count = int(
            await self.session.scalar(
                select(func.count()).select_from(NavigationWaterArea).where(
                    NavigationWaterArea.source_code == REAL_WATER_SOURCE_CODE,
                    NavigationWaterArea.is_enabled.is_(True),
                )
            )
            or 0
        )
        named_count = int(
            await self.session.scalar(
                select(func.count()).select_from(NavigationWaterArea).where(
                    NavigationWaterArea.source_code == REAL_WATER_SOURCE_CODE,
                    NavigationWaterArea.is_enabled.is_(True),
                    NavigationWaterArea.water_name.is_not(None),
                )
            )
            or 0
        )
        matched_count = int(
            await self.session.scalar(
                select(func.count(func.distinct(NavigationChannelWaterBodyMatch.water_body_id))).where(
                    NavigationChannelWaterBodyMatch.is_current.is_(True)
                )
            )
            or 0
        )
        layer_rows = list(
            (
                await self.session.execute(
                    select(
                        NavigationWaterArea.source_layer_name,
                        func.max(NavigationWaterArea.source_layer_code),
                        func.max(NavigationWaterArea.source_layer_display_name),
                        func.max(NavigationWaterArea.source_layer_role_code),
                        func.min(NavigationWaterArea.source_layer_order),
                        func.count(),
                        func.sum(case((NavigationWaterArea.is_enabled.is_(True), 1), else_=0)),
                        func.sum(case((NavigationWaterArea.is_enabled.is_(False), 1), else_=0)),
                        func.sum(case((NavigationWaterArea.water_name.is_not(None), 1), else_=0)),
                    )
                    .where(
                        NavigationWaterArea.source_code == REAL_WATER_SOURCE_CODE,
                    )
                    .group_by(NavigationWaterArea.source_layer_name)
                    .order_by(func.coalesce(func.min(NavigationWaterArea.source_layer_order), 999), NavigationWaterArea.source_layer_name)
                )
            ).all()
        )
        body_count = int(await self.session.scalar(select(func.count()).select_from(NavigationWaterBody)) or 0)
        hierarchy_body_count = int(
            await self.session.scalar(
                select(func.count()).select_from(NavigationWaterBody).where(NavigationWaterBody.body_role_code == "PRIMARY_HIERARCHY")
            )
            or 0
        )
        rx_fill_body_count = int(
            await self.session.scalar(
                select(func.count()).select_from(NavigationWaterBody).where(NavigationWaterBody.body_role_code == "RX_FILL_GAP")
            )
            or 0
        )
        rx_duplicate_link_count = int(
            await self.session.scalar(
                select(func.count()).select_from(NavigationWaterBodyFeatureLink).where(
                    NavigationWaterBodyFeatureLink.link_role_code == "RX_DUPLICATE"
                )
            )
            or 0
        )
        rx8_body_count = int(
            await self.session.scalar(
                select(func.count()).select_from(NavigationWaterBody).where(NavigationWaterBody.body_role_code == "RX8_BACKUP")
            )
            or 0
        )
        invalid_body_count = int(
            await self.session.scalar(
                select(func.count()).select_from(NavigationWaterBody).where(NavigationWaterBody.body_role_code == "INVALID_DIAGNOSTIC")
            )
            or 0
        )
        matched_water_body_count = int(
            await self.session.scalar(
                select(func.count(func.distinct(NavigationChannelWaterBodyMatch.water_body_id))).where(
                    NavigationChannelWaterBodyMatch.is_current.is_(True)
                )
            )
            or 0
        )
        unnamed_water_body_count = int(
            await self.session.scalar(
                select(func.count()).select_from(NavigationWaterBody).where(
                    NavigationWaterBody.name_status_code == "UNNAMED",
                    NavigationWaterBody.is_enabled.is_(True),
                )
            )
            or 0
        )
        return NavigationWaterAreaSummaryResponse(
            total_count=enabled_count,
            raw_total_count=raw_total_count,
            enabled_count=enabled_count,
            invalid_count=invalid_count,
            real_count=real_count,
            named_count=named_count,
            unnamed_count=max(real_count - named_count, 0),
            matched_count=matched_count,
            unmatched_count=max(real_count - matched_count, 0),
            water_body_count=body_count,
            standard_body_count=hierarchy_body_count + rx_fill_body_count,
            hierarchy_body_count=hierarchy_body_count,
            rx_fill_body_count=rx_fill_body_count,
            rx_duplicate_link_count=rx_duplicate_link_count,
            rx8_body_count=rx8_body_count,
            invalid_body_count=invalid_body_count,
            matched_water_body_count=matched_water_body_count,
            unmatched_water_body_count=max(body_count - matched_water_body_count, 0),
            unnamed_water_body_count=unnamed_water_body_count,
            layer_counts=[
                NavigationWaterAreaLayerSummaryResponse(
                    source_layer_name=str(layer_name),
                    source_layer_code=str(source_layer_code) if source_layer_code else water_area_layer_meta(str(layer_name)).source_layer_code,
                    source_layer_display_name=str(display_name) if display_name else water_area_layer_meta(str(layer_name)).source_layer_display_name,
                    source_layer_role_code=str(role_code) if role_code else water_area_layer_meta(str(layer_name)).source_layer_role_code,
                    source_layer_order=int(source_layer_order) if source_layer_order is not None else water_area_layer_meta(str(layer_name)).source_layer_order,
                    count=int(enabled_count_row or 0),
                    raw_count=int(raw_count or 0),
                    enabled_count=int(enabled_count_row or 0),
                    invalid_count=int(invalid_count_row or 0),
                    named_count=int(named_count_row or 0),
                )
                for (
                    layer_name,
                    source_layer_code,
                    display_name,
                    role_code,
                    source_layer_order,
                    raw_count,
                    enabled_count_row,
                    invalid_count_row,
                    named_count_row,
                ) in layer_rows
            ],
        )

    async def list_water_body_matches(
        self,
        *,
        channel_id: int,
        limit: int = 500,
    ) -> NavigationChannelWaterBodyMatchListResponse:
        channel = await self._ensure_channel(channel_id)
        rows = list(
            (
                await self.session.execute(
                    select(NavigationChannelWaterBodyMatch, NavigationWaterBody)
                    .join(NavigationWaterBody, NavigationWaterBody.id == NavigationChannelWaterBodyMatch.water_body_id)
                    .where(
                        NavigationChannelWaterBodyMatch.channel_id == channel_id,
                        NavigationChannelWaterBodyMatch.is_current.is_(True),
                    )
                    .order_by(NavigationChannelWaterBodyMatch.score.desc(), NavigationChannelWaterBodyMatch.id)
                    .limit(self._limit(limit, default=500, max_value=1000))
                )
            ).all()
        )
        items = [
            self._water_body_match_item_response(channel=channel, match=match, water_body=water_body)
            for match, water_body in rows
        ]
        issue_codes = sorted({issue for item in items for issue in item.issue_codes})
        best = items[0] if items else None
        return NavigationChannelWaterBodyMatchListResponse(
            channel_id=channel.id,
            channel_code=channel.channel_code,
            channel_name=channel.channel_name,
            current_match_count=len(items),
            best_score=best.score if best else None,
            confidence_code=best.confidence_code if best else "MISSING",
            issue_codes=issue_codes or (["NO_WATER_BODY_MATCH"] if not items else []),
            match_batch_code=best.match_batch_code if best else None,
            items=items,
        )

    async def create_water_body_match(
        self,
        *,
        channel_id: int,
        body: NavigationWaterBodyMatchCreateRequest,
    ) -> NavigationChannelWaterBodyMatchListResponse:
        channel = await self._ensure_channel(channel_id)
        water_body = await self.session.get(NavigationWaterBody, body.water_body_id)
        if water_body is None or not water_body.is_enabled:
            raise NotFoundError("NavigationWaterBody", body.water_body_id)
        if water_body.body_role_code not in {"PRIMARY_HIERARCHY", "RX_FILL_GAP"}:
            raise ValidationError("Only production water bodies can be assigned to navigation channels")
        existing = (
            await self.session.execute(
                select(NavigationChannelWaterBodyMatch).where(
                    NavigationChannelWaterBodyMatch.channel_id == channel_id,
                    NavigationChannelWaterBodyMatch.water_body_id == body.water_body_id,
                    NavigationChannelWaterBodyMatch.is_current.is_(True),
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            water_area_ids = [
                int(item)
                for item in (water_body.source_water_area_ids_json or [])
                if isinstance(item, int) or str(item).isdigit()
            ]
            match = NavigationChannelWaterBodyMatch(
                channel_id=channel.id,
                water_body_id=water_body.id,
                match_batch_code=body.match_batch_code or f"MANUAL-BODY-MATCH-{self._now().strftime('%Y%m%d%H%M%S')}",
                match_type_code=body.match_type_code.upper(),
                matched_term=body.matched_term or water_body.production_name or water_body.display_name or water_body.water_body_name,
                score=body.score,
                confidence_code=body.confidence_code.upper(),
                issue_codes=body.issue_codes,
                is_current=True,
                source_water_area_ids_json=water_area_ids,
                source_trace_json={
                    "source": "navigation_water_body_manual_assign",
                    "water_body_id": water_body.id,
                    "source_water_area_ids": water_area_ids[:100],
                    "raw_water_area_is_trace_only": True,
                    **(body.source_trace_json or {}),
                },
            )
            self.session.add(match)
            await self.session.commit()
        return await self.list_water_body_matches(channel_id=channel_id)

    async def remove_water_body_match(
        self,
        *,
        channel_id: int,
        match_id: int,
    ) -> NavigationChannelWaterBodyMatchListResponse:
        await self._ensure_channel(channel_id)
        match = await self.session.get(NavigationChannelWaterBodyMatch, match_id)
        if match is None or match.channel_id != channel_id:
            raise NotFoundError("NavigationChannelWaterBodyMatch", match_id)
        match.is_current = False
        trace = match.source_trace_json if isinstance(match.source_trace_json, dict) else {}
        match.source_trace_json = {
            **trace,
            "removed_from_production_at": self._now().isoformat(),
            "removed_source": "navigation_water_body_manual_remove",
        }
        await self.session.commit()
        return await self.list_water_body_matches(channel_id=channel_id)

    async def update_water_body_name(
        self,
        *,
        water_body_id: int,
        body: NavigationWaterBodyNameUpdateRequest,
    ) -> NavigationWaterBodyListItemResponse:
        water_body = await self.session.get(NavigationWaterBody, water_body_id)
        if water_body is None or not water_body.is_enabled:
            raise NotFoundError("NavigationWaterBody", water_body_id)
        production_name = " ".join(body.production_name.strip().split())
        if not production_name:
            raise ValidationError("Production name is required")
        water_body.production_name = production_name
        water_body.display_name = production_name
        water_body.name_status_code = "PRODUCTION_NAMED"
        water_body.name_source_code = "MANUAL_PRODUCTION"
        water_body.name_note = body.name_note
        trace = water_body.source_layer_summary_json if isinstance(water_body.source_layer_summary_json, dict) else {}
        water_body.source_layer_summary_json = {
            **trace,
            "production_name_updated_at": self._now().isoformat(),
            "raw_name_preserved": water_body.water_body_name,
        }
        await self.session.commit()
        await self.session.refresh(water_body)
        return await self._water_body_asset_response(water_body)

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
        else:
            stmt = stmt.where(NavigationGeometryDraft.status_code.not_in(ARCHIVED_DRAFT_STATUSES))
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
        if draft.status_code in FINAL_DRAFT_STATUSES | ARCHIVED_DRAFT_STATUSES:
            raise ConflictError("已发布或已归档的草稿不能继续编辑")
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
        if body.geometry_json is not None:
            geometry = self._normalized_geometry(body.geometry_json)
            draft.geometry_type_code = self._validate_geometry_for_draft(draft.draft_type_code, geometry, draft.channel_id)
            draft.geometry_json = geometry
            for key, value in self._geometry_bbox(geometry).items():
                setattr(draft, key, value)
        if draft.status_code == "PUBLISH_BLOCKED":
            draft.status_code = "DRAFT"
            draft.quality_code = "NEED_REVIEW"
        await self.session.commit()
        return await self._draft_response_by_id(draft.id)

    async def publish_geometry_draft(
        self,
        draft_id: int,
        *,
        published_by: int | None,
    ) -> NavigationGeometryDraftResponse:
        draft = await self._draft(draft_id)
        if draft.status_code not in {"DRAFT", "PUBLISH_BLOCKED"}:
            raise ConflictError("只有 DRAFT 或 PUBLISH_BLOCKED 草稿可以发布")
        try:
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
        except ValidationError as exc:
            draft.status_code = "PUBLISH_BLOCKED"
            draft.quality_code = "PUBLISH_BLOCKED"
            draft.review_comment = exc.message[:512]
            await self.session.commit()
            raise
        draft.publish_target_id = target_id
        draft.status_code = "PUBLISHED"
        draft.quality_code = "READY"
        draft.published_by = published_by
        draft.published_at = self._now()
        await self.session.commit()
        return await self._draft_response_by_id(draft.id)

    async def archive_geometry_draft(self, draft_id: int) -> NavigationGeometryDraftResponse:
        draft = await self._draft(draft_id)
        if draft.status_code == "PUBLISHED":
            raise ConflictError("已发布草稿不能删除；请通过新版本发布完成替换")
        if draft.status_code in ARCHIVED_DRAFT_STATUSES:
            return await self._draft_response_by_id(draft.id)
        draft.status_code = "ARCHIVED"
        draft.quality_code = "ARCHIVED"
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
        await self._validate_centerline_publish(draft)
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
            review_status_code="PUBLISHED",
            version_no=1,
            is_current=True,
            source_trace_json={
                "navigation_geometry_draft_id": draft.id,
                "published_by": published_by,
                "published_at": self._now().isoformat(),
                **(draft.source_trace_json or {}),
            },
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
        self._validate_boundary_publish(draft.geometry_json)
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
            boundary_quality_code="MANUAL_PUBLISHED",
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

    async def _matched_channels_by_water_area(self, water_area_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
        if not water_area_ids:
            return {}
        rows = list(
            (
                await self.session.execute(
                    select(NavigationWaterBodyFeatureLink.water_area_id, NavigationChannelWaterBodyMatch, NavigationChannel)
                    .join(
                        NavigationChannelWaterBodyMatch,
                        NavigationChannelWaterBodyMatch.water_body_id == NavigationWaterBodyFeatureLink.water_body_id,
                    )
                    .join(NavigationChannel, NavigationChannel.id == NavigationChannelWaterBodyMatch.channel_id)
                    .where(
                        NavigationWaterBodyFeatureLink.water_area_id.in_(water_area_ids),
                        NavigationChannelWaterBodyMatch.is_current.is_(True),
                    )
                    .order_by(NavigationChannelWaterBodyMatch.score.desc(), NavigationChannel.id)
                )
            ).all()
        )
        best_by_area_channel: dict[tuple[int, int], dict[str, Any]] = {}
        for water_area_id, match, channel in rows:
            key = (int(water_area_id), int(channel.id))
            item = {
                "match_id": match.id,
                "channel_id": channel.id,
                "channel_code": channel.channel_code,
                "channel_name": channel.channel_name,
                "score": match.score,
                "match_type_code": match.match_type_code,
                "confidence_code": match.confidence_code,
            }
            existing = best_by_area_channel.get(key)
            if existing is None or int(item["score"]) > int(existing["score"]):
                best_by_area_channel[key] = item
        output: dict[int, list[dict[str, Any]]] = {}
        for (water_area_id, _channel_id), item in best_by_area_channel.items():
            output.setdefault(water_area_id, []).append(item)
        for items in output.values():
            items.sort(key=lambda item: (-int(item["score"]), int(item["channel_id"])))
        return output

    async def _matched_channels_for_water_body(self, water_body_id: int) -> list[dict[str, Any]]:
        rows = list(
            (
                await self.session.execute(
                    select(NavigationChannelWaterBodyMatch, NavigationChannel)
                    .join(NavigationChannel, NavigationChannel.id == NavigationChannelWaterBodyMatch.channel_id)
                    .where(
                        NavigationChannelWaterBodyMatch.water_body_id == water_body_id,
                        NavigationChannelWaterBodyMatch.is_current.is_(True),
                    )
                    .order_by(NavigationChannelWaterBodyMatch.score.desc(), NavigationChannel.id)
                )
            ).all()
        )
        return [
            {
                "match_id": match.id,
                "channel_id": channel.id,
                "channel_code": channel.channel_code,
                "channel_name": channel.channel_name,
                "score": match.score,
                "match_type_code": match.match_type_code,
                "confidence_code": match.confidence_code,
            }
            for match, channel in rows
        ]

    def _water_body_match_item_response(
        self,
        *,
        channel: NavigationChannel,
        match: NavigationChannelWaterBodyMatch,
        water_body: NavigationWaterBody,
    ) -> NavigationChannelWaterBodyMatchItemResponse:
        return NavigationChannelWaterBodyMatchItemResponse(
            id=match.id,
            channel_id=channel.id,
            channel_code=channel.channel_code,
            channel_name=channel.channel_name,
            water_body_id=water_body.id,
            water_body_code=water_body.water_body_code,
            water_name=water_body.water_body_name,
            production_name=water_body.production_name,
            source_code=water_body.source_code,
            body_role_code=water_body.body_role_code,
            source_layer_name=water_body.source_layer_name,
            source_layer_display_name=water_body.source_layer_display_name,
            water_type_code=water_body.water_type_code,
            feature_count=int(water_body.feature_count or 0),
            match_batch_code=match.match_batch_code,
            match_type_code=match.match_type_code,
            matched_term=match.matched_term,
            score=match.score,
            confidence_code=match.confidence_code,
            issue_codes=match.issue_codes or [],
            is_current=match.is_current,
            bbox=self._bbox_dict(water_body),
            source_water_area_ids=[
                int(item)
                for item in (match.source_water_area_ids_json or water_body.source_water_area_ids_json or [])
                if isinstance(item, int) or str(item).isdigit()
            ][:500],
            source_trace_json=match.source_trace_json,
        )

    def _water_body_base_stmt(
        self,
        *,
        keyword: str | None,
        channel_id: int | None,
        source_layer_code: str | None,
        layer_role_code: str | None,
        water_type_code: str | None,
        geometry_status_code: str | None,
        name_status_code: str | None,
        only_matched: bool,
        only_unmatched: bool,
        include_invalid: bool,
    ):
        stmt = select(
            NavigationWaterArea.source_code.label("source_code"),
            NavigationWaterArea.source_layer_code.label("source_layer_code"),
            func.max(NavigationWaterArea.source_layer_name).label("source_layer_name"),
            func.max(NavigationWaterArea.source_layer_display_name).label("source_layer_display_name"),
            func.max(NavigationWaterArea.source_layer_role_code).label("source_layer_role_code"),
            func.min(NavigationWaterArea.source_layer_order).label("source_layer_order"),
            NavigationWaterArea.normalized_water_name.label("normalized_water_name"),
            func.max(NavigationWaterArea.water_name).label("water_name"),
            NavigationWaterArea.water_type_code.label("water_type_code"),
            func.count(NavigationWaterArea.id).label("feature_count"),
            func.sum(case((NavigationWaterArea.is_enabled.is_(True), 1), else_=0)).label("enabled_count"),
            func.sum(case((NavigationWaterArea.geometry_status_code == "REPAIRED", 1), else_=0)).label("repaired_count"),
            func.sum(case((NavigationWaterArea.geometry_status_code == "INVALID", 1), else_=0)).label("invalid_count"),
            func.sum(NavigationWaterArea.area_km2).label("total_area_km2"),
            func.min(NavigationWaterArea.bbox_min_lng).label("bbox_min_lng"),
            func.min(NavigationWaterArea.bbox_min_lat).label("bbox_min_lat"),
            func.max(NavigationWaterArea.bbox_max_lng).label("bbox_max_lng"),
            func.max(NavigationWaterArea.bbox_max_lat).label("bbox_max_lat"),
        ).where(
            NavigationWaterArea.source_code == REAL_WATER_SOURCE_CODE,
            NavigationWaterArea.normalized_water_name.is_not(None),
        )
        if not include_invalid:
            stmt = stmt.where(NavigationWaterArea.is_enabled.is_(True))
        if channel_id:
            matched_area_ids = (
                select(NavigationWaterBodyFeatureLink.water_area_id)
                .join(
                    NavigationChannelWaterBodyMatch,
                    NavigationChannelWaterBodyMatch.water_body_id == NavigationWaterBodyFeatureLink.water_body_id,
                )
                .where(
                    NavigationChannelWaterBodyMatch.channel_id == channel_id,
                    NavigationChannelWaterBodyMatch.is_current.is_(True),
                )
            )
            stmt = stmt.where(NavigationWaterArea.id.in_(matched_area_ids))
        if only_matched:
            matched_area_ids = (
                select(NavigationWaterBodyFeatureLink.water_area_id)
                .join(
                    NavigationChannelWaterBodyMatch,
                    NavigationChannelWaterBodyMatch.water_body_id == NavigationWaterBodyFeatureLink.water_body_id,
                )
                .where(NavigationChannelWaterBodyMatch.is_current.is_(True))
            )
            stmt = stmt.where(NavigationWaterArea.id.in_(matched_area_ids))
        if only_unmatched:
            matched_area_ids = (
                select(NavigationWaterBodyFeatureLink.water_area_id)
                .join(
                    NavigationChannelWaterBodyMatch,
                    NavigationChannelWaterBodyMatch.water_body_id == NavigationWaterBodyFeatureLink.water_body_id,
                )
                .where(NavigationChannelWaterBodyMatch.is_current.is_(True))
            )
            stmt = stmt.where(NavigationWaterArea.id.not_in(matched_area_ids))
        if source_layer_code:
            stmt = stmt.where(NavigationWaterArea.source_layer_code == source_layer_code.upper())
        if layer_role_code:
            stmt = stmt.where(NavigationWaterArea.source_layer_role_code == layer_role_code.upper())
        if water_type_code:
            stmt = stmt.where(NavigationWaterArea.water_type_code == water_type_code.upper())
        if geometry_status_code:
            stmt = stmt.where(NavigationWaterArea.geometry_status_code == geometry_status_code.upper())
        if keyword:
            text = keyword.strip()
            like = f"%{text}%"
            stmt = stmt.where(
                (NavigationWaterArea.water_name.like(like)) | (NavigationWaterArea.normalized_water_name.like(like))
            )
        stmt = stmt.group_by(
            NavigationWaterArea.source_code,
            NavigationWaterArea.source_layer_code,
            NavigationWaterArea.normalized_water_name,
            NavigationWaterArea.water_type_code,
        )
        if keyword:
            text = keyword.strip()
            exact_rank = case((NavigationWaterArea.normalized_water_name == text, 0), else_=1)
            stmt = stmt.order_by(
                exact_rank,
                func.min(NavigationWaterArea.source_layer_order),
                func.count(NavigationWaterArea.id).desc(),
                func.sum(NavigationWaterArea.area_km2).desc(),
                NavigationWaterArea.normalized_water_name,
            )
        else:
            stmt = stmt.order_by(
                func.min(NavigationWaterArea.source_layer_order),
                NavigationWaterArea.normalized_water_name,
                NavigationWaterArea.water_type_code,
            )
        return stmt

    def _water_body_asset_stmt(
        self,
        *,
        keyword: str | None,
        channel_id: int | None,
        body_role_code: str | None,
        dedupe_status_code: str | None,
        source_layer_code: str | None,
        layer_role_code: str | None,
        water_type_code: str | None,
        geometry_status_code: str | None,
        name_status_code: str | None,
        only_matched: bool,
        only_unmatched: bool,
        include_invalid: bool,
    ):
        stmt = select(NavigationWaterBody).where(NavigationWaterBody.source_code == REAL_WATER_SOURCE_CODE)
        if not include_invalid:
            stmt = stmt.where(NavigationWaterBody.is_enabled.is_(True))
        if channel_id:
            matched_body_ids = (
                select(NavigationChannelWaterBodyMatch.water_body_id)
                .where(
                    NavigationChannelWaterBodyMatch.channel_id == channel_id,
                    NavigationChannelWaterBodyMatch.is_current.is_(True),
                )
            )
            stmt = stmt.where(NavigationWaterBody.id.in_(matched_body_ids))
        if only_matched:
            matched_body_ids = (
                select(NavigationChannelWaterBodyMatch.water_body_id)
                .where(NavigationChannelWaterBodyMatch.is_current.is_(True))
            )
            stmt = stmt.where(NavigationWaterBody.id.in_(matched_body_ids))
        if only_unmatched:
            matched_body_ids = (
                select(NavigationChannelWaterBodyMatch.water_body_id)
                .where(NavigationChannelWaterBodyMatch.is_current.is_(True))
            )
            stmt = stmt.where(NavigationWaterBody.id.not_in(matched_body_ids))
        if body_role_code:
            role = body_role_code.upper()
            if role == "STANDARD":
                stmt = stmt.where(NavigationWaterBody.body_role_code.in_(["PRIMARY_HIERARCHY", "RX_FILL_GAP"]))
            elif role == "RX_DUPLICATE":
                duplicate_body_ids = select(NavigationWaterBodyFeatureLink.water_body_id).where(
                    NavigationWaterBodyFeatureLink.link_role_code == "RX_DUPLICATE"
                )
                stmt = stmt.where(NavigationWaterBody.id.in_(duplicate_body_ids))
            else:
                stmt = stmt.where(NavigationWaterBody.body_role_code == role)
        if dedupe_status_code:
            stmt = stmt.where(NavigationWaterBody.dedupe_status_code == dedupe_status_code.upper())
        if source_layer_code:
            stmt = stmt.where(NavigationWaterBody.source_layer_code == source_layer_code.upper())
        if layer_role_code:
            stmt = stmt.where(NavigationWaterBody.source_layer_role_code == layer_role_code.upper())
        if water_type_code:
            stmt = stmt.where(NavigationWaterBody.water_type_code == water_type_code.upper())
        if geometry_status_code:
            status = geometry_status_code.upper()
            if status == "INVALID":
                stmt = stmt.where(NavigationWaterBody.invalid_feature_count > 0)
            elif status == "REPAIRED":
                stmt = stmt.where(NavigationWaterBody.repaired_feature_count > 0)
            else:
                stmt = stmt.where(NavigationWaterBody.quality_code == status)
        if name_status_code:
            stmt = stmt.where(NavigationWaterBody.name_status_code == name_status_code.upper())
        if keyword:
            text = keyword.strip()
            like = f"%{text}%"
            stmt = stmt.where(
                (NavigationWaterBody.water_body_name.like(like))
                | (NavigationWaterBody.normalized_water_name.like(like))
                | (NavigationWaterBody.display_name.like(like))
                | (NavigationWaterBody.production_name.like(like))
            )
            exact_rank = case(
                (
                    (NavigationWaterBody.normalized_water_name == text)
                    | (NavigationWaterBody.water_body_name == text)
                    | (NavigationWaterBody.production_name == text)
                    | (NavigationWaterBody.display_name == text),
                    0,
                ),
                else_=1,
            )
            stmt = stmt.order_by(
                exact_rank,
                NavigationWaterBody.source_layer_order,
                NavigationWaterBody.feature_count.desc(),
                NavigationWaterBody.area_km2.desc(),
                NavigationWaterBody.water_body_name,
            )
        else:
            role_rank = case(
                (NavigationWaterBody.body_role_code == "PRIMARY_HIERARCHY", 0),
                (NavigationWaterBody.body_role_code == "RX_FILL_GAP", 1),
                (NavigationWaterBody.body_role_code == "RX_DUPLICATE", 2),
                (NavigationWaterBody.body_role_code == "RX8_BACKUP", 3),
                (NavigationWaterBody.body_role_code == "INVALID_DIAGNOSTIC", 4),
                else_=9,
            )
            stmt = stmt.order_by(role_rank, NavigationWaterBody.source_layer_order, NavigationWaterBody.water_body_name, NavigationWaterBody.id)
        return stmt

    async def _water_body_asset_response(self, body: NavigationWaterBody) -> NavigationWaterBodyListItemResponse:
        water_area_ids = [
            int(item)
            for item in (body.source_water_area_ids_json or [])
            if isinstance(item, int) or str(item).isdigit()
        ][:500]
        matched_channels = await self._matched_channels_for_water_body(int(body.id))
        return NavigationWaterBodyListItemResponse(
            id=body.id,
            group_key=self._encode_water_body_key({"water_body_id": body.id}),
            water_body_code=body.water_body_code,
            source_code=body.source_code,
            body_role_code=body.body_role_code,
            dedupe_status_code=body.dedupe_status_code,
            source_layer_code=body.source_layer_code,
            source_layer_name=body.source_layer_name,
            source_layer_display_name=body.source_layer_display_name,
            source_layer_role_code=body.source_layer_role_code,
            source_layer_order=body.source_layer_order,
            water_name=body.water_body_name,
            normalized_water_name=body.normalized_water_name,
            display_name=body.display_name or body.production_name or body.water_body_name,
            production_name=body.production_name,
            name_status_code=body.name_status_code,
            name_source_code=body.name_source_code,
            name_note=body.name_note,
            water_type_code=body.water_type_code,
            feature_count=int(body.feature_count or 0),
            enabled_count=int(body.enabled_feature_count or 0),
            repaired_count=int(body.repaired_feature_count or 0),
            invalid_count=int(body.invalid_feature_count or 0),
            total_area_km2=self._float(body.area_km2),
            quality_code=body.quality_code,
            source_layer_summary=body.source_layer_summary_json,
            coordinate_system_code=body.coordinate_system_code,
            display_coordinate_system_code=body.display_coordinate_system_code,
            bbox={
                "min_lng": self._float(body.bbox_min_lng),
                "min_lat": self._float(body.bbox_min_lat),
                "max_lng": self._float(body.bbox_max_lng),
                "max_lat": self._float(body.bbox_max_lat),
            },
            display_bbox={
                "min_lng": self._float(body.display_bbox_min_lng),
                "min_lat": self._float(body.display_bbox_min_lat),
                "max_lng": self._float(body.display_bbox_max_lng),
                "max_lat": self._float(body.display_bbox_max_lat),
            },
            match_count=len(matched_channels),
            is_matched=bool(matched_channels),
            matched_channels=matched_channels,
            representative_water_area_ids=water_area_ids,
        )

    async def _water_body_ids(
        self,
        *,
        source_code: str,
        source_layer_code: str | None,
        normalized_water_name: str,
        water_type_code: str,
        include_invalid: bool,
        limit: int,
    ) -> list[int]:
        stmt = (
            select(NavigationWaterArea.id)
            .where(
                NavigationWaterArea.source_code == source_code,
                NavigationWaterArea.normalized_water_name == normalized_water_name,
                NavigationWaterArea.water_type_code == water_type_code,
            )
            .order_by(NavigationWaterArea.source_layer_order, NavigationWaterArea.id)
            .limit(limit)
        )
        if source_layer_code:
            stmt = stmt.where(NavigationWaterArea.source_layer_code == source_layer_code)
        else:
            stmt = stmt.where(NavigationWaterArea.source_layer_code.is_(None))
        if not include_invalid:
            stmt = stmt.where(NavigationWaterArea.is_enabled.is_(True))
        return [int(row[0]) for row in (await self.session.execute(stmt)).all()]

    def _water_body_feature_stmt(self, payload: dict[str, Any]):
        if payload.get("water_body_id") is not None:
            try:
                water_body_id = int(payload.get("water_body_id"))
            except (TypeError, ValueError) as exc:
                raise ValidationError("Invalid water body key") from exc
            return (
                select(NavigationWaterArea)
                .join(NavigationWaterBodyFeatureLink, NavigationWaterBodyFeatureLink.water_area_id == NavigationWaterArea.id)
                .where(NavigationWaterBodyFeatureLink.water_body_id == water_body_id)
                .order_by(
                    NavigationWaterBodyFeatureLink.is_primary.desc(),
                    NavigationWaterArea.source_layer_order,
                    NavigationWaterArea.id,
                )
            )
        source_code = str(payload.get("source_code") or REAL_WATER_SOURCE_CODE)
        source_layer_code = payload.get("source_layer_code")
        normalized_water_name = str(payload.get("normalized_water_name") or "")
        water_type_code = str(payload.get("water_type_code") or "")
        if not normalized_water_name or not water_type_code:
            raise ValidationError("Invalid water body key")
        stmt = (
            select(NavigationWaterArea)
            .where(
                NavigationWaterArea.source_code == source_code,
                NavigationWaterArea.normalized_water_name == normalized_water_name,
                NavigationWaterArea.water_type_code == water_type_code,
            )
            .order_by(NavigationWaterArea.source_layer_order, NavigationWaterArea.id)
        )
        if source_layer_code:
            stmt = stmt.where(NavigationWaterArea.source_layer_code == str(source_layer_code))
        else:
            stmt = stmt.where(NavigationWaterArea.source_layer_code.is_(None))
        return stmt

    async def _matched_channels_for_water_ids(self, water_area_ids: list[int]) -> list[dict[str, Any]]:
        matched_by_area = await self._matched_channels_by_water_area(water_area_ids)
        by_channel: dict[int, dict[str, Any]] = {}
        for channels in matched_by_area.values():
            for channel in channels:
                existing = by_channel.get(int(channel["channel_id"]))
                if existing is None or int(channel["score"]) > int(existing["score"]):
                    by_channel[int(channel["channel_id"])] = channel
        return sorted(by_channel.values(), key=lambda item: (-int(item["score"]), int(item["channel_id"])))

    def _encode_water_body_key(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    def _decode_water_body_key(self, value: str) -> dict[str, Any]:
        try:
            padded = value + ("=" * (-len(value) % 4))
            payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        except Exception as exc:
            raise ValidationError("Invalid water body key") from exc
        if not isinstance(payload, dict):
            raise ValidationError("Invalid water body key")
        return payload

    def _water_area_response(
        self,
        row: NavigationWaterArea,
        matched_channels: list[dict[str, Any]] | None = None,
    ) -> NavigationWaterAreaListItemResponse:
        matched_channels = matched_channels or []
        meta = water_area_layer_meta(row.source_layer_name)
        return NavigationWaterAreaListItemResponse(
            id=row.id,
            source_code=row.source_code,
            source_layer_name=row.source_layer_name,
            source_layer_code=row.source_layer_code or meta.source_layer_code,
            source_layer_display_name=row.source_layer_display_name or meta.source_layer_display_name,
            source_layer_role_code=row.source_layer_role_code or meta.source_layer_role_code,
            source_layer_order=row.source_layer_order if row.source_layer_order is not None else meta.source_layer_order,
            source_file_name=row.source_file_name,
            source_object_id=row.source_object_id,
            has_attributes=bool(row.has_attributes),
            raw_properties_summary=self._raw_properties_summary(row.raw_properties_json),
            water_name=row.water_name,
            normalized_water_name=row.normalized_water_name,
            water_type_code=row.water_type_code,
            geometry_status_code=row.geometry_status_code,
            bbox=self._bbox_dict(row),
            center_lng=self._float(row.center_lng),
            center_lat=self._float(row.center_lat),
            area_km2=self._float(row.area_km2),
            match_count=len(matched_channels),
            is_matched=bool(matched_channels),
            matched_channels=matched_channels,
        )

    def _raw_properties_summary(self, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(value, dict) or not value:
            return None
        keys = ("OBJECTID", "NAME", "REMARK", "Shape_Leng", "Shape_Area")
        return {key: value.get(key) for key in keys if key in value}

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

    def _publish_validation_error(self, code: str, message: str) -> ValidationError:
        return ValidationError(f"{code}: {message}", code=code, detail={"error_code": code, "message": message})

    async def _validate_centerline_publish(self, draft: NavigationGeometryDraft) -> None:
        geometry = draft.geometry_json
        try:
            line = shape(geometry)
        except Exception as exc:
            raise self._publish_validation_error("CENTERLINE_GEOMETRY_INVALID", "中心线 GeoJSON 无法解析") from exc
        if not isinstance(line, LineString) or line.is_empty or len(line.coords) < 2:
            raise self._publish_validation_error("CENTERLINE_GEOMETRY_INVALID", "中心线必须是至少包含 2 个点的 LineString")
        if not self._coordinates_legal(geometry):
            raise self._publish_validation_error("CENTERLINE_COORDINATE_INVALID", "中心线经纬度不合法")
        length_m = abs(float(GEOD.line_length([coord[0] for coord in line.coords], [coord[1] for coord in line.coords])))
        if length_m < MIN_CENTERLINE_LENGTH_M:
            raise self._publish_validation_error("CENTERLINE_TOO_SHORT", f"中心线长度 {length_m:.1f}m 小于 {MIN_CENTERLINE_LENGTH_M:.0f}m")
        boundary = await self._current_available_boundary(draft.channel_id)
        if boundary is None or not boundary.geometry_json:
            return
        try:
            boundary_geometry = shape(boundary.geometry_json)
        except Exception as exc:
            raise self._publish_validation_error("CENTERLINE_OUT_OF_BOUNDARY", "当前边界几何无法用于中心线校验") from exc
        if boundary_geometry.covers(line) or boundary_geometry.buffer(PUBLISH_BOUNDARY_TOLERANCE_DEGREE).covers(line):
            return
        raise self._publish_validation_error("CENTERLINE_OUT_OF_BOUNDARY", "中心线明显超出当前航道边界，禁止发布")

    def _validate_boundary_publish(self, geometry: dict[str, Any]) -> None:
        try:
            polygon = shape(geometry)
        except Exception as exc:
            raise self._publish_validation_error("BOUNDARY_GEOMETRY_INVALID", "边界 GeoJSON 无法解析") from exc
        if not isinstance(polygon, (Polygon, MultiPolygon)) or polygon.is_empty:
            raise self._publish_validation_error("BOUNDARY_GEOMETRY_INVALID", "边界必须是 Polygon 或 MultiPolygon")
        if not self._coordinates_legal(geometry):
            raise self._publish_validation_error("BOUNDARY_GEOMETRY_INVALID", "边界经纬度不合法")
        if not self._rings_closed(geometry):
            raise self._publish_validation_error("BOUNDARY_RING_NOT_CLOSED", "边界环必须闭合")
        if not polygon.is_valid:
            raise self._publish_validation_error("BOUNDARY_GEOMETRY_INVALID", "边界几何不合法")
        area_m2 = abs(float(GEOD.geometry_area_perimeter(polygon)[0]))
        if area_m2 < MIN_BOUNDARY_AREA_M2:
            raise self._publish_validation_error("BOUNDARY_AREA_TOO_SMALL", f"边界面积 {area_m2:.1f}m² 小于最低阈值")
        min_lng, min_lat, max_lng, max_lat = polygon.bounds
        if min_lng >= max_lng or min_lat >= max_lat:
            raise self._publish_validation_error("BOUNDARY_GEOMETRY_INVALID", "边界 bbox 无效")

    async def _current_available_boundary(self, channel_id: int | None) -> NavigationChannelBoundary | None:
        if channel_id is None:
            return None
        return (
            await self.session.execute(
                select(NavigationChannelBoundary)
                .where(
                    NavigationChannelBoundary.channel_id == channel_id,
                    NavigationChannelBoundary.is_current.is_(True),
                    NavigationChannelBoundary.geometry_status_code == "AVAILABLE",
                )
                .order_by(NavigationChannelBoundary.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    def _coordinates_legal(self, geometry: dict[str, Any]) -> bool:
        pairs = self._coordinate_pairs(geometry.get("coordinates"))
        raw_count = 0

        def walk(item: Any) -> None:
            nonlocal raw_count
            if not isinstance(item, list):
                return
            if len(item) >= 2 and all(isinstance(item[index], (int, float)) for index in (0, 1)):
                raw_count += 1
                return
            for child in item:
                walk(child)

        walk(geometry.get("coordinates"))
        return raw_count > 0 and raw_count == len(pairs)

    def _rings_closed(self, geometry: dict[str, Any]) -> bool:
        geometry_type = geometry.get("type")
        coordinates = geometry.get("coordinates")
        polygons = [coordinates] if geometry_type == "Polygon" else coordinates if geometry_type == "MultiPolygon" else []
        if not isinstance(polygons, list) or not polygons:
            return False
        for polygon in polygons:
            if not isinstance(polygon, list) or not polygon:
                return False
            for ring in polygon:
                if not isinstance(ring, list) or len(ring) < 4:
                    return False
                if ring[0] != ring[-1]:
                    return False
        return True

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
