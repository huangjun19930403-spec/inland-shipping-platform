from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from shapely.geometry import LineString, mapping, shape
from shapely.validation import make_valid

from app.core.exceptions import NotFoundError, ValidationError
from app.models import (
    NavigationAnnotationTask,
    NavigationChannelCenterline,
    NavigationChannelBoundary,
    NavigationGraphEdge,
    NavigationGraphVersion,
    NavigationRouteQualityIssue,
    NavigationRouteRequest,
    NavigationRouteResult,
)
from app.modules.navigation.schemas import (
    NavigationAnnotationSuggestionResponse,
    NavigationAnnotationTaskBatchCreateResponse,
    NavigationAnnotationTaskListResponse,
    NavigationAnnotationTaskResolveRequest,
    NavigationAnnotationTaskResponse,
)
from app.modules.navigation.services.graph_diagnostics_service import repair_graph_edge_constraint


OPEN_TASK_STATUSES = {"OPEN", "IN_PROGRESS", "NEED_REVIEW"}
ROUTE_REPAIR_TASK_ISSUE_CODES = {
    "UNKNOWN_CONSTRAINT_DATA",
    "PATH_OUT_OF_WATER",
    "PATH_WATER_COVERAGE_WARNING",
    "PATH_OUT_OF_CHANNEL_BOUNDARY",
    "PATH_CHANNEL_BOUNDARY_WARNING",
    "ROUTE_STRAIGHT_LINE_FALLBACK",
    "ROUTE_LONG_STRAIGHT_SEGMENT_REVIEW",
    "ROUTE_FOLDBACK_REVIEW",
    "ROUTE_SELF_INTERSECTION_REVIEW",
    "GRAPH_DISCONNECTED",
    "NO_ACTIVE_GRAPH_VERSION",
    "NO_ROUTING_EDGE_IN_BBOX",
    "NO_ROUTING_EDGE_IN_EXPANDED_BBOX",
    "NO_PATH_FOUND",
    "ORIGIN_TOO_FAR_FROM_GRAPH",
    "DESTINATION_TOO_FAR_FROM_GRAPH",
    "CHANNEL_BOUNDARY_SOURCE_NOT_VERIFIED",
    "CHANNEL_BOUNDARY_TRUST_NEEDS_REVIEW",
    "CHANNEL_BOUNDARY_SOURCE_FRAGMENTED",
    "CHANNEL_BOUNDARY_BASEMAP_NOT_VERIFIED",
    "CENTERLINE_SEED_FALLBACK_ROUTE",
}
RESOLUTION_TARGET_REQUIRED_TYPES = {
    "BOUNDARY_VERSION_CREATED",
    "CENTERLINE_VERSION_CREATED",
    "CONSTRAINT_CREATED",
    "GRAPH_VERSION_REBUILT",
}


class NavigationAnnotationTaskService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_tasks(
        self,
        *,
        status_code: str | None = None,
        task_type_code: str | None = None,
        target_type_code: str | None = None,
        channel_id: int | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> NavigationAnnotationTaskListResponse:
        page = max(1, int(page or 1))
        page_size = max(1, min(int(page_size or 20), 100))
        stmt = select(NavigationAnnotationTask)
        if status_code:
            stmt = stmt.where(NavigationAnnotationTask.status_code == status_code.upper())
        if task_type_code:
            stmt = stmt.where(NavigationAnnotationTask.task_type_code == task_type_code.upper())
        if target_type_code:
            stmt = stmt.where(NavigationAnnotationTask.target_type_code == target_type_code.upper())
        if channel_id:
            stmt = stmt.where(NavigationAnnotationTask.channel_id == channel_id)
        total = int((await self.session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one() or 0)
        rows = list(
            (
                await self.session.execute(
                    stmt.order_by(NavigationAnnotationTask.created_at.desc(), NavigationAnnotationTask.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).scalars()
        )
        return NavigationAnnotationTaskListResponse(
            items=[self._to_response(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_task(self, task_id: int) -> NavigationAnnotationTaskResponse:
        return self._to_response(await self._task(task_id))

    async def create_from_route_result(
        self,
        route_result_id: int,
        *,
        created_by: int | None = None,
    ) -> NavigationAnnotationTaskBatchCreateResponse:
        result = await self.session.get(NavigationRouteResult, route_result_id)
        if result is None:
            raise NotFoundError("NavigationRouteResult", route_result_id)
        request = await self.session.get(NavigationRouteRequest, result.request_id)
        issues = list(
            (
                await self.session.execute(
                    select(NavigationRouteQualityIssue)
                    .where(NavigationRouteQualityIssue.route_result_id == route_result_id)
                    .order_by(NavigationRouteQualityIssue.id)
                )
            ).scalars()
        )
        task_ids: list[int] = []
        created_count = 0
        existing_count = 0
        for issue in issues:
            if not self._should_create_route_issue_task(issue.issue_type_code):
                continue
            channel_id = await self._channel_id_for_route_issue(result, issue)
            task_type = self._task_type_for_issue(issue.issue_type_code)
            task_geometry_json = self._route_issue_task_geometry(result=result, request=request, issue=issue)
            dedupe_key = self._route_issue_task_dedupe_key(
                result=result,
                request=request,
                issue=issue,
                task_type_code=task_type,
                channel_id=channel_id,
                geometry_json=task_geometry_json,
            )
            suggestion = self._route_issue_suggestion(
                result=result,
                issue=issue,
                task_type_code=task_type,
                fallback_geometry_json=task_geometry_json,
            )
            task, created = await self._get_or_create_task(
                task_type_code=task_type,
                target_type_code="ROUTE_QUALITY_ISSUE",
                target_id=issue.id,
                issue_code=issue.issue_type_code,
                issue_summary=issue.message,
                priority_code=self._priority_for_issue(issue.issue_type_code, issue.severity_code),
                geometry_json=task_geometry_json,
                channel_id=channel_id,
                graph_version_id=request.graph_version_id if request else None,
                created_by=created_by,
                dedupe_key=dedupe_key,
            )
            if suggestion:
                task.suggestion_json = {
                    **(task.suggestion_json or {}),
                    **suggestion,
                }
            issue.related_annotation_task_id = task.id
            task_ids.append(task.id)
            created_count += 1 if created else 0
            existing_count += 0 if created else 1
        await self.session.commit()
        return NavigationAnnotationTaskBatchCreateResponse(
            created_count=created_count,
            existing_count=existing_count,
            task_ids=task_ids,
            source_type_code="ROUTE_QUALITY_ISSUE",
        )

    async def create_from_graph_version(
        self,
        graph_version_id: int,
        *,
        created_by: int | None = None,
    ) -> NavigationAnnotationTaskBatchCreateResponse:
        graph_version = await self.session.get(NavigationGraphVersion, graph_version_id)
        if graph_version is None:
            raise NotFoundError("NavigationGraphVersion", graph_version_id)
        task_ids: list[int] = []
        created_count = 0
        existing_count = 0

        candidates = self._validation_candidates(graph_version.validation_report_json)
        for candidate in candidates:
            task, created = await self._get_or_create_task(
                task_type_code=self._normalize_task_type(str(candidate.get("task_type_code") or "GRAPH_QUALITY_REPAIR")),
                target_type_code=str(candidate.get("target_type_code") or "GRAPH_VERSION").upper(),
                target_id=self._int_or_none(candidate.get("target_id")),
                issue_code=str(candidate.get("issue_code") or "GRAPH_QUALITY_ISSUE").upper(),
                issue_summary=str(candidate.get("issue_summary") or "图网络质量问题需要处理"),
                priority_code=str(candidate.get("priority_code") or "MEDIUM").upper(),
                graph_version_id=graph_version.id,
                created_by=created_by,
            )
            task_ids.append(task.id)
            created_count += 1 if created else 0
            existing_count += 0 if created else 1

        edge_rows = list(
            (
                await self.session.execute(
                    select(NavigationGraphEdge)
                    .where(
                        NavigationGraphEdge.graph_version_id == graph_version.id,
                        (
                            NavigationGraphEdge.quality_code.in_(
                                {"NEED_REVIEW", "LOW_CONFIDENCE", "SHORT_EDGE_REVIEW", "READY_WITH_WARNING"}
                            )
                        )
                        | (NavigationGraphEdge.unknown_constraint_flag.is_(True))
                        | (NavigationGraphEdge.routing_enabled.is_(False)),
                    )
                    .order_by(NavigationGraphEdge.id)
                )
            ).scalars()
        )
        for edge in edge_rows:
            issue_code = "UNKNOWN_CONSTRAINT_DATA" if edge.unknown_constraint_flag else edge.quality_code
            task_type = "CONSTRAINT_DATA_REPAIR" if edge.unknown_constraint_flag else "GRAPH_EDGE_REPAIR"
            task, created = await self._get_or_create_task(
                task_type_code=task_type,
                target_type_code="GRAPH_EDGE",
                target_id=edge.id,
                issue_code=issue_code,
                issue_summary=f"路径图边 {edge.edge_code} 需要处理：{issue_code}",
                priority_code="MEDIUM" if edge.routing_enabled else "HIGH",
                geometry_json=edge.geometry_json,
                channel_id=edge.channel_id,
                graph_version_id=graph_version.id,
                created_by=created_by,
            )
            task_ids.append(task.id)
            created_count += 1 if created else 0
            existing_count += 0 if created else 1

        await self.session.commit()
        return NavigationAnnotationTaskBatchCreateResponse(
            created_count=created_count,
            existing_count=existing_count,
            task_ids=self._dedupe_ids(task_ids),
            source_type_code="GRAPH_VALIDATION",
        )

    async def create_from_centerline_quality(
        self,
        *,
        created_by: int | None = None,
    ) -> NavigationAnnotationTaskBatchCreateResponse:
        rows = list(
            (
                await self.session.execute(
                    select(NavigationChannelCenterline)
                    .where(
                        NavigationChannelCenterline.is_current.is_(True),
                        (
                            NavigationChannelCenterline.quality_code.in_(
                                {"NEED_REVIEW", "LOW_CONFIDENCE", "BROKEN", "OUT_OF_BOUNDARY", "DUPLICATED"}
                            )
                        )
                        | (NavigationChannelCenterline.review_status_code != "PUBLISHED"),
                    )
                    .order_by(NavigationChannelCenterline.id)
                )
            ).scalars()
        )
        task_ids: list[int] = []
        created_count = 0
        existing_count = 0
        for centerline in rows:
            task, created = await self._get_or_create_task(
                task_type_code="CENTERLINE_REPAIR",
                target_type_code="CENTERLINE",
                target_id=centerline.id,
                issue_code=centerline.quality_code,
                issue_summary=(
                    f"Centerline {centerline.centerline_code} needs production repair: "
                    f"{centerline.quality_code}/{centerline.review_status_code}"
                ),
                priority_code="HIGH" if centerline.quality_code in {"BROKEN", "OUT_OF_BOUNDARY"} else "MEDIUM",
                geometry_json=centerline.geometry_json,
                channel_id=centerline.channel_id,
                created_by=created_by,
            )
            task_ids.append(task.id)
            created_count += 1 if created else 0
            existing_count += 0 if created else 1
        await self.session.commit()
        return NavigationAnnotationTaskBatchCreateResponse(
            created_count=created_count,
            existing_count=existing_count,
            task_ids=task_ids,
            source_type_code="CENTERLINE_QUALITY",
        )

    async def create_from_boundary_integrity(
        self,
        *,
        channel_id: int | None = None,
        created_by: int | None = None,
    ) -> NavigationAnnotationTaskBatchCreateResponse:
        stmt = select(NavigationChannelBoundary).where(NavigationChannelBoundary.is_current.is_(True))
        if channel_id is not None:
            stmt = stmt.where(NavigationChannelBoundary.channel_id == channel_id)
        rows = list(
            (
                await self.session.execute(
                    stmt.order_by(NavigationChannelBoundary.channel_id, NavigationChannelBoundary.id)
                )
            ).scalars()
        )

        task_ids: list[int] = []
        created_count = 0
        existing_count = 0
        for boundary in rows:
            audit = self._boundary_integrity_audit(boundary.source_trace_json)
            if not self._boundary_needs_integrity_task(boundary, audit):
                continue
            issue_codes = [str(item).upper() for item in (audit.get("issue_codes") or []) if item]
            trust_code = str(audit.get("trust_code") or "SOURCE_NOT_VERIFIED").upper()
            primary_issue = self._primary_boundary_integrity_issue(trust_code, issue_codes)
            task, created = await self._get_or_create_task(
                task_type_code="SEED_BOUNDARY_REPAIR",
                target_type_code="CHANNEL_BOUNDARY",
                target_id=boundary.id,
                issue_code=primary_issue,
                issue_summary=self._boundary_integrity_summary(boundary, trust_code, issue_codes),
                priority_code=self._boundary_integrity_priority(trust_code, issue_codes),
                geometry_json=boundary.geometry_json,
                channel_id=boundary.channel_id,
                created_by=created_by,
                dedupe_key=f"BOUNDARY_INTEGRITY_V1|boundary={boundary.id}",
            )
            task.suggestion_json = {
                **(task.suggestion_json or {}),
                "repair_strategy_code": "REAL_WATERWAY_BOUNDARY_REPAIR",
                "candidate_operation_code": "REBUILD_OR_EXPAND_CHANNEL_BOUNDARY",
                "boundary_id": boundary.id,
                "channel_id": boundary.channel_id,
                "trust_code": trust_code,
                "issue_codes": issue_codes,
                "boundary_quality_code": boundary.boundary_quality_code,
                "repair_status_code": boundary.repair_status_code,
                "boundary_integrity_audit": audit,
                "publish_allowed": False,
                "requires_operator_confirmation": True,
                "guardrails": [
                    "不能把碎片水系 union 结果直接视为可用航道边界",
                    "边界必须包住真实水道、当前中心线和抽样轨迹后才能升为 READY",
                    "技术等级缺失时不能承诺可通行船型或吨级",
                ],
                "next_actions": [
                    "打开边界生成页，用底图、原始水系、HiFleet 轨迹和已发布中心线逐段核对",
                    "对缺口或过窄段创建边界草稿并扩大/补齐真实水道范围",
                    "发布边界后重建中心线和 Graph，再重新跑路径矩阵",
                ],
            }
            task_ids.append(task.id)
            created_count += 1 if created else 0
            existing_count += 0 if created else 1

        await self.session.commit()
        return NavigationAnnotationTaskBatchCreateResponse(
            created_count=created_count,
            existing_count=existing_count,
            task_ids=self._dedupe_ids(task_ids),
            source_type_code="BOUNDARY_INTEGRITY",
        )

    async def generate_suggestion(self, task_id: int) -> NavigationAnnotationSuggestionResponse:
        task = await self._task(task_id)
        suggestion = self._suggestion_for_task(task)
        task.suggestion_json = suggestion
        await self.session.commit()
        return NavigationAnnotationSuggestionResponse(task_id=task.id, suggestion_json=suggestion)

    async def resolve_task(
        self,
        task_id: int,
        body: NavigationAnnotationTaskResolveRequest,
        *,
        reviewed_by: int | None = None,
    ) -> NavigationAnnotationTaskResponse:
        task = await self._task(task_id)
        resolution_type = body.resolution_type_code.upper()
        target_type = body.resolution_target_type_code.upper() if body.resolution_target_type_code else None
        if resolution_type in RESOLUTION_TARGET_REQUIRED_TYPES and (not target_type or body.resolution_target_id is None):
            raise ValidationError("resolution target is required for version-producing resolutions")
        repaired_edge = None
        if body.constraint_repair is not None:
            repaired_edge = await self._repair_constraint_task(
                task,
                body,
                reviewed_by=reviewed_by,
            )
            resolution_type = "CONSTRAINT_CREATED"
            target_type = "GRAPH_EDGE"
        task.status_code = body.status_code.upper()
        task.resolution_type_code = resolution_type
        task.resolution_target_type_code = target_type
        task.resolution_target_id = body.resolution_target_id or (repaired_edge.id if repaired_edge else None)
        task.reviewed_by = reviewed_by
        task.reviewed_at = datetime.now(UTC).replace(tzinfo=None)
        task.resolved_at = task.reviewed_at if task.status_code in {"RESOLVED", "CLOSED"} else None
        resolution_payload: dict[str, Any] = {}
        if body.suggestion_json:
            resolution_payload.update(body.suggestion_json)
        if body.source_evidence_json:
            resolution_payload["source_evidence_json"] = body.source_evidence_json
        if repaired_edge is not None:
            resolution_payload["constraint_repair_result"] = {
                "edge_id": repaired_edge.id,
                "edge_code": repaired_edge.edge_code,
                "unknown_constraint_flag": repaired_edge.unknown_constraint_flag,
                "constraint_count": repaired_edge.constraint_count,
                "issue_codes": repaired_edge.issue_codes,
            }
        if resolution_payload:
            task.suggestion_json = {**(task.suggestion_json or {}), "manual_resolution": resolution_payload}
        await self.session.commit()
        await self.session.refresh(task)
        return self._to_response(task)

    async def _repair_constraint_task(
        self,
        task: NavigationAnnotationTask,
        body: NavigationAnnotationTaskResolveRequest,
        *,
        reviewed_by: int | None,
    ):
        if task.task_type_code != "CONSTRAINT_DATA_REPAIR" or task.target_type_code != "GRAPH_EDGE" or task.target_id is None:
            raise ValidationError(
                "只有 GRAPH_EDGE 类型的约束数据补齐任务可以直接写入图边约束",
                code="ANNOTATION_CONSTRAINT_REPAIR_TARGET_INVALID",
                detail={
                    "error_code": "ANNOTATION_CONSTRAINT_REPAIR_TARGET_INVALID",
                    "message": "只有 GRAPH_EDGE 类型的约束数据补齐任务可以直接写入图边约束",
                },
            )
        repair_body = body.constraint_repair
        if repair_body is None:
            raise ValidationError("constraint_repair is required")
        source_evidence = dict(repair_body.source_evidence_json or {})
        if body.source_evidence_json:
            source_evidence.update(body.source_evidence_json)
        source_evidence.update(
            {
                "annotation_task_id": int(task.id),
                "annotation_task_no": task.task_no,
                "issue_summary": task.issue_summary,
            }
        )
        repair_body = repair_body.model_copy(update={"source_evidence_json": source_evidence})
        return await repair_graph_edge_constraint(
            self.session,
            edge_id=int(task.target_id),
            body=repair_body,
            repaired_by=reviewed_by,
            include_geometry=True,
            commit=False,
        )

    async def _get_or_create_task(
        self,
        *,
        task_type_code: str,
        target_type_code: str,
        target_id: int | None,
        issue_code: str,
        issue_summary: str,
        priority_code: str,
        geometry_json: dict[str, Any] | None = None,
        channel_id: int | None = None,
        graph_version_id: int | None = None,
        created_by: int | None = None,
        dedupe_key: str | None = None,
    ) -> tuple[NavigationAnnotationTask, bool]:
        existing = await self.session.scalar(
            select(NavigationAnnotationTask)
            .where(
                NavigationAnnotationTask.task_type_code == task_type_code,
                NavigationAnnotationTask.target_type_code == target_type_code,
                NavigationAnnotationTask.target_id == target_id,
                NavigationAnnotationTask.status_code.in_(OPEN_TASK_STATUSES),
            )
            .order_by(NavigationAnnotationTask.id.desc())
            .limit(1)
        )
        if existing is not None:
            return existing, False
        existing = await self._find_open_task_by_dedupe_key(
            task_type_code=task_type_code,
            target_type_code=target_type_code,
            issue_code=issue_code,
            geometry_json=geometry_json,
            channel_id=channel_id,
            graph_version_id=graph_version_id,
            dedupe_key=dedupe_key,
        )
        if existing is not None:
            return existing, False
        suggestion_json = self._base_suggestion(issue_code=issue_code, task_type_code=task_type_code)
        if dedupe_key:
            suggestion_json["dedupe_key"] = dedupe_key
        task = NavigationAnnotationTask(
            task_no=self._task_no(),
            task_type_code=task_type_code,
            target_type_code=target_type_code,
            target_id=target_id,
            channel_id=channel_id,
            graph_version_id=graph_version_id,
            geometry_json=geometry_json,
            priority_code=priority_code,
            status_code="OPEN",
            issue_summary=issue_summary[:2000],
            suggestion_json=suggestion_json,
            created_by=created_by,
        )
        self.session.add(task)
        await self.session.flush()
        return task, True

    async def _find_open_task_by_dedupe_key(
        self,
        *,
        task_type_code: str,
        target_type_code: str,
        issue_code: str,
        geometry_json: dict[str, Any] | None,
        channel_id: int | None,
        graph_version_id: int | None,
        dedupe_key: str | None,
    ) -> NavigationAnnotationTask | None:
        if not dedupe_key:
            return None
        stmt = (
            select(NavigationAnnotationTask)
            .where(
                NavigationAnnotationTask.task_type_code == task_type_code,
                NavigationAnnotationTask.target_type_code == target_type_code,
                NavigationAnnotationTask.status_code.in_(OPEN_TASK_STATUSES),
            )
            .order_by(NavigationAnnotationTask.id.desc())
            .limit(200)
        )
        if channel_id is not None:
            stmt = stmt.where(NavigationAnnotationTask.channel_id == channel_id)
        if graph_version_id is not None:
            stmt = stmt.where(NavigationAnnotationTask.graph_version_id == graph_version_id)
        geometry_hash = self._geometry_fingerprint(geometry_json)
        issue_code = issue_code.upper()
        rows = list((await self.session.execute(stmt)).scalars())
        for row in rows:
            suggestion = row.suggestion_json if isinstance(row.suggestion_json, dict) else {}
            if suggestion.get("dedupe_key") == dedupe_key:
                return row
            if str(suggestion.get("issue_code") or "").upper() != issue_code:
                continue
            if geometry_hash and self._geometry_fingerprint(row.geometry_json) == geometry_hash:
                return row
            if self._legacy_endpoint_dedupe_key_matches(suggestion.get("dedupe_key"), issue_code, geometry_json):
                if row.geometry_json is None:
                    row.geometry_json = geometry_json
                row.suggestion_json = {**suggestion, "dedupe_key": dedupe_key}
                return row
        return None

    async def _task(self, task_id: int) -> NavigationAnnotationTask:
        task = await self.session.get(NavigationAnnotationTask, task_id)
        if task is None:
            raise NotFoundError("NavigationAnnotationTask", task_id)
        return task

    async def _channel_id_for_edge(self, edge_id: int | None) -> int | None:
        if edge_id is None:
            return None
        edge = await self.session.get(NavigationGraphEdge, edge_id)
        return edge.channel_id if edge else None

    async def _channel_id_for_route_issue(
        self,
        result: NavigationRouteResult,
        issue: NavigationRouteQualityIssue,
    ) -> int | None:
        channel_id = await self._channel_id_for_edge(issue.related_edge_id)
        if channel_id is not None:
            return channel_id
        channel_ids = [int(item) for item in (result.channel_ids or []) if item is not None]
        if issue.issue_type_code in {
            "PATH_OUT_OF_WATER",
            "PATH_WATER_COVERAGE_WARNING",
            "PATH_OUT_OF_CHANNEL_BOUNDARY",
            "PATH_CHANNEL_BOUNDARY_WARNING",
            "CHANNEL_BOUNDARY_SOURCE_NOT_VERIFIED",
            "CHANNEL_BOUNDARY_TRUST_NEEDS_REVIEW",
            "CHANNEL_BOUNDARY_SOURCE_FRAGMENTED",
            "CHANNEL_BOUNDARY_BASEMAP_NOT_VERIFIED",
        } and channel_ids:
            return channel_ids[0]
        return None

    def _to_response(self, row: NavigationAnnotationTask) -> NavigationAnnotationTaskResponse:
        return NavigationAnnotationTaskResponse(
            id=row.id,
            task_no=row.task_no,
            task_type_code=row.task_type_code,
            target_type_code=row.target_type_code,
            target_id=row.target_id,
            channel_id=row.channel_id,
            graph_version_id=row.graph_version_id,
            geometry_json=row.geometry_json,
            priority_code=row.priority_code,
            status_code=row.status_code,
            issue_summary=row.issue_summary,
            suggestion_json=row.suggestion_json,
            assigned_to=row.assigned_to,
            reviewed_by=row.reviewed_by,
            resolution_type_code=row.resolution_type_code,
            resolution_target_type_code=row.resolution_target_type_code,
            resolution_target_id=row.resolution_target_id,
            created_by=row.created_by,
        )

    def _task_no(self) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        return f"NAT-{timestamp}-{uuid.uuid4().hex[:8].upper()}"

    def _task_type_for_issue(self, issue_code: str) -> str:
        if issue_code == "UNKNOWN_CONSTRAINT_DATA" or issue_code.startswith("VSL_"):
            return "CONSTRAINT_DATA_REPAIR"
        if issue_code in {
            "GRAPH_DISCONNECTED",
            "NO_ACTIVE_GRAPH_VERSION",
            "NO_ROUTING_EDGE_IN_BBOX",
            "ROUTE_STRAIGHT_LINE_FALLBACK",
        }:
            return "GRAPH_CONNECTIVITY_REPAIR"
        if "SNAP" in issue_code or "ORIGIN" in issue_code or "DESTINATION" in issue_code:
            return "SNAP_REPAIR"
        if issue_code in {
            "PATH_OUT_OF_WATER",
            "PATH_WATER_COVERAGE_WARNING",
            "PATH_OUT_OF_CHANNEL_BOUNDARY",
            "PATH_CHANNEL_BOUNDARY_WARNING",
            "CHANNEL_BOUNDARY_SOURCE_NOT_VERIFIED",
            "CHANNEL_BOUNDARY_TRUST_NEEDS_REVIEW",
            "CHANNEL_BOUNDARY_SOURCE_FRAGMENTED",
            "CHANNEL_BOUNDARY_BASEMAP_NOT_VERIFIED",
        }:
            return "SEED_BOUNDARY_REPAIR"
        if issue_code == "CENTERLINE_SEED_FALLBACK_ROUTE":
            return "GRAPH_CONNECTIVITY_REPAIR"
        if issue_code in {
            "LOW_CONFIDENCE_EDGE",
            "EDGE_NEED_MANUAL_REVIEW",
            "ROUTE_LONG_STRAIGHT_SEGMENT_REVIEW",
            "ROUTE_FOLDBACK_REVIEW",
            "ROUTE_SELF_INTERSECTION_REVIEW",
        }:
            return "GRAPH_EDGE_REPAIR"
        return "ROUTE_QUALITY_REPAIR"

    def _should_create_route_issue_task(self, issue_code: str) -> bool:
        issue_code = issue_code.upper()
        return issue_code in ROUTE_REPAIR_TASK_ISSUE_CODES or issue_code.startswith("VSL_")

    def _route_issue_task_dedupe_key(
        self,
        *,
        result: NavigationRouteResult,
        request: NavigationRouteRequest | None,
        issue: NavigationRouteQualityIssue,
        task_type_code: str,
        channel_id: int | None,
        geometry_json: dict[str, Any] | None,
    ) -> str | None:
        issue_code = issue.issue_type_code.upper()
        graph_version_id = request.graph_version_id if request else None
        parts = [
            "ROUTE_REPAIR_TASK_V1",
            f"type={task_type_code}",
            f"issue={issue_code}",
            f"graph={graph_version_id or ''}",
            f"channel={channel_id or ''}",
        ]
        if issue.related_edge_id is not None:
            parts.append(f"edge={int(issue.related_edge_id)}")
        elif issue.related_node_id is not None:
            parts.append(f"node={int(issue.related_node_id)}")
        else:
            geometry_hash = self._geometry_fingerprint(geometry_json)
            if geometry_hash:
                parts.append(f"geometry={geometry_hash}")
            elif request is not None and all(
                value is not None
                for value in (request.origin_lng, request.origin_lat, request.destination_lng, request.destination_lat)
            ):
                parts.append(
                    "od="
                    f"{float(request.origin_lng):.7f},{float(request.origin_lat):.7f}->"
                    f"{float(request.destination_lng):.7f},{float(request.destination_lat):.7f}"
                )
            else:
                return None
        return "|".join(parts)

    def _route_issue_task_geometry(
        self,
        *,
        result: NavigationRouteResult,
        request: NavigationRouteRequest | None,
        issue: NavigationRouteQualityIssue,
    ) -> dict[str, Any] | None:
        if issue.geometry_json:
            return issue.geometry_json
        if request is not None:
            if issue.issue_type_code.upper().startswith("ORIGIN_") and request.origin_lng is not None and request.origin_lat is not None:
                return {
                    "type": "Point",
                    "coordinates": [float(request.origin_lng), float(request.origin_lat)],
                }
            if (
                issue.issue_type_code.upper().startswith("DESTINATION_")
                and request.destination_lng is not None
                and request.destination_lat is not None
            ):
                return {
                    "type": "Point",
                    "coordinates": [float(request.destination_lng), float(request.destination_lat)],
                }
        return result.geometry_json

    def _geometry_fingerprint(self, geometry_json: dict[str, Any] | None) -> str | None:
        if not isinstance(geometry_json, dict):
            return None
        try:
            payload = mapping(shape(geometry_json))
        except Exception:  # noqa: BLE001
            payload = geometry_json
        normalized = self._normalize_geometry_payload(payload)
        digest = hashlib.sha256(
            json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return digest[:24]

    def _normalize_geometry_payload(self, value: Any) -> Any:
        if isinstance(value, float):
            return round(value, 7)
        if isinstance(value, dict):
            return {str(key): self._normalize_geometry_payload(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._normalize_geometry_payload(item) for item in value]
        return value

    def _legacy_endpoint_dedupe_key_matches(
        self,
        candidate_key: Any,
        issue_code: str,
        geometry_json: dict[str, Any] | None,
    ) -> bool:
        if not isinstance(candidate_key, str) or not isinstance(geometry_json, dict):
            return False
        if geometry_json.get("type") != "Point":
            return False
        coords = geometry_json.get("coordinates")
        if not isinstance(coords, (list, tuple)) or len(coords) < 2:
            return False
        coord_key = f"{float(coords[0]):.7f},{float(coords[1]):.7f}"
        if issue_code.startswith("ORIGIN_"):
            return f"|od={coord_key}->" in candidate_key
        if issue_code.startswith("DESTINATION_"):
            return candidate_key.endswith(f"->{coord_key}") or f"->{coord_key}|" in candidate_key
        return False

    def _normalize_task_type(self, task_type_code: str) -> str:
        task_type = task_type_code.upper()
        replacements = {
            "GRAPH_QUALITY_REVIEW": "GRAPH_QUALITY_REPAIR",
            "GRAPH_EDGE_REVIEW": "GRAPH_EDGE_REPAIR",
            "CONSTRAINT_DATA_REVIEW": "CONSTRAINT_DATA_REPAIR",
            "CENTERLINE_REVIEW": "CENTERLINE_REPAIR",
            "SNAP_REVIEW": "SNAP_REPAIR",
            "ROUTE_QUALITY_REVIEW": "ROUTE_QUALITY_REPAIR",
        }
        return replacements.get(task_type, task_type)

    def _priority_for_issue(self, issue_code: str, severity_code: str) -> str:
        if severity_code == "ERROR" or issue_code in {
            "GRAPH_DISCONNECTED",
            "PATH_OUT_OF_WATER",
            "PATH_OUT_OF_CHANNEL_BOUNDARY",
            "CHANNEL_BOUNDARY_SOURCE_NOT_VERIFIED",
            "CHANNEL_BOUNDARY_TRUST_NEEDS_REVIEW",
        }:
            return "HIGH"
        if issue_code in {"UNKNOWN_CONSTRAINT_DATA", "LOW_CONFIDENCE_EDGE"}:
            return "MEDIUM"
        return "MEDIUM"

    def _route_issue_suggestion(
        self,
        *,
        result: NavigationRouteResult,
        issue: NavigationRouteQualityIssue,
        task_type_code: str,
        fallback_geometry_json: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if task_type_code == "SNAP_REPAIR":
            route_geometry = issue.geometry_json or fallback_geometry_json or result.geometry_json
            return {
                "repair_strategy_code": "ENDPOINT_SNAP_AND_SEED_ACCESS_REPAIR",
                "candidate_operation_code": "CREATE_ACCESS_CENTERLINE_AND_REBUILD_GRAPH",
                "candidate_endpoint_geometry_json": route_geometry,
                "route_result_id": result.id,
                "route_result_provider_code": result.provider_code,
                "route_result_quality_code": result.quality_code,
                "route_channel_ids": list(result.channel_ids or []),
                "route_edge_ids": list(result.edge_ids or []),
                "snap_repair_reason": issue.issue_type_code,
                "publish_allowed": False,
                "requires_operator_confirmation": True,
                "guardrails": [
                    "不要通过放大吸附阈值直接生成长距离直连",
                    "优先用 HiFleet 参考轨迹、水域面和现有中心线生成接入段候选",
                    "接入段必须通过水域、边界、折返、跳点校验后才能参与 Graph 重建",
                ],
                "next_actions": [
                    "查找端点附近真实水域和最近可用 Graph 边",
                    "用 HiFleet 参考轨迹截取端点到主航道的接入段候选",
                    "生成中心线或连接点草稿，发布后重建 Graph 并重新跑路径矩阵",
                ],
            }
        if task_type_code != "SEED_BOUNDARY_REPAIR":
            return None
        route_geometry = issue.geometry_json or fallback_geometry_json or result.geometry_json
        patch = self._boundary_expansion_patch(route_geometry)
        return {
            "repair_strategy_code": "BOUNDARY_EXPANSION_CANDIDATE",
            "candidate_operation_code": "UNION_PATCH",
            "candidate_boundary_patch_geometry_json": patch,
            "candidate_buffer_m": 350,
            "route_result_id": result.id,
            "route_result_provider_code": result.provider_code,
            "route_result_quality_code": result.quality_code,
            "route_channel_ids": list(result.channel_ids or []),
            "route_edge_ids": list(result.edge_ids or []),
            "boundary_repair_reason": issue.issue_type_code,
            "publish_allowed": False,
            "requires_operator_confirmation": True,
            "guardrails": [
                "该几何只是扩边候选补丁，不能自动发布为当前边界",
                "先检查是否真实航道边界缺失或过窄，再以草稿 UNION_PATCH 合入",
                "发布新边界后必须重新生成中心线区段和 Graph，再重新跑路径验证",
            ],
        }

    def _boundary_expansion_patch(self, geometry_json: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(geometry_json, dict):
            return None
        try:
            geometry = shape(geometry_json)
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(geometry, LineString) or geometry.is_empty:
            return None
        buffer_degree = 350 / 111_320
        try:
            patch = make_valid(geometry.buffer(buffer_degree, cap_style=2, join_style=2))
        except Exception:  # noqa: BLE001
            patch = geometry.buffer(buffer_degree)
        if patch.is_empty:
            return None
        return mapping(patch)

    def _boundary_integrity_audit(self, source_trace_json: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(source_trace_json, dict):
            return {}
        audit = source_trace_json.get("boundary_integrity_audit")
        return audit if isinstance(audit, dict) else {}

    def _boundary_needs_integrity_task(self, boundary: NavigationChannelBoundary, audit: dict[str, Any]) -> bool:
        trust_code = str(audit.get("trust_code") or "").upper()
        if trust_code in {"FAILED", "NEEDS_REVIEW"}:
            return True
        if audit and str(audit.get("trust_code") or "").upper() != "READY":
            return True
        if boundary.boundary_quality_code in {"FAILED", "REVIEW", "LOW_CONFIDENCE", "UNKNOWN"}:
            return True
        return boundary.repair_status_code not in {"NONE", "REPAIRED", "VERIFIED"}

    def _primary_boundary_integrity_issue(self, trust_code: str, issue_codes: list[str]) -> str:
        for code in (
            "CHANNEL_BOUNDARY_MISSING",
            "CHANNEL_BOUNDARY_GEOMETRY_INVALID",
            "TRAJECTORY_NOT_ENCLOSED_BY_BOUNDARY",
            "CENTERLINE_NOT_ENCLOSED_BY_BOUNDARY",
            "CENTERLINE_MISSING_BOUNDARY_NOT_VERIFIED",
            "SOURCE_GEOMETRY_FRAGMENTED",
            "BOUNDARY_NOT_INDEPENDENTLY_BASEMAP_VERIFIED",
            "NAVIGATION_TECHNICAL_GRADE_UNKNOWN",
        ):
            if code in issue_codes:
                return code
        if trust_code == "FAILED":
            return "CHANNEL_BOUNDARY_INTEGRITY_FAILED"
        return "CHANNEL_BOUNDARY_INTEGRITY_NEEDS_REVIEW"

    def _boundary_integrity_priority(self, trust_code: str, issue_codes: list[str]) -> str:
        if trust_code == "FAILED" or any(
            code in issue_codes
            for code in {
                "CHANNEL_BOUNDARY_MISSING",
                "CHANNEL_BOUNDARY_GEOMETRY_INVALID",
                "TRAJECTORY_NOT_ENCLOSED_BY_BOUNDARY",
                "CENTERLINE_NOT_ENCLOSED_BY_BOUNDARY",
            }
        ):
            return "HIGH"
        return "MEDIUM"

    def _boundary_integrity_summary(
        self,
        boundary: NavigationChannelBoundary,
        trust_code: str,
        issue_codes: list[str],
    ) -> str:
        issue_text = ", ".join(issue_codes[:8]) if issue_codes else "SOURCE_NOT_VERIFIED"
        return (
            f"航道 {boundary.channel_id} 当前边界 {boundary.id} 完整性为 {trust_code}，"
            f"不能作为真实路径验收前置边界；问题：{issue_text}"
        )

    def _validation_candidates(self, validation_report: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not isinstance(validation_report, dict):
            return []
        candidates = validation_report.get("annotation_task_candidates") or []
        return [candidate for candidate in candidates if isinstance(candidate, dict)]

    def _base_suggestion(self, *, issue_code: str, task_type_code: str) -> dict[str, Any]:
        return {
            "suggestion_source_code": "RULE_BASED_ASSISTANT",
            "issue_code": issue_code,
            "task_type_code": task_type_code,
            "publish_allowed": False,
            "requires_operator_confirmation": True,
            "next_actions": self._next_actions(issue_code, task_type_code),
        }

    def _suggestion_for_task(self, task: NavigationAnnotationTask) -> dict[str, Any]:
        current = task.suggestion_json or {}
        issue_code = str(current.get("issue_code") or task.task_type_code)
        return {
            **current,
            "suggestion_source_code": "RULE_BASED_ASSISTANT",
            "generated_at": datetime.now(UTC).isoformat(),
            "publish_allowed": False,
            "requires_operator_confirmation": True,
            "guardrails": [
                "不要把 AI 建议直接发布为当前可用路径图边",
                "重建图网络前应先创建新的边界、中心线或约束版本",
                "保留上一版图网络，便于历史路径复现",
            ],
            "next_actions": self._next_actions(issue_code, task.task_type_code),
        }

    def _next_actions(self, issue_code: str, task_type_code: str) -> list[str]:
        if task_type_code == "WATER_AREA_MATCH_REPAIR":
            return [
                "打开水系归属页查看系统推荐候选水域",
                "确认真实水域归属；必要时补充 alias/scope 配置",
                "生成候选边界后再进入边界生成页逐段修正",
            ]
        if task_type_code == "SEED_BOUNDARY_REPAIR":
            return [
                "打开边界生成页查看参考边界来源和真实水域重叠问题",
                "从候选边界或水域归属复制为草稿，逐段编辑后发布当前边界",
                "发布边界后再生产中心线，不要用参考边界直接生成路径",
            ]
        if issue_code == "UNKNOWN_CONSTRAINT_DATA" or task_type_code in {"CONSTRAINT_DATA_REPAIR", "CONSTRAINT_DATA_REVIEW"}:
            return [
                "补齐船闸、桥梁、吃水、吨级或限航数据",
                "创建路径图边约束或关联约束点资料",
                "重新生成或校验图网络版本",
            ]
        if task_type_code in {"CENTERLINE_REPAIR", "CENTERLINE_REVIEW"}:
            return [
                "检查中心线是否位于参考边界或真实水域内",
                "人工修正后创建新的中心线版本",
                "发布中心线版本后再参与图网络重建",
            ]
        if task_type_code in {"GRAPH_CONNECTIVITY_REPAIR", "GRAPH_EDGE_REPAIR", "GRAPH_EDGE_REVIEW"}:
            return [
                "定位断点、低置信路径图边或错连位置",
                "通过人工连接点、码头接入或中心线版本修正生成候选数据",
                "重建图网络版本并运行图网络校验",
            ]
        return [
            "确认问题位置和关联数据来源",
            "生成新的 boundary、centerline 或 constraint 版本",
            "发布修正数据后再重建 graph version",
        ]

    def _int_or_none(self, value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _dedupe_ids(self, task_ids: list[int]) -> list[int]:
        seen: set[int] = set()
        output: list[int] = []
        for task_id in task_ids:
            if task_id in seen:
                continue
            seen.add(task_id)
            output.append(task_id)
        return output
