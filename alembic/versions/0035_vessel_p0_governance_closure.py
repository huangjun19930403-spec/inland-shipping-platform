"""vessel p0 governance closure

Revision ID: 0035_vessel_p0_governance_closure
Revises: 0034_vessel_audit_governance_loop_round10
Create Date: 2026-05-10
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


revision: str = "0035_vessel_p0_governance_closure"
down_revision: Union[str, None] = "0034_vessel_audit_governance_loop_round10"
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


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if _has_table(table) and column.name not in _columns(table):
        op.add_column(table, column)


def _drop_column_if_exists(table: str, column_name: str) -> None:
    if _has_table(table) and column_name in _columns(table):
        op.drop_column(table, column_name)


def _create_index_if_missing(table: str, index_name: str, columns: list[str], **kw) -> None:
    if _has_table(table) and not _has_index(table, index_name):
        op.create_index(index_name, table, columns, **kw)


def _drop_index_if_exists(table: str, index_name: str) -> None:
    if _has_index(table, index_name):
        op.drop_index(index_name, table_name=table)


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


def _seed_dicts() -> None:
    _seed_dict(
        "VESSEL_RELATION_CONCLUSION_STATUS",
        "船舶主体关系结论状态",
        [
            _dict_item("CANDIDATE", "候选结论", color="primary", is_default=True, sort_order=10),
            _dict_item("CURRENT", "当前结论", color="success", sort_order=20),
            _dict_item("CONFLICTED", "证据冲突", color="danger", sort_order=30),
            _dict_item("STALE_NEEDS_REVIEW", "待复核", color="warning", sort_order=40),
            _dict_item("EXPIRED", "已过期", color="info", sort_order=50),
            _dict_item("VOIDED", "已作废", color="info", sort_order=60),
        ],
        487,
    )
    _seed_dict(
        "VESSEL_GOVERNANCE_SYNC_STATUS",
        "船舶治理同步状态",
        [
            _dict_item("RUNNING", "执行中", color="primary", sort_order=10),
            _dict_item("SUCCESS", "成功", color="success", is_default=True, sort_order=20),
            _dict_item("FAILED", "失败", color="danger", sort_order=30),
        ],
        488,
    )


def _create_conclusion_table(table_name: str, *, affiliation: bool = False) -> None:
    if _has_table(table_name):
        return
    columns = [
        sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("vessel_profile_id", BigInteger(), sa.ForeignKey("vessel_profile.id"), nullable=False),
        sa.Column("conclusion_status_code", sa.String(32), nullable=False, server_default="CANDIDATE"),
        sa.Column("confidence_level", sa.String(32), nullable=False, server_default="UNKNOWN"),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=True),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conflict_reason", sa.Text(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("confirmed_by", BigInteger(), nullable=True),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.Column("voided_by", BigInteger(), nullable=True),
        sa.Column("void_reason", sa.String(500), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    ]
    if affiliation:
        columns[3:3] = [
            sa.Column("affiliation_type_code", sa.String(64), nullable=False, server_default="UNKNOWN"),
            sa.Column("subject_name", sa.String(128), nullable=True),
            sa.Column("counterparty_name", sa.String(128), nullable=True),
        ]
    else:
        columns[3:3] = [
            sa.Column("party_name", sa.String(128), nullable=False),
            sa.Column("controller_role_code", sa.String(64), nullable=False, server_default="ACTUAL_CONTROLLER"),
        ]
    op.create_table(table_name, *columns)


def upgrade() -> None:
    if not _has_table("vessel_governance_sync_batch"):
        op.create_table(
            "vessel_governance_sync_batch",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("batch_no", sa.String(40), nullable=False, unique=True),
            sa.Column("trigger_type_code", sa.String(32), nullable=False, server_default="MANUAL"),
            sa.Column("triggered_by", BigInteger(), nullable=True),
            sa.Column("status_code", sa.String(32), nullable=False, server_default="RUNNING"),
            sa.Column("source_rules_json", sa.JSON(), nullable=True),
            sa.Column("rule_result_json", sa.JSON(), nullable=True),
            sa.Column("affected_scope_json", sa.JSON(), nullable=True),
            sa.Column("touched_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_task_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reopened_task_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
    _create_index_if_missing("vessel_governance_sync_batch", "ix_vessel_governance_sync_batch_status", ["status_code"])
    _create_index_if_missing("vessel_governance_sync_batch", "ix_vessel_governance_sync_batch_trigger", ["trigger_type_code"])
    _create_index_if_missing("vessel_governance_sync_batch", "ix_vessel_governance_sync_batch_user", ["triggered_by"])

    for column in (
        sa.Column("source_batch_id", BigInteger(), sa.ForeignKey("vessel_governance_sync_batch.id"), nullable=True),
        sa.Column("source_rule_code", sa.String(96), nullable=True),
        sa.Column("generation_reason_json", sa.JSON(), nullable=True),
    ):
        _add_column_if_missing("vessel_governance_task", column)
    _create_index_if_missing("vessel_governance_task", "ix_vessel_governance_task_batch", ["source_batch_id"])
    _create_index_if_missing("vessel_governance_task", "ix_vessel_governance_task_rule", ["source_rule_code"])

    for column in (
        sa.Column("last_rechecked_at", sa.DateTime(), nullable=True),
        sa.Column("last_recheck_status_code", sa.String(32), nullable=True),
        sa.Column("last_recheck_message", sa.Text(), nullable=True),
    ):
        _add_column_if_missing("vessel_data_quality_issue", column)

    _create_conclusion_table("vessel_controller_conclusion", affiliation=False)
    _create_index_if_missing("vessel_controller_conclusion", "ix_vessel_controller_conclusion_vessel", ["vessel_profile_id"])
    _create_index_if_missing("vessel_controller_conclusion", "ix_vessel_controller_conclusion_status", ["conclusion_status_code"])
    _create_index_if_missing(
        "vessel_controller_conclusion",
        "uq_vessel_controller_conclusion_current",
        ["vessel_profile_id"],
        unique=True,
        sqlite_where=sa.text("conclusion_status_code = 'CURRENT'"),
        postgresql_where=sa.text("conclusion_status_code = 'CURRENT'"),
    )

    _create_conclusion_table("vessel_affiliation_conclusion", affiliation=True)
    _create_index_if_missing("vessel_affiliation_conclusion", "ix_vessel_affiliation_conclusion_vessel", ["vessel_profile_id"])
    _create_index_if_missing("vessel_affiliation_conclusion", "ix_vessel_affiliation_conclusion_status", ["conclusion_status_code"])
    _create_index_if_missing(
        "vessel_affiliation_conclusion",
        "uq_vessel_affiliation_conclusion_current",
        ["vessel_profile_id", "affiliation_type_code"],
        unique=True,
        sqlite_where=sa.text("conclusion_status_code = 'CURRENT'"),
        postgresql_where=sa.text("conclusion_status_code = 'CURRENT'"),
    )

    _seed_dicts()


def downgrade() -> None:
    for table, indexes in {
        "vessel_affiliation_conclusion": [
            "uq_vessel_affiliation_conclusion_current",
            "ix_vessel_affiliation_conclusion_status",
            "ix_vessel_affiliation_conclusion_vessel",
        ],
        "vessel_controller_conclusion": [
            "uq_vessel_controller_conclusion_current",
            "ix_vessel_controller_conclusion_status",
            "ix_vessel_controller_conclusion_vessel",
        ],
    }.items():
        for index_name in indexes:
            _drop_index_if_exists(table, index_name)
        if _has_table(table):
            op.drop_table(table)

    for column_name in ("last_recheck_message", "last_recheck_status_code", "last_rechecked_at"):
        _drop_column_if_exists("vessel_data_quality_issue", column_name)

    _drop_index_if_exists("vessel_governance_task", "ix_vessel_governance_task_rule")
    _drop_index_if_exists("vessel_governance_task", "ix_vessel_governance_task_batch")
    for column_name in ("generation_reason_json", "source_rule_code", "source_batch_id"):
        _drop_column_if_exists("vessel_governance_task", column_name)

    for index_name in (
        "ix_vessel_governance_sync_batch_user",
        "ix_vessel_governance_sync_batch_trigger",
        "ix_vessel_governance_sync_batch_status",
    ):
        _drop_index_if_exists("vessel_governance_sync_batch", index_name)
    if _has_table("vessel_governance_sync_batch"):
        op.drop_table("vessel_governance_sync_batch")

    if _has_table("std_dict") and _has_table("std_dict_item"):
        bind = op.get_bind()
        new_dicts = ["VESSEL_RELATION_CONCLUSION_STATUS", "VESSEL_GOVERNANCE_SYNC_STATUS"]
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
