"""Round 10 vessel governance loop service."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.modules.approval.client import ApprovalClient
from app.models.vessel import (
    VesselBlacklistSignal,
    VesselDataQualityIssue,
    VesselGovernanceTask,
    VesselProfile,
    VesselRiskReview,
    VesselRiskSignal,
)
from app.modules.vessel.schemas import (
    PageResponse,
    VesselBlacklistSignalCreateRequest,
    VesselBlacklistSignalGlobalQuery,
    VesselBlacklistSignalListItemResponse,
    VesselBlacklistSignalResponse,
    VesselBlacklistSignalUpdateRequest,
    VesselGovernanceTaskActionRequest,
    VesselGovernanceTaskQuery,
    VesselGovernanceTaskResponse,
    VesselQualityIssueVesselSummary,
    VesselRiskReviewRequest,
    VesselRiskReviewResponse,
)
from app.modules.vessel.asset.service import VesselAssetService
from app.modules.vessel.quality.service import VesselQualityService
from app.modules.vessel.governance_dashboard import VesselGovernanceDashboardMixin
from app.modules.vessel.governance_responses import VesselGovernanceResponseMixin
from app.modules.vessel.governance_rules import VesselGovernanceRulesMixin
from app.modules.vessel.governance_sync import VesselGovernanceSyncMixin
from app.modules.vessel.shared.base import (
    COMPLIANCE_ACTIVE_STATUSES,
    COMPLIANCE_CLOSED_STATUSES,
    _load_label_map,
    _jsonable,
    _risk_fingerprint,
    _row_dict,
)


ACTIVE_TASK_STATUSES = {"OPEN", "ASSIGNED", "IN_PROGRESS", "REOPENED"}
EVIDENCE_APPROVAL_SOURCE_TYPES = {"VESSEL_CONTROLLER_EVIDENCE", "VESSEL_AFFILIATION_EVIDENCE"}


def _utcnow() -> datetime:
    return datetime.utcnow()


def _is_active_blacklist(row: VesselBlacklistSignal, today: date | None = None) -> bool:
    today = today or date.today()
    if row.status_code != "ACTIVE" or row.voided_at is not None:
        return False
    if row.effective_to and row.effective_to < today:
        return False
    return True


class VesselGovernanceService(
    VesselGovernanceSyncMixin,
    VesselGovernanceDashboardMixin,
    VesselGovernanceRulesMixin,
    VesselGovernanceResponseMixin,
):
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._sync_batch_id: int | None = None
        self._sync_rule_results: dict[str, dict[str, int]] | None = None
        self._sync_affected_vessel_ids: set[int] = set()

    async def list_tasks(self, query: VesselGovernanceTaskQuery) -> PageResponse[VesselGovernanceTaskResponse]:
        stmt = select(VesselGovernanceTask).outerjoin(VesselProfile, VesselProfile.id == VesselGovernanceTask.vessel_profile_id)
        if query.status_code:
            stmt = stmt.where(VesselGovernanceTask.status_code == query.status_code)
        if query.task_type_code:
            stmt = stmt.where(VesselGovernanceTask.task_type_code == query.task_type_code)
        if query.priority_code:
            stmt = stmt.where(VesselGovernanceTask.priority_code == query.priority_code)
        if query.vessel_id:
            stmt = stmt.where(VesselGovernanceTask.vessel_profile_id == query.vessel_id)
        if query.source_object_type:
            stmt = stmt.where(VesselGovernanceTask.source_object_type == query.source_object_type)
        if query.assigned_to:
            stmt = stmt.where(VesselGovernanceTask.assigned_to == query.assigned_to)
        if query.keyword:
            like_value = f"%{query.keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    VesselGovernanceTask.task_no.ilike(like_value),
                    VesselGovernanceTask.title.ilike(like_value),
                    VesselGovernanceTask.description.ilike(like_value),
                    VesselGovernanceTask.source_object_id.ilike(like_value),
                    VesselGovernanceTask.fingerprint.ilike(like_value),
                    VesselProfile.ship_name.ilike(like_value),
                    VesselProfile.current_mmsi.ilike(like_value),
                    VesselProfile.vessel_profile_code.ilike(like_value),
                )
            )
        total = int(await self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        rows = (
            await self.db.scalars(
                stmt.order_by(VesselGovernanceTask.last_seen_at.desc(), VesselGovernanceTask.id.desc())
                .offset((query.page - 1) * query.page_size)
                .limit(query.page_size)
            )
        ).all()
        profiles = await self._profiles_by_ids([row.vessel_profile_id for row in rows if row.vessel_profile_id])
        approval_info = await self._approval_info_by_task(rows)
        label_map = await _load_label_map(self.db)
        return PageResponse(
            total=total,
            page=query.page,
            page_size=query.page_size,
            items=[
                self._task_response(
                    row,
                    label_map,
                    profiles.get(row.vessel_profile_id),
                    approval_info.get((row.source_object_type, row.source_object_id)),
                )
                for row in rows
            ],
        )

    async def update_task(
        self,
        task_id: int,
        payload: VesselGovernanceTaskActionRequest,
        *,
        operator_id: int | None = None,
    ) -> VesselGovernanceTaskResponse:
        row = await self.db.get(VesselGovernanceTask, task_id)
        if row is None:
            raise NotFoundError("VesselGovernanceTask", task_id)
        self._ensure_revision(row, payload.revision)
        action = payload.action_code.upper()
        now = _utcnow()
        if action == "ASSIGN":
            if payload.assigned_to is None:
                raise ValidationError("指派治理任务必须提供 assigned_to")
            row.assigned_to = payload.assigned_to
            row.assigned_at = now
            row.status_code = "ASSIGNED"
        elif action == "START":
            row.started_at = row.started_at or now
            row.status_code = "IN_PROGRESS"
        elif action == "RESOLVE":
            if not payload.reason:
                raise ValidationError("解决治理任务必须填写 reason")
            await self._ensure_resolution_verified(row, operator_id=operator_id)
            row.status_code = "RESOLVED"
            row.resolved_at = now
            row.resolved_by = operator_id
            row.resolution_reason = payload.reason
            row.resolution_evidence_json = payload.evidence_json
            await self._apply_resolution(row, payload, operator_id=operator_id)
        elif action == "CANNOT_RESOLVE":
            if not payload.reason:
                raise ValidationError("无法解决治理任务必须填写 reason")
            row.status_code = "CANNOT_RESOLVE"
            row.resolved_at = now
            row.resolved_by = operator_id
            row.resolution_reason = payload.reason
            row.resolution_evidence_json = payload.evidence_json
        elif action == "VOID":
            row.status_code = "VOIDED"
            row.resolved_at = now
            row.resolved_by = operator_id
            row.resolution_reason = payload.reason or "治理任务作废"
        elif action == "REOPEN":
            row.status_code = "REOPENED"
            row.reopen_count = int(row.reopen_count or 0) + 1
            row.resolved_at = None
            row.resolved_by = None
            row.resolution_reason = None
            row.resolution_evidence_json = None
        else:
            raise ValidationError(f"unsupported governance task action: {payload.action_code}")
        row.revision = int(row.revision or 1) + 1
        row.updated_at = now
        await self._refresh_after_governance(row.vessel_profile_id, operator_id=operator_id, row=row)
        await self.db.commit()
        await self.db.refresh(row)
        label_map = await _load_label_map(self.db)
        profile = await self.db.get(VesselProfile, row.vessel_profile_id) if row.vessel_profile_id else None
        approval_info = await self._approval_info_by_task([row])
        return self._task_response(row, label_map, profile, approval_info.get((row.source_object_type, row.source_object_id)))

    async def create_risk_review(
        self,
        vessel_id: int,
        payload: VesselRiskReviewRequest,
        *,
        operator_id: int | None = None,
    ) -> VesselRiskReviewResponse:
        await self._require_profile(vessel_id)
        signal: VesselRiskSignal | None = None
        if payload.risk_signal_id is not None:
            signal = await self.db.get(VesselRiskSignal, payload.risk_signal_id)
            if signal is None or signal.vessel_profile_id != vessel_id:
                raise NotFoundError("VesselRiskSignal", payload.risk_signal_id)
        task: VesselGovernanceTask | None = None
        if payload.governance_task_id is not None:
            task = await self.db.get(VesselGovernanceTask, payload.governance_task_id)
            if task is None or task.vessel_profile_id != vessel_id:
                raise NotFoundError("VesselGovernanceTask", payload.governance_task_id)
            if signal is None and task.source_object_type == "VESSEL_RISK_SIGNAL":
                signal = await self.db.get(VesselRiskSignal, int(task.source_object_id))
        now = _utcnow()
        from_status = signal.status_code if signal else None
        from_level = signal.risk_level if signal else None
        to_status = payload.to_status_code or self._status_from_review_action(payload.review_action_code, from_status)
        level_after = payload.risk_level_after or from_level
        review = VesselRiskReview(
            vessel_profile_id=vessel_id,
            risk_signal_id=signal.id if signal else payload.risk_signal_id,
            governance_task_id=task.id if task else payload.governance_task_id,
            review_action_code=payload.review_action_code,
            from_status_code=from_status,
            to_status_code=to_status,
            risk_level_before=from_level,
            risk_level_after=level_after,
            evidence_json=payload.evidence_json,
            review_reason=payload.review_reason,
            reviewed_by=operator_id,
            reviewed_at=now,
        )
        self.db.add(review)
        await self.db.flush()
        requires_approval = self._risk_review_requires_approval(payload.review_action_code, to_status)
        if requires_approval:
            approval = await self._submit_vessel_approval(
                object_type_code="VESSEL_RISK_REVIEW",
                object_id=int(review.id),
                object_name=f"{signal.risk_type_code} 风险复核" if signal else "船舶风险复核",
                change_type_code="UPDATE",
                operator_id=operator_id,
                comment=payload.review_reason or "提交风险复核审核",
                summary_json={
                    "vessel_profile_id": vessel_id,
                    "risk_signal_id": signal.id if signal else payload.risk_signal_id,
                    "governance_task_id": task.id if task else payload.governance_task_id,
                    "review_action_code": payload.review_action_code,
                    "from_status_code": from_status,
                    "to_status_code": to_status,
                    "risk_level_before": from_level,
                    "risk_level_after": level_after,
                    "review_reason": payload.review_reason,
                },
                after_snapshot_json={
                    "review": _row_dict(review),
                    "risk_signal": _row_dict(signal) if signal else None,
                    "governance_task": _row_dict(task) if task else None,
                },
            )
            if signal is not None and signal.status_code in COMPLIANCE_ACTIVE_STATUSES:
                signal.status_code = "IN_REVIEW"
                signal.evidence_json = {
                    **(signal.evidence_json or {}),
                    "pending_risk_review": {
                        "risk_review_id": review.id,
                        "approval_instance_id": approval.id,
                        "intended_status_code": to_status,
                    },
                }
                signal.updated_at = now
                signal.revision = int(signal.revision or 1) + 1
            if task is not None and task.status_code in ACTIVE_TASK_STATUSES:
                task.source_status_code = "IN_REVIEW"
                task.status_code = "IN_PROGRESS"
                task.impact_summary_json = {
                    **(task.impact_summary_json or {}),
                    "approval_instance_id": approval.id,
                    "approval_instance_no": approval.instance_no,
                    "business_sync_status_code": "WAITING_APPROVAL",
                }
                task.updated_at = now
                task.revision = int(task.revision or 1) + 1
            await self.db.commit()
            await self.db.refresh(review)
            return self._risk_review_response(review, approval)
        if signal is not None:
            signal.status_code = to_status or signal.status_code
            if payload.risk_level_after:
                signal.risk_level = payload.risk_level_after
            signal.evidence_json = {**(signal.evidence_json or {}), "risk_reviews": [{**(payload.evidence_json or {}), "reviewed_at": now.isoformat()}]}
            if signal.status_code in COMPLIANCE_CLOSED_STATUSES:
                if not payload.review_reason:
                    raise ValidationError("关闭风险必须填写 review_reason")
                signal.resolution_reason = payload.review_reason
                signal.resolved_by = operator_id
                signal.resolved_at = now
            signal.revision = int(signal.revision or 1) + 1
            signal.updated_at = now
        if task is not None and task.status_code in ACTIVE_TASK_STATUSES and to_status in COMPLIANCE_CLOSED_STATUSES:
            task.status_code = "RESOLVED"
            task.resolved_at = now
            task.resolved_by = operator_id
            task.resolution_reason = payload.review_reason or "风险复核关闭"
            task.resolution_evidence_json = payload.evidence_json
            task.revision = int(task.revision or 1) + 1
        await self.db.flush()
        if to_status in COMPLIANCE_CLOSED_STATUSES:
            await self._refresh_after_governance(vessel_id, operator_id=operator_id, row=task)
        elif task is not None:
            impact = dict(task.impact_summary_json or {})
            impact["round9_fact_refresh"] = "RECORDED_FOR_NEXT_ANALYSIS_RUN"
            task.impact_summary_json = impact
        await self.db.commit()
        await self.db.refresh(review)
        return self._risk_review_response(review)

    async def list_blacklist_signals(self, vessel_id: int) -> list[VesselBlacklistSignalResponse]:
        await self._require_profile(vessel_id)
        rows = (
            await self.db.scalars(
                select(VesselBlacklistSignal)
                .where(VesselBlacklistSignal.vessel_profile_id == vessel_id)
                .order_by(VesselBlacklistSignal.voided_at.asc().nullsfirst(), VesselBlacklistSignal.updated_at.desc())
            )
        ).all()
        label_map = await _load_label_map(self.db)
        return [self._blacklist_response(row, label_map) for row in rows]

    async def list_blacklist_signal_queue(self, query: VesselBlacklistSignalGlobalQuery) -> PageResponse[VesselBlacklistSignalListItemResponse]:
        stmt = select(VesselBlacklistSignal).join(VesselProfile, VesselProfile.id == VesselBlacklistSignal.vessel_profile_id)
        if query.signal_id:
            stmt = stmt.where(VesselBlacklistSignal.id == query.signal_id)
        if query.vessel_id:
            stmt = stmt.where(VesselBlacklistSignal.vessel_profile_id == query.vessel_id)
        if query.list_type_code:
            stmt = stmt.where(VesselBlacklistSignal.list_type_code == query.list_type_code)
        if query.status_code:
            stmt = stmt.where(VesselBlacklistSignal.status_code == query.status_code)
        if query.risk_level:
            stmt = stmt.where(VesselBlacklistSignal.risk_level == query.risk_level)
        if query.keyword:
            like_value = f"%{query.keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    VesselBlacklistSignal.list_type_code.ilike(like_value),
                    VesselBlacklistSignal.signal_type_code.ilike(like_value),
                    VesselBlacklistSignal.evidence_summary.ilike(like_value),
                    VesselProfile.vessel_profile_code.ilike(like_value),
                    VesselProfile.ship_name.ilike(like_value),
                    VesselProfile.current_mmsi.ilike(like_value),
                )
            )
        total = int(await self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        rows = (
            await self.db.scalars(
                stmt.order_by(VesselBlacklistSignal.updated_at.desc(), VesselBlacklistSignal.id.desc())
                .offset((query.page - 1) * query.page_size)
                .limit(query.page_size)
            )
        ).all()
        label_map = await _load_label_map(self.db)
        profiles = await self._profiles_by_ids([row.vessel_profile_id for row in rows])
        tasks_by_signal: dict[str, VesselGovernanceTask] = {}
        risks_by_signal: dict[int, VesselRiskSignal] = {}
        if rows:
            signal_ids = [str(row.id) for row in rows]
            task_rows = (
                await self.db.scalars(
                    select(VesselGovernanceTask)
                    .where(
                        VesselGovernanceTask.source_object_type == "VESSEL_BLACKLIST_SIGNAL",
                        VesselGovernanceTask.source_object_id.in_(signal_ids),
                    )
                    .order_by(VesselGovernanceTask.updated_at.desc(), VesselGovernanceTask.id.desc())
                )
            ).all()
            for task in task_rows:
                tasks_by_signal.setdefault(task.source_object_id, task)
            risk_rows = (
                await self.db.scalars(
                    select(VesselRiskSignal).where(
                        VesselRiskSignal.risk_type_code == "BLACKLIST_SIGNAL",
                        VesselRiskSignal.vessel_profile_id.in_([row.vessel_profile_id for row in rows]),
                    )
                )
            ).all()
            for risk in risk_rows:
                evidence = risk.evidence_json or {}
                signal_id = evidence.get("blacklist_signal_id")
                if signal_id is not None and int(signal_id) in {row.id for row in rows}:
                    risks_by_signal.setdefault(int(signal_id), risk)
        items: list[VesselBlacklistSignalListItemResponse] = []
        for row in rows:
            profile = profiles.get(row.vessel_profile_id)
            task = tasks_by_signal.get(str(row.id))
            risk = risks_by_signal.get(row.id)
            vessel = None
            if profile is not None:
                vessel = VesselQualityIssueVesselSummary(
                    id=profile.id,
                    ship_name=profile.ship_name,
                    current_mmsi=profile.current_mmsi,
                    vessel_profile_code=profile.vessel_profile_code,
                    profile_status_code=profile.profile_status_code,
                    profile_status_name=label_map.get("VESSEL_PROFILE_STATUS", {}).get(profile.profile_status_code),
                )
            items.append(
                VesselBlacklistSignalListItemResponse(
                    **self._blacklist_response(row, label_map).model_dump(),
                    vessel=vessel,
                    governance_task_id=task.id if task else None,
                    governance_task_no=task.task_no if task else None,
                    governance_task_status_code=task.status_code if task else None,
                    governance_task_assigned_to=task.assigned_to if task else None,
                    risk_signal_id=risk.id if risk else None,
                    risk_signal_status_code=risk.status_code if risk else None,
                    risk_signal_level=risk.risk_level if risk else None,
                )
            )
        return PageResponse(total=total, page=query.page, page_size=query.page_size, items=items)

    async def create_blacklist_signal(
        self,
        vessel_id: int,
        payload: VesselBlacklistSignalCreateRequest,
        *,
        operator_id: int | None = None,
    ) -> VesselBlacklistSignalResponse:
        await self._require_profile(vessel_id)
        data = payload.model_dump(exclude_none=True)
        if data.get("effective_to") and data["effective_to"] < date.today() and data.get("status_code", "ACTIVE") == "ACTIVE":
            data["status_code"] = "EXPIRED"
        row = VesselBlacklistSignal(vessel_profile_id=vessel_id, **data)
        self.db.add(row)
        await self.db.flush()
        await self._upsert_blacklist_risk(row, operator_id=operator_id)
        await self.sync_tasks()
        await self._refresh_after_governance(vessel_id, operator_id=operator_id)
        await self.db.commit()
        await self.db.refresh(row)
        return self._blacklist_response(row, await _load_label_map(self.db))

    async def update_blacklist_signal(
        self,
        vessel_id: int,
        signal_id: int,
        payload: VesselBlacklistSignalUpdateRequest,
        *,
        operator_id: int | None = None,
    ) -> VesselBlacklistSignalResponse:
        await self._require_profile(vessel_id)
        row = await self.db.get(VesselBlacklistSignal, signal_id)
        if row is None or row.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselBlacklistSignal", signal_id)
        self._ensure_revision(row, payload.revision)
        updates = payload.model_dump(exclude_none=True)
        updates.pop("revision", None)
        updates.pop("reason", None)
        if not updates:
            raise ValidationError("no update fields provided")
        for key, value in updates.items():
            setattr(row, key, value)
        if row.effective_to and row.effective_to < date.today() and row.status_code == "ACTIVE":
            row.status_code = "EXPIRED"
        row.revision = int(row.revision or 1) + 1
        row.updated_at = _utcnow()
        await self._upsert_blacklist_risk(row, operator_id=operator_id)
        await self.sync_tasks()
        await self._refresh_after_governance(vessel_id, operator_id=operator_id)
        await self.db.commit()
        await self.db.refresh(row)
        return self._blacklist_response(row, await _load_label_map(self.db))

    async def void_blacklist_signal(
        self,
        vessel_id: int,
        signal_id: int,
        payload: Any,
        *,
        operator_id: int | None = None,
    ) -> VesselBlacklistSignalResponse:
        await self._require_profile(vessel_id)
        row = await self.db.get(VesselBlacklistSignal, signal_id)
        if row is None or row.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselBlacklistSignal", signal_id)
        self._ensure_revision(row, getattr(payload, "revision", None))
        now = _utcnow()
        approval = await self._submit_vessel_approval(
            object_type_code="VESSEL_BLACKLIST_SIGNAL",
            object_id=int(row.id),
            object_name=f"{row.list_type_code} / {row.signal_type_code}",
            change_type_code="UPDATE",
            operator_id=operator_id,
            comment=getattr(payload, "reason", None) or "提交名单信号解除/作废审核",
            summary_json={
                "vessel_profile_id": vessel_id,
                "blacklist_signal_id": row.id,
                "review_action_code": "VOID",
                "reason": getattr(payload, "reason", None) or "名单信号作废",
            },
            before_snapshot_json=_row_dict(row),
            after_snapshot_json={
                **_row_dict(row),
                "pending_status_code": "VOIDED",
                "pending_void_reason": getattr(payload, "reason", None) or "名单信号作废",
            },
        )
        row.status_code = "IN_REVIEW"
        row.evidence_json = {
            **(row.evidence_json or {}),
            "pending_blacklist_review": {
                "approval_instance_id": approval.id,
                "approval_instance_no": approval.instance_no,
                "intended_status_code": "VOIDED",
            },
        }
        row.revision = int(row.revision or 1) + 1
        row.updated_at = now
        await self._refresh_after_governance(vessel_id, operator_id=operator_id)
        await self.db.commit()
        await self.db.refresh(row)
        return self._blacklist_response(row, await _load_label_map(self.db))

    async def _apply_resolution(
        self,
        task: VesselGovernanceTask,
        payload: VesselGovernanceTaskActionRequest,
        *,
        operator_id: int | None,
    ) -> None:
        now = _utcnow()
        if task.source_object_type == "VESSEL_DATA_QUALITY_ISSUE":
            issue = await self.db.get(VesselDataQualityIssue, int(task.source_object_id))
            if issue is not None and issue.status_code == "RESOLVED":
                issue.status_code = "RESOLVED"
                issue.resolved_at = now
                issue.resolved_by = operator_id
                issue.resolved_evidence = payload.reason
                issue.updated_at = now
        elif task.source_object_type == "VESSEL_RISK_SIGNAL":
            signal = await self.db.get(VesselRiskSignal, int(task.source_object_id))
            if signal is not None and signal.status_code in COMPLIANCE_ACTIVE_STATUSES:
                signal.status_code = "CLOSED"
                signal.resolved_at = now
                signal.resolved_by = operator_id
                signal.resolution_reason = payload.reason
                signal.evidence_json = {**(signal.evidence_json or {}), "governance_resolution": payload.evidence_json or {}}
                signal.revision = int(signal.revision or 1) + 1

    async def _ensure_resolution_verified(self, task: VesselGovernanceTask, *, operator_id: int | None = None) -> None:
        if task.source_object_type == "VESSEL_DATA_QUALITY_ISSUE":
            result = await VesselQualityService(self.db).recheck_quality_issue(
                int(task.source_object_id),
                operator_id=operator_id,
                commit=False,
                close_tasks=False,
            )
            if not result.resolved:
                raise ValidationError(result.recheck_message or "质量问题仍未通过重新校验，不能直接关闭治理任务")
        elif task.source_object_type == "VESSEL_RISK_SIGNAL":
            signal = await self.db.get(VesselRiskSignal, int(task.source_object_id))
            if signal is not None:
                from app.modules.vessel.compliance.service import VesselComplianceService

                await VesselComplianceService(self.db).refresh_compliance_risk(signal.vessel_profile_id, operator_id=operator_id)
                signal = await self.db.get(VesselRiskSignal, int(task.source_object_id))
            if signal is not None and signal.status_code in COMPLIANCE_ACTIVE_STATUSES:
                raise ValidationError("风险仍命中规则，不能直接关闭治理任务；请先补证、修复数据或提交风险复核")
        elif task.source_object_type in EVIDENCE_APPROVAL_SOURCE_TYPES:
            approval_info = await self._approval_info_by_task([task])
            approval_path = (approval_info.get((task.source_object_type, task.source_object_id)) or {}).get("approval_action_path")
            suffix = f"：{approval_path}" if approval_path else ""
            raise ValidationError(f"证据审核类治理任务必须在审批中心处理，不能通过治理任务直接关闭{suffix}")
        elif task.source_object_type == "VESSEL_BLACKLIST_SIGNAL":
            approval_info = await self._approval_info_by_task([task])
            approval_path = (approval_info.get((task.source_object_type, task.source_object_id)) or {}).get("approval_action_path")
            suffix = f"：{approval_path}" if approval_path else ""
            raise ValidationError(f"名单复核/解除必须在审批中心处理，不能通过治理任务直接关闭{suffix}")

    async def _upsert_blacklist_risk(self, row: VesselBlacklistSignal, *, operator_id: int | None = None) -> None:
        if not _is_active_blacklist(row):
            await self._close_blacklist_risk(row, reason="名单信号已失效", operator_id=operator_id)
            return
        now = _utcnow()
        fingerprint = _risk_fingerprint(row.vessel_profile_id, "BLACKLIST_SIGNAL", row.signal_type_code, f"blacklist:{row.id}")
        existing = await self.db.scalar(
            select(VesselRiskSignal).where(
                VesselRiskSignal.fingerprint == fingerprint,
                VesselRiskSignal.status_code.in_(COMPLIANCE_ACTIVE_STATUSES),
            )
        )
        evidence = {
            "blacklist_signal_id": row.id,
            "list_type_code": row.list_type_code,
            "signal_type_code": row.signal_type_code,
            "evidence_summary": row.evidence_summary,
        }
        if existing is None:
            existing = VesselRiskSignal(
                vessel_profile_id=row.vessel_profile_id,
                risk_type_code="BLACKLIST_SIGNAL",
                risk_level=row.risk_level,
                rule_code=row.signal_type_code,
                status_code="OPEN",
                confidence_level=row.confidence_level,
                fingerprint=fingerprint,
                evidence_json=evidence,
                source_trace_json=[{"source": "vessel_blacklist_signal", "id": row.id}],
                uncertainty_notes_json=[],
                first_detected_at=now,
                last_detected_at=now,
            )
            self.db.add(existing)
        else:
            existing.risk_level = row.risk_level
            existing.confidence_level = row.confidence_level
            existing.evidence_json = evidence
            existing.last_detected_at = now
            existing.updated_at = now

    async def _close_blacklist_risk(
        self,
        row: VesselBlacklistSignal,
        *,
        reason: str,
        operator_id: int | None = None,
    ) -> None:
        now = _utcnow()
        fingerprint = _risk_fingerprint(row.vessel_profile_id, "BLACKLIST_SIGNAL", row.signal_type_code, f"blacklist:{row.id}")
        risks = (
            await self.db.scalars(
                select(VesselRiskSignal).where(
                    VesselRiskSignal.fingerprint == fingerprint,
                    VesselRiskSignal.status_code.in_(COMPLIANCE_ACTIVE_STATUSES),
                )
            )
        ).all()
        for risk in risks:
            risk.status_code = "CLOSED"
            risk.resolved_at = now
            risk.resolved_by = operator_id
            risk.resolution_reason = reason
            risk.evidence_json = {
                **(risk.evidence_json or {}),
                "blacklist_signal_status": row.status_code,
                "blacklist_signal_id": row.id,
            }
            risk.revision = int(risk.revision or 1) + 1
            risk.updated_at = now

    async def _refresh_after_governance(
        self,
        vessel_id: int | None,
        *,
        operator_id: int | None = None,
        row: VesselGovernanceTask | None = None,
    ) -> None:
        if vessel_id is None:
            return
        impact = dict(row.impact_summary_json or {}) if row is not None else {}
        try:
            from app.modules.vessel.compliance.service import VesselComplianceService

            await VesselAssetService(self.db)._refresh_summary_best_effort(vessel_id)
            await VesselComplianceService(self.db)._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
            impact["summary_refresh"] = "SUCCESS"
            impact["risk_refresh"] = "SUCCESS"
            impact["round9_fact_refresh"] = "RECORDED_FOR_NEXT_ANALYSIS_RUN"
        except Exception as exc:  # noqa: BLE001
            impact["refresh_error"] = str(exc)
            await self.db.rollback()
        if row is not None:
            row.impact_summary_json = impact

    async def _profiles_by_ids(self, ids: list[int | None]) -> dict[int, VesselProfile]:
        real_ids = sorted({int(item) for item in ids if item})
        if not real_ids:
            return {}
        rows = (await self.db.scalars(select(VesselProfile).where(VesselProfile.id.in_(real_ids)))).all()
        return {int(row.id): row for row in rows}

    async def _require_profile(self, vessel_id: int) -> VesselProfile:
        row = await self.db.get(VesselProfile, vessel_id)
        if row is None:
            raise NotFoundError("VesselProfile", vessel_id)
        return row

    @staticmethod
    def _ensure_revision(row: Any, revision: int | None) -> None:
        if revision is None or int(row.revision or 1) != int(revision):
            raise ConflictError("数据已被其他操作更新，请刷新后重试", code="REVISION_CONFLICT")

    @staticmethod
    def _status_from_review_action(action: str, fallback: str | None) -> str:
        return {
            "ADD_EVIDENCE": "EVIDENCE_ADDED",
            "MITIGATE": "MITIGATED",
            "CLOSE": "CLOSED",
            "FALSE_POSITIVE": "FALSE_POSITIVE",
        }.get(action.upper(), fallback or "IN_REVIEW")

    @staticmethod
    def _risk_review_requires_approval(action: str, to_status: str | None) -> bool:
        return (to_status in COMPLIANCE_CLOSED_STATUSES) or action.upper() in {"MITIGATE", "CLOSE", "FALSE_POSITIVE"}

    async def _submit_vessel_approval(
        self,
        *,
        object_type_code: str,
        object_id: int,
        object_name: str | None,
        change_type_code: str,
        operator_id: int | None,
        comment: str,
        summary_json: dict[str, Any],
        after_snapshot_json: dict[str, Any],
        before_snapshot_json: dict[str, Any] | None = None,
    ) -> Any:
        return await ApprovalClient(self.db).submit(
            {
                "subject_type": object_type_code,
                "trigger_action_code": change_type_code,
                "subject_id": object_id,
                "subject_ref": f"{object_type_code}:{object_id}",
                "subject_code": str(object_id),
                "subject_name": object_name or f"{object_type_code} #{object_id}",
                "subject_path": self._subject_path(object_type_code, object_id, summary_json),
                "before_snapshot_json": _jsonable(before_snapshot_json) if before_snapshot_json else None,
                "after_snapshot_json": _jsonable(after_snapshot_json),
                "diff_json": None,
                "summary_json": _jsonable(summary_json),
                "submit_payload_json": {
                    "object_type_code": object_type_code,
                    "object_id": object_id,
                    "comment": comment,
                    **_jsonable(summary_json),
                },
                "idempotency_key": f"VESSEL:{object_type_code}:{object_id}:{change_type_code}",
            },
            submitter_id=operator_id,
        )

    @staticmethod
    def _subject_path(object_type_code: str, object_id: int, summary_json: dict[str, Any]) -> str:
        vessel_id = summary_json.get("vessel_profile_id")
        if object_type_code == "VESSEL_RISK_REVIEW":
            return f"/vessels/{vessel_id}/compliance?risk_review_id={object_id}" if vessel_id else "/vessels/compliance-risks"
        if object_type_code == "VESSEL_BLACKLIST_SIGNAL":
            vessel_query = f"&vessel_id={vessel_id}" if vessel_id else ""
            return f"/vessels/blacklist-signals?blacklist_signal_id={object_id}{vessel_query}"
        return f"/vessels/{vessel_id}/profile-card" if vessel_id else "/vessels"

    async def _approval_info_by_task(self, rows: list[VesselGovernanceTask]) -> dict[tuple[str, str], dict[str, Any]]:
        result: dict[tuple[str, str], dict[str, Any]] = {}
        client = ApprovalClient(self.db)
        for subject_type in EVIDENCE_APPROVAL_SOURCE_TYPES:
            ids = [
                int(row.source_object_id)
                for row in rows
                if row.source_object_type == subject_type and str(row.source_object_id).isdigit()
            ]
            states = await client.latest_state_for_subjects(subject_type=subject_type, subject_ids=ids)
            for subject_id, approval in states.items():
                result[(subject_type, str(subject_id))] = self._approval_info_response(approval)
        risk_rows = [row for row in rows if row.source_object_type == "VESSEL_RISK_SIGNAL" and str(row.source_object_id).isdigit()]
        blacklist_rows = [row for row in rows if row.source_object_type == "VESSEL_BLACKLIST_SIGNAL" and str(row.source_object_id).isdigit()]
        if risk_rows:
            risk_ids = [int(row.source_object_id) for row in risk_rows]
            review_rows = (
                await self.db.scalars(
                    select(VesselRiskReview)
                    .where(VesselRiskReview.risk_signal_id.in_(risk_ids))
                    .order_by(VesselRiskReview.updated_at.desc(), VesselRiskReview.id.desc())
                )
            ).all()
            latest_review_by_signal: dict[int, int] = {}
            for review in review_rows:
                latest_review_by_signal.setdefault(int(review.risk_signal_id), int(review.id))
            states = await client.latest_state_for_subjects(
                subject_type="VESSEL_RISK_REVIEW",
                subject_ids=list(latest_review_by_signal.values()),
            )
            for signal_id, review_id in latest_review_by_signal.items():
                approval = states.get(review_id)
                if approval:
                    result[("VESSEL_RISK_SIGNAL", str(signal_id))] = self._approval_info_response(approval)
        if blacklist_rows:
            signal_ids = [int(row.source_object_id) for row in blacklist_rows]
            states = await client.latest_state_for_subjects(subject_type="VESSEL_BLACKLIST_SIGNAL", subject_ids=signal_ids)
            for subject_id, approval in states.items():
                result[("VESSEL_BLACKLIST_SIGNAL", str(subject_id))] = self._approval_info_response(approval)
        return result

    @staticmethod
    def _approval_info_response(approval: Any) -> dict[str, Any]:
        status_name = {
            "PENDING": "待启动",
            "RUNNING": "审批中",
            "APPROVED": "已通过",
            "REJECTED": "已驳回",
            "RETURNED": "已退回",
            "CANCELED": "已取消",
            "FAILED": "失败",
        }.get(approval.status_code, approval.status_code)
        waiting = approval.status_code in {"PENDING", "RUNNING", "RETURNED"}
        return {
            "approval_instance_id": int(approval.id),
            "approval_instance_no": approval.instance_no,
            "approval_status_code": approval.status_code,
            "approval_status_name": status_name,
            "approval_action_path": f"/approvals/instances/{approval.id}",
            "business_sync_status_code": "WAITING_APPROVAL" if waiting else "SYNCED",
            "business_sync_message": (
                "审批中心处理完成后将自动同步主体结论、合规风险和治理任务"
                if waiting
                else "审批结果已镜像到船舶治理任务"
            ),
        }
