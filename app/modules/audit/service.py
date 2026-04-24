"""audit 模块 service。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.modules.dictionary.service import CodeSequenceService
from app.modules.audit.repository import AuditRecordRepository, AuditTaskRepository
from app.modules.audit.schemas import (
    AuditPendingCountResponse,
    AuditRecordResponse,
    AuditTaskCreateRequest,
    AuditTaskDetailResponse,
    AuditTaskResponse,
    PageResponse,
)

_FINAL_STATUSES = {"APPROVED", "REJECTED", "CANCELED"}


def _to_task_response(entity) -> AuditTaskResponse:
    return AuditTaskResponse(
        id=entity.id,
        task_no=entity.task_no,
        task_type=entity.biz_type_code,
        object_id=entity.biz_id,
        object_type=entity.biz_code,
        object_code=entity.biz_code,
        submitter_id=entity.submitter_id,
        assignee_user_id=entity.current_handler_id,
        status_code=entity.audit_status,
        audit_remark=entity.audit_remark,
        submitted_at=entity.submitted_at,
        completed_at=entity.completed_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_record_response(entity) -> AuditRecordResponse:
    return AuditRecordResponse(
        id=entity.id,
        task_id=entity.task_id,
        action_code=entity.action_code,
        operator_id=entity.operator_id,
        from_status_code=entity.from_status_code,
        to_status_code=entity.to_status_code,
        remark=entity.remark,
        created_at=entity.created_at,
    )


def _ensure_task_actionable(task) -> None:
    if task.audit_status in _FINAL_STATUSES:
        raise ValidationError(f"task already finished with status {task.audit_status}")


class AuditTaskService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.task_repo = AuditTaskRepository(db)
        self.record_repo = AuditRecordRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def list_tasks(
        self,
        keyword: str | None,
        task_type: str | None,
        status_code: str | None,
        object_type: str | None,
        object_id: int | None,
        assignee_user_id: int | None,
        page: int,
        page_size: int,
    ) -> PageResponse[AuditTaskResponse]:
        rows, total = await self.task_repo.list_tasks(
            keyword=keyword,
            task_type=task_type,
            status_code=status_code,
            object_type=object_type,
            object_id=object_id,
            assignee_user_id=assignee_user_id,
            page=page,
            page_size=page_size,
        )
        return PageResponse[AuditTaskResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_task_response(item) for item in rows],
        )

    async def create_task(self, payload: AuditTaskCreateRequest) -> AuditTaskResponse:
        now = datetime.utcnow()
        task_no = (payload.task_no or "").strip()
        if not task_no:
            task_no = await self.sequence_service.next_code("AUDIT_TASK_NO")
        if not task_no:
            raise ValidationError("task_no cannot be empty")
        task = await self.task_repo.create_task(
            {
                "task_no": task_no,
                "biz_type_code": payload.task_type.strip(),
                "biz_id": payload.object_id,
                "biz_code": payload.object_code or payload.object_type,
                "submitter_id": payload.submitter_id,
                "current_handler_id": payload.assignee_user_id,
                "audit_status": "PENDING",
                "audit_remark": payload.comment,
                "submitted_at": now,
                "completed_at": None,
            }
        )
        await self.record_repo.create_record(
            {
                "task_id": task.id,
                "action_code": "SUBMIT",
                "operator_id": payload.submitter_id,
                "from_status_code": None,
                "to_status_code": "PENDING",
                "remark": payload.comment,
                "created_at": now,
            }
        )
        await self.db.commit()
        return _to_task_response(task)

    async def get_task_detail(self, task_id: int) -> AuditTaskDetailResponse:
        task = await self.task_repo.get_task_by_id(task_id)
        if task is None:
            raise NotFoundError("AuditTask", task_id)
        rows, _ = await self.record_repo.list_records(task_id, page=1, page_size=500)
        return AuditTaskDetailResponse(
            task=_to_task_response(task),
            records=[_to_record_response(item) for item in rows],
        )

    async def assign_task(self, task_id: int, assignee_user_id: int, operator_user_id: int) -> None:
        task = await self.task_repo.get_task_by_id(task_id)
        if task is None:
            raise NotFoundError("AuditTask", task_id)
        _ensure_task_actionable(task)
        from_status = task.audit_status
        ok = await self.task_repo.assign_task(task_id, assignee_user_id)
        if not ok:
            raise NotFoundError("AuditTask", task_id)
        await self.record_repo.create_record(
            {
                "task_id": task_id,
                "action_code": "ASSIGN",
                "operator_id": operator_user_id,
                "from_status_code": from_status,
                "to_status_code": from_status,
                "remark": f"assign_to={assignee_user_id}",
            }
        )
        await self.db.commit()

    async def approve_task(self, task_id: int, comment: str | None, operator_user_id: int) -> None:
        await self._finish_task(
            task_id=task_id,
            target_status="APPROVED",
            action_code="APPROVE",
            comment=comment,
            operator_user_id=operator_user_id,
        )

    async def reject_task(self, task_id: int, comment: str | None, operator_user_id: int) -> None:
        await self._finish_task(
            task_id=task_id,
            target_status="REJECTED",
            action_code="REJECT",
            comment=comment,
            operator_user_id=operator_user_id,
        )

    async def cancel_task(self, task_id: int, comment: str | None, operator_user_id: int) -> None:
        await self._finish_task(
            task_id=task_id,
            target_status="CANCELED",
            action_code="CANCEL",
            comment=comment,
            operator_user_id=operator_user_id,
        )

    async def _finish_task(
        self,
        task_id: int,
        target_status: str,
        action_code: str,
        comment: str | None,
        operator_user_id: int,
    ) -> None:
        task = await self.task_repo.get_task_by_id(task_id)
        if task is None:
            raise NotFoundError("AuditTask", task_id)
        _ensure_task_actionable(task)
        now = datetime.utcnow()
        from_status = task.audit_status
        updated = await self.task_repo.update_task(
            task_id,
            {
                "audit_status": target_status,
                "audit_remark": comment,
                "completed_at": now,
            },
        )
        if updated is None:
            raise NotFoundError("AuditTask", task_id)
        await self.record_repo.create_record(
            {
                "task_id": task_id,
                "action_code": action_code,
                "operator_id": operator_user_id,
                "from_status_code": from_status,
                "to_status_code": target_status,
                "remark": comment,
                "created_at": now,
            }
        )
        await self.db.commit()

    async def get_pending_count(self, assignee_user_id: int | None = None) -> AuditPendingCountResponse:
        count = await self.task_repo.get_pending_count(assignee_user_id)
        return AuditPendingCountResponse(pending_count=count)


class AuditRecordService:
    def __init__(self, db: AsyncSession) -> None:
        self.repo = AuditRecordRepository(db)

    async def list_records(
        self,
        task_id: int,
        page: int,
        page_size: int,
    ) -> PageResponse[AuditRecordResponse]:
        rows, total = await self.repo.list_records(task_id, page=page, page_size=page_size)
        return PageResponse[AuditRecordResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_record_response(item) for item in rows],
        )
