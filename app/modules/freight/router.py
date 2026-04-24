"""freight 模块 router。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.modules.freight.schemas import (
    FreightAttachmentCreateRequest,
    FreightAttachmentResponse,
    FreightAttachmentUpdateRequest,
    FreightContactReplaceRequest,
    FreightContactResponse,
    FreightCreateRequest,
    FreightDetailResponse,
    FreightListQuery,
    FreightResponse,
    FreightStatusChangeRequest,
    FreightTagRelationResponse,
    FreightTagReplaceRequest,
    FreightUpdateRequest,
    PageResponse,
)
from app.modules.freight.service import (
    FreightAttachmentService,
    FreightContactService,
    FreightService,
    FreightTagService,
)

router = APIRouter()


@router.get("", response_model=PageResponse[FreightResponse])
async def list_freights(
    query: FreightListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightService(db)
    return await service.list_freights(
        keyword=query.keyword,
        status_code=query.status_code,
        source_type=query.source_type,
        source_channel=query.source_channel,
        origin_city_code=query.origin_city_code,
        destination_city_code=query.destination_city_code,
        commodity_id=query.commodity_id,
        page=query.page,
        page_size=query.page_size,
    )


@router.get("/{freight_id}", response_model=FreightDetailResponse)
async def get_freight_detail(
    freight_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightService(db)
    return await service.get_freight_detail(freight_id)


@router.post("", response_model=FreightResponse)
async def create_freight(
    body: FreightCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightService(db)
    return await service.create_freight(body)


@router.put("/{freight_id}", response_model=FreightResponse)
async def update_freight(
    freight_id: int,
    body: FreightUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightService(db)
    return await service.update_freight(freight_id, body)


@router.put("/{freight_id}/status")
async def change_freight_status(
    freight_id: int,
    body: FreightStatusChangeRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightService(db)
    await service.change_freight_status(freight_id, body.status_code)
    return {"ok": True}


@router.put("/{freight_id}/contacts", response_model=list[FreightContactResponse])
async def replace_freight_contacts(
    freight_id: int,
    body: FreightContactReplaceRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightContactService(db)
    return await service.replace_contacts(
        freight_id,
        [item.model_dump(exclude_none=True) for item in body.contacts],
    )


@router.get("/{freight_id}/attachments", response_model=list[FreightAttachmentResponse])
async def list_freight_attachments(
    freight_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightAttachmentService(db)
    return await service.list_attachments(freight_id)


@router.post("/{freight_id}/attachments", response_model=FreightAttachmentResponse)
async def create_freight_attachment(
    freight_id: int,
    body: FreightAttachmentCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightAttachmentService(db)
    return await service.create_attachment(freight_id, body)


@router.put("/attachments/{attachment_id}", response_model=FreightAttachmentResponse)
async def update_freight_attachment(
    attachment_id: int,
    body: FreightAttachmentUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightAttachmentService(db)
    return await service.update_attachment(attachment_id, body)


@router.delete("/attachments/{attachment_id}")
async def delete_freight_attachment(
    attachment_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightAttachmentService(db)
    await service.delete_attachment(attachment_id)
    return {"ok": True}


@router.get("/{freight_id}/tags", response_model=list[FreightTagRelationResponse])
async def list_freight_tags(
    freight_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightTagService(db)
    return await service.list_tag_relations(freight_id)


@router.put("/{freight_id}/tags", response_model=list[FreightTagRelationResponse])
async def replace_freight_tags(
    freight_id: int,
    body: FreightTagReplaceRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightTagService(db)
    return await service.replace_tag_relations(freight_id, body.tags)
