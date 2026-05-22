from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import BigInteger

import app.models  # noqa: F401
from app.models.approval import ApprovalOutbox
from app.models.base import Base
from app.modules.approval.client import ApprovalClient
from app.modules.approval.schemas import (
    ApprovalActionRequest,
    ApprovalFlowDefinitionCreateRequest,
    ApprovalStepDefinitionPayload,
    ApprovalSubjectDefinitionCreateRequest,
)
from app.modules.approval.service import ApprovalService


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


@pytest.mark.asyncio
async def test_vessel_evidence_submit_uses_approval_center_and_outbox(session: AsyncSession) -> None:
    service = ApprovalService(session)
    await service.create_subject_definition(
        ApprovalSubjectDefinitionCreateRequest(
            subject_type="VESSEL_CONTROLLER_EVIDENCE",
            subject_name="船舶实际控制人证据",
            module_code="VESSEL",
            detail_path_template="/vessels/{vessel_profile_id}/relations",
            read_permission_code="VESSEL:READ",
            submit_permission_code="VESSEL:WRITE",
        )
    )
    await service.create_flow_definition(
        ApprovalFlowDefinitionCreateRequest(
            flow_code="VESSEL_CONTROLLER_EVIDENCE_VERIFY",
            flow_name="控制人证据审批",
            subject_type="VESSEL_CONTROLLER_EVIDENCE",
            trigger_action_code="VERIFY",
            status_code="ACTIVE",
            steps=[
                ApprovalStepDefinitionPayload(
                    step_key="approval",
                    step_order=1,
                    step_name="证据审批",
                    step_type="HUMAN",
                    assignment_type="USER",
                    assignee_user_id=1,
                    action_policy="ANY_ONE",
                )
            ],
        )
    )

    client = ApprovalClient(session)
    instance = await client.submit(
        {
            "subject_type": "VESSEL_CONTROLLER_EVIDENCE",
            "trigger_action_code": "VERIFY",
            "subject_id": 101,
            "subject_ref": "VESSEL_CONTROLLER_EVIDENCE:101",
            "subject_code": "101",
            "subject_name": "控制人证据 #101",
            "subject_path": "/vessels/1/relations",
            "before_snapshot_json": None,
            "after_snapshot_json": {"party_name": "测试公司", "verified_status_code": "PENDING"},
            "diff_json": None,
            "summary_json": {"vessel_profile_id": 1, "object_type_code": "VESSEL_CONTROLLER_EVIDENCE"},
            "submit_payload_json": {"vessel_profile_id": 1, "evidence_id": 101},
            "idempotency_key": "VESSEL_EVIDENCE:VESSEL_CONTROLLER_EVIDENCE:101:1",
        },
        submitter_id=2,
    )

    assert instance.subject_type == "VESSEL_CONTROLLER_EVIDENCE"
    assert instance.status_code == "RUNNING"

    approved = await service.approve_instance(instance.id, ApprovalActionRequest(comment="证据有效"), operator_id=1)
    assert approved.status_code == "APPROVED"

    outbox = await session.scalar(select(ApprovalOutbox).where(ApprovalOutbox.instance_id == instance.id))
    assert outbox is not None
    assert outbox.subject_type == "VESSEL_CONTROLLER_EVIDENCE"
    assert outbox.payload_json["decision_code"] == "APPROVED"
