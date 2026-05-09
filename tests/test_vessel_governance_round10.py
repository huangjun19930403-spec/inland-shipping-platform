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
from app.models.vessel import (
    VesselBlacklistSignal,
    VesselControllerEvidence,
    VesselDataQualityIssue,
    VesselGovernanceTask,
    VesselProfile,
    VesselRiskReview,
    VesselRiskSignal,
)
from app.modules.vessel.governance_service import VesselGovernanceService
from app.modules.vessel.schemas import (
    VesselBlacklistSignalCreateRequest,
    VesselControllerEvidenceCreateRequest,
    VesselControllerEvidenceUpdateRequest,
    VesselGovernanceTaskActionRequest,
    VesselGovernanceTaskQuery,
    VesselVoidRequest,
    VesselRiskReviewRequest,
)
from app.modules.vessel.service import VesselService
from scripts.seed_builtin_dicts import BUILTIN_DICTS


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
    assert "patch" in paths["/api/v1/vessels/governance/tasks/{task_id}"]
    assert "post" in paths["/api/v1/vessels/{vessel_id}/risk-reviews"]
    assert "get" in paths["/api/v1/vessels/{vessel_id}/blacklist-signals"]
    assert VesselGovernanceTask.__tablename__ == "vessel_governance_task"
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
    page = await service.list_tasks(VesselGovernanceTaskQuery(status_code="OPEN", page=1, page_size=20))
    assert page.total == 1
    task = page.items[0]
    assert task.task_type_code == "AIS_UNMATCHED"

    await service.update_task(
        task.id,
        VesselGovernanceTaskActionRequest(action_code="RESOLVE", revision=task.revision, reason="已补齐 MMSI 证据"),
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
    await service.sync_tasks()
    await session.commit()
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

    task_page = await governance_service.list_tasks(
        VesselGovernanceTaskQuery(source_object_type="VESSEL_CONTROLLER_EVIDENCE", status_code="OPEN", page=1, page_size=20)
    )
    task = next(item for item in task_page.items if item.source_object_id == str(evidence.id))
    await governance_service.update_task(
        task.id,
        VesselGovernanceTaskActionRequest(action_code="RESOLVE", revision=task.revision, reason="控制人证据审核通过"),
        operator_id=9,
    )
    approved = await session.get(VesselControllerEvidence, evidence.id)
    assert approved is not None
    assert approved.verified_status_code == "APPROVED"
    risk = await vessel_service.refresh_compliance_risk(1, operator_id=9)
    assert not any(item.risk_type_code == "CONTROLLER_UNKNOWN" and item.status_code in {"OPEN", "IN_REVIEW", "EVIDENCE_ADDED"} for item in risk.signals)

    voided = await vessel_service.void_controller_evidence(
        1,
        evidence.id,
        VesselVoidRequest(revision=approved.revision, reason="证据撤回"),
        operator_id=9,
    )
    assert voided.status_code == "VOIDED"
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

    voided = await service.void_blacklist_signal(1, active.id, VesselVoidRequest(revision=active.revision, reason="名单证据撤销"), operator_id=2)
    assert voided.status_code == "VOIDED"
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
