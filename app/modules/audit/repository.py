"""audit 模块 repository。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditRecord, AuditTask


class AuditTaskRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_task_by_id(self, task_id: int) -> AuditTask | None:
        return await self.db.scalar(select(AuditTask).where(AuditTask.id == task_id))

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
    ) -> tuple[list[AuditTask], int]:
        stmt = select(AuditTask)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    AuditTask.task_no.ilike(like_value),
                    AuditTask.biz_code.ilike(like_value),
                    AuditTask.audit_remark.ilike(like_value),
                )
            )
        if task_type:
            stmt = stmt.where(AuditTask.biz_type_code == task_type)
        if status_code:
            stmt = stmt.where(AuditTask.audit_status == status_code)
        if object_type:
            stmt = stmt.where(AuditTask.biz_code == object_type)
        if object_id is not None:
            stmt = stmt.where(AuditTask.biz_id == object_id)
        if assignee_user_id is not None:
            stmt = stmt.where(AuditTask.current_handler_id == assignee_user_id)

        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(AuditTask.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def create_task(self, data: dict[str, Any]) -> AuditTask:
        row = AuditTask(**data)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update_task(self, task_id: int, data: dict[str, Any]) -> AuditTask | None:
        row = await self.get_task_by_id(task_id)
        if row is None:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update_task_status(self, task_id: int, status_code: str) -> bool:
        row = await self.get_task_by_id(task_id)
        if row is None:
            return False
        row.audit_status = status_code
        await self.db.flush()
        return True

    async def assign_task(self, task_id: int, assignee_user_id: int) -> bool:
        row = await self.get_task_by_id(task_id)
        if row is None:
            return False
        row.current_handler_id = assignee_user_id
        await self.db.flush()
        return True

    async def get_pending_count(self, assignee_user_id: int | None = None) -> int:
        stmt = select(func.count(AuditTask.id)).where(AuditTask.audit_status == "PENDING")
        if assignee_user_id is not None:
            stmt = stmt.where(AuditTask.current_handler_id == assignee_user_id)
        return int((await self.db.execute(stmt)).scalar_one())


class AuditRecordRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_records(
        self,
        task_id: int,
        page: int,
        page_size: int,
    ) -> tuple[list[AuditRecord], int]:
        stmt = select(AuditRecord).where(AuditRecord.task_id == task_id)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(AuditRecord.id.asc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def create_record(self, data: dict[str, Any]) -> AuditRecord:
        payload = data.copy()
        payload.setdefault("created_at", datetime.utcnow())
        row = AuditRecord(**payload)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row
