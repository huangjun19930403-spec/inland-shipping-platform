"""船舶主数据 seed。"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, update

from app.core.database import AsyncSessionLocal
from app.models.common import CodeSequence
from app.models.analysis import (
    FactVesselAisFreshnessDaily,
    FactVesselAssetDaily,
    FactVesselNodeDaily,
    FactVesselQualityDaily,
    FactVesselRiskDaily,
    FactVesselRouteSegmentDaily,
    FactVesselTrajectoryDaily,
)
from app.models.vessel import (
    VesselAffiliationEvidence,
    VesselAisCitySnapshotItem,
    VesselAisSnapshot,
    VesselBlacklistSignal,
    VesselBuildInfo,
    VesselCapacityDimension,
    VesselCandidateAnalysis,
    VesselCandidateAnalysisAnnotation,
    VesselCandidateAnalysisItem,
    VesselCertificate,
    VesselCertificateFile,
    VesselCertificateImageRecognition,
    VesselCertificateRequirementRule,
    VesselChangeEvent,
    VesselContact,
    VesselControllerEvidence,
    VesselCrewAssignment,
    VesselDataQualityIssue,
    VesselGovernanceTask,
    VesselIdentifierHistory,
    VesselIdentity,
    VesselIdentityLink,
    VesselLatestPositionSnapshot,
    VesselNameHistory,
    VesselNavigationConstraintEvidence,
    VesselNodeObservationItem,
    VesselNodeObservationVessel,
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
    VesselRiskReview,
    VesselRiskSignal,
    VesselRouteSegmentMatchSample,
    VesselRouteSegmentObservationItem,
    VesselSpatialObservationSnapshot,
)


SEED_FILE = Path(__file__).resolve().parent / "seed_data" / "vessel" / "vessels.json"


def _load_seed_rows() -> list[dict[str, Any]]:
    return json.loads(SEED_FILE.read_text(encoding="utf-8"))


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _dt(value: Any, fallback: datetime) -> datetime:
    if not value:
        return fallback
    try:
        return datetime.fromisoformat(str(value).strip())
    except ValueError:
        return fallback


def _status(row: dict[str, Any]) -> str:
    return "ACTIVE" if row.get("enabled_status_text") == "启用" else "INACTIVE"


PORT_SEEDS = [
    ("320900", "盐城", "盐城港"),
    ("320800", "淮安", "淮安港"),
    ("320100", "南京", "南京港"),
    ("320600", "南通", "南通港"),
    ("321000", "扬州", "扬州港"),
    ("321200", "泰州", "泰州港"),
]

PORT_POSITION_CENTERS: dict[str, tuple[Decimal, Decimal]] = {
    "320100": (Decimal("118.780000"), Decimal("32.060000")),
    "320600": (Decimal("120.860000"), Decimal("32.010000")),
    "320800": (Decimal("119.020000"), Decimal("33.610000")),
    "320900": (Decimal("120.160000"), Decimal("33.350000")),
    "321000": (Decimal("119.420000"), Decimal("32.390000")),
    "321200": (Decimal("119.920000"), Decimal("32.460000")),
}


def _ship_type(row: dict[str, Any]) -> str:
    text = str(row.get("source_ship_type_text") or "")
    name = str(row.get("ship_name") or "")
    deadweight = float(row.get("deadweight_ton") or 0)
    if "集装箱" in text or "集" in name:
        return "CONTAINER"
    if "自卸" in text or "砂" in name:
        return "SELF_UNLOADING_SAND"
    if deadweight >= 5000:
        return "DRY_BULK"
    if deadweight >= 1000:
        return "GENERAL_CARGO"
    return "OTHER"


def _port_seed(idx: int) -> tuple[str, str, str]:
    return PORT_SEEDS[(idx - 1) % len(PORT_SEEDS)]


def _position_seed(idx: int, city_code: str) -> tuple[Decimal, Decimal]:
    base_longitude, base_latitude = PORT_POSITION_CENTERS.get(city_code, PORT_POSITION_CENTERS["320100"])
    longitude_offset = Decimal((idx % 7) - 3) / Decimal("1000")
    latitude_offset = Decimal((idx % 5) - 2) / Decimal("1000")
    return (
        (base_longitude + longitude_offset).quantize(Decimal("0.000001")),
        (base_latitude + latitude_offset).quantize(Decimal("0.000001")),
    )


def _building_year(idx: int, row: dict[str, Any]) -> int:
    created_at = _dt(row.get("source_created_at"), datetime.utcnow())
    year = created_at.year - (idx % 9) - 1
    return max(2005, min(year, 2024))


def _operator_name(idx: int, row: dict[str, Any]) -> str:
    _, city_name, _ = _port_seed(idx)
    return f"{city_name}方圆船舶管理有限公司"


def _operator_contact_name(idx: int) -> str:
    names = ["王调度", "李经理", "张运营", "陈调度", "刘经理", "赵运营"]
    return names[(idx - 1) % len(names)]


async def _clear_vessels(session) -> None:
    for model in (
        FactVesselRiskDaily,
        FactVesselQualityDaily,
        FactVesselRouteSegmentDaily,
        FactVesselNodeDaily,
        FactVesselTrajectoryDaily,
        FactVesselAisFreshnessDaily,
        FactVesselAssetDaily,
        VesselRiskReview,
        VesselBlacklistSignal,
        VesselGovernanceTask,
        VesselCertificateRequirementRule,
        VesselRecognitionAdoptionRecord,
        VesselRecognitionFieldDiff,
        VesselCandidateAnalysisAnnotation,
        VesselCandidateAnalysisItem,
        VesselCandidateAnalysis,
        VesselNavigationConstraintEvidence,
        VesselRouteSegmentMatchSample,
        VesselRouteSegmentObservationItem,
        VesselNodeObservationVessel,
        VesselNodeObservationItem,
        VesselSpatialObservationSnapshot,
        VesselLatestPositionSnapshot,
        VesselAisCitySnapshotItem,
        VesselAisSnapshot,
        VesselAffiliationEvidence,
        VesselControllerEvidence,
        VesselRiskSignal,
        VesselDataQualityIssue,
        VesselProfileSummary,
        VesselChangeEvent,
        VesselOwnerDocumentImageRecognition,
        VesselOwnerDocument,
        VesselPersonCertificateImageRecognition,
        VesselPersonCertificateFile,
        VesselCertificateImageRecognition,
        VesselCertificateFile,
        VesselCertificate,
        VesselPersonCertificate,
        VesselCrewAssignment,
        VesselContact,
        VesselOperatorPeriod,
        VesselOwnerPeriod,
        VesselBuildInfo,
        VesselCapacityDimension,
        VesselRegistrationInfo,
        VesselIdentifierHistory,
        VesselNameHistory,
        VesselIdentityLink,
        VesselProfile,
        VesselIdentity,
    ):
        await session.execute(delete(model))


async def seed_vessel_samples() -> None:
    rows = _load_seed_rows()
    async with AsyncSessionLocal() as session:
        await _clear_vessels(session)
        now = datetime.utcnow()
        ais_snapshot_id = "SEED_AIS_CURRENT"
        spatial_snapshot_id = "SEED_NODE_CURRENT"
        seed_profiles: list[dict[str, Any]] = []

        for idx, row in enumerate(rows, start=1):
            created_at = _dt(row.get("source_created_at"), now)
            updated_at = _dt(row.get("source_updated_at"), created_at)
            profile_code = row.get("vessel_code") or f"VP{idx:06d}"
            mmsi = str(row["mmsi"])
            ship_name = str(row["ship_name"])
            registry_city_code, registry_city_name, home_port_name = _port_seed(idx)
            ship_type_code = _ship_type(row)
            building_year = _building_year(idx, row)

            identity = VesselIdentity(
                identity_code=f"VID{idx:06d}",
                identity_status_code="VERIFIED",
                canonical_mmsi=mmsi,
                canonical_ship_name=ship_name,
                confidence_score=95,
                source_type_code="IMPORT",
                remark="由船舶台账 seed 生成",
            )
            session.add(identity)
            await session.flush()

            profile = VesselProfile(
                vessel_profile_code=profile_code,
                vessel_identity_id=identity.id,
                ship_name=ship_name,
                ship_name_en=row.get("ship_name_en"),
                current_mmsi=mmsi,
                ship_type_code=ship_type_code,
                profile_status_code=_status(row),
                identity_status_code="LINKED",
                operation_status_code="OPERATING" if row.get("source_status_text") == "正常" else None,
                home_port_name=home_port_name,
                registry_city_code=registry_city_code,
                source_type_code="IMPORT",
                audit_status="APPROVED",
                audited_at=updated_at,
                remark=(
                    f"来源船型：{row.get('source_ship_type_text') or '-'}；"
                    f"定位服务：{row.get('position_service_text') or '-'}；"
                    f"载重状态：{row.get('loaded_flag_text') or '-'}"
                ),
                created_at=created_at,
                updated_at=updated_at,
            )
            session.add(profile)
            await session.flush()

            session.add(
                VesselIdentityLink(
                    vessel_identity_id=identity.id,
                    vessel_profile_id=profile.id,
                    link_type_code="PROFILE",
                    confidence_score=95,
                    is_primary=True,
                    start_at=created_at,
                    created_at=created_at,
                    updated_at=updated_at,
                )
            )
            session.add(
                VesselNameHistory(
                    vessel_profile_id=profile.id,
                    ship_name=ship_name,
                    source_type_code="IMPORT",
                    created_at=created_at,
                )
            )
            session.add(
                VesselIdentifierHistory(
                    vessel_profile_id=profile.id,
                    identifier_type_code="MMSI",
                    identifier_value=mmsi,
                    source_type_code="IMPORT",
                    created_at=created_at,
                )
            )
            session.add(
                VesselRegistrationInfo(
                    vessel_profile_id=profile.id,
                    registry_city_code=registry_city_code,
                    ship_registry_no=None,
                    home_port_name=home_port_name,
                    flag_code="CN" if row.get("nationality") == "中国" else None,
                    inspection_org=f"{registry_city_name}市交通运输综合行政执法支队",
                    remark=f"来源船舶编码：{profile_code}",
                    updated_at=updated_at,
                )
            )

            deadweight = _decimal(row.get("deadweight_ton"))
            length = _decimal(row.get("length_m"))
            width = _decimal(row.get("width_m"))
            session.add(
                VesselBuildInfo(
                    vessel_profile_id=profile.id,
                    building_year=building_year,
                    builder_name=f"{registry_city_name}内河船舶修造厂",
                    build_place=f"江苏{registry_city_name}",
                    hull_material_code="STEEL",
                    remark="seed 模拟建造资料，用于船龄展示",
                    updated_at=updated_at,
                )
            )

            session.add(
                VesselCapacityDimension(
                    vessel_profile_id=profile.id,
                    deadweight_ton=deadweight,
                    reference_load_ton=deadweight,
                    length_m=length,
                    width_m=width,
                    capacity_remark="由船舶台账吨位和长宽生成",
                    updated_at=updated_at,
                )
            )

            owner = VesselOwnerPeriod(
                vessel_profile_id=profile.id,
                party_name=f"{ship_name}船东",
                party_type_code="PERSON",
                is_current=True,
                is_primary=True,
                created_at=created_at,
                updated_at=updated_at,
            )
            session.add(owner)
            operator = VesselOperatorPeriod(
                vessel_profile_id=profile.id,
                operator_name=_operator_name(idx, row),
                party_type_code="COMPANY",
                start_date=created_at.date(),
                is_current=True,
                is_primary=True,
                created_at=created_at,
                updated_at=updated_at,
            )
            session.add(operator)
            await session.flush()
            operator_phone = row.get("contact_phone") or f"139{idx:08d}"[-11:]

            if row.get("owner_phone"):
                session.add(
                    VesselContact(
                        vessel_profile_id=profile.id,
                        contact_scope_code="OWNER",
                        owner_period_id=owner.id,
                        contact_name="船东联系人",
                        contact_role_code="OWNER_CONTACT",
                        mobile_phone=row.get("owner_phone"),
                        is_primary=False,
                        is_available=True,
                        last_verified_at=updated_at,
                        remark="由船舶台账船主联系电话生成",
                        created_at=created_at,
                        updated_at=updated_at,
                    )
                )
            session.add(
                VesselContact(
                    vessel_profile_id=profile.id,
                    contact_scope_code="OPERATOR",
                    operator_period_id=operator.id,
                    contact_name=_operator_contact_name(idx),
                    contact_role_code="OPERATOR_CONTACT",
                    mobile_phone=operator_phone,
                    is_primary=True,
                    is_available=True,
                    last_verified_at=updated_at,
                    remark="seed 模拟运营方联系人",
                    created_at=created_at,
                    updated_at=updated_at,
                )
            )
            session.add(
                VesselOwnerPeriod(
                    vessel_profile_id=profile.id,
                    party_name=f"{ship_name}历史船东",
                    party_type_code="PERSON",
                    end_date=created_at.date(),
                    is_current=False,
                    is_primary=False,
                    created_at=created_at,
                    updated_at=updated_at,
                )
            )
            session.add(
                VesselContact(
                    vessel_profile_id=profile.id,
                    contact_scope_code="GENERAL",
                    contact_name="台账联系人",
                    contact_role_code="BUSINESS_CONTACT",
                    mobile_phone=row.get("contact_phone") or operator_phone,
                    is_primary=False,
                    is_available=True,
                    last_verified_at=updated_at,
                    remark="由船舶台账联系电话生成",
                    created_at=created_at,
                    updated_at=updated_at,
                )
            )
            session.add(
                VesselChangeEvent(
                    vessel_profile_id=profile.id,
                    event_type_code="SEED_CREATE",
                    event_title="船舶台账样例生成",
                    before_json=None,
                    after_json={"vessel_profile_code": profile_code, "mmsi": mmsi},
                    operator_id=None,
                    created_at=created_at,
                )
            )
            seed_profiles.append(
                {
                    "idx": idx,
                    "profile_id": profile.id,
                    "profile_code": profile_code,
                    "ship_name": ship_name,
                    "mmsi": mmsi,
                    "ship_type_code": ship_type_code,
                    "deadweight": deadweight,
                    "length": length,
                    "width": width,
                    "building_year": building_year,
                    "owner_id": owner.id,
                    "owner_name": owner.party_name,
                    "operator_id": operator.id,
                    "operator_name": operator.operator_name,
                    "operator_phone": operator_phone,
                    "city_code": registry_city_code,
                    "city_name": registry_city_name,
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )

        session.add_all(
            [
                VesselCertificateRequirementRule(
                    rule_code="SEED_CERT_MIN_CREW",
                    rule_name="内河货船最低船员证书要求",
                    scope_type_code="SHIP_TYPE",
                    ship_type_code="GENERAL_CARGO",
                    required_certificate_type_code="CREW_QUALIFICATION",
                    risk_type_code="CERTIFICATE_MISSING",
                    risk_level_when_missing="HIGH",
                    condition_json={"min_deadweight_ton": 500},
                    evidence_requirements_json={"required_fields": ["holder_name", "certificate_no", "valid_to"]},
                    remark="seed 合规规则，用于本地合规页调试",
                    created_at=now,
                    updated_at=now,
                ),
                VesselCertificateRequirementRule(
                    rule_code="SEED_CERT_CONTAINER",
                    rule_name="集装箱船证照完整性要求",
                    scope_type_code="SHIP_TYPE",
                    ship_type_code="CONTAINER",
                    required_certificate_type_code="VESSEL_OPERATION_CERT",
                    risk_type_code="CERTIFICATE_MISSING",
                    risk_level_when_missing="MEDIUM",
                    condition_json={"ship_type_code": "CONTAINER"},
                    evidence_requirements_json={"required_fields": ["certificate_no", "valid_from", "valid_to"]},
                    remark="seed 合规规则，用于证照风险样例",
                    created_at=now,
                    updated_at=now,
                ),
                VesselCertificateRequirementRule(
                    rule_code="SEED_CERT_SAND",
                    rule_name="砂石自卸船专项证照要求",
                    scope_type_code="SHIP_TYPE",
                    ship_type_code="SELF_UNLOADING_SAND",
                    required_certificate_type_code="CARGO_OPERATION_PERMIT",
                    risk_type_code="CERTIFICATE_MISSING",
                    risk_level_when_missing="HIGH",
                    condition_json={"ship_type_code": "SELF_UNLOADING_SAND"},
                    evidence_requirements_json={"required_fields": ["certificate_no", "issuing_authority"]},
                    remark="seed 合规规则，用于风险复核样例",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )

        session.add(
            VesselAisSnapshot(
                snapshot_id=ais_snapshot_id,
                query_hash="seed-current-ais",
                query_params_json={"source": "seed_system_init", "scope": "all_vessels"},
                status_code="READY",
                generated_at=now,
                expires_at=now + timedelta(days=365),
                cache_backend_code="seed",
                scanned_profile_count=len(seed_profiles),
                queried_mmsi_count=len(seed_profiles),
                matched_profile_count=len(seed_profiles),
                matched_position_count=len(seed_profiles),
                unmatched_mmsi_count=0,
                invalid_position_count=0,
                unknown_city_count=0,
                failed_batch_count=0,
                failed_batches_json=[],
                coverage_rate=Decimal("100.00"),
                freshness_distribution_json={"FRESH": len(seed_profiles), "STALE": 0},
                source_indices_json=["seed"],
                uncertainty_notes_json=[],
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()

        city_counts: dict[tuple[str, str], int] = {}
        for item in seed_profiles:
            city_key = (item["city_code"], item["city_name"])
            city_counts[city_key] = city_counts.get(city_key, 0) + 1
            longitude, latitude = _position_seed(item["idx"], item["city_code"])
            quality_level = "GOOD" if item["idx"] % 7 else "REVIEW"
            risk_level = "LOW" if item["idx"] % 9 else "MEDIUM"
            freshness_level = "FRESH" if item["idx"] % 11 else "STALE"
            issue_count = 1 if item["idx"] % 10 == 0 else 0

            session.add(
                VesselProfileSummary(
                    vessel_profile_id=item["profile_id"],
                    ship_name=item["ship_name"],
                    current_mmsi=item["mmsi"],
                    ship_type_code=item["ship_type_code"],
                    ship_type_name=item["ship_type_code"],
                    deadweight_ton=item["deadweight"],
                    length_m=item["length"],
                    width_m=item["width"],
                    building_year=item["building_year"],
                    ship_age=now.year - item["building_year"],
                    primary_owner_name=item["owner_name"],
                    primary_operator_name=item["operator_name"],
                    primary_contact_name=_operator_contact_name(item["idx"]),
                    primary_contact_phone_masked=f"{item['operator_phone'][:3]}****{item['operator_phone'][-4:]}",
                    contact_available=True,
                    profile_completeness_rate=Decimal("96.00"),
                    data_quality_score=Decimal("92.00") if issue_count == 0 else Decimal("78.00"),
                    data_quality_level=quality_level,
                    identity_confidence_level="HIGH",
                    contact_trust_level="HIGH",
                    subject_consistency_level="CONSISTENT",
                    quality_issue_count=issue_count,
                    missing_field_count=0,
                    conflict_count=0,
                    risk_level=risk_level,
                    risk_evidence_summary_json=[] if risk_level == "LOW" else ["证照待补充"],
                    certificate_missing_count=1 if risk_level != "LOW" else 0,
                    certificate_expiring_count=0,
                    certificate_expired_count=0,
                    latest_position_time=now - timedelta(minutes=item["idx"] % 60),
                    latest_city_code=item["city_code"],
                    latest_city_name=item["city_name"],
                    ais_freshness_level=freshness_level,
                    ais_unavailable_reason=None,
                    analysis_sample_tags_json=["seed", item["ship_type_code"]],
                    analysis_sample_tags_key=f"seed|{item['ship_type_code']}",
                    data_sources_json=["vessel_seed", "ais_seed"],
                    uncertainty_notes_json=[],
                    source_layer="SEED",
                    coverage_rate=Decimal("100.00"),
                    summary_status_code="READY",
                    summary_version="SEED_V3_BASELINE",
                    refreshed_at=now,
                    source_updated_at=item["updated_at"],
                    last_verified_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                VesselLatestPositionSnapshot(
                    snapshot_id=ais_snapshot_id,
                    vessel_profile_id=item["profile_id"],
                    mmsi=item["mmsi"],
                    longitude=longitude,
                    latitude=latitude,
                    speed_kn=Decimal(str(5 + item["idx"] % 8)),
                    course_deg=Decimal(str((item["idx"] * 17) % 360)),
                    heading_deg=Decimal(str((item["idx"] * 17) % 360)),
                    position_time=now - timedelta(minutes=item["idx"] % 60),
                    source_index="seed",
                    freshness_level=freshness_level,
                    match_status_code="MATCHED_PROFILE",
                    city_code=item["city_code"],
                    city_name=item["city_name"],
                    valid_position_flag=True,
                    created_at=now,
                )
            )

        for (city_code, city_name), count in city_counts.items():
            session.add(
                VesselAisCitySnapshotItem(
                    snapshot_id=ais_snapshot_id,
                    city_code=city_code,
                    city_name=city_name,
                    positioned_count=count,
                    matched_position_count=count,
                    unmatched_mmsi_count=0,
                    invalid_position_count=0,
                    stale_position_count=0,
                    freshness_distribution_json={"FRESH": count},
                    boundary_status_code="READY",
                    has_boundary=True,
                    boundary_precision="CITY",
                    latest_position_time=now,
                    created_at=now,
                )
            )

        session.add(
            VesselSpatialObservationSnapshot(
                snapshot_id=spatial_snapshot_id,
                source_snapshot_id=ais_snapshot_id,
                observation_type_code="NODE",
                query_hash="seed-node-current",
                query_params_json={"source": "seed_system_init", "radius_km": 5},
                status_code="READY",
                source_status_code="AVAILABLE",
                stat_time=now,
                window_start=now - timedelta(hours=1),
                window_end=now,
                generated_at=now,
                expires_at=now + timedelta(days=365),
                coverage_rate=Decimal("96.00"),
                confidence_level="HIGH",
                freshness_distribution_json={"FRESH": len(seed_profiles)},
                source_indices_json=["seed"],
                failed_batch_count=0,
                failed_batches_json=[],
                unmatched_mmsi_count=0,
                invalid_position_count=0,
                stale_position_count=0,
                matched_position_count=len(seed_profiles),
                active_vessel_count=len(seed_profiles),
                not_computable_reasons_json=[],
                quality_warnings_json=[],
                uncertainty_notes_json=[],
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()

        for item in seed_profiles[:18]:
            issue = VesselDataQualityIssue(
                issue_type_code="MISSING_CERTIFICATE" if item["idx"] % 2 else "CONTACT_NEEDS_RECHECK",
                severity_code="HIGH" if item["idx"] % 3 == 0 else "MEDIUM",
                affected_object_type="VESSEL_PROFILE",
                affected_object_id=str(item["profile_id"]),
                vessel_profile_id=item["profile_id"],
                field_name="certificate" if item["idx"] % 2 else "contact",
                fingerprint=f"seed-quality-{item['profile_id']}",
                evidence_source="SEED",
                impact_scope_json=["asset", "compliance"],
                status_code="OPEN",
                last_rechecked_at=now,
                last_recheck_status_code="OPEN",
                last_recheck_message="seed 样例：需人工补充或复核",
                created_at=now,
                updated_at=now,
            )
            session.add(issue)
            signal = VesselRiskSignal(
                vessel_profile_id=item["profile_id"],
                risk_type_code="CERTIFICATE_MISSING",
                risk_level="HIGH" if item["idx"] % 3 == 0 else "MEDIUM",
                rule_code="SEED_CERT_MIN_CREW",
                status_code="OPEN",
                confidence_level="MEDIUM",
                fingerprint=f"seed-risk-{item['profile_id']}",
                evidence_json={"reason": "seed 本地调试风险信号", "profile_code": item["profile_code"]},
                source_trace_json=[{"source": "seed_system_init"}],
                uncertainty_notes_json=["样例数据，仅用于本地调试"],
                first_detected_at=now,
                last_detected_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(signal)
            task = VesselGovernanceTask(
                task_no=f"VGT-SEED-{item['idx']:04d}",
                task_type_code="RISK_REVIEW",
                priority_code="HIGH" if item["idx"] % 3 == 0 else "MEDIUM",
                status_code="OPEN",
                vessel_profile_id=item["profile_id"],
                source_rule_code="SEED_CERT_MIN_CREW",
                source_object_type="VESSEL_RISK_SIGNAL",
                source_object_id=f"seed-risk-{item['profile_id']}",
                source_status_code="OPEN",
                source_fingerprint=f"seed-risk-{item['profile_id']}",
                fingerprint=f"seed-governance-{item['profile_id']}",
                title=f"{item['ship_name']} 证照风险复核",
                description="seed 样例：用于治理任务页面调试",
                evidence_summary="证照台账缺失，需补充资料",
                source_trace_json=[{"source": "seed_system_init"}],
                generation_reason_json={"reason": "CERTIFICATE_MISSING"},
                impact_summary_json={"pages": ["compliance", "quality", "governance"]},
                confidence_level="MEDIUM",
                coverage_rate=Decimal("85.00"),
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(task)
            if item["idx"] <= 6:
                session.add(
                    VesselBlacklistSignal(
                        vessel_profile_id=item["profile_id"],
                        list_type_code="WATCHLIST",
                        signal_type_code="LOCAL_RISK_SAMPLE",
                        status_code="ACTIVE",
                        risk_level="HIGH",
                        confidence_level="LOW",
                        source_type_code="SEED",
                        source_trace_id=f"seed-blacklist-{item['idx']}",
                        evidence_summary="seed 样例：关注名单风险",
                        evidence_json={"reason": "本地调试样例"},
                        created_at=now,
                        updated_at=now,
                    )
                )
            if item["idx"] <= 8:
                session.add(
                    VesselRecognitionFieldDiff(
                        vessel_profile_id=item["profile_id"],
                        recognition_object_type="VESSEL_CERTIFICATE_IMAGE",
                        recognition_id=item["profile_id"],
                        target_object_type="VESSEL_PROFILE",
                        target_object_id=item["profile_id"],
                        field_name="ship_name",
                        current_value_text=item["ship_name"],
                        recognized_value_text=f"{item['ship_name']}号",
                        confidence_score=86,
                        evidence_text="seed OCR 差异样例",
                        adopt_status_code="REVIEW_REQUIRED",
                        created_at=now,
                        updated_at=now,
                    )
                )
                session.add(
                    VesselRecognitionAdoptionRecord(
                        vessel_profile_id=item["profile_id"],
                        recognition_object_type="VESSEL_CERTIFICATE_IMAGE",
                        recognition_id=item["profile_id"],
                        target_object_type="VESSEL_PROFILE",
                        target_object_id=item["profile_id"],
                        adopted_fields_json=["ship_type_code"],
                        skipped_fields_json=["ship_name"],
                        confirmed_by=None,
                        confirmed_at=now,
                        reason="seed 样例：保留差异供识别工作台调试",
                        created_at=now,
                    )
                )
            if item["idx"] <= 6:
                session.add(
                    VesselControllerEvidence(
                        vessel_profile_id=item["profile_id"],
                        party_name=f"{item['city_name']}港航投资有限公司",
                        controller_role_code="ACTUAL_CONTROLLER",
                        confidence_level="MEDIUM",
                        source_type_code="SEED",
                        source_trace_id=f"seed-controller-{item['idx']}",
                        evidence_summary="seed 样例：实际控制人线索",
                        evidence_json={"reason": "联系人和运营方地址一致"},
                        effective_from=now.date(),
                        status_code="ACTIVE",
                        verified_status_code="DRAFT",
                        created_at=now,
                        updated_at=now,
                    )
                )
                session.add(
                    VesselAffiliationEvidence(
                        vessel_profile_id=item["profile_id"],
                        owner_period_id=item["owner_id"],
                        operator_period_id=item["operator_id"],
                        affiliation_type_code="OWNER_OPERATOR_LINK",
                        subject_name=item["owner_name"],
                        counterparty_name=item["operator_name"],
                        confidence_level="MEDIUM",
                        source_type_code="SEED",
                        source_trace_id=f"seed-affiliation-{item['idx']}",
                        evidence_summary="seed 样例：船东与运营方关联线索",
                        evidence_json={"reason": "同城业务关系"},
                        effective_from=now.date(),
                        status_code="ACTIVE",
                        verified_status_code="DRAFT",
                        created_at=now,
                        updated_at=now,
                    )
                )

        candidate = VesselCandidateAnalysis(
            context_type_code="CITY_PAIR",
            source_layer_code="SEED",
            origin_city_code=PORT_SEEDS[0][0],
            destination_city_code=PORT_SEEDS[2][0],
            context_json={"origin_city_name": PORT_SEEDS[0][1], "destination_city_name": PORT_SEEDS[2][1]},
            filters_json={"ship_types": ["GENERAL_CARGO", "DRY_BULK"], "min_deadweight_ton": 500},
            source_ais_snapshot_id=ais_snapshot_id,
            source_spatial_snapshot_id=spatial_snapshot_id,
            query_hash="seed-city-pair-analysis",
            status_code="READY",
            coverage_rate=Decimal("90.00"),
            confidence_level="MEDIUM",
            candidate_count=10,
            low_confidence_count=2,
            not_computable_reasons_json=[],
            uncertainty_notes_json=["部分 AIS 点位为 seed 坐标"],
            data_sources_json=["vessel_profile_summary", "latest_position_snapshot"],
            generated_at=now,
            expires_at=now + timedelta(days=365),
            created_by=None,
            created_at=now,
            updated_at=now,
        )
        session.add(candidate)
        await session.flush()
        for rank, item in enumerate(seed_profiles[:10], start=1):
            session.add(
                VesselCandidateAnalysisItem(
                    analysis_id=candidate.id,
                    vessel_profile_id=item["profile_id"],
                    mmsi=item["mmsi"],
                    ship_name=item["ship_name"],
                    ship_type_code=item["ship_type_code"],
                    deadweight_ton=item["deadweight"],
                    latest_position_time=now - timedelta(minutes=item["idx"] % 60),
                    ais_freshness_level="FRESH",
                    risk_level="LOW" if rank > 3 else "MEDIUM",
                    quality_level="GOOD",
                    fit_score=Decimal(str(96 - rank * 3)),
                    candidate_value_level="HIGH" if rank <= 3 else "MEDIUM",
                    confidence_level="HIGH" if rank <= 5 else "MEDIUM",
                    node_distance_km=Decimal(str(rank * 1.3)),
                    route_match_score=Decimal(str(90 - rank)),
                    direction_consistency=Decimal("88.00"),
                    constraint_status_code="PASS",
                    score_parts_json={"capacity": 90, "position": 88, "risk": 80},
                    risk_reasons_json=[] if rank > 3 else ["证照待复核"],
                    uncertainty_reasons_json=[],
                    not_computable_reasons_json=[],
                    data_sources_json=["seed"],
                    created_at=now,
                )
            )
        session.add(
            VesselNavigationConstraintEvidence(
                snapshot_id=spatial_snapshot_id,
                context_type_code="CITY_PAIR",
                context_id=candidate.id,
                constraint_name="seed 航行限制样例",
                constraint_type_code="DRAFT_LIMIT",
                status_code="PASS",
                source_type_code="SEED",
                source_ref="seed_system_init",
                observed_at=now,
                expires_at=now + timedelta(days=365),
                value_json={"max_draft_m": 5.5},
                confidence_level="MEDIUM",
                created_at=now,
            )
        )

        await session.execute(
            update(CodeSequence)
            .where(CodeSequence.biz_code == "VESSEL_PROFILE_CODE")
            .values(current_value=len(rows), updated_at=now)
        )
        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_vessel_samples())
