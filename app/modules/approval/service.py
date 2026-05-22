"""Approval center service."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, PermissionError, ValidationError
from app.core.security import list_current_user_permission_codes, list_current_user_role_codes
from app.models.approval import (
    ApprovalActionLog,
    ApprovalFlowDefinition,
    ApprovalInstance,
    ApprovalSnapshot,
    ApprovalStepDefinition,
    ApprovalStepInstance,
    ApprovalSubjectDefinition,
)
from app.models.system import SysUser
from app.modules.approval.engine.config_engine import ConfigApprovalEngine
from app.modules.approval.engine.spiff_engine import SpiffApprovalEngine
from app.modules.approval.repository import ApprovalRepository
from app.modules.approval.schemas import (
    ApprovalActionLogResponse,
    ApprovalActionRequest,
    ApprovalAssignRequest,
    ApprovalCandidateResponse,
    ApprovalFlowDefinitionCreateRequest,
    ApprovalFlowDefinitionListQuery,
    ApprovalFlowDefinitionResponse,
    ApprovalFlowDefinitionUpdateRequest,
    ApprovalInstanceDetailResponse,
    ApprovalInstanceListQuery,
    ApprovalInstanceResponse,
    ApprovalInstanceSubmitRequest,
    ApprovalMetadataResponse,
    ApprovalPendingCountResponse,
    ApprovalSnapshotResponse,
    ApprovalStepDefinitionPayload,
    ApprovalStepDefinitionResponse,
    ApprovalStepInstanceResponse,
    ApprovalSubjectDefinitionCreateRequest,
    ApprovalSubjectDefinitionResponse,
    ApprovalSubjectDefinitionUpdateRequest,
    PageResponse,
)


FINAL_INSTANCE_STATUSES = {"APPROVED", "REJECTED", "CANCELED", "FAILED"}
INSTANCE_STATUS_META = [
    {"code": "PENDING", "name": "待启动", "color": "info"},
    {"code": "RUNNING", "name": "审批中", "color": "warning"},
    {"code": "APPROVED", "name": "已通过", "color": "success"},
    {"code": "REJECTED", "name": "已驳回", "color": "danger"},
    {"code": "RETURNED", "name": "已退回", "color": "warning"},
    {"code": "CANCELED", "name": "已撤销", "color": "info"},
    {"code": "FAILED", "name": "失败", "color": "danger"},
]
ACTION_META = [
    {"code": "SUBMIT", "name": "提交"},
    {"code": "ASSIGN", "name": "指派"},
    {"code": "APPROVE", "name": "通过"},
    {"code": "REJECT", "name": "驳回"},
    {"code": "RETURN", "name": "退回"},
    {"code": "CANCEL", "name": "撤销"},
    {"code": "AUTO_PASS", "name": "自动通过"},
    {"code": "SERVICE_CALLBACK", "name": "服务回调"},
]
ENGINE_META = [
    {"code": "CONFIG", "name": "配置化流程"},
    {"code": "BPMN", "name": "BPMN/SpiffWorkflow"},
]
ASSIGNMENT_META = [
    {"code": "USER", "name": "指定用户"},
    {"code": "ROLE", "name": "指定角色"},
    {"code": "PERMISSION", "name": "指定权限"},
    {"code": "SUBMITTER_MANAGER", "name": "提交人主管"},
]
STEP_TYPE_META = [
    {"code": "HUMAN", "name": "人工任务"},
    {"code": "AUTO", "name": "自动判断"},
    {"code": "SERVICE", "name": "服务任务"},
]
ACTION_POLICY_META = [
    {"code": "ANY_ONE", "name": "任一处理"},
    {"code": "ALL", "name": "全部处理"},
]


def _now() -> datetime:
    return datetime.utcnow()


def _normal(value: str | None) -> str:
    return (value or "").strip().upper()


def _new_instance_no() -> str:
    return f"AP{_now():%Y%m%d%H%M%S}{uuid4().hex[:8].upper()}"


def _has_permission(granted_codes: list[str], required: str | None) -> bool:
    if not required:
        return True
    required_value = _normal(required)
    required_module = required_value.split(":", 1)[0]
    for granted in granted_codes:
        granted_value = _normal(granted)
        if granted_value in {required_value, "SYSTEM:ALL", f"{required_module}:ALL"}:
            return True
        if granted_value == "APPROVAL:ALL" and required_module == "APPROVAL":
            return True
        if granted_value.endswith(":WRITE") and required_value.endswith(":READ"):
            return granted_value.split(":", 1)[0] == required_module
    return False


class ApprovalService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ApprovalRepository(db)

    async def get_metadata(self) -> ApprovalMetadataResponse:
        subjects = [self._to_subject_response(row) for row in await self.repo.list_subject_definitions()]
        flows, _ = await self.repo.list_flow_definitions(status_code="ACTIVE", page=1, page_size=500)
        return ApprovalMetadataResponse(
            statuses=INSTANCE_STATUS_META,
            actions=ACTION_META,
            engines=ENGINE_META,
            assignment_types=ASSIGNMENT_META,
            step_types=STEP_TYPE_META,
            action_policies=ACTION_POLICY_META,
            subject_definitions=subjects,
            flow_definitions=[await self._to_flow_response(row) for row in flows],
        )

    async def list_subject_definitions(self) -> list[ApprovalSubjectDefinitionResponse]:
        return [self._to_subject_response(row) for row in await self.repo.list_subject_definitions()]

    async def create_subject_definition(
        self, payload: ApprovalSubjectDefinitionCreateRequest
    ) -> ApprovalSubjectDefinitionResponse:
        existing = await self.repo.get_subject_definition_by_type(payload.subject_type)
        if existing is not None:
            raise ConflictError(f"subject_type already exists: {payload.subject_type}")
        row = await self.repo.create_subject_definition(payload.model_dump())
        await self.db.commit()
        await self.db.refresh(row)
        return self._to_subject_response(row)

    async def update_subject_definition(
        self, definition_id: int, payload: ApprovalSubjectDefinitionUpdateRequest
    ) -> ApprovalSubjectDefinitionResponse:
        row = await self.repo.get_subject_definition(definition_id)
        if row is None:
            raise NotFoundError("ApprovalSubjectDefinition", definition_id)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(row, key, value)
        await self.db.commit()
        await self.db.refresh(row)
        return self._to_subject_response(row)

    async def list_flow_definitions(
        self, query: ApprovalFlowDefinitionListQuery
    ) -> PageResponse[ApprovalFlowDefinitionResponse]:
        rows, total = await self.repo.list_flow_definitions(
            subject_type=query.subject_type,
            trigger_action_code=query.trigger_action_code,
            engine_type=query.engine_type,
            status_code=query.status_code,
            keyword=query.keyword,
            page=query.page,
            page_size=query.page_size,
        )
        return PageResponse(
            total=total,
            page=query.page,
            page_size=query.page_size,
            items=[await self._to_flow_response(row) for row in rows],
        )

    async def create_flow_definition(
        self, payload: ApprovalFlowDefinitionCreateRequest
    ) -> ApprovalFlowDefinitionResponse:
        existing = await self.repo.get_flow_definition_by_code(payload.flow_code)
        if existing is not None:
            raise ConflictError(f"flow_code already exists: {payload.flow_code}")
        data = payload.model_dump(exclude={"steps"})
        data["engine_type"] = _normal(data.get("engine_type")) or "CONFIG"
        data["approval_mode"] = _normal(data.get("approval_mode")) or "SINGLE"
        data["status_code"] = _normal(data.get("status_code")) or "DRAFT"
        steps = [self._step_payload_to_dict(step) for step in payload.steps]
        await self._validate_flow_payload(data, steps)
        row = await self.repo.create_flow_definition(data)
        await self.repo.replace_step_definitions(int(row.id), steps)
        if row.status_code == "ACTIVE":
            await self._ensure_no_other_active_flow(row)
        await self.db.commit()
        await self.db.refresh(row)
        return await self._to_flow_response(row)

    async def update_flow_definition(
        self, flow_id: int, payload: ApprovalFlowDefinitionUpdateRequest
    ) -> ApprovalFlowDefinitionResponse:
        row = await self.repo.get_flow_definition(flow_id)
        if row is None:
            raise NotFoundError("ApprovalFlowDefinition", flow_id)
        values = payload.model_dump(exclude_unset=True)
        steps_payload = values.pop("steps", None)
        if row.status_code == "ACTIVE" and steps_payload is not None:
            raise ValidationError("ACTIVE flow steps cannot be edited directly; disable or create a new draft first")
        for key in ("engine_type", "approval_mode", "status_code"):
            if key in values and values[key] is not None:
                values[key] = _normal(values[key])
        draft_data = {
            "flow_code": row.flow_code,
            "flow_name": values.get("flow_name", row.flow_name),
            "subject_type": values.get("subject_type", row.subject_type),
            "trigger_action_code": values.get("trigger_action_code", row.trigger_action_code),
            "engine_type": values.get("engine_type", row.engine_type),
            "approval_mode": values.get("approval_mode", row.approval_mode),
            "status_code": values.get("status_code", row.status_code),
            "spiff_spec_id": values.get("spiff_spec_id", row.spiff_spec_id),
            "config_json": values.get("config_json", row.config_json),
        }
        existing_steps = await self.repo.list_step_definitions(flow_id)
        steps = (
            [self._step_payload_to_dict(step) for step in steps_payload]
            if steps_payload is not None
            else [self._step_definition_to_payload(row).model_dump() for row in existing_steps]
        )
        await self._validate_flow_payload(draft_data, steps)
        for key, value in values.items():
            setattr(row, key, value)
        if steps_payload is not None:
            await self.repo.replace_step_definitions(flow_id, steps)
        if row.status_code == "ACTIVE":
            await self._ensure_no_other_active_flow(row)
        await self.db.commit()
        await self.db.refresh(row)
        return await self._to_flow_response(row)

    async def submit_instance(
        self, payload: ApprovalInstanceSubmitRequest, submitter_id: int | None
    ) -> ApprovalInstanceResponse:
        existing = await self.repo.get_instance_by_idempotency_key(payload.idempotency_key)
        if existing is not None:
            return await self._to_instance_response(existing, submitter_id)
        subject = await self.repo.get_subject_definition_by_type(payload.subject_type)
        if subject is None or subject.status_code != "ACTIVE":
            raise ValidationError(f"approval subject is not active: {payload.subject_type}")
        flow = await self.repo.get_active_flow(payload.subject_type, payload.trigger_action_code)
        if flow is None:
            raise ValidationError(
                f"active approval flow not found: {payload.subject_type}/{payload.trigger_action_code}"
            )
        steps = await self.repo.list_step_definitions(int(flow.id))
        if flow.engine_type == "BPMN":
            engine_state = SpiffApprovalEngine().start(
                spec_id=flow.spiff_spec_id,
                payload=payload.submit_payload_json,
            )
        else:
            engine_state = {"engine": "CONFIG"}
        now = _now()
        instance = await self.repo.create_instance(
            {
                "instance_no": _new_instance_no(),
                "flow_id": flow.id,
                "flow_code": flow.flow_code,
                "subject_type": payload.subject_type,
                "subject_id": payload.subject_id,
                "subject_ref": payload.subject_ref,
                "subject_code": payload.subject_code,
                "subject_name": payload.subject_name,
                "subject_path": payload.subject_path,
                "trigger_action_code": payload.trigger_action_code,
                "status_code": "RUNNING",
                "submitter_id": submitter_id,
                "submitted_at": now,
                "engine_type": flow.engine_type,
                "engine_state_json": engine_state,
                "idempotency_key": payload.idempotency_key,
                "lock_version": 0,
            }
        )
        await self.repo.create_snapshot(
            {
                "instance_id": instance.id,
                "before_snapshot_json": payload.before_snapshot_json,
                "after_snapshot_json": payload.after_snapshot_json,
                "diff_json": payload.diff_json,
                "summary_json": payload.summary_json,
                "submit_payload_json": payload.submit_payload_json,
            }
        )
        await self.repo.create_action_log(
            {
                "instance_id": instance.id,
                "step_instance_id": None,
                "action_code": "SUBMIT",
                "operator_id": submitter_id,
                "from_status_code": None,
                "to_status_code": "RUNNING",
                "comment": None,
                "request_id": None,
                "created_at": now,
            }
        )
        runtime_steps = ConfigApprovalEngine().build_runtime_steps(flow, steps, submitter_id)
        step_instances = await self.repo.create_step_instances(
            [
                {
                    "instance_id": instance.id,
                    "step_key": step.step_key,
                    "step_order": step.step_order,
                    "step_name": step.step_name,
                    "status_code": "PENDING",
                    "candidate_user_id": step.candidate_user_id,
                    "candidate_role_code": step.candidate_role_code,
                    "candidate_permission_code": step.candidate_permission_code,
                }
                for step in runtime_steps
            ]
        )
        if step_instances:
            first_step = sorted(step_instances, key=lambda row: row.step_order)[0]
            first_step.status_code = "RUNNING"
            first_step.started_at = now
            instance.current_step_instance_id = first_step.id
            await self.repo.create_action_log(
                {
                    "instance_id": instance.id,
                    "step_instance_id": first_step.id,
                    "action_code": "ASSIGN",
                    "operator_id": submitter_id,
                    "from_status_code": "PENDING",
                    "to_status_code": "RUNNING",
                    "comment": "流程启动后自动分派首个步骤",
                    "request_id": None,
                    "created_at": now,
                }
            )
        else:
            await self._complete_instance(instance, "APPROVED", submitter_id, "AUTO_PASS", "无人工步骤，自动通过")
        await self.db.commit()
        await self.db.refresh(instance)
        return await self._to_instance_response(instance, submitter_id)

    async def list_instances(
        self, query: ApprovalInstanceListQuery, current_user_id: int | None
    ) -> PageResponse[ApprovalInstanceResponse]:
        rows, total = await self.repo.list_instances(
            tab=query.tab,
            current_user_id=current_user_id,
            subject_type=query.subject_type,
            flow_code=query.flow_code,
            status_code=query.status_code,
            submitter_id=query.submitter_id,
            actor_id=query.actor_id,
            submitted_from=query.submitted_from,
            submitted_to=query.submitted_to,
            keyword=query.keyword,
            page=query.page,
            page_size=query.page_size,
        )
        return PageResponse(
            total=total,
            page=query.page,
            page_size=query.page_size,
            items=[await self._to_instance_response(row, current_user_id) for row in rows],
        )

    async def get_instance_detail(
        self, instance_id: int, current_user_id: int | None
    ) -> ApprovalInstanceDetailResponse:
        instance = await self.repo.get_instance(instance_id)
        if instance is None:
            raise NotFoundError("ApprovalInstance", instance_id)
        snapshot = await self.repo.get_snapshot(instance_id)
        steps = await self.repo.list_step_instances(instance_id)
        logs = await self.repo.list_action_logs(instance_id)
        flow = await self.repo.get_flow_definition(int(instance.flow_id))
        return ApprovalInstanceDetailResponse(
            instance=await self._to_instance_response(instance, current_user_id, steps=steps),
            snapshot=self._to_snapshot_response(snapshot) if snapshot else None,
            steps=[await self._to_step_instance_response(row) for row in steps],
            action_logs=[self._to_action_log_response(row) for row in logs],
            flow_definition=await self._to_flow_response(flow) if flow else None,
        )

    async def get_pending_count(self, current_user_id: int | None) -> ApprovalPendingCountResponse:
        query = ApprovalInstanceListQuery(tab="PENDING", page=1, page_size=1)
        page = await self.list_instances(query, current_user_id)
        return ApprovalPendingCountResponse(pending_count=page.total)

    async def approve_instance(
        self, instance_id: int, payload: ApprovalActionRequest, operator_id: int
    ) -> ApprovalInstanceResponse:
        instance, current_step = await self._require_actionable_instance(instance_id, operator_id)
        now = _now()
        from_status = current_step.status_code
        current_step.status_code = "APPROVED"
        current_step.actor_id = operator_id
        current_step.comment = payload.comment
        current_step.acted_at = now
        await self.repo.create_action_log(
            self._action_log_data(instance, current_step, "APPROVE", operator_id, from_status, "APPROVED", payload)
        )
        steps = await self.repo.list_step_instances(instance_id)
        next_step = next((row for row in steps if row.status_code == "PENDING"), None)
        if next_step:
            next_step.status_code = "RUNNING"
            next_step.started_at = now
            instance.current_step_instance_id = next_step.id
            await self.repo.create_action_log(
                {
                    "instance_id": instance.id,
                    "step_instance_id": next_step.id,
                    "action_code": "ASSIGN",
                    "operator_id": operator_id,
                    "from_status_code": "PENDING",
                    "to_status_code": "RUNNING",
                    "comment": "上一步审批通过后自动分派",
                    "request_id": payload.request_id,
                    "created_at": now,
                }
            )
        else:
            await self._complete_instance(instance, "APPROVED", operator_id, "APPROVE", payload.comment)
        await self.db.commit()
        await self.db.refresh(instance)
        return await self._to_instance_response(instance, operator_id)

    async def reject_instance(
        self, instance_id: int, payload: ApprovalActionRequest, operator_id: int
    ) -> ApprovalInstanceResponse:
        if not (payload.comment or "").strip():
            raise ValidationError("驳回必须填写意见")
        instance, current_step = await self._require_actionable_instance(instance_id, operator_id)
        now = _now()
        from_step_status = current_step.status_code
        current_step.status_code = "REJECTED"
        current_step.actor_id = operator_id
        current_step.comment = payload.comment
        current_step.acted_at = now
        await self.repo.create_action_log(
            self._action_log_data(instance, current_step, "REJECT", operator_id, from_step_status, "REJECTED", payload)
        )
        await self._complete_instance(instance, "REJECTED", operator_id, "REJECT", payload.comment)
        await self.db.commit()
        await self.db.refresh(instance)
        return await self._to_instance_response(instance, operator_id)

    async def return_instance(
        self, instance_id: int, payload: ApprovalActionRequest, operator_id: int
    ) -> ApprovalInstanceResponse:
        if not (payload.comment or "").strip():
            raise ValidationError("退回必须填写意见")
        instance, current_step = await self._require_actionable_instance(instance_id, operator_id)
        from_status = instance.status_code
        current_step.status_code = "RETURNED"
        current_step.actor_id = operator_id
        current_step.comment = payload.comment
        current_step.acted_at = _now()
        instance.status_code = "RETURNED"
        instance.current_step_instance_id = None
        instance.completed_at = _now()
        instance.lock_version += 1
        await self.repo.create_action_log(
            {
                "instance_id": instance.id,
                "step_instance_id": current_step.id,
                "action_code": "RETURN",
                "operator_id": operator_id,
                "from_status_code": from_status,
                "to_status_code": "RETURNED",
                "comment": payload.comment,
                "request_id": payload.request_id,
                "created_at": _now(),
            }
        )
        await self._create_result_outbox(instance, "RETURNED", operator_id, payload.comment)
        await self.db.commit()
        await self.db.refresh(instance)
        return await self._to_instance_response(instance, operator_id)

    async def cancel_instance(
        self, instance_id: int, payload: ApprovalActionRequest, operator_id: int
    ) -> ApprovalInstanceResponse:
        instance = await self.repo.get_instance(instance_id)
        if instance is None:
            raise NotFoundError("ApprovalInstance", instance_id)
        if instance.status_code in FINAL_INSTANCE_STATUSES:
            raise ConflictError(f"approval instance already finished with status {instance.status_code}")
        if instance.submitter_id is not None and instance.submitter_id != operator_id:
            raise PermissionError("只能撤销自己提交的审批")
        from_status = instance.status_code
        current_step = (
            await self.repo.get_step_instance(int(instance.current_step_instance_id))
            if instance.current_step_instance_id
            else None
        )
        if current_step and current_step.status_code == "RUNNING":
            current_step.status_code = "SKIPPED"
            current_step.acted_at = _now()
        instance.status_code = "CANCELED"
        instance.current_step_instance_id = None
        instance.completed_at = _now()
        instance.lock_version += 1
        await self.repo.create_action_log(
            {
                "instance_id": instance.id,
                "step_instance_id": current_step.id if current_step else None,
                "action_code": "CANCEL",
                "operator_id": operator_id,
                "from_status_code": from_status,
                "to_status_code": "CANCELED",
                "comment": payload.comment,
                "request_id": payload.request_id,
                "created_at": _now(),
            }
        )
        await self._create_result_outbox(instance, "CANCELED", operator_id, payload.comment)
        await self.db.commit()
        await self.db.refresh(instance)
        return await self._to_instance_response(instance, operator_id)

    async def assign_instance(
        self, instance_id: int, payload: ApprovalAssignRequest, operator_id: int
    ) -> ApprovalInstanceResponse:
        instance = await self.repo.get_instance(instance_id)
        if instance is None:
            raise NotFoundError("ApprovalInstance", instance_id)
        if instance.status_code != "RUNNING" or not instance.current_step_instance_id:
            raise ConflictError("approval instance is not assignable")
        current_step = await self.repo.get_step_instance(int(instance.current_step_instance_id))
        if current_step is None:
            raise NotFoundError("ApprovalStepInstance", instance.current_step_instance_id)
        if not any([payload.assignee_user_id, payload.assignee_role_code, payload.assignee_permission_code]):
            raise ValidationError("指派必须提供用户、角色或权限候选")
        current_step.candidate_user_id = payload.assignee_user_id
        current_step.candidate_role_code = payload.assignee_role_code
        current_step.candidate_permission_code = payload.assignee_permission_code
        instance.lock_version += 1
        await self.repo.create_action_log(
            {
                "instance_id": instance.id,
                "step_instance_id": current_step.id,
                "action_code": "ASSIGN",
                "operator_id": operator_id,
                "from_status_code": "RUNNING",
                "to_status_code": "RUNNING",
                "comment": payload.comment,
                "request_id": payload.request_id,
                "created_at": _now(),
            }
        )
        await self.db.commit()
        await self.db.refresh(instance)
        return await self._to_instance_response(instance, operator_id)

    async def _validate_flow_payload(self, data: dict[str, Any], steps: list[dict[str, Any]]) -> None:
        engine_type = _normal(data.get("engine_type"))
        status_code = _normal(data.get("status_code"))
        approval_mode = _normal(data.get("approval_mode"))
        if engine_type not in {"CONFIG", "BPMN"}:
            raise ValidationError("engine_type must be CONFIG or BPMN")
        if approval_mode not in {"SINGLE", "SINGLE_STEP", "MULTI_STEP"}:
            raise ValidationError("approval_mode must be SINGLE or MULTI_STEP")
        if status_code not in {"DRAFT", "ACTIVE", "DISABLED"}:
            raise ValidationError("flow status_code must be DRAFT, ACTIVE or DISABLED")
        subject = await self.repo.get_subject_definition_by_type(str(data.get("subject_type")))
        if subject is None:
            raise ValidationError(f"approval subject not configured: {data.get('subject_type')}")
        if engine_type == "BPMN" and not data.get("spiff_spec_id"):
            raise ValidationError("BPMN flow requires spiff_spec_id")
        if engine_type == "CONFIG":
            self._validate_config_steps(steps)

    @staticmethod
    def _validate_config_steps(steps: list[dict[str, Any]]) -> None:
        if not steps:
            raise ValidationError("CONFIG flow requires at least one step")
        keys = [str(row.get("step_key")) for row in steps]
        orders = [int(row.get("step_order") or 0) for row in steps]
        if len(keys) != len(set(keys)):
            raise ValidationError("step_key must be unique")
        if sorted(orders) != list(range(1, len(orders) + 1)):
            raise ValidationError("step_order must be continuous from 1")
        if not any(_normal(row.get("step_type")) == "HUMAN" for row in steps):
            raise ValidationError("CONFIG flow requires at least one human step")
        for row in steps:
            step_type = _normal(row.get("step_type"))
            assignment_type = _normal(row.get("assignment_type"))
            action_policy = _normal(row.get("action_policy"))
            if step_type not in {"HUMAN", "AUTO", "SERVICE"}:
                raise ValidationError("step_type must be HUMAN, AUTO or SERVICE")
            if assignment_type not in {"USER", "ROLE", "PERMISSION", "SUBMITTER_MANAGER"}:
                raise ValidationError("assignment_type must be USER, ROLE, PERMISSION or SUBMITTER_MANAGER")
            if action_policy not in {"ANY_ONE", "ALL"}:
                raise ValidationError("action_policy must be ANY_ONE or ALL")
            if step_type == "HUMAN":
                if assignment_type == "USER" and not row.get("assignee_user_id"):
                    raise ValidationError(f"{row.get('step_key')} requires assignee_user_id")
                if assignment_type == "ROLE" and not row.get("assignee_role_code"):
                    raise ValidationError(f"{row.get('step_key')} requires assignee_role_code")
                if assignment_type == "PERMISSION" and not row.get("assignee_permission_code"):
                    raise ValidationError(f"{row.get('step_key')} requires assignee_permission_code")

    async def _ensure_no_other_active_flow(self, row: ApprovalFlowDefinition) -> None:
        existing = await self.repo.get_active_flow(row.subject_type, row.trigger_action_code)
        if existing is not None and int(existing.id) != int(row.id):
            raise ConflictError(
                f"active flow already exists for {row.subject_type}/{row.trigger_action_code}: {existing.flow_code}"
            )

    async def _require_actionable_instance(
        self, instance_id: int, operator_id: int
    ) -> tuple[ApprovalInstance, ApprovalStepInstance]:
        instance = await self.repo.get_instance(instance_id)
        if instance is None:
            raise NotFoundError("ApprovalInstance", instance_id)
        if instance.status_code != "RUNNING" or not instance.current_step_instance_id:
            raise ConflictError(f"approval instance is not actionable with status {instance.status_code}")
        current_step = await self.repo.get_step_instance(int(instance.current_step_instance_id))
        if current_step is None:
            raise NotFoundError("ApprovalStepInstance", instance.current_step_instance_id)
        if not await self._is_step_candidate(current_step, operator_id):
            raise PermissionError("当前账号不是该步骤候选处理人")
        return instance, current_step

    async def _is_step_candidate(self, step: ApprovalStepInstance, user_id: int) -> bool:
        if step.candidate_user_id is not None:
            return int(step.candidate_user_id) == int(user_id)
        role_codes = await list_current_user_role_codes(self.db, user_id)
        permission_codes = await list_current_user_permission_codes(self.db, user_id)
        if "SUPER_ADMIN" in {code.upper() for code in role_codes}:
            return True
        if step.candidate_role_code:
            return _normal(step.candidate_role_code) in {_normal(code) for code in role_codes}
        if step.candidate_permission_code:
            return _has_permission(permission_codes, step.candidate_permission_code)
        return _has_permission(permission_codes, "APPROVAL:WRITE")

    async def _complete_instance(
        self,
        instance: ApprovalInstance,
        decision_code: str,
        operator_id: int | None,
        action_code: str,
        comment: str | None,
    ) -> None:
        from_status = instance.status_code
        now = _now()
        instance.status_code = decision_code
        instance.completed_at = now
        instance.current_step_instance_id = None
        instance.lock_version += 1
        if action_code == "AUTO_PASS":
            await self.repo.create_action_log(
                {
                    "instance_id": instance.id,
                    "step_instance_id": None,
                    "action_code": "AUTO_PASS",
                    "operator_id": operator_id,
                    "from_status_code": from_status,
                    "to_status_code": decision_code,
                    "comment": comment,
                    "request_id": None,
                    "created_at": now,
                }
            )
        await self._create_result_outbox(instance, decision_code, operator_id, comment)

    async def _create_result_outbox(
        self,
        instance: ApprovalInstance,
        decision_code: str,
        operator_id: int | None,
        comment: str | None,
    ) -> None:
        snapshot = await self.repo.get_snapshot(int(instance.id))
        await self.repo.create_outbox(
            {
                "event_type": "APPROVAL_COMPLETED",
                "instance_id": instance.id,
                "subject_type": instance.subject_type,
                "subject_id": instance.subject_id,
                "decision_code": decision_code,
                "payload_json": {
                    "instance_id": instance.id,
                    "instance_no": instance.instance_no,
                    "subject_type": instance.subject_type,
                    "subject_id": instance.subject_id,
                    "subject_ref": instance.subject_ref,
                    "subject_code": instance.subject_code,
                    "trigger_action_code": instance.trigger_action_code,
                    "decision_code": decision_code,
                    "operator_id": operator_id,
                    "comment": comment,
                    "summary_json": snapshot.summary_json if snapshot else None,
                    "submit_payload_json": snapshot.submit_payload_json if snapshot else None,
                    "before_snapshot_json": snapshot.before_snapshot_json if snapshot else None,
                    "after_snapshot_json": snapshot.after_snapshot_json if snapshot else None,
                    "diff_json": snapshot.diff_json if snapshot else None,
                },
                "status_code": "PENDING",
                "retry_count": 0,
                "next_retry_at": _now(),
                "last_error": None,
            }
        )

    def _action_log_data(
        self,
        instance: ApprovalInstance,
        step: ApprovalStepInstance,
        action_code: str,
        operator_id: int,
        from_status: str | None,
        to_status: str | None,
        payload: ApprovalActionRequest,
    ) -> dict[str, Any]:
        return {
            "instance_id": instance.id,
            "step_instance_id": step.id,
            "action_code": action_code,
            "operator_id": operator_id,
            "from_status_code": from_status,
            "to_status_code": to_status,
            "comment": payload.comment,
            "request_id": payload.request_id,
            "created_at": _now(),
        }

    def _to_subject_response(self, row: ApprovalSubjectDefinition) -> ApprovalSubjectDefinitionResponse:
        return ApprovalSubjectDefinitionResponse(
            id=int(row.id),
            subject_type=row.subject_type,
            subject_name=row.subject_name,
            module_code=row.module_code,
            detail_path_template=row.detail_path_template,
            read_permission_code=row.read_permission_code,
            submit_permission_code=row.submit_permission_code,
            status_code=row.status_code,
            summary_schema_json=row.summary_schema_json,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _to_flow_response(self, row: ApprovalFlowDefinition) -> ApprovalFlowDefinitionResponse:
        steps = await self.repo.list_step_definitions(int(row.id))
        return ApprovalFlowDefinitionResponse(
            id=int(row.id),
            flow_code=row.flow_code,
            flow_name=row.flow_name,
            subject_type=row.subject_type,
            trigger_action_code=row.trigger_action_code,
            engine_type=row.engine_type,
            approval_mode=row.approval_mode,
            status_code=row.status_code,
            spiff_spec_id=row.spiff_spec_id,
            config_json=row.config_json,
            created_at=row.created_at,
            updated_at=row.updated_at,
            steps=[self._to_step_definition_response(step) for step in steps],
        )

    @staticmethod
    def _to_step_definition_response(row: ApprovalStepDefinition) -> ApprovalStepDefinitionResponse:
        return ApprovalStepDefinitionResponse(
            id=int(row.id),
            flow_id=int(row.flow_id),
            step_key=row.step_key,
            step_order=row.step_order,
            step_name=row.step_name,
            step_type=row.step_type,
            assignment_type=row.assignment_type,
            assignee_user_id=row.assignee_user_id,
            assignee_role_code=row.assignee_role_code,
            assignee_permission_code=row.assignee_permission_code,
            action_policy=row.action_policy,
            condition_json=row.condition_json,
            sla_hours=row.sla_hours,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _step_definition_to_payload(row: ApprovalStepDefinition) -> ApprovalStepDefinitionPayload:
        return ApprovalStepDefinitionPayload(
            step_key=row.step_key,
            step_order=row.step_order,
            step_name=row.step_name,
            step_type=row.step_type,
            assignment_type=row.assignment_type,
            assignee_user_id=row.assignee_user_id,
            assignee_role_code=row.assignee_role_code,
            assignee_permission_code=row.assignee_permission_code,
            action_policy=row.action_policy,
            condition_json=row.condition_json,
            sla_hours=row.sla_hours,
        )

    @staticmethod
    def _step_payload_to_dict(row: ApprovalStepDefinitionPayload) -> dict[str, Any]:
        data = row.model_dump()
        data["step_type"] = _normal(data.get("step_type")) or "HUMAN"
        data["assignment_type"] = _normal(data.get("assignment_type")) or "PERMISSION"
        data["action_policy"] = _normal(data.get("action_policy")) or "ANY_ONE"
        return data

    async def _to_instance_response(
        self,
        row: ApprovalInstance,
        current_user_id: int | None = None,
        steps: list[ApprovalStepInstance] | None = None,
    ) -> ApprovalInstanceResponse:
        if steps is None:
            steps = await self.repo.list_step_instances(int(row.id))
        current_step = next((step for step in steps if step.id == row.current_step_instance_id), None)
        flow = await self.repo.get_flow_definition(int(row.flow_id))
        available_actions: list[str] = []
        if (
            row.status_code == "RUNNING"
            and current_step is not None
            and current_user_id is not None
            and await self._is_step_candidate(current_step, current_user_id)
        ):
            available_actions = ["APPROVE", "REJECT", "RETURN", "ASSIGN"]
        if (
            row.status_code not in FINAL_INSTANCE_STATUSES
            and current_user_id is not None
            and row.submitter_id == current_user_id
        ):
            available_actions.append("CANCEL")
        current_candidates = self._current_candidates(current_step)
        return ApprovalInstanceResponse(
            id=int(row.id),
            instance_no=row.instance_no,
            flow_id=int(row.flow_id),
            flow_code=row.flow_code,
            flow_name=flow.flow_name if flow else None,
            subject_type=row.subject_type,
            subject_id=row.subject_id,
            subject_ref=row.subject_ref,
            subject_code=row.subject_code,
            subject_name=row.subject_name,
            subject_path=row.subject_path,
            trigger_action_code=row.trigger_action_code,
            status_code=row.status_code,
            current_step_instance_id=row.current_step_instance_id,
            current_step_name=current_step.step_name if current_step else None,
            submitter_id=row.submitter_id,
            submitted_at=row.submitted_at,
            completed_at=row.completed_at,
            engine_type=row.engine_type,
            lock_version=row.lock_version,
            created_at=row.created_at,
            updated_at=row.updated_at,
            available_actions=available_actions,
            current_candidates=current_candidates,
        )

    async def _to_step_instance_response(self, row: ApprovalStepInstance) -> ApprovalStepInstanceResponse:
        definitions = (
            await self.db.scalars(
                select(ApprovalStepDefinition)
                .join(ApprovalFlowDefinition, ApprovalFlowDefinition.id == ApprovalStepDefinition.flow_id)
                .join(ApprovalInstance, ApprovalInstance.flow_id == ApprovalFlowDefinition.id)
                .where(
                    ApprovalInstance.id == row.instance_id,
                    ApprovalStepDefinition.step_key == row.step_key,
                )
            )
        ).all()
        definition = definitions[0] if definitions else None
        return ApprovalStepInstanceResponse(
            id=int(row.id),
            instance_id=int(row.instance_id),
            step_key=row.step_key,
            step_order=row.step_order,
            step_name=row.step_name,
            status_code=row.status_code,
            candidate_user_id=row.candidate_user_id,
            candidate_role_code=row.candidate_role_code,
            candidate_permission_code=row.candidate_permission_code,
            actor_id=row.actor_id,
            comment=row.comment,
            started_at=row.started_at,
            acted_at=row.acted_at,
            sla_hours=definition.sla_hours if definition else None,
        )

    @staticmethod
    def _to_snapshot_response(row: ApprovalSnapshot) -> ApprovalSnapshotResponse:
        return ApprovalSnapshotResponse(
            before_snapshot_json=row.before_snapshot_json,
            after_snapshot_json=row.after_snapshot_json,
            diff_json=row.diff_json,
            summary_json=row.summary_json,
            submit_payload_json=row.submit_payload_json,
        )

    @staticmethod
    def _to_action_log_response(row: ApprovalActionLog) -> ApprovalActionLogResponse:
        return ApprovalActionLogResponse(
            id=int(row.id),
            instance_id=int(row.instance_id),
            step_instance_id=row.step_instance_id,
            action_code=row.action_code,
            operator_id=row.operator_id,
            from_status_code=row.from_status_code,
            to_status_code=row.to_status_code,
            comment=row.comment,
            request_id=row.request_id,
            created_at=row.created_at,
        )

    @staticmethod
    def _current_candidates(step: ApprovalStepInstance | None) -> list[ApprovalCandidateResponse]:
        if step is None:
            return []
        if step.candidate_user_id is not None:
            return [
                ApprovalCandidateResponse(
                    user_id=step.candidate_user_id,
                    display_name=f"用户 {step.candidate_user_id}",
                )
            ]
        if step.candidate_role_code:
            return [
                ApprovalCandidateResponse(
                    role_code=step.candidate_role_code,
                    display_name=f"角色 {step.candidate_role_code}",
                )
            ]
        if step.candidate_permission_code:
            return [
                ApprovalCandidateResponse(
                    permission_code=step.candidate_permission_code,
                    display_name=f"权限 {step.candidate_permission_code}",
                )
            ]
        return [ApprovalCandidateResponse(display_name="审批中心处理人")]
