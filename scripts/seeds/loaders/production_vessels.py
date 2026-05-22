"""Seed curated production vessel profiles."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.vessel import (
    VesselBuildInfo,
    VesselCapacityDimension,
    VesselContact,
    VesselIdentifierHistory,
    VesselIdentity,
    VesselIdentityLink,
    VesselNameHistory,
    VesselProfile,
    VesselProfileSummary,
    VesselRegistrationInfo,
)


PRODUCTION_VESSEL_FILE = (
    Path(__file__).resolve().parents[2]
    / "seed_data"
    / "vessel"
    / "production_vessels.json"
)
PRODUCTION_VESSEL_SOURCE_TYPES = {"TMS", "HIGH_VALUE_INLAND", "TMS_HIGH_VALUE"}
BATCH_SIZE = 1000
PROFILE_VESSEL_LIMITS = {
    "local-demo": 20000,
    "test": 1500,
}
SOURCE_PRIORITY = {
    "TMS_HIGH_VALUE": 0,
    "TMS": 1,
    "HIGH_VALUE_INLAND": 2,
}
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _load_json(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return list(payload.get("vessels") or payload.get("data") or [])
    return list(payload)


def _chunks(rows: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for index in range(0, len(rows), size):
        yield rows[index : index + size]


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _datetime(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value))


def _truncate(value: Any, length: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:length]


def _mask_phone(phone: Any) -> str | None:
    if not phone:
        return None
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if len(digits) < 7:
        return "***"
    return f"{digits[:3]}****{digits[-4:]}"


def _profile_completeness_score(row: dict[str, Any]) -> int:
    capacity = row.get("capacity") or {}
    build = row.get("build") or {}
    values = [
        row.get("mmsi"),
        row.get("ship_name"),
        row.get("ship_type_code"),
        row.get("registry_city_code"),
        capacity.get("deadweight_ton"),
        capacity.get("length_m"),
        capacity.get("width_m"),
        build.get("building_year"),
        row.get("contacts"),
    ]
    return sum(1 for value in values if value not in (None, "", []))


def _profile_sort_key(row: dict[str, Any]) -> tuple[int, int, int, int, float, str]:
    capacity = row.get("capacity") or {}
    source_type = str(row.get("source_type_code") or "")
    deadweight = float(capacity.get("deadweight_ton") or 0)
    return (
        SOURCE_PRIORITY.get(source_type, 9),
        -_profile_completeness_score(row),
        0 if row.get("contacts") else 1,
        0 if CJK_RE.search(str(row.get("ship_name") or "")) else 1,
        -deadweight,
        str(row.get("mmsi") or ""),
    )


def _profile_limited_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    profile = (os.getenv("SEED_PROFILE") or "").strip().lower()
    raw_limit = (os.getenv("SEED_VESSEL_LIMIT") or "").strip().lower()
    if raw_limit == "":
        limit = PROFILE_VESSEL_LIMITS.get(profile)
    elif raw_limit in {"full", "all", "0"}:
        limit = None
    else:
        limit = max(1, int(raw_limit))
    ordered = sorted(rows, key=_profile_sort_key)
    if limit is None or len(ordered) <= limit:
        return ordered
    return ordered[:limit]


def _source_summary(source_type_code: str) -> list[dict[str, Any]]:
    if source_type_code == "TMS_HIGH_VALUE":
        return [
            {"source_type_code": "TMS", "record_count": None},
            {"source_type_code": "HIGH_VALUE_INLAND", "record_count": None},
        ]
    return [{"source_type_code": source_type_code, "record_count": None}]


def _summary_payload(row: dict[str, Any]) -> dict[str, Any]:
    provided = row.get("summary")
    if isinstance(provided, dict) and provided:
        return provided

    capacity = row.get("capacity") or {}
    build = row.get("build") or {}
    contacts = row.get("contacts") or []
    primary_contact = contacts[0] if contacts else {}
    source_type_code = str(row.get("source_type_code") or "TMS_HIGH_VALUE")
    completeness_values = [
        row.get("mmsi"),
        row.get("ship_name"),
        row.get("ship_type_code"),
        row.get("registry_city_code"),
        capacity.get("deadweight_ton"),
        capacity.get("length_m"),
        capacity.get("width_m"),
        build.get("building_year"),
        contacts,
    ]
    missing = sum(1 for value in completeness_values if value in (None, "", []))
    completeness = round((len(completeness_values) - missing) / len(completeness_values) * 100, 2)
    conflict_count = int(row.get("conflict_count") or 0)
    data_quality_score = max(0, completeness - conflict_count * 5)
    if data_quality_score >= 85:
        quality_level = "HIGH"
    elif data_quality_score >= 60:
        quality_level = "MEDIUM"
    else:
        quality_level = "LOW"
    building_year = build.get("building_year")
    ship_age = None
    if building_year:
        ship_age = max(0, 2026 - int(building_year))

    return {
        "ship_name": row.get("ship_name"),
        "current_mmsi": row.get("mmsi"),
        "ship_type_code": row.get("ship_type_code"),
        "ship_type_name": row.get("ship_type_name"),
        "deadweight_ton": capacity.get("deadweight_ton"),
        "length_m": capacity.get("length_m"),
        "width_m": capacity.get("width_m"),
        "design_draft_m": capacity.get("design_draft_m"),
        "building_year": building_year,
        "ship_age": ship_age,
        "primary_owner_name": None,
        "primary_operator_name": None,
        "primary_contact_name": primary_contact.get("contact_name"),
        "primary_contact_phone_masked": _mask_phone(primary_contact.get("mobile_phone")),
        "contact_available": bool(contacts),
        "profile_completeness_rate": completeness,
        "data_quality_score": round(data_quality_score, 2),
        "data_quality_level": quality_level,
        "identity_confidence_level": "HIGH" if source_type_code == "TMS_HIGH_VALUE" else "MEDIUM",
        "contact_trust_level": "MEDIUM" if contacts else "UNKNOWN",
        "subject_consistency_level": "UNKNOWN",
        "quality_issue_count": missing + conflict_count,
        "missing_field_count": missing,
        "conflict_count": conflict_count,
        "risk_level": "UNKNOWN",
        "risk_evidence_summary_json": [],
        "certificate_missing_count": 0,
        "certificate_expiring_count": 0,
        "certificate_expired_count": 0,
        "latest_position_time": None,
        "latest_city_code": None,
        "latest_city_name": None,
        "ais_freshness_level": "UNKNOWN",
        "ais_unavailable_reason": "生产船舶 seed 不生成模拟 AIS 位置。",
        "analysis_sample_tags_json": [],
        "analysis_sample_tags_key": None,
        "data_sources_json": _source_summary(source_type_code),
        "uncertainty_notes_json": row.get("uncertainty_notes") or [],
        "source_layer": "PROFILE_SUMMARY",
        "coverage_rate": completeness,
        "summary_status_code": "READY",
        "summary_version": "ROUND_05_V1",
        "refreshed_at": "2026-05-15T00:00:00",
        "source_updated_at": None,
        "last_verified_at": None,
    }


async def seed_production_vessels() -> None:
    rows = _load_json(PRODUCTION_VESSEL_FILE)
    if not rows:
        return
    rows = _profile_limited_rows(rows)

    async with AsyncSessionLocal() as session:
        for batch in _chunks(rows, BATCH_SIZE):
            identity_codes = [str(row["identity_code"]) for row in batch]
            profile_codes = [str(row["profile_code"]) for row in batch]
            identities = (
                await session.execute(
                    select(VesselIdentity).where(VesselIdentity.identity_code.in_(identity_codes))
                )
            ).scalars().all()
            profiles = (
                await session.execute(
                    select(VesselProfile).where(VesselProfile.vessel_profile_code.in_(profile_codes))
                )
            ).scalars().all()
            identity_by_code = {row.identity_code: row for row in identities}
            profile_by_code = {row.vessel_profile_code: row for row in profiles}
            now = datetime.utcnow()
            prepared: list[tuple[dict[str, Any], VesselIdentity, VesselProfile]] = []

            for row in batch:
                identity_code = str(row["identity_code"])
                profile_code = str(row["profile_code"])
                source_type_code = str(row.get("source_type_code") or "TMS_HIGH_VALUE")
                identity_payload = {
                    "identity_code": identity_code,
                    "identity_status_code": row.get("identity_status_code") or "LINKED",
                    "canonical_mmsi": row.get("mmsi"),
                    "canonical_ship_name": _truncate(row.get("ship_name"), 128),
                    "confidence_score": 100 if source_type_code == "TMS_HIGH_VALUE" else 90,
                    "source_type_code": source_type_code,
                    "remark": _truncate(row.get("remark"), 512),
                }
                identity = identity_by_code.get(identity_code)
                if identity is None:
                    identity = VesselIdentity(**identity_payload)
                    session.add(identity)
                    identity_by_code[identity_code] = identity
                else:
                    for key, value in identity_payload.items():
                        setattr(identity, key, value)
                    identity.deleted_at = None

                profile_payload = {
                    "vessel_profile_code": profile_code,
                    "ship_name": _truncate(row.get("ship_name") or profile_code, 128),
                    "ship_name_en": _truncate(row.get("ship_name_en"), 256),
                    "current_mmsi": row.get("mmsi"),
                    "ship_type_code": row.get("ship_type_code") or "OTHER",
                    "profile_status_code": row.get("profile_status_code") or "ACTIVE",
                    "identity_status_code": row.get("identity_status_code") or "LINKED",
                    "operation_status_code": row.get("operation_status_code"),
                    "home_port_code": row.get("registry_city_code"),
                    "home_port_name": _truncate(row.get("home_port_name"), 128),
                    "registry_city_code": row.get("registry_city_code"),
                    "source_type_code": source_type_code,
                    "remark": _truncate(row.get("remark"), 512),
                }
                profile = profile_by_code.get(profile_code)
                if profile is None:
                    profile = VesselProfile(**profile_payload)
                    session.add(profile)
                    profile_by_code[profile_code] = profile
                else:
                    for key, value in profile_payload.items():
                        setattr(profile, key, value)
                    profile.deleted_at = None
                prepared.append((row, identity, profile))

            await session.flush()

            profile_ids = [profile.id for _row, _identity, profile in prepared]
            for model in (
                VesselProfileSummary,
                VesselContact,
                VesselBuildInfo,
                VesselCapacityDimension,
                VesselRegistrationInfo,
                VesselIdentifierHistory,
                VesselNameHistory,
                VesselIdentityLink,
            ):
                await session.execute(delete(model).where(model.vessel_profile_id.in_(profile_ids)))

            for row, identity, profile in prepared:
                profile.vessel_identity_id = identity.id
                session.add(
                    VesselIdentityLink(
                        vessel_identity_id=identity.id,
                        vessel_profile_id=profile.id,
                        link_type_code="PROFILE",
                        confidence_score=100 if row.get("source_type_code") == "TMS_HIGH_VALUE" else 90,
                        is_primary=True,
                        start_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )
                names = row.get("names") or [
                    {
                        "ship_name": row.get("ship_name"),
                        "source_type_code": row.get("source_type_code"),
                    }
                ]
                for name in names:
                    ship_name = str(name.get("ship_name") or "").strip()
                    if not ship_name:
                        continue
                    session.add(
                        VesselNameHistory(
                            vessel_profile_id=profile.id,
                            ship_name=_truncate(ship_name, 128) or ship_name,
                            source_type_code=name.get("source_type_code") or row.get("source_type_code") or "IMPORT",
                            created_at=now,
                        )
                    )
                identifiers = [
                    {
                        "identifier_type_code": "MMSI",
                        "identifier_value": row.get("mmsi"),
                        "source_type_code": row.get("source_type_code") or "TMS_HIGH_VALUE",
                        "source_trace_id": None,
                        "confidence_score": 100,
                    }
                ] + list(row.get("extra_identifiers") or row.get("identifiers") or [])
                for identifier in identifiers:
                    value = str(identifier.get("identifier_value") or "").strip()
                    identifier_type = str(identifier.get("identifier_type_code") or "").strip()
                    if not value or not identifier_type:
                        continue
                    session.add(
                        VesselIdentifierHistory(
                            vessel_profile_id=profile.id,
                            identifier_type_code=identifier_type,
                            identifier_value=_truncate(value, 64) or value,
                            source_type_code=identifier.get("source_type_code") or row.get("source_type_code") or "IMPORT",
                            source_trace_id=_truncate(identifier.get("source_trace_id"), 128),
                            status_code=identifier.get("status_code") or "ACTIVE",
                            confidence_score=int(identifier.get("confidence_score") or 100),
                            created_at=now,
                        )
                    )

                registration = row.get("registration") or {}
                session.add(
                    VesselRegistrationInfo(
                        vessel_profile_id=profile.id,
                        registry_city_code=registration.get("registry_city_code"),
                        ship_registry_no=registration.get("ship_registry_no"),
                        home_port_code=registration.get("home_port_code"),
                        home_port_name=_truncate(registration.get("home_port_name"), 128),
                        flag_code=registration.get("flag_code"),
                        mmsi_issuing_authority=_truncate(registration.get("mmsi_issuing_authority"), 128),
                        inspection_org=_truncate(registration.get("inspection_org"), 128),
                        remark=_truncate(registration.get("remark"), 512),
                        updated_at=now,
                    )
                )

                capacity = row.get("capacity") or {}
                session.add(
                    VesselCapacityDimension(
                        vessel_profile_id=profile.id,
                        deadweight_ton=_decimal(capacity.get("deadweight_ton")),
                        reference_load_ton=_decimal(capacity.get("reference_load_ton")),
                        total_tonnage=_decimal(capacity.get("total_tonnage")),
                        net_tonnage=_decimal(capacity.get("net_tonnage")),
                        length_m=_decimal(capacity.get("length_m")),
                        width_m=_decimal(capacity.get("width_m")),
                        depth_m=_decimal(capacity.get("depth_m")),
                        design_draft_m=_decimal(capacity.get("design_draft_m")),
                        max_draft_m=_decimal(capacity.get("max_draft_m")),
                        design_speed_kn=_decimal(capacity.get("design_speed_kn")),
                        hold_count=capacity.get("hold_count"),
                        teu_capacity=capacity.get("teu_capacity"),
                        capacity_remark=_truncate(capacity.get("capacity_remark"), 512),
                        updated_at=now,
                    )
                )

                build = row.get("build") or {}
                session.add(
                    VesselBuildInfo(
                        vessel_profile_id=profile.id,
                        building_year=build.get("building_year"),
                        builder_name=_truncate(build.get("builder_name"), 128),
                        build_place=_truncate(build.get("build_place"), 128),
                        hull_material_code=_truncate(build.get("hull_material_code"), 64),
                        engine_power_kw=_decimal(build.get("engine_power_kw")),
                        remark=_truncate(build.get("remark"), 512),
                        updated_at=now,
                    )
                )

                for contact in row.get("contacts") or []:
                    contact_name = str(contact.get("contact_name") or "").strip()
                    if not contact_name:
                        continue
                    session.add(
                        VesselContact(
                            vessel_profile_id=profile.id,
                            contact_scope_code=contact.get("contact_scope_code") or "GENERAL",
                            contact_name=_truncate(contact_name, 64) or contact_name,
                            contact_role_code=contact.get("contact_role_code") or "BUSINESS_CONTACT",
                            mobile_phone=_truncate(contact.get("mobile_phone"), 32),
                            wechat=_truncate(contact.get("wechat"), 64),
                            email=_truncate(contact.get("email"), 128),
                            is_current=True,
                            is_primary=bool(contact.get("is_primary", False)),
                            is_available=bool(contact.get("is_available", True)),
                            verified_status_code=contact.get("verified_status_code") or "UNVERIFIED",
                            source_type_code=contact.get("source_type_code") or "TMS",
                            source_trace_id=_truncate(contact.get("source_trace_id"), 128),
                            remark=_truncate(contact.get("remark"), 512),
                            created_at=now,
                            updated_at=now,
                        )
                    )

                summary = _summary_payload(row)
                session.add(
                    VesselProfileSummary(
                        vessel_profile_id=profile.id,
                        ship_name=_truncate(summary.get("ship_name"), 128),
                        current_mmsi=summary.get("current_mmsi"),
                        ship_type_code=summary.get("ship_type_code"),
                        ship_type_name=_truncate(summary.get("ship_type_name"), 128),
                        deadweight_ton=_decimal(summary.get("deadweight_ton")),
                        length_m=_decimal(summary.get("length_m")),
                        width_m=_decimal(summary.get("width_m")),
                        design_draft_m=_decimal(summary.get("design_draft_m")),
                        building_year=summary.get("building_year"),
                        ship_age=summary.get("ship_age"),
                        primary_owner_name=_truncate(summary.get("primary_owner_name"), 128),
                        primary_operator_name=_truncate(summary.get("primary_operator_name"), 128),
                        primary_contact_name=_truncate(summary.get("primary_contact_name"), 64),
                        primary_contact_phone_masked=_truncate(summary.get("primary_contact_phone_masked"), 32),
                        contact_available=summary.get("contact_available"),
                        profile_completeness_rate=_decimal(summary.get("profile_completeness_rate")),
                        data_quality_score=_decimal(summary.get("data_quality_score")),
                        data_quality_level=summary.get("data_quality_level") or "UNKNOWN",
                        identity_confidence_level=summary.get("identity_confidence_level") or "UNKNOWN",
                        contact_trust_level=summary.get("contact_trust_level") or "UNKNOWN",
                        subject_consistency_level=summary.get("subject_consistency_level") or "UNKNOWN",
                        quality_issue_count=int(summary.get("quality_issue_count") or 0),
                        missing_field_count=int(summary.get("missing_field_count") or 0),
                        conflict_count=int(summary.get("conflict_count") or 0),
                        risk_level=summary.get("risk_level") or "UNKNOWN",
                        risk_evidence_summary_json=summary.get("risk_evidence_summary_json"),
                        certificate_missing_count=int(summary.get("certificate_missing_count") or 0),
                        certificate_expiring_count=int(summary.get("certificate_expiring_count") or 0),
                        certificate_expired_count=int(summary.get("certificate_expired_count") or 0),
                        latest_position_time=_datetime(summary.get("latest_position_time")),
                        latest_city_code=summary.get("latest_city_code"),
                        latest_city_name=_truncate(summary.get("latest_city_name"), 128),
                        ais_freshness_level=summary.get("ais_freshness_level") or "UNKNOWN",
                        ais_unavailable_reason=_truncate(summary.get("ais_unavailable_reason"), 512),
                        analysis_sample_tags_json=summary.get("analysis_sample_tags_json"),
                        analysis_sample_tags_key=summary.get("analysis_sample_tags_key"),
                        data_sources_json=summary.get("data_sources_json"),
                        uncertainty_notes_json=summary.get("uncertainty_notes_json"),
                        source_layer=summary.get("source_layer") or "PROFILE_SUMMARY",
                        coverage_rate=_decimal(summary.get("coverage_rate")),
                        summary_status_code=summary.get("summary_status_code") or "READY",
                        summary_version=summary.get("summary_version") or "ROUND_05_V1",
                        refreshed_at=_datetime(summary.get("refreshed_at")),
                        source_updated_at=_datetime(summary.get("source_updated_at")),
                        last_verified_at=_datetime(summary.get("last_verified_at")),
                        refresh_error=summary.get("refresh_error"),
                        created_at=now,
                        updated_at=now,
                    )
                )
            await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_production_vessels())
