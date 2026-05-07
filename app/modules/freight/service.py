"""freight 模块 service。"""

from __future__ import annotations

import json
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
    FreightAttachmentRepository,
    FreightBatchTaskRepository,
    FreightCandidateManualFeedbackRepository,
    FreightCandidateRepository,
    FreightClueRepository,
    FreightContactRepository,
    FreightRepository,
    FreightTagRelationRepository,
    FreightTmsInboundRepository,
)
from app.modules.freight.schemas import (
    FreightAttachmentResponse,
    FreightBatchDetailResponse,
    FreightBatchResponse,
    FreightCandidateBulkConfirmResponse,
    FreightCandidateResponse,
    FreightClueResponse,
    FreightConfirmationResponse,
    FreightContactResponse,
    FreightDetailResponse,
    FreightResponse,
    FreightTagRelationResponse,
    FreightTmsInboundDetailResponse,
    FreightTmsInboundResponse,
    PageResponse,
)
from app.modules.system.runtime_config import RuntimeConfigService


DISPLAY_DICT_CODES = [
    "SOURCE_TYPE",
    "SOURCE_CHANNEL",
    "FREIGHT_STATUS",
    "AUDIT_STATUS",
    "PACKAGING_FORM",
    "FREIGHT_BATCH_STATUS",
    "FREIGHT_TMS_INBOUND_STATUS",
    "FREIGHT_CLUE_STATUS",
    "FREIGHT_CANDIDATE_STATUS",
    "FREIGHT_CONFIRM_ACTION",
    "FREIGHT_MATCH_LEVEL",
    "FREIGHT_HALL_STATUS",
    "FREIGHT_AVAILABILITY_STATUS",
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


def _first(segment: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = segment.get(key)
        if value not in (None, ""):
            return value
    return None


async def _load_display_context(
    db: AsyncSession,
    *,
    freights: list[Any] | None = None,
    candidates: list[Any] | None = None,
    batches: list[Any] | None = None,
    tms_inbounds: list[Any] | None = None,
    clues: list[Any] | None = None,
    feedback: list[Any] | None = None,
) -> dict[str, Any]:
    freights = freights or []
    candidates = candidates or []
    batches = batches or []
    tms_inbounds = tms_inbounds or []
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
        for region_id in (getattr(item, "origin_region_id_cache", None), getattr(item, "destination_region_id_cache", None))
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
        "batches": batches,
        "tms_inbounds": tms_inbounds,
        "clues": clues,
        "feedback": feedback,
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
        source_batch_id=entity.source_batch_id,
        source_tms_inbound_id=entity.source_tms_inbound_id,
        source_clue_id=entity.source_clue_id,
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
        hall_status_code=entity.hall_status_code,
        hall_status_name=_label(ctx, "FREIGHT_HALL_STATUS", entity.hall_status_code),
        hall_published_at=entity.hall_published_at,
        hall_unpublished_at=entity.hall_unpublished_at,
        hall_visible_until=entity.hall_visible_until,
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
    return FreightTagRelationResponse(id=entity.id, freight_id=entity.freight_id, tag_code=entity.tag_code, created_at=entity.created_at)


def _to_batch_response(entity, ctx: dict[str, Any] | None = None) -> FreightBatchResponse:
    ctx = ctx or {}
    summary = (ctx.get("batch_candidate_summary") or {}).get(entity.id, {})
    return FreightBatchResponse(
        id=entity.id,
        batch_no=entity.batch_no,
        source_type_code=entity.source_type_code,
        source_type_name=_label(ctx, "SOURCE_TYPE", entity.source_type_code),
        source_channel_code=entity.source_channel_code,
        source_channel_name=_label(ctx, "SOURCE_CHANNEL", entity.source_channel_code),
        raw_text=entity.raw_text,
        status_code=entity.status_code,
        status_name=_label(ctx, "FREIGHT_BATCH_STATUS", entity.status_code),
        clue_count=entity.clue_count,
        candidate_count=entity.candidate_count,
        success_count=entity.success_count,
        failed_count=entity.failed_count,
        pending_count=int(summary.get("pending_count") or 0),
        confirmed_count=int(summary.get("confirmed_count") or 0),
        rejected_count=int(summary.get("rejected_count") or 0),
        ready_count=int(summary.get("ready_count") or 0),
        review_count=int(summary.get("review_count") or 0),
        route_summary=summary.get("route_summary"),
        contact_summary=summary.get("contact_summary"),
        creator_id=entity.creator_id,
        remark=entity.remark,
        error_message=entity.error_message,
        prompt_version=entity.prompt_version,
        started_at=entity.started_at,
        finished_at=entity.finished_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_tms_response(entity, ctx: dict[str, Any] | None = None) -> FreightTmsInboundResponse:
    ctx = ctx or {}
    return FreightTmsInboundResponse(
        id=entity.id,
        inbound_no=entity.inbound_no,
        source_type_code=entity.source_type_code,
        source_type_name=_label(ctx, "SOURCE_TYPE", entity.source_type_code),
        source_channel_code=entity.source_channel_code,
        source_channel_name=_label(ctx, "SOURCE_CHANNEL", entity.source_channel_code),
        source_trace_id=entity.source_trace_id,
        idempotency_key=entity.idempotency_key,
        external_ref_no=entity.external_ref_no,
        payload_json=entity.payload_json,
        raw_content=entity.raw_content,
        status_code=entity.status_code,
        status_name=_label(ctx, "FREIGHT_TMS_INBOUND_STATUS", entity.status_code),
        clue_count=entity.clue_count,
        candidate_count=entity.candidate_count,
        processed_at=entity.processed_at,
        error_message=entity.error_message,
        prompt_version=entity.prompt_version,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_clue_response(entity, ctx: dict[str, Any] | None = None) -> FreightClueResponse:
    ctx = ctx or {}
    return FreightClueResponse(
        id=entity.id,
        clue_no=entity.clue_no,
        source_type_code=entity.source_type_code,
        source_channel_code=entity.source_channel_code,
        source_batch_id=entity.source_batch_id,
        source_tms_inbound_id=entity.source_tms_inbound_id,
        segment_index=entity.segment_index,
        raw_text=entity.raw_text,
        context_summary=entity.context_summary,
        extracted_fields_json=entity.extracted_fields_json,
        quality_score=entity.quality_score,
        status_code=entity.status_code,
        status_name=_label(ctx, "FREIGHT_CLUE_STATUS", entity.status_code),
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_candidate_response(entity, ctx: dict[str, Any] | None = None) -> FreightCandidateResponse:
    ctx = ctx or {}
    commodity = _commodity(ctx, entity.commodity_standard_id)
    return FreightCandidateResponse(
        id=entity.id,
        candidate_no=entity.candidate_no,
        source_type_code=entity.source_type_code,
        source_type_name=_label(ctx, "SOURCE_TYPE", entity.source_type_code),
        source_channel_code=entity.source_channel_code,
        source_channel_name=_label(ctx, "SOURCE_CHANNEL", entity.source_channel_code),
        source_batch_id=entity.source_batch_id,
        source_tms_inbound_id=entity.source_tms_inbound_id,
        clue_id=entity.clue_id,
        source_ref_no=entity.source_ref_no,
        raw_text=entity.raw_text,
        raw_commodity_name=entity.raw_commodity_name,
        raw_origin_text=entity.raw_origin_text,
        raw_destination_text=entity.raw_destination_text,
        cargo_title=entity.cargo_title,
        cargo_description=entity.cargo_description,
        commodity_standard_id=entity.commodity_standard_id,
        commodity_standard_name=commodity.name if commodity is not None else None,
        commodity_match_name=entity.commodity_match_name,
        commodity_match_score=entity.commodity_match_score,
        commodity_match_level_code=entity.commodity_match_level_code,
        commodity_options_json=entity.commodity_options_json,
        packaging_form_code=entity.packaging_form_code,
        estimated_tonnage=entity.estimated_tonnage,
        min_tonnage=entity.min_tonnage,
        max_tonnage=entity.max_tonnage,
        unit_price=entity.unit_price,
        total_price=entity.total_price,
        price_unit=entity.price_unit,
        settlement_method_code=entity.settlement_method_code,
        origin_node_id=entity.origin_node_id,
        origin_node_name=_node_name(ctx, entity.origin_node_id),
        destination_node_id=entity.destination_node_id,
        destination_node_name=_node_name(ctx, entity.destination_node_id),
        origin_node_match_score=entity.origin_node_match_score,
        destination_node_match_score=entity.destination_node_match_score,
        origin_match_level_code=entity.origin_match_level_code,
        destination_match_level_code=entity.destination_match_level_code,
        origin_options_json=entity.origin_options_json,
        destination_options_json=entity.destination_options_json,
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
        publisher_org_name=entity.publisher_org_name,
        contact_name=entity.contact_name,
        contact_phone=entity.contact_phone,
        contact_wechat=entity.contact_wechat,
        confidence_score=entity.confidence_score,
        completeness_score=entity.completeness_score,
        match_basis_json=entity.match_basis_json,
        ai_suggestion_json=entity.ai_suggestion_json,
        availability_status_code=entity.availability_status_code,
        availability_status_name=_label(ctx, "FREIGHT_AVAILABILITY_STATUS", entity.availability_status_code),
        manual_review_reason=entity.manual_review_reason,
        ai_warning_json=entity.ai_warning_json,
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


class FreightNormalizationMixin:
    db: AsyncSession
    sequence_service: CodeSequenceService

    async def _business_region_id(self, city_region_id: int | None) -> int | None:
        if city_region_id is None:
            return None
        relation = await self.db.scalar(
            select(RegionCityRelation)
            .where(RegionCityRelation.city_region_id == city_region_id)
            .order_by(RegionCityRelation.is_primary.desc(), RegionCityRelation.sort_order.asc())
        )
        return int(relation.region_id) if relation is not None else None

    async def _city_by_code(self, city_code: str | None) -> AdminRegion | None:
        if not city_code:
            return None
        return await self.db.scalar(select(AdminRegion).where(AdminRegion.code == city_code))

    async def _node_by_id(self, node_id: int | None) -> TransportNode | None:
        if node_id is None:
            return None
        return await self.db.scalar(select(TransportNode).where(TransportNode.id == node_id, TransportNode.deleted_at.is_(None)))

    async def _enrich_location_updates(self, updates: dict[str, Any], prefix: str) -> None:
        node_key = f"{prefix}_node_id"
        city_key = f"{prefix}_city_code"
        province_key = f"{prefix}_province_code"
        district_key = f"{prefix}_district_code"
        region_key = f"{prefix}_region_id_cache"
        if node_key in updates and updates.get(node_key):
            node = await self._node_by_id(updates[node_key])
            if node is not None:
                updates[province_key] = node.province_code
                updates[city_key] = node.city_code
                updates[district_key] = node.district_code
                updates[region_key] = await self._business_region_id(node.city_region_id)
                updates[f"{prefix}_match_level_code"] = "NODE"
            return
        if city_key in updates and updates.get(city_key):
            city = await self._city_by_code(updates[city_key])
            if city is not None:
                updates[province_key] = city.province_code or city.code[:2].ljust(6, "0")
                updates[region_key] = await self._business_region_id(city.id)
                updates[f"{prefix}_match_level_code"] = updates.get(f"{prefix}_match_level_code") or "CITY"

    async def _match_commodity(self, raw_name: str) -> tuple[int | None, Decimal | None, str | None, list[dict[str, Any]], dict[str, Any]]:
        text = raw_name.strip()
        if not text:
            return None, None, None, [], {"status": "NO_TEXT"}
        standards = (await self.db.execute(select(CommodityStandard).where(CommodityStandard.deleted_at.is_(None)))).scalars().all()
        aliases = (await self.db.execute(select(CommodityAlias))).scalars().all()
        options: list[dict[str, Any]] = []
        for standard in standards:
            score = None
            level = None
            if text == standard.name or text == (standard.short_name or ""):
                score, level = Decimal("1.0"), "STANDARD"
            elif text in standard.name or standard.name in text:
                score, level = Decimal("0.82"), "STANDARD"
            if score is not None:
                options.append({"id": int(standard.id), "name": standard.name, "score": str(score), "match_level_code": level, "basis": "standard"})
        for alias in aliases:
            score = None
            if text == alias.alias_name:
                score = Decimal("1.0")
            elif text in alias.alias_name or alias.alias_name in text:
                score = Decimal("0.80")
            if score is not None:
                standard = next((item for item in standards if item.id == alias.commodity_standard_id), None)
                options.append(
                    {
                        "id": int(alias.commodity_standard_id),
                        "name": standard.name if standard is not None else alias.alias_name,
                        "score": str(score),
                        "match_level_code": "ALIAS",
                        "basis": alias.alias_name,
                    }
                )
        dedup: dict[int, dict[str, Any]] = {}
        for option in sorted(options, key=lambda item: Decimal(str(item["score"])), reverse=True):
            dedup.setdefault(int(option["id"]), option)
        ordered = list(dedup.values())[:5]
        if not ordered:
            return None, Decimal("0.0"), "UNMATCHED", [], {"status": "UNMATCHED", "text": text}
        first = ordered[0]
        return int(first["id"]), Decimal(str(first["score"])), str(first["match_level_code"]), ordered, {"status": "MATCHED", "text": text, "top": first}

    async def _match_location(self, raw_text: str) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        text = raw_text.strip()
        if not text:
            return {}, [], {"status": "NO_TEXT"}
        nodes = (await self.db.execute(select(TransportNode).where(TransportNode.deleted_at.is_(None)))).scalars().all()
        aliases = (await self.db.execute(select(NodeAlias))).scalars().all()
        cities = (await self.db.execute(select(AdminRegion).where(AdminRegion.level == 2, AdminRegion.status == 1))).scalars().all()
        options: list[dict[str, Any]] = []
        for node in nodes:
            names = [node.name, node.short_name or ""]
            score = None
            if any(text == name for name in names if name):
                score = Decimal("1.0")
            elif any(name and (name in text or text in name) for name in names):
                score = Decimal("0.86")
            if score is not None:
                options.append(
                    {
                        "level": "NODE",
                        "node_id": int(node.id),
                        "node_name": node.name,
                        "city_code": node.city_code,
                        "province_code": node.province_code,
                        "district_code": node.district_code,
                        "region_id": await self._business_region_id(node.city_region_id),
                        "score": str(score),
                        "basis": node.name,
                    }
                )
        for alias in aliases:
            score = None
            if text == alias.alias_name:
                score = Decimal("1.0")
            elif alias.alias_name in text or text in alias.alias_name:
                score = Decimal("0.82")
            if score is not None:
                node = next((item for item in nodes if item.id == alias.node_id), None)
                if node is not None:
                    options.append(
                        {
                            "level": "NODE",
                            "node_id": int(node.id),
                            "node_name": node.name,
                            "city_code": node.city_code,
                            "province_code": node.province_code,
                            "district_code": node.district_code,
                            "region_id": await self._business_region_id(node.city_region_id),
                            "score": str(score),
                            "basis": alias.alias_name,
                        }
                    )
        for city in cities:
            score = None
            if text == city.name:
                score = Decimal("0.90")
            elif city.name in text or text in city.name:
                score = Decimal("0.76")
            if score is not None:
                options.append(
                    {
                        "level": "CITY",
                        "node_id": None,
                        "node_name": None,
                        "city_code": city.code,
                        "city_name": city.name,
                        "province_code": city.province_code or city.code[:2].ljust(6, "0"),
                        "district_code": None,
                        "region_id": await self._business_region_id(city.id),
                        "score": str(score),
                        "basis": city.name,
                    }
                )
        ordered = sorted(options, key=lambda item: Decimal(str(item["score"])), reverse=True)[:6]
        if not ordered:
            return {}, [], {"status": "UNMATCHED", "text": text}
        first = ordered[0]
        normalized = {
            "node_id": first.get("node_id"),
            "province_code": first.get("province_code"),
            "city_code": first.get("city_code"),
            "district_code": first.get("district_code"),
            "region_id": first.get("region_id"),
            "match_score": Decimal(str(first["score"])),
            "match_level_code": first["level"],
        }
        return normalized, ordered, {"status": "MATCHED", "text": text, "top": first}

    async def _candidate_from_segment(
        self,
        *,
        source_type_code: str,
        source_channel_code: str,
        source_batch_id: int | None,
        source_tms_inbound_id: int | None,
        clue_id: int,
        segment: dict[str, Any],
    ) -> dict[str, Any]:
        commodity_name = str(_first(segment, "commodity_name", "cargo_name", "goods_name", "cargo") or "").strip()
        commodity_id, commodity_score, commodity_level, commodity_options, commodity_basis = await self._match_commodity(commodity_name)
        origin_text = str(_first(segment, "origin_text", "loading_place", "origin", "from") or "").strip()
        destination_text = str(_first(segment, "destination_text", "unloading_place", "destination", "to") or "").strip()
        origin, origin_options, origin_basis = await self._match_location(origin_text)
        destination, destination_options, destination_basis = await self._match_location(destination_text)
        confidence = _to_decimal_or_none(_first(segment, "confidence_score", "confidence")) or Decimal("0.50")
        completeness_score = self._completeness_score(
            commodity_id=commodity_id,
            origin_city_code=origin.get("city_code"),
            destination_city_code=destination.get("city_code"),
            tonnage=_to_decimal_or_none(_first(segment, "estimated_tonnage", "quantity_ton", "tonnage")),
            unit_price=_to_decimal_or_none(_first(segment, "unit_price", "price")),
        )
        title = str(_first(segment, "cargo_title", "title") or "").strip()
        if not title:
            pieces = [origin_text, destination_text, commodity_name or "货源"]
            title = " - ".join([item for item in pieces if item])[:256] or "待确认货源"
        raw_text = str(_first(segment, "raw_text", "source_text") or "").strip()
        return {
            "candidate_no": await self.sequence_service.next_code("FREIGHT_CANDIDATE_NO"),
            "source_type_code": source_type_code,
            "source_channel_code": source_channel_code,
            "source_batch_id": source_batch_id,
            "source_tms_inbound_id": source_tms_inbound_id,
            "clue_id": clue_id,
            "source_ref_no": _first(segment, "source_ref_no", "waybill_no", "order_no"),
            "raw_text": raw_text or None,
            "raw_commodity_name": commodity_name or None,
            "raw_origin_text": origin_text or None,
            "raw_destination_text": destination_text or None,
            "cargo_title": title,
            "cargo_description": _first(segment, "cargo_description", "description"),
            "commodity_standard_id": commodity_id,
            "commodity_match_name": commodity_name or None,
            "commodity_match_score": commodity_score,
            "commodity_match_level_code": commodity_level,
            "commodity_options_json": commodity_options,
            "packaging_form_code": _first(segment, "packaging_form_code", "packaging_form"),
            "estimated_tonnage": _to_decimal_or_none(_first(segment, "estimated_tonnage", "quantity_ton", "tonnage")),
            "min_tonnage": _to_decimal_or_none(segment.get("min_tonnage")),
            "max_tonnage": _to_decimal_or_none(segment.get("max_tonnage")),
            "unit_price": _to_decimal_or_none(_first(segment, "unit_price", "price")),
            "total_price": _to_decimal_or_none(segment.get("total_price")),
            "price_unit": _first(segment, "price_unit") or "元/吨",
            "settlement_method_code": segment.get("settlement_method_code"),
            "origin_node_id": origin.get("node_id"),
            "destination_node_id": destination.get("node_id"),
            "origin_node_match_score": origin.get("match_score"),
            "destination_node_match_score": destination.get("match_score"),
            "origin_match_level_code": origin.get("match_level_code"),
            "destination_match_level_code": destination.get("match_level_code"),
            "origin_options_json": origin_options,
            "destination_options_json": destination_options,
            "origin_province_code": origin.get("province_code"),
            "origin_city_code": origin.get("city_code"),
            "origin_district_code": origin.get("district_code"),
            "destination_province_code": destination.get("province_code"),
            "destination_city_code": destination.get("city_code"),
            "destination_district_code": destination.get("district_code"),
            "origin_region_id_cache": origin.get("region_id"),
            "destination_region_id_cache": destination.get("region_id"),
            "publisher_org_name": _first(segment, "publisher_org_name", "shipper", "company"),
            "contact_name": _first(segment, "contact_name", "contact"),
            "contact_phone": _first(segment, "contact_phone", "phone", "mobile"),
            "contact_wechat": segment.get("contact_wechat"),
            "confidence_score": confidence,
            "completeness_score": completeness_score,
            "match_basis_json": {
                "commodity": commodity_basis,
                "origin": origin_basis,
                "destination": destination_basis,
                "evidence": segment.get("evidence") or [],
            },
            "ai_suggestion_json": segment,
            "availability_status_code": str(_first(segment, "availability_status_code") or "UNKNOWN").upper(),
            "manual_review_reason": _first(segment, "manual_review_reason", "review_reason"),
            "ai_warning_json": segment.get("ai_warning_json"),
            "status_code": "PENDING",
        }

    @staticmethod
    def _completeness_score(
        *,
        commodity_id: int | None,
        origin_city_code: str | None,
        destination_city_code: str | None,
        tonnage: Decimal | None,
        unit_price: Decimal | None,
    ) -> Decimal:
        score = Decimal("0.20")
        score += Decimal("0.20") if commodity_id else Decimal("0")
        score += Decimal("0.20") if origin_city_code else Decimal("0")
        score += Decimal("0.20") if destination_city_code else Decimal("0")
        score += Decimal("0.10") if tonnage else Decimal("0")
        score += Decimal("0.10") if unit_price else Decimal("0")
        return score.quantize(Decimal("0.0001"))


class FreightService(FreightNormalizationMixin):
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = FreightRepository(db)
        self.contact_repo = FreightContactRepository(db)
        self.attachment_repo = FreightAttachmentRepository(db)
        self.tag_repo = FreightTagRelationRepository(db)
        self.batch_repo = FreightBatchTaskRepository(db)
        self.tms_repo = FreightTmsInboundRepository(db)
        self.clue_repo = FreightClueRepository(db)
        self.candidate_repo = FreightCandidateRepository(db)
        self.feedback_repo = FreightCandidateManualFeedbackRepository(db)
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
        return PageResponse[FreightResponse](total=total, page=page, page_size=page_size, items=[_to_freight_response(item, ctx) for item in rows])

    async def create_manual_freight(self, payload) -> FreightResponse:
        data = payload.model_dump(exclude_none=True)
        freight_no = (payload.freight_no or "").strip() or await self.sequence_service.next_code("FREIGHT_NO")
        if await self.repo.exists_freight_no(freight_no):
            raise ConflictError(f"freight_no already exists: {freight_no}")
        data.update(
            {
                "freight_no": freight_no,
                "source_type_code": "MANUAL",
                "source_channel_code": "MANUAL_FORM",
                "cargo_title": payload.cargo_title.strip(),
                "audit_status": "APPROVED",
                "confirmed_at": datetime.utcnow(),
            }
        )
        if data.get("status_code") == "PUBLISHED" and data.get("published_at") is None:
            data["published_at"] = datetime.utcnow()
        if data.get("hall_status_code") == "PUBLISHED" and data.get("hall_published_at") is None:
            data["hall_published_at"] = datetime.utcnow()
        row = await self.repo.create_freight(data)
        await self.db.commit()
        ctx = await _load_display_context(self.db, freights=[row])
        return _to_freight_response(row, ctx)

    async def update_freight(self, freight_id: int, payload) -> FreightResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        if updates.get("hall_status_code") == "PUBLISHED" and updates.get("hall_published_at") is None:
            updates["hall_published_at"] = datetime.utcnow()
            updates["hall_unpublished_at"] = None
        if updates.get("hall_status_code") == "UNPUBLISHED" and updates.get("hall_unpublished_at") is None:
            updates["hall_unpublished_at"] = datetime.utcnow()
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
        source_batch = await self.batch_repo.get_by_id(freight.source_batch_id) if freight.source_batch_id else None
        source_tms = await self.tms_repo.get_by_id(freight.source_tms_inbound_id) if freight.source_tms_inbound_id else None
        source_clue = await self.clue_repo.get_by_id(freight.source_clue_id) if freight.source_clue_id else None
        source_candidate = await self.candidate_repo.get_by_id(freight.source_candidate_id) if freight.source_candidate_id else None
        feedback_rows = await self.feedback_repo.list_by_candidate_ids([source_candidate.id] if source_candidate else [])
        ctx = await _load_display_context(
            self.db,
            freights=[freight],
            candidates=[source_candidate] if source_candidate is not None else [],
            batches=[source_batch] if source_batch is not None else [],
            tms_inbounds=[source_tms] if source_tms is not None else [],
            clues=[source_clue] if source_clue is not None else [],
            feedback=feedback_rows,
        )
        return FreightDetailResponse(
            profile=_to_freight_response(freight, ctx),
            contacts=[_to_contact_response(item) for item in contacts],
            attachments=[_to_attachment_response(item) for item in attachments],
            tags=[_to_tag_response(item) for item in tags],
            source_batch=_to_batch_response(source_batch, ctx) if source_batch is not None else None,
            source_tms_inbound=_to_tms_response(source_tms, ctx) if source_tms is not None else None,
            source_clue=_to_clue_response(source_clue, ctx) if source_clue is not None else None,
            source_candidate=_to_candidate_response(source_candidate, ctx) if source_candidate is not None else None,
            confirmation_records=[_to_feedback_response(item, source_candidate, ctx) for item in feedback_rows],
        )

    async def change_freight_status(self, freight_id: int, status_code: str) -> None:
        ok = await self.repo.update_freight_status(freight_id, status_code)
        if not ok:
            raise NotFoundError("Freight", freight_id)
        await self.db.commit()


class FreightBatchTaskService(FreightNormalizationMixin):
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = FreightBatchTaskRepository(db)
        self.clue_repo = FreightClueRepository(db)
        self.candidate_repo = FreightCandidateRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def list_items(
        self,
        *,
        keyword: str | None,
        status_code: str | None,
        page: int,
        page_size: int,
    ) -> PageResponse[FreightBatchResponse]:
        rows, total = await self.repo.list_items(keyword=keyword, status_code=status_code, page=page, page_size=page_size)
        ctx = await _load_display_context(self.db, batches=rows)
        ctx["batch_candidate_summary"] = await self._batch_candidate_summary([int(item.id) for item in rows])
        return PageResponse[FreightBatchResponse](total=total, page=page, page_size=page_size, items=[_to_batch_response(item, ctx) for item in rows])

    async def _batch_candidate_summary(self, batch_ids: list[int]) -> dict[int, dict[str, Any]]:
        rows = await self.candidate_repo.list_by_batch_ids(batch_ids)
        summary: dict[int, dict[str, Any]] = {}
        for item in rows:
            if item.source_batch_id is None:
                continue
            data = summary.setdefault(
                int(item.source_batch_id),
                {
                    "pending_count": 0,
                    "confirmed_count": 0,
                    "rejected_count": 0,
                    "ready_count": 0,
                    "review_count": 0,
                    "routes": [],
                    "contacts": set(),
                },
            )
            if item.status_code == "PENDING":
                data["pending_count"] += 1
            if item.status_code == "CONFIRMED":
                data["confirmed_count"] += 1
            if item.status_code == "REJECTED":
                data["rejected_count"] += 1
            if item.availability_status_code == "READY":
                data["ready_count"] += 1
            elif item.status_code == "PENDING":
                data["review_count"] += 1
            origin = item.raw_origin_text or item.origin_city_code or "-"
            dest = item.raw_destination_text or item.destination_city_code or "-"
            commodity = item.raw_commodity_name or item.commodity_match_name or ""
            data["routes"].append(f"{origin}->{dest}{f' {commodity}' if commodity else ''}")
            if item.contact_phone:
                data["contacts"].add(f"{item.contact_name or ''}{item.contact_phone}".strip())
        for data in summary.values():
            routes = data.pop("routes")
            contacts = sorted(data.pop("contacts"))
            data["route_summary"] = "；".join(routes[:3]) + ("..." if len(routes) > 3 else "") if routes else None
            data["contact_summary"] = "、".join(contacts[:3]) if contacts else None
        return summary

    async def create_wechat_batch(self, payload, creator_id: int | None) -> FreightBatchResponse:
        batch_no = (payload.batch_no or "").strip() or await self.sequence_service.next_code("FREIGHT_BATCH_NO")
        row = await self.repo.create(
            {
                "batch_no": batch_no,
                "source_type_code": "WECHAT",
                "source_channel_code": "WECHAT_TEXT",
                "raw_text": payload.raw_text.strip(),
                "status_code": "NEW",
                "creator_id": creator_id,
                "remark": payload.remark,
            }
        )
        await self.db.commit()
        ctx = await _load_display_context(self.db, batches=[row])
        return _to_batch_response(row, ctx)

    async def get_detail(self, batch_id: int) -> FreightBatchDetailResponse:
        batch = await self.repo.get_by_id(batch_id)
        if batch is None:
            raise NotFoundError("FreightBatchTask", batch_id)
        clues = await self.clue_repo.list_by_batch(batch_id)
        candidates = await self.candidate_repo.list_by_batch(batch_id)
        ctx = await _load_display_context(self.db, batches=[batch], clues=clues, candidates=candidates)
        ctx["batch_candidate_summary"] = await self._batch_candidate_summary([batch_id])
        return FreightBatchDetailResponse(
            batch=_to_batch_response(batch, ctx),
            clues=[_to_clue_response(item, ctx) for item in clues],
            candidates=[_to_candidate_response(item, ctx) for item in candidates],
        )

    async def parse(self, batch_id: int, requested_by: int | None = None) -> FreightBatchDetailResponse:
        batch = await self.repo.get_by_id(batch_id)
        if batch is None:
            raise NotFoundError("FreightBatchTask", batch_id)
        if batch.status_code == "PARSING":
            return await self.get_detail(batch_id)
        await self.repo.update(batch_id, {"status_code": "QUEUED", "error_message": None, "finished_at": None})
        await self.db.commit()
        try:
            from app.tasks.freight_ai_tasks import parse_wechat_batch_task

            parse_wechat_batch_task.delay(batch_id, requested_by)
        except Exception as exc:  # noqa: BLE001
            await self.repo.update(batch_id, {"status_code": "FAILED", "finished_at": datetime.utcnow(), "error_message": f"解析任务投递失败：{exc}"})
            await self.db.commit()
            raise ValidationError(f"解析任务投递失败：{exc}") from exc
        return await self.get_detail(batch_id)

    async def run_parse_now(self, batch_id: int, requested_by: int | None = None) -> FreightBatchDetailResponse:
        _ = requested_by
        batch = await self.repo.get_by_id(batch_id)
        if batch is None:
            raise NotFoundError("FreightBatchTask", batch_id)
        existing = await self.candidate_repo.list_by_batch(batch_id)
        if batch.status_code == "PARSED" and existing:
            return await self.get_detail(batch_id)
        clue_ids = await self.candidate_repo.delete_unconfirmed_by_batch(batch_id)
        await self.clue_repo.delete_by_ids(clue_ids)
        started = datetime.utcnow()
        await self.repo.update(batch_id, {"status_code": "PARSING", "started_at": started, "finished_at": None, "error_message": None})
        await self.db.commit()
        client = DashScopeQwenFreightParserClient(runtime_config=RuntimeConfigService(self.db))
        try:
            parsed = await client.parse(batch.raw_text, source_type_code="WECHAT")
            clue_count = 0
            candidate_count = 0
            failed_count = 0
            for index, segment in enumerate(parsed.segments, start=1):
                try:
                    clue = await self.clue_repo.create(
                        {
                            "clue_no": await self.sequence_service.next_code("FREIGHT_CLUE_NO"),
                            "source_type_code": "WECHAT",
                            "source_channel_code": "WECHAT_TEXT",
                            "source_batch_id": batch_id,
                            "source_tms_inbound_id": None,
                            "segment_index": index,
                            "raw_text": str(segment.get("raw_text") or batch.raw_text),
                            "context_summary": segment.get("context_summary"),
                            "extracted_fields_json": segment,
                            "quality_score": _to_decimal_or_none(segment.get("confidence_score")),
                            "status_code": "CANDIDATE_CREATED",
                        }
                    )
                    await self.candidate_repo.create(
                        await self._candidate_from_segment(
                            source_type_code="WECHAT",
                            source_channel_code="WECHAT_TEXT",
                            source_batch_id=batch_id,
                            source_tms_inbound_id=None,
                            clue_id=clue.id,
                            segment=segment,
                        )
                    )
                    clue_count += 1
                    candidate_count += 1
                except Exception:  # noqa: BLE001
                    failed_count += 1
                    continue
            status = "PARSED" if candidate_count and failed_count == 0 else "PARTIAL_FAILED" if candidate_count else "FAILED"
            await self.repo.update(
                batch_id,
                {
                    "status_code": status,
                    "clue_count": clue_count,
                    "candidate_count": candidate_count,
                    "success_count": candidate_count,
                    "failed_count": failed_count if candidate_count else 1,
                    "prompt_version": parsed.prompt_version,
                    "finished_at": datetime.utcnow(),
                    "raw_response_json": {"parsed_payload": parsed.parsed_payload, "raw_response": parsed.raw_response},
                },
            )
            await self.db.commit()
        except Exception as exc:
            message = str(exc)
            await self.db.rollback()
            await self.repo.update(batch_id, {"status_code": "FAILED", "finished_at": datetime.utcnow(), "error_message": message})
            await self.db.commit()
            raise
        return await self.get_detail(batch_id)


class FreightTmsInboundService(FreightNormalizationMixin):
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = FreightTmsInboundRepository(db)
        self.clue_repo = FreightClueRepository(db)
        self.candidate_repo = FreightCandidateRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def list_items(
        self,
        *,
        keyword: str | None,
        status_code: str | None,
        page: int,
        page_size: int,
    ) -> PageResponse[FreightTmsInboundResponse]:
        rows, total = await self.repo.list_items(keyword=keyword, status_code=status_code, page=page, page_size=page_size)
        ctx = await _load_display_context(self.db, tms_inbounds=rows)
        return PageResponse[FreightTmsInboundResponse](total=total, page=page, page_size=page_size, items=[_to_tms_response(item, ctx) for item in rows])

    async def create(self, payload) -> FreightTmsInboundResponse:
        existing = await self.repo.get_by_idempotency_key(payload.idempotency_key.strip())
        if existing is not None:
            ctx = await _load_display_context(self.db, tms_inbounds=[existing])
            return _to_tms_response(existing, ctx)
        inbound_no = (payload.inbound_no or "").strip() or await self.sequence_service.next_code("FREIGHT_TMS_INBOUND_NO")
        raw_content = (payload.raw_content or "").strip() or json.dumps(payload.payload_json, ensure_ascii=False)
        row = await self.repo.create(
            {
                "inbound_no": inbound_no,
                "source_type_code": "TMS",
                "source_channel_code": payload.source_channel_code,
                "source_trace_id": payload.source_trace_id,
                "idempotency_key": payload.idempotency_key.strip(),
                "external_ref_no": payload.external_ref_no,
                "payload_json": payload.payload_json,
                "raw_content": raw_content,
                "status_code": "NEW",
            }
        )
        await self.db.commit()
        ctx = await _load_display_context(self.db, tms_inbounds=[row])
        return _to_tms_response(row, ctx)

    async def get_detail(self, inbound_id: int) -> FreightTmsInboundDetailResponse:
        inbound = await self.repo.get_by_id(inbound_id)
        if inbound is None:
            raise NotFoundError("FreightTmsInbound", inbound_id)
        clues = await self.clue_repo.list_by_tms_inbound(inbound_id)
        candidates = await self.candidate_repo.list_by_tms_inbound(inbound_id)
        ctx = await _load_display_context(self.db, tms_inbounds=[inbound], clues=clues, candidates=candidates)
        return FreightTmsInboundDetailResponse(
            inbound=_to_tms_response(inbound, ctx),
            clues=[_to_clue_response(item, ctx) for item in clues],
            candidates=[_to_candidate_response(item, ctx) for item in candidates],
        )

    async def parse(self, inbound_id: int, requested_by: int | None = None) -> FreightTmsInboundDetailResponse:
        inbound = await self.repo.get_by_id(inbound_id)
        if inbound is None:
            raise NotFoundError("FreightTmsInbound", inbound_id)
        if inbound.status_code == "PARSING":
            return await self.get_detail(inbound_id)
        await self.repo.update(inbound_id, {"status_code": "QUEUED", "error_message": None})
        await self.db.commit()
        try:
            from app.tasks.freight_ai_tasks import parse_tms_inbound_task

            parse_tms_inbound_task.delay(inbound_id, requested_by)
        except Exception as exc:  # noqa: BLE001
            await self.repo.update(inbound_id, {"status_code": "FAILED", "processed_at": datetime.utcnow(), "error_message": f"解析任务投递失败：{exc}"})
            await self.db.commit()
            raise ValidationError(f"解析任务投递失败：{exc}") from exc
        return await self.get_detail(inbound_id)

    async def run_parse_now(self, inbound_id: int, requested_by: int | None = None) -> FreightTmsInboundDetailResponse:
        _ = requested_by
        inbound = await self.repo.get_by_id(inbound_id)
        if inbound is None:
            raise NotFoundError("FreightTmsInbound", inbound_id)
        existing = await self.candidate_repo.list_by_tms_inbound(inbound_id)
        if inbound.status_code == "PARSED" and existing:
            return await self.get_detail(inbound_id)
        clue_ids = await self.candidate_repo.delete_unconfirmed_by_tms_inbound(inbound_id)
        await self.clue_repo.delete_by_ids(clue_ids)
        await self.repo.update(inbound_id, {"status_code": "PARSING", "error_message": None})
        await self.db.commit()
        client = DashScopeQwenFreightParserClient(runtime_config=RuntimeConfigService(self.db))
        try:
            parsed = await client.parse(inbound.raw_content, source_type_code="TMS")
            clue_count = 0
            candidate_count = 0
            failed_count = 0
            for index, segment in enumerate(parsed.segments, start=1):
                try:
                    clue = await self.clue_repo.create(
                        {
                            "clue_no": await self.sequence_service.next_code("FREIGHT_CLUE_NO"),
                            "source_type_code": "TMS",
                            "source_channel_code": inbound.source_channel_code,
                            "source_batch_id": None,
                            "source_tms_inbound_id": inbound_id,
                            "segment_index": index,
                            "raw_text": str(segment.get("raw_text") or inbound.raw_content),
                            "context_summary": segment.get("context_summary"),
                            "extracted_fields_json": segment,
                            "quality_score": _to_decimal_or_none(segment.get("confidence_score")),
                            "status_code": "CANDIDATE_CREATED",
                        }
                    )
                    await self.candidate_repo.create(
                        await self._candidate_from_segment(
                            source_type_code="TMS",
                            source_channel_code=inbound.source_channel_code,
                            source_batch_id=None,
                            source_tms_inbound_id=inbound_id,
                            clue_id=clue.id,
                            segment=segment,
                        )
                    )
                    clue_count += 1
                    candidate_count += 1
                except Exception:  # noqa: BLE001
                    failed_count += 1
                    continue
            status = "PARSED" if candidate_count and failed_count == 0 else "PARTIAL_FAILED" if candidate_count else "FAILED"
            await self.repo.update(
                inbound_id,
                {
                    "status_code": status,
                    "clue_count": clue_count,
                    "candidate_count": candidate_count,
                    "processed_at": datetime.utcnow(),
                    "prompt_version": parsed.prompt_version,
                    "raw_response_json": {"parsed_payload": parsed.parsed_payload, "raw_response": parsed.raw_response},
                },
            )
            await self.db.commit()
        except Exception as exc:
            message = str(exc)
            await self.db.rollback()
            await self.repo.update(inbound_id, {"status_code": "FAILED", "processed_at": datetime.utcnow(), "error_message": message})
            await self.db.commit()
            raise
        return await self.get_detail(inbound_id)


class FreightCandidateService(FreightNormalizationMixin):
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = FreightCandidateRepository(db)
        self.feedback_repo = FreightCandidateManualFeedbackRepository(db)
        self.freight_repo = FreightRepository(db)
        self.contact_repo = FreightContactRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def list_items(
        self,
        *,
        keyword: str | None,
        status_code: str | None,
        source_type_code: str | None,
        page: int,
        page_size: int,
    ) -> PageResponse[FreightCandidateResponse]:
        rows, total = await self.repo.list_items(
            keyword=keyword,
            status_code=status_code,
            source_type_code=source_type_code,
            page=page,
            page_size=page_size,
        )
        ctx = await _load_display_context(self.db, candidates=rows)
        return PageResponse[FreightCandidateResponse](total=total, page=page, page_size=page_size, items=[_to_candidate_response(item, ctx) for item in rows])

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
        await self._enrich_location_updates(updates, "origin")
        await self._enrich_location_updates(updates, "destination")
        row = await self.repo.get_by_id(candidate_id)
        if row is None:
            raise NotFoundError("FreightCandidate", candidate_id)
        manual = dict(row.manual_overrides_json or {})
        manual.update(_compact_json_value(updates))
        updates["manual_overrides_json"] = manual
        row = await self.repo.update(candidate_id, updates)
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
        has_overrides = payload.overrides is not None and bool(payload.overrides.model_dump(exclude_none=True))
        if payload.overrides is not None:
            updates = payload.overrides.model_dump(exclude_none=True)
            if updates:
                await self._enrich_location_updates(updates, "origin")
                await self._enrich_location_updates(updates, "destination")
                manual = dict(candidate.manual_overrides_json or {})
                manual.update(_compact_json_value(updates))
                updates["manual_overrides_json"] = manual
                candidate = await self.repo.update(candidate_id, updates) or candidate
                action_code = "EDIT_CONFIRM"
        self._validate_candidate_ready(candidate, allow_review_override=has_overrides)
        now = datetime.utcnow()
        freight = await self.freight_repo.create_freight(
            {
                "freight_no": await self.sequence_service.next_code("FREIGHT_NO"),
                "source_type_code": candidate.source_type_code,
                "source_channel_code": candidate.source_channel_code,
                "source_ref_no": candidate.source_ref_no or candidate.candidate_no,
                "source_batch_id": candidate.source_batch_id,
                "source_tms_inbound_id": candidate.source_tms_inbound_id,
                "source_clue_id": candidate.clue_id,
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
                "hall_status_code": "NOT_LISTED",
                "audit_status": "APPROVED",
            }
        )
        candidate = await self.repo.update(
            candidate.id,
            {"status_code": "CONFIRMED", "confirmed_freight_id": freight.id, "confirmed_at": now},
        ) or candidate
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

    async def bulk_confirm_batch(self, batch_id: int, operator_id: int | None) -> FreightCandidateBulkConfirmResponse:
        rows = await self.repo.list_by_batch(batch_id)
        confirmed_ids: list[int] = []
        skipped: list[dict[str, Any]] = []
        for row in rows:
            if row.status_code != "PENDING":
                skipped.append({"candidate_id": row.id, "candidate_no": row.candidate_no, "reason": "不是待确认状态"})
                continue
            if row.availability_status_code != "READY":
                skipped.append({"candidate_id": row.id, "candidate_no": row.candidate_no, "reason": row.manual_review_reason or "需要人工编辑确认"})
                continue
            try:
                freight = await self.confirm(row.id, type("Payload", (), {"remark": "批次一键确认入库", "overrides": None})(), operator_id)
                confirmed_ids.append(freight.id)
            except Exception as exc:  # noqa: BLE001
                skipped.append({"candidate_id": row.id, "candidate_no": row.candidate_no, "reason": str(exc)})
        return FreightCandidateBulkConfirmResponse(
            batch_id=batch_id,
            confirmed_count=len(confirmed_ids),
            skipped_count=len(skipped),
            freight_ids=confirmed_ids,
            skipped=skipped,
        )

    @staticmethod
    def _candidate_snapshot_fields() -> list[str]:
        return [
            "candidate_no",
            "cargo_title",
            "commodity_standard_id",
            "origin_node_id",
            "origin_city_code",
            "destination_node_id",
            "destination_city_code",
            "estimated_tonnage",
            "unit_price",
            "availability_status_code",
            "manual_review_reason",
            "status_code",
        ]

    @staticmethod
    def _validate_candidate_ready(candidate, *, allow_review_override: bool = False) -> None:
        if candidate.availability_status_code != "READY" and not allow_review_override:
            reason = candidate.manual_review_reason or "AI 未判断为可直接发布"
            raise ValidationError(f"候选货源需要编辑确认后才能入库：{reason}")
        missing: list[str] = []
        if candidate.commodity_standard_id is None:
            missing.append("标准货品")
        if not candidate.origin_province_code or not candidate.origin_city_code:
            missing.append("装货城市")
        if not candidate.destination_province_code or not candidate.destination_city_code:
            missing.append("卸货城市")
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
