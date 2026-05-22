"""Business-facing approval client.

Business modules must use this client instead of writing approval tables
directly. The client deliberately exposes a narrow surface: submit approval and
read latest approval state for a subject.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.approval.repository import ApprovalRepository
from app.modules.approval.schemas import ApprovalInstanceResponse, ApprovalInstanceSubmitRequest
from app.modules.approval.service import ApprovalService


class ApprovalClient:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.service = ApprovalService(db)
        self.repo = ApprovalRepository(db)

    async def submit(
        self, payload: ApprovalInstanceSubmitRequest | dict, submitter_id: int | None = None
    ) -> ApprovalInstanceResponse:
        body = payload if isinstance(payload, ApprovalInstanceSubmitRequest) else ApprovalInstanceSubmitRequest(**payload)
        return await self.service.submit_instance(body, submitter_id)

    async def latest_state(
        self,
        *,
        subject_type: str,
        subject_id: int | None = None,
        subject_ref: str | None = None,
    ) -> ApprovalInstanceResponse | None:
        from sqlalchemy import select
        from app.models.approval import ApprovalInstance

        stmt = select(ApprovalInstance).where(ApprovalInstance.subject_type == subject_type)
        if subject_id is not None:
            stmt = stmt.where(ApprovalInstance.subject_id == subject_id)
        elif subject_ref is not None:
            stmt = stmt.where(ApprovalInstance.subject_ref == subject_ref)
        else:
            return None
        row = await self.db.scalar(stmt.order_by(ApprovalInstance.submitted_at.desc(), ApprovalInstance.id.desc()))
        return await self.service._to_instance_response(row) if row is not None else None

    async def latest_state_for_subjects(
        self, *, subject_type: str, subject_ids: list[int]
    ) -> dict[int, ApprovalInstanceResponse]:
        rows = await self.repo.latest_state_for_subjects(subject_type, subject_ids)
        return {subject_id: await self.service._to_instance_response(row) for subject_id, row in rows.items()}
