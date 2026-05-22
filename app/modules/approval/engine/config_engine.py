"""Configuration-table approval engine."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.approval import ApprovalFlowDefinition, ApprovalStepDefinition


@dataclass(frozen=True)
class RuntimeStep:
    step_key: str
    step_order: int
    step_name: str
    candidate_user_id: int | None = None
    candidate_role_code: str | None = None
    candidate_permission_code: str | None = None
    sla_hours: int | None = None


class ConfigApprovalEngine:
    def build_runtime_steps(
        self,
        flow: ApprovalFlowDefinition,
        definitions: list[ApprovalStepDefinition],
        submitter_id: int | None = None,
    ) -> list[RuntimeStep]:
        _ = flow, submitter_id
        return [
            RuntimeStep(
                step_key=row.step_key,
                step_order=row.step_order,
                step_name=row.step_name,
                candidate_user_id=row.assignee_user_id,
                candidate_role_code=row.assignee_role_code,
                candidate_permission_code=row.assignee_permission_code,
                sla_hours=row.sla_hours,
            )
            for row in sorted(definitions, key=lambda item: item.step_order)
            if row.step_type == "HUMAN"
        ]
