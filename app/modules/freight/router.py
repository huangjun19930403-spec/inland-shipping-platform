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
    FreightBatchCreateRequest,
    FreightBatchDetailResponse,
    FreightBatchListQuery,
    FreightBatchResponse,
    FreightCandidateConfirmRequest,
    FreightCandidateBulkConfirmResponse,
    FreightCandidateRejectRequest,
    FreightCandidateResponse,
    FreightCandidateUpdateRequest,
    FreightContactReplaceRequest,
    FreightContactResponse,
    FreightDetailResponse,
    FreightListQuery,
    FreightManualCreateRequest,
    FreightNormalizationCleanResponse,
    FreightNormalizationQualityResponse,
    FreightNormalizationSuggestionListQuery,
    FreightNormalizationSuggestionResponse,
    FreightResponse,
    FreightStatusChangeRequest,
    FreightTagRelationResponse,
    FreightTagReplaceRequest,
    FreightTmsInboundCreateRequest,
    FreightTmsInboundDetailResponse,
    FreightTmsInboundListQuery,
    FreightTmsInboundResponse,
    FreightUpdateRequest,
    PageResponse,
)
from app.modules.freight.service import (
    FreightAttachmentService,
    FreightBatchTaskService,
    FreightCandidateService,
    FreightContactService,
    FreightNormalizationSuggestionService,
    FreightService,
    FreightTagService,
    FreightTmsInboundService,
)

router = APIRouter()


@router.get("/batches", response_model=PageResponse[FreightBatchResponse])
async def list_freight_batches(
    query: FreightBatchListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightBatchTaskService(db)
    return await service.list_items(keyword=query.keyword, status_code=query.status_code, page=query.page, page_size=query.page_size)


@router.post("/batches/wechat", response_model=FreightBatchResponse)
async def create_wechat_batch(
    body: FreightBatchCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = FreightBatchTaskService(db)
    return await service.create_wechat_batch(body, creator_id=getattr(current_user, "id", None))


@router.get("/batches/{batch_id}", response_model=FreightBatchDetailResponse)
async def get_freight_batch_detail(
    batch_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightBatchTaskService(db)
    return await service.get_detail(batch_id)


@router.post("/batches/{batch_id}/parse", response_model=FreightBatchDetailResponse)
async def parse_freight_batch(
    batch_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = FreightBatchTaskService(db)
    return await service.parse(batch_id, requested_by=getattr(current_user, "id", None))


@router.post("/batches/{batch_id}/candidates/bulk-confirm", response_model=FreightCandidateBulkConfirmResponse)
async def bulk_confirm_batch_candidates(
    batch_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = FreightCandidateService(db)
    return await service.bulk_confirm_batch(batch_id, operator_id=getattr(current_user, "id", None))


@router.get("/tms-inbounds", response_model=PageResponse[FreightTmsInboundResponse])
async def list_tms_inbounds(
    query: FreightTmsInboundListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightTmsInboundService(db)
    return await service.list_items(keyword=query.keyword, status_code=query.status_code, page=query.page, page_size=query.page_size)


@router.post("/tms-inbounds", response_model=FreightTmsInboundResponse)
async def create_tms_inbound(
    body: FreightTmsInboundCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightTmsInboundService(db)
    return await service.create(body)


@router.get("/tms-inbounds/{inbound_id}", response_model=FreightTmsInboundDetailResponse)
async def get_tms_inbound_detail(
    inbound_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightTmsInboundService(db)
    return await service.get_detail(inbound_id)


@router.post("/tms-inbounds/{inbound_id}/parse", response_model=FreightTmsInboundDetailResponse)
async def parse_tms_inbound(
    inbound_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = FreightTmsInboundService(db)
    return await service.parse(inbound_id, requested_by=getattr(current_user, "id", None))


@router.get("/candidates", response_model=PageResponse[FreightCandidateResponse])
async def list_candidates(
    keyword: str | None = None,
    status_code: str | None = None,
    source_type_code: str | None = None,
    page: int = 1,
    page_size: int = 20,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightCandidateService(db)
    return await service.list_items(
        keyword=keyword,
        status_code=status_code,
        source_type_code=source_type_code,
        page=page,
        page_size=page_size,
    )


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


@router.get("/normalization-suggestions", response_model=PageResponse[FreightNormalizationSuggestionResponse])
async def list_normalization_suggestions(
    query: FreightNormalizationSuggestionListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightNormalizationSuggestionService(db)
    return await service.list_items(
        keyword=query.keyword,
        status_code=query.status_code,
        suggestion_type_code=query.suggestion_type_code,
        page=query.page,
        page_size=query.page_size,
    )


@router.get("/normalization/quality", response_model=FreightNormalizationQualityResponse)
async def get_normalization_quality(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightNormalizationSuggestionService(db)
    return await service.quality()


@router.post("/normalization/clean", response_model=FreightNormalizationCleanResponse)
async def clean_freight_normalization(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = FreightNormalizationSuggestionService(db)
    return await service.clean(operator_id=getattr(current_user, "id", None))


@router.post("/normalization-suggestions/{suggestion_id}/apply", response_model=FreightNormalizationSuggestionResponse)
async def apply_normalization_suggestion(
    suggestion_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = FreightNormalizationSuggestionService(db)
    return await service.apply(suggestion_id, operator_id=getattr(current_user, "id", None))


@router.post("/normalization-suggestions/{suggestion_id}/reject", response_model=FreightNormalizationSuggestionResponse)
async def reject_normalization_suggestion(
    suggestion_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = FreightNormalizationSuggestionService(db)
    return await service.reject(suggestion_id, operator_id=getattr(current_user, "id", None))


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


@router.post("/manual", response_model=FreightResponse)
async def create_manual_freight(
    body: FreightManualCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = FreightService(db)
    return await service.create_manual_freight(body)


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
    return await service.replace_contacts(freight_id, [item.model_dump(exclude_none=True) for item in body.contacts])


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
