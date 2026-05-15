"""统一后台任务中心 router。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.modules.tasks.schemas import (
    AsyncTaskRunQuery,
    AsyncTaskRunResponse,
    PageResponse,
    TaskRecoverStaleResponse,
    TaskRetryRequest,
)
from app.modules.tasks.service import AsyncTaskRunService

router = APIRouter()


@router.get("/runs", response_model=PageResponse[AsyncTaskRunResponse])
async def list_task_runs(
    query: AsyncTaskRunQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AsyncTaskRunService(db)
    return await service.list_runs(
        keyword=query.keyword,
        task_name=query.task_name,
        queue_name=query.queue_name,
        business_type=query.business_type,
        status_code=query.status_code,
        include_analysis_runs=query.include_analysis_runs,
        page=query.page,
        page_size=query.page_size,
    )


@router.get("/runs/{task_run_id}", response_model=AsyncTaskRunResponse)
async def get_task_run(
    task_run_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AsyncTaskRunService(db)
    return await service.get_run(task_run_id)


@router.post("/runs/{task_run_id}/retry", response_model=AsyncTaskRunResponse)
async def retry_task_run(
    task_run_id: int,
    body: TaskRetryRequest | None = None,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AsyncTaskRunService(db)
    return await service.retry(task_run_id, reason=body.reason if body else None)


@router.post("/runs/recover-stale", response_model=TaskRecoverStaleResponse)
async def recover_stale_task_runs(
    stale_seconds: int = 1800,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = AsyncTaskRunService(db)
    return await service.recover_stale(stale_seconds=stale_seconds)
