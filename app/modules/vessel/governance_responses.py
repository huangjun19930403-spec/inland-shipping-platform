from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.models.vessel import VesselBlacklistSignal, VesselGovernanceTask, VesselProfile, VesselRiskReview
from app.modules.vessel.schemas import (
    VesselBlacklistSignalResponse,
    VesselGovernanceTaskResponse,
    VesselQualityIssueVesselSummary,
    VesselRecommendedAction,
    VesselRiskReviewResponse,
)
from app.modules.vessel.shared.base import _row_dict

ACTIVE_TASK_STATUSES = {"OPEN", "ASSIGNED", "IN_PROGRESS", "REOPENED"}
EVIDENCE_APPROVAL_SOURCE_TYPES = {"VESSEL_CONTROLLER_EVIDENCE", "VESSEL_AFFILIATION_EVIDENCE"}


def _utcnow() -> datetime:
    return datetime.utcnow()


class VesselGovernanceResponseMixin:
    def _task_response(
        self,
        row: VesselGovernanceTask,
        label_map: dict[str, dict[str, str]],
        profile: VesselProfile | None = None,
        approval_info: dict[str, Any] | None = None,
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
            action_path=self._task_action_path(row, approval_info),
            field_anchor=self._task_field_anchor(row),
            recommended_actions=self._task_actions(row, approval_info),
            next_actions=self._task_actions(row, approval_info),
            explain_reason=self._task_explain_reason(row),
            evidence_gaps=self._task_evidence_gaps(row),
            source_object_anchor=self._task_source_anchor(row),
            workbench_group=self._task_workbench_group(row),
            verification_status_code=self._task_verification_status(row),
            verification_message=self._task_verification_message(row),
            approval_instance_id=(approval_info or {}).get("approval_instance_id"),
            approval_instance_no=(approval_info or {}).get("approval_instance_no"),
            approval_status_code=(approval_info or {}).get("approval_status_code"),
            approval_status_name=(approval_info or {}).get("approval_status_name"),
            approval_action_path=(approval_info or {}).get("approval_action_path"),
            business_sync_status_code=(approval_info or {}).get("business_sync_status_code"),
            business_sync_message=(approval_info or {}).get("business_sync_message"),
            sla_due_at=self._task_sla_due_at(row),
            overdue_level=self._task_overdue_level(row),
            assignee_load=None,
            today_priority_score=self._task_priority_score(row),
            validation_entrypoint=self._task_validation_entrypoint(row),
        )

    def _task_actions(self, row: VesselGovernanceTask, approval_info: dict[str, Any] | None = None) -> list[VesselRecommendedAction]:
        target_path = self._task_action_path(row, approval_info)
        if not target_path:
            return []
        return [
            VesselRecommendedAction(
                action_type="APPROVAL_REVIEW" if row.source_object_type in EVIDENCE_APPROVAL_SOURCE_TYPES | {"VESSEL_BLACKLIST_SIGNAL"} or (row.source_object_type == "VESSEL_RISK_SIGNAL" and approval_info and approval_info.get("approval_action_path")) else "FIX_SOURCE",
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
            "VESSEL_CONTROLLER_EVIDENCE": "ApprovalService.approve/reject",
            "VESSEL_AFFILIATION_EVIDENCE": "ApprovalService.approve/reject",
            "VESSEL_BLACKLIST_SIGNAL": "ApprovalService.approve/reject",
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

    def _task_action_path(self, row: VesselGovernanceTask, approval_info: dict[str, Any] | None = None) -> str | None:
        vessel_id = row.vessel_profile_id
        source_id = row.source_object_id
        field = self._task_field_anchor(row)
        if row.source_object_type == "VESSEL_DATA_QUALITY_ISSUE":
            suffix = f"?quality_issue_id={source_id}"
            if field:
                suffix = f"{suffix}&field={field}"
            return f"/vessels/{vessel_id}/edit{suffix}" if vessel_id else f"/vessels/quality?quality_issue_id={source_id}"
        if row.source_object_type == "VESSEL_RISK_SIGNAL":
            if approval_info and approval_info.get("approval_action_path"):
                return str(approval_info["approval_action_path"])
            return f"/vessels/{vessel_id}/compliance?risk_signal_id={source_id}" if vessel_id else f"/vessels/compliance-risks?risk_signal_id={source_id}"
        if row.source_object_type == "VESSEL_CONTROLLER_EVIDENCE":
            if approval_info and approval_info.get("approval_action_path"):
                return str(approval_info["approval_action_path"])
            return f"/vessels/{vessel_id}/relations?tab=controller&evidence_id={source_id}" if vessel_id else None
        if row.source_object_type == "VESSEL_AFFILIATION_EVIDENCE":
            if approval_info and approval_info.get("approval_action_path"):
                return str(approval_info["approval_action_path"])
            return f"/vessels/{vessel_id}/relations?tab=affiliation&evidence_id={source_id}" if vessel_id else None
        if row.source_object_type == "VESSEL_BLACKLIST_SIGNAL":
            if approval_info and approval_info.get("approval_action_path"):
                return str(approval_info["approval_action_path"])
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
    def _risk_review_response(row: VesselRiskReview, approval: Any | None = None) -> VesselRiskReviewResponse:
        approval_id = getattr(approval, "id", None) if approval is not None else None
        return VesselRiskReviewResponse(
            **_row_dict(row),
            approval_instance_id=int(approval_id) if approval_id else None,
            approval_instance_no=getattr(approval, "instance_no", None) if approval else None,
            approval_status_code=getattr(approval, "status_code", None) if approval else None,
            approval_action_path=f"/approvals/instances/{approval_id}" if approval_id else None,
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
