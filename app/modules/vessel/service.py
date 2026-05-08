"""vessel 模块 service。"""

from __future__ import annotations

import logging
import asyncio
import hashlib
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import UploadFile
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError, ValidationError
from app.integrations.ai.vessel_image_assistant import VesselCertificateImageAssistant
from app.integrations.config_keys import ES_R_HOST, ES_R_INDEX, ES_REALTIME_CONFIG_PROFILE
from app.integrations.es import RealtimeEsClient
from app.models.address import AdminRegion, AdminRegionBoundary, Region
from app.models.dictionary import StdDict, StdDictItem
from app.models.vessel import (
    VesselBuildInfo,
    VesselCapacityDimension,
    VesselCertificate,
    VesselCertificateFile,
    VesselCertificateImageRecognition,
    VesselChangeEvent,
    VesselContact,
    VesselCrewAssignment,
    VesselIdentifierHistory,
    VesselIdentityLink,
    VesselNameHistory,
    VesselOperatorPeriod,
    VesselOwnerDocument,
    VesselOwnerDocumentImageRecognition,
    VesselOwnerPeriod,
    VesselPersonCertificate,
    VesselPersonCertificateFile,
    VesselPersonCertificateImageRecognition,
    VesselProfile,
    VesselRegistrationInfo,
)
from app.modules.dictionary.service import CodeSequenceService
from app.modules.address.geometry import normalize_boundary_geometry
from app.modules.storage.service import FileStorageService
from app.modules.system.runtime_config import RuntimeConfigService
from app.modules.vessel.repository import VesselRepository
from app.modules.vessel.schemas import (
    PageResponse,
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
    VesselPositionCitySituationItemResponse,
    VesselPositionCitySituationResponse,
    VesselPositionCitySituationSummary,
    VesselPositionCityVesselsResponse,
    VesselPositionMonitorItemResponse,
    VesselPositionMonitorResponse,
    VesselPositionMonitorSummary,
    VesselShipTypeDistributionItemResponse,
    VesselProfileResponse,
    VesselRegistrationResponse,
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
CITY_BOUNDARY_SIMPLIFY_TOLERANCE = {
    "low": 0.02,
    "medium": 0.006,
}
CITY_SITUATION_CACHE_KEY_PREFIX = "vessel:city_situation:response:"
CITY_SITUATION_SNAPSHOT_KEY_PREFIX = "vessel:city_situation:snapshot:"
CITY_SITUATION_SNAPSHOT_TTL_SECONDS = settings.VESSEL_CITY_SITUATION_SNAPSHOT_TTL_SECONDS
CITY_SITUATION_SNAPSHOT_MAX_SIZE = 20
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


@dataclass(slots=True)
class _CitySituationSnapshot:
    snapshot_id: str
    expires_at: datetime
    items: list[VesselPositionMonitorItemResponse]
    partial: bool
    error_message: str | None
    generated_at: datetime


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


def _city_situation_cache_ttl() -> int:
    return max(5, int(settings.VESSEL_CITY_SITUATION_CACHE_TTL_SECONDS or 60))


def _city_snapshot_ttl() -> int:
    return max(30, int(settings.VESSEL_CITY_SITUATION_SNAPSHOT_TTL_SECONDS or CITY_SITUATION_SNAPSHOT_TTL_SECONDS))


def _city_cache_backend_setting() -> str:
    return (settings.VESSEL_CITY_SITUATION_CACHE_BACKEND or "memory").strip().lower()


def _city_situation_query_cache_key(query: Any) -> str:
    payload = query.model_dump(mode="json") if hasattr(query, "model_dump") else dict(query)
    payload.pop("force_refresh", None)
    normalized = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _money(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"))


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
        "ERROR": "实时船位异常",
    }.get(code, code)


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


def _extract_geojson_polygons(geometry: dict[str, Any]) -> list[list[list[tuple[float, float]]]]:
    geometry_type = str(geometry.get("type") or "").strip()
    if geometry_type == "Feature":
        return _extract_geojson_polygons(geometry.get("geometry") or {})
    if geometry_type == "FeatureCollection":
        polygons: list[list[list[tuple[float, float]]]] = []
        for feature in geometry.get("features") or []:
            if isinstance(feature, dict):
                polygons.extend(_extract_geojson_polygons(feature))
        return polygons
    if geometry_type == "Polygon":
        polygon = _normalize_polygon_coordinates(geometry.get("coordinates") or [])
        return [polygon] if polygon else []
    if geometry_type == "MultiPolygon":
        polygons = []
        for polygon_coordinates in geometry.get("coordinates") or []:
            polygon = _normalize_polygon_coordinates(polygon_coordinates)
            if polygon:
                polygons.append(polygon)
        return polygons
    return []


def _normalize_polygon_coordinates(value: Any) -> list[list[tuple[float, float]]]:
    rings: list[list[tuple[float, float]]] = []
    if not isinstance(value, list):
        return rings
    for raw_ring in value:
        ring: list[tuple[float, float]] = []
        if not isinstance(raw_ring, list):
            continue
        for raw_point in raw_ring:
            if not isinstance(raw_point, (list, tuple)) or len(raw_point) < 2:
                continue
            try:
                ring.append((float(raw_point[0]), float(raw_point[1])))
            except (TypeError, ValueError):
                continue
        if len(ring) >= 3:
            rings.append(ring)
    return rings


def _polygons_bbox(polygons: list[list[list[tuple[float, float]]]]) -> tuple[float, float, float, float] | None:
    points = [point for polygon in polygons for ring in polygon for point in ring]
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _bbox_contains(bbox: tuple[float, float, float, float], longitude: float, latitude: float) -> bool:
    min_x, min_y, max_x, max_y = bbox
    return min_x <= longitude <= max_x and min_y <= latitude <= max_y


def _point_in_polygon_with_holes(longitude: float, latitude: float, polygon: list[list[tuple[float, float]]]) -> bool:
    if not polygon or not _point_in_ring(longitude, latitude, polygon[0]):
        return False
    return not any(_point_in_ring(longitude, latitude, hole) for hole in polygon[1:])


def _point_in_ring(longitude: float, latitude: float, ring: list[tuple[float, float]]) -> bool:
    inside = False
    count = len(ring)
    if count < 3:
        return False
    j = count - 1
    for i in range(count):
        xi, yi = ring[i]
        xj, yj = ring[j]
        intersects = ((yi > latitude) != (yj > latitude)) and (
            longitude < (xj - xi) * (latitude - yi) / ((yj - yi) or 1e-12) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def _perpendicular_distance(point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]) -> float:
    x, y = point
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    return abs(dy * x - dx * y + x2 * y1 - y2 * x1) / ((dx * dx + dy * dy) ** 0.5)


def _rdp_simplify(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    if len(points) <= 3:
        return points
    first = points[0]
    last = points[-1]
    max_distance = -1.0
    index = 0
    for idx in range(1, len(points) - 1):
        distance = _perpendicular_distance(points[idx], first, last)
        if distance > max_distance:
            max_distance = distance
            index = idx
    if max_distance > tolerance:
        left = _rdp_simplify(points[: index + 1], tolerance)
        right = _rdp_simplify(points[index:], tolerance)
        return left[:-1] + right
    return [first, last]


def _simplify_ring(ring: list[tuple[float, float]], precision: str) -> list[tuple[float, float]]:
    tolerance = CITY_BOUNDARY_SIMPLIFY_TOLERANCE.get(precision, CITY_BOUNDARY_SIMPLIFY_TOLERANCE["low"])
    if len(ring) < 4:
        return ring
    closed = ring[0] == ring[-1]
    source = ring[:-1] if closed else ring
    simplified = _rdp_simplify(source, tolerance)
    if len(simplified) < 3:
        simplified = source[:3]
    if simplified[0] != simplified[-1]:
        simplified.append(simplified[0])
    return simplified


def _boundary_paths_for_precision(
    polygons: list[list[list[tuple[float, float]]]],
    precision: str,
) -> list[list[tuple[float, float]]]:
    paths: list[list[tuple[float, float]]] = []
    for polygon in polygons:
        if not polygon:
            continue
        exterior = polygon[0]
        simplified = _simplify_ring(exterior, precision)
        if len(simplified) >= 4:
            paths.append(simplified)
    return paths


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

    async def _city_cache_backend(self) -> str:
        if _city_cache_backend_setting() == "redis" and Redis is not None:
            return "redis"
        return "memory"

    async def _city_redis(self) -> Any | None:
        global _CITY_SITUATION_REDIS_CLIENT
        if await self._city_cache_backend() != "redis":
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
        if await self._city_cache_backend() == "redis":
            try:
                redis_client = await self._city_redis()
                payload = await redis_client.get(CITY_SITUATION_CACHE_KEY_PREFIX + cache_key) if redis_client else None
                if payload:
                    return VesselPositionCitySituationResponse.model_validate_json(payload), "redis"
            except Exception as exc:  # noqa: BLE001
                logger.warning("city situation redis cache read failed: %s", exc)
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
        if await self._city_cache_backend() == "redis":
            try:
                redis_client = await self._city_redis()
                if redis_client is not None:
                    await redis_client.setex(CITY_SITUATION_CACHE_KEY_PREFIX + cache_key, ttl, response.model_dump_json())
                    return
            except Exception as exc:  # noqa: BLE001
                logger.warning("city situation redis cache write failed: %s", exc)
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
        result = await self._position_monitor_items_for_profiles(
            profiles,
            generated_at=generated_at,
            reported_within_minutes=query.reported_within_minutes or 1440,
            es_batch_size=200,
            es_max_concurrency=1,
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
            ),
            items=fresh_items,
        )

    async def position_city_situation(self, query) -> VesselPositionCitySituationResponse:
        generated_at = datetime.utcnow()
        cache_key = _city_situation_query_cache_key(query)
        cache_backend = await self._city_cache_backend()
        if not query.force_refresh:
            cached = await self._get_city_situation_response_cache(cache_key)
            if cached is not None:
                cached_response, cache_backend = cached
                return cached_response.model_copy(
                    update={
                        "cache_status": "HIT",
                        "cache_generated_at": cached_response.generated_at,
                        "is_stale_cache": False,
                        "snapshot_backend": cache_backend,
                    },
                    deep=True,
                )
        profile_limit = query.profile_limit or query.max_profiles
        total_profile_count = await self._position_monitor_profile_count(query) if profile_limit is not None else None
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
            es_batch_size=query.es_batch_size,
            es_max_concurrency=query.es_max_concurrency,
            include_stale=True,
        )
        partial = result.partial
        error_message = result.error_message
        if profile_limit is not None:
            partial = True
            error_parts = [part for part in [error_message, f"当前按 profile_limit={profile_limit} 做部分统计"] if part]
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
        response = VesselPositionCitySituationResponse(
            source_status="ERROR" if partial and not cities else ("AVAILABLE" if cities else "EMPTY"),
            source_status_name=_source_status_name("ERROR" if partial and not cities else ("AVAILABLE" if cities else "EMPTY")),
            generated_at=generated_at,
            message=error_message if partial else (None if cities else "实时 ES 暂无符合筛选条件的城市态势"),
            cache_status="MISS",
            cache_generated_at=generated_at,
            is_stale_cache=False,
            snapshot_backend=cache_backend,
            summary=VesselPositionCitySituationSummary(
                matched_profile_count=total_profile_count or len(profiles),
                scanned_profile_count=len(profiles),
                unscanned_profile_count=unscanned_profile_count,
                queried_mmsi_count=result.queried_mmsi_count,
                matched_position_count=result.matched_position_count,
                unpositioned_count=result.unpositioned_count,
                invalid_position_count=result.invalid_position_count,
                unknown_city_count=result.unknown_city_count,
                positioned_count=len(positioned_items),
                stale_position_count=len(result.items) - len(positioned_items),
                contactable_position_count=sum(1 for item in positioned_items if item.contact_available),
                certificate_risk_count=sum(1 for item in positioned_items if risk_by_profile.get(item.id)),
                city_count=sum(1 for city in cities if city.city_code),
                boundary_city_count=sum(1 for city in cities if city.city_code and city.has_boundary),
                missing_boundary_city_count=len(missing_boundary_cities),
                missing_boundary_cities=missing_boundary_cities,
                query_snapshot_id=snapshot_id,
                failed_batch_count=result.failed_batch_count,
                is_partial=partial,
                error_message=error_message,
            ),
            cities=cities,
        )
        await self._store_city_situation_response_cache(cache_key, response)
        return response

    async def position_city_vessels(self, query) -> VesselPositionCityVesselsResponse:
        generated_at = datetime.utcnow()
        snapshot = await self._get_city_situation_snapshot(query.query_snapshot_id)
        snapshot_hit = snapshot is not None
        if snapshot:
            items = [
                item for item in snapshot.items
                if not self._is_stale_position(item, snapshot.generated_at, query.reported_within_minutes or 1440)
            ]
            partial = snapshot.partial
            error_message = snapshot.error_message
            snapshot_id = snapshot.snapshot_id
        else:
            profile_limit = query.profile_limit or query.max_profiles
            profiles = await self._position_monitor_profiles(query, limit=profile_limit)
            if not profiles or not await self._realtime_es_host():
                return VesselPositionCityVesselsResponse(total=0, page=query.page, page_size=query.page_size, items=[], query_snapshot_id=query.query_snapshot_id, snapshot_hit=False)
            result = await self._position_monitor_items_for_profiles(
                profiles,
                generated_at=generated_at,
                reported_within_minutes=query.reported_within_minutes or 1440,
                es_batch_size=query.es_batch_size,
                es_max_concurrency=query.es_max_concurrency,
                include_stale=False,
            )
            items = result.items
            partial = result.partial or profile_limit is not None
            error_message = result.error_message
            snapshot_id = await self._store_city_situation_snapshot(items, generated_at=generated_at, partial=partial, error_message=error_message)
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
            is_partial=partial,
            error_message=error_message,
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
        return await self._build_profile_response(entity.id)

    async def update_profile(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselProfileResponse:
        profile = await self._require_profile(vessel_id)
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        before = _row_dict(profile)
        if "ship_name" in updates:
            updates["ship_name"] = updates["ship_name"].strip()
        row = await self.repo.update_profile(vessel_id, updates)
        if row is None:
            raise NotFoundError("VesselProfile", vessel_id)
        if "ship_name" in updates and updates["ship_name"] != before.get("ship_name"):
            await self.repo.add_name_history(vessel_id, updates["ship_name"])
        if "current_mmsi" in updates and updates["current_mmsi"] != before.get("current_mmsi"):
            await self.repo.add_identifier_history(vessel_id, "MMSI", updates["current_mmsi"])
        await self._add_change_event(vessel_id, "UPDATE_PROFILE", "更新船舶主档", before, updates, operator_id)
        await self.db.commit()
        return await self._build_profile_response(vessel_id)

    async def get_detail(self, vessel_id: int) -> VesselDetailResponse:
        profile = await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        city_map = await _load_city_map(self.db, [profile.registry_city_code] if profile.registry_city_code else [])
        region_map = await _load_region_map(self.db, [profile.business_region_id] if profile.business_region_id else [])
        owner_rows = await self.repo.list_by_profile(VesselOwnerPeriod, vessel_id)
        owner_documents = await self._owner_documents_by_owner(vessel_id, label_map)
        return VesselDetailResponse(
            profile=_profile_response(profile, label_map=label_map, city_map=city_map, region_map=region_map),
            registration=self._maybe(VesselRegistrationResponse, await self.repo.get_one_by_profile(VesselRegistrationInfo, vessel_id)),
            capacity=self._maybe(VesselCapacityResponse, await self.repo.get_one_by_profile(VesselCapacityDimension, vessel_id)),
            build_info=self._maybe(VesselBuildInfoResponse, await self.repo.get_one_by_profile(VesselBuildInfo, vessel_id)),
            owners=[self._owner_response(row, label_map, documents=owner_documents.get(row.id, [])) for row in owner_rows],
            operators=[self._operator_response(row, label_map) for row in await self.repo.list_by_profile(VesselOperatorPeriod, vessel_id)],
            contacts=[self._contact_response(row, label_map) for row in await self.repo.list_by_profile(VesselContact, vessel_id)],
            crew=[self._crew_response(row, label_map) for row in await self.repo.list_by_profile(VesselCrewAssignment, vessel_id)],
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
        return VesselRegistrationResponse(**_row_dict(row))

    async def upsert_capacity(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselCapacityResponse:
        await self._require_profile(vessel_id)
        row = await self.repo.upsert_one_by_profile(VesselCapacityDimension, vessel_id, payload.model_dump(exclude_none=True))
        await self._add_change_event(vessel_id, "UPSERT_CAPACITY", "维护船舶尺寸信息", None, _row_dict(row), operator_id)
        await self.db.commit()
        return VesselCapacityResponse(**_row_dict(row))

    async def upsert_build_info(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselBuildInfoResponse:
        await self._require_profile(vessel_id)
        row = await self.repo.upsert_one_by_profile(VesselBuildInfo, vessel_id, payload.model_dump(exclude_none=True))
        await self._add_change_event(vessel_id, "UPSERT_BUILD_INFO", "维护建造信息", None, _row_dict(row), operator_id)
        await self.db.commit()
        return VesselBuildInfoResponse(**_row_dict(row))

    async def replace_owners(self, vessel_id: int, payload, *, operator_id: int | None = None) -> list[VesselOwnerResponse]:
        await self._require_profile(vessel_id)
        existing_current_owner = await self.db.scalar(
            select(VesselOwnerPeriod).where(
                VesselOwnerPeriod.vessel_profile_id == vessel_id,
                VesselOwnerPeriod.is_current.is_(True),
            ).limit(1)
        )
        if existing_current_owner is not None:
            raise ValidationError("当前所有方不可直接覆盖修改，请使用所有方变更流程生成新的船舶档案")
        owner_payloads = [item.model_dump(exclude_none=True) for item in payload.owners]
        current_count = sum(1 for item in owner_payloads if item.get("is_current", True))
        if current_count > 1:
            raise ValidationError("同一船舶业务档案只能有一个当前所有方")
        rows = await self.repo.replace_many_by_profile(
            VesselOwnerPeriod,
            vessel_id,
            owner_payloads,
        )
        await self._add_change_event(vessel_id, "REPLACE_OWNERS", "维护所有方", None, {"count": len(rows)}, operator_id)
        await self.db.commit()
        label_map = await _load_label_map(self.db)
        return [self._owner_response(row, label_map) for row in rows]

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
        rows = await self.repo.replace_many_by_profile(
            VesselOperatorPeriod,
            vessel_id,
            [item.model_dump(exclude_none=True) for item in payload.operators],
        )
        if rows:
            await self.repo.update_profile(vessel_id, {"operation_status_code": "OPERATING"})
        await self._add_change_event(vessel_id, "REPLACE_OPERATORS", "维护运营方", None, {"count": len(rows)}, operator_id)
        await self.db.commit()
        label_map = await _load_label_map(self.db)
        return [self._operator_response(row, label_map) for row in rows]

    async def replace_contacts(self, vessel_id: int, payload, *, operator_id: int | None = None) -> list[VesselContactResponse]:
        await self._require_profile(vessel_id)
        rows = await self.repo.replace_many_by_profile(
            VesselContact,
            vessel_id,
            [item.model_dump(exclude_none=True) for item in payload.contacts],
        )
        await self._add_change_event(vessel_id, "REPLACE_CONTACTS", "维护联系人", None, {"count": len(rows)}, operator_id)
        await self.db.commit()
        label_map = await _load_label_map(self.db)
        return [self._contact_response(row, label_map) for row in rows]

    async def replace_crew(self, vessel_id: int, payload, *, operator_id: int | None = None) -> list[VesselCrewResponse]:
        await self._require_profile(vessel_id)
        existing_rows = await self.repo.list_by_profile(VesselCrewAssignment, vessel_id)
        existing_by_id = {int(row.id): row for row in existing_rows}
        person_certs = list(
            (
                await self.db.execute(
                    select(VesselPersonCertificate).where(
                        VesselPersonCertificate.vessel_profile_id == vessel_id,
                        VesselPersonCertificate.voided_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        incoming_rows = [item.model_dump(exclude_none=True) for item in payload.crew]
        incoming_ids = {int(item["id"]) for item in incoming_rows if item.get("id") is not None}
        unknown_ids = sorted(incoming_ids - set(existing_by_id))
        if unknown_ids:
            raise ValidationError(f"船员任职记录不存在或不属于当前船舶：{', '.join(str(item) for item in unknown_ids)}")
        if person_certs:
            removed_bound_names = sorted(
                {
                    cert.holder_name
                    for cert in person_certs
                    if cert.crew_assignment_id is not None and int(cert.crew_assignment_id) not in incoming_ids
                }
            )
            if removed_bound_names:
                raise ValidationError(f"船员适任证仍绑定这些持有人，不能直接从任职中移除：{', '.join(removed_bound_names)}")
            incoming_names = {str(item.get("crew_name") or "").strip() for item in incoming_rows if item.get("crew_name")}
            missing_orphan_names = sorted(
                {
                    cert.holder_name
                    for cert in person_certs
                    if cert.crew_assignment_id is None and cert.holder_name not in incoming_names
                }
            )
            if missing_orphan_names:
                raise ValidationError(f"船员适任证仍绑定这些持有人，不能直接从任职中移除：{', '.join(missing_orphan_names)}")

        rows: list[VesselCrewAssignment] = []
        now = datetime.utcnow()
        for item in incoming_rows:
            item_id = item.pop("id", None)
            if item_id is not None:
                row = existing_by_id[int(item_id)]
                for key, value in item.items():
                    setattr(row, key, value)
                row.updated_at = now
            else:
                row = VesselCrewAssignment(vessel_profile_id=vessel_id, **item)
                self.db.add(row)
            rows.append(row)
        for row_id, row in existing_by_id.items():
            if row_id not in incoming_ids:
                await self.db.delete(row)
        await self.db.flush()
        if person_certs:
            crew_by_id = {int(row.id): row for row in rows if row.id is not None}
            crew_by_name = {row.crew_name: row for row in rows}
            for cert in person_certs:
                matched_crew = crew_by_id.get(int(cert.crew_assignment_id)) if cert.crew_assignment_id is not None else None
                if matched_crew is None:
                    matched_crew = crew_by_name.get(cert.holder_name)
                if matched_crew is not None:
                    cert.crew_assignment_id = matched_crew.id
                    cert.holder_name = matched_crew.crew_name
        await self._add_change_event(vessel_id, "REPLACE_CREW", "维护船员任职", None, {"count": len(rows)}, operator_id)
        await self.db.commit()
        label_map = await _load_label_map(self.db)
        return [self._crew_response(row, label_map) for row in rows]

    async def replace_person_certificates(self, vessel_id: int, payload, *, operator_id: int | None = None) -> list[VesselPersonCertificateResponse]:
        await self._require_profile(vessel_id)
        _ = payload, operator_id
        raise ValidationError("人员适任证不能整体替换保存，请按船员任职逐本新增、补充附件或作废")

    async def create_person_certificate(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselPersonCertificateResponse:
        await self._require_profile(vessel_id)
        data = payload.model_dump(exclude_none=True)
        crew = await self._require_crew_assignment(vessel_id, data.get("crew_assignment_id"))
        data["crew_assignment_id"] = crew.id
        data["holder_name"] = data.get("holder_name") or crew.crew_name
        data["certificate_type_code"] = CREW_CERTIFICATE_TYPE
        data.setdefault("verify_status_code", "PENDING")
        row = await self.repo.create_person_certificate(vessel_id, data)
        await self._add_change_event(vessel_id, "CREATE_PERSON_CERTIFICATE", "新增人员证件", None, _row_dict(row), operator_id)
        await self.db.commit()
        return (await self._person_certificates_with_files(vessel_id, person_certificate_id=row.id))[0]

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
        if not updates:
            raise ValidationError("no update fields provided")
        if "crew_assignment_id" in updates:
            crew = await self._require_crew_assignment(vessel_id, updates["crew_assignment_id"])
            updates["holder_name"] = updates.get("holder_name") or crew.crew_name
        elif cert.crew_assignment_id is None:
            raise ValidationError("人员适任证必须绑定当前船员任职")
        if "certificate_type_code" in updates:
            updates["certificate_type_code"] = CREW_CERTIFICATE_TYPE
        row = await self.repo.update_person_certificate(person_certificate_id, updates)
        assert row is not None
        await self._add_change_event(vessel_id, "UPDATE_PERSON_CERTIFICATE", "更新人员证件", before, _row_dict(row), operator_id)
        await self.db.commit()
        return (await self._person_certificates_with_files(vessel_id, person_certificate_id=row.id))[0]

    async def delete_person_certificate(
        self,
        vessel_id: int,
        person_certificate_id: int,
        *,
        reason: str | None = None,
        operator_id: int | None = None,
    ) -> None:
        cert = await self.repo.get_person_certificate(person_certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselPersonCertificate", person_certificate_id)
        before = _row_dict(cert)
        now = datetime.utcnow()
        cert.voided_at = now
        cert.voided_by = operator_id
        cert.void_reason = reason or "人员适任证作废"
        cert.verify_status_code = "VOIDED"
        await self._add_change_event(vessel_id, "VOID_PERSON_CERTIFICATE", "作废人员适任证", before, _row_dict(cert), operator_id)
        await self.db.commit()

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
        profile.profile_status_code = "TRANSFERRED"
        existing_owners = await self.repo.list_by_profile(VesselOwnerPeriod, vessel_id)
        for owner in existing_owners:
            if owner.is_current:
                owner.is_current = False
                owner.end_date = transfer_date
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

    async def _search_realtime_positions_batched(
        self,
        mmsi_values: list[str],
        *,
        batch_size: int,
        max_concurrency: int,
    ) -> tuple[dict[str, dict[str, Any]], bool, str | None, int]:
        positions: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        unique_values = [value for value in dict.fromkeys(mmsi_values) if value]
        batches = [unique_values[start:start + batch_size] for start in range(0, len(unique_values), batch_size)]
        semaphore = asyncio.Semaphore(max(1, max_concurrency))

        async def run_batch(batch: list[str]) -> tuple[dict[str, dict[str, Any]], str | None]:
            async with semaphore:
                try:
                    return await self._search_realtime_positions(batch, max_hits=max(len(batch) * 3, 200)), None
                except Exception as exc:  # noqa: BLE001
                    return {}, str(exc)

        for batch_positions, error in await asyncio.gather(*(run_batch(batch) for batch in batches)):
            if batch_positions:
                positions.update(batch_positions)
            if error:
                errors.append(error)
        return positions, bool(errors), "；".join(errors[:3]) if errors else None, len(errors)

    async def _position_monitor_items_for_profiles(
        self,
        profiles: list[VesselProfile],
        *,
        generated_at: datetime,
        reported_within_minutes: int,
        es_batch_size: int,
        es_max_concurrency: int,
        include_stale: bool,
    ) -> _PositionBuildResult:
        mmsi_by_profile = await self._mmsi_values_by_profile([row.id for row in profiles])
        mmsi_values = sorted({item for values in mmsi_by_profile.values() for item in values if item})
        if not mmsi_values:
            return _PositionBuildResult([], False, None, 0, 0, 0, 0, 0, 0)
        positions, partial, error_message, failed_batch_count = await self._search_realtime_positions_batched(
            mmsi_values,
            batch_size=es_batch_size,
            max_concurrency=es_max_concurrency,
        )
        boundaries = await self._city_boundaries()
        boundary_grid = _CITY_BOUNDARY_CACHE.get("grid_index") or {}
        profile_by_mmsi: dict[str, VesselProfile] = {}
        for profile in profiles:
            for mmsi in mmsi_by_profile.get(profile.id, [profile.current_mmsi]):
                profile_by_mmsi[mmsi] = profile
        position_by_profile: dict[int, dict[str, Any]] = {}
        freshness_limit = generated_at - timedelta(minutes=reported_within_minutes)
        for mmsi, position in positions.items():
            profile = profile_by_mmsi.get(mmsi)
            if profile is None or profile.id in position_by_profile:
                continue
            position_time = position.get("position_time")
            if not include_stale and position_time and position_time < freshness_limit:
                continue
            position_by_profile[profile.id] = position
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
                continue
            resolved_city = self._resolve_current_city_from_boundaries(longitude, latitude, boundaries, boundary_grid)
            if resolved_city.current_city_source != CURRENT_CITY_SOURCE_ADMIN_BOUNDARY:
                unknown_city_count += 1
            position_time = position.get("position_time")
            age_minutes = int((generated_at - position_time).total_seconds() // 60) if position_time else None
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
                )
            )
        matched_position_count = len(items)
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
        )

    def _is_stale_position(self, item: VesselPositionMonitorItemResponse, generated_at: datetime, reported_within_minutes: int) -> bool:
        return bool(item.position_time and item.position_time < generated_at - timedelta(minutes=reported_within_minutes))

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
    ) -> list[VesselPositionCitySituationItemResponse]:
        boundary_paths_by_code = boundary_paths_by_code or {}
        boundary_codes = boundary_codes or set(boundary_paths_by_code.keys())
        grouped: dict[str, list[VesselPositionMonitorItemResponse]] = defaultdict(list)
        for item in items:
            grouped[self._position_city_code(item)].append(item)
        result: list[VesselPositionCitySituationItemResponse] = []
        for city_code, city_items in grouped.items():
            fresh_items = [item for item in city_items if not self._is_stale_position(item, generated_at, reported_within_minutes)]
            stats_items = fresh_items or city_items
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
            serialized_boundary_paths = None if is_unknown_city else self._serialize_boundary_paths(boundary_paths_by_code.get(city_code))
            has_boundary = False if is_unknown_city else city_code in boundary_codes
            result.append(
                VesselPositionCitySituationItemResponse(
                    city_code=None if is_unknown_city else city_code,
                    city_name=self._position_city_name(first_item) if first_item else UNKNOWN_CITY_NAME,
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
                    latest_position_time=max([item.position_time for item in city_items if item.position_time], default=None),
                    mmsi_count=queried_mmsi_count if is_unknown_city else len(city_items),
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

    @staticmethod
    def _serialize_boundary_paths(paths: list[list[tuple[float, float]]] | None) -> list[list[list[float]]] | None:
        if not paths:
            return None
        return [[[float(lng), float(lat)] for lng, lat in ring] for ring in paths if len(ring) >= 4] or None

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
        snapshot = _CitySituationSnapshot(
            snapshot_id=snapshot_id,
            expires_at=now + timedelta(seconds=ttl_seconds),
            items=list(items),
            partial=partial,
            error_message=error_message,
            generated_at=generated_at,
        )
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
                    )
                    if restored.expires_at > datetime.utcnow():
                        _CITY_SITUATION_SNAPSHOTS[snapshot_id] = restored
                        return restored
            except Exception as exc:  # noqa: BLE001
                logger.warning("city situation redis snapshot read failed: %s", exc)
        return None

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
        )

    def _contact_response(self, row: VesselContact, label_map: dict[str, dict[str, str]]) -> VesselContactResponse:
        return VesselContactResponse(
            **_row_dict(row),
            contact_scope_name=label_map.get("CONTACT_SCOPE", {}).get(row.contact_scope_code),
            contact_role_name=label_map.get("CONTACT_ROLE", {}).get(row.contact_role_code),
        )

    def _crew_response(self, row: VesselCrewAssignment, label_map: dict[str, dict[str, str]]) -> VesselCrewResponse:
        return VesselCrewResponse(
            **_row_dict(row),
            crew_role_name=label_map.get("VESSEL_CREW_ROLE", {}).get(row.crew_role_code),
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
    ) -> None:
        self.db.add(
            VesselChangeEvent(
                vessel_profile_id=vessel_id,
                event_type_code=event_type_code,
                event_title=event_title,
                before_json=_jsonable(before),
                after_json=_jsonable(after),
                operator_id=operator_id,
                created_at=datetime.utcnow(),
            )
        )
        await self.db.flush()

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
