"""Round 10 vessel governance loop service."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.vessel import (
    VesselAffiliationEvidence,
    VesselBlacklistSignal,
    VesselCandidateAnalysisAnnotation,
    VesselControllerEvidence,
    VesselDataQualityIssue,
    VesselGovernanceTask,
    VesselProfile,
    VesselProfileSummary,
    VesselRecognitionFieldDiff,
    VesselRiskReview,
    VesselRiskSignal,
)
from app.modules.vessel.schemas import (
    PageResponse,
    VesselBlacklistSignalCreateRequest,
    VesselBlacklistSignalResponse,
    VesselBlacklistSignalUpdateRequest,
    VesselGovernanceDashboardMetric,
    VesselGovernanceDashboardResponse,
    VesselGovernanceTaskActionRequest,
    VesselGovernanceTaskQuery,
    VesselGovernanceTaskResponse,
    VesselQualityIssueVesselSummary,
    VesselRiskReviewRequest,
    VesselRiskReviewResponse,
)
from app.modules.vessel.service import (
    COMPLIANCE_ACTIVE_STATUSES,
    COMPLIANCE_CLOSED_STATUSES,
    VesselService,
    _load_label_map,
    _risk_fingerprint,
    _row_dict,
)


ACTIVE_TASK_STATUSES = {"OPEN", "ASSIGNED", "IN_PROGRESS", "REOPENED"}
TERMINAL_TASK_STATUSES = {"RESOLVED", "CANNOT_RESOLVE", "VOIDED"}


def _utcnow() -> datetime:
    return datetime.utcnow()


def _task_no() -> str:
    return f"VG{_utcnow():%Y%m%d%H%M%S}{uuid.uuid4().hex[:6].upper()}"


def _task_fingerprint(*parts: Any) -> str:
    return "|".join(str(part or "") for part in parts)[:128]


def _priority_from_severity(severity: str | None) -> str:
    return {"CRITICAL": "URGENT", "HIGH": "HIGH", "LOW": "LOW"}.get(severity or "MEDIUM", "MEDIUM")


def _is_active_blacklist(row: VesselBlacklistSignal, today: date | None = None) -> bool:
    today = today or date.today()
    if row.status_code != "ACTIVE" or row.voided_at is not None:
        return False
    if row.effective_to and row.effective_to < today:
        return False
    return True


class VesselGovernanceService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def sync_tasks(self) -> int:
        now = _utcnow()
        touched = 0
        touched += await self._sync_quality_tasks(now)
        touched += await self._sync_risk_tasks(now)
        touched += await self._sync_candidate_annotation_tasks(now)
        touched += await self._sync_unverified_evidence_tasks(now)
        touched += await self._sync_blacklist_tasks(now)
        await self.db.flush()
        return touched

    async def dashboard(self) -> VesselGovernanceDashboardResponse:
        await self.sync_tasks()
        await self.db.commit()
        now = _utcnow()
        total_issues = int(await self.db.scalar(select(func.count(VesselDataQualityIssue.id))) or 0)
        resolved_issues = int(
            await self.db.scalar(
                select(func.count(VesselDataQualityIssue.id)).where(VesselDataQualityIssue.status_code == "RESOLVED")
            )
            or 0
        )
        issue_rows = (
            await self.db.scalars(
                select(VesselDataQualityIssue).where(
                    VesselDataQualityIssue.resolved_at.is_not(None),
                    VesselDataQualityIssue.created_at.is_not(None),
                )
            )
        ).all()
        close_hours = [
            max(0, (row.resolved_at - row.created_at).total_seconds() / 3600)
            for row in issue_rows
            if row.resolved_at and row.created_at
        ]
        open_high_risks = int(
            await self.db.scalar(
                select(func.count(VesselRiskSignal.id)).where(
                    VesselRiskSignal.status_code.in_(COMPLIANCE_ACTIVE_STATUSES),
                    VesselRiskSignal.risk_level == "HIGH",
                )
            )
            or 0
        )
        active_risks = int(
            await self.db.scalar(
                select(func.count(VesselRiskSignal.id)).where(VesselRiskSignal.status_code.in_(COMPLIANCE_ACTIVE_STATUSES))
            )
            or 0
        )
        unknown_risks = int(
            await self.db.scalar(
                select(func.count(VesselRiskSignal.id)).where(
                    VesselRiskSignal.status_code.in_(COMPLIANCE_ACTIVE_STATUSES),
                    VesselRiskSignal.risk_level == "UNKNOWN",
                )
            )
            or 0
        )
        unmatched_mmsi = int(
            await self.db.scalar(
                select(func.count(VesselDataQualityIssue.id)).where(
                    VesselDataQualityIssue.issue_type_code == "AIS_UNMATCHED",
                    VesselDataQualityIssue.status_code.in_(("OPEN", "IN_PROGRESS")),
                )
            )
            or 0
        )
        ocr_pending = int(
            await self.db.scalar(
                select(func.count(VesselRecognitionFieldDiff.id)).where(
                    VesselRecognitionFieldDiff.adopt_status_code.in_(("REVIEW_REQUIRED", "PENDING_REVIEW"))
                )
            )
            or 0
        )
        task_total = int(await self.db.scalar(select(func.count(VesselGovernanceTask.id))) or 0)
        duplicate_sum = int(await self.db.scalar(select(func.coalesce(func.sum(VesselGovernanceTask.duplicate_count), 0))) or 0)
        summary_total = int(await self.db.scalar(select(func.count(VesselProfileSummary.id))) or 0)
        high_quality = int(
            await self.db.scalar(
                select(func.count(VesselProfileSummary.id)).where(VesselProfileSummary.data_quality_level == "HIGH")
            )
            or 0
        )
        latest = await self.db.scalar(select(func.max(VesselGovernanceTask.updated_at)))
        metrics = [
            self._metric("quality_closure_rate", "质量问题关闭率", self._rate(resolved_issues, total_issues), "%", total_issues, latest),
            self._metric("avg_close_hours", "平均关闭时长", Decimal(str(round(sum(close_hours) / len(close_hours), 2))) if close_hours else None, "小时", len(close_hours), latest),
            self._metric("duplicate_issue_rate", "重复问题率", self._rate(duplicate_sum, max(task_total, 1)), "%", task_total, latest),
            self._metric("high_risk_open_count", "高风险未闭合数", open_high_risks, "条", active_risks, latest),
            self._metric("ocr_pending_fields", "OCR 待确认字段", ocr_pending, "项", ocr_pending, latest),
            self._metric("unmatched_mmsi", "未匹配 MMSI", unmatched_mmsi, "个", unmatched_mmsi, latest),
            self._metric("unknown_risk_ratio", "未知风险占比", self._rate(unknown_risks, active_risks), "%", active_risks, latest),
            self._metric("high_quality_profile_ratio", "高质量档案占比", self._rate(high_quality, summary_total), "%", summary_total, latest),
        ]
        return VesselGovernanceDashboardResponse(
            generated_at=now,
            coverage_rate=Decimal("100.00") if task_total or total_issues or active_risks else Decimal("0.00"),
            confidence_level="HIGH" if task_total or total_issues or active_risks else "UNKNOWN",
            latest_success_at=latest,
            metrics=metrics,
        )

    async def list_tasks(self, query: VesselGovernanceTaskQuery) -> PageResponse[VesselGovernanceTaskResponse]:
        if query.auto_sync:
            await self.sync_tasks()
            await self.db.commit()
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
        label_map = await _load_label_map(self.db)
        return PageResponse(
            total=total,
            page=query.page,
            page_size=query.page_size,
            items=[self._task_response(row, label_map, profiles.get(row.vessel_profile_id)) for row in rows],
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
        return self._task_response(row, label_map, profile)

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
        row.status_code = "VOIDED"
        row.voided_at = _utcnow()
        row.voided_by = operator_id
        row.void_reason = getattr(payload, "reason", None) or "名单信号作废"
        row.revision = int(row.revision or 1) + 1
        row.updated_at = _utcnow()
        await self._close_blacklist_risk(row, reason=row.void_reason, operator_id=operator_id)
        await self._refresh_after_governance(vessel_id, operator_id=operator_id)
        await self.db.commit()
        await self.db.refresh(row)
        return self._blacklist_response(row, await _load_label_map(self.db))

    async def _sync_quality_tasks(self, now: datetime) -> int:
        rows = (
            await self.db.scalars(
                select(VesselDataQualityIssue).where(VesselDataQualityIssue.status_code.in_(("OPEN", "IN_PROGRESS")))
            )
        ).all()
        touched = 0
        for row in rows:
            task_type = "QUALITY_ISSUE"
            if row.issue_type_code == "AIS_UNMATCHED":
                task_type = "AIS_UNMATCHED"
            elif row.issue_type_code == "OCR_UNCONFIRMED":
                task_type = "OCR_LOW_CONFIDENCE"
            await self._upsert_task(
                fingerprint=_task_fingerprint(task_type, "QUALITY", row.fingerprint),
                task_type_code=task_type,
                priority_code=_priority_from_severity(row.severity_code),
                vessel_profile_id=row.vessel_profile_id,
                source_object_type="VESSEL_DATA_QUALITY_ISSUE",
                source_object_id=str(row.id),
                source_status_code=row.status_code,
                source_fingerprint=row.fingerprint,
                title=f"{row.issue_type_code} 数据质量问题",
                description=f"{row.affected_object_type}/{row.affected_object_id}",
                evidence_summary=row.evidence_source,
                source_trace_json=[{"source": "vessel_data_quality_issue", "id": row.id}],
                impact_summary_json={"field_name": row.field_name, "impact_scope": row.impact_scope_json or []},
                confidence_level="MEDIUM" if row.severity_code != "HIGH" else "LOW",
                now=now,
            )
            touched += 1
        return touched

    async def _sync_risk_tasks(self, now: datetime) -> int:
        rows = (
            await self.db.scalars(
                select(VesselRiskSignal).where(
                    VesselRiskSignal.status_code.in_(COMPLIANCE_ACTIVE_STATUSES),
                    VesselRiskSignal.risk_level.in_(("HIGH", "UNKNOWN")),
                )
            )
        ).all()
        touched = 0
        for row in rows:
            await self._upsert_task(
                fingerprint=_task_fingerprint("RISK_REVIEW", row.fingerprint),
                task_type_code="RISK_REVIEW",
                priority_code="HIGH" if row.risk_level == "HIGH" else "MEDIUM",
                vessel_profile_id=row.vessel_profile_id,
                source_object_type="VESSEL_RISK_SIGNAL",
                source_object_id=str(row.id),
                source_status_code=row.status_code,
                source_fingerprint=row.fingerprint,
                title=f"{row.risk_type_code} 风险复核",
                description=row.resolution_reason,
                evidence_summary=row.rule_code,
                source_trace_json=row.source_trace_json or [{"source": "vessel_risk_signal", "id": row.id}],
                impact_summary_json={"risk_level": row.risk_level, "uncertainty": row.uncertainty_notes_json or []},
                confidence_level=row.confidence_level,
                now=now,
            )
            touched += 1
        return touched

    async def _sync_candidate_annotation_tasks(self, now: datetime) -> int:
        rows = (
            await self.db.scalars(
                select(VesselCandidateAnalysisAnnotation).where(
                    VesselCandidateAnalysisAnnotation.annotation_type_code.in_(
                        ("DATA_INSUFFICIENT", "CERTIFICATE_RISK", "POSITION_ABNORMAL", "NEEDS_REVIEW")
                    )
                )
            )
        ).all()
        touched = 0
        for row in rows:
            await self._upsert_task(
                fingerprint=_task_fingerprint("CANDIDATE_REVIEW", row.annotation_type_code, row.analysis_id, row.item_id),
                task_type_code="CANDIDATE_REVIEW",
                priority_code="HIGH" if row.annotation_type_code == "CERTIFICATE_RISK" else "MEDIUM",
                vessel_profile_id=None,
                source_object_type="VESSEL_CANDIDATE_ANALYSIS_ANNOTATION",
                source_object_id=str(row.id),
                source_status_code=row.annotation_type_code,
                source_fingerprint=f"{row.analysis_id}:{row.item_id}:{row.annotation_type_code}",
                title=f"{row.annotation_type_code} 候选分析标注",
                description=row.comment,
                evidence_summary=row.comment,
                source_trace_json=[{"source": "vessel_candidate_analysis_annotation", "id": row.id}],
                impact_summary_json={"analysis_id": row.analysis_id, "item_id": row.item_id},
                confidence_level="MEDIUM",
                now=now,
            )
            touched += 1
        return touched

    async def _sync_unverified_evidence_tasks(self, now: datetime) -> int:
        touched = 0
        controller_rows = (
            await self.db.scalars(
                select(VesselControllerEvidence).where(
                    VesselControllerEvidence.status_code == "ACTIVE",
                    VesselControllerEvidence.verified_status_code.in_(("DRAFT", "PENDING", "CHANGE_REQUESTED")),
                )
            )
        ).all()
        for row in controller_rows:
            await self._upsert_task(
                fingerprint=_task_fingerprint("CONTROLLER", row.id),
                task_type_code="CONTROLLER_AFFILIATION",
                priority_code="MEDIUM",
                vessel_profile_id=row.vessel_profile_id,
                source_object_type="VESSEL_CONTROLLER_EVIDENCE",
                source_object_id=str(row.id),
                source_status_code=row.verified_status_code,
                source_fingerprint=f"controller:{row.id}",
                title="实际控制人证据审核",
                description=row.party_name,
                evidence_summary=row.evidence_summary,
                source_trace_json=[{"source": "vessel_controller_evidence", "id": row.id}],
                impact_summary_json={"party_name": row.party_name, "role": row.controller_role_code},
                confidence_level=row.confidence_level,
                now=now,
            )
            touched += 1
        affiliation_rows = (
            await self.db.scalars(
                select(VesselAffiliationEvidence).where(
                    VesselAffiliationEvidence.status_code == "ACTIVE",
                    VesselAffiliationEvidence.verified_status_code.in_(("DRAFT", "PENDING", "CHANGE_REQUESTED")),
                )
            )
        ).all()
        for row in affiliation_rows:
            await self._upsert_task(
                fingerprint=_task_fingerprint("AFFILIATION", row.id),
                task_type_code="CONTROLLER_AFFILIATION",
                priority_code="MEDIUM",
                vessel_profile_id=row.vessel_profile_id,
                source_object_type="VESSEL_AFFILIATION_EVIDENCE",
                source_object_id=str(row.id),
                source_status_code=row.verified_status_code,
                source_fingerprint=f"affiliation:{row.id}",
                title="挂靠关系证据审核",
                description=row.subject_name or row.counterparty_name,
                evidence_summary=row.evidence_summary,
                source_trace_json=[{"source": "vessel_affiliation_evidence", "id": row.id}],
                impact_summary_json={"subject_name": row.subject_name, "counterparty_name": row.counterparty_name},
                confidence_level=row.confidence_level,
                now=now,
            )
            touched += 1
        return touched

    async def _sync_blacklist_tasks(self, now: datetime) -> int:
        rows = (
            await self.db.scalars(
                select(VesselBlacklistSignal).where(VesselBlacklistSignal.status_code == "ACTIVE", VesselBlacklistSignal.voided_at.is_(None))
            )
        ).all()
        touched = 0
        for row in rows:
            if not _is_active_blacklist(row):
                row.status_code = "EXPIRED"
                await self._close_blacklist_risk(row, reason="名单信号已过期")
                continue
            await self._upsert_task(
                fingerprint=_task_fingerprint("BLACKLIST_REVIEW", row.id),
                task_type_code="BLACKLIST_REVIEW",
                priority_code="HIGH" if row.risk_level == "HIGH" else "MEDIUM",
                vessel_profile_id=row.vessel_profile_id,
                source_object_type="VESSEL_BLACKLIST_SIGNAL",
                source_object_id=str(row.id),
                source_status_code=row.status_code,
                source_fingerprint=f"blacklist:{row.id}",
                title=f"{row.list_type_code} 名单信号复核",
                description=row.evidence_summary,
                evidence_summary=row.evidence_summary,
                source_trace_json=[{"source": "vessel_blacklist_signal", "id": row.id}],
                impact_summary_json={"risk_level": row.risk_level, "signal_type": row.signal_type_code},
                confidence_level=row.confidence_level,
                now=now,
            )
            await self._upsert_blacklist_risk(row)
            touched += 1
        return touched

    async def _upsert_task(self, *, now: datetime, **data: Any) -> VesselGovernanceTask:
        fingerprint = data["fingerprint"]
        row = await self.db.scalar(
            select(VesselGovernanceTask)
            .where(VesselGovernanceTask.fingerprint == fingerprint)
            .order_by(VesselGovernanceTask.id.desc())
            .limit(1)
        )
        if row is None:
            row = VesselGovernanceTask(task_no=_task_no(), first_seen_at=now, last_seen_at=now, **data)
            self.db.add(row)
            return row
        for key, value in data.items():
            if key in {"fingerprint"}:
                continue
            setattr(row, key, value)
        if row.status_code in TERMINAL_TASK_STATUSES:
            row.status_code = "REOPENED"
            row.reopen_count = int(row.reopen_count or 0) + 1
            row.resolved_at = None
            row.resolved_by = None
            row.resolution_reason = None
            row.resolution_evidence_json = None
        else:
            row.duplicate_count = int(row.duplicate_count or 0) + 1
        row.last_seen_at = now
        row.updated_at = now
        return row

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
            if issue is not None:
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
        elif task.source_object_type == "VESSEL_CONTROLLER_EVIDENCE":
            evidence = await self.db.get(VesselControllerEvidence, int(task.source_object_id))
            if evidence is not None:
                evidence.verified_status_code = "APPROVED"
                evidence.verified_at = now
                evidence.verified_by = operator_id
                evidence.revision = int(evidence.revision or 1) + 1
        elif task.source_object_type == "VESSEL_AFFILIATION_EVIDENCE":
            evidence = await self.db.get(VesselAffiliationEvidence, int(task.source_object_id))
            if evidence is not None:
                evidence.verified_status_code = "APPROVED"
                evidence.verified_at = now
                evidence.verified_by = operator_id
                evidence.revision = int(evidence.revision or 1) + 1

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
            service = VesselService(self.db)
            await service._refresh_summary_best_effort(vessel_id)
            await service._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
            impact["summary_refresh"] = "SUCCESS"
            impact["risk_refresh"] = "SUCCESS"
            impact["round9_fact_refresh"] = "RECORDED_FOR_NEXT_ANALYSIS_RUN"
        except Exception as exc:  # noqa: BLE001
            impact["refresh_error"] = str(exc)
            await self.db.rollback()
        if row is not None:
            row.impact_summary_json = impact

    def _metric(
        self,
        code: str,
        name: str,
        value: Decimal | int | None,
        unit: str,
        sample_count: int,
        source_updated_at: datetime | None,
    ) -> VesselGovernanceDashboardMetric:
        return VesselGovernanceDashboardMetric(
            code=code,
            name=name,
            value=value,
            unit=unit,
            sample_count=sample_count,
            coverage_rate=Decimal("100.00") if sample_count else Decimal("0.00"),
            confidence_level="HIGH" if sample_count else "UNKNOWN",
            not_computable_reasons=[] if sample_count else ["NO_GOVERNANCE_SAMPLE"],
            source_updated_at=source_updated_at,
        )

    @staticmethod
    def _rate(numerator: int, denominator: int) -> Decimal | None:
        if denominator <= 0:
            return None
        return Decimal(str(round(numerator * 100 / denominator, 2)))

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

    def _task_response(
        self,
        row: VesselGovernanceTask,
        label_map: dict[str, dict[str, str]],
        profile: VesselProfile | None = None,
    ) -> VesselGovernanceTaskResponse:
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
        return VesselGovernanceTaskResponse(
            **_row_dict(row),
            task_type_name=label_map.get("VESSEL_GOVERNANCE_TASK_TYPE", {}).get(row.task_type_code),
            priority_name=label_map.get("VESSEL_GOVERNANCE_PRIORITY", {}).get(row.priority_code),
            status_name=label_map.get("VESSEL_GOVERNANCE_TASK_STATUS", {}).get(row.status_code),
            confidence_level_name=label_map.get("VESSEL_CONFIDENCE_LEVEL", {}).get(row.confidence_level),
            vessel=vessel,
        )

    @staticmethod
    def _risk_review_response(row: VesselRiskReview) -> VesselRiskReviewResponse:
        return VesselRiskReviewResponse(**_row_dict(row))

    def _blacklist_response(
        self,
        row: VesselBlacklistSignal,
        label_map: dict[str, dict[str, str]],
    ) -> VesselBlacklistSignalResponse:
        return VesselBlacklistSignalResponse(
            **_row_dict(row),
            list_type_name=label_map.get("VESSEL_BLACKLIST_LIST_TYPE", {}).get(row.list_type_code),
            signal_type_name=label_map.get("VESSEL_BLACKLIST_SIGNAL_TYPE", {}).get(row.signal_type_code),
            status_name=label_map.get("VESSEL_BLACKLIST_SIGNAL_STATUS", {}).get(row.status_code),
            risk_level_name=label_map.get("VESSEL_RISK_LEVEL", {}).get(row.risk_level),
            confidence_level_name=label_map.get("VESSEL_CONFIDENCE_LEVEL", {}).get(row.confidence_level),
            source_type_name=label_map.get("SOURCE_TYPE", {}).get(row.source_type_code),
        )
