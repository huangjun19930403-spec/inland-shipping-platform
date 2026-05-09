"""vessel ais snapshot production

Revision ID: 0030_vessel_ais_snapshot_production
Revises: 0029_vessel_risk_signal_active_fingerprint
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


revision: str = "0030_vessel_ais_snapshot_production"
down_revision: Union[str, None] = "0029_vessel_risk_signal_active_fingerprint"
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


def _seed_round6_dicts() -> None:
    if not (_has_table("std_dict") and _has_table("std_dict_item")):
        return
    dicts = [
        {
            "dict_code": "VESSEL_AIS_FRESHNESS_LEVEL",
            "dict_name": "AIS 新鲜度等级",
            "items": [
                _dict_item("FRESH", "2 小时内", color="success", sort_order=10),
                _dict_item("RECENT", "12 小时内", color="primary", sort_order=20),
                _dict_item("STALE", "24 小时内", color="warning", sort_order=30),
                _dict_item("EXPIRED", "超过 24 小时", color="danger", sort_order=40),
                _dict_item("UNKNOWN", "未知", color="info", is_default=True, sort_order=50),
            ],
        },
        {
            "dict_code": "VESSEL_AIS_SNAPSHOT_STATUS",
            "dict_name": "AIS 态势快照状态",
            "items": [
                _dict_item("READY", "已生成", color="success", is_default=True, sort_order=10),
                _dict_item("PARTIAL", "部分生成", color="warning", sort_order=20),
                _dict_item("FAILED", "生成失败", color="danger", sort_order=30),
                _dict_item("EXPIRED", "已过期", color="info", sort_order=40),
            ],
        },
        {
            "dict_code": "VESSEL_AIS_POSITION_MATCH_STATUS",
            "dict_name": "AIS 点位匹配状态",
            "items": [
                _dict_item("MATCHED_PROFILE", "已匹配档案", color="success", is_default=True, sort_order=10),
                _dict_item("UNMATCHED_MMSI", "未匹配 MMSI", color="warning", sort_order=20),
                _dict_item("MULTI_PROFILE_CONFLICT", "多档案冲突", color="danger", sort_order=30),
                _dict_item("INVALID_POSITION", "点位无效", color="danger", sort_order=40),
            ],
        },
        {
            "dict_code": "VESSEL_AIS_SOURCE_STATUS",
            "dict_name": "AIS 数据源状态",
            "items": [
                _dict_item("AVAILABLE", "实时船位可用", color="success", is_default=True, sort_order=10),
                _dict_item("EMPTY", "暂无实时船位", color="info", sort_order=20),
                _dict_item("UNCONFIGURED", "实时 ES 未配置", color="warning", sort_order=30),
                _dict_item("PARTIAL", "部分可用", color="warning", sort_order=40),
                _dict_item("ERROR", "实时船位异常", color="danger", sort_order=50),
            ],
        },
        {
            "dict_code": "VESSEL_AIS_BOUNDARY_STATUS",
            "dict_name": "AIS 城市边界状态",
            "items": [
                _dict_item("AVAILABLE", "边界可用", color="success", is_default=True, sort_order=10),
                _dict_item("MISSING", "缺少边界", color="warning", sort_order=20),
                _dict_item("UNKNOWN_CITY", "未知城市", color="info", sort_order=30),
                _dict_item("UNKNOWN", "未知", color="info", sort_order=40),
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
    for sort_order, payload in enumerate(dicts, start=360):
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
                sa.text("update std_dict set dict_name = :name, is_system = 1, status = 1 where dict_code = :code"),
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
                    {**item, "dict_id": dict_id},
                )
            else:
                op.bulk_insert(item_table, [{**item, "dict_id": dict_id}])


def upgrade() -> None:
    if not _has_table("vessel_ais_snapshot"):
        op.create_table(
            "vessel_ais_snapshot",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("snapshot_id", sa.String(64), nullable=False),
            sa.Column("query_hash", sa.String(64), nullable=False),
            sa.Column("query_params_json", sa.JSON(), nullable=True),
            sa.Column("status_code", sa.String(32), nullable=False, server_default="READY"),
            sa.Column("generated_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("cache_backend_code", sa.String(32), nullable=False, server_default="memory"),
            sa.Column("scanned_profile_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("queried_mmsi_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("matched_profile_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("matched_position_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unmatched_mmsi_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("invalid_position_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unknown_city_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_batch_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_batches_json", sa.JSON(), nullable=True),
            sa.Column("coverage_rate", sa.Numeric(5, 2), nullable=True),
            sa.Column("freshness_distribution_json", sa.JSON(), nullable=True),
            sa.Column("source_indices_json", sa.JSON(), nullable=True),
            sa.Column("uncertainty_notes_json", sa.JSON(), nullable=True),
            sa.Column("boundary_version_id", BigInteger(), nullable=True),
            sa.Column("refresh_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("snapshot_id", name="uq_vessel_ais_snapshot_snapshot_id"),
        )
    _create_index_if_missing("vessel_ais_snapshot", "ix_vessel_ais_snapshot_query_hash", ["query_hash"])
    _create_index_if_missing("vessel_ais_snapshot", "ix_vessel_ais_snapshot_status_code", ["status_code"])
    _create_index_if_missing("vessel_ais_snapshot", "ix_vessel_ais_snapshot_generated_at", ["generated_at"])
    _create_index_if_missing("vessel_ais_snapshot", "ix_vessel_ais_snapshot_expires_at", ["expires_at"])

    if not _has_table("vessel_ais_city_snapshot_item"):
        op.create_table(
            "vessel_ais_city_snapshot_item",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("snapshot_id", sa.String(64), sa.ForeignKey("vessel_ais_snapshot.snapshot_id"), nullable=False),
            sa.Column("city_code", sa.String(12), nullable=True),
            sa.Column("city_name", sa.String(128), nullable=False),
            sa.Column("positioned_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("matched_position_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unmatched_mmsi_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("invalid_position_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("stale_position_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("freshness_distribution_json", sa.JSON(), nullable=True),
            sa.Column("boundary_status_code", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("has_boundary", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("boundary_precision", sa.String(16), nullable=True),
            sa.Column("latest_position_time", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    _create_index_if_missing("vessel_ais_city_snapshot_item", "ix_vessel_ais_city_snapshot_item_snapshot_id", ["snapshot_id"])
    _create_index_if_missing("vessel_ais_city_snapshot_item", "ix_vessel_ais_city_snapshot_item_city_code", ["city_code"])

    if not _has_table("vessel_latest_position_snapshot"):
        op.create_table(
            "vessel_latest_position_snapshot",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("snapshot_id", sa.String(64), sa.ForeignKey("vessel_ais_snapshot.snapshot_id"), nullable=False),
            sa.Column("vessel_profile_id", BigInteger(), sa.ForeignKey("vessel_profile.id"), nullable=True),
            sa.Column("mmsi", sa.String(16), nullable=False),
            sa.Column("longitude", sa.Numeric(12, 6), nullable=True),
            sa.Column("latitude", sa.Numeric(12, 6), nullable=True),
            sa.Column("speed_kn", sa.Numeric(10, 2), nullable=True),
            sa.Column("course_deg", sa.Numeric(10, 2), nullable=True),
            sa.Column("heading_deg", sa.Numeric(10, 2), nullable=True),
            sa.Column("position_time", sa.DateTime(), nullable=True),
            sa.Column("source_index", sa.String(128), nullable=True),
            sa.Column("freshness_level", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("match_status_code", sa.String(32), nullable=False, server_default="MATCHED_PROFILE"),
            sa.Column("city_code", sa.String(12), nullable=True),
            sa.Column("city_name", sa.String(128), nullable=True),
            sa.Column("valid_position_flag", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    _create_index_if_missing("vessel_latest_position_snapshot", "ix_vessel_latest_position_snapshot_snapshot_id", ["snapshot_id"])
    _create_index_if_missing("vessel_latest_position_snapshot", "ix_vessel_latest_position_snapshot_vessel_profile_id", ["vessel_profile_id"])
    _create_index_if_missing("vessel_latest_position_snapshot", "ix_vessel_latest_position_snapshot_mmsi", ["mmsi"])
    _create_index_if_missing("vessel_latest_position_snapshot", "ix_vessel_latest_position_snapshot_position_time", ["position_time"])
    _create_index_if_missing("vessel_latest_position_snapshot", "ix_vessel_latest_position_snapshot_freshness_level", ["freshness_level"])
    _create_index_if_missing("vessel_latest_position_snapshot", "ix_vessel_latest_position_snapshot_match_status_code", ["match_status_code"])
    _create_index_if_missing("vessel_latest_position_snapshot", "ix_vessel_latest_position_snapshot_city_code", ["city_code"])
    _create_index_if_missing(
        "vessel_latest_position_snapshot",
        "ix_vessel_latest_position_snapshot_snapshot_match",
        ["snapshot_id", "match_status_code"],
    )

    _seed_round6_dicts()


def downgrade() -> None:
    _drop_index_if_exists("vessel_latest_position_snapshot", "ix_vessel_latest_position_snapshot_snapshot_match")
    _drop_index_if_exists("vessel_latest_position_snapshot", "ix_vessel_latest_position_snapshot_city_code")
    _drop_index_if_exists("vessel_latest_position_snapshot", "ix_vessel_latest_position_snapshot_match_status_code")
    _drop_index_if_exists("vessel_latest_position_snapshot", "ix_vessel_latest_position_snapshot_freshness_level")
    _drop_index_if_exists("vessel_latest_position_snapshot", "ix_vessel_latest_position_snapshot_position_time")
    _drop_index_if_exists("vessel_latest_position_snapshot", "ix_vessel_latest_position_snapshot_mmsi")
    _drop_index_if_exists("vessel_latest_position_snapshot", "ix_vessel_latest_position_snapshot_vessel_profile_id")
    _drop_index_if_exists("vessel_latest_position_snapshot", "ix_vessel_latest_position_snapshot_snapshot_id")
    if _has_table("vessel_latest_position_snapshot"):
        op.drop_table("vessel_latest_position_snapshot")

    _drop_index_if_exists("vessel_ais_city_snapshot_item", "ix_vessel_ais_city_snapshot_item_city_code")
    _drop_index_if_exists("vessel_ais_city_snapshot_item", "ix_vessel_ais_city_snapshot_item_snapshot_id")
    if _has_table("vessel_ais_city_snapshot_item"):
        op.drop_table("vessel_ais_city_snapshot_item")

    _drop_index_if_exists("vessel_ais_snapshot", "ix_vessel_ais_snapshot_expires_at")
    _drop_index_if_exists("vessel_ais_snapshot", "ix_vessel_ais_snapshot_generated_at")
    _drop_index_if_exists("vessel_ais_snapshot", "ix_vessel_ais_snapshot_status_code")
    _drop_index_if_exists("vessel_ais_snapshot", "ix_vessel_ais_snapshot_query_hash")
    if _has_table("vessel_ais_snapshot"):
        op.drop_table("vessel_ais_snapshot")
