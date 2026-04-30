"""freight 模块 repository。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.freight import (
    Freight,
    FreightAiParseTask,
    FreightCandidate,
    FreightCandidateFeedback,
    FreightClue,
    FreightContact,
    FreightSourceAttachment,
    FreightSourceInbound,
    FreightTagRelation,
)


class FreightRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_freight_by_id(self, freight_id: int) -> Freight | None:
        return await self.db.scalar(
            select(Freight).where(Freight.id == freight_id, Freight.deleted_at.is_(None))
        )

    async def list_freights(
        self,
        keyword: str | None,
        status_code: str | None,
        source_type: str | None,
        source_channel: str | None,
        origin_city_code: str | None,
        destination_city_code: str | None,
        commodity_id: int | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Freight], int]:
        stmt = select(Freight).where(Freight.deleted_at.is_(None))
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    Freight.freight_no.ilike(like_value),
                    Freight.cargo_title.ilike(like_value),
                    Freight.cargo_description.ilike(like_value),
                    Freight.publisher_org_name.ilike(like_value),
                    Freight.source_ref_no.ilike(like_value),
                )
            )
        if status_code:
            stmt = stmt.where(Freight.status_code == status_code)
        if source_type:
            stmt = stmt.where(Freight.source_type_code == source_type)
        if source_channel:
            stmt = stmt.where(Freight.source_channel_code == source_channel)
        if origin_city_code:
            stmt = stmt.where(Freight.origin_city_code == origin_city_code)
        if destination_city_code:
            stmt = stmt.where(Freight.destination_city_code == destination_city_code)
        if commodity_id is not None:
            stmt = stmt.where(Freight.commodity_standard_id == commodity_id)

        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(Freight.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def create_freight(self, data: dict[str, Any]) -> Freight:
        row = Freight(**data)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update_freight(self, freight_id: int, data: dict[str, Any]) -> Freight | None:
        row = await self.get_freight_by_id(freight_id)
        if row is None:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update_freight_status(self, freight_id: int, status_code: str) -> bool:
        row = await self.get_freight_by_id(freight_id)
        if row is None:
            return False
        row.status_code = status_code
        await self.db.flush()
        return True

    async def exists_freight_reference(
        self,
        source_type: str | None = None,
        source_ref_no: str | None = None,
        exclude_freight_id: int | None = None,
    ) -> bool:
        stmt = select(Freight).where(Freight.deleted_at.is_(None))
        if source_type:
            stmt = stmt.where(Freight.source_type_code == source_type)
        if source_ref_no:
            stmt = stmt.where(Freight.source_ref_no == source_ref_no)
        if exclude_freight_id is not None:
            stmt = stmt.where(Freight.id != exclude_freight_id)
        if source_type is None and source_ref_no is None:
            return False
        return await self.db.scalar(stmt) is not None

    async def exists_freight_no(self, freight_no: str, exclude_freight_id: int | None = None) -> bool:
        stmt = select(Freight).where(
            Freight.freight_no == freight_no,
            Freight.deleted_at.is_(None),
        )
        if exclude_freight_id is not None:
            stmt = stmt.where(Freight.id != exclude_freight_id)
        return await self.db.scalar(stmt) is not None


class FreightSourceInboundRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, inbound_id: int) -> FreightSourceInbound | None:
        return await self.db.scalar(select(FreightSourceInbound).where(FreightSourceInbound.id == inbound_id))

    async def list_items(
        self,
        *,
        keyword: str | None,
        status_code: str | None,
        source_channel_code: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[FreightSourceInbound], int]:
        stmt = select(FreightSourceInbound)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    FreightSourceInbound.inbound_no.ilike(like_value),
                    FreightSourceInbound.external_ref_no.ilike(like_value),
                    FreightSourceInbound.sender_name.ilike(like_value),
                    FreightSourceInbound.raw_title.ilike(like_value),
                    FreightSourceInbound.raw_content.ilike(like_value),
                )
            )
        if status_code:
            stmt = stmt.where(FreightSourceInbound.status_code == status_code)
        if source_channel_code:
            stmt = stmt.where(FreightSourceInbound.source_channel_code == source_channel_code)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(FreightSourceInbound.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def create(self, data: dict[str, Any]) -> FreightSourceInbound:
        row = FreightSourceInbound(**data)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update(self, inbound_id: int, data: dict[str, Any]) -> FreightSourceInbound | None:
        row = await self.get_by_id(inbound_id)
        if row is None:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.db.flush()
        await self.db.refresh(row)
        return row


class FreightAiParseTaskRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, task_id: int) -> FreightAiParseTask | None:
        return await self.db.scalar(select(FreightAiParseTask).where(FreightAiParseTask.id == task_id))

    async def list_items(
        self,
        *,
        keyword: str | None,
        status_code: str | None,
        source_channel_code: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[FreightAiParseTask], int]:
        stmt = select(FreightAiParseTask)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    FreightAiParseTask.task_no.ilike(like_value),
                    FreightAiParseTask.raw_content.ilike(like_value),
                    FreightAiParseTask.error_message.ilike(like_value),
                )
            )
        if status_code:
            stmt = stmt.where(FreightAiParseTask.status_code == status_code)
        if source_channel_code:
            stmt = stmt.where(FreightAiParseTask.source_channel_code == source_channel_code)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(FreightAiParseTask.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def create(self, data: dict[str, Any]) -> FreightAiParseTask:
        row = FreightAiParseTask(**data)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update(self, task_id: int, data: dict[str, Any]) -> FreightAiParseTask | None:
        row = await self.get_by_id(task_id)
        if row is None:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.db.flush()
        await self.db.refresh(row)
        return row


class FreightClueRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_by_task(self, task_id: int) -> list[FreightClue]:
        rows = (
            await self.db.execute(
                select(FreightClue)
                .where(FreightClue.parse_task_id == task_id)
                .order_by(FreightClue.segment_index.asc(), FreightClue.id.asc())
            )
        ).scalars().all()
        return list(rows)

    async def create(self, data: dict[str, Any]) -> FreightClue:
        row = FreightClue(**data)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row


class FreightCandidateRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_id(self, candidate_id: int) -> FreightCandidate | None:
        return await self.db.scalar(select(FreightCandidate).where(FreightCandidate.id == candidate_id))

    async def list_by_task(self, task_id: int) -> list[FreightCandidate]:
        rows = (
            await self.db.execute(
                select(FreightCandidate)
                .where(FreightCandidate.parse_task_id == task_id)
                .order_by(FreightCandidate.id.asc())
            )
        ).scalars().all()
        return list(rows)

    async def list_items(
        self,
        *,
        keyword: str | None,
        status_code: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[FreightCandidate], int]:
        stmt = select(FreightCandidate)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    FreightCandidate.candidate_no.ilike(like_value),
                    FreightCandidate.cargo_title.ilike(like_value),
                    FreightCandidate.origin_text.ilike(like_value),
                    FreightCandidate.destination_text.ilike(like_value),
                    FreightCandidate.commodity_match_name.ilike(like_value),
                    FreightCandidate.contact_phone.ilike(like_value),
                )
            )
        if status_code:
            stmt = stmt.where(FreightCandidate.status_code == status_code)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(FreightCandidate.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def create(self, data: dict[str, Any]) -> FreightCandidate:
        row = FreightCandidate(**data)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update(self, candidate_id: int, data: dict[str, Any]) -> FreightCandidate | None:
        row = await self.get_by_id(candidate_id)
        if row is None:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.db.flush()
        await self.db.refresh(row)
        return row


class FreightCandidateFeedbackRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, data: dict[str, Any]) -> FreightCandidateFeedback:
        row = FreightCandidateFeedback(**data)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def list_by_candidate_ids(self, candidate_ids: list[int]) -> list[FreightCandidateFeedback]:
        if not candidate_ids:
            return []
        rows = (
            await self.db.execute(
                select(FreightCandidateFeedback)
                .where(FreightCandidateFeedback.candidate_id.in_(candidate_ids))
                .order_by(FreightCandidateFeedback.operated_at.desc(), FreightCandidateFeedback.id.desc())
            )
        ).scalars().all()
        return list(rows)


class FreightContactRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_contacts(self, freight_id: int) -> list[FreightContact]:
        rows = (
            await self.db.execute(
                select(FreightContact)
                .where(FreightContact.freight_id == freight_id)
                .order_by(FreightContact.is_primary.desc(), FreightContact.id.asc())
            )
        ).scalars().all()
        return list(rows)

    async def replace_contacts(
        self,
        freight_id: int,
        contacts: list[dict[str, Any]],
    ) -> list[FreightContact]:
        await self.db.execute(delete(FreightContact).where(FreightContact.freight_id == freight_id))
        rows: list[FreightContact] = []
        for item in contacts:
            row = FreightContact(freight_id=freight_id, **item)
            self.db.add(row)
            rows.append(row)
        await self.db.flush()
        return rows

    async def create_contact(self, freight_id: int, data: dict[str, Any]) -> FreightContact:
        row = FreightContact(freight_id=freight_id, **data)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row


class FreightAttachmentRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_attachments(self, freight_id: int) -> list[FreightSourceAttachment]:
        rows = (
            await self.db.execute(
                select(FreightSourceAttachment)
                .where(FreightSourceAttachment.freight_id == freight_id)
                .order_by(FreightSourceAttachment.id.desc())
            )
        ).scalars().all()
        return list(rows)

    async def get_attachment(self, attachment_id: int) -> FreightSourceAttachment | None:
        return await self.db.scalar(
            select(FreightSourceAttachment).where(FreightSourceAttachment.id == attachment_id)
        )

    async def create_attachment(
        self,
        freight_id: int,
        data: dict[str, Any],
    ) -> FreightSourceAttachment:
        row = FreightSourceAttachment(freight_id=freight_id, created_at=datetime.utcnow(), **data)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update_attachment(
        self,
        attachment_id: int,
        data: dict[str, Any],
    ) -> FreightSourceAttachment | None:
        row = await self.get_attachment(attachment_id)
        if row is None:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def delete_attachment(self, attachment_id: int) -> bool:
        row = await self.get_attachment(attachment_id)
        if row is None:
            return False
        await self.db.delete(row)
        await self.db.flush()
        return True


class FreightTagRelationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_tag_relations(self, freight_id: int) -> list[FreightTagRelation]:
        rows = (
            await self.db.execute(
                select(FreightTagRelation)
                .where(FreightTagRelation.freight_id == freight_id)
                .order_by(FreightTagRelation.id.asc())
            )
        ).scalars().all()
        return list(rows)

    async def replace_tag_relations(
        self,
        freight_id: int,
        tags: list[str],
    ) -> list[FreightTagRelation]:
        await self.db.execute(delete(FreightTagRelation).where(FreightTagRelation.freight_id == freight_id))
        rows: list[FreightTagRelation] = []
        now = datetime.utcnow()
        for tag in tags:
            tag_code = tag.strip()
            if not tag_code:
                continue
            row = FreightTagRelation(freight_id=freight_id, tag_code=tag_code, created_at=now)
            self.db.add(row)
            rows.append(row)
        await self.db.flush()
        return rows
