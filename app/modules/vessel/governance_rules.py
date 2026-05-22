from __future__ import annotations

from app.core.exceptions import NotFoundError
from app.models.vessel import VesselGovernanceSyncBatch
from app.modules.vessel.schemas import VesselGovernanceRuleResponse, VesselGovernanceSyncBatchResponse


_RULE_CATALOG = (
    ("VESSEL_DATA_QUALITY_ISSUE", "数据质量问题生成治理任务", "VESSEL_DATA_QUALITY_ISSUE", "QUALITY_ISSUE", "BY_SEVERITY", "质量问题状态为 OPEN/IN_PROGRESS 时生成任务，字段修复并重校验通过后关闭。", "POST /api/v1/vessels/quality/{issue_id}/recheck", "RECHECK_REQUIRED", "/vessels/quality", ["源字段修复", "重新校验通过记录"]),
    ("VESSEL_RISK_SIGNAL", "高风险/未知风险生成复核任务", "VESSEL_RISK_SIGNAL", "RISK_REVIEW", "HIGH_OR_MEDIUM", "风险状态仍命中且等级为 HIGH/UNKNOWN 时生成复核任务。", "POST /api/v1/vessels/{vessel_id}/compliance-risk/refresh", "RISK_RECHECK_OR_APPROVAL_REQUIRED", "/vessels/compliance-risks", ["风险源证据", "合规重算结果", "风险复核审批意见"]),
    ("VESSEL_CONTROLLER_EVIDENCE", "实际控制人证据审批提醒", "VESSEL_CONTROLLER_EVIDENCE", "CONTROLLER_AFFILIATION", "MEDIUM", "控制人证据处于 DRAFT/PENDING/CHANGE_REQUESTED 时生成提醒任务。", "ApprovalService.approve/reject", "APPROVAL_CENTER_ONLY", "/approvals/instances", ["结构化证据", "附件引用", "审批意见"]),
    ("VESSEL_AFFILIATION_EVIDENCE", "挂靠/授权证据审批提醒", "VESSEL_AFFILIATION_EVIDENCE", "CONTROLLER_AFFILIATION", "MEDIUM", "挂靠/授权证据处于 DRAFT/PENDING/CHANGE_REQUESTED 时生成提醒任务。", "ApprovalService.approve/reject", "APPROVAL_CENTER_ONLY", "/approvals/instances", ["协议信息", "资质证明", "审批意见"]),
    ("VESSEL_BLACKLIST_SIGNAL", "名单信号复核任务", "VESSEL_BLACKLIST_SIGNAL", "BLACKLIST_REVIEW", "BY_RISK_LEVEL", "名单信号 ACTIVE 且未作废时生成复核任务，解除/作废需走审批中心。", "ApprovalService.approve/reject", "APPROVAL_CENTER_ONLY", "/vessels/blacklist-signals", ["名单证据", "有效期", "解除或作废审批意见"]),
    ("VESSEL_CANDIDATE_ANALYSIS_ANNOTATION", "候选分析标注复核任务", "VESSEL_CANDIDATE_ANALYSIS_ANNOTATION", "CANDIDATE_REVIEW", "MEDIUM", "候选适配结果被标注为证据不足、证书风险、位置异常或需复核时生成任务。", None, "MANUAL_REVIEW_WITH_REASON", "/vessels/candidate-analysis", ["标注原因", "候选项上下文"]),
)


class VesselGovernanceRulesMixin:
    async def get_sync_batch(self, batch_id: int) -> VesselGovernanceSyncBatchResponse:
        row = await self.db.get(VesselGovernanceSyncBatch, batch_id)
        if row is None:
            raise NotFoundError("VesselGovernanceSyncBatch", batch_id)
        return VesselGovernanceSyncBatchResponse.model_validate(row, from_attributes=True)

    async def list_rule_catalog(self) -> list[VesselGovernanceRuleResponse]:
        return [
            VesselGovernanceRuleResponse(
                rule_code=rule_code,
                rule_name=rule_name,
                source_object_type=source_object_type,
                task_type_code=task_type_code,
                default_priority_code=default_priority_code,
                generation_reason=generation_reason,
                validation_entrypoint=validation_entrypoint,
                close_policy=close_policy,
                target_path=target_path,
                evidence_requirements=evidence_requirements,
            )
            for (
                rule_code,
                rule_name,
                source_object_type,
                task_type_code,
                default_priority_code,
                generation_reason,
                validation_entrypoint,
                close_policy,
                target_path,
                evidence_requirements,
            ) in _RULE_CATALOG
        ]
