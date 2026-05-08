"""vessel 模块 service。"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import UploadFile
from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError, ValidationError
from app.integrations.config_keys import ES_R_HOST, ES_R_INDEX, ES_REALTIME_CONFIG_PROFILE
from app.integrations.ai.vessel_image_assistant import VesselCertificateImageAssistant
from app.integrations.es import RealtimeEsClient
from app.models.address import AdminRegion, Region
from app.models.dictionary import StdDict, StdDictItem
from app.models.storage import StorageFile
from app.models.vessel import (
    VesselBehaviorProfile,
    VesselBuildInfo,
    VesselCapacityDimension,
    VesselCargoCapability,
    VesselCertificate,
    VesselCertificateFile,
    VesselCertificateImageRecognition,
    VesselChangeEvent,
    VesselContact,
    VesselCrewAssignment,
    VesselIdentifierHistory,
    VesselIdentity,
    VesselIdentityCandidate,
    VesselIdentityLink,
    VesselManualPreference,
    VesselNameHistory,
    VesselOperatorPeriod,
    VesselOwnerPeriod,
    VesselPersonCertificate,
    VesselProfile,
    VesselQualityIssue,
    VesselQualitySnapshot,
    VesselRegistrationInfo,
)
from app.modules.dictionary.service import CodeSequenceService
from app.modules.storage.service import FileStorageService
from app.modules.system.runtime_config import RuntimeConfigService
from app.modules.vessel.repository import VesselRepository
from app.modules.vessel.schemas import (
    PageResponse,
    VesselBehaviorProfileResponse,
    VesselBuildInfoResponse,
    VesselCapacityResponse,
    VesselCargoCapabilityResponse,
    VesselCertificateFileResponse,
    VesselCertificateImageRecognitionResponse,
    VesselCertificateResponse,
    VesselChangeEventResponse,
    VesselContactResponse,
    VesselCrewResponse,
    VesselDashboardResponse,
    VesselDashboardRiskItem,
    VesselDashboardTaskBucket,
    VesselDetailResponse,
    VesselGovernanceSummaryResponse,
    VesselGovernanceTaskResponse,
    VesselIdentifierHistoryResponse,
    VesselIdentityCandidateResponse,
    VesselImportConfirmResponse,
    VesselImportPreviewResponse,
    VesselListItemResponse,
    VesselManualPreferenceResponse,
    VesselMetricResponse,
    VesselNameHistoryResponse,
    VesselOperatorResponse,
    VesselOwnerResponse,
    VesselPersonCertificateResponse,
    VesselPositionMonitorItemResponse,
    VesselPositionMonitorResponse,
    VesselPositionMonitorSummary,
    VesselProfileResponse,
    VesselQualityIssueResponse,
    VesselQualitySnapshotResponse,
    VesselRealtimeSourceStatus,
    VesselRegistrationResponse,
)


LABEL_DICTS = [
    "SHIP_TYPE",
    "NAVIGATION_POWER_TYPE",
    "VESSEL_PROFILE_STATUS",
    "VESSEL_IDENTITY_STATUS",
    "VESSEL_QUALITY_LEVEL",
    "SHIP_OPERATION_STATUS",
    "SOURCE_TYPE",
    "AUDIT_STATUS",
    "CONTACT_ROLE",
    "PARTY_SUBJECT_TYPE",
    "PARTY_RELATION_TYPE",
    "VESSEL_OPERATOR_ROLE",
    "VESSEL_OPERATOR_RISK_LEVEL",
    "CERTIFICATE_TYPE",
    "CERTIFICATE_VERIFY_STATUS",
    "VESSEL_CERTIFICATE_IMAGE_RECOGNITION_STATUS",
    "VESSEL_CERTIFICATE_RISK",
    "VESSEL_QUALITY_ISSUE_TYPE",
    "VESSEL_QUALITY_ISSUE_STATUS",
    "VESSEL_ISSUE_SEVERITY",
    "VESSEL_IDENTITY_CANDIDATE_TYPE",
    "VESSEL_IDENTITY_CANDIDATE_STATUS",
    "VESSEL_POSITION_SOURCE_STATUS",
    "VESSEL_CHANGE_EVENT_TYPE",
]


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


def _capability_summary(row: VesselCargoCapability | None) -> str | None:
    if row is None:
        return None
    tags: list[str] = []
    if row.has_self_unloading:
        tags.append("自卸")
    if row.has_container_fittings:
        tags.append("集装箱")
    if row.can_carry_dangerous:
        tags.append("危货")
    if row.temperature_control:
        tags.append("温控")
    for item in row.capability_tags_json or []:
        if isinstance(item, str) and item not in tags:
            tags.append(item)
    return "、".join(tags[:4]) if tags else row.cargo_handling_notes


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
        navigation_power_type_name=label_map.get("NAVIGATION_POWER_TYPE", {}).get(row.navigation_power_type_code or ""),
        profile_status_name=label_map.get("VESSEL_PROFILE_STATUS", {}).get(row.profile_status_code),
        identity_status_name=label_map.get("VESSEL_IDENTITY_STATUS", {}).get(row.identity_status_code),
        quality_level_name=label_map.get("VESSEL_QUALITY_LEVEL", {}).get(row.quality_level_code),
        operation_status_name=label_map.get("SHIP_OPERATION_STATUS", {}).get(row.operation_status_code or ""),
        source_type_name=label_map.get("SOURCE_TYPE", {}).get(row.source_type_code),
        audit_status_name=label_map.get("AUDIT_STATUS", {}).get(row.audit_status),
        registry_city_name=city_map.get(row.registry_city_code or ""),
        business_region_name=region_map.get(row.business_region_id or 0),
        ship_age=_ship_age(row.building_year),
    )


def _certificate_risk(certificates: list[VesselCertificate]) -> str:
    if not certificates:
        return "MISSING"
    today = date.today()
    soon = today + timedelta(days=30)
    has_valid = False
    has_expiring = False
    for cert in certificates:
        if cert.is_long_term_valid:
            has_valid = True
            continue
        if cert.valid_to is None:
            continue
        if cert.valid_to < today:
            return "EXPIRED"
        if cert.valid_to <= soon:
            has_expiring = True
        else:
            has_valid = True
    if has_expiring:
        return "EXPIRING"
    return "OK" if has_valid else "UNKNOWN"


def _certificate_risk_name(code: str | None) -> str:
    return {
        "MISSING": "证件缺失",
        "EXPIRED": "证件过期",
        "EXPIRING": "即将到期",
        "OK": "证件正常",
        "UNKNOWN": "需核验",
    }.get(code or "", code or "未知")


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


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = []
        for key in ("name", "text", "label", "ship_type", "cargo", "route", "mmsi", "ais_id", "certificate_no"):
            if value.get(key):
                parts.append(str(value.get(key)))
        return " ".join(parts) if parts else " ".join(str(item) for item in value.values() if item is not None)
    if isinstance(value, list):
        return " ".join(_json_text(item) for item in value)
    return str(value)


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


def _contains_json_text(value: Any, keyword: str) -> bool:
    return keyword.lower() in _json_text(value).lower()


def _quality_action(issue_type_code: str) -> str:
    return {
        "MISSING_SHIP_TYPE": "补全船型",
        "MISSING_CAPACITY": "补全载重与尺度",
        "MISSING_OWNER": "维护所有人",
        "MISSING_OPERATOR": "维护运营方",
        "MISSING_CONTACT": "维护主联系人",
        "MISSING_CERTIFICATE": "补充船舶证件",
        "DUPLICATE_MMSI": "查看重复身份候选",
        "IDENTITY_CONFLICT": "核对身份关系",
    }.get(issue_type_code, "处理资料问题")


def _evidence_summary(value: dict[str, Any] | None) -> str | None:
    if not value:
        return None
    parts: list[str] = []
    for key, label in {
        "mmsi": "MMSI",
        "ais_id": "AIS",
        "ship_name": "船名",
        "certificate_no": "证件号",
    }.items():
        if value.get(key):
            parts.append(f"{label} {value[key]}")
    return "；".join(parts) if parts else _json_text(value)


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

    async def dashboard(self) -> VesselDashboardResponse:
        profiles = (
            await self.db.execute(select(VesselProfile).where(VesselProfile.deleted_at.is_(None)))
        ).scalars().all()
        capacities = (
            await self.db.execute(select(VesselCapacityDimension))
        ).scalars().all()
        issues_count = int(
            await self.db.scalar(
                select(func.count()).select_from(VesselQualityIssue).where(VesselQualityIssue.status_code == "OPEN")
            )
            or 0
        )
        contact_count = int(
            await self.db.scalar(
                select(func.count())
                .select_from(VesselContact)
                .where(VesselContact.is_available.is_(True))
            )
            or 0
        )
        total_deadweight = sum((_money(row.deadweight_ton) or Decimal("0")) for row in capacities)
        status_counts: dict[str, int] = defaultdict(int)
        quality_counts: dict[str, int] = defaultdict(int)
        for row in profiles:
            status_counts[row.profile_status_code] += 1
            quality_counts[row.quality_level_code] += 1
        label_map = await _load_label_map(self.db, ["VESSEL_PROFILE_STATUS", "VESSEL_QUALITY_LEVEL"])
        return VesselDashboardResponse(
            metrics=[
                VesselMetricResponse(code="total_count", name="船舶档案", value=len(profiles), unit="艘"),
                VesselMetricResponse(code="contactable_count", name="可联系船舶", value=contact_count, unit="艘"),
                VesselMetricResponse(code="open_issue_count", name="待治理问题", value=issues_count, unit="项"),
                VesselMetricResponse(code="total_deadweight_ton", name="总载重吨", value=total_deadweight, unit="吨"),
            ],
            status_distribution=[
                VesselMetricResponse(
                    code=code,
                    name=label_map.get("VESSEL_PROFILE_STATUS", {}).get(code, code),
                    value=count,
                    unit="艘",
                )
                for code, count in sorted(status_counts.items())
            ],
            quality_distribution=[
                VesselMetricResponse(
                    code=code,
                    name=label_map.get("VESSEL_QUALITY_LEVEL", {}).get(code, code),
                    value=count,
                    unit="艘",
                )
                for code, count in sorted(quality_counts.items())
            ],
            generated_at=datetime.utcnow(),
            risk_vessels=await self._dashboard_risk_vessels(),
            task_buckets=await self._governance_task_buckets(),
            position_status=await self._position_source_status(),
        )

    async def _dashboard_risk_vessels(self) -> list[VesselDashboardRiskItem]:
        rows = (
            await self.db.execute(
                select(VesselProfile)
                .where(
                    VesselProfile.deleted_at.is_(None),
                    or_(
                        VesselProfile.quality_level_code == "LOW",
                        VesselProfile.identity_status_code == "CONFLICT",
                        exists(
                            select(VesselQualityIssue.id).where(
                                VesselQualityIssue.vessel_profile_id == VesselProfile.id,
                                VesselQualityIssue.status_code == "OPEN",
                            )
                        ),
                    ),
                )
                .order_by(VesselProfile.updated_at.desc(), VesselProfile.id.desc())
                .limit(8)
            )
        ).scalars().all()
        if not rows:
            return []
        ids = [row.id for row in rows]
        label_map = await _load_label_map(self.db)
        issue_counts = await self._open_issue_counts(ids)
        certs = await self._certificates_by_profile(ids)
        latest_issues = await self._latest_open_issues(ids)
        result: list[VesselDashboardRiskItem] = []
        for profile in rows:
            risk = _certificate_risk(certs.get(profile.id, []))
            issue = latest_issues.get(profile.id)
            title = issue.issue_title if issue else _certificate_risk_name(risk)
            result.append(
                VesselDashboardRiskItem(
                    vessel_profile_id=profile.id,
                    ship_name=profile.ship_name,
                    current_mmsi=profile.current_mmsi,
                    vessel_profile_code=profile.vessel_profile_code,
                    risk_title=title,
                    risk_desc=getattr(issue, "issue_desc", None),
                    quality_level_code=profile.quality_level_code,
                    quality_level_name=label_map.get("VESSEL_QUALITY_LEVEL", {}).get(profile.quality_level_code),
                    certificate_risk=risk,
                    certificate_risk_name=_certificate_risk_name(risk),
                    open_issue_count=issue_counts.get(profile.id, 0),
                )
            )
        return result

    async def _position_source_status(self) -> VesselRealtimeSourceStatus:
        now = datetime.utcnow()
        if not await self._realtime_es_host():
            return VesselRealtimeSourceStatus(
                source_status="UNCONFIGURED",
                source_status_name=_source_status_name("UNCONFIGURED"),
                message="实时 ES 未配置，船位监控将显示空态",
                generated_at=now,
            )
        return VesselRealtimeSourceStatus(
            source_status="AVAILABLE",
            source_status_name=_source_status_name("AVAILABLE"),
            message=None,
            generated_at=now,
        )

    async def _governance_task_buckets(self) -> list[VesselDashboardTaskBucket]:
        open_issue_count = int(
            await self.db.scalar(
                select(func.count()).select_from(VesselQualityIssue).where(VesselQualityIssue.status_code == "OPEN")
            )
            or 0
        )
        high_issue_count = int(
            await self.db.scalar(
                select(func.count())
                .select_from(VesselQualityIssue)
                .where(VesselQualityIssue.status_code == "OPEN", VesselQualityIssue.severity_code == "HIGH")
            )
            or 0
        )
        identity_count = int(
            await self.db.scalar(
                select(func.count())
                .select_from(VesselIdentityCandidate)
                .where(VesselIdentityCandidate.status_code == "PENDING")
            )
            or 0
        )
        missing_cert_count = int(
            await self.db.scalar(
                select(func.count()).select_from(VesselProfile).where(
                    VesselProfile.deleted_at.is_(None),
                    ~exists(
                        select(VesselCertificate.id).where(VesselCertificate.vessel_profile_id == VesselProfile.id)
                    ),
                )
            )
            or 0
        )
        return [
            VesselDashboardTaskBucket(code="PROFILE_COMPLETION", name="资料补全", count=open_issue_count, action_path="/vessels/governance?tab=completion"),
            VesselDashboardTaskBucket(code="HIGH_RISK", name="高风险问题", count=high_issue_count, action_path="/vessels/governance?tab=completion&severity=HIGH"),
            VesselDashboardTaskBucket(code="CERTIFICATE_RISK", name="证件风险", count=missing_cert_count, action_path="/vessels/governance?tab=certificate"),
            VesselDashboardTaskBucket(code="IDENTITY_CANDIDATE", name="重复身份", count=identity_count, action_path="/vessels/governance?tab=identity"),
        ]

    async def governance_summary(self) -> VesselGovernanceSummaryResponse:
        open_issue_count = int(
            await self.db.scalar(
                select(func.count()).select_from(VesselQualityIssue).where(VesselQualityIssue.status_code == "OPEN")
            )
            or 0
        )
        pending_identity_count = int(
            await self.db.scalar(
                select(func.count()).select_from(VesselIdentityCandidate).where(VesselIdentityCandidate.status_code == "PENDING")
            )
            or 0
        )
        low_quality_count = int(
            await self.db.scalar(
                select(func.count()).select_from(VesselProfile).where(
                    VesselProfile.deleted_at.is_(None),
                    VesselProfile.quality_level_code == "LOW",
                )
            )
            or 0
        )
        today = date.today()
        expiring_cert_count = int(
            await self.db.scalar(
                select(func.count()).select_from(VesselCertificate).where(
                    VesselCertificate.is_long_term_valid.is_(False),
                    VesselCertificate.valid_to.is_not(None),
                    VesselCertificate.valid_to >= today,
                    VesselCertificate.valid_to <= today + timedelta(days=30),
                )
            )
            or 0
        )
        return VesselGovernanceSummaryResponse(
            generated_at=datetime.utcnow(),
            metrics=[
                VesselMetricResponse(code="open_issue_count", name="待处理问题", value=open_issue_count, unit="项"),
                VesselMetricResponse(code="low_quality_count", name="低质量档案", value=low_quality_count, unit="艘"),
                VesselMetricResponse(code="pending_identity_count", name="重复身份候选", value=pending_identity_count, unit="组"),
                VesselMetricResponse(code="expiring_cert_count", name="证件即将到期", value=expiring_cert_count, unit="项"),
            ],
            task_buckets=await self._governance_task_buckets(),
        )

    async def governance_tasks(
        self,
        *,
        task_type: str | None = None,
        status_code: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> PageResponse[VesselGovernanceTaskResponse]:
        tasks: list[VesselGovernanceTaskResponse] = []
        label_map = await _load_label_map(self.db)
        if task_type in (None, "COMPLETION", "QUALITY", "CERTIFICATE"):
            issue_stmt = select(VesselQualityIssue).where(VesselQualityIssue.status_code == (status_code or "OPEN"))
            issue_rows = (
                await self.db.execute(issue_stmt.order_by(VesselQualityIssue.id.desc()).limit(300))
            ).scalars().all()
            profiles = await self._profiles_by_ids([row.vessel_profile_id for row in issue_rows])
            for row in issue_rows:
                profile = profiles.get(row.vessel_profile_id)
                if profile is None:
                    continue
                issue_type_name = label_map.get("VESSEL_QUALITY_ISSUE_TYPE", {}).get(row.issue_type_code, row.issue_type_code)
                tasks.append(
                    VesselGovernanceTaskResponse(
                        task_type_code="CERTIFICATE" if "CERTIFICATE" in row.issue_type_code else "COMPLETION",
                        task_type_name="证件风险" if "CERTIFICATE" in row.issue_type_code else "资料补全",
                        source_id=row.id,
                        vessel_profile_id=profile.id,
                        ship_name=profile.ship_name,
                        current_mmsi=profile.current_mmsi,
                        title=row.issue_title or issue_type_name,
                        description=row.issue_desc,
                        severity_code=row.severity_code,
                        severity_name=label_map.get("VESSEL_ISSUE_SEVERITY", {}).get(row.severity_code),
                        status_code=row.status_code,
                        status_name=label_map.get("VESSEL_QUALITY_ISSUE_STATUS", {}).get(row.status_code),
                        recommended_action=_quality_action(row.issue_type_code),
                        action_path=f"/vessels/{profile.id}/edit",
                        created_at=row.created_at,
                    )
                )
        if task_type in (None, "IDENTITY"):
            candidate_status = status_code or "PENDING"
            candidate_rows = (
                await self.db.execute(
                    select(VesselIdentityCandidate)
                    .where(VesselIdentityCandidate.status_code == candidate_status)
                    .order_by(VesselIdentityCandidate.id.desc())
                    .limit(300)
                )
            ).scalars().all()
            profiles = await self._profiles_by_ids(
                list({row.source_profile_id for row in candidate_rows} | {row.target_profile_id for row in candidate_rows})
            )
            for row in candidate_rows:
                source = profiles.get(row.source_profile_id)
                target = profiles.get(row.target_profile_id)
                if source is None:
                    continue
                tasks.append(
                    VesselGovernanceTaskResponse(
                        task_type_code="IDENTITY",
                        task_type_name="重复身份",
                        source_id=row.id,
                        vessel_profile_id=source.id,
                        ship_name=source.ship_name,
                        current_mmsi=source.current_mmsi,
                        title=f"疑似同一船舶：{source.ship_name} / {getattr(target, 'ship_name', '未知船舶')}",
                        description=_evidence_summary(row.evidence_json),
                        severity_code="HIGH" if row.confidence_score >= 85 else "MEDIUM",
                        severity_name="高" if row.confidence_score >= 85 else "中",
                        status_code=row.status_code,
                        status_name=label_map.get("VESSEL_IDENTITY_CANDIDATE_STATUS", {}).get(row.status_code),
                        recommended_action="核对后确认或驳回",
                        action_path="/vessels/governance?tab=identity",
                        related_profile_id=getattr(target, "id", None),
                        related_ship_name=getattr(target, "ship_name", None),
                        created_at=row.created_at,
                    )
                )
        tasks.sort(key=lambda item: item.created_at, reverse=True)
        start = (page - 1) * page_size
        return PageResponse[VesselGovernanceTaskResponse](
            total=len(tasks),
            page=page,
            page_size=page_size,
            items=tasks[start : start + page_size],
        )

    async def list_vessels(self, query) -> PageResponse[VesselListItemResponse]:
        stmt = (
            select(VesselProfile)
            .outerjoin(VesselCapacityDimension, VesselCapacityDimension.vessel_profile_id == VesselProfile.id)
            .outerjoin(
                VesselOwnerPeriod,
                and_(VesselOwnerPeriod.vessel_profile_id == VesselProfile.id, VesselOwnerPeriod.is_current.is_(True)),
            )
            .outerjoin(
                VesselOperatorPeriod,
                and_(VesselOperatorPeriod.vessel_profile_id == VesselProfile.id, VesselOperatorPeriod.is_current.is_(True)),
            )
            .outerjoin(VesselContact, VesselContact.vessel_profile_id == VesselProfile.id)
            .outerjoin(VesselCargoCapability, VesselCargoCapability.vessel_profile_id == VesselProfile.id)
            .where(VesselProfile.deleted_at.is_(None))
        )

        if query.keyword:
            like_value = f"%{query.keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    VesselProfile.vessel_profile_code.ilike(like_value),
                    VesselProfile.ais_id.ilike(like_value),
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
        if query.identity_status_code:
            stmt = stmt.where(VesselProfile.identity_status_code == query.identity_status_code)
        if query.quality_level_code:
            stmt = stmt.where(VesselProfile.quality_level_code == query.quality_level_code)
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
            stmt = stmt.where(VesselProfile.building_year <= current_year - query.ship_age_min)
        if query.ship_age_max is not None:
            stmt = stmt.where(VesselProfile.building_year >= current_year - query.ship_age_max)
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
        if query.cargo_capability:
            like_value = f"%{query.cargo_capability.strip()}%"
            stmt = stmt.where(VesselCargoCapability.cargo_handling_notes.ilike(like_value))
        if query.source_type_code:
            stmt = stmt.where(VesselProfile.source_type_code == query.source_type_code)
        if query.updated_from:
            stmt = stmt.where(VesselProfile.updated_at >= query.updated_from)
        if query.updated_to:
            stmt = stmt.where(VesselProfile.updated_at <= query.updated_to)
        if query.certificate_risk:
            today = date.today()
            soon = today + timedelta(days=30)
            cert_exists = exists(
                select(VesselCertificate.id).where(VesselCertificate.vessel_profile_id == VesselProfile.id)
            )
            expired_exists = exists(
                select(VesselCertificate.id).where(
                    VesselCertificate.vessel_profile_id == VesselProfile.id,
                    VesselCertificate.is_long_term_valid.is_(False),
                    VesselCertificate.valid_to < today,
                )
            )
            expiring_exists = exists(
                select(VesselCertificate.id).where(
                    VesselCertificate.vessel_profile_id == VesselProfile.id,
                    VesselCertificate.is_long_term_valid.is_(False),
                    VesselCertificate.valid_to >= today,
                    VesselCertificate.valid_to <= soon,
                )
            )
            valid_exists = exists(
                select(VesselCertificate.id).where(
                    VesselCertificate.vessel_profile_id == VesselProfile.id,
                    or_(
                        VesselCertificate.is_long_term_valid.is_(True),
                        VesselCertificate.valid_to > soon,
                    ),
                )
            )
            if query.certificate_risk == "MISSING":
                stmt = stmt.where(~cert_exists)
            elif query.certificate_risk == "EXPIRED":
                stmt = stmt.where(expired_exists)
            elif query.certificate_risk == "EXPIRING":
                stmt = stmt.where(~expired_exists, expiring_exists)
            elif query.certificate_risk == "OK":
                stmt = stmt.where(cert_exists, ~expired_exists, ~expiring_exists, valid_exists)
            elif query.certificate_risk == "UNKNOWN":
                stmt = stmt.where(cert_exists, ~expired_exists, ~expiring_exists, ~valid_exists)

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
            return VesselPositionMonitorResponse(
                source_status="EMPTY",
                source_status_name=_source_status_name("EMPTY"),
                generated_at=generated_at,
                message="未匹配到符合条件的船舶档案",
                summary=VesselPositionMonitorSummary(
                    matched_profile_count=0,
                    positioned_count=0,
                    stale_position_count=0,
                    contactable_position_count=0,
                    risk_position_count=0,
                ),
                items=[],
            )
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
                    risk_position_count=0,
                ),
                items=[],
            )

        mmsi_by_profile = await self._mmsi_values_by_profile([row.id for row in profiles])
        mmsi_values = sorted({item for values in mmsi_by_profile.values() for item in values if item})
        if not mmsi_values:
            return VesselPositionMonitorResponse(
                source_status="EMPTY",
                source_status_name=_source_status_name("EMPTY"),
                generated_at=generated_at,
                message="匹配船舶缺少可用于实时查询的 MMSI",
                summary=VesselPositionMonitorSummary(
                    matched_profile_count=len(profiles),
                    positioned_count=0,
                    stale_position_count=0,
                    contactable_position_count=0,
                    risk_position_count=0,
                ),
                items=[],
            )

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
                    risk_position_count=0,
                ),
                items=[],
            )

        if not positions:
            return VesselPositionMonitorResponse(
                source_status="EMPTY",
                source_status_name=_source_status_name("EMPTY"),
                generated_at=generated_at,
                message="实时 ES 未返回匹配船位",
                summary=VesselPositionMonitorSummary(
                    matched_profile_count=len(profiles),
                    positioned_count=0,
                    stale_position_count=0,
                    contactable_position_count=0,
                    risk_position_count=0,
                ),
                items=[],
            )

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
                risk_position_count=sum(1 for item in items if item.certificate_risk in {"MISSING", "EXPIRED", "EXPIRING"} or item.open_issue_count > 0),
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
                "profile_status_code": "NEED_GOVERNANCE",
                "identity_status_code": "UNLINKED",
                "quality_level_code": "LOW",
                "source_type_code": "MANUAL",
                "audit_status": "PENDING",
            }
        )
        await self.repo.add_name_history(entity.id, entity.ship_name)
        await self.repo.add_identifier_history(entity.id, "MMSI", entity.current_mmsi)
        await self._add_change_event(entity.id, "CREATE", "新增船舶档案", None, _row_dict(entity), operator_id)
        await self._rebuild_identity_candidates(entity.id)
        await self.rebuild_quality(entity.id)
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
        if "ais_id" in updates and updates["ais_id"] != before.get("ais_id") and updates["ais_id"]:
            await self.repo.add_identifier_history(vessel_id, "AIS", updates["ais_id"])
        await self._add_change_event(vessel_id, "UPDATE_PROFILE", "更新船舶主档", before, updates, operator_id)
        await self._rebuild_identity_candidates(vessel_id)
        await self.rebuild_quality(vessel_id)
        await self.db.commit()
        return await self._build_profile_response(vessel_id)

    async def get_detail(self, vessel_id: int) -> VesselDetailResponse:
        profile = await self._require_profile(vessel_id)
        label_map = await _load_label_map(self.db)
        city_map = await _load_city_map(self.db, [profile.registry_city_code] if profile.registry_city_code else [])
        region_map = await _load_region_map(self.db, [profile.business_region_id] if profile.business_region_id else [])
        certificates = await self._certificates_with_files(vessel_id, label_map=label_map)
        candidate_page = await self.list_identity_candidates(source_profile_id=vessel_id, target_profile_id=vessel_id)
        return VesselDetailResponse(
            profile=_profile_response(profile, label_map=label_map, city_map=city_map, region_map=region_map),
            registration=self._maybe(VesselRegistrationResponse, await self.repo.get_one_by_profile(VesselRegistrationInfo, vessel_id)),
            capacity=self._maybe(VesselCapacityResponse, await self.repo.get_one_by_profile(VesselCapacityDimension, vessel_id)),
            build_info=self._maybe(VesselBuildInfoResponse, await self.repo.get_one_by_profile(VesselBuildInfo, vessel_id)),
            cargo_capability=self._maybe(VesselCargoCapabilityResponse, await self.repo.get_one_by_profile(VesselCargoCapability, vessel_id)),
            owners=[self._owner_response(row, label_map) for row in await self.repo.list_by_profile(VesselOwnerPeriod, vessel_id)],
            operators=[self._operator_response(row, label_map) for row in await self.repo.list_by_profile(VesselOperatorPeriod, vessel_id)],
            contacts=[self._contact_response(row, label_map) for row in await self.repo.list_by_profile(VesselContact, vessel_id)],
            crew=[self._crew_response(row, label_map) for row in await self.repo.list_by_profile(VesselCrewAssignment, vessel_id)],
            person_certificates=[
                self._person_certificate_response(row, label_map)
                for row in await self.repo.list_by_profile(VesselPersonCertificate, vessel_id)
            ],
            certificates=certificates,
            manual_preference=self._maybe(VesselManualPreferenceResponse, await self.repo.get_one_by_profile(VesselManualPreference, vessel_id)),
            behavior_profile=self._maybe(VesselBehaviorProfileResponse, await self.repo.get_one_by_profile(VesselBehaviorProfile, vessel_id)),
            quality=self._maybe(VesselQualitySnapshotResponse, await self.repo.get_one_by_profile(VesselQualitySnapshot, vessel_id)),
            quality_issues=[
                self._quality_issue_response(row, profile=profile, label_map=label_map)
                for row in await self.repo.list_by_profile(VesselQualityIssue, vessel_id, order_desc=True)
            ],
            identity_candidates=candidate_page.items,
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
        await self._add_change_event(vessel_id, "UPSERT_REGISTRATION", "维护登记信息", _row_dict(before) if before else None, _row_dict(row), operator_id)
        await self.rebuild_quality(vessel_id)
        await self.db.commit()
        return VesselRegistrationResponse(**_row_dict(row))

    async def upsert_capacity(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselCapacityResponse:
        await self._require_profile(vessel_id)
        row = await self.repo.upsert_one_by_profile(VesselCapacityDimension, vessel_id, payload.model_dump(exclude_none=True))
        await self._add_change_event(vessel_id, "UPSERT_CAPACITY", "维护容量尺度", None, _row_dict(row), operator_id)
        await self.rebuild_quality(vessel_id)
        await self.db.commit()
        return VesselCapacityResponse(**_row_dict(row))

    async def upsert_build_info(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselBuildInfoResponse:
        await self._require_profile(vessel_id)
        row = await self.repo.upsert_one_by_profile(VesselBuildInfo, vessel_id, payload.model_dump(exclude_none=True))
        if row.building_year:
            await self.repo.update_profile(vessel_id, {"building_year": row.building_year})
        await self._add_change_event(vessel_id, "UPSERT_BUILD_INFO", "维护建造信息", None, _row_dict(row), operator_id)
        await self.rebuild_quality(vessel_id)
        await self.db.commit()
        return VesselBuildInfoResponse(**_row_dict(row))

    async def upsert_cargo_capability(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselCargoCapabilityResponse:
        await self._require_profile(vessel_id)
        row = await self.repo.upsert_one_by_profile(VesselCargoCapability, vessel_id, payload.model_dump())
        await self._add_change_event(vessel_id, "UPSERT_CARGO_CAPABILITY", "维护货运能力", None, _row_dict(row), operator_id)
        await self.rebuild_quality(vessel_id)
        await self.db.commit()
        return VesselCargoCapabilityResponse(**_row_dict(row))

    async def upsert_manual_preference(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselManualPreferenceResponse:
        await self._require_profile(vessel_id)
        row = await self.repo.upsert_one_by_profile(VesselManualPreference, vessel_id, payload.model_dump())
        await self._add_change_event(vessel_id, "UPSERT_MANUAL_PREFERENCE", "维护人工偏好", None, _row_dict(row), operator_id)
        await self.db.commit()
        return VesselManualPreferenceResponse(**_row_dict(row))

    async def replace_owners(self, vessel_id: int, payload, *, operator_id: int | None = None) -> list[VesselOwnerResponse]:
        await self._require_profile(vessel_id)
        rows = await self.repo.replace_many_by_profile(
            VesselOwnerPeriod,
            vessel_id,
            [item.model_dump(exclude_none=True) for item in payload.owners],
        )
        primary = next((row for row in rows if row.is_primary or row.is_current), None)
        if primary:
            await self.repo.update_profile(vessel_id, {"owner_name": primary.party_name})
        await self._add_change_event(vessel_id, "REPLACE_OWNERS", "维护所有人周期", None, {"count": len(rows)}, operator_id)
        await self.rebuild_quality(vessel_id)
        await self.db.commit()
        label_map = await _load_label_map(self.db)
        return [self._owner_response(row, label_map) for row in rows]

    async def replace_operators(self, vessel_id: int, payload, *, operator_id: int | None = None) -> list[VesselOperatorResponse]:
        await self._require_profile(vessel_id)
        rows = await self.repo.replace_many_by_profile(
            VesselOperatorPeriod,
            vessel_id,
            [item.model_dump(exclude_none=True) for item in payload.operators],
        )
        primary = next((row for row in rows if row.is_primary or row.is_current), None)
        if primary:
            await self.repo.update_profile(vessel_id, {"operation_status_code": "OPERATING"})
        await self._add_change_event(vessel_id, "REPLACE_OPERATORS", "维护运营方周期", None, {"count": len(rows)}, operator_id)
        await self.rebuild_quality(vessel_id)
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
        await self.rebuild_quality(vessel_id)
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
        rows = await self.repo.replace_many_by_profile(
            VesselPersonCertificate,
            vessel_id,
            [item.model_dump(exclude_none=True) for item in payload.person_certificates],
        )
        await self._add_change_event(vessel_id, "REPLACE_PERSON_CERTIFICATES", "维护人员证书", None, {"count": len(rows)}, operator_id)
        await self.db.commit()
        label_map = await _load_label_map(self.db)
        return [self._person_certificate_response(row, label_map) for row in rows]

    async def list_certificates(self, vessel_id: int) -> list[VesselCertificateResponse]:
        await self._require_profile(vessel_id)
        return await self._certificates_with_files(vessel_id)

    async def create_certificate(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselCertificateResponse:
        await self._require_profile(vessel_id)
        row = await self.repo.create_certificate(vessel_id, payload.model_dump(exclude_none=True))
        await self._add_change_event(vessel_id, "CREATE_CERTIFICATE", "新增船舶证件", None, _row_dict(row), operator_id)
        await self._rebuild_identity_candidates(vessel_id)
        await self.rebuild_quality(vessel_id)
        await self.db.commit()
        return (await self._certificates_with_files(vessel_id, certificate_id=row.id))[0]

    async def update_certificate(self, certificate_id: int, payload, *, operator_id: int | None = None) -> VesselCertificateResponse:
        cert = await self.repo.get_certificate(certificate_id)
        if cert is None:
            raise NotFoundError("VesselCertificate", certificate_id)
        before = _row_dict(cert)
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        row = await self.repo.update_certificate(certificate_id, updates)
        assert row is not None
        await self._add_change_event(row.vessel_profile_id, "UPDATE_CERTIFICATE", "更新船舶证件", before, _row_dict(row), operator_id)
        await self._rebuild_identity_candidates(row.vessel_profile_id)
        await self.rebuild_quality(row.vessel_profile_id)
        await self.db.commit()
        return (await self._certificates_with_files(row.vessel_profile_id, certificate_id=row.id))[0]

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
        await self.rebuild_quality(vessel_id)
        await self.db.commit()
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

        recognition = await self.repo.create_image_recognition(
            {
                "vessel_profile_id": vessel_id,
                "vessel_certificate_id": certificate_id,
                "certificate_file_id": cert_file.id,
                "storage_file_id": payload.file_id,
                "status_code": "PROCESSING",
                "created_by": operator_id,
            }
        )
        try:
            storage_file, file_result = await FileStorageService(self.db).download_file(payload.file_id)
            result = await VesselCertificateImageAssistant(self.runtime_config).recognize(
                content=file_result.content,
                content_type=file_result.content_type or storage_file.content_type,
                file_name=storage_file.original_file_name,
            )
            recognition.status_code = "NEED_CONFIRM"
            recognition.provider_code = result.provider
            recognition.model_name = result.model
            recognition.candidate_payload_json = result.candidate_payload
            recognition.raw_text = result.raw_text
            recognition.raw_response_json = result.raw_response
            recognition.confidence_score = result.confidence_score
            recognition.error_message = None
            await self._add_change_event(
                vessel_id,
                "IMAGE_RECOGNIZE_CERTIFICATE",
                "识别证件图片",
                None,
                {"recognition_id": recognition.id, "status_code": recognition.status_code},
                operator_id,
            )
        except Exception as exc:  # noqa: BLE001
            recognition.status_code = "FAILED"
            recognition.error_message = str(exc)[:512]
            await self._add_change_event(
                vessel_id,
                "IMAGE_RECOGNIZE_CERTIFICATE_FAILED",
                "证件图片识别失败",
                None,
                {"recognition_id": recognition.id, "error_message": recognition.error_message},
                operator_id,
            )
        await self.db.flush()
        await self.db.refresh(recognition)
        await self.db.commit()
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
        accepted = payload.accepted_payload_json or recognition.candidate_payload_json or {}
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
        await self._rebuild_identity_candidates(vessel_id)
        await self.rebuild_quality(vessel_id)
        await self.db.flush()
        await self.db.commit()
        return (await self._certificates_with_files(vessel_id, certificate_id=certificate_id))[0]

    async def owner_transfer(self, vessel_id: int, payload, *, operator_id: int | None = None) -> VesselProfileResponse:
        profile = await self._require_profile(vessel_id)
        transfer_date = payload.transfer_date or date.today()
        code = await CodeSequenceService(self.db).next_code("VESSEL_PROFILE_CODE")
        old_snapshot = _row_dict(profile)
        profile.profile_status_code = "TRANSFERRED"
        new_profile = await self.repo.create_profile(
            {
                **{
                    key: getattr(profile, key)
                    for key in [
                        "vessel_identity_id",
                        "ais_id",
                        "ship_name",
                        "ship_name_en",
                        "current_mmsi",
                        "ship_type_code",
                        "navigation_power_type_code",
                        "quality_level_code",
                        "operation_status_code",
                        "home_port_code",
                        "home_port_name",
                        "building_year",
                        "registry_city_code",
                        "business_region_id",
                        "source_type_code",
                    ]
                },
                "vessel_profile_code": code,
                "profile_status_code": "NEED_GOVERNANCE",
                "identity_status_code": profile.identity_status_code,
                "owner_name": payload.new_owner_name,
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
                    "party_relation_type_code": "OWNER",
                    "certificate_no": payload.certificate_no,
                    "mobile_phone": payload.mobile_phone,
                    "address": payload.address,
                    "start_date": transfer_date,
                    "is_current": True,
                    "is_primary": True,
                }
            ],
        )
        if profile.vessel_identity_id:
            self.db.add(
                VesselIdentityLink(
                    vessel_identity_id=profile.vessel_identity_id,
                    vessel_profile_id=new_profile.id,
                    link_type_code="OWNER_TRANSFER",
                    confidence_score=90,
                    is_primary=False,
                    start_at=datetime.utcnow(),
                )
            )
        await self._add_change_event(vessel_id, "OWNER_TRANSFER_OUT", "所有人转移出", old_snapshot, {"new_profile_id": new_profile.id}, operator_id)
        await self._add_change_event(new_profile.id, "OWNER_TRANSFER_IN", "所有人转移入", None, {"from_profile_id": vessel_id}, operator_id)
        await self._rebuild_identity_candidates(new_profile.id)
        await self.rebuild_quality(vessel_id)
        await self.rebuild_quality(new_profile.id)
        await self.db.commit()
        return await self._build_profile_response(new_profile.id)

    async def get_behavior_profile(self, vessel_id: int) -> VesselBehaviorProfileResponse | None:
        await self._require_profile(vessel_id)
        row = await self.repo.get_one_by_profile(VesselBehaviorProfile, vessel_id)
        return self._maybe(VesselBehaviorProfileResponse, row)

    async def get_quality(self, vessel_id: int) -> VesselQualitySnapshotResponse | None:
        await self._require_profile(vessel_id)
        row = await self.repo.get_one_by_profile(VesselQualitySnapshot, vessel_id)
        return self._maybe(VesselQualitySnapshotResponse, row)

    async def get_change_events(self, vessel_id: int) -> list[VesselChangeEventResponse]:
        await self._require_profile(vessel_id)
        return [
            VesselChangeEventResponse(**_row_dict(row))
            for row in await self.repo.list_by_profile(VesselChangeEvent, vessel_id, order_desc=True)
        ]

    async def list_quality_issues(
        self,
        *,
        vessel_profile_id: int | None = None,
        status_code: str | None = None,
        issue_type_code: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> PageResponse[VesselQualityIssueResponse]:
        stmt = select(VesselQualityIssue)
        if vessel_profile_id:
            stmt = stmt.where(VesselQualityIssue.vessel_profile_id == vessel_profile_id)
        if status_code:
            stmt = stmt.where(VesselQualityIssue.status_code == status_code)
        if issue_type_code:
            stmt = stmt.where(VesselQualityIssue.issue_type_code == issue_type_code)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(VesselQualityIssue.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).scalars().all()
        profiles = await self._profiles_by_ids([row.vessel_profile_id for row in rows])
        label_map = await _load_label_map(self.db)
        return PageResponse[VesselQualityIssueResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[
                self._quality_issue_response(row, profile=profiles.get(row.vessel_profile_id), label_map=label_map)
                for row in rows
            ],
        )

    async def create_quality_issue(self, payload, *, operator_id: int | None = None) -> VesselQualityIssueResponse:
        await self._require_profile(payload.vessel_profile_id)
        row = VesselQualityIssue(**payload.model_dump())
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        await self._add_change_event(row.vessel_profile_id, "CREATE_QUALITY_ISSUE", "新增质量问题", None, _row_dict(row), operator_id)
        await self.rebuild_quality(row.vessel_profile_id)
        await self.db.commit()
        return self._quality_issue_response(row, profile=await self._require_profile(row.vessel_profile_id), label_map=await _load_label_map(self.db))

    async def update_quality_issue(self, issue_id: int, payload, *, operator_id: int | None = None) -> VesselQualityIssueResponse:
        row = await self.db.scalar(select(VesselQualityIssue).where(VesselQualityIssue.id == issue_id))
        if row is None:
            raise NotFoundError("VesselQualityIssue", issue_id)
        before = _row_dict(row)
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        for key, value in updates.items():
            setattr(row, key, value)
        if updates.get("status_code") in {"RESOLVED", "CLOSED", "IGNORED"}:
            row.resolved_at = datetime.utcnow()
        await self.db.flush()
        await self._add_change_event(row.vessel_profile_id, "UPDATE_QUALITY_ISSUE", "更新质量问题", before, _row_dict(row), operator_id)
        await self.rebuild_quality(row.vessel_profile_id)
        await self.db.commit()
        return self._quality_issue_response(row, profile=await self._require_profile(row.vessel_profile_id), label_map=await _load_label_map(self.db))

    async def list_identity_candidates(
        self,
        *,
        source_profile_id: int | None = None,
        target_profile_id: int | None = None,
        status_code: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> PageResponse[VesselIdentityCandidateResponse]:
        stmt = select(VesselIdentityCandidate)
        if source_profile_id and target_profile_id and source_profile_id == target_profile_id:
            stmt = stmt.where(
                or_(
                    VesselIdentityCandidate.source_profile_id == source_profile_id,
                    VesselIdentityCandidate.target_profile_id == target_profile_id,
                )
            )
        else:
            if source_profile_id:
                stmt = stmt.where(VesselIdentityCandidate.source_profile_id == source_profile_id)
            if target_profile_id:
                stmt = stmt.where(VesselIdentityCandidate.target_profile_id == target_profile_id)
        if status_code:
            stmt = stmt.where(VesselIdentityCandidate.status_code == status_code)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(VesselIdentityCandidate.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).scalars().all()
        profiles = await self._profiles_by_ids(
            list({row.source_profile_id for row in rows} | {row.target_profile_id for row in rows})
        )
        label_map = await _load_label_map(self.db)
        items = [
            self._identity_candidate_response(row, profiles=profiles, label_map=label_map)
            for row in rows
        ]
        return PageResponse[VesselIdentityCandidateResponse](total=total, page=page, page_size=page_size, items=items)

    async def review_identity_candidate(self, candidate_id: int, payload, *, operator_id: int | None = None) -> VesselIdentityCandidateResponse:
        row = await self.db.scalar(select(VesselIdentityCandidate).where(VesselIdentityCandidate.id == candidate_id))
        if row is None:
            raise NotFoundError("VesselIdentityCandidate", candidate_id)
        before = _row_dict(row)
        row.status_code = payload.status_code
        row.reviewed_by = operator_id
        row.reviewed_at = datetime.utcnow()
        await self.db.flush()
        await self._add_change_event(
            row.source_profile_id,
            "REVIEW_IDENTITY_CANDIDATE",
            "审核身份候选",
            before,
            {"status_code": payload.status_code, "review_note": payload.review_note},
            operator_id,
        )
        await self.db.commit()
        profiles = await self._profiles_by_ids([row.source_profile_id, row.target_profile_id])
        return self._identity_candidate_response(row, profiles=profiles, label_map=await _load_label_map(self.db))

    async def import_template(self) -> dict[str, Any]:
        return {
            "columns": [
                {"field": "mmsi", "name": "MMSI", "required": True, "example": "413123456"},
                {"field": "ship_name", "name": "船名", "required": True, "example": "江海联运001"},
            ]
        }

    async def import_preview(self, payload) -> VesselImportPreviewResponse:
        rows: list[dict[str, Any]] = []
        valid_count = 0
        for idx, item in enumerate(payload.rows, start=1):
            mmsi = str(item.get("mmsi") or item.get("current_mmsi") or "").strip()
            ship_name = str(item.get("ship_name") or "").strip()
            errors: list[str] = []
            if len(mmsi) != 9 or not mmsi.isdigit():
                errors.append("MMSI 必须为 9 位数字")
            if not ship_name:
                errors.append("船名不能为空")
            if not errors:
                valid_count += 1
            rows.append({"row_no": idx, "mmsi": mmsi, "ship_name": ship_name, "errors": errors})
        return VesselImportPreviewResponse(
            total=len(rows),
            valid_count=valid_count,
            invalid_count=len(rows) - valid_count,
            rows=rows,
        )

    async def import_confirm(self, payload, *, operator_id: int | None = None) -> VesselImportConfirmResponse:
        vessel_ids: list[int] = []
        for item in payload.rows:
            response = await self.create_vessel(item, operator_id=operator_id)
            vessel_ids.append(response.id)
        return VesselImportConfirmResponse(total=len(payload.rows), created_count=len(vessel_ids), vessel_ids=vessel_ids)

    async def rebuild_quality(self, vessel_id: int) -> VesselQualitySnapshotResponse:
        profile = await self._require_profile(vessel_id)
        capacity = await self.repo.get_one_by_profile(VesselCapacityDimension, vessel_id)
        owners = await self.repo.list_by_profile(VesselOwnerPeriod, vessel_id)
        operators = await self.repo.list_by_profile(VesselOperatorPeriod, vessel_id)
        contacts = await self.repo.list_by_profile(VesselContact, vessel_id)
        certificates = await self.repo.list_by_profile(VesselCertificate, vessel_id)

        await self.db.execute(
            delete(VesselQualityIssue).where(
                VesselQualityIssue.vessel_profile_id == vessel_id,
                VesselQualityIssue.issue_type_code.in_(
                    [
                        "MISSING_SHIP_TYPE",
                        "MISSING_CAPACITY",
                        "MISSING_OWNER",
                        "MISSING_OPERATOR",
                        "MISSING_CONTACT",
                        "MISSING_CERTIFICATE",
                        "DUPLICATE_MMSI",
                    ]
                ),
                VesselQualityIssue.status_code == "OPEN",
            )
        )
        issues: list[tuple[str, str, str]] = []
        if not profile.ship_type_code:
            issues.append(("MISSING_SHIP_TYPE", "HIGH", "缺少船型"))
        if capacity is None or capacity.deadweight_ton is None:
            issues.append(("MISSING_CAPACITY", "MEDIUM", "缺少载重/尺度"))
        if not owners:
            issues.append(("MISSING_OWNER", "HIGH", "缺少所有人信息"))
        if not operators:
            issues.append(("MISSING_OPERATOR", "MEDIUM", "缺少运营方信息"))
        if not any(row.is_available and (row.mobile_phone or row.wechat) for row in contacts):
            issues.append(("MISSING_CONTACT", "HIGH", "缺少可用联系人"))
        if not certificates:
            issues.append(("MISSING_CERTIFICATE", "MEDIUM", "缺少船舶证件"))
        duplicate_mmsi_count = int(
            await self.db.scalar(
                select(func.count())
                .select_from(VesselProfile)
                .where(
                    VesselProfile.current_mmsi == profile.current_mmsi,
                    VesselProfile.id != profile.id,
                    VesselProfile.deleted_at.is_(None),
                )
            )
            or 0
        )
        if duplicate_mmsi_count:
            issues.append(("DUPLICATE_MMSI", "HIGH", "存在相同 MMSI 档案，需在数据治理中心确认"))
        for issue_type, severity, title in issues:
            self.db.add(
                VesselQualityIssue(
                    vessel_profile_id=vessel_id,
                    issue_type_code=issue_type,
                    severity_code=severity,
                    issue_title=title,
                    issue_desc=None,
                    status_code="OPEN",
                )
            )
        completeness = 40 + (20 if profile.ship_type_code else 0) + (20 if capacity else 0) + (10 if owners else 0) + (10 if operators else 0)
        contact_score = 100 if any(row.is_available and row.mobile_phone for row in contacts) else (60 if contacts else 0)
        risk = _certificate_risk(list(certificates))
        certificate_score = {"OK": 100, "EXPIRING": 70, "UNKNOWN": 50, "MISSING": 20, "EXPIRED": 0}.get(risk, 40)
        identity_score = 80 if profile.identity_status_code == "LINKED" else (40 if duplicate_mmsi_count else 60)
        open_issues = len(issues) + int(
            await self.db.scalar(
                select(func.count())
                .select_from(VesselQualityIssue)
                .where(
                    VesselQualityIssue.vessel_profile_id == vessel_id,
                    VesselQualityIssue.status_code == "OPEN",
                    ~VesselQualityIssue.issue_type_code.in_([item[0] for item in issues] or ["__NONE__"]),
                )
            )
            or 0
        )
        avg_score = int((completeness + contact_score + certificate_score + identity_score) / 4)
        quality_level = "HIGH" if avg_score >= 80 and not open_issues else ("MEDIUM" if avg_score >= 55 else "LOW")
        snapshot = await self.repo.get_one_by_profile(VesselQualitySnapshot, vessel_id)
        data = {
            "quality_level_code": quality_level,
            "completeness_score": min(completeness, 100),
            "contact_score": contact_score,
            "certificate_score": certificate_score,
            "identity_score": identity_score,
            "issue_count": open_issues,
            "generated_at": datetime.utcnow(),
        }
        if snapshot is None:
            snapshot = VesselQualitySnapshot(vessel_profile_id=vessel_id, **data)
            self.db.add(snapshot)
        else:
            for key, value in data.items():
                setattr(snapshot, key, value)
        profile.quality_level_code = quality_level
        await self.db.flush()
        await self.db.refresh(snapshot)
        return VesselQualitySnapshotResponse(**_row_dict(snapshot))

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
        cargo = await self._map_by_profile(VesselCargoCapability, ids)
        behavior = await self._map_by_profile(VesselBehaviorProfile, ids)
        owners = await self._first_by_profile(VesselOwnerPeriod, ids)
        operators = await self._first_by_profile(VesselOperatorPeriod, ids)
        contacts = await self._first_by_profile(VesselContact, ids)
        issue_counts = await self._open_issue_counts(ids)
        certs = await self._certificates_by_profile(ids)
        items: list[VesselListItemResponse] = []
        for profile in profiles:
            base = _profile_response(profile, label_map=label_map, city_map=city_map, region_map=region_map).model_dump()
            capacity = capacities.get(profile.id)
            contact = contacts.get(profile.id)
            item = VesselListItemResponse(
                **base,
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
                capability_summary=_capability_summary(cargo.get(profile.id)),
                certificate_risk=_certificate_risk(certs.get(profile.id, [])),
                last_active_at=getattr(behavior.get(profile.id), "last_active_at", None)
                or getattr(operators.get(profile.id), "last_active_at", None),
                open_issue_count=issue_counts.get(profile.id, 0),
            )
            items.append(item)
        return items

    def _certificate_updates_from_recognition(self, payload: dict[str, Any]) -> dict[str, Any]:
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
        if valid_to:
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
        if "ship_registry_no" in requested and payload.get("ship_registry_no"):
            # ship_registry_no belongs to registration info, not profile; first version keeps it in the certificate payload.
            pass
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
        rows = (
            await self.db.execute(select(model).where(model.vessel_profile_id.in_(ids)))
        ).scalars().all()
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
            .outerjoin(VesselCargoCapability, VesselCargoCapability.vessel_profile_id == VesselProfile.id)
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
        if query.demand_ton is not None:
            stmt = stmt.where(
                or_(
                    VesselCapacityDimension.reference_load_ton >= query.demand_ton,
                    VesselCapacityDimension.deadweight_ton >= query.demand_ton,
                )
            )
        if query.draft_max is not None:
            stmt = stmt.where(VesselCapacityDimension.design_draft_m <= query.draft_max)
        if query.contact_available is not None:
            stmt = stmt.where(VesselContact.is_available.is_(query.contact_available))
        if query.cargo_keyword:
            like_value = f"%{query.cargo_keyword.strip()}%"
            stmt = stmt.where(VesselCargoCapability.cargo_handling_notes.ilike(like_value))
        if query.origin_city_code or query.destination_city_code:
            city_codes = [code for code in [query.origin_city_code, query.destination_city_code] if code]
            stmt = stmt.outerjoin(VesselBehaviorProfile, VesselBehaviorProfile.vessel_profile_id == VesselProfile.id)
            stmt = stmt.where(or_(VesselProfile.registry_city_code.in_(city_codes), VesselBehaviorProfile.active_city_codes_json.is_not(None)))
        if query.certificate_risk:
            today = date.today()
            soon = today + timedelta(days=30)
            cert_exists = exists(
                select(VesselCertificate.id).where(VesselCertificate.vessel_profile_id == VesselProfile.id)
            )
            expired_exists = exists(
                select(VesselCertificate.id).where(
                    VesselCertificate.vessel_profile_id == VesselProfile.id,
                    VesselCertificate.is_long_term_valid.is_(False),
                    VesselCertificate.valid_to < today,
                )
            )
            expiring_exists = exists(
                select(VesselCertificate.id).where(
                    VesselCertificate.vessel_profile_id == VesselProfile.id,
                    VesselCertificate.is_long_term_valid.is_(False),
                    VesselCertificate.valid_to >= today,
                    VesselCertificate.valid_to <= soon,
                )
            )
            valid_exists = exists(
                select(VesselCertificate.id).where(
                    VesselCertificate.vessel_profile_id == VesselProfile.id,
                    or_(
                        VesselCertificate.is_long_term_valid.is_(True),
                        VesselCertificate.valid_to > soon,
                    ),
                )
            )
            if query.certificate_risk == "MISSING":
                stmt = stmt.where(~cert_exists)
            elif query.certificate_risk == "EXPIRED":
                stmt = stmt.where(expired_exists)
            elif query.certificate_risk == "EXPIRING":
                stmt = stmt.where(~expired_exists, expiring_exists)
            elif query.certificate_risk == "OK":
                stmt = stmt.where(cert_exists, ~expired_exists, ~expiring_exists, valid_exists)
            elif query.certificate_risk == "UNKNOWN":
                stmt = stmt.where(cert_exists, ~expired_exists, ~expiring_exists, ~valid_exists)
        rows = (
            await self.db.execute(
                stmt.group_by(VesselProfile.id)
                .order_by(VesselProfile.quality_level_code.asc(), VesselProfile.updated_at.desc())
                .limit(max(query.max_items * 3, query.max_items))
            )
        ).scalars().all()
        if not query.cargo_keyword and not (query.origin_city_code or query.destination_city_code):
            return list(rows)
        filtered: list[VesselProfile] = []
        behavior = await self._map_by_profile(VesselBehaviorProfile, [row.id for row in rows])
        cargo = await self._map_by_profile(VesselCargoCapability, [row.id for row in rows])
        for profile in rows:
            if query.cargo_keyword and not (
                _contains_json_text(cargo.get(profile.id).capability_tags_json if cargo.get(profile.id) else None, query.cargo_keyword)
                or _contains_json_text(cargo.get(profile.id).preferred_cargo_json if cargo.get(profile.id) else None, query.cargo_keyword)
                or (cargo.get(profile.id) and query.cargo_keyword.lower() in (cargo.get(profile.id).cargo_handling_notes or "").lower())
            ):
                continue
            city_codes = [code for code in [query.origin_city_code, query.destination_city_code] if code]
            if city_codes:
                behavior_row = behavior.get(profile.id)
                active_codes = set(behavior_row.active_city_codes_json or []) if behavior_row else set()
                if profile.registry_city_code not in city_codes and not active_codes.intersection(city_codes):
                    continue
            filtered.append(profile)
        return filtered

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
            terms.append(value)
            if value.isdigit():
                terms.append(int(value))
        query_body = {
            "size": min(max_hits, 1000),
            "query": {
                "bool": {
                    "should": [
                        {"terms": {"mmsi": terms}},
                        {"terms": {"ship_mmsi": terms}},
                    ],
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
        payload = await client.search(index, query_body)
        hits = ((payload.get("hits") or {}).get("hits") or []) if isinstance(payload, dict) else []
        result: dict[str, dict[str, Any]] = {}
        for hit in hits:
            source = hit.get("_source") if isinstance(hit, dict) else None
            if not isinstance(source, dict):
                continue
            mmsi_raw = _first_value(source, ["mmsi", "ship_mmsi", "MMSI"])
            if mmsi_raw is None:
                continue
            mmsi = str(mmsi_raw).strip()
            longitude = _to_decimal(_first_value(source, ["lon", "lng", "longitude", "x"]))
            latitude = _to_decimal(_first_value(source, ["lat", "latitude", "y"]))
            if longitude is None or latitude is None:
                continue
            if not (Decimal("-180") <= longitude <= Decimal("180") and Decimal("-90") <= latitude <= Decimal("90")):
                continue
            position_time = _parse_position_time(
                _first_value(source, ["timestamp", "location_time", "update_time", "position_time", "time", "@timestamp"])
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
                "heading_deg": _first_value(source, ["heading", "hdg", "heading_deg"]),
                "position_time": position_time,
                "location_text": _first_value(source, ["location_text", "address", "area_name", "city_name"]),
            }
        return result

    async def _open_issue_counts(self, ids: list[int]) -> dict[int, int]:
        rows = (
            await self.db.execute(
                select(VesselQualityIssue.vessel_profile_id, func.count())
                .where(VesselQualityIssue.vessel_profile_id.in_(ids), VesselQualityIssue.status_code == "OPEN")
                .group_by(VesselQualityIssue.vessel_profile_id)
            )
        ).all()
        return {vessel_id: int(count) for vessel_id, count in rows}

    async def _latest_open_issues(self, ids: list[int]) -> dict[int, VesselQualityIssue]:
        if not ids:
            return {}
        rows = (
            await self.db.execute(
                select(VesselQualityIssue)
                .where(VesselQualityIssue.vessel_profile_id.in_(ids), VesselQualityIssue.status_code == "OPEN")
                .order_by(VesselQualityIssue.vessel_profile_id.asc(), VesselQualityIssue.severity_code.asc(), VesselQualityIssue.id.desc())
            )
        ).scalars().all()
        result: dict[int, VesselQualityIssue] = {}
        for row in rows:
            result.setdefault(row.vessel_profile_id, row)
        return result

    async def _certificates_by_profile(self, ids: list[int]) -> dict[int, list[VesselCertificate]]:
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

    def _owner_response(self, row: VesselOwnerPeriod, label_map: dict[str, dict[str, str]]) -> VesselOwnerResponse:
        return VesselOwnerResponse(
            **_row_dict(row),
            party_type_name=label_map.get("PARTY_SUBJECT_TYPE", {}).get(row.party_type_code),
            party_relation_type_name=label_map.get("PARTY_RELATION_TYPE", {}).get(row.party_relation_type_code),
        )

    def _operator_response(self, row: VesselOperatorPeriod, label_map: dict[str, dict[str, str]]) -> VesselOperatorResponse:
        return VesselOperatorResponse(
            **_row_dict(row),
            party_type_name=label_map.get("PARTY_SUBJECT_TYPE", {}).get(row.party_type_code),
            operator_role_name=label_map.get("VESSEL_OPERATOR_ROLE", {}).get(row.operator_role_code),
            risk_level_name=label_map.get("VESSEL_OPERATOR_RISK_LEVEL", {}).get(row.risk_level_code or ""),
        )

    def _contact_response(self, row: VesselContact, label_map: dict[str, dict[str, str]]) -> VesselContactResponse:
        return VesselContactResponse(
            **_row_dict(row),
            contact_role_name=label_map.get("CONTACT_ROLE", {}).get(row.contact_role_code),
        )

    def _crew_response(self, row: VesselCrewAssignment, label_map: dict[str, dict[str, str]]) -> VesselCrewResponse:
        return VesselCrewResponse(
            **_row_dict(row),
            crew_role_name=label_map.get("CONTACT_ROLE", {}).get(row.crew_role_code),
        )

    def _person_certificate_response(
        self,
        row: VesselPersonCertificate,
        label_map: dict[str, dict[str, str]],
    ) -> VesselPersonCertificateResponse:
        return VesselPersonCertificateResponse(
            **_row_dict(row),
            certificate_type_name=label_map.get("CERTIFICATE_TYPE", {}).get(row.certificate_type_code),
            verify_status_name=label_map.get("CERTIFICATE_VERIFY_STATUS", {}).get(row.verify_status_code),
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

    def _quality_issue_response(
        self,
        row: VesselQualityIssue,
        *,
        profile: VesselProfile | None = None,
        label_map: dict[str, dict[str, str]] | None = None,
    ) -> VesselQualityIssueResponse:
        label_map = label_map or {}
        return VesselQualityIssueResponse(
            **_row_dict(row),
            ship_name=getattr(profile, "ship_name", None),
            current_mmsi=getattr(profile, "current_mmsi", None),
            issue_type_name=label_map.get("VESSEL_QUALITY_ISSUE_TYPE", {}).get(row.issue_type_code),
            severity_name=label_map.get("VESSEL_ISSUE_SEVERITY", {}).get(row.severity_code),
            status_name=label_map.get("VESSEL_QUALITY_ISSUE_STATUS", {}).get(row.status_code),
            recommended_action=_quality_action(row.issue_type_code),
            action_path=f"/vessels/{row.vessel_profile_id}/edit",
        )

    def _identity_candidate_response(
        self,
        row: VesselIdentityCandidate,
        *,
        profiles: dict[int, VesselProfile],
        label_map: dict[str, dict[str, str]] | None = None,
    ) -> VesselIdentityCandidateResponse:
        label_map = label_map or {}
        source = profiles.get(row.source_profile_id)
        target = profiles.get(row.target_profile_id)
        return VesselIdentityCandidateResponse(
            **_row_dict(row),
            source_ship_name=getattr(source, "ship_name", None),
            source_mmsi=getattr(source, "current_mmsi", None),
            target_ship_name=getattr(target, "ship_name", None),
            target_mmsi=getattr(target, "current_mmsi", None),
            candidate_type_name=label_map.get("VESSEL_IDENTITY_CANDIDATE_TYPE", {}).get(row.candidate_type_code),
            status_name=label_map.get("VESSEL_IDENTITY_CANDIDATE_STATUS", {}).get(row.status_code),
            evidence_summary=_evidence_summary(row.evidence_json),
            recommended_action="核对后确认同一船舶" if row.status_code == "PENDING" else "查看处理结果",
            action_path="/vessels/governance?tab=identity",
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

    async def _rebuild_identity_candidates(self, vessel_id: int) -> None:
        profile = await self._require_profile(vessel_id)
        candidate_specs: list[tuple[int, str, int, dict[str, Any]]] = []
        same_mmsi = (
            await self.db.execute(
                select(VesselProfile).where(
                    VesselProfile.id != profile.id,
                    VesselProfile.deleted_at.is_(None),
                    VesselProfile.current_mmsi == profile.current_mmsi,
                )
            )
        ).scalars().all()
        for other in same_mmsi:
            candidate_specs.append((other.id, "SAME_MMSI", 90, {"mmsi": profile.current_mmsi}))
        if profile.ais_id:
            same_ais = (
                await self.db.execute(
                    select(VesselProfile).where(
                        VesselProfile.id != profile.id,
                        VesselProfile.deleted_at.is_(None),
                        VesselProfile.ais_id == profile.ais_id,
                    )
                )
            ).scalars().all()
            for other in same_ais:
                candidate_specs.append((other.id, "SAME_AIS", 95, {"ais_id": profile.ais_id}))
        same_name = (
            await self.db.execute(
                select(VesselProfile).where(
                    VesselProfile.id != profile.id,
                    VesselProfile.deleted_at.is_(None),
                    VesselProfile.ship_name == profile.ship_name,
                )
            )
        ).scalars().all()
        for other in same_name:
            candidate_specs.append((other.id, "SAME_NAME", 70, {"ship_name": profile.ship_name}))

        cert_nos = [
            row.certificate_no
            for row in (await self.repo.list_by_profile(VesselCertificate, vessel_id))
            if row.certificate_no
        ]
        if cert_nos:
            cert_rows = (
                await self.db.execute(
                    select(VesselCertificate).where(
                        VesselCertificate.vessel_profile_id != vessel_id,
                        VesselCertificate.certificate_no.in_(cert_nos),
                    )
                )
            ).scalars().all()
            for cert in cert_rows:
                candidate_specs.append(
                    (cert.vessel_profile_id, "SAME_CERTIFICATE", 88, {"certificate_no": cert.certificate_no})
                )

        for target_id, candidate_type, score, evidence in candidate_specs:
            source_id, target_id_ordered = sorted([vessel_id, target_id])
            existing = await self.db.scalar(
                select(VesselIdentityCandidate).where(
                    VesselIdentityCandidate.source_profile_id == source_id,
                    VesselIdentityCandidate.target_profile_id == target_id_ordered,
                    VesselIdentityCandidate.candidate_type_code == candidate_type,
                    VesselIdentityCandidate.status_code == "PENDING",
                )
            )
            if existing is None:
                self.db.add(
                    VesselIdentityCandidate(
                        source_profile_id=source_id,
                        target_profile_id=target_id_ordered,
                        candidate_type_code=candidate_type,
                        confidence_score=score,
                        evidence_json=evidence,
                        status_code="PENDING",
                    )
                )
        await self.db.flush()

    async def _copy_singletons(self, source_id: int, target_id: int) -> None:
        for model in [VesselRegistrationInfo, VesselCapacityDimension, VesselBuildInfo, VesselCargoCapability, VesselManualPreference]:
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
