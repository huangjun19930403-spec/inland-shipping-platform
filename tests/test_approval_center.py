from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import BigInteger

import app.models  # noqa: F401
from app.core.exceptions import PermissionError, ValidationError
from app.models.approval import ApprovalOutbox
from app.models.base import Base
from app.modules.approval.outbox import ApprovalServiceRegistry, dispatch_pending_outbox
from app.modules.approval.schemas import (
    ApprovalActionRequest,
    ApprovalFlowDefinitionCreateRequest,
    ApprovalInstanceSubmitRequest,
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


async def _seed_flow(
    session: AsyncSession,
    *,
    subject_type: str = "TEST_SUBJECT",
    trigger_action_code: str = "CREATE",
    step_count: int = 1,
) -> None:
    service = ApprovalService(session)
    await service.create_subject_definition(
        ApprovalSubjectDefinitionCreateRequest(
            subject_type=subject_type,
            subject_name=subject_type,
            module_code="TEST",
            detail_path_template="/test/{subject_id}",
            read_permission_code="APPROVAL:READ",
            submit_permission_code="APPROVAL:SUBMIT",
        )
    )
    await service.create_flow_definition(
        ApprovalFlowDefinitionCreateRequest(
            flow_code=f"{subject_type}_{trigger_action_code}",
            flow_name=f"{subject_type} flow",
            subject_type=subject_type,
            trigger_action_code=trigger_action_code,
            engine_type="CONFIG",
            approval_mode="MULTI_STEP" if step_count > 1 else "SINGLE",
            status_code="ACTIVE",
            steps=[
                ApprovalStepDefinitionPayload(
                    step_key=f"step_{index}",
                    step_order=index,
                    step_name=f"Step {index}",
                    step_type="HUMAN",
                    assignment_type="USER",
                    assignee_user_id=1,
                    action_policy="ANY_ONE",
                )
                for index in range(1, step_count + 1)
            ],
        )
    )


def _submit_payload(subject_type: str = "TEST_SUBJECT", key: str = "idem-1") -> ApprovalInstanceSubmitRequest:
    return ApprovalInstanceSubmitRequest(
        subject_type=subject_type,
        trigger_action_code="CREATE",
        subject_id=100,
        subject_ref=f"{subject_type}:100",
        subject_code="S-100",
        subject_name="Test subject",
        subject_path="/test/100",
        before_snapshot_json={"name": "old"},
        after_snapshot_json={"name": "new"},
        diff_json={"name": ["old", "new"]},
        summary_json={"name": "Test subject"},
        submit_payload_json={"intent": "create"},
        idempotency_key=key,
    )


@pytest.mark.asyncio
async def test_single_step_approval_approve_reject_return_cancel(session: AsyncSession) -> None:
    await _seed_flow(session)
    service = ApprovalService(session)

    approved = await service.submit_instance(_submit_payload(key="approve"), submitter_id=2)
    approved = await service.approve_instance(approved.id, ApprovalActionRequest(comment="ok"), operator_id=1)
    assert approved.status_code == "APPROVED"

    rejected = await service.submit_instance(_submit_payload(key="reject"), submitter_id=2)
    rejected = await service.reject_instance(rejected.id, ApprovalActionRequest(comment="bad"), operator_id=1)
    assert rejected.status_code == "REJECTED"

    returned = await service.submit_instance(_submit_payload(key="return"), submitter_id=2)
    returned = await service.return_instance(returned.id, ApprovalActionRequest(comment="fix"), operator_id=1)
    assert returned.status_code == "RETURNED"

    canceled = await service.submit_instance(_submit_payload(key="cancel"), submitter_id=2)
    canceled = await service.cancel_instance(canceled.id, ApprovalActionRequest(comment="stop"), operator_id=2)
    assert canceled.status_code == "CANCELED"


@pytest.mark.asyncio
async def test_multi_step_approval_advances_until_final(session: AsyncSession) -> None:
    await _seed_flow(session, subject_type="TEST_MULTI", step_count=2)
    service = ApprovalService(session)

    instance = await service.submit_instance(_submit_payload("TEST_MULTI", "multi"), submitter_id=2)
    assert instance.status_code == "RUNNING"
    assert instance.current_step_name == "Step 1"

    instance = await service.approve_instance(instance.id, ApprovalActionRequest(comment="one"), operator_id=1)
    assert instance.status_code == "RUNNING"
    assert instance.current_step_name == "Step 2"

    instance = await service.approve_instance(instance.id, ApprovalActionRequest(comment="two"), operator_id=1)
    assert instance.status_code == "APPROVED"
    assert instance.current_step_instance_id is None


@pytest.mark.asyncio
async def test_idempotent_submit_returns_existing_instance(session: AsyncSession) -> None:
    await _seed_flow(session)
    service = ApprovalService(session)

    first = await service.submit_instance(_submit_payload(key="same"), submitter_id=2)
    second = await service.submit_instance(_submit_payload(key="same"), submitter_id=2)

    assert first.id == second.id
    assert first.instance_no == second.instance_no


@pytest.mark.asyncio
async def test_action_validation_and_outbox_dispatch(session: AsyncSession) -> None:
    await _seed_flow(session, subject_type="TEST_OUTBOX")
    service = ApprovalService(session)
    instance = await service.submit_instance(_submit_payload("TEST_OUTBOX", "outbox"), submitter_id=2)

    with pytest.raises(ValidationError):
        await service.reject_instance(instance.id, ApprovalActionRequest(comment=""), operator_id=1)
    with pytest.raises(PermissionError):
        await service.cancel_instance(instance.id, ApprovalActionRequest(comment=None), operator_id=9)

    await service.approve_instance(instance.id, ApprovalActionRequest(comment="done"), operator_id=1)
    outbox = await session.scalar(select(ApprovalOutbox).where(ApprovalOutbox.instance_id == instance.id))
    assert outbox is not None
    assert outbox.status_code == "PENDING"

    delivered: list[dict] = []

    async def _handler(payload: dict, db: AsyncSession) -> None:
        _ = db
        delivered.append(payload)

    ApprovalServiceRegistry.register("TEST_OUTBOX", _handler)
    assert await dispatch_pending_outbox(session) == 1
    assert delivered[0]["decision_code"] == "APPROVED"
    await session.refresh(outbox)
    assert outbox.status_code == "DELIVERED"
