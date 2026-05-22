"""Shared freight service helpers, DTO presentation, and normalization primitives."""

from __future__ import annotations

import json
import re
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
from app.modules.freight.ai_evidence_gate import (
    apply_segment_evidence_gate,
    patch_semantic_map_with_gate_result,
    should_call_ai_repair,
    validate_semantic_map_contract,
)
from app.modules.freight.ai_text_index import FreightTextIndexer
from app.modules.freight.ai_structural_skeleton import (
    FreightParseBudget,
    FreightStructuralSkeletonBuilder,
    apply_skeleton_to_semantic_map,
    ensure_segments_for_route_clues,
)
from app.modules.freight.master_data_matcher import FreightMasterDataBatchMatcher, _is_packaging_only_commodity_text
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
    FreightNormalizationBulkActionResponse,
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
from app.modules.tasks.service import AsyncTaskRunService


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
    "FREIGHT_NORMALIZATION_TASK_STATUS",
    "FREIGHT_NORMALIZATION_REVIEW_STATUS",
    "FREIGHT_NORMALIZATION_SUGGESTION_STATUS",
]

AI_REVIEW_PASS = "PASS"
AI_REVIEW_REQUIRED = "REVIEW_REQUIRED"
AI_REVIEW_MANUAL_ACCEPTED = "MANUAL_ACCEPTED"
FREIGHT_AI_PIPELINE_VERSION = "freight_ai_semantic_pipeline_v3"

FREIGHT_STATUS_LABELS = {
    "DRAFT": "草稿",
    "PUBLISHED": "已发布",
    "MATCHING": "匹配中",
    "EXPIRED": "已过期",
    "CLOSED": "已关闭",
}

FREIGHT_STATUS_ACTIONS: dict[str, set[str]] = {
    "DRAFT": {"PUBLISHED", "CLOSED"},
    "PUBLISHED": {"MATCHING", "EXPIRED", "CLOSED"},
    "MATCHING": {"PUBLISHED", "CLOSED"},
    "EXPIRED": {"PUBLISHED", "CLOSED"},
    "CLOSED": set(),
}


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
        return "OPEN_PENDING_QUEUE", "去候选证据池"
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


def _parse_optional_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _parse_loading_time_hint(value: Any, *, base: datetime | None = None) -> tuple[datetime | None, datetime | None]:
    text = str(value or "").strip()
    if not text:
        return None, None
    now = base or datetime.utcnow()
    today = now.date()
    if "今晚" in text:
        start = datetime.combine(today, datetime.min.time()).replace(hour=18)
        end = datetime.combine(today, datetime.max.time())
        return start, end
    offset = 1 if "明天" in text else 2 if "后天" in text else None
    if offset is not None:
        day = today + timedelta(days=offset)
        return datetime.combine(day, datetime.min.time()), datetime.combine(day, datetime.max.time())
    match = re.search(r"(\d{1,2})(?:\s*[-—–]\s*(\d{1,2}))?\s*装", text)
    if not match:
        return None, None
    start_day = int(match.group(1))
    end_day = int(match.group(2) or start_day)
    year = today.year
    month = today.month
    try:
        start = datetime(year, month, start_day)
        end = datetime.combine(datetime(year, month, end_day).date(), datetime.max.time())
    except ValueError:
        return None, None
    if start.date() < today and today.day >= 25 and start_day <= 7:
        month = 1 if today.month == 12 else today.month + 1
        year = today.year + 1 if today.month == 12 else today.year
        try:
            start = datetime(year, month, start_day)
            end = datetime.combine(datetime(year, month, end_day).date(), datetime.max.time())
        except ValueError:
            return None, None
    return start, end


def _clean_contact_name(value: Any) -> str | None:
    text = str(value or "").strip()
    compact = text.replace(" ", "")
    if not compact or compact in {"微信", "同号", "微信同号", "电话", "联系", "联系电话"}:
        return None
    if "微信" in compact and "同号" in compact:
        return None
    return text


def _to_normalization_task_response(
    entity: FreightNormalizationTask,
    *,
    status_counts: dict[str, int] | None = None,
    type_counts: dict[str, int] | None = None,
    ctx: dict[str, Any] | None = None,
) -> FreightNormalizationTaskResponse:
    status_counts = status_counts or {}
    type_counts = type_counts or {}
    result_json = entity.result_json or {}
    return FreightNormalizationTaskResponse(
        id=entity.id,
        task_no=entity.task_no,
        celery_task_id=entity.celery_task_id,
        status_code=entity.status_code,
        review_status_code=getattr(entity, "review_status_code", None) or "NOT_REQUIRED",
        review_status_name=_label(ctx or {}, "FREIGHT_NORMALIZATION_REVIEW_STATUS", getattr(entity, "review_status_code", None) or "NOT_REQUIRED"),
        review_completed_at=getattr(entity, "review_completed_at", None),
        stage_code=entity.stage_code,
        stage_name=entity.stage_name,
        stage_message=entity.stage_message,
        progress_percent=entity.progress_percent,
        scanned_count=entity.scanned_count,
        suggestion_count=entity.suggestion_count,
        auto_applied_count=entity.auto_applied_count,
        pending_count=entity.pending_count,
        applied_count=status_counts.get("APPLIED", 0),
        rejected_count=status_counts.get("REJECTED", 0),
        failed_count=entity.failed_count,
        suggestion_status_counts=status_counts,
        suggestion_type_counts=type_counts,
        affected_date_from=_parse_optional_datetime(result_json.get("affected_date_from")),
        affected_date_to=_parse_optional_datetime(result_json.get("affected_date_to")),
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
    status_code = str(entity.status_code or "NEW").upper()
    stage_name = _label(ctx, "FREIGHT_TMS_INBOUND_STATUS", status_code) or status_code
    progress_map = {
        "NEW": 0,
        "QUEUED": 8,
        "PARSING": 45,
        "PARSED": 100,
        "PARTIAL_FAILED": 100,
        "FAILED": 100,
    }
    heartbeat_at = entity.processed_at or entity.updated_at
    heartbeat_age = max(0, int((datetime.utcnow() - heartbeat_at).total_seconds())) if heartbeat_at else None
    stale_seconds = int(ctx.get("stale_heartbeat_seconds") or settings.FREIGHT_AI_STALE_HEARTBEAT_SECONDS)
    is_stale = status_code in {"QUEUED", "PARSING"} and (
        heartbeat_age is None or heartbeat_age >= max(30, stale_seconds)
    )
    if status_code == "QUEUED":
        stage_message = "解析任务已提交，等待后台 worker 消费"
    elif status_code == "PARSING":
        stage_message = "AI 正在解析 TMS 结构化入站内容"
    elif status_code == "PARSED":
        stage_message = f"解析完成，生成 {entity.candidate_count} 条候选货源"
    elif status_code in {"FAILED", "PARTIAL_FAILED"}:
        stage_message = entity.error_message or "解析失败，可检查原文后重试"
    else:
        stage_message = "入站记录已保存，尚未提交解析"
    elapsed_seconds = 0
    if entity.processed_at and entity.created_at:
        elapsed_seconds = max(0, int((entity.processed_at - entity.created_at).total_seconds()))
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
        status_name=stage_name,
        clue_count=entity.clue_count,
        candidate_count=entity.candidate_count,
        processed_at=entity.processed_at,
        error_message=entity.error_message,
        prompt_version=entity.prompt_version,
        parse_stage_code=status_code,
        parse_stage_name=stage_name,
        parse_stage_message=stage_message,
        parse_progress_percent=progress_map.get(status_code, 0),
        parse_heartbeat_at=heartbeat_at,
        parse_is_stale=is_stale,
        parse_heartbeat_age_seconds=heartbeat_age,
        ai_elapsed_seconds=elapsed_seconds,
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

    async def _master_data_matcher(self) -> FreightMasterDataBatchMatcher:
        matcher = getattr(self, "_freight_master_data_matcher", None)
        if matcher is None:
            matcher = FreightMasterDataBatchMatcher(self.db)
            await matcher._load_once()
            self._freight_master_data_matcher = matcher
        return matcher

    async def _match_commodity(self, raw_name: str) -> tuple[int | None, Decimal | None, str | None, list[dict[str, Any]], dict[str, Any]]:
        matcher = await self._master_data_matcher()
        return matcher.match_commodity(raw_name)

    async def _match_location(
        self, raw_text: str, ai_level_code: str | None = None
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        matcher = await self._master_data_matcher()
        return matcher.match_location(raw_text, ai_level_code)

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
            title = " - ".join([item for item in pieces if item])[:256] or "候选货源"
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
        loading_time_from = _parse_optional_datetime(segment.get("loading_time_from"))
        loading_time_to = _parse_optional_datetime(segment.get("loading_time_to"))
        if loading_time_from is None and loading_time_to is None:
            loading_time_from, loading_time_to = _parse_loading_time_hint(
                _first(segment, "loading_time_text", "loading_time", "loading_date_text")
            )
        contact_name = _clean_contact_name(_first(segment, "contact_name", "contact"))
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
            "field_evidence": segment.get("field_evidence") or {},
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
            "field_quality_gate": (
                (segment.get("ai_review_json") or {}).get("field_quality_gate")
                if isinstance(segment.get("ai_review_json"), dict)
                else None
            ),
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
            "loading_time_from": loading_time_from,
            "loading_time_to": loading_time_to,
            "unloading_time_from": _parse_optional_datetime(segment.get("unloading_time_from")),
            "unloading_time_to": _parse_optional_datetime(segment.get("unloading_time_to")),
            "publisher_org_name": _first(segment, "publisher_org_name", "shipper", "company"),
            "contact_name": contact_name,
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




__all__ = [name for name in globals() if not name.startswith("__")]
