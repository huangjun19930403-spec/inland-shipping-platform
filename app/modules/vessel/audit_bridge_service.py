"""Bridge audit-center decisions back into vessel governance state."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditTask, AuditTaskSnapshot
from app.models.vessel import (
    VesselAffiliationEvidence,
    VesselBlacklistSignal,
    VesselControllerEvidence,
    VesselGovernanceTask,
    VesselRiskReview,
    VesselRiskSignal,
)
from app.modules.vessel.service import VesselService


logger = logging.getLogger(__name__)

EVIDENCE_AUDIT_OBJECT_TYPES = {"VESSEL_CONTROLLER_EVIDENCE", "VESSEL_AFFILIATION_EVIDENCE"}
VESSEL_AUDIT_OBJECT_TYPES = EVIDENCE_AUDIT_OBJECT_TYPES | {"VESSEL_RISK_REVIEW", "VESSEL_BLACKLIST_SIGNAL"}
ACTIVE_GOVERNANCE_STATUSES = {"OPEN", "ASSIGNED", "IN_PROGRESS", "REOPENED"}
COMPLIANCE_CLOSED_STATUSES = {"MITIGATED", "CLOSED", "FALSE_POSITIVE"}


@dataclass(slots=True)
class VesselAuditBridgeResult:
    status_code: str
    message: str
    vessel_id: int | None = None
    related_governance_task_id: int | None = None
    related_object_path: str | None = None


class VesselAuditBridgeService:
    """Keeps vessel evidence governance mirrored to the single audit workflow."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def sync_after_audit(
        self,
        task: AuditTask,
        *,
        target_status: str,
        operator_user_id: int | None,
        audited_at: datetime,
    ) -> VesselAuditBridgeResult:
        object_type = self._object_type(task)
        if object_type not in VESSEL_AUDIT_OBJECT_TYPES:
            return VesselAuditBridgeResult(status_code="NOT_REQUIRED", message="非船舶证据审核对象，无需同步")
        if object_type == "VESSEL_RISK_REVIEW":
            return await self._sync_risk_review_after_audit(task, target_status=target_status, operator_user_id=operator_user_id, audited_at=audited_at)
        if object_type == "VESSEL_BLACKLIST_SIGNAL":
            return await self._sync_blacklist_after_audit(task, target_status=target_status, operator_user_id=operator_user_id, audited_at=audited_at)
        evidence = await self._load_evidence(object_type, task.biz_id)
        if evidence is None:
            return VesselAuditBridgeResult(status_code="TARGET_MISSING", message="船舶证据对象不存在")

        vessel_id = int(evidence.vessel_profile_id)
        await VesselService(self.db).rebuild_relation_conclusion_candidates(
            vessel_id,
            operator_id=operator_user_id,
            commit=False,
        )
        governance_task = await self._mirror_governance_task(
            object_type=object_type,
            object_id=int(task.biz_id),
            audit_status=target_status,
            operator_user_id=operator_user_id,
            audited_at=audited_at,
            audit_task_id=int(task.id),
            audit_task_no=task.task_no,
        )
        await self.db.flush()
        return VesselAuditBridgeResult(
            status_code="SYNCED",
            message="已同步证据审核状态、主体结论候选和治理任务镜像",
            vessel_id=vessel_id,
            related_governance_task_id=governance_task.id if governance_task else None,
            related_object_path=self._object_path(object_type, vessel_id, int(task.biz_id)),
        )

    async def refresh_compliance_best_effort(self, vessel_id: int, *, operator_user_id: int | None) -> None:
        try:
            await VesselService(self.db).refresh_compliance_risk(vessel_id, operator_id=operator_user_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("vessel audit bridge compliance refresh failed for profile %s: %s", vessel_id, exc)
            await self.db.rollback()

    async def detail_context(self, task: AuditTask) -> dict[str, Any]:
        object_type = self._object_type(task)
        if object_type not in VESSEL_AUDIT_OBJECT_TYPES:
            return {
                "related_governance_task_id": None,
                "related_object_path": None,
                "business_sync_status_code": "NOT_REQUIRED",
                "business_sync_message": "非船舶证据审核对象，无需同步",
            }
        if object_type == "VESSEL_RISK_REVIEW":
            return await self._risk_review_detail_context(task)
        if object_type == "VESSEL_BLACKLIST_SIGNAL":
            return await self._blacklist_detail_context(task)
        evidence = await self._load_evidence(object_type, task.biz_id)
        governance_task = await self._related_governance_task(object_type, int(task.biz_id))
        if evidence is None:
            return {
                "related_governance_task_id": governance_task.id if governance_task else None,
                "related_object_path": None,
                "business_sync_status_code": "TARGET_MISSING",
                "business_sync_message": "船舶证据对象不存在",
            }
        return {
            "related_governance_task_id": governance_task.id if governance_task else None,
            "related_object_path": self._object_path(object_type, int(evidence.vessel_profile_id), int(task.biz_id)),
            "business_sync_status_code": self._detail_sync_status(task, evidence, governance_task),
            "business_sync_message": self._detail_sync_message(task, evidence, governance_task),
        }

    async def _load_evidence(self, object_type: str, object_id: int) -> VesselControllerEvidence | VesselAffiliationEvidence | None:
        model = VesselControllerEvidence if object_type == "VESSEL_CONTROLLER_EVIDENCE" else VesselAffiliationEvidence
        return await self.db.get(model, object_id)

    async def _sync_risk_review_after_audit(
        self,
        task: AuditTask,
        *,
        target_status: str,
        operator_user_id: int | None,
        audited_at: datetime,
    ) -> VesselAuditBridgeResult:
        review = await self.db.get(VesselRiskReview, task.biz_id)
        if review is None:
            return VesselAuditBridgeResult(status_code="TARGET_MISSING", message="风险复核记录不存在")
        signal = await self.db.get(VesselRiskSignal, review.risk_signal_id) if review.risk_signal_id else None
        governance_task = await self.db.get(VesselGovernanceTask, review.governance_task_id) if review.governance_task_id else None
        if target_status == "APPROVED" and signal is not None:
            signal.status_code = review.to_status_code or signal.status_code
            if review.risk_level_after:
                signal.risk_level = review.risk_level_after
            signal.evidence_json = {
                **(signal.evidence_json or {}),
                "approved_risk_review": {
                    "risk_review_id": review.id,
                    "audit_task_id": task.id,
                    "review_action_code": review.review_action_code,
                },
            }
            if signal.status_code in COMPLIANCE_CLOSED_STATUSES:
                signal.resolution_reason = review.review_reason or task.audit_remark
                signal.resolved_by = operator_user_id
                signal.resolved_at = audited_at
            signal.revision = int(signal.revision or 1) + 1
            signal.updated_at = audited_at
        elif signal is not None:
            signal.status_code = review.from_status_code or "OPEN"
            signal.updated_at = audited_at
            signal.revision = int(signal.revision or 1) + 1

        if governance_task is None and review.risk_signal_id is not None:
            governance_task = await self._related_governance_task("VESSEL_RISK_SIGNAL", int(review.risk_signal_id))
        if governance_task is not None:
            governance_task.source_status_code = signal.status_code if signal else target_status
            if governance_task.status_code in ACTIVE_GOVERNANCE_STATUSES:
                if target_status == "APPROVED" and signal is not None and signal.status_code in COMPLIANCE_CLOSED_STATUSES:
                    governance_task.status_code = "RESOLVED"
                elif target_status == "REJECTED":
                    governance_task.status_code = "REOPENED"
                governance_task.resolved_at = audited_at if governance_task.status_code == "RESOLVED" else None
                governance_task.resolved_by = operator_user_id if governance_task.status_code == "RESOLVED" else None
                governance_task.resolution_reason = task.audit_remark
                governance_task.resolution_evidence_json = {
                    **(governance_task.resolution_evidence_json or {}),
                    "audit_task_id": task.id,
                    "audit_task_no": task.task_no,
                    "audit_status_code": target_status,
                }
            governance_task.revision = int(governance_task.revision or 1) + 1
            governance_task.updated_at = audited_at
        vessel_id = int(review.vessel_profile_id)
        return VesselAuditBridgeResult(
            status_code="SYNCED",
            message="已同步风险复核审核结果、风险信号和治理任务镜像",
            vessel_id=vessel_id,
            related_governance_task_id=governance_task.id if governance_task else None,
            related_object_path=f"/vessels/{vessel_id}/compliance?risk_signal_id={review.risk_signal_id}",
        )

    async def _sync_blacklist_after_audit(
        self,
        task: AuditTask,
        *,
        target_status: str,
        operator_user_id: int | None,
        audited_at: datetime,
    ) -> VesselAuditBridgeResult:
        signal = await self.db.get(VesselBlacklistSignal, task.biz_id)
        if signal is None:
            return VesselAuditBridgeResult(status_code="TARGET_MISSING", message="名单信号不存在")
        summary = await self._audit_summary(task)
        governance_task = await self._related_governance_task("VESSEL_BLACKLIST_SIGNAL", int(signal.id))
        if target_status == "APPROVED":
            action = str(summary.get("review_action_code") or "VOID").upper()
            if action in {"VOID", "RELEASE", "CANCEL"}:
                signal.status_code = "VOIDED"
                signal.voided_at = audited_at
                signal.voided_by = operator_user_id
                signal.void_reason = str(summary.get("reason") or task.audit_remark or "名单信号审核解除")
                from app.modules.vessel.governance_service import VesselGovernanceService

                await VesselGovernanceService(self.db)._close_blacklist_risk(
                    signal,
                    reason=signal.void_reason,
                    operator_id=operator_user_id,
                )
            else:
                signal.status_code = "ACTIVE"
        elif signal.status_code == "IN_REVIEW":
            signal.status_code = "ACTIVE"
        signal.revision = int(signal.revision or 1) + 1
        signal.updated_at = audited_at
        if governance_task is not None:
            governance_task.source_status_code = signal.status_code
            if governance_task.status_code in ACTIVE_GOVERNANCE_STATUSES:
                governance_task.status_code = "RESOLVED" if target_status == "APPROVED" and signal.status_code == "VOIDED" else "REOPENED"
                governance_task.resolved_at = audited_at if governance_task.status_code == "RESOLVED" else None
                governance_task.resolved_by = operator_user_id if governance_task.status_code == "RESOLVED" else None
                governance_task.resolution_reason = task.audit_remark
                governance_task.resolution_evidence_json = {
                    **(governance_task.resolution_evidence_json or {}),
                    "audit_task_id": task.id,
                    "audit_task_no": task.task_no,
                    "audit_status_code": target_status,
                }
            governance_task.revision = int(governance_task.revision or 1) + 1
            governance_task.updated_at = audited_at
        return VesselAuditBridgeResult(
            status_code="SYNCED",
            message="已同步名单审核结果、风险信号和治理任务镜像",
            vessel_id=int(signal.vessel_profile_id),
            related_governance_task_id=governance_task.id if governance_task else None,
            related_object_path=f"/vessels/blacklist-signals?blacklist_signal_id={signal.id}&vessel_id={signal.vessel_profile_id}",
        )

    async def _risk_review_detail_context(self, task: AuditTask) -> dict[str, Any]:
        review = await self.db.get(VesselRiskReview, task.biz_id)
        governance_task = None
        if review is not None:
            governance_task = await self._related_governance_task("VESSEL_RISK_SIGNAL", int(review.risk_signal_id)) if review.risk_signal_id else None
        return {
            "related_governance_task_id": governance_task.id if governance_task else None,
            "related_object_path": (
                f"/vessels/{review.vessel_profile_id}/compliance?risk_signal_id={review.risk_signal_id}"
                if review is not None
                else None
            ),
            "business_sync_status_code": "WAITING_AUDIT" if task.audit_status == "PENDING" else "SYNCED",
            "business_sync_message": "风险复核审核完成后将同步风险信号和治理任务" if task.audit_status == "PENDING" else "风险复核结果已同步到船舶治理",
        }

    async def _blacklist_detail_context(self, task: AuditTask) -> dict[str, Any]:
        signal = await self.db.get(VesselBlacklistSignal, task.biz_id)
        governance_task = await self._related_governance_task("VESSEL_BLACKLIST_SIGNAL", int(task.biz_id))
        return {
            "related_governance_task_id": governance_task.id if governance_task else None,
            "related_object_path": (
                f"/vessels/blacklist-signals?blacklist_signal_id={task.biz_id}&vessel_id={signal.vessel_profile_id}"
                if signal is not None
                else None
            ),
            "business_sync_status_code": "WAITING_AUDIT" if task.audit_status == "PENDING" else "SYNCED",
            "business_sync_message": "名单审核完成后将同步名单状态、风险信号和治理任务" if task.audit_status == "PENDING" else "名单审核结果已同步到船舶治理",
        }

    async def _audit_summary(self, task: AuditTask) -> dict[str, Any]:
        snapshot = await self.db.scalar(select(AuditTaskSnapshot).where(AuditTaskSnapshot.task_id == task.id))
        return snapshot.summary_json or {} if snapshot is not None else {}

    async def _mirror_governance_task(
        self,
        *,
        object_type: str,
        object_id: int,
        audit_status: str,
        operator_user_id: int | None,
        audited_at: datetime,
        audit_task_id: int,
        audit_task_no: str,
    ) -> VesselGovernanceTask | None:
        rows = (
            await self.db.scalars(
                select(VesselGovernanceTask).where(
                    VesselGovernanceTask.source_object_type == object_type,
                    VesselGovernanceTask.source_object_id == str(object_id),
                )
            )
        ).all()
        if not rows:
            return None
        target = rows[0]
        next_status = "RESOLVED" if audit_status == "APPROVED" else "CANNOT_RESOLVE"
        reason = f"审核中心任务 {audit_task_no} 已{('通过' if audit_status == 'APPROVED' else '驳回')}"
        for row in rows:
            row.source_status_code = audit_status
            if row.status_code in ACTIVE_GOVERNANCE_STATUSES:
                row.status_code = next_status
                row.resolved_at = audited_at
                row.resolved_by = operator_user_id
                row.resolution_reason = reason
                row.resolution_evidence_json = {
                    **(row.resolution_evidence_json or {}),
                    "audit_task_id": audit_task_id,
                    "audit_task_no": audit_task_no,
                    "audit_status_code": audit_status,
                }
            row.revision = int(row.revision or 1) + 1
            row.updated_at = audited_at
        return target

    async def _related_governance_task(self, object_type: str, object_id: int) -> VesselGovernanceTask | None:
        return await self.db.scalar(
            select(VesselGovernanceTask)
            .where(
                VesselGovernanceTask.source_object_type == object_type,
                VesselGovernanceTask.source_object_id == str(object_id),
            )
            .order_by(VesselGovernanceTask.updated_at.desc(), VesselGovernanceTask.id.desc())
            .limit(1)
        )

    @staticmethod
    def _object_type(task: AuditTask) -> str | None:
        return task.object_type_code or task.biz_type_code or task.biz_code

    @staticmethod
    def _object_path(object_type: str, vessel_id: int, object_id: int) -> str:
        tab = "controller" if object_type == "VESSEL_CONTROLLER_EVIDENCE" else "affiliation"
        return f"/vessels/{vessel_id}/relations?tab={tab}&evidence_id={object_id}"

    @staticmethod
    def _detail_sync_status(
        task: AuditTask,
        evidence: VesselControllerEvidence | VesselAffiliationEvidence,
        governance_task: VesselGovernanceTask | None,
    ) -> str:
        if task.audit_status == "PENDING":
            return "WAITING_AUDIT"
        if evidence.verified_status_code == task.audit_status and governance_task is not None:
            return "SYNCED"
        return "SYNC_PENDING"

    @staticmethod
    def _detail_sync_message(
        task: AuditTask,
        evidence: VesselControllerEvidence | VesselAffiliationEvidence,
        governance_task: VesselGovernanceTask | None,
    ) -> str:
        if task.audit_status == "PENDING":
            return "审核完成后将自动同步证据状态、主体结论候选、合规风险和治理任务镜像"
        if evidence.verified_status_code != task.audit_status:
            return "审核结果尚未同步到船舶证据，请刷新或检查桥接任务"
        if governance_task is None:
            return "证据状态已同步；未找到关联治理任务"
        return "证据状态、主体结论和关联治理任务已同步"
