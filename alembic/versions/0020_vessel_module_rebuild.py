"""vessel_module_rebuild

Revision ID: 0020_vessel_module_rebuild
Revises: 0019_freight_normalization_review_flow
Create Date: 2026-05-08 12:30:00.000000

"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import BigInteger

from app.models.storage import StorageFile  # noqa: F401
from app.models.vessel import (
    VesselBuildInfo,
    VesselCapacityDimension,
    VesselCertificate,
    VesselCertificateFile,
    VesselChangeEvent,
    VesselContact,
    VesselCrewAssignment,
    VesselIdentifierHistory,
    VesselIdentity,
    VesselIdentityLink,
    VesselNameHistory,
    VesselOperatorPeriod,
    VesselOwnerPeriod,
    VesselPersonCertificate,
    VesselProfile,
    VesselRegistrationInfo,
)


@compiles(BigInteger, "sqlite")
def _compile_bigint_sqlite(_type, _compiler, **_kw):
    return "INTEGER"


revision: str = "0020_vessel_module_rebuild"
down_revision: Union[str, None] = "0019_freight_normalization_review_flow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


VESSEL_TABLES = [
    VesselIdentity.__table__,
    VesselProfile.__table__,
    VesselIdentityLink.__table__,
    VesselIdentifierHistory.__table__,
    VesselNameHistory.__table__,
    VesselRegistrationInfo.__table__,
    VesselCapacityDimension.__table__,
    VesselBuildInfo.__table__,
    VesselOwnerPeriod.__table__,
    VesselOperatorPeriod.__table__,
    VesselContact.__table__,
    VesselCrewAssignment.__table__,
    VesselPersonCertificate.__table__,
    VesselCertificate.__table__,
    VesselCertificateFile.__table__,
    VesselChangeEvent.__table__,
]

OLD_SHIP_TABLES = [
    "ship_certificate_file",
    "ship_certificate",
    "ship_mmsi_history",
    "ship_name_history",
    "ship_contact",
    "ship_owner",
    "ship_operation",
    "ship_capacity",
    "ship_dynamic",
    "ship_import_record",
    "ship_import_raw",
    "ship_import_batch",
    "stat_ship_flow_daily",
    "stat_ship_city_daily",
    "ship_profile",
]

SHIP_TYPE_MAP = {
    "BULK_CARRIER": "DRY_BULK",
    "SELF_UNLOADING_BULK": "SELF_UNLOADING_SAND",
    "GENERAL_CARGO_SHIP": "GENERAL_CARGO",
    "CONTAINER_SHIP": "CONTAINER",
    "MULTIPURPOSE": "MULTI_PURPOSE",
    "BARGE": "OTHER",
    "TUG": "TUG",
    "OIL_TANKER": "OIL_TANKER",
    "CHEMICAL_TANKER": "CHEMICAL_TANKER",
}


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _mmsi(value: str | None, row_id: int) -> str:
    cleaned = (value or "").strip()
    if len(cleaned) == 9 and cleaned.isdigit():
        return cleaned
    return f"900{int(row_id) % 1_000_000:06d}"[-9:]


def _insert(table: str, data: dict) -> None:
    data = {
        key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
        for key, value in data.items()
    }
    keys = list(data)
    columns = ", ".join(keys)
    values = ", ".join(f":{key}" for key in keys)
    op.get_bind().execute(sa.text(f"insert into {table} ({columns}) values ({values})"), data)


def _clear_vessel_tables() -> None:
    bind = op.get_bind()
    for table in reversed(VESSEL_TABLES):
        if _has_table(table.name):
            bind.execute(sa.text(f"delete from {table.name}"))


def _backfill_from_ship_tables() -> None:
    bind = op.get_bind()
    if not _has_table("ship_profile"):
        return

    now = datetime.utcnow()
    profiles = bind.execute(sa.text("select * from ship_profile order by id asc")).mappings().all()
    for row in profiles:
        vessel_id = int(row["id"])
        mmsi = _mmsi(row.get("current_mmsi"), vessel_id)
        ship_type = SHIP_TYPE_MAP.get(row.get("ship_type_code"), row.get("ship_type_code"))
        identity_status = "UNLINKED"
        _insert(
            "vessel_identity",
            {
                "id": vessel_id,
                "identity_code": f"VID{vessel_id:06d}",
                "identity_status_code": "VERIFIED" if identity_status == "LINKED" else "UNVERIFIED",
                "canonical_mmsi": mmsi,
                "canonical_ship_name": row.get("ship_name"),
                "confidence_score": 90 if identity_status == "LINKED" else 40,
                "source_type_code": row.get("source_type_code") or "LEGACY_SHIP",
                "remark": "由旧 ship_profile 回填",
                "created_at": row.get("created_at") or now,
                "updated_at": row.get("updated_at") or now,
                "deleted_at": row.get("deleted_at"),
            },
        )
        _insert(
            "vessel_profile",
            {
                "id": vessel_id,
                "vessel_profile_code": f"VP{vessel_id:06d}",
                "vessel_identity_id": vessel_id,
                "ship_name": row.get("ship_name"),
                "ship_name_en": row.get("ship_name_en"),
                "current_mmsi": mmsi,
                "ship_type_code": ship_type,
                "profile_status_code": row.get("profile_status_code") or "ACTIVE",
                "identity_status_code": identity_status,
                "operation_status_code": row.get("operation_status_code"),
                "home_port_code": row.get("home_port_code"),
                "home_port_name": row.get("home_port_name"),
                "registry_city_code": row.get("registry_city_code"),
                "business_region_id": row.get("business_region_id"),
                "source_type_code": row.get("source_type_code") or "LEGACY_SHIP",
                "remark": None,
                "created_at": row.get("created_at") or now,
                "updated_at": row.get("updated_at") or now,
                "deleted_at": row.get("deleted_at"),
                "audit_status": row.get("audit_status") or "PENDING",
                "submitter_id": row.get("submitter_id"),
                "auditor_id": row.get("auditor_id"),
                "audited_at": row.get("audited_at"),
            },
        )
        _insert(
            "vessel_identity_link",
            {
                "vessel_identity_id": vessel_id,
                "vessel_profile_id": vessel_id,
                "link_type_code": "LEGACY_PROFILE",
                "confidence_score": 90,
                "is_primary": True,
                "start_at": row.get("created_at") or now,
                "end_at": None,
                "created_at": now,
                "updated_at": now,
            },
        )
        _insert(
            "vessel_name_history",
            {
                "vessel_profile_id": vessel_id,
                "ship_name": row.get("ship_name"),
                "start_date": None,
                "end_date": None,
                "source_type_code": row.get("source_type_code") or "LEGACY_SHIP",
                "created_at": row.get("created_at") or now,
            },
        )
        _insert(
            "vessel_identifier_history",
            {
                "vessel_profile_id": vessel_id,
                "identifier_type_code": "MMSI",
                "identifier_value": mmsi,
                "start_date": None,
                "end_date": None,
                "source_type_code": row.get("source_type_code") or "LEGACY_SHIP",
                "created_at": row.get("created_at") or now,
            },
        )
        _insert(
            "vessel_registration_info",
            {
                "vessel_profile_id": vessel_id,
                "registry_city_code": row.get("registry_city_code"),
                "ship_registry_no": None,
                "home_port_code": row.get("home_port_code"),
                "home_port_name": row.get("home_port_name"),
                "flag_code": "CN",
                "mmsi_issuing_authority": None,
                "inspection_org": None,
                "remark": None,
                "updated_at": row.get("updated_at") or now,
            },
        )
        _insert(
            "vessel_build_info",
            {
                "vessel_profile_id": vessel_id,
                "building_year": row.get("building_year"),
                "builder_name": None,
                "build_place": None,
                "hull_material_code": None,
                "engine_power_kw": None,
                "remark": None,
                "updated_at": row.get("updated_at") or now,
            },
        )

    if _has_table("ship_capacity"):
        for row in bind.execute(sa.text("select * from ship_capacity")).mappings().all():
            _insert(
                "vessel_capacity_dimension",
                {
                    "vessel_profile_id": row.get("ship_id"),
                    "deadweight_ton": row.get("deadweight_ton"),
                    "reference_load_ton": row.get("reference_load_ton"),
                    "total_tonnage": row.get("total_tonnage"),
                    "net_tonnage": row.get("net_tonnage"),
                    "length_m": row.get("length_m"),
                    "width_m": row.get("width_m"),
                    "depth_m": row.get("depth_m"),
                    "design_draft_m": row.get("design_draft_m"),
                    "max_draft_m": row.get("design_draft_m"),
                    "design_speed_kn": row.get("design_speed_kn"),
                    "hold_count": row.get("hold_count"),
                    "teu_capacity": None,
                    "capacity_remark": row.get("capacity_remark"),
                    "updated_at": row.get("updated_at") or now,
                },
            )

    if _has_table("ship_operation"):
        for row in bind.execute(sa.text("select * from ship_operation")).mappings().all():
            if row.get("operator_name") or row.get("manager_name"):
                _insert(
                    "vessel_operator_period",
                    {
                        "vessel_profile_id": row.get("ship_id"),
                        "operator_name": row.get("operator_name") or row.get("manager_name") or "未知运营方",
                        "party_type_code": "UNKNOWN",
                        "contact_phone": row.get("contact_phone"),
                        "start_date": None,
                        "end_date": None,
                        "is_current": True,
                        "is_primary": True,
                        "created_at": now,
                        "updated_at": row.get("updated_at") or now,
                    },
                )

    if _has_table("ship_owner"):
        for row in bind.execute(sa.text("select * from ship_owner")).mappings().all():
            _insert(
                "vessel_owner_period",
                    {
                        "vessel_profile_id": row.get("ship_id"),
                        "party_name": row.get("party_name"),
                        "party_type_code": "UNKNOWN",
                        "certificate_no": row.get("certificate_no"),
                        "mobile_phone": row.get("mobile_phone"),
                        "landline_phone": row.get("landline_phone"),
                    "address": row.get("address"),
                    "start_date": None,
                    "end_date": None,
                    "is_current": True,
                    "is_primary": row.get("is_primary"),
                    "created_at": row.get("created_at") or now,
                    "updated_at": row.get("updated_at") or now,
                },
            )

    if _has_table("ship_contact"):
        for row in bind.execute(sa.text("select * from ship_contact")).mappings().all():
            _insert(
                "vessel_contact",
                {
                    "vessel_profile_id": row.get("ship_id"),
                    "contact_name": row.get("contact_name"),
                    "contact_role_code": row.get("contact_role_code"),
                    "mobile_phone": row.get("mobile_phone"),
                    "wechat": row.get("wechat"),
                    "email": row.get("email"),
                    "is_primary": row.get("is_primary"),
                    "is_available": True,
                    "last_verified_at": row.get("updated_at"),
                    "remark": row.get("remark"),
                    "created_at": row.get("created_at") or now,
                    "updated_at": row.get("updated_at") or now,
                },
            )

    if _has_table("ship_certificate"):
        for row in bind.execute(sa.text("select * from ship_certificate")).mappings().all():
            _insert(
                "vessel_certificate",
                {
                    "id": row.get("id"),
                    "vessel_profile_id": row.get("ship_id"),
                    "certificate_type_code": row.get("certificate_type_code"),
                    "certificate_no": row.get("certificate_no"),
                    "issuing_authority": row.get("issuing_authority"),
                    "valid_from": row.get("valid_from"),
                    "valid_to": row.get("valid_to"),
                    "is_long_term_valid": row.get("is_long_term_valid"),
                    "validity_text_raw": row.get("validity_text_raw"),
                    "verify_status_code": row.get("verify_status_code"),
                    "structured_payload_json": row.get("structured_payload_json"),
                    "remark": row.get("remark"),
                    "created_at": row.get("created_at") or now,
                    "updated_at": row.get("updated_at") or now,
                },
            )

    if _has_table("ship_name_history"):
        for row in bind.execute(sa.text("select * from ship_name_history")).mappings().all():
            _insert(
                "vessel_name_history",
                {
                    "vessel_profile_id": row.get("ship_id"),
                    "ship_name": row.get("ship_name"),
                    "start_date": row.get("start_date"),
                    "end_date": row.get("end_date"),
                    "source_type_code": row.get("source_type_code"),
                    "created_at": row.get("created_at") or now,
                },
            )

    if _has_table("ship_mmsi_history"):
        for row in bind.execute(sa.text("select * from ship_mmsi_history")).mappings().all():
            _insert(
                "vessel_identifier_history",
                {
                    "vessel_profile_id": row.get("ship_id"),
                    "identifier_type_code": "MMSI",
                    "identifier_value": _mmsi(row.get("mmsi"), row.get("ship_id")),
                    "start_date": row.get("start_date"),
                    "end_date": row.get("end_date"),
                    "source_type_code": row.get("source_type_code"),
                    "created_at": row.get("created_at") or now,
                },
            )

    bind.execute(
        sa.text(
            """
            insert into code_sequence (
                biz_code, biz_name, target_table, target_column, prefix, date_format,
                separator, current_value, value_length, step, reset_rule, is_enabled,
                remark, created_at, updated_at
            )
            select
                'VESSEL_PROFILE_CODE', '船舶档案编码', 'vessel_profile', 'vessel_profile_code',
                'VP', null, null, coalesce(max(id), 0), 6, 1, 'NONE', 1,
                '船舶重构档案编码', :now, :now
            from vessel_profile
            where not exists (select 1 from code_sequence where biz_code = 'VESSEL_PROFILE_CODE')
            """
        ),
        {"now": now},
    )


def upgrade() -> None:
    bind = op.get_bind()
    for table in VESSEL_TABLES:
        table.create(bind, checkfirst=True)
    _clear_vessel_tables()
    _backfill_from_ship_tables()
    for table_name in OLD_SHIP_TABLES:
        if _has_table(table_name):
            op.drop_table(table_name)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(VESSEL_TABLES):
        table.drop(bind, checkfirst=True)
    bind.execute(sa.text("delete from code_sequence where biz_code = 'VESSEL_PROFILE_CODE'"))
