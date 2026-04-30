"""freight 模块 service。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.integrations.ai import DashScopeQwenFreightParserClient
from app.models.address import AdminRegion, NodeAlias, Region, RegionCityRelation, TransportNode
from app.models.commodity import CommodityAlias, CommodityStandard
from app.models.dictionary import StdDict, StdDictItem
from app.models.freight import FreightCandidate
from app.modules.dictionary.service import CodeSequenceService
from app.modules.freight.repository import (
    FreightAiParseTaskRepository,
    FreightAttachmentRepository,
    FreightCandidateFeedbackRepository,
    FreightCandidateRepository,
    FreightClueRepository,
    FreightContactRepository,
    FreightRepository,
    FreightSourceInboundRepository,
    FreightTagRelationRepository,
)
from app.modules.freight.schemas import (
    FreightAiParseTaskDetailResponse,
    FreightAiParseTaskResponse,
    FreightAiTraceResponse,
    FreightAttachmentResponse,
    FreightCandidateResponse,
    FreightClueResponse,
    FreightConfirmationResponse,
    FreightContactResponse,
    FreightDetailResponse,
    FreightResponse,
    FreightSourceInboundResponse,
    FreightTagRelationResponse,
    PageResponse,
)
from app.modules.system.runtime_config import RuntimeConfigService


DISPLAY_DICT_CODES = [
    "SOURCE_TYPE",
    "SOURCE_CHANNEL",
    "FREIGHT_STATUS",
    "AUDIT_STATUS",
    "PACKAGING_FORM",
    "FREIGHT_INBOUND_STATUS",
    "AI_PARSE_STATUS",
    "FREIGHT_CLUE_STATUS",
    "FREIGHT_CANDIDATE_STATUS",
    "FREIGHT_CONFIRM_ACTION",
]


def _to_decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None


def _compact_json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _compact_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_compact_json_value(item) for item in value]
    return value


def _entity_snapshot(entity: Any, fields: list[str]) -> dict[str, Any]:
    return {field: _compact_json_value(getattr(entity, field, None)) for field in fields}


async def _load_display_context(
    db: AsyncSession,
    *,
    freights: list[Any] | None = None,
    candidates: list[Any] | None = None,
    inbounds: list[Any] | None = None,
    tasks: list[Any] | None = None,
    clues: list[Any] | None = None,
    feedback: list[Any] | None = None,
) -> dict[str, Any]:
    freights = freights or []
    candidates = candidates or []
    inbounds = inbounds or []
    tasks = tasks or []
    clues = clues or []
    feedback = feedback or []

    dict_rows = (
        await db.execute(
            select(StdDict.dict_code, StdDictItem.item_code, StdDictItem.item_name)
            .join(StdDictItem, StdDictItem.dict_id == StdDict.id)
            .where(StdDict.dict_code.in_(DISPLAY_DICT_CODES), StdDict.status == 1, StdDictItem.status == 1)
        )
    ).all()
    dict_labels: dict[str, dict[str, str]] = {}
    for dict_code, item_code, item_name in dict_rows:
        dict_labels.setdefault(dict_code, {})[item_code] = item_name

    commodity_ids = {
        item.commodity_standard_id
        for item in [*freights, *candidates]
        if getattr(item, "commodity_standard_id", None) is not None
    }
    commodities: dict[int, CommodityStandard] = {}
    if commodity_ids:
        rows = (await db.execute(select(CommodityStandard).where(CommodityStandard.id.in_(commodity_ids)))).scalars().all()
        commodities = {int(row.id): row for row in rows}

    node_ids = {
        node_id
        for item in [*freights, *candidates]
        for node_id in (getattr(item, "origin_node_id", None), getattr(item, "destination_node_id", None))
        if node_id is not None
    }
    nodes: dict[int, TransportNode] = {}
    if node_ids:
        rows = (await db.execute(select(TransportNode).where(TransportNode.id.in_(node_ids)))).scalars().all()
        nodes = {int(row.id): row for row in rows}

    city_codes = {
        code
        for item in [*freights, *candidates]
        for code in (getattr(item, "origin_city_code", None), getattr(item, "destination_city_code", None))
        if code
    }
    cities: dict[str, AdminRegion] = {}
    if city_codes:
        rows = (await db.execute(select(AdminRegion).where(AdminRegion.code.in_(city_codes)))).scalars().all()
        cities = {row.code: row for row in rows}

    region_ids = {
        region_id
        for item in [*freights, *candidates]
        for region_id in (
            getattr(item, "origin_region_id_cache", None),
            getattr(item, "destination_region_id_cache", None),
        )
        if region_id is not None
    }
    regions: dict[int, Region] = {}
    if region_ids:
        rows = (await db.execute(select(Region).where(Region.id.in_(region_ids)))).scalars().all()
        regions = {int(row.id): row for row in rows}

    return {
        "dict_labels": dict_labels,
        "commodities": commodities,
        "nodes": nodes,
        "cities": cities,
        "regions": regions,
    }


def _label(ctx: dict[str, Any], dict_code: str, item_code: str | None) -> str | None:
    if not item_code:
        return None
    return ctx.get("dict_labels", {}).get(dict_code, {}).get(item_code)


def _commodity(ctx: dict[str, Any], commodity_id: int | None) -> CommodityStandard | None:
    if commodity_id is None:
        return None
    return ctx.get("commodities", {}).get(int(commodity_id))


def _node_name(ctx: dict[str, Any], node_id: int | None) -> str | None:
    if node_id is None:
        return None
    node = ctx.get("nodes", {}).get(int(node_id))
    return node.name if node is not None else None


def _city_name(ctx: dict[str, Any], city_code: str | None) -> str | None:
    if not city_code:
        return None
    city = ctx.get("cities", {}).get(city_code)
    return city.name if city is not None else None


def _region_name(ctx: dict[str, Any], region_id: int | None) -> str | None:
    if region_id is None:
        return None
    region = ctx.get("regions", {}).get(int(region_id))
    return region.name if region is not None else None


def _to_freight_response(entity, ctx: dict[str, Any] | None = None) -> FreightResponse:
    ctx = ctx or {}
    commodity = _commodity(ctx, entity.commodity_standard_id)
    return FreightResponse(
        id=entity.id,
        freight_no=entity.freight_no,
        source_type_code=entity.source_type_code,
        source_type_name=_label(ctx, "SOURCE_TYPE", entity.source_type_code),
        source_channel_code=entity.source_channel_code,
        source_channel_name=_label(ctx, "SOURCE_CHANNEL", entity.source_channel_code),
        source_ref_no=entity.source_ref_no,
        source_candidate_id=entity.source_candidate_id,
        cargo_title=entity.cargo_title,
        cargo_description=entity.cargo_description,
        commodity_standard_id=entity.commodity_standard_id,
        commodity_standard_code=commodity.code if commodity is not None else None,
        commodity_standard_name=commodity.name if commodity is not None else None,
        packaging_form_code=entity.packaging_form_code,
        packaging_form_name=_label(ctx, "PACKAGING_FORM", entity.packaging_form_code),
        estimated_tonnage=entity.estimated_tonnage,
        min_tonnage=entity.min_tonnage,
        max_tonnage=entity.max_tonnage,
        unit_price=entity.unit_price,
        total_price=entity.total_price,
        price_unit=entity.price_unit,
        settlement_method_code=entity.settlement_method_code,
        settlement_method_name=None,
        origin_node_id=entity.origin_node_id,
        origin_node_name=_node_name(ctx, entity.origin_node_id),
        destination_node_id=entity.destination_node_id,
        destination_node_name=_node_name(ctx, entity.destination_node_id),
        origin_province_code=entity.origin_province_code,
        origin_city_code=entity.origin_city_code,
        origin_city_name=_city_name(ctx, entity.origin_city_code),
        origin_district_code=entity.origin_district_code,
        destination_province_code=entity.destination_province_code,
        destination_city_code=entity.destination_city_code,
        destination_city_name=_city_name(ctx, entity.destination_city_code),
        destination_district_code=entity.destination_district_code,
        origin_region_id_cache=entity.origin_region_id_cache,
        origin_region_name=_region_name(ctx, entity.origin_region_id_cache),
        destination_region_id_cache=entity.destination_region_id_cache,
        destination_region_name=_region_name(ctx, entity.destination_region_id_cache),
        loading_time_from=entity.loading_time_from,
        loading_time_to=entity.loading_time_to,
        unloading_time_from=entity.unloading_time_from,
        unloading_time_to=entity.unloading_time_to,
        publisher_org_name=entity.publisher_org_name,
        status_code=entity.status_code,
        status_name=_label(ctx, "FREIGHT_STATUS", entity.status_code),
        published_at=entity.published_at,
        expired_at=entity.expired_at,
        confirmed_at=entity.confirmed_at,
        confirmed_by=entity.confirmed_by,
        audit_status=entity.audit_status,
        audit_status_name=_label(ctx, "AUDIT_STATUS", entity.audit_status),
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


def _to_inbound_response(entity, ctx: dict[str, Any] | None = None) -> FreightSourceInboundResponse:
    ctx = ctx or {}
    return FreightSourceInboundResponse(
        id=entity.id,
        inbound_no=entity.inbound_no,
        source_type_code=entity.source_type_code,
        source_type_name=_label(ctx, "SOURCE_TYPE", entity.source_type_code),
        source_channel_code=entity.source_channel_code,
        source_channel_name=_label(ctx, "SOURCE_CHANNEL", entity.source_channel_code),
        external_ref_no=entity.external_ref_no,
        sender_name=entity.sender_name,
        sender_contact=entity.sender_contact,
        raw_title=entity.raw_title,
        raw_content=entity.raw_content,
        received_at=entity.received_at,
        status_code=entity.status_code,
        status_name=_label(ctx, "FREIGHT_INBOUND_STATUS", entity.status_code),
        parse_task_id=entity.parse_task_id,
        error_message=entity.error_message,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_task_response(entity, ctx: dict[str, Any] | None = None) -> FreightAiParseTaskResponse:
    ctx = ctx or {}
    return FreightAiParseTaskResponse(
        id=entity.id,
        task_no=entity.task_no,
        source_inbound_id=entity.source_inbound_id,
        source_type_code=entity.source_type_code,
        source_type_name=_label(ctx, "SOURCE_TYPE", entity.source_type_code),
        source_channel_code=entity.source_channel_code,
        source_channel_name=_label(ctx, "SOURCE_CHANNEL", entity.source_channel_code),
        raw_content=entity.raw_content,
        status_code=entity.status_code,
        status_name=_label(ctx, "AI_PARSE_STATUS", entity.status_code),
        ai_provider_code=entity.ai_provider_code,
        ai_model=entity.ai_model,
        prompt_version=entity.prompt_version,
        requested_by=entity.requested_by,
        started_at=entity.started_at,
        finished_at=entity.finished_at,
        error_message=entity.error_message,
        raw_response_json=entity.raw_response_json,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_clue_response(entity, ctx: dict[str, Any] | None = None) -> FreightClueResponse:
    ctx = ctx or {}
    return FreightClueResponse(
        id=entity.id,
        clue_no=entity.clue_no,
        parse_task_id=entity.parse_task_id,
        source_inbound_id=entity.source_inbound_id,
        segment_index=entity.segment_index,
        raw_text=entity.raw_text,
        status_code=entity.status_code,
        status_name=_label(ctx, "FREIGHT_CLUE_STATUS", entity.status_code),
        parse_result_json=entity.parse_result_json,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_candidate_response(entity, ctx: dict[str, Any] | None = None) -> FreightCandidateResponse:
    ctx = ctx or {}
    commodity = _commodity(ctx, entity.commodity_standard_id)
    return FreightCandidateResponse(
        id=entity.id,
        candidate_no=entity.candidate_no,
        parse_task_id=entity.parse_task_id,
        clue_id=entity.clue_id,
        source_inbound_id=entity.source_inbound_id,
        cargo_title=entity.cargo_title,
        cargo_description=entity.cargo_description,
        commodity_standard_id=entity.commodity_standard_id,
        commodity_standard_name=commodity.name if commodity is not None else None,
        commodity_match_name=entity.commodity_match_name,
        commodity_match_score=entity.commodity_match_score,
        packaging_form_code=entity.packaging_form_code,
        estimated_tonnage=entity.estimated_tonnage,
        min_tonnage=entity.min_tonnage,
        max_tonnage=entity.max_tonnage,
        unit_price=entity.unit_price,
        total_price=entity.total_price,
        price_unit=entity.price_unit,
        settlement_method_code=entity.settlement_method_code,
        origin_text=entity.origin_text,
        destination_text=entity.destination_text,
        origin_node_id=entity.origin_node_id,
        origin_node_name=_node_name(ctx, entity.origin_node_id),
        destination_node_id=entity.destination_node_id,
        destination_node_name=_node_name(ctx, entity.destination_node_id),
        origin_province_code=entity.origin_province_code,
        origin_city_code=entity.origin_city_code,
        origin_city_name=_city_name(ctx, entity.origin_city_code),
        origin_district_code=entity.origin_district_code,
        destination_province_code=entity.destination_province_code,
        destination_city_code=entity.destination_city_code,
        destination_city_name=_city_name(ctx, entity.destination_city_code),
        destination_district_code=entity.destination_district_code,
        origin_region_id_cache=entity.origin_region_id_cache,
        destination_region_id_cache=entity.destination_region_id_cache,
        publisher_org_name=entity.publisher_org_name,
        contact_name=entity.contact_name,
        contact_phone=entity.contact_phone,
        contact_wechat=entity.contact_wechat,
        confidence_score=entity.confidence_score,
        match_basis_json=entity.match_basis_json,
        status_code=entity.status_code,
        status_name=_label(ctx, "FREIGHT_CANDIDATE_STATUS", entity.status_code),
        confirmed_freight_id=entity.confirmed_freight_id,
        confirmed_at=entity.confirmed_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_feedback_response(entity, candidate: FreightCandidate | None, ctx: dict[str, Any] | None = None) -> FreightConfirmationResponse:
    ctx = ctx or {}
    return FreightConfirmationResponse(
        candidate_id=entity.candidate_id,
        candidate_no=candidate.candidate_no if candidate is not None else str(entity.candidate_id),
        action_code=entity.action_code,
        action_name=_label(ctx, "FREIGHT_CONFIRM_ACTION", entity.action_code),
        operator_id=entity.operator_id,
        operated_at=entity.operated_at,
        feedback_remark=entity.feedback_remark,
        before_json=entity.before_json,
        after_json=entity.after_json,
    )


class FreightService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = FreightRepository(db)
        self.contact_repo = FreightContactRepository(db)
        self.attachment_repo = FreightAttachmentRepository(db)
        self.tag_repo = FreightTagRelationRepository(db)
        self.candidate_repo = FreightCandidateRepository(db)
        self.feedback_repo = FreightCandidateFeedbackRepository(db)
        self.task_repo = FreightAiParseTaskRepository(db)
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
        ctx = await _load_display_context(self.db, freights=rows)
        return PageResponse[FreightResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_freight_response(item, ctx) for item in rows],
        )

    async def create_freight(self, payload) -> FreightResponse:
        data = payload.model_dump(exclude_none=True)
        freight_no = (payload.freight_no or "").strip()
        if not freight_no:
            freight_no = await self.sequence_service.next_code("FREIGHT_NO")
        data["freight_no"] = freight_no
        if await self.repo.exists_freight_no(freight_no):
            raise ConflictError(f"freight_no already exists: {freight_no}")
        data["cargo_title"] = payload.cargo_title.strip()
        if data.get("status_code") == "PUBLISHED" and data.get("published_at") is None:
            data["published_at"] = datetime.utcnow()
        row = await self.repo.create_freight(data)
        await self.db.commit()
        ctx = await _load_display_context(self.db, freights=[row])
        return _to_freight_response(row, ctx)

    async def update_freight(self, freight_id: int, payload) -> FreightResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        row = await self.repo.update_freight(freight_id, updates)
        if row is None:
            raise NotFoundError("Freight", freight_id)
        await self.db.commit()
        ctx = await _load_display_context(self.db, freights=[row])
        return _to_freight_response(row, ctx)

    async def get_freight_detail(self, freight_id: int) -> FreightDetailResponse:
        freight = await self.repo.get_freight_by_id(freight_id)
        if freight is None:
            raise NotFoundError("Freight", freight_id)
        contacts = await self.contact_repo.list_contacts(freight_id)
        attachments = await self.attachment_repo.list_attachments(freight_id)
        tags = await self.tag_repo.list_tag_relations(freight_id)

        candidates: list[FreightCandidate] = []
        task = None
        if freight.source_candidate_id:
            candidate = await self.candidate_repo.get_by_id(freight.source_candidate_id)
            if candidate is not None:
                candidates.append(candidate)
                task = await self.task_repo.get_by_id(candidate.parse_task_id)
        feedback_rows = await self.feedback_repo.list_by_candidate_ids([item.id for item in candidates])
        ctx = await _load_display_context(
            self.db,
            freights=[freight],
            candidates=candidates,
            tasks=[task] if task is not None else [],
            feedback=feedback_rows,
        )
        candidate_by_id = {item.id: item for item in candidates}
        ai_records = []
        if task is not None:
            candidate = candidates[0] if candidates else None
            ai_records.append(
                FreightAiTraceResponse(
                    parse_task_id=task.id,
                    task_no=task.task_no,
                    status_code=task.status_code,
                    status_name=_label(ctx, "AI_PARSE_STATUS", task.status_code),
                    raw_content=task.raw_content,
                    source_inbound_id=task.source_inbound_id,
                    candidate_id=candidate.id if candidate is not None else None,
                    candidate_no=candidate.candidate_no if candidate is not None else None,
                    confidence_score=candidate.confidence_score if candidate is not None else None,
                    match_basis_json=candidate.match_basis_json if candidate is not None else None,
                )
            )
        return FreightDetailResponse(
            profile=_to_freight_response(freight, ctx),
            contacts=[_to_contact_response(item) for item in contacts],
            attachments=[_to_attachment_response(item) for item in attachments],
            tags=[_to_tag_response(item) for item in tags],
            ai_parse_records=ai_records,
            confirmation_records=[
                _to_feedback_response(item, candidate_by_id.get(item.candidate_id), ctx)
                for item in feedback_rows
            ],
        )

    async def change_freight_status(self, freight_id: int, status_code: str) -> None:
        ok = await self.repo.update_freight_status(freight_id, status_code)
        if not ok:
            raise NotFoundError("Freight", freight_id)
        await self.db.commit()


class FreightSourceInboundService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = FreightSourceInboundRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def list_items(
        self,
        *,
        keyword: str | None,
        status_code: str | None,
        source_channel_code: str | None,
        page: int,
        page_size: int,
    ) -> PageResponse[FreightSourceInboundResponse]:
        rows, total = await self.repo.list_items(
            keyword=keyword,
            status_code=status_code,
            source_channel_code=source_channel_code,
            page=page,
            page_size=page_size,
        )
        ctx = await _load_display_context(self.db, inbounds=rows)
        return PageResponse[FreightSourceInboundResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_inbound_response(item, ctx) for item in rows],
        )

    async def create(self, payload) -> FreightSourceInboundResponse:
        inbound_no = (payload.inbound_no or "").strip() or await self.sequence_service.next_code("FREIGHT_INBOUND_NO")
        row = await self.repo.create(
            {
                **payload.model_dump(exclude_none=True, exclude={"inbound_no"}),
                "inbound_no": inbound_no,
                "raw_content": payload.raw_content.strip(),
                "received_at": payload.received_at or datetime.utcnow(),
                "status_code": "NEW",
            }
        )
        await self.db.commit()
        ctx = await _load_display_context(self.db, inbounds=[row])
        return _to_inbound_response(row, ctx)

    async def get(self, inbound_id: int) -> FreightSourceInboundResponse:
        row = await self.repo.get_by_id(inbound_id)
        if row is None:
            raise NotFoundError("FreightSourceInbound", inbound_id)
        ctx = await _load_display_context(self.db, inbounds=[row])
        return _to_inbound_response(row, ctx)


class FreightAiParseTaskService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = FreightAiParseTaskRepository(db)
        self.inbound_repo = FreightSourceInboundRepository(db)
        self.clue_repo = FreightClueRepository(db)
        self.candidate_repo = FreightCandidateRepository(db)
        self.feedback_repo = FreightCandidateFeedbackRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def list_items(
        self,
        *,
        keyword: str | None,
        status_code: str | None,
        source_channel_code: str | None,
        page: int,
        page_size: int,
    ) -> PageResponse[FreightAiParseTaskResponse]:
        rows, total = await self.repo.list_items(
            keyword=keyword,
            status_code=status_code,
            source_channel_code=source_channel_code,
            page=page,
            page_size=page_size,
        )
        ctx = await _load_display_context(self.db, tasks=rows)
        return PageResponse[FreightAiParseTaskResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_task_response(item, ctx) for item in rows],
        )

    async def create(self, payload, requested_by: int | None = None) -> FreightAiParseTaskResponse:
        inbound = None
        raw_content = (payload.raw_content or "").strip()
        source_type_code = payload.source_type_code
        source_channel_code = payload.source_channel_code
        if payload.source_inbound_id is not None:
            inbound = await self.inbound_repo.get_by_id(payload.source_inbound_id)
            if inbound is None:
                raise NotFoundError("FreightSourceInbound", payload.source_inbound_id)
            raw_content = inbound.raw_content
            source_type_code = inbound.source_type_code
            source_channel_code = inbound.source_channel_code
        if not raw_content:
            raise ValidationError("raw_content is required when source_inbound_id is not provided")
        task_no = (payload.task_no or "").strip() or await self.sequence_service.next_code("FREIGHT_PARSE_TASK_NO")
        row = await self.repo.create(
            {
                "task_no": task_no,
                "source_inbound_id": payload.source_inbound_id,
                "source_type_code": source_type_code,
                "source_channel_code": source_channel_code,
                "raw_content": raw_content,
                "status_code": "PENDING",
                "ai_provider_code": "DASHSCOPE_QWEN",
                "ai_model": "qwen-plus",
                "prompt_version": DashScopeQwenFreightParserClient.prompt_version,
                "requested_by": requested_by,
            }
        )
        if inbound is not None:
            await self.inbound_repo.update(inbound.id, {"parse_task_id": row.id, "status_code": "PARSING"})
        await self.db.commit()
        ctx = await _load_display_context(self.db, tasks=[row])
        return _to_task_response(row, ctx)

    async def get_detail(self, task_id: int) -> FreightAiParseTaskDetailResponse:
        task = await self.repo.get_by_id(task_id)
        if task is None:
            raise NotFoundError("FreightAiParseTask", task_id)
        inbound = await self.inbound_repo.get_by_id(task.source_inbound_id) if task.source_inbound_id else None
        clues = await self.clue_repo.list_by_task(task_id)
        candidates = await self.candidate_repo.list_by_task(task_id)
        feedback = await self.feedback_repo.list_by_candidate_ids([item.id for item in candidates])
        ctx = await _load_display_context(
            self.db,
            tasks=[task],
            inbounds=[inbound] if inbound is not None else [],
            clues=clues,
            candidates=candidates,
            feedback=feedback,
        )
        candidate_by_id = {item.id: item for item in candidates}
        return FreightAiParseTaskDetailResponse(
            task=_to_task_response(task, ctx),
            source_inbound=_to_inbound_response(inbound, ctx) if inbound is not None else None,
            clues=[_to_clue_response(item, ctx) for item in clues],
            candidates=[_to_candidate_response(item, ctx) for item in candidates],
            feedback=[
                _to_feedback_response(item, candidate_by_id.get(item.candidate_id), ctx)
                for item in feedback
            ],
        )

    async def run(self, task_id: int, requested_by: int | None = None) -> FreightAiParseTaskDetailResponse:
        task = await self.repo.get_by_id(task_id)
        if task is None:
            raise NotFoundError("FreightAiParseTask", task_id)
        existing_candidates = await self.candidate_repo.list_by_task(task_id)
        if task.status_code == "SUCCESS" and existing_candidates:
            return await self.get_detail(task_id)

        started_at = datetime.utcnow()
        await self.repo.update(
            task_id,
            {
                "status_code": "RUNNING",
                "started_at": started_at,
                "finished_at": None,
                "error_message": None,
                "requested_by": requested_by or task.requested_by,
            },
        )
        if task.source_inbound_id:
            await self.inbound_repo.update(task.source_inbound_id, {"status_code": "PARSING", "error_message": None})
        await self.db.commit()

        runtime_config = RuntimeConfigService(self.db)
        client = DashScopeQwenFreightParserClient(runtime_config=runtime_config)
        try:
            parsed = await client.parse(task.raw_content)
            clue_count = 0
            for index, segment in enumerate(parsed.segments, start=1):
                clue = await self.clue_repo.create(
                    {
                        "clue_no": await self.sequence_service.next_code("FREIGHT_CLUE_NO"),
                        "parse_task_id": task_id,
                        "source_inbound_id": task.source_inbound_id,
                        "segment_index": index,
                        "raw_text": str(segment.get("raw_text") or task.raw_content),
                        "status_code": "CANDIDATE_CREATED",
                        "parse_result_json": segment,
                    }
                )
                candidate_data = await self._candidate_from_segment(task, clue.id, segment)
                await self.candidate_repo.create(candidate_data)
                clue_count += 1
            status_code = "SUCCESS" if clue_count else "FAILED"
            await self.repo.update(
                task_id,
                {
                    "status_code": status_code,
                    "ai_provider_code": parsed.provider,
                    "ai_model": parsed.model,
                    "prompt_version": DashScopeQwenFreightParserClient.prompt_version,
                    "finished_at": datetime.utcnow(),
                    "raw_response_json": {
                        "parsed_payload": parsed.parsed_payload,
                        "raw_response": parsed.raw_response,
                    },
                },
            )
            if task.source_inbound_id:
                await self.inbound_repo.update(task.source_inbound_id, {"status_code": "PARSED", "error_message": None})
            await self.db.commit()
        except Exception as exc:
            message = str(exc)
            await self.repo.update(
                task_id,
                {
                    "status_code": "FAILED",
                    "finished_at": datetime.utcnow(),
                    "error_message": message,
                },
            )
            if task.source_inbound_id:
                await self.inbound_repo.update(task.source_inbound_id, {"status_code": "FAILED", "error_message": message[:512]})
            await self.db.commit()
            raise
        return await self.get_detail(task_id)

    async def _candidate_from_segment(self, task, clue_id: int, segment: dict[str, Any]) -> dict[str, Any]:
        commodity_name = str(segment.get("commodity_name") or "").strip()
        commodity_id, commodity_score, commodity_basis = await self._match_commodity(commodity_name)
        origin_text = str(segment.get("origin_text") or "").strip()
        destination_text = str(segment.get("destination_text") or "").strip()
        origin_node, origin_basis = await self._match_node(origin_text)
        destination_node, destination_basis = await self._match_node(destination_text)
        confidence = _to_decimal_or_none(segment.get("confidence_score")) or Decimal("0.50")
        basis = {
            "commodity": commodity_basis,
            "origin": origin_basis,
            "destination": destination_basis,
            "evidence": segment.get("evidence") or [],
        }
        title = str(segment.get("cargo_title") or "").strip()
        if not title:
            pieces = [commodity_name or "货源", origin_text, destination_text]
            title = " - ".join([item for item in pieces if item])[:256] or "待确认货源"
        return {
            "candidate_no": await self.sequence_service.next_code("FREIGHT_CANDIDATE_NO"),
            "parse_task_id": task.id,
            "clue_id": clue_id,
            "source_inbound_id": task.source_inbound_id,
            "cargo_title": title,
            "cargo_description": segment.get("cargo_description"),
            "commodity_standard_id": commodity_id,
            "commodity_match_name": commodity_name or None,
            "commodity_match_score": commodity_score,
            "packaging_form_code": segment.get("packaging_form_code"),
            "estimated_tonnage": _to_decimal_or_none(segment.get("estimated_tonnage")),
            "min_tonnage": _to_decimal_or_none(segment.get("min_tonnage")),
            "max_tonnage": _to_decimal_or_none(segment.get("max_tonnage")),
            "unit_price": _to_decimal_or_none(segment.get("unit_price")),
            "total_price": _to_decimal_or_none(segment.get("total_price")),
            "price_unit": segment.get("price_unit") or "元/吨",
            "settlement_method_code": segment.get("settlement_method_code"),
            "origin_text": origin_text or None,
            "destination_text": destination_text or None,
            "origin_node_id": origin_node.id if origin_node is not None else None,
            "destination_node_id": destination_node.id if destination_node is not None else None,
            "origin_province_code": origin_node.province_code if origin_node is not None else None,
            "origin_city_code": origin_node.city_code if origin_node is not None else None,
            "origin_district_code": origin_node.district_code if origin_node is not None else None,
            "destination_province_code": destination_node.province_code if destination_node is not None else None,
            "destination_city_code": destination_node.city_code if destination_node is not None else None,
            "destination_district_code": destination_node.district_code if destination_node is not None else None,
            "origin_region_id_cache": await self._business_region_id(origin_node.city_region_id) if origin_node is not None else None,
            "destination_region_id_cache": await self._business_region_id(destination_node.city_region_id) if destination_node is not None else None,
            "publisher_org_name": segment.get("publisher_org_name"),
            "contact_name": segment.get("contact_name"),
            "contact_phone": segment.get("contact_phone"),
            "contact_wechat": segment.get("contact_wechat"),
            "confidence_score": confidence,
            "match_basis_json": basis,
            "status_code": "PENDING",
        }

    async def _business_region_id(self, city_region_id: int | None) -> int | None:
        if city_region_id is None:
            return None
        relation = await self.db.scalar(
            select(RegionCityRelation)
            .where(RegionCityRelation.city_region_id == city_region_id)
            .order_by(RegionCityRelation.is_primary.desc(), RegionCityRelation.sort_order.asc())
        )
        return int(relation.region_id) if relation is not None else None

    async def _match_commodity(self, raw_name: str) -> tuple[int | None, Decimal | None, dict[str, Any]]:
        text = raw_name.strip()
        if not text:
            return None, None, {"status": "NO_TEXT"}
        standards = (await self.db.execute(select(CommodityStandard))).scalars().all()
        aliases = (await self.db.execute(select(CommodityAlias))).scalars().all()
        for standard in standards:
            if text == standard.name or text == (standard.short_name or ""):
                return int(standard.id), Decimal("1.0"), {"status": "STANDARD_EXACT", "name": standard.name}
        for alias in aliases:
            if text == alias.alias_name:
                return int(alias.commodity_standard_id), Decimal("1.0"), {"status": "ALIAS_EXACT", "alias": alias.alias_name}
        for standard in standards:
            if text in standard.name or standard.name in text:
                return int(standard.id), Decimal("0.82"), {"status": "STANDARD_CONTAINS", "name": standard.name}
        for alias in aliases:
            if text in alias.alias_name or alias.alias_name in text:
                return int(alias.commodity_standard_id), Decimal("0.80"), {"status": "ALIAS_CONTAINS", "alias": alias.alias_name}
        return None, Decimal("0.0"), {"status": "UNMATCHED", "text": text}

    async def _match_node(self, raw_text: str) -> tuple[TransportNode | None, dict[str, Any]]:
        text = raw_text.strip()
        if not text:
            return None, {"status": "NO_TEXT"}
        nodes = (await self.db.execute(select(TransportNode).where(TransportNode.deleted_at.is_(None)))).scalars().all()
        aliases = (await self.db.execute(select(NodeAlias))).scalars().all()
        for node in nodes:
            if text == node.name or text == (node.short_name or ""):
                return node, {"status": "NODE_EXACT", "name": node.name}
        for alias in aliases:
            if text == alias.alias_name:
                node = next((item for item in nodes if item.id == alias.node_id), None)
                return node, {"status": "ALIAS_EXACT", "alias": alias.alias_name}
        for node in nodes:
            names = [node.name, node.short_name or ""]
            if any(name and (name in text or text in name) for name in names):
                return node, {"status": "NODE_CONTAINS", "name": node.name}
        for alias in aliases:
            if alias.alias_name in text or text in alias.alias_name:
                node = next((item for item in nodes if item.id == alias.node_id), None)
                return node, {"status": "ALIAS_CONTAINS", "alias": alias.alias_name}
        return None, {"status": "UNMATCHED", "text": text}


class FreightCandidateService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = FreightCandidateRepository(db)
        self.feedback_repo = FreightCandidateFeedbackRepository(db)
        self.freight_repo = FreightRepository(db)
        self.contact_repo = FreightContactRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def list_items(
        self,
        *,
        keyword: str | None,
        status_code: str | None,
        page: int,
        page_size: int,
    ) -> PageResponse[FreightCandidateResponse]:
        rows, total = await self.repo.list_items(
            keyword=keyword,
            status_code=status_code,
            page=page,
            page_size=page_size,
        )
        ctx = await _load_display_context(self.db, candidates=rows)
        return PageResponse[FreightCandidateResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_candidate_response(item, ctx) for item in rows],
        )

    async def get(self, candidate_id: int) -> FreightCandidateResponse:
        row = await self.repo.get_by_id(candidate_id)
        if row is None:
            raise NotFoundError("FreightCandidate", candidate_id)
        ctx = await _load_display_context(self.db, candidates=[row])
        return _to_candidate_response(row, ctx)

    async def update(self, candidate_id: int, payload) -> FreightCandidateResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        row = await self.repo.update(candidate_id, updates)
        if row is None:
            raise NotFoundError("FreightCandidate", candidate_id)
        await self.db.commit()
        ctx = await _load_display_context(self.db, candidates=[row])
        return _to_candidate_response(row, ctx)

    async def confirm(self, candidate_id: int, payload, operator_id: int | None) -> FreightResponse:
        candidate = await self.repo.get_by_id(candidate_id)
        if candidate is None:
            raise NotFoundError("FreightCandidate", candidate_id)
        if candidate.status_code != "PENDING":
            raise ValidationError("只有待确认候选货源可以确认入库")
        before = _entity_snapshot(candidate, self._candidate_snapshot_fields())
        action_code = "CONFIRM"
        if payload.overrides is not None:
            updates = payload.overrides.model_dump(exclude_none=True)
            if updates:
                candidate = await self.repo.update(candidate_id, updates) or candidate
                action_code = "EDIT_CONFIRM"
        self._validate_candidate_ready(candidate)
        freight_no = await self.sequence_service.next_code("FREIGHT_NO")
        now = datetime.utcnow()
        freight = await self.freight_repo.create_freight(
            {
                "freight_no": freight_no,
                "source_type_code": "WECHAT" if candidate.source_inbound_id else "SYSTEM",
                "source_channel_code": "WECHAT_TEXT" if candidate.source_inbound_id else "SYSTEM_SYNC",
                "source_ref_no": candidate.candidate_no,
                "source_candidate_id": candidate.id,
                "cargo_title": candidate.cargo_title,
                "cargo_description": candidate.cargo_description,
                "commodity_standard_id": candidate.commodity_standard_id,
                "packaging_form_code": candidate.packaging_form_code,
                "estimated_tonnage": candidate.estimated_tonnage,
                "min_tonnage": candidate.min_tonnage,
                "max_tonnage": candidate.max_tonnage,
                "unit_price": candidate.unit_price,
                "total_price": candidate.total_price,
                "price_unit": candidate.price_unit,
                "settlement_method_code": candidate.settlement_method_code,
                "origin_node_id": candidate.origin_node_id,
                "destination_node_id": candidate.destination_node_id,
                "origin_province_code": candidate.origin_province_code,
                "origin_city_code": candidate.origin_city_code,
                "origin_district_code": candidate.origin_district_code,
                "destination_province_code": candidate.destination_province_code,
                "destination_city_code": candidate.destination_city_code,
                "destination_district_code": candidate.destination_district_code,
                "origin_region_id_cache": candidate.origin_region_id_cache,
                "destination_region_id_cache": candidate.destination_region_id_cache,
                "loading_time_from": candidate.loading_time_from,
                "loading_time_to": candidate.loading_time_to,
                "unloading_time_from": candidate.unloading_time_from,
                "unloading_time_to": candidate.unloading_time_to,
                "publisher_org_name": candidate.publisher_org_name,
                "status_code": "PUBLISHED",
                "published_at": now,
                "expired_at": candidate.loading_time_to,
                "confirmed_at": now,
                "confirmed_by": operator_id,
                "audit_status": "APPROVED",
            }
        )
        await self.repo.update(candidate.id, {"status_code": "CONFIRMED", "confirmed_freight_id": freight.id, "confirmed_at": now})
        if candidate.contact_name or candidate.contact_phone or candidate.contact_wechat:
            await self.contact_repo.create_contact(
                freight.id,
                {
                    "contact_name": candidate.contact_name or "货源联系人",
                    "contact_role_code": "FREIGHT_CONTACT",
                    "mobile_phone": candidate.contact_phone,
                    "landline_phone": None,
                    "wechat": candidate.contact_wechat,
                    "is_primary": True,
                },
            )
        await self.feedback_repo.create(
            {
                "candidate_id": candidate.id,
                "action_code": action_code,
                "before_json": before,
                "after_json": _entity_snapshot(candidate, self._candidate_snapshot_fields()),
                "feedback_remark": payload.remark,
                "operator_id": operator_id,
                "operated_at": now,
                "created_at": now,
            }
        )
        await self.db.commit()
        ctx = await _load_display_context(self.db, freights=[freight])
        return _to_freight_response(freight, ctx)

    async def reject(self, candidate_id: int, payload, operator_id: int | None) -> FreightCandidateResponse:
        candidate = await self.repo.get_by_id(candidate_id)
        if candidate is None:
            raise NotFoundError("FreightCandidate", candidate_id)
        if candidate.status_code == "CONFIRMED":
            raise ValidationError("已确认候选货源不能驳回")
        before = _entity_snapshot(candidate, self._candidate_snapshot_fields())
        row = await self.repo.update(candidate_id, {"status_code": "REJECTED"})
        now = datetime.utcnow()
        await self.feedback_repo.create(
            {
                "candidate_id": candidate_id,
                "action_code": "REJECT",
                "before_json": before,
                "after_json": _entity_snapshot(row, self._candidate_snapshot_fields()) if row is not None else None,
                "feedback_remark": payload.remark,
                "operator_id": operator_id,
                "operated_at": now,
                "created_at": now,
            }
        )
        await self.db.commit()
        ctx = await _load_display_context(self.db, candidates=[row])
        return _to_candidate_response(row, ctx)

    @staticmethod
    def _candidate_snapshot_fields() -> list[str]:
        return [
            "candidate_no",
            "cargo_title",
            "commodity_standard_id",
            "origin_node_id",
            "destination_node_id",
            "estimated_tonnage",
            "unit_price",
            "status_code",
        ]

    @staticmethod
    def _validate_candidate_ready(candidate) -> None:
        missing: list[str] = []
        if candidate.commodity_standard_id is None:
            missing.append("标准货品")
        if not candidate.origin_province_code or not candidate.origin_city_code:
            missing.append("起运省市")
        if not candidate.destination_province_code or not candidate.destination_city_code:
            missing.append("目的省市")
        if missing:
            raise ValidationError(f"候选货源缺少确认入库字段：{', '.join(missing)}")


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
