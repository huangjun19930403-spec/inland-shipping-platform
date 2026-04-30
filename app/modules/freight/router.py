"""freight 模块 router。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.modules.freight.schemas import (
    FreightAiParseTaskCreateRequest,
    FreightAiParseTaskDetailResponse,
    FreightAiParseTaskListQuery,
    FreightAiParseTaskResponse,
    FreightAttachmentCreateRequest,
    FreightAttachmentResponse,
    FreightAttachmentUpdateRequest,
    FreightCandidateConfirmRequest,
    FreightCandidateRejectRequest,
    FreightCandidateResponse,
    FreightCandidateUpdateRequest,
    FreightContactReplaceRequest,
    FreightContactResponse,
    FreightCreateRequest,
    FreightDetailResponse,
    FreightListQuery,
    FreightResponse,
    FreightSourceInboundCreateRequest,
    FreightSourceInboundListQuery,
    FreightSourceInboundResponse,
    FreightStatusChangeRequest,
    FreightTagRelationResponse,
    FreightTagReplaceRequest,
    FreightUpdateRequest,
    PageResponse,
)
from app.modules.freight.service import (
    FreightAiParseTaskService,
    FreightAttachmentService,
    FreightCandidateService,
    FreightContactService,
    FreightService,
    FreightSourceInboundService,
    FreightTagService,
)

router = APIRouter()


@router.get("/source-inbounds", response_model=PageResponse[FreightSourceInboundResponse])
async def list_source_inbounds(
    query: FreightSourceInboundListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightSourceInboundService(db)
    return await service.list_items(
        keyword=query.keyword,
        status_code=query.status_code,
        source_channel_code=query.source_channel_code,
        page=query.page,
        page_size=query.page_size,
    )


@router.post("/source-inbounds", response_model=FreightSourceInboundResponse)
async def create_source_inbound(
    body: FreightSourceInboundCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightSourceInboundService(db)
    return await service.create(body)


@router.get("/source-inbounds/{inbound_id}", response_model=FreightSourceInboundResponse)
async def get_source_inbound(
    inbound_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightSourceInboundService(db)
    return await service.get(inbound_id)


@router.get("/ai/parse-tasks", response_model=PageResponse[FreightAiParseTaskResponse])
async def list_ai_parse_tasks(
    query: FreightAiParseTaskListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightAiParseTaskService(db)
    return await service.list_items(
        keyword=query.keyword,
        status_code=query.status_code,
        source_channel_code=query.source_channel_code,
        page=query.page,
        page_size=query.page_size,
    )


@router.post("/ai/parse-tasks", response_model=FreightAiParseTaskResponse)
async def create_ai_parse_task(
    body: FreightAiParseTaskCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = FreightAiParseTaskService(db)
    return await service.create(body, requested_by=getattr(current_user, "id", None))


@router.get("/ai/parse-tasks/{task_id}", response_model=FreightAiParseTaskDetailResponse)
async def get_ai_parse_task_detail(
    task_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightAiParseTaskService(db)
    return await service.get_detail(task_id)


@router.post("/ai/parse-tasks/{task_id}/run", response_model=FreightAiParseTaskDetailResponse)
async def run_ai_parse_task(
    task_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = FreightAiParseTaskService(db)
    return await service.run(task_id, requested_by=getattr(current_user, "id", None))


@router.get("/candidates", response_model=PageResponse[FreightCandidateResponse])
async def list_candidates(
    keyword: str | None = None,
    status_code: str | None = None,
    page: int = 1,
    page_size: int = 20,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightCandidateService(db)
    return await service.list_items(keyword=keyword, status_code=status_code, page=page, page_size=page_size)


@router.get("/candidates/{candidate_id}", response_model=FreightCandidateResponse)
async def get_candidate(
    candidate_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightCandidateService(db)
    return await service.get(candidate_id)


@router.put("/candidates/{candidate_id}", response_model=FreightCandidateResponse)
async def update_candidate(
    candidate_id: int,
    body: FreightCandidateUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightCandidateService(db)
    return await service.update(candidate_id, body)


@router.post("/candidates/{candidate_id}/confirm", response_model=FreightResponse)
async def confirm_candidate(
    candidate_id: int,
    body: FreightCandidateConfirmRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = FreightCandidateService(db)
    return await service.confirm(candidate_id, body, operator_id=getattr(current_user, "id", None))


@router.post("/candidates/{candidate_id}/reject", response_model=FreightCandidateResponse)
async def reject_candidate(
    candidate_id: int,
    body: FreightCandidateRejectRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = FreightCandidateService(db)
    return await service.reject(candidate_id, body, operator_id=getattr(current_user, "id", None))


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


@router.post("", response_model=FreightResponse)
async def create_freight(
    body: FreightCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightService(db)
    return await service.create_freight(body)


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


@router.get("/{freight_id}", response_model=FreightDetailResponse)
async def get_freight_detail(
    freight_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightService(db)
    return await service.get_freight_detail(freight_id)


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
