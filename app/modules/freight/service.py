"""freight 模块 service。"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.integrations.config_keys import DASHSCOPE_CONFIG_PROFILE, FREIGHT_AI_STALE_HEARTBEAT_SECONDS
from app.integrations.ai import DashScopeQwenFreightParserClient
from app.integrations.ai.dashscope_qwen_client import _prepare_segments
from app.models.address import AdminRegion, NodeAlias, Region, RegionCityRelation, TransportNode
from app.models.commodity import CommodityAlias, CommodityStandard
from app.models.dictionary import StdDict, StdDictItem
from app.models.freight import Freight, FreightCandidate, FreightContact, FreightNormalizationSuggestion, FreightNormalizationTask
from app.modules.dictionary.service import CodeSequenceService
from app.modules.freight.ai_semantic_validator import FreightSemanticValidator
from app.modules.freight.ai_text_index import FreightTextIndexer
from app.modules.freight.master_data_matcher import FreightMasterDataBatchMatcher
from app.modules.freight.repository import (
    FreightAttachmentRepository,
    FreightBatchTaskRepository,
    FreightCandidateManualFeedbackRepository,
    FreightCandidateRepository,
    FreightClueRepository,
    FreightContactRepository,
    FreightNormalizationSuggestionRepository,
    FreightNormalizationTaskRepository,
    FreightRepository,
    FreightTagRelationRepository,
    FreightTmsInboundRepository,
)
from app.modules.freight.schemas import (
    FreightAttachmentResponse,
    FreightBatchDetailResponse,
    FreightBatchHandoffResponse,
    FreightBatchResponse,
    FreightCandidateBulkConfirmResponse,
    FreightCandidateResponse,
    FreightClueResponse,
    FreightConfirmationResponse,
    FreightContactResponse,
    FreightDetailResponse,
    FreightNormalizationCleanResponse,
    FreightNormalizationBulkApplyResponse,
    FreightNormalizationTaskResponse,
    FreightNormalizationQualityResponse,
    FreightNormalizationSuggestionResponse,
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
    "FREIGHT_BATCH_REVIEW_FLOW",
    "FREIGHT_TMS_INBOUND_STATUS",
    "FREIGHT_CLUE_STATUS",
    "FREIGHT_CANDIDATE_STATUS",
    "FREIGHT_CONFIRM_ACTION",
    "FREIGHT_MATCH_LEVEL",
    "FREIGHT_HALL_STATUS",
    "FREIGHT_AVAILABILITY_STATUS",
    "FREIGHT_AI_REVIEW_STATUS",
]

AI_REVIEW_PASS = "PASS"
AI_REVIEW_REQUIRED = "REVIEW_REQUIRED"
AI_REVIEW_MANUAL_ACCEPTED = "MANUAL_ACCEPTED"
FREIGHT_AI_PIPELINE_VERSION = "freight_ai_semantic_pipeline_v2"


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


def _segment_core_missing(segment: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not str(_first(segment, "origin_text", "loading_place", "origin", "from") or "").strip():
        missing.append("装货地")
    if not str(_first(segment, "destination_text", "unloading_place", "destination", "to") or "").strip():
        missing.append("卸货地")
    if not str(_first(segment, "commodity_name", "cargo_name", "goods_name", "cargo") or "").strip():
        missing.append("货品")
    return missing


def _segment_route_missing(segment: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not str(_first(segment, "origin_text", "loading_place", "origin", "from") or "").strip():
        missing.append("装货地")
    if not str(_first(segment, "destination_text", "unloading_place", "destination", "to") or "").strip():
        missing.append("卸货地")
    return missing


def _append_reason(current: Any, reason: str) -> str:
    text = str(current or "").strip()
    if not text:
        return reason
    return text if reason in text else f"{text}；{reason}"


def _segment_ignore_reason(segment: dict[str, Any]) -> str | None:
    if segment.get("is_freight_candidate") is False or segment.get("drop_reason"):
        return str(segment.get("drop_reason") or "AI 判断该片段不是完整货源线索")
    missing = _segment_route_missing(segment)
    semantic_role = str(_first(segment, "semantic_role_code", "role_code") or "ROUTE").strip().upper()
    if missing and semantic_role != "ROUTE":
        return f"AI 输出不是可追溯路线线索，缺少{','.join(missing)}"
    return None


def _candidate_ai_review_pass(candidate: FreightCandidate) -> bool:
    return str(getattr(candidate, "ai_review_status_code", None) or AI_REVIEW_PASS).upper() == AI_REVIEW_PASS


def _candidate_ai_review_reason(candidate: FreightCandidate) -> str | None:
    review = getattr(candidate, "ai_review_json", None)
    if isinstance(review, dict):
        for key in ("reason", "review_reason", "summary"):
            value = review.get(key)
            if value not in (None, ""):
                return str(value)
    return getattr(candidate, "manual_review_reason", None)


def _derive_segment_ai_review(segment: dict[str, Any], *, availability_status: str, manual_review_reason: Any) -> tuple[str, str | None, list[str]]:
    checks: list[str] = []
    reason = str(manual_review_reason or "").strip() or None
    explicit_status = str(
        _first(segment, "ai_review_status_code", "review_status_code", "business_review_status_code") or ""
    ).strip().upper()
    if explicit_status and explicit_status != AI_REVIEW_PASS:
        reason = _append_reason(reason, str(_first(segment, "ai_review_reason", "review_reason") or "AI 裁决需人工判断"))
        checks.append("AI_REVIEW_FLAG")
    if bool(segment.get("needs_strong_review")):
        reason = _append_reason(reason, "AI 复核标记需人工判断")
        checks.append("STRONG_REVIEW_FLAG")
    if str(availability_status or "").upper() != "READY":
        reason = _append_reason(reason, "AI 未判断为可直接确认")
        checks.append("NOT_READY")
    missing = _segment_core_missing(segment)
    if missing:
        reason = _append_reason(reason, f"缺少{','.join(missing)}，无法直接确认")
        checks.append("CORE_FIELDS_MISSING")
    return (AI_REVIEW_REQUIRED, reason, checks) if reason else (AI_REVIEW_PASS, None, checks)


def _parse_heartbeat_age_seconds(entity) -> int | None:
    heartbeat = entity.parse_heartbeat_at
    if heartbeat is None:
        return None
    return max(0, int((datetime.utcnow() - heartbeat).total_seconds()))


def _derive_batch_review_flow(entity, summary: dict[str, Any]) -> str:
    stored = str(getattr(entity, "review_flow_status_code", "") or "").upper()
    pending = int(summary.get("pending_count") or 0)
    candidate_count = int(summary.get("candidate_count") or entity.candidate_count or 0)
    handled = int(summary.get("confirmed_count") or 0) + int(summary.get("rejected_count") or 0)
    if stored == "QUEUED_FOR_REVIEW" and pending > 0:
        return "QUEUED_FOR_REVIEW"
    if candidate_count > 0 and pending == 0 and handled >= candidate_count:
        return "COMPLETED"
    return "REVIEWING"


def _derive_batch_next_action(entity, summary: dict[str, Any], *, parse_is_stale: bool) -> tuple[str, str]:
    status = str(entity.status_code or "").upper()
    review_flow = _derive_batch_review_flow(entity, summary)
    pending = int(summary.get("pending_count") or 0)
    candidate_count = int(summary.get("candidate_count") or entity.candidate_count or 0)
    if status in {"QUEUED", "PARSING"} and not parse_is_stale:
        return "VIEW_PARSE_PROGRESS", "查看解析进度"
    if parse_is_stale or status in {"NEW", "FAILED"}:
        return "RETRY_PARSE", "重新解析"
    if review_flow == "QUEUED_FOR_REVIEW" and pending > 0:
        return "OPEN_PENDING_QUEUE", "去待确认货源"
    if pending > 0:
        return "REVIEW_IN_BATCH", "进入确认"
    if candidate_count > 0:
        return "VIEW_RESULT", "查看结果"
    return "VIEW_DETAIL", "查看详情"


async def _load_display_context(
    db: AsyncSession,
    *,
    freights: list[Any] | None = None,
    candidates: list[Any] | None = None,
    batches: list[Any] | None = None,
    tms_inbounds: list[Any] | None = None,
    clues: list[Any] | None = None,
    feedback: list[Any] | None = None,
    suggestions: list[Any] | None = None,
) -> dict[str, Any]:
    freights = freights or []
    candidates = candidates or []
    batches = batches or []
    tms_inbounds = tms_inbounds or []
    clues = clues or []
    feedback = feedback or []
    suggestions = suggestions or []

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
    commodity_ids.update(
        item.suggested_commodity_standard_id
        for item in suggestions
        if getattr(item, "suggested_commodity_standard_id", None) is not None
    )
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
    node_ids.update(item.suggested_node_id for item in suggestions if getattr(item, "suggested_node_id", None) is not None)
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
    city_codes.update(item.suggested_city_code for item in suggestions if getattr(item, "suggested_city_code", None))
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
    region_ids.update(item.suggested_region_id for item in suggestions if getattr(item, "suggested_region_id", None) is not None)

    freight_ids = {item.freight_id for item in suggestions if getattr(item, "freight_id", None) is not None}
    freight_ids.update(item.id for item in freights if getattr(item, "id", None) is not None)
    freights_by_id: dict[int, Freight] = {}
    if freight_ids:
        rows = (await db.execute(select(Freight).where(Freight.id.in_(freight_ids)))).scalars().all()
        freights_by_id = {int(row.id): row for row in rows}
    contacts_by_freight_id: dict[int, list[FreightContact]] = {}
    if freight_ids:
        contact_rows = (
            await db.execute(
                select(FreightContact)
                .where(FreightContact.freight_id.in_(freight_ids))
                .order_by(FreightContact.is_primary.desc(), FreightContact.id.asc())
            )
        ).scalars().all()
        for contact in contact_rows:
            contacts_by_freight_id.setdefault(int(contact.freight_id), []).append(contact)
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
        "freights_by_id": freights_by_id,
        "contacts_by_freight_id": contacts_by_freight_id,
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


def _location_summary(entity: Any, ctx: dict[str, Any], prefix: str) -> str:
    node_name = _node_name(ctx, getattr(entity, f"{prefix}_node_id", None))
    city_name = _city_name(ctx, getattr(entity, f"{prefix}_city_code", None))
    raw_text = getattr(entity, f"raw_{prefix}_text", None)
    if node_name:
        return node_name
    if city_name:
        return city_name
    return str(raw_text or "-")


def _tonnage_summary(entity: Any) -> str | None:
    raw = getattr(entity, "raw_tonnage_text", None)
    minimum = getattr(entity, "min_tonnage", None)
    maximum = getattr(entity, "max_tonnage", None)
    estimated = getattr(entity, "estimated_tonnage", None)
    if minimum is not None and maximum is not None:
        return f"{minimum}-{maximum} 吨"
    if estimated is not None:
        return f"{estimated} 吨"
    return raw


def _price_summary(entity: Any) -> str | None:
    unit_price = getattr(entity, "unit_price", None)
    total_price = getattr(entity, "total_price", None)
    price_unit = getattr(entity, "price_unit", None) or "元/吨"
    if unit_price is not None:
        return f"{unit_price} {price_unit}"
    if total_price is not None:
        return f"总价 {total_price}"
    return None


def _freight_preview(entity: Freight, ctx: dict[str, Any]) -> dict[str, Any]:
    contacts = ctx.get("contacts_by_freight_id", {}).get(int(entity.id), [])
    contact_summary = "、".join(
        f"{item.contact_name}{f' {item.mobile_phone}' if item.mobile_phone else ''}".strip()
        for item in contacts[:2]
    ) or None
    commodity = _commodity(ctx, entity.commodity_standard_id)
    commodity_summary = commodity.name if commodity is not None else (entity.raw_commodity_name or entity.cargo_title)
    origin = _location_summary(entity, ctx, "origin")
    destination = _location_summary(entity, ctx, "destination")
    return {
        "freight_no": entity.freight_no,
        "route_summary": f"{origin} 至 {destination}",
        "commodity_summary": commodity_summary,
        "tonnage_summary": _tonnage_summary(entity),
        "price_summary": _price_summary(entity),
        "contact_summary": contact_summary,
        "source_summary": _label(ctx, "SOURCE_TYPE", entity.source_type_code) or entity.source_type_code,
        "match_summary": f"装货{entity.origin_match_level_code or '-'} / 卸货{entity.destination_match_level_code or '-'} / 货品{entity.commodity_match_level_code or '-'}",
        "cargo_title": entity.cargo_title,
        "raw_origin_text": entity.raw_origin_text,
        "raw_destination_text": entity.raw_destination_text,
        "raw_commodity_name": entity.raw_commodity_name,
    }


def _to_normalization_task_response(entity: FreightNormalizationTask) -> FreightNormalizationTaskResponse:
    return FreightNormalizationTaskResponse(
        id=entity.id,
        task_no=entity.task_no,
        celery_task_id=entity.celery_task_id,
        status_code=entity.status_code,
        stage_code=entity.stage_code,
        stage_name=entity.stage_name,
        stage_message=entity.stage_message,
        progress_percent=entity.progress_percent,
        scanned_count=entity.scanned_count,
        suggestion_count=entity.suggestion_count,
        auto_applied_count=entity.auto_applied_count,
        pending_count=entity.pending_count,
        failed_count=entity.failed_count,
        requested_by=entity.requested_by,
        started_at=entity.started_at,
        finished_at=entity.finished_at,
        heartbeat_at=entity.heartbeat_at,
        error_message=entity.error_message,
        result_json=entity.result_json,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


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
        raw_commodity_name=entity.raw_commodity_name,
        raw_tonnage_text=entity.raw_tonnage_text,
        raw_origin_text=entity.raw_origin_text,
        raw_destination_text=entity.raw_destination_text,
        cargo_title=entity.cargo_title,
        cargo_description=entity.cargo_description,
        commodity_standard_id=entity.commodity_standard_id,
        commodity_standard_code=commodity.code if commodity is not None else None,
        commodity_standard_name=commodity.name if commodity is not None else None,
        commodity_match_level_code=entity.commodity_match_level_code,
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
        origin_match_level_code=entity.origin_match_level_code,
        destination_match_level_code=entity.destination_match_level_code,
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
    stale_seconds = int(ctx.get("stale_heartbeat_seconds") or settings.FREIGHT_AI_STALE_HEARTBEAT_SECONDS)
    heartbeat_age = _parse_heartbeat_age_seconds(entity)
    parse_is_stale = (
        str(entity.status_code or "").upper() == "PARSING"
        and (heartbeat_age is None or heartbeat_age >= max(30, stale_seconds))
    )
    review_flow = _derive_batch_review_flow(entity, summary)
    next_action_code, next_action_name = _derive_batch_next_action(entity, summary, parse_is_stale=parse_is_stale)
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
        review_flow_status_code=review_flow,
        review_flow_status_name=_label(ctx, "FREIGHT_BATCH_REVIEW_FLOW", review_flow),
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
        ai_pipeline_version=getattr(entity, "ai_pipeline_version", None),
        ai_semantic_map_json=getattr(entity, "ai_semantic_map_json", None),
        parse_stage_code=entity.parse_stage_code,
        parse_stage_name=entity.parse_stage_name,
        parse_stage_message=entity.parse_stage_message,
        parse_progress_percent=entity.parse_progress_percent,
        parse_heartbeat_at=entity.parse_heartbeat_at,
        parse_is_stale=parse_is_stale,
        parse_heartbeat_age_seconds=heartbeat_age,
        next_action_code=next_action_code,
        next_action_name=next_action_name,
        ai_elapsed_seconds=entity.ai_elapsed_seconds,
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
        semantic_role_code=getattr(entity, "semantic_role_code", None),
        raw_text=entity.raw_text,
        line_refs_json=getattr(entity, "line_refs_json", None),
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
        raw_tonnage_text=entity.raw_tonnage_text,
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
        ai_understanding_json=getattr(entity, "ai_understanding_json", None),
        ai_tool_match_json=getattr(entity, "ai_tool_match_json", None),
        ai_review_json=getattr(entity, "ai_review_json", None),
        ai_review_status_code=getattr(entity, "ai_review_status_code", None) or AI_REVIEW_PASS,
        ai_review_status_name=_label(ctx, "FREIGHT_AI_REVIEW_STATUS", getattr(entity, "ai_review_status_code", None) or AI_REVIEW_PASS),
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


def _to_normalization_suggestion_response(
    entity: FreightNormalizationSuggestion, ctx: dict[str, Any] | None = None
) -> FreightNormalizationSuggestionResponse:
    ctx = ctx or {}
    freight = ctx.get("freights_by_id", {}).get(int(entity.freight_id))
    commodity = _commodity(ctx, entity.suggested_commodity_standard_id)
    preview = _freight_preview(freight, ctx) if freight is not None else {}
    return FreightNormalizationSuggestionResponse(
        id=entity.id,
        clean_task_id=entity.clean_task_id,
        freight_id=entity.freight_id,
        freight_no=freight.freight_no if freight is not None else None,
        cargo_title=freight.cargo_title if freight is not None else None,
        freight_route_summary=preview.get("route_summary"),
        freight_commodity_summary=preview.get("commodity_summary"),
        freight_tonnage_summary=preview.get("tonnage_summary"),
        freight_price_summary=preview.get("price_summary"),
        freight_contact_summary=preview.get("contact_summary"),
        freight_source_summary=preview.get("source_summary"),
        freight_match_summary=preview.get("match_summary"),
        freight_detail_preview=preview or None,
        suggestion_type_code=entity.suggestion_type_code,
        raw_text=entity.raw_text,
        current_level_code=entity.current_level_code,
        suggested_level_code=entity.suggested_level_code,
        suggested_node_id=entity.suggested_node_id,
        suggested_node_name=_node_name(ctx, entity.suggested_node_id),
        suggested_commodity_standard_id=entity.suggested_commodity_standard_id,
        suggested_commodity_standard_name=commodity.name if commodity is not None else None,
        suggested_province_code=entity.suggested_province_code,
        suggested_city_code=entity.suggested_city_code,
        suggested_city_name=_city_name(ctx, entity.suggested_city_code),
        suggested_district_code=entity.suggested_district_code,
        suggested_region_id=entity.suggested_region_id,
        suggested_region_name=_region_name(ctx, entity.suggested_region_id),
        confidence_score=entity.confidence_score,
        status_code=entity.status_code,
        auto_apply_flag=entity.auto_apply_flag,
        match_basis_json=entity.match_basis_json,
        before_json=entity.before_json,
        after_json=entity.after_json,
        applied_at=entity.applied_at,
        applied_by=entity.applied_by,
        rejected_at=entity.rejected_at,
        rejected_by=entity.rejected_by,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
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
        level_key = f"{prefix}_match_level_code"
        requested_level = str(updates.get(level_key) or "").upper()
        if requested_level == "RAW":
            updates[node_key] = None
            updates[province_key] = None
            updates[city_key] = None
            updates[district_key] = None
            updates[region_key] = None
            updates[level_key] = "RAW"
            return
        if requested_level == "CITY":
            updates[node_key] = None
        if node_key in updates and updates.get(node_key):
            node = await self._node_by_id(updates[node_key])
            if node is not None:
                updates[province_key] = node.province_code
                updates[city_key] = node.city_code
                updates[district_key] = node.district_code
                updates[region_key] = await self._business_region_id(node.city_region_id)
                updates[level_key] = "NODE"
            return
        if node_key in updates and updates.get(node_key) is None and requested_level != "CITY":
            updates[province_key] = None
            updates[city_key] = None
            updates[district_key] = None
            updates[region_key] = None
            updates[level_key] = requested_level or "RAW"
        if city_key in updates and updates.get(city_key):
            city = await self._city_by_code(updates[city_key])
            if city is not None:
                updates[node_key] = None
                updates[province_key] = city.province_code or city.code[:2].ljust(6, "0")
                updates[district_key] = None
                updates[region_key] = await self._business_region_id(city.id)
                updates[level_key] = "CITY"

    async def _enrich_commodity_updates(self, updates: dict[str, Any]) -> None:
        if str(updates.get("commodity_match_level_code") or "").upper() == "RAW":
            updates["commodity_standard_id"] = None
            updates["commodity_match_level_code"] = "RAW"
            return
        if "commodity_standard_id" in updates and updates.get("commodity_standard_id"):
            standard = await self.db.scalar(
                select(CommodityStandard).where(
                    CommodityStandard.id == updates["commodity_standard_id"],
                    CommodityStandard.deleted_at.is_(None),
                )
            )
            if standard is not None:
                updates["commodity_match_level_code"] = "STANDARD"
        elif "commodity_standard_id" in updates and updates.get("commodity_standard_id") is None:
            updates["commodity_match_level_code"] = updates.get("commodity_match_level_code") or "RAW"

    @staticmethod
    def _fill_default_raw_levels(data: dict[str, Any]) -> None:
        if not data.get("commodity_match_level_code"):
            data["commodity_match_level_code"] = "STANDARD" if data.get("commodity_standard_id") is not None else "RAW"
        if not data.get("origin_match_level_code"):
            if data.get("origin_node_id") is not None:
                data["origin_match_level_code"] = "NODE"
            elif data.get("origin_city_code"):
                data["origin_match_level_code"] = "CITY"
            elif data.get("raw_origin_text"):
                data["origin_match_level_code"] = "RAW"
        if not data.get("destination_match_level_code"):
            if data.get("destination_node_id") is not None:
                data["destination_match_level_code"] = "NODE"
            elif data.get("destination_city_code"):
                data["destination_match_level_code"] = "CITY"
            elif data.get("raw_destination_text"):
                data["destination_match_level_code"] = "RAW"

    async def _match_commodity(self, raw_name: str) -> tuple[int | None, Decimal | None, str | None, list[dict[str, Any]], dict[str, Any]]:
        text = raw_name.strip()
        if not text:
            return None, None, None, [], {"status": "NO_TEXT"}
        standards = (
            await self.db.execute(
                select(CommodityStandard).where(
                    CommodityStandard.deleted_at.is_(None),
                    CommodityStandard.is_active.is_(True),
                )
            )
        ).scalars().all()
        standard_by_id = {int(item.id): item for item in standards}
        standard_ids = list(standard_by_id)
        aliases = []
        if standard_ids:
            aliases = (
                await self.db.execute(
                    select(CommodityAlias).where(
                        CommodityAlias.is_enabled.is_(True),
                        CommodityAlias.commodity_standard_id.in_(standard_ids),
                    )
                )
            ).scalars().all()
        options: list[dict[str, Any]] = []
        for standard in standards:
            score = None
            level = None
            if text == standard.name or text == (standard.short_name or ""):
                score, level = Decimal("1.0"), "STANDARD"
            elif text in standard.name or standard.name in text:
                score, level = Decimal("0.82"), "STANDARD"
            if score is not None:
                priority_boost = Decimal(str(max(min(standard.recognition_priority or 50, 100), 0))) / Decimal("1000")
                score = min(score + priority_boost, Decimal("1.0"))
                options.append(
                    {
                        "id": int(standard.id),
                        "code": standard.code,
                        "name": standard.name,
                        "category_id": int(standard.category_id) if standard.category_id is not None else None,
                        "type_id": int(standard.type_id) if standard.type_id is not None else None,
                        "score": str(score),
                        "match_level_code": level,
                        "basis": "标准名称/简称",
                        "matched_text": text,
                    }
                )
        for alias in aliases:
            score = None
            if text == alias.alias_name:
                score = Decimal("1.0")
            elif text in alias.alias_name or alias.alias_name in text:
                score = Decimal("0.80")
            if score is not None:
                standard = standard_by_id.get(int(alias.commodity_standard_id))
                if standard is None:
                    continue
                weight_boost = Decimal(str(max(min(alias.match_weight or 80, 100), 0))) / Decimal("1000")
                priority_boost = Decimal(str(max(min(standard.recognition_priority or 50, 100), 0))) / Decimal("1000")
                score = min(score + weight_boost + priority_boost, Decimal("1.0"))
                options.append(
                    {
                        "id": int(alias.commodity_standard_id),
                        "code": standard.code,
                        "name": standard.name,
                        "category_id": int(standard.category_id) if standard.category_id is not None else None,
                        "type_id": int(standard.type_id) if standard.type_id is not None else None,
                        "score": str(score),
                        "match_level_code": "ALIAS",
                        "basis": f"启用别名:{alias.alias_name}",
                        "alias_type_code": alias.alias_type_code,
                        "matched_text": alias.alias_name,
                    }
                )
        dedup: dict[int, dict[str, Any]] = {}
        for option in sorted(options, key=lambda item: Decimal(str(item["score"])), reverse=True):
            dedup.setdefault(int(option["id"]), option)
        ordered = list(dedup.values())[:5]
        if not ordered:
            return None, Decimal("0.0"), "RAW", [{"level": "RAW", "name": text, "score": "0.0"}], {"status": "UNMATCHED", "text": text}
        first = ordered[0]
        return int(first["id"]), Decimal(str(first["score"])), str(first["match_level_code"]), ordered, {"status": "MATCHED", "text": text, "top": first}

    async def _match_location(
        self, raw_text: str, ai_level_code: str | None = None
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        text = raw_text.strip()
        if not text:
            return {}, [], {"status": "NO_TEXT"}
        ai_level = str(ai_level_code or "").strip().upper()
        if ai_level not in {"NODE", "CITY", "RAW"}:
            ai_level = ""
        nodes = (await self.db.execute(select(TransportNode).where(TransportNode.deleted_at.is_(None)))).scalars().all()
        aliases = (await self.db.execute(select(NodeAlias))).scalars().all()
        cities = (await self.db.execute(select(AdminRegion).where(AdminRegion.level == 2, AdminRegion.status == 1))).scalars().all()
        exact_node_options: list[dict[str, Any]] = []
        strong_node_options: list[dict[str, Any]] = []
        weak_node_options: list[dict[str, Any]] = []
        city_options: list[dict[str, Any]] = []
        exact_city_options: list[dict[str, Any]] = []

        async def make_node_option(node, *, score: Decimal, basis: str, strength: str) -> dict[str, Any]:
            return {
                "level": "NODE",
                "node_id": int(node.id),
                "node_name": node.name,
                "city_code": node.city_code,
                "province_code": node.province_code,
                "district_code": node.district_code,
                "region_id": await self._business_region_id(node.city_region_id),
                "score": str(score),
                "basis": basis,
                "match_strength": strength,
            }

        for node in nodes:
            names = [name for name in [node.name, node.short_name or ""] if name]
            if any(text == name for name in names):
                exact_node_options.append(await make_node_option(node, score=Decimal("1.0"), basis=node.name, strength="EXACT"))
            elif any(name in text for name in names if len(name) >= 3):
                strong_node_options.append(await make_node_option(node, score=Decimal("0.92"), basis=node.name, strength="NODE_NAME_IN_TEXT"))
            elif any(text in name for name in names if len(text) >= 2):
                weak_node_options.append(await make_node_option(node, score=Decimal("0.72"), basis=node.name, strength="TEXT_IN_NODE_NAME"))
        for alias in aliases:
            alias_name = (alias.alias_name or "").strip()
            if not alias_name:
                continue
            node = next((item for item in nodes if item.id == alias.node_id), None)
            if node is None:
                continue
            if text == alias_name:
                exact_node_options.append(await make_node_option(node, score=Decimal("1.0"), basis=alias_name, strength="ALIAS_EXACT"))
            elif alias_name in text and len(alias_name) >= 2:
                strong_node_options.append(await make_node_option(node, score=Decimal("0.90"), basis=alias_name, strength="ALIAS_IN_TEXT"))
            elif text in alias_name and len(text) >= 2:
                weak_node_options.append(await make_node_option(node, score=Decimal("0.72"), basis=alias_name, strength="TEXT_IN_ALIAS"))
        for city in cities:
            names = [name for name in [city.name, city.short_name or ""] if name]
            score = None
            strength = ""
            basis = city.name
            if any(text == name for name in names):
                score = Decimal("0.98")
                strength = "CITY_EXACT"
                basis = city.short_name if text == (city.short_name or "") else city.name
            elif city.name and city.name in text and len(city.name) >= 3:
                score = Decimal("0.78")
                strength = "CITY_NAME_IN_TEXT"
            elif city.short_name and city.short_name in text and len(city.short_name) >= 2:
                score = Decimal("0.76")
                strength = "CITY_SHORT_IN_TEXT"
                basis = city.short_name
            if score is None:
                continue
            option = {
                "level": "CITY",
                "node_id": None,
                "node_name": None,
                "city_code": city.code,
                "city_name": city.name,
                "province_code": city.province_code or city.code[:2].ljust(6, "0"),
                "district_code": None,
                "region_id": await self._business_region_id(city.id),
                "score": str(score),
                "basis": basis,
                "match_strength": strength,
            }
            city_options.append(option)
            if strength == "CITY_EXACT":
                exact_city_options.append(option)

        def order_options(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
            dedup: dict[tuple[str, Any, Any], dict[str, Any]] = {}
            for option in sorted(options, key=lambda item: Decimal(str(item["score"])), reverse=True):
                key = (str(option.get("level")), option.get("node_id"), option.get("city_code"))
                dedup.setdefault(key, option)
            return list(dedup.values())[:6]

        all_options = order_options(exact_node_options + strong_node_options + exact_city_options + city_options + weak_node_options)

        def normalize_node(first: dict[str, Any]) -> dict[str, Any]:
            return {
                "node_id": first.get("node_id"),
                "province_code": first.get("province_code"),
                "city_code": first.get("city_code"),
                "district_code": first.get("district_code"),
                "region_id": first.get("region_id"),
                "match_score": Decimal(str(first["score"])),
                "match_level_code": "NODE",
            }

        def normalize_city(first: dict[str, Any]) -> dict[str, Any]:
            return {
                "node_id": None,
                "province_code": first.get("province_code"),
                "city_code": first.get("city_code"),
                "district_code": None,
                "region_id": first.get("region_id"),
                "match_score": Decimal(str(first["score"])),
                "match_level_code": "CITY",
            }

        if exact_node_options:
            first = order_options(exact_node_options)[0]
            return normalize_node(first), all_options, {"status": "MATCHED_NODE", "text": text, "top": first, "ai_level": ai_level}
        if exact_city_options and ai_level != "NODE":
            first = order_options(exact_city_options)[0]
            return normalize_city(first), all_options, {"status": "MATCHED_CITY", "text": text, "top": first, "ai_level": ai_level}
        if strong_node_options and ai_level == "NODE":
            first = order_options(strong_node_options)[0]
            return normalize_node(first), all_options, {"status": "MATCHED_NODE_AI", "text": text, "top": first, "ai_level": ai_level}
        if city_options and ai_level in {"CITY", ""}:
            first = order_options(city_options)[0]
            return normalize_city(first), all_options, {"status": "MATCHED_CITY", "text": text, "top": first, "ai_level": ai_level}
        if strong_node_options:
            first = order_options(strong_node_options)[0]
            return normalize_node(first), all_options, {"status": "MATCHED_NODE_STRONG", "text": text, "top": first, "ai_level": ai_level}
        if city_options:
            first = order_options(city_options)[0]
            return normalize_city(first), all_options, {"status": "MATCHED_CITY", "text": text, "top": first, "ai_level": ai_level}
        return {"match_level_code": "RAW"}, all_options or [{"level": "RAW", "name": text, "score": "0.0"}], {"status": "UNMATCHED", "text": text, "ai_level": ai_level}

    async def _candidate_from_segment(
        self,
        *,
        source_type_code: str,
        source_channel_code: str,
        source_batch_id: int | None,
        source_tms_inbound_id: int | None,
        clue_id: int,
        segment: dict[str, Any],
        candidate_no: str | None = None,
        match_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        commodity_name = str(_first(segment, "commodity_name", "cargo_name", "goods_name", "cargo") or "").strip()
        origin_text = str(_first(segment, "origin_text", "loading_place", "origin", "from") or "").strip()
        destination_text = str(_first(segment, "destination_text", "unloading_place", "destination", "to") or "").strip()
        if match_result is None:
            commodity_id, commodity_score, commodity_level, commodity_options, commodity_basis = await self._match_commodity(commodity_name)
            origin, origin_options, origin_basis = await self._match_location(
                origin_text, str(_first(segment, "origin_match_level_code", "origin_level_code") or "")
            )
            destination, destination_options, destination_basis = await self._match_location(
                destination_text, str(_first(segment, "destination_match_level_code", "destination_level_code") or "")
            )
        else:
            commodity_match = match_result.get("commodity") or {}
            origin_match = match_result.get("origin") or {}
            destination_match = match_result.get("destination") or {}
            commodity_id = commodity_match.get("id")
            commodity_score = commodity_match.get("score")
            commodity_level = commodity_match.get("level")
            commodity_options = commodity_match.get("options") or []
            commodity_basis = commodity_match.get("basis") or {}
            origin = origin_match.get("selected") or {}
            origin_options = origin_match.get("options") or []
            origin_basis = origin_match.get("basis") or {}
            destination = destination_match.get("selected") or {}
            destination_options = destination_match.get("options") or []
            destination_basis = destination_match.get("basis") or {}
        confidence = _to_decimal_or_none(_first(segment, "confidence_score", "confidence")) or Decimal("0.50")
        parsed_tonnage = _to_decimal_or_none(_first(segment, "estimated_tonnage", "quantity_ton", "tonnage"))
        min_tonnage = _to_decimal_or_none(segment.get("min_tonnage"))
        max_tonnage = _to_decimal_or_none(segment.get("max_tonnage"))
        completeness_score = self._completeness_score(
            commodity_id=commodity_id,
            origin_city_code=origin.get("city_code"),
            destination_city_code=destination.get("city_code"),
            tonnage=parsed_tonnage or max_tonnage or min_tonnage,
            unit_price=_to_decimal_or_none(_first(segment, "unit_price", "price")),
        )
        title = str(_first(segment, "cargo_title", "title") or "").strip()
        if not title:
            pieces = [origin_text, destination_text, commodity_name or "货源"]
            title = " - ".join([item for item in pieces if item])[:256] or "待确认货源"
        raw_text = str(_first(segment, "raw_text", "source_text") or "").strip()
        availability_status = str(_first(segment, "availability_status_code") or "UNKNOWN").upper()
        manual_review_reason = _first(segment, "manual_review_reason", "review_reason")
        missing = _segment_core_missing(segment)
        if missing:
            availability_status = "UNKNOWN"
            manual_review_reason = _append_reason(manual_review_reason, f"缺少{','.join(missing)}，无法直接确认")
        ai_review_status, ai_review_reason, ai_review_checks = _derive_segment_ai_review(
            segment,
            availability_status=availability_status,
            manual_review_reason=manual_review_reason,
        )
        if ai_review_status != AI_REVIEW_PASS:
            availability_status = "UNKNOWN" if availability_status == "READY" else availability_status
            manual_review_reason = ai_review_reason
        raw_tonnage_text = _first(segment, "raw_tonnage_text", "tonnage_text", "tonnage_raw")
        ai_understanding = {
            "semantic_role_code": _first(segment, "semantic_role_code", "role_code") or "ROUTE",
            "line_refs": segment.get("line_refs") or segment.get("line_refs_json") or [],
            "raw_text": raw_text or None,
            "route": {"origin_text": origin_text or None, "destination_text": destination_text or None},
            "commodity_name": commodity_name or None,
            "missing_field_codes": segment.get("missing_field_codes") or segment.get("missing_fields") or [],
            "tonnage": {
                "raw_text": raw_tonnage_text,
                "estimated_tonnage": _compact_json_value(parsed_tonnage),
                "min_tonnage": _compact_json_value(min_tonnage),
                "max_tonnage": _compact_json_value(max_tonnage),
                "decision": segment.get("tonnage_decision_json") or segment.get("tonnage_decision"),
                "candidates": segment.get("tonnage_candidates_json") or segment.get("tonnage_candidates") or [],
            },
            "quantity_description": _first(segment, "quantity_description", "vessel_description", "ship_description"),
            "inherited_context": segment.get("inherited_context") or {},
            "evidence": segment.get("evidence") or [],
        }
        ai_tool_match = {
            "commodity": {"basis": commodity_basis, "options": commodity_options, "selected_id": commodity_id},
            "origin": {"basis": origin_basis, "options": origin_options, "selected": origin},
            "destination": {"basis": destination_basis, "options": destination_options, "selected": destination},
        }
        ai_review = {
            "status_code": ai_review_status,
            "reason": manual_review_reason,
            "checks": ai_review_checks,
            "llm_review": segment.get("ai_review_json") or segment.get("review_json"),
            "missing_field_codes": segment.get("missing_field_codes") or segment.get("missing_fields") or [],
            "inference_basis": segment.get("inference_basis_json") or segment.get("inference_basis"),
            "needs_strong_review": bool(segment.get("needs_strong_review")),
        }
        return {
            "candidate_no": candidate_no or await self.sequence_service.next_code("FREIGHT_CANDIDATE_NO"),
            "source_type_code": source_type_code,
            "source_channel_code": source_channel_code,
            "source_batch_id": source_batch_id,
            "source_tms_inbound_id": source_tms_inbound_id,
            "clue_id": clue_id,
            "source_ref_no": _first(segment, "source_ref_no", "waybill_no", "order_no"),
            "raw_text": raw_text or None,
            "raw_commodity_name": commodity_name or None,
            "raw_tonnage_text": raw_tonnage_text,
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
            "estimated_tonnage": parsed_tonnage,
            "min_tonnage": min_tonnage,
            "max_tonnage": max_tonnage,
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
            "ai_understanding_json": _compact_json_value(ai_understanding),
            "ai_tool_match_json": _compact_json_value(ai_tool_match),
            "ai_review_json": _compact_json_value(ai_review),
            "ai_review_status_code": ai_review_status,
            "availability_status_code": availability_status,
            "manual_review_reason": manual_review_reason,
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
        await self._enrich_location_updates(data, "origin")
        await self._enrich_location_updates(data, "destination")
        await self._enrich_commodity_updates(data)
        self._fill_default_raw_levels(data)
        self._validate_freight_minimum(data)
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
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            raise ValidationError("no update fields provided")
        await self._enrich_location_updates(updates, "origin")
        await self._enrich_location_updates(updates, "destination")
        await self._enrich_commodity_updates(updates)
        self._fill_default_raw_levels(updates)
        if updates.get("hall_status_code") == "PUBLISHED" and updates.get("hall_published_at") is None:
            updates["hall_published_at"] = datetime.utcnow()
            updates["hall_unpublished_at"] = None
        if updates.get("hall_status_code") == "UNPUBLISHED" and updates.get("hall_unpublished_at") is None:
            updates["hall_unpublished_at"] = datetime.utcnow()
        row = await self.repo.update_freight(freight_id, updates)
        if row is None:
            raise NotFoundError("Freight", freight_id)
        self._validate_freight_minimum(_entity_snapshot(row, self._freight_minimum_fields()))
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

    @staticmethod
    def _freight_minimum_fields() -> list[str]:
        return [
            "cargo_title",
            "raw_commodity_name",
            "commodity_standard_id",
            "raw_origin_text",
            "origin_node_id",
            "origin_city_code",
            "raw_destination_text",
            "destination_node_id",
            "destination_city_code",
        ]

    @staticmethod
    def _validate_freight_minimum(data: dict[str, Any]) -> None:
        missing: list[str] = []
        if str(data.get("commodity_match_level_code") or "").upper() == "STANDARD" and not data.get("commodity_standard_id"):
            missing.append("标准货品")
        if not (str(data.get("cargo_title") or "").strip() or str(data.get("raw_commodity_name") or "").strip() or data.get("commodity_standard_id")):
            missing.append("货品原文或货源标题")
        origin_level = str(data.get("origin_match_level_code") or "").upper()
        destination_level = str(data.get("destination_match_level_code") or "").upper()
        if origin_level == "NODE" and not data.get("origin_node_id"):
            missing.append("装货节点")
        if origin_level == "CITY" and not data.get("origin_city_code"):
            missing.append("装货城市")
        if destination_level == "NODE" and not data.get("destination_node_id"):
            missing.append("卸货节点")
        if destination_level == "CITY" and not data.get("destination_city_code"):
            missing.append("卸货城市")
        if not (str(data.get("raw_origin_text") or "").strip() or data.get("origin_node_id") or data.get("origin_city_code")):
            missing.append("装货地原文")
        if not (str(data.get("raw_destination_text") or "").strip() or data.get("destination_node_id") or data.get("destination_city_code")):
            missing.append("卸货地原文")
        if missing:
            raise ValidationError(f"正式货源缺少最低入库字段：{', '.join(missing)}")


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
        ctx["stale_heartbeat_seconds"] = await self._stale_heartbeat_seconds()
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
                    "candidate_count": 0,
                    "pending_count": 0,
                    "confirmed_count": 0,
                    "rejected_count": 0,
                    "ready_count": 0,
                    "review_count": 0,
                    "routes": [],
                    "contacts": set(),
                },
            )
            data["candidate_count"] += 1
            if item.status_code == "PENDING":
                data["pending_count"] += 1
            if item.status_code == "CONFIRMED":
                data["confirmed_count"] += 1
            if item.status_code == "REJECTED":
                data["rejected_count"] += 1
            if item.status_code == "PENDING" and item.availability_status_code == "READY" and _candidate_ai_review_pass(item):
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

    async def _stale_heartbeat_seconds(self) -> int:
        value = await RuntimeConfigService(self.db).get_int(
            FREIGHT_AI_STALE_HEARTBEAT_SECONDS,
            settings.FREIGHT_AI_STALE_HEARTBEAT_SECONDS,
            profile_code=DASHSCOPE_CONFIG_PROFILE,
        )
        return max(30, value)

    async def _update_parse_progress(
        self,
        batch_id: int,
        *,
        stage_code: str,
        stage_name: str,
        stage_message: str,
        percent: int,
        started_at: datetime | None,
        status_code: str | None = None,
        error_message: str | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        now = datetime.utcnow()
        updates: dict[str, Any] = {
            "parse_stage_code": stage_code,
            "parse_stage_name": stage_name,
            "parse_stage_message": stage_message,
            "parse_progress_percent": max(0, min(int(percent), 100)),
            "parse_heartbeat_at": now,
            "ai_elapsed_seconds": int((now - started_at).total_seconds()) if started_at else 0,
        }
        if status_code is not None:
            updates["status_code"] = status_code
        if error_message is not None:
            updates["error_message"] = error_message
        if finished_at is not None:
            updates["finished_at"] = finished_at
        await self.repo.update(batch_id, updates)
        await self.db.commit()

    async def _progress_callback(self, batch_id: int, started_at: datetime):
        last_update = {"at": 0.0, "stage": ""}

        async def callback(stage_code: str, stage_name: str, stage_message: str, percent: int) -> None:
            import time

            now = time.monotonic()
            if last_update["stage"] == stage_code and now - float(last_update["at"]) < 3:
                return
            last_update["stage"] = stage_code
            last_update["at"] = now
            await self._update_parse_progress(
                batch_id,
                stage_code=stage_code,
                stage_name=stage_name,
                stage_message=stage_message,
                percent=percent,
                started_at=started_at,
                status_code="PARSING",
            )

        return callback

    async def create_wechat_batch(self, payload, creator_id: int | None) -> FreightBatchResponse:
        batch_no = (payload.batch_no or "").strip() or await self.sequence_service.next_code("FREIGHT_BATCH_NO")
        row = await self.repo.create(
            {
                "batch_no": batch_no,
                "source_type_code": "WECHAT",
                "source_channel_code": "WECHAT_TEXT",
                "raw_text": payload.raw_text.strip(),
                "status_code": "NEW",
                "review_flow_status_code": "REVIEWING",
                "parse_stage_code": "NEW",
                "parse_stage_name": "待解析",
                "parse_stage_message": "批次已保存，尚未提交 AI 解析",
                "parse_progress_percent": 0,
                "ai_elapsed_seconds": 0,
                "ai_pipeline_version": FREIGHT_AI_PIPELINE_VERSION,
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
        ctx["stale_heartbeat_seconds"] = await self._stale_heartbeat_seconds()
        return FreightBatchDetailResponse(
            batch=_to_batch_response(batch, ctx),
            clues=[_to_clue_response(item, ctx) for item in clues],
            candidates=[_to_candidate_response(item, ctx) for item in candidates],
        )

    async def parse(self, batch_id: int, requested_by: int | None = None) -> FreightBatchDetailResponse:
        batch = await self.repo.get_by_id(batch_id)
        if batch is None:
            raise NotFoundError("FreightBatchTask", batch_id)
        existing = await self.candidate_repo.list_by_batch(batch_id)
        if any(item.status_code == "CONFIRMED" or item.confirmed_freight_id is not None for item in existing):
            raise ValidationError("该采集批次已有确认入库货源，不能重新解析")
        if str(getattr(batch, "review_flow_status_code", "") or "").upper() == "QUEUED_FOR_REVIEW":
            raise ValidationError("该采集批次已移交待确认货源队列，不能重新解析")
        if batch.status_code == "PARSING":
            stale_seconds = await self._stale_heartbeat_seconds()
            heartbeat = batch.parse_heartbeat_at or batch.updated_at or batch.started_at
            if heartbeat and datetime.utcnow() - heartbeat < timedelta(seconds=stale_seconds):
                return await self.get_detail(batch_id)
        now = datetime.utcnow()
        await self.repo.update(
            batch_id,
            {
                "status_code": "QUEUED",
                "review_flow_status_code": "REVIEWING",
                "error_message": None,
                "finished_at": None,
                "parse_stage_code": "QUEUED",
                "parse_stage_name": "排队中",
                "parse_stage_message": "解析任务已提交，等待 Celery worker 消费",
                "parse_progress_percent": 5,
                "parse_heartbeat_at": now,
                "ai_elapsed_seconds": 0,
            },
        )
        await self.db.commit()
        try:
            from app.tasks.freight_ai_tasks import parse_wechat_batch_task

            parse_wechat_batch_task.delay(batch_id, requested_by)
        except Exception as exc:  # noqa: BLE001
            await self.repo.update(
                batch_id,
                {
                    "status_code": "FAILED",
                    "finished_at": datetime.utcnow(),
                    "error_message": f"解析任务投递失败：{exc}",
                    "parse_stage_code": "FAILED",
                    "parse_stage_name": "投递失败",
                    "parse_stage_message": f"解析任务投递失败：{exc}",
                    "parse_progress_percent": 100,
                    "parse_heartbeat_at": datetime.utcnow(),
                },
            )
            await self.db.commit()
            raise ValidationError(f"解析任务投递失败：{exc}") from exc
        return await self.get_detail(batch_id)

    async def run_parse_now(self, batch_id: int, requested_by: int | None = None) -> FreightBatchDetailResponse:
        _ = requested_by
        batch = await self.repo.get_by_id(batch_id)
        if batch is None:
            raise NotFoundError("FreightBatchTask", batch_id)
        existing = await self.candidate_repo.list_by_batch(batch_id)
        if any(item.status_code == "CONFIRMED" or item.confirmed_freight_id is not None for item in existing):
            raise ValidationError("该采集批次已有确认入库货源，不能重新解析")
        if str(getattr(batch, "review_flow_status_code", "") or "").upper() == "QUEUED_FOR_REVIEW":
            raise ValidationError("该采集批次已移交待确认货源队列，不能重新解析")
        if batch.status_code == "PARSED" and existing:
            return await self.get_detail(batch_id)
        started = datetime.utcnow()
        timings: dict[str, int] = {}
        timer_started = time.monotonic()

        def mark_timing(stage_code: str) -> None:
            timings[stage_code] = int((time.monotonic() - timer_started) * 1000)

        await self.repo.update(
            batch_id,
            {
                "status_code": "PARSING",
                "review_flow_status_code": "REVIEWING",
                "started_at": started,
                "finished_at": None,
                "error_message": None,
                "parse_stage_code": "PREPARE",
                "parse_stage_name": "准备解析",
                "parse_stage_message": "系统正在准备原文行号索引和解析上下文",
                "parse_progress_percent": 8,
                "parse_heartbeat_at": started,
                "ai_elapsed_seconds": 0,
            },
        )
        await self.db.commit()
        client = DashScopeQwenFreightParserClient(runtime_config=RuntimeConfigService(self.db))
        try:
            callback = await self._progress_callback(batch_id, started)
            if hasattr(client, "parse_semantic_map") and hasattr(client, "complete_candidate_fields"):
                runtime = await client._runtime()  # noqa: SLF001 - staged orchestration uses the parser runtime contract.
                indexed_text = FreightTextIndexer().index(batch.raw_text)
                semantic_map, semantic_raw = await client.parse_semantic_map(
                    indexed_text,
                    runtime=runtime,
                    progress_callback=callback,
                )
                validator = FreightSemanticValidator(indexed_text)
                semantic_warnings = validator.validate_semantic_map(semantic_map)
                mark_timing("AI_SEMANTIC_MAP")

                segments, detail_raws, detail_warnings = await client.complete_candidate_fields(
                    indexed_text,
                    semantic_map,
                    runtime=runtime,
                    progress_callback=callback,
                )
                semantic_warnings.extend(validator.validate_segments(semantic_map, segments))
                mark_timing("AI_DETAIL")

                await self._update_parse_progress(
                    batch_id,
                    stage_code="MATCHING",
                    stage_name="标准化匹配",
                    stage_message="系统正在批量匹配运输节点、城市和标准货品",
                    percent=68,
                    started_at=started,
                    status_code="PARSING",
                )
                matcher = FreightMasterDataBatchMatcher(self.db)
                await matcher.match_segments(segments)
                mark_timing("MATCHING")

                review_results, review_raw, review_failed_count = await client.review_risky_segments(
                    indexed_text,
                    semantic_map,
                    segments,
                    runtime=runtime,
                    progress_callback=callback,
                )
                if review_results:
                    segments = client.merge_review_results(segments, review_results)
                    semantic_warnings.extend(validator.validate_segments(semantic_map, segments))
                mark_timing("AI_REVIEW")

                accepted_segments, ignored_segments, quality_warnings = _prepare_segments(batch.raw_text, segments)
                final_match_results = await matcher.match_segments(accepted_segments)
                warnings = list(
                    dict.fromkeys(
                        [
                            *(semantic_map.get("warnings") or []),
                            *semantic_warnings,
                            *detail_warnings,
                            *quality_warnings,
                        ]
                    )
                )
                parsed = type(
                    "StagedFreightParseResult",
                    (),
                    {
                        "segments": accepted_segments,
                        "ignored_segments": ignored_segments,
                        "prompt_version": client.wechat_prompt_version,
                        "model": " -> ".join(
                            dict.fromkeys(
                                [
                                    runtime["semantic_model"],
                                    runtime["detail_model"],
                                    *([runtime["review_model"]] if review_raw is not None else []),
                                ]
                            )
                        ),
                        "parsed_payload": {
                            "segments": accepted_segments,
                            "ignored_segments": ignored_segments,
                            "context_blocks": semantic_map.get("context_blocks") or [],
                            "context_notes": semantic_map.get("context_notes") or [],
                            "warnings": warnings,
                        },
                        "raw_response": {
                            "provider": runtime["provider"],
                            "pipeline": "freight_ai_semantic_pipeline_v2",
                            "semantic_map": semantic_raw,
                            "detail": detail_raws,
                            "review": review_raw,
                        },
                        "review_failed_count": review_failed_count,
                        "semantic_map": semantic_map,
                        "review_results": review_results,
                        "match_results": final_match_results,
                    },
                )()
            else:
                parsed = await client.parse(
                    batch.raw_text,
                    source_type_code="WECHAT",
                    progress_callback=callback,
                )
                await self._update_parse_progress(
                    batch_id,
                    stage_code="MATCHING",
                    stage_name="标准化匹配",
                    stage_message="系统正在批量匹配运输节点、城市和标准货品",
                    percent=68,
                    started_at=started,
                    status_code="PARSING",
                )
                matcher = FreightMasterDataBatchMatcher(self.db)
                parsed.match_results = await matcher.match_segments(list(getattr(parsed, "segments", []) or []))
                mark_timing("MATCHING")
                mark_timing("AI_REVIEW")

            await self._update_parse_progress(
                batch_id,
                stage_code="SAVING",
                stage_name="保存候选",
                stage_message="系统正在批量生成编码并保存候选货源",
                percent=88,
                started_at=started,
                status_code="PARSING",
            )
            mark_timing("SAVING_START")
            ignored_segments = list(getattr(parsed, "ignored_segments", []) or [])
            work_items = [("ignored", item) for item in ignored_segments] + [("candidate", item) for item in parsed.segments]
            candidate_segments = [segment for item_type, segment in work_items if item_type == "candidate" and not _segment_ignore_reason(segment)]
            if not candidate_segments:
                raise ValidationError("AI 未生成可入库候选")
            clue_nos = await self.sequence_service.next_codes("FREIGHT_CLUE_NO", len(work_items))
            candidate_nos = await self.sequence_service.next_codes("FREIGHT_CANDIDATE_NO", len(candidate_segments))
            match_results = list(getattr(parsed, "match_results", []) or [])

            clue_rows: list[dict[str, Any]] = []
            normalized_work_items: list[tuple[str, dict[str, Any], str | None]] = []
            for index, (item_type, segment) in enumerate(work_items, start=1):
                ignore_reason = str(segment.get("drop_reason") or "") if item_type == "ignored" else _segment_ignore_reason(segment)
                if ignore_reason:
                    segment = {**segment, "drop_reason": ignore_reason, "is_freight_candidate": False}
                normalized_work_items.append((item_type, segment, ignore_reason))
                clue_rows.append(
                    {
                        "clue_no": clue_nos[index - 1],
                        "source_type_code": "WECHAT",
                        "source_channel_code": "WECHAT_TEXT",
                        "source_batch_id": batch_id,
                        "source_tms_inbound_id": None,
                        "segment_index": int(segment.get("segment_index") or index),
                        "semantic_role_code": _first(segment, "semantic_role_code", "role_code") or ("IGNORED" if ignore_reason else "ROUTE"),
                        "raw_text": str(segment.get("raw_text") or batch.raw_text),
                        "line_refs_json": segment.get("line_refs") or segment.get("line_refs_json"),
                        "context_summary": segment.get("context_summary") or ignore_reason or segment.get("manual_review_reason"),
                        "extracted_fields_json": segment,
                        "quality_score": _to_decimal_or_none(segment.get("confidence_score")),
                        "status_code": "IGNORED" if ignore_reason else "CANDIDATE_CREATED",
                    }
                )

            clue_ids = await self.candidate_repo.delete_unconfirmed_by_batch(batch_id)
            await self.clue_repo.delete_by_ids(clue_ids)
            clues = await self.clue_repo.bulk_create(clue_rows)
            candidate_rows: list[dict[str, Any]] = []
            candidate_index = 0
            for item_index, (item_type, segment, ignore_reason) in enumerate(normalized_work_items):
                if item_type != "candidate" or ignore_reason:
                    continue
                candidate_rows.append(
                    await self._candidate_from_segment(
                        source_type_code="WECHAT",
                        source_channel_code="WECHAT_TEXT",
                        source_batch_id=batch_id,
                        source_tms_inbound_id=None,
                        clue_id=clues[item_index].id,
                        segment=segment,
                        candidate_no=candidate_nos[candidate_index],
                        match_result=match_results[candidate_index] if candidate_index < len(match_results) else None,
                    )
                )
                candidate_index += 1
            await self.candidate_repo.bulk_create(candidate_rows)
            clue_count = len(clue_rows)
            candidate_count = len(candidate_rows)
            failed_count = int(getattr(parsed, "review_failed_count", 0) or 0)
            mark_timing("SAVING")
            status = "PARSED" if candidate_count and failed_count == 0 else "PARTIAL_FAILED" if candidate_count else "FAILED"
            finished = datetime.utcnow()
            semantic_map_json = getattr(parsed, "semantic_map", None) or {
                "context_blocks": (getattr(parsed, "parsed_payload", {}) or {}).get("context_blocks") or [],
                "context_notes": (getattr(parsed, "parsed_payload", {}) or {}).get("context_notes") or [],
                "ignored_segments": (getattr(parsed, "parsed_payload", {}) or {}).get("ignored_segments") or [],
                "warnings": (getattr(parsed, "parsed_payload", {}) or {}).get("warnings") or [],
            }
            semantic_map_json = {
                "pipeline_version": FREIGHT_AI_PIPELINE_VERSION,
                "prompt_version": parsed.prompt_version,
                **semantic_map_json,
            }
            raw_response_json = {
                "semantic_map": semantic_map_json,
                "segments": (getattr(parsed, "parsed_payload", {}) or {}).get("segments") or [],
                "review_results": getattr(parsed, "review_results", []) or [],
                "warnings": (getattr(parsed, "parsed_payload", {}) or {}).get("warnings") or [],
                "timings": timings,
                "raw_response": getattr(parsed, "raw_response", {}),
            }
            await self.repo.update(
                batch_id,
                {
                    "status_code": status,
                    "review_flow_status_code": "REVIEWING" if status != "FAILED" else "REVIEWING",
                    "clue_count": clue_count,
                    "candidate_count": candidate_count,
                    "success_count": candidate_count,
                    "failed_count": failed_count if candidate_count else 1,
                    "prompt_version": parsed.prompt_version,
                    "ai_pipeline_version": FREIGHT_AI_PIPELINE_VERSION,
                    "ai_semantic_map_json": semantic_map_json,
                    "finished_at": finished,
                    "parse_stage_code": "DONE" if status != "FAILED" else "FAILED",
                    "parse_stage_name": "解析完成" if status != "FAILED" else "解析失败",
                    "parse_stage_message": "候选货源已生成，可进入确认入库" if status != "FAILED" else "AI 未生成可入库候选",
                    "parse_progress_percent": 100,
                    "parse_heartbeat_at": finished,
                    "ai_elapsed_seconds": int((finished - started).total_seconds()),
                    "raw_response_json": raw_response_json,
                },
            )
            await self.db.commit()
        except Exception as exc:
            message = str(exc)
            await self.db.rollback()
            finished = datetime.utcnow()
            await self.repo.update(
                batch_id,
                {
                    "status_code": "FAILED",
                    "finished_at": finished,
                    "error_message": message,
                    "parse_stage_code": "FAILED",
                    "parse_stage_name": "解析失败",
                    "parse_stage_message": message,
                    "parse_progress_percent": 100,
                    "parse_heartbeat_at": finished,
                    "ai_elapsed_seconds": int((finished - started).total_seconds()),
                },
            )
            await self.db.commit()
            raise
        return await self.get_detail(batch_id)

    async def handoff_review(self, batch_id: int, operator_id: int | None = None) -> FreightBatchHandoffResponse:
        _ = operator_id
        batch = await self.repo.get_by_id(batch_id)
        if batch is None:
            raise NotFoundError("FreightBatchTask", batch_id)
        if batch.status_code not in {"PARSED", "PARTIAL_FAILED"}:
            raise ValidationError("只有解析完成的批次可以移交待确认货源队列")
        candidates = await self.candidate_repo.list_by_batch(batch_id)
        pending_count = sum(1 for item in candidates if item.status_code == "PENDING")
        if pending_count <= 0:
            raise ValidationError("该批次没有待确认候选货源")
        await self.repo.update(batch_id, {"review_flow_status_code": "QUEUED_FOR_REVIEW"})
        await self.db.commit()
        return FreightBatchHandoffResponse(
            batch_id=batch_id,
            handoff_count=pending_count,
            review_flow_status_code="QUEUED_FOR_REVIEW",
            message=f"已移交 {pending_count} 条候选货源到待确认货源队列",
        )


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
                            "semantic_role_code": _first(segment, "semantic_role_code", "role_code") or "ROUTE",
                            "raw_text": str(segment.get("raw_text") or inbound.raw_content),
                            "line_refs_json": segment.get("line_refs") or segment.get("line_refs_json"),
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
        source_batch_id: int | None,
        page: int,
        page_size: int,
    ) -> PageResponse[FreightCandidateResponse]:
        rows, total = await self.repo.list_items(
            keyword=keyword,
            status_code=status_code,
            source_type_code=source_type_code,
            source_batch_id=source_batch_id,
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
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            raise ValidationError("no update fields provided")
        await self._enrich_location_updates(updates, "origin")
        await self._enrich_location_updates(updates, "destination")
        await self._enrich_commodity_updates(updates)
        self._fill_default_raw_levels(updates)
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
        has_overrides = payload.overrides is not None and bool(payload.overrides.model_dump(exclude_unset=True))
        if payload.overrides is not None:
            updates = payload.overrides.model_dump(exclude_unset=True)
            if updates:
                await self._enrich_location_updates(updates, "origin")
                await self._enrich_location_updates(updates, "destination")
                await self._enrich_commodity_updates(updates)
                self._fill_default_raw_levels(updates)
                manual = dict(candidate.manual_overrides_json or {})
                manual.update(_compact_json_value(updates))
                updates["manual_overrides_json"] = manual
                candidate = await self.repo.update(candidate_id, updates) or candidate
                action_code = "EDIT_CONFIRM"
        self._validate_candidate_ready(candidate, allow_review_override=has_overrides)
        if has_overrides:
            candidate = await self.repo.update(
                candidate_id,
                {
                    "ai_review_status_code": AI_REVIEW_MANUAL_ACCEPTED,
                    "ai_review_json": {
                        **(candidate.ai_review_json or {}),
                        "status_code": AI_REVIEW_MANUAL_ACCEPTED,
                        "reason": "人工编辑确认后接受",
                        "accepted_by": operator_id,
                    },
                },
            ) or candidate
        now = datetime.utcnow()
        freight_payload = {
                "freight_no": await self.sequence_service.next_code("FREIGHT_NO"),
                "source_type_code": candidate.source_type_code,
                "source_channel_code": candidate.source_channel_code,
                "source_ref_no": candidate.source_ref_no or candidate.candidate_no,
                "source_batch_id": candidate.source_batch_id,
                "source_tms_inbound_id": candidate.source_tms_inbound_id,
                "source_clue_id": candidate.clue_id,
                "source_candidate_id": candidate.id,
                "raw_commodity_name": candidate.raw_commodity_name,
                "raw_tonnage_text": candidate.raw_tonnage_text,
                "raw_origin_text": candidate.raw_origin_text,
                "raw_destination_text": candidate.raw_destination_text,
                "cargo_title": candidate.cargo_title,
                "cargo_description": candidate.cargo_description,
                "commodity_standard_id": candidate.commodity_standard_id,
                "commodity_match_level_code": candidate.commodity_match_level_code,
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
                "origin_match_level_code": candidate.origin_match_level_code,
                "destination_match_level_code": candidate.destination_match_level_code,
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
        self._fill_default_raw_levels(freight_payload)
        freight = await self.freight_repo.create_freight(freight_payload)
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
            if not _candidate_ai_review_pass(row):
                skipped.append({"candidate_id": row.id, "candidate_no": row.candidate_no, "reason": _candidate_ai_review_reason(row) or "AI 复核状态需人工判断"})
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
            "commodity_match_level_code",
            "raw_commodity_name",
            "origin_node_id",
            "origin_city_code",
            "origin_match_level_code",
            "raw_origin_text",
            "destination_node_id",
            "destination_city_code",
            "destination_match_level_code",
            "raw_destination_text",
            "raw_tonnage_text",
            "estimated_tonnage",
            "unit_price",
            "availability_status_code",
            "manual_review_reason",
            "ai_review_status_code",
            "status_code",
        ]

    @staticmethod
    def _validate_candidate_ready(candidate, *, allow_review_override: bool = False) -> None:
        if candidate.availability_status_code != "READY" and not allow_review_override:
            reason = candidate.manual_review_reason or "AI 未判断为可直接发布"
            raise ValidationError(f"候选货源需要编辑确认后才能入库：{reason}")
        if not _candidate_ai_review_pass(candidate) and not allow_review_override:
            reason = _candidate_ai_review_reason(candidate) or "AI 复核状态需人工判断"
            raise ValidationError(f"候选货源需要编辑确认后才能入库：{reason}")
        missing: list[str] = []
        if str(candidate.commodity_match_level_code or "").upper() == "STANDARD" and candidate.commodity_standard_id is None:
            missing.append("标准货品")
        if not (
            str(candidate.cargo_title or "").strip()
            or str(candidate.raw_commodity_name or "").strip()
            or candidate.commodity_standard_id is not None
        ):
            missing.append("货品原文或货源标题")
        origin_level = str(candidate.origin_match_level_code or "").upper()
        destination_level = str(candidate.destination_match_level_code or "").upper()
        if origin_level == "NODE" and candidate.origin_node_id is None:
            missing.append("装货节点")
        if origin_level == "CITY" and not candidate.origin_city_code:
            missing.append("装货城市")
        if destination_level == "NODE" and candidate.destination_node_id is None:
            missing.append("卸货节点")
        if destination_level == "CITY" and not candidate.destination_city_code:
            missing.append("卸货城市")
        if not (
            str(candidate.raw_origin_text or "").strip()
            or candidate.origin_node_id is not None
            or bool(candidate.origin_city_code)
        ):
            missing.append("装货地原文")
        if not (
            str(candidate.raw_destination_text or "").strip()
            or candidate.destination_node_id is not None
            or bool(candidate.destination_city_code)
        ):
            missing.append("卸货地原文")
        if missing:
            raise ValidationError(f"候选货源缺少确认入库字段：{', '.join(missing)}")


class FreightNormalizationSuggestionService(FreightNormalizationMixin):
    AUTO_LOCATION_THRESHOLD = Decimal("0.86")
    AUTO_COMMODITY_THRESHOLD = Decimal("0.82")

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = FreightNormalizationSuggestionRepository(db)
        self.task_repo = FreightNormalizationTaskRepository(db)
        self.freight_repo = FreightRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def list_tasks(self, *, page: int, page_size: int) -> PageResponse[FreightNormalizationTaskResponse]:
        rows, total = await self.task_repo.list_items(page=page, page_size=page_size)
        return PageResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_normalization_task_response(item) for item in rows],
        )

    async def get_task(self, task_id: int) -> FreightNormalizationTaskResponse:
        row = await self.task_repo.get_by_id(task_id)
        if row is None:
            raise NotFoundError("FreightNormalizationTask", task_id)
        return _to_normalization_task_response(row)

    async def list_items(
        self,
        *,
        keyword: str | None,
        status_code: str | None,
        suggestion_type_code: str | None,
        page: int,
        page_size: int,
    ) -> PageResponse[FreightNormalizationSuggestionResponse]:
        rows, total = await self.repo.list_items(
            keyword=keyword,
            status_code=status_code,
            suggestion_type_code=suggestion_type_code,
            page=page,
            page_size=page_size,
        )
        ctx = await _load_display_context(self.db, suggestions=rows)
        return PageResponse[FreightNormalizationSuggestionResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_normalization_suggestion_response(item, ctx) for item in rows],
        )

    async def quality(self) -> FreightNormalizationQualityResponse:
        freight_count = int(
            await self.db.scalar(select(func.count(Freight.id)).where(Freight.deleted_at.is_(None)))
            or 0
        )
        raw_origin_count = int(
            await self.db.scalar(
                select(func.count(Freight.id)).where(
                    Freight.deleted_at.is_(None),
                    or_(Freight.origin_match_level_code == "RAW", Freight.origin_city_code.is_(None)),
                )
            )
            or 0
        )
        raw_destination_count = int(
            await self.db.scalar(
                select(func.count(Freight.id)).where(
                    Freight.deleted_at.is_(None),
                    or_(Freight.destination_match_level_code == "RAW", Freight.destination_city_code.is_(None)),
                )
            )
            or 0
        )
        raw_commodity_count = int(
            await self.db.scalar(
                select(func.count(Freight.id)).where(
                    Freight.deleted_at.is_(None),
                    or_(Freight.commodity_match_level_code == "RAW", Freight.commodity_standard_id.is_(None)),
                )
            )
            or 0
        )
        pending = int(
            await self.db.scalar(
                select(func.count(FreightNormalizationSuggestion.id)).where(
                    FreightNormalizationSuggestion.status_code == "PENDING"
                )
            )
            or 0
        )
        auto_applied = int(
            await self.db.scalar(
                select(func.count(FreightNormalizationSuggestion.id)).where(
                    FreightNormalizationSuggestion.status_code == "AUTO_APPLIED"
                )
            )
            or 0
        )
        running_tasks = int(
            await self.db.scalar(
                select(func.count(FreightNormalizationTask.id)).where(
                    FreightNormalizationTask.status_code.in_(["QUEUED", "RUNNING"])
                )
            )
            or 0
        )
        failed_tasks = int(
            await self.db.scalar(
                select(func.count(FreightNormalizationTask.id)).where(FreightNormalizationTask.status_code == "FAILED")
            )
            or 0
        )
        latest = await self.task_repo.latest()
        return FreightNormalizationQualityResponse(
            freight_count=freight_count,
            raw_origin_count=raw_origin_count,
            raw_destination_count=raw_destination_count,
            raw_commodity_count=raw_commodity_count,
            pending_suggestion_count=pending,
            auto_applied_suggestion_count=auto_applied,
            running_task_count=running_tasks,
            failed_task_count=failed_tasks,
            latest_task_id=latest.id if latest is not None else None,
            latest_task_no=latest.task_no if latest is not None else None,
            latest_task_status_code=latest.status_code if latest is not None else None,
            latest_task_stage_name=latest.stage_name if latest is not None else None,
            latest_task_finished_at=latest.finished_at if latest is not None else None,
        )

    async def clean(self, operator_id: int | None = None) -> FreightNormalizationCleanResponse:
        now = datetime.utcnow()
        task = await self.task_repo.create(
            {
                "task_no": await self.sequence_service.next_code("FREIGHT_NORMALIZATION_TASK_NO"),
                "celery_task_id": None,
                "status_code": "QUEUED",
                "stage_code": "QUEUED",
                "stage_name": "排队中",
                "stage_message": "清洗任务已提交，等待 Celery worker 消费",
                "progress_percent": 5,
                "requested_by": operator_id,
                "heartbeat_at": now,
                "created_at": now,
                "updated_at": now,
            }
        )
        await self.db.commit()
        celery_task_id: str | None = None
        try:
            from app.tasks.freight_ai_tasks import clean_freight_normalization_task

            async_result = clean_freight_normalization_task.delay(task.id, operator_id)
            celery_task_id = str(async_result.id)
            task = await self.task_repo.update(task.id, {"celery_task_id": celery_task_id}) or task
            await self.db.commit()
        except Exception as exc:  # noqa: BLE001
            task = await self.task_repo.update(
                task.id,
                {
                    "status_code": "FAILED",
                    "stage_code": "FAILED",
                    "stage_name": "投递失败",
                    "stage_message": f"清洗任务投递失败：{exc}",
                    "error_message": f"清洗任务投递失败：{exc}",
                    "progress_percent": 100,
                    "finished_at": datetime.utcnow(),
                    "heartbeat_at": datetime.utcnow(),
                },
            ) or task
            await self.db.commit()
            raise ValidationError(f"清洗任务投递失败：{exc}") from exc
        return self._clean_response_from_task(task, message="清洗任务已提交，正在后台执行")

    def _clean_response_from_task(self, task: FreightNormalizationTask, *, message: str | None = None) -> FreightNormalizationCleanResponse:
        result_json = task.result_json or {}
        affected_from = result_json.get("affected_date_from")
        affected_to = result_json.get("affected_date_to")
        if isinstance(affected_from, str):
            affected_from = datetime.fromisoformat(affected_from) if affected_from else None
        if isinstance(affected_to, str):
            affected_to = datetime.fromisoformat(affected_to) if affected_to else None
        return FreightNormalizationCleanResponse(
            task_id=task.id,
            task_no=task.task_no,
            celery_task_id=task.celery_task_id,
            status_code=task.status_code,
            stage_name=task.stage_name,
            message=message or task.stage_message,
            scanned_count=task.scanned_count,
            suggestion_count=task.suggestion_count,
            auto_applied_count=task.auto_applied_count,
            pending_count=task.pending_count,
            affected_date_from=affected_from,
            affected_date_to=affected_to,
        )

    async def _update_clean_task(
        self,
        task_id: int,
        *,
        status_code: str | None = None,
        stage_code: str,
        stage_name: str,
        stage_message: str,
        progress_percent: int,
        **extra: Any,
    ) -> None:
        updates: dict[str, Any] = {
            "stage_code": stage_code,
            "stage_name": stage_name,
            "stage_message": stage_message,
            "progress_percent": max(0, min(int(progress_percent), 100)),
            "heartbeat_at": datetime.utcnow(),
            **extra,
        }
        if status_code is not None:
            updates["status_code"] = status_code
        await self.task_repo.update(task_id, updates)
        await self.db.commit()

    async def run_clean_now(self, task_id: int, operator_id: int | None = None) -> FreightNormalizationCleanResponse:
        task = await self.task_repo.get_by_id(task_id)
        if task is None:
            raise NotFoundError("FreightNormalizationTask", task_id)
        started = datetime.utcnow()
        await self._update_clean_task(
            task_id,
            status_code="RUNNING",
            stage_code="SCANNING",
            stage_name="扫描正式货源",
            stage_message="正在扫描原文级、缺城市、缺节点和缺标准货品的正式货源",
            progress_percent=12,
            started_at=started,
            error_message=None,
        )
        rows = (
            await self.db.execute(
                select(Freight)
                .where(
                    Freight.deleted_at.is_(None),
                    or_(
                        Freight.origin_match_level_code == "RAW",
                        Freight.origin_city_code.is_(None),
                        Freight.destination_match_level_code == "RAW",
                        Freight.destination_city_code.is_(None),
                        Freight.commodity_match_level_code == "RAW",
                        Freight.commodity_standard_id.is_(None),
                    ),
                )
                .order_by(Freight.id.asc())
            )
        ).scalars().all()
        await self._update_clean_task(
            task_id,
            status_code="RUNNING",
            stage_code="MATCHING",
            stage_name="AI 清洗匹配",
            stage_message=f"已扫描 {len(rows)} 条正式货源，正在生成标准化建议",
            progress_percent=30,
            scanned_count=len(rows),
        )
        suggestion_count = 0
        auto_applied_count = 0
        pending_count = 0
        failed_count = 0
        affected_dates: list[datetime] = []
        total = max(len(rows), 1)
        for index, freight in enumerate(rows, start=1):
            for suggestion_type in ("ORIGIN", "DESTINATION", "COMMODITY"):
                try:
                    suggestion = await self._suggest_for_freight(freight, suggestion_type, clean_task_id=task_id)
                    if suggestion is None:
                        continue
                    suggestion_count += 1
                    if suggestion.auto_apply_flag:
                        await self._apply_suggestion(suggestion, operator_id=operator_id, auto=True)
                        auto_applied_count += 1
                        affected_date = freight.published_at or freight.confirmed_at or freight.created_at
                        if affected_date is not None:
                            affected_dates.append(affected_date)
                    else:
                        pending_count += 1
                except Exception:  # noqa: BLE001
                    failed_count += 1
                    continue
            if index == len(rows) or index % 10 == 0:
                await self._update_clean_task(
                    task_id,
                    status_code="RUNNING",
                    stage_code="MATCHING",
                    stage_name="AI 清洗匹配",
                    stage_message=f"正在清洗正式货源 {index}/{len(rows)}",
                    progress_percent=30 + int(index / total * 45),
                    scanned_count=len(rows),
                    suggestion_count=suggestion_count,
                    auto_applied_count=auto_applied_count,
                    pending_count=pending_count,
                    failed_count=failed_count,
                )
        await self.db.commit()
        if affected_dates:
            await self._update_clean_task(
                task_id,
                status_code="RUNNING",
                stage_code="REBUILD_ANALYSIS",
                stage_name="重算分析事实",
                stage_message="自动提升已回填，正在重算受影响的货源分析事实",
                progress_percent=86,
            )
            await self._rebuild_affected_analysis(min(affected_dates), max(affected_dates))
        finished = datetime.utcnow()
        task = await self.task_repo.update(
            task_id,
            {
                "status_code": "SUCCESS" if failed_count == 0 else "PARTIAL_SUCCESS",
                "stage_code": "DONE",
                "stage_name": "清洗完成",
                "stage_message": "正式货源清洗任务已完成",
                "progress_percent": 100,
                "scanned_count": len(rows),
                "suggestion_count": suggestion_count,
                "auto_applied_count": auto_applied_count,
                "pending_count": pending_count,
                "failed_count": failed_count,
                "finished_at": finished,
                "heartbeat_at": finished,
                "result_json": {
                    "affected_date_from": min(affected_dates).isoformat() if affected_dates else None,
                    "affected_date_to": max(affected_dates).isoformat() if affected_dates else None,
                },
            },
        ) or task
        await self.db.commit()
        return self._clean_response_from_task(
            task,
            message=f"已扫描 {len(rows)} 条，自动提升 {auto_applied_count} 条，待确认 {pending_count} 条",
        )

    async def apply(self, suggestion_id: int, operator_id: int | None = None) -> FreightNormalizationSuggestionResponse:
        row = await self.repo.get_by_id(suggestion_id)
        if row is None:
            raise NotFoundError("FreightNormalizationSuggestion", suggestion_id)
        if row.status_code != "PENDING":
            raise ValidationError("只有待确认清洗建议可以应用")
        await self._apply_suggestion(row, operator_id=operator_id, auto=False)
        await self.db.commit()
        ctx = await _load_display_context(self.db, suggestions=[row])
        return _to_normalization_suggestion_response(row, ctx)

    async def reject(self, suggestion_id: int, operator_id: int | None = None) -> FreightNormalizationSuggestionResponse:
        row = await self.repo.get_by_id(suggestion_id)
        if row is None:
            raise NotFoundError("FreightNormalizationSuggestion", suggestion_id)
        if row.status_code != "PENDING":
            raise ValidationError("只有待确认清洗建议可以拒绝")
        row = await self.repo.update(
            suggestion_id,
            {"status_code": "REJECTED", "rejected_at": datetime.utcnow(), "rejected_by": operator_id},
        ) or row
        await self.db.commit()
        ctx = await _load_display_context(self.db, suggestions=[row])
        return _to_normalization_suggestion_response(row, ctx)

    async def bulk_apply(self, payload, operator_id: int | None = None) -> FreightNormalizationBulkApplyResponse:
        suggestion_ids = [int(item) for item in (payload.suggestion_ids or []) if int(item) > 0]
        if not payload.apply_all_filtered and not suggestion_ids:
            raise ValidationError("请选择要批量应用的清洗建议")
        rows = await self.repo.list_pending_for_bulk(
            suggestion_ids=None if payload.apply_all_filtered else suggestion_ids,
            keyword=(payload.keyword or "").strip() or None,
            suggestion_type_code=(payload.suggestion_type_code or "").strip() or None,
        )
        applied_count = 0
        skipped: list[dict[str, Any]] = []
        affected_dates: list[datetime] = []
        for row in rows:
            try:
                freight = await self.freight_repo.get_freight_by_id(row.freight_id)
                await self._apply_suggestion(row, operator_id=operator_id, auto=False)
                applied_count += 1
                if freight is not None:
                    affected_date = freight.published_at or freight.confirmed_at or freight.created_at
                    if affected_date is not None:
                        affected_dates.append(affected_date)
            except Exception as exc:  # noqa: BLE001
                skipped.append({"suggestion_id": row.id, "reason": str(exc)})
        await self.db.commit()
        if affected_dates:
            await self._rebuild_affected_analysis(min(affected_dates), max(affected_dates))
        return FreightNormalizationBulkApplyResponse(
            applied_count=applied_count,
            skipped_count=len(skipped),
            skipped=skipped,
        )

    async def _suggest_for_freight(
        self, freight: Freight, suggestion_type: str, *, clean_task_id: int | None = None
    ) -> FreightNormalizationSuggestion | None:
        current = await self.repo.find_open(freight.id, suggestion_type)
        if current is not None:
            return None
        if suggestion_type == "ORIGIN":
            if freight.origin_match_level_code != "RAW" and freight.origin_city_code:
                return None
            raw_text = freight.raw_origin_text
            normalized, options, basis = await self._match_location(raw_text or "")
            return await self._create_location_suggestion(freight, suggestion_type, raw_text, freight.origin_match_level_code, normalized, options, basis, clean_task_id=clean_task_id)
        if suggestion_type == "DESTINATION":
            if freight.destination_match_level_code != "RAW" and freight.destination_city_code:
                return None
            raw_text = freight.raw_destination_text
            normalized, options, basis = await self._match_location(raw_text or "")
            return await self._create_location_suggestion(freight, suggestion_type, raw_text, freight.destination_match_level_code, normalized, options, basis, clean_task_id=clean_task_id)
        if freight.commodity_match_level_code != "RAW" and freight.commodity_standard_id is not None:
            return None
        raw_text = freight.raw_commodity_name or freight.cargo_title
        commodity_id, score, level, options, basis = await self._match_commodity(raw_text or "")
        if commodity_id is None or level == "RAW":
            return None
        return await self._create_suggestion(
            freight=freight,
            clean_task_id=clean_task_id,
            suggestion_type_code="COMMODITY",
            raw_text=raw_text,
            current_level_code=freight.commodity_match_level_code,
            suggested_level_code="STANDARD",
            confidence_score=score,
            auto_apply_flag=score is not None and score >= self.AUTO_COMMODITY_THRESHOLD,
            match_basis_json={"commodity": basis, "options": options},
            suggested_commodity_standard_id=commodity_id,
        )

    async def _create_location_suggestion(
        self,
        freight: Freight,
        suggestion_type: str,
        raw_text: str | None,
        current_level: str | None,
        normalized: dict[str, Any],
        options: list[dict[str, Any]],
        basis: dict[str, Any],
        clean_task_id: int | None = None,
    ) -> FreightNormalizationSuggestion | None:
        level = normalized.get("match_level_code")
        if level not in {"NODE", "CITY"}:
            return None
        score = _to_decimal_or_none(normalized.get("match_score")) or Decimal("0")
        return await self._create_suggestion(
            freight=freight,
            clean_task_id=clean_task_id,
            suggestion_type_code=suggestion_type,
            raw_text=raw_text,
            current_level_code=current_level,
            suggested_level_code=level,
            suggested_node_id=normalized.get("node_id"),
            suggested_province_code=normalized.get("province_code"),
            suggested_city_code=normalized.get("city_code"),
            suggested_district_code=normalized.get("district_code"),
            suggested_region_id=normalized.get("region_id"),
            confidence_score=score,
            auto_apply_flag=score >= self.AUTO_LOCATION_THRESHOLD,
            match_basis_json={"location": basis, "options": options},
        )

    async def _create_suggestion(self, **data: Any) -> FreightNormalizationSuggestion:
        now = datetime.utcnow()
        freight = data.pop("freight")
        auto_apply = bool(data.get("auto_apply_flag"))
        return await self.repo.create(
            {
                "freight_id": freight.id,
                "status_code": "PENDING",
                "before_json": _entity_snapshot(freight, self._freight_snapshot_fields()),
                "created_at": now,
                "updated_at": now,
                **data,
                "auto_apply_flag": auto_apply,
            }
        )

    async def _apply_suggestion(self, row: FreightNormalizationSuggestion, *, operator_id: int | None, auto: bool) -> None:
        freight = await self.freight_repo.get_freight_by_id(row.freight_id)
        if freight is None:
            raise NotFoundError("Freight", row.freight_id)
        updates = self._updates_from_suggestion(row)
        after_preview = dict(_entity_snapshot(freight, self._freight_snapshot_fields()))
        after_preview.update(_compact_json_value(updates))
        await self.freight_repo.update_freight(freight.id, updates)
        await self.repo.update(
            row.id,
            {
                "status_code": "AUTO_APPLIED" if auto else "APPLIED",
                "after_json": after_preview,
                "applied_at": datetime.utcnow(),
                "applied_by": operator_id,
            },
        )

    def _updates_from_suggestion(self, row: FreightNormalizationSuggestion) -> dict[str, Any]:
        if row.suggestion_type_code == "COMMODITY":
            return {
                "commodity_standard_id": row.suggested_commodity_standard_id,
                "commodity_match_level_code": row.suggested_level_code,
            }
        prefix = "origin" if row.suggestion_type_code == "ORIGIN" else "destination"
        return {
            f"{prefix}_node_id": row.suggested_node_id,
            f"{prefix}_province_code": row.suggested_province_code,
            f"{prefix}_city_code": row.suggested_city_code,
            f"{prefix}_district_code": row.suggested_district_code,
            f"{prefix}_region_id_cache": row.suggested_region_id,
            f"{prefix}_match_level_code": row.suggested_level_code,
        }

    async def _rebuild_affected_analysis(self, start_at: datetime, end_at: datetime) -> None:
        from app.modules.analysis.statistics import AnalysisStatisticsService

        service = AnalysisStatisticsService(self.db)
        start = start_at.date()
        end = end_at.date()
        await service.run_freight_flow_daily(start, end)
        await service.run_freight_commodity_daily(start, end)
        await service.run_freight_city_daily(start, end)
        await service.run_freight_node_daily(start, end)
        await self.db.commit()

    @staticmethod
    def _freight_snapshot_fields() -> list[str]:
        return [
            "freight_no",
            "cargo_title",
            "raw_commodity_name",
            "commodity_standard_id",
            "commodity_match_level_code",
            "raw_origin_text",
            "origin_node_id",
            "origin_city_code",
            "origin_match_level_code",
            "raw_destination_text",
            "destination_node_id",
            "destination_city_code",
            "destination_match_level_code",
        ]


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
