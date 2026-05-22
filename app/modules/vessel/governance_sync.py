from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select

from app.models.vessel import (
    VesselAffiliationEvidence,
    VesselBlacklistSignal,
    VesselCandidateAnalysisAnnotation,
    VesselControllerEvidence,
    VesselDataQualityIssue,
    VesselGovernanceSyncBatch,
    VesselGovernanceTask,
    VesselRiskSignal,
)
from app.modules.vessel.schemas import VesselGovernanceTaskSyncResponse
from app.modules.vessel.shared.base import COMPLIANCE_ACTIVE_STATUSES


TERMINAL_TASK_STATUSES = {"RESOLVED", "CANNOT_RESOLVE", "VOIDED"}


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


class VesselGovernanceSyncMixin:
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

    async def sync_tasks_command(
        self,
        *,
        operator_id: int | None = None,
        trigger_type_code: str = "MANUAL",
    ) -> VesselGovernanceTaskSyncResponse:
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
            touched = await self.sync_tasks(
                batch_id=batch.id,
                rule_results=rule_results,
                affected_vessel_ids=affected_vessel_ids,
            )
            created = sum(item.get("created", 0) for item in rule_results.values())
            reopened = sum(item.get("reopened", 0) for item in rule_results.values())
            skipped = sum(item.get("skipped", 0) for item in rule_results.values())
            batch.status_code = "SUCCESS"
            batch.touched_count = touched
            batch.created_task_count = created
            batch.reopened_task_count = reopened
            batch.skipped_count = skipped
            batch.rule_result_json = rule_results
            batch.affected_scope_json = {
                "vessel_profile_ids": sorted(affected_vessel_ids),
                "vessel_count": len(affected_vessel_ids),
            }
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
            batch.affected_scope_json = {
                "vessel_profile_ids": sorted(affected_vessel_ids),
                "vessel_count": len(affected_vessel_ids),
            }
            await self.db.commit()
            raise

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
        specs = (
            (
                VesselControllerEvidence,
                "CONTROLLER",
                "VESSEL_CONTROLLER_EVIDENCE",
                "实际控制人证据审核",
                lambda row: row.party_name,
                lambda row: {"party_name": row.party_name, "role": row.controller_role_code},
            ),
            (
                VesselAffiliationEvidence,
                "AFFILIATION",
                "VESSEL_AFFILIATION_EVIDENCE",
                "挂靠关系证据审核",
                lambda row: row.subject_name or row.counterparty_name,
                lambda row: {"subject_name": row.subject_name, "counterparty_name": row.counterparty_name},
            ),
        )
        for model, fingerprint_prefix, source_type, title, description, impact_summary in specs:
            rows = (
                await self.db.scalars(
                    select(model).where(
                        model.status_code == "ACTIVE",
                        model.verified_status_code.in_(("DRAFT", "PENDING", "CHANGE_REQUESTED")),
                    )
                )
            ).all()
            for row in rows:
                await self._upsert_task(
                    fingerprint=_task_fingerprint(fingerprint_prefix, row.id),
                    task_type_code="CONTROLLER_AFFILIATION",
                    priority_code="MEDIUM",
                    vessel_profile_id=row.vessel_profile_id,
                    source_object_type=source_type,
                    source_object_id=str(row.id),
                    source_status_code=row.verified_status_code,
                    source_fingerprint=f"{fingerprint_prefix.lower()}:{row.id}",
                    title=title,
                    description=description(row),
                    evidence_summary=row.evidence_summary,
                    source_trace_json=[{"source": source_type.lower(), "id": row.id}],
                    impact_summary_json=impact_summary(row),
                    confidence_level=row.confidence_level,
                    now=now,
                )
                touched += 1
        return touched

    async def _sync_blacklist_tasks(self, now: datetime) -> int:
        rows = (
            await self.db.scalars(
                select(VesselBlacklistSignal).where(
                    VesselBlacklistSignal.status_code == "ACTIVE",
                    VesselBlacklistSignal.voided_at.is_(None),
                )
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
