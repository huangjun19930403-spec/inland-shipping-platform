"""Governance task service boundary for vessel routes."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.vessel.governance_service import VesselGovernanceService
from app.models.vessel import VesselGovernanceSyncBatch
from app.modules.vessel.schemas import (
    PageResponse,
    VesselBlacklistSignalCreateRequest,
    VesselBlacklistSignalGlobalQuery,
    VesselBlacklistSignalListItemResponse,
    VesselBlacklistSignalResponse,
    VesselBlacklistSignalUpdateRequest,
    VesselGovernanceDashboardResponse,
    VesselGovernanceRuleResponse,
    VesselGovernanceSyncBatchResponse,
    VesselGovernanceTaskActionRequest,
    VesselGovernanceTaskQuery,
    VesselGovernanceTaskResponse,
    VesselGovernanceTaskSyncResponse,
    VesselRiskReviewRequest,
    VesselRiskReviewResponse,
)
from app.core.exceptions import NotFoundError


class VesselGovernanceTaskService:
    """Facade for workbench, task queue, sync batch, and blacklist workflows."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._facade = VesselGovernanceService(db)

    async def dashboard(self) -> VesselGovernanceDashboardResponse:
        return await self._facade.dashboard()

    async def list_tasks(self, query: VesselGovernanceTaskQuery) -> PageResponse[VesselGovernanceTaskResponse]:
        return await self._facade.list_tasks(query)

    async def sync_tasks_command(
        self,
        *,
        operator_id: int | None = None,
        trigger_type_code: str = "MANUAL",
    ) -> VesselGovernanceTaskSyncResponse:
        return await self._facade.sync_tasks_command(operator_id=operator_id, trigger_type_code=trigger_type_code)

    async def update_task(
        self,
        task_id: int,
        payload: VesselGovernanceTaskActionRequest,
        *,
        operator_id: int | None = None,
    ) -> VesselGovernanceTaskResponse:
        return await self._facade.update_task(task_id, payload, operator_id=operator_id)

    async def get_sync_batch(self, batch_id: int) -> VesselGovernanceSyncBatchResponse:
        row = await self.db.get(VesselGovernanceSyncBatch, batch_id)
        if row is None:
            raise NotFoundError("VesselGovernanceSyncBatch", batch_id)
        return VesselGovernanceSyncBatchResponse.model_validate(row, from_attributes=True)

    async def list_rule_catalog(self) -> list[VesselGovernanceRuleResponse]:
        return [
            VesselGovernanceRuleResponse(
                rule_code="VESSEL_DATA_QUALITY_ISSUE",
                rule_name="数据质量问题生成治理任务",
                source_object_type="VESSEL_DATA_QUALITY_ISSUE",
                task_type_code="QUALITY_ISSUE",
                default_priority_code="BY_SEVERITY",
                generation_reason="质量问题状态为 OPEN/IN_PROGRESS 时生成任务，字段修复并重校验通过后关闭。",
                validation_entrypoint="POST /api/v1/vessels/quality/{issue_id}/recheck",
                close_policy="RECHECK_REQUIRED",
                target_path="/vessels/quality",
                evidence_requirements=["源字段修复", "重新校验通过记录"],
            ),
            VesselGovernanceRuleResponse(
                rule_code="VESSEL_RISK_SIGNAL",
                rule_name="高风险/未知风险生成复核任务",
                source_object_type="VESSEL_RISK_SIGNAL",
                task_type_code="RISK_REVIEW",
                default_priority_code="HIGH_OR_MEDIUM",
                generation_reason="风险状态仍命中且等级为 HIGH/UNKNOWN 时生成复核任务。",
                validation_entrypoint="POST /api/v1/vessels/{vessel_id}/compliance-risk/refresh",
                close_policy="RISK_RECHECK_OR_AUDIT_REVIEW_REQUIRED",
                target_path="/vessels/compliance-risks",
                evidence_requirements=["风险源证据", "合规重算结果", "风险复核审核意见"],
            ),
            VesselGovernanceRuleResponse(
                rule_code="VESSEL_CONTROLLER_EVIDENCE",
                rule_name="实际控制人证据审核提醒",
                source_object_type="VESSEL_CONTROLLER_EVIDENCE",
                task_type_code="CONTROLLER_AFFILIATION",
                default_priority_code="MEDIUM",
                generation_reason="控制人证据处于 DRAFT/PENDING/CHANGE_REQUESTED 时生成提醒任务。",
                validation_entrypoint="AuditTaskService.approve/reject",
                close_policy="AUDIT_CENTER_ONLY",
                target_path="/audit/tasks",
                evidence_requirements=["结构化证据", "附件引用", "审核意见"],
            ),
            VesselGovernanceRuleResponse(
                rule_code="VESSEL_AFFILIATION_EVIDENCE",
                rule_name="挂靠/授权证据审核提醒",
                source_object_type="VESSEL_AFFILIATION_EVIDENCE",
                task_type_code="CONTROLLER_AFFILIATION",
                default_priority_code="MEDIUM",
                generation_reason="挂靠/授权证据处于 DRAFT/PENDING/CHANGE_REQUESTED 时生成提醒任务。",
                validation_entrypoint="AuditTaskService.approve/reject",
                close_policy="AUDIT_CENTER_ONLY",
                target_path="/audit/tasks",
                evidence_requirements=["协议信息", "资质证明", "审核意见"],
            ),
            VesselGovernanceRuleResponse(
                rule_code="VESSEL_BLACKLIST_SIGNAL",
                rule_name="名单信号复核任务",
                source_object_type="VESSEL_BLACKLIST_SIGNAL",
                task_type_code="BLACKLIST_REVIEW",
                default_priority_code="BY_RISK_LEVEL",
                generation_reason="名单信号 ACTIVE 且未作废时生成复核任务，解除/作废需走审核中心。",
                validation_entrypoint="AuditTaskService.approve/reject",
                close_policy="AUDIT_CENTER_ONLY",
                target_path="/vessels/blacklist-signals",
                evidence_requirements=["名单证据", "有效期", "解除或作废审核意见"],
            ),
            VesselGovernanceRuleResponse(
                rule_code="VESSEL_CANDIDATE_ANALYSIS_ANNOTATION",
                rule_name="候选分析标注复核任务",
                source_object_type="VESSEL_CANDIDATE_ANALYSIS_ANNOTATION",
                task_type_code="CANDIDATE_REVIEW",
                default_priority_code="MEDIUM",
                generation_reason="候选适配结果被标注为证据不足、证书风险、位置异常或需复核时生成任务。",
                validation_entrypoint=None,
                close_policy="MANUAL_REVIEW_WITH_REASON",
                target_path="/vessels/candidate-analysis",
                evidence_requirements=["标注原因", "候选项上下文"],
            ),
        ]

    async def create_risk_review(
        self,
        vessel_id: int,
        payload: VesselRiskReviewRequest,
        *,
        operator_id: int | None = None,
    ) -> VesselRiskReviewResponse:
        return await self._facade.create_risk_review(vessel_id, payload, operator_id=operator_id)

    async def list_blacklist_signal_queue(
        self,
        query: VesselBlacklistSignalGlobalQuery,
    ) -> PageResponse[VesselBlacklistSignalListItemResponse]:
        return await self._facade.list_blacklist_signal_queue(query)

    async def list_blacklist_signals(self, vessel_id: int) -> list[VesselBlacklistSignalResponse]:
        return await self._facade.list_blacklist_signals(vessel_id)

    async def create_blacklist_signal(
        self,
        vessel_id: int,
        payload: VesselBlacklistSignalCreateRequest,
        *,
        operator_id: int | None = None,
    ) -> VesselBlacklistSignalResponse:
        return await self._facade.create_blacklist_signal(vessel_id, payload, operator_id=operator_id)

    async def update_blacklist_signal(
        self,
        vessel_id: int,
        signal_id: int,
        payload: VesselBlacklistSignalUpdateRequest,
        *,
        operator_id: int | None = None,
    ) -> VesselBlacklistSignalResponse:
        return await self._facade.update_blacklist_signal(vessel_id, signal_id, payload, operator_id=operator_id)

    async def void_blacklist_signal(
        self,
        vessel_id: int,
        signal_id: int,
        payload: Any,
        *,
        operator_id: int | None = None,
    ) -> VesselBlacklistSignalResponse:
        return await self._facade.void_blacklist_signal(vessel_id, signal_id, payload, operator_id=operator_id)
