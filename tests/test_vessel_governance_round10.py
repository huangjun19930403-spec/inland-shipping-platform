from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import BigInteger

import app.models  # noqa: F401
from main import app
from app.models.base import Base
from app.models.audit import AuditTask
from app.models.vessel import (
    VesselBlacklistSignal,
    VesselControllerConclusion,
    VesselControllerEvidence,
    VesselDataQualityIssue,
    VesselGovernanceSyncBatch,
    VesselGovernanceTask,
    VesselProfile,
    VesselRiskReview,
    VesselRiskSignal,
)
from app.core.exceptions import ValidationError
from app.modules.audit.service import AuditTaskService
from app.modules.vessel.governance_service import VesselGovernanceService
from app.modules.vessel.schemas import (
    VesselAffiliationEvidenceCreateRequest,
    VesselBlacklistSignalCreateRequest,
    VesselBlacklistSignalGlobalQuery,
    VesselControllerEvidenceCreateRequest,
    VesselControllerEvidenceUpdateRequest,
    VesselGovernanceTaskActionRequest,
    VesselGovernanceTaskQuery,
    VesselVoidRequest,
    VesselRiskReviewRequest,
)
from app.modules.vessel.shared.aggregate import VesselDomainService as VesselService
from scripts.seeds.loaders.builtin_dicts import BUILTIN_DICTS


@compiles(BigInteger, "sqlite")
def _compile_bigint_sqlite(element, compiler, **kw) -> str:
    _ = element, compiler, kw
    return "INTEGER"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


async def _seed_profile(session: AsyncSession, vessel_id: int = 1) -> VesselProfile:
    profile = VesselProfile(
        id=vessel_id,
        vessel_profile_code=f"VSL{vessel_id:04d}",
        ship_name=f"治理测试船{vessel_id}",
        current_mmsi=f"41300000{vessel_id}",
        ship_type_code="DRY_BULK",
        profile_status_code="ACTIVE",
        identity_status_code="LINKED",
        source_type_code="MANUAL",
    )
    session.add(profile)
    await session.flush()
    return profile


def test_round10_openapi_models_and_dicts_exist() -> None:
    paths = app.openapi()["paths"]
    assert "get" in paths["/api/v1/vessels/governance/dashboard"]
    assert "get" in paths["/api/v1/vessels/governance/tasks"]
    assert "post" in paths["/api/v1/vessels/governance/tasks/sync"]
    assert "patch" in paths["/api/v1/vessels/governance/tasks/{task_id}"]
    assert "post" in paths["/api/v1/vessels/quality/{issue_id}/recheck"]
    assert "get" in paths["/api/v1/vessels/blacklist-signals"]
    assert "post" in paths["/api/v1/vessels/{vessel_id}/risk-reviews"]
    assert "get" in paths["/api/v1/vessels/{vessel_id}/blacklist-signals"]
    assert "get" in paths["/api/v1/vessels/{vessel_id}/relation-conclusions"]
    assert "post" in paths["/api/v1/vessels/{vessel_id}/controller-conclusions/{conclusion_id}/confirm"]
    dashboard_schema_ref = paths["/api/v1/vessels/governance/dashboard"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    dashboard_schema = app.openapi()["components"]["schemas"][dashboard_schema_ref.rsplit("/", 1)[-1]]
    assert "work_items" in dashboard_schema["properties"]
    task_schema = app.openapi()["components"]["schemas"]["VesselGovernanceTaskResponse"]
    assert {
        "explain_reason",
        "next_actions",
        "evidence_gaps",
        "source_object_anchor",
        "workbench_group",
    }.issubset(task_schema["properties"])
    controller_schema = app.openapi()["components"]["schemas"]["VesselControllerEvidenceResponse"]
    affiliation_schema = app.openapi()["components"]["schemas"]["VesselAffiliationEvidenceResponse"]
    for schema in (controller_schema, affiliation_schema):
        assert {
            "conclusion_refs",
            "evidence_completeness",
            "missing_required_fields",
        }.issubset(schema["properties"])
    assert VesselGovernanceTask.__tablename__ == "vessel_governance_task"
    assert VesselGovernanceSyncBatch.__tablename__ == "vessel_governance_sync_batch"
    assert VesselControllerConclusion.__tablename__ == "vessel_controller_conclusion"
    assert VesselRiskReview.__tablename__ == "vessel_risk_review"
    assert VesselBlacklistSignal.__tablename__ == "vessel_blacklist_signal"
    dict_codes = {item["dict_code"] for item in BUILTIN_DICTS}
    assert {
        "VESSEL_GOVERNANCE_TASK_TYPE",
        "VESSEL_GOVERNANCE_TASK_STATUS",
        "VESSEL_GOVERNANCE_PRIORITY",
        "VESSEL_EVIDENCE_VERIFIED_STATUS",
        "VESSEL_BLACKLIST_LIST_TYPE",
        "VESSEL_BLACKLIST_SIGNAL_TYPE",
        "VESSEL_BLACKLIST_SIGNAL_STATUS",
        "VESSEL_RELATION_CONCLUSION_STATUS",
        "VESSEL_GOVERNANCE_SYNC_STATUS",
    }.issubset(dict_codes)
    dict_items = {
        item["dict_code"]: {option["item_code"]: option["item_name"] for option in item["items"]}
        for item in BUILTIN_DICTS
    }
    assert dict_items["VESSEL_DATA_SOURCE_TYPE"]["GOVERNANCE_TASK"] == "治理任务"
    assert dict_items["VESSEL_DATA_SOURCE_TYPE"]["VESSEL_SUMMARY"] == "船舶摘要"
    assert dict_items["VESSEL_DATA_SOURCE_TYPE"]["VESSEL_SPATIAL_OBSERVATION"] == "空间观测"
    assert dict_items["VESSEL_DATA_SOURCE_TYPE"]["VESSEL_NODE_OBSERVATION"] == "节点观测"
    assert dict_items["VESSEL_DATA_SOURCE_TYPE"]["VESSEL_ROUTE_SEGMENT_OBSERVATION"] == "航线段观测"
    assert dict_items["ANALYSIS_NOT_COMPUTABLE_REASON"]["NO_GOVERNANCE_SAMPLE"] == "暂无治理样本"


@pytest.mark.asyncio
async def test_structured_relation_evidence_completeness_and_conclusion_refs(session: AsyncSession) -> None:
    await _seed_profile(session)
    service = VesselService(session)
    today = datetime.utcnow().date()

    partial = await service.create_controller_evidence(
        1,
        VesselControllerEvidenceCreateRequest(
            party_name="结构化控制人",
            controller_role_code="EVIDENCE_PROVIDER",
            confidence_level="HIGH",
            evidence_summary="合同、付款流水和联系人指向同一实际控制人",
            evidence_json={"confirmation": {"source": "合同材料"}},
        ),
        operator_id=1,
    )
    assert partial.evidence_completeness == "MISSING_REQUIRED"
    assert "必填：确认方式" in partial.missing_required_fields

    complete = await service.update_controller_evidence(
        1,
        partial.id,
        VesselControllerEvidenceUpdateRequest(
            revision=partial.revision,
            verified_status_code="APPROVED",
            effective_from=today,
            evidence_json={
                "controller_identity": {"certificate_type": "ID_CARD", "certificate_no": "320000199001010000"},
                "contact": {"phone": "13800000000"},
                "relationship": {"owner_relationship": "实际出资人", "operator_relationship": "经营决策人"},
                "confirmation": {"source": "合同材料", "method": "人工核验", "confirmed_at": "2026-05-10T10:00:00", "confirmed_by": "合规专员"},
                "attachment_refs": ["file-1"],
                "audit_opinion": "材料齐全",
            },
        ),
        operator_id=1,
    )
    assert complete.evidence_completeness == "COMPLETE"

    await service.rebuild_relation_conclusion_candidates(1, operator_id=1)
    listed = await service.list_controller_evidence(1)
    matched = next(item for item in listed if item.id == complete.id)
    assert matched.conclusion_refs
    assert matched.conclusion_refs[0].conclusion_type == "CONTROLLER"

    affiliation = await service.create_affiliation_evidence(
        1,
        VesselAffiliationEvidenceCreateRequest(
            affiliation_type_code="AFFILIATION",
            subject_name="结构化挂靠主体",
            counterparty_name="授权经营公司",
            confidence_level="HIGH",
            evidence_summary="协议、营运证和管理费流水一致",
            effective_from=today,
            verified_status_code="APPROVED",
            evidence_json={
                "affiliation_contract": {
                    "affiliation_company": "授权经营公司",
                    "actual_shipowner": "结构化挂靠主体",
                    "agreement_start": "2026-01-01",
                    "agreement_end": "2026-12-31",
                },
                "operation_qualification": {
                    "certificate_operator": "授权经营公司",
                    "transport_permit_relation": "营运证经营主体一致",
                },
                "contact": {"business_contact": "李四"},
                "confirmation": {"source": "挂靠协议", "method": "人工核验", "confirmed_at": "2026-05-10T10:00:00"},
                "attachment_refs": ["file-2"],
                "risk_level": "MEDIUM",
            },
        ),
        operator_id=1,
    )
    assert affiliation.evidence_completeness == "COMPLETE"
    await service.rebuild_relation_conclusion_candidates(1, operator_id=1)
    listed_affiliations = await service.list_affiliation_evidence(1)
    matched_affiliation = next(item for item in listed_affiliations if item.id == affiliation.id)
    assert matched_affiliation.conclusion_refs
    assert matched_affiliation.conclusion_refs[0].conclusion_type == "AFFILIATION"


@pytest.mark.asyncio
async def test_quality_issue_governance_task_resolve_and_reopen(session: AsyncSession) -> None:
    await _seed_profile(session)
    issue = VesselDataQualityIssue(
        issue_type_code="AIS_UNMATCHED",
        severity_code="HIGH",
        affected_object_type="mmsi",
        affected_object_id="413999999",
        vessel_profile_id=1,
        field_name="current_mmsi",
        fingerprint="fp-ais-unmatched",
        evidence_source="AIS_SNAPSHOT",
        impact_scope_json=[],
        status_code="OPEN",
    )
    session.add(issue)
    await session.commit()

    service = VesselGovernanceService(session)
    dashboard = await service.dashboard()
    assert dashboard.metrics
    assert dashboard.work_items
    assert next(item for item in dashboard.work_items if item.code == "unmatched_mmsi").count == 1
    assert await session.scalar(select(VesselGovernanceTask)) is None
    page = await service.list_tasks(VesselGovernanceTaskQuery(status_code="OPEN", page=1, page_size=20))
    assert page.total == 0

    sync_result = await service.sync_tasks_command()
    assert sync_result.touched_count == 1
    assert sync_result.batch_id is not None
    assert sync_result.created_task_count == 1
    batch = await session.get(VesselGovernanceSyncBatch, sync_result.batch_id)
    assert batch is not None
    assert batch.status_code == "SUCCESS"
    page = await service.list_tasks(VesselGovernanceTaskQuery(status_code="OPEN", page=1, page_size=20))
    assert page.total == 1
    task = page.items[0]
    assert task.task_type_code == "AIS_UNMATCHED"
    assert task.source_batch_id == sync_result.batch_id
    assert task.generation_reason_json
    assert task.action_path is not None
    assert task.recommended_actions
    assert task.explain_reason
    assert task.source_object_anchor == f"VESSEL_DATA_QUALITY_ISSUE:{issue.id}"
    assert task.workbench_group == "QUALITY"
    assert "重新校验通过记录" in task.evidence_gaps

    with pytest.raises(ValidationError):
        await service.update_task(
            task.id,
            VesselGovernanceTaskActionRequest(action_code="RESOLVE", revision=task.revision, reason="已补齐 MMSI 证据"),
            operator_id=9,
        )

    issue.status_code = "RESOLVED"
    issue.resolved_at = datetime.utcnow()
    await session.commit()
    refreshed_task = await session.get(VesselGovernanceTask, task.id)
    assert refreshed_task is not None
    await service.update_task(
        task.id,
        VesselGovernanceTaskActionRequest(action_code="RESOLVE", revision=refreshed_task.revision, reason="重新校验已通过"),
        operator_id=9,
    )
    refreshed_issue = await session.get(VesselDataQualityIssue, issue.id)
    assert refreshed_issue is not None
    assert refreshed_issue.status_code == "RESOLVED"
    assert refreshed_issue.resolved_by == 9

    reopened_issue = VesselDataQualityIssue(
        issue_type_code="AIS_UNMATCHED",
        severity_code="HIGH",
        affected_object_type="mmsi",
        affected_object_id="413999999",
        vessel_profile_id=1,
        field_name="current_mmsi",
        fingerprint="fp-ais-unmatched",
        evidence_source="AIS_SNAPSHOT",
        impact_scope_json=[],
        status_code="OPEN",
    )
    session.add(reopened_issue)
    await session.commit()
    await service.sync_tasks_command()
    reopened_task = await session.scalar(select(VesselGovernanceTask).where(VesselGovernanceTask.fingerprint == "AIS_UNMATCHED|QUALITY|fp-ais-unmatched"))
    assert reopened_task is not None
    assert reopened_task.status_code == "REOPENED"
    assert reopened_task.reopen_count >= 1


@pytest.mark.asyncio
async def test_cannot_resolve_does_not_close_quality_issue(session: AsyncSession) -> None:
    await _seed_profile(session)
    issue = VesselDataQualityIssue(
        issue_type_code="PROFILE_FIELD_MISSING",
        severity_code="MEDIUM",
        affected_object_type="profile",
        affected_object_id="1",
        vessel_profile_id=1,
        field_name="deadweight_ton",
        fingerprint="fp-field-missing",
        status_code="OPEN",
    )
    session.add(issue)
    await session.commit()

    service = VesselGovernanceService(session)
    await service.sync_tasks_command()
    page = await service.list_tasks(VesselGovernanceTaskQuery(status_code="OPEN", page=1, page_size=20))
    task = next(item for item in page.items if item.source_object_id == str(issue.id))
    await service.update_task(
        task.id,
        VesselGovernanceTaskActionRequest(action_code="CANNOT_RESOLVE", revision=task.revision, reason="外部来源暂不可用"),
        operator_id=7,
    )
    refreshed_issue = await session.get(VesselDataQualityIssue, issue.id)
    assert refreshed_issue is not None
    assert refreshed_issue.status_code == "OPEN"
    assert refreshed_issue.resolved_at is None


@pytest.mark.asyncio
async def test_risk_review_records_history_without_auto_lowering_unknown(session: AsyncSession) -> None:
    await _seed_profile(session)
    now = datetime.utcnow()
    signal = VesselRiskSignal(
        vessel_profile_id=1,
        risk_type_code="CONTROLLER_UNKNOWN",
        risk_level="UNKNOWN",
        rule_code=None,
        status_code="OPEN",
        confidence_level="LOW",
        fingerprint="risk-controller-unknown",
        evidence_json={},
        source_trace_json=[],
        uncertainty_notes_json=["实际控制人证据不足"],
        first_detected_at=now,
        last_detected_at=now,
    )
    session.add(signal)
    await session.commit()

    response = await VesselGovernanceService(session).create_risk_review(
        1,
        VesselRiskReviewRequest(
            risk_signal_id=signal.id,
            review_action_code="ADD_EVIDENCE",
            evidence_json={"source": "manual"},
            review_reason="补充材料，继续观察",
        ),
        operator_id=3,
    )
    refreshed = await session.get(VesselRiskSignal, signal.id)
    assert response.id is not None
    assert refreshed is not None
    assert refreshed.status_code == "EVIDENCE_ADDED"
    assert refreshed.risk_level == "UNKNOWN"


@pytest.mark.asyncio
async def test_controller_evidence_requires_approval_before_risk_is_cleared(session: AsyncSession) -> None:
    await _seed_profile(session)
    draft = VesselControllerEvidence(
        vessel_profile_id=1,
        party_name="测试控制人",
        controller_role_code="EVIDENCE_PROVIDER",
        confidence_level="HIGH",
        source_type_code="MANUAL",
        status_code="ACTIVE",
        verified_status_code="DRAFT",
    )
    session.add(draft)
    await session.commit()

    risk = await VesselService(session).refresh_compliance_risk(1, operator_id=1)
    assert any(item.risk_type_code == "CONTROLLER_UNKNOWN" for item in risk.signals)

    draft.verified_status_code = "APPROVED"
    draft.verified_at = datetime.utcnow()
    draft.verified_by = 1
    draft.updated_at = datetime.utcnow()
    await session.commit()
    risk = await VesselService(session).refresh_compliance_risk(1, operator_id=1)
    assert any(item.risk_type_code == "CONTROLLER_UNKNOWN" for item in risk.signals)

    conclusions = await VesselService(session).rebuild_relation_conclusion_candidates(1, operator_id=1)
    assert conclusions.controller_conclusions
    await VesselService(session).confirm_controller_conclusion(1, conclusions.controller_conclusions[0].id, operator_id=1)
    risk = await VesselService(session).refresh_compliance_risk(1, operator_id=1)
    assert not any(item.risk_type_code == "CONTROLLER_UNKNOWN" and item.status_code in {"OPEN", "IN_REVIEW", "EVIDENCE_ADDED"} for item in risk.signals)


@pytest.mark.asyncio
async def test_controller_evidence_submit_review_resolve_and_void_reopens_risk(session: AsyncSession) -> None:
    await _seed_profile(session)
    vessel_service = VesselService(session)
    governance_service = VesselGovernanceService(session)

    risk = await vessel_service.refresh_compliance_risk(1, operator_id=1)
    assert any(item.risk_type_code == "CONTROLLER_UNKNOWN" for item in risk.signals)

    evidence = await vessel_service.create_controller_evidence(
        1,
        VesselControllerEvidenceCreateRequest(
            party_name="待审控制人",
            controller_role_code="EVIDENCE_PROVIDER",
            confidence_level="HIGH",
            evidence_summary="合同与付款流水指向同一控制主体",
            verified_status_code="DRAFT",
        ),
        operator_id=8,
    )
    risk = await vessel_service.refresh_compliance_risk(1, operator_id=1)
    assert any(item.risk_type_code == "CONTROLLER_UNKNOWN" and item.status_code in {"OPEN", "IN_REVIEW", "EVIDENCE_ADDED"} for item in risk.signals)

    pending = await vessel_service.update_controller_evidence(
        1,
        evidence.id,
        VesselControllerEvidenceUpdateRequest(
            revision=evidence.revision,
            verified_status_code="PENDING",
            evidence_json={"submitted_from": "test"},
        ),
        operator_id=8,
    )
    assert pending.verified_status_code == "PENDING"
    assert pending.audit_task_id is not None

    await governance_service.sync_tasks_command()
    task_page = await governance_service.list_tasks(
        VesselGovernanceTaskQuery(source_object_type="VESSEL_CONTROLLER_EVIDENCE", status_code="OPEN", page=1, page_size=20)
    )
    task = next(item for item in task_page.items if item.source_object_id == str(evidence.id))
    assert task.audit_task_id == pending.audit_task_id
    assert task.audit_action_path == f"/audit/tasks/{pending.audit_task_id}"
    with pytest.raises(ValidationError):
        await governance_service.update_task(
            task.id,
            VesselGovernanceTaskActionRequest(action_code="RESOLVE", revision=task.revision, reason="控制人证据审核通过"),
            operator_id=9,
        )

    await AuditTaskService(session).approve_task(
        int(pending.audit_task_id),
        "控制人证据审核通过",
        operator_user_id=9,
    )
    approved = await session.get(VesselControllerEvidence, evidence.id)
    assert approved is not None
    assert approved.verified_status_code == "APPROVED"
    mirrored = await session.get(VesselGovernanceTask, task.id)
    assert mirrored is not None
    assert mirrored.status_code == "RESOLVED"
    conclusions = await vessel_service.list_relation_conclusions(1)
    assert conclusions.controller_conclusions
    assert conclusions.controller_conclusions[0].conclusion_status_code == "CANDIDATE"
    await vessel_service.confirm_controller_conclusion(1, conclusions.controller_conclusions[0].id, operator_id=9)
    risk = await vessel_service.refresh_compliance_risk(1, operator_id=9)
    assert not any(item.risk_type_code == "CONTROLLER_UNKNOWN" and item.status_code in {"OPEN", "IN_REVIEW", "EVIDENCE_ADDED"} for item in risk.signals)

    voided = await vessel_service.void_controller_evidence(
        1,
        evidence.id,
        VesselVoidRequest(revision=approved.revision, reason="证据撤回"),
        operator_id=9,
    )
    assert voided.status_code == "VOIDED"
    stale = await session.scalar(select(VesselControllerConclusion).where(VesselControllerConclusion.vessel_profile_id == 1))
    assert stale is not None
    assert stale.conclusion_status_code in {"STALE_NEEDS_REVIEW", "VOIDED", "EXPIRED"}
    risk = await vessel_service.refresh_compliance_risk(1, operator_id=9)
    assert any(item.risk_type_code == "CONTROLLER_UNKNOWN" and item.status_code in {"OPEN", "IN_REVIEW", "EVIDENCE_ADDED"} for item in risk.signals)


@pytest.mark.asyncio
async def test_blacklist_signal_enters_governance_and_risk_but_expired_does_not(session: AsyncSession) -> None:
    await _seed_profile(session)
    service = VesselGovernanceService(session)
    active = await service.create_blacklist_signal(
        1,
        VesselBlacklistSignalCreateRequest(
            list_type_code="WATCHLIST",
            signal_type_code="MANUAL_RISK",
            risk_level="HIGH",
            confidence_level="HIGH",
            evidence_summary="人工观察名单证据",
        ),
        operator_id=2,
    )
    assert active.status_code == "ACTIVE"
    task_page = await service.list_tasks(VesselGovernanceTaskQuery(task_type_code="BLACKLIST_REVIEW", page=1, page_size=20))
    assert task_page.total == 1
    risk_signal = await session.scalar(select(VesselRiskSignal).where(VesselRiskSignal.risk_type_code == "BLACKLIST_SIGNAL"))
    assert risk_signal is not None
    assert risk_signal.risk_level == "HIGH"
    assert risk_signal.status_code == "OPEN"
    queue = await service.list_blacklist_signal_queue(VesselBlacklistSignalGlobalQuery(vessel_id=1, status_code="ACTIVE", page=1, page_size=20))
    assert queue.total == 1
    assert queue.items[0].governance_task_id is not None
    assert queue.items[0].risk_signal_id == risk_signal.id

    voided = await service.void_blacklist_signal(1, active.id, VesselVoidRequest(revision=active.revision, reason="名单证据撤销"), operator_id=2)
    assert voided.status_code == "IN_REVIEW"
    audit = await session.scalar(
        select(AuditTask).where(AuditTask.object_type_code == "VESSEL_BLACKLIST_SIGNAL", AuditTask.biz_id == active.id)
    )
    assert audit is not None
    task_page = await service.list_tasks(VesselGovernanceTaskQuery(task_type_code="BLACKLIST_REVIEW", page=1, page_size=20))
    blacklist_task = task_page.items[0]
    assert blacklist_task.audit_task_id == audit.id
    assert blacklist_task.audit_action_path == f"/audit/tasks/{audit.id}"
    with pytest.raises(ValidationError):
        await service.update_task(
            blacklist_task.id,
            VesselGovernanceTaskActionRequest(action_code="RESOLVE", revision=blacklist_task.revision, reason="名单复核通过"),
            operator_id=2,
        )
    await AuditTaskService(session).approve_task(audit.id, "名单证据撤销", operator_user_id=2)
    await session.refresh(risk_signal)
    approved_signal = await session.get(VesselBlacklistSignal, active.id)
    assert approved_signal is not None
    assert approved_signal.status_code == "VOIDED"
    await session.refresh(risk_signal)
    assert risk_signal.status_code == "CLOSED"
    assert risk_signal.resolution_reason == "名单证据撤销"

    expired = await service.create_blacklist_signal(
        1,
        VesselBlacklistSignalCreateRequest(
            list_type_code="BLACKLIST",
            signal_type_code="SANCTION",
            risk_level="HIGH",
            confidence_level="HIGH",
            effective_to=(datetime.utcnow() - timedelta(days=1)).date(),
        ),
        operator_id=2,
    )
    assert expired.status_code == "EXPIRED"
    active_blacklist_risk_count = await session.scalar(
        select(VesselRiskSignal).where(
            VesselRiskSignal.risk_type_code == "BLACKLIST_SIGNAL",
            VesselRiskSignal.status_code.in_(("OPEN", "IN_REVIEW", "EVIDENCE_ADDED")),
        )
    )
    assert active_blacklist_risk_count is None
