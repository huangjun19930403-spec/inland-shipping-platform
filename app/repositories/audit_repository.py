"""
审计数据访问层
"""
from typing import Optional, Sequence

from sqlalchemy import select, and_, desc

from app.models.audit import AuditRecord
from app.repositories.base import BaseRepository


class AuditRepository(BaseRepository):
    model_class = AuditRecord

    async def create_record(self, record: AuditRecord) -> AuditRecord:
        return await self.create(record)

    async def get_record(self, record_id: int) -> Optional[AuditRecord]:
        return await self.get_by_id(record_id)

    async def list_records(
        self,
        status: Optional[str] = None,
        target_type: Optional[str] = None,
        operator_id: Optional[int] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[AuditRecord], int]:
        filters = []
        if status:
            filters.append(AuditRecord.audit_status == status)
        if target_type:
            filters.append(AuditRecord.target_type == target_type)
        if operator_id:
            filters.append(AuditRecord.operator_id == operator_id)

        query = select(AuditRecord)
        if filters:
            query = query.where(and_(*filters))

        from sqlalchemy import func
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

    async def get_pending_by_target(
        self, target_type: str, target_id: int
    ) -> Optional[AuditRecord]:
        result = await self._db.execute(
            select(AuditRecord).where(
                and_(
                    AuditRecord.target_type == target_type,
                    AuditRecord.target_id == target_id,
                    AuditRecord.audit_status == "PENDING",
                )
            )
        )
        return result.scalar_one_or_none()

    async def approve_record(
        self, record_id: int, auditor_id: int, comment: Optional[str] = None
    ) -> Optional[AuditRecord]:
        record = await self.get_by_id(record_id)
        if record:
            record.audit_status = "APPROVED"
            record.auditor_id = auditor_id
            if comment:
                record.audit_comment = comment
            await self._db.flush()
        return record

    async def reject_record(
        self, record_id: int, auditor_id: int, reason: str
    ) -> Optional[AuditRecord]:
        record = await self.get_by_id(record_id)
        if record:
            record.audit_status = "REJECTED"
            record.auditor_id = auditor_id
            record.audit_comment = reason
            await self._db.flush()
        return record
