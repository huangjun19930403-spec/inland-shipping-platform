from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models import (
    NavigationAnnotationTask,
    NavigationChannelCenterline,
    NavigationChannelWaterBodyMatch,
    NavigationGraphEdge,
    NavigationGraphVersion,
    NavigationRouteResult,
    NavigationWaterArea,
    NavigationWaterBody,
)
from app.models.address import NavigationChannel, NavigationChannelBoundary, NavigationChannelSegment
from app.modules.navigation.annotation_service import NavigationAnnotationTaskService
from app.modules.navigation.schemas import (
    NavigationAnnotationTaskBatchCreateResponse,
    NavigationChannelDiagnosticBoundaryResponse,
    NavigationChannelDiagnosticResponse,
    NavigationDiagnosticsRunResponse,
    NavigationCandidateConfirmRequest,
    NavigationWaterBodyCandidateListResponse,
    NavigationWaterBodyCandidateResponse,
    NavigationWaterBodyMatchCreateRequest,
)
from app.modules.navigation.workbench_service import NavigationWorkbenchService


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ALIAS_CONFIG = PROJECT_ROOT / "scripts" / "seed_data" / "navigation" / "navigation_channel_aliases.json"
DEFAULT_SCOPE_CONFIG = PROJECT_ROOT / "scripts" / "seed_data" / "navigation" / "navigation_real_scope.json"
REAL_WATER_SOURCE_CODE = "RIVER_SHAPEFILE_2026"
SEED_OVERLAP_SUSPECT_THRESHOLD = 0.35
LAYER_PRIORITY = {
    "一级水系": 1,
    "二级水系": 2,
    "三级水系": 3,
    "四级水系": 4,
    "五级水系": 5,
    "六级水系": 6,
    "七级水系": 7,
    "rx": 80,
    "rx8": 90,
}


class NavigationDiagnosticService:
    """Diagnose real-channel production blockers and suggest water-area candidates.

    Diagnostics are deliberately separate from route generation. They never build
    graph edges and never treat water polygons as a route.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.workbench = NavigationWorkbenchService(session)
        self._alias_config: dict[str, Any] | None = None
        self._scope_config: dict[str, Any] | None = None

    async def channel_diagnostics(self, channel_id: int, *, include_spatial: bool = True) -> NavigationChannelDiagnosticResponse:
        channel = await self._channel(channel_id)
        counts = await self._counts(channel)
        stage_code, stage_name, blockers = self._production_stage(counts)
        boundary = await self._current_boundary(channel.id)
        overlap_ratio = await self._seed_boundary_overlap_ratio(boundary) if include_spatial else None
        suggested_terms = await self._suggested_terms(channel)
        has_alias_config = self._has_alias_config(channel.channel_code)
        scope = self._scope_for_channel(channel)
        candidate_count = await self._candidate_count(channel, suggested_terms, boundary, scope)
        issues = self._issue_codes(
            counts=counts,
            boundary=boundary,
            overlap_ratio=overlap_ratio,
            has_alias_config=has_alias_config,
            scope=scope,
            candidate_count=candidate_count,
        )
        next_action, next_path = self._next_action(stage_code, channel.id, issues)
        return NavigationChannelDiagnosticResponse(
            channel_id=channel.id,
            channel_code=channel.channel_code,
            channel_name=channel.channel_name,
            production_stage_code=stage_code,
            production_stage_name=stage_name,
            current_boundary=self._boundary_response(boundary),
            boundary_source_code=self._boundary_source_code(boundary),
            boundary_source_explanation=self._boundary_explanation(channel, boundary),
            seed_boundary_overlap_ratio=overlap_ratio,
            current_water_body_match_count=counts["match"],
            water_body_candidate_count=candidate_count,
            candidate_boundary_count=counts["candidate_boundary"],
            current_boundary_count=counts["boundary"],
            centerline_candidate_count=counts["centerline_candidate"],
            approved_current_centerline_count=counts["centerline"],
            active_graph_edge_count=counts["edge"],
            route_verified_count=counts["route"],
            issue_codes=issues,
            blocker_codes=sorted(set(blockers + [issue for issue in issues if issue.endswith("_MISSING") or issue.endswith("_BLOCKED")])),
            recommended_next_action=next_action,
            recommended_path=next_path,
            suggested_terms=suggested_terms,
            source_trace_json={
                "channel_source_version": channel.source_version,
                "channel_source_summary": channel.source_summary,
                "scope_code": scope.get("scope_code") if scope else None,
                "scope_configured": scope is not None,
                "alias_configured": has_alias_config,
                "route_guardrail": "water_area_and_boundary_are_not_routing_objects",
            },
            warnings=self._warnings(issues, overlap_ratio),
        )

    async def water_body_candidates(
        self,
        channel_id: int,
        *,
        limit: int = 80,
    ) -> NavigationWaterBodyCandidateListResponse:
        channel = await self._channel(channel_id)
        boundary = await self._current_boundary(channel.id)
        scope = self._scope_for_channel(channel)
        suggested_terms = await self._suggested_terms(channel)
        existing_ids = set(
            (
                await self.session.execute(
                    select(NavigationChannelWaterBodyMatch.water_body_id).where(
                        NavigationChannelWaterBodyMatch.channel_id == channel.id,
                        NavigationChannelWaterBodyMatch.is_current.is_(True),
                    )
                )
            ).scalars()
        )

        candidates: dict[int, NavigationWaterBodyCandidateResponse] = {}
        for row in await self._name_candidate_rows(suggested_terms, limit=max(limit * 2, 80)):
            candidate = self._candidate_from_water_body(
                row,
                channel=channel,
                candidate_type_code="NAME_ALIAS_CANDIDATE",
                suggested_terms=suggested_terms,
                boundary=boundary,
                scope=scope,
                existing_ids=existing_ids,
            )
            self._merge_candidate(candidates, candidate)

        for row in await self._bbox_candidate_rows(boundary=boundary, scope=scope, limit=max(limit * 2, 80)):
            candidate = self._candidate_from_water_body(
                row,
                channel=channel,
                candidate_type_code="SEED_BOUNDARY_NEARBY",
                suggested_terms=suggested_terms,
                boundary=boundary,
                scope=scope,
                existing_ids=existing_ids,
            )
            self._merge_candidate(candidates, candidate)

        items = sorted(
            candidates.values(),
            key=lambda item: (
                item.already_matched,
                -item.score,
                len(item.issue_codes),
                "SEED_BOUNDARY_BBOX_INTERSECT" not in item.reason_codes,
                self._layer_priority(item.source_layer_name),
                -(item.area_km2 or 0),
                item.water_name or "",
                item.water_body_id,
            ),
        )[: max(1, min(limit, 200))]
        issue_codes = []
        if not items:
            issue_codes.append("NO_WATER_BODY_CANDIDATE")
        if not self._has_alias_config(channel.channel_code):
            issue_codes.append("MISSING_ALIAS_CONFIG")
        if scope is None:
            issue_codes.append("SCOPE_NOT_CONFIGURED")
        return NavigationWaterBodyCandidateListResponse(
            channel_id=channel.id,
            channel_code=channel.channel_code,
            channel_name=channel.channel_name,
            total=len(items),
            suggested_terms=suggested_terms,
            issue_codes=sorted(set(issue_codes)),
            items=items,
        )

    async def confirm_water_body_candidate(
        self,
        channel_id: int,
        water_body_id: int,
        body: NavigationCandidateConfirmRequest,
    ):
        water_body = await self.session.get(NavigationWaterBody, water_body_id)
        if water_body is None or not water_body.is_enabled:
            raise NotFoundError("NavigationWaterBody", water_body_id)
        return await self.workbench.create_water_body_match(
            channel_id=channel_id,
            body=NavigationWaterBodyMatchCreateRequest(
                water_body_id=water_body_id,
                match_type_code=body.candidate_type_code or "CONFIRMED_MATCH",
                matched_term=water_body.production_name or water_body.display_name or water_body.water_body_name,
                score=body.score,
                confidence_code="MANUAL_CONFIRMED",
                issue_codes=body.issue_codes,
                match_batch_code=f"CONFIRMED-BODY-MATCH-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
                source_trace_json={
                    "source": "navigation_diagnostic_water_body_candidate_confirm",
                    "reason_codes": body.reason_codes,
                    "route_guardrail": "confirmed water-body match is not a route edge",
                },
            ),
        )

    async def run_diagnostics(self, *, include_spatial: bool = False) -> NavigationDiagnosticsRunResponse:
        channels = list(
            (
                await self.session.execute(
                    select(NavigationChannel)
                    .where(NavigationChannel.is_enabled.is_(True))
                    .order_by(NavigationChannel.sort_order, NavigationChannel.id)
                )
            ).scalars()
        )
        items = [await self.channel_diagnostics(channel.id, include_spatial=include_spatial) for channel in channels]
        issue_counts = Counter(issue for item in items for issue in item.issue_codes)
        return NavigationDiagnosticsRunResponse(
            channel_count=len(items),
            issue_counts=dict(sorted(issue_counts.items())),
            items=items,
        )

    async def create_annotation_tasks_from_diagnostics(
        self,
        *,
        channel_id: int | None = None,
        created_by: int | None = None,
    ) -> NavigationAnnotationTaskBatchCreateResponse:
        diagnostics = (
            [await self.channel_diagnostics(channel_id, include_spatial=True)]
            if channel_id
            else (await self.run_diagnostics(include_spatial=False)).items
        )
        annotation_service = NavigationAnnotationTaskService(self.session)
        created_count = 0
        existing_count = 0
        task_ids: list[int] = []
        for item in diagnostics:
            task_specs = self._task_specs_for_diagnostics(item)
            for task_type_code, issue_code, summary, priority_code in task_specs:
                task, created = await annotation_service._get_or_create_task(
                    task_type_code=task_type_code,
                    target_type_code="NAVIGATION_CHANNEL",
                    target_id=item.channel_id,
                    issue_code=issue_code,
                    issue_summary=summary,
                    priority_code=priority_code,
                    channel_id=item.channel_id,
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
            source_type_code="CHANNEL_DIAGNOSTICS",
        )

    async def _channel(self, channel_id: int) -> NavigationChannel:
        channel = await self.session.get(NavigationChannel, channel_id)
        if channel is None:
            raise NotFoundError("NavigationChannel", channel_id)
        return channel

    async def _counts(self, channel: NavigationChannel) -> dict[str, int]:
        active_graph_version = await self._active_graph_version()
        edge_count = 0
        if active_graph_version is not None:
            edge_count = int(
                await self.session.scalar(
                    select(func.count()).select_from(NavigationGraphEdge).where(
                        NavigationGraphEdge.graph_version_id == active_graph_version.id,
                        NavigationGraphEdge.channel_id == channel.id,
                        NavigationGraphEdge.routing_enabled.is_(True),
                    )
                )
                or 0
            )
        return {
            "match": int(
                await self.session.scalar(
                    select(func.count()).select_from(NavigationChannelWaterBodyMatch).where(
                        NavigationChannelWaterBodyMatch.channel_id == channel.id,
                        NavigationChannelWaterBodyMatch.is_current.is_(True),
                    )
                )
                or 0
            ),
            "candidate_boundary": int(
                await self.session.scalar(
                    select(func.count()).select_from(NavigationChannelBoundary).where(
                        NavigationChannelBoundary.channel_id == channel.id,
                        NavigationChannelBoundary.is_current.is_(False),
                        NavigationChannelBoundary.coverage_policy_code == "RIVER_MATCH_CANDIDATE",
                    )
                )
                or 0
            ),
            "boundary": int(
                await self.session.scalar(
                    select(func.count()).select_from(NavigationChannelBoundary).where(
                        NavigationChannelBoundary.channel_id == channel.id,
                        NavigationChannelBoundary.is_current.is_(True),
                        NavigationChannelBoundary.geometry_status_code == "AVAILABLE",
                    )
                )
                or 0
            ),
            "centerline_candidate": int(
                await self.session.scalar(
                    select(func.count()).select_from(NavigationChannelCenterline).where(
                        NavigationChannelCenterline.channel_id == channel.id,
                        NavigationChannelCenterline.review_status_code != "APPROVED",
                    )
                )
                or 0
            ),
            "centerline": int(
                await self.session.scalar(
                    select(func.count()).select_from(NavigationChannelCenterline).where(
                        NavigationChannelCenterline.channel_id == channel.id,
                        NavigationChannelCenterline.is_current.is_(True),
                        NavigationChannelCenterline.review_status_code == "APPROVED",
                        NavigationChannelCenterline.quality_code.in_({"READY", "READY_WITH_WARNING"}),
                    )
                )
                or 0
            ),
            "edge": edge_count,
            "route": await self._route_verified_count(channel.id),
        }

    def _production_stage(self, counts: dict[str, int]) -> tuple[str, str, list[str]]:
        if counts["match"] <= 0:
            return "NO_WATER_MATCH", "水体待归属", ["NO_WATER_BODY_MATCH"]
        if counts["candidate_boundary"] > 0:
            return "BOUNDARY_CANDIDATE", "边界待生产", ["BOUNDARY_CANDIDATE_TO_PUBLISH"]
        if counts["boundary"] <= 0:
            return "WATER_MATCH_READY", "边界待生产", ["NO_CURRENT_BOUNDARY"]
        if counts["centerline"] > 0 and counts["edge"] > 0 and counts["route"] > 0:
            return "ROUTE_VERIFIED", "路径已验证", []
        if counts["centerline"] > 0 and counts["edge"] > 0:
            return "GRAPH_READY", "路径待验证", []
        if counts["centerline"] > 0:
            return "CENTERLINE_PUBLISHED", "Graph 待构建", []
        if counts["centerline_candidate"] > 0:
            return "CENTERLINE_CANDIDATE", "中心线待发布", ["CENTERLINE_CANDIDATE_TO_PUBLISH"]
        return "BOUNDARY_PUBLISHED", "中心线待生产", ["NO_APPROVED_CENTERLINE"]

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
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _route_verified_count(self, channel_id: int) -> int:
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
        return sum(1 for channel_ids in rows if isinstance(channel_ids, list) and channel_id in {self._int_or_none(item) for item in channel_ids})

    async def _current_boundary(self, channel_id: int) -> NavigationChannelBoundary | None:
        return (
            await self.session.execute(
                select(NavigationChannelBoundary)
                .where(
                    NavigationChannelBoundary.channel_id == channel_id,
                    NavigationChannelBoundary.is_current.is_(True),
                )
                .order_by(NavigationChannelBoundary.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _suggested_terms(self, channel: NavigationChannel) -> list[str]:
        configured = self._alias_config_data().get("channels", {}).get(channel.channel_code, {})
        terms: list[str] = []
        for value in [
            channel.channel_name,
            channel.official_name,
            channel.display_name,
            *(channel.alias_names or []),
            *configured.get("aliases", []),
            *configured.get("water_names", []),
        ]:
            self._append_unique_term(terms, value)
        segments = list(
            (
                await self.session.execute(
                    select(NavigationChannelSegment).where(NavigationChannelSegment.channel_id == channel.id)
                )
            ).scalars()
        )
        for segment in segments:
            self._append_unique_term(terms, segment.segment_name)
            for value in segment.source_water_names or []:
                self._append_unique_term(terms, value)
        return terms[:40]

    def _append_unique_term(self, terms: list[str], value: Any) -> None:
        if value is None:
            return
        term = str(value).strip()
        if not term or self._norm(term) in {self._norm(item) for item in terms}:
            return
        terms.append(term)

    async def _candidate_count(
        self,
        channel: NavigationChannel,
        suggested_terms: list[str],
        boundary: NavigationChannelBoundary | None,
        scope: dict[str, Any] | None,
    ) -> int:
        # A cheap bounded count for overview/diagnostics. Full candidate scoring is
        # done by water_body_candidates().
        rows = await self._name_candidate_rows(suggested_terms, limit=20)
        if rows:
            return len(rows)
        return len(await self._bbox_candidate_rows(boundary=boundary, scope=scope, limit=20))

    async def _name_candidate_rows(self, suggested_terms: list[str], *, limit: int) -> list[NavigationWaterBody]:
        normalized_terms = [self._norm(term) for term in suggested_terms if self._norm(term)]
        if not normalized_terms:
            return []
        clauses = []
        for term in normalized_terms[:18]:
            like = f"%{term}%"
            clauses.append(NavigationWaterBody.normalized_water_name.like(like))
            clauses.append(NavigationWaterBody.water_body_name.like(f"%{term}%"))
            clauses.append(NavigationWaterBody.display_name.like(f"%{term}%"))
            clauses.append(NavigationWaterBody.production_name.like(f"%{term}%"))
        return list(
            (
                await self.session.execute(
                    select(NavigationWaterBody)
                    .where(
                        NavigationWaterBody.is_enabled.is_(True),
                        NavigationWaterBody.source_code == REAL_WATER_SOURCE_CODE,
                        NavigationWaterBody.body_role_code.in_(["PRIMARY_HIERARCHY", "RX_FILL_GAP"]),
                        NavigationWaterBody.normalized_water_name.is_not(None),
                        or_(*clauses),
                    )
                    .order_by(func.coalesce(NavigationWaterBody.source_layer_order, 999), NavigationWaterBody.area_km2.desc().nullslast(), NavigationWaterBody.id)
                    .limit(limit)
                )
            ).scalars()
        )

    async def _bbox_candidate_rows(
        self,
        *,
        boundary: NavigationChannelBoundary | None,
        scope: dict[str, Any] | None,
        limit: int,
    ) -> list[NavigationWaterBody]:
        bbox = self._bbox_dict(boundary) if boundary else None
        if bbox is None and scope is not None:
            bbox = scope.get("bbox")
        if bbox is None:
            return []
        expanded = self._expand_bbox(bbox, margin_degree=0.3)
        return list(
            (
                await self.session.execute(
                    select(NavigationWaterBody)
                    .where(
                        NavigationWaterBody.is_enabled.is_(True),
                        NavigationWaterBody.source_code == REAL_WATER_SOURCE_CODE,
                        NavigationWaterBody.body_role_code.in_(["PRIMARY_HIERARCHY", "RX_FILL_GAP"]),
                        *self._bbox_intersects(NavigationWaterBody, expanded),
                    )
                    .order_by(NavigationWaterBody.area_km2.desc().nullslast(), NavigationWaterBody.id)
                    .limit(limit)
                )
            ).scalars()
        )

    def _candidate_from_water_body(
        self,
        row: NavigationWaterBody,
        *,
        channel: NavigationChannel,
        candidate_type_code: str,
        suggested_terms: list[str],
        boundary: NavigationChannelBoundary | None,
        scope: dict[str, Any] | None,
        existing_ids: set[int],
    ) -> NavigationWaterBodyCandidateResponse:
        name = row.production_name or row.display_name or row.water_body_name or row.normalized_water_name
        matched_term = self._matched_term(name, suggested_terms)
        score = 45
        reason_codes: set[str] = set()
        issue_codes: set[str] = set()
        if matched_term:
            if self._norm(matched_term) in self._primary_term_norms(channel):
                reason_codes.add("NAME_OR_ALIAS_MATCH")
                score = max(score, 95 if self._norm(name) == self._norm(matched_term) else 78)
            else:
                reason_codes.add("SEED_SEGMENT_TERM_MATCH")
                issue_codes.add("SEED_SEGMENT_TERM_NEEDS_REVIEW")
                score = max(score, 68 if self._norm(name) == self._norm(matched_term) else 58)
        normalized_name = self._norm(name)
        normalized_channel_name = self._norm(channel.channel_name)
        if normalized_name and normalized_channel_name and len(normalized_name) >= 2 and normalized_name in normalized_channel_name:
            reason_codes.add("CHANNEL_NAME_ROOT_MATCH")
            score = max(score, 100)
        if boundary is not None:
            boundary_bbox = self._bbox_dict(boundary)
            water_bbox = self._bbox_dict(row)
            if boundary_bbox and water_bbox and self._bbox_intersects_plain(water_bbox, boundary_bbox):
                reason_codes.add("SEED_BOUNDARY_BBOX_INTERSECT")
                score = max(score, 62)
            elif boundary_bbox and water_bbox and self._bbox_intersects_plain(water_bbox, self._expand_bbox(boundary_bbox, margin_degree=0.3)):
                reason_codes.add("NEAR_SEED_BOUNDARY")
                score = max(score, 52)
            elif boundary_bbox:
                issue_codes.add("OUT_OF_SEED_BOUNDARY_BBOX")
                score = max(0, score - 8)
        if scope is not None and scope.get("bbox"):
            water_bbox = self._bbox_dict(row)
            if water_bbox and self._bbox_intersects_plain(water_bbox, scope["bbox"]):
                reason_codes.add("IN_REAL_SCOPE")
            else:
                issue_codes.add("OUT_OF_REAL_SCOPE")
        if row.body_role_code == "RX_FILL_GAP":
            reason_codes.add("RX_FILL_GAP")
            score = min(100, score + 3)
        if self._float(row.area_km2) and (self._float(row.area_km2) or 0) >= 10:
            reason_codes.add("LARGE_WATER_AREA")
            score = max(score, 55)
        if not matched_term and candidate_type_code == "SEED_BOUNDARY_NEARBY":
            issue_codes.add("NAME_NOT_MATCHED")
        return NavigationWaterBodyCandidateResponse(
            water_body_id=row.id,
            water_body_code=row.water_body_code,
            water_name=row.water_body_name,
            normalized_water_name=row.normalized_water_name,
            display_name=row.display_name,
            production_name=row.production_name,
            source_code=row.source_code,
            body_role_code=row.body_role_code,
            source_layer_name=row.source_layer_name,
            source_layer_display_name=row.source_layer_display_name,
            source_layer_role_code=row.source_layer_role_code,
            water_type_code=row.water_type_code,
            feature_count=row.feature_count,
            area_km2=self._float(row.area_km2),
            bbox=self._bbox_dict(row) or {},
            display_bbox=self._display_bbox_dict(row) or {},
            candidate_type_code=candidate_type_code,
            matched_term=matched_term,
            score=min(100, max(0, score)),
            confidence_code="HIGH_CONFIDENCE" if score >= 90 else ("MEDIUM_CONFIDENCE" if score >= 65 else "LOW_CONFIDENCE"),
            reason_codes=sorted(reason_codes),
            issue_codes=sorted(issue_codes),
            already_matched=row.id in existing_ids,
        )

    def _merge_candidate(
        self,
        candidates: dict[int, NavigationWaterBodyCandidateResponse],
        candidate: NavigationWaterBodyCandidateResponse,
    ) -> None:
        existing = candidates.get(candidate.water_body_id)
        if existing is None or candidate.score > existing.score:
            candidates[candidate.water_body_id] = candidate
            return
        if existing is not None:
            existing.reason_codes = sorted(set(existing.reason_codes + candidate.reason_codes))
            existing.issue_codes = sorted(set(existing.issue_codes + candidate.issue_codes))

    def _issue_codes(
        self,
        *,
        counts: dict[str, int],
        boundary: NavigationChannelBoundary | None,
        overlap_ratio: float | None,
        has_alias_config: bool,
        scope: dict[str, Any] | None,
        candidate_count: int,
    ) -> list[str]:
        issues: set[str] = set()
        if counts["match"] <= 0:
            issues.add("NO_WATER_BODY_MATCH")
        if candidate_count <= 0:
            issues.add("NO_WATER_BODY_CANDIDATE")
        if not has_alias_config:
            issues.add("MISSING_ALIAS_CONFIG")
        if scope is None:
            issues.add("SCOPE_NOT_CONFIGURED")
        if boundary is None:
            issues.add("SEED_BOUNDARY_MISSING")
        else:
            if boundary.coverage_policy_code == "CHANNEL_CORRIDOR_ENVELOPE":
                issues.add("SEED_BOUNDARY_REFERENCE")
            if overlap_ratio is not None and overlap_ratio < SEED_OVERLAP_SUSPECT_THRESHOLD:
                issues.add("SEED_BOUNDARY_SUSPECT")
            if str(boundary.boundary_quality_code or "").upper() in {"REVIEW", "LOW_CONFIDENCE", "UNKNOWN"}:
                issues.add("SEED_BOUNDARY_NEEDS_PRODUCTION")
        if counts["centerline"] <= 0:
            issues.add("CENTERLINE_MISSING")
        if counts["edge"] <= 0:
            issues.add("GRAPH_BLOCKED")
        return sorted(issues)

    async def _seed_boundary_overlap_ratio(self, boundary: NavigationChannelBoundary | None) -> float | None:
        if boundary is None:
            return None
        boundary_bbox = self._bbox_dict(boundary)
        if not boundary_bbox:
            return None
        bbox_area = self._bbox_area(boundary_bbox)
        if bbox_area is None or bbox_area <= 0:
            return None
        # Keep interactive diagnostics bounded. Exact polygon overlay on broad
        # seed envelopes can run for minutes and continue occupying DB
        # connections after the browser request times out. The UI only needs a
        # quick suspect signal; exact geometry validation belongs in an offline
        # audit job.
        return await self._seed_boundary_bbox_overlap_ratio(boundary_bbox)

    async def _seed_boundary_bbox_overlap_ratio(self, boundary_bbox: dict[str, float]) -> float | None:
        boundary_area = self._bbox_area(boundary_bbox)
        if boundary_area is None or boundary_area <= 0:
            return None
        rows = list(
            (
                await self.session.execute(
                    select(
                        NavigationWaterBody.bbox_min_lng,
                        NavigationWaterBody.bbox_min_lat,
                        NavigationWaterBody.bbox_max_lng,
                        NavigationWaterBody.bbox_max_lat,
                    )
                    .where(
                        NavigationWaterBody.is_enabled.is_(True),
                        NavigationWaterBody.source_code == REAL_WATER_SOURCE_CODE,
                        NavigationWaterBody.body_role_code.in_(["PRIMARY_HIERARCHY", "RX_FILL_GAP"]),
                        *self._bbox_intersects(NavigationWaterBody, boundary_bbox),
                    )
                )
            ).all()
        )
        overlap_area = 0.0
        for min_lng, min_lat, max_lng, max_lat in rows:
            water_bbox = {
                "min_lng": self._float(min_lng),
                "min_lat": self._float(min_lat),
                "max_lng": self._float(max_lng),
                "max_lat": self._float(max_lat),
            }
            overlap_area += self._bbox_intersection_area(boundary_bbox, water_bbox)
        return round(min(1.0, max(0.0, overlap_area / boundary_area)), 4)

    def _bbox_area(self, bbox: dict[str, float | None]) -> float | None:
        min_lng = self._float(bbox.get("min_lng"))
        min_lat = self._float(bbox.get("min_lat"))
        max_lng = self._float(bbox.get("max_lng"))
        max_lat = self._float(bbox.get("max_lat"))
        if None in {min_lng, min_lat, max_lng, max_lat}:
            return None
        width = max(0.0, float(max_lng) - float(min_lng))
        height = max(0.0, float(max_lat) - float(min_lat))
        return width * height

    def _bbox_intersection_area(self, left: dict[str, float | None], right: dict[str, float | None]) -> float:
        left_min_lng = self._float(left.get("min_lng"))
        left_min_lat = self._float(left.get("min_lat"))
        left_max_lng = self._float(left.get("max_lng"))
        left_max_lat = self._float(left.get("max_lat"))
        right_min_lng = self._float(right.get("min_lng"))
        right_min_lat = self._float(right.get("min_lat"))
        right_max_lng = self._float(right.get("max_lng"))
        right_max_lat = self._float(right.get("max_lat"))
        if None in {left_min_lng, left_min_lat, left_max_lng, left_max_lat, right_min_lng, right_min_lat, right_max_lng, right_max_lat}:
            return 0.0
        width = max(0.0, min(float(left_max_lng), float(right_max_lng)) - max(float(left_min_lng), float(right_min_lng)))
        height = max(0.0, min(float(left_max_lat), float(right_max_lat)) - max(float(left_min_lat), float(right_min_lat)))
        return width * height

    def _task_specs_for_diagnostics(self, item: NavigationChannelDiagnosticResponse) -> list[tuple[str, str, str, str]]:
        specs: list[tuple[str, str, str, str]] = []
        issues = set(item.issue_codes)
        if "SEED_BOUNDARY_SUSPECT" in issues:
            specs.append(
                (
                    "SEED_BOUNDARY_REPAIR",
                    "SEED_BOUNDARY_SUSPECT",
                    f"{item.channel_name} seed 边界疑似偏离真实水域，需要在边界生产页逐段修正后发布。",
                    "HIGH",
                )
            )
        if {"NO_WATER_BODY_MATCH", "MISSING_ALIAS_CONFIG", "SCOPE_NOT_CONFIGURED"} & issues:
            specs.append(
                (
                    "WATER_BODY_MATCH_REPAIR",
                    "NO_WATER_BODY_MATCH",
                    f"{item.channel_name} 缺少已确认规范水体归属，需要从系统候选中确认真实水体。",
                    "HIGH",
                )
            )
        if "CENTERLINE_MISSING" in issues:
            specs.append(
                (
                    "CENTERLINE_REVIEW",
                    "CENTERLINE_MISSING",
                    f"{item.channel_name} 缺少已发布中心线，Graph 和路径生成被阻塞。",
                    "MEDIUM",
                )
            )
        if "GRAPH_BLOCKED" in issues and "CENTERLINE_MISSING" not in issues:
            specs.append(
                (
                    "GRAPH_CONNECTIVITY_REPAIR",
                    "GRAPH_BLOCKED",
                    f"{item.channel_name} 已有中心线但没有可用 Graph edge，需要重建并校验 graph。",
                    "MEDIUM",
                )
            )
        return specs

    def _next_action(self, stage_code: str, channel_id: int, issues: list[str]) -> tuple[str, str]:
        if "SEED_BOUNDARY_SUSPECT" in issues:
            return "查看 seed 边界问题并进入边界生产", f"/navigation/production/boundaries?channel_id={channel_id}"
        if stage_code == "NO_WATER_MATCH":
            return "确认系统推荐水体归属", f"/navigation/production/water-matches?channel_id={channel_id}"
        if stage_code in {"WATER_MATCH_READY", "BOUNDARY_CANDIDATE"}:
            return "编辑并发布当前边界", f"/navigation/production/boundaries?channel_id={channel_id}"
        if stage_code in {"BOUNDARY_PUBLISHED", "CENTERLINE_CANDIDATE"}:
            return "生产并发布中心线", f"/navigation/production/centerlines?channel_id={channel_id}"
        if stage_code == "CENTERLINE_PUBLISHED":
            return "构建 Graph", f"/navigation/production/graphs?channel_id={channel_id}"
        if stage_code == "GRAPH_READY":
            return "验证路径", f"/navigation/routes?channel_id={channel_id}"
        return "查看诊断任务", f"/navigation/production/annotations?channel_id={channel_id}"

    def _warnings(self, issues: list[str], overlap_ratio: float | None) -> list[str]:
        warnings: list[str] = []
        if "SEED_BOUNDARY_SUSPECT" in issues:
            text_ratio = f"{overlap_ratio:.1%}" if overlap_ratio is not None else "未知"
            warnings.append(f"当前 seed 边界与真实水域重叠比例为 {text_ratio}，只能作为参考，不能直接发布为可信生产边界。")
        if "NO_WATER_BODY_MATCH" in issues:
            warnings.append("该航道还没有已确认规范水体归属，系统会先给出候选水体，用户只需要确认、移除或补充。")
        if "CENTERLINE_MISSING" in issues:
            warnings.append("无已发布中心线，Graph 构建和路径生成必须失败；不能用 polygon 或 boundary 画假路线。")
        return warnings

    def _boundary_response(self, boundary: NavigationChannelBoundary | None) -> NavigationChannelDiagnosticBoundaryResponse | None:
        if boundary is None:
            return None
        return NavigationChannelDiagnosticBoundaryResponse(
            id=boundary.id,
            coverage_policy_code=boundary.coverage_policy_code,
            boundary_quality_code=boundary.boundary_quality_code,
            connectivity_status_code=boundary.connectivity_status_code,
            repair_status_code=boundary.repair_status_code,
            geometry_status_code=boundary.geometry_status_code,
            coordinate_system_code=boundary.boundary_coordinate_system_code,
            ring_count=boundary.ring_count,
            point_count=boundary.point_count,
            bbox=self._bbox_dict(boundary) or {},
        )

    def _boundary_source_code(self, boundary: NavigationChannelBoundary | None) -> str:
        if boundary is None:
            return "NONE"
        if boundary.coverage_policy_code in {"CHANNEL_CORRIDOR_ENVELOPE", "SEED_BOUNDARY"}:
            return "SEED_BOUNDARY"
        if boundary.coverage_policy_code == "RIVER_MATCH_CANDIDATE":
            return "RIVER_MATCH_CANDIDATE"
        if boundary.coverage_policy_code == "MANUAL_DRAW":
            return "MANUAL_BOUNDARY"
        return boundary.coverage_policy_code

    def _boundary_explanation(self, channel: NavigationChannel, boundary: NavigationChannelBoundary | None) -> str:
        if boundary is None:
            return "当前航道没有发布边界，地图不会使用网络查询临时补边界。"
        if boundary.coverage_policy_code in {"CHANNEL_CORRIDOR_ENVELOPE", "SEED_BOUNDARY"}:
            return (
                f"当前地图边界来自本地 seed/数据库，不是网络查询；"
                f"coverage_policy={boundary.coverage_policy_code}，"
                f"channel_source_version={channel.source_version}。"
            )
        return f"当前地图边界来自数据库资产：coverage_policy={boundary.coverage_policy_code}。"

    def _scope_for_channel(self, channel: NavigationChannel) -> dict[str, Any] | None:
        config = self._scope_config_data()
        if channel.channel_code in set(config.get("priority_channel_codes") or []):
            return {
                "scope_code": config.get("scope_code"),
                "bbox": config.get("bbox"),
            }
        for scope_code, scope in (config.get("scopes") or {}).items():
            if channel.channel_code in set(scope.get("priority_channel_codes") or []):
                return {
                    "scope_code": scope.get("scope_code") or scope_code,
                    "bbox": scope.get("bbox"),
                }
        return None

    def _has_alias_config(self, channel_code: str) -> bool:
        return channel_code in (self._alias_config_data().get("channels") or {})

    def _primary_term_norms(self, channel: NavigationChannel) -> set[str]:
        configured = self._alias_config_data().get("channels", {}).get(channel.channel_code, {})
        values = [
            channel.channel_name,
            channel.official_name,
            channel.display_name,
            *(channel.alias_names or []),
            *configured.get("aliases", []),
            *configured.get("water_names", []),
        ]
        return {normalized for value in values if (normalized := self._norm(value))}

    def _alias_config_data(self) -> dict[str, Any]:
        if self._alias_config is None:
            self._alias_config = self._load_json(DEFAULT_ALIAS_CONFIG)
        return self._alias_config

    def _scope_config_data(self) -> dict[str, Any]:
        if self._scope_config is None:
            self._scope_config = self._load_json(DEFAULT_SCOPE_CONFIG)
        return self._scope_config

    def _load_json(self, path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    def _matched_term(self, water_name: str | None, suggested_terms: Iterable[str]) -> str | None:
        normalized_name = self._norm(water_name)
        if not normalized_name:
            return None
        for term in sorted((term for term in suggested_terms if self._norm(term)), key=lambda value: len(self._norm(value) or ""), reverse=True):
            normalized_term = self._norm(term)
            if normalized_term and (normalized_term == normalized_name or normalized_term in normalized_name or normalized_name in normalized_term):
                return term
        return None

    def _bbox_intersects(self, model, bbox: dict[str, float]):
        return (
            model.bbox_min_lng.is_not(None),
            model.bbox_min_lat.is_not(None),
            model.bbox_max_lng.is_not(None),
            model.bbox_max_lat.is_not(None),
            model.bbox_min_lng <= bbox["max_lng"],
            model.bbox_max_lng >= bbox["min_lng"],
            model.bbox_min_lat <= bbox["max_lat"],
            model.bbox_max_lat >= bbox["min_lat"],
        )

    def _bbox_intersects_plain(self, left: dict[str, float | None], right: dict[str, float | None]) -> bool:
        if any(left.get(key) is None or right.get(key) is None for key in ("min_lng", "min_lat", "max_lng", "max_lat")):
            return False
        return bool(
            (left["max_lng"] or 0) >= (right["min_lng"] or 0)
            and (left["min_lng"] or 0) <= (right["max_lng"] or 0)
            and (left["max_lat"] or 0) >= (right["min_lat"] or 0)
            and (left["min_lat"] or 0) <= (right["max_lat"] or 0)
        )

    def _bbox_dict(self, row: Any) -> dict[str, float | None] | None:
        if row is None:
            return None
        values = {
            "min_lng": self._float(getattr(row, "bbox_min_lng", None)),
            "min_lat": self._float(getattr(row, "bbox_min_lat", None)),
            "max_lng": self._float(getattr(row, "bbox_max_lng", None)),
            "max_lat": self._float(getattr(row, "bbox_max_lat", None)),
        }
        if all(value is None for value in values.values()):
            return None
        return values

    def _display_bbox_dict(self, row: Any) -> dict[str, float | None] | None:
        if row is None:
            return None
        values = {
            "min_lng": self._float(getattr(row, "display_bbox_min_lng", None)),
            "min_lat": self._float(getattr(row, "display_bbox_min_lat", None)),
            "max_lng": self._float(getattr(row, "display_bbox_max_lng", None)),
            "max_lat": self._float(getattr(row, "display_bbox_max_lat", None)),
        }
        if all(value is None for value in values.values()):
            return None
        return values

    def _expand_bbox(self, bbox: dict[str, float | None], *, margin_degree: float) -> dict[str, float]:
        return {
            "min_lng": max(-180.0, float(bbox["min_lng"] or -180.0) - margin_degree),
            "min_lat": max(-90.0, float(bbox["min_lat"] or -90.0) - margin_degree),
            "max_lng": min(180.0, float(bbox["max_lng"] or 180.0) + margin_degree),
            "max_lat": min(90.0, float(bbox["max_lat"] or 90.0) + margin_degree),
        }

    def _float(self, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return float(value)
        return float(value)

    def _int_or_none(self, value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _norm(self, value: Any) -> str | None:
        if value is None:
            return None
        text_value = str(value).strip().lower()
        if not text_value:
            return None
        return re.sub(r"[\s\t\n—\-_（）()/·]+", "", text_value)

    def _layer_priority(self, layer_name: str | None) -> int:
        return LAYER_PRIORITY.get(str(layer_name or ""), 99)

    def _dedupe_ids(self, task_ids: list[int]) -> list[int]:
        seen: set[int] = set()
        output: list[int] = []
        for task_id in task_ids:
            if task_id in seen:
                continue
            seen.add(task_id)
            output.append(task_id)
        return output
