"""后台任务运行账本 repository。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import AnalysisJobRun
from app.models.task import AsyncTaskRun


ACTIVE_STATUSES = {"QUEUED", "STARTED", "RUNNING", "RETRYING"}


class AsyncTaskRunRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, task_run_id: int) -> AsyncTaskRun | None:
        return await self.db.scalar(select(AsyncTaskRun).where(AsyncTaskRun.id == task_run_id))

    async def get_active_by_idempotency_key(self, idempotency_key: str) -> AsyncTaskRun | None:
        return await self.db.scalar(
            select(AsyncTaskRun)
            .where(
                AsyncTaskRun.idempotency_key == idempotency_key,
                AsyncTaskRun.status_code.in_(ACTIVE_STATUSES),
            )
            .order_by(AsyncTaskRun.id.desc())
        )

    async def create(self, data: dict[str, Any]) -> AsyncTaskRun:
        row = AsyncTaskRun(**data)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update(self, task_run_id: int, data: dict[str, Any]) -> AsyncTaskRun | None:
        row = await self.get_by_id(task_run_id)
        if row is None:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def list_items(
        self,
        *,
        keyword: str | None,
        task_name: str | None,
        queue_name: str | None,
        business_type: str | None,
        status_code: str | None,
        limit: int,
    ) -> list[AsyncTaskRun]:
        stmt = select(AsyncTaskRun)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    AsyncTaskRun.task_title.ilike(like_value),
                    AsyncTaskRun.task_name.ilike(like_value),
                    AsyncTaskRun.business_no.ilike(like_value),
                    AsyncTaskRun.celery_task_id.ilike(like_value),
                    AsyncTaskRun.error_message.ilike(like_value),
                )
            )
        if task_name:
            stmt = stmt.where(AsyncTaskRun.task_name == task_name)
        if queue_name:
            stmt = stmt.where(AsyncTaskRun.queue_name == queue_name)
        if business_type:
            stmt = stmt.where(AsyncTaskRun.business_type == business_type)
        if status_code:
            stmt = stmt.where(AsyncTaskRun.status_code == status_code)
        rows = (
            await self.db.execute(
                stmt.order_by(AsyncTaskRun.created_at.desc(), AsyncTaskRun.id.desc()).limit(limit)
            )
        ).scalars().all()
        return list(rows)

    async def count_items(
        self,
        *,
        keyword: str | None,
        task_name: str | None,
        queue_name: str | None,
        business_type: str | None,
        status_code: str | None,
    ) -> int:
        stmt = select(AsyncTaskRun)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    AsyncTaskRun.task_title.ilike(like_value),
                    AsyncTaskRun.task_name.ilike(like_value),
                    AsyncTaskRun.business_no.ilike(like_value),
                    AsyncTaskRun.celery_task_id.ilike(like_value),
                    AsyncTaskRun.error_message.ilike(like_value),
                )
            )
        if task_name:
            stmt = stmt.where(AsyncTaskRun.task_name == task_name)
        if queue_name:
            stmt = stmt.where(AsyncTaskRun.queue_name == queue_name)
        if business_type:
            stmt = stmt.where(AsyncTaskRun.business_type == business_type)
        if status_code:
            stmt = stmt.where(AsyncTaskRun.status_code == status_code)
        return int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())

    async def list_stale(self, *, stale_seconds: int) -> list[AsyncTaskRun]:
        cutoff = datetime.utcnow() - timedelta(seconds=max(30, stale_seconds))
        rows = (
            await self.db.execute(
                select(AsyncTaskRun)
                .where(
                    AsyncTaskRun.status_code.in_(ACTIVE_STATUSES),
                    AsyncTaskRun.heartbeat_at.is_not(None),
                    AsyncTaskRun.heartbeat_at < cutoff,
                )
                .order_by(AsyncTaskRun.heartbeat_at.asc())
            )
        ).scalars().all()
        return list(rows)


class AnalysisJobRunAdapterRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_items(
        self,
        *,
        keyword: str | None,
        status_code: str | None,
        limit: int,
    ) -> list[AnalysisJobRun]:
        stmt = select(AnalysisJobRun)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    AnalysisJobRun.job_code.ilike(like_value),
                    AnalysisJobRun.job_name.ilike(like_value),
                    AnalysisJobRun.module_name.ilike(like_value),
                    AnalysisJobRun.celery_task_id.ilike(like_value),
                    AnalysisJobRun.error_message.ilike(like_value),
                )
            )
        if status_code:
            stmt = stmt.where(AnalysisJobRun.status_code == status_code)
        rows = (
            await self.db.execute(
                stmt.order_by(AnalysisJobRun.created_at.desc(), AnalysisJobRun.id.desc()).limit(limit)
            )
        ).scalars().all()
        return list(rows)

    async def count_items(self, *, keyword: str | None, status_code: str | None) -> int:
        stmt = select(AnalysisJobRun)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    AnalysisJobRun.job_code.ilike(like_value),
                    AnalysisJobRun.job_name.ilike(like_value),
                    AnalysisJobRun.module_name.ilike(like_value),
                    AnalysisJobRun.celery_task_id.ilike(like_value),
                    AnalysisJobRun.error_message.ilike(like_value),
                )
            )
        if status_code:
            stmt = stmt.where(AnalysisJobRun.status_code == status_code)
        return int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
