"""Round 10 vessel governance loop service."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.audit import AuditRecord, AuditTask, AuditTaskSnapshot
from app.models.vessel import (
    VesselAffiliationEvidence,
    VesselBlacklistSignal,
    VesselCandidateAnalysisAnnotation,
    VesselControllerEvidence,
    VesselDataQualityIssue,
    VesselGovernanceSyncBatch,
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
    VesselBlacklistSignalGlobalQuery,
    VesselBlacklistSignalListItemResponse,
    VesselBlacklistSignalResponse,
    VesselBlacklistSignalUpdateRequest,
    VesselGovernanceDashboardMetric,
    VesselGovernanceDashboardResponse,
    VesselGovernanceSyncBatchResponse,
    VesselGovernanceTaskActionRequest,
    VesselGovernanceTaskQuery,
    VesselGovernanceTaskResponse,
    VesselGovernanceTaskSyncResponse,
    VesselQualityIssueVesselSummary,
    VesselRecommendedAction,
    VesselRiskReviewRequest,
    VesselRiskReviewResponse,
    VesselWorkbenchItemResponse,
)
from app.modules.vessel.asset.service import VesselAssetService
from app.modules.vessel.quality.service import VesselQualityService
from app.modules.vessel.shared.base import (
    COMPLIANCE_ACTIVE_STATUSES,
    COMPLIANCE_CLOSED_STATUSES,
    _load_label_map,
    _jsonable,
    _risk_fingerprint,
    _row_dict,
)


ACTIVE_TASK_STATUSES = {"OPEN", "ASSIGNED", "IN_PROGRESS", "REOPENED"}
TERMINAL_TASK_STATUSES = {"RESOLVED", "CANNOT_RESOLVE", "VOIDED"}
EVIDENCE_AUDIT_SOURCE_TYPES = {"VESSEL_CONTROLLER_EVIDENCE", "VESSEL_AFFILIATION_EVIDENCE"}


def _utcnow() -> datetime:
    return datetime.utcnow()


def _task_no() -> str:
    return f"VG{_utcnow():%Y%m%d%H%M%S}{uuid.uuid4().hex[:6].upper()}"


def _sync_batch_no() -> str:
    return f"VGS{_utcnow():%Y%m%d%H%M%S}{uuid.uuid4().hex[:6].upper()}"


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
        self._sync_batch_id: int | None = None
        self._sync_rule_results: dict[str, dict[str, int]] | None = None
        self._sync_affected_vessel_ids: set[int] = set()

    async def sync_tasks(
        self,
        *,
        batch_id: int | None = None,
        rule_results: dict[str, dict[str, int]] | None = None,
        affected_vessel_ids: set[int] | None = None,
    ) -> int:
        now = _utcnow()
        previous_batch_id = self._sync_batch_id
        previous_rule_results = self._sync_rule_results
        previous_affected = self._sync_affected_vessel_ids
        self._sync_batch_id = batch_id
        self._sync_rule_results = rule_results
        self._sync_affected_vessel_ids = affected_vessel_ids if affected_vessel_ids is not None else set()
        touched = 0
        try:
            touched += await self._sync_quality_tasks(now)
            touched += await self._sync_risk_tasks(now)
            touched += await self._sync_candidate_annotation_tasks(now)
            touched += await self._sync_unverified_evidence_tasks(now)
            touched += await self._sync_blacklist_tasks(now)
            await self.db.flush()
            return touched
        finally:
            self._sync_batch_id = previous_batch_id
            self._sync_rule_results = previous_rule_results
            self._sync_affected_vessel_ids = previous_affected

    async def sync_tasks_command(self, *, operator_id: int | None = None, trigger_type_code: str = "MANUAL") -> VesselGovernanceTaskSyncResponse:
        now = _utcnow()
        source_rules = [
            "VESSEL_DATA_QUALITY_ISSUE",
            "VESSEL_RISK_SIGNAL",
            "VESSEL_CANDIDATE_ANNOTATION",
            "VESSEL_CONTROLLER_EVIDENCE",
            "VESSEL_AFFILIATION_EVIDENCE",
            "VESSEL_BLACKLIST_SIGNAL",
        ]
        batch = VesselGovernanceSyncBatch(
            batch_no=_sync_batch_no(),
            trigger_type_code=trigger_type_code,
            triggered_by=operator_id,
            status_code="RUNNING",
            source_rules_json=source_rules,
            rule_result_json={},
            affected_scope_json={},
            started_at=now,
        )
        self.db.add(batch)
        await self.db.flush()
        rule_results: dict[str, dict[str, int]] = {}
        affected_vessel_ids: set[int] = set()
        try:
            touched = await self.sync_tasks(batch_id=batch.id, rule_results=rule_results, affected_vessel_ids=affected_vessel_ids)
            created = sum(item.get("created", 0) for item in rule_results.values())
            reopened = sum(item.get("reopened", 0) for item in rule_results.values())
            skipped = sum(item.get("skipped", 0) for item in rule_results.values())
            batch.status_code = "SUCCESS"
            batch.touched_count = touched
            batch.created_task_count = created
            batch.reopened_task_count = reopened
            batch.skipped_count = skipped
            batch.rule_result_json = rule_results
            batch.affected_scope_json = {"vessel_profile_ids": sorted(affected_vessel_ids), "vessel_count": len(affected_vessel_ids)}
            batch.finished_at = _utcnow()
            batch.message = "治理任务已按显式指令同步，查询接口不会自动生成任务。"
            await self.db.commit()
            return VesselGovernanceTaskSyncResponse(
                batch_id=batch.id,
                batch_no=batch.batch_no,
                synced_at=batch.finished_at or _utcnow(),
                touched_count=touched,
                created_task_count=created,
                reopened_task_count=reopened,
                skipped_count=skipped,
                source_rules=source_rules,
                rule_results=rule_results,
                affected_scope=batch.affected_scope_json or {},
                message=batch.message or "",
            )
        except Exception as exc:  # noqa: BLE001
            batch.status_code = "FAILED"
            batch.finished_at = _utcnow()
            batch.message = str(exc)[:1000]
            batch.rule_result_json = rule_results
            batch.affected_scope_json = {"vessel_profile_ids": sorted(affected_vessel_ids), "vessel_count": len(affected_vessel_ids)}
            await self.db.commit()
            raise

    async def dashboard(self) -> VesselGovernanceDashboardResponse:
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
        active_tasks = int(
            await self.db.scalar(
                select(func.count(VesselGovernanceTask.id)).where(VesselGovernanceTask.status_code.in_(ACTIVE_TASK_STATUSES))
            )
            or 0
        )
        quality_recheck_failed = int(
            await self.db.scalar(
                select(func.count(VesselDataQualityIssue.id)).where(
                    VesselDataQualityIssue.status_code.in_(("OPEN", "IN_PROGRESS", "REOPENED")),
                    VesselDataQualityIssue.last_recheck_status_code == "FAILED",
                )
            )
            or 0
        )
        pending_evidence = int(
            await self.db.scalar(
                select(func.count(VesselControllerEvidence.id)).where(
                    VesselControllerEvidence.status_code == "ACTIVE",
                    VesselControllerEvidence.voided_at.is_(None),
                    VesselControllerEvidence.verified_status_code.in_(("DRAFT", "PENDING", "CHANGE_REQUESTED")),
                )
            )
            or 0
        ) + int(
            await self.db.scalar(
                select(func.count(VesselAffiliationEvidence.id)).where(
                    VesselAffiliationEvidence.status_code == "ACTIVE",
                    VesselAffiliationEvidence.voided_at.is_(None),
                    VesselAffiliationEvidence.verified_status_code.in_(("DRAFT", "PENDING", "CHANGE_REQUESTED")),
                )
            )
            or 0
        )
        blacklist_review = int(
            await self.db.scalar(
                select(func.count(VesselBlacklistSignal.id)).where(
                    VesselBlacklistSignal.status_code == "ACTIVE",
                    VesselBlacklistSignal.voided_at.is_(None),
                )
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
        work_items = [
            self._work_item(
                "today_active_tasks",
                "今日待处理治理任务",
                active_tasks,
                "HIGH" if active_tasks else "LOW",
                "/vessels/governance/tasks",
                {"status_code": "OPEN"},
                "来自最近一次显式同步批次和人工重开任务；看板刷新不会生成新任务。",
                "TASK",
            ),
            self._work_item(
                "high_risk_open",
                "高风险未闭合",
                open_high_risks,
                "URGENT" if open_high_risks else "LOW",
                "/vessels/compliance-risks",
                {"risk_level": "HIGH", "status_code": "OPEN"},
                "高风险船舶需要补齐证照、主体结论、名单复核或走风险复核链路。",
                "RISK",
                ["证照有效性", "主体关系结论", "风险复核意见"],
            ),
            self._work_item(
                "quality_recheck_failed",
                "质量重校验失败",
                quality_recheck_failed,
                "HIGH" if quality_recheck_failed else "LOW",
                "/vessels/quality",
                {"last_recheck_status_code": "FAILED", "status_code": "OPEN"},
                "这些问题已尝试重新校验但仍命中，需要继续定位源字段或证据。",
                "QUALITY",
                ["源字段修复", "重新校验结果"],
            ),
            self._work_item(
                "ocr_pending_fields",
                "OCR 待采纳字段",
                ocr_pending,
                "MEDIUM",
                "/vessels/recognitions",
                {"adopt_status_code": "REVIEW_REQUIRED"},
                "OCR 字段差异需要人工确认后才能进入可信档案。",
                "OCR",
                ["识别字段确认", "采纳或跳过原因"],
            ),
            self._work_item(
                "unmatched_mmsi",
                "未匹配 MMSI",
                unmatched_mmsi,
                "HIGH" if unmatched_mmsi else "LOW",
                "/vessels/quality",
                {"issue_type_code": "AIS_UNMATCHED", "status_code": "OPEN"},
                "AIS 侧发现但未能稳定映射到船舶档案，影响轨迹和空间分析可信度。",
                "AIS",
                ["MMSI 核对", "AIS 最新快照"],
            ),
            self._work_item(
                "evidence_pending_review",
                "主体证据待审",
                pending_evidence,
                "MEDIUM",
                "/vessels/governance/tasks",
                {"source_object_type": "VESSEL_CONTROLLER_EVIDENCE"},
                "控制人/挂靠证据审核后会形成候选结论，人工确认后才成为当前结论。",
                "EVIDENCE",
                ["证据摘要", "审核意见", "结论确认"],
            ),
            self._work_item(
                "blacklist_review",
                "名单信号复核",
                blacklist_review,
                "HIGH" if blacklist_review else "LOW",
                "/vessels/blacklist-signals",
                {"status_code": "ACTIVE"},
                "名单信号会联动风险和治理任务，需确认有效期、证据和解除条件。",
                "BLACKLIST",
                ["名单证据", "有效期", "解除或作废原因"],
            ),
        ]
        return VesselGovernanceDashboardResponse(
            generated_at=now,
            coverage_rate=Decimal("100.00") if task_total or total_issues or active_risks else Decimal("0.00"),
            confidence_level="HIGH" if task_total or total_issues or active_risks else "UNKNOWN",
            latest_success_at=latest,
            metrics=metrics,
            work_items=work_items,
        )

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
        audit_info = await self._audit_info_by_task(rows)
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
                    audit_info.get((row.source_object_type, row.source_object_id)),
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
        audit_info = await self._audit_info_by_task([row])
        return self._task_response(row, label_map, profile, audit_info.get((row.source_object_type, row.source_object_id)))

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
        requires_audit = self._risk_review_requires_audit(payload.review_action_code, to_status)
        if requires_audit:
            audit = await self._create_vessel_audit_task(
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
                        "audit_task_id": audit.id,
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
                    "audit_task_id": audit.id,
                    "audit_task_no": audit.task_no,
                    "business_sync_status_code": "WAITING_AUDIT",
                }
                task.updated_at = now
                task.revision = int(task.revision or 1) + 1
            await self.db.commit()
            await self.db.refresh(review)
            return self._risk_review_response(review, audit)
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
        audit = await self._create_vessel_audit_task(
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
                "audit_task_id": audit.id,
                "audit_task_no": audit.task_no,
                "intended_status_code": "VOIDED",
            },
        }
        row.revision = int(row.revision or 1) + 1
        row.updated_at = now
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
        rule_code = data.get("source_rule_code") or data.get("source_object_type") or data.get("task_type_code") or "UNKNOWN"
        data.setdefault("source_batch_id", self._sync_batch_id)
        data.setdefault("source_rule_code", rule_code)
        data.setdefault(
            "generation_reason_json",
            {
                "source_rule_code": rule_code,
                "source_object_type": data.get("source_object_type"),
                "source_object_id": data.get("source_object_id"),
                "source_status_code": data.get("source_status_code"),
                "task_type_code": data.get("task_type_code"),
                "title": data.get("title"),
            },
        )
        if data.get("vessel_profile_id"):
            self._sync_affected_vessel_ids.add(int(data["vessel_profile_id"]))
        row = await self.db.scalar(
            select(VesselGovernanceTask)
            .where(VesselGovernanceTask.fingerprint == fingerprint)
            .order_by(VesselGovernanceTask.id.desc())
            .limit(1)
        )
        if row is None:
            row = VesselGovernanceTask(task_no=_task_no(), first_seen_at=now, last_seen_at=now, **data)
            self.db.add(row)
            self._record_sync_result(rule_code, "created")
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
            self._record_sync_result(rule_code, "reopened")
        else:
            row.duplicate_count = int(row.duplicate_count or 0) + 1
            self._record_sync_result(rule_code, "skipped")
        row.last_seen_at = now
        row.updated_at = now
        return row

    def _record_sync_result(self, rule_code: str, key: str) -> None:
        if self._sync_rule_results is None:
            return
        stats = self._sync_rule_results.setdefault(rule_code, {"created": 0, "reopened": 0, "skipped": 0})
        stats[key] = int(stats.get(key, 0)) + 1

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
        elif task.source_object_type in EVIDENCE_AUDIT_SOURCE_TYPES:
            audit_info = await self._audit_info_by_task([task])
            audit_path = (audit_info.get((task.source_object_type, task.source_object_id)) or {}).get("audit_action_path")
            suffix = f"：{audit_path}" if audit_path else ""
            raise ValidationError(f"证据审核类治理任务必须在审核中心处理，不能通过治理任务直接关闭{suffix}")
        elif task.source_object_type == "VESSEL_BLACKLIST_SIGNAL":
            audit_info = await self._audit_info_by_task([task])
            audit_path = (audit_info.get((task.source_object_type, task.source_object_id)) or {}).get("audit_action_path")
            suffix = f"：{audit_path}" if audit_path else ""
            raise ValidationError(f"名单复核/解除必须在审核中心处理，不能通过治理任务直接关闭{suffix}")

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
            target_path=self._metric_target_path(code),
            target_query=self._metric_target_query(code),
            recommended_actions=self._metric_actions(code),
        )

    @staticmethod
    def _metric_target_path(code: str) -> str | None:
        return {
            "quality_closure_rate": "/vessels/quality",
            "avg_close_hours": "/vessels/governance/tasks",
            "duplicate_issue_rate": "/vessels/governance/tasks",
            "high_risk_open_count": "/vessels/compliance-risks",
            "ocr_pending_fields": "/vessels/recognitions",
            "unmatched_mmsi": "/vessels/quality",
            "unknown_risk_ratio": "/vessels/compliance-risks",
            "high_quality_profile_ratio": "/vessels/assets",
        }.get(code)

    @staticmethod
    def _metric_target_query(code: str) -> dict[str, Any]:
        return {
            "high_risk_open_count": {"risk_level": "HIGH", "status_code": "OPEN"},
            "ocr_pending_fields": {"adopt_status_code": "REVIEW_REQUIRED"},
            "unmatched_mmsi": {"issue_type_code": "AIS_UNMATCHED", "status_code": "OPEN"},
            "unknown_risk_ratio": {"risk_level": "UNKNOWN", "status_code": "OPEN"},
            "avg_close_hours": {"status_code": "RESOLVED"},
            "duplicate_issue_rate": {"sort": "duplicate_count_desc"},
            "high_quality_profile_ratio": {"quality_level": "HIGH"},
        }.get(code, {})

    def _metric_actions(self, code: str) -> list[VesselRecommendedAction]:
        target_path = self._metric_target_path(code)
        if not target_path:
            return []
        labels = {
            "quality_closure_rate": "查看质量治理任务",
            "avg_close_hours": "查看已关闭任务",
            "duplicate_issue_rate": "查看重复任务",
            "high_risk_open_count": "处理高风险船舶",
            "ocr_pending_fields": "确认 OCR 字段",
            "unmatched_mmsi": "治理未匹配 MMSI",
            "unknown_risk_ratio": "复核未知风险",
            "high_quality_profile_ratio": "查看高质量档案",
        }
        return [
            VesselRecommendedAction(
                action_type="DRILLDOWN",
                label=labels.get(code, "查看明细"),
                target_path=target_path,
                target_object_type="GOVERNANCE_METRIC",
                target_object_id=code,
                payload=self._metric_target_query(code),
            )
        ]

    @staticmethod
    def _work_item(
        code: str,
        title: str,
        count: int,
        priority_code: str,
        target_path: str,
        target_query: dict[str, Any],
        explain_reason: str,
        workbench_group: str,
        evidence_gaps: list[str] | None = None,
    ) -> VesselWorkbenchItemResponse:
        return VesselWorkbenchItemResponse(
            code=code,
            title=title,
            count=count,
            priority_code=priority_code,
            target_path=target_path,
            target_query=target_query,
            explain_reason=explain_reason,
            evidence_gaps=evidence_gaps or [],
            source_object_anchor=f"WORKBENCH:{code}",
        workbench_group=workbench_group,
            sla_due_at=_utcnow() + timedelta(hours={"URGENT": 8, "HIGH": 24, "MEDIUM": 72, "LOW": 168}.get(priority_code, 72)) if count else None,
            overdue_level="OVERDUE" if count and priority_code in {"URGENT", "HIGH"} else ("NORMAL" if count else "NONE"),
            assignee_load=count,
            today_priority_score=count * {"URGENT": 100, "HIGH": 80, "MEDIUM": 50, "LOW": 20}.get(priority_code, 50),
            recommended_actions=[
                VesselRecommendedAction(
                    action_type="DRILLDOWN",
                    label="进入处理",
                    target_path=target_path,
                    target_object_type="WORKBENCH_ITEM",
                    target_object_id=code,
                    source_object_anchor=f"WORKBENCH:{code}",
                    workbench_group=workbench_group,
                    payload=target_query,
                    description=explain_reason,
                )
            ],
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

    @staticmethod
    def _risk_review_requires_audit(action: str, to_status: str | None) -> bool:
        return (to_status in COMPLIANCE_CLOSED_STATUSES) or action.upper() in {"MITIGATE", "CLOSE", "FALSE_POSITIVE"}

    async def _create_vessel_audit_task(
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
    ) -> AuditTask:
        now = _utcnow()
        task = AuditTask(
            task_no=f"VA{now:%Y%m%d%H%M%S}{uuid.uuid4().hex[:6].upper()}",
            biz_type_code="VESSEL",
            biz_id=object_id,
            biz_code=object_type_code,
            object_type_code=object_type_code,
            object_code=str(object_id),
            object_name=object_name,
            change_type_code=change_type_code,
            source_module_code="VESSEL",
            submitter_id=operator_id,
            audit_status="PENDING",
            audit_remark=comment,
            submitted_at=now,
        )
        self.db.add(task)
        await self.db.flush()
        self.db.add_all(
            [
                AuditTaskSnapshot(
                    task_id=task.id,
                    before_snapshot_json=_jsonable(before_snapshot_json) if before_snapshot_json else None,
                    after_snapshot_json=_jsonable(after_snapshot_json),
                    diff_json=None,
                    summary_json=_jsonable(summary_json),
                    created_at=now,
                    updated_at=now,
                ),
                AuditRecord(
                    task_id=task.id,
                    action_code="SUBMIT",
                    operator_id=operator_id,
                    from_status_code=None,
                    to_status_code="PENDING",
                    remark=comment,
                    created_at=now,
                ),
            ]
        )
        return task

    async def _audit_info_by_task(self, rows: list[VesselGovernanceTask]) -> dict[tuple[str, str], dict[str, Any]]:
        evidence_keys = [
            (row.source_object_type, row.source_object_id)
            for row in rows
            if row.source_object_type in EVIDENCE_AUDIT_SOURCE_TYPES and str(row.source_object_id).isdigit()
        ]
        result: dict[tuple[str, str], dict[str, Any]] = {}
        controller_ids = [int(object_id) for object_type, object_id in evidence_keys if object_type == "VESSEL_CONTROLLER_EVIDENCE"]
        affiliation_ids = [int(object_id) for object_type, object_id in evidence_keys if object_type == "VESSEL_AFFILIATION_EVIDENCE"]
        evidence_audit_ids: dict[tuple[str, str], int] = {}
        if controller_ids:
            controller_rows = (
                await self.db.scalars(
                    select(VesselControllerEvidence).where(VesselControllerEvidence.id.in_(controller_ids))
                )
            ).all()
            evidence_audit_ids.update(
                {
                    ("VESSEL_CONTROLLER_EVIDENCE", str(row.id)): int(row.audit_task_id)
                    for row in controller_rows
                    if row.audit_task_id
                }
            )
        if affiliation_ids:
            affiliation_rows = (
                await self.db.scalars(
                    select(VesselAffiliationEvidence).where(VesselAffiliationEvidence.id.in_(affiliation_ids))
                )
            ).all()
            evidence_audit_ids.update(
                {
                    ("VESSEL_AFFILIATION_EVIDENCE", str(row.id)): int(row.audit_task_id)
                    for row in affiliation_rows
                    if row.audit_task_id
                }
            )
        risk_rows = [row for row in rows if row.source_object_type == "VESSEL_RISK_SIGNAL" and str(row.source_object_id).isdigit()]
        blacklist_rows = [row for row in rows if row.source_object_type == "VESSEL_BLACKLIST_SIGNAL" and str(row.source_object_id).isdigit()]
        risk_audit_ids: dict[tuple[str, str], int] = {}
        if risk_rows:
            risk_ids = [int(row.source_object_id) for row in risk_rows]
            review_rows = (
                await self.db.scalars(
                    select(VesselRiskReview)
                    .where(VesselRiskReview.risk_signal_id.in_(risk_ids))
                    .order_by(VesselRiskReview.updated_at.desc(), VesselRiskReview.id.desc())
                )
            ).all()
            if review_rows:
                audit_rows_for_review = (
                    await self.db.scalars(
                        select(AuditTask).where(
                            AuditTask.object_type_code == "VESSEL_RISK_REVIEW",
                            AuditTask.biz_id.in_([row.id for row in review_rows]),
                        )
                    )
                ).all()
                audit_by_review_id = {int(row.biz_id): row.id for row in audit_rows_for_review}
                for review in review_rows:
                    audit_id = audit_by_review_id.get(int(review.id))
                    if audit_id:
                        risk_audit_ids.setdefault(("VESSEL_RISK_SIGNAL", str(review.risk_signal_id)), int(audit_id))
        blacklist_audit_ids: dict[tuple[str, str], int] = {}
        if blacklist_rows:
            signal_ids = [int(row.source_object_id) for row in blacklist_rows]
            audit_rows_for_blacklist = (
                await self.db.scalars(
                    select(AuditTask)
                    .where(AuditTask.object_type_code == "VESSEL_BLACKLIST_SIGNAL", AuditTask.biz_id.in_(signal_ids))
                    .order_by(AuditTask.updated_at.desc(), AuditTask.id.desc())
                )
            ).all()
            for audit in audit_rows_for_blacklist:
                blacklist_audit_ids.setdefault(("VESSEL_BLACKLIST_SIGNAL", str(audit.biz_id)), int(audit.id))
        all_audit_ids = set(evidence_audit_ids.values()) | set(risk_audit_ids.values()) | set(blacklist_audit_ids.values())
        if not all_audit_ids:
            return result
        audit_rows = (await self.db.scalars(select(AuditTask).where(AuditTask.id.in_(all_audit_ids)))).all()
        audit_by_id = {int(row.id): row for row in audit_rows}
        for key, audit_id in {**evidence_audit_ids, **risk_audit_ids, **blacklist_audit_ids}.items():
            audit = audit_by_id.get(audit_id)
            if audit is None:
                continue
            status_name = {"PENDING": "待审核", "APPROVED": "已通过", "REJECTED": "已驳回", "CANCELED": "已取消"}.get(
                audit.audit_status,
                audit.audit_status,
            )
            result[key] = {
                "audit_task_id": int(audit.id),
                "audit_task_no": audit.task_no,
                "audit_status_code": audit.audit_status,
                "audit_status_name": status_name,
                "audit_action_path": f"/audit/tasks/{audit.id}",
                "business_sync_status_code": "WAITING_AUDIT" if audit.audit_status == "PENDING" else "SYNCED",
                "business_sync_message": (
                    "审核中心处理完成后将自动同步主体结论、合规风险和治理任务"
                    if audit.audit_status == "PENDING"
                    else "审核结果已镜像到船舶治理任务"
                ),
            }
        return result

    def _task_response(
        self,
        row: VesselGovernanceTask,
        label_map: dict[str, dict[str, str]],
        profile: VesselProfile | None = None,
        audit_info: dict[str, Any] | None = None,
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
            action_path=self._task_action_path(row, audit_info),
            field_anchor=self._task_field_anchor(row),
            recommended_actions=self._task_actions(row, audit_info),
            next_actions=self._task_actions(row, audit_info),
            explain_reason=self._task_explain_reason(row),
            evidence_gaps=self._task_evidence_gaps(row),
            source_object_anchor=self._task_source_anchor(row),
            workbench_group=self._task_workbench_group(row),
            verification_status_code=self._task_verification_status(row),
            verification_message=self._task_verification_message(row),
            audit_task_id=(audit_info or {}).get("audit_task_id"),
            audit_task_no=(audit_info or {}).get("audit_task_no"),
            audit_status_code=(audit_info or {}).get("audit_status_code"),
            audit_status_name=(audit_info or {}).get("audit_status_name"),
            audit_action_path=(audit_info or {}).get("audit_action_path"),
            business_sync_status_code=(audit_info or {}).get("business_sync_status_code"),
            business_sync_message=(audit_info or {}).get("business_sync_message"),
            sla_due_at=self._task_sla_due_at(row),
            overdue_level=self._task_overdue_level(row),
            assignee_load=None,
            today_priority_score=self._task_priority_score(row),
            validation_entrypoint=self._task_validation_entrypoint(row),
        )

    def _task_actions(self, row: VesselGovernanceTask, audit_info: dict[str, Any] | None = None) -> list[VesselRecommendedAction]:
        target_path = self._task_action_path(row, audit_info)
        if not target_path:
            return []
        return [
            VesselRecommendedAction(
                action_type="AUDIT_REVIEW" if row.source_object_type in EVIDENCE_AUDIT_SOURCE_TYPES | {"VESSEL_BLACKLIST_SIGNAL"} or (row.source_object_type == "VESSEL_RISK_SIGNAL" and audit_info and audit_info.get("audit_action_path")) else "FIX_SOURCE",
                label=self._task_action_label(row),
                target_path=target_path,
                target_object_type=row.source_object_type,
                target_object_id=row.source_object_id,
                required_fields=[field for field in [self._task_field_anchor(row)] if field],
                source_object_anchor=self._task_source_anchor(row),
                workbench_group=self._task_workbench_group(row),
                description="进入源对象完成数据修复或证据补充，重新校验通过后任务才能关闭。",
            )
        ]

    @staticmethod
    def _task_action_label(row: VesselGovernanceTask) -> str:
        return {
            "VESSEL_DATA_QUALITY_ISSUE": "定位字段并修复",
            "VESSEL_RISK_SIGNAL": "查看风险修复建议",
            "VESSEL_CONTROLLER_EVIDENCE": "审核控制人证据",
            "VESSEL_AFFILIATION_EVIDENCE": "审核挂靠/授权证据",
            "VESSEL_BLACKLIST_SIGNAL": "复核名单信号",
            "VESSEL_RECOGNITION_FIELD_DIFF": "确认 OCR 字段",
            "VESSEL_CANDIDATE_ANALYSIS_ANNOTATION": "查看候选标注",
        }.get(row.source_object_type, "查看源对象")

    @staticmethod
    def _task_sla_due_at(row: VesselGovernanceTask) -> datetime | None:
        start = row.first_seen_at or row.created_at
        if start is None:
            return None
        hours = {"URGENT": 8, "HIGH": 24, "MEDIUM": 72, "LOW": 168}.get(row.priority_code or "MEDIUM", 72)
        return start + timedelta(hours=hours)

    def _task_overdue_level(self, row: VesselGovernanceTask) -> str:
        if row.status_code not in ACTIVE_TASK_STATUSES:
            return "NONE"
        due_at = self._task_sla_due_at(row)
        if due_at is None:
            return "UNKNOWN"
        hours = (_utcnow() - due_at).total_seconds() / 3600
        if hours >= 24:
            return "SEVERE"
        if hours >= 0:
            return "OVERDUE"
        if hours >= -8:
            return "DUE_SOON"
        return "NORMAL"

    def _task_priority_score(self, row: VesselGovernanceTask) -> int:
        base = {"URGENT": 100, "HIGH": 80, "MEDIUM": 50, "LOW": 20}.get(row.priority_code or "MEDIUM", 50)
        overdue_bonus = {"SEVERE": 40, "OVERDUE": 25, "DUE_SOON": 10}.get(self._task_overdue_level(row), 0)
        duplicate_bonus = min(int(row.duplicate_count or 0), 20)
        return base + overdue_bonus + duplicate_bonus

    @staticmethod
    def _task_validation_entrypoint(row: VesselGovernanceTask) -> str | None:
        return {
            "VESSEL_DATA_QUALITY_ISSUE": "POST /api/v1/vessels/quality/{issue_id}/recheck",
            "VESSEL_RISK_SIGNAL": "POST /api/v1/vessels/{vessel_id}/compliance-risk/refresh",
            "VESSEL_CONTROLLER_EVIDENCE": "AuditTaskService.approve/reject",
            "VESSEL_AFFILIATION_EVIDENCE": "AuditTaskService.approve/reject",
            "VESSEL_BLACKLIST_SIGNAL": "AuditTaskService.approve/reject",
        }.get(row.source_object_type)

    @staticmethod
    def _task_source_anchor(row: VesselGovernanceTask) -> str:
        return f"{row.source_object_type}:{row.source_object_id}"

    @staticmethod
    def _task_workbench_group(row: VesselGovernanceTask) -> str:
        return {
            "VESSEL_DATA_QUALITY_ISSUE": "QUALITY",
            "VESSEL_RISK_SIGNAL": "RISK",
            "VESSEL_CONTROLLER_EVIDENCE": "EVIDENCE",
            "VESSEL_AFFILIATION_EVIDENCE": "EVIDENCE",
            "VESSEL_BLACKLIST_SIGNAL": "BLACKLIST",
            "VESSEL_RECOGNITION_FIELD_DIFF": "OCR",
            "VESSEL_CANDIDATE_ANALYSIS_ANNOTATION": "CANDIDATE",
        }.get(row.source_object_type, "TASK")

    def _task_explain_reason(self, row: VesselGovernanceTask) -> str:
        reason = row.generation_reason_json or {}
        trigger = reason.get("reason") or reason.get("source_reason") or row.evidence_summary or row.description
        rule = row.source_rule_code or row.source_object_type
        batch = f"同步批次 #{row.source_batch_id}" if row.source_batch_id else "人工或历史任务"
        if trigger:
            return f"{batch} 根据规则 {rule} 生成：{trigger}"
        return f"{batch} 根据规则 {rule} 生成，源对象为 {self._task_source_anchor(row)}。"

    def _task_evidence_gaps(self, row: VesselGovernanceTask) -> list[str]:
        if row.source_object_type == "VESSEL_DATA_QUALITY_ISSUE":
            field = self._task_field_anchor(row)
            return [item for item in [field or "源字段", "重新校验通过记录"] if item]
        if row.source_object_type == "VESSEL_RISK_SIGNAL":
            return ["风险源证据", "合规重算结果", "必要时的风险复核意见"]
        if row.source_object_type in {"VESSEL_CONTROLLER_EVIDENCE", "VESSEL_AFFILIATION_EVIDENCE"}:
            return ["证据摘要", "审核意见", "候选/当前结论确认"]
        if row.source_object_type == "VESSEL_BLACKLIST_SIGNAL":
            return ["名单证据", "有效期", "复核或解除原因"]
        if row.source_object_type == "VESSEL_RECOGNITION_FIELD_DIFF":
            return ["识别字段", "采纳/跳过原因"]
        return []

    @staticmethod
    def _task_field_anchor(row: VesselGovernanceTask) -> str | None:
        impact = row.impact_summary_json or {}
        field_name = impact.get("field_name") or impact.get("field")
        if field_name:
            return str(field_name)
        trace = row.source_trace_json or []
        if isinstance(trace, list):
            for item in trace:
                if isinstance(item, dict) and item.get("field_name"):
                    return str(item["field_name"])
        return None

    def _task_action_path(self, row: VesselGovernanceTask, audit_info: dict[str, Any] | None = None) -> str | None:
        vessel_id = row.vessel_profile_id
        source_id = row.source_object_id
        field = self._task_field_anchor(row)
        if row.source_object_type == "VESSEL_DATA_QUALITY_ISSUE":
            suffix = f"?quality_issue_id={source_id}"
            if field:
                suffix = f"{suffix}&field={field}"
            return f"/vessels/{vessel_id}/edit{suffix}" if vessel_id else f"/vessels/quality?quality_issue_id={source_id}"
        if row.source_object_type == "VESSEL_RISK_SIGNAL":
            if audit_info and audit_info.get("audit_action_path"):
                return str(audit_info["audit_action_path"])
            return f"/vessels/{vessel_id}/compliance?risk_signal_id={source_id}" if vessel_id else f"/vessels/compliance-risks?risk_signal_id={source_id}"
        if row.source_object_type == "VESSEL_CONTROLLER_EVIDENCE":
            if audit_info and audit_info.get("audit_action_path"):
                return str(audit_info["audit_action_path"])
            return f"/vessels/{vessel_id}/relations?tab=controller&evidence_id={source_id}" if vessel_id else None
        if row.source_object_type == "VESSEL_AFFILIATION_EVIDENCE":
            if audit_info and audit_info.get("audit_action_path"):
                return str(audit_info["audit_action_path"])
            return f"/vessels/{vessel_id}/relations?tab=affiliation&evidence_id={source_id}" if vessel_id else None
        if row.source_object_type == "VESSEL_BLACKLIST_SIGNAL":
            if audit_info and audit_info.get("audit_action_path"):
                return str(audit_info["audit_action_path"])
            vessel_query = f"&vessel_id={vessel_id}" if vessel_id else ""
            return f"/vessels/blacklist-signals?blacklist_signal_id={source_id}{vessel_query}"
        if row.source_object_type == "VESSEL_RECOGNITION_FIELD_DIFF":
            return f"/vessels/recognitions?vessel_id={vessel_id}&field_diff_id={source_id}"
        if row.source_object_type == "VESSEL_CANDIDATE_ANALYSIS_ANNOTATION":
            return f"/vessels/candidate-analysis?annotation_id={source_id}"
        return f"/vessels/{vessel_id}/profile-card" if vessel_id else None

    @staticmethod
    def _task_verification_status(row: VesselGovernanceTask) -> str:
        if row.source_object_type in {"VESSEL_DATA_QUALITY_ISSUE", "VESSEL_RISK_SIGNAL"}:
            if row.status_code == "RESOLVED":
                return "PASSED"
            return "WAITING_RECHECK"
        if row.source_object_type in {"VESSEL_CONTROLLER_EVIDENCE", "VESSEL_AFFILIATION_EVIDENCE"}:
            return "WAITING_REVIEW" if row.status_code in ACTIVE_TASK_STATUSES else "REVIEWED"
        if row.source_object_type == "VESSEL_BLACKLIST_SIGNAL":
            return "WAITING_REVIEW" if row.status_code in ACTIVE_TASK_STATUSES else "REVIEWED"
        return "NOT_REQUIRED"

    @staticmethod
    def _task_verification_message(row: VesselGovernanceTask) -> str | None:
        if row.source_object_type == "VESSEL_DATA_QUALITY_ISSUE":
            return "修复字段并重新计算摘要后，质量问题关闭时任务才能关闭。"
        if row.source_object_type == "VESSEL_RISK_SIGNAL":
            return "补证或修复数据后重新跑合规规则；仍命中时请走风险复核。"
        if row.source_object_type in {"VESSEL_CONTROLLER_EVIDENCE", "VESSEL_AFFILIATION_EVIDENCE"}:
            return "审核通过会生成候选结论；业务人员确认后才成为当前主体关系。"
        if row.source_object_type == "VESSEL_BLACKLIST_SIGNAL":
            return "名单复核、解除或作废必须在审核中心完成，治理任务只镜像审核结果。"
        return None

    @staticmethod
    def _risk_review_response(row: VesselRiskReview, audit: AuditTask | None = None) -> VesselRiskReviewResponse:
        return VesselRiskReviewResponse(
            **_row_dict(row),
            audit_task_id=int(audit.id) if audit else None,
            audit_task_no=audit.task_no if audit else None,
            audit_status_code=audit.audit_status if audit else None,
            audit_action_path=f"/audit/tasks/{audit.id}" if audit else None,
        )

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
