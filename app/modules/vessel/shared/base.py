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
    VesselAffiliationConclusion,
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
    VesselControllerConclusion,
    VesselCrewAssignment,
    VesselDataQualityIssue,
    VesselGovernanceTask,
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
    VesselRelationEvidenceAttachment,
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
from app.modules.vessel.services.compliance_rules import (
    compliance_risk_action_label,
    compliance_risk_action_path,
    compliance_risk_required_fields,
)
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
    VesselSummaryRefreshBatchRequest,
    VesselSummaryRefreshBatchResponse,
    VesselSummaryRefreshBatchItemResponse,
    VesselSummaryRefreshDiffResponse,
    VesselCertificateRequirementRuleResponse,
    VesselComplianceRiskResponse,
    VesselControllerEvidenceResponse,
    VesselEvidenceConclusionRefResponse,
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
    VesselRecommendedAction,
    VesselRelationConclusionConflictResolveRequest,
    VesselRelationConclusionSummaryResponse,
    VesselRelationEvidenceAttachmentResponse,
    VesselControllerConclusionResponse,
    VesselAffiliationConclusionResponse,
    VesselQualityIssueRecheckResponse,
    VesselRiskSignalResponse,
    VesselRiskSignalVesselSummary,
    VesselWorkbenchItemResponse,
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
    "VESSEL_EVIDENCE_VERIFIED_STATUS",
    "VESSEL_GOVERNANCE_TASK_TYPE",
    "VESSEL_GOVERNANCE_TASK_STATUS",
    "VESSEL_GOVERNANCE_PRIORITY",
    "VESSEL_BLACKLIST_LIST_TYPE",
    "VESSEL_BLACKLIST_SIGNAL_TYPE",
    "VESSEL_BLACKLIST_SIGNAL_STATUS",
    "VESSEL_RELATION_CONCLUSION_STATUS",
    "VESSEL_GOVERNANCE_SYNC_STATUS",
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
