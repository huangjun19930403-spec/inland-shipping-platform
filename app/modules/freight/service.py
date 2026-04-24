"""freight 模块 service。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.modules.dictionary.service import CodeSequenceService
from app.modules.freight.repository import (
    FreightAttachmentRepository,
    FreightContactRepository,
    FreightRepository,
    FreightTagRelationRepository,
)
from app.modules.freight.schemas import (
    FreightAttachmentResponse,
    FreightContactResponse,
    FreightDetailResponse,
    FreightResponse,
    FreightTagRelationResponse,
    PageResponse,
)


def _to_freight_response(entity) -> FreightResponse:
    return FreightResponse(
        id=entity.id,
        freight_no=entity.freight_no,
        source_type_code=entity.source_type_code,
        cargo_title=entity.cargo_title,
        cargo_description=entity.cargo_description,
        commodity_standard_id=entity.commodity_standard_id,
        packaging_form_code=entity.packaging_form_code,
        estimated_tonnage=entity.estimated_tonnage,
        min_tonnage=entity.min_tonnage,
        max_tonnage=entity.max_tonnage,
        unit_price=entity.unit_price,
        total_price=entity.total_price,
        price_unit=entity.price_unit,
        settlement_method_code=entity.settlement_method_code,
        origin_node_id=entity.origin_node_id,
        destination_node_id=entity.destination_node_id,
        origin_province_code=entity.origin_province_code,
        origin_city_code=entity.origin_city_code,
        origin_district_code=entity.origin_district_code,
        destination_province_code=entity.destination_province_code,
        destination_city_code=entity.destination_city_code,
        destination_district_code=entity.destination_district_code,
        origin_region_id_cache=entity.origin_region_id_cache,
        destination_region_id_cache=entity.destination_region_id_cache,
        loading_time_from=entity.loading_time_from,
        loading_time_to=entity.loading_time_to,
        unloading_time_from=entity.unloading_time_from,
        unloading_time_to=entity.unloading_time_to,
        publisher_org_name=entity.publisher_org_name,
        status_code=entity.status_code,
        published_at=entity.published_at,
        expired_at=entity.expired_at,
        audit_status=entity.audit_status,
        submitter_id=entity.submitter_id,
        auditor_id=entity.auditor_id,
        audited_at=entity.audited_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_contact_response(entity) -> FreightContactResponse:
    return FreightContactResponse(
        id=entity.id,
        freight_id=entity.freight_id,
        contact_name=entity.contact_name,
        contact_role_code=entity.contact_role_code,
        mobile_phone=entity.mobile_phone,
        landline_phone=entity.landline_phone,
        wechat=entity.wechat,
        is_primary=entity.is_primary,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_attachment_response(entity) -> FreightAttachmentResponse:
    return FreightAttachmentResponse(
        id=entity.id,
        freight_id=entity.freight_id,
        storage_provider_code=entity.storage_provider_code,
        file_url=entity.file_url,
        file_name=entity.file_name,
        file_ext=entity.file_ext,
        file_size=entity.file_size,
        source_type_code=entity.source_type_code,
        uploaded_by=entity.uploaded_by,
        uploaded_at=entity.uploaded_at,
        created_at=entity.created_at,
    )


def _to_tag_response(entity) -> FreightTagRelationResponse:
    return FreightTagRelationResponse(
        id=entity.id,
        freight_id=entity.freight_id,
        tag_code=entity.tag_code,
        created_at=entity.created_at,
    )


class FreightService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = FreightRepository(db)
        self.contact_repo = FreightContactRepository(db)
        self.attachment_repo = FreightAttachmentRepository(db)
        self.tag_repo = FreightTagRelationRepository(db)
        self.sequence_service = CodeSequenceService(db)

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
    ) -> PageResponse[FreightResponse]:
        rows, total = await self.repo.list_freights(
            keyword=keyword,
            status_code=status_code,
            source_type=source_type,
            source_channel=source_channel,
            origin_city_code=origin_city_code,
            destination_city_code=destination_city_code,
            commodity_id=commodity_id,
            page=page,
            page_size=page_size,
        )
        return PageResponse[FreightResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_freight_response(item) for item in rows],
        )

    async def create_freight(self, payload) -> FreightResponse:
        data = payload.model_dump(exclude_none=True)
        freight_no = (payload.freight_no or "").strip()
        if not freight_no:
            freight_no = await self.sequence_service.next_code("FREIGHT_NO")
        data["freight_no"] = freight_no
        if await self.repo.exists_freight_no(freight_no):
            raise ConflictError(f"freight_no already exists: {freight_no}")
        row = await self.repo.create_freight(
            {
                **data,
                "cargo_title": payload.cargo_title.strip(),
            }
        )
        await self.db.commit()
        return _to_freight_response(row)

    async def update_freight(self, freight_id: int, payload) -> FreightResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        row = await self.repo.update_freight(freight_id, updates)
        if row is None:
            raise NotFoundError("Freight", freight_id)
        await self.db.commit()
        return _to_freight_response(row)

    async def get_freight_detail(self, freight_id: int) -> FreightDetailResponse:
        freight = await self.repo.get_freight_by_id(freight_id)
        if freight is None:
            raise NotFoundError("Freight", freight_id)
        contacts = await self.contact_repo.list_contacts(freight_id)
        attachments = await self.attachment_repo.list_attachments(freight_id)
        tags = await self.tag_repo.list_tag_relations(freight_id)
        return FreightDetailResponse(
            profile=_to_freight_response(freight),
            contacts=[_to_contact_response(item) for item in contacts],
            attachments=[_to_attachment_response(item) for item in attachments],
            tags=[_to_tag_response(item) for item in tags],
        )

    async def change_freight_status(self, freight_id: int, status_code: str) -> None:
        ok = await self.repo.update_freight_status(freight_id, status_code)
        if not ok:
            raise NotFoundError("Freight", freight_id)
        await self.db.commit()


class FreightContactService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.freight_repo = FreightRepository(db)
        self.repo = FreightContactRepository(db)

    async def replace_contacts(self, freight_id: int, contacts: list[dict]) -> list[FreightContactResponse]:
        freight = await self.freight_repo.get_freight_by_id(freight_id)
        if freight is None:
            raise NotFoundError("Freight", freight_id)
        rows = await self.repo.replace_contacts(freight_id, contacts)
        await self.db.commit()
        return [_to_contact_response(item) for item in rows]


class FreightAttachmentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.freight_repo = FreightRepository(db)
        self.repo = FreightAttachmentRepository(db)

    async def list_attachments(self, freight_id: int) -> list[FreightAttachmentResponse]:
        freight = await self.freight_repo.get_freight_by_id(freight_id)
        if freight is None:
            raise NotFoundError("Freight", freight_id)
        rows = await self.repo.list_attachments(freight_id)
        return [_to_attachment_response(item) for item in rows]

    async def create_attachment(self, freight_id: int, payload) -> FreightAttachmentResponse:
        freight = await self.freight_repo.get_freight_by_id(freight_id)
        if freight is None:
            raise NotFoundError("Freight", freight_id)
        row = await self.repo.create_attachment(freight_id, payload.model_dump(exclude_none=True))
        await self.db.commit()
        return _to_attachment_response(row)

    async def update_attachment(self, attachment_id: int, payload) -> FreightAttachmentResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        row = await self.repo.update_attachment(attachment_id, updates)
        if row is None:
            raise NotFoundError("FreightSourceAttachment", attachment_id)
        await self.db.commit()
        return _to_attachment_response(row)

    async def delete_attachment(self, attachment_id: int) -> None:
        ok = await self.repo.delete_attachment(attachment_id)
        if not ok:
            raise NotFoundError("FreightSourceAttachment", attachment_id)
        await self.db.commit()


class FreightTagService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.freight_repo = FreightRepository(db)
        self.repo = FreightTagRelationRepository(db)

    async def list_tag_relations(self, freight_id: int) -> list[FreightTagRelationResponse]:
        freight = await self.freight_repo.get_freight_by_id(freight_id)
        if freight is None:
            raise NotFoundError("Freight", freight_id)
        rows = await self.repo.list_tag_relations(freight_id)
        return [_to_tag_response(item) for item in rows]

    async def replace_tag_relations(self, freight_id: int, tags: list[str]) -> list[FreightTagRelationResponse]:
        freight = await self.freight_repo.get_freight_by_id(freight_id)
        if freight is None:
            raise NotFoundError("Freight", freight_id)
        rows = await self.repo.replace_tag_relations(freight_id, tags)
        await self.db.commit()
        return [_to_tag_response(item) for item in rows]
