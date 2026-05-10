"""Implementation methods for the vessel quality domain."""

from __future__ import annotations

from app.modules.vessel.shared import base as _base

globals().update({name: getattr(_base, name) for name in dir(_base) if not name.startswith("__")})


class VesselQualityMixin:
    """Implementation methods for the vessel quality domain."""

    async def _active_quality_issue_counts(self, ids: list[int]) -> dict[int, int]:
        if not ids:
            return {}
        rows = (
            await self.db.execute(
                select(VesselDataQualityIssue.vessel_profile_id, func.count(VesselDataQualityIssue.id))
                .where(
                    VesselDataQualityIssue.vessel_profile_id.in_(ids),
                    VesselDataQualityIssue.status_code.in_(ACTIVE_ISSUE_STATUSES),
                )
                .group_by(VesselDataQualityIssue.vessel_profile_id)
            )
        ).all()
        return {int(profile_id): int(count) for profile_id, count in rows if profile_id is not None}

    async def _upsert_quality_issue(
        self,
        *,
        issue_type_code: str,
        profile_id: int | None,
        object_type: str,
        object_id: str | int | None,
        normalized_key: str,
        field_name: str | None = None,
        evidence_source: str | None = None,
        severity_code: str = "MEDIUM",
        impact_scope: list[dict[str, Any]] | None = None,
    ) -> VesselDataQualityIssue:
        return await _upsert_quality_issue_in_session(
            self.db,
            issue_type_code=issue_type_code,
            profile_id=profile_id,
            object_type=object_type,
            object_id=object_id,
            normalized_key=normalized_key,
            field_name=field_name,
            evidence_source=evidence_source,
            severity_code=severity_code,
            impact_scope=impact_scope,
        )

    async def list_quality_issues(
        self,
        vessel_id: int,
        query: Any,
    ) -> PageResponse[VesselQualityIssueResponse]:
        await self._require_profile(vessel_id)
        stmt = select(VesselDataQualityIssue).where(VesselDataQualityIssue.vessel_profile_id == vessel_id)
        if getattr(query, "status_code", None):
            stmt = stmt.where(VesselDataQualityIssue.status_code == query.status_code)
        if getattr(query, "issue_type_code", None):
            stmt = stmt.where(VesselDataQualityIssue.issue_type_code == query.issue_type_code)
        total = await self.db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = (
            await self.db.execute(
                stmt.order_by(VesselDataQualityIssue.updated_at.desc(), VesselDataQualityIssue.id.desc())
                .offset((query.page - 1) * query.page_size)
                .limit(query.page_size)
            )
        ).scalars().all()
        label_map = await _load_label_map(self.db)
        return PageResponse(
            total=int(total or 0),
            page=query.page,
            page_size=query.page_size,
            items=[
                VesselQualityIssueResponse(
                    **_row_dict(row),
                    issue_type_name=label_map.get("VESSEL_QUALITY_ISSUE_TYPE", {}).get(row.issue_type_code),
                    status_name=label_map.get("VESSEL_QUALITY_ISSUE_STATUS", {}).get(row.status_code),
                )
                for row in rows
            ],
        )

    async def list_quality_issue_queue(self, query: Any) -> PageResponse[VesselQualityIssueListItemResponse]:
        stmt = select(VesselDataQualityIssue).outerjoin(
            VesselProfile,
            VesselProfile.id == VesselDataQualityIssue.vessel_profile_id,
        )
        if getattr(query, "vessel_id", None):
            stmt = stmt.where(VesselDataQualityIssue.vessel_profile_id == query.vessel_id)
        if getattr(query, "status_code", None):
            stmt = stmt.where(VesselDataQualityIssue.status_code == query.status_code)
        if getattr(query, "issue_type_code", None):
            stmt = stmt.where(VesselDataQualityIssue.issue_type_code == query.issue_type_code)
        if getattr(query, "severity_code", None):
            stmt = stmt.where(VesselDataQualityIssue.severity_code == query.severity_code)
        if getattr(query, "keyword", None):
            like_value = f"%{query.keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    VesselDataQualityIssue.issue_type_code.ilike(like_value),
                    VesselDataQualityIssue.affected_object_type.ilike(like_value),
                    VesselDataQualityIssue.affected_object_id.ilike(like_value),
                    VesselDataQualityIssue.field_name.ilike(like_value),
                    VesselDataQualityIssue.fingerprint.ilike(like_value),
                    VesselProfile.vessel_profile_code.ilike(like_value),
                    VesselProfile.ship_name.ilike(like_value),
                    VesselProfile.current_mmsi.ilike(like_value),
                )
            )
        total = await self.db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = (
            await self.db.execute(
                stmt.order_by(VesselDataQualityIssue.updated_at.desc(), VesselDataQualityIssue.id.desc())
                .offset((query.page - 1) * query.page_size)
                .limit(query.page_size)
            )
        ).scalars().all()
        label_map = await _load_label_map(self.db)
        profiles = await self._profiles_by_ids([row.vessel_profile_id for row in rows if row.vessel_profile_id])
        task_by_issue_id: dict[str, VesselGovernanceTask] = {}
        if rows:
            issue_ids = [str(row.id) for row in rows]
            task_rows = (
                await self.db.scalars(
                    select(VesselGovernanceTask)
                    .where(
                        VesselGovernanceTask.source_object_type == "VESSEL_DATA_QUALITY_ISSUE",
                        VesselGovernanceTask.source_object_id.in_(issue_ids),
                    )
                    .order_by(VesselGovernanceTask.updated_at.desc(), VesselGovernanceTask.id.desc())
                )
            ).all()
            for task in task_rows:
                task_by_issue_id.setdefault(task.source_object_id, task)
        items: list[VesselQualityIssueListItemResponse] = []
        for row in rows:
            profile = profiles.get(row.vessel_profile_id) if row.vessel_profile_id else None
            task = task_by_issue_id.get(str(row.id))
            vessel_summary = None
            if profile is not None:
                vessel_summary = VesselQualityIssueVesselSummary(
                    id=profile.id,
                    ship_name=profile.ship_name,
                    current_mmsi=profile.current_mmsi,
                    vessel_profile_code=profile.vessel_profile_code,
                    profile_status_code=profile.profile_status_code,
                    profile_status_name=label_map.get("VESSEL_PROFILE_STATUS", {}).get(profile.profile_status_code),
                )
            items.append(
                VesselQualityIssueListItemResponse(
                    **_row_dict(row),
                    issue_type_name=label_map.get("VESSEL_QUALITY_ISSUE_TYPE", {}).get(row.issue_type_code),
                    status_name=label_map.get("VESSEL_QUALITY_ISSUE_STATUS", {}).get(row.status_code),
                    vessel=vessel_summary,
                    governance_task_id=task.id if task else None,
                    governance_task_no=task.task_no if task else None,
                    governance_task_status_code=task.status_code if task else None,
                    governance_task_assigned_to=task.assigned_to if task else None,
                    action_path=self._quality_issue_action_path(row),
                    field_anchor=row.field_name,
                    recommended_actions=self._quality_issue_actions(row),
                    next_actions=self._quality_issue_actions(row),
                    explain_reason=self._quality_issue_explain_reason(row),
                    evidence_gaps=self._quality_issue_evidence_gaps(row),
                    source_object_anchor=f"VESSEL_DATA_QUALITY_ISSUE:{row.id}",
                    workbench_group="QUALITY",
                    verification_status_code=row.last_recheck_status_code or ("PASSED" if row.status_code == "RESOLVED" else "WAITING_RECHECK"),
                    verification_message=(
                        row.last_recheck_message
                        or ("问题已关闭，最近一次校验通过。" if row.status_code == "RESOLVED" else "请修复字段并重新计算资产摘要；问题关闭后对应任务才能关闭。")
                    ),
                )
            )
        return PageResponse(total=int(total or 0), page=query.page, page_size=query.page_size, items=items)

    async def recheck_quality_issue(
        self,
        issue_id: int,
        *,
        operator_id: int | None = None,
        commit: bool = True,
        close_tasks: bool = True,
    ) -> VesselQualityIssueRecheckResponse:
        issue = await self.db.get(VesselDataQualityIssue, issue_id)
        if issue is None:
            raise NotFoundError("VesselDataQualityIssue", issue_id)
        now = datetime.utcnow()
        profile: VesselProfile | None = None
        if issue.vessel_profile_id is not None:
            profile = await self.db.get(VesselProfile, issue.vessel_profile_id)
            if profile is not None:
                await self._upsert_vessel_summary(profile)
                await self.db.flush()
                await self.db.refresh(issue)
        resolved = issue.status_code == "RESOLVED"
        issue.last_rechecked_at = now
        issue.last_recheck_status_code = "PASSED" if resolved else "FAILED"
        if resolved:
            issue.last_recheck_message = "重新校验通过，质量问题已自动关闭。"
        elif profile is None:
            issue.last_recheck_message = "该质量问题缺少可重算的船舶档案上下文，需补齐来源对象后再校验。"
        else:
            issue.last_recheck_message = "重新校验仍命中，请继续修复源字段或证据。"
        latest_task: VesselGovernanceTask | None = None
        task_rows = (
            await self.db.scalars(
                select(VesselGovernanceTask)
                .where(
                    VesselGovernanceTask.source_object_type == "VESSEL_DATA_QUALITY_ISSUE",
                    VesselGovernanceTask.source_object_id == str(issue.id),
                )
                .order_by(VesselGovernanceTask.updated_at.desc(), VesselGovernanceTask.id.desc())
            )
        ).all()
        if task_rows:
            latest_task = task_rows[0]
        if resolved and close_tasks:
            for task in task_rows:
                if task.status_code in {"OPEN", "ASSIGNED", "IN_PROGRESS", "REOPENED"}:
                    task.status_code = "RESOLVED"
                    task.resolved_at = now
                    task.resolved_by = operator_id
                    task.resolution_reason = "质量问题重新校验通过，任务自动关闭"
                    task.resolution_evidence_json = {"quality_issue_recheck": "PASSED", "issue_id": issue.id}
                    task.revision = int(task.revision or 1) + 1
                    task.updated_at = now
                    latest_task = task
        await self.db.flush()
        if commit:
            await self.db.commit()
            await self.db.refresh(issue)
            if latest_task is not None:
                await self.db.refresh(latest_task)
        return VesselQualityIssueRecheckResponse(
            issue_id=issue.id,
            status_code=issue.status_code,
            recheck_status_code=issue.last_recheck_status_code or ("PASSED" if resolved else "FAILED"),
            recheck_message=issue.last_recheck_message or "",
            resolved=resolved,
            rechecked_at=issue.last_rechecked_at or now,
            governance_task_id=latest_task.id if latest_task else None,
            governance_task_status_code=latest_task.status_code if latest_task else None,
        )

    def _quality_issue_action_path(self, row: VesselDataQualityIssue) -> str | None:
        if row.vessel_profile_id:
            suffix = f"?quality_issue_id={row.id}"
            if row.field_name:
                suffix = f"{suffix}&field={row.field_name}"
            return f"/vessels/{row.vessel_profile_id}/edit{suffix}"
        return f"/vessels/quality?quality_issue_id={row.id}"

    def _quality_issue_actions(self, row: VesselDataQualityIssue) -> list[VesselRecommendedAction]:
        target_path = self._quality_issue_action_path(row)
        if target_path is None:
            return []
        label = "定位字段并修复"
        description = "修复源数据后重新计算资产摘要，系统校验通过才关闭问题。"
        if row.issue_type_code == "AIS_UNMATCHED":
            label = "核对 MMSI 与 AIS 映射"
            description = "核对 MMSI、AIS 最新快照和未匹配来源，重新扫描后自动关闭。"
        return [
            VesselRecommendedAction(
                action_type="FIX_SOURCE",
                label=label,
                target_path=target_path,
                target_object_type="VESSEL_DATA_QUALITY_ISSUE",
                target_object_id=str(row.id),
                required_fields=[row.field_name] if row.field_name else [],
                source_object_anchor=f"VESSEL_DATA_QUALITY_ISSUE:{row.id}",
                workbench_group="QUALITY",
                description=description,
            )
        ]

    @staticmethod
    def _quality_issue_explain_reason(row: VesselDataQualityIssue) -> str:
        parts = [f"{row.issue_type_code} 命中 {row.affected_object_type}:{row.affected_object_id}"]
        if row.field_name:
            parts.append(f"字段 {row.field_name} 需要修复或补证")
        if row.evidence_source:
            parts.append(f"来源 {row.evidence_source}")
        return "，".join(parts) + "。"

    @staticmethod
    def _quality_issue_evidence_gaps(row: VesselDataQualityIssue) -> list[str]:
        gaps: list[str] = []
        if row.field_name:
            gaps.append(row.field_name)
        if row.issue_type_code == "AIS_UNMATCHED":
            gaps.extend(["MMSI 与 AIS 映射", "AIS 最新快照"])
        elif row.issue_type_code == "MMSI_CONFLICT":
            gaps.extend(["冲突船舶核对", "MMSI 当前有效性"])
        elif row.issue_type_code == "PRIMARY_RELATION_MISSING":
            gaps.extend(["主所有方/经营方", "主体关系结论"])
        else:
            gaps.append("重新校验通过记录")
        return list(dict.fromkeys(gaps))
