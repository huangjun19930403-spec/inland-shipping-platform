"""Seed approval subject and flow definitions."""

from __future__ import annotations

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.approval import ApprovalFlowDefinition, ApprovalStepDefinition, ApprovalSubjectDefinition


SUBJECTS = (
    {
        "subject_type": "VESSEL_CONTROLLER_EVIDENCE",
        "subject_name": "船舶实际控制人证据",
        "module_code": "VESSEL",
        "detail_path_template": "/vessels/{vessel_profile_id}/relations?tab=controller&evidence_id={subject_id}",
        "read_permission_code": "VESSEL:READ",
        "submit_permission_code": "VESSEL:WRITE",
        "summary_schema_json": {"fields": ["vessel_profile_id", "party_name", "verified_status_code"]},
    },
    {
        "subject_type": "VESSEL_AFFILIATION_EVIDENCE",
        "subject_name": "船舶挂靠/授权证据",
        "module_code": "VESSEL",
        "detail_path_template": "/vessels/{vessel_profile_id}/relations?tab=affiliation&evidence_id={subject_id}",
        "read_permission_code": "VESSEL:READ",
        "submit_permission_code": "VESSEL:WRITE",
        "summary_schema_json": {"fields": ["vessel_profile_id", "subject_name", "verified_status_code"]},
    },
    {
        "subject_type": "VESSEL_RISK_REVIEW",
        "subject_name": "船舶风险复核",
        "module_code": "VESSEL",
        "detail_path_template": "/vessels/{vessel_profile_id}/compliance?risk_review_id={subject_id}",
        "read_permission_code": "VESSEL:READ",
        "submit_permission_code": "VESSEL:WRITE",
        "summary_schema_json": {"fields": ["vessel_profile_id", "risk_signal_id", "review_action_code"]},
    },
    {
        "subject_type": "VESSEL_BLACKLIST_SIGNAL",
        "subject_name": "船舶名单信号解除/作废",
        "module_code": "VESSEL",
        "detail_path_template": "/vessels/blacklist-signals?blacklist_signal_id={subject_id}",
        "read_permission_code": "VESSEL:READ",
        "submit_permission_code": "VESSEL:WRITE",
        "summary_schema_json": {"fields": ["vessel_profile_id", "blacklist_signal_id", "review_action_code"]},
    },
)

FLOWS = (
    ("VESSEL_CONTROLLER_EVIDENCE_VERIFY", "控制人证据单步审批", "VESSEL_CONTROLLER_EVIDENCE", "VERIFY"),
    ("VESSEL_AFFILIATION_EVIDENCE_VERIFY", "挂靠/授权证据单步审批", "VESSEL_AFFILIATION_EVIDENCE", "VERIFY"),
    ("VESSEL_RISK_REVIEW_UPDATE", "风险复核单步审批", "VESSEL_RISK_REVIEW", "UPDATE"),
    ("VESSEL_BLACKLIST_SIGNAL_UPDATE", "名单信号单步审批", "VESSEL_BLACKLIST_SIGNAL", "UPDATE"),
)


async def seed_approval_base() -> None:
    async with AsyncSessionLocal() as session:
        for payload in SUBJECTS:
            row = await session.scalar(
                select(ApprovalSubjectDefinition).where(
                    ApprovalSubjectDefinition.subject_type == payload["subject_type"]
                )
            )
            data = {"status_code": "ACTIVE", **payload}
            if row is None:
                session.add(ApprovalSubjectDefinition(**data))
            else:
                for key, value in data.items():
                    setattr(row, key, value)
        await session.flush()

        for flow_code, flow_name, subject_type, trigger_action_code in FLOWS:
            flow = await session.scalar(
                select(ApprovalFlowDefinition).where(ApprovalFlowDefinition.flow_code == flow_code)
            )
            data = {
                "flow_code": flow_code,
                "flow_name": flow_name,
                "subject_type": subject_type,
                "trigger_action_code": trigger_action_code,
                "engine_type": "CONFIG",
                "approval_mode": "SINGLE",
                "status_code": "ACTIVE",
                "spiff_spec_id": None,
                "config_json": {"template": "single_step"},
            }
            if flow is None:
                flow = ApprovalFlowDefinition(**data)
                session.add(flow)
                await session.flush()
            else:
                for key, value in data.items():
                    setattr(flow, key, value)
                await session.flush()

            await session.execute(
                delete(ApprovalStepDefinition).where(ApprovalStepDefinition.flow_id == flow.id)
            )
            session.add(
                ApprovalStepDefinition(
                    flow_id=flow.id,
                    step_key="approval",
                    step_order=1,
                    step_name="审批",
                    step_type="HUMAN",
                    assignment_type="PERMISSION",
                    assignee_permission_code="APPROVAL:WRITE",
                    action_policy="ANY_ONE",
                    condition_json=None,
                    sla_hours=24,
                )
            )
        await session.commit()
