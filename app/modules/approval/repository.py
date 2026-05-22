"""Approval center repository."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import (
    ApprovalActionLog,
    ApprovalFlowDefinition,
    ApprovalInstance,
    ApprovalOutbox,
    ApprovalSnapshot,
    ApprovalStepDefinition,
    ApprovalStepInstance,
    ApprovalSubjectDefinition,
)


class ApprovalRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_subject_definition_by_type(self, subject_type: str) -> ApprovalSubjectDefinition | None:
        return await self.db.scalar(
            select(ApprovalSubjectDefinition).where(ApprovalSubjectDefinition.subject_type == subject_type)
        )

    async def list_subject_definitions(self) -> list[ApprovalSubjectDefinition]:
        return list(
            (
                await self.db.scalars(
                    select(ApprovalSubjectDefinition).order_by(
                        ApprovalSubjectDefinition.module_code.asc(),
                        ApprovalSubjectDefinition.subject_type.asc(),
                    )
                )
            ).all()
        )

    async def get_subject_definition(self, definition_id: int) -> ApprovalSubjectDefinition | None:
        return await self.db.get(ApprovalSubjectDefinition, definition_id)

    async def create_subject_definition(self, data: dict[str, Any]) -> ApprovalSubjectDefinition:
        row = ApprovalSubjectDefinition(**data)
        self.db.add(row)
        await self.db.flush()
        return row

    async def list_flow_definitions(
        self,
        *,
        subject_type: str | None = None,
        trigger_action_code: str | None = None,
        engine_type: str | None = None,
        status_code: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ApprovalFlowDefinition], int]:
        stmt = select(ApprovalFlowDefinition)
        if subject_type:
            stmt = stmt.where(ApprovalFlowDefinition.subject_type == subject_type)
        if trigger_action_code:
            stmt = stmt.where(ApprovalFlowDefinition.trigger_action_code == trigger_action_code)
        if engine_type:
            stmt = stmt.where(ApprovalFlowDefinition.engine_type == engine_type)
        if status_code:
            stmt = stmt.where(ApprovalFlowDefinition.status_code == status_code)
        if keyword:
            like_value = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    ApprovalFlowDefinition.flow_code.ilike(like_value),
                    ApprovalFlowDefinition.flow_name.ilike(like_value),
                    ApprovalFlowDefinition.subject_type.ilike(like_value),
                )
            )
        total = await self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = (
            await self.db.scalars(
                stmt.order_by(ApprovalFlowDefinition.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return list(rows), int(total)

    async def get_flow_definition(self, flow_id: int) -> ApprovalFlowDefinition | None:
        return await self.db.get(ApprovalFlowDefinition, flow_id)

    async def get_flow_definition_by_code(self, flow_code: str) -> ApprovalFlowDefinition | None:
        return await self.db.scalar(select(ApprovalFlowDefinition).where(ApprovalFlowDefinition.flow_code == flow_code))

    async def get_active_flow(self, subject_type: str, trigger_action_code: str) -> ApprovalFlowDefinition | None:
        return await self.db.scalar(
            select(ApprovalFlowDefinition)
            .where(
                ApprovalFlowDefinition.subject_type == subject_type,
                ApprovalFlowDefinition.trigger_action_code == trigger_action_code,
                ApprovalFlowDefinition.status_code == "ACTIVE",
            )
            .order_by(ApprovalFlowDefinition.updated_at.desc(), ApprovalFlowDefinition.id.desc())
        )

    async def create_flow_definition(self, data: dict[str, Any]) -> ApprovalFlowDefinition:
        row = ApprovalFlowDefinition(**data)
        self.db.add(row)
        await self.db.flush()
        return row

    async def replace_step_definitions(
        self, flow_id: int, steps: list[dict[str, Any]]
    ) -> list[ApprovalStepDefinition]:
        await self.db.execute(delete(ApprovalStepDefinition).where(ApprovalStepDefinition.flow_id == flow_id))
        rows = [ApprovalStepDefinition(flow_id=flow_id, **data) for data in steps]
        self.db.add_all(rows)
        await self.db.flush()
        return rows

    async def list_step_definitions(self, flow_id: int) -> list[ApprovalStepDefinition]:
        return list(
            (
                await self.db.scalars(
                    select(ApprovalStepDefinition)
                    .where(ApprovalStepDefinition.flow_id == flow_id)
                    .order_by(ApprovalStepDefinition.step_order.asc())
                )
            ).all()
        )

    async def get_instance(self, instance_id: int) -> ApprovalInstance | None:
        return await self.db.get(ApprovalInstance, instance_id)

    async def get_instance_by_idempotency_key(self, idempotency_key: str) -> ApprovalInstance | None:
        return await self.db.scalar(
            select(ApprovalInstance).where(ApprovalInstance.idempotency_key == idempotency_key)
        )

    async def create_instance(self, data: dict[str, Any]) -> ApprovalInstance:
        row = ApprovalInstance(**data)
        self.db.add(row)
        await self.db.flush()
        return row

    async def list_instances(
        self,
        *,
        tab: str | None = None,
        current_user_id: int | None = None,
        subject_type: str | None = None,
        flow_code: str | None = None,
        status_code: str | None = None,
        submitter_id: int | None = None,
        actor_id: int | None = None,
        submitted_from: datetime | None = None,
        submitted_to: datetime | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ApprovalInstance], int]:
        stmt: Select = select(ApprovalInstance)
        if subject_type:
            stmt = stmt.where(ApprovalInstance.subject_type == subject_type)
        if flow_code:
            stmt = stmt.where(ApprovalInstance.flow_code == flow_code)
        if status_code:
            stmt = stmt.where(ApprovalInstance.status_code == status_code)
        if submitter_id:
            stmt = stmt.where(ApprovalInstance.submitter_id == submitter_id)
        if submitted_from:
            stmt = stmt.where(ApprovalInstance.submitted_at >= submitted_from)
        if submitted_to:
            stmt = stmt.where(ApprovalInstance.submitted_at <= submitted_to)
        if keyword:
            like_value = f"%{keyword}%"
            stmt = stmt.where(
                or_(
                    ApprovalInstance.instance_no.ilike(like_value),
                    ApprovalInstance.subject_code.ilike(like_value),
                    ApprovalInstance.subject_name.ilike(like_value),
                    ApprovalInstance.subject_ref.ilike(like_value),
                )
            )
        if tab == "SUBMITTED" and current_user_id:
            stmt = stmt.where(ApprovalInstance.submitter_id == current_user_id)
        elif tab == "PENDING" and current_user_id:
            stmt = stmt.join(
                ApprovalStepInstance,
                ApprovalStepInstance.id == ApprovalInstance.current_step_instance_id,
            ).where(
                ApprovalInstance.status_code == "RUNNING",
                or_(
                    ApprovalStepInstance.candidate_user_id == current_user_id,
                    ApprovalStepInstance.candidate_user_id.is_(None),
                ),
            )
        elif tab == "DONE" and current_user_id:
            acted = select(ApprovalActionLog.instance_id).where(ApprovalActionLog.operator_id == current_user_id)
            stmt = stmt.where(ApprovalInstance.id.in_(acted))
        if actor_id:
            acted = select(ApprovalActionLog.instance_id).where(ApprovalActionLog.operator_id == actor_id)
            stmt = stmt.where(ApprovalInstance.id.in_(acted))
        total = await self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = (
            await self.db.scalars(
                stmt.order_by(ApprovalInstance.submitted_at.desc(), ApprovalInstance.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return list(rows), int(total)

    async def list_step_instances(self, instance_id: int) -> list[ApprovalStepInstance]:
        return list(
            (
                await self.db.scalars(
                    select(ApprovalStepInstance)
                    .where(ApprovalStepInstance.instance_id == instance_id)
                    .order_by(ApprovalStepInstance.step_order.asc())
                )
            ).all()
        )

    async def create_step_instances(self, rows: list[dict[str, Any]]) -> list[ApprovalStepInstance]:
        entities = [ApprovalStepInstance(**row) for row in rows]
        self.db.add_all(entities)
        await self.db.flush()
        return entities

    async def get_step_instance(self, step_instance_id: int) -> ApprovalStepInstance | None:
        return await self.db.get(ApprovalStepInstance, step_instance_id)

    async def get_snapshot(self, instance_id: int) -> ApprovalSnapshot | None:
        return await self.db.scalar(select(ApprovalSnapshot).where(ApprovalSnapshot.instance_id == instance_id))

    async def create_snapshot(self, data: dict[str, Any]) -> ApprovalSnapshot:
        row = ApprovalSnapshot(**data)
        self.db.add(row)
        await self.db.flush()
        return row

    async def list_action_logs(self, instance_id: int) -> list[ApprovalActionLog]:
        return list(
            (
                await self.db.scalars(
                    select(ApprovalActionLog)
                    .where(ApprovalActionLog.instance_id == instance_id)
                    .order_by(ApprovalActionLog.created_at.asc(), ApprovalActionLog.id.asc())
                )
            ).all()
        )

    async def create_action_log(self, data: dict[str, Any]) -> ApprovalActionLog:
        row = ApprovalActionLog(**data)
        self.db.add(row)
        await self.db.flush()
        return row

    async def create_outbox(self, data: dict[str, Any]) -> ApprovalOutbox:
        row = ApprovalOutbox(**data)
        self.db.add(row)
        await self.db.flush()
        return row

    async def latest_state_for_subjects(
        self, subject_type: str, subject_ids: list[int]
    ) -> dict[int, ApprovalInstance]:
        if not subject_ids:
            return {}
        rows = (
            await self.db.scalars(
                select(ApprovalInstance)
                .where(
                    ApprovalInstance.subject_type == subject_type,
                    ApprovalInstance.subject_id.in_(subject_ids),
                )
                .order_by(ApprovalInstance.subject_id.asc(), ApprovalInstance.submitted_at.desc(), ApprovalInstance.id.desc())
            )
        ).all()
        result: dict[int, ApprovalInstance] = {}
        for row in rows:
            if row.subject_id is not None and row.subject_id not in result:
                result[int(row.subject_id)] = row
        return result
