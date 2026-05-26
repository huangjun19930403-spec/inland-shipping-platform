from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import (
    NavigationChannelCenterline,
    NavigationChannelWaterBodyMatch,
    NavigationGeometryDraft,
    NavigationGraphEdge,
    NavigationGraphVersion,
    NavigationRouteResult,
    NavigationWaterArea,
    NavigationWaterBody,
    NavigationWaterBodyFeatureLink,
)
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.modules.navigation.schemas import (
    NavigationBoundaryListItemResponse,
    NavigationCandidateGenerateRequest,
    NavigationCandidateGenerateResponse,
    NavigationChannelPipelineResponse,
    NavigationOsmImportRequest,
    NavigationOsmImportResponse,
    NavigationProductionChannelResponse,
    NavigationProductionLayerLegendResponse,
    NavigationProductionStepResponse,
    NavigationProductionSummaryResponse,
    NavigationProductionWorkspaceResponse,
)
from app.modules.navigation.diagnostic_service import NavigationDiagnosticService
from app.modules.navigation.map_layer_service import NavigationMapLayerService
from app.modules.navigation.services.boundary_candidate_service import NavigationBoundaryCandidateService
from app.modules.navigation.services.osm_import_service import import_osm_waterways
from app.modules.navigation.workbench_service import NavigationWorkbenchService


REAL_WATER_SOURCE_CODE = "RIVER_SHAPEFILE_2026"
BOUNDARY_CANDIDATE_POLICIES = {
    "RIVER_MATCH_CANDIDATE",
    "WATER_BODY_UNION_RAW",
    "WATER_BODY_UNION_CLEANED",
    "WATER_BODY_UNION_SIMPLIFIED",
    "CENTERLINE_BUFFER",
    "AIS_INFERRED",
    "MANUAL_DRAW",
}
PUBLISHED_BOUNDARY_POLICIES = {"MANUAL_DRAW", "OFFICIAL_IMPORT"}
STAGE_LABELS = {
    "NO_WATER_MATCH": "水体待归属",
    "WATER_MATCH_READY": "边界待生成",
    "BOUNDARY_CANDIDATE": "边界待发布",
    "BOUNDARY_PUBLISHED": "中心线待生产",
    "CENTERLINE_CANDIDATE": "中心线待发布",
    "CENTERLINE_PUBLISHED": "图网络待构建",
    "GRAPH_READY": "路径待验证",
    "ROUTE_VERIFIED": "路径已验证",
    "BLOCKED": "生产阻塞",
}
NEXT_ACTIONS = {
    "NO_WATER_MATCH": ("规划航道水系", "/navigation/production/water-matches"),
    "WATER_MATCH_READY": ("生成边界", "/navigation/production/boundaries"),
    "BOUNDARY_CANDIDATE": ("修正并确认边界", "/navigation/production/boundaries"),
    "BOUNDARY_PUBLISHED": ("生成中心线", "/navigation/production/centerlines"),
    "CENTERLINE_CANDIDATE": ("发布中心线", "/navigation/production/centerlines"),
    "CENTERLINE_PUBLISHED": ("构建图网络", "/navigation/production/graphs"),
    "GRAPH_READY": ("验证路径", "/navigation/routes"),
    "ROUTE_VERIFIED": ("查看路径验证", "/navigation/routes"),
    "BLOCKED": ("处理标注任务", "/navigation/production/annotations"),
}
STEP_NAMES = {
    "WATER_MATCH": "航道水系规划",
    "BOUNDARY": "边界生成",
    "CENTERLINE": "中心线生成",
    "GRAPH": "图网络构建",
    "ROUTE": "路径验证",
}


class NavigationProductionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.workbench = NavigationWorkbenchService(session)

    async def summary(self) -> NavigationProductionSummaryResponse:
        channels = await self._channels()
        channel_rows = await self._production_channels(channels)
        stage_counts = dict(Counter(row.production_stage_code for row in channel_rows))
        active_graph_version = await self._active_graph_version()
        stats = {
            "channel_count": len(channels),
            "real_water_area_count": int(
                await self.session.scalar(
                    select(func.count()).select_from(NavigationWaterArea).where(
                        NavigationWaterArea.source_code == REAL_WATER_SOURCE_CODE,
                        NavigationWaterArea.is_enabled.is_(True),
                    )
                )
                or 0
            ),
            "water_body_count": int(
                await self.session.scalar(
                    select(func.count()).select_from(NavigationWaterBody).where(NavigationWaterBody.is_enabled.is_(True))
                )
                or 0
            ),
            "water_body_matched_channel_count": sum(1 for row in channel_rows if row.current_water_body_match_count > 0),
            "boundary_candidate_channel_count": sum(1 for row in channel_rows if row.candidate_boundary_count > 0),
            "published_centerline_channel_count": sum(1 for row in channel_rows if row.published_current_centerline_count > 0),
            "active_graph_channel_count": sum(1 for row in channel_rows if row.active_graph_edge_count > 0),
            "route_verified_channel_count": sum(1 for row in channel_rows if row.route_verified_count > 0),
        }
        return NavigationProductionSummaryResponse(
            stats=stats,
            stage_counts=stage_counts,
            active_graph_version=self.workbench._graph_version_dict(active_graph_version) if active_graph_version else None,
            channels=channel_rows,
            warnings=[
                "本模块只使用真实 revier 水系 seed、清洗航道 seed、运输节点与约束点作为生产数据。",
                "外部水路线中心线默认只是候选，必须发布后才能进入图网络。",
                "READY 只代表业务路径图可用，不代表官方安全通航确认。",
            ],
        )

    async def channels(self) -> list[NavigationProductionChannelResponse]:
        return await self._production_channels(await self._channels())

    async def pipeline(self, channel_id: int) -> NavigationChannelPipelineResponse:
        channel = await self.session.get(NavigationChannel, channel_id)
        if channel is None:
            raise NotFoundError("NavigationChannel", channel_id)
        row = (await self._production_channels([channel]))[0]
        return NavigationChannelPipelineResponse(
            channel=row,
            map_layer_query={
                "channel_id": channel_id,
                "include_water_area": True,
                "include_boundary": True,
                "include_centerline": True,
                "include_graph_edge": True,
                "limit": 260,
            },
            available_actions=row.available_actions,
            warnings=self._warnings_for(row),
        )

    async def production_workspace(self, channel_id: int, *, step: str) -> NavigationProductionWorkspaceResponse:
        channel = await self.session.get(NavigationChannel, channel_id)
        if channel is None:
            raise NotFoundError("NavigationChannel", channel_id)
        step_code = self._normalize_workspace_step(step)
        row = (await self._production_channels([channel]))[0]
        include_water = step_code in {"WATER", "BOUNDARY", "CENTERLINE"}
        include_boundary = step_code in {"WATER", "BOUNDARY", "CENTERLINE"}
        include_centerline = step_code in {"CENTERLINE", "GRAPH", "ROUTE"}
        include_graph = step_code in {"GRAPH", "ROUTE"}
        map_layers = await NavigationMapLayerService(self.session).get_layers(
            min_lng=None,
            min_lat=None,
            max_lng=None,
            max_lat=None,
            channel_id=channel_id,
            route_result_id=None,
            include_water_area=include_water,
            include_boundary=include_boundary,
            include_centerline=include_centerline,
            include_centerline_segments=step_code == "CENTERLINE",
            include_graph_edge=include_graph,
            limit=260,
        )
        water_matches = None
        water_candidates = None
        boundaries: list[NavigationBoundaryListItemResponse] = []
        centerlines = []
        drafts = []
        if step_code == "WATER":
            water_matches = await self.workbench.list_water_body_matches(channel_id=channel_id, limit=500)
            water_candidates = await NavigationDiagnosticService(self.session).water_body_candidates(channel_id, limit=80)
        if step_code == "BOUNDARY":
            boundaries = await self._boundary_workspace_rows(channel_id)
            drafts = await self.workbench.list_geometry_drafts(channel_id=channel_id, limit=80)
            drafts = [draft for draft in drafts if draft.draft_type_code == "BOUNDARY"]
        if step_code == "CENTERLINE":
            centerlines = await self.centerline_candidates(channel_id=channel_id, limit=200)
            drafts = await self.workbench.list_geometry_drafts(channel_id=channel_id, limit=80)
            drafts = [draft for draft in drafts if draft.draft_type_code == "CENTERLINE"]
        current_boundary = next((item for item in boundaries if item.is_current), None)
        if current_boundary is None:
            current_boundary = await self._current_boundary_item(channel_id)
        current_centerline = next((item for item in centerlines if item.is_current and item.review_status_code == "PUBLISHED"), None)
        if current_centerline is None:
            current_centerline = await self._current_centerline_item(channel_id)
        active_graph_version = await self._active_graph_version()
        downstream_stale = self._downstream_stale(current_boundary, current_centerline, active_graph_version)
        matched_water_body_bbox = self._features_bbox(map_layers.water_areas)
        current_boundary_bbox = self._geometry_bbox(current_boundary.geometry_json) if current_boundary else None
        channel_reference_bbox = matched_water_body_bbox or current_boundary_bbox
        centerline_bbox = self._geometry_bbox(current_centerline.geometry_json) if current_centerline else None
        graph_bbox = self._graph_bbox(active_graph_version) if active_graph_version else None
        return NavigationProductionWorkspaceResponse(
            channel=row,
            step_code=step_code,
            step_name=self._workspace_step_name(step_code),
            map_layers=map_layers,
            layer_legends=self._layer_legends(step_code),
            water_matches=water_matches,
            water_candidates=water_candidates,
            boundaries=boundaries,
            centerlines=centerlines,
            drafts=drafts,
            current_boundary=current_boundary,
            current_centerline=current_centerline,
            active_graph_version=self.workbench._graph_version_dict(active_graph_version) if active_graph_version else None,
            channel_reference_bbox=channel_reference_bbox,
            matched_water_body_bbox=matched_water_body_bbox,
            current_boundary_bbox=current_boundary_bbox,
            boundary_coverage_status=self._coverage_status(channel_reference_bbox, current_boundary_bbox),
            centerline_coverage_status=self._coverage_status(current_boundary_bbox, centerline_bbox, stale=downstream_stale.get("centerline_stale")),
            graph_coverage_status=self._coverage_status(current_boundary_bbox, graph_bbox, stale=downstream_stale.get("graph_stale")),
            downstream_stale=downstream_stale,
            available_actions=row.available_actions,
            blocker_codes=row.blocker_codes,
            warnings=self._warnings_for(row),
        )

    async def boundary_candidates(self, channel_id: int, limit: int = 120) -> list[NavigationBoundaryListItemResponse]:
        await self.pipeline(channel_id)
        rows = list(
            (
                await self.session.execute(
                    select(NavigationChannelBoundary, NavigationChannel)
                    .join(NavigationChannel, NavigationChannel.id == NavigationChannelBoundary.channel_id)
                    .where(
                        NavigationChannelBoundary.channel_id == channel_id,
                        NavigationChannelBoundary.is_current.is_(False),
                        NavigationChannelBoundary.coverage_policy_code.in_(BOUNDARY_CANDIDATE_POLICIES),
                        NavigationChannelBoundary.geometry_status_code == "AVAILABLE",
                    )
                    .order_by(NavigationChannelBoundary.id.desc())
                    .limit(max(1, min(limit, 300)))
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
                source_trace_json=boundary.source_trace_json,
            )
            for boundary, channel in rows
        ]

    async def generate_boundary_candidates(
        self,
        *,
        channel_id: int,
        body: NavigationCandidateGenerateRequest,
    ) -> NavigationCandidateGenerateResponse:
        return await NavigationBoundaryCandidateService(self.session, self.workbench).generate_boundary_candidates(
            channel_id=channel_id,
            body=body,
        )

    async def centerline_candidates(self, channel_id: int, limit: int = 120):
        await self.pipeline(channel_id)
        return await self.workbench.list_centerlines(channel_id=channel_id, limit=limit)

    async def generate_centerline_candidates(
        self,
        *,
        channel_id: int,
        body: NavigationCandidateGenerateRequest,
    ) -> NavigationCandidateGenerateResponse:
        await self.pipeline(channel_id)
        centerlines = await self.centerline_candidates(channel_id=channel_id, limit=300)
        candidate_ids = [
            item.id
            for item in centerlines
            if not item.is_current or item.review_status_code != "PUBLISHED" or item.quality_code not in {"READY", "READY_WITH_WARNING"}
        ]
        if candidate_ids:
            return NavigationCandidateGenerateResponse(
                status_code="EXISTS",
                message="已找到真实中心线候选，请在地图中载入修正后发布。",
                candidate_count=len(candidate_ids),
                centerline_ids=candidate_ids,
                next_path=f"/navigation/production/centerlines?channel_id={channel_id}",
            )
        return NavigationCandidateGenerateResponse(
            status_code="WAITING_FOR_SOURCE",
            message="当前没有可用中心线候选。请使用地图绘制中心线，或先通过后台导入真实外部水路线、历史轨迹或人工中心线数据源。",
            blocker_codes=["CENTERLINE_SOURCE_MISSING"],
            next_path=f"/navigation/production/centerlines?channel_id={channel_id}",
        )

    async def create_osm_import(self, body: NavigationOsmImportRequest) -> NavigationOsmImportResponse:
        source_path = Path(body.source_path).expanduser() if body.source_path else None
        if source_path is None or not source_path.exists():
            return NavigationOsmImportResponse(
                status_code="WAITING_FOR_SOURCE",
                message="请先配置真实外部水路线数据源；系统不会生成示例中心线。",
                next_path="/navigation/production/centerlines",
            )
        summary = await import_osm_waterways(
            session=self.session,
            source_path=source_path,
            scope_code=body.scope_code,
            dry_run=body.dry_run,
        )
        return NavigationOsmImportResponse(
            status_code="DRY_RUN" if body.dry_run else "IMPORTED",
            imported_count=0 if body.dry_run else summary.candidate_count,
            candidate_count=summary.candidate_count,
            message=f"已处理真实外部水路线数据：候选 {summary.candidate_count} 条，跳过 {summary.skipped_count} 条。",
            next_path="/navigation/production/centerlines",
        )

    async def _boundary_workspace_rows(self, channel_id: int) -> list[NavigationBoundaryListItemResponse]:
        rows = list(
            (
                await self.session.execute(
                    select(NavigationChannelBoundary, NavigationChannel)
                    .join(NavigationChannel, NavigationChannel.id == NavigationChannelBoundary.channel_id)
                    .where(
                        NavigationChannelBoundary.channel_id == channel_id,
                        NavigationChannelBoundary.geometry_status_code == "AVAILABLE",
                    )
                    .order_by(NavigationChannelBoundary.is_current.desc(), NavigationChannelBoundary.id.desc())
                    .limit(300)
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
                source_trace_json=boundary.source_trace_json,
                previous_boundary_id=self.workbench._trace_int(boundary.source_trace_json, "previous_boundary_id"),
                caused_downstream_stale=self.workbench._trace_bool(boundary.source_trace_json, "caused_downstream_stale"),
                created_at=self.workbench._iso_datetime(boundary.created_at),
                updated_at=self.workbench._iso_datetime(boundary.updated_at),
            )
            for boundary, channel in rows
        ]

    async def _current_boundary_item(self, channel_id: int) -> NavigationBoundaryListItemResponse | None:
        boundaries = await self.workbench.list_boundaries(channel_id=channel_id, limit=300)
        return next((item for item in boundaries if item.is_current and item.geometry_status_code == "AVAILABLE"), None)

    async def _current_centerline_item(self, channel_id: int):
        centerlines = await self.workbench.list_centerlines(channel_id=channel_id, limit=100)
        return next((item for item in centerlines if item.is_current and item.review_status_code == "PUBLISHED"), None)

    def _downstream_stale(
        self,
        current_boundary: NavigationBoundaryListItemResponse | None,
        current_centerline: Any | None,
        active_graph_version: NavigationGraphVersion | None,
    ) -> dict[str, Any]:
        boundary_id = current_boundary.id if current_boundary else None
        centerline_boundary_id = current_centerline.based_on_boundary_id if current_centerline else None
        graph_summary = active_graph_version.source_summary_json if active_graph_version is not None else None
        graph_boundary_ids = []
        if isinstance(graph_summary, dict):
            raw_ids = graph_summary.get("source_boundary_ids") or []
            graph_boundary_ids = [int(item) for item in raw_ids if isinstance(item, int) or (isinstance(item, str) and item.isdigit())]
        boundary_caused_stale = bool(current_boundary and current_boundary.caused_downstream_stale)
        centerline_stale = bool(
            boundary_id
            and current_centerline
            and (
                (centerline_boundary_id and int(centerline_boundary_id) != int(boundary_id))
                or (boundary_caused_stale and not centerline_boundary_id)
            )
        )
        graph_stale = bool(
            boundary_id
            and active_graph_version
            and (
                (graph_boundary_ids and int(boundary_id) not in graph_boundary_ids)
                or (boundary_caused_stale and not graph_boundary_ids)
            )
        )
        return {
            "current_boundary_id": boundary_id,
            "current_centerline_boundary_id": centerline_boundary_id,
            "active_graph_boundary_ids": graph_boundary_ids,
            "boundary_caused_downstream_stale": boundary_caused_stale,
            "centerline_stale": centerline_stale,
            "graph_stale": graph_stale,
            "any_stale": centerline_stale or graph_stale,
        }

    def _features_bbox(self, items: list[Any]) -> dict[str, float] | None:
        boxes = [self._geometry_bbox(item.geometry_json) for item in items if item.geometry_json]
        boxes = [box for box in boxes if box is not None]
        if not boxes:
            return None
        return {
            "min_lng": min(box["min_lng"] for box in boxes),
            "min_lat": min(box["min_lat"] for box in boxes),
            "max_lng": max(box["max_lng"] for box in boxes),
            "max_lat": max(box["max_lat"] for box in boxes),
        }

    def _geometry_bbox(self, geometry_json: dict[str, Any] | None) -> dict[str, float] | None:
        coords: list[tuple[float, float]] = []

        def walk(value: Any) -> None:
            if not isinstance(value, list):
                return
            if len(value) >= 2 and isinstance(value[0], (int, float)) and isinstance(value[1], (int, float)):
                coords.append((float(value[0]), float(value[1])))
                return
            for child in value:
                walk(child)

        if isinstance(geometry_json, dict):
            geometry = geometry_json.get("geometry") if geometry_json.get("type") == "Feature" else geometry_json
            if isinstance(geometry, dict):
                walk(geometry.get("coordinates"))
        if not coords:
            return None
        return {
            "min_lng": min(lng for lng, _lat in coords),
            "min_lat": min(lat for _lng, lat in coords),
            "max_lng": max(lng for lng, _lat in coords),
            "max_lat": max(lat for _lng, lat in coords),
        }

    def _graph_bbox(self, graph_version: NavigationGraphVersion) -> dict[str, float] | None:
        bbox = graph_version.build_scope_bbox_json if isinstance(graph_version.build_scope_bbox_json, dict) else None
        if not bbox:
            return None
        if {"min_lng", "min_lat", "max_lng", "max_lat"}.issubset(bbox):
            return {
                "min_lng": float(bbox["min_lng"]),
                "min_lat": float(bbox["min_lat"]),
                "max_lng": float(bbox["max_lng"]),
                "max_lat": float(bbox["max_lat"]),
            }
        return None

    def _coverage_status(
        self,
        expected: dict[str, float] | None,
        actual: dict[str, float] | None,
        *,
        stale: bool | None = False,
    ) -> str:
        if actual is None:
            return "MISSING"
        if stale:
            return "STALE"
        if expected is None:
            return "UNKNOWN"
        expected_area = max((expected["max_lng"] - expected["min_lng"]) * (expected["max_lat"] - expected["min_lat"]), 1e-9)
        inter_lng = max(0.0, min(expected["max_lng"], actual["max_lng"]) - max(expected["min_lng"], actual["min_lng"]))
        inter_lat = max(0.0, min(expected["max_lat"], actual["max_lat"]) - max(expected["min_lat"], actual["min_lat"]))
        ratio = (inter_lng * inter_lat) / expected_area
        if ratio < 0.65:
            return "COVERAGE_INCOMPLETE"
        return "READY"

    def _normalize_workspace_step(self, step: str) -> str:
        value = (step or "").strip().upper().replace("-", "_")
        aliases = {
            "WATER_MATCH": "WATER",
            "WATER_PLANNING": "WATER",
            "BOUNDARIES": "BOUNDARY",
            "CENTERLINES": "CENTERLINE",
            "GRAPH": "GRAPH",
            "ROUTE": "ROUTE",
        }
        value = aliases.get(value, value)
        return value if value in {"WATER", "BOUNDARY", "CENTERLINE", "GRAPH", "ROUTE"} else "BOUNDARY"

    def _workspace_step_name(self, step_code: str) -> str:
        return {
            "WATER": "航道水系规划",
            "BOUNDARY": "边界生成",
            "CENTERLINE": "中心线生成",
            "GRAPH": "图网络构建",
            "ROUTE": "路径验证",
        }.get(step_code, "边界生成")

    def _layer_legends(self, step_code: str) -> list[NavigationProductionLayerLegendResponse]:
        by_step = {
            "WATER": [
                ("raw_water_boundary", "原始水系边界", "用于确认该航道应归属哪些真实水体"),
                ("planning_reference", "规划航道参考范围", "来自 seed 的航道包络，仅作定位参考"),
            ],
            "BOUNDARY": [
                ("matched_water_boundary", "已归属水体边界", "已确认归属水体的真实水面"),
                ("planning_reference", "规划航道参考范围", "seed 参考范围，不等于最终边界"),
                ("candidate_boundary", "系统候选边界", "由归属水体生成，需人工修正"),
                ("manual_boundary", "人工修正边界", "制图人员正在修正的边界"),
                ("final_boundary", "最终确认边界", "当前发布边界"),
            ],
            "CENTERLINE": [
                ("raw_water_boundary", "原始水系边界", "中心线不得明显离开水体"),
                ("final_boundary", "最终确认边界", "中心线生产约束范围"),
                ("candidate_centerline", "候选中心线", "真实候选线，需人工修正发布"),
                ("published_centerline", "已发布中心线", "可进入图网络构建"),
            ],
            "GRAPH": [
                ("published_centerline", "已发布中心线", "图边来源"),
                ("route_graph", "路径图边", "路径搜索唯一对象"),
            ],
            "ROUTE": [
                ("route_graph", "路径图边", "路径搜索唯一对象"),
                ("route_result", "验证路径", "本次路径验证结果"),
            ],
        }
        return [
            NavigationProductionLayerLegendResponse(layer_code=code, layer_name=name, layer_role=role)
            for code, name, role in by_step.get(step_code, by_step["BOUNDARY"])
        ]

    def _candidate_boundary_geometry(self, bodies: list[NavigationWaterBody]) -> dict[str, Any] | None:
        polygons: list[Any] = []
        for body in bodies:
            geometry = body.geometry_wgs84_json
            if not isinstance(geometry, dict):
                continue
            geometry_type = str(geometry.get("type") or "")
            coordinates = geometry.get("coordinates")
            if geometry_type == "Polygon" and isinstance(coordinates, list):
                polygons.append(coordinates)
            elif geometry_type == "MultiPolygon" and isinstance(coordinates, list):
                polygons.extend([item for item in coordinates if isinstance(item, list)])
        valid_polygons = [
            polygon
            for polygon in polygons
            if isinstance(polygon, list) and polygon and isinstance(polygon[0], list) and len(polygon[0]) >= 4
        ]
        if not valid_polygons:
            return None
        return {"type": "MultiPolygon", "coordinates": valid_polygons}

    async def _channels(self) -> list[NavigationChannel]:
        return list(
            (
                await self.session.execute(
                    select(NavigationChannel)
                    .where(NavigationChannel.is_enabled.is_(True))
                    .order_by(NavigationChannel.sort_order, NavigationChannel.id)
                )
            ).scalars()
        )

    async def _production_channels(self, channels: list[NavigationChannel]) -> list[NavigationProductionChannelResponse]:
        channel_ids = [row.id for row in channels]
        published_boundary_counts = await self.workbench._counts_by_channel(
            NavigationChannelBoundary.channel_id,
            select(NavigationChannelBoundary.channel_id, func.count()).where(
                NavigationChannelBoundary.channel_id.in_(channel_ids),
                NavigationChannelBoundary.is_current.is_(True),
                NavigationChannelBoundary.geometry_status_code == "AVAILABLE",
                or_(
                    NavigationChannelBoundary.coverage_policy_code.in_(PUBLISHED_BOUNDARY_POLICIES),
                    NavigationChannelBoundary.boundary_quality_code == "MANUAL_PUBLISHED",
                ),
            ),
        )
        candidate_boundary_counts = await self.workbench._counts_by_channel(
            NavigationChannelBoundary.channel_id,
            select(NavigationChannelBoundary.channel_id, func.count()).where(
                NavigationChannelBoundary.channel_id.in_(channel_ids),
                NavigationChannelBoundary.is_current.is_(False),
                NavigationChannelBoundary.coverage_policy_code.in_(BOUNDARY_CANDIDATE_POLICIES),
                NavigationChannelBoundary.geometry_status_code == "AVAILABLE",
            ),
        )
        centerline_candidate_counts = await self.workbench._counts_by_channel(
            NavigationChannelCenterline.channel_id,
            select(NavigationChannelCenterline.channel_id, func.count()).where(
                NavigationChannelCenterline.channel_id.in_(channel_ids),
                NavigationChannelCenterline.review_status_code != "PUBLISHED",
            ),
        )
        published_centerline_counts = await self.workbench._counts_by_channel(
            NavigationChannelCenterline.channel_id,
            select(NavigationChannelCenterline.channel_id, func.count()).where(
                NavigationChannelCenterline.channel_id.in_(channel_ids),
                NavigationChannelCenterline.is_current.is_(True),
                NavigationChannelCenterline.review_status_code == "PUBLISHED",
                NavigationChannelCenterline.quality_code.in_({"READY", "READY_WITH_WARNING"}),
            ),
        )
        current_match_counts = await self.workbench._counts_by_channel(
            NavigationChannelWaterBodyMatch.channel_id,
            select(NavigationChannelWaterBodyMatch.channel_id, func.count()).where(
                NavigationChannelWaterBodyMatch.channel_id.in_(channel_ids),
                NavigationChannelWaterBodyMatch.is_current.is_(True),
            ),
        )
        active_graph_version = await self._active_graph_version()
        active_edge_counts = await self.workbench._active_graph_edge_counts(channel_ids)
        route_verified_by_channel = await self._route_verified_by_channel(channel_ids)

        rows: list[NavigationProductionChannelResponse] = []
        for channel in channels:
            counts = {
                "match": current_match_counts.get(channel.id, 0),
                "candidate_boundary": candidate_boundary_counts.get(channel.id, 0),
                "boundary": published_boundary_counts.get(channel.id, 0),
                "centerline_candidate": centerline_candidate_counts.get(channel.id, 0),
                "centerline": published_centerline_counts.get(channel.id, 0),
                "edge": active_edge_counts.get(channel.id, 0),
                "route": route_verified_by_channel.get(channel.id, 0),
            }
            stage, blockers = self._stage(counts)
            next_label, next_path = NEXT_ACTIONS[stage]
            steps = self._steps(counts)
            actions = self._available_actions(channel.id, counts, stage)
            diagnostic_issues = self._cheap_diagnostic_issues(counts, blockers)
            rows.append(
                NavigationProductionChannelResponse(
                    id=channel.id,
                    channel_code=channel.channel_code,
                    channel_name=channel.channel_name,
                    display_name=channel.display_name,
                    planning_level_code=channel.planning_level_code,
                    channel_type_code=channel.channel_type_code,
                    production_stage_code=stage,
                    production_stage_name=STAGE_LABELS[stage],
                    next_action_label=next_label,
                    next_path=f"{next_path}?channel_id={channel.id}",
                    blocker_codes=blockers,
                    current_water_body_match_count=counts["match"],
                    candidate_boundary_count=counts["candidate_boundary"],
                    current_boundary_count=counts["boundary"],
                    centerline_candidate_count=counts["centerline_candidate"],
                    published_current_centerline_count=counts["centerline"],
                    active_graph_edge_count=counts["edge"],
                    route_verified_count=counts["route"],
                    diagnostic_issue_codes=diagnostic_issues,
                    water_body_candidate_count=0,
                    seed_boundary_overlap_ratio=None,
                    steps=steps,
                    available_actions=actions,
                )
            )
        return rows

    async def _active_graph_version(self) -> NavigationGraphVersion | None:
        return (
            await self.session.execute(
                select(NavigationGraphVersion)
                .where(
                    NavigationGraphVersion.is_active.is_(True),
                    NavigationGraphVersion.status_code == "READY",
                    NavigationGraphVersion.scope_code.not_like("MVP%"),
                    NavigationGraphVersion.edge_count > 0,
                )
                .order_by(NavigationGraphVersion.id.desc())
            )
        ).scalars().first()

    def _stage(self, counts: dict[str, int]) -> tuple[str, list[str]]:
        if counts["match"] <= 0:
            return "NO_WATER_MATCH", ["NO_WATER_BODY_MATCH"]
        if counts["boundary"] <= 0:
            if counts["candidate_boundary"] > 0:
                return "BOUNDARY_CANDIDATE", ["BOUNDARY_CANDIDATE_TO_PUBLISH"]
            return "WATER_MATCH_READY", ["NO_PUBLISHED_BOUNDARY"]
        if counts["centerline"] > 0 and counts["edge"] > 0 and counts["route"] > 0:
            return "ROUTE_VERIFIED", []
        if counts["centerline"] > 0 and counts["edge"] > 0:
            return "GRAPH_READY", []
        if counts["centerline"] > 0:
            return "CENTERLINE_PUBLISHED", []
        if counts["centerline_candidate"] > 0:
            return "CENTERLINE_CANDIDATE", ["CENTERLINE_CANDIDATE_TO_PUBLISH"]
        return "BOUNDARY_PUBLISHED", ["NO_PUBLISHED_CENTERLINE"]

    def _steps(self, counts: dict[str, int]) -> list[NavigationProductionStepResponse]:
        return [
            NavigationProductionStepResponse(
                step_code="WATER_MATCH",
                step_name=STEP_NAMES["WATER_MATCH"],
                status_code="READY" if counts["match"] else "BLOCKED",
                count=counts["match"],
                blocker_code=None if counts["match"] else "NO_WATER_BODY_MATCH",
                next_path="/navigation/production/water-matches",
            ),
            NavigationProductionStepResponse(
                step_code="BOUNDARY",
                step_name=STEP_NAMES["BOUNDARY"],
                status_code="READY" if counts["boundary"] else ("NEED_REVIEW" if counts["candidate_boundary"] else "BLOCKED"),
                count=counts["boundary"] or counts["candidate_boundary"],
                blocker_code=None
                if counts["boundary"]
                else ("BOUNDARY_CANDIDATE_TO_PUBLISH" if counts["candidate_boundary"] else "NO_PUBLISHED_BOUNDARY"),
                next_path="/navigation/production/boundaries",
            ),
            NavigationProductionStepResponse(
                step_code="CENTERLINE",
                step_name=STEP_NAMES["CENTERLINE"],
                status_code="READY" if counts["centerline"] else ("NEED_REVIEW" if counts["centerline_candidate"] else "BLOCKED"),
                count=counts["centerline"] or counts["centerline_candidate"],
                blocker_code=None if counts["centerline"] else ("CENTERLINE_CANDIDATE_TO_PUBLISH" if counts["centerline_candidate"] else "NO_PUBLISHED_CENTERLINE"),
                next_path="/navigation/production/centerlines",
            ),
            NavigationProductionStepResponse(
                step_code="GRAPH",
                step_name=STEP_NAMES["GRAPH"],
                status_code="READY" if counts["edge"] else "BLOCKED",
                count=counts["edge"],
                blocker_code=None if counts["edge"] else "NO_GRAPH_EDGE",
                next_path="/navigation/production/graphs",
            ),
            NavigationProductionStepResponse(
                step_code="ROUTE",
                step_name=STEP_NAMES["ROUTE"],
                status_code="READY" if counts["route"] else "PENDING",
                count=counts["route"],
                next_path="/navigation/routes",
            ),
        ]

    def _available_actions(self, channel_id: int, counts: dict[str, int], stage: str) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = [
            {
                "action_code": "OPEN_WATER_MATCH",
                "label": "进入水系归属",
                "path": f"/navigation/production/water-matches?channel_id={channel_id}",
                "enabled": True,
            },
            {
                "action_code": "OPEN_BOUNDARY",
                "label": "生产边界",
                "path": f"/navigation/production/boundaries?channel_id={channel_id}",
                "enabled": counts["match"] > 0,
                "disabled_reason": None if counts["match"] > 0 else "NO_WATER_BODY_MATCH",
            },
            {
                "action_code": "OPEN_CENTERLINE",
                "label": "生产中心线",
                "path": f"/navigation/production/centerlines?channel_id={channel_id}",
                "enabled": counts["boundary"] > 0,
                "disabled_reason": None if counts["boundary"] > 0 else "NO_PUBLISHED_BOUNDARY",
            },
            {
                "action_code": "BUILD_GRAPH",
                "label": "构建图网络",
                "path": f"/navigation/production/graphs?channel_id={channel_id}",
                "enabled": counts["centerline"] > 0,
                "disabled_reason": None if counts["centerline"] > 0 else "NO_PUBLISHED_CENTERLINE",
            },
            {
                "action_code": "VERIFY_ROUTE",
                "label": "验证路径",
                "path": f"/navigation/routes?channel_id={channel_id}",
                "enabled": counts["edge"] > 0,
                "disabled_reason": None if counts["edge"] > 0 else "NO_ACTIVE_GRAPH_EDGE",
            },
        ]
        if stage == "BLOCKED":
            actions.append(
                {
                    "action_code": "OPEN_ANNOTATION",
                    "label": "处理标注任务",
                    "path": f"/navigation/production/annotations?channel_id={channel_id}",
                    "enabled": True,
                }
            )
        return actions

    def _warnings_for(self, row: NavigationProductionChannelResponse) -> list[str]:
        warnings: list[str] = []
        if row.current_water_body_match_count <= 0:
            warnings.append("该航道还没有真实规范水体归属，地图不会展示无关水域。")
        if row.candidate_boundary_count > 0 and row.current_boundary_count <= 0:
            warnings.append("候选边界来自真实水系归属，只能载入草稿编辑后发布。")
        if row.candidate_boundary_count > 0 and row.current_boundary_count > 0:
            warnings.append("存在可替换候选边界，但当前已发布边界不受它阻塞。")
        if row.published_current_centerline_count <= 0:
            warnings.append("无已发布中心线，图网络构建和路径生成必须失败。")
        return warnings

    def _cheap_diagnostic_issues(self, counts: dict[str, int], blockers: list[str]) -> list[str]:
        issues = set(blockers)
        if counts["match"] <= 0:
            issues.add("NO_WATER_BODY_MATCH")
        if counts["centerline"] <= 0:
            issues.add("CENTERLINE_MISSING")
        if counts["edge"] <= 0:
            issues.add("GRAPH_BLOCKED")
        return sorted(issues)

    async def _route_verified_by_channel(self, channel_ids: list[int]) -> dict[int, int]:
        if not channel_ids:
            return {}
        rows = list(
            (
                await self.session.execute(
                    select(NavigationRouteResult.channel_ids).where(
                        NavigationRouteResult.status_code == "SUCCESS",
                        NavigationRouteResult.edge_ids.is_not(None),
                    )
                )
            ).scalars()
        )
        counts: dict[int, int] = {}
        allowed = set(channel_ids)
        for result_channel_ids in rows:
            if not isinstance(result_channel_ids, list):
                continue
            for channel_id in result_channel_ids:
                try:
                    key = int(channel_id)
                except (TypeError, ValueError):
                    continue
                if key in allowed:
                    counts[key] = counts.get(key, 0) + 1
        return counts
