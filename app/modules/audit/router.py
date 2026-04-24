"""audit 模块 router。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.modules.audit.schemas import (
    AuditPendingCountResponse,
    AuditRecordListQuery,
    AuditRecordResponse,
    AuditTaskActionRequest,
    AuditTaskAssignRequest,
    AuditTaskCreateRequest,
    AuditTaskDetailResponse,
    AuditTaskListQuery,
    AuditTaskResponse,
    PageResponse,
)
from app.modules.audit.service import AuditRecordService, AuditTaskService

router = APIRouter()


@router.get("/tasks", response_model=PageResponse[AuditTaskResponse])
async def list_tasks(
    query: AuditTaskListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AuditTaskService(db)
    return await service.list_tasks(
        keyword=query.keyword,
        task_type=query.task_type,
        status_code=query.status_code,
        object_type=query.object_type,
        object_id=query.object_id,
        assignee_user_id=query.assignee_user_id,
        page=query.page,
        page_size=query.page_size,
    )


@router.get("/tasks/{task_id}", response_model=AuditTaskDetailResponse)
async def get_task_detail(
    task_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AuditTaskService(db)
    return await service.get_task_detail(task_id)


@router.post("/tasks", response_model=AuditTaskResponse)
async def create_task(
    body: AuditTaskCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AuditTaskService(db)
    return await service.create_task(body)


@router.put("/tasks/{task_id}/assign")
async def assign_task(
    task_id: int,
    body: AuditTaskAssignRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AuditTaskService(db)
    await service.assign_task(
        task_id=task_id,
        assignee_user_id=body.assignee_user_id,
        operator_user_id=current_user.id,
    )
    return {"ok": True}


@router.put("/tasks/{task_id}/approve")
async def approve_task(
    task_id: int,
    body: AuditTaskActionRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AuditTaskService(db)
    await service.approve_task(task_id, body.comment, current_user.id)
    return {"ok": True}


@router.put("/tasks/{task_id}/reject")
async def reject_task(
    task_id: int,
    body: AuditTaskActionRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AuditTaskService(db)
    await service.reject_task(task_id, body.comment, current_user.id)
    return {"ok": True}


@router.put("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: int,
    body: AuditTaskActionRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AuditTaskService(db)
    await service.cancel_task(task_id, body.comment, current_user.id)
    return {"ok": True}


@router.get("/pending-count", response_model=AuditPendingCountResponse)
async def get_pending_count(
    assignee_user_id: int | None = None,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AuditTaskService(db)
    return await service.get_pending_count(assignee_user_id)


@router.get("/tasks/{task_id}/records", response_model=PageResponse[AuditRecordResponse])
async def list_task_records(
    task_id: int,
    query: AuditRecordListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AuditRecordService(db)
    return await service.list_records(task_id=task_id, page=query.page, page_size=query.page_size)
