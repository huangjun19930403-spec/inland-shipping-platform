"""
审核数据访问层
包含：AuditRecord（历史日志）+ AuditTask（任务工单）
"""
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import select, and_, desc, func

from app.models.audit import AuditRecord, AuditTask
from app.repositories.base import BaseRepository


class AuditRepository(BaseRepository):
    model_class = AuditRecord

    # ─────────────────────────────────────────────────
    # AuditRecord — 审核历史日志（只增不改）
    # ─────────────────────────────────────────────────

    async def create_record(self, record: AuditRecord) -> AuditRecord:
        return await self.create(record)

    async def get_record(self, record_id: int) -> Optional[AuditRecord]:
        return await self.get_by_id(record_id)

    async def list_records(
        self,
        status: Optional[str] = None,
        target_type: Optional[str] = None,
        submitter_id: Optional[int] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[AuditRecord], int]:
        filters = []
        if status:
            filters.append(AuditRecord.audit_result == status)
        if target_type:
            filters.append(AuditRecord.target_type == target_type)
        if submitter_id:
            filters.append(AuditRecord.submitter_id == submitter_id)

        query = select(AuditRecord)
        if filters:
            query = query.where(and_(*filters))

        total_result = await self._db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = total_result.scalar_one()

        result = await self._db.execute(
            query.order_by(desc(AuditRecord.created_at))
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all(), total

    async def get_pending_record_by_target(
        self, target_type: str, target_id: int
    ) -> Optional[AuditRecord]:
        result = await self._db.execute(
            select(AuditRecord).where(
                and_(
                    AuditRecord.target_type == target_type,
                    AuditRecord.target_id == target_id,
                    AuditRecord.audit_result == "PENDING",
                )
            )
        )
        return result.scalar_one_or_none()

    # ─────────────────────────────────────────────────
    # AuditTask — 审核任务工单（待办工作台）
    # ─────────────────────────────────────────────────

    async def create_task(self, task: AuditTask) -> AuditTask:
        self._db.add(task)
        await self._db.flush()
        await self._db.refresh(task)
        return task

    async def get_task(self, task_id: int) -> Optional[AuditTask]:
        result = await self._db.execute(
            select(AuditTask).where(AuditTask.id == task_id)
        )
        return result.scalar_one_or_none()

    async def get_pending_task_by_target(
        self, target_type: str, target_id: int
    ) -> Optional[AuditTask]:
        """查询某对象当前处于 pending 状态的任务"""
        result = await self._db.execute(
            select(AuditTask).where(
                and_(
                    AuditTask.target_type == target_type,
                    AuditTask.target_id == target_id,
                    AuditTask.status == "pending",
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_tasks(
        self,
        status: Optional[str] = None,
        target_type: Optional[str] = None,
        submitter_id: Optional[int] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[AuditTask], int]:
        filters = []
        if status:
            filters.append(AuditTask.status == status)
        if target_type:
            filters.append(AuditTask.target_type == target_type)
        if submitter_id:
            filters.append(AuditTask.submitter_id == submitter_id)

        query = select(AuditTask)
        if filters:
            query = query.where(and_(*filters))

        total_result = await self._db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = total_result.scalar_one()

        result = await self._db.execute(
            query.order_by(desc(AuditTask.submit_time))
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all(), total

    async def approve_task(
        self, task_id: int, auditor_id: int, remark: Optional[str] = None
    ) -> Optional[AuditTask]:
        task = await self.get_task(task_id)
        if task:
            task.status = "approved"
            task.auditor_id = auditor_id
            task.audit_time = datetime.now()
            if remark:
                task.remark = remark
            await self._db.flush()
            await self._db.refresh(task)
        return task

    async def reject_task(
        self, task_id: int, auditor_id: int, remark: str
    ) -> Optional[AuditTask]:
        task = await self.get_task(task_id)
        if task:
            task.status = "rejected"
            task.auditor_id = auditor_id
            task.audit_time = datetime.now()
            task.remark = remark
            await self._db.flush()
            await self._db.refresh(task)
        return task

    async def count_pending_by_type(self) -> dict:
        """统计各类型待审数量"""
        result = await self._db.execute(
            select(AuditTask.target_type, func.count(AuditTask.id))
            .where(AuditTask.status == "pending")
            .group_by(AuditTask.target_type)
        )
        return {row[0]: row[1] for row in result.all()}
