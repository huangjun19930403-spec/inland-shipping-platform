"""vessel compliance risk and ocr workbench

Revision ID: 0028_vessel_compliance_risk_ocr_workbench
Revises: 0027_vessel_profile_summary
Create Date: 2026-05-09 18:00:00.000000

"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import BigInteger


@compiles(BigInteger, "sqlite")
def _compile_bigint_sqlite(_type, _compiler, **_kw):
    return "INTEGER"


revision: str = "0028_vessel_compliance_risk_ocr_workbench"
down_revision: Union[str, None] = "0027_vessel_profile_summary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _has_index(table: str, index_name: str) -> bool:
    if not _has_table(table):
        return False
    return index_name in {item["name"] for item in inspect(op.get_bind()).get_indexes(table)}


def _create_index_if_missing(table: str, index_name: str, columns: list[str], *, unique: bool = False) -> None:
    if _has_table(table) and not _has_index(table, index_name):
        op.create_index(index_name, table, columns, unique=unique)


def _drop_index_if_exists(table: str, index_name: str) -> None:
    if _has_index(table, index_name):
        op.drop_index(index_name, table_name=table)


def _seed_default_rules() -> None:
    table = sa.table(
        "vessel_certificate_requirement_rule",
        sa.column("rule_code", sa.String),
        sa.column("rule_name", sa.String),
        sa.column("scope_type_code", sa.String),
        sa.column("required_certificate_type_code", sa.String),
        sa.column("risk_type_code", sa.String),
        sa.column("risk_level_when_missing", sa.String),
        sa.column("status_code", sa.String),
        sa.column("condition_json", sa.JSON),
        sa.column("evidence_requirements_json", sa.JSON),
        sa.column("revision", sa.Integer),
        sa.column("remark", sa.String),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    now = datetime.utcnow()
    rules = [
        ("REQ_VESSEL_OWNERSHIP_CERT_GLOBAL", "必需船舶所有权证书", "VESSEL_OWNERSHIP_CERT"),
        ("REQ_VESSEL_NATIONALITY_CERT_GLOBAL", "必需船舶国籍证书", "VESSEL_NATIONALITY_CERT"),
        ("REQ_VESSEL_OPERATION_CERT_GLOBAL", "必需船舶营业运输证", "VESSEL_OPERATION_CERT"),
        ("REQ_VESSEL_INSPECTION_BOOK_GLOBAL", "必需船检簿", "VESSEL_INSPECTION_BOOK"),
        ("REQ_VESSEL_SEAWORTHINESS_CERT_GLOBAL", "必需适航证", "VESSEL_SEAWORTHINESS_CERT"),
        ("REQ_VESSEL_AIS_CERT_GLOBAL", "必需船舶 AIS 证书", "VESSEL_AIS_CERT"),
    ]
    bind = op.get_bind()
    for rule_code, rule_name, cert_type in rules:
        exists = bind.execute(sa.text("select 1 from vessel_certificate_requirement_rule where rule_code = :code"), {"code": rule_code}).first()
        if exists:
            continue
        op.bulk_insert(
            table,
            [
                {
                    "rule_code": rule_code,
                    "rule_name": rule_name,
                    "scope_type_code": "GLOBAL",
                    "required_certificate_type_code": cert_type,
                    "risk_type_code": "CERTIFICATE_MISSING",
                    "risk_level_when_missing": "MEDIUM",
                    "status_code": "ACTIVE",
                    "condition_json": {"scope": "GLOBAL"},
                    "evidence_requirements_json": {
                        "verify_status_code": "VERIFIED",
                        "required_fields": ["certificate_no", "valid_to_or_long_term"],
                    },
                    "revision": 1,
                    "remark": "Round 5 default global vessel certificate requirement",
                    "created_at": now,
                    "updated_at": now,
                }
            ],
        )


def _dict_item(
    code: str,
    name: str,
    *,
    color: str | None = None,
    is_default: bool = False,
    sort_order: int = 0,
) -> dict[str, object]:
    return {
        "item_code": code,
        "item_name": name,
        "item_name_en": code,
        "color": color,
        "description": None,
        "is_default": is_default,
        "is_system": True,
        "status": 1,
        "sort_order": sort_order,
    }


def _seed_round5_dicts() -> None:
    if not (_has_table("std_dict") and _has_table("std_dict_item")):
        return
    dicts = [
        {
            "dict_code": "VESSEL_RISK_SIGNAL_TYPE",
            "dict_name": "船舶风险信号类型",
            "items": [
                _dict_item("CERTIFICATE_MISSING", "证书缺失", color="warning", sort_order=10),
                _dict_item("CERTIFICATE_EXPIRED", "证书过期", color="danger", sort_order=20),
                _dict_item("CERTIFICATE_EXPIRING", "证书临期", color="warning", sort_order=30),
                _dict_item("SUBJECT_MISMATCH", "主体不一致", color="danger", sort_order=40),
                _dict_item("OPERATOR_QUALIFICATION_UNKNOWN", "经营资质不明", color="info", sort_order=50),
                _dict_item("CONTROLLER_UNKNOWN", "实际控制人不明", color="info", sort_order=60),
                _dict_item("AFFILIATION_UNCLEAR", "挂靠关系不清", color="warning", sort_order=70),
                _dict_item("CARGO_ROUTE_SHIPTYPE_UNCERTAIN", "货类航区船型适配不可计算", color="info", sort_order=80),
                _dict_item("OCR_LOW_CONFIDENCE", "OCR 低置信", color="warning", sort_order=90),
            ],
        },
        {
            "dict_code": "VESSEL_RISK_SIGNAL_STATUS",
            "dict_name": "船舶风险信号状态",
            "items": [
                _dict_item("OPEN", "待处理", color="warning", is_default=True, sort_order=10),
                _dict_item("IN_REVIEW", "复核中", color="primary", sort_order=20),
                _dict_item("EVIDENCE_ADDED", "已补证", color="primary", sort_order=30),
                _dict_item("MITIGATED", "已缓解", color="success", sort_order=40),
                _dict_item("CLOSED", "已关闭", color="info", sort_order=50),
                _dict_item("FALSE_POSITIVE", "误报", color="info", sort_order=60),
            ],
        },
        {
            "dict_code": "VESSEL_REQUIREMENT_RULE_STATUS",
            "dict_name": "船舶合规规则状态",
            "items": [
                _dict_item("DRAFT", "草稿", color="info", sort_order=10),
                _dict_item("ACTIVE", "启用", color="success", is_default=True, sort_order=20),
                _dict_item("INACTIVE", "停用", color="info", sort_order=30),
                _dict_item("VOIDED", "作废", color="info", sort_order=40),
            ],
        },
        {
            "dict_code": "VESSEL_RULE_SCOPE_TYPE",
            "dict_name": "船舶合规规则适用范围",
            "items": [
                _dict_item("GLOBAL", "全局", color="primary", is_default=True, sort_order=10),
                _dict_item("SHIP_TYPE", "按船型", color="success", sort_order=20),
                _dict_item("CARGO_CATEGORY", "按货类", color="warning", sort_order=30),
                _dict_item("ROUTE_AREA", "按航区", color="warning", sort_order=40),
            ],
        },
        {
            "dict_code": "VESSEL_CONTROLLER_ROLE",
            "dict_name": "船舶实际控制人证据角色",
            "items": [
                _dict_item("DATA_MAINTAINER", "资料维护主体", sort_order=10),
                _dict_item("OPERATING_CONTACT", "运营联系人", sort_order=20),
                _dict_item("EVIDENCE_PROVIDER", "证据提供方", is_default=True, sort_order=30),
                _dict_item("HISTORICAL_CONTACT", "历史联系人", sort_order=40),
            ],
        },
        {
            "dict_code": "VESSEL_AFFILIATION_TYPE",
            "dict_name": "船舶挂靠关系类型",
            "items": [
                _dict_item("OWNER_OPERATOR", "自有自营", color="success", sort_order=10),
                _dict_item("AUTHORIZED_OPERATION", "授权经营", color="primary", sort_order=20),
                _dict_item("AFFILIATED_COMPANY", "挂靠公司", color="warning", sort_order=30),
                _dict_item("EVIDENCE_ONLY", "仅有证据", color="info", sort_order=40),
                _dict_item("UNKNOWN", "未知", color="info", is_default=True, sort_order=50),
            ],
        },
        {
            "dict_code": "VESSEL_CHANGE_EVENT_TYPE",
            "dict_name": "船舶变更事件类型",
            "items": [
                _dict_item("REFRESH_COMPLIANCE_RISK", "刷新合规风险", sort_order=500),
                _dict_item("UPDATE_RISK_SIGNAL", "处理风险信号", sort_order=501),
                _dict_item("CREATE_CONTROLLER_EVIDENCE", "新增实际控制人证据", sort_order=502),
                _dict_item("UPDATE_CONTROLLER_EVIDENCE", "更新实际控制人证据", sort_order=503),
                _dict_item("VOID_CONTROLLER_EVIDENCE", "作废实际控制人证据", sort_order=504),
                _dict_item("CREATE_AFFILIATION_EVIDENCE", "新增挂靠关系证据", sort_order=505),
                _dict_item("UPDATE_AFFILIATION_EVIDENCE", "更新挂靠关系证据", sort_order=506),
                _dict_item("VOID_AFFILIATION_EVIDENCE", "作废挂靠关系证据", sort_order=507),
            ],
        },
    ]
    dict_table = sa.table(
        "std_dict",
        sa.column("dict_code", sa.String),
        sa.column("dict_name", sa.String),
        sa.column("dict_name_en", sa.String),
        sa.column("description", sa.String),
        sa.column("is_system", sa.Boolean),
        sa.column("status", sa.Integer),
        sa.column("sort_order", sa.Integer),
    )
    item_table = sa.table(
        "std_dict_item",
        sa.column("dict_id", BigInteger),
        sa.column("item_code", sa.String),
        sa.column("item_name", sa.String),
        sa.column("item_name_en", sa.String),
        sa.column("color", sa.String),
        sa.column("description", sa.String),
        sa.column("is_default", sa.Boolean),
        sa.column("is_system", sa.Boolean),
        sa.column("status", sa.Integer),
        sa.column("sort_order", sa.Integer),
    )
    bind = op.get_bind()
    for sort_order, payload in enumerate(dicts, start=300):
        dict_code = payload["dict_code"]
        row = bind.execute(sa.text("select id from std_dict where dict_code = :code"), {"code": dict_code}).first()
        if row is None:
            op.bulk_insert(
                dict_table,
                [
                    {
                        "dict_code": dict_code,
                        "dict_name": payload["dict_name"],
                        "dict_name_en": dict_code,
                        "description": None,
                        "is_system": True,
                        "status": 1,
                        "sort_order": sort_order,
                    }
                ],
            )
            row = bind.execute(sa.text("select id from std_dict where dict_code = :code"), {"code": dict_code}).first()
        else:
            bind.execute(
                sa.text(
                    "update std_dict set dict_name = :name, is_system = 1, status = 1 "
                    "where dict_code = :code"
                ),
                {"name": payload["dict_name"], "code": dict_code},
            )
        if row is None:
            continue
        dict_id = row[0]
        for item in payload["items"]:
            exists = bind.execute(
                sa.text("select 1 from std_dict_item where dict_id = :dict_id and item_code = :item_code"),
                {"dict_id": dict_id, "item_code": item["item_code"]},
            ).first()
            item_payload = {"dict_id": dict_id, **item}
            if exists is None:
                op.bulk_insert(item_table, [item_payload])
            else:
                bind.execute(
                    sa.text(
                        "update std_dict_item set item_name = :item_name, item_name_en = :item_name_en, "
                        "color = :color, description = :description, is_default = :is_default, "
                        "is_system = 1, status = 1, sort_order = :sort_order "
                        "where dict_id = :dict_id and item_code = :item_code"
                    ),
                    item_payload,
                )


def upgrade() -> None:
    if not _has_table("vessel_certificate_requirement_rule"):
        op.create_table(
            "vessel_certificate_requirement_rule",
            sa.Column("id", BigInteger(), autoincrement=True, nullable=False),
            sa.Column("rule_code", sa.String(length=96), nullable=False),
            sa.Column("rule_name", sa.String(length=128), nullable=False),
            sa.Column("scope_type_code", sa.String(length=64), nullable=False, server_default="GLOBAL"),
            sa.Column("ship_type_code", sa.String(length=64), nullable=True),
            sa.Column("cargo_category_code", sa.String(length=64), nullable=True),
            sa.Column("route_area_code", sa.String(length=64), nullable=True),
            sa.Column("required_certificate_type_code", sa.String(length=64), nullable=False),
            sa.Column("risk_type_code", sa.String(length=64), nullable=False, server_default="CERTIFICATE_MISSING"),
            sa.Column("risk_level_when_missing", sa.String(length=32), nullable=False, server_default="MEDIUM"),
            sa.Column("status_code", sa.String(length=32), nullable=False, server_default="ACTIVE"),
            sa.Column("condition_json", sa.JSON(), nullable=True),
            sa.Column("evidence_requirements_json", sa.JSON(), nullable=True),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("remark", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("rule_code", name="uq_vessel_certificate_requirement_rule_code"),
        )
    _create_index_if_missing("vessel_certificate_requirement_rule", "idx_vessel_cert_req_rule_code", ["rule_code"], unique=True)
    _create_index_if_missing("vessel_certificate_requirement_rule", "idx_vessel_cert_req_rule_scope", ["scope_type_code"])
    _create_index_if_missing("vessel_certificate_requirement_rule", "idx_vessel_cert_req_rule_cert", ["required_certificate_type_code"])
    _create_index_if_missing("vessel_certificate_requirement_rule", "idx_vessel_cert_req_rule_status", ["status_code"])

    if not _has_table("vessel_risk_signal"):
        op.create_table(
            "vessel_risk_signal",
            sa.Column("id", BigInteger(), autoincrement=True, nullable=False),
            sa.Column("vessel_profile_id", BigInteger(), nullable=False),
            sa.Column("risk_type_code", sa.String(length=64), nullable=False),
            sa.Column("risk_level", sa.String(length=32), nullable=False, server_default="UNKNOWN"),
            sa.Column("rule_code", sa.String(length=96), nullable=True),
            sa.Column("status_code", sa.String(length=32), nullable=False, server_default="OPEN"),
            sa.Column("confidence_level", sa.String(length=32), nullable=False, server_default="UNKNOWN"),
            sa.Column("fingerprint", sa.String(length=64), nullable=False),
            sa.Column("evidence_json", sa.JSON(), nullable=True),
            sa.Column("source_trace_json", sa.JSON(), nullable=True),
            sa.Column("uncertainty_notes_json", sa.JSON(), nullable=True),
            sa.Column("first_detected_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("last_detected_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.Column("resolved_by", BigInteger(), nullable=True),
            sa.Column("resolution_reason", sa.Text(), nullable=True),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["vessel_profile_id"], ["vessel_profile.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("vessel_risk_signal", "idx_vessel_risk_signal_profile_status", ["vessel_profile_id", "status_code"])
    _create_index_if_missing("vessel_risk_signal", "idx_vessel_risk_signal_type_status", ["risk_type_code", "status_code"])
    _create_index_if_missing("vessel_risk_signal", "idx_vessel_risk_signal_level", ["risk_level"])
    _create_index_if_missing("vessel_risk_signal", "idx_vessel_risk_signal_fingerprint", ["fingerprint"])
    _create_index_if_missing("vessel_risk_signal", "idx_vessel_risk_signal_rule", ["rule_code"])

    if not _has_table("vessel_controller_evidence"):
        op.create_table(
            "vessel_controller_evidence",
            sa.Column("id", BigInteger(), autoincrement=True, nullable=False),
            sa.Column("vessel_profile_id", BigInteger(), nullable=False),
            sa.Column("party_name", sa.String(length=128), nullable=False),
            sa.Column("controller_role_code", sa.String(length=64), nullable=False, server_default="EVIDENCE_PROVIDER"),
            sa.Column("confidence_level", sa.String(length=32), nullable=False, server_default="UNKNOWN"),
            sa.Column("source_type_code", sa.String(length=64), nullable=False, server_default="MANUAL"),
            sa.Column("source_trace_id", sa.String(length=128), nullable=True),
            sa.Column("evidence_summary", sa.String(length=500), nullable=True),
            sa.Column("evidence_json", sa.JSON(), nullable=True),
            sa.Column("effective_from", sa.Date(), nullable=True),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("status_code", sa.String(length=32), nullable=False, server_default="ACTIVE"),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("voided_at", sa.DateTime(), nullable=True),
            sa.Column("voided_by", BigInteger(), nullable=True),
            sa.Column("void_reason", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["vessel_profile_id"], ["vessel_profile.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("vessel_controller_evidence", "idx_vessel_controller_evidence_profile", ["vessel_profile_id"])
    _create_index_if_missing("vessel_controller_evidence", "idx_vessel_controller_evidence_status", ["status_code"])

    if not _has_table("vessel_affiliation_evidence"):
        op.create_table(
            "vessel_affiliation_evidence",
            sa.Column("id", BigInteger(), autoincrement=True, nullable=False),
            sa.Column("vessel_profile_id", BigInteger(), nullable=False),
            sa.Column("owner_period_id", BigInteger(), nullable=True),
            sa.Column("operator_period_id", BigInteger(), nullable=True),
            sa.Column("affiliation_type_code", sa.String(length=64), nullable=False, server_default="UNKNOWN"),
            sa.Column("subject_name", sa.String(length=128), nullable=True),
            sa.Column("counterparty_name", sa.String(length=128), nullable=True),
            sa.Column("confidence_level", sa.String(length=32), nullable=False, server_default="UNKNOWN"),
            sa.Column("source_type_code", sa.String(length=64), nullable=False, server_default="MANUAL"),
            sa.Column("source_trace_id", sa.String(length=128), nullable=True),
            sa.Column("evidence_summary", sa.String(length=500), nullable=True),
            sa.Column("evidence_json", sa.JSON(), nullable=True),
            sa.Column("effective_from", sa.Date(), nullable=True),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("status_code", sa.String(length=32), nullable=False, server_default="ACTIVE"),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("voided_at", sa.DateTime(), nullable=True),
            sa.Column("voided_by", BigInteger(), nullable=True),
            sa.Column("void_reason", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["vessel_profile_id"], ["vessel_profile.id"]),
            sa.ForeignKeyConstraint(["owner_period_id"], ["vessel_owner_period.id"]),
            sa.ForeignKeyConstraint(["operator_period_id"], ["vessel_operator_period.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("vessel_affiliation_evidence", "idx_vessel_affiliation_evidence_profile", ["vessel_profile_id"])
    _create_index_if_missing("vessel_affiliation_evidence", "idx_vessel_affiliation_evidence_status", ["status_code"])

    _seed_default_rules()
    _seed_round5_dicts()


def downgrade() -> None:
    if _has_table("vessel_affiliation_evidence"):
        _drop_index_if_exists("vessel_affiliation_evidence", "idx_vessel_affiliation_evidence_status")
        _drop_index_if_exists("vessel_affiliation_evidence", "idx_vessel_affiliation_evidence_profile")
        op.drop_table("vessel_affiliation_evidence")
    if _has_table("vessel_controller_evidence"):
        _drop_index_if_exists("vessel_controller_evidence", "idx_vessel_controller_evidence_status")
        _drop_index_if_exists("vessel_controller_evidence", "idx_vessel_controller_evidence_profile")
        op.drop_table("vessel_controller_evidence")
    if _has_table("vessel_risk_signal"):
        for index_name in [
            "idx_vessel_risk_signal_rule",
            "idx_vessel_risk_signal_fingerprint",
            "idx_vessel_risk_signal_level",
            "idx_vessel_risk_signal_type_status",
            "idx_vessel_risk_signal_profile_status",
        ]:
            _drop_index_if_exists("vessel_risk_signal", index_name)
        op.drop_table("vessel_risk_signal")
    if _has_table("vessel_certificate_requirement_rule"):
        for index_name in [
            "idx_vessel_cert_req_rule_status",
            "idx_vessel_cert_req_rule_cert",
            "idx_vessel_cert_req_rule_scope",
            "idx_vessel_cert_req_rule_code",
        ]:
            _drop_index_if_exists("vessel_certificate_requirement_rule", index_name)
        op.drop_table("vessel_certificate_requirement_rule")
