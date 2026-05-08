"""船舶主数据 seed。"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, update

from app.core.database import AsyncSessionLocal
from app.models.common import CodeSequence
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
    VesselIdentity,
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


async def _clear_vessels(session) -> None:
    for model in (
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

        for idx, row in enumerate(rows, start=1):
            created_at = _dt(row.get("source_created_at"), now)
            updated_at = _dt(row.get("source_updated_at"), created_at)
            profile_code = row.get("vessel_code") or f"VP{idx:06d}"
            mmsi = str(row["mmsi"])
            ship_name = str(row["ship_name"])

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
                ship_type_code="OTHER",
                profile_status_code=_status(row),
                identity_status_code="LINKED",
                operation_status_code="OPERATING" if row.get("source_status_text") == "正常" else None,
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
                    flag_code="CN" if row.get("nationality") == "中国" else None,
                    remark=f"来源船舶编码：{profile_code}",
                    updated_at=updated_at,
                )
            )

            deadweight = _decimal(row.get("deadweight_ton"))
            length = _decimal(row.get("length_m"))
            width = _decimal(row.get("width_m"))
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

            session.add(
                VesselOwnerPeriod(
                    vessel_profile_id=profile.id,
                    party_name="待补录船东",
                    party_type_code="UNKNOWN",
                    is_current=True,
                    is_primary=True,
                    created_at=created_at,
                    updated_at=updated_at,
                )
            )
            if row.get("owner_phone"):
                session.add(
                    VesselContact(
                        vessel_profile_id=profile.id,
                        contact_scope_code="OWNER",
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
                    contact_scope_code="GENERAL",
                    contact_name="台账联系人",
                    contact_role_code="BUSINESS_CONTACT",
                    mobile_phone=row.get("contact_phone"),
                    is_primary=True,
                    is_available=bool(row.get("contact_phone")),
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

        await session.execute(
            update(CodeSequence)
            .where(CodeSequence.biz_code == "VESSEL_PROFILE_CODE")
            .values(current_value=len(rows), updated_at=now)
        )
        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_vessel_samples())
