from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.models.vessel import (
    VesselAffiliationEvidence,
    VesselBlacklistSignal,
    VesselControllerEvidence,
    VesselDataQualityIssue,
    VesselGovernanceTask,
    VesselProfileSummary,
    VesselRecognitionFieldDiff,
    VesselRiskSignal,
)
from app.modules.vessel.schemas import (
    VesselGovernanceDashboardResponse,
    VesselGovernanceDashboardMetric,
    VesselRecommendedAction,
    VesselWorkbenchItemResponse,
)
from app.modules.vessel.shared.base import COMPLIANCE_ACTIVE_STATUSES


ACTIVE_TASK_STATUSES = {"OPEN", "ASSIGNED", "IN_PROGRESS", "REOPENED"}


def _utcnow() -> datetime:
    return datetime.utcnow()


class VesselGovernanceDashboardMixin:
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
            self._metric(
                "avg_close_hours",
                "平均关闭时长",
                Decimal(str(round(sum(close_hours) / len(close_hours), 2))) if close_hours else None,
                "小时",
                len(close_hours),
                latest,
            ),
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
