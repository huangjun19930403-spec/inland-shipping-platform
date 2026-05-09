"""vessel 模块 service。"""

from __future__ import annotations

import logging
import asyncio
import hashlib
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import UploadFile
from sqlalchemy import and_, case, delete, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.exceptions import AppException, ConflictError, NotFoundError, ValidationError
from app.integrations.ai.vessel_image_assistant import VesselCertificateImageAssistant
from app.integrations.config_keys import ES_R_HOST, ES_R_INDEX, ES_REALTIME_CONFIG_PROFILE
from app.integrations.config_keys import (
    VESSEL_AIS_ES_BATCH_SIZE,
    VESSEL_AIS_ES_MAX_CONCURRENCY,
    VESSEL_AIS_PROFILE_LIMIT,
    VESSEL_AIS_UNMATCHED_SCAN_LIMIT,
)
from app.integrations.es import RealtimeEsClient
from app.models.address import AdminRegion, AdminRegionBoundary, Region
from app.models.audit import AuditRecord, AuditTask, AuditTaskSnapshot
from app.models.dictionary import StdDict, StdDictItem
from app.models.vessel import (
    VesselAffiliationEvidence,
    VesselAisCitySnapshotItem,
    VesselAisSnapshot,
    VesselBuildInfo,
    VesselCapacityDimension,
    VesselCertificate,
    VesselCertificateFile,
    VesselCertificateImageRecognition,
    VesselCertificateRequirementRule,
    VesselChangeEvent,
    VesselContact,
    VesselControllerEvidence,
    VesselCrewAssignment,
    VesselDataQualityIssue,
    VesselIdentifierHistory,
    VesselIdentityLink,
    VesselNameHistory,
    VesselLatestPositionSnapshot,
    VesselOperatorPeriod,
    VesselOwnerDocument,
    VesselOwnerDocumentImageRecognition,
    VesselOwnerPeriod,
    VesselPersonCertificate,
    VesselPersonCertificateFile,
    VesselPersonCertificateImageRecognition,
    VesselProfile,
    VesselProfileSummary,
    VesselRecognitionAdoptionRecord,
    VesselRecognitionFieldDiff,
    VesselRegistrationInfo,
    VesselRiskSignal,
)
from app.modules.dictionary.service import CodeSequenceService
from app.modules.address.boundary_utils import (
    BOUNDARY_SIMPLIFY_TOLERANCE as CITY_BOUNDARY_SIMPLIFY_TOLERANCE,
    bbox_contains as _bbox_contains,
    boundary_paths_for_precision as _boundary_paths_for_precision,
    extract_geojson_polygons as _extract_geojson_polygons,
    point_in_polygon_with_holes as _point_in_polygon_with_holes,
    polygons_bbox as _polygons_bbox,
    serialize_boundary_paths as _serialize_boundary_paths,
)
from app.modules.address.geometry import normalize_boundary_geometry
from app.modules.storage.service import FileStorageService
from app.modules.system.runtime_config import RuntimeConfigService
from app.modules.vessel.repository import VesselRepository
from app.modules.vessel.schemas import (
    PageResponse,
    VesselAisSituationCardResponse,
    VesselAffiliationEvidenceResponse,
    VesselAssetDistributionItemResponse,
    VesselBuildInfoResponse,
    VesselCapacityResponse,
    VesselCertificateFileResponse,
    VesselCertificateImageRecognitionResponse,
    VesselCertificateLedgerItemResponse,
    VesselCertificateResponse,
    VesselChangeEventResponse,
    VesselContactResponse,
    VesselCrewResponse,
    VesselBusinessSituationCardResponse,
    VesselDetailResponse,
    VesselIdentifierHistoryResponse,
    VesselAssetPageResponse,
    VesselAssetListItemResponse,
    VesselAssetSummaryResponse,
    VesselCertificateRequirementRuleResponse,
    VesselComplianceRiskResponse,
    VesselControllerEvidenceResponse,
    VesselListItemResponse,
    VesselNameHistoryResponse,
    VesselOperatorResponse,
    VesselOwnerDocumentCompletenessResponse,
    VesselOwnerDocumentLedgerItemResponse,
    VesselOwnerResponse,
    VesselOwnerDocumentImageRecognitionResponse,
    VesselOwnerDocumentResponse,
    VesselPersonCertificateFileResponse,
    VesselPersonCertificateImageRecognitionResponse,
    VesselPersonCertificateResponse,
    VesselQualityIssueResponse,
    VesselRecognitionAdoptionRecordResponse,
    VesselRecognitionFieldDiffResponse,
    VesselPositionCitySituationItemResponse,
    VesselPositionCitySituationResponse,
    VesselPositionCitySituationSummary,
    VesselPositionCityVesselsResponse,
    VesselAisCityBoundaryItemResponse,
    VesselAisCityBoundaryResponse,
    VesselAisSnapshotResponse,
    VesselAisUnmatchedMmsiResponse,
    VesselPositionMonitorItemResponse,
    VesselPositionMonitorResponse,
    VesselPositionMonitorSummary,
    VesselShipTypeDistributionItemResponse,
    VesselProfileResponse,
    VesselProfileCardBaseCard,
    VesselProfileCardEvidenceItem,
    VesselProfileCardEvidenceResponse,
    VesselProfileCardIssueSummary,
    VesselProfileCardResponse,
    VesselProfileCardSourceTrace,
    VesselProfileCandidateCard,
    VesselProfileComplianceCard,
    VesselProfileIdentityCard,
    VesselProfileQualityCard,
    VesselProfileRecognitionCard,
    VesselProfileRelationCard,
    VesselProfileTrajectoryCard,
    VesselQualityIssueListItemResponse,
    VesselQualityIssueVesselSummary,
    VesselRecognitionQueueItemResponse,
    VesselRegistrationResponse,
    VesselRiskSignalResponse,
    VesselRiskSignalVesselSummary,
)

try:  # Redis is optional for local development; memory cache remains the fallback.
    from redis.asyncio import Redis
except Exception:  # pragma: no cover - optional dependency guard
    Redis = None  # type: ignore[assignment]


LABEL_DICTS = [
    "SHIP_TYPE",
    "VESSEL_PROFILE_STATUS",
    "VESSEL_IDENTITY_STATUS",
    "SHIP_OPERATION_STATUS",
    "SOURCE_TYPE",
    "AUDIT_STATUS",
    "CONTACT_ROLE",
    "CONTACT_SCOPE",
    "VESSEL_CREW_ROLE",
    "PARTY_SUBJECT_TYPE",
    "CERTIFICATE_TYPE",
    "VESSEL_CERTIFICATE_TYPE",
    "CREW_CERTIFICATE_TYPE",
    "OWNER_DOCUMENT_TYPE",
    "CERTIFICATE_VERIFY_STATUS",
    "VESSEL_CERTIFICATE_IMAGE_RECOGNITION_STATUS",
    "VESSEL_POSITION_SOURCE_STATUS",
    "VESSEL_CHANGE_EVENT_TYPE",
    "VESSEL_RELATION_VERIFIED_STATUS",
    "VESSEL_QUALITY_ISSUE_TYPE",
    "VESSEL_QUALITY_ISSUE_STATUS",
    "VESSEL_CONFIDENCE_LEVEL",
    "VESSEL_RISK_LEVEL",
    "VESSEL_AIS_FRESHNESS_LEVEL",
    "VESSEL_ANALYSIS_SAMPLE_TAG",
    "VESSEL_DATA_SOURCE_TYPE",
    "VESSEL_SUMMARY_STATUS",
    "VESSEL_RISK_SIGNAL_TYPE",
    "VESSEL_RISK_SIGNAL_STATUS",
    "VESSEL_REQUIREMENT_RULE_STATUS",
    "VESSEL_RULE_SCOPE_TYPE",
    "VESSEL_CONTROLLER_ROLE",
    "VESSEL_AFFILIATION_TYPE",
]


REQUIRED_VESSEL_CERTIFICATE_TYPES = [
    "VESSEL_OWNERSHIP_CERT",
    "VESSEL_NATIONALITY_CERT",
    "VESSEL_OPERATION_CERT",
    "VESSEL_INSPECTION_BOOK",
    "VESSEL_SEAWORTHINESS_CERT",
    "VESSEL_AIS_CERT",
]
VALID_VESSEL_CERTIFICATE_TYPES = set(REQUIRED_VESSEL_CERTIFICATE_TYPES) | {"UNKNOWN", "OTHER"}
CREW_CERTIFICATE_TYPE = "CREW_COMPETENCY_CERT"
ACTIVE_RECOGNITION_STATUSES = {"QUEUED", "PROCESSING"}
CURRENT_RECOGNITION_STATUSES = {"QUEUED", "PROCESSING", "NEED_CONFIRM", "FAILED"}
LOW_CONFIDENCE_SCORE_THRESHOLD = 80
IMAGE_RECOGNIZABLE_OWNER_DOCUMENT_TYPES = {"PERSON_ID_FRONT", "PERSON_ID_BACK", "BUSINESS_LICENSE"}
OWNER_DOCUMENT_LEDGER_TYPES = [
    "PERSON_ID_FRONT",
    "PERSON_ID_BACK",
    "BUSINESS_LICENSE",
    "AUTHORIZATION_DOC",
    "AFFILIATION_PROOF",
    "PERSON_VESSEL_PHOTO",
    "VESSEL_PHOTO",
    "OTHER",
]
OWNER_REQUIRED_DOCUMENT_TYPES_BY_PARTY = {
    "PERSON": {"PERSON_ID_FRONT", "PERSON_ID_BACK"},
    "COMPANY": {"BUSINESS_LICENSE"},
}
UNKNOWN_CITY_CODE = "UNKNOWN"
UNKNOWN_CITY_NAME = "未知城市"
CURRENT_CITY_SOURCE_ADMIN_BOUNDARY = "ADMIN_BOUNDARY"
CURRENT_CITY_SOURCE_UNKNOWN = "UNKNOWN"
CURRENT_CITY_SOURCE_INVALID_POSITION = "INVALID_POSITION"
CITY_BOUNDARY_CACHE_TTL_SECONDS = 1800
CITY_GRID_CELL_SIZE_DEGREES = 1.0
CITY_SITUATION_CACHE_KEY_PREFIX = "vessel:city_situation:response:"
CITY_SITUATION_SNAPSHOT_KEY_PREFIX = "vessel:city_situation:snapshot:"
CITY_SITUATION_SNAPSHOT_TTL_SECONDS = settings.VESSEL_CITY_SITUATION_SNAPSHOT_TTL_SECONDS
CITY_SITUATION_SNAPSHOT_MAX_SIZE = 20
ACTIVE_PROFILE_STATUS = "ACTIVE"
ACTIVE_ISSUE_STATUSES = {"OPEN", "IN_PROGRESS"}
CERTIFICATE_PROFILE_ADOPTION_FIELDS = {
    "ship_name",
    "current_mmsi",
    "ship_type_code",
    "deadweight_ton",
    "total_tonnage",
    "net_tonnage",
    "length_m",
    "width_m",
    "depth_m",
    "design_draft_m",
}
OWNER_DOCUMENT_ADOPTABLE_FIELDS = {"certificate_no", "address"}
SUMMARY_VERSION = "ROUND_3_V1"
SUMMARY_READY_STATUSES = {"READY", "PARTIAL", "STALE"}
COMPLIANCE_ACTIVE_STATUSES = {"OPEN", "IN_REVIEW", "EVIDENCE_ADDED"}
COMPLIANCE_CLOSED_STATUSES = {"MITIGATED", "CLOSED", "FALSE_POSITIVE"}
COMPLIANCE_VERSION = "ROUND_5_V1"
COMPLIANCE_NOT_COMPUTABLE_NOTE = "货类/航区/船型适配缺少明确业务上下文，Round 5 标记为 NOT_COMPUTABLE，不输出候选结论"
SUMMARY_REQUIRED_FIELDS = [
    ("ship_name", "船名"),
    ("current_mmsi", "MMSI"),
    ("ship_type_code", "船型"),
    ("deadweight_ton", "载重吨"),
    ("length_m", "船长"),
    ("width_m", "船宽"),
    ("design_draft_m", "设计吃水"),
    ("primary_owner_name", "主所有方"),
    ("primary_operator_name", "主运营方"),
    ("primary_contact_name", "主联系人"),
    ("certificate_evidence", "证书基础证据"),
]
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _CityBoundary:
    code: str
    name: str
    center_longitude: Decimal | None
    center_latitude: Decimal | None
    area_km2: Decimal | None
    bbox: tuple[float, float, float, float]
    bbox_area: float
    polygons: list[list[list[tuple[float, float]]]]
    boundary_paths_by_precision: dict[str, list[list[tuple[float, float]]]] | None = None


@dataclass(slots=True)
class _ResolvedCity:
    city_code: str | None
    city_name: str
    current_city_source: str
    city_center_longitude: Decimal | None = None
    city_center_latitude: Decimal | None = None
    matched_city_candidates: list[dict[str, Any]] | None = None


@dataclass(slots=True)
class _PositionBuildResult:
    items: list[VesselPositionMonitorItemResponse]
    partial: bool
    error_message: str | None
    failed_batch_count: int
    queried_mmsi_count: int
    matched_position_count: int
    unpositioned_count: int
    invalid_position_count: int
    unknown_city_count: int
    unmatched_positions: list[dict[str, Any]] = field(default_factory=list)
    invalid_positions: list[dict[str, Any]] = field(default_factory=list)
    source_indices: list[str] = field(default_factory=list)
    failed_batches: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class _CitySituationSnapshot:
    snapshot_id: str
    expires_at: datetime
    items: list[VesselPositionMonitorItemResponse]
    partial: bool
    error_message: str | None
    generated_at: datetime
    status_code: str = "READY"
    refresh_required: bool = False


@dataclass(slots=True)
class _CitySituationResponseCacheEntry:
    expires_at: datetime
    response: VesselPositionCitySituationResponse


_CITY_BOUNDARY_CACHE: dict[str, Any] = {"loaded_at": None, "boundaries": [], "grid_index": {}}
_CITY_SITUATION_SNAPSHOTS: dict[str, _CitySituationSnapshot] = {}
_CITY_SITUATION_RESPONSE_CACHE: dict[str, _CitySituationResponseCacheEntry] = {}
_CITY_SITUATION_REDIS_CLIENT: Any | None = None


def _dispatch_certificate_recognition_task(recognition_id: int) -> None:
    from app.tasks.vessel_ai_tasks import recognize_vessel_certificate_image_task

    recognize_vessel_certificate_image_task.delay(recognition_id)


def _dispatch_person_recognition_task(recognition_id: int) -> None:
    from app.tasks.vessel_ai_tasks import recognize_vessel_person_certificate_image_task

    recognize_vessel_person_certificate_image_task.delay(recognition_id)


def _dispatch_owner_document_recognition_task(recognition_id: int) -> None:
    from app.tasks.vessel_ai_tasks import recognize_vessel_owner_document_image_task

    recognize_vessel_owner_document_image_task.delay(recognition_id)


def _row_dict(row: Any) -> dict[str, Any]:
    return {key: value for key, value in vars(row).items() if not key.startswith("_")}


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _normalized_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True)
    else:
        text = str(value)
    return " ".join(text.strip().lower().split())


def _quality_fingerprint(
    issue_type: str,
    profile_id: int | None,
    object_type: str,
    object_id: str | int | None,
    field_name: str | None,
    normalized_key: str,
) -> str:
    normalized = _normalized_text(normalized_key)
    normalized_object_id = _normalized_text(object_id or "")
    if issue_type == "MMSI_CONFLICT":
        raw = f"MMSI_CONFLICT|mmsi|{normalized_object_id or normalized.rsplit('|', 1)[-1]}"
    elif issue_type == "PRIMARY_RELATION_MISSING":
        raw = f"PRIMARY_RELATION_MISSING|profile|{profile_id or ''}|{normalized.rsplit('|', 1)[-1]}"
    elif issue_type == "PROFILE_FIELD_MISSING":
        raw = f"PROFILE_FIELD_MISSING|profile|{profile_id or ''}|{field_name or normalized.rsplit('|', 1)[-1]}"
    elif issue_type == "OCR_UNCONFIRMED":
        raw = f"OCR_UNCONFIRMED|recognition|{normalized_object_id or normalized.rsplit('|', 1)[-1]}"
    elif issue_type == "AIS_UNMATCHED":
        raw = f"AIS_UNMATCHED|mmsi|{normalized_object_id or normalized.rsplit('|', 1)[-1]}"
    elif issue_type == "POSITION_STALE":
        raw = f"POSITION_STALE|profile|{profile_id or ''}|{normalized_object_id or normalized.rsplit('|', 1)[-1]}"
    else:
        raw = "|".join(
            [
                issue_type,
                str(profile_id or ""),
                object_type,
                str(object_id or ""),
                field_name or "",
                normalized,
            ]
        )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _risk_fingerprint(profile_id: int, risk_type: str, rule_code: str | None, evidence_key: str) -> str:
    raw = "|".join([str(profile_id), risk_type, rule_code or "", _normalized_text(evidence_key)])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _risk_rank(level: str | None) -> int:
    return {"HIGH": 4, "MEDIUM": 3, "LOW": 2, "UNKNOWN": 1}.get(level or "UNKNOWN", 1)


def _max_risk_level(levels: list[str]) -> str:
    if not levels:
        return "UNKNOWN"
    return max(levels, key=_risk_rank)


async def _upsert_quality_issue_in_session(
    db: AsyncSession,
    *,
    issue_type_code: str,
    profile_id: int | None,
    object_type: str,
    object_id: str | int | None,
    normalized_key: str,
    field_name: str | None = None,
    evidence_source: str | None = None,
    severity_code: str = "MEDIUM",
    impact_scope: list[dict[str, Any]] | None = None,
) -> VesselDataQualityIssue:
    fingerprint = _quality_fingerprint(issue_type_code, profile_id, object_type, object_id, field_name, normalized_key)
    row = await db.scalar(
        select(VesselDataQualityIssue).where(
            VesselDataQualityIssue.fingerprint == fingerprint,
            VesselDataQualityIssue.status_code.in_(ACTIVE_ISSUE_STATUSES),
        )
    )
    if row is None:
        row = VesselDataQualityIssue(
            issue_type_code=issue_type_code,
            severity_code=severity_code,
            affected_object_type=object_type,
            affected_object_id=str(object_id or ""),
            vessel_profile_id=profile_id,
            field_name=field_name,
            fingerprint=fingerprint,
            evidence_source=evidence_source,
            impact_scope_json=impact_scope or [],
            status_code="OPEN",
        )
        db.add(row)
    else:
        row.severity_code = severity_code
        row.evidence_source = evidence_source
        row.impact_scope_json = impact_scope or row.impact_scope_json
    await db.flush()
    return row


def _changed_fields(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[str]:
    if not before or not after:
        return []
    return sorted(
        key
        for key in set(before) | set(after)
        if _jsonable(before.get(key)) != _jsonable(after.get(key))
    )


def _relation_is_effective(row: Any) -> bool:
    return (
        getattr(row, "voided_at", None) is None
        and bool(getattr(row, "is_current", True))
        and getattr(row, "end_date", None) is None
    )


def _ensure_relation_writable(row: Any, *, require_current: bool = True) -> None:
    if getattr(row, "voided_at", None) is not None:
        raise ConflictError(
            "关系记录已作废，不能继续修改",
            code="RELATION_VOIDED",
            detail={"id": getattr(row, "id", None)},
        )
    if require_current and (getattr(row, "end_date", None) is not None or bool(getattr(row, "is_current", True)) is False):
        raise ConflictError(
            "关系记录已进入历史，不能继续修改",
            code="RELATION_NOT_CURRENT",
            detail={"id": getattr(row, "id", None)},
        )


def _city_situation_cache_ttl() -> int:
    return max(5, int(settings.VESSEL_CITY_SITUATION_CACHE_TTL_SECONDS or 60))


def _city_snapshot_ttl() -> int:
    return max(30, int(settings.VESSEL_CITY_SITUATION_SNAPSHOT_TTL_SECONDS or CITY_SITUATION_SNAPSHOT_TTL_SECONDS))


def _city_cache_backend_setting() -> str:
    return (settings.VESSEL_CITY_SITUATION_CACHE_BACKEND or "redis").strip().lower()


def _city_shared_cache_required() -> bool:
    app_env = str(getattr(settings, "APP_ENV", "") or "").strip().lower()
    return app_env in {"prod", "production"} or not bool(getattr(settings, "DEBUG", True))


def _safe_int(value: Any, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def _city_situation_query_cache_key(query: Any) -> str:
    payload = query.model_dump(mode="json") if hasattr(query, "model_dump") else dict(query)
    payload.pop("force_refresh", None)
    normalized = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _money(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _percent(numerator: int | float | Decimal, denominator: int | float | Decimal) -> Decimal:
    if not denominator:
        return Decimal("0.00")
    return (Decimal(str(numerator)) * Decimal("100") / Decimal(str(denominator))).quantize(Decimal("0.01"))


def _level_from_score(score: Decimal | None) -> str:
    if score is None:
        return "UNKNOWN"
    if score >= Decimal("85"):
        return "HIGH"
    if score >= Decimal("65"):
        return "MEDIUM"
    return "LOW"


def _coverage_confidence_level(coverage_rate: Decimal, failed_count: int = 0) -> str:
    if coverage_rate <= 0:
        return "UNKNOWN"
    adjusted = max(Decimal("0"), coverage_rate - Decimal(str(failed_count * 5)))
    return _level_from_score(adjusted)


def _mask_phone(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if len(text) <= 4:
        return "*" * len(text)
    if len(text) <= 7:
        return f"{text[0]}***{text[-2:]}"
    return f"{text[:3]}****{text[-4:]}"


def _tag_key(tags: list[str]) -> str:
    return "|" + "|".join(tags) + "|" if tags else ""


def _ship_age(building_year: int | None) -> int | None:
    if not building_year:
        return None
    current_year = datetime.utcnow().year
    if building_year > current_year:
        return None
    return current_year - building_year


def _size_text(capacity: VesselCapacityDimension | None) -> str | None:
    if capacity is None:
        return None
    parts: list[str] = []
    if capacity.length_m is not None:
        parts.append(f"{capacity.length_m}m")
    if capacity.width_m is not None:
        parts.append(f"{capacity.width_m}m")
    if capacity.design_draft_m is not None:
        parts.append(f"吃水{capacity.design_draft_m}m")
    return " / ".join(parts) if parts else None


def _source_status_name(code: str) -> str:
    return {
        "AVAILABLE": "实时船位可用",
        "EMPTY": "暂无实时船位",
        "UNCONFIGURED": "实时 ES 未配置",
        "PARTIAL": "实时船位部分可用",
        "ERROR": "实时船位异常",
    }.get(code, code)


def _ais_freshness_level(age_minutes: int | None) -> str:
    if age_minutes is None:
        return "UNKNOWN"
    if age_minutes <= 120:
        return "FRESH"
    if age_minutes <= 720:
        return "RECENT"
    if age_minutes <= 4320:
        return "STALE"
    return "EXPIRED"


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None


def _parse_position_time(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        raw = float(value)
        if raw > 10_000_000_000:
            raw = raw / 1000
        try:
            return datetime.utcfromtimestamp(raw)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _first_value(payload: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def _looks_long_term(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if not text:
        return False
    return any(token in text for token in ["长期", "永久", "long-term", "long term", "permanent", "forever"])


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "on", "长期", "长期有效", "永久", "permanent", "forever"}


def _to_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


async def _load_label_map(db: AsyncSession, dict_codes: list[str] | None = None) -> dict[str, dict[str, str]]:
    codes = dict_codes or LABEL_DICTS
    rows = (
        await db.execute(
            select(StdDict.dict_code, StdDictItem.item_code, StdDictItem.item_name)
            .join(StdDictItem, StdDictItem.dict_id == StdDict.id)
            .where(StdDict.dict_code.in_(codes), StdDict.status == 1, StdDictItem.status == 1)
        )
    ).all()
    label_map: dict[str, dict[str, str]] = {code: {} for code in codes}
    for dict_code, item_code, item_name in rows:
        label_map.setdefault(dict_code, {})[item_code] = item_name
    return label_map


async def _load_city_map(db: AsyncSession, city_codes: list[str]) -> dict[str, str]:
    codes = sorted({code for code in city_codes if code})
    if not codes:
        return {}
    rows = (await db.execute(select(AdminRegion.code, AdminRegion.name).where(AdminRegion.code.in_(codes)))).all()
    return {code: name for code, name in rows}


async def _load_region_map(db: AsyncSession, region_ids: list[int]) -> dict[int, str]:
    ids = sorted({region_id for region_id in region_ids if region_id})
    if not ids:
        return {}
    rows = (await db.execute(select(Region.id, Region.name).where(Region.id.in_(ids)))).all()
    return {region_id: name for region_id, name in rows}


def _grid_range(min_value: float, max_value: float) -> range:
    import math

    start = math.floor(min_value / CITY_GRID_CELL_SIZE_DEGREES)
    end = math.floor(max_value / CITY_GRID_CELL_SIZE_DEGREES)
    return range(start, end + 1)


def _grid_key(longitude: float, latitude: float) -> tuple[int, int]:
    import math

    return (
        math.floor(longitude / CITY_GRID_CELL_SIZE_DEGREES),
        math.floor(latitude / CITY_GRID_CELL_SIZE_DEGREES),
    )


def _build_city_boundary_grid(boundaries: list[_CityBoundary]) -> dict[tuple[int, int], list[_CityBoundary]]:
    grid: dict[tuple[int, int], list[_CityBoundary]] = defaultdict(list)
    for boundary in boundaries:
        min_x, min_y, max_x, max_y = boundary.bbox
        for x_index in _grid_range(min_x, max_x):
            for y_index in _grid_range(min_y, max_y):
                grid[(x_index, y_index)].append(boundary)
    return dict(grid)


def _profile_response(
    row: VesselProfile,
    *,
    label_map: dict[str, dict[str, str]] | None = None,
    city_map: dict[str, str] | None = None,
    region_map: dict[int, str] | None = None,
) -> VesselProfileResponse:
    label_map = label_map or {}
    city_map = city_map or {}
    region_map = region_map or {}
    return VesselProfileResponse(
        **_row_dict(row),
        ship_type_name=label_map.get("SHIP_TYPE", {}).get(row.ship_type_code or ""),
        profile_status_name=label_map.get("VESSEL_PROFILE_STATUS", {}).get(row.profile_status_code),
        identity_status_name=label_map.get("VESSEL_IDENTITY_STATUS", {}).get(row.identity_status_code),
        operation_status_name=label_map.get("SHIP_OPERATION_STATUS", {}).get(row.operation_status_code or ""),
        source_type_name=label_map.get("SOURCE_TYPE", {}).get(row.source_type_code),
        audit_status_name=label_map.get("AUDIT_STATUS", {}).get(row.audit_status),
        registry_city_name=city_map.get(row.registry_city_code or ""),
        business_region_name=region_map.get(row.business_region_id or 0),
    )


class VesselService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = VesselRepository(db)
        self.runtime_config = RuntimeConfigService(db)

    async def _realtime_es_host(self) -> str:
        value = await self.runtime_config.get_value(
            ES_R_HOST,
            settings.ES_R_HOST or "",
            profile_code=ES_REALTIME_CONFIG_PROFILE,
        )
        return (value or "").strip()

    async def _ais_runtime_limits(self) -> dict[str, int]:
        profile_limit = await self.runtime_config.get_int(
            VESSEL_AIS_PROFILE_LIMIT,
            int(settings.VESSEL_AIS_PROFILE_LIMIT or 2000),
            profile_code=ES_REALTIME_CONFIG_PROFILE,
        )
        batch_size = await self.runtime_config.get_int(
            VESSEL_AIS_ES_BATCH_SIZE,
            int(settings.VESSEL_AIS_ES_BATCH_SIZE or 500),
            profile_code=ES_REALTIME_CONFIG_PROFILE,
        )
        max_concurrency = await self.runtime_config.get_int(
            VESSEL_AIS_ES_MAX_CONCURRENCY,
            int(settings.VESSEL_AIS_ES_MAX_CONCURRENCY or 4),
            profile_code=ES_REALTIME_CONFIG_PROFILE,
        )
        unmatched_scan_limit = await self.runtime_config.get_int(
            VESSEL_AIS_UNMATCHED_SCAN_LIMIT,
            int(settings.VESSEL_AIS_UNMATCHED_SCAN_LIMIT or 1000),
            profile_code=ES_REALTIME_CONFIG_PROFILE,
        )
        return {
            "profile_limit": _safe_int(profile_limit, 2000, minimum=1, maximum=20000),
            "es_batch_size": _safe_int(batch_size, 500, minimum=1, maximum=2000),
            "es_max_concurrency": _safe_int(max_concurrency, 4, minimum=1, maximum=16),
            "unmatched_scan_limit": _safe_int(unmatched_scan_limit, 1000, minimum=1, maximum=10000),
        }

    async def _city_cache_backend(self) -> str:
        setting = _city_cache_backend_setting()
        if setting not in {"memory", "redis"}:
            raise AppException(
                "AIS 城市态势缓存配置非法，仅支持 redis 或 memory",
                code="VESSEL_AIS_CACHE_BACKEND_INVALID",
                status_code=503,
                detail={"cache_backend": setting},
            )
        shared_required = _city_shared_cache_required()
        if setting == "memory":
            if shared_required:
                raise AppException(
                    "生产环境 AIS 城市态势必须配置 Redis 快照缓存，禁止使用 memory",
                    code="VESSEL_AIS_MEMORY_CACHE_FORBIDDEN",
                    status_code=503,
                    detail={
                        "cache_backend": setting,
                        "app_env": getattr(settings, "APP_ENV", None),
                        "debug": getattr(settings, "DEBUG", None),
                    },
                )
            return "memory"
        if Redis is None:
            if shared_required:
                raise AppException(
                    "生产环境 AIS 城市态势 Redis 客户端不可用",
                    code="VESSEL_AIS_REDIS_UNAVAILABLE",
                    status_code=503,
                    detail={"cache_backend": setting},
                )
            logger.warning("city situation redis client unavailable; falling back to memory cache")
            return "memory"
        try:
            redis_client = await self._city_redis()
            if redis_client is not None:
                await redis_client.ping()
                return "redis"
        except Exception as exc:  # noqa: BLE001
            if shared_required:
                raise AppException(
                    "生产环境 AIS 城市态势 Redis 不可用",
                    code="VESSEL_AIS_REDIS_UNAVAILABLE",
                    status_code=503,
                    detail={"cache_backend": setting, "error": str(exc)},
                ) from exc
            logger.warning("city situation redis unavailable; falling back to memory cache: %s", exc)
        return "memory"

    async def _city_redis(self) -> Any | None:
        global _CITY_SITUATION_REDIS_CLIENT
        if Redis is None:
            return None
        if _CITY_SITUATION_REDIS_CLIENT is None:
            _CITY_SITUATION_REDIS_CLIENT = Redis.from_url(
                settings.CELERY_BROKER_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=0.25,
                socket_timeout=0.8,
            )
        return _CITY_SITUATION_REDIS_CLIENT

    async def _get_city_situation_response_cache(
        self,
        cache_key: str,
    ) -> tuple[VesselPositionCitySituationResponse, str] | None:
        now = datetime.utcnow()
        shared_required = _city_shared_cache_required()
        if await self._city_cache_backend() == "redis":
            try:
                redis_client = await self._city_redis()
                payload = await redis_client.get(CITY_SITUATION_CACHE_KEY_PREFIX + cache_key) if redis_client else None
                if payload:
                    return VesselPositionCitySituationResponse.model_validate_json(payload), "redis"
            except Exception as exc:  # noqa: BLE001
                logger.warning("city situation redis cache read failed: %s", exc)
            if shared_required:
                return None
        if shared_required:
            return None
        cached = _CITY_SITUATION_RESPONSE_CACHE.get(cache_key)
        if cached is None:
            return None
        if cached.expires_at <= now:
            _CITY_SITUATION_RESPONSE_CACHE.pop(cache_key, None)
            return None
        return cached.response.model_copy(deep=True), "memory"

    async def _store_city_situation_response_cache(
        self,
        cache_key: str,
        response: VesselPositionCitySituationResponse,
    ) -> None:
        ttl = _city_situation_cache_ttl()
        shared_required = _city_shared_cache_required()
        if await self._city_cache_backend() == "redis":
            try:
                redis_client = await self._city_redis()
                if redis_client is not None:
                    await redis_client.setex(CITY_SITUATION_CACHE_KEY_PREFIX + cache_key, ttl, response.model_dump_json())
                    return
            except Exception as exc:  # noqa: BLE001
                logger.warning("city situation redis cache write failed: %s", exc)
            if shared_required:
                return
        if shared_required:
            return
        _CITY_SITUATION_RESPONSE_CACHE[cache_key] = _CitySituationResponseCacheEntry(
            expires_at=datetime.utcnow() + timedelta(seconds=ttl),
            response=response.model_copy(deep=True),
        )

    async def list_vessels(self, query) -> PageResponse[VesselListItemResponse]:
        stmt = (
            select(VesselProfile)
            .outerjoin(VesselCapacityDimension, VesselCapacityDimension.vessel_profile_id == VesselProfile.id)
            .outerjoin(VesselBuildInfo, VesselBuildInfo.vessel_profile_id == VesselProfile.id)
            .outerjoin(
                VesselOwnerPeriod,
                and_(VesselOwnerPeriod.vessel_profile_id == VesselProfile.id, VesselOwnerPeriod.is_current.is_(True)),
            )
            .outerjoin(
                VesselOperatorPeriod,
                and_(VesselOperatorPeriod.vessel_profile_id == VesselProfile.id, VesselOperatorPeriod.is_current.is_(True)),
            )
            .outerjoin(VesselContact, VesselContact.vessel_profile_id == VesselProfile.id)
            .where(VesselProfile.deleted_at.is_(None))
        )
        if query.keyword:
            like_value = f"%{query.keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    VesselProfile.vessel_profile_code.ilike(like_value),
                    VesselProfile.ship_name.ilike(like_value),
                    VesselProfile.ship_name_en.ilike(like_value),
                    VesselProfile.current_mmsi.ilike(like_value),
                    VesselOwnerPeriod.party_name.ilike(like_value),
                    VesselOperatorPeriod.operator_name.ilike(like_value),
                    VesselContact.contact_name.ilike(like_value),
                    VesselContact.mobile_phone.ilike(like_value),
                )
            )
        if query.mmsi:
            stmt = stmt.where(VesselProfile.current_mmsi.ilike(f"%{query.mmsi.strip()}%"))
        if query.ship_name:
            stmt = stmt.where(VesselProfile.ship_name.ilike(f"%{query.ship_name.strip()}%"))
        if query.ship_type_code:
            stmt = stmt.where(VesselProfile.ship_type_code == query.ship_type_code)
        if query.profile_status_code:
            stmt = stmt.where(VesselProfile.profile_status_code == query.profile_status_code)
        city_code = query.registry_city_code or query.city_code
        if city_code:
            stmt = stmt.where(VesselProfile.registry_city_code == city_code)
        if query.business_region_id:
            stmt = stmt.where(VesselProfile.business_region_id == query.business_region_id)
        if query.deadweight_min is not None:
            stmt = stmt.where(VesselCapacityDimension.deadweight_ton >= query.deadweight_min)
        if query.deadweight_max is not None:
            stmt = stmt.where(VesselCapacityDimension.deadweight_ton <= query.deadweight_max)
        current_year = datetime.utcnow().year
        if query.ship_age_min is not None:
            stmt = stmt.where(VesselBuildInfo.building_year <= current_year - query.ship_age_min)
        if query.ship_age_max is not None:
            stmt = stmt.where(VesselBuildInfo.building_year >= current_year - query.ship_age_max)
        if query.length_min is not None:
            stmt = stmt.where(VesselCapacityDimension.length_m >= query.length_min)
        if query.length_max is not None:
            stmt = stmt.where(VesselCapacityDimension.length_m <= query.length_max)
        if query.draft_min is not None:
            stmt = stmt.where(VesselCapacityDimension.design_draft_m >= query.draft_min)
        if query.draft_max is not None:
            stmt = stmt.where(VesselCapacityDimension.design_draft_m <= query.draft_max)
        if query.owner_name:
            stmt = stmt.where(VesselOwnerPeriod.party_name.ilike(f"%{query.owner_name.strip()}%"))
        if query.operator_name:
            stmt = stmt.where(VesselOperatorPeriod.operator_name.ilike(f"%{query.operator_name.strip()}%"))
        if query.contact_available is not None:
            stmt = stmt.where(VesselContact.is_available.is_(query.contact_available))
        if query.updated_from:
            stmt = stmt.where(VesselProfile.updated_at >= query.updated_from)
        if query.updated_to:
            stmt = stmt.where(VesselProfile.updated_at <= query.updated_to)

        total_subquery = stmt.with_only_columns(VesselProfile.id).group_by(VesselProfile.id).subquery()
        total = int((await self.db.execute(select(func.count()).select_from(total_subquery))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.group_by(VesselProfile.id)
                .order_by(VesselProfile.updated_at.desc(), VesselProfile.id.desc())
                .offset((query.page - 1) * query.page_size)
                .limit(query.page_size)
            )
        ).scalars().all()
        return PageResponse[VesselListItemResponse](
            total=total,
            page=query.page,
            page_size=query.page_size,
            items=await self._build_list_items(list(rows)),
        )

    async def list_assets(self, query) -> VesselAssetPageResponse:
        stmt = self._asset_profile_stmt(query)
        total_subquery = stmt.with_only_columns(VesselProfile.id).group_by(VesselProfile.id).subquery()
        total = int((await self.db.execute(select(func.count()).select_from(total_subquery))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.group_by(VesselProfile.id)
                .order_by(*self._asset_order_by(query))
                .offset((query.page - 1) * query.page_size)
                .limit(query.page_size)
            )
        ).scalars().all()
        items = await self._build_asset_items(list(rows))
        page_summary = await self._asset_query_summary(stmt)
        return VesselAssetPageResponse(
            total=total,
            page=query.page,
            page_size=query.page_size,
            items=items,
            coverage_rate=page_summary["coverage_rate"],
            confidence_level=page_summary["confidence_level"],
            generated_at=page_summary["generated_at"],
            summary_status_counts=page_summary["summary_status_counts"],
            summarized_count=page_summary["summarized_count"],
            missing_summary_count=page_summary["missing_summary_count"],
            failed_summary_count=page_summary["failed_summary_count"],
            stale_summary_count=page_summary["stale_summary_count"],
            source_updated_at=page_summary["source_updated_at"],
            uncertainty_reasons=page_summary["uncertainty_reasons"],
        )

    async def asset_summary(self) -> VesselAssetSummaryResponse:
        generated_at = datetime.utcnow()
        total_profiles = int(
            await self.db.scalar(select(func.count(VesselProfile.id)).where(VesselProfile.deleted_at.is_(None))) or 0
        )
        summary_total = int(
            await self.db.scalar(
                select(func.count(VesselProfileSummary.id))
                .join(VesselProfile, VesselProfile.id == VesselProfileSummary.vessel_profile_id)
                .where(VesselProfile.deleted_at.is_(None))
            )
            or 0
        )
        label_map = await _load_label_map(self.db)
        missing_without_row = max(0, total_profiles - summary_total)
        quality_distribution = await self._summary_distribution(
            VesselProfileSummary.data_quality_level,
            "VESSEL_CONFIDENCE_LEVEL",
            label_map,
            missing_unknown=missing_without_row,
        )
        risk_distribution = await self._summary_distribution(
            VesselProfileSummary.risk_level,
            "VESSEL_RISK_LEVEL",
            label_map,
            missing_unknown=missing_without_row,
        )
        ais_distribution = await self._summary_distribution(
            VesselProfileSummary.ais_freshness_level,
            "VESSEL_AIS_FRESHNESS_LEVEL",
            label_map,
            missing_unknown=missing_without_row,
        )
        status_distribution = await self._summary_status_distribution(label_map, missing_without_row=missing_without_row)
        status_counts = {item.code: item.count for item in status_distribution}
        missing_summary_count = status_counts.get("MISSING", 0)
        failed_summary_count = status_counts.get("FAILED", 0)
        stale_summary_count = status_counts.get("STALE", 0)
        summarized_count = max(0, total_profiles - missing_summary_count)
        coverage_rate = _percent(summarized_count, total_profiles)
        confidence_level = _coverage_confidence_level(coverage_rate, failed_summary_count)
        return VesselAssetSummaryResponse(
            total_profiles=total_profiles,
            summarized_count=summarized_count,
            missing_summary_count=missing_summary_count,
            failed_summary_count=failed_summary_count,
            stale_summary_count=stale_summary_count,
            coverage_rate=coverage_rate,
            confidence_level=confidence_level,
            generated_at=generated_at,
            quality_distribution=quality_distribution,
            risk_distribution=risk_distribution,
            ais_freshness_distribution=ais_distribution,
            summary_status_distribution=status_distribution,
        )

    async def refresh_vessel_summary(self, vessel_id: int) -> VesselAssetListItemResponse:
        profile = await self._require_profile(vessel_id)
        try:
            await self._upsert_vessel_summary(profile)
        except Exception as exc:  # noqa: BLE001
            logger.warning("vessel summary refresh failed for profile %s: %s", vessel_id, exc)
            await self.db.rollback()
            profile = await self._require_profile(vessel_id)
            await self._mark_vessel_summary_failed(profile, str(exc))
        await self.db.commit()
        return (await self._build_asset_items([profile]))[0]

    async def _refresh_summary_best_effort(self, vessel_id: int) -> None:
        try:
            profile = await self._require_profile(vessel_id)
            await self._upsert_vessel_summary(profile)
            await self.db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("best-effort vessel summary refresh failed for profile %s: %s", vessel_id, exc)
            await self.db.rollback()
            try:
                profile = await self._require_profile(vessel_id)
                await self._mark_vessel_summary_failed(profile, str(exc))
                await self.db.commit()
            except Exception as mark_exc:  # noqa: BLE001
                logger.warning("mark vessel summary failed state failed for profile %s: %s", vessel_id, mark_exc)
                await self.db.rollback()

    def _asset_profile_stmt(self, query: Any):
        owner_join = and_(
            VesselOwnerPeriod.vessel_profile_id == VesselProfile.id,
            VesselOwnerPeriod.is_current.is_(True),
            VesselOwnerPeriod.end_date.is_(None),
            VesselOwnerPeriod.voided_at.is_(None),
        )
        operator_join = and_(
            VesselOperatorPeriod.vessel_profile_id == VesselProfile.id,
            VesselOperatorPeriod.is_current.is_(True),
            VesselOperatorPeriod.end_date.is_(None),
            VesselOperatorPeriod.voided_at.is_(None),
        )
        contact_join = and_(
            VesselContact.vessel_profile_id == VesselProfile.id,
            VesselContact.is_current.is_(True),
            VesselContact.end_date.is_(None),
            VesselContact.voided_at.is_(None),
        )
        stmt = (
            select(VesselProfile)
            .outerjoin(VesselCapacityDimension, VesselCapacityDimension.vessel_profile_id == VesselProfile.id)
            .outerjoin(VesselBuildInfo, VesselBuildInfo.vessel_profile_id == VesselProfile.id)
            .outerjoin(VesselOwnerPeriod, owner_join)
            .outerjoin(VesselOperatorPeriod, operator_join)
            .outerjoin(VesselContact, contact_join)
            .outerjoin(VesselProfileSummary, VesselProfileSummary.vessel_profile_id == VesselProfile.id)
            .where(VesselProfile.deleted_at.is_(None))
        )
        if getattr(query, "keyword", None):
            like_value = f"%{query.keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    VesselProfile.vessel_profile_code.ilike(like_value),
                    VesselProfile.ship_name.ilike(like_value),
                    VesselProfile.ship_name_en.ilike(like_value),
                    VesselProfile.current_mmsi.ilike(like_value),
                    VesselOwnerPeriod.party_name.ilike(like_value),
                    VesselOperatorPeriod.operator_name.ilike(like_value),
                    VesselContact.contact_name.ilike(like_value),
                    VesselContact.mobile_phone.ilike(like_value),
                )
            )
        if getattr(query, "mmsi", None):
            stmt = stmt.where(VesselProfile.current_mmsi.ilike(f"%{query.mmsi.strip()}%"))
        if getattr(query, "ship_name", None):
            stmt = stmt.where(VesselProfile.ship_name.ilike(f"%{query.ship_name.strip()}%"))
        if getattr(query, "ship_type_code", None):
            stmt = stmt.where(VesselProfile.ship_type_code == query.ship_type_code)
        if getattr(query, "profile_status_code", None):
            stmt = stmt.where(VesselProfile.profile_status_code == query.profile_status_code)
        city_code = getattr(query, "registry_city_code", None) or getattr(query, "city_code", None)
        if city_code:
            stmt = stmt.where(or_(VesselProfile.registry_city_code == city_code, VesselProfileSummary.latest_city_code == city_code))
        if getattr(query, "region_code", None):
            stmt = stmt.where(VesselProfileSummary.latest_city_code == query.region_code)
        if getattr(query, "business_region_id", None):
            stmt = stmt.where(VesselProfile.business_region_id == query.business_region_id)
        if getattr(query, "deadweight_min", None) is not None:
            stmt = stmt.where(VesselCapacityDimension.deadweight_ton >= query.deadweight_min)
        if getattr(query, "deadweight_max", None) is not None:
            stmt = stmt.where(VesselCapacityDimension.deadweight_ton <= query.deadweight_max)
        current_year = datetime.utcnow().year
        if getattr(query, "ship_age_min", None) is not None:
            stmt = stmt.where(VesselBuildInfo.building_year <= current_year - query.ship_age_min)
        if getattr(query, "ship_age_max", None) is not None:
            stmt = stmt.where(VesselBuildInfo.building_year >= current_year - query.ship_age_max)
        if getattr(query, "length_min", None) is not None:
            stmt = stmt.where(VesselCapacityDimension.length_m >= query.length_min)
        if getattr(query, "length_max", None) is not None:
            stmt = stmt.where(VesselCapacityDimension.length_m <= query.length_max)
        if getattr(query, "draft_min", None) is not None:
            stmt = stmt.where(VesselCapacityDimension.design_draft_m >= query.draft_min)
        if getattr(query, "draft_max", None) is not None:
            stmt = stmt.where(VesselCapacityDimension.design_draft_m <= query.draft_max)
        if getattr(query, "owner_name", None):
            stmt = stmt.where(VesselOwnerPeriod.party_name.ilike(f"%{query.owner_name.strip()}%"))
        if getattr(query, "operator_name", None):
            stmt = stmt.where(VesselOperatorPeriod.operator_name.ilike(f"%{query.operator_name.strip()}%"))
        if getattr(query, "contact_available", None) is not None:
            stmt = stmt.where(VesselContact.is_available.is_(query.contact_available))
        if getattr(query, "updated_from", None):
            stmt = stmt.where(VesselProfile.updated_at >= query.updated_from)
        if getattr(query, "updated_to", None):
            stmt = stmt.where(VesselProfile.updated_at <= query.updated_to)
        stmt = self._apply_summary_filter(stmt, VesselProfileSummary.data_quality_level, getattr(query, "quality_level", None))
        stmt = self._apply_summary_filter(stmt, VesselProfileSummary.risk_level, getattr(query, "risk_level", None))
        freshness = getattr(query, "ais_freshness_level", None) or getattr(query, "freshness_level", None)
        stmt = self._apply_summary_filter(stmt, VesselProfileSummary.ais_freshness_level, freshness)
        status_code = getattr(query, "summary_status_code", None)
        if status_code:
            if status_code == "MISSING":
                stmt = stmt.where(or_(VesselProfileSummary.id.is_(None), VesselProfileSummary.summary_status_code == "MISSING"))
            elif status_code == "STALE":
                stmt = stmt.where(or_(VesselProfileSummary.summary_status_code == "STALE", self._summary_stale_condition()))
            elif status_code in SUMMARY_READY_STATUSES:
                stmt = stmt.where(
                    VesselProfileSummary.summary_status_code == status_code,
                    not_(self._summary_stale_condition()),
                )
            else:
                stmt = stmt.where(VesselProfileSummary.summary_status_code == status_code)
        source_layer = getattr(query, "source_layer", None)
        if source_layer:
            stmt = stmt.where(VesselProfileSummary.source_layer == source_layer)
        sample_tag = getattr(query, "analysis_sample_tag", None) or getattr(query, "sample_tag", None)
        if sample_tag:
            stmt = stmt.where(VesselProfileSummary.analysis_sample_tags_key.ilike(f"%|{sample_tag}|%"))
        return stmt

    def _apply_summary_filter(self, stmt: Any, column: Any, value: str | None) -> Any:
        if not value:
            return stmt
        if value == "UNKNOWN":
            return stmt.where(or_(VesselProfileSummary.id.is_(None), column == "UNKNOWN"))
        return stmt.where(column == value)

    def _asset_order_by(self, query: Any) -> list[Any]:
        sort = getattr(query, "sort", None)
        if sort == "quality_score_asc":
            return [VesselProfileSummary.data_quality_score.asc().nullslast(), VesselProfile.updated_at.desc(), VesselProfile.id.desc()]
        if sort == "quality_score_desc":
            return [VesselProfileSummary.data_quality_score.desc().nullslast(), VesselProfile.updated_at.desc(), VesselProfile.id.desc()]
        if sort == "refreshed_at_desc":
            return [VesselProfileSummary.refreshed_at.desc().nullslast(), VesselProfile.updated_at.desc(), VesselProfile.id.desc()]
        if sort == "ais_time_desc":
            return [VesselProfileSummary.latest_position_time.desc().nullslast(), VesselProfile.updated_at.desc(), VesselProfile.id.desc()]
        return [VesselProfile.updated_at.desc(), VesselProfile.id.desc()]

    async def _summary_distribution(
        self,
        column: Any,
        dict_code: str,
        label_map: dict[str, dict[str, str]],
        *,
        missing_unknown: int = 0,
        missing_code: str = "UNKNOWN",
    ) -> list[VesselAssetDistributionItemResponse]:
        rows = (
            await self.db.execute(
                select(column, func.count(VesselProfileSummary.id))
                .join(VesselProfile, VesselProfile.id == VesselProfileSummary.vessel_profile_id)
                .where(VesselProfile.deleted_at.is_(None))
                .group_by(column)
            )
        ).all()
        counts: dict[str, int] = {str(code or missing_code): int(count or 0) for code, count in rows}
        if missing_unknown:
            counts[missing_code] = counts.get(missing_code, 0) + missing_unknown
        return [
            VesselAssetDistributionItemResponse(
                code=code,
                name=label_map.get(dict_code, {}).get(code),
                count=count,
            )
            for code, count in sorted(counts.items())
            if count
        ]

    def _summary_stale_condition(self) -> Any:
        return and_(
            VesselProfileSummary.summary_status_code.in_(SUMMARY_READY_STATUSES),
            VesselProfileSummary.source_updated_at.is_not(None),
            VesselProfileSummary.refreshed_at.is_not(None),
            VesselProfileSummary.source_updated_at > VesselProfileSummary.refreshed_at,
        )

    def _summary_effective_status_expr(self) -> Any:
        return case(
            (VesselProfileSummary.id.is_(None), "MISSING"),
            (self._summary_stale_condition(), "STALE"),
            else_=VesselProfileSummary.summary_status_code,
        )

    def _effective_summary_status(self, summary: VesselProfileSummary) -> str:
        if (
            summary.summary_status_code in SUMMARY_READY_STATUSES
            and summary.source_updated_at is not None
            and summary.refreshed_at is not None
            and summary.source_updated_at > summary.refreshed_at
        ):
            return "STALE"
        return summary.summary_status_code

    async def _summary_status_distribution(
        self,
        label_map: dict[str, dict[str, str]],
        *,
        missing_without_row: int = 0,
    ) -> list[VesselAssetDistributionItemResponse]:
        status_expr = self._summary_effective_status_expr()
        rows = (
            await self.db.execute(
                select(status_expr, func.count(VesselProfile.id))
                .outerjoin(VesselProfileSummary, VesselProfileSummary.vessel_profile_id == VesselProfile.id)
                .where(VesselProfile.deleted_at.is_(None))
                .group_by(status_expr)
            )
        ).all()
        counts: dict[str, int] = {str(code or "MISSING"): int(count or 0) for code, count in rows}
        if missing_without_row:
            counts["MISSING"] = max(counts.get("MISSING", 0), missing_without_row)
        return [
            VesselAssetDistributionItemResponse(
                code=code,
                name=label_map.get("VESSEL_SUMMARY_STATUS", {}).get(code),
                count=count,
            )
            for code, count in sorted(counts.items())
            if count
        ]

    async def _asset_query_summary(self, stmt: Any) -> dict[str, Any]:
        generated_at = datetime.utcnow()
        subquery = (
            stmt.with_only_columns(
                VesselProfile.id.label("profile_id"),
                VesselProfileSummary.id.label("summary_id"),
                self._summary_effective_status_expr().label("summary_status_code"),
                VesselProfileSummary.source_updated_at.label("source_updated_at"),
            )
            .group_by(VesselProfile.id)
            .subquery()
        )
        total = int((await self.db.scalar(select(func.count()).select_from(subquery))) or 0)
        status_rows = (
            await self.db.execute(
                select(subquery.c.summary_status_code, func.count(subquery.c.profile_id))
                .select_from(subquery)
                .group_by(subquery.c.summary_status_code)
            )
        ).all()
        status_counts = {str(code or "MISSING"): int(count or 0) for code, count in status_rows}
        missing_count = status_counts.get("MISSING", 0)
        failed_count = status_counts.get("FAILED", 0)
        stale_count = status_counts.get("STALE", 0)
        summarized_count = max(0, total - missing_count)
        coverage_rate = _percent(summarized_count, total)
        source_updated_at = await self.db.scalar(select(func.max(subquery.c.source_updated_at)).select_from(subquery))
        uncertainty_reasons: list[str] = []
        if total == 0:
            uncertainty_reasons.append("当前筛选无船舶资产样本")
        if missing_count:
            uncertainty_reasons.append(f"筛选结果中 {missing_count} 条摘要未生成")
        if failed_count:
            uncertainty_reasons.append(f"筛选结果中 {failed_count} 条摘要生成失败")
        if stale_count:
            uncertainty_reasons.append(f"筛选结果中 {stale_count} 条摘要已过期")
        if coverage_rate < Decimal("100.00") and total:
            uncertainty_reasons.append("筛选结果覆盖率不足 100%，分析结论需结合缺失样本判断")
        return {
            "coverage_rate": coverage_rate,
            "confidence_level": _coverage_confidence_level(coverage_rate, failed_count),
            "generated_at": generated_at,
            "summary_status_counts": status_counts,
            "summarized_count": summarized_count,
            "missing_summary_count": missing_count,
            "failed_summary_count": failed_count,
            "stale_summary_count": stale_count,
            "source_updated_at": source_updated_at,
            "uncertainty_reasons": uncertainty_reasons,
        }

    async def _build_asset_items(self, profiles: list[VesselProfile]) -> list[VesselAssetListItemResponse]:
        if not profiles:
            return []
        ids = [row.id for row in profiles]
        base_items = await self._build_list_items(profiles)
        summaries = await self._map_by_profile(VesselProfileSummary, ids)
        counts = await self._active_quality_issue_counts(ids)
        label_map = await _load_label_map(self.db)
        items: list[VesselAssetListItemResponse] = []
        for item in base_items:
            summary = summaries.get(item.id)
            if summary is None:
                quality_count = counts.get(item.id, 0)
                notes = ["摘要未生成，请刷新摘要后再用于资产分析"]
                if quality_count:
                    notes.append(f"当前存在 {quality_count} 条未关闭质量问题")
                items.append(
                    VesselAssetListItemResponse(
                        **item.model_dump(),
                        profile_completeness_rate=None,
                        data_quality_score=None,
                        data_quality_level="UNKNOWN",
                        identity_confidence_level="UNKNOWN",
                        contact_trust_level="UNKNOWN",
                        subject_consistency_level="UNKNOWN",
                        quality_level="UNKNOWN",
                        risk_level="UNKNOWN",
                        ais_freshness_level="UNKNOWN",
                        quality_issue_count=quality_count,
                        analysis_sample_tags=[],
                        data_sources=["VESSEL_PROFILE", "RELATION_LEDGER", "QUALITY_ISSUE"],
                        uncertainty_notes=notes,
                        summary_status_code="MISSING",
                        summary_status_name=label_map.get("VESSEL_SUMMARY_STATUS", {}).get("MISSING"),
                        evidence_updated_at=item.updated_at,
                    )
                )
                continue
            payload = item.model_dump()
            for key in [
                "ship_name",
                "current_mmsi",
                "ship_type_code",
                "ship_type_name",
                "deadweight_ton",
                "length_m",
                "width_m",
                "design_draft_m",
                "building_year",
                "ship_age",
                "primary_owner_name",
                "primary_operator_name",
                "primary_contact_name",
                "contact_available",
            ]:
                value = getattr(summary, key, None)
                if value is not None:
                    payload[key] = value
            payload["primary_contact_phone"] = summary.primary_contact_phone_masked
            summary_status_code = self._effective_summary_status(summary)
            uncertainty_notes = list(summary.uncertainty_notes_json or [])
            if summary_status_code == "STALE" and not any("过期" in item for item in uncertainty_notes):
                uncertainty_notes.append("摘要已过期，请刷新摘要后再用于资产分析")
            items.append(
                VesselAssetListItemResponse(
                    **payload,
                    profile_completeness_rate=summary.profile_completeness_rate,
                    data_quality_score=summary.data_quality_score,
                    data_quality_level=summary.data_quality_level,
                    identity_confidence_level=summary.identity_confidence_level,
                    contact_trust_level=summary.contact_trust_level,
                    subject_consistency_level=summary.subject_consistency_level,
                    quality_level=summary.data_quality_level,
                    risk_level=summary.risk_level,
                    ais_freshness_level=summary.ais_freshness_level,
                    quality_issue_count=summary.quality_issue_count,
                    missing_field_count=summary.missing_field_count,
                    conflict_count=summary.conflict_count,
                    certificate_missing_count=summary.certificate_missing_count,
                    certificate_expiring_count=summary.certificate_expiring_count,
                    certificate_expired_count=summary.certificate_expired_count,
                    latest_position_time=summary.latest_position_time,
                    latest_city_code=summary.latest_city_code,
                    latest_city_name=summary.latest_city_name,
                    analysis_sample_tags=summary.analysis_sample_tags_json or [],
                    data_sources=summary.data_sources_json or [],
                    uncertainty_notes=uncertainty_notes,
                    risk_evidence_summary=summary.risk_evidence_summary_json or [],
                    summary_status_code=summary_status_code,
                    summary_status_name=label_map.get("VESSEL_SUMMARY_STATUS", {}).get(summary_status_code),
                    summary_version=summary.summary_version,
                    source_layer=summary.source_layer,
                    coverage_rate=summary.coverage_rate,
                    refreshed_at=summary.refreshed_at,
                    source_updated_at=summary.source_updated_at,
                    refresh_error=summary.refresh_error,
                    evidence_updated_at=summary.refreshed_at or summary.source_updated_at or item.updated_at,
                )
            )
        return items

    async def _upsert_vessel_summary(self, profile: VesselProfile) -> VesselProfileSummary:
        now = datetime.utcnow()
        payload = await self._summary_payload(profile, now)
        row = await self.db.scalar(select(VesselProfileSummary).where(VesselProfileSummary.vessel_profile_id == profile.id))
        if row is None:
            row = VesselProfileSummary(vessel_profile_id=profile.id, created_at=now, updated_at=now, **payload)
            self.db.add(row)
        else:
            for key, value in payload.items():
                setattr(row, key, value)
            row.updated_at = now
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def _mark_vessel_summary_failed(self, profile: VesselProfile, error: str) -> VesselProfileSummary:
        now = datetime.utcnow()
        row = await self.db.scalar(select(VesselProfileSummary).where(VesselProfileSummary.vessel_profile_id == profile.id))
        if row is None:
            row = VesselProfileSummary(
                vessel_profile_id=profile.id,
                ship_name=profile.ship_name,
                current_mmsi=profile.current_mmsi,
                ship_type_code=profile.ship_type_code,
                data_quality_level="UNKNOWN",
                identity_confidence_level="UNKNOWN",
                contact_trust_level="UNKNOWN",
                subject_consistency_level="UNKNOWN",
                risk_level="UNKNOWN",
                ais_freshness_level="UNKNOWN",
                summary_status_code="FAILED",
                summary_version=SUMMARY_VERSION,
                data_sources_json=["VESSEL_PROFILE"],
                uncertainty_notes_json=["摘要生成失败"],
                refresh_error=error[:1000],
                created_at=now,
                updated_at=now,
            )
            self.db.add(row)
        else:
            row.summary_status_code = "FAILED"
            row.refresh_error = error[:1000]
            row.updated_at = now
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def _summary_payload(self, profile: VesselProfile, now: datetime) -> dict[str, Any]:
        label_map = await _load_label_map(self.db)
        capacity = await self.repo.get_one_by_profile(VesselCapacityDimension, profile.id)
        build = await self.repo.get_one_by_profile(VesselBuildInfo, profile.id)
        owner = await self._summary_primary_relation(VesselOwnerPeriod, profile.id)
        operator = await self._summary_primary_relation(VesselOperatorPeriod, profile.id)
        contact = await self._summary_primary_relation(VesselContact, profile.id)
        certificates = await self._summary_certificates(profile.id)
        source_updated_at = await self._summary_source_updated_at(profile.id, profile, capacity, build, owner, operator, contact, *certificates)
        facts = {
            "ship_name": profile.ship_name,
            "current_mmsi": profile.current_mmsi,
            "ship_type_code": profile.ship_type_code,
            "deadweight_ton": getattr(capacity, "deadweight_ton", None),
            "length_m": getattr(capacity, "length_m", None),
            "width_m": getattr(capacity, "width_m", None),
            "design_draft_m": getattr(capacity, "design_draft_m", None),
            "primary_owner_name": getattr(owner, "party_name", None),
            "primary_operator_name": getattr(operator, "operator_name", None),
            "primary_contact_name": getattr(contact, "contact_name", None),
            "certificate_evidence": bool(certificates),
        }
        missing_fields = [key for key, _ in SUMMARY_REQUIRED_FIELDS if not facts.get(key)]
        await self._sync_summary_missing_issues(profile.id, missing_fields)
        active_issues = await self._summary_active_issues(profile.id)
        severity_counts = defaultdict(int)
        issue_type_counts = defaultdict(int)
        for issue in active_issues:
            severity_counts[issue.severity_code] += 1
            issue_type_counts[issue.issue_type_code] += 1
        completeness = _percent(len(SUMMARY_REQUIRED_FIELDS) - len(missing_fields), len(SUMMARY_REQUIRED_FIELDS))
        quality_score = max(
            Decimal("0.00"),
            completeness
            - Decimal(str(severity_counts.get("HIGH", 0) * 20))
            - Decimal(str(severity_counts.get("MEDIUM", 0) * 10))
            - Decimal(str(severity_counts.get("LOW", 0) * 5)),
        ).quantize(Decimal("0.01"))
        data_quality_level = _level_from_score(quality_score)
        identity_level = self._summary_identity_level(profile, issue_type_counts)
        contact_trust_level = self._summary_contact_trust_level(contact)
        subject_level = self._summary_subject_consistency_level(owner, operator)
        risk_payload = self._summary_certificate_risk(certificates, active_issues)
        formal_risk_payload = await self._formal_risk_summary(profile.id)
        if formal_risk_payload.get("has_formal_signals"):
            risk_payload = formal_risk_payload
        ais_payload = await self._summary_ais_payload(profile, now)
        tags = self._summary_sample_tags(data_quality_level, risk_payload["risk_level"], ais_payload["ais_freshness_level"], contact_trust_level, severity_counts)
        data_sources = ["VESSEL_PROFILE", "RELATION_LEDGER", "CERTIFICATE_LEDGER", "QUALITY_ISSUE"]
        if ais_payload["latest_position_time"] is not None:
            data_sources.append("ES_REALTIME")
        notes: list[str] = []
        if missing_fields:
            labels = {key: label for key, label in SUMMARY_REQUIRED_FIELDS}
            notes.append("缺失字段：" + "、".join(labels.get(key, key) for key in missing_fields))
        notes.append(
            "合规风险来源：Round 5 风险信号"
            if formal_risk_payload.get("has_formal_signals")
            else "证书风险为 Round 3 轻量账本口径，正式规则未刷新时仅作预规则提示"
        )
        if ais_payload["ais_unavailable_reason"]:
            notes.append(ais_payload["ais_unavailable_reason"])
        status = "PARTIAL" if ais_payload["ais_unavailable_reason"] else "READY"
        return {
            "ship_name": profile.ship_name,
            "current_mmsi": profile.current_mmsi,
            "ship_type_code": profile.ship_type_code,
            "ship_type_name": label_map.get("SHIP_TYPE", {}).get(profile.ship_type_code),
            "deadweight_ton": getattr(capacity, "deadweight_ton", None),
            "length_m": getattr(capacity, "length_m", None),
            "width_m": getattr(capacity, "width_m", None),
            "design_draft_m": getattr(capacity, "design_draft_m", None),
            "building_year": getattr(build, "building_year", None),
            "ship_age": _ship_age(getattr(build, "building_year", None)),
            "primary_owner_name": getattr(owner, "party_name", None),
            "primary_operator_name": getattr(operator, "operator_name", None),
            "primary_contact_name": getattr(contact, "contact_name", None),
            "primary_contact_phone_masked": _mask_phone(getattr(contact, "mobile_phone", None)),
            "contact_available": getattr(contact, "is_available", None),
            "profile_completeness_rate": completeness,
            "data_quality_score": quality_score,
            "data_quality_level": data_quality_level,
            "identity_confidence_level": identity_level,
            "contact_trust_level": contact_trust_level,
            "subject_consistency_level": subject_level,
            "quality_issue_count": len(active_issues),
            "missing_field_count": len(missing_fields),
            "conflict_count": issue_type_counts.get("MMSI_CONFLICT", 0),
            "risk_level": risk_payload["risk_level"],
            "risk_evidence_summary_json": risk_payload["risk_evidence_summary"],
            "certificate_missing_count": risk_payload["certificate_missing_count"],
            "certificate_expiring_count": risk_payload["certificate_expiring_count"],
            "certificate_expired_count": risk_payload["certificate_expired_count"],
            "latest_position_time": ais_payload["latest_position_time"],
            "latest_city_code": ais_payload["latest_city_code"],
            "latest_city_name": ais_payload["latest_city_name"],
            "ais_freshness_level": ais_payload["ais_freshness_level"],
            "ais_unavailable_reason": ais_payload["ais_unavailable_reason"],
            "analysis_sample_tags_json": tags,
            "analysis_sample_tags_key": _tag_key(tags),
            "data_sources_json": data_sources,
            "uncertainty_notes_json": notes,
            "source_layer": "PROFILE_SUMMARY",
            "coverage_rate": completeness,
            "summary_status_code": status,
            "summary_version": SUMMARY_VERSION,
            "refreshed_at": now,
            "source_updated_at": source_updated_at,
            "last_verified_at": getattr(contact, "last_verified_at", None),
            "refresh_error": None,
        }

    async def _summary_primary_relation(self, model: type[Any], vessel_id: int) -> Any | None:
        stmt = (
            select(model)
            .where(
                model.vessel_profile_id == vessel_id,
                model.is_current.is_(True),
                model.voided_at.is_(None),
                model.end_date.is_(None),
            )
            .order_by(model.is_primary.desc() if hasattr(model, "is_primary") else model.id.asc(), model.id.asc())
            .limit(1)
        )
        return await self.db.scalar(stmt)

    async def _summary_certificates(self, vessel_id: int) -> list[VesselCertificate]:
        rows = (
            await self.db.execute(
                select(VesselCertificate).where(
                    VesselCertificate.vessel_profile_id == vessel_id,
                    VesselCertificate.voided_at.is_(None),
                )
            )
        ).scalars().all()
        return list(rows)

    async def _summary_active_issues(self, vessel_id: int) -> list[VesselDataQualityIssue]:
        rows = (
            await self.db.execute(
                select(VesselDataQualityIssue).where(
                    VesselDataQualityIssue.vessel_profile_id == vessel_id,
                    VesselDataQualityIssue.status_code.in_(ACTIVE_ISSUE_STATUSES),
                )
            )
        ).scalars().all()
        return list(rows)

    async def _summary_source_updated_at(self, vessel_id: int, *rows: Any) -> datetime | None:
        values = [getattr(row, "updated_at", None) for row in rows if row is not None]
        latest_quality = await self.db.scalar(
            select(func.max(VesselDataQualityIssue.updated_at)).where(VesselDataQualityIssue.vessel_profile_id == vessel_id)
        )
        if latest_quality is not None:
            values.append(latest_quality)
        return max((value for value in values if value is not None), default=None)

    async def _sync_summary_missing_issues(self, vessel_id: int, missing_fields: list[str]) -> None:
        missing_set = set(missing_fields)
        for field_name, _ in SUMMARY_REQUIRED_FIELDS:
            if field_name in {"primary_owner_name", "primary_operator_name", "primary_contact_name"}:
                relation_type = {
                    "primary_owner_name": "OWNER",
                    "primary_operator_name": "OPERATOR",
                    "primary_contact_name": "CONTACT",
                }[field_name]
                if field_name in missing_set:
                    await self._upsert_quality_issue(
                        issue_type_code="PRIMARY_RELATION_MISSING",
                        profile_id=vessel_id,
                        object_type="profile",
                        object_id=vessel_id,
                        field_name=field_name,
                        normalized_key=f"profile|{vessel_id}|{relation_type}",
                        evidence_source="VESSEL_SUMMARY_REFRESH",
                        severity_code="MEDIUM",
                        impact_scope=[{"relation_type": relation_type, "vessel_profile_id": vessel_id}],
                    )
                else:
                    await self._resolve_summary_issue(
                        "PRIMARY_RELATION_MISSING",
                        vessel_id,
                        "profile",
                        vessel_id,
                        field_name,
                        f"profile|{vessel_id}|{relation_type}",
                    )
                continue
            if field_name in missing_set:
                await self._upsert_quality_issue(
                    issue_type_code="PROFILE_FIELD_MISSING",
                    profile_id=vessel_id,
                    object_type="profile",
                    object_id=vessel_id,
                    field_name=field_name,
                    normalized_key=f"profile|{vessel_id}|{field_name}",
                    evidence_source="VESSEL_SUMMARY_REFRESH",
                    severity_code="MEDIUM",
                    impact_scope=[{"field_name": field_name, "vessel_profile_id": vessel_id}],
                )
            else:
                await self._resolve_summary_issue(
                    "PROFILE_FIELD_MISSING",
                    vessel_id,
                    "profile",
                    vessel_id,
                    field_name,
                    f"profile|{vessel_id}|{field_name}",
                )
        await self.db.flush()

    async def _resolve_summary_issue(
        self,
        issue_type_code: str,
        profile_id: int,
        object_type: str,
        object_id: str | int | None,
        field_name: str | None,
        normalized_key: str,
    ) -> None:
        fingerprint = _quality_fingerprint(issue_type_code, profile_id, object_type, object_id, field_name, normalized_key)
        rows = (
            await self.db.execute(
                select(VesselDataQualityIssue).where(
                    VesselDataQualityIssue.fingerprint == fingerprint,
                    VesselDataQualityIssue.status_code.in_(ACTIVE_ISSUE_STATUSES),
                )
            )
        ).scalars().all()
        now = datetime.utcnow()
        for row in rows:
            row.status_code = "RESOLVED"
            row.resolved_at = now
            row.resolved_evidence = "VESSEL_SUMMARY_REFRESH"

    def _summary_identity_level(self, profile: VesselProfile, issue_type_counts: dict[str, int]) -> str:
        if issue_type_counts.get("MMSI_CONFLICT", 0):
            return "LOW"
        if not profile.current_mmsi:
            return "UNKNOWN"
        if profile.identity_status_code == "LINKED":
            return "HIGH"
        if profile.identity_status_code in {"CANDIDATE", "UNLINKED"}:
            return "MEDIUM"
        if profile.identity_status_code == "CONFLICT":
            return "LOW"
        return "MEDIUM"

    def _summary_contact_trust_level(self, contact: Any | None) -> str:
        if contact is None:
            return "UNKNOWN"
        if not getattr(contact, "is_available", True):
            return "LOW"
        if getattr(contact, "verified_status_code", None) == "VERIFIED":
            return "HIGH"
        if getattr(contact, "last_verified_at", None) is not None:
            return "MEDIUM"
        return "MEDIUM"

    def _summary_subject_consistency_level(self, owner: Any | None, operator: Any | None) -> str:
        if owner is None and operator is None:
            return "UNKNOWN"
        if owner is None or operator is None:
            return "LOW"
        if getattr(owner, "verified_status_code", None) == "VERIFIED" and getattr(operator, "verified_status_code", None) == "VERIFIED":
            return "HIGH"
        return "MEDIUM"

    def _summary_certificate_risk(
        self,
        certificates: list[VesselCertificate],
        active_issues: list[VesselDataQualityIssue],
    ) -> dict[str, Any]:
        today = date.today()
        expiring_limit = today + timedelta(days=30)
        current_by_type: dict[str, list[VesselCertificate]] = defaultdict(list)
        expired_count = 0
        expiring_count = 0
        evidence: list[dict[str, Any]] = [{"source": "CERTIFICATE_LEDGER_PRE_RULE"}]
        for cert in certificates:
            cert_type = cert.certificate_type_code or "UNKNOWN"
            current_by_type[cert_type].append(cert)
        missing_types = [code for code in REQUIRED_VESSEL_CERTIFICATE_TYPES if code not in current_by_type]
        insufficient_types: list[str] = []
        complete_required_certs: list[VesselCertificate] = []
        for code in REQUIRED_VESSEL_CERTIFICATE_TYPES:
            rows = current_by_type.get(code, [])
            complete_rows = [cert for cert in rows if self._certificate_has_complete_evidence(cert)]
            if rows and not complete_rows:
                insufficient_types.append(code)
            complete_required_certs.extend(complete_rows)
        for cert in complete_required_certs:
            if cert.is_long_term_valid:
                continue
            if cert.valid_to is None:
                continue
            if cert.valid_to < today:
                expired_count += 1
            elif cert.valid_to <= expiring_limit:
                expiring_count += 1
        high_quality_issues = [item for item in active_issues if item.severity_code == "HIGH"]
        if expired_count:
            risk_level = "HIGH"
        elif expiring_count or missing_types:
            risk_level = "MEDIUM"
        elif insufficient_types or high_quality_issues:
            risk_level = "UNKNOWN"
        elif len(complete_required_certs) >= len(REQUIRED_VESSEL_CERTIFICATE_TYPES):
            risk_level = "LOW"
        else:
            risk_level = "UNKNOWN"
        evidence.append(
            {
                "missing_certificate_type_codes": missing_types,
                "insufficient_certificate_type_codes": insufficient_types,
                "expired_count": expired_count,
                "expiring_count": expiring_count,
            }
        )
        return {
            "risk_level": risk_level,
            "risk_evidence_summary": evidence,
            "certificate_missing_count": len(missing_types),
            "certificate_expiring_count": expiring_count,
            "certificate_expired_count": expired_count,
        }

    def _certificate_has_complete_evidence(self, cert: VesselCertificate) -> bool:
        return (
            getattr(cert, "verify_status_code", None) == "VERIFIED"
            and bool(getattr(cert, "certificate_no", None))
            and (bool(getattr(cert, "is_long_term_valid", False)) or getattr(cert, "valid_to", None) is not None)
        )

    async def _summary_ais_payload(self, profile: VesselProfile, now: datetime) -> dict[str, Any]:
        if not profile.current_mmsi:
            return {
                "latest_position_time": None,
                "latest_city_code": None,
                "latest_city_name": None,
                "ais_freshness_level": "UNKNOWN",
                "ais_unavailable_reason": "无 MMSI，无法查询实时 AIS",
            }
        if not await self._realtime_es_host():
            return {
                "latest_position_time": None,
                "latest_city_code": None,
                "latest_city_name": None,
                "ais_freshness_level": "UNKNOWN",
                "ais_unavailable_reason": "实时 ES 未配置，AIS 新鲜度未知",
            }
        try:
            positions, partial, error_message, _, _ = await self._search_realtime_positions_batched(
                [profile.current_mmsi],
                batch_size=1,
                max_concurrency=1,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "latest_position_time": None,
                "latest_city_code": None,
                "latest_city_name": None,
                "ais_freshness_level": "UNKNOWN",
                "ais_unavailable_reason": f"实时 AIS 查询失败：{str(exc)[:160]}",
            }
        position = positions.get(profile.current_mmsi)
        if not position:
            reason = error_message if partial and error_message else "暂无实时船位"
            return {
                "latest_position_time": None,
                "latest_city_code": None,
                "latest_city_name": None,
                "ais_freshness_level": "UNKNOWN",
                "ais_unavailable_reason": reason,
            }
        position_time = position.get("position_time")
        age_minutes = int((now - position_time).total_seconds() // 60) if position_time else None
        latest_city_code = None
        latest_city_name = None
        longitude = _to_decimal(position.get("longitude"))
        latitude = _to_decimal(position.get("latitude"))
        if longitude is not None and latitude is not None and self._valid_longitude_latitude(longitude, latitude):
            boundaries = await self._city_boundaries()
            resolved_city = self._resolve_current_city_from_boundaries(longitude, latitude, boundaries, _CITY_BOUNDARY_CACHE.get("grid_index") or {})
            latest_city_code = resolved_city.city_code
            latest_city_name = resolved_city.city_name
        return {
            "latest_position_time": position_time,
            "latest_city_code": latest_city_code,
            "latest_city_name": latest_city_name,
            "ais_freshness_level": _ais_freshness_level(age_minutes),
            "ais_unavailable_reason": error_message if partial and error_message else None,
        }

    def _summary_sample_tags(
        self,
        data_quality_level: str,
        risk_level: str,
        ais_freshness_level: str,
        contact_trust_level: str,
        severity_counts: dict[str, int],
    ) -> list[str]:
        tags: list[str] = []
        if data_quality_level == "HIGH" and not severity_counts.get("HIGH"):
            tags.append("HIGH_QUALITY_PROFILE")
        if ais_freshness_level in {"FRESH", "RECENT"}:
            tags.append("ACTIVE_SAMPLE")
        if risk_level == "LOW":
            tags.append("LOW_RISK_SAMPLE")
        if contact_trust_level in {"HIGH", "MEDIUM"}:
            tags.append("CONTACT_REFERENCEABLE")
        return tags

    def _relation_status_code(self, row: Any) -> str:
        if getattr(row, "voided_at", None) is not None:
            return "VOIDED"
        if getattr(row, "end_date", None) is not None or bool(getattr(row, "is_current", True)) is False:
            return "HISTORY"
        return "CURRENT"

    def _profile_card_source_trace(
        self,
        source_code: str,
        *,
        updated_at: datetime | None = None,
        confidence_level: str = "UNKNOWN",
        coverage_rate: Decimal | None = None,
        status_code: str | None = None,
        note: str | None = None,
    ) -> VesselProfileCardSourceTrace:
        return VesselProfileCardSourceTrace(
            source_code=source_code,
            source_name={
                "VESSEL_PROFILE": "船舶主档",
                "VESSEL_SUMMARY": "船舶资产摘要",
                "RELATION_LEDGER": "主体关系账本",
                "QUALITY_ISSUE": "质量问题",
                "CERTIFICATE_LEDGER_PRE_RULE": "证书账本预规则",
                "CERTIFICATE_REQUIREMENT_RULE": "证书要求规则",
                "VESSEL_RISK_SIGNAL": "合规风险信号",
                "VESSEL_COMPLIANCE_ENGINE": "合规风险引擎",
                "AIS_SUMMARY": "AIS 摘要",
                "OCR_ADOPTION": "OCR 可信采纳",
                "CANDIDATE_ANALYSIS": "候选适配分析",
            }.get(source_code, source_code),
            updated_at=updated_at,
            confidence_level=confidence_level,
            coverage_rate=coverage_rate,
            status_code=status_code,
            note=note,
        )

    def _summary_json_list(self, value: Any) -> list[Any]:
        return value if isinstance(value, list) else []

    def _latest_datetime(self, *values: datetime | None) -> datetime | None:
        filtered = [item for item in values if item is not None]
        return max(filtered) if filtered else None

    def _issue_summary(self, row: VesselDataQualityIssue) -> VesselProfileCardIssueSummary:
        return VesselProfileCardIssueSummary(
            id=row.id,
            issue_type_code=row.issue_type_code,
            severity_code=row.severity_code,
            status_code=row.status_code,
            field_name=row.field_name,
            affected_object_type=row.affected_object_type,
            affected_object_id=row.affected_object_id,
            updated_at=row.updated_at,
        )

    async def _recognition_card_metrics(self, vessel_id: int) -> dict[str, Any]:
        pending_diff_count = await self.db.scalar(
            select(func.count(VesselRecognitionFieldDiff.id)).where(
                VesselRecognitionFieldDiff.vessel_profile_id == vessel_id,
                VesselRecognitionFieldDiff.adopt_status_code == "REVIEW_REQUIRED",
            )
        )
        low_confidence_diff_count = await self.db.scalar(
            select(func.count(VesselRecognitionFieldDiff.id)).where(
                VesselRecognitionFieldDiff.vessel_profile_id == vessel_id,
                VesselRecognitionFieldDiff.adopt_status_code == "REVIEW_REQUIRED",
                VesselRecognitionFieldDiff.confidence_score.is_not(None),
                VesselRecognitionFieldDiff.confidence_score < LOW_CONFIDENCE_SCORE_THRESHOLD,
            )
        )
        adoption_count = await self.db.scalar(
            select(func.count(VesselRecognitionAdoptionRecord.id)).where(
                VesselRecognitionAdoptionRecord.vessel_profile_id == vessel_id
            )
        )
        latest_adoption = await self.db.scalar(
            select(VesselRecognitionAdoptionRecord)
            .where(VesselRecognitionAdoptionRecord.vessel_profile_id == vessel_id)
            .order_by(VesselRecognitionAdoptionRecord.confirmed_at.desc(), VesselRecognitionAdoptionRecord.id.desc())
            .limit(1)
        )
        active_task_count = 0
        for model in [
            VesselCertificateImageRecognition,
            VesselPersonCertificateImageRecognition,
            VesselOwnerDocumentImageRecognition,
        ]:
            active_task_count += int(
                await self.db.scalar(
                    select(func.count(model.id)).where(
                        model.vessel_profile_id == vessel_id,
                        model.status_code.in_(ACTIVE_RECOGNITION_STATUSES | {"NEED_CONFIRM"}),
                    )
                )
                or 0
            )
        return {
            "pending_diff_count": int(pending_diff_count or 0),
            "low_confidence_diff_count": int(low_confidence_diff_count or 0),
            "active_task_count": active_task_count,
            "adoption_count": int(adoption_count or 0),
            "latest_adoption": (
                {
                    "id": latest_adoption.id,
                    "recognition_object_type": latest_adoption.recognition_object_type,
                    "recognition_id": latest_adoption.recognition_id,
                    "target_object_type": latest_adoption.target_object_type,
                    "target_object_id": latest_adoption.target_object_id,
                    "adopted_fields": latest_adoption.adopted_fields_json or [],
                    "skipped_fields": latest_adoption.skipped_fields_json or [],
                    "confirmed_at": latest_adoption.confirmed_at,
                    "change_event_id": latest_adoption.change_event_id,
                }
                if latest_adoption is not None
                else None
            ),
            "updated_at": latest_adoption.confirmed_at if latest_adoption is not None else None,
        }

    async def get_profile_card(self, vessel_id: int) -> VesselProfileCardResponse:
        profile = await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        city_map = await _load_city_map(self.db, [profile.registry_city_code] if profile.registry_city_code else [])
        region_map = await _load_region_map(self.db, [profile.business_region_id] if profile.business_region_id else [])
        profile_response = _profile_response(profile, label_map=label_map, city_map=city_map, region_map=region_map)
        summary = await self.db.scalar(select(VesselProfileSummary).where(VesselProfileSummary.vessel_profile_id == vessel_id))
        summary_status = self._effective_summary_status(summary) if summary is not None else "MISSING"
        summary_notes = self._summary_json_list(summary.uncertainty_notes_json if summary is not None else None)
        if summary is None:
            summary_notes.append("资产摘要未生成，画像可信字段以 UNKNOWN 展示")
        elif summary_status == "STALE":
            summary_notes.append("源数据晚于摘要刷新时间，画像可能已过期")
        elif summary.summary_status_code == "FAILED":
            summary_notes.append(summary.refresh_error or "摘要刷新失败")

        capacity = await self.repo.get_one_by_profile(VesselCapacityDimension, vessel_id)
        owner_rows = await self.repo.list_by_profile(VesselOwnerPeriod, vessel_id)
        operator_rows = await self.repo.list_by_profile(VesselOperatorPeriod, vessel_id)
        contact_rows = await self.repo.list_by_profile(VesselContact, vessel_id)
        crew_rows = await self.repo.list_by_profile(VesselCrewAssignment, vessel_id)
        current_owners = [row for row in owner_rows if _relation_is_effective(row)]
        current_operators = [row for row in operator_rows if _relation_is_effective(row)]
        current_contacts = [row for row in contact_rows if _relation_is_effective(row)]
        current_crew = [row for row in crew_rows if _relation_is_effective(row)]
        all_relation_rows = [*owner_rows, *operator_rows, *contact_rows, *crew_rows]
        primary_owner = next((row for row in current_owners if row.is_primary), current_owners[0] if current_owners else None)
        primary_operator = next((row for row in current_operators if row.is_primary), current_operators[0] if current_operators else None)
        primary_contact = next((row for row in current_contacts if row.is_primary), current_contacts[0] if current_contacts else None)
        if hasattr(self.db, "scalars"):
            controller_rows = (
                await self.db.scalars(
                    select(VesselControllerEvidence).where(
                        VesselControllerEvidence.vessel_profile_id == vessel_id,
                        VesselControllerEvidence.status_code == "ACTIVE",
                        VesselControllerEvidence.voided_at.is_(None),
                    )
                )
            ).all()
            affiliation_rows = (
                await self.db.scalars(
                    select(VesselAffiliationEvidence).where(
                        VesselAffiliationEvidence.vessel_profile_id == vessel_id,
                        VesselAffiliationEvidence.status_code == "ACTIVE",
                        VesselAffiliationEvidence.voided_at.is_(None),
                    )
                )
            ).all()
        else:
            controller_rows = []
            affiliation_rows = []
        approved_controller_count = sum(
            1 for row in controller_rows if row.verified_status_code == "APPROVED" and row.confidence_level in {"HIGH", "MEDIUM"}
        )
        approved_affiliation_count = sum(
            1 for row in affiliation_rows if row.verified_status_code == "APPROVED" and row.confidence_level in {"HIGH", "MEDIUM"}
        )
        pending_controller_count = sum(1 for row in controller_rows if row.verified_status_code in {"DRAFT", "PENDING", "CHANGE_REQUESTED"})
        pending_affiliation_count = sum(1 for row in affiliation_rows if row.verified_status_code in {"DRAFT", "PENDING", "CHANGE_REQUESTED"})

        name_history = (await self.repo.list_by_profile(VesselNameHistory, vessel_id, order_desc=True))[:5]
        identifier_history = (await self.repo.list_by_profile(VesselIdentifierHistory, vessel_id, order_desc=True))[:5]
        active_issues = await self._summary_active_issues(vessel_id)
        certificate_evidence_count = int(
            await self.db.scalar(
                select(func.count(VesselCertificate.id)).where(
                    VesselCertificate.vessel_profile_id == vessel_id,
                    VesselCertificate.voided_at.is_(None),
                )
            )
            or 0
        )
        formal_risk_payload = await self._formal_risk_summary(vessel_id)
        formal_risk_signals = await self._active_risk_signals(vessel_id) if formal_risk_payload.get("has_formal_signals") else []
        compliance_risk_level = (
            formal_risk_payload["risk_level"]
            if formal_risk_payload.get("has_formal_signals")
            else (summary.risk_level if summary is not None else "UNKNOWN")
        )
        compliance_source_code = "VESSEL_RISK_SIGNAL" if formal_risk_payload.get("has_formal_signals") else "CERTIFICATE_LEDGER_PRE_RULE"
        compliance_source_status = "FORMAL_RISK" if formal_risk_payload.get("has_formal_signals") else "PRE_RULE"
        compliance_message = (
            "Round 5 风险信号，包含规则来源、证据和处理状态"
            if formal_risk_payload.get("has_formal_signals")
            else "证书账本预规则回退，不代表正式合规判断"
        )
        severity_counts: dict[str, int] = defaultdict(int)
        for issue in active_issues:
            severity_counts[issue.severity_code] += 1
        recognition_metrics = await self._recognition_card_metrics(vessel_id)
        relation_updated_at = self._latest_datetime(*(getattr(row, "updated_at", None) for row in all_relation_rows))
        quality_updated_at = self._latest_datetime(*(row.updated_at for row in active_issues))
        recognition_updated_at = recognition_metrics["updated_at"]

        summary_confidence = summary.data_quality_level if summary is not None else "UNKNOWN"
        summary_coverage = _decimal(summary.coverage_rate) if summary is not None else None
        profile_source = self._profile_card_source_trace(
            "VESSEL_PROFILE",
            updated_at=profile.updated_at,
            confidence_level=summary.identity_confidence_level if summary is not None else "UNKNOWN",
        )
        summary_source = self._profile_card_source_trace(
            "VESSEL_SUMMARY",
            updated_at=summary.refreshed_at if summary is not None else None,
            confidence_level=summary_confidence,
            coverage_rate=summary_coverage,
            status_code=summary_status,
            note=summary.refresh_error if summary is not None and summary.summary_status_code == "FAILED" else None,
        )
        relation_source = self._profile_card_source_trace(
            "RELATION_LEDGER",
            updated_at=relation_updated_at,
            confidence_level=summary.subject_consistency_level if summary is not None else "UNKNOWN",
        )
        quality_source = self._profile_card_source_trace(
            "QUALITY_ISSUE",
            updated_at=quality_updated_at,
            confidence_level=summary.data_quality_level if summary is not None else "UNKNOWN",
            status_code="ACTIVE" if active_issues else "EMPTY",
        )
        compliance_source = self._profile_card_source_trace(
            compliance_source_code,
            updated_at=(max((row.updated_at for row in formal_risk_signals), default=None) if formal_risk_signals else (summary.refreshed_at if summary is not None else None)),
            confidence_level=compliance_risk_level,
            status_code=compliance_source_status,
            note=compliance_message,
        )
        trajectory_source = self._profile_card_source_trace(
            "AIS_SUMMARY",
            updated_at=summary.latest_position_time if summary is not None else None,
            confidence_level=summary.ais_freshness_level if summary is not None else "UNKNOWN",
            status_code="AVAILABLE" if summary is not None and summary.latest_position_time else "UNKNOWN",
            note=summary.ais_unavailable_reason if summary is not None else None,
        )
        recognition_source = self._profile_card_source_trace(
            "OCR_ADOPTION",
            updated_at=recognition_updated_at,
            confidence_level="LOW" if recognition_metrics["low_confidence_diff_count"] else ("MEDIUM" if recognition_metrics["pending_diff_count"] else "UNKNOWN"),
            status_code="REVIEW_REQUIRED" if recognition_metrics["pending_diff_count"] else ("ADOPTED" if recognition_metrics["adoption_count"] else "EMPTY"),
        )
        candidate_source = self._profile_card_source_trace(
            "CANDIDATE_ANALYSIS",
            confidence_level="UNKNOWN",
            status_code="UNAVAILABLE",
            note="候选资源适配分析将在 Round 8 接入",
        )
        source_trace = [
            profile_source,
            summary_source,
            relation_source,
            quality_source,
            compliance_source,
            trajectory_source,
            recognition_source,
            candidate_source,
        ]
        identity_updated_at = self._latest_datetime(profile.updated_at, summary.refreshed_at if summary else None)
        relation_voided_count = sum(1 for row in all_relation_rows if getattr(row, "voided_at", None) is not None)
        relation_history_count = sum(1 for row in all_relation_rows if self._relation_status_code(row) == "HISTORY")
        current_relation_count = len(current_owners) + len(current_operators) + len(current_contacts) + len(current_crew)
        top_issues = [self._issue_summary(row) for row in active_issues[:5]]
        conflict_warnings = [
            f"{item.issue_type_code}:{item.field_name or item.affected_object_type}"
            for item in active_issues
            if item.issue_type_code in {"MMSI_CONFLICT", "PROFILE_FIELD_MISSING", "PRIMARY_RELATION_MISSING"}
        ][:5]
        trajectory_card = VesselProfileTrajectoryCard(
            status_code="AVAILABLE" if summary is not None and summary.latest_position_time else "UNKNOWN",
            confidence_level=summary.ais_freshness_level if summary is not None else "UNKNOWN",
            evidence_count=1 if summary is not None and summary.latest_position_time else 0,
            updated_at=summary.latest_position_time if summary is not None else None,
            source_codes=["AIS_SUMMARY", "VESSEL_SUMMARY"],
            uncertainty_notes=[summary.ais_unavailable_reason] if summary is not None and summary.ais_unavailable_reason else ([] if summary is not None and summary.latest_position_time else ["暂无 AIS 摘要位置证据"]),
            ais_freshness_level=summary.ais_freshness_level if summary is not None else "UNKNOWN",
            latest_position_time=summary.latest_position_time if summary is not None else None,
            latest_city_code=summary.latest_city_code if summary is not None else None,
            latest_city_name=summary.latest_city_name if summary is not None else None,
            ais_unavailable_reason=summary.ais_unavailable_reason if summary is not None else None,
            data_availability_status="AVAILABLE" if summary is not None and summary.latest_position_time else "UNKNOWN",
        )
        ais_card = trajectory_card.model_copy(update={"deprecated_alias": True})

        return VesselProfileCardResponse(
            vessel_id=vessel_id,
            generated_at=datetime.utcnow(),
            summary_status_code=summary_status,
            refreshed_at=summary.refreshed_at if summary is not None else None,
            source_updated_at=summary.source_updated_at if summary is not None else profile.updated_at,
            refresh_available=summary_status in {"MISSING", "STALE", "FAILED", "PARTIAL"},
            stale=summary_status == "STALE",
            data_sources=[item.source_code for item in source_trace],
            confidence_level=summary_confidence,
            coverage_rate=summary_coverage,
            source_trace=source_trace,
            uncertainty_notes=summary_notes,
            quality_warnings=[] if not active_issues else [f"当前存在 {len(active_issues)} 条未关闭质量问题"],
            identity_card=VesselProfileIdentityCard(
                status_code="AVAILABLE",
                confidence_level=summary.identity_confidence_level if summary is not None else "UNKNOWN",
                evidence_count=1 + len(name_history) + len(identifier_history),
                updated_at=identity_updated_at,
                source_codes=["VESSEL_PROFILE", "VESSEL_SUMMARY"],
                uncertainty_notes=conflict_warnings,
                ship_name=summary.ship_name if summary is not None and summary.ship_name else profile_response.ship_name,
                current_mmsi=summary.current_mmsi if summary is not None and summary.current_mmsi else profile_response.current_mmsi,
                vessel_profile_code=profile_response.vessel_profile_code,
                ship_type_code=summary.ship_type_code if summary is not None and summary.ship_type_code else profile_response.ship_type_code,
                ship_type_name=summary.ship_type_name if summary is not None and summary.ship_type_name else profile_response.ship_type_name,
                profile_status_code=profile_response.profile_status_code,
                profile_status_name=profile_response.profile_status_name,
                identity_status_code=profile_response.identity_status_code,
                identity_status_name=profile_response.identity_status_name,
                registry_city_code=profile_response.registry_city_code,
                registry_city_name=profile_response.registry_city_name,
                deadweight_ton=_decimal(summary.deadweight_ton if summary is not None else getattr(capacity, "deadweight_ton", None)),
                length_m=_decimal(summary.length_m if summary is not None else getattr(capacity, "length_m", None)),
                width_m=_decimal(summary.width_m if summary is not None else getattr(capacity, "width_m", None)),
                design_draft_m=_decimal(summary.design_draft_m if summary is not None else getattr(capacity, "design_draft_m", None)),
                name_history_summary=[
                    {"id": row.id, "ship_name": row.ship_name, "source_type_code": row.source_type_code, "created_at": row.created_at}
                    for row in name_history[:3]
                ],
                identifier_history_summary=[
                    {
                        "id": row.id,
                        "identifier_type_code": row.identifier_type_code,
                        "identifier_value": row.identifier_value,
                        "status_code": row.status_code,
                        "created_at": row.created_at,
                    }
                    for row in identifier_history[:3]
                ],
                conflict_warnings=conflict_warnings,
            ),
            relation_card=VesselProfileRelationCard(
                status_code="AVAILABLE" if current_relation_count else "UNKNOWN",
                confidence_level=summary.subject_consistency_level if summary is not None else "UNKNOWN",
                evidence_count=len(all_relation_rows),
                updated_at=relation_updated_at,
                source_codes=["RELATION_LEDGER"],
                uncertainty_notes=(
                    ([] if current_relation_count else ["当前有效主体关系缺失"])
                    + ([] if approved_controller_count else ["实际控制人缺少已审核可信证据"])
                    + ([] if approved_affiliation_count or not (primary_owner and primary_operator) else ["挂靠/授权关系缺少已审核可信证据"])
                ),
                primary_owner_name=summary.primary_owner_name if summary is not None and summary.primary_owner_name else (primary_owner.party_name if primary_owner else None),
                primary_operator_name=summary.primary_operator_name if summary is not None and summary.primary_operator_name else (primary_operator.operator_name if primary_operator else None),
                primary_contact_name=summary.primary_contact_name if summary is not None and summary.primary_contact_name else (primary_contact.contact_name if primary_contact else None),
                primary_contact_phone_masked=summary.primary_contact_phone_masked if summary is not None and summary.primary_contact_phone_masked else _mask_phone(primary_contact.mobile_phone if primary_contact else None),
                owner_count=len(current_owners),
                operator_count=len(current_operators),
                contact_count=len(current_contacts),
                crew_count=len(current_crew),
                current_relation_count=current_relation_count,
                history_relation_count=relation_history_count,
                voided_relation_count=relation_voided_count,
                controller_status_code="APPROVED" if approved_controller_count else ("PENDING" if pending_controller_count else "UNKNOWN"),
                affiliation_status_code="APPROVED" if approved_affiliation_count else ("PENDING" if pending_affiliation_count else "UNKNOWN"),
                controller_message=f"已审核可信证据 {approved_controller_count} 条；待治理 {pending_controller_count} 条",
                affiliation_message=f"已审核可信证据 {approved_affiliation_count} 条；待治理 {pending_affiliation_count} 条",
            ),
            quality_card=VesselProfileQualityCard(
                status_code="AVAILABLE" if summary is not None else "UNKNOWN",
                confidence_level=summary.data_quality_level if summary is not None else "UNKNOWN",
                evidence_count=len(active_issues),
                updated_at=quality_updated_at or (summary.refreshed_at if summary is not None else None),
                source_codes=["VESSEL_SUMMARY", "QUALITY_ISSUE"],
                uncertainty_notes=[] if summary is not None else ["摘要缺失，质量评分不可计算"],
                profile_completeness_rate=_decimal(summary.profile_completeness_rate if summary is not None else None),
                data_quality_score=_decimal(summary.data_quality_score if summary is not None else None),
                quality_level=summary.data_quality_level if summary is not None else "UNKNOWN",
                open_issue_count=len(active_issues),
                high_issue_count=severity_counts.get("HIGH", 0),
                medium_issue_count=severity_counts.get("MEDIUM", 0),
                missing_field_count=summary.missing_field_count if summary is not None else 0,
                conflict_count=summary.conflict_count if summary is not None else 0,
                top_active_issues=top_issues,
            ),
            compliance_card=VesselProfileComplianceCard(
                status_code=compliance_source_status if summary is not None or formal_risk_signals else "UNKNOWN",
                confidence_level=compliance_risk_level,
                evidence_count=len(formal_risk_signals) if formal_risk_signals else certificate_evidence_count,
                updated_at=max((row.updated_at for row in formal_risk_signals), default=None) if formal_risk_signals else (summary.refreshed_at if summary is not None else None),
                source_codes=[compliance_source_code, "VESSEL_SUMMARY"],
                uncertainty_notes=[] if compliance_risk_level != "UNKNOWN" else ["证书或主体证据不足，不能输出确定低风险"],
                risk_level=compliance_risk_level,
                certificate_missing_count=formal_risk_payload.get("certificate_missing_count", summary.certificate_missing_count if summary is not None else 0),
                certificate_expiring_count=formal_risk_payload.get("certificate_expiring_count", summary.certificate_expiring_count if summary is not None else 0),
                certificate_expired_count=formal_risk_payload.get("certificate_expired_count", summary.certificate_expired_count if summary is not None else 0),
                risk_evidence_summary=(
                    formal_risk_payload.get("risk_evidence_summary", [])
                    if formal_risk_payload.get("has_formal_signals")
                    else self._summary_json_list(summary.risk_evidence_summary_json if summary is not None else None)
                ),
                evidence_gap_count=(
                    formal_risk_payload.get("certificate_missing_count", 0)
                    + formal_risk_payload.get("certificate_expiring_count", 0)
                    + formal_risk_payload.get("certificate_expired_count", 0)
                    if formal_risk_payload.get("has_formal_signals")
                    else ((summary.certificate_missing_count + summary.certificate_expiring_count + summary.certificate_expired_count) if summary is not None else 0)
                ),
                message=compliance_message,
            ),
            trajectory_card=trajectory_card,
            ais_card=ais_card,
            recognition_card=VesselProfileRecognitionCard(
                status_code="REVIEW_REQUIRED" if recognition_metrics["pending_diff_count"] else ("ADOPTED" if recognition_metrics["adoption_count"] else "EMPTY"),
                confidence_level="LOW" if recognition_metrics["low_confidence_diff_count"] else ("MEDIUM" if recognition_metrics["pending_diff_count"] else "UNKNOWN"),
                evidence_count=recognition_metrics["pending_diff_count"] + recognition_metrics["adoption_count"],
                updated_at=recognition_updated_at,
                source_codes=["OCR_ADOPTION"],
                uncertainty_notes=["存在低置信 OCR 字段待复核"] if recognition_metrics["low_confidence_diff_count"] else [],
                pending_diff_count=recognition_metrics["pending_diff_count"],
                low_confidence_diff_count=recognition_metrics["low_confidence_diff_count"],
                active_task_count=recognition_metrics["active_task_count"],
                adoption_count=recognition_metrics["adoption_count"],
                latest_adoption=recognition_metrics["latest_adoption"],
                message="暂无 OCR 证据" if not recognition_metrics["pending_diff_count"] and not recognition_metrics["adoption_count"] else None,
            ),
            candidate_card=VesselProfileCandidateCard(
                status_code="UNAVAILABLE",
                confidence_level="UNKNOWN",
                evidence_count=0,
                source_codes=["CANDIDATE_ANALYSIS"],
                uncertainty_notes=["候选资源适配分析将在 Round 8 接入"],
            ),
        )

    def _paginate_evidence_items(
        self,
        items: list[VesselProfileCardEvidenceItem],
        *,
        page: int,
        page_size: int,
    ) -> list[VesselProfileCardEvidenceItem]:
        start = (page - 1) * page_size
        return items[start : start + page_size]

    def _relation_evidence_item(self, section: str, object_type: str, row: Any, title: str) -> VesselProfileCardEvidenceItem:
        status_code = self._relation_status_code(row)
        return VesselProfileCardEvidenceItem(
            id=f"{object_type}:{row.id}",
            section=section,
            object_type=object_type,
            object_id=str(row.id),
            title=title,
            status_code=status_code,
            source_code=getattr(row, "source_type_code", None),
            created_at=getattr(row, "created_at", None),
            updated_at=getattr(row, "updated_at", None),
            payload={
                "start_date": getattr(row, "start_date", None),
                "end_date": getattr(row, "end_date", None),
                "is_current": getattr(row, "is_current", None),
                "is_primary": getattr(row, "is_primary", None),
                "revision": getattr(row, "revision", None),
                "verified_status_code": getattr(row, "verified_status_code", None),
                "voided_at": getattr(row, "voided_at", None),
                "void_reason": getattr(row, "void_reason", None),
            },
        )

    async def get_profile_card_evidence(self, vessel_id: int, query: Any) -> VesselProfileCardEvidenceResponse:
        profile = await self._require_profile(vessel_id)
        section = query.section
        page = query.page
        page_size = query.page_size
        items: list[VesselProfileCardEvidenceItem] = []
        notes: list[str] = []

        if section == "identity":
            capacity = await self.repo.get_one_by_profile(VesselCapacityDimension, vessel_id)
            items.append(
                VesselProfileCardEvidenceItem(
                    id=f"vessel_profile:{profile.id}",
                    section=section,
                    object_type="VESSEL_PROFILE",
                    object_id=str(profile.id),
                    title=f"当前船舶主档：{profile.ship_name}",
                    status_code=profile.identity_status_code,
                    source_code=profile.source_type_code,
                    created_at=profile.created_at,
                    updated_at=profile.updated_at,
                    payload={
                        "ship_name": profile.ship_name,
                        "current_mmsi": profile.current_mmsi,
                        "vessel_profile_code": profile.vessel_profile_code,
                        "ship_type_code": profile.ship_type_code,
                        "profile_status_code": profile.profile_status_code,
                        "registry_city_code": profile.registry_city_code,
                        "deadweight_ton": getattr(capacity, "deadweight_ton", None),
                        "length_m": getattr(capacity, "length_m", None),
                        "width_m": getattr(capacity, "width_m", None),
                        "design_draft_m": getattr(capacity, "design_draft_m", None),
                    },
                )
            )
            name_rows = await self.repo.list_by_profile(VesselNameHistory, vessel_id, order_desc=True)
            identifier_rows = await self.repo.list_by_profile(VesselIdentifierHistory, vessel_id, order_desc=True)
            for row in name_rows:
                items.append(
                    VesselProfileCardEvidenceItem(
                        id=f"name_history:{row.id}",
                        section=section,
                        object_type="NAME_HISTORY",
                        object_id=str(row.id),
                        title=f"船名历史：{row.ship_name}",
                        source_code=row.source_type_code,
                        created_at=row.created_at,
                        updated_at=row.created_at,
                        payload={
                            "ship_name": row.ship_name,
                            "start_date": row.start_date,
                            "end_date": row.end_date,
                        },
                    )
                )
            for row in identifier_rows:
                items.append(
                    VesselProfileCardEvidenceItem(
                        id=f"identifier_history:{row.id}",
                        section=section,
                        object_type="IDENTIFIER_HISTORY",
                        object_id=str(row.id),
                        title=f"{row.identifier_type_code} 历史：{row.identifier_value}",
                        status_code=row.status_code,
                        source_code=row.source_type_code,
                        confidence_score=row.confidence_score,
                        created_at=row.created_at,
                        updated_at=row.created_at,
                        payload={
                            "identifier_type_code": row.identifier_type_code,
                            "identifier_value": row.identifier_value,
                            "start_date": row.start_date,
                            "end_date": row.end_date,
                            "source_trace_id": row.source_trace_id,
                        },
                    )
                )
        elif section == "relation":
            for row in await self.repo.list_by_profile(VesselOwnerPeriod, vessel_id):
                items.append(self._relation_evidence_item(section, "OWNER_PERIOD", row, f"所有方：{row.party_name}"))
            for row in await self.repo.list_by_profile(VesselOperatorPeriod, vessel_id):
                items.append(self._relation_evidence_item(section, "OPERATOR_PERIOD", row, f"经营方：{row.operator_name}"))
            for row in await self.repo.list_by_profile(VesselContact, vessel_id):
                items.append(self._relation_evidence_item(section, "CONTACT", row, f"联系人：{row.contact_name}"))
            for row in await self.repo.list_by_profile(VesselCrewAssignment, vessel_id):
                items.append(self._relation_evidence_item(section, "CREW_ASSIGNMENT", row, f"船员：{row.crew_name}"))
            controller_rows = (
                await self.db.scalars(
                    select(VesselControllerEvidence)
                    .where(VesselControllerEvidence.vessel_profile_id == vessel_id)
                    .order_by(VesselControllerEvidence.voided_at.asc().nullsfirst(), VesselControllerEvidence.updated_at.desc())
                )
            ).all()
            affiliation_rows = (
                await self.db.scalars(
                    select(VesselAffiliationEvidence)
                    .where(VesselAffiliationEvidence.vessel_profile_id == vessel_id)
                    .order_by(VesselAffiliationEvidence.voided_at.asc().nullsfirst(), VesselAffiliationEvidence.updated_at.desc())
                )
            ).all()
            for row in controller_rows:
                items.append(self._relation_evidence_item(section, "VESSEL_CONTROLLER_EVIDENCE", row, f"实际控制人证据：{row.party_name}"))
            for row in affiliation_rows:
                items.append(self._relation_evidence_item(section, "VESSEL_AFFILIATION_EVIDENCE", row, f"挂靠关系证据：{row.affiliation_type_code}"))
            if not controller_rows:
                notes.append("暂无实际控制人证据，相关风险保持不可计算或待补证")
            if not affiliation_rows:
                notes.append("暂无挂靠关系证据，相关风险保持不可计算或待补证")
        elif section == "quality":
            rows = (
                await self.db.scalars(
                    select(VesselDataQualityIssue)
                    .where(VesselDataQualityIssue.vessel_profile_id == vessel_id)
                    .order_by(VesselDataQualityIssue.updated_at.desc(), VesselDataQualityIssue.id.desc())
                )
            ).all()
            for row in rows:
                items.append(
                    VesselProfileCardEvidenceItem(
                        id=f"quality_issue:{row.id}",
                        section=section,
                        object_type="QUALITY_ISSUE",
                        object_id=str(row.id),
                        title=f"{row.issue_type_code} / {row.field_name or row.affected_object_type}",
                        status_code=row.status_code,
                        severity_code=row.severity_code,
                        source_code=row.evidence_source,
                        created_at=row.created_at,
                        updated_at=row.updated_at,
                        payload={
                            "affected_object_type": row.affected_object_type,
                            "affected_object_id": row.affected_object_id,
                            "fingerprint": row.fingerprint,
                            "impact_scope": row.impact_scope_json or [],
                            "resolved_at": row.resolved_at,
                            "resolved_evidence": row.resolved_evidence,
                        },
                    )
                )
        elif section == "compliance":
            signal_rows = (
                await self.db.scalars(
                    select(VesselRiskSignal)
                    .where(VesselRiskSignal.vessel_profile_id == vessel_id)
                    .order_by(VesselRiskSignal.updated_at.desc(), VesselRiskSignal.id.desc())
                )
            ).all()
            for row in signal_rows:
                items.append(
                    VesselProfileCardEvidenceItem(
                        id=f"risk_signal:{row.id}",
                        section=section,
                        object_type="VESSEL_RISK_SIGNAL",
                        object_id=str(row.id),
                        title=f"风险信号：{row.risk_type_code}",
                        status_code=row.status_code,
                        severity_code=row.risk_level,
                        source_code="VESSEL_RISK_SIGNAL",
                        created_at=row.created_at,
                        updated_at=row.updated_at,
                        payload={
                            "risk_type_code": row.risk_type_code,
                            "risk_level": row.risk_level,
                            "rule_code": row.rule_code,
                            "confidence_level": row.confidence_level,
                            "evidence": row.evidence_json or {},
                            "uncertainty_notes": row.uncertainty_notes_json or [],
                            "revision": row.revision,
                        },
                    )
                )
            for row in await self.db.scalars(
                select(VesselControllerEvidence).where(VesselControllerEvidence.vessel_profile_id == vessel_id)
            ):
                items.append(
                    VesselProfileCardEvidenceItem(
                        id=f"controller_evidence:{row.id}",
                        section=section,
                        object_type="VESSEL_CONTROLLER_EVIDENCE",
                        object_id=str(row.id),
                        title=f"实际控制人证据：{row.party_name}",
                        status_code=row.status_code,
                        source_code=row.source_type_code,
                        created_at=row.created_at,
                        updated_at=row.updated_at,
                        payload={
                            "controller_role_code": row.controller_role_code,
                            "confidence_level": row.confidence_level,
                            "verified_status_code": row.verified_status_code,
                            "audit_task_id": row.audit_task_id,
                            "evidence_summary": row.evidence_summary,
                            "revision": row.revision,
                        },
                    )
                )
            for row in await self.db.scalars(
                select(VesselAffiliationEvidence).where(VesselAffiliationEvidence.vessel_profile_id == vessel_id)
            ):
                items.append(
                    VesselProfileCardEvidenceItem(
                        id=f"affiliation_evidence:{row.id}",
                        section=section,
                        object_type="VESSEL_AFFILIATION_EVIDENCE",
                        object_id=str(row.id),
                        title=f"挂靠关系证据：{row.affiliation_type_code}",
                        status_code=row.status_code,
                        source_code=row.source_type_code,
                        created_at=row.created_at,
                        updated_at=row.updated_at,
                        payload={
                            "subject_name": row.subject_name,
                            "counterparty_name": row.counterparty_name,
                            "confidence_level": row.confidence_level,
                            "verified_status_code": row.verified_status_code,
                            "audit_task_id": row.audit_task_id,
                            "evidence_summary": row.evidence_summary,
                            "revision": row.revision,
                        },
                    )
                )
            if signal_rows:
                notes.append("合规风险证据来自 Round 5 风险信号和补充证据")
            rows = (
                await self.db.scalars(
                    select(VesselCertificate)
                    .where(VesselCertificate.vessel_profile_id == vessel_id, VesselCertificate.voided_at.is_(None))
                    .order_by(VesselCertificate.updated_at.desc(), VesselCertificate.id.desc())
                )
            ).all()
            for row in rows:
                items.append(
                    VesselProfileCardEvidenceItem(
                        id=f"certificate:{row.id}",
                        section=section,
                        object_type="VESSEL_CERTIFICATE",
                        object_id=str(row.id),
                        title=f"船舶证书：{row.certificate_type_code}",
                        status_code=row.verify_status_code,
                        source_code="CERTIFICATE_LEDGER_PRE_RULE",
                        created_at=row.created_at,
                        updated_at=row.updated_at,
                        payload={
                            "certificate_type_code": row.certificate_type_code,
                            "certificate_no": row.certificate_no,
                            "issuing_authority": row.issuing_authority,
                            "valid_from": row.valid_from,
                            "valid_to": row.valid_to,
                            "is_long_term_valid": row.is_long_term_valid,
                            "validity_text_raw": row.validity_text_raw,
                        },
                    )
                )
            if not signal_rows:
                notes.append("尚未刷新正式风险信号，当前仅展示证书账本证据")
        elif section == "recognition":
            diff_rows = (
                await self.db.scalars(
                    select(VesselRecognitionFieldDiff)
                    .where(VesselRecognitionFieldDiff.vessel_profile_id == vessel_id)
                    .order_by(VesselRecognitionFieldDiff.updated_at.desc(), VesselRecognitionFieldDiff.id.desc())
                )
            ).all()
            adoption_rows = (
                await self.db.scalars(
                    select(VesselRecognitionAdoptionRecord)
                    .where(VesselRecognitionAdoptionRecord.vessel_profile_id == vessel_id)
                    .order_by(VesselRecognitionAdoptionRecord.confirmed_at.desc(), VesselRecognitionAdoptionRecord.id.desc())
                )
            ).all()
            for row in diff_rows:
                items.append(
                    VesselProfileCardEvidenceItem(
                        id=f"recognition_diff:{row.id}",
                        section=section,
                        object_type="RECOGNITION_FIELD_DIFF",
                        object_id=str(row.id),
                        title=f"字段差异：{row.field_name}",
                        status_code=row.adopt_status_code,
                        source_code=row.recognition_object_type,
                        confidence_score=row.confidence_score,
                        created_at=row.created_at,
                        updated_at=row.updated_at,
                        payload={
                            "recognition_id": row.recognition_id,
                            "target_object_type": row.target_object_type,
                            "target_object_id": row.target_object_id,
                            "current_value_text": row.current_value_text,
                            "recognized_value_text": row.recognized_value_text,
                            "evidence_text": row.evidence_text,
                        },
                    )
                )
            for row in adoption_rows:
                items.append(
                    VesselProfileCardEvidenceItem(
                        id=f"recognition_adoption:{row.id}",
                        section=section,
                        object_type="RECOGNITION_ADOPTION",
                        object_id=str(row.id),
                        title=f"OCR 采纳：{row.target_object_type}",
                        status_code="ADOPTED",
                        source_code=row.recognition_object_type,
                        created_at=row.created_at,
                        updated_at=row.confirmed_at,
                        payload={
                            "recognition_id": row.recognition_id,
                            "target_object_id": row.target_object_id,
                            "adopted_fields": row.adopted_fields_json or [],
                            "skipped_fields": row.skipped_fields_json or [],
                            "reason": row.reason,
                            "change_event_id": row.change_event_id,
                        },
                    )
                )
            if not items:
                notes.append("暂无 OCR 证据")
        elif section == "trajectory":
            summary = await self.db.scalar(select(VesselProfileSummary).where(VesselProfileSummary.vessel_profile_id == vessel_id))
            if summary is None:
                notes.append("资产摘要未生成，暂无轨迹摘要证据")
            else:
                items.append(
                    VesselProfileCardEvidenceItem(
                        id=f"trajectory_summary:{summary.id}",
                        section=section,
                        object_type="AIS_SUMMARY",
                        object_id=str(summary.id),
                        title=f"AIS 摘要：{summary.ais_freshness_level}",
                        status_code=summary.ais_freshness_level,
                        source_code="AIS_SUMMARY",
                        created_at=summary.created_at,
                        updated_at=summary.refreshed_at,
                        payload={
                            "latest_position_time": summary.latest_position_time,
                            "latest_city_code": summary.latest_city_code,
                            "latest_city_name": summary.latest_city_name,
                            "ais_unavailable_reason": summary.ais_unavailable_reason,
                            "summary_status_code": self._effective_summary_status(summary),
                        },
                    )
                )

        items.sort(key=lambda item: item.updated_at or item.created_at or datetime.min, reverse=True)
        source_code = {
            "identity": "VESSEL_PROFILE",
            "relation": "RELATION_LEDGER",
            "quality": "QUALITY_ISSUE",
            "compliance": "VESSEL_RISK_SIGNAL",
            "recognition": "OCR_ADOPTION",
            "trajectory": "AIS_SUMMARY",
        }.get(section, "VESSEL_PROFILE")
        return VesselProfileCardEvidenceResponse(
            total=len(items),
            page=page,
            page_size=page_size,
            items=self._paginate_evidence_items(items, page=page, page_size=page_size),
            section=section,
            source_trace=[self._profile_card_source_trace(source_code, status_code="AVAILABLE" if items else "EMPTY")],
            uncertainty_notes=notes,
        )

    async def position_monitor(self, query) -> VesselPositionMonitorResponse:
        generated_at = datetime.utcnow()
        profiles = await self._position_monitor_profiles(query)
        if not profiles:
            return self._empty_position_response(generated_at, "未匹配到符合条件的船舶档案")
        if not await self._realtime_es_host():
            return VesselPositionMonitorResponse(
                source_status="UNCONFIGURED",
                source_status_name=_source_status_name("UNCONFIGURED"),
                generated_at=generated_at,
                message="实时 ES 未配置，暂无可展示船位",
                summary=VesselPositionMonitorSummary(
                    matched_profile_count=len(profiles),
                    positioned_count=0,
                    stale_position_count=0,
                    contactable_position_count=0,
                ),
                items=[],
            )
        mmsi_by_profile = await self._mmsi_values_by_profile([row.id for row in profiles])
        mmsi_values = sorted({item for values in mmsi_by_profile.values() for item in values if item})
        if not mmsi_values:
            return self._empty_position_response(generated_at, "匹配船舶缺少可用于实时查询的 MMSI", len(profiles))
        limits = await self._ais_runtime_limits()
        result = await self._position_monitor_items_for_profiles(
            profiles,
            generated_at=generated_at,
            reported_within_minutes=query.reported_within_minutes or 1440,
            es_batch_size=limits["es_batch_size"],
            es_max_concurrency=limits["es_max_concurrency"],
            include_stale=True,
        )
        if not result.items and not result.partial:
            return self._empty_position_response(generated_at, "实时 ES 未返回匹配船位", len(profiles))
        fresh_items = [
            item for item in result.items
            if not self._is_stale_position(item, generated_at, query.reported_within_minutes or 1440)
        ][:query.max_items]
        return VesselPositionMonitorResponse(
            source_status="ERROR" if result.partial and not fresh_items else ("AVAILABLE" if fresh_items else "EMPTY"),
            source_status_name=_source_status_name("ERROR" if result.partial and not fresh_items else ("AVAILABLE" if fresh_items else "EMPTY")),
            generated_at=generated_at,
            message=result.error_message if result.partial else (None if fresh_items else "实时 ES 暂无符合筛选条件的船位"),
            summary=VesselPositionMonitorSummary(
                matched_profile_count=len(profiles),
                positioned_count=len(fresh_items),
                stale_position_count=max(0, len(result.items) - len(fresh_items)),
                contactable_position_count=sum(1 for item in fresh_items if item.contact_available),
                unmatched_mmsi_count=0,
                invalid_position_count=len(result.invalid_positions),
                coverage_rate=self._coverage_rate(result.matched_position_count, result.queried_mmsi_count),
                freshness_distribution=self._position_freshness_distribution(result.items),
            ),
            items=fresh_items,
        )

    async def position_city_situation(self, query) -> VesselPositionCitySituationResponse:
        generated_at = datetime.utcnow()
        cache_key = _city_situation_query_cache_key(query)
        cache_backend = await self._city_cache_backend()
        limits = await self._ais_runtime_limits()
        profile_limit = limits["profile_limit"]
        es_batch_size = limits["es_batch_size"]
        es_max_concurrency = limits["es_max_concurrency"]
        unmatched_scan_limit = limits["unmatched_scan_limit"]
        cached = await self._get_city_situation_response_cache(cache_key)
        if cached is not None:
            cached_response, cache_backend = cached
            return cached_response.model_copy(
                update={
                    "cache_status": "HIT",
                    "cache_generated_at": cached_response.generated_at,
                    "is_stale_cache": False,
                    "snapshot_backend": cache_backend,
                    "cache_backend_note": "memory 仅适合本地开发；生产多实例请配置 Redis" if cache_backend == "memory" else None,
                },
                deep=True,
            )
        total_profile_count = await self._position_monitor_profile_count(query)
        profiles = await self._position_monitor_profiles(query, limit=profile_limit)
        unscanned_profile_count = max(0, (total_profile_count or len(profiles)) - len(profiles))
        if not profiles:
            return VesselPositionCitySituationResponse(
                source_status="EMPTY",
                source_status_name=_source_status_name("EMPTY"),
                generated_at=generated_at,
                message="未匹配到符合条件的船舶档案",
                cache_status="MISS",
                cache_generated_at=generated_at,
                is_stale_cache=False,
                snapshot_backend=cache_backend,
                cache_backend_note="memory 仅适合本地开发；生产多实例请配置 Redis" if cache_backend == "memory" else None,
                summary=VesselPositionCitySituationSummary(
                    matched_profile_count=0,
                    scanned_profile_count=0,
                    unscanned_profile_count=0,
                    queried_mmsi_count=0,
                    matched_position_count=0,
                    unpositioned_count=0,
                    invalid_position_count=0,
                    unknown_city_count=0,
                    positioned_count=0,
                    stale_position_count=0,
                    contactable_position_count=0,
                    certificate_risk_count=0,
                    city_count=0,
                    query_snapshot_id=None,
                ),
                cities=[],
            )
        if not await self._realtime_es_host():
            return VesselPositionCitySituationResponse(
                source_status="UNCONFIGURED",
                source_status_name=_source_status_name("UNCONFIGURED"),
                generated_at=generated_at,
                message="实时 ES 未配置，暂无城市态势",
                cache_status="MISS",
                cache_generated_at=generated_at,
                is_stale_cache=False,
                snapshot_backend=cache_backend,
                cache_backend_note="memory 仅适合本地开发；生产多实例请配置 Redis" if cache_backend == "memory" else None,
                summary=VesselPositionCitySituationSummary(
                    matched_profile_count=total_profile_count or len(profiles),
                    scanned_profile_count=len(profiles),
                    unscanned_profile_count=unscanned_profile_count,
                    queried_mmsi_count=0,
                    matched_position_count=0,
                    unpositioned_count=0,
                    invalid_position_count=0,
                    unknown_city_count=0,
                    positioned_count=0,
                    stale_position_count=0,
                    contactable_position_count=0,
                    certificate_risk_count=0,
                    city_count=0,
                    query_snapshot_id=None,
                ),
                cities=[],
            )
        result = await self._position_monitor_items_for_profiles(
            profiles,
            generated_at=generated_at,
            reported_within_minutes=query.reported_within_minutes or 1440,
            es_batch_size=es_batch_size,
            es_max_concurrency=es_max_concurrency,
            include_stale=True,
            include_unmatched=True,
            unmatched_scan_limit=unmatched_scan_limit,
        )
        partial = result.partial
        error_message = result.error_message
        if unscanned_profile_count > 0:
            partial = True
            error_parts = [part for part in [error_message, f"服务端按扫描上限统计，未扫描档案 {unscanned_profile_count} 艘"] if part]
            error_message = "；".join(error_parts) or None
        risk_by_profile = await self._compliance_risk_by_profile([item.id for item in result.items])
        boundaries = await self._city_boundaries()
        boundary_codes = {boundary.code for boundary in boundaries}
        boundary_paths_by_code = self._city_boundary_paths_by_code(boundaries, query.boundary_precision) if query.include_boundary else {}
        cities = self._city_situation_items(
            result.items,
            risk_by_profile,
            generated_at,
            query.reported_within_minutes or 1440,
            result.queried_mmsi_count,
            result.matched_position_count,
            result.unpositioned_count,
            result.invalid_position_count,
            result.unknown_city_count,
            partial,
            error_message,
            boundary_paths_by_code,
            query.boundary_precision if query.include_boundary else None,
            boundary_codes,
            result.unmatched_positions,
        )
        missing_boundary_cities = [
            {
                "city_code": city.city_code,
                "city_name": city.city_name,
                "positioned_count": city.positioned_count,
            }
            for city in cities
            if city.city_code and city.positioned_count > 0 and not city.has_boundary
        ]
        snapshot_id = await self._store_city_situation_snapshot(
            result.items,
            generated_at=generated_at,
            partial=partial,
            error_message=error_message,
        )
        positioned_items = [item for item in result.items if not self._is_stale_position(item, generated_at, query.reported_within_minutes or 1440)]
        freshness_distribution = self._position_freshness_distribution(result.items, result.unmatched_positions)
        coverage_rate = self._coverage_rate(result.matched_position_count, result.queried_mmsi_count)
        uncertainty_notes: list[str] = []
        if cache_backend == "memory":
            uncertainty_notes.append("当前快照使用本机内存缓存，多实例部署时建议使用 Redis；DB 快照仍会保留一致性基线")
        if partial:
            uncertainty_notes.append("本次 AIS 态势为部分结果")
        if result.unmatched_positions:
            uncertainty_notes.append(f"发现未匹配 MMSI {len(result.unmatched_positions)} 个")
        if result.invalid_positions:
            uncertainty_notes.append(f"发现无效点位 {len(result.invalid_positions)} 条")
        if result.source_indices:
            uncertainty_notes.append(f"实时 ES 来源索引：{', '.join(result.source_indices[:5])}")
        snapshot_expires_at = generated_at + timedelta(seconds=_city_snapshot_ttl())
        response_status = "PARTIAL" if partial and cities else ("ERROR" if partial and not cities else ("AVAILABLE" if cities else "EMPTY"))
        response = VesselPositionCitySituationResponse(
            source_status=response_status,
            source_status_name=_source_status_name(response_status),
            generated_at=generated_at,
            message=error_message if partial else (None if cities else "实时 ES 暂无符合筛选条件的城市态势"),
            cache_status="MISS",
            cache_generated_at=generated_at,
            is_stale_cache=False,
            snapshot_backend=cache_backend,
            cache_backend_note="memory 仅适合本地开发；生产多实例请配置 Redis" if cache_backend == "memory" else None,
            summary=VesselPositionCitySituationSummary(
                matched_profile_count=total_profile_count or len(profiles),
                scanned_profile_count=len(profiles),
                unscanned_profile_count=unscanned_profile_count,
                queried_mmsi_count=result.queried_mmsi_count,
                matched_position_count=result.matched_position_count,
                unmatched_mmsi_count=len([item for item in result.unmatched_positions if item.get("match_status_code") == "UNMATCHED_MMSI"]),
                unpositioned_count=result.unpositioned_count,
                invalid_position_count=len(result.invalid_positions),
                unknown_city_count=result.unknown_city_count + len([item for item in result.unmatched_positions if not item.get("city_code")]),
                positioned_count=len(positioned_items),
                stale_position_count=len(result.items) - len(positioned_items),
                contactable_position_count=sum(1 for item in positioned_items if item.contact_available),
                certificate_risk_count=sum(1 for item in positioned_items if risk_by_profile.get(item.id)),
                city_count=sum(1 for city in cities if city.city_code),
                boundary_city_count=sum(1 for city in cities if city.city_code and city.has_boundary),
                missing_boundary_city_count=len(missing_boundary_cities),
                missing_boundary_cities=missing_boundary_cities,
                query_snapshot_id=snapshot_id,
                snapshot_status_code="PARTIAL" if partial else "READY",
                snapshot_expires_at=snapshot_expires_at,
                refresh_required=False,
                coverage_rate=coverage_rate,
                freshness_distribution=freshness_distribution,
                source_indices=result.source_indices,
                uncertainty_notes=uncertainty_notes,
                failed_batch_count=result.failed_batch_count,
                failed_batches=getattr(result, "failed_batches", []),
                is_partial=partial,
                error_message=error_message,
            ),
            cities=cities,
        )
        persisted = False
        try:
            await self._persist_city_situation_snapshot(
                snapshot_id=snapshot_id,
                query=query,
                response=response,
                result=result,
                cities=cities,
                cache_backend=cache_backend,
            )
            await self.db.commit()
            persisted = True
        except Exception as exc:  # noqa: BLE001
            await self.db.rollback()
            await self._discard_city_situation_snapshot(snapshot_id)
            failure_note = "AIS 城市态势快照持久化失败，城市下钻已禁用"
            response.summary.query_snapshot_id = None
            response.summary.snapshot_status_code = "PERSIST_FAILED"
            response.summary.refresh_required = True
            response.summary.error_message = "；".join([part for part in [response.summary.error_message, failure_note] if part])
            response.summary.uncertainty_notes = [*response.summary.uncertainty_notes, failure_note]
            response.message = "；".join([part for part in [response.message, failure_note] if part])
            logger.warning("persist AIS city situation snapshot failed: %s", exc)
        if persisted:
            try:
                for position in result.unmatched_positions[:50]:
                    if position.get("match_status_code") != "UNMATCHED_MMSI":
                        continue
                    mmsi = str(position.get("mmsi") or "")
                    if not mmsi:
                        continue
                    await self._upsert_quality_issue(
                        issue_type_code="AIS_UNMATCHED",
                        profile_id=None,
                        object_type="mmsi",
                        object_id=mmsi,
                        normalized_key=f"mmsi|{mmsi}",
                        evidence_source="AIS_REALTIME",
                        severity_code="LOW",
                        impact_scope=[{"snapshot_id": snapshot_id, "mmsi": mmsi, "position_time": _jsonable(position.get("position_time"))}],
                    )
                await self.db.commit()
            except Exception as exc:  # noqa: BLE001
                await self.db.rollback()
                logger.warning("persist AIS unmatched quality issues failed: %s", exc)
            await self._store_city_situation_response_cache(cache_key, response)
        return response

    async def position_city_vessels(self, query) -> VesselPositionCityVesselsResponse:
        snapshot = await self._get_city_situation_snapshot(query.query_snapshot_id)
        snapshot_hit = snapshot is not None
        if not query.query_snapshot_id:
            return VesselPositionCityVesselsResponse(
                total=0,
                page=query.page,
                page_size=query.page_size,
                items=[],
                query_snapshot_id=None,
                snapshot_hit=False,
                refresh_required=True,
                snapshot_status_code="MISSING",
                is_partial=False,
                error_message="城市下钻必须带 query_snapshot_id，请先刷新 AIS 城市态势",
            )
        if not snapshot or snapshot.refresh_required or snapshot.status_code == "EXPIRED":
            return VesselPositionCityVesselsResponse(
                total=0,
                page=query.page,
                page_size=query.page_size,
                items=[],
                query_snapshot_id=query.query_snapshot_id,
                snapshot_hit=False,
                refresh_required=True,
                snapshot_status_code="EXPIRED",
                is_partial=False,
                error_message="SNAPSHOT_EXPIRED",
            )
        items = [
            item for item in snapshot.items
            if not self._is_stale_position(item, snapshot.generated_at, query.reported_within_minutes or 1440)
        ]
        partial = snapshot.partial
        error_message = snapshot.error_message
        snapshot_id = snapshot.snapshot_id
        filtered = [
            item for item in items
            if self._city_matches(item, city_code=query.city_code, city_name=query.city_name)
        ]
        start = (query.page - 1) * query.page_size
        return VesselPositionCityVesselsResponse(
            total=len(filtered),
            page=query.page,
            page_size=query.page_size,
            items=filtered[start:start + query.page_size],
            query_snapshot_id=snapshot_id,
            snapshot_hit=snapshot_hit,
            refresh_required=False,
            snapshot_status_code=snapshot.status_code,
            is_partial=partial,
            error_message=error_message,
        )

    async def ais_city_boundaries(self, query) -> VesselAisCityBoundaryResponse:
        precision = getattr(query, "precision", "low") or "low"
        requested_codes: set[str] = set()
        city_code = getattr(query, "city_code", None)
        city_codes = getattr(query, "city_codes", None)
        if city_code:
            requested_codes.add(str(city_code).strip())
        if city_codes:
            requested_codes.update(code.strip() for code in str(city_codes).split(",") if code.strip())
        boundaries = await self._city_boundaries()
        items: list[VesselAisCityBoundaryItemResponse] = []
        for boundary in boundaries:
            if requested_codes and boundary.code not in requested_codes:
                continue
            paths = (boundary.boundary_paths_by_precision or {}).get(precision) or _boundary_paths_for_precision(boundary.polygons, precision)
            items.append(
                VesselAisCityBoundaryItemResponse(
                    city_code=boundary.code,
                    city_name=boundary.name,
                    boundary_paths=_serialize_boundary_paths(paths) or [],
                    has_boundary=bool(paths),
                    boundary_precision=precision,
                    boundary_status_code="AVAILABLE" if paths else "MISSING",
                    city_center_longitude=boundary.center_longitude,
                    city_center_latitude=boundary.center_latitude,
                )
            )
        missing = sorted(requested_codes - {item.city_code for item in items})
        return VesselAisCityBoundaryResponse(
            generated_at=datetime.utcnow(),
            boundary_version_id=self._city_boundary_version_id(),
            precision=precision,
            total=len(items),
            items=items,
            uncertainty_notes=[f"缺少城市边界：{', '.join(missing)}"] if missing else [],
        )

    async def ais_snapshot(self, snapshot_id: str) -> VesselAisSnapshotResponse:
        snapshot = await self.db.scalar(select(VesselAisSnapshot).where(VesselAisSnapshot.snapshot_id == snapshot_id))
        if snapshot is None:
            raise NotFoundError("VesselAisSnapshot", snapshot_id)
        status_code = "EXPIRED" if snapshot.expires_at <= datetime.utcnow() else snapshot.status_code
        return VesselAisSnapshotResponse(
            snapshot_id=snapshot.snapshot_id,
            query_hash=snapshot.query_hash,
            query_params=snapshot.query_params_json or {},
            status_code=status_code,
            generated_at=snapshot.generated_at,
            expires_at=snapshot.expires_at,
            cache_backend_code=snapshot.cache_backend_code,
            scanned_profile_count=snapshot.scanned_profile_count,
            queried_mmsi_count=snapshot.queried_mmsi_count,
            matched_profile_count=snapshot.matched_profile_count,
            matched_position_count=snapshot.matched_position_count,
            unmatched_mmsi_count=snapshot.unmatched_mmsi_count,
            invalid_position_count=snapshot.invalid_position_count,
            unknown_city_count=snapshot.unknown_city_count,
            failed_batch_count=snapshot.failed_batch_count,
            failed_batches=snapshot.failed_batches_json or [],
            coverage_rate=snapshot.coverage_rate,
            freshness_distribution=snapshot.freshness_distribution_json or {},
            source_indices=snapshot.source_indices_json or [],
            uncertainty_notes=snapshot.uncertainty_notes_json or [],
            refresh_error=snapshot.refresh_error,
        )

    async def list_unmatched_mmsi(self, query) -> PageResponse[VesselAisUnmatchedMmsiResponse]:
        snapshot_id = getattr(query, "snapshot_id", None)
        snapshot = None
        if snapshot_id:
            snapshot = await self.db.scalar(select(VesselAisSnapshot).where(VesselAisSnapshot.snapshot_id == snapshot_id))
        else:
            snapshot = await self.db.scalar(
                select(VesselAisSnapshot)
                .where(VesselAisSnapshot.status_code.in_(["READY", "PARTIAL"]))
                .order_by(VesselAisSnapshot.generated_at.desc())
                .limit(1)
            )
        if snapshot is None:
            return PageResponse(total=0, page=query.page, page_size=query.page_size, items=[])
        stmt = (
            select(VesselLatestPositionSnapshot)
            .where(
                VesselLatestPositionSnapshot.snapshot_id == snapshot.snapshot_id,
                VesselLatestPositionSnapshot.match_status_code == "UNMATCHED_MMSI",
            )
            .order_by(VesselLatestPositionSnapshot.position_time.desc(), VesselLatestPositionSnapshot.id.desc())
        )
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(stmt.offset((query.page - 1) * query.page_size).limit(query.page_size))
        ).scalars().all()
        return PageResponse(
            total=total,
            page=query.page,
            page_size=query.page_size,
            items=[
                VesselAisUnmatchedMmsiResponse(
                    snapshot_id=row.snapshot_id,
                    generated_at=snapshot.generated_at,
                    mmsi=row.mmsi,
                    longitude=row.longitude,
                    latitude=row.latitude,
                    position_time=row.position_time,
                    freshness_level=row.freshness_level,
                    source_index=row.source_index,
                    city_code=row.city_code,
                    city_name=row.city_name,
                    match_status_code=row.match_status_code,
                )
                for row in rows
            ],
        )

    async def position_ais_situation_card(self, vessel_id: int) -> VesselAisSituationCardResponse:
        generated_at = datetime.utcnow()
        profile = await self._require_profile(vessel_id)
        list_item = (await self._build_list_items([profile]))[0]
        data_sources = ["VESSEL_PROFILE"]
        uncertainty_notes: list[str] = []
        result = None
        items: list[VesselPositionMonitorItemResponse] = []
        realtime_available = await self._realtime_es_host()
        if realtime_available:
            data_sources.append("AIS_REALTIME")
            limits = await self._ais_runtime_limits()
            result = await self._position_monitor_items_for_profiles(
                [profile],
                generated_at=generated_at,
                reported_within_minutes=1440,
                es_batch_size=limits["es_batch_size"],
                es_max_concurrency=limits["es_max_concurrency"],
                include_stale=True,
            )
            items = result.items
        else:
            uncertainty_notes.append("实时 ES 未配置，AIS 位置不可计算")
        position = items[0] if items else None
        source_status = "UNCONFIGURED"
        if realtime_available:
            source_status = "ERROR" if result and result.partial and position is None else ("AVAILABLE" if position else "EMPTY")
        if result and result.error_message:
            uncertainty_notes.append(result.error_message)
        if position is None and realtime_available:
            uncertainty_notes.append("实时 ES 暂未返回该船最新位置")
        freshness_level = _ais_freshness_level(position.position_age_minutes if position else None)
        if freshness_level in {"STALE", "EXPIRED", "UNKNOWN"}:
            uncertainty_notes.append(f"AIS 新鲜度为 {freshness_level}")
        return VesselAisSituationCardResponse(
            vessel_id=vessel_id,
            generated_at=generated_at,
            data_sources=data_sources,
            uncertainty_notes=uncertainty_notes,
            identity={
                "ship_name": list_item.ship_name,
                "current_mmsi": list_item.current_mmsi,
                "ship_type_name": list_item.ship_type_name,
                "deadweight_ton": list_item.deadweight_ton,
                "size_text": list_item.size_text,
                "ship_age": list_item.ship_age,
                "registry_city_name": list_item.registry_city_name,
            },
            realtime={
                "longitude": position.longitude if position else None,
                "latitude": position.latitude if position else None,
                "current_city_code": getattr(position, "current_city_code", None) if position else None,
                "current_city_name": getattr(position, "current_city_name", None) if position else None,
                "current_city_source": getattr(position, "current_city_source", None) if position else None,
                "location_text": position.location_text if position else None,
                "speed_kn": position.speed_kn if position else None,
                "course_deg": position.course_deg if position else None,
                "heading_deg": position.heading_deg if position else None,
                "position_time": position.position_time if position else None,
                "position_age_minutes": position.position_age_minutes if position else None,
                "ais_freshness_level": freshness_level,
            },
            data_availability={
                "source_status": source_status,
                "source_status_name": _source_status_name(source_status),
                "has_realtime_position": position is not None,
                "reported_within_minutes": 1440,
                "partial": bool(result.partial) if result else False,
                "error_message": result.error_message if result else None,
                "snapshot_backend": await self._city_cache_backend(),
                "source_index": getattr(position, "source_index", None) if position else None,
            },
            quality={
                "mmsi_present": bool(list_item.current_mmsi),
                "valid_position": position is not None,
                "position_freshness_level": freshness_level,
                "current_city_source": getattr(position, "current_city_source", None) if position else None,
            },
        )

    async def position_business_card(self, vessel_id: int) -> VesselBusinessSituationCardResponse:
        generated_at = datetime.utcnow()
        profile = await self._require_profile(vessel_id)
        items: list[VesselPositionMonitorItemResponse] = []
        if await self._realtime_es_host():
            result = await self._position_monitor_items_for_profiles(
                [profile],
                generated_at=generated_at,
                reported_within_minutes=43200,
                es_batch_size=50,
                es_max_concurrency=1,
                include_stale=True,
            )
            items = result.items
        list_item = (await self._build_list_items([profile]))[0]
        position = items[0] if items else None
        risk = (await self._compliance_risk_by_profile([vessel_id])).get(vessel_id, {})
        return VesselBusinessSituationCardResponse(
            vessel_id=vessel_id,
            generated_at=generated_at,
            identity={
                "ship_name": list_item.ship_name,
                "current_mmsi": list_item.current_mmsi,
                "ship_type_name": list_item.ship_type_name,
                "deadweight_ton": list_item.deadweight_ton,
                "size_text": list_item.size_text,
                "ship_age": list_item.ship_age,
                "registry_city_name": list_item.registry_city_name,
            },
            realtime={
                "longitude": position.longitude if position else None,
                "latitude": position.latitude if position else None,
                "current_city_code": getattr(position, "current_city_code", None) if position else None,
                "current_city_name": getattr(position, "current_city_name", None) if position else None,
                "current_city_source": getattr(position, "current_city_source", None) if position else None,
                "location_text": position.location_text if position else None,
                "speed_kn": position.speed_kn if position else None,
                "course_deg": position.course_deg if position else None,
                "heading_deg": position.heading_deg if position else None,
                "position_time": position.position_time if position else None,
                "position_age_minutes": position.position_age_minutes if position else None,
            },
            operation={
                "owner_name": list_item.primary_owner_name,
                "operator_name": list_item.primary_operator_name,
                "primary_contact_name": list_item.primary_contact_name,
                "primary_contact_phone": list_item.primary_contact_phone,
                "contact_available": list_item.contact_available,
            },
            compliance=risk,
            business={
                "contactable": bool(list_item.contact_available and list_item.primary_contact_phone),
                "tonnage_ready": list_item.deadweight_ton is not None,
            },
        )

    async def create_vessel(self, payload, *, operator_id: int | None = None) -> VesselProfileResponse:
        await self._assert_active_mmsi_available(payload.mmsi, evidence_source="CREATE_VESSEL")
        code = await CodeSequenceService(self.db).next_code("VESSEL_PROFILE_CODE")
        entity = await self.repo.create_profile(
            {
                "vessel_profile_code": code,
                "ship_name": payload.ship_name.strip(),
                "current_mmsi": payload.mmsi,
                "profile_status_code": "ACTIVE",
                "identity_status_code": "UNLINKED",
                "source_type_code": "MANUAL",
                "audit_status": "PENDING",
            }
        )
        await self.repo.add_name_history(entity.id, entity.ship_name)
        await self.repo.add_identifier_history(entity.id, "MMSI", entity.current_mmsi)
        await self._add_change_event(entity.id, "CREATE", "新增船舶档案", None, _row_dict(entity), operator_id)
        await self.db.commit()
        await self._refresh_summary_best_effort(entity.id)
        return await self._build_profile_response(entity.id)

    async def update_profile(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselProfileResponse:
        profile = await self._require_profile(vessel_id)
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        before = _row_dict(profile)
        if "ship_name" in updates:
            updates["ship_name"] = updates["ship_name"].strip()
        new_status = updates.get("profile_status_code", profile.profile_status_code)
        new_mmsi = updates.get("current_mmsi", profile.current_mmsi)
        becoming_active = profile.profile_status_code != ACTIVE_PROFILE_STATUS and new_status == ACTIVE_PROFILE_STATUS
        mmsi_changing = "current_mmsi" in updates and new_mmsi != before.get("current_mmsi")
        if new_status == ACTIVE_PROFILE_STATUS and (becoming_active or mmsi_changing):
            await self._assert_active_mmsi_available(
                new_mmsi,
                exclude_vessel_id=vessel_id,
                attempted_profile_id=vessel_id,
                evidence_source="UPDATE_PROFILE",
            )
        row = await self.repo.update_profile(vessel_id, updates)
        if row is None:
            raise NotFoundError("VesselProfile", vessel_id)
        if "ship_name" in updates and updates["ship_name"] != before.get("ship_name"):
            await self.repo.add_name_history(vessel_id, updates["ship_name"])
        if "current_mmsi" in updates and updates["current_mmsi"] != before.get("current_mmsi"):
            await self._close_current_mmsi_history(vessel_id, before.get("current_mmsi"))
            await self.repo.add_identifier_history(vessel_id, "MMSI", updates["current_mmsi"])
        await self._add_change_event(vessel_id, "UPDATE_PROFILE", "更新船舶主档", before, updates, operator_id)
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        return await self._build_profile_response(vessel_id)

    async def get_detail(self, vessel_id: int) -> VesselDetailResponse:
        profile = await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        city_map = await _load_city_map(self.db, [profile.registry_city_code] if profile.registry_city_code else [])
        region_map = await _load_region_map(self.db, [profile.business_region_id] if profile.business_region_id else [])
        owner_rows = [row for row in await self.repo.list_by_profile(VesselOwnerPeriod, vessel_id) if _relation_is_effective(row)]
        owner_documents = await self._owner_documents_by_owner(vessel_id, label_map)
        operator_rows = [row for row in await self.repo.list_by_profile(VesselOperatorPeriod, vessel_id) if _relation_is_effective(row)]
        contact_rows = [row for row in await self.repo.list_by_profile(VesselContact, vessel_id) if _relation_is_effective(row)]
        crew_rows = [row for row in await self.repo.list_by_profile(VesselCrewAssignment, vessel_id) if _relation_is_effective(row)]
        return VesselDetailResponse(
            profile=_profile_response(profile, label_map=label_map, city_map=city_map, region_map=region_map),
            registration=self._maybe(VesselRegistrationResponse, await self.repo.get_one_by_profile(VesselRegistrationInfo, vessel_id)),
            capacity=self._maybe(VesselCapacityResponse, await self.repo.get_one_by_profile(VesselCapacityDimension, vessel_id)),
            build_info=self._maybe(VesselBuildInfoResponse, await self.repo.get_one_by_profile(VesselBuildInfo, vessel_id)),
            owners=[self._owner_response(row, label_map, documents=owner_documents.get(row.id, [])) for row in owner_rows],
            operators=[self._operator_response(row, label_map) for row in operator_rows],
            contacts=[self._contact_response(row, label_map) for row in contact_rows],
            crew=[self._crew_response(row, label_map) for row in crew_rows],
            person_certificates=await self._person_certificates_with_files(vessel_id, label_map=label_map),
            certificates=await self._certificates_with_files(vessel_id, label_map=label_map),
            name_history=[
                VesselNameHistoryResponse(
                    **_row_dict(row),
                    source_type_name=label_map.get("SOURCE_TYPE", {}).get(row.source_type_code),
                )
                for row in await self.repo.list_by_profile(VesselNameHistory, vessel_id, order_desc=True)
            ],
            identifier_history=[
                VesselIdentifierHistoryResponse(
                    **_row_dict(row),
                    source_type_name=label_map.get("SOURCE_TYPE", {}).get(row.source_type_code),
                )
                for row in await self.repo.list_by_profile(VesselIdentifierHistory, vessel_id, order_desc=True)
            ],
            change_events=[
                VesselChangeEventResponse(
                    **_row_dict(row),
                    event_type_name=label_map.get("VESSEL_CHANGE_EVENT_TYPE", {}).get(row.event_type_code),
                )
                for row in await self.repo.list_by_profile(VesselChangeEvent, vessel_id, order_desc=True)
            ],
        )

    async def list_owners(self, vessel_id: int, *, current_only: bool = True) -> list[VesselOwnerResponse]:
        await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        rows = await self.repo.list_by_profile(VesselOwnerPeriod, vessel_id)
        if current_only:
            rows = [row for row in rows if _relation_is_effective(row)]
        docs = await self._owner_documents_by_owner(vessel_id, label_map)
        return [self._owner_response(row, label_map, documents=docs.get(row.id, [])) for row in rows]

    async def list_operators(self, vessel_id: int, *, current_only: bool = True) -> list[VesselOperatorResponse]:
        await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        rows = await self.repo.list_by_profile(VesselOperatorPeriod, vessel_id)
        if current_only:
            rows = [row for row in rows if _relation_is_effective(row)]
        return [self._operator_response(row, label_map) for row in rows]

    async def list_contacts(self, vessel_id: int, *, current_only: bool = True) -> list[VesselContactResponse]:
        await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        rows = await self.repo.list_by_profile(VesselContact, vessel_id)
        if current_only:
            rows = [row for row in rows if _relation_is_effective(row)]
        return [self._contact_response(row, label_map) for row in rows]

    async def list_crew(self, vessel_id: int, *, current_only: bool = True) -> list[VesselCrewResponse]:
        await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        rows = await self.repo.list_by_profile(VesselCrewAssignment, vessel_id)
        if current_only:
            rows = [row for row in rows if _relation_is_effective(row)]
        return [self._crew_response(row, label_map) for row in rows]

    async def list_person_certificates(self, vessel_id: int) -> list[VesselPersonCertificateResponse]:
        await self._require_profile(vessel_id)
        return await self._person_certificates_with_files(vessel_id)

    async def _assert_replace_initialization_allowed(self, model: type[Any], vessel_id: int, resource_name: str) -> None:
        existing = await self.db.scalar(select(model.id).where(model.vessel_profile_id == vessel_id).limit(1))  # type: ignore[attr-defined]
        if existing is not None:
            raise ConflictError(
                f"{resource_name} 整组覆盖接口已废弃：仅允许空数据初始化，已有数据请使用增量新增/修改/结束/作废接口",
                code="REPLACE_API_DEPRECATED_UNSAFE",
                detail={"resource": resource_name},
            )

    def _raise_replace_gone(self, resource_name: str) -> None:
        raise AppException(
            status_code=410,
            code="REPLACE_API_GONE",
            message=f"{resource_name} 整组覆盖接口已退出 Round 2；请使用增量新增、修改、结束或作废接口",
            detail={"resource": resource_name},
        )

    async def upsert_registration(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselRegistrationResponse:
        await self._require_profile(vessel_id)
        before = await self.repo.get_one_by_profile(VesselRegistrationInfo, vessel_id)
        row = await self.repo.upsert_one_by_profile(VesselRegistrationInfo, vessel_id, payload.model_dump(exclude_none=True))
        profile_updates: dict[str, Any] = {}
        if row.registry_city_code:
            profile_updates["registry_city_code"] = row.registry_city_code
        if row.home_port_code:
            profile_updates["home_port_code"] = row.home_port_code
        if row.home_port_name:
            profile_updates["home_port_name"] = row.home_port_name
        if profile_updates:
            await self.repo.update_profile(vessel_id, profile_updates)
        await self._add_change_event(vessel_id, "UPSERT_REGISTRATION", "维护船籍信息", _row_dict(before) if before else None, _row_dict(row), operator_id)
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        return VesselRegistrationResponse(**_row_dict(row))

    async def upsert_capacity(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselCapacityResponse:
        await self._require_profile(vessel_id)
        row = await self.repo.upsert_one_by_profile(VesselCapacityDimension, vessel_id, payload.model_dump(exclude_none=True))
        await self._add_change_event(vessel_id, "UPSERT_CAPACITY", "维护船舶尺寸信息", None, _row_dict(row), operator_id)
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        return VesselCapacityResponse(**_row_dict(row))

    async def upsert_build_info(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselBuildInfoResponse:
        await self._require_profile(vessel_id)
        row = await self.repo.upsert_one_by_profile(VesselBuildInfo, vessel_id, payload.model_dump(exclude_none=True))
        await self._add_change_event(vessel_id, "UPSERT_BUILD_INFO", "维护建造信息", None, _row_dict(row), operator_id)
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        return VesselBuildInfoResponse(**_row_dict(row))

    async def replace_owners(self, vessel_id: int, payload, *, operator_id: int | None = None) -> list[VesselOwnerResponse]:
        await self._require_profile(vessel_id)
        _ = payload, operator_id
        self._raise_replace_gone("owners")

    async def upload_owner_document(
        self,
        vessel_id: int,
        owner_id: int,
        file: UploadFile,
        *,
        document_type_code: str,
        operator_id: int | None = None,
    ) -> VesselOwnerDocumentResponse:
        await self._require_profile(vessel_id)
        owner = await self.db.get(VesselOwnerPeriod, owner_id)
        if owner is None or owner.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselOwnerPeriod", owner_id)
        row = await self._store_owner_document(
            vessel_id,
            owner_id,
            file,
            document_type_code=document_type_code,
            operator_id=operator_id,
        )
        recognition = None
        if row.content_type.lower().startswith("image/") and document_type_code in IMAGE_RECOGNIZABLE_OWNER_DOCUMENT_TYPES:
            recognition = await self._create_owner_document_image_recognition_record(
                vessel_id,
                owner_id,
                row.id,
                row.storage_file_id,
                operator_id=operator_id,
            )
        await self.db.commit()
        if recognition is not None:
            await self._dispatch_owner_document_recognition_or_fail(recognition)
        label_map = await _load_label_map(self.db)
        latest = await self._latest_owner_document_recognition(row.id)
        return self._owner_document_response(
            row,
            label_map,
            latest_recognition=latest,
            current_recognition=latest if latest is not None and latest.status_code in CURRENT_RECOGNITION_STATUSES else None,
            latest_confirmed_recognition=latest if latest is not None and latest.status_code == "CONFIRMED" else None,
            has_recognition_history=latest is not None,
        )

    async def void_owner_document(
        self,
        vessel_id: int,
        owner_id: int,
        owner_document_id: int,
        *,
        reason: str | None = None,
        operator_id: int | None = None,
    ) -> None:
        owner = await self.db.get(VesselOwnerPeriod, owner_id)
        if owner is None or owner.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselOwnerPeriod", owner_id)
        document = await self.repo.get_owner_document(owner_document_id)
        if document is None or document.vessel_owner_period_id != owner_id or document.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselOwnerDocument", owner_document_id)
        before = _row_dict(document)
        document.voided_at = datetime.utcnow()
        document.voided_by = operator_id
        document.void_reason = reason or "所有方证照作废"
        await self._add_change_event(vessel_id, "VOID_OWNER_DOCUMENT", "作废所有方证照", before, _row_dict(document), operator_id)
        await self.db.commit()

    async def confirm_owner_document_image_recognition(
        self,
        vessel_id: int,
        owner_id: int,
        owner_document_id: int,
        recognition_id: int,
        payload,
        *,
        operator_id: int | None = None,
    ) -> VesselOwnerResponse:
        return await self.adopt_owner_document_recognition(
            vessel_id,
            owner_id,
            owner_document_id,
            recognition_id,
            payload,
            operator_id=operator_id,
        )
        owner = await self.db.get(VesselOwnerPeriod, owner_id)
        if owner is None or owner.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselOwnerPeriod", owner_id)
        document = await self.repo.get_owner_document(owner_document_id)
        if document is None or document.vessel_owner_period_id != owner_id or document.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselOwnerDocument", owner_document_id)
        recognition = await self.repo.get_owner_document_image_recognition(recognition_id)
        if (
            recognition is None
            or recognition.vessel_profile_id != vessel_id
            or recognition.vessel_owner_period_id != owner_id
            or recognition.owner_document_id != owner_document_id
        ):
            raise NotFoundError("VesselOwnerDocumentImageRecognition", recognition_id)
        accepted = self._normalize_recognition_payload(payload.accepted_payload_json or recognition.candidate_payload_json or {})
        updates: dict[str, Any] = {}
        owner_name_conflict: dict[str, Any] | None = None
        if payload.apply_to_owner:
            party_name = accepted.get("holder_name") or accepted.get("company_name") or accepted.get("party_name")
            certificate_no = accepted.get("certificate_no") or accepted.get("document_no") or accepted.get("license_no")
            address = accepted.get("address")
            if party_name:
                recognized_name = str(party_name).strip()
                if recognized_name and recognized_name != owner.party_name:
                    owner_name_conflict = {
                        "current_party_name": owner.party_name,
                        "recognized_party_name": recognized_name,
                        "message": "识别名称与当前所有方不一致，请通过所有方变更流程处理",
                    }
                    accepted["owner_name_conflict"] = owner_name_conflict
            if certificate_no:
                updates["certificate_no"] = str(certificate_no).strip()
            if address:
                updates["address"] = str(address).strip()
            for key, value in updates.items():
                setattr(owner, key, value)
        recognition.status_code = "CONFIRMED"
        recognition.confirmed_payload_json = accepted
        recognition.confirmed_by = operator_id
        recognition.confirmed_at = datetime.utcnow()
        await self._add_change_event(
            vessel_id,
            "CONFIRM_OWNER_DOCUMENT_IMAGE_RECOGNITION",
            "确认所有方证照识别",
            None,
            {"recognition_id": recognition.id, "owner_updates": updates, "owner_name_conflict": owner_name_conflict},
            operator_id,
        )
        await self.db.commit()
        label_map = await _load_label_map(self.db)
        docs = await self._owner_documents_by_owner(vessel_id, label_map)
        return self._owner_response(owner, label_map, documents=docs.get(owner.id, []))

    async def replace_operators(self, vessel_id: int, payload, *, operator_id: int | None = None) -> list[VesselOperatorResponse]:
        await self._require_profile(vessel_id)
        _ = payload, operator_id
        self._raise_replace_gone("operators")

    async def replace_contacts(self, vessel_id: int, payload, *, operator_id: int | None = None) -> list[VesselContactResponse]:
        await self._require_profile(vessel_id)
        _ = payload, operator_id
        self._raise_replace_gone("contacts")

    async def replace_crew(self, vessel_id: int, payload, *, operator_id: int | None = None) -> list[VesselCrewResponse]:
        await self._require_profile(vessel_id)
        _ = payload, operator_id
        self._raise_replace_gone("crew")

    async def replace_person_certificates(self, vessel_id: int, payload, *, operator_id: int | None = None) -> list[VesselPersonCertificateResponse]:
        await self._require_profile(vessel_id)
        _ = payload, operator_id
        raise AppException(
            status_code=410,
            code="REPLACE_API_GONE",
            message="人员适任证已纳入证书资产改造，不支持整组替换；请逐本新增、更新、补附件或作废",
        )

    async def create_owner(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselOwnerResponse:
        await self._require_profile(vessel_id)
        row, cancelled_ids, event_id = await self._create_relation(
            VesselOwnerPeriod,
            vessel_id,
            payload.model_dump(exclude_none=True),
            event_type_code="CREATE_OWNER",
            event_title="新增所有方关系",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        docs = await self._owner_documents_by_owner(vessel_id, label_map)
        response = self._owner_response(row, label_map, documents=docs.get(row.id, []))
        response.cancelled_primary_ids = cancelled_ids
        response.change_event_id = event_id
        return response

    async def update_owner(self, vessel_id: int, owner_id: int, payload, *, operator_id: int | None = None) -> VesselOwnerResponse:
        row, event_id = await self._update_relation(
            VesselOwnerPeriod,
            vessel_id,
            owner_id,
            payload,
            event_type_code="UPDATE_OWNER",
            event_title="更新所有方关系",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        docs = await self._owner_documents_by_owner(vessel_id, label_map)
        response = self._owner_response(row, label_map, documents=docs.get(row.id, []))
        response.change_event_id = event_id
        return response

    async def end_owner(self, vessel_id: int, owner_id: int, payload, *, operator_id: int | None = None) -> VesselOwnerResponse:
        row, event_id = await self._end_relation(
            VesselOwnerPeriod,
            vessel_id,
            owner_id,
            payload,
            event_type_code="END_OWNER",
            event_title="结束所有方关系",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._owner_response(row, label_map)
        response.change_event_id = event_id
        return response

    async def void_owner(self, vessel_id: int, owner_id: int, payload, *, operator_id: int | None = None) -> VesselOwnerResponse:
        row, event_id = await self._void_relation(
            VesselOwnerPeriod,
            vessel_id,
            owner_id,
            payload,
            event_type_code="VOID_OWNER",
            event_title="作废所有方关系",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._owner_response(row, label_map)
        response.change_event_id = event_id
        return response

    async def set_primary_owner(self, vessel_id: int, owner_id: int, payload, *, operator_id: int | None = None) -> VesselOwnerResponse:
        row, cancelled_ids, event_id = await self._set_primary_relation(
            VesselOwnerPeriod,
            vessel_id,
            owner_id,
            payload,
            event_type_code="SET_PRIMARY_OWNER",
            event_title="设置主所有方",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        docs = await self._owner_documents_by_owner(vessel_id, label_map)
        response = self._owner_response(row, label_map, documents=docs.get(row.id, []))
        response.cancelled_primary_ids = cancelled_ids
        response.change_event_id = event_id
        return response

    async def create_operator(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselOperatorResponse:
        await self._require_profile(vessel_id)
        row, cancelled_ids, event_id = await self._create_relation(
            VesselOperatorPeriod,
            vessel_id,
            payload.model_dump(exclude_none=True),
            event_type_code="CREATE_OPERATOR",
            event_title="新增运营方关系",
            operator_id=operator_id,
        )
        await self.repo.update_profile(vessel_id, {"operation_status_code": "OPERATING"})
        await self.db.commit()
        label_map = await _load_label_map(self.db)
        response = self._operator_response(row, label_map)
        response.cancelled_primary_ids = cancelled_ids
        response.change_event_id = event_id
        return response

    async def update_operator(self, vessel_id: int, operator_period_id: int, payload, *, operator_id: int | None = None) -> VesselOperatorResponse:
        row, event_id = await self._update_relation(
            VesselOperatorPeriod,
            vessel_id,
            operator_period_id,
            payload,
            event_type_code="UPDATE_OPERATOR",
            event_title="更新运营方关系",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._operator_response(row, label_map)
        response.change_event_id = event_id
        return response

    async def end_operator(self, vessel_id: int, operator_period_id: int, payload, *, operator_id: int | None = None) -> VesselOperatorResponse:
        row, event_id = await self._end_relation(
            VesselOperatorPeriod,
            vessel_id,
            operator_period_id,
            payload,
            event_type_code="END_OPERATOR",
            event_title="结束运营方关系",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._operator_response(row, label_map)
        response.change_event_id = event_id
        return response

    async def void_operator(self, vessel_id: int, operator_period_id: int, payload, *, operator_id: int | None = None) -> VesselOperatorResponse:
        row, event_id = await self._void_relation(
            VesselOperatorPeriod,
            vessel_id,
            operator_period_id,
            payload,
            event_type_code="VOID_OPERATOR",
            event_title="作废运营方关系",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._operator_response(row, label_map)
        response.change_event_id = event_id
        return response

    async def set_primary_operator(self, vessel_id: int, operator_period_id: int, payload, *, operator_id: int | None = None) -> VesselOperatorResponse:
        row, cancelled_ids, event_id = await self._set_primary_relation(
            VesselOperatorPeriod,
            vessel_id,
            operator_period_id,
            payload,
            event_type_code="SET_PRIMARY_OPERATOR",
            event_title="设置主运营方",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._operator_response(row, label_map)
        response.cancelled_primary_ids = cancelled_ids
        response.change_event_id = event_id
        return response

    async def create_contact(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselContactResponse:
        await self._require_profile(vessel_id)
        row, cancelled_ids, event_id = await self._create_relation(
            VesselContact,
            vessel_id,
            payload.model_dump(exclude_none=True),
            event_type_code="CREATE_CONTACT",
            event_title="新增联系人",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._contact_response(row, label_map)
        response.cancelled_primary_ids = cancelled_ids
        response.change_event_id = event_id
        return response

    async def update_contact(self, vessel_id: int, contact_id: int, payload, *, operator_id: int | None = None) -> VesselContactResponse:
        row, event_id = await self._update_relation(
            VesselContact,
            vessel_id,
            contact_id,
            payload,
            event_type_code="UPDATE_CONTACT",
            event_title="更新联系人",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._contact_response(row, label_map)
        response.change_event_id = event_id
        return response

    async def end_contact(self, vessel_id: int, contact_id: int, payload, *, operator_id: int | None = None) -> VesselContactResponse:
        row, event_id = await self._end_relation(
            VesselContact,
            vessel_id,
            contact_id,
            payload,
            event_type_code="END_CONTACT",
            event_title="结束联系人",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._contact_response(row, label_map)
        response.change_event_id = event_id
        return response

    async def void_contact(self, vessel_id: int, contact_id: int, payload, *, operator_id: int | None = None) -> VesselContactResponse:
        row, event_id = await self._void_relation(
            VesselContact,
            vessel_id,
            contact_id,
            payload,
            event_type_code="VOID_CONTACT",
            event_title="作废联系人",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._contact_response(row, label_map)
        response.change_event_id = event_id
        return response

    async def set_primary_contact(self, vessel_id: int, contact_id: int, payload, *, operator_id: int | None = None) -> VesselContactResponse:
        row, cancelled_ids, event_id = await self._set_primary_relation(
            VesselContact,
            vessel_id,
            contact_id,
            payload,
            event_type_code="SET_PRIMARY_CONTACT",
            event_title="设置主联系人",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._contact_response(row, label_map)
        response.cancelled_primary_ids = cancelled_ids
        response.change_event_id = event_id
        return response

    async def create_crew(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselCrewResponse:
        await self._require_profile(vessel_id)
        data = payload.model_dump(exclude_none=True)
        data.pop("id", None)
        row, _, event_id = await self._create_relation(
            VesselCrewAssignment,
            vessel_id,
            data,
            event_type_code="CREATE_CREW",
            event_title="新增船员任职",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._crew_response(row, label_map)
        response.change_event_id = event_id
        return response

    async def update_crew(self, vessel_id: int, crew_id: int, payload, *, operator_id: int | None = None) -> VesselCrewResponse:
        row, event_id = await self._update_relation(
            VesselCrewAssignment,
            vessel_id,
            crew_id,
            payload,
            event_type_code="UPDATE_CREW",
            event_title="更新船员任职",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._crew_response(row, label_map)
        response.change_event_id = event_id
        return response

    async def end_crew(self, vessel_id: int, crew_id: int, payload, *, operator_id: int | None = None) -> VesselCrewResponse:
        row, event_id = await self._end_relation(
            VesselCrewAssignment,
            vessel_id,
            crew_id,
            payload,
            event_type_code="END_CREW",
            event_title="结束船员任职",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._crew_response(row, label_map)
        response.change_event_id = event_id
        return response

    async def void_crew(self, vessel_id: int, crew_id: int, payload, *, operator_id: int | None = None) -> VesselCrewResponse:
        row, event_id = await self._void_relation(
            VesselCrewAssignment,
            vessel_id,
            crew_id,
            payload,
            event_type_code="VOID_CREW",
            event_title="作废船员任职",
            operator_id=operator_id,
        )
        label_map = await _load_label_map(self.db)
        response = self._crew_response(row, label_map)
        response.change_event_id = event_id
        return response

    async def create_person_certificate(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselPersonCertificateResponse:
        await self._require_profile(vessel_id)
        data = payload.model_dump(exclude_none=True)
        data.pop("revision", None)
        crew = await self._require_crew_assignment(vessel_id, data.get("crew_assignment_id"))
        data["crew_assignment_id"] = crew.id
        data["holder_name"] = data.get("holder_name") or crew.crew_name
        data["certificate_type_code"] = CREW_CERTIFICATE_TYPE
        data.setdefault("verify_status_code", "PENDING")
        data.setdefault("revision", 1)
        data.setdefault("source_type_code", "MANUAL")
        row = await self.repo.create_person_certificate(vessel_id, data)
        event_id = await self._add_change_event(
            vessel_id,
            "CREATE_PERSON_CERTIFICATE",
            "新增人员证件",
            None,
            _row_dict(row),
            operator_id,
            object_type="vessel_person_certificate",
            object_id=row.id,
        )
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        response = (await self._person_certificates_with_files(vessel_id, person_certificate_id=row.id))[0]
        response.change_event_id = event_id
        return response

    async def update_person_certificate(
        self,
        vessel_id: int,
        person_certificate_id: int,
        payload,
        *,
        operator_id: int | None = None,
    ) -> VesselPersonCertificateResponse:
        cert = await self.repo.get_person_certificate(person_certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselPersonCertificate", person_certificate_id)
        before = _row_dict(cert)
        updates = payload.model_dump(exclude_none=True)
        revision = updates.pop("revision", None)
        self._ensure_revision(cert, revision)
        if not updates:
            raise ValidationError("no update fields provided")
        if "crew_assignment_id" in updates:
            crew = await self._require_crew_assignment(vessel_id, updates["crew_assignment_id"])
            updates["holder_name"] = updates.get("holder_name") or crew.crew_name
        elif cert.crew_assignment_id is None:
            raise ValidationError("人员适任证必须绑定当前船员任职")
        if "certificate_type_code" in updates:
            updates["certificate_type_code"] = CREW_CERTIFICATE_TYPE
        updates["revision"] = int(cert.revision or 1) + 1
        row = await self.repo.update_person_certificate(person_certificate_id, updates)
        assert row is not None
        event_id = await self._add_change_event(
            vessel_id,
            "UPDATE_PERSON_CERTIFICATE",
            "更新人员证件",
            before,
            _row_dict(row),
            operator_id,
            object_type="vessel_person_certificate",
            object_id=row.id,
        )
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        response = (await self._person_certificates_with_files(vessel_id, person_certificate_id=row.id))[0]
        response.change_event_id = event_id
        return response

    async def delete_person_certificate(
        self,
        vessel_id: int,
        person_certificate_id: int,
        *,
        reason: str | None = None,
        revision: int | None = None,
        operator_id: int | None = None,
    ) -> None:
        cert = await self.repo.get_person_certificate(person_certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselPersonCertificate", person_certificate_id)
        if revision is not None:
            self._ensure_revision(cert, revision)
        before = _row_dict(cert)
        now = datetime.utcnow()
        cert.voided_at = now
        cert.voided_by = operator_id
        cert.void_reason = reason or "人员适任证作废"
        cert.verify_status_code = "VOIDED"
        cert.revision = int(cert.revision or 1) + 1
        await self._add_change_event(
            vessel_id,
            "VOID_PERSON_CERTIFICATE",
            "作废人员适任证",
            before,
            _row_dict(cert),
            operator_id,
            object_type="vessel_person_certificate",
            object_id=cert.id,
            reason=reason,
        )
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)

    async def upload_person_certificate_file_first(
        self,
        vessel_id: int,
        file: UploadFile,
        *,
        crew_assignment_id: int,
        certificate_type_code: str = "CREW_COMPETENCY_CERT",
        operator_id: int | None = None,
    ) -> VesselPersonCertificateResponse:
        await self._require_profile(vessel_id)
        crew = await self._require_crew_assignment(vessel_id, crew_assignment_id)
        cert = await self.repo.create_person_certificate(
            vessel_id,
            {
                "crew_assignment_id": crew.id,
                "holder_name": crew.crew_name,
                "certificate_type_code": CREW_CERTIFICATE_TYPE,
                "verify_status_code": "PENDING",
                "remark": "由船员适任证附件上传创建，待识别或人工补录",
            },
        )
        file_row = await self._store_person_certificate_file(vessel_id, cert.id, file, operator_id=operator_id)
        recognition = None
        if file_row.content_type.lower().startswith("image/"):
            recognition = await self._create_person_image_recognition_record(
                vessel_id,
                cert.id,
                file_row.id,
                file_row.storage_file_id,
                operator_id=operator_id,
            )
        await self._add_change_event(vessel_id, "CREATE_PERSON_CERTIFICATE", "上传附件创建船员适任证草稿", None, _row_dict(cert), operator_id)
        await self.db.commit()
        if recognition is not None:
            await self._dispatch_person_recognition_or_fail(recognition)
        return (await self._person_certificates_with_files(vessel_id, person_certificate_id=cert.id))[0]

    async def upload_person_certificate_file(
        self,
        vessel_id: int,
        person_certificate_id: int,
        file: UploadFile,
        *,
        operator_id: int | None = None,
    ) -> VesselPersonCertificateFileResponse:
        await self._require_profile(vessel_id)
        cert = await self.repo.get_person_certificate(person_certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselPersonCertificate", person_certificate_id)
        row = await self._store_person_certificate_file(vessel_id, person_certificate_id, file, operator_id=operator_id)
        await self.db.commit()
        if row.content_type.lower().startswith("image/"):
            recognition = await self._create_person_image_recognition_record(
                vessel_id,
                person_certificate_id,
                row.id,
                row.storage_file_id,
                operator_id=operator_id,
            )
            await self.db.commit()
            await self._dispatch_person_recognition_or_fail(recognition)
        return self._person_file_response(row)

    async def void_person_certificate_file(
        self,
        vessel_id: int,
        person_certificate_id: int,
        file_id: int,
        *,
        reason: str | None = None,
        operator_id: int | None = None,
    ) -> None:
        cert = await self.repo.get_person_certificate(person_certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselPersonCertificate", person_certificate_id)
        row = await self.db.scalar(
            select(VesselPersonCertificateFile).where(
                VesselPersonCertificateFile.id == file_id,
                VesselPersonCertificateFile.vessel_person_certificate_id == person_certificate_id,
            )
        )
        if row is None:
            raise NotFoundError("VesselPersonCertificateFile", file_id)
        before = _row_dict(row)
        row.voided_at = datetime.utcnow()
        row.voided_by = operator_id
        row.void_reason = reason or "船员适任证附件作废"
        await self._add_change_event(vessel_id, "VOID_PERSON_CERTIFICATE_FILE", "作废船员适任证附件", before, _row_dict(row), operator_id)
        await self.db.commit()

    async def create_person_certificate_image_recognition(
        self,
        vessel_id: int,
        person_certificate_id: int,
        payload,
        *,
        operator_id: int | None = None,
    ) -> VesselPersonCertificateImageRecognitionResponse:
        await self._require_profile(vessel_id)
        cert = await self.repo.get_person_certificate(person_certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselPersonCertificate", person_certificate_id)
        cert_file = await self.repo.get_person_certificate_file_by_storage_file(person_certificate_id, payload.file_id)
        if cert_file is None:
            raise NotFoundError("VesselPersonCertificateFile", payload.file_id)
        if not (cert_file.content_type or "").lower().startswith("image/"):
            raise ValidationError("图片识别助手仅支持图片附件，PDF 可归档预览但不能识别")

        await self.db.commit()
        recognition = await self._create_person_image_recognition_record(
            vessel_id,
            person_certificate_id,
            cert_file.id,
            payload.file_id,
            operator_id=operator_id,
        )
        await self.db.commit()
        await self._dispatch_person_recognition_or_fail(recognition)
        await self.db.refresh(recognition)
        label_map = await _load_label_map(self.db)
        return self._person_image_recognition_response(recognition, label_map)

    async def confirm_person_certificate_image_recognition(
        self,
        vessel_id: int,
        person_certificate_id: int,
        recognition_id: int,
        payload,
        *,
        operator_id: int | None = None,
    ) -> VesselPersonCertificateResponse:
        return await self.adopt_person_certificate_recognition(
            vessel_id,
            person_certificate_id,
            recognition_id,
            payload,
            operator_id=operator_id,
        )
        await self._require_profile(vessel_id)
        cert = await self.repo.get_person_certificate(person_certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselPersonCertificate", person_certificate_id)
        recognition = await self.repo.get_person_image_recognition(recognition_id)
        if (
            recognition is None
            or recognition.vessel_profile_id != vessel_id
            or recognition.vessel_person_certificate_id != person_certificate_id
        ):
            raise NotFoundError("VesselPersonCertificateImageRecognition", recognition_id)
        accepted = self._normalize_recognition_payload(
            payload.accepted_payload_json or recognition.candidate_payload_json or {}
        )
        if not accepted:
            raise ValidationError("没有可确认的识别结果")

        before = _row_dict(cert)
        updates = self._person_certificate_updates_from_recognition(accepted)
        if updates:
            updates["structured_payload_json"] = accepted
            updates["verify_status_code"] = "VERIFIED"
            await self.repo.update_person_certificate(person_certificate_id, updates)
        recognition.status_code = "CONFIRMED"
        recognition.confirmed_payload_json = accepted
        recognition.confirmed_by = operator_id
        recognition.confirmed_at = datetime.utcnow()
        await self._add_change_event(
            vessel_id,
            "CONFIRM_PERSON_CERTIFICATE_IMAGE_RECOGNITION",
            "确认人员证件图片识别结果",
            before,
            {"recognition_id": recognition.id, "certificate_updates": updates},
            operator_id,
        )
        await self.db.flush()
        await self.db.commit()
        return (await self._person_certificates_with_files(vessel_id, person_certificate_id=person_certificate_id))[0]

    async def list_certificates(self, vessel_id: int) -> list[VesselCertificateResponse]:
        await self._require_profile(vessel_id)
        return await self._certificates_with_files(vessel_id)

    async def list_certificate_image_recognitions(
        self,
        vessel_id: int,
        certificate_id: int,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> PageResponse[VesselCertificateImageRecognitionResponse]:
        cert = await self.repo.get_certificate(certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselCertificate", certificate_id)
        page_size = min(max(page_size, 1), 100)
        page = max(page, 1)
        filters = (
            VesselCertificateImageRecognition.vessel_profile_id == vessel_id,
            VesselCertificateImageRecognition.vessel_certificate_id == certificate_id,
        )
        total = int(await self.db.scalar(select(func.count()).select_from(VesselCertificateImageRecognition).where(*filters)) or 0)
        rows = (
            await self.db.execute(
                select(VesselCertificateImageRecognition)
                .where(*filters)
                .order_by(VesselCertificateImageRecognition.created_at.desc(), VesselCertificateImageRecognition.id.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        ).scalars().all()
        label_map = await _load_label_map(self.db)
        return PageResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[self._image_recognition_response(row, label_map) for row in rows],
        )

    async def list_person_certificate_image_recognitions(
        self,
        vessel_id: int,
        person_certificate_id: int,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> PageResponse[VesselPersonCertificateImageRecognitionResponse]:
        cert = await self.repo.get_person_certificate(person_certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselPersonCertificate", person_certificate_id)
        page_size = min(max(page_size, 1), 100)
        page = max(page, 1)
        filters = (
            VesselPersonCertificateImageRecognition.vessel_profile_id == vessel_id,
            VesselPersonCertificateImageRecognition.vessel_person_certificate_id == person_certificate_id,
        )
        total = int(await self.db.scalar(select(func.count()).select_from(VesselPersonCertificateImageRecognition).where(*filters)) or 0)
        rows = (
            await self.db.execute(
                select(VesselPersonCertificateImageRecognition)
                .where(*filters)
                .order_by(VesselPersonCertificateImageRecognition.created_at.desc(), VesselPersonCertificateImageRecognition.id.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        ).scalars().all()
        label_map = await _load_label_map(self.db)
        return PageResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[self._person_image_recognition_response(row, label_map) for row in rows],
        )

    async def list_owner_document_image_recognitions(
        self,
        vessel_id: int,
        owner_id: int,
        owner_document_id: int,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> PageResponse[VesselOwnerDocumentImageRecognitionResponse]:
        owner = await self.db.scalar(
            select(VesselOwnerPeriod).where(VesselOwnerPeriod.id == owner_id)
        )
        if owner is None or owner.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselOwnerPeriod", owner_id)
        document = await self.repo.get_owner_document(owner_document_id)
        if document is None or document.vessel_profile_id != vessel_id or document.vessel_owner_period_id != owner_id:
            raise NotFoundError("VesselOwnerDocument", owner_document_id)
        page_size = min(max(page_size, 1), 100)
        page = max(page, 1)
        filters = (
            VesselOwnerDocumentImageRecognition.vessel_profile_id == vessel_id,
            VesselOwnerDocumentImageRecognition.vessel_owner_period_id == owner_id,
            VesselOwnerDocumentImageRecognition.owner_document_id == owner_document_id,
        )
        total = int(await self.db.scalar(select(func.count()).select_from(VesselOwnerDocumentImageRecognition).where(*filters)) or 0)
        rows = (
            await self.db.execute(
                select(VesselOwnerDocumentImageRecognition)
                .where(*filters)
                .order_by(VesselOwnerDocumentImageRecognition.created_at.desc(), VesselOwnerDocumentImageRecognition.id.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        ).scalars().all()
        label_map = await _load_label_map(self.db)
        return PageResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[self._owner_document_image_recognition_response(row, label_map) for row in rows],
        )

    async def get_certificate_ledger(self, vessel_id: int) -> list[VesselCertificateLedgerItemResponse]:
        await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        certs = await self._certificates_with_files(vessel_id, label_map=label_map)
        by_type: dict[str, VesselCertificateResponse] = {}
        for cert in certs:
            by_type.setdefault(cert.certificate_type_code, cert)
        return [
            VesselCertificateLedgerItemResponse(
                certificate_type_code=code,
                certificate_type_name=label_map.get("VESSEL_CERTIFICATE_TYPE", {}).get(code),
                required=True,
                status_code=self._certificate_ledger_status(by_type.get(code)),
                status_name=self._certificate_ledger_status_name(self._certificate_ledger_status(by_type.get(code))),
                certificate=by_type.get(code),
            )
            for code in REQUIRED_VESSEL_CERTIFICATE_TYPES
        ]

    async def create_certificate(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselCertificateResponse:
        await self._require_profile(vessel_id)
        data = payload.model_dump(exclude_none=True)
        self._validate_vessel_certificate_type(data.get("certificate_type_code"))
        row = await self.repo.create_certificate(vessel_id, data)
        await self._add_change_event(vessel_id, "CREATE_CERTIFICATE", "新增船舶证件", None, _row_dict(row), operator_id)
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        await self._refresh_summary_best_effort(vessel_id)
        return (await self._certificates_with_files(vessel_id, certificate_id=row.id))[0]

    async def update_certificate(self, vessel_id: int, certificate_id: int, payload, *, operator_id: int | None = None) -> VesselCertificateResponse:
        cert = await self.repo.get_certificate(certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselCertificate", certificate_id)
        before = _row_dict(cert)
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        if "certificate_type_code" in updates:
            self._validate_vessel_certificate_type(updates.get("certificate_type_code"))
        row = await self.repo.update_certificate(certificate_id, updates)
        assert row is not None
        await self._add_change_event(row.vessel_profile_id, "UPDATE_CERTIFICATE", "更新船舶证件", before, _row_dict(row), operator_id)
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        await self._refresh_summary_best_effort(vessel_id)
        return (await self._certificates_with_files(row.vessel_profile_id, certificate_id=row.id))[0]

    async def void_certificate(
        self,
        vessel_id: int,
        certificate_id: int,
        *,
        reason: str | None = None,
        operator_id: int | None = None,
    ) -> None:
        cert = await self.repo.get_certificate(certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselCertificate", certificate_id)
        before = _row_dict(cert)
        cert.voided_at = datetime.utcnow()
        cert.voided_by = operator_id
        cert.void_reason = reason or "船舶证书作废"
        cert.verify_status_code = "VOIDED"
        await self._add_change_event(vessel_id, "VOID_CERTIFICATE", "作废船舶证书", before, _row_dict(cert), operator_id)
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        await self._refresh_summary_best_effort(vessel_id)

    async def upload_certificate_file_first(
        self,
        vessel_id: int,
        file: UploadFile,
        *,
        certificate_type_code: str = "UNKNOWN",
        operator_id: int | None = None,
    ) -> VesselCertificateResponse:
        await self._require_profile(vessel_id)
        self._validate_vessel_certificate_type(certificate_type_code)
        cert = await self.repo.create_certificate(
            vessel_id,
            {
                "certificate_type_code": certificate_type_code or "UNKNOWN",
                "verify_status_code": "PENDING",
                "remark": "由附件上传创建，待识别或人工补录",
            },
        )
        file_row = await self._store_certificate_file(vessel_id, cert.id, file, operator_id=operator_id)
        recognition = None
        if file_row.content_type.lower().startswith("image/"):
            recognition = await self._create_certificate_image_recognition_record(
                vessel_id,
                cert.id,
                file_row.id,
                file_row.storage_file_id,
                operator_id=operator_id,
            )
        await self._add_change_event(vessel_id, "CREATE_CERTIFICATE", "上传附件创建证件草稿", None, _row_dict(cert), operator_id)
        await self.db.commit()
        if recognition is not None:
            await self._dispatch_certificate_recognition_or_fail(recognition)
        return (await self._certificates_with_files(vessel_id, certificate_id=cert.id))[0]

    async def upload_certificate_file(
        self,
        vessel_id: int,
        certificate_id: int,
        file: UploadFile,
        *,
        operator_id: int | None = None,
    ) -> VesselCertificateFileResponse:
        await self._require_profile(vessel_id)
        cert = await self.repo.get_certificate(certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselCertificate", certificate_id)
        row = await self._store_certificate_file(vessel_id, certificate_id, file, operator_id=operator_id)
        await self.db.commit()
        if row.content_type.lower().startswith("image/"):
            recognition = await self._create_certificate_image_recognition_record(
                vessel_id,
                certificate_id,
                row.id,
                row.storage_file_id,
                operator_id=operator_id,
            )
            await self.db.commit()
            await self._dispatch_certificate_recognition_or_fail(recognition)
        return self._file_response(row)

    async def void_certificate_file(
        self,
        vessel_id: int,
        certificate_id: int,
        file_id: int,
        *,
        reason: str | None = None,
        operator_id: int | None = None,
    ) -> None:
        cert = await self.repo.get_certificate(certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselCertificate", certificate_id)
        row = await self.db.scalar(
            select(VesselCertificateFile).where(
                VesselCertificateFile.id == file_id,
                VesselCertificateFile.vessel_certificate_id == certificate_id,
            )
        )
        if row is None:
            raise NotFoundError("VesselCertificateFile", file_id)
        before = _row_dict(row)
        row.voided_at = datetime.utcnow()
        row.voided_by = operator_id
        row.void_reason = reason or "船舶证书附件作废"
        await self._add_change_event(vessel_id, "VOID_CERTIFICATE_FILE", "作废船舶证书附件", before, _row_dict(row), operator_id)
        await self.db.commit()

    async def create_certificate_image_recognition(
        self,
        vessel_id: int,
        certificate_id: int,
        payload,
        *,
        operator_id: int | None = None,
    ) -> VesselCertificateImageRecognitionResponse:
        await self._require_profile(vessel_id)
        cert = await self.repo.get_certificate(certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselCertificate", certificate_id)
        cert_file = await self.repo.get_certificate_file_by_storage_file(certificate_id, payload.file_id)
        if cert_file is None:
            raise NotFoundError("VesselCertificateFile", payload.file_id)
        if not (cert_file.content_type or "").lower().startswith("image/"):
            raise ValidationError("图片识别助手仅支持图片附件，PDF 可归档预览但不能识别")

        await self.db.commit()
        recognition = await self._create_certificate_image_recognition_record(
            vessel_id,
            certificate_id,
            cert_file.id,
            payload.file_id,
            operator_id=operator_id,
        )
        await self.db.commit()
        await self._dispatch_certificate_recognition_or_fail(recognition)
        await self.db.refresh(recognition)
        label_map = await _load_label_map(self.db)
        return self._image_recognition_response(recognition, label_map)

    async def confirm_certificate_image_recognition(
        self,
        vessel_id: int,
        certificate_id: int,
        recognition_id: int,
        payload,
        *,
        operator_id: int | None = None,
    ) -> VesselCertificateResponse:
        return await self.adopt_certificate_recognition(
            vessel_id,
            certificate_id,
            recognition_id,
            payload,
            operator_id=operator_id,
        )
        await self._require_profile(vessel_id)
        cert = await self.repo.get_certificate(certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselCertificate", certificate_id)
        recognition = await self.repo.get_image_recognition(recognition_id)
        if (
            recognition is None
            or recognition.vessel_profile_id != vessel_id
            or recognition.vessel_certificate_id != certificate_id
        ):
            raise NotFoundError("VesselCertificateImageRecognition", recognition_id)
        accepted = self._normalize_recognition_payload(payload.accepted_payload_json or recognition.candidate_payload_json or {})
        if not isinstance(accepted, dict) or not accepted:
            raise ValidationError("没有可确认的识别结果")

        before_cert = _row_dict(cert)
        updates = self._certificate_updates_from_recognition(accepted)
        if updates:
            updates["structured_payload_json"] = accepted
            updates["verify_status_code"] = "VERIFIED"
            await self.repo.update_certificate(certificate_id, updates)
        recognition.status_code = "CONFIRMED"
        recognition.confirmed_payload_json = accepted
        recognition.confirmed_by = operator_id
        recognition.confirmed_at = datetime.utcnow()

        profile_updates, capacity_updates = self._adoption_updates_from_recognition(
            accepted,
            payload.adopt_to_profile_fields,
        )
        if profile_updates:
            await self.repo.update_profile(vessel_id, profile_updates)
            if "ship_name" in profile_updates:
                await self.repo.add_name_history(vessel_id, profile_updates["ship_name"], source_type_code="AI_RECOGNITION")
            if "current_mmsi" in profile_updates:
                await self.repo.add_identifier_history(vessel_id, "MMSI", profile_updates["current_mmsi"], source_type_code="AI_RECOGNITION")
        if capacity_updates:
            await self.repo.upsert_one_by_profile(VesselCapacityDimension, vessel_id, capacity_updates)

        await self._add_change_event(
            vessel_id,
            "CONFIRM_CERTIFICATE_IMAGE_RECOGNITION",
            "确认证件图片识别结果",
            before_cert,
            {
                "recognition_id": recognition.id,
                "certificate_updates": updates,
                "profile_updates": profile_updates,
                "capacity_updates": capacity_updates,
            },
            operator_id,
        )
        await self.db.flush()
        await self.db.commit()
        return (await self._certificates_with_files(vessel_id, certificate_id=certificate_id))[0]

    async def owner_transfer(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselProfileResponse:
        profile = await self._require_profile(vessel_id)
        transfer_date = payload.transfer_date or date.today()
        transfer_time = datetime.utcnow()
        code = await CodeSequenceService(self.db).next_code("VESSEL_PROFILE_CODE")
        old_snapshot = _row_dict(profile)
        await self._assert_active_mmsi_available(
            profile.current_mmsi,
            exclude_vessel_id=vessel_id,
            attempted_profile_id=vessel_id,
            evidence_source="OWNER_TRANSFER",
        )
        profile.profile_status_code = "TRANSFERRED"
        existing_owners = await self.repo.list_by_profile(VesselOwnerPeriod, vessel_id)
        for owner in existing_owners:
            if owner.is_current:
                owner.is_current = False
                owner.end_date = transfer_date
                owner.is_primary = False
                owner.revision = int(owner.revision or 1) + 1
        new_profile = await self.repo.create_profile(
            {
                "vessel_identity_id": profile.vessel_identity_id,
                "ship_name": profile.ship_name,
                "ship_name_en": profile.ship_name_en,
                "current_mmsi": profile.current_mmsi,
                "ship_type_code": profile.ship_type_code,
                "operation_status_code": profile.operation_status_code,
                "home_port_code": profile.home_port_code,
                "home_port_name": profile.home_port_name,
                "registry_city_code": profile.registry_city_code,
                "business_region_id": profile.business_region_id,
                "source_type_code": profile.source_type_code,
                "vessel_profile_code": code,
                "profile_status_code": "ACTIVE",
                "identity_status_code": profile.identity_status_code,
                "audit_status": "PENDING",
                "remark": payload.remark,
            }
        )
        await self._copy_singletons(vessel_id, new_profile.id)
        await self._copy_history(vessel_id, new_profile.id)
        await self.repo.replace_many_by_profile(
            VesselOwnerPeriod,
            new_profile.id,
            [
                {
                    "party_name": payload.new_owner_name,
                    "party_type_code": payload.party_type_code,
                    "certificate_no": payload.certificate_no,
                    "address": payload.address,
                    "start_date": transfer_date,
                    "is_current": True,
                    "is_primary": True,
                }
            ],
        )
        if profile.vessel_identity_id:
            existing_links = (
                await self.db.execute(
                    select(VesselIdentityLink).where(
                        VesselIdentityLink.vessel_identity_id == profile.vessel_identity_id,
                        VesselIdentityLink.vessel_profile_id == vessel_id,
                        VesselIdentityLink.end_at.is_(None),
                    )
                )
            ).scalars().all()
            for link in existing_links:
                link.end_at = transfer_time
                link.is_primary = False
            self.db.add(
                VesselIdentityLink(
                    vessel_identity_id=profile.vessel_identity_id,
                    vessel_profile_id=new_profile.id,
                    link_type_code="OWNER_TRANSFER",
                    confidence_score=90,
                    is_primary=True,
                    start_at=transfer_time,
                )
            )
        await self._add_change_event(vessel_id, "OWNER_TRANSFER_OUT", "所有方转移出", old_snapshot, {"new_profile_id": new_profile.id}, operator_id)
        await self._add_change_event(new_profile.id, "OWNER_TRANSFER_IN", "所有方转移入", None, {"from_profile_id": vessel_id}, operator_id)
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        await self._refresh_summary_best_effort(new_profile.id)
        return await self._build_profile_response(new_profile.id)

    async def get_change_events(self, vessel_id: int) -> list[VesselChangeEventResponse]:
        await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        return [
            VesselChangeEventResponse(
                **_row_dict(row),
                event_type_name=label_map.get("VESSEL_CHANGE_EVENT_TYPE", {}).get(row.event_type_code),
            )
            for row in await self.repo.list_by_profile(VesselChangeEvent, vessel_id, order_desc=True)
        ]

    async def _store_certificate_file(
        self,
        vessel_id: int,
        certificate_id: int,
        file: UploadFile,
        *,
        operator_id: int | None,
    ) -> VesselCertificateFile:
        storage_file = await FileStorageService(self.db).upload_file(
            file=file,
            object_prefix=f"vessels/{vessel_id}/certificates/{certificate_id}",
            uploaded_by=operator_id,
            allowed_content_types={"application/pdf", "image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"},
        )
        now = datetime.utcnow()
        row = await self.repo.create_certificate_file(
            {
                "vessel_certificate_id": certificate_id,
                "storage_file_id": storage_file.id,
                "file_name": storage_file.original_file_name,
                "content_type": storage_file.content_type,
                "file_size": storage_file.file_size,
                "uploaded_by": operator_id,
                "uploaded_at": now,
                "created_at": now,
            }
        )
        await self._add_change_event(vessel_id, "UPLOAD_CERTIFICATE_FILE", "上传证件附件", None, _row_dict(row), operator_id)
        return row

    async def _store_person_certificate_file(
        self,
        vessel_id: int,
        person_certificate_id: int,
        file: UploadFile,
        *,
        operator_id: int | None,
    ) -> VesselPersonCertificateFile:
        storage_file = await FileStorageService(self.db).upload_file(
            file=file,
            object_prefix=f"vessels/{vessel_id}/person-certificates/{person_certificate_id}",
            uploaded_by=operator_id,
            allowed_content_types={"application/pdf", "image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"},
        )
        now = datetime.utcnow()
        row = await self.repo.create_person_certificate_file(
            {
                "vessel_person_certificate_id": person_certificate_id,
                "storage_file_id": storage_file.id,
                "file_name": storage_file.original_file_name,
                "content_type": storage_file.content_type,
                "file_size": storage_file.file_size,
                "uploaded_by": operator_id,
                "uploaded_at": now,
                "created_at": now,
            }
        )
        await self._add_change_event(vessel_id, "UPLOAD_PERSON_CERTIFICATE_FILE", "上传人员证件附件", None, _row_dict(row), operator_id)
        return row

    async def _store_owner_document(
        self,
        vessel_id: int,
        owner_id: int,
        file: UploadFile,
        *,
        document_type_code: str,
        operator_id: int | None,
    ) -> VesselOwnerDocument:
        storage_file = await FileStorageService(self.db).upload_file(
            file=file,
            object_prefix=f"vessels/{vessel_id}/owners/{owner_id}",
            uploaded_by=operator_id,
            allowed_content_types={"application/pdf", "image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"},
        )
        now = datetime.utcnow()
        row = await self.repo.create_owner_document(
            {
                "vessel_profile_id": vessel_id,
                "vessel_owner_period_id": owner_id,
                "document_type_code": document_type_code or "OTHER",
                "storage_file_id": storage_file.id,
                "file_name": storage_file.original_file_name,
                "content_type": storage_file.content_type,
                "file_size": storage_file.file_size,
                "uploaded_by": operator_id,
                "uploaded_at": now,
                "created_at": now,
            }
        )
        await self._add_change_event(vessel_id, "UPLOAD_OWNER_DOCUMENT", "上传所有方证照", None, _row_dict(row), operator_id)
        return row

    async def _create_owner_document_image_recognition_record(
        self,
        vessel_id: int,
        owner_id: int,
        owner_document_id: int,
        storage_file_id: int,
        *,
        operator_id: int | None,
    ) -> VesselOwnerDocumentImageRecognition:
        return await self.repo.create_owner_document_image_recognition(
            {
                "vessel_profile_id": vessel_id,
                "vessel_owner_period_id": owner_id,
                "owner_document_id": owner_document_id,
                "storage_file_id": storage_file_id,
                "status_code": "QUEUED",
                "created_by": operator_id,
            }
        )

    async def _create_certificate_image_recognition_record(
        self,
        vessel_id: int,
        certificate_id: int,
        certificate_file_id: int,
        storage_file_id: int,
        *,
        operator_id: int | None,
    ) -> VesselCertificateImageRecognition:
        return await self.repo.create_image_recognition(
            {
                "vessel_profile_id": vessel_id,
                "vessel_certificate_id": certificate_id,
                "certificate_file_id": certificate_file_id,
                "storage_file_id": storage_file_id,
                "status_code": "QUEUED",
                "created_by": operator_id,
            }
        )

    async def _create_person_image_recognition_record(
        self,
        vessel_id: int,
        person_certificate_id: int,
        person_certificate_file_id: int,
        storage_file_id: int,
        *,
        operator_id: int | None,
    ) -> VesselPersonCertificateImageRecognition:
        return await self.repo.create_person_image_recognition(
            {
                "vessel_profile_id": vessel_id,
                "vessel_person_certificate_id": person_certificate_id,
                "person_certificate_file_id": person_certificate_file_id,
                "storage_file_id": storage_file_id,
                "status_code": "QUEUED",
                "created_by": operator_id,
            }
        )

    async def _dispatch_certificate_recognition_or_fail(self, recognition: VesselCertificateImageRecognition) -> None:
        try:
            _dispatch_certificate_recognition_task(int(recognition.id))
        except Exception as exc:  # noqa: BLE001
            recognition.status_code = "FAILED"
            recognition.error_message = f"证件图片识别任务投递失败：{exc}"[:512]
            await self._add_change_event(
                int(recognition.vessel_profile_id),
                "IMAGE_RECOGNIZE_CERTIFICATE_FAILED",
                "证件图片识别任务投递失败",
                None,
                {"recognition_id": recognition.id, "error_message": recognition.error_message},
                recognition.created_by,
            )
            await self.db.commit()

    async def _dispatch_person_recognition_or_fail(self, recognition: VesselPersonCertificateImageRecognition) -> None:
        try:
            _dispatch_person_recognition_task(int(recognition.id))
        except Exception as exc:  # noqa: BLE001
            recognition.status_code = "FAILED"
            recognition.error_message = f"人员证件图片识别任务投递失败：{exc}"[:512]
            await self._add_change_event(
                int(recognition.vessel_profile_id),
                "IMAGE_RECOGNIZE_PERSON_CERTIFICATE_FAILED",
                "人员证件图片识别任务投递失败",
                None,
                {"recognition_id": recognition.id, "error_message": recognition.error_message},
                recognition.created_by,
            )
            await self.db.commit()

    async def _dispatch_owner_document_recognition_or_fail(self, recognition: VesselOwnerDocumentImageRecognition) -> None:
        try:
            _dispatch_owner_document_recognition_task(int(recognition.id))
        except Exception as exc:  # noqa: BLE001
            recognition.status_code = "FAILED"
            recognition.error_message = f"所有方证照图片识别任务投递失败：{exc}"[:512]
            await self._add_change_event(
                int(recognition.vessel_profile_id),
                "IMAGE_RECOGNIZE_OWNER_DOCUMENT_FAILED",
                "所有方证照图片识别任务投递失败",
                None,
                {"recognition_id": recognition.id, "error_message": recognition.error_message},
                recognition.created_by,
            )
            await self.db.commit()

    async def process_certificate_image_recognition(self, recognition_id: int) -> dict[str, Any]:
        recognition = await self.repo.get_image_recognition(recognition_id)
        if recognition is None:
            raise NotFoundError("VesselCertificateImageRecognition", recognition_id)
        try:
            recognition.status_code = "PROCESSING"
            await self.db.flush()
            storage_file, file_result = await FileStorageService(self.db).download_file(recognition.storage_file_id)
            result = await VesselCertificateImageAssistant(self.runtime_config).recognize(
                content=file_result.content,
                content_type=file_result.content_type or storage_file.content_type,
                file_name=storage_file.original_file_name,
                scenario="vessel_certificate",
            )
            recognition.status_code = "NEED_CONFIRM"
            recognition.provider_code = result.provider
            recognition.model_name = result.model
            recognition.candidate_payload_json = self._normalize_recognition_payload(result.candidate_payload)
            recognition.raw_text = result.raw_text
            recognition.raw_response_json = result.raw_response
            recognition.confidence_score = result.confidence_score
            recognition.error_message = None
            await self._add_change_event(
                recognition.vessel_profile_id,
                "IMAGE_RECOGNIZE_CERTIFICATE",
                "识别证件图片",
                None,
                {"recognition_id": recognition.id, "status_code": recognition.status_code},
                recognition.created_by,
            )
        except Exception as exc:  # noqa: BLE001
            recognition.status_code = "FAILED"
            recognition.error_message = str(exc)[:512]
            await self._add_change_event(
                recognition.vessel_profile_id,
                "IMAGE_RECOGNIZE_CERTIFICATE_FAILED",
                "证件图片识别失败",
                None,
                {"recognition_id": recognition.id, "error_message": recognition.error_message},
                recognition.created_by,
            )
        await self.db.commit()
        return {"recognition_id": recognition.id, "status_code": recognition.status_code}

    async def process_person_certificate_image_recognition(self, recognition_id: int) -> dict[str, Any]:
        recognition = await self.repo.get_person_image_recognition(recognition_id)
        if recognition is None:
            raise NotFoundError("VesselPersonCertificateImageRecognition", recognition_id)
        try:
            recognition.status_code = "PROCESSING"
            await self.db.flush()
            storage_file, file_result = await FileStorageService(self.db).download_file(recognition.storage_file_id)
            result = await VesselCertificateImageAssistant(self.runtime_config).recognize(
                content=file_result.content,
                content_type=file_result.content_type or storage_file.content_type,
                file_name=storage_file.original_file_name,
                scenario="crew_competency_certificate",
            )
            recognition.status_code = "NEED_CONFIRM"
            recognition.provider_code = result.provider
            recognition.model_name = result.model
            recognition.candidate_payload_json = self._normalize_recognition_payload(result.candidate_payload)
            recognition.raw_text = result.raw_text
            recognition.raw_response_json = result.raw_response
            recognition.confidence_score = result.confidence_score
            recognition.error_message = None
            await self._add_change_event(
                recognition.vessel_profile_id,
                "IMAGE_RECOGNIZE_PERSON_CERTIFICATE",
                "识别人员证件图片",
                None,
                {"recognition_id": recognition.id, "status_code": recognition.status_code},
                recognition.created_by,
            )
        except Exception as exc:  # noqa: BLE001
            recognition.status_code = "FAILED"
            recognition.error_message = str(exc)[:512]
            await self._add_change_event(
                recognition.vessel_profile_id,
                "IMAGE_RECOGNIZE_PERSON_CERTIFICATE_FAILED",
                "人员证件图片识别失败",
                None,
                {"recognition_id": recognition.id, "error_message": recognition.error_message},
                recognition.created_by,
            )
        await self.db.commit()
        return {"recognition_id": recognition.id, "status_code": recognition.status_code}

    async def process_owner_document_image_recognition(self, recognition_id: int) -> dict[str, Any]:
        recognition = await self.repo.get_owner_document_image_recognition(recognition_id)
        if recognition is None:
            raise NotFoundError("VesselOwnerDocumentImageRecognition", recognition_id)
        try:
            recognition.status_code = "PROCESSING"
            await self.db.flush()
            storage_file, file_result = await FileStorageService(self.db).download_file(recognition.storage_file_id)
            result = await VesselCertificateImageAssistant(self.runtime_config).recognize(
                content=file_result.content,
                content_type=file_result.content_type or storage_file.content_type,
                file_name=storage_file.original_file_name,
                scenario="owner_document",
            )
            recognition.status_code = "NEED_CONFIRM"
            recognition.provider_code = result.provider
            recognition.model_name = result.model
            recognition.candidate_payload_json = self._normalize_recognition_payload(result.candidate_payload)
            recognition.raw_text = result.raw_text
            recognition.raw_response_json = result.raw_response
            recognition.confidence_score = result.confidence_score
            recognition.error_message = None
            await self._add_change_event(
                recognition.vessel_profile_id,
                "IMAGE_RECOGNIZE_OWNER_DOCUMENT",
                "识别所有方证照图片",
                None,
                {"recognition_id": recognition.id, "status_code": recognition.status_code},
                recognition.created_by,
            )
        except Exception as exc:  # noqa: BLE001
            recognition.status_code = "FAILED"
            recognition.error_message = str(exc)[:512]
            await self._add_change_event(
                recognition.vessel_profile_id,
                "IMAGE_RECOGNIZE_OWNER_DOCUMENT_FAILED",
                "所有方证照图片识别失败",
                None,
                {"recognition_id": recognition.id, "error_message": recognition.error_message},
                recognition.created_by,
            )
        await self.db.commit()
        return {"recognition_id": recognition.id, "status_code": recognition.status_code}

    async def _compliance_risk_by_profile(self, ids: list[int]) -> dict[int, dict[str, Any]]:
        if not ids:
            return {}
        today = date.today()
        expiring_until = today + timedelta(days=30)
        cert_rows = (
            await self.db.execute(
                select(VesselCertificate).where(
                    VesselCertificate.vessel_profile_id.in_(ids),
                    VesselCertificate.voided_at.is_(None),
                )
            )
        ).scalars().all()
        certs_by_profile: dict[int, list[VesselCertificate]] = defaultdict(list)
        for cert in cert_rows:
            certs_by_profile[cert.vessel_profile_id].append(cert)

        owner_rows = (
            await self.db.execute(
                select(VesselOwnerPeriod).where(
                    VesselOwnerPeriod.vessel_profile_id.in_(ids),
                    VesselOwnerPeriod.is_current.is_(True),
                )
            )
        ).scalars().all()
        owner_by_profile = {owner.vessel_profile_id: owner for owner in owner_rows}
        owner_ids = [owner.id for owner in owner_rows]
        owner_docs = (
            await self.db.execute(
                select(VesselOwnerDocument).where(
                    VesselOwnerDocument.vessel_owner_period_id.in_(owner_ids),
                    VesselOwnerDocument.voided_at.is_(None),
                )
            )
        ).scalars().all() if owner_ids else []
        owner_doc_types: dict[int, set[str]] = defaultdict(set)
        for document in owner_docs:
            owner_doc_types[document.vessel_owner_period_id].add(document.document_type_code)

        result: dict[int, dict[str, Any]] = {}
        for profile_id in ids:
            certs = certs_by_profile.get(profile_id, [])
            cert_types = {cert.certificate_type_code for cert in certs}
            missing_cert_types = [code for code in REQUIRED_VESSEL_CERTIFICATE_TYPES if code not in cert_types]
            expiring_certs = [
                cert.certificate_type_code for cert in certs
                if cert.valid_to is not None and cert.valid_to <= expiring_until and not cert.is_long_term_valid
            ]
            owner = owner_by_profile.get(profile_id)
            missing_owner_docs: list[str] = []
            owner_completeness_status = "UNKNOWN_OWNER_TYPE"
            if owner is not None:
                required_owner_docs = self._owner_required_document_types(owner)
                if required_owner_docs:
                    missing_owner_docs = sorted(required_owner_docs - owner_doc_types.get(owner.id, set()))
                    owner_completeness_status = "COMPLETE" if not missing_owner_docs else "INCOMPLETE"
            has_risk = bool(missing_cert_types or expiring_certs or missing_owner_docs)
            result[profile_id] = {
                "has_certificate_risk": has_risk,
                "missing_certificate_type_codes": missing_cert_types,
                "expiring_certificate_type_codes": expiring_certs,
                "owner_document_completeness_status": owner_completeness_status,
                "missing_owner_document_type_codes": missing_owner_docs,
                "required_certificate_count": len(REQUIRED_VESSEL_CERTIFICATE_TYPES),
                "archived_certificate_count": len(cert_types & set(REQUIRED_VESSEL_CERTIFICATE_TYPES)),
            }
        return result

    async def _build_profile_response(self, vessel_id: int) -> VesselProfileResponse:
        profile = await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        city_map = await _load_city_map(self.db, [profile.registry_city_code] if profile.registry_city_code else [])
        region_map = await _load_region_map(self.db, [profile.business_region_id] if profile.business_region_id else [])
        return _profile_response(profile, label_map=label_map, city_map=city_map, region_map=region_map)

    async def _build_list_items(self, profiles: list[VesselProfile]) -> list[VesselListItemResponse]:
        if not profiles:
            return []
        ids = [row.id for row in profiles]
        label_map = await _load_label_map(self.db)
        city_map = await _load_city_map(self.db, [row.registry_city_code for row in profiles if row.registry_city_code])
        region_map = await _load_region_map(self.db, [row.business_region_id for row in profiles if row.business_region_id])
        capacities = await self._map_by_profile(VesselCapacityDimension, ids)
        builds = await self._map_by_profile(VesselBuildInfo, ids)
        owners = await self._first_by_profile(VesselOwnerPeriod, ids)
        operators = await self._first_by_profile(VesselOperatorPeriod, ids)
        contacts = await self._first_by_profile(VesselContact, ids)
        items: list[VesselListItemResponse] = []
        for profile in profiles:
            base = _profile_response(profile, label_map=label_map, city_map=city_map, region_map=region_map).model_dump()
            capacity = capacities.get(profile.id)
            build = builds.get(profile.id)
            contact = contacts.get(profile.id)
            items.append(
                VesselListItemResponse(
                    **base,
                    building_year=getattr(build, "building_year", None),
                    ship_age=_ship_age(getattr(build, "building_year", None)),
                    deadweight_ton=capacity.deadweight_ton if capacity else None,
                    length_m=capacity.length_m if capacity else None,
                    width_m=capacity.width_m if capacity else None,
                    design_draft_m=capacity.design_draft_m if capacity else None,
                    size_text=_size_text(capacity),
                    primary_owner_name=getattr(owners.get(profile.id), "party_name", None),
                    primary_operator_name=getattr(operators.get(profile.id), "operator_name", None),
                    primary_contact_name=getattr(contact, "contact_name", None),
                    primary_contact_phone=getattr(contact, "mobile_phone", None),
                    contact_available=getattr(contact, "is_available", None),
                )
            )
        return items

    def _normalize_recognition_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        normalized: dict[str, Any] = {key: _jsonable(value) for key, value in payload.items()}
        alias_groups = {
            "certificate_type_code": ["certificate_type_code", "certificate_type", "cert_type_code"],
            "certificate_no": ["certificate_no", "cert_no", "license_no", "document_no", "证件号"],
            "issuing_authority": ["issuing_authority", "issue_authority", "issuer", "发证机关"],
            "holder_name": ["holder_name", "person_name", "crew_name", "name", "姓名"],
            "valid_from": ["valid_from", "valid_start", "validity_start", "start_date", "issue_date", "签发日期"],
            "valid_to": ["valid_to", "valid_end", "validity_end", "expiry_date", "expire_date", "end_date", "有效期至"],
            "validity_text_raw": ["validity_text_raw", "validity_text", "valid_period", "validity", "有效期"],
            "is_long_term_valid": ["is_long_term_valid", "long_term_valid", "permanent", "valid_forever"],
        }
        for target_key, keys in alias_groups.items():
            value = _first_value(payload, keys)
            if value not in (None, "") and normalized.get(target_key) in (None, ""):
                normalized[target_key] = _jsonable(value)

        valid_to_raw = normalized.get("valid_to")
        validity_text = normalized.get("validity_text_raw")
        long_term_raw = normalized.get("is_long_term_valid")
        if _truthy(long_term_raw) or _looks_long_term(valid_to_raw) or _looks_long_term(validity_text):
            normalized["is_long_term_valid"] = True
            normalized["valid_to"] = None
        elif "is_long_term_valid" in normalized:
            normalized["is_long_term_valid"] = _truthy(normalized.get("is_long_term_valid"))
        return normalized

    def _certificate_updates_from_recognition(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = self._normalize_recognition_payload(payload)
        updates: dict[str, Any] = {}
        for source_key, target_key in {
            "certificate_type_code": "certificate_type_code",
            "certificate_no": "certificate_no",
            "issuing_authority": "issuing_authority",
            "validity_text_raw": "validity_text_raw",
        }.items():
            value = payload.get(source_key)
            if value not in (None, ""):
                updates[target_key] = value
        valid_from = _to_date(payload.get("valid_from"))
        valid_to = _to_date(payload.get("valid_to"))
        if valid_from:
            updates["valid_from"] = valid_from
        if payload.get("is_long_term_valid") is True:
            updates["is_long_term_valid"] = True
            updates["valid_to"] = None
        elif valid_to:
            updates["valid_to"] = valid_to
        if "is_long_term_valid" in payload:
            updates["is_long_term_valid"] = bool(payload.get("is_long_term_valid"))
        return updates

    def _person_certificate_updates_from_recognition(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = self._normalize_recognition_payload(payload)
        updates: dict[str, Any] = {}
        for source_key, target_key in {
            "holder_name": "holder_name",
            "certificate_type_code": "certificate_type_code",
            "certificate_no": "certificate_no",
            "validity_text_raw": "validity_text_raw",
        }.items():
            value = payload.get(source_key)
            if value not in (None, ""):
                updates[target_key] = value
        valid_from = _to_date(payload.get("valid_from"))
        valid_to = _to_date(payload.get("valid_to"))
        if valid_from:
            updates["valid_from"] = valid_from
        if payload.get("is_long_term_valid") is True:
            updates["is_long_term_valid"] = True
            updates["valid_to"] = None
        elif valid_to:
            updates["valid_to"] = valid_to
        if "is_long_term_valid" in payload:
            updates["is_long_term_valid"] = bool(payload.get("is_long_term_valid"))
        return updates

    def _adoption_updates_from_recognition(
        self,
        payload: dict[str, Any],
        fields: list[str],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        requested = {str(field).strip() for field in fields if str(field).strip()}
        profile_updates: dict[str, Any] = {}
        capacity_updates: dict[str, Any] = {}
        profile_field_map = {
            "ship_name": "ship_name",
            "mmsi": "current_mmsi",
            "ship_type_code": "ship_type_code",
        }
        capacity_field_map = {
            "deadweight_ton": "deadweight_ton",
            "total_tonnage": "total_tonnage",
            "net_tonnage": "net_tonnage",
            "length_m": "length_m",
            "width_m": "width_m",
            "depth_m": "depth_m",
            "design_draft_m": "design_draft_m",
        }
        for source_key, target_key in profile_field_map.items():
            if target_key in requested and payload.get(source_key) not in (None, ""):
                profile_updates[target_key] = payload[source_key]
        for source_key, target_key in capacity_field_map.items():
            if target_key in requested:
                value = _to_decimal(payload.get(source_key))
                if value is not None:
                    capacity_updates[target_key] = value
        return profile_updates, capacity_updates

    def _text_value(self, value: Any) -> str | None:
        if value in (None, ""):
            return None
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, (dict, list)):
            return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True)
        return str(value)

    async def _persist_recognition_diffs(
        self,
        *,
        vessel_id: int,
        recognition_object_type: str,
        recognition_id: int,
        target_object_type: str,
        target_object_id: int,
        diffs: dict[str, tuple[Any, Any]],
        confidence_score: int | None,
        evidence_text: str | None,
    ) -> list[VesselRecognitionFieldDiff]:
        await self.db.execute(
            delete(VesselRecognitionFieldDiff).where(
                VesselRecognitionFieldDiff.recognition_object_type == recognition_object_type,
                VesselRecognitionFieldDiff.recognition_id == recognition_id,
                VesselRecognitionFieldDiff.target_object_type == target_object_type,
                VesselRecognitionFieldDiff.target_object_id == target_object_id,
                VesselRecognitionFieldDiff.adopt_status_code == "REVIEW_REQUIRED",
            )
        )
        now = datetime.utcnow()
        rows: list[VesselRecognitionFieldDiff] = []
        for field_name, (current, recognized) in diffs.items():
            if recognized in (None, ""):
                continue
            if _normalized_text(current) == _normalized_text(recognized):
                continue
            row = VesselRecognitionFieldDiff(
                vessel_profile_id=vessel_id,
                recognition_object_type=recognition_object_type,
                recognition_id=recognition_id,
                target_object_type=target_object_type,
                target_object_id=target_object_id,
                field_name=field_name,
                current_value_text=self._text_value(current),
                recognized_value_text=self._text_value(recognized),
                confidence_score=confidence_score,
                evidence_text=evidence_text,
                adopt_status_code="REVIEW_REQUIRED",
                created_at=now,
                updated_at=now,
            )
            self.db.add(row)
            rows.append(row)
        await self.db.flush()
        return rows

    async def _recognition_review_diff_rows(self, recognition_object_type: str, recognition_id: int) -> list[VesselRecognitionFieldDiff]:
        return list(
            (
                await self.db.execute(
                    select(VesselRecognitionFieldDiff).where(
                        VesselRecognitionFieldDiff.recognition_object_type == recognition_object_type,
                        VesselRecognitionFieldDiff.recognition_id == recognition_id,
                        VesselRecognitionFieldDiff.adopt_status_code == "REVIEW_REQUIRED",
                    )
                )
            )
            .scalars()
            .all()
        )

    def _validate_ocr_adoption_selection(
        self,
        diff_rows: list[VesselRecognitionFieldDiff],
        selected_fields: set[str],
        reason: str | None,
    ) -> set[str]:
        if not diff_rows or not selected_fields:
            raise ConflictError(
                "OCR 字段差异尚未确认，请先获取 field-diff 并选择采纳字段",
                code="OCR_DIFF_REQUIRED",
            )
        diff_field_names = {row.field_name for row in diff_rows}
        applicable_fields = selected_fields & diff_field_names
        if not applicable_fields:
            raise ConflictError(
                "提交的采纳字段不在当前 OCR diff 中",
                code="OCR_DIFF_REQUIRED",
                detail={"diff_fields": sorted(diff_field_names), "selected_fields": sorted(selected_fields)},
            )
        low_confidence_fields = sorted(
            row.field_name
            for row in diff_rows
            if row.field_name in applicable_fields
            and row.confidence_score is not None
            and row.confidence_score < LOW_CONFIDENCE_SCORE_THRESHOLD
        )
        if low_confidence_fields and not reason:
            raise ValidationError(
                "低置信字段需要人工确认原因",
                code="LOW_CONFIDENCE_CONFIRM_REQUIRED",
                detail={"fields": low_confidence_fields, "threshold": LOW_CONFIDENCE_SCORE_THRESHOLD},
            )
        return applicable_fields

    async def _certificate_recognition_diff_rows(
        self,
        vessel_id: int,
        cert: VesselCertificate,
        recognition: VesselCertificateImageRecognition,
        accepted: dict[str, Any],
    ) -> list[VesselRecognitionFieldDiff]:
        cert_updates = self._certificate_updates_from_recognition(accepted)
        profile_updates, capacity_updates = self._adoption_updates_from_recognition(
            accepted,
            sorted(CERTIFICATE_PROFILE_ADOPTION_FIELDS),
        )
        profile = await self._require_profile(vessel_id)
        capacity = await self.repo.get_one_by_profile(VesselCapacityDimension, vessel_id)
        diffs: dict[str, tuple[Any, Any]] = {key: (getattr(cert, key, None), value) for key, value in cert_updates.items()}
        diffs.update({key: (getattr(profile, key, None), value) for key, value in profile_updates.items()})
        diffs.update({key: (getattr(capacity, key, None) if capacity else None, value) for key, value in capacity_updates.items()})
        return await self._persist_recognition_diffs(
            vessel_id=vessel_id,
            recognition_object_type="VESSEL_CERTIFICATE_IMAGE_RECOGNITION",
            recognition_id=recognition.id,
            target_object_type="vessel_certificate",
            target_object_id=cert.id,
            diffs=diffs,
            confidence_score=recognition.confidence_score,
            evidence_text=recognition.raw_text,
        )

    async def _person_certificate_recognition_diff_rows(
        self,
        vessel_id: int,
        cert: VesselPersonCertificate,
        recognition: VesselPersonCertificateImageRecognition,
        accepted: dict[str, Any],
    ) -> list[VesselRecognitionFieldDiff]:
        updates = self._person_certificate_updates_from_recognition(accepted)
        diffs = {key: (getattr(cert, key, None), value) for key, value in updates.items()}
        return await self._persist_recognition_diffs(
            vessel_id=vessel_id,
            recognition_object_type="PERSON_CERTIFICATE_IMAGE_RECOGNITION",
            recognition_id=recognition.id,
            target_object_type="vessel_person_certificate",
            target_object_id=cert.id,
            diffs=diffs,
            confidence_score=recognition.confidence_score,
            evidence_text=recognition.raw_text,
        )

    async def _owner_document_recognition_diff_rows(
        self,
        vessel_id: int,
        owner: VesselOwnerPeriod,
        recognition: VesselOwnerDocumentImageRecognition,
        accepted: dict[str, Any],
    ) -> list[VesselRecognitionFieldDiff]:
        party_name = accepted.get("holder_name") or accepted.get("company_name") or accepted.get("party_name")
        diffs = {
            "party_name": (owner.party_name, party_name),
            "certificate_no": (owner.certificate_no, accepted.get("certificate_no") or accepted.get("document_no") or accepted.get("license_no")),
            "address": (owner.address, accepted.get("address")),
        }
        return await self._persist_recognition_diffs(
            vessel_id=vessel_id,
            recognition_object_type="OWNER_DOCUMENT_IMAGE_RECOGNITION",
            recognition_id=recognition.id,
            target_object_type="vessel_owner_period",
            target_object_id=owner.id,
            diffs=diffs,
            confidence_score=recognition.confidence_score,
            evidence_text=recognition.raw_text,
        )

    async def certificate_recognition_field_diff(
        self,
        vessel_id: int,
        certificate_id: int,
        recognition_id: int,
    ) -> list[VesselRecognitionFieldDiffResponse]:
        cert = await self.repo.get_certificate(certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselCertificate", certificate_id)
        recognition = await self.repo.get_image_recognition(recognition_id)
        if (
            recognition is None
            or recognition.vessel_profile_id != vessel_id
            or recognition.vessel_certificate_id != certificate_id
        ):
            raise NotFoundError("VesselCertificateImageRecognition", recognition_id)
        accepted = self._normalize_recognition_payload(recognition.candidate_payload_json or {})
        rows = await self._certificate_recognition_diff_rows(vessel_id, cert, recognition, accepted)
        await self.db.commit()
        return [VesselRecognitionFieldDiffResponse(**_row_dict(row)) for row in rows]

    async def adopt_certificate_recognition(
        self,
        vessel_id: int,
        certificate_id: int,
        recognition_id: int,
        payload,
        *,
        operator_id: int | None = None,
    ) -> VesselCertificateResponse:
        await self._require_profile(vessel_id)
        cert = await self.repo.get_certificate(certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselCertificate", certificate_id)
        recognition = await self.repo.get_image_recognition(recognition_id)
        if (
            recognition is None
            or recognition.vessel_profile_id != vessel_id
            or recognition.vessel_certificate_id != certificate_id
        ):
            raise NotFoundError("VesselCertificateImageRecognition", recognition_id)
        accepted = self._normalize_recognition_payload(payload.accepted_payload_json or recognition.candidate_payload_json or {})
        if not accepted:
            raise ValidationError("没有可确认的识别结果")
        if not await self._recognition_review_diff_rows("VESSEL_CERTIFICATE_IMAGE_RECOGNITION", recognition_id):
            raise ConflictError("请先获取 OCR 字段差异再提交采纳", code="OCR_DIFF_REQUIRED")
        diff_rows = await self._certificate_recognition_diff_rows(vessel_id, cert, recognition, accepted)
        before_cert = _row_dict(cert)
        requested_fields = set(getattr(payload, "adopt_fields", None) or [])
        requested_profile_fields = set(getattr(payload, "adopt_to_profile_fields", None) or [])
        applicable_fields = self._validate_ocr_adoption_selection(
            diff_rows,
            requested_fields | requested_profile_fields,
            getattr(payload, "reason", None),
        )
        updates = self._certificate_updates_from_recognition(accepted)
        updates = {key: value for key, value in updates.items() if key in requested_fields and key in applicable_fields}
        adopted_fields = sorted(updates)
        profile_updates, capacity_updates = self._adoption_updates_from_recognition(
            accepted,
            sorted(requested_profile_fields & applicable_fields),
        )
        if "current_mmsi" in profile_updates:
            profile = await self._require_profile(vessel_id)
            if profile.profile_status_code == ACTIVE_PROFILE_STATUS and profile_updates["current_mmsi"] != profile.current_mmsi:
                await self._assert_active_mmsi_available(
                    profile_updates["current_mmsi"],
                    exclude_vessel_id=vessel_id,
                    attempted_profile_id=vessel_id,
                    evidence_source="OCR_ADOPTION",
                )
        if updates:
            updates["structured_payload_json"] = accepted
            updates["verify_status_code"] = "VERIFIED"
            await self.repo.update_certificate(certificate_id, updates)
        if profile_updates:
            old_profile = await self._require_profile(vessel_id)
            await self.repo.update_profile(vessel_id, profile_updates)
            if "ship_name" in profile_updates:
                await self.repo.add_name_history(vessel_id, profile_updates["ship_name"], source_type_code="AI_RECOGNITION")
            if "current_mmsi" in profile_updates:
                await self._close_current_mmsi_history(vessel_id, old_profile.current_mmsi)
                await self.repo.add_identifier_history(vessel_id, "MMSI", profile_updates["current_mmsi"], source_type_code="AI_RECOGNITION")
            adopted_fields.extend(sorted(profile_updates))
        if capacity_updates:
            await self.repo.upsert_one_by_profile(VesselCapacityDimension, vessel_id, capacity_updates)
            adopted_fields.extend(sorted(capacity_updates))
        recognition.status_code = "CONFIRMED"
        recognition.confirmed_payload_json = accepted
        recognition.confirmed_by = operator_id
        recognition.confirmed_at = datetime.utcnow()
        event_id = await self._add_change_event(
            vessel_id,
            "ADOPT_CERTIFICATE_IMAGE_RECOGNITION",
            "采纳船舶证书识别结果",
            before_cert,
            {"recognition_id": recognition.id, "certificate_updates": updates, "profile_updates": profile_updates, "capacity_updates": capacity_updates},
            operator_id,
            object_type="vessel_certificate",
            object_id=certificate_id,
            reason=getattr(payload, "reason", None),
        )
        self.db.add(
            VesselRecognitionAdoptionRecord(
                vessel_profile_id=vessel_id,
                recognition_object_type="VESSEL_CERTIFICATE_IMAGE_RECOGNITION",
                recognition_id=recognition_id,
                target_object_type="vessel_certificate",
                target_object_id=certificate_id,
                adopted_fields_json=sorted(set(adopted_fields)),
                skipped_fields_json=sorted({row.field_name for row in diff_rows} - set(adopted_fields)),
                confirmed_by=operator_id,
                confirmed_at=datetime.utcnow(),
                reason=getattr(payload, "reason", None),
                change_event_id=event_id,
                created_at=datetime.utcnow(),
            )
        )
        adopted_set = set(adopted_fields)
        for diff in diff_rows:
            diff.adopt_status_code = "ADOPTED" if diff.field_name in adopted_set else "SKIPPED"
            diff.updated_at = datetime.utcnow()
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        await self._refresh_summary_best_effort(vessel_id)
        return (await self._certificates_with_files(vessel_id, certificate_id=certificate_id))[0]

    async def person_certificate_recognition_field_diff(
        self,
        vessel_id: int,
        person_certificate_id: int,
        recognition_id: int,
    ) -> list[VesselRecognitionFieldDiffResponse]:
        cert = await self.repo.get_person_certificate(person_certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselPersonCertificate", person_certificate_id)
        recognition = await self.repo.get_person_image_recognition(recognition_id)
        if (
            recognition is None
            or recognition.vessel_profile_id != vessel_id
            or recognition.vessel_person_certificate_id != person_certificate_id
        ):
            raise NotFoundError("VesselPersonCertificateImageRecognition", recognition_id)
        accepted = self._normalize_recognition_payload(recognition.candidate_payload_json or {})
        rows = await self._person_certificate_recognition_diff_rows(vessel_id, cert, recognition, accepted)
        await self.db.commit()
        return [VesselRecognitionFieldDiffResponse(**_row_dict(row)) for row in rows]

    async def adopt_person_certificate_recognition(
        self,
        vessel_id: int,
        person_certificate_id: int,
        recognition_id: int,
        payload,
        *,
        operator_id: int | None = None,
    ) -> VesselPersonCertificateResponse:
        cert = await self.repo.get_person_certificate(person_certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselPersonCertificate", person_certificate_id)
        recognition = await self.repo.get_person_image_recognition(recognition_id)
        if (
            recognition is None
            or recognition.vessel_profile_id != vessel_id
            or recognition.vessel_person_certificate_id != person_certificate_id
        ):
            raise NotFoundError("VesselPersonCertificateImageRecognition", recognition_id)
        accepted = self._normalize_recognition_payload(payload.accepted_payload_json or recognition.candidate_payload_json or {})
        if not accepted:
            raise ValidationError("没有可确认的识别结果")
        if not await self._recognition_review_diff_rows("PERSON_CERTIFICATE_IMAGE_RECOGNITION", recognition_id):
            raise ConflictError("请先获取 OCR 字段差异再提交采纳", code="OCR_DIFF_REQUIRED")
        diff_rows = await self._person_certificate_recognition_diff_rows(vessel_id, cert, recognition, accepted)
        before = _row_dict(cert)
        requested_fields = set(getattr(payload, "adopt_fields", None) or [])
        applicable_fields = self._validate_ocr_adoption_selection(diff_rows, requested_fields, getattr(payload, "reason", None))
        updates = self._person_certificate_updates_from_recognition(accepted)
        updates = {key: value for key, value in updates.items() if key in requested_fields and key in applicable_fields}
        if updates:
            updates["structured_payload_json"] = accepted
            updates["verify_status_code"] = "VERIFIED"
            updates["source_type_code"] = "AI_RECOGNITION"
            updates["source_trace_id"] = f"PERSON_CERTIFICATE_IMAGE_RECOGNITION:{recognition_id}"
            updates["revision"] = int(cert.revision or 1) + 1
            await self.repo.update_person_certificate(person_certificate_id, updates)
        recognition.status_code = "CONFIRMED"
        recognition.confirmed_payload_json = accepted
        recognition.confirmed_by = operator_id
        recognition.confirmed_at = datetime.utcnow()
        adopted_fields = sorted(updates)
        event_id = await self._add_change_event(
            vessel_id,
            "ADOPT_PERSON_CERTIFICATE_IMAGE_RECOGNITION",
            "采纳人员证件图片识别结果",
            before,
            {"recognition_id": recognition.id, "certificate_updates": updates},
            operator_id,
            object_type="vessel_person_certificate",
            object_id=person_certificate_id,
            reason=getattr(payload, "reason", None),
        )
        self.db.add(
            VesselRecognitionAdoptionRecord(
                vessel_profile_id=vessel_id,
                recognition_object_type="PERSON_CERTIFICATE_IMAGE_RECOGNITION",
                recognition_id=recognition_id,
                target_object_type="vessel_person_certificate",
                target_object_id=person_certificate_id,
                adopted_fields_json=adopted_fields,
                skipped_fields_json=sorted({row.field_name for row in diff_rows} - set(adopted_fields)),
                confirmed_by=operator_id,
                confirmed_at=datetime.utcnow(),
                reason=getattr(payload, "reason", None),
                change_event_id=event_id,
                created_at=datetime.utcnow(),
            )
        )
        adopted_set = set(adopted_fields)
        for diff in diff_rows:
            diff.adopt_status_code = "ADOPTED" if diff.field_name in adopted_set else "SKIPPED"
            diff.updated_at = datetime.utcnow()
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        await self._refresh_summary_best_effort(vessel_id)
        return (await self._person_certificates_with_files(vessel_id, person_certificate_id=person_certificate_id))[0]

    async def owner_document_recognition_field_diff(
        self,
        vessel_id: int,
        owner_id: int,
        owner_document_id: int,
        recognition_id: int,
    ) -> list[VesselRecognitionFieldDiffResponse]:
        owner = await self.db.get(VesselOwnerPeriod, owner_id)
        if owner is None or owner.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselOwnerPeriod", owner_id)
        recognition = await self.repo.get_owner_document_image_recognition(recognition_id)
        if (
            recognition is None
            or recognition.vessel_profile_id != vessel_id
            or recognition.vessel_owner_period_id != owner_id
            or recognition.owner_document_id != owner_document_id
        ):
            raise NotFoundError("VesselOwnerDocumentImageRecognition", recognition_id)
        accepted = self._normalize_recognition_payload(recognition.candidate_payload_json or {})
        rows = await self._owner_document_recognition_diff_rows(vessel_id, owner, recognition, accepted)
        await self.db.commit()
        return [VesselRecognitionFieldDiffResponse(**_row_dict(row)) for row in rows]

    async def adopt_owner_document_recognition(
        self,
        vessel_id: int,
        owner_id: int,
        owner_document_id: int,
        recognition_id: int,
        payload,
        *,
        operator_id: int | None = None,
    ) -> VesselOwnerResponse:
        owner = await self.db.get(VesselOwnerPeriod, owner_id)
        if owner is None or owner.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselOwnerPeriod", owner_id)
        document = await self.repo.get_owner_document(owner_document_id)
        if document is None or document.vessel_owner_period_id != owner_id or document.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselOwnerDocument", owner_document_id)
        recognition = await self.repo.get_owner_document_image_recognition(recognition_id)
        if (
            recognition is None
            or recognition.vessel_profile_id != vessel_id
            or recognition.vessel_owner_period_id != owner_id
            or recognition.owner_document_id != owner_document_id
        ):
            raise NotFoundError("VesselOwnerDocumentImageRecognition", recognition_id)
        accepted = self._normalize_recognition_payload(payload.accepted_payload_json or recognition.candidate_payload_json or {})
        if not accepted:
            raise ValidationError("没有可确认的识别结果")
        if not await self._recognition_review_diff_rows("OWNER_DOCUMENT_IMAGE_RECOGNITION", recognition_id):
            raise ConflictError("请先获取 OCR 字段差异再提交采纳", code="OCR_DIFF_REQUIRED")
        diff_rows = await self._owner_document_recognition_diff_rows(vessel_id, owner, recognition, accepted)
        before = _row_dict(owner)
        updates: dict[str, Any] = {}
        skipped_fields: list[str] = []
        requested_fields = set(getattr(payload, "adopt_fields", None) or []) & OWNER_DOCUMENT_ADOPTABLE_FIELDS
        applicable_fields = self._validate_ocr_adoption_selection(diff_rows, requested_fields, getattr(payload, "reason", None))
        if getattr(payload, "apply_to_owner", True):
            party_name = accepted.get("holder_name") or accepted.get("company_name") or accepted.get("party_name")
            if party_name and _normalized_text(party_name) != _normalized_text(owner.party_name):
                skipped_fields.append("party_name")
                await self._upsert_quality_issue(
                    issue_type_code="OCR_UNCONFIRMED",
                    profile_id=vessel_id,
                    object_type="recognition",
                    object_id=recognition_id,
                    field_name="party_name",
                    normalized_key=f"recognition|{recognition_id}",
                    evidence_source="OWNER_DOCUMENT_OCR",
                    impact_scope=[{"owner_id": owner_id, "current_party_name": owner.party_name, "recognized_party_name": str(party_name)}],
                )
            for field_name, value in {
                "certificate_no": accepted.get("certificate_no") or accepted.get("document_no") or accepted.get("license_no"),
                "address": accepted.get("address"),
            }.items():
                if value in (None, ""):
                    continue
                if field_name not in requested_fields or field_name not in applicable_fields:
                    skipped_fields.append(field_name)
                    continue
                updates[field_name] = str(value).strip()
        if updates:
            for key, value in updates.items():
                setattr(owner, key, value)
            owner.source_type_code = "AI_RECOGNITION"
            owner.source_trace_id = f"OWNER_DOCUMENT_IMAGE_RECOGNITION:{recognition_id}"
            owner.revision = int(owner.revision or 1) + 1
        skipped_fields = sorted({row.field_name for row in diff_rows} - set(updates))
        recognition.status_code = "CONFIRMED"
        recognition.confirmed_payload_json = {**accepted, "skipped_fields": skipped_fields}
        recognition.confirmed_by = operator_id
        recognition.confirmed_at = datetime.utcnow()
        event_id = await self._add_change_event(
            vessel_id,
            "ADOPT_OWNER_DOCUMENT_IMAGE_RECOGNITION",
            "采纳所有方证照识别结果",
            before,
            {"recognition_id": recognition.id, "owner_updates": updates, "skipped_fields": skipped_fields},
            operator_id,
            object_type="vessel_owner_period",
            object_id=owner_id,
            reason=getattr(payload, "reason", None),
        )
        self.db.add(
            VesselRecognitionAdoptionRecord(
                vessel_profile_id=vessel_id,
                recognition_object_type="OWNER_DOCUMENT_IMAGE_RECOGNITION",
                recognition_id=recognition_id,
                target_object_type="vessel_owner_period",
                target_object_id=owner_id,
                adopted_fields_json=sorted(updates),
                skipped_fields_json=skipped_fields,
                confirmed_by=operator_id,
                confirmed_at=datetime.utcnow(),
                reason=getattr(payload, "reason", None),
                change_event_id=event_id,
                created_at=datetime.utcnow(),
            )
        )
        adopted_set = set(updates)
        for diff in diff_rows:
            if diff.field_name in adopted_set:
                diff.adopt_status_code = "ADOPTED"
            else:
                diff.adopt_status_code = "SKIPPED"
            diff.updated_at = datetime.utcnow()
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        await self._refresh_summary_best_effort(vessel_id)
        label_map = await _load_label_map(self.db)
        docs = await self._owner_documents_by_owner(vessel_id, label_map)
        response = self._owner_response(owner, label_map, documents=docs.get(owner.id, []))
        response.change_event_id = event_id
        return response

    def _validate_vessel_certificate_type(self, certificate_type_code: str | None) -> None:
        code = certificate_type_code or "UNKNOWN"
        if code not in VALID_VESSEL_CERTIFICATE_TYPES:
            raise ValidationError("船舶证书类型必须从船舶证书目录中选择")

    def _certificate_ledger_status(self, cert: VesselCertificateResponse | None) -> str:
        if cert is None:
            return "MISSING"
        if cert.voided_at is not None:
            return "VOIDED"
        current = cert.current_image_recognition
        if current is not None and current.status_code == "NEED_CONFIRM":
            return "NEED_CONFIRM"
        if current is not None and current.status_code in ACTIVE_RECOGNITION_STATUSES:
            return current.status_code
        if current is not None and current.status_code == "FAILED":
            return "RECOGNITION_FAILED"
        has_core_fields = bool(cert.certificate_no) and (cert.is_long_term_valid or cert.valid_to is not None)
        if not cert.files and not has_core_fields:
            return "DRAFT"
        if cert.verify_status_code != "VERIFIED" or not has_core_fields:
            return "ARCHIVED" if cert.files else "DRAFT"
        if cert.verify_status_code == "VERIFIED":
            if cert.is_long_term_valid:
                return "VERIFIED"
            if cert.valid_to is not None:
                today = date.today()
                if cert.valid_to < today:
                    return "EXPIRED"
                if cert.valid_to <= today + timedelta(days=30):
                    return "EXPIRING"
            return "VERIFIED"
        return "ARCHIVED"

    def _certificate_ledger_status_name(self, status_code: str) -> str:
        return {
            "MISSING": "缺失",
            "DRAFT": "草稿",
            "ARCHIVED": "已归档",
            "QUEUED": "排队识别",
            "PROCESSING": "识别中",
            "NEED_CONFIRM": "待确认",
            "RECOGNITION_FAILED": "识别失败",
            "VERIFIED": "已核验",
            "EXPIRING": "即将到期",
            "EXPIRED": "已过期",
            "VOIDED": "已作废",
        }.get(status_code, status_code)

    async def _require_profile(self, vessel_id: int) -> VesselProfile:
        profile = await self.repo.get_profile(vessel_id)
        if profile is None:
            raise NotFoundError("VesselProfile", vessel_id)
        return profile

    async def _require_crew_assignment(self, vessel_id: int, crew_assignment_id: int | None) -> VesselCrewAssignment:
        if crew_assignment_id is None:
            raise ValidationError("船员适任证必须绑定当前船员任职")
        crew = await self.db.get(VesselCrewAssignment, crew_assignment_id)
        if crew is None or crew.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselCrewAssignment", crew_assignment_id)
        if not crew.is_current:
            raise ValidationError("船员适任证只能绑定当前任职船员")
        return crew

    async def _map_by_profile(self, model, ids: list[int]) -> dict[int, Any]:
        rows = (await self.db.execute(select(model).where(model.vessel_profile_id.in_(ids)))).scalars().all()
        return {row.vessel_profile_id: row for row in rows}

    async def _first_by_profile(self, model, ids: list[int]) -> dict[int, Any]:
        rows = (
            await self.db.execute(
                select(model)
                .where(model.vessel_profile_id.in_(ids))
                .order_by(model.vessel_profile_id.asc(), model.is_primary.desc(), model.id.asc())
            )
        ).scalars().all()
        result: dict[int, Any] = {}
        for row in rows:
            result.setdefault(row.vessel_profile_id, row)
        return result

    async def _profiles_by_ids(self, ids: list[int]) -> dict[int, VesselProfile]:
        if not ids:
            return {}
        rows = (await self.db.execute(select(VesselProfile).where(VesselProfile.id.in_(ids)))).scalars().all()
        return {row.id: row for row in rows}

    async def _active_quality_issue_counts(self, ids: list[int]) -> dict[int, int]:
        if not ids:
            return {}
        rows = (
            await self.db.execute(
                select(VesselDataQualityIssue.vessel_profile_id, func.count(VesselDataQualityIssue.id))
                .where(
                    VesselDataQualityIssue.vessel_profile_id.in_(ids),
                    VesselDataQualityIssue.status_code.in_(ACTIVE_ISSUE_STATUSES),
                )
                .group_by(VesselDataQualityIssue.vessel_profile_id)
            )
        ).all()
        return {int(profile_id): int(count) for profile_id, count in rows if profile_id is not None}

    def _position_monitor_profile_base_stmt(self, query):
        stmt = (
            select(VesselProfile)
            .outerjoin(VesselCapacityDimension, VesselCapacityDimension.vessel_profile_id == VesselProfile.id)
            .outerjoin(VesselContact, VesselContact.vessel_profile_id == VesselProfile.id)
            .outerjoin(
                VesselOwnerPeriod,
                and_(VesselOwnerPeriod.vessel_profile_id == VesselProfile.id, VesselOwnerPeriod.is_current.is_(True)),
            )
            .outerjoin(
                VesselOperatorPeriod,
                and_(VesselOperatorPeriod.vessel_profile_id == VesselProfile.id, VesselOperatorPeriod.is_current.is_(True)),
            )
            .where(VesselProfile.deleted_at.is_(None))
        )
        if query.keyword:
            like_value = f"%{query.keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    VesselProfile.vessel_profile_code.ilike(like_value),
                    VesselProfile.ship_name.ilike(like_value),
                    VesselProfile.current_mmsi.ilike(like_value),
                    VesselOwnerPeriod.party_name.ilike(like_value),
                    VesselOperatorPeriod.operator_name.ilike(like_value),
                    VesselContact.contact_name.ilike(like_value),
                    VesselContact.mobile_phone.ilike(like_value),
                )
            )
        if query.ship_type_code:
            stmt = stmt.where(VesselProfile.ship_type_code == query.ship_type_code)
        if query.profile_status_code:
            stmt = stmt.where(VesselProfile.profile_status_code == query.profile_status_code)
        else:
            stmt = stmt.where(~VesselProfile.profile_status_code.in_(["INACTIVE", "TRANSFERRED", "ARCHIVED", "DECOMMISSIONED"]))
        if query.deadweight_min is not None:
            stmt = stmt.where(VesselCapacityDimension.deadweight_ton >= query.deadweight_min)
        if query.deadweight_max is not None:
            stmt = stmt.where(VesselCapacityDimension.deadweight_ton <= query.deadweight_max)
        if query.draft_max is not None:
            stmt = stmt.where(VesselCapacityDimension.design_draft_m <= query.draft_max)
        if query.contact_available is not None:
            stmt = stmt.where(VesselContact.is_available.is_(query.contact_available))
        return stmt

    async def _position_monitor_profile_count(self, query) -> int:
        subquery = self._position_monitor_profile_base_stmt(query).with_only_columns(VesselProfile.id).group_by(VesselProfile.id).subquery()
        return int((await self.db.execute(select(func.count()).select_from(subquery))).scalar_one() or 0)

    async def _position_monitor_profiles(self, query, *, limit: int | None = None) -> list[VesselProfile]:
        stmt = self._position_monitor_profile_base_stmt(query)
        stmt = stmt.group_by(VesselProfile.id).order_by(VesselProfile.updated_at.desc(), VesselProfile.id.desc())
        if limit is not None:
            stmt = stmt.limit(limit)
        elif hasattr(query, "max_items"):
            stmt = stmt.limit(max(query.max_items * 3, query.max_items))
        rows = (await self.db.execute(stmt)).scalars().all()
        return list(rows)

    async def _mmsi_values_by_profile(self, ids: list[int]) -> dict[int, list[str]]:
        rows = (
            await self.db.execute(
                select(VesselIdentifierHistory)
                .where(
                    VesselIdentifierHistory.vessel_profile_id.in_(ids),
                    VesselIdentifierHistory.identifier_type_code == "MMSI",
                    or_(VesselIdentifierHistory.end_date.is_(None), VesselIdentifierHistory.end_date >= date.today()),
                )
            )
        ).scalars().all()
        result: dict[int, list[str]] = defaultdict(list)
        profiles = await self._profiles_by_ids(ids)
        for profile_id, profile in profiles.items():
            result[profile_id].append(profile.current_mmsi)
        for row in rows:
            if row.identifier_value and row.identifier_value not in result[row.vessel_profile_id]:
                result[row.vessel_profile_id].append(row.identifier_value)
        return result

    async def _search_realtime_positions(self, mmsi_values: list[str], *, max_hits: int) -> dict[str, dict[str, Any]]:
        terms: list[Any] = []
        for value in mmsi_values:
            text_value = str(value).strip()
            if not text_value:
                continue
            terms.append(text_value)
            if text_value.isdigit():
                terms.append(int(text_value))
        terms = list(dict.fromkeys(terms))
        mmsi_fields = [
            "shipMmsi",
            "shipMmsi.keyword",
            "mmsi",
            "mmsi.keyword",
            "ship_mmsi",
            "ship_mmsi.keyword",
            "MMSI",
            "ais",
            "ship_ais",
        ]
        time_fields = ["posTime", "updateTime", "timestamp", "location_time", "update_time", "position_time", "time", "@timestamp"]
        source_fields = [
            "shipMmsi",
            "mmsi",
            "ship_mmsi",
            "MMSI",
            "ais",
            "ship_ais",
            "lon",
            "lng",
            "longitude",
            "longitude_gcj02",
            "lat",
            "latitude",
            "latitude_gcj02",
            "speed",
            "sog",
            "speed_kn",
            "cog",
            "course",
            "course_deg",
            "head",
            "heading",
            "hdg",
            "heading_deg",
            "posTime",
            "updateTime",
            "timestamp",
            "location_time",
            "update_time",
            "position_time",
            "time",
            "@timestamp",
            "location_text",
            "address",
            "area_name",
            "city_name",
            "city",
            "city_code",
            "cityCode",
            "adcode",
            "city_adcode",
            "region_code",
            "shipEnName",
        ]
        query_body = {
            "size": min(max_hits, 1000),
            "track_total_hits": False,
            "_source": source_fields,
            "sort": [
                {field: {"order": "desc", "unmapped_type": "date", "missing": "_last"}}
                for field in time_fields
            ],
            "query": {
                "bool": {
                    "should": [{"terms": {field: terms}} for field in mmsi_fields],
                    "minimum_should_match": 1,
                }
            },
        }
        client = RealtimeEsClient(runtime_config=self.runtime_config)
        index = (
            await self.runtime_config.get_value(
                ES_R_INDEX,
                settings.ES_R_INDEX or "ship_positions",
                profile_code=ES_REALTIME_CONFIG_PROFILE,
            )
            or "ship_positions"
        ).strip()
        try:
            payload = await client.search(index, query_body)
        except Exception:
            query_body.pop("sort", None)
            payload = await client.search(index, query_body)
        hits = ((payload.get("hits") or {}).get("hits") or []) if isinstance(payload, dict) else []
        result: dict[str, dict[str, Any]] = {}
        for hit in hits:
            source = hit.get("_source") if isinstance(hit, dict) else None
            if not isinstance(source, dict):
                continue
            mmsi_raw = _first_value(source, ["shipMmsi", "mmsi", "ship_mmsi", "MMSI", "ais", "ship_ais"])
            if mmsi_raw is None:
                continue
            mmsi = str(mmsi_raw).strip()
            longitude = _to_decimal(_first_value(source, ["lon", "lng", "longitude", "x", "longitude_gcj02"]))
            latitude = _to_decimal(_first_value(source, ["lat", "latitude", "y", "latitude_gcj02"]))
            position_time = _parse_position_time(
                _first_value(source, ["posTime", "updateTime", "timestamp", "location_time", "update_time", "position_time", "time", "@timestamp"])
            )
            existing = result.get(mmsi)
            if existing and existing.get("position_time") and position_time and existing["position_time"] >= position_time:
                continue
            result[mmsi] = {
                "mmsi": mmsi,
                "source_index": hit.get("_index") if isinstance(hit, dict) else None,
                "longitude": longitude,
                "latitude": latitude,
                "speed_kn": _first_value(source, ["speed", "sog", "speed_kn"]),
                "course_deg": _first_value(source, ["course", "cog", "course_deg"]),
                "heading_deg": _first_value(source, ["heading", "head", "hdg", "heading_deg"]),
                "position_time": position_time,
                "location_text": _first_value(source, ["location_text", "address", "area_name", "city_name"]),
                "raw_city_code": _first_value(source, ["city_code", "cityCode", "adcode", "city_adcode", "region_code"]),
                "raw_city_name": _first_value(source, ["city_name", "city", "area_name"]),
            }
        return result

    async def _search_recent_realtime_positions(self, *, reported_within_minutes: int, max_hits: int) -> dict[str, dict[str, Any]]:
        time_fields = ["posTime", "updateTime", "timestamp", "location_time", "update_time", "position_time", "time", "@timestamp"]
        source_fields = [
            "shipMmsi", "mmsi", "ship_mmsi", "MMSI", "ais", "ship_ais",
            "lon", "lng", "longitude", "longitude_gcj02", "lat", "latitude", "latitude_gcj02",
            "speed", "sog", "speed_kn", "cog", "course", "course_deg", "head", "heading", "hdg", "heading_deg",
            "posTime", "updateTime", "timestamp", "location_time", "update_time", "position_time", "time", "@timestamp",
            "location_text", "address", "area_name", "city_name", "city", "city_code", "cityCode", "adcode", "city_adcode", "region_code",
        ]
        earliest = (datetime.utcnow() - timedelta(minutes=reported_within_minutes)).isoformat()
        range_should = [{"range": {field: {"gte": earliest}}} for field in time_fields]
        query_body = {
            "size": min(max_hits, 10000),
            "track_total_hits": False,
            "_source": source_fields,
            "sort": [
                {field: {"order": "desc", "unmapped_type": "date", "missing": "_last"}}
                for field in time_fields
            ],
            "query": {
                "bool": {
                    "should": range_should,
                    "minimum_should_match": 1,
                }
            },
        }
        client = RealtimeEsClient(runtime_config=self.runtime_config)
        index = (
            await self.runtime_config.get_value(
                ES_R_INDEX,
                settings.ES_R_INDEX or "ship_positions",
                profile_code=ES_REALTIME_CONFIG_PROFILE,
            )
            or "ship_positions"
        ).strip()
        try:
            payload = await client.search(index, query_body)
        except Exception:
            query_body.pop("sort", None)
            payload = await client.search(index, query_body)
        hits = ((payload.get("hits") or {}).get("hits") or []) if isinstance(payload, dict) else []
        result: dict[str, dict[str, Any]] = {}
        for hit in hits:
            source = hit.get("_source") if isinstance(hit, dict) else None
            if not isinstance(source, dict):
                continue
            mmsi_raw = _first_value(source, ["shipMmsi", "mmsi", "ship_mmsi", "MMSI", "ais", "ship_ais"])
            if mmsi_raw is None:
                continue
            mmsi = str(mmsi_raw).strip()
            if not mmsi:
                continue
            position_time = _parse_position_time(
                _first_value(source, ["posTime", "updateTime", "timestamp", "location_time", "update_time", "position_time", "time", "@timestamp"])
            )
            existing = result.get(mmsi)
            if existing and existing.get("position_time") and position_time and existing["position_time"] >= position_time:
                continue
            result[mmsi] = {
                "mmsi": mmsi,
                "source_index": hit.get("_index") if isinstance(hit, dict) else None,
                "longitude": _to_decimal(_first_value(source, ["lon", "lng", "longitude", "x", "longitude_gcj02"])),
                "latitude": _to_decimal(_first_value(source, ["lat", "latitude", "y", "latitude_gcj02"])),
                "speed_kn": _first_value(source, ["speed", "sog", "speed_kn"]),
                "course_deg": _first_value(source, ["course", "cog", "course_deg"]),
                "heading_deg": _first_value(source, ["heading", "head", "hdg", "heading_deg"]),
                "position_time": position_time,
                "location_text": _first_value(source, ["location_text", "address", "area_name", "city_name"]),
                "raw_city_code": _first_value(source, ["city_code", "cityCode", "adcode", "city_adcode", "region_code"]),
                "raw_city_name": _first_value(source, ["city_name", "city", "area_name"]),
            }
        return result

    async def _search_realtime_positions_batched(
        self,
        mmsi_values: list[str],
        *,
        batch_size: int,
        max_concurrency: int,
    ) -> tuple[dict[str, dict[str, Any]], bool, str | None, int, list[dict[str, Any]]]:
        positions: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        unique_values = [value for value in dict.fromkeys(mmsi_values) if value]
        batches = [unique_values[start:start + batch_size] for start in range(0, len(unique_values), batch_size)]
        semaphore = asyncio.Semaphore(max(1, max_concurrency))

        async def run_batch(batch_index: int, batch: list[str]) -> tuple[int, list[str], dict[str, dict[str, Any]], str | None]:
            async with semaphore:
                try:
                    return batch_index, batch, await self._search_realtime_positions(batch, max_hits=max(len(batch) * 3, 200)), None
                except Exception as exc:  # noqa: BLE001
                    return batch_index, batch, {}, str(exc)

        failed_batches: list[dict[str, Any]] = []
        for batch_index, batch, batch_positions, error in await asyncio.gather(
            *(run_batch(batch_index, batch) for batch_index, batch in enumerate(batches, start=1))
        ):
            if batch_positions:
                positions.update(batch_positions)
            if error:
                errors.append(error)
                failed_batches.append({
                    "batch_index": batch_index,
                    "mmsi_count": len(batch),
                    "sample_mmsi": batch[:5],
                    "error_message": error,
                })
        return positions, bool(errors), "；".join(errors[:3]) if errors else None, len(errors), failed_batches

    async def _position_monitor_items_for_profiles(
        self,
        profiles: list[VesselProfile],
        *,
        generated_at: datetime,
        reported_within_minutes: int,
        es_batch_size: int,
        es_max_concurrency: int,
        include_stale: bool,
        include_unmatched: bool = False,
        unmatched_scan_limit: int = 0,
    ) -> _PositionBuildResult:
        mmsi_by_profile = await self._mmsi_values_by_profile([row.id for row in profiles])
        mmsi_values = sorted({item for values in mmsi_by_profile.values() for item in values if item})
        if not mmsi_values:
            return _PositionBuildResult([], False, None, 0, 0, 0, 0, 0, 0)
        positions, partial, error_message, failed_batch_count, failed_batches = await self._search_realtime_positions_batched(
            mmsi_values,
            batch_size=es_batch_size,
            max_concurrency=es_max_concurrency,
        )
        if include_unmatched and unmatched_scan_limit > 0:
            try:
                recent_positions = await self._search_recent_realtime_positions(
                    reported_within_minutes=reported_within_minutes,
                    max_hits=unmatched_scan_limit,
                )
                for mmsi, position in recent_positions.items():
                    positions.setdefault(mmsi, position)
            except Exception as exc:  # noqa: BLE001
                partial = True
                failed_batch_count += 1
                error_message = "；".join(part for part in [error_message, f"未匹配 MMSI 扫描失败：{exc}"] if part)
                failed_batches.append({
                    "batch_index": "unmatched_scan",
                    "mmsi_count": 0,
                    "sample_mmsi": [],
                    "error_message": str(exc),
                })
        boundaries = await self._city_boundaries()
        boundary_grid = _CITY_BOUNDARY_CACHE.get("grid_index") or {}
        profiles_by_mmsi: dict[str, list[VesselProfile]] = defaultdict(list)
        for profile in profiles:
            for mmsi in mmsi_by_profile.get(profile.id, [profile.current_mmsi]):
                if mmsi:
                    profiles_by_mmsi[mmsi].append(profile)
        position_by_profile: dict[int, dict[str, Any]] = {}
        match_status_by_profile: dict[int, str] = {}
        freshness_limit = generated_at - timedelta(minutes=reported_within_minutes)
        unmatched_positions: list[dict[str, Any]] = []
        invalid_positions: list[dict[str, Any]] = []
        for mmsi, position in positions.items():
            matched_profiles = profiles_by_mmsi.get(mmsi) or []
            if not matched_profiles:
                longitude = _to_decimal(position.get("longitude"))
                latitude = _to_decimal(position.get("latitude"))
                position_time = position.get("position_time")
                age_minutes = int((generated_at - position_time).total_seconds() // 60) if position_time else None
                valid_position = self._valid_longitude_latitude(longitude, latitude)
                resolved_city = self._resolve_current_city_from_boundaries(longitude, latitude, boundaries, boundary_grid) if valid_position else _ResolvedCity(None, UNKNOWN_CITY_NAME, CURRENT_CITY_SOURCE_INVALID_POSITION)
                unmatched_positions.append({
                    **position,
                    "mmsi": mmsi,
                    "longitude": longitude,
                    "latitude": latitude,
                    "position_age_minutes": age_minutes,
                    "freshness_level": _ais_freshness_level(age_minutes),
                    "match_status_code": "UNMATCHED_MMSI" if valid_position else "INVALID_POSITION",
                    "valid_position_flag": valid_position,
                    "city_code": resolved_city.city_code,
                    "city_name": resolved_city.city_name,
                    "current_city_source": resolved_city.current_city_source,
                })
                if not valid_position:
                    invalid_positions.append(unmatched_positions[-1])
                continue
            profile = matched_profiles[0]
            if profile.id in position_by_profile:
                continue
            position_time = position.get("position_time")
            if not include_stale and position_time and position_time < freshness_limit:
                continue
            position_by_profile[profile.id] = position
            match_status_by_profile[profile.id] = "MULTI_PROFILE_CONFLICT" if len(matched_profiles) > 1 else "MATCHED_PROFILE"
        positioned_profiles = [profile for profile in profiles if profile.id in position_by_profile]
        list_items = await self._build_list_items(positioned_profiles)
        items: list[VesselPositionMonitorItemResponse] = []
        invalid_position_count = 0
        unknown_city_count = 0
        for item in list_items:
            position = position_by_profile.get(item.id)
            if position is None:
                continue
            longitude = _to_decimal(position.get("longitude"))
            latitude = _to_decimal(position.get("latitude"))
            if longitude is None or latitude is None or not self._valid_longitude_latitude(longitude, latitude):
                invalid_position_count += 1
                invalid_positions.append({**position, "mmsi": item.current_mmsi, "vessel_profile_id": item.id, "match_status_code": "INVALID_POSITION", "valid_position_flag": False})
                continue
            resolved_city = self._resolve_current_city_from_boundaries(longitude, latitude, boundaries, boundary_grid)
            if resolved_city.current_city_source != CURRENT_CITY_SOURCE_ADMIN_BOUNDARY:
                unknown_city_count += 1
            position_time = position.get("position_time")
            age_minutes = int((generated_at - position_time).total_seconds() // 60) if position_time else None
            freshness_level = _ais_freshness_level(age_minutes)
            items.append(
                VesselPositionMonitorItemResponse(
                    **item.model_dump(),
                    longitude=longitude,
                    latitude=latitude,
                    speed_kn=_to_decimal(position.get("speed_kn")),
                    course_deg=_to_decimal(position.get("course_deg")),
                    heading_deg=_to_decimal(position.get("heading_deg")),
                    position_time=position_time,
                    position_age_minutes=age_minutes,
                    city_code=resolved_city.city_code,
                    city_name=resolved_city.city_name,
                    current_city_code=resolved_city.city_code,
                    current_city_name=resolved_city.city_name,
                    current_city_source=resolved_city.current_city_source,
                    city_center_longitude=resolved_city.city_center_longitude,
                    city_center_latitude=resolved_city.city_center_latitude,
                    matched_city_candidates=resolved_city.matched_city_candidates,
                    location_text=position.get("location_text"),
                    position_source_name="实时 ES",
                    source_index=position.get("source_index"),
                    freshness_level=freshness_level,
                    match_status_code=match_status_by_profile.get(item.id, "MATCHED_PROFILE"),
                )
            )
        matched_position_count = len(items)
        source_indices = sorted({str(position.get("source_index")) for position in positions.values() if position.get("source_index")})
        return _PositionBuildResult(
            items=items,
            partial=partial,
            error_message=error_message,
            failed_batch_count=failed_batch_count,
            queried_mmsi_count=len(mmsi_values),
            matched_position_count=matched_position_count,
            unpositioned_count=max(0, len(mmsi_values) - matched_position_count - invalid_position_count),
            invalid_position_count=invalid_position_count,
            unknown_city_count=unknown_city_count,
            unmatched_positions=unmatched_positions,
            invalid_positions=invalid_positions,
            source_indices=source_indices,
            failed_batches=failed_batches,
        )

    def _is_stale_position(self, item: VesselPositionMonitorItemResponse, generated_at: datetime, reported_within_minutes: int) -> bool:
        return bool(item.position_time and item.position_time < generated_at - timedelta(minutes=reported_within_minutes))

    def _position_freshness_distribution(self, items: list[VesselPositionMonitorItemResponse], unmatched: list[dict[str, Any]] | None = None) -> dict[str, int]:
        result = {"FRESH": 0, "RECENT": 0, "STALE": 0, "EXPIRED": 0, "UNKNOWN": 0}
        for item in items:
            level = getattr(item, "freshness_level", None)
            if not level:
                position_time = getattr(item, "position_time", None)
                age_minutes = int((datetime.utcnow() - position_time).total_seconds() // 60) if position_time else None
                level = _ais_freshness_level(age_minutes)
            result[level or "UNKNOWN"] = result.get(level or "UNKNOWN", 0) + 1
        for item in unmatched or []:
            level = str(item.get("freshness_level") or "UNKNOWN")
            result[level] = result.get(level, 0) + 1
        return result

    def _coverage_rate(self, matched_position_count: int, queried_mmsi_count: int) -> Decimal | None:
        if queried_mmsi_count <= 0:
            return None
        return (Decimal(matched_position_count) / Decimal(queried_mmsi_count) * Decimal("100")).quantize(Decimal("0.01"))

    def _position_city_code(self, item: VesselPositionMonitorItemResponse | None) -> str:
        if item is None:
            return UNKNOWN_CITY_CODE
        return (item.current_city_code or item.city_code or "").strip() or UNKNOWN_CITY_CODE

    def _position_city_name(self, item: VesselPositionMonitorItemResponse | None) -> str:
        if item is None:
            return UNKNOWN_CITY_NAME
        return (item.current_city_name or item.city_name or "").strip() or UNKNOWN_CITY_NAME

    def _city_matches(self, item: VesselPositionMonitorItemResponse, *, city_code: str | None, city_name: str | None) -> bool:
        if city_code:
            expected = city_code.strip()
            actual = self._position_city_code(item)
            if expected == UNKNOWN_CITY_CODE:
                return actual == UNKNOWN_CITY_CODE
            return actual == expected
        if city_name:
            return self._position_city_name(item) == city_name.strip()
        return True

    def _city_situation_items(
        self,
        items: list[VesselPositionMonitorItemResponse],
        risk_by_profile: dict[int, dict[str, Any]],
        generated_at: datetime,
        reported_within_minutes: int,
        queried_mmsi_count: int,
        matched_position_count: int,
        unpositioned_count: int,
        invalid_position_count: int,
        unknown_city_count: int,
        partial: bool,
        error_message: str | None,
        boundary_paths_by_code: dict[str, list[list[tuple[float, float]]]] | None = None,
        boundary_precision: str | None = None,
        boundary_codes: set[str] | None = None,
        unmatched_positions: list[dict[str, Any]] | None = None,
    ) -> list[VesselPositionCitySituationItemResponse]:
        boundary_paths_by_code = boundary_paths_by_code or {}
        boundary_codes = boundary_codes or set(boundary_paths_by_code.keys())
        unmatched_positions = unmatched_positions or []
        grouped: dict[str, list[VesselPositionMonitorItemResponse]] = defaultdict(list)
        for item in items:
            grouped[self._position_city_code(item)].append(item)
        unmatched_grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for position in unmatched_positions:
            city_code = str(position.get("city_code") or UNKNOWN_CITY_CODE)
            unmatched_grouped[city_code].append(position)
            grouped.setdefault(city_code, [])
        result: list[VesselPositionCitySituationItemResponse] = []
        for city_code, city_items in grouped.items():
            fresh_items = [item for item in city_items if not self._is_stale_position(item, generated_at, reported_within_minutes)]
            stats_items = fresh_items or city_items
            city_unmatched = unmatched_grouped.get(city_code, [])
            ages = [Decimal(item.ship_age) for item in stats_items if item.ship_age is not None]
            deadweights = [_to_decimal(item.deadweight_ton) for item in stats_items if item.deadweight_ton is not None]
            deadweights = [value for value in deadweights if value is not None]
            type_counts: dict[str | None, int] = defaultdict(int)
            type_names: dict[str | None, str | None] = {}
            for item in stats_items:
                type_counts[item.ship_type_code] += 1
                type_names[item.ship_type_code] = item.ship_type_name
            longitudes = [_to_decimal(item.longitude) for item in stats_items]
            latitudes = [_to_decimal(item.latitude) for item in stats_items]
            longitudes = [value for value in longitudes if value is not None]
            latitudes = [value for value in latitudes if value is not None]
            is_unknown_city = city_code == UNKNOWN_CITY_CODE
            heat_longitude = (sum(longitudes, Decimal("0")) / Decimal(len(longitudes))).quantize(Decimal("0.000001")) if longitudes and not is_unknown_city else None
            heat_latitude = (sum(latitudes, Decimal("0")) / Decimal(len(latitudes))).quantize(Decimal("0.000001")) if latitudes and not is_unknown_city else None
            first_item = stats_items[0] if stats_items else None
            serialized_boundary_paths = None if is_unknown_city else _serialize_boundary_paths(boundary_paths_by_code.get(city_code))
            has_boundary = False if is_unknown_city else city_code in boundary_codes
            freshness_distribution = self._position_freshness_distribution(city_items, city_unmatched)
            result.append(
                VesselPositionCitySituationItemResponse(
                    city_code=None if is_unknown_city else city_code,
                    city_name=self._position_city_name(first_item) if first_item else str(city_unmatched[0].get("city_name") or UNKNOWN_CITY_NAME) if city_unmatched else UNKNOWN_CITY_NAME,
                    longitude=None if is_unknown_city else getattr(first_item, "city_center_longitude", None),
                    latitude=None if is_unknown_city else getattr(first_item, "city_center_latitude", None),
                    city_center_longitude=None if is_unknown_city else getattr(first_item, "city_center_longitude", None),
                    city_center_latitude=None if is_unknown_city else getattr(first_item, "city_center_latitude", None),
                    heat_center_longitude=heat_longitude,
                    heat_center_latitude=heat_latitude,
                    boundary_paths=serialized_boundary_paths,
                    has_boundary=has_boundary,
                    boundary_precision=None if is_unknown_city or not serialized_boundary_paths else boundary_precision,
                    positioned_count=len(fresh_items),
                    contactable_position_count=sum(1 for item in fresh_items if item.contact_available),
                    average_ship_age=(sum(ages, Decimal("0")) / Decimal(len(ages))).quantize(Decimal("0.1")) if ages else None,
                    total_deadweight_ton=sum(deadweights, Decimal("0")).quantize(Decimal("0.01")) if deadweights else Decimal("0"),
                    ship_type_distribution=[
                        VesselShipTypeDistributionItemResponse(
                            ship_type_code=code,
                            ship_type_name=type_names.get(code),
                            count=count,
                        )
                        for code, count in sorted(type_counts.items(), key=lambda item: item[1], reverse=True)
                    ],
                    stale_position_count=len(city_items) - len(fresh_items),
                    certificate_risk_count=sum(1 for item in fresh_items if risk_by_profile.get(item.id, {}).get("has_certificate_risk")),
                    unmatched_mmsi_count=len(city_unmatched),
                    invalid_position_count=sum(1 for item in city_unmatched if not item.get("valid_position_flag", True)),
                    freshness_distribution=freshness_distribution,
                    boundary_status_code="UNKNOWN_CITY" if is_unknown_city else ("AVAILABLE" if has_boundary else "MISSING"),
                    latest_position_time=max([item.position_time for item in city_items if item.position_time], default=None),
                    mmsi_count=(queried_mmsi_count + len(city_unmatched)) if is_unknown_city else len(city_items) + len(city_unmatched),
                    matched_position_count=matched_position_count if is_unknown_city else len(city_items),
                    unpositioned_count=(unpositioned_count + invalid_position_count) if is_unknown_city else 0,
                    is_partial=partial,
                    error_message=error_message,
                )
            )
        missing_position_count = unpositioned_count + invalid_position_count
        if missing_position_count and UNKNOWN_CITY_CODE not in grouped:
            result.append(
                VesselPositionCitySituationItemResponse(
                    city_code=None,
                    city_name=UNKNOWN_CITY_NAME,
                    longitude=None,
                    latitude=None,
                    city_center_longitude=None,
                    city_center_latitude=None,
                    heat_center_longitude=None,
                    heat_center_latitude=None,
                    positioned_count=0,
                    contactable_position_count=0,
                    average_ship_age=None,
                    total_deadweight_ton=Decimal("0"),
                    ship_type_distribution=[],
                    stale_position_count=0,
                    certificate_risk_count=0,
                    unmatched_mmsi_count=0,
                    invalid_position_count=invalid_position_count,
                    freshness_distribution={},
                    boundary_status_code="UNKNOWN_CITY",
                    latest_position_time=None,
                    mmsi_count=queried_mmsi_count,
                    matched_position_count=matched_position_count,
                    unpositioned_count=missing_position_count,
                    is_partial=partial,
                    error_message=error_message,
                )
            )
        return sorted(result, key=lambda item: (item.positioned_count, item.total_deadweight_ton or Decimal("0")), reverse=True)

    @staticmethod
    def _valid_longitude_latitude(longitude: Decimal | None, latitude: Decimal | None) -> bool:
        if longitude is None or latitude is None:
            return False
        return Decimal("-180") <= longitude <= Decimal("180") and Decimal("-90") <= latitude <= Decimal("90")

    async def _city_boundaries(self) -> list[_CityBoundary]:
        now = datetime.utcnow()
        loaded_at = _CITY_BOUNDARY_CACHE.get("loaded_at")
        if loaded_at and (now - loaded_at).total_seconds() < CITY_BOUNDARY_CACHE_TTL_SECONDS:
            return list(_CITY_BOUNDARY_CACHE.get("boundaries") or [])

        rows = (
            await self.db.execute(
                select(AdminRegionBoundary, AdminRegion)
                .join(AdminRegion, AdminRegion.id == AdminRegionBoundary.admin_region_id)
                .where(
                    AdminRegionBoundary.is_current.is_(True),
                    AdminRegion.level == 2,
                    AdminRegion.status == 1,
                )
            )
        ).all()
        boundaries: list[_CityBoundary] = []
        for boundary, region in rows:
            polygons = _extract_geojson_polygons(normalize_boundary_geometry(boundary.geometry_json))
            if not polygons:
                continue
            bbox = _polygons_bbox(polygons)
            if bbox is None:
                continue
            min_x, min_y, max_x, max_y = bbox
            boundary_paths_by_precision = {
                precision: _boundary_paths_for_precision(polygons, precision)
                for precision in CITY_BOUNDARY_SIMPLIFY_TOLERANCE
            }
            boundaries.append(
                _CityBoundary(
                    code=region.code,
                    name=region.name,
                    center_longitude=_to_decimal(boundary.center_longitude if boundary.center_longitude is not None else region.longitude),
                    center_latitude=_to_decimal(boundary.center_latitude if boundary.center_latitude is not None else region.latitude),
                    area_km2=_to_decimal(boundary.area_km2),
                    bbox=bbox,
                    bbox_area=max(0.0, (max_x - min_x) * (max_y - min_y)),
                    polygons=polygons,
                    boundary_paths_by_precision=boundary_paths_by_precision,
                )
            )
        _CITY_BOUNDARY_CACHE["loaded_at"] = now
        _CITY_BOUNDARY_CACHE["boundaries"] = boundaries
        _CITY_BOUNDARY_CACHE["grid_index"] = _build_city_boundary_grid(boundaries)
        return boundaries

    def _city_boundary_paths_by_code(
        self,
        boundaries: list[_CityBoundary],
        precision: str,
    ) -> dict[str, list[list[tuple[float, float]]]]:
        result: dict[str, list[list[tuple[float, float]]]] = {}
        for boundary in boundaries:
            paths = (boundary.boundary_paths_by_precision or {}).get(precision)
            if paths is None:
                paths = _boundary_paths_for_precision(boundary.polygons, precision)
            if paths:
                result[boundary.code] = paths
        return result

    def _city_boundary_version_id(self) -> int | None:
        loaded_at = _CITY_BOUNDARY_CACHE.get("loaded_at")
        return int(loaded_at.timestamp()) if isinstance(loaded_at, datetime) else None

    async def _persist_city_situation_snapshot(
        self,
        *,
        snapshot_id: str,
        query: Any,
        response: VesselPositionCitySituationResponse,
        result: _PositionBuildResult,
        cities: list[VesselPositionCitySituationItemResponse],
        cache_backend: str,
    ) -> None:
        now = datetime.utcnow()
        summary = response.summary
        query_payload = query.model_dump(mode="json") if hasattr(query, "model_dump") else dict(query)
        query_payload = _jsonable(query_payload)
        query_hash = _city_situation_query_cache_key(query)
        status_code = "PARTIAL" if summary.is_partial else "READY"
        expires_at = summary.snapshot_expires_at or (now + timedelta(seconds=_city_snapshot_ttl()))
        await self.db.execute(delete(VesselLatestPositionSnapshot).where(VesselLatestPositionSnapshot.snapshot_id == snapshot_id))
        await self.db.execute(delete(VesselAisCitySnapshotItem).where(VesselAisCitySnapshotItem.snapshot_id == snapshot_id))
        await self.db.execute(delete(VesselAisSnapshot).where(VesselAisSnapshot.snapshot_id == snapshot_id))
        snapshot = VesselAisSnapshot(
            snapshot_id=snapshot_id,
            query_hash=query_hash,
            query_params_json=query_payload,
            status_code=status_code,
            generated_at=response.generated_at,
            expires_at=expires_at,
            cache_backend_code=cache_backend,
            scanned_profile_count=summary.scanned_profile_count,
            queried_mmsi_count=summary.queried_mmsi_count,
            matched_profile_count=summary.matched_profile_count,
            matched_position_count=summary.matched_position_count,
            unmatched_mmsi_count=summary.unmatched_mmsi_count,
            invalid_position_count=summary.invalid_position_count,
            unknown_city_count=summary.unknown_city_count,
            failed_batch_count=summary.failed_batch_count,
            failed_batches_json=summary.failed_batches,
            coverage_rate=summary.coverage_rate,
            freshness_distribution_json=summary.freshness_distribution,
            source_indices_json=summary.source_indices,
            uncertainty_notes_json=summary.uncertainty_notes,
            boundary_version_id=self._city_boundary_version_id(),
            refresh_error=summary.error_message,
            created_at=now,
            updated_at=now,
        )
        self.db.add(snapshot)
        await self.db.flush()
        for city in cities:
            self.db.add(
                VesselAisCitySnapshotItem(
                    snapshot_id=snapshot_id,
                    city_code=city.city_code,
                    city_name=city.city_name,
                    positioned_count=city.positioned_count,
                    matched_position_count=city.matched_position_count,
                    unmatched_mmsi_count=city.unmatched_mmsi_count,
                    invalid_position_count=city.invalid_position_count,
                    stale_position_count=city.stale_position_count,
                    freshness_distribution_json=city.freshness_distribution,
                    boundary_status_code=city.boundary_status_code,
                    has_boundary=city.has_boundary,
                    boundary_precision=city.boundary_precision,
                    latest_position_time=city.latest_position_time,
                    created_at=now,
                )
            )
        for item in result.items:
            self.db.add(
                VesselLatestPositionSnapshot(
                    snapshot_id=snapshot_id,
                    vessel_profile_id=item.id,
                    mmsi=item.current_mmsi,
                    longitude=item.longitude,
                    latitude=item.latitude,
                    speed_kn=item.speed_kn,
                    course_deg=item.course_deg,
                    heading_deg=item.heading_deg,
                    position_time=item.position_time,
                    source_index=item.source_index,
                    freshness_level=item.freshness_level,
                    match_status_code=item.match_status_code,
                    city_code=item.current_city_code or item.city_code,
                    city_name=item.current_city_name or item.city_name,
                    valid_position_flag=True,
                    created_at=now,
                )
            )
        stored_invalid_keys: set[tuple[str, int | None]] = set()
        for position in result.invalid_positions:
            mmsi = str(position.get("mmsi") or "")
            profile_id = position.get("vessel_profile_id")
            stored_invalid_keys.add((mmsi, int(profile_id) if profile_id else None))
            self.db.add(
                VesselLatestPositionSnapshot(
                    snapshot_id=snapshot_id,
                    vessel_profile_id=int(profile_id) if profile_id else None,
                    mmsi=mmsi or "UNKNOWN",
                    longitude=_to_decimal(position.get("longitude")),
                    latitude=_to_decimal(position.get("latitude")),
                    speed_kn=_to_decimal(position.get("speed_kn")),
                    course_deg=_to_decimal(position.get("course_deg")),
                    heading_deg=_to_decimal(position.get("heading_deg")),
                    position_time=position.get("position_time"),
                    source_index=position.get("source_index"),
                    freshness_level=str(position.get("freshness_level") or "UNKNOWN"),
                    match_status_code="INVALID_POSITION",
                    city_code=None,
                    city_name=UNKNOWN_CITY_NAME,
                    valid_position_flag=False,
                    created_at=now,
                )
            )
        for position in result.unmatched_positions:
            mmsi = str(position.get("mmsi") or "")
            key = (mmsi, None)
            if key in stored_invalid_keys:
                continue
            self.db.add(
                VesselLatestPositionSnapshot(
                    snapshot_id=snapshot_id,
                    vessel_profile_id=None,
                    mmsi=mmsi or "UNKNOWN",
                    longitude=_to_decimal(position.get("longitude")),
                    latitude=_to_decimal(position.get("latitude")),
                    speed_kn=_to_decimal(position.get("speed_kn")),
                    course_deg=_to_decimal(position.get("course_deg")),
                    heading_deg=_to_decimal(position.get("heading_deg")),
                    position_time=position.get("position_time"),
                    source_index=position.get("source_index"),
                    freshness_level=str(position.get("freshness_level") or "UNKNOWN"),
                    match_status_code=str(position.get("match_status_code") or "UNMATCHED_MMSI"),
                    city_code=position.get("city_code"),
                    city_name=position.get("city_name"),
                    valid_position_flag=bool(position.get("valid_position_flag", True)),
                    created_at=now,
                )
            )
        await self.db.flush()

    async def _discard_city_situation_snapshot(self, snapshot_id: str) -> None:
        _CITY_SITUATION_SNAPSHOTS.pop(snapshot_id, None)
        if _city_cache_backend_setting() != "redis" or Redis is None:
            return
        try:
            redis_client = await self._city_redis()
            if redis_client is not None:
                await redis_client.delete(CITY_SITUATION_SNAPSHOT_KEY_PREFIX + snapshot_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("city situation redis snapshot discard failed: %s", exc)

    async def _restore_city_situation_snapshot_from_db(self, snapshot_id: str) -> _CitySituationSnapshot | None:
        snapshot = await self.db.scalar(select(VesselAisSnapshot).where(VesselAisSnapshot.snapshot_id == snapshot_id))
        if snapshot is None:
            return None
        if snapshot.expires_at <= datetime.utcnow():
            return _CitySituationSnapshot(
                snapshot_id=snapshot.snapshot_id,
                expires_at=snapshot.expires_at,
                items=[],
                partial=snapshot.status_code == "PARTIAL",
                error_message=snapshot.refresh_error or "SNAPSHOT_EXPIRED",
                generated_at=snapshot.generated_at,
                status_code="EXPIRED",
                refresh_required=True,
            )
        rows = (
            await self.db.execute(
                select(VesselLatestPositionSnapshot).where(
                    VesselLatestPositionSnapshot.snapshot_id == snapshot_id,
                    VesselLatestPositionSnapshot.vessel_profile_id.is_not(None),
                    VesselLatestPositionSnapshot.valid_position_flag.is_(True),
                )
            )
        ).scalars().all()
        profile_ids = [int(row.vessel_profile_id) for row in rows if row.vessel_profile_id is not None]
        profiles = list((await self.db.execute(select(VesselProfile).where(VesselProfile.id.in_(profile_ids)))).scalars().all()) if profile_ids else []
        base_items = {item.id: item for item in await self._build_list_items(profiles)}
        items: list[VesselPositionMonitorItemResponse] = []
        for row in rows:
            base = base_items.get(int(row.vessel_profile_id or 0))
            if base is None:
                continue
            items.append(
                VesselPositionMonitorItemResponse(
                    **base.model_dump(),
                    longitude=row.longitude,
                    latitude=row.latitude,
                    speed_kn=row.speed_kn,
                    course_deg=row.course_deg,
                    heading_deg=row.heading_deg,
                    position_time=row.position_time,
                    position_age_minutes=int((snapshot.generated_at - row.position_time).total_seconds() // 60) if row.position_time else None,
                    city_code=row.city_code,
                    city_name=row.city_name,
                    current_city_code=row.city_code,
                    current_city_name=row.city_name,
                    current_city_source=CURRENT_CITY_SOURCE_ADMIN_BOUNDARY if row.city_code else CURRENT_CITY_SOURCE_UNKNOWN,
                    location_text=None,
                    position_source_name="实时 ES",
                    source_index=row.source_index,
                    freshness_level=row.freshness_level,
                    match_status_code=row.match_status_code,
                )
            )
        return _CitySituationSnapshot(
            snapshot_id=snapshot.snapshot_id,
            expires_at=snapshot.expires_at,
            items=items,
            partial=snapshot.status_code == "PARTIAL",
            error_message=snapshot.refresh_error,
            generated_at=snapshot.generated_at,
            status_code=snapshot.status_code,
            refresh_required=False,
        )

    def _resolve_current_city_from_boundaries(
        self,
        longitude: Decimal | None,
        latitude: Decimal | None,
        boundaries: list[_CityBoundary],
        grid_index: dict[tuple[int, int], list[_CityBoundary]] | None = None,
    ) -> _ResolvedCity:
        if not self._valid_longitude_latitude(longitude, latitude):
            return _ResolvedCity(None, UNKNOWN_CITY_NAME, CURRENT_CITY_SOURCE_INVALID_POSITION)
        lon = float(longitude)
        lat = float(latitude)
        candidates = grid_index.get(_grid_key(lon, lat), boundaries) if grid_index else boundaries
        matches = [
            boundary for boundary in candidates
            if _bbox_contains(boundary.bbox, lon, lat)
            and any(_point_in_polygon_with_holes(lon, lat, polygon) for polygon in boundary.polygons)
        ]
        if not matches:
            return _ResolvedCity(None, UNKNOWN_CITY_NAME, CURRENT_CITY_SOURCE_UNKNOWN)
        matches.sort(key=lambda item: (item.area_km2 if item.area_km2 is not None else Decimal("999999999"), Decimal(str(item.bbox_area))))
        selected = matches[0]
        candidates: list[dict[str, Any]] | None = None
        if len(matches) > 1:
            candidates = [
                {
                    "city_code": item.code,
                    "city_name": item.name,
                    "area_km2": str(item.area_km2) if item.area_km2 is not None else None,
                    "bbox_area": item.bbox_area,
                }
                for item in matches
            ]
            logger.warning(
                "vessel position matched multiple city boundaries: longitude=%s latitude=%s candidates=%s selected=%s",
                longitude,
                latitude,
                candidates,
                selected.code,
            )
        return _ResolvedCity(
            selected.code,
            selected.name,
            CURRENT_CITY_SOURCE_ADMIN_BOUNDARY,
            selected.center_longitude,
            selected.center_latitude,
            candidates,
        )

    async def _store_city_situation_snapshot(
        self,
        items: list[VesselPositionMonitorItemResponse],
        *,
        generated_at: datetime,
        partial: bool,
        error_message: str | None,
    ) -> str:
        now = datetime.utcnow()
        ttl_seconds = _city_snapshot_ttl()
        expired = [key for key, value in _CITY_SITUATION_SNAPSHOTS.items() if value.expires_at <= now]
        for key in expired:
            _CITY_SITUATION_SNAPSHOTS.pop(key, None)
        while len(_CITY_SITUATION_SNAPSHOTS) >= CITY_SITUATION_SNAPSHOT_MAX_SIZE:
            oldest_key = min(_CITY_SITUATION_SNAPSHOTS, key=lambda key: _CITY_SITUATION_SNAPSHOTS[key].expires_at)
            _CITY_SITUATION_SNAPSHOTS.pop(oldest_key, None)
        snapshot_id = uuid.uuid4().hex
        shared_required = _city_shared_cache_required()
        snapshot = _CitySituationSnapshot(
            snapshot_id=snapshot_id,
            expires_at=now + timedelta(seconds=ttl_seconds),
            items=list(items),
            partial=partial,
            error_message=error_message,
            generated_at=generated_at,
            status_code="PARTIAL" if partial else "READY",
        )
        if not shared_required:
            _CITY_SITUATION_SNAPSHOTS[snapshot_id] = snapshot
        if await self._city_cache_backend() == "redis":
            try:
                redis_client = await self._city_redis()
                if redis_client is not None:
                    payload = json.dumps(
                        {
                            "snapshot_id": snapshot.snapshot_id,
                            "expires_at": snapshot.expires_at.isoformat(),
                            "items": [item.model_dump(mode="json") for item in snapshot.items],
                            "partial": snapshot.partial,
                            "error_message": snapshot.error_message,
                            "generated_at": snapshot.generated_at.isoformat(),
                            "status_code": snapshot.status_code,
                        },
                        ensure_ascii=False,
                        default=str,
                    )
                    await redis_client.setex(CITY_SITUATION_SNAPSHOT_KEY_PREFIX + snapshot_id, ttl_seconds, payload)
            except Exception as exc:  # noqa: BLE001
                logger.warning("city situation redis snapshot write failed: %s", exc)
        return snapshot_id

    async def _get_city_situation_snapshot(self, snapshot_id: str | None) -> _CitySituationSnapshot | None:
        if not snapshot_id:
            return None
        shared_required = _city_shared_cache_required()
        if not shared_required:
            snapshot = _CITY_SITUATION_SNAPSHOTS.get(snapshot_id)
            if snapshot is not None:
                if snapshot.expires_at <= datetime.utcnow():
                    _CITY_SITUATION_SNAPSHOTS.pop(snapshot_id, None)
                else:
                    return snapshot
        if await self._city_cache_backend() == "redis":
            try:
                redis_client = await self._city_redis()
                payload = await redis_client.get(CITY_SITUATION_SNAPSHOT_KEY_PREFIX + snapshot_id) if redis_client else None
                if payload:
                    data = json.loads(payload)
                    restored = _CitySituationSnapshot(
                        snapshot_id=str(data["snapshot_id"]),
                        expires_at=datetime.fromisoformat(str(data["expires_at"])),
                        items=[VesselPositionMonitorItemResponse.model_validate(item) for item in data.get("items") or []],
                        partial=bool(data.get("partial")),
                        error_message=data.get("error_message"),
                        generated_at=datetime.fromisoformat(str(data["generated_at"])),
                        status_code=str(data.get("status_code") or ("PARTIAL" if data.get("partial") else "READY")),
                    )
                    if restored.expires_at > datetime.utcnow():
                        if not shared_required:
                            _CITY_SITUATION_SNAPSHOTS[snapshot_id] = restored
                        return restored
                    return _CitySituationSnapshot(
                        snapshot_id=restored.snapshot_id,
                        expires_at=restored.expires_at,
                        items=[],
                        partial=restored.partial,
                        error_message="SNAPSHOT_EXPIRED",
                        generated_at=restored.generated_at,
                        status_code="EXPIRED",
                        refresh_required=True,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("city situation redis snapshot read failed: %s", exc)
        return await self._restore_city_situation_snapshot_from_db(snapshot_id)

    def _empty_position_response(
        self,
        generated_at: datetime,
        message: str,
        matched_count: int = 0,
    ) -> VesselPositionMonitorResponse:
        return VesselPositionMonitorResponse(
            source_status="EMPTY",
            source_status_name=_source_status_name("EMPTY"),
            generated_at=generated_at,
            message=message,
            summary=VesselPositionMonitorSummary(
                matched_profile_count=matched_count,
                positioned_count=0,
                stale_position_count=0,
                contactable_position_count=0,
            ),
            items=[],
        )

    async def _certificates_by_profile(self, ids: list[int]) -> dict[int, list[VesselCertificate]]:
        if not ids:
            return {}
        rows = (
            await self.db.execute(select(VesselCertificate).where(VesselCertificate.vessel_profile_id.in_(ids)))
        ).scalars().all()
        result: dict[int, list[VesselCertificate]] = defaultdict(list)
        for row in rows:
            result[row.vessel_profile_id].append(row)
        return result

    async def _certificates_with_files(
        self,
        vessel_id: int,
        *,
        certificate_id: int | None = None,
        label_map: dict[str, dict[str, str]] | None = None,
    ) -> list[VesselCertificateResponse]:
        label_map = label_map or await _load_label_map(self.db)
        stmt = select(VesselCertificate).where(
            VesselCertificate.vessel_profile_id == vessel_id,
            VesselCertificate.voided_at.is_(None),
        )
        if certificate_id:
            stmt = stmt.where(VesselCertificate.id == certificate_id)
        certs = (await self.db.execute(stmt.order_by(VesselCertificate.id.desc()))).scalars().all()
        if not certs:
            return []
        files = (
            await self.db.execute(
                select(VesselCertificateFile).where(
                    VesselCertificateFile.vessel_certificate_id.in_([row.id for row in certs]),
                    VesselCertificateFile.voided_at.is_(None),
                )
            )
        ).scalars().all()
        file_map: dict[int, list[VesselCertificateFileResponse]] = defaultdict(list)
        for item in files:
            file_map[item.vessel_certificate_id].append(self._file_response(item))
        recognition_rows = (
            await self.db.execute(
                select(VesselCertificateImageRecognition)
                .where(VesselCertificateImageRecognition.vessel_certificate_id.in_([row.id for row in certs]))
                .order_by(VesselCertificateImageRecognition.id.desc())
            )
        ).scalars().all()
        latest_recognition_map: dict[int, VesselCertificateImageRecognition] = {}
        current_recognition_map: dict[int, VesselCertificateImageRecognition] = {}
        latest_confirmed_recognition_map: dict[int, VesselCertificateImageRecognition] = {}
        has_recognition_history: set[int] = set()
        for row in recognition_rows:
            has_recognition_history.add(row.vessel_certificate_id)
            if row.vessel_certificate_id not in latest_recognition_map:
                latest_recognition_map[row.vessel_certificate_id] = row
                if row.status_code in CURRENT_RECOGNITION_STATUSES:
                    current_recognition_map[row.vessel_certificate_id] = row
            if row.status_code == "CONFIRMED":
                latest_confirmed_recognition_map.setdefault(row.vessel_certificate_id, row)
        return [
            self._certificate_response(
                cert,
                files=file_map.get(cert.id, []),
                label_map=label_map,
                latest_recognition=latest_recognition_map.get(cert.id),
                current_recognition=current_recognition_map.get(cert.id),
                latest_confirmed_recognition=latest_confirmed_recognition_map.get(cert.id),
                has_recognition_history=cert.id in has_recognition_history,
            )
            for cert in certs
        ]

    def _file_response(self, row: VesselCertificateFile) -> VesselCertificateFileResponse:
        return VesselCertificateFileResponse(**_row_dict(row), download_url=f"/api/v1/files/{row.storage_file_id}/content")

    async def _person_certificates_with_files(
        self,
        vessel_id: int,
        *,
        person_certificate_id: int | None = None,
        label_map: dict[str, dict[str, str]] | None = None,
    ) -> list[VesselPersonCertificateResponse]:
        label_map = label_map or await _load_label_map(self.db)
        stmt = select(VesselPersonCertificate).where(
            VesselPersonCertificate.vessel_profile_id == vessel_id,
            VesselPersonCertificate.voided_at.is_(None),
        )
        if person_certificate_id:
            stmt = stmt.where(VesselPersonCertificate.id == person_certificate_id)
        certs = (await self.db.execute(stmt.order_by(VesselPersonCertificate.id.desc()))).scalars().all()
        if not certs:
            return []
        files = (
            await self.db.execute(
                select(VesselPersonCertificateFile).where(
                    VesselPersonCertificateFile.vessel_person_certificate_id.in_([row.id for row in certs]),
                    VesselPersonCertificateFile.voided_at.is_(None),
                )
            )
        ).scalars().all()
        file_map: dict[int, list[VesselPersonCertificateFileResponse]] = defaultdict(list)
        for item in files:
            file_map[item.vessel_person_certificate_id].append(self._person_file_response(item))
        recognition_rows = (
            await self.db.execute(
                select(VesselPersonCertificateImageRecognition)
                .where(
                    VesselPersonCertificateImageRecognition.vessel_person_certificate_id.in_(
                        [row.id for row in certs]
                    )
                )
                .order_by(VesselPersonCertificateImageRecognition.id.desc())
            )
        ).scalars().all()
        latest_recognition_map: dict[int, VesselPersonCertificateImageRecognition] = {}
        current_recognition_map: dict[int, VesselPersonCertificateImageRecognition] = {}
        latest_confirmed_recognition_map: dict[int, VesselPersonCertificateImageRecognition] = {}
        has_recognition_history: set[int] = set()
        for row in recognition_rows:
            has_recognition_history.add(row.vessel_person_certificate_id)
            if row.vessel_person_certificate_id not in latest_recognition_map:
                latest_recognition_map[row.vessel_person_certificate_id] = row
                if row.status_code in CURRENT_RECOGNITION_STATUSES:
                    current_recognition_map[row.vessel_person_certificate_id] = row
            if row.status_code == "CONFIRMED":
                latest_confirmed_recognition_map.setdefault(row.vessel_person_certificate_id, row)
        return [
            self._person_certificate_response(
                cert,
                label_map,
                files=file_map.get(cert.id, []),
                latest_recognition=latest_recognition_map.get(cert.id),
                current_recognition=current_recognition_map.get(cert.id),
                latest_confirmed_recognition=latest_confirmed_recognition_map.get(cert.id),
                has_recognition_history=cert.id in has_recognition_history,
            )
            for cert in certs
        ]

    def _person_file_response(self, row: VesselPersonCertificateFile) -> VesselPersonCertificateFileResponse:
        return VesselPersonCertificateFileResponse(
            **_row_dict(row),
            download_url=f"/api/v1/files/{row.storage_file_id}/content",
        )

    async def _latest_owner_document_recognition(self, owner_document_id: int) -> VesselOwnerDocumentImageRecognition | None:
        return await self.db.scalar(
            select(VesselOwnerDocumentImageRecognition)
            .where(VesselOwnerDocumentImageRecognition.owner_document_id == owner_document_id)
            .order_by(VesselOwnerDocumentImageRecognition.created_at.desc(), VesselOwnerDocumentImageRecognition.id.desc())
        )

    async def _owner_documents_by_owner(
        self,
        vessel_id: int,
        label_map: dict[str, dict[str, str]],
    ) -> dict[int, list[VesselOwnerDocumentResponse]]:
        docs = [row for row in await self.repo.list_owner_documents(vessel_id) if row.voided_at is None]
        if not docs:
            return {}
        recognition_rows = (
            await self.db.execute(
                select(VesselOwnerDocumentImageRecognition)
                .where(VesselOwnerDocumentImageRecognition.owner_document_id.in_([row.id for row in docs]))
                .order_by(VesselOwnerDocumentImageRecognition.created_at.desc(), VesselOwnerDocumentImageRecognition.id.desc())
            )
        ).scalars().all()
        latest_recognition_map: dict[int, VesselOwnerDocumentImageRecognition] = {}
        current_recognition_map: dict[int, VesselOwnerDocumentImageRecognition] = {}
        latest_confirmed_recognition_map: dict[int, VesselOwnerDocumentImageRecognition] = {}
        has_recognition_history: set[int] = set()
        for row in recognition_rows:
            has_recognition_history.add(row.owner_document_id)
            if row.owner_document_id not in latest_recognition_map:
                latest_recognition_map[row.owner_document_id] = row
                if row.status_code in CURRENT_RECOGNITION_STATUSES:
                    current_recognition_map[row.owner_document_id] = row
            if row.status_code == "CONFIRMED":
                latest_confirmed_recognition_map.setdefault(row.owner_document_id, row)
        result: dict[int, list[VesselOwnerDocumentResponse]] = defaultdict(list)
        for row in docs:
            result[row.vessel_owner_period_id].append(
                self._owner_document_response(
                    row,
                    label_map,
                    latest_recognition=latest_recognition_map.get(row.id),
                    current_recognition=current_recognition_map.get(row.id),
                    latest_confirmed_recognition=latest_confirmed_recognition_map.get(row.id),
                    has_recognition_history=row.id in has_recognition_history,
                )
            )
        return result

    def _owner_document_response(
        self,
        row: VesselOwnerDocument,
        label_map: dict[str, dict[str, str]],
        *,
        latest_recognition: VesselOwnerDocumentImageRecognition | None = None,
        current_recognition: VesselOwnerDocumentImageRecognition | None = None,
        latest_confirmed_recognition: VesselOwnerDocumentImageRecognition | None = None,
        has_recognition_history: bool = False,
    ) -> VesselOwnerDocumentResponse:
        return VesselOwnerDocumentResponse(
            **_row_dict(row),
            document_type_name=label_map.get("OWNER_DOCUMENT_TYPE", {}).get(row.document_type_code),
            download_url=f"/api/v1/files/{row.storage_file_id}/content",
            latest_image_recognition=(
                self._owner_document_image_recognition_response(latest_recognition, label_map)
                if latest_recognition is not None
                else None
            ),
            current_image_recognition=(
                self._owner_document_image_recognition_response(current_recognition, label_map)
                if current_recognition is not None
                else None
            ),
            latest_confirmed_image_recognition=(
                self._owner_document_image_recognition_response(latest_confirmed_recognition, label_map)
                if latest_confirmed_recognition is not None
                else None
            ),
            has_recognition_history=has_recognition_history,
        )

    def _owner_document_image_recognition_response(
        self,
        row: VesselOwnerDocumentImageRecognition,
        label_map: dict[str, dict[str, str]],
    ) -> VesselOwnerDocumentImageRecognitionResponse:
        return VesselOwnerDocumentImageRecognitionResponse(
            **_row_dict(row),
            status_name=label_map.get("VESSEL_CERTIFICATE_IMAGE_RECOGNITION_STATUS", {}).get(row.status_code),
        )

    def _owner_response(
        self,
        row: VesselOwnerPeriod,
        label_map: dict[str, dict[str, str]],
        *,
        documents: list[VesselOwnerDocumentResponse] | None = None,
    ) -> VesselOwnerResponse:
        document_list = documents or []
        return VesselOwnerResponse(
            **_row_dict(row),
            party_type_name=label_map.get("PARTY_SUBJECT_TYPE", {}).get(row.party_type_code),
            verified_status_name=label_map.get("VESSEL_RELATION_VERIFIED_STATUS", {}).get(row.verified_status_code),
            source_type_name=label_map.get("SOURCE_TYPE", {}).get(row.source_type_code),
            documents=document_list,
            document_ledger=self._owner_document_ledger(row, document_list, label_map),
            document_completeness=self._owner_document_completeness(row, document_list),
        )

    def _owner_required_document_types(self, row: VesselOwnerPeriod) -> set[str]:
        return OWNER_REQUIRED_DOCUMENT_TYPES_BY_PARTY.get(row.party_type_code or "UNKNOWN", set())

    def _owner_document_ledger(
        self,
        owner: VesselOwnerPeriod,
        documents: list[VesselOwnerDocumentResponse],
        label_map: dict[str, dict[str, str]],
    ) -> list[VesselOwnerDocumentLedgerItemResponse]:
        required_types = self._owner_required_document_types(owner)
        doc_by_type: dict[str, VesselOwnerDocumentResponse] = {}
        for document in documents:
            doc_by_type.setdefault(document.document_type_code, document)
        types = [code for code in OWNER_DOCUMENT_LEDGER_TYPES if code in required_types or code in doc_by_type or code not in {"OTHER"}]
        if "OTHER" in doc_by_type:
            types.append("OTHER")
        result: list[VesselOwnerDocumentLedgerItemResponse] = []
        for code in dict.fromkeys(types):
            document = doc_by_type.get(code)
            status = self._owner_document_ledger_status(owner, document)
            result.append(
                VesselOwnerDocumentLedgerItemResponse(
                    document_type_code=code,
                    document_type_name=label_map.get("OWNER_DOCUMENT_TYPE", {}).get(code),
                    required=code in required_types,
                    status_code=status,
                    status_name=self._owner_document_ledger_status_name(status),
                    document=document,
                )
            )
        return result

    def _owner_document_ledger_status(
        self,
        owner: VesselOwnerPeriod,
        document: VesselOwnerDocumentResponse | None,
    ) -> str:
        if owner.party_type_code not in OWNER_REQUIRED_DOCUMENT_TYPES_BY_PARTY:
            return "UNKNOWN_OWNER_TYPE"
        if document is None:
            return "MISSING"
        current = document.current_image_recognition
        if current is not None and current.status_code == "NEED_CONFIRM":
            return "NEED_CONFIRM"
        if current is not None and current.status_code in ACTIVE_RECOGNITION_STATUSES:
            return current.status_code
        if current is not None and current.status_code == "FAILED":
            return "RECOGNITION_FAILED"
        if document.latest_confirmed_image_recognition is not None:
            return "CONFIRMED"
        return "ARCHIVED"

    def _owner_document_ledger_status_name(self, status: str) -> str:
        return {
            "UNKNOWN_OWNER_TYPE": "主体类型未确认",
            "MISSING": "缺失",
            "ARCHIVED": "已归档",
            "QUEUED": "排队识别",
            "PROCESSING": "识别中",
            "NEED_CONFIRM": "待确认",
            "RECOGNITION_FAILED": "识别失败",
            "CONFIRMED": "已确认",
        }.get(status, status)

    def _owner_document_completeness(
        self,
        owner: VesselOwnerPeriod,
        documents: list[VesselOwnerDocumentResponse],
    ) -> VesselOwnerDocumentCompletenessResponse:
        required_types = self._owner_required_document_types(owner)
        if not required_types:
            return VesselOwnerDocumentCompletenessResponse(
                status_code="UNKNOWN_OWNER_TYPE",
                status_name="主体类型未确认",
                required_count=0,
                completed_count=0,
                missing_document_type_codes=[],
                message="主体类型未确认，无法计算资料完整度",
            )
        existing_types = {document.document_type_code for document in documents}
        missing = sorted(required_types - existing_types)
        return VesselOwnerDocumentCompletenessResponse(
            status_code="COMPLETE" if not missing else "INCOMPLETE",
            status_name="资料完整" if not missing else "资料缺失",
            required_count=len(required_types),
            completed_count=len(required_types) - len(missing),
            missing_document_type_codes=missing,
            message=None if not missing else "缺少必备所有方证照",
        )

    def _operator_response(self, row: VesselOperatorPeriod, label_map: dict[str, dict[str, str]]) -> VesselOperatorResponse:
        return VesselOperatorResponse(
            **_row_dict(row),
            party_type_name=label_map.get("PARTY_SUBJECT_TYPE", {}).get(row.party_type_code),
            verified_status_name=label_map.get("VESSEL_RELATION_VERIFIED_STATUS", {}).get(row.verified_status_code),
            source_type_name=label_map.get("SOURCE_TYPE", {}).get(row.source_type_code),
        )

    def _contact_response(self, row: VesselContact, label_map: dict[str, dict[str, str]]) -> VesselContactResponse:
        return VesselContactResponse(
            **_row_dict(row),
            contact_scope_name=label_map.get("CONTACT_SCOPE", {}).get(row.contact_scope_code),
            contact_role_name=label_map.get("CONTACT_ROLE", {}).get(row.contact_role_code),
            verified_status_name=label_map.get("VESSEL_RELATION_VERIFIED_STATUS", {}).get(row.verified_status_code),
            source_type_name=label_map.get("SOURCE_TYPE", {}).get(row.source_type_code),
        )

    def _crew_response(self, row: VesselCrewAssignment, label_map: dict[str, dict[str, str]]) -> VesselCrewResponse:
        return VesselCrewResponse(
            **_row_dict(row),
            crew_role_name=label_map.get("VESSEL_CREW_ROLE", {}).get(row.crew_role_code),
            verified_status_name=label_map.get("VESSEL_RELATION_VERIFIED_STATUS", {}).get(row.verified_status_code),
            source_type_name=label_map.get("SOURCE_TYPE", {}).get(row.source_type_code),
        )

    def _person_certificate_response(
        self,
        row: VesselPersonCertificate,
        label_map: dict[str, dict[str, str]],
        *,
        files: list[VesselPersonCertificateFileResponse] | None = None,
        latest_recognition: VesselPersonCertificateImageRecognition | None = None,
        current_recognition: VesselPersonCertificateImageRecognition | None = None,
        latest_confirmed_recognition: VesselPersonCertificateImageRecognition | None = None,
        has_recognition_history: bool = False,
    ) -> VesselPersonCertificateResponse:
        return VesselPersonCertificateResponse(
            **_row_dict(row),
            certificate_type_name=label_map.get("CREW_CERTIFICATE_TYPE", {}).get(row.certificate_type_code)
            or label_map.get("CERTIFICATE_TYPE", {}).get(row.certificate_type_code),
            verify_status_name=label_map.get("CERTIFICATE_VERIFY_STATUS", {}).get(row.verify_status_code),
            source_type_name=label_map.get("SOURCE_TYPE", {}).get(row.source_type_code),
            files=files or [],
            latest_image_recognition=(
                self._person_image_recognition_response(latest_recognition, label_map)
                if latest_recognition is not None
                else None
            ),
            current_image_recognition=(
                self._person_image_recognition_response(current_recognition, label_map)
                if current_recognition is not None
                else None
            ),
            latest_confirmed_image_recognition=(
                self._person_image_recognition_response(latest_confirmed_recognition, label_map)
                if latest_confirmed_recognition is not None
                else None
            ),
            has_recognition_history=has_recognition_history,
        )

    def _image_recognition_response(
        self,
        row: VesselCertificateImageRecognition,
        label_map: dict[str, dict[str, str]],
    ) -> VesselCertificateImageRecognitionResponse:
        return VesselCertificateImageRecognitionResponse(
            **_row_dict(row),
            status_name=label_map.get("VESSEL_CERTIFICATE_IMAGE_RECOGNITION_STATUS", {}).get(row.status_code),
        )

    def _person_image_recognition_response(
        self,
        row: VesselPersonCertificateImageRecognition,
        label_map: dict[str, dict[str, str]],
    ) -> VesselPersonCertificateImageRecognitionResponse:
        return VesselPersonCertificateImageRecognitionResponse(
            **_row_dict(row),
            status_name=label_map.get("VESSEL_CERTIFICATE_IMAGE_RECOGNITION_STATUS", {}).get(row.status_code),
        )

    def _certificate_response(
        self,
        row: VesselCertificate,
        *,
        files: list[VesselCertificateFileResponse],
        label_map: dict[str, dict[str, str]],
        latest_recognition: VesselCertificateImageRecognition | None = None,
        current_recognition: VesselCertificateImageRecognition | None = None,
        latest_confirmed_recognition: VesselCertificateImageRecognition | None = None,
        has_recognition_history: bool = False,
    ) -> VesselCertificateResponse:
        recognition_status = current_recognition.status_code if current_recognition is not None else "NOT_STARTED"
        confirmation_status = "CONFIRMED" if latest_confirmed_recognition is not None else "UNCONFIRMED"
        return VesselCertificateResponse(
            **_row_dict(row),
            certificate_type_name=label_map.get("VESSEL_CERTIFICATE_TYPE", {}).get(row.certificate_type_code)
            or label_map.get("CERTIFICATE_TYPE", {}).get(row.certificate_type_code),
            verify_status_name=label_map.get("CERTIFICATE_VERIFY_STATUS", {}).get(row.verify_status_code),
            recognition_status_code=recognition_status,
            recognition_status_name=label_map.get("VESSEL_CERTIFICATE_IMAGE_RECOGNITION_STATUS", {}).get(recognition_status),
            confirmation_status_code=confirmation_status,
            confirmation_status_name=label_map.get("VESSEL_CERTIFICATE_IMAGE_RECOGNITION_STATUS", {}).get(confirmation_status),
            files=files,
            latest_image_recognition=(
                self._image_recognition_response(latest_recognition, label_map) if latest_recognition is not None else None
            ),
            current_image_recognition=(
                self._image_recognition_response(current_recognition, label_map) if current_recognition is not None else None
            ),
            latest_confirmed_image_recognition=(
                self._image_recognition_response(latest_confirmed_recognition, label_map)
                if latest_confirmed_recognition is not None
                else None
            ),
            has_recognition_history=has_recognition_history,
        )

    async def _require_relation_row(self, model: type[Any], vessel_id: int, row_id: int) -> Any:
        row = await self.db.get(model, row_id)
        if row is None or getattr(row, "vessel_profile_id", None) != vessel_id:
            raise NotFoundError(model.__name__, row_id)
        return row

    def _ensure_revision(self, row: Any, revision: int | None) -> None:
        if revision is None:
            raise ValidationError("revision is required")
        if int(getattr(row, "revision", 1)) != int(revision):
            raise ConflictError(
                "记录 revision 已变化，请刷新后重试",
                code="REVISION_CONFLICT",
                detail={"id": getattr(row, "id", None), "current_revision": getattr(row, "revision", None)},
            )

    async def _create_relation(
        self,
        model: type[Any],
        vessel_id: int,
        data: dict[str, Any],
        *,
        event_type_code: str,
        event_title: str,
        operator_id: int | None,
    ) -> tuple[Any, list[int], int]:
        wants_primary = bool(data.get("is_primary", False)) and hasattr(model, "is_primary")
        data.setdefault("revision", 1)
        data.setdefault("verified_status_code", "UNVERIFIED")
        data.setdefault("source_type_code", "MANUAL")
        row = model(vessel_profile_id=vessel_id, **data)
        self.db.add(row)
        await self.db.flush()
        cancelled_ids: list[int] = []
        if wants_primary:
            cancelled_ids = await self._cancel_other_primaries(model, vessel_id, int(row.id))
        after = _row_dict(row)
        event_id = await self._add_change_event(
            vessel_id,
            event_type_code,
            event_title,
            None,
            {"row": after, "cancelled_primary_ids": cancelled_ids},
            operator_id,
            object_type=model.__tablename__,
            object_id=row.id,
        )
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        return row, cancelled_ids, event_id

    async def _update_relation(
        self,
        model: type[Any],
        vessel_id: int,
        row_id: int,
        payload: Any,
        *,
        event_type_code: str,
        event_title: str,
        operator_id: int | None,
    ) -> tuple[Any, int]:
        await self._require_profile(vessel_id)
        row = await self._require_relation_row(model, vessel_id, row_id)
        _ensure_relation_writable(row)
        updates = payload.model_dump(exclude_none=True)
        revision = updates.pop("revision", None)
        reason = updates.pop("reason", None)
        self._ensure_revision(row, revision)
        if not updates:
            raise ValidationError("no update fields provided")
        before = _row_dict(row)
        for key, value in updates.items():
            setattr(row, key, value)
        row.revision = int(row.revision or 1) + 1
        event_id = await self._add_change_event(
            vessel_id,
            event_type_code,
            event_title,
            before,
            _row_dict(row),
            operator_id,
            object_type=model.__tablename__,
            object_id=row.id,
            reason=reason,
        )
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        return row, event_id

    async def _end_relation(
        self,
        model: type[Any],
        vessel_id: int,
        row_id: int,
        payload: Any,
        *,
        event_type_code: str,
        event_title: str,
        operator_id: int | None,
    ) -> tuple[Any, int]:
        await self._require_profile(vessel_id)
        row = await self._require_relation_row(model, vessel_id, row_id)
        self._ensure_revision(row, payload.revision)
        _ensure_relation_writable(row)
        before = _row_dict(row)
        row.end_date = payload.end_date or date.today()
        row.is_current = False
        if hasattr(row, "is_primary"):
            row.is_primary = False
        row.revision = int(row.revision or 1) + 1
        event_id = await self._add_change_event(
            vessel_id,
            event_type_code,
            event_title,
            before,
            _row_dict(row),
            operator_id,
            object_type=model.__tablename__,
            object_id=row.id,
            reason=payload.reason,
        )
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        return row, event_id

    async def _void_relation(
        self,
        model: type[Any],
        vessel_id: int,
        row_id: int,
        payload: Any,
        *,
        event_type_code: str,
        event_title: str,
        operator_id: int | None,
    ) -> tuple[Any, int]:
        await self._require_profile(vessel_id)
        row = await self._require_relation_row(model, vessel_id, row_id)
        self._ensure_revision(row, payload.revision)
        _ensure_relation_writable(row, require_current=False)
        before = _row_dict(row)
        row.voided_at = datetime.utcnow()
        row.voided_by = operator_id
        row.void_reason = payload.reason or "关系作废"
        row.is_current = False
        if hasattr(row, "is_primary"):
            row.is_primary = False
        row.revision = int(row.revision or 1) + 1
        event_id = await self._add_change_event(
            vessel_id,
            event_type_code,
            event_title,
            before,
            _row_dict(row),
            operator_id,
            object_type=model.__tablename__,
            object_id=row.id,
            reason=payload.reason,
        )
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        return row, event_id

    async def _cancel_other_primaries(self, model: type[Any], vessel_id: int, target_id: int) -> list[int]:
        rows = (
            await self.db.execute(
                select(model).where(
                    model.vessel_profile_id == vessel_id,
                    model.id != target_id,
                    model.is_primary.is_(True),
                    model.is_current.is_(True),
                    model.voided_at.is_(None),
                )
            )
        ).scalars().all()
        cancelled_ids: list[int] = []
        for row in rows:
            row.is_primary = False
            row.revision = int(row.revision or 1) + 1
            cancelled_ids.append(int(row.id))
        return cancelled_ids

    async def _set_primary_relation(
        self,
        model: type[Any],
        vessel_id: int,
        row_id: int,
        payload: Any,
        *,
        event_type_code: str,
        event_title: str,
        operator_id: int | None,
    ) -> tuple[Any, list[int], int | None]:
        await self._require_profile(vessel_id)
        row = await self._require_relation_row(model, vessel_id, row_id)
        self._ensure_revision(row, payload.revision)
        if not _relation_is_effective(row):
            _ensure_relation_writable(row)
            raise ConflictError(
                "只能将当前有效关系设置为主关系",
                code="RELATION_NOT_CURRENT",
                detail={"id": getattr(row, "id", None)},
            )
        primary_rows = (
            await self.db.execute(
                select(model).where(
                    model.vessel_profile_id == vessel_id,
                    model.is_primary.is_(True),
                    model.is_current.is_(True),
                    model.voided_at.is_(None),
                    model.end_date.is_(None),
                )
            )
        ).scalars().all()
        if row.is_primary and len(primary_rows) == 1 and int(primary_rows[0].id) == int(row.id):
            await self.db.commit()
            return row, [], None
        before = {"target": _row_dict(row), "primaries": [_row_dict(item) for item in primary_rows]}
        cancelled_ids = await self._cancel_other_primaries(model, vessel_id, int(row.id))
        if not row.is_primary:
            row.is_primary = True
        row.revision = int(row.revision or 1) + 1
        event_id = await self._add_change_event(
            vessel_id,
            event_type_code,
            event_title,
            before,
            {"target": _row_dict(row), "cancelled_primary_ids": cancelled_ids},
            operator_id,
            object_type=model.__tablename__,
            object_id=row.id,
            reason=payload.reason,
        )
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        return row, cancelled_ids, event_id

    async def _active_mmsi_holder(self, mmsi: str, *, exclude_vessel_id: int | None = None) -> VesselProfile | None:
        stmt = select(VesselProfile).where(
            VesselProfile.current_mmsi == mmsi,
            VesselProfile.profile_status_code == ACTIVE_PROFILE_STATUS,
            VesselProfile.deleted_at.is_(None),
        )
        if exclude_vessel_id is not None:
            stmt = stmt.where(VesselProfile.id != exclude_vessel_id)
        return await self.db.scalar(stmt.limit(1))

    async def _assert_active_mmsi_available(
        self,
        mmsi: str,
        *,
        exclude_vessel_id: int | None = None,
        attempted_profile_id: int | None = None,
        evidence_source: str = "PROFILE_WRITE",
    ) -> None:
        holder = await self._active_mmsi_holder(mmsi, exclude_vessel_id=exclude_vessel_id)
        if holder is None:
            return
        issue_profile_id = attempted_profile_id or exclude_vessel_id or holder.id
        issue_payload = {
            "issue_type_code": "MMSI_CONFLICT",
            "profile_id": issue_profile_id,
            "object_type": "mmsi",
            "object_id": mmsi,
            "field_name": "current_mmsi",
            "normalized_key": f"mmsi|{mmsi}",
            "evidence_source": evidence_source,
            "severity_code": "HIGH",
            "impact_scope": [
                {"profile_id": holder.id, "ship_name": holder.ship_name, "role": "conflict_holder"},
                {"profile_id": attempted_profile_id or exclude_vessel_id, "role": "attempted_write"},
            ],
        }
        async with AsyncSessionLocal() as issue_db:
            await _upsert_quality_issue_in_session(issue_db, **issue_payload)
            await issue_db.commit()
        raise ConflictError(
            "ACTIVE MMSI 已被其他可用船舶档案占用",
            code="MMSI_ACTIVE_CONFLICT",
            detail={"mmsi": mmsi, "conflict_profile_id": holder.id},
        )

    async def _upsert_quality_issue(
        self,
        *,
        issue_type_code: str,
        profile_id: int | None,
        object_type: str,
        object_id: str | int | None,
        normalized_key: str,
        field_name: str | None = None,
        evidence_source: str | None = None,
        severity_code: str = "MEDIUM",
        impact_scope: list[dict[str, Any]] | None = None,
    ) -> VesselDataQualityIssue:
        return await _upsert_quality_issue_in_session(
            self.db,
            issue_type_code=issue_type_code,
            profile_id=profile_id,
            object_type=object_type,
            object_id=object_id,
            normalized_key=normalized_key,
            field_name=field_name,
            evidence_source=evidence_source,
            severity_code=severity_code,
            impact_scope=impact_scope,
        )

    async def list_quality_issues(
        self,
        vessel_id: int,
        query: Any,
    ) -> PageResponse[VesselQualityIssueResponse]:
        await self._require_profile(vessel_id)
        stmt = select(VesselDataQualityIssue).where(VesselDataQualityIssue.vessel_profile_id == vessel_id)
        if getattr(query, "status_code", None):
            stmt = stmt.where(VesselDataQualityIssue.status_code == query.status_code)
        if getattr(query, "issue_type_code", None):
            stmt = stmt.where(VesselDataQualityIssue.issue_type_code == query.issue_type_code)
        total = await self.db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = (
            await self.db.execute(
                stmt.order_by(VesselDataQualityIssue.updated_at.desc(), VesselDataQualityIssue.id.desc())
                .offset((query.page - 1) * query.page_size)
                .limit(query.page_size)
            )
        ).scalars().all()
        label_map = await _load_label_map(self.db)
        return PageResponse(
            total=int(total or 0),
            page=query.page,
            page_size=query.page_size,
            items=[
                VesselQualityIssueResponse(
                    **_row_dict(row),
                    issue_type_name=label_map.get("VESSEL_QUALITY_ISSUE_TYPE", {}).get(row.issue_type_code),
                    status_name=label_map.get("VESSEL_QUALITY_ISSUE_STATUS", {}).get(row.status_code),
                )
                for row in rows
            ],
        )

    async def list_quality_issue_queue(self, query: Any) -> PageResponse[VesselQualityIssueListItemResponse]:
        stmt = select(VesselDataQualityIssue).outerjoin(
            VesselProfile,
            VesselProfile.id == VesselDataQualityIssue.vessel_profile_id,
        )
        if getattr(query, "vessel_id", None):
            stmt = stmt.where(VesselDataQualityIssue.vessel_profile_id == query.vessel_id)
        if getattr(query, "status_code", None):
            stmt = stmt.where(VesselDataQualityIssue.status_code == query.status_code)
        if getattr(query, "issue_type_code", None):
            stmt = stmt.where(VesselDataQualityIssue.issue_type_code == query.issue_type_code)
        if getattr(query, "severity_code", None):
            stmt = stmt.where(VesselDataQualityIssue.severity_code == query.severity_code)
        if getattr(query, "keyword", None):
            like_value = f"%{query.keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    VesselDataQualityIssue.issue_type_code.ilike(like_value),
                    VesselDataQualityIssue.affected_object_type.ilike(like_value),
                    VesselDataQualityIssue.affected_object_id.ilike(like_value),
                    VesselDataQualityIssue.field_name.ilike(like_value),
                    VesselDataQualityIssue.fingerprint.ilike(like_value),
                    VesselProfile.vessel_profile_code.ilike(like_value),
                    VesselProfile.ship_name.ilike(like_value),
                    VesselProfile.current_mmsi.ilike(like_value),
                )
            )
        total = await self.db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = (
            await self.db.execute(
                stmt.order_by(VesselDataQualityIssue.updated_at.desc(), VesselDataQualityIssue.id.desc())
                .offset((query.page - 1) * query.page_size)
                .limit(query.page_size)
            )
        ).scalars().all()
        label_map = await _load_label_map(self.db)
        profiles = await self._profiles_by_ids([row.vessel_profile_id for row in rows if row.vessel_profile_id])
        items: list[VesselQualityIssueListItemResponse] = []
        for row in rows:
            profile = profiles.get(row.vessel_profile_id) if row.vessel_profile_id else None
            vessel_summary = None
            if profile is not None:
                vessel_summary = VesselQualityIssueVesselSummary(
                    id=profile.id,
                    ship_name=profile.ship_name,
                    current_mmsi=profile.current_mmsi,
                    vessel_profile_code=profile.vessel_profile_code,
                    profile_status_code=profile.profile_status_code,
                    profile_status_name=label_map.get("VESSEL_PROFILE_STATUS", {}).get(profile.profile_status_code),
                )
            items.append(
                VesselQualityIssueListItemResponse(
                    **_row_dict(row),
                    issue_type_name=label_map.get("VESSEL_QUALITY_ISSUE_TYPE", {}).get(row.issue_type_code),
                    status_name=label_map.get("VESSEL_QUALITY_ISSUE_STATUS", {}).get(row.status_code),
                    vessel=vessel_summary,
                )
            )
        return PageResponse(total=int(total or 0), page=query.page, page_size=query.page_size, items=items)

    async def list_compliance_risks(self, query: Any) -> PageResponse[VesselRiskSignalResponse]:
        stmt = select(VesselRiskSignal).join(VesselProfile, VesselProfile.id == VesselRiskSignal.vessel_profile_id)
        if getattr(query, "vessel_id", None):
            stmt = stmt.where(VesselRiskSignal.vessel_profile_id == query.vessel_id)
        if getattr(query, "status_code", None):
            stmt = stmt.where(VesselRiskSignal.status_code == query.status_code)
        if getattr(query, "risk_type_code", None):
            stmt = stmt.where(VesselRiskSignal.risk_type_code == query.risk_type_code)
        if getattr(query, "risk_level", None):
            stmt = stmt.where(VesselRiskSignal.risk_level == query.risk_level)
        if getattr(query, "rule_code", None):
            stmt = stmt.where(VesselRiskSignal.rule_code == query.rule_code)
        if getattr(query, "keyword", None):
            like_value = f"%{query.keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    VesselRiskSignal.risk_type_code.ilike(like_value),
                    VesselRiskSignal.rule_code.ilike(like_value),
                    VesselRiskSignal.fingerprint.ilike(like_value),
                    VesselProfile.vessel_profile_code.ilike(like_value),
                    VesselProfile.ship_name.ilike(like_value),
                    VesselProfile.current_mmsi.ilike(like_value),
                )
            )
        total = await self.db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = (
            await self.db.scalars(
                stmt.order_by(VesselRiskSignal.last_detected_at.desc(), VesselRiskSignal.id.desc())
                .offset((query.page - 1) * query.page_size)
                .limit(query.page_size)
            )
        ).all()
        label_map = await _load_label_map(self.db)
        profiles = await self._profiles_by_ids([row.vessel_profile_id for row in rows])
        return PageResponse(
            total=int(total or 0),
            page=query.page,
            page_size=query.page_size,
            items=[self._risk_signal_response(row, label_map, profiles.get(row.vessel_profile_id)) for row in rows],
        )

    async def list_compliance_rules(self, query: Any) -> PageResponse[VesselCertificateRequirementRuleResponse]:
        stmt = select(VesselCertificateRequirementRule)
        if getattr(query, "status_code", None):
            stmt = stmt.where(VesselCertificateRequirementRule.status_code == query.status_code)
        if getattr(query, "scope_type_code", None):
            stmt = stmt.where(VesselCertificateRequirementRule.scope_type_code == query.scope_type_code)
        if getattr(query, "certificate_type_code", None):
            stmt = stmt.where(VesselCertificateRequirementRule.required_certificate_type_code == query.certificate_type_code)
        if getattr(query, "keyword", None):
            like_value = f"%{query.keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    VesselCertificateRequirementRule.rule_code.ilike(like_value),
                    VesselCertificateRequirementRule.rule_name.ilike(like_value),
                    VesselCertificateRequirementRule.required_certificate_type_code.ilike(like_value),
                )
            )
        total = await self.db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = (
            await self.db.scalars(
                stmt.order_by(VesselCertificateRequirementRule.status_code.asc(), VesselCertificateRequirementRule.id.asc())
                .offset((query.page - 1) * query.page_size)
                .limit(query.page_size)
            )
        ).all()
        label_map = await _load_label_map(self.db)
        return PageResponse(
            total=int(total or 0),
            page=query.page,
            page_size=query.page_size,
            items=[self._compliance_rule_response(row, label_map) for row in rows],
        )

    async def create_compliance_rule(self, payload: Any) -> VesselCertificateRequirementRuleResponse:
        data = payload.model_dump(exclude_none=True)
        existed = await self.db.scalar(
            select(VesselCertificateRequirementRule).where(VesselCertificateRequirementRule.rule_code == data["rule_code"])
        )
        if existed is not None:
            raise ConflictError("规则编码已存在", code="VESSEL_RULE_CODE_EXISTS")
        row = VesselCertificateRequirementRule(**data)
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return self._compliance_rule_response(row, await _load_label_map(self.db))

    async def update_compliance_rule(self, rule_id: int, payload: Any) -> VesselCertificateRequirementRuleResponse:
        row = await self.db.get(VesselCertificateRequirementRule, rule_id)
        if row is None:
            raise NotFoundError("VesselCertificateRequirementRule", rule_id)
        updates = payload.model_dump(exclude_none=True)
        revision = updates.pop("revision", None)
        self._ensure_revision(row, revision)
        if not updates:
            raise ValidationError("no update fields provided")
        for key, value in updates.items():
            setattr(row, key, value)
        row.revision = int(row.revision or 1) + 1
        row.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(row)
        return self._compliance_rule_response(row, await _load_label_map(self.db))

    async def void_compliance_rule(self, rule_id: int, payload: Any) -> VesselCertificateRequirementRuleResponse:
        row = await self.db.get(VesselCertificateRequirementRule, rule_id)
        if row is None:
            raise NotFoundError("VesselCertificateRequirementRule", rule_id)
        self._ensure_revision(row, getattr(payload, "revision", None))
        row.status_code = "VOIDED"
        row.remark = getattr(payload, "reason", None) or row.remark
        row.revision = int(row.revision or 1) + 1
        row.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(row)
        return self._compliance_rule_response(row, await _load_label_map(self.db))

    async def get_compliance_risk(self, vessel_id: int) -> VesselComplianceRiskResponse:
        await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        signals = await self._active_risk_signals(vessel_id)
        return await self._compliance_risk_response(vessel_id, signals, label_map)

    async def refresh_compliance_risk(self, vessel_id: int, *, operator_id: int | None = None) -> VesselComplianceRiskResponse:
        profile = await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        try:
            evaluated = await self._evaluate_compliance_risks(profile)
            touched = await self._sync_risk_signals(profile.id, evaluated)
            await self._add_change_event(
                profile.id,
                "REFRESH_COMPLIANCE_RISK",
                "刷新合规风险",
                None,
                {"risk_signal_count": len(touched), "version": COMPLIANCE_VERSION},
                operator_id,
                object_type="vessel_profile",
                object_id=profile.id,
            )
            await self.db.commit()
        except Exception as exc:  # noqa: BLE001
            await self.db.rollback()
            logger.warning("vessel compliance risk refresh failed for profile %s: %s", vessel_id, exc)
            signals = await self._active_risk_signals(vessel_id)
            return await self._compliance_risk_response(
                vessel_id,
                signals,
                label_map,
                engine_status_code="FAILED",
                extra_uncertainty_notes=["合规风险刷新失败，已保留既有风险信号；请修复数据或规则后重试"],
            )
        await self._refresh_summary_best_effort(vessel_id)
        signals = await self._active_risk_signals(vessel_id)
        return await self._compliance_risk_response(vessel_id, signals, label_map, engine_refreshed=True)

    async def _refresh_compliance_risk_best_effort(self, vessel_id: int, *, operator_id: int | None = None) -> None:
        try:
            await self.refresh_compliance_risk(vessel_id, operator_id=operator_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("best-effort vessel compliance risk refresh failed for profile %s: %s", vessel_id, exc)
            await self.db.rollback()

    async def update_risk_signal(self, vessel_id: int, signal_id: int, payload: Any, *, operator_id: int | None = None) -> VesselRiskSignalResponse:
        await self._require_profile(vessel_id)
        row = await self.db.get(VesselRiskSignal, signal_id)
        if row is None or row.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselRiskSignal", signal_id)
        self._ensure_revision(row, payload.revision)
        if payload.status_code in COMPLIANCE_CLOSED_STATUSES and not payload.resolution_reason:
            raise ValidationError("关闭风险必须填写处理原因")
        before = _row_dict(row)
        row.status_code = payload.status_code
        row.resolution_reason = payload.resolution_reason
        row.evidence_json = {**(row.evidence_json or {}), "resolution_evidence": payload.evidence_json or {}}
        row.resolved_by = operator_id if payload.status_code in COMPLIANCE_CLOSED_STATUSES else None
        row.resolved_at = datetime.utcnow() if payload.status_code in COMPLIANCE_CLOSED_STATUSES else None
        row.revision = int(row.revision or 1) + 1
        row.updated_at = datetime.utcnow()
        await self._add_change_event(
            vessel_id,
            "UPDATE_RISK_SIGNAL",
            "处理风险信号",
            before,
            _row_dict(row),
            operator_id,
            object_type="vessel_risk_signal",
            object_id=row.id,
            reason=payload.resolution_reason,
        )
        await self.db.commit()
        await self._refresh_summary_best_effort(vessel_id)
        return self._risk_signal_response(row, await _load_label_map(self.db), await self._require_profile(vessel_id))

    async def list_controller_evidence(self, vessel_id: int) -> list[VesselControllerEvidenceResponse]:
        await self._require_profile(vessel_id)
        rows = (
            await self.db.scalars(
                select(VesselControllerEvidence)
                .where(VesselControllerEvidence.vessel_profile_id == vessel_id)
                .order_by(VesselControllerEvidence.voided_at.asc().nullsfirst(), VesselControllerEvidence.updated_at.desc())
            )
        ).all()
        label_map = await _load_label_map(self.db)
        return [self._controller_evidence_response(row, label_map) for row in rows]

    async def create_controller_evidence(self, vessel_id: int, payload: Any, *, operator_id: int | None = None) -> VesselControllerEvidenceResponse:
        await self._require_profile(vessel_id)
        row = VesselControllerEvidence(vessel_profile_id=vessel_id, **payload.model_dump(exclude_none=True))
        self.db.add(row)
        await self.db.flush()
        await self._create_evidence_audit_task_if_needed(
            row,
            object_type_code="VESSEL_CONTROLLER_EVIDENCE",
            object_name=row.party_name,
            operator_id=operator_id,
            before=None,
            after=_row_dict(row),
        )
        await self._add_change_event(vessel_id, "CREATE_CONTROLLER_EVIDENCE", "新增实际控制人证据", None, _row_dict(row), operator_id, object_type="vessel_controller_evidence", object_id=row.id)
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        return self._controller_evidence_response(row, await _load_label_map(self.db))

    async def update_controller_evidence(self, vessel_id: int, evidence_id: int, payload: Any, *, operator_id: int | None = None) -> VesselControllerEvidenceResponse:
        row = await self._require_evidence_row(VesselControllerEvidence, vessel_id, evidence_id)
        updates = payload.model_dump(exclude_none=True)
        revision = updates.pop("revision", None)
        reason = updates.pop("reason", None)
        self._ensure_revision(row, revision)
        if not updates:
            raise ValidationError("no update fields provided")
        before = _row_dict(row)
        for key, value in updates.items():
            setattr(row, key, value)
        row.revision = int(row.revision or 1) + 1
        row.updated_at = datetime.utcnow()
        await self._create_evidence_audit_task_if_needed(
            row,
            object_type_code="VESSEL_CONTROLLER_EVIDENCE",
            object_name=row.party_name,
            operator_id=operator_id,
            before=before,
            after=_row_dict(row),
        )
        await self._add_change_event(vessel_id, "UPDATE_CONTROLLER_EVIDENCE", "更新实际控制人证据", before, _row_dict(row), operator_id, object_type="vessel_controller_evidence", object_id=row.id, reason=reason)
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        return self._controller_evidence_response(row, await _load_label_map(self.db))

    async def void_controller_evidence(self, vessel_id: int, evidence_id: int, payload: Any, *, operator_id: int | None = None) -> VesselControllerEvidenceResponse:
        row = await self._require_evidence_row(VesselControllerEvidence, vessel_id, evidence_id)
        if row.voided_at is not None:
            raise ConflictError("证据已作废", code="EVIDENCE_VOIDED")
        self._ensure_revision(row, getattr(payload, "revision", None))
        before = _row_dict(row)
        row.voided_at = datetime.utcnow()
        row.voided_by = operator_id
        row.void_reason = getattr(payload, "reason", None) or "证据作废"
        row.status_code = "VOIDED"
        row.revision = int(row.revision or 1) + 1
        row.updated_at = datetime.utcnow()
        await self._add_change_event(vessel_id, "VOID_CONTROLLER_EVIDENCE", "作废实际控制人证据", before, _row_dict(row), operator_id, object_type="vessel_controller_evidence", object_id=row.id, reason=row.void_reason)
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        return self._controller_evidence_response(row, await _load_label_map(self.db))

    async def list_affiliation_evidence(self, vessel_id: int) -> list[VesselAffiliationEvidenceResponse]:
        await self._require_profile(vessel_id)
        rows = (
            await self.db.scalars(
                select(VesselAffiliationEvidence)
                .where(VesselAffiliationEvidence.vessel_profile_id == vessel_id)
                .order_by(VesselAffiliationEvidence.voided_at.asc().nullsfirst(), VesselAffiliationEvidence.updated_at.desc())
            )
        ).all()
        label_map = await _load_label_map(self.db)
        return [self._affiliation_evidence_response(row, label_map) for row in rows]

    async def create_affiliation_evidence(self, vessel_id: int, payload: Any, *, operator_id: int | None = None) -> VesselAffiliationEvidenceResponse:
        await self._require_profile(vessel_id)
        data = payload.model_dump(exclude_none=True)
        await self._validate_affiliation_relation_refs(vessel_id, data)
        row = VesselAffiliationEvidence(vessel_profile_id=vessel_id, **data)
        self.db.add(row)
        await self.db.flush()
        await self._create_evidence_audit_task_if_needed(
            row,
            object_type_code="VESSEL_AFFILIATION_EVIDENCE",
            object_name=row.subject_name or row.counterparty_name or row.affiliation_type_code,
            operator_id=operator_id,
            before=None,
            after=_row_dict(row),
        )
        await self._add_change_event(vessel_id, "CREATE_AFFILIATION_EVIDENCE", "新增挂靠关系证据", None, _row_dict(row), operator_id, object_type="vessel_affiliation_evidence", object_id=row.id)
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        return self._affiliation_evidence_response(row, await _load_label_map(self.db))

    async def update_affiliation_evidence(self, vessel_id: int, evidence_id: int, payload: Any, *, operator_id: int | None = None) -> VesselAffiliationEvidenceResponse:
        row = await self._require_evidence_row(VesselAffiliationEvidence, vessel_id, evidence_id)
        updates = payload.model_dump(exclude_none=True)
        revision = updates.pop("revision", None)
        reason = updates.pop("reason", None)
        self._ensure_revision(row, revision)
        await self._validate_affiliation_relation_refs(vessel_id, updates)
        if not updates:
            raise ValidationError("no update fields provided")
        before = _row_dict(row)
        for key, value in updates.items():
            setattr(row, key, value)
        row.revision = int(row.revision or 1) + 1
        row.updated_at = datetime.utcnow()
        await self._create_evidence_audit_task_if_needed(
            row,
            object_type_code="VESSEL_AFFILIATION_EVIDENCE",
            object_name=row.subject_name or row.counterparty_name or row.affiliation_type_code,
            operator_id=operator_id,
            before=before,
            after=_row_dict(row),
        )
        await self._add_change_event(vessel_id, "UPDATE_AFFILIATION_EVIDENCE", "更新挂靠关系证据", before, _row_dict(row), operator_id, object_type="vessel_affiliation_evidence", object_id=row.id, reason=reason)
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        return self._affiliation_evidence_response(row, await _load_label_map(self.db))

    async def void_affiliation_evidence(self, vessel_id: int, evidence_id: int, payload: Any, *, operator_id: int | None = None) -> VesselAffiliationEvidenceResponse:
        row = await self._require_evidence_row(VesselAffiliationEvidence, vessel_id, evidence_id)
        if row.voided_at is not None:
            raise ConflictError("证据已作废", code="EVIDENCE_VOIDED")
        self._ensure_revision(row, getattr(payload, "revision", None))
        before = _row_dict(row)
        row.voided_at = datetime.utcnow()
        row.voided_by = operator_id
        row.void_reason = getattr(payload, "reason", None) or "证据作废"
        row.status_code = "VOIDED"
        row.revision = int(row.revision or 1) + 1
        row.updated_at = datetime.utcnow()
        await self._add_change_event(vessel_id, "VOID_AFFILIATION_EVIDENCE", "作废挂靠关系证据", before, _row_dict(row), operator_id, object_type="vessel_affiliation_evidence", object_id=row.id, reason=row.void_reason)
        await self.db.commit()
        await self._refresh_compliance_risk_best_effort(vessel_id, operator_id=operator_id)
        return self._affiliation_evidence_response(row, await _load_label_map(self.db))

    async def list_recognition_queue(self, query: Any) -> PageResponse[VesselRecognitionQueueItemResponse]:
        rows: list[tuple[str, Any]] = []
        type_models = [
            ("certificate", VesselCertificateImageRecognition),
            ("person-certificate", VesselPersonCertificateImageRecognition),
            ("owner-document", VesselOwnerDocumentImageRecognition),
        ]
        for recognition_type, model in type_models:
            if getattr(query, "recognition_type", None) and query.recognition_type != recognition_type:
                continue
            stmt = select(model)
            if getattr(query, "status_code", None):
                stmt = stmt.where(model.status_code == query.status_code)
            if getattr(query, "vessel_id", None):
                stmt = stmt.where(model.vessel_profile_id == query.vessel_id)
            if getattr(query, "low_confidence", None) is True:
                stmt = stmt.where(model.confidence_score.is_not(None), model.confidence_score < LOW_CONFIDENCE_SCORE_THRESHOLD)
            elif getattr(query, "low_confidence", None) is False:
                stmt = stmt.where(or_(model.confidence_score.is_(None), model.confidence_score >= LOW_CONFIDENCE_SCORE_THRESHOLD))
            rows.extend((recognition_type, row) for row in (await self.db.scalars(stmt)).all())
        profiles = await self._profiles_by_ids([row.vessel_profile_id for _, row in rows])
        if getattr(query, "keyword", None):
            text = query.keyword.strip().lower()
            rows = [
                (recognition_type, row)
                for recognition_type, row in rows
                if text in recognition_type
                or text in str(row.id)
                or text in (profiles.get(row.vessel_profile_id).ship_name.lower() if profiles.get(row.vessel_profile_id) else "")
                or text in (profiles.get(row.vessel_profile_id).current_mmsi if profiles.get(row.vessel_profile_id) else "")
            ]
        rows.sort(key=lambda item: (item[1].updated_at, item[1].id), reverse=True)
        total = len(rows)
        paged = rows[(query.page - 1) * query.page_size : query.page * query.page_size]
        label_map = await _load_label_map(self.db)
        items = [await self._recognition_queue_item(recognition_type, row, profiles.get(row.vessel_profile_id), label_map) for recognition_type, row in paged]
        return PageResponse(total=total, page=query.page, page_size=query.page_size, items=items)

    async def unified_recognition_field_diff(self, recognition_type: str, recognition_id: int) -> list[VesselRecognitionFieldDiffResponse]:
        if recognition_type == "certificate":
            row = await self.repo.get_image_recognition(recognition_id)
            if row is None:
                raise NotFoundError("VesselCertificateImageRecognition", recognition_id)
            return await self.certificate_recognition_field_diff(row.vessel_profile_id, row.vessel_certificate_id, recognition_id)
        if recognition_type == "person-certificate":
            row = await self.repo.get_person_image_recognition(recognition_id)
            if row is None:
                raise NotFoundError("VesselPersonCertificateImageRecognition", recognition_id)
            return await self.person_certificate_recognition_field_diff(row.vessel_profile_id, row.vessel_person_certificate_id, recognition_id)
        if recognition_type == "owner-document":
            row = await self.repo.get_owner_document_image_recognition(recognition_id)
            if row is None:
                raise NotFoundError("VesselOwnerDocumentImageRecognition", recognition_id)
            return await self.owner_document_recognition_field_diff(row.vessel_profile_id, row.vessel_owner_period_id, row.owner_document_id, recognition_id)
        raise ValidationError("unsupported recognition_type")

    async def unified_recognition_adoption(self, recognition_type: str, recognition_id: int, payload: Any, *, operator_id: int | None = None) -> Any:
        if recognition_type == "certificate":
            row = await self.repo.get_image_recognition(recognition_id)
            if row is None:
                raise NotFoundError("VesselCertificateImageRecognition", recognition_id)
            return await self.adopt_certificate_recognition(row.vessel_profile_id, row.vessel_certificate_id, recognition_id, payload, operator_id=operator_id)
        if recognition_type == "person-certificate":
            row = await self.repo.get_person_image_recognition(recognition_id)
            if row is None:
                raise NotFoundError("VesselPersonCertificateImageRecognition", recognition_id)
            return await self.adopt_person_certificate_recognition(row.vessel_profile_id, row.vessel_person_certificate_id, recognition_id, payload, operator_id=operator_id)
        if recognition_type == "owner-document":
            row = await self.repo.get_owner_document_image_recognition(recognition_id)
            if row is None:
                raise NotFoundError("VesselOwnerDocumentImageRecognition", recognition_id)
            return await self.adopt_owner_document_recognition(row.vessel_profile_id, row.vessel_owner_period_id, row.owner_document_id, recognition_id, payload, operator_id=operator_id)
        raise ValidationError("unsupported recognition_type")

    def _vessel_signal_summary(self, profile: VesselProfile | None, label_map: dict[str, dict[str, str]]) -> VesselRiskSignalVesselSummary | None:
        if profile is None:
            return None
        return VesselRiskSignalVesselSummary(
            id=profile.id,
            ship_name=profile.ship_name,
            current_mmsi=profile.current_mmsi,
            vessel_profile_code=profile.vessel_profile_code,
            profile_status_code=profile.profile_status_code,
            profile_status_name=label_map.get("VESSEL_PROFILE_STATUS", {}).get(profile.profile_status_code),
        )

    def _risk_signal_response(
        self,
        row: VesselRiskSignal,
        label_map: dict[str, dict[str, str]],
        profile: VesselProfile | None = None,
    ) -> VesselRiskSignalResponse:
        return VesselRiskSignalResponse(
            **_row_dict(row),
            risk_type_name=label_map.get("VESSEL_RISK_SIGNAL_TYPE", {}).get(row.risk_type_code),
            risk_level_name=label_map.get("VESSEL_RISK_LEVEL", {}).get(row.risk_level),
            status_name=label_map.get("VESSEL_RISK_SIGNAL_STATUS", {}).get(row.status_code),
            confidence_level_name=label_map.get("VESSEL_CONFIDENCE_LEVEL", {}).get(row.confidence_level),
            vessel=self._vessel_signal_summary(profile, label_map),
        )

    def _compliance_rule_response(
        self,
        row: VesselCertificateRequirementRule,
        label_map: dict[str, dict[str, str]],
    ) -> VesselCertificateRequirementRuleResponse:
        return VesselCertificateRequirementRuleResponse(
            **_row_dict(row),
            scope_type_name=label_map.get("VESSEL_RULE_SCOPE_TYPE", {}).get(row.scope_type_code),
            ship_type_name=label_map.get("SHIP_TYPE", {}).get(row.ship_type_code or ""),
            required_certificate_type_name=label_map.get("VESSEL_CERTIFICATE_TYPE", {}).get(row.required_certificate_type_code),
            risk_type_name=label_map.get("VESSEL_RISK_SIGNAL_TYPE", {}).get(row.risk_type_code),
            risk_level_when_missing_name=label_map.get("VESSEL_RISK_LEVEL", {}).get(row.risk_level_when_missing),
            status_name=label_map.get("VESSEL_REQUIREMENT_RULE_STATUS", {}).get(row.status_code),
        )

    def _controller_evidence_response(
        self,
        row: VesselControllerEvidence,
        label_map: dict[str, dict[str, str]],
    ) -> VesselControllerEvidenceResponse:
        return VesselControllerEvidenceResponse(
            **_row_dict(row),
            controller_role_name=label_map.get("VESSEL_CONTROLLER_ROLE", {}).get(row.controller_role_code),
            confidence_level_name=label_map.get("VESSEL_CONFIDENCE_LEVEL", {}).get(row.confidence_level),
            source_type_name=label_map.get("SOURCE_TYPE", {}).get(row.source_type_code),
            verified_status_name=label_map.get("VESSEL_EVIDENCE_VERIFIED_STATUS", {}).get(row.verified_status_code),
        )

    def _affiliation_evidence_response(
        self,
        row: VesselAffiliationEvidence,
        label_map: dict[str, dict[str, str]],
    ) -> VesselAffiliationEvidenceResponse:
        return VesselAffiliationEvidenceResponse(
            **_row_dict(row),
            affiliation_type_name=label_map.get("VESSEL_AFFILIATION_TYPE", {}).get(row.affiliation_type_code),
            confidence_level_name=label_map.get("VESSEL_CONFIDENCE_LEVEL", {}).get(row.confidence_level),
            source_type_name=label_map.get("SOURCE_TYPE", {}).get(row.source_type_code),
            verified_status_name=label_map.get("VESSEL_EVIDENCE_VERIFIED_STATUS", {}).get(row.verified_status_code),
        )

    async def _create_evidence_audit_task_if_needed(
        self,
        row: Any,
        *,
        object_type_code: str,
        object_name: str | None,
        operator_id: int | None,
        before: dict[str, Any] | None,
        after: dict[str, Any],
    ) -> None:
        if getattr(row, "verified_status_code", None) != "PENDING" or getattr(row, "audit_task_id", None):
            return
        now = datetime.utcnow()
        task = AuditTask(
            task_no=f"VA{now:%Y%m%d%H%M%S}{uuid.uuid4().hex[:6].upper()}",
            biz_type_code="VESSEL",
            biz_id=row.id,
            biz_code=object_type_code,
            object_type_code=object_type_code,
            object_code=str(row.id),
            object_name=object_name,
            change_type_code="UPDATE" if before else "CREATE",
            source_module_code="VESSEL",
            submitter_id=operator_id,
            current_handler_id=None,
            audit_status="PENDING",
            audit_remark="Round 10 船舶证据审核",
            submitted_at=now,
        )
        self.db.add(task)
        await self.db.flush()
        row.audit_task_id = task.id
        self.db.add_all(
            [
                AuditTaskSnapshot(
                    task_id=task.id,
                    before_snapshot_json=_jsonable(before) if before else None,
                    after_snapshot_json=_jsonable(after),
                    diff_json=None,
                    summary_json={
                        "round": "ROUND_10",
                        "object_type_code": object_type_code,
                        "vessel_profile_id": row.vessel_profile_id,
                    },
                    created_at=now,
                    updated_at=now,
                ),
                AuditRecord(
                    task_id=task.id,
                    action_code="SUBMIT",
                    operator_id=operator_id,
                    from_status_code=None,
                    to_status_code="PENDING",
                    remark="提交船舶证据审核",
                    created_at=now,
                ),
            ]
        )

    async def _require_evidence_row(self, model: type[Any], vessel_id: int, row_id: int) -> Any:
        row = await self.db.get(model, row_id)
        if row is None or getattr(row, "vessel_profile_id", None) != vessel_id:
            raise NotFoundError(model.__name__, row_id)
        return row

    async def _validate_affiliation_relation_refs(self, vessel_id: int, data: dict[str, Any]) -> None:
        owner_id = data.get("owner_period_id")
        operator_id = data.get("operator_period_id")
        if owner_id is not None:
            owner = await self.db.get(VesselOwnerPeriod, owner_id)
            if owner is None or owner.vessel_profile_id != vessel_id:
                raise NotFoundError("VesselOwnerPeriod", owner_id)
        if operator_id is not None:
            operator = await self.db.get(VesselOperatorPeriod, operator_id)
            if operator is None or operator.vessel_profile_id != vessel_id:
                raise NotFoundError("VesselOperatorPeriod", operator_id)

    async def _active_risk_signals(self, vessel_id: int) -> list[VesselRiskSignal]:
        if not hasattr(self.db, "scalars"):
            return []
        return list(
            (
                await self.db.scalars(
                    select(VesselRiskSignal)
                    .where(
                        VesselRiskSignal.vessel_profile_id == vessel_id,
                        VesselRiskSignal.status_code.in_(COMPLIANCE_ACTIVE_STATUSES),
                    )
                    .order_by(VesselRiskSignal.risk_level.asc(), VesselRiskSignal.last_detected_at.desc())
                )
            ).all()
        )

    async def _compliance_risk_response(
        self,
        vessel_id: int,
        signals: list[VesselRiskSignal],
        label_map: dict[str, dict[str, str]],
        *,
        engine_refreshed: bool = False,
        engine_status_code: str | None = None,
        extra_uncertainty_notes: list[str] | None = None,
    ) -> VesselComplianceRiskResponse:
        profile = await self._require_profile(vessel_id)
        rules = await self._active_certificate_rules(profile)
        context_gap = self._compliance_context_gap(profile)
        active_levels = [row.risk_level for row in signals if row.status_code in COMPLIANCE_ACTIVE_STATUSES]
        overall = _max_risk_level(active_levels)
        if not signals and rules and engine_refreshed and not context_gap["not_computable"]:
            overall = "LOW"
        high_count = sum(1 for row in signals if row.risk_level == "HIGH")
        medium_count = sum(1 for row in signals if row.risk_level == "MEDIUM")
        gap_count = sum(1 for row in signals if row.risk_level in {"HIGH", "MEDIUM", "UNKNOWN"})
        rule_summary = await self._certificate_rule_summary(vessel_id, rules)
        notes: list[str] = []
        if not rules:
            notes.append("证书要求规则缺失，合规风险不可计算")
        if any(row.risk_level == "UNKNOWN" for row in signals):
            notes.append("存在证据不足的风险信号，UNKNOWN 不等同低风险")
        if context_gap["not_computable"]:
            notes.append(COMPLIANCE_NOT_COMPUTABLE_NOTE)
        if extra_uncertainty_notes:
            notes.extend(extra_uncertainty_notes)
        status_code = engine_status_code or ("RULE_MISSING" if not rules else ("NOT_COMPUTABLE" if context_gap["not_computable"] else "READY"))
        profiles = await self._profiles_by_ids([vessel_id])
        return VesselComplianceRiskResponse(
            vessel_id=vessel_id,
            generated_at=datetime.utcnow(),
            overall_risk_level=overall,
            overall_risk_level_name=label_map.get("VESSEL_RISK_LEVEL", {}).get(overall),
            engine_status_code=status_code,
            risk_signal_count=len(signals),
            open_signal_count=sum(1 for row in signals if row.status_code == "OPEN"),
            high_signal_count=high_count,
            medium_signal_count=medium_count,
            rule_coverage_rate=_percent(len(rules), len(REQUIRED_VESSEL_CERTIFICATE_TYPES)),
            evidence_gap_count=gap_count,
            data_sources=["CERTIFICATE_REQUIREMENT_RULE", "CERTIFICATE_LEDGER", "RELATION_LEDGER", "OCR_ADOPTION"],
            uncertainty_notes=notes,
            rule_summary=rule_summary,
            signals=[self._risk_signal_response(row, label_map, profiles.get(vessel_id)) for row in signals],
        )

    async def _active_certificate_rules(self, profile: VesselProfile) -> list[VesselCertificateRequirementRule]:
        stmt = select(VesselCertificateRequirementRule).where(VesselCertificateRequirementRule.status_code == "ACTIVE")
        rows = list((await self.db.scalars(stmt)).all())
        matched: list[VesselCertificateRequirementRule] = []
        for row in rows:
            if self._rule_matches_profile_context(row, profile):
                matched.append(row)
        return matched

    @staticmethod
    def _rule_scope_codes(row: VesselCertificateRequirementRule, field_name: str) -> set[str]:
        values: set[str] = set()
        direct = getattr(row, field_name, None)
        if direct:
            values.add(str(direct))
        condition = row.condition_json or {}
        for key in (field_name, f"{field_name}s", field_name.replace("_code", "_codes")):
            raw = condition.get(key)
            if isinstance(raw, list):
                values.update(str(item) for item in raw if item)
            elif raw:
                values.add(str(raw))
        return values

    @staticmethod
    def _profile_context_code(profile: VesselProfile, *field_names: str) -> str | None:
        for field_name in field_names:
            raw = getattr(profile, field_name, None)
            if raw:
                return str(raw)
        return None

    def _rule_matches_profile_context(self, row: VesselCertificateRequirementRule, profile: VesselProfile) -> bool:
        if row.scope_type_code == "GLOBAL":
            return True
        if row.scope_type_code == "SHIP_TYPE":
            values = self._rule_scope_codes(row, "ship_type_code")
            return bool(values and profile.ship_type_code and str(profile.ship_type_code) in values)
        if row.scope_type_code == "CARGO_CATEGORY":
            values = self._rule_scope_codes(row, "cargo_category_code")
            profile_value = self._profile_context_code(profile, "cargo_category_code")
            return bool(values and profile_value and profile_value in values)
        if row.scope_type_code == "ROUTE_AREA":
            values = self._rule_scope_codes(row, "route_area_code")
            profile_value = self._profile_context_code(profile, "route_area_code")
            return bool(values and profile_value and profile_value in values)
        return False

    def _compliance_context_gap(self, profile: VesselProfile) -> dict[str, Any]:
        missing_context: list[str] = []
        if not getattr(profile, "ship_type_code", None):
            missing_context.append("ship_type_code")
        if not self._profile_context_code(profile, "cargo_category_code"):
            missing_context.append("cargo_category_code")
        if not self._profile_context_code(profile, "route_area_code"):
            missing_context.append("route_area_code")
        return {
            "not_computable": bool(missing_context),
            "missing_context": missing_context,
            "ship_type_code": getattr(profile, "ship_type_code", None),
            "cargo_category_code": self._profile_context_code(profile, "cargo_category_code"),
            "route_area_code": self._profile_context_code(profile, "route_area_code"),
        }

    async def _certificate_rule_summary(
        self,
        vessel_id: int,
        rules: list[VesselCertificateRequirementRule],
    ) -> list[dict[str, Any]]:
        certificates = await self._summary_certificates(vessel_id)
        by_type: dict[str, list[VesselCertificate]] = defaultdict(list)
        for cert in certificates:
            by_type[cert.certificate_type_code].append(cert)
        result: list[dict[str, Any]] = []
        for rule in rules:
            rows = by_type.get(rule.required_certificate_type_code, [])
            complete = [row for row in rows if self._certificate_has_complete_evidence(row)]
            result.append(
                {
                    "rule_code": rule.rule_code,
                    "rule_name": rule.rule_name,
                    "required_certificate_type_code": rule.required_certificate_type_code,
                    "status_code": "SATISFIED" if complete else ("INSUFFICIENT" if rows else "MISSING"),
                    "evidence_count": len(complete),
                    "candidate_count": len(rows),
                }
            )
        return result

    async def _evaluate_compliance_risks(self, profile: VesselProfile) -> list[dict[str, Any]]:
        today = date.today()
        expiring_limit = today + timedelta(days=30)
        rules = await self._active_certificate_rules(profile)
        certificates = await self._summary_certificates(profile.id)
        certs_by_type: dict[str, list[VesselCertificate]] = defaultdict(list)
        for cert in certificates:
            certs_by_type[cert.certificate_type_code].append(cert)
        risks: list[dict[str, Any]] = []
        for rule in rules:
            rows = certs_by_type.get(rule.required_certificate_type_code, [])
            complete_rows = [cert for cert in rows if self._certificate_has_complete_evidence(cert)]
            if not rows:
                risks.append(self._risk_payload(profile.id, "CERTIFICATE_MISSING", rule.risk_level_when_missing, rule.rule_code, rule.required_certificate_type_code, {"missing_certificate_type_code": rule.required_certificate_type_code}, ["证书缺失"]))
                continue
            if rows and not complete_rows:
                risks.append(self._risk_payload(profile.id, "CERTIFICATE_MISSING", "UNKNOWN", rule.rule_code, f"{rule.required_certificate_type_code}|insufficient", {"insufficient_certificate_type_code": rule.required_certificate_type_code, "candidate_certificate_ids": [row.id for row in rows]}, ["证书未核验或缺少证书号/有效期证据"]))
            for cert in complete_rows:
                if cert.is_long_term_valid or cert.valid_to is None:
                    continue
                if cert.valid_to < today:
                    risks.append(self._risk_payload(profile.id, "CERTIFICATE_EXPIRED", "HIGH", rule.rule_code, f"{cert.id}|expired", {"certificate_id": cert.id, "certificate_type_code": cert.certificate_type_code, "valid_to": cert.valid_to}, ["证书已过期"]))
                elif cert.valid_to <= expiring_limit:
                    risks.append(self._risk_payload(profile.id, "CERTIFICATE_EXPIRING", "MEDIUM", rule.rule_code, f"{cert.id}|expiring", {"certificate_id": cert.id, "certificate_type_code": cert.certificate_type_code, "valid_to": cert.valid_to}, ["证书 30 天内到期"]))

        owner = await self._summary_primary_relation(VesselOwnerPeriod, profile.id)
        operator = await self._summary_primary_relation(VesselOperatorPeriod, profile.id)
        if operator is None or getattr(operator, "verified_status_code", None) != "VERIFIED":
            risks.append(self._risk_payload(profile.id, "OPERATOR_QUALIFICATION_UNKNOWN", "UNKNOWN", None, "operator_qualification", {"operator_id": getattr(operator, "id", None), "verified_status_code": getattr(operator, "verified_status_code", None)}, ["经营方资质证据不足"]))
        subject_evidence = self._certificate_subject_values(certificates)
        if subject_evidence and owner is not None:
            mismatches = [item for item in subject_evidence if _normalized_text(item["subject_name"]) and _normalized_text(item["subject_name"]) != _normalized_text(owner.party_name)]
            if mismatches:
                risks.append(self._risk_payload(profile.id, "SUBJECT_MISMATCH", "MEDIUM", None, "certificate_subject_owner", {"owner_name": owner.party_name, "mismatches": mismatches}, ["证书主体与主所有方不一致"]))
        elif certificates:
            risks.append(self._risk_payload(profile.id, "SUBJECT_MISMATCH", "UNKNOWN", None, "certificate_subject_missing", {"certificate_count": len(certificates)}, ["证书主体字段证据不足，不能判断主体一致性"]))

        controller_count = int(
            await self.db.scalar(
                select(func.count(VesselControllerEvidence.id)).where(
                    VesselControllerEvidence.vessel_profile_id == profile.id,
                    VesselControllerEvidence.voided_at.is_(None),
                    VesselControllerEvidence.status_code == "ACTIVE",
                    VesselControllerEvidence.verified_status_code == "APPROVED",
                    VesselControllerEvidence.confidence_level.in_(["HIGH", "MEDIUM"]),
                )
            )
            or 0
        )
        if not controller_count:
            risks.append(self._risk_payload(profile.id, "CONTROLLER_UNKNOWN", "UNKNOWN", None, "controller_missing", {}, ["实际控制人证据不足"]))

        owner_is_person = owner is not None and getattr(owner, "party_type_code", None) == "PERSON"
        operator_is_company = operator is not None and getattr(operator, "party_type_code", None) == "COMPANY"
        if owner_is_person and operator_is_company:
            affiliation_count = int(
                await self.db.scalar(
                    select(func.count(VesselAffiliationEvidence.id)).where(
                        VesselAffiliationEvidence.vessel_profile_id == profile.id,
                        VesselAffiliationEvidence.voided_at.is_(None),
                        VesselAffiliationEvidence.status_code == "ACTIVE",
                        VesselAffiliationEvidence.verified_status_code == "APPROVED",
                        VesselAffiliationEvidence.confidence_level.in_(["HIGH", "MEDIUM"]),
                    )
                )
                or 0
            )
            if not affiliation_count:
                risks.append(self._risk_payload(profile.id, "AFFILIATION_UNCLEAR", "UNKNOWN", None, "affiliation_missing", {"owner_id": owner.id, "operator_id": operator.id}, ["个人所有方 + 公司经营方缺少挂靠/授权证据"]))

        low_diff_count = int(
            await self.db.scalar(
                select(func.count(VesselRecognitionFieldDiff.id)).where(
                    VesselRecognitionFieldDiff.vessel_profile_id == profile.id,
                    VesselRecognitionFieldDiff.confidence_score.is_not(None),
                    VesselRecognitionFieldDiff.confidence_score < LOW_CONFIDENCE_SCORE_THRESHOLD,
                    VesselRecognitionFieldDiff.adopt_status_code.in_(["REVIEW_REQUIRED", "ADOPTED"]),
                )
            )
            or 0
        )
        if low_diff_count:
            risks.append(self._risk_payload(profile.id, "OCR_LOW_CONFIDENCE", "MEDIUM", None, "ocr_low_confidence", {"low_confidence_diff_count": low_diff_count}, ["存在低置信 OCR 字段需要复核"]))

        context_gap = self._compliance_context_gap(profile)
        if context_gap["not_computable"]:
            risks.append(
                self._risk_payload(
                    profile.id,
                    "CARGO_ROUTE_SHIPTYPE_UNCERTAIN",
                    "UNKNOWN",
                    None,
                    "cargo_route_shiptype_not_computable",
                    context_gap,
                    [COMPLIANCE_NOT_COMPUTABLE_NOTE],
                )
            )

        return risks

    def _risk_payload(
        self,
        profile_id: int,
        risk_type_code: str,
        risk_level: str,
        rule_code: str | None,
        evidence_key: str,
        evidence: dict[str, Any],
        notes: list[str],
    ) -> dict[str, Any]:
        return {
            "vessel_profile_id": profile_id,
            "risk_type_code": risk_type_code,
            "risk_level": risk_level,
            "rule_code": rule_code,
            "confidence_level": "LOW" if risk_level == "UNKNOWN" else "MEDIUM",
            "fingerprint": _risk_fingerprint(profile_id, risk_type_code, rule_code, evidence_key),
            "evidence_json": _jsonable(evidence),
            "source_trace_json": [
                {"source_code": "CERTIFICATE_REQUIREMENT_RULE" if rule_code else "VESSEL_COMPLIANCE_ENGINE", "rule_code": rule_code},
            ],
            "uncertainty_notes_json": notes,
        }

    async def _sync_risk_signals(self, vessel_id: int, evaluated: list[dict[str, Any]]) -> list[VesselRiskSignal]:
        now = datetime.utcnow()
        active_rows = list(
            (
                await self.db.scalars(
                    select(VesselRiskSignal).where(
                        VesselRiskSignal.vessel_profile_id == vessel_id,
                        VesselRiskSignal.status_code.in_(COMPLIANCE_ACTIVE_STATUSES),
                    )
                )
            ).all()
        )
        active_by_fingerprint = {row.fingerprint: row for row in active_rows}
        seen: set[str] = set()
        touched: list[VesselRiskSignal] = []
        for payload in evaluated:
            fingerprint = payload["fingerprint"]
            seen.add(fingerprint)
            row = active_by_fingerprint.get(fingerprint)
            if row is None:
                row = VesselRiskSignal(
                    status_code="OPEN",
                    first_detected_at=now,
                    last_detected_at=now,
                    created_at=now,
                    updated_at=now,
                    **payload,
                )
                self.db.add(row)
            else:
                row.risk_level = payload["risk_level"]
                row.rule_code = payload["rule_code"]
                row.confidence_level = payload["confidence_level"]
                row.evidence_json = payload["evidence_json"]
                row.source_trace_json = payload["source_trace_json"]
                row.uncertainty_notes_json = payload["uncertainty_notes_json"]
                row.last_detected_at = now
                row.updated_at = now
                row.revision = int(row.revision or 1) + 1
            touched.append(row)
        for row in active_rows:
            if row.fingerprint not in seen:
                if row.risk_type_code == "BLACKLIST_SIGNAL":
                    continue
                row.status_code = "MITIGATED"
                row.resolved_at = now
                row.resolution_reason = "规则重算后不再命中"
                row.updated_at = now
                row.revision = int(row.revision or 1) + 1
        await self.db.flush()
        return touched

    async def _formal_risk_summary(self, vessel_id: int) -> dict[str, Any]:
        signals = await self._active_risk_signals(vessel_id)
        if not signals:
            return {"has_formal_signals": False}
        active = [row for row in signals if row.status_code in COMPLIANCE_ACTIVE_STATUSES]
        levels = [row.risk_level for row in active]
        risk_level = _max_risk_level(levels)
        return {
            "has_formal_signals": True,
            "risk_level": risk_level,
            "risk_evidence_summary": [
                {
                    "source": "VESSEL_RISK_SIGNAL",
                    "risk_signal_id": row.id,
                    "risk_type_code": row.risk_type_code,
                    "risk_level": row.risk_level,
                    "rule_code": row.rule_code,
                    "status_code": row.status_code,
                    "evidence": row.evidence_json or {},
                    "uncertainty_notes": row.uncertainty_notes_json or [],
                }
                for row in active[:20]
            ],
            "certificate_missing_count": sum(1 for row in active if row.risk_type_code == "CERTIFICATE_MISSING"),
            "certificate_expiring_count": sum(1 for row in active if row.risk_type_code == "CERTIFICATE_EXPIRING"),
            "certificate_expired_count": sum(1 for row in active if row.risk_type_code == "CERTIFICATE_EXPIRED"),
        }

    def _certificate_subject_values(self, certificates: list[VesselCertificate]) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        for cert in certificates:
            payload = cert.structured_payload_json or {}
            subject = _first_value(payload, ["owner_name", "holder_name", "ship_owner", "subject_name", "company_name"])
            if subject:
                values.append({"certificate_id": cert.id, "certificate_type_code": cert.certificate_type_code, "subject_name": str(subject)})
        return values

    async def _recognition_queue_item(
        self,
        recognition_type: str,
        row: Any,
        profile: VesselProfile | None,
        label_map: dict[str, dict[str, str]],
    ) -> VesselRecognitionQueueItemResponse:
        object_type = {
            "certificate": "VESSEL_CERTIFICATE_IMAGE_RECOGNITION",
            "person-certificate": "PERSON_CERTIFICATE_IMAGE_RECOGNITION",
            "owner-document": "OWNER_DOCUMENT_IMAGE_RECOGNITION",
        }[recognition_type]
        target_object_type = {
            "certificate": "vessel_certificate",
            "person-certificate": "vessel_person_certificate",
            "owner-document": "vessel_owner_period",
        }[recognition_type]
        target_id = getattr(row, "vessel_certificate_id", None) or getattr(row, "vessel_person_certificate_id", None) or getattr(row, "vessel_owner_period_id", None)
        pending_diff_count = int(
            await self.db.scalar(
                select(func.count(VesselRecognitionFieldDiff.id)).where(
                    VesselRecognitionFieldDiff.recognition_object_type == object_type,
                    VesselRecognitionFieldDiff.recognition_id == row.id,
                    VesselRecognitionFieldDiff.adopt_status_code == "REVIEW_REQUIRED",
                )
            )
            or 0
        )
        low_diff_count = int(
            await self.db.scalar(
                select(func.count(VesselRecognitionFieldDiff.id)).where(
                    VesselRecognitionFieldDiff.recognition_object_type == object_type,
                    VesselRecognitionFieldDiff.recognition_id == row.id,
                    VesselRecognitionFieldDiff.confidence_score.is_not(None),
                    VesselRecognitionFieldDiff.confidence_score < LOW_CONFIDENCE_SCORE_THRESHOLD,
                )
            )
            or 0
        )
        adoption_count = int(
            await self.db.scalar(
                select(func.count(VesselRecognitionAdoptionRecord.id)).where(
                    VesselRecognitionAdoptionRecord.recognition_object_type == object_type,
                    VesselRecognitionAdoptionRecord.recognition_id == row.id,
                )
            )
            or 0
        )
        return VesselRecognitionQueueItemResponse(
            id=f"{recognition_type}:{row.id}",
            recognition_type=recognition_type,
            recognition_object_type=object_type,
            recognition_id=row.id,
            vessel_profile_id=row.vessel_profile_id,
            vessel=self._vessel_signal_summary(profile, label_map),
            target_object_type=target_object_type,
            target_object_id=int(target_id or 0),
            status_code=row.status_code,
            status_name=label_map.get("VESSEL_CERTIFICATE_IMAGE_RECOGNITION_STATUS", {}).get(row.status_code),
            confidence_score=row.confidence_score,
            low_confidence=bool(row.confidence_score is not None and row.confidence_score < LOW_CONFIDENCE_SCORE_THRESHOLD),
            pending_diff_count=pending_diff_count,
            low_confidence_diff_count=low_diff_count,
            adoption_count=adoption_count,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _close_current_mmsi_history(self, vessel_id: int, old_mmsi: str | None) -> None:
        if not old_mmsi:
            return
        rows = (
            await self.db.execute(
                select(VesselIdentifierHistory).where(
                    VesselIdentifierHistory.vessel_profile_id == vessel_id,
                    VesselIdentifierHistory.identifier_type_code == "MMSI",
                    VesselIdentifierHistory.identifier_value == old_mmsi,
                    VesselIdentifierHistory.end_date.is_(None),
                )
            )
        ).scalars().all()
        for row in rows:
            row.end_date = date.today()
            row.status_code = "HISTORICAL"

    @staticmethod
    def _maybe(response_cls, row):
        return response_cls(**_row_dict(row)) if row is not None else None

    async def _add_change_event(
        self,
        vessel_id: int,
        event_type_code: str,
        event_title: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        operator_id: int | None,
        *,
        object_type: str | None = None,
        object_id: str | int | None = None,
        changed_fields: list[str] | None = None,
        reason: str | None = None,
    ) -> int:
        row = VesselChangeEvent(
            vessel_profile_id=vessel_id,
            event_type_code=event_type_code,
            event_title=event_title,
            object_type=object_type,
            object_id=str(object_id) if object_id is not None else None,
            before_json=_jsonable(before),
            after_json=_jsonable(after),
            changed_fields_json=changed_fields if changed_fields is not None else _changed_fields(before, after),
            reason=reason,
            operator_id=operator_id,
            created_at=datetime.utcnow(),
        )
        self.db.add(row)
        await self.db.flush()
        return int(row.id)

    async def _copy_singletons(self, source_id: int, target_id: int) -> None:
        for model in [VesselRegistrationInfo, VesselCapacityDimension, VesselBuildInfo]:
            row = await self.repo.get_one_by_profile(model, source_id)
            if row is None:
                continue
            data = _row_dict(row)
            data.pop("id", None)
            data["vessel_profile_id"] = target_id
            if "updated_at" in data:
                data["updated_at"] = datetime.utcnow()
            self.db.add(model(**data))
        await self.db.flush()

    async def _copy_history(self, source_id: int, target_id: int) -> None:
        for model in [VesselNameHistory, VesselIdentifierHistory]:
            rows = await self.repo.list_by_profile(model, source_id)
            for row in rows:
                data = _row_dict(row)
                data.pop("id", None)
                data["vessel_profile_id"] = target_id
                self.db.add(model(**data))
        await self.db.flush()
