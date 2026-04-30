"""audit 模块 repository。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditRecord, AuditTask, AuditTaskSnapshot


class AuditTaskRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_task_by_id(self, task_id: int) -> AuditTask | None:
        return await self.db.scalar(select(AuditTask).where(AuditTask.id == task_id))

    async def list_tasks(
        self,
        keyword: str | None,
        queue_type: str | None,
        task_type: str | None,
        status_code: str | None,
        object_type: str | None,
        object_type_code: str | None,
        object_id: int | None,
        submitter_id: int | None,
        assignee_user_id: int | None,
        current_handler_id: int | None,
        submitted_from: datetime | None,
        submitted_to: datetime | None,
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
                    AuditTask.object_code.ilike(like_value),
                    AuditTask.object_name.ilike(like_value),
                    AuditTask.audit_remark.ilike(like_value),
                )
            )
        if queue_type:
            queue = queue_type.upper()
            if queue == "PENDING":
                stmt = stmt.where(AuditTask.audit_status == "PENDING")
            elif queue == "DONE":
                stmt = stmt.where(AuditTask.audit_status.in_(("APPROVED", "REJECTED", "CANCELED")))
        if task_type:
            stmt = stmt.where(AuditTask.biz_type_code == task_type)
        if status_code:
            stmt = stmt.where(AuditTask.audit_status == status_code)
        object_type_value = object_type_code or object_type
        if object_type_value:
            stmt = stmt.where(
                or_(
                    AuditTask.object_type_code == object_type_value,
                    AuditTask.biz_code == object_type_value,
                )
            )
        if object_id is not None:
            stmt = stmt.where(AuditTask.biz_id == object_id)
        if submitter_id is not None:
            stmt = stmt.where(AuditTask.submitter_id == submitter_id)
        handler_id = current_handler_id if current_handler_id is not None else assignee_user_id
        if handler_id is not None:
            stmt = stmt.where(AuditTask.current_handler_id == handler_id)
        if submitted_from is not None:
            stmt = stmt.where(AuditTask.submitted_at >= submitted_from)
        if submitted_to is not None:
            stmt = stmt.where(AuditTask.submitted_at <= submitted_to)

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


class AuditTaskSnapshotRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_snapshot_by_task_id(self, task_id: int) -> AuditTaskSnapshot | None:
        return await self.db.scalar(
            select(AuditTaskSnapshot).where(AuditTaskSnapshot.task_id == task_id)
        )

    async def upsert_snapshot(self, task_id: int, data: dict[str, Any]) -> AuditTaskSnapshot:
        now = datetime.utcnow()
        row = await self.get_snapshot_by_task_id(task_id)
        payload = {
            "before_snapshot_json": data.get("before_snapshot_json"),
            "after_snapshot_json": data.get("after_snapshot_json"),
            "diff_json": data.get("diff_json"),
            "summary_json": data.get("summary_json"),
            "updated_at": now,
        }
        if row is None:
            row = AuditTaskSnapshot(
                task_id=task_id,
                created_at=now,
                **payload,
            )
            self.db.add(row)
        else:
            for key, value in payload.items():
                setattr(row, key, value)
        await self.db.flush()
        await self.db.refresh(row)
        return row


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
