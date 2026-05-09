"""vessel audit governance loop round10

Revision ID: 0034_vessel_audit_governance_loop_round10
Revises: 0033_vessel_analysis_fact_round9
Create Date: 2026-05-09
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import BigInteger


@compiles(BigInteger, "sqlite")
def _compile_bigint_sqlite(_type, _compiler, **_kw):
    return "INTEGER"


revision: str = "0034_vessel_audit_governance_loop_round10"
down_revision: Union[str, None] = "0033_vessel_analysis_fact_round9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _columns(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {item["name"] for item in inspect(op.get_bind()).get_columns(table)}


def _has_index(table: str, index_name: str) -> bool:
    if not _has_table(table):
        return False
    return index_name in {item["name"] for item in inspect(op.get_bind()).get_indexes(table)}


def _create_index_if_missing(table: str, index_name: str, columns: list[str], **kw) -> None:
    if _has_table(table) and not _has_index(table, index_name):
        op.create_index(index_name, table, columns, **kw)


def _drop_index_if_exists(table: str, index_name: str) -> None:
    if _has_index(table, index_name):
        op.drop_index(index_name, table_name=table)


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if _has_table(table) and column.name not in _columns(table):
        op.add_column(table, column)


def _drop_column_if_exists(table: str, column_name: str) -> None:
    if _has_table(table) and column_name in _columns(table):
        op.drop_column(table, column_name)


def _dict_item(code: str, name: str, *, color: str | None = None, is_default: bool = False, sort_order: int = 0) -> dict[str, object]:
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


def _seed_dict(dict_code: str, dict_name: str, items: list[dict[str, object]], sort_order: int) -> None:
    if not (_has_table("std_dict") and _has_table("std_dict_item")):
        return
    bind = op.get_bind()
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
    row = bind.execute(sa.text("select id from std_dict where dict_code = :code"), {"code": dict_code}).first()
    if row is None:
        op.bulk_insert(
            dict_table,
            [{
                "dict_code": dict_code,
                "dict_name": dict_name,
                "dict_name_en": dict_code,
                "description": None,
                "is_system": True,
                "status": 1,
                "sort_order": sort_order,
            }],
        )
        row = bind.execute(sa.text("select id from std_dict where dict_code = :code"), {"code": dict_code}).first()
    else:
        bind.execute(
            sa.text("update std_dict set dict_name = :name, is_system = 1, status = 1 where dict_code = :code"),
            {"name": dict_name, "code": dict_code},
        )
    if row is None:
        return
    dict_id = row[0]
    for item in items:
        exists = bind.execute(
            sa.text("select 1 from std_dict_item where dict_id = :dict_id and item_code = :item_code"),
            {"dict_id": dict_id, "item_code": item["item_code"]},
        ).first()
        payload = {**item, "dict_id": dict_id}
        if exists:
            bind.execute(
                sa.text(
                    """
                    update std_dict_item
                    set item_name = :item_name,
                        item_name_en = :item_name_en,
                        color = :color,
                        is_default = :is_default,
                        is_system = 1,
                        status = 1,
                        sort_order = :sort_order
                    where dict_id = :dict_id and item_code = :item_code
                    """
                ),
                payload,
            )
        else:
            op.bulk_insert(item_table, [payload])


def _seed_round10_dicts() -> None:
    _seed_dict(
        "VESSEL_RISK_SIGNAL_TYPE",
        "船舶风险信号类型",
        [
            _dict_item("CERTIFICATE_MISSING", "证书缺失", color="warning", sort_order=10),
            _dict_item("CERTIFICATE_EXPIRED", "证书过期", color="danger", sort_order=20),
            _dict_item("CERTIFICATE_EXPIRING", "证书临期", color="warning", sort_order=30),
            _dict_item("SUBJECT_MISMATCH", "主体不一致", color="danger", sort_order=40),
            _dict_item("OPERATOR_QUALIFICATION_UNKNOWN", "经营资质不明", color="info", sort_order=50),
            _dict_item("CONTROLLER_UNKNOWN", "实际控制人不明", color="info", sort_order=60),
            _dict_item("AFFILIATION_UNCLEAR", "挂靠关系不清", color="warning", sort_order=70),
            _dict_item("BLACKLIST_SIGNAL", "黑名单/观察名单信号", color="danger", sort_order=75),
            _dict_item("CARGO_ROUTE_SHIPTYPE_UNCERTAIN", "货类航区船型适配不可计算", color="info", sort_order=80),
            _dict_item("OCR_LOW_CONFIDENCE", "OCR 低置信", color="warning", sort_order=90),
        ],
        466,
    )
    _seed_dict(
        "VESSEL_GOVERNANCE_TASK_TYPE",
        "船舶治理任务类型",
        [
            _dict_item("QUALITY_ISSUE", "质量问题", color="warning", sort_order=10),
            _dict_item("RISK_REVIEW", "风险复核", color="danger", sort_order=20),
            _dict_item("AIS_UNMATCHED", "AIS 未匹配", color="warning", sort_order=30),
            _dict_item("OCR_LOW_CONFIDENCE", "OCR 低置信", color="warning", sort_order=40),
            _dict_item("CANDIDATE_REVIEW", "候选标注复核", color="info", sort_order=50),
            _dict_item("CONTROLLER_AFFILIATION", "控制人/挂靠证据", color="primary", sort_order=60),
            _dict_item("BLACKLIST_REVIEW", "黑名单/观察名单复核", color="danger", sort_order=70),
        ],
        480,
    )
    _seed_dict(
        "VESSEL_GOVERNANCE_TASK_STATUS",
        "船舶治理任务状态",
        [
            _dict_item("OPEN", "待处理", color="warning", is_default=True, sort_order=10),
            _dict_item("ASSIGNED", "已指派", color="primary", sort_order=20),
            _dict_item("IN_PROGRESS", "处理中", color="primary", sort_order=30),
            _dict_item("RESOLVED", "已解决", color="success", sort_order=40),
            _dict_item("CANNOT_RESOLVE", "无法解决", color="info", sort_order=50),
            _dict_item("VOIDED", "已作废", color="info", sort_order=60),
            _dict_item("REOPENED", "已重开", color="warning", sort_order=70),
        ],
        481,
    )
    _seed_dict(
        "VESSEL_GOVERNANCE_PRIORITY",
        "船舶治理优先级",
        [
            _dict_item("URGENT", "紧急", color="danger", sort_order=10),
            _dict_item("HIGH", "高", color="warning", sort_order=20),
            _dict_item("MEDIUM", "中", color="primary", is_default=True, sort_order=30),
            _dict_item("LOW", "低", color="info", sort_order=40),
        ],
        482,
    )
    _seed_dict(
        "VESSEL_EVIDENCE_VERIFIED_STATUS",
        "船舶证据审核状态",
        [
            _dict_item("DRAFT", "草稿", color="info", is_default=True, sort_order=10),
            _dict_item("PENDING", "待审核", color="warning", sort_order=20),
            _dict_item("APPROVED", "已通过", color="success", sort_order=30),
            _dict_item("REJECTED", "已驳回", color="danger", sort_order=40),
            _dict_item("CHANGE_REQUESTED", "需修改", color="warning", sort_order=50),
        ],
        483,
    )
    _seed_dict(
        "VESSEL_BLACKLIST_LIST_TYPE",
        "船舶名单类型",
        [
            _dict_item("BLACKLIST", "黑名单", color="danger", sort_order=10),
            _dict_item("WATCHLIST", "观察名单", color="warning", is_default=True, sort_order=20),
        ],
        484,
    )
    _seed_dict(
        "VESSEL_BLACKLIST_SIGNAL_TYPE",
        "船舶名单信号类型",
        [
            _dict_item("SANCTION", "制裁/禁入", color="danger", sort_order=10),
            _dict_item("FRAUD_RISK", "欺诈风险", color="danger", sort_order=20),
            _dict_item("SUBJECT_RISK", "主体风险", color="warning", sort_order=30),
            _dict_item("CERTIFICATE_RISK", "证照风险", color="warning", sort_order=40),
            _dict_item("MANUAL_RISK", "人工风险", color="primary", sort_order=50),
            _dict_item("OTHER", "其他", color="info", sort_order=60),
        ],
        485,
    )
    _seed_dict(
        "VESSEL_BLACKLIST_SIGNAL_STATUS",
        "船舶名单信号状态",
        [
            _dict_item("ACTIVE", "生效", color="danger", is_default=True, sort_order=10),
            _dict_item("EXPIRED", "已过期", color="info", sort_order=20),
            _dict_item("RESOLVED", "已解除", color="success", sort_order=30),
            _dict_item("VOIDED", "已作废", color="info", sort_order=40),
        ],
        486,
    )
    _seed_dict(
        "AUDIT_OBJECT_TYPE",
        "审核对象类型",
        [
            _dict_item("TRANSPORT_NODE", "运输节点", color="primary", sort_order=10),
            _dict_item("REGION", "业务区域", color="success", sort_order=20),
            _dict_item("COMMODITY_STANDARD", "标准货品", color="warning", sort_order=30),
            _dict_item("VESSEL_PROFILE", "船舶档案", color="info", sort_order=40),
            _dict_item("FREIGHT", "正式货源", color="danger", sort_order=50),
            _dict_item("VESSEL_RELATION", "船舶主关系", color="primary", sort_order=60),
            _dict_item("VESSEL_CERTIFICATE", "船舶证书", color="warning", sort_order=70),
            _dict_item("VESSEL_OCR_ADOPTION", "OCR 采纳", color="warning", sort_order=80),
            _dict_item("VESSEL_CONTROLLER_EVIDENCE", "实际控制人证据", color="primary", sort_order=90),
            _dict_item("VESSEL_AFFILIATION_EVIDENCE", "挂靠关系证据", color="primary", sort_order=100),
            _dict_item("VESSEL_RISK_REVIEW", "船舶风险复核", color="danger", sort_order=110),
            _dict_item("VESSEL_BLACKLIST_SIGNAL", "船舶名单信号", color="danger", sort_order=120),
        ],
        440,
    )


def upgrade() -> None:
    if not _has_table("vessel_governance_task"):
        op.create_table(
            "vessel_governance_task",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("task_no", sa.String(32), nullable=False, unique=True),
            sa.Column("task_type_code", sa.String(64), nullable=False),
            sa.Column("priority_code", sa.String(32), nullable=False, server_default="MEDIUM"),
            sa.Column("status_code", sa.String(32), nullable=False, server_default="OPEN"),
            sa.Column("vessel_profile_id", BigInteger(), sa.ForeignKey("vessel_profile.id"), nullable=True),
            sa.Column("source_object_type", sa.String(64), nullable=False),
            sa.Column("source_object_id", sa.String(64), nullable=False),
            sa.Column("source_status_code", sa.String(64), nullable=True),
            sa.Column("source_fingerprint", sa.String(128), nullable=True),
            sa.Column("fingerprint", sa.String(128), nullable=False),
            sa.Column("title", sa.String(256), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("evidence_summary", sa.Text(), nullable=True),
            sa.Column("source_trace_json", sa.JSON(), nullable=True),
            sa.Column("impact_summary_json", sa.JSON(), nullable=True),
            sa.Column("confidence_level", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("coverage_rate", sa.Numeric(5, 2), nullable=True),
            sa.Column("assigned_to", BigInteger(), nullable=True),
            sa.Column("assigned_at", sa.DateTime(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.Column("resolved_by", BigInteger(), nullable=True),
            sa.Column("resolution_reason", sa.Text(), nullable=True),
            sa.Column("resolution_evidence_json", sa.JSON(), nullable=True),
            sa.Column("first_seen_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
            sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reopen_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
    _create_index_if_missing("vessel_governance_task", "ix_vessel_governance_task_status_code", ["status_code"])
    _create_index_if_missing("vessel_governance_task", "ix_vessel_governance_task_type", ["task_type_code"])
    _create_index_if_missing("vessel_governance_task", "ix_vessel_governance_task_priority", ["priority_code"])
    _create_index_if_missing("vessel_governance_task", "ix_vessel_governance_task_vessel", ["vessel_profile_id"])
    _create_index_if_missing("vessel_governance_task", "ix_vessel_governance_task_source", ["source_object_type", "source_object_id"])
    _create_index_if_missing("vessel_governance_task", "ix_vessel_governance_task_last_seen", ["last_seen_at"])
    _create_index_if_missing(
        "vessel_governance_task",
        "uq_vessel_governance_task_active_fingerprint",
        ["fingerprint"],
        unique=True,
        sqlite_where=sa.text("status_code IN ('OPEN', 'ASSIGNED', 'IN_PROGRESS', 'REOPENED')"),
        postgresql_where=sa.text("status_code IN ('OPEN', 'ASSIGNED', 'IN_PROGRESS', 'REOPENED')"),
    )

    if not _has_table("vessel_risk_review"):
        op.create_table(
            "vessel_risk_review",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("vessel_profile_id", BigInteger(), sa.ForeignKey("vessel_profile.id"), nullable=False),
            sa.Column("risk_signal_id", BigInteger(), sa.ForeignKey("vessel_risk_signal.id"), nullable=True),
            sa.Column("governance_task_id", BigInteger(), sa.ForeignKey("vessel_governance_task.id"), nullable=True),
            sa.Column("review_action_code", sa.String(64), nullable=False),
            sa.Column("from_status_code", sa.String(64), nullable=True),
            sa.Column("to_status_code", sa.String(64), nullable=True),
            sa.Column("risk_level_before", sa.String(32), nullable=True),
            sa.Column("risk_level_after", sa.String(32), nullable=True),
            sa.Column("evidence_json", sa.JSON(), nullable=True),
            sa.Column("review_reason", sa.Text(), nullable=True),
            sa.Column("reviewed_by", BigInteger(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
    _create_index_if_missing("vessel_risk_review", "ix_vessel_risk_review_vessel", ["vessel_profile_id"])
    _create_index_if_missing("vessel_risk_review", "ix_vessel_risk_review_signal", ["risk_signal_id"])
    _create_index_if_missing("vessel_risk_review", "ix_vessel_risk_review_task", ["governance_task_id"])
    _create_index_if_missing("vessel_risk_review", "ix_vessel_risk_review_action", ["review_action_code"])

    if not _has_table("vessel_blacklist_signal"):
        op.create_table(
            "vessel_blacklist_signal",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("vessel_profile_id", BigInteger(), sa.ForeignKey("vessel_profile.id"), nullable=False),
            sa.Column("list_type_code", sa.String(32), nullable=False, server_default="WATCHLIST"),
            sa.Column("signal_type_code", sa.String(64), nullable=False),
            sa.Column("status_code", sa.String(32), nullable=False, server_default="ACTIVE"),
            sa.Column("risk_level", sa.String(32), nullable=False, server_default="HIGH"),
            sa.Column("confidence_level", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("source_type_code", sa.String(64), nullable=False, server_default="MANUAL"),
            sa.Column("source_trace_id", sa.String(128), nullable=True),
            sa.Column("evidence_summary", sa.Text(), nullable=True),
            sa.Column("evidence_json", sa.JSON(), nullable=True),
            sa.Column("effective_from", sa.Date(), nullable=True),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("voided_at", sa.DateTime(), nullable=True),
            sa.Column("voided_by", BigInteger(), nullable=True),
            sa.Column("void_reason", sa.Text(), nullable=True),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
    _create_index_if_missing("vessel_blacklist_signal", "ix_vessel_blacklist_signal_vessel", ["vessel_profile_id"])
    _create_index_if_missing("vessel_blacklist_signal", "ix_vessel_blacklist_signal_list_type", ["list_type_code"])
    _create_index_if_missing("vessel_blacklist_signal", "ix_vessel_blacklist_signal_type", ["signal_type_code"])
    _create_index_if_missing("vessel_blacklist_signal", "ix_vessel_blacklist_signal_status", ["status_code"])

    for table in ("vessel_controller_evidence", "vessel_affiliation_evidence"):
        _add_column_if_missing(table, sa.Column("verified_status_code", sa.String(32), nullable=False, server_default="DRAFT"))
        # SQLite cannot add a new foreign key constraint through ALTER TABLE.
        # Keep the ORM relationship and indexed id while preserving migration rollback safety.
        _add_column_if_missing(table, sa.Column("audit_task_id", BigInteger(), nullable=True))
        _add_column_if_missing(table, sa.Column("verified_at", sa.DateTime(), nullable=True))
        _add_column_if_missing(table, sa.Column("verified_by", BigInteger(), nullable=True))
        _create_index_if_missing(table, f"ix_{table}_verified_status_code", ["verified_status_code"])
        _create_index_if_missing(table, f"ix_{table}_audit_task_id", ["audit_task_id"])

    _seed_round10_dicts()


def downgrade() -> None:
    for table in ("vessel_controller_evidence", "vessel_affiliation_evidence"):
        _drop_index_if_exists(table, f"ix_{table}_audit_task_id")
        _drop_index_if_exists(table, f"ix_{table}_verified_status_code")
        _drop_column_if_exists(table, "verified_by")
        _drop_column_if_exists(table, "verified_at")
        _drop_column_if_exists(table, "audit_task_id")
        _drop_column_if_exists(table, "verified_status_code")

    for table, indexes in {
        "vessel_blacklist_signal": [
            "ix_vessel_blacklist_signal_status",
            "ix_vessel_blacklist_signal_type",
            "ix_vessel_blacklist_signal_list_type",
            "ix_vessel_blacklist_signal_vessel",
        ],
        "vessel_risk_review": [
            "ix_vessel_risk_review_action",
            "ix_vessel_risk_review_task",
            "ix_vessel_risk_review_signal",
            "ix_vessel_risk_review_vessel",
        ],
        "vessel_governance_task": [
            "uq_vessel_governance_task_active_fingerprint",
            "ix_vessel_governance_task_last_seen",
            "ix_vessel_governance_task_source",
            "ix_vessel_governance_task_vessel",
            "ix_vessel_governance_task_priority",
            "ix_vessel_governance_task_type",
            "ix_vessel_governance_task_status_code",
        ],
    }.items():
        for index_name in indexes:
            _drop_index_if_exists(table, index_name)
        if _has_table(table):
            op.drop_table(table)

    if _has_table("std_dict") and _has_table("std_dict_item"):
        bind = op.get_bind()
        new_dicts = [
            "VESSEL_GOVERNANCE_TASK_TYPE",
            "VESSEL_GOVERNANCE_TASK_STATUS",
            "VESSEL_GOVERNANCE_PRIORITY",
            "VESSEL_EVIDENCE_VERIFIED_STATUS",
            "VESSEL_BLACKLIST_LIST_TYPE",
            "VESSEL_BLACKLIST_SIGNAL_TYPE",
            "VESSEL_BLACKLIST_SIGNAL_STATUS",
        ]
        bind.execute(
            sa.text(
                "delete from std_dict_item where dict_id in (select id from std_dict where dict_code in :codes)"
            ).bindparams(sa.bindparam("codes", expanding=True)),
            {"codes": new_dicts},
        )
        bind.execute(
            sa.text("delete from std_dict where dict_code in :codes").bindparams(sa.bindparam("codes", expanding=True)),
            {"codes": new_dicts},
        )
        audit_items = [
            "VESSEL_RELATION",
            "VESSEL_CERTIFICATE",
            "VESSEL_OCR_ADOPTION",
            "VESSEL_CONTROLLER_EVIDENCE",
            "VESSEL_AFFILIATION_EVIDENCE",
            "VESSEL_RISK_REVIEW",
            "VESSEL_BLACKLIST_SIGNAL",
        ]
        bind.execute(
            sa.text(
                """
                delete from std_dict_item
                where item_code in :items
                  and dict_id in (select id from std_dict where dict_code = 'AUDIT_OBJECT_TYPE')
                """
            ).bindparams(sa.bindparam("items", expanding=True)),
            {"items": audit_items},
        )
        bind.execute(
            sa.text(
                """
                delete from std_dict_item
                where item_code = 'BLACKLIST_SIGNAL'
                  and dict_id in (select id from std_dict where dict_code = 'VESSEL_RISK_SIGNAL_TYPE')
                """
            )
        )
