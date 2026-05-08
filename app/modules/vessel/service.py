"""vessel 模块 service。"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import UploadFile
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError, ValidationError
from app.integrations.ai.vessel_image_assistant import VesselCertificateImageAssistant
from app.integrations.config_keys import ES_R_HOST, ES_R_INDEX, ES_REALTIME_CONFIG_PROFILE
from app.integrations.es import RealtimeEsClient
from app.models.address import AdminRegion, Region
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
from app.modules.storage.service import FileStorageService
from app.modules.system.runtime_config import RuntimeConfigService
from app.modules.vessel.repository import VesselRepository
from app.modules.vessel.schemas import (
    PageResponse,
    VesselBuildInfoResponse,
    VesselCapacityResponse,
    VesselCertificateFileResponse,
    VesselCertificateImageRecognitionResponse,
    VesselCertificateResponse,
    VesselChangeEventResponse,
    VesselContactResponse,
    VesselCrewResponse,
    VesselDetailResponse,
    VesselIdentifierHistoryResponse,
    VesselListItemResponse,
    VesselNameHistoryResponse,
    VesselOperatorResponse,
    VesselOwnerResponse,
    VesselOwnerDocumentImageRecognitionResponse,
    VesselOwnerDocumentResponse,
    VesselPersonCertificateFileResponse,
    VesselPersonCertificateImageRecognitionResponse,
    VesselPersonCertificateResponse,
    VesselPositionMonitorItemResponse,
    VesselPositionMonitorResponse,
    VesselPositionMonitorSummary,
    VesselProfileResponse,
    VesselRegistrationResponse,
)


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
    "OWNER_DOCUMENT_TYPE",
    "CERTIFICATE_VERIFY_STATUS",
    "VESSEL_CERTIFICATE_IMAGE_RECOGNITION_STATUS",
    "VESSEL_POSITION_SOURCE_STATUS",
    "VESSEL_CHANGE_EVENT_TYPE",
]


IMAGE_RECOGNIZABLE_OWNER_DOCUMENT_TYPES = {"PERSON_ID_FRONT", "PERSON_ID_BACK", "BUSINESS_LICENSE"}


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
        try:
            positions = await self._search_realtime_positions(mmsi_values, max_hits=max(query.max_items * 4, 200))
        except Exception as exc:  # noqa: BLE001
            return VesselPositionMonitorResponse(
                source_status="ERROR",
                source_status_name=_source_status_name("ERROR"),
                generated_at=generated_at,
                message=f"实时 ES 查询失败：{exc}",
                summary=VesselPositionMonitorSummary(
                    matched_profile_count=len(profiles),
                    positioned_count=0,
                    stale_position_count=0,
                    contactable_position_count=0,
                ),
                items=[],
            )
        if not positions:
            return self._empty_position_response(generated_at, "实时 ES 未返回匹配船位", len(profiles))

        profile_by_mmsi: dict[str, VesselProfile] = {}
        for profile in profiles:
            for mmsi in mmsi_by_profile.get(profile.id, [profile.current_mmsi]):
                profile_by_mmsi[mmsi] = profile
        positioned_profiles: list[VesselProfile] = []
        position_by_profile: dict[int, dict[str, Any]] = {}
        stale_count = 0
        freshness_limit = generated_at - timedelta(minutes=query.reported_within_minutes or 1440)
        for mmsi, position in positions.items():
            profile = profile_by_mmsi.get(mmsi)
            if profile is None:
                continue
            position_time = position.get("position_time")
            if position_time and position_time < freshness_limit:
                stale_count += 1
                continue
            if profile.id in position_by_profile:
                continue
            positioned_profiles.append(profile)
            position_by_profile[profile.id] = position
            if len(positioned_profiles) >= query.max_items:
                break
        list_items = await self._build_list_items(positioned_profiles)
        items: list[VesselPositionMonitorItemResponse] = []
        for item in list_items:
            position = position_by_profile.get(item.id)
            if position is None:
                continue
            longitude = _to_decimal(position.get("longitude"))
            latitude = _to_decimal(position.get("latitude"))
            if longitude is None or latitude is None:
                continue
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
                    location_text=position.get("location_text"),
                    position_source_name="实时 ES",
                )
            )
        return VesselPositionMonitorResponse(
            source_status="AVAILABLE" if items else "EMPTY",
            source_status_name=_source_status_name("AVAILABLE" if items else "EMPTY"),
            generated_at=generated_at,
            message=None if items else "实时 ES 暂无符合筛选条件的船位",
            summary=VesselPositionMonitorSummary(
                matched_profile_count=len(profiles),
                positioned_count=len(items),
                stale_position_count=stale_count,
                contactable_position_count=sum(1 for item in items if item.contact_available),
            ),
            items=items,
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
        return self._owner_document_response(row, label_map, latest_recognition=latest)

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
        if payload.apply_to_owner:
            party_name = accepted.get("holder_name") or accepted.get("company_name") or accepted.get("party_name")
            certificate_no = accepted.get("certificate_no") or accepted.get("document_no") or accepted.get("license_no")
            address = accepted.get("address")
            if party_name:
                updates["party_name"] = str(party_name).strip()
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
            {"recognition_id": recognition.id, "owner_updates": updates},
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
        rows = await self.repo.replace_many_by_profile(
            VesselCrewAssignment,
            vessel_id,
            [item.model_dump(exclude_none=True) for item in payload.crew],
        )
        await self._add_change_event(vessel_id, "REPLACE_CREW", "维护船员任职", None, {"count": len(rows)}, operator_id)
        await self.db.commit()
        label_map = await _load_label_map(self.db)
        return [self._crew_response(row, label_map) for row in rows]

    async def replace_person_certificates(self, vessel_id: int, payload, *, operator_id: int | None = None) -> list[VesselPersonCertificateResponse]:
        await self._require_profile(vessel_id)
        existing_ids = (
            await self.db.execute(
                select(VesselPersonCertificate.id).where(VesselPersonCertificate.vessel_profile_id == vessel_id)
            )
        ).scalars().all()
        if existing_ids:
            await self.db.execute(
                delete(VesselPersonCertificateImageRecognition).where(
                    VesselPersonCertificateImageRecognition.vessel_person_certificate_id.in_(existing_ids)
                )
            )
            await self.db.execute(
                delete(VesselPersonCertificateFile).where(
                    VesselPersonCertificateFile.vessel_person_certificate_id.in_(existing_ids)
                )
            )
        rows = await self.repo.replace_many_by_profile(
            VesselPersonCertificate,
            vessel_id,
            [item.model_dump(exclude_none=True) for item in payload.person_certificates],
        )
        await self._add_change_event(vessel_id, "REPLACE_PERSON_CERTIFICATES", "维护人员证书", None, {"count": len(rows)}, operator_id)
        await self.db.commit()
        return await self._person_certificates_with_files(vessel_id)

    async def create_person_certificate(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselPersonCertificateResponse:
        await self._require_profile(vessel_id)
        data = payload.model_dump(exclude_none=True)
        data.setdefault("holder_name", "待补录")
        data.setdefault("certificate_type_code", "CREW_COMPETENCY_CERT")
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
        operator_id: int | None = None,
    ) -> None:
        cert = await self.repo.get_person_certificate(person_certificate_id)
        if cert is None or cert.vessel_profile_id != vessel_id:
            raise NotFoundError("VesselPersonCertificate", person_certificate_id)
        before = _row_dict(cert)
        await self.db.execute(
            delete(VesselPersonCertificateImageRecognition).where(
                VesselPersonCertificateImageRecognition.vessel_person_certificate_id == person_certificate_id
            )
        )
        await self.db.execute(
            delete(VesselPersonCertificateFile).where(
                VesselPersonCertificateFile.vessel_person_certificate_id == person_certificate_id
            )
        )
        await self.repo.delete_person_certificate(person_certificate_id)
        await self._add_change_event(vessel_id, "DELETE_PERSON_CERTIFICATE", "删除人员证件", before, None, operator_id)
        await self.db.commit()

    async def upload_person_certificate_file_first(
        self,
        vessel_id: int,
        file: UploadFile,
        *,
        certificate_type_code: str = "CREW_COMPETENCY_CERT",
        holder_name: str = "待补录",
        operator_id: int | None = None,
    ) -> VesselPersonCertificateResponse:
        await self._require_profile(vessel_id)
        cert = await self.repo.create_person_certificate(
            vessel_id,
            {
                "holder_name": holder_name.strip() or "待补录",
                "certificate_type_code": certificate_type_code or "CREW_COMPETENCY_CERT",
                "verify_status_code": "PENDING",
                "remark": "由人员证件附件上传创建，待识别或人工补录",
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
        await self._add_change_event(vessel_id, "CREATE_PERSON_CERTIFICATE", "上传附件创建人员证件草稿", None, _row_dict(cert), operator_id)
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

    async def create_certificate(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselCertificateResponse:
        await self._require_profile(vessel_id)
        row = await self.repo.create_certificate(vessel_id, payload.model_dump(exclude_none=True))
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
        row = await self.repo.update_certificate(certificate_id, updates)
        assert row is not None
        await self._add_change_event(row.vessel_profile_id, "UPDATE_CERTIFICATE", "更新船舶证件", before, _row_dict(row), operator_id)
        await self.db.commit()
        return (await self._certificates_with_files(row.vessel_profile_id, certificate_id=row.id))[0]

    async def upload_certificate_file_first(
        self,
        vessel_id: int,
        file: UploadFile,
        *,
        certificate_type_code: str = "UNKNOWN",
        operator_id: int | None = None,
    ) -> VesselCertificateResponse:
        await self._require_profile(vessel_id)
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
                "status_code": "PROCESSING",
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
                "status_code": "PROCESSING",
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
                "status_code": "PROCESSING",
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
            storage_file, file_result = await FileStorageService(self.db).download_file(recognition.storage_file_id)
            result = await VesselCertificateImageAssistant(self.runtime_config).recognize(
                content=file_result.content,
                content_type=file_result.content_type or storage_file.content_type,
                file_name=storage_file.original_file_name,
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
            storage_file, file_result = await FileStorageService(self.db).download_file(recognition.storage_file_id)
            result = await VesselCertificateImageAssistant(self.runtime_config).recognize(
                content=file_result.content,
                content_type=file_result.content_type or storage_file.content_type,
                file_name=storage_file.original_file_name,
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
            storage_file, file_result = await FileStorageService(self.db).download_file(recognition.storage_file_id)
            result = await VesselCertificateImageAssistant(self.runtime_config).recognize(
                content=file_result.content,
                content_type=file_result.content_type or storage_file.content_type,
                file_name=storage_file.original_file_name,
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

    async def _require_profile(self, vessel_id: int) -> VesselProfile:
        profile = await self.repo.get_profile(vessel_id)
        if profile is None:
            raise NotFoundError("VesselProfile", vessel_id)
        return profile

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

    async def _position_monitor_profiles(self, query) -> list[VesselProfile]:
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
        rows = (
            await self.db.execute(
                stmt.group_by(VesselProfile.id)
                .order_by(VesselProfile.updated_at.desc(), VesselProfile.id.desc())
                .limit(max(query.max_items * 3, query.max_items))
            )
        ).scalars().all()
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
            if longitude is None or latitude is None:
                continue
            if not (Decimal("-180") <= longitude <= Decimal("180") and Decimal("-90") <= latitude <= Decimal("90")):
                continue
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
            }
        return result

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
        stmt = select(VesselCertificate).where(VesselCertificate.vessel_profile_id == vessel_id)
        if certificate_id:
            stmt = stmt.where(VesselCertificate.id == certificate_id)
        certs = (await self.db.execute(stmt.order_by(VesselCertificate.id.desc()))).scalars().all()
        if not certs:
            return []
        files = (
            await self.db.execute(
                select(VesselCertificateFile).where(
                    VesselCertificateFile.vessel_certificate_id.in_([row.id for row in certs])
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
        for row in recognition_rows:
            latest_recognition_map.setdefault(row.vessel_certificate_id, row)
        return [
            self._certificate_response(
                cert,
                files=file_map.get(cert.id, []),
                label_map=label_map,
                latest_recognition=latest_recognition_map.get(cert.id),
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
        stmt = select(VesselPersonCertificate).where(VesselPersonCertificate.vessel_profile_id == vessel_id)
        if person_certificate_id:
            stmt = stmt.where(VesselPersonCertificate.id == person_certificate_id)
        certs = (await self.db.execute(stmt.order_by(VesselPersonCertificate.id.desc()))).scalars().all()
        if not certs:
            return []
        files = (
            await self.db.execute(
                select(VesselPersonCertificateFile).where(
                    VesselPersonCertificateFile.vessel_person_certificate_id.in_([row.id for row in certs])
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
        for row in recognition_rows:
            latest_recognition_map.setdefault(row.vessel_person_certificate_id, row)
        return [
            self._person_certificate_response(
                cert,
                label_map,
                files=file_map.get(cert.id, []),
                latest_recognition=latest_recognition_map.get(cert.id),
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
        docs = await self.repo.list_owner_documents(vessel_id)
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
        for row in recognition_rows:
            latest_recognition_map.setdefault(row.owner_document_id, row)
        result: dict[int, list[VesselOwnerDocumentResponse]] = defaultdict(list)
        for row in docs:
            result[row.vessel_owner_period_id].append(
                self._owner_document_response(row, label_map, latest_recognition=latest_recognition_map.get(row.id))
            )
        return result

    def _owner_document_response(
        self,
        row: VesselOwnerDocument,
        label_map: dict[str, dict[str, str]],
        *,
        latest_recognition: VesselOwnerDocumentImageRecognition | None = None,
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
        return VesselOwnerResponse(
            **_row_dict(row),
            party_type_name=label_map.get("PARTY_SUBJECT_TYPE", {}).get(row.party_type_code),
            documents=documents or [],
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
    ) -> VesselPersonCertificateResponse:
        return VesselPersonCertificateResponse(
            **_row_dict(row),
            certificate_type_name=label_map.get("CERTIFICATE_TYPE", {}).get(row.certificate_type_code),
            verify_status_name=label_map.get("CERTIFICATE_VERIFY_STATUS", {}).get(row.verify_status_code),
            files=files or [],
            latest_image_recognition=(
                self._person_image_recognition_response(latest_recognition, label_map)
                if latest_recognition is not None
                else None
            ),
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
    ) -> VesselCertificateResponse:
        recognition_status = latest_recognition.status_code if latest_recognition is not None else "NOT_STARTED"
        confirmation_status = "CONFIRMED" if recognition_status == "CONFIRMED" else "UNCONFIRMED"
        return VesselCertificateResponse(
            **_row_dict(row),
            certificate_type_name=label_map.get("CERTIFICATE_TYPE", {}).get(row.certificate_type_code),
            verify_status_name=label_map.get("CERTIFICATE_VERIFY_STATUS", {}).get(row.verify_status_code),
            recognition_status_code=recognition_status,
            recognition_status_name=label_map.get("VESSEL_CERTIFICATE_IMAGE_RECOGNITION_STATUS", {}).get(recognition_status),
            confirmation_status_code=confirmation_status,
            confirmation_status_name=label_map.get("VESSEL_CERTIFICATE_IMAGE_RECOGNITION_STATUS", {}).get(confirmation_status),
            files=files,
            latest_image_recognition=(
                self._image_recognition_response(latest_recognition, label_map) if latest_recognition is not None else None
            ),
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
