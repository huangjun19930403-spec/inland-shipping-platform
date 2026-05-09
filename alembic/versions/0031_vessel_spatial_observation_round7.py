"""vessel spatial observation round7

Revision ID: 0031_vessel_spatial_observation_round7
Revises: 0030_vessel_ais_snapshot_production
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


revision: str = "0031_vessel_spatial_observation_round7"
down_revision: Union[str, None] = "0030_vessel_ais_snapshot_production"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return column in {item["name"] for item in inspect(op.get_bind()).get_columns(table)}


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


def _seed_round7_dicts() -> None:
    if not (_has_table("std_dict") and _has_table("std_dict_item")):
        return
    dicts = [
        {
            "dict_code": "VESSEL_SPATIAL_OBSERVATION_TYPE",
            "dict_name": "船舶空间观测类型",
            "items": [
                _dict_item("NODE", "节点周边", color="primary", is_default=True, sort_order=10),
                _dict_item("ROUTE", "航线段", color="success", sort_order=20),
            ],
        },
        {
            "dict_code": "VESSEL_SPATIAL_OBSERVATION_STATUS",
            "dict_name": "船舶空间观测状态",
            "items": [
                _dict_item("READY", "已生成", color="success", is_default=True, sort_order=10),
                _dict_item("PARTIAL", "部分生成", color="warning", sort_order=20),
                _dict_item("NOT_COMPUTABLE", "不可计算", color="info", sort_order=30),
                _dict_item("FAILED", "生成失败", color="danger", sort_order=40),
                _dict_item("EXPIRED", "已过期", color="info", sort_order=50),
            ],
        },
        {
            "dict_code": "VESSEL_SPATIAL_MATCH_STATUS",
            "dict_name": "船舶空间匹配状态",
            "items": [
                _dict_item("NEARBY", "节点周边", color="primary", sort_order=10),
                _dict_item("STAY", "疑似停留", color="success", sort_order=20),
                _dict_item("PASSBY", "疑似经过", color="warning", sort_order=30),
                _dict_item("MATCHED", "航线匹配", color="success", sort_order=40),
                _dict_item("LOW_CONFIDENCE", "低可信", color="warning", sort_order=50),
                _dict_item("NOT_COMPUTABLE", "不可计算", color="info", sort_order=60),
            ],
        },
        {
            "dict_code": "VESSEL_SPATIAL_NOT_COMPUTABLE_REASON",
            "dict_name": "船舶空间分析不可计算原因",
            "items": [
                _dict_item("NODE_COORD_MISSING", "节点缺少经纬度", color="warning", sort_order=10),
                _dict_item("ROUTE_GEOMETRY_MISSING", "航线段缺少轨迹", color="warning", sort_order=20),
                _dict_item("MAIN_LINE_MISSING", "航线缺少主线", color="warning", sort_order=30),
                _dict_item("HISTORICAL_AIS_UNCONFIGURED", "历史 AIS 未配置", color="info", sort_order=40),
                _dict_item("TRACK_SAMPLE_INSUFFICIENT", "轨迹样本不足", color="info", sort_order=50),
                _dict_item("LATEST_AIS_SNAPSHOT_MISSING", "最新 AIS 快照缺失", color="info", sort_order=60),
            ],
        },
        {
            "dict_code": "VESSEL_NAVIGATION_CONSTRAINT_STATUS",
            "dict_name": "船舶通航约束证据状态",
            "items": [
                _dict_item("AVAILABLE", "有证据", color="success", sort_order=10),
                _dict_item("UNKNOWN", "未知", color="info", is_default=True, sort_order=20),
                _dict_item("STALE", "证据过期", color="warning", sort_order=30),
                _dict_item("MISSING_SOURCE", "来源缺失", color="warning", sort_order=40),
                _dict_item("NOT_APPLICABLE", "不适用", color="info", sort_order=50),
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
    for sort_order, payload in enumerate(dicts, start=370):
        row = bind.execute(sa.text("select id from std_dict where dict_code = :code"), {"code": payload["dict_code"]}).first()
        if row is None:
            op.bulk_insert(
                dict_table,
                [{
                    "dict_code": payload["dict_code"],
                    "dict_name": payload["dict_name"],
                    "dict_name_en": payload["dict_code"],
                    "description": None,
                    "is_system": True,
                    "status": 1,
                    "sort_order": sort_order,
                }],
            )
            row = bind.execute(sa.text("select id from std_dict where dict_code = :code"), {"code": payload["dict_code"]}).first()
        else:
            bind.execute(
                sa.text("update std_dict set dict_name = :name, is_system = 1, status = 1 where dict_code = :code"),
                {"name": payload["dict_name"], "code": payload["dict_code"]},
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
    if _has_table("vessel_ais_snapshot") and not _has_column("vessel_ais_snapshot", "failed_batches_json"):
        op.add_column("vessel_ais_snapshot", sa.Column("failed_batches_json", sa.JSON(), nullable=True))

    if not _has_table("vessel_spatial_observation_snapshot"):
        op.create_table(
            "vessel_spatial_observation_snapshot",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("snapshot_id", sa.String(64), nullable=False),
            sa.Column("source_snapshot_id", sa.String(64), sa.ForeignKey("vessel_ais_snapshot.snapshot_id"), nullable=True),
            sa.Column("observation_type_code", sa.String(32), nullable=False),
            sa.Column("query_hash", sa.String(64), nullable=False),
            sa.Column("query_params_json", sa.JSON(), nullable=True),
            sa.Column("status_code", sa.String(32), nullable=False, server_default="READY"),
            sa.Column("source_status_code", sa.String(32), nullable=False, server_default="AVAILABLE"),
            sa.Column("stat_time", sa.DateTime(), nullable=True),
            sa.Column("window_start", sa.DateTime(), nullable=True),
            sa.Column("window_end", sa.DateTime(), nullable=True),
            sa.Column("generated_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("coverage_rate", sa.Numeric(5, 2), nullable=True),
            sa.Column("confidence_level", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("freshness_distribution_json", sa.JSON(), nullable=True),
            sa.Column("source_indices_json", sa.JSON(), nullable=True),
            sa.Column("failed_batch_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_batches_json", sa.JSON(), nullable=True),
            sa.Column("unmatched_mmsi_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("invalid_position_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("stale_position_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("matched_position_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("active_vessel_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("not_computable_reasons_json", sa.JSON(), nullable=True),
            sa.Column("quality_warnings_json", sa.JSON(), nullable=True),
            sa.Column("uncertainty_notes_json", sa.JSON(), nullable=True),
            sa.Column("refresh_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("snapshot_id", name="uq_vessel_spatial_observation_snapshot_snapshot_id"),
        )
    _create_index_if_missing("vessel_spatial_observation_snapshot", "ix_vessel_spatial_observation_snapshot_source_snapshot_id", ["source_snapshot_id"])
    _create_index_if_missing("vessel_spatial_observation_snapshot", "ix_vessel_spatial_observation_snapshot_observation_type_code", ["observation_type_code"])
    _create_index_if_missing("vessel_spatial_observation_snapshot", "ix_vessel_spatial_observation_snapshot_query_hash", ["query_hash"])
    _create_index_if_missing("vessel_spatial_observation_snapshot", "ix_vessel_spatial_observation_snapshot_status_code", ["status_code"])
    _create_index_if_missing("vessel_spatial_observation_snapshot", "ix_vessel_spatial_observation_snapshot_generated_at", ["generated_at"])
    _create_index_if_missing("vessel_spatial_observation_snapshot", "ix_vessel_spatial_observation_snapshot_expires_at", ["expires_at"])

    if not _has_table("vessel_node_observation_item"):
        op.create_table(
            "vessel_node_observation_item",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("snapshot_id", sa.String(64), sa.ForeignKey("vessel_spatial_observation_snapshot.snapshot_id"), nullable=False),
            sa.Column("node_id", BigInteger(), sa.ForeignKey("transport_node.id"), nullable=False),
            sa.Column("node_name", sa.String(128), nullable=False),
            sa.Column("node_type_code", sa.String(64), nullable=True),
            sa.Column("city_code", sa.String(12), nullable=True),
            sa.Column("radius_km", sa.Numeric(8, 2), nullable=False),
            sa.Column("longitude", sa.Numeric(12, 6), nullable=True),
            sa.Column("latitude", sa.Numeric(12, 6), nullable=True),
            sa.Column("active_vessel_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("stay_vessel_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("passby_vessel_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("inflow_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("outflow_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unmatched_mmsi_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("invalid_position_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("stale_position_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("coverage_rate", sa.Numeric(5, 2), nullable=True),
            sa.Column("confidence_level", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("freshness_distribution_json", sa.JSON(), nullable=True),
            sa.Column("ship_type_distribution_json", sa.JSON(), nullable=True),
            sa.Column("risk_distribution_json", sa.JSON(), nullable=True),
            sa.Column("latest_position_time", sa.DateTime(), nullable=True),
            sa.Column("not_computable_reasons_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    _create_index_if_missing("vessel_node_observation_item", "ix_vessel_node_observation_item_snapshot_id", ["snapshot_id"])
    _create_index_if_missing("vessel_node_observation_item", "ix_vessel_node_observation_item_node_id", ["node_id"])
    _create_index_if_missing("vessel_node_observation_item", "ix_vessel_node_observation_item_city_code", ["city_code"])

    if not _has_table("vessel_node_observation_vessel"):
        op.create_table(
            "vessel_node_observation_vessel",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("snapshot_id", sa.String(64), sa.ForeignKey("vessel_spatial_observation_snapshot.snapshot_id"), nullable=False),
            sa.Column("node_id", BigInteger(), sa.ForeignKey("transport_node.id"), nullable=False),
            sa.Column("vessel_profile_id", BigInteger(), sa.ForeignKey("vessel_profile.id"), nullable=True),
            sa.Column("mmsi", sa.String(16), nullable=False),
            sa.Column("ship_name", sa.String(128), nullable=True),
            sa.Column("ship_type_code", sa.String(64), nullable=True),
            sa.Column("deadweight_ton", sa.Numeric(18, 2), nullable=True),
            sa.Column("longitude", sa.Numeric(12, 6), nullable=True),
            sa.Column("latitude", sa.Numeric(12, 6), nullable=True),
            sa.Column("distance_km", sa.Numeric(10, 3), nullable=True),
            sa.Column("position_time", sa.DateTime(), nullable=True),
            sa.Column("source_index", sa.String(128), nullable=True),
            sa.Column("freshness_level", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("match_status_code", sa.String(32), nullable=False, server_default="NEARBY"),
            sa.Column("stay_duration_minutes", sa.Integer(), nullable=True),
            sa.Column("direction_status_code", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("risk_level", sa.String(32), nullable=True),
            sa.Column("quality_level", sa.String(32), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    _create_index_if_missing("vessel_node_observation_vessel", "ix_vessel_node_observation_vessel_snapshot_id", ["snapshot_id"])
    _create_index_if_missing("vessel_node_observation_vessel", "ix_vessel_node_observation_vessel_node_id", ["node_id"])
    _create_index_if_missing("vessel_node_observation_vessel", "ix_vessel_node_observation_vessel_vessel_profile_id", ["vessel_profile_id"])
    _create_index_if_missing("vessel_node_observation_vessel", "ix_vessel_node_observation_vessel_mmsi", ["mmsi"])
    _create_index_if_missing("vessel_node_observation_vessel", "ix_vessel_node_observation_vessel_position_time", ["position_time"])
    _create_index_if_missing("vessel_node_observation_vessel", "ix_vessel_node_observation_vessel_match_status_code", ["match_status_code"])

    if not _has_table("vessel_route_segment_observation_item"):
        op.create_table(
            "vessel_route_segment_observation_item",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("snapshot_id", sa.String(64), sa.ForeignKey("vessel_spatial_observation_snapshot.snapshot_id"), nullable=False),
            sa.Column("route_id", BigInteger(), sa.ForeignKey("shipping_route.id"), nullable=True),
            sa.Column("line_id", BigInteger(), sa.ForeignKey("shipping_route_line.id"), nullable=False),
            sa.Column("segment_id", BigInteger(), sa.ForeignKey("shipping_route_line_segment.id"), nullable=False),
            sa.Column("segment_no", sa.Integer(), nullable=False),
            sa.Column("segment_name", sa.String(128), nullable=True),
            sa.Column("geometry_status_code", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("geometry_source", sa.String(64), nullable=True),
            sa.Column("geometry_json", sa.JSON(), nullable=True),
            sa.Column("matched_vessel_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("active_vessel_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("point_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("gap_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("covered_ratio", sa.Numeric(5, 2), nullable=True),
            sa.Column("average_match_score", sa.Numeric(5, 2), nullable=True),
            sa.Column("coverage_rate", sa.Numeric(5, 2), nullable=True),
            sa.Column("confidence_level", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("not_computable_reasons_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    _create_index_if_missing("vessel_route_segment_observation_item", "ix_vessel_route_segment_observation_item_snapshot_id", ["snapshot_id"])
    _create_index_if_missing("vessel_route_segment_observation_item", "ix_vessel_route_segment_observation_item_route_id", ["route_id"])
    _create_index_if_missing("vessel_route_segment_observation_item", "ix_vessel_route_segment_observation_item_line_id", ["line_id"])
    _create_index_if_missing("vessel_route_segment_observation_item", "ix_vessel_route_segment_observation_item_segment_id", ["segment_id"])

    if not _has_table("vessel_route_segment_match_sample"):
        op.create_table(
            "vessel_route_segment_match_sample",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("snapshot_id", sa.String(64), sa.ForeignKey("vessel_spatial_observation_snapshot.snapshot_id"), nullable=False),
            sa.Column("segment_id", BigInteger(), sa.ForeignKey("shipping_route_line_segment.id"), nullable=False),
            sa.Column("vessel_profile_id", BigInteger(), sa.ForeignKey("vessel_profile.id"), nullable=True),
            sa.Column("mmsi", sa.String(16), nullable=False),
            sa.Column("ship_name", sa.String(128), nullable=True),
            sa.Column("ship_type_code", sa.String(64), nullable=True),
            sa.Column("deadweight_ton", sa.Numeric(18, 2), nullable=True),
            sa.Column("match_score", sa.Numeric(5, 2), nullable=True),
            sa.Column("covered_ratio", sa.Numeric(5, 2), nullable=True),
            sa.Column("direction_consistency", sa.Numeric(5, 2), nullable=True),
            sa.Column("point_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("gap_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("latest_position_time", sa.DateTime(), nullable=True),
            sa.Column("source_index", sa.String(128), nullable=True),
            sa.Column("freshness_level", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("confidence_level", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("match_status_code", sa.String(32), nullable=False, server_default="MATCHED"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    _create_index_if_missing("vessel_route_segment_match_sample", "ix_vessel_route_segment_match_sample_snapshot_id", ["snapshot_id"])
    _create_index_if_missing("vessel_route_segment_match_sample", "ix_vessel_route_segment_match_sample_segment_id", ["segment_id"])
    _create_index_if_missing("vessel_route_segment_match_sample", "ix_vessel_route_segment_match_sample_vessel_profile_id", ["vessel_profile_id"])
    _create_index_if_missing("vessel_route_segment_match_sample", "ix_vessel_route_segment_match_sample_mmsi", ["mmsi"])
    _create_index_if_missing("vessel_route_segment_match_sample", "ix_vessel_route_segment_match_sample_match_status_code", ["match_status_code"])

    if not _has_table("vessel_navigation_constraint_evidence"):
        op.create_table(
            "vessel_navigation_constraint_evidence",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("snapshot_id", sa.String(64), sa.ForeignKey("vessel_spatial_observation_snapshot.snapshot_id"), nullable=True),
            sa.Column("context_type_code", sa.String(32), nullable=False),
            sa.Column("context_id", BigInteger(), nullable=False),
            sa.Column("constraint_point_id", BigInteger(), sa.ForeignKey("navigation_constraint_point.id"), nullable=True),
            sa.Column("constraint_name", sa.String(128), nullable=True),
            sa.Column("constraint_type_code", sa.String(64), nullable=True),
            sa.Column("status_code", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("source_type_code", sa.String(64), nullable=False, server_default="BASE_DATA"),
            sa.Column("source_ref", sa.String(128), nullable=True),
            sa.Column("observed_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("value_json", sa.JSON(), nullable=True),
            sa.Column("confidence_level", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("unavailable_reason", sa.String(128), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    _create_index_if_missing("vessel_navigation_constraint_evidence", "ix_vessel_navigation_constraint_evidence_snapshot_id", ["snapshot_id"])
    _create_index_if_missing("vessel_navigation_constraint_evidence", "ix_vessel_navigation_constraint_evidence_context", ["context_type_code", "context_id"])
    _create_index_if_missing("vessel_navigation_constraint_evidence", "ix_vessel_navigation_constraint_evidence_constraint_point_id", ["constraint_point_id"])
    _create_index_if_missing("vessel_navigation_constraint_evidence", "ix_vessel_navigation_constraint_evidence_status_code", ["status_code"])

    _seed_round7_dicts()


def downgrade() -> None:
    _drop_index_if_exists("vessel_navigation_constraint_evidence", "ix_vessel_navigation_constraint_evidence_status_code")
    _drop_index_if_exists("vessel_navigation_constraint_evidence", "ix_vessel_navigation_constraint_evidence_constraint_point_id")
    _drop_index_if_exists("vessel_navigation_constraint_evidence", "ix_vessel_navigation_constraint_evidence_context")
    _drop_index_if_exists("vessel_navigation_constraint_evidence", "ix_vessel_navigation_constraint_evidence_snapshot_id")
    if _has_table("vessel_navigation_constraint_evidence"):
        op.drop_table("vessel_navigation_constraint_evidence")

    _drop_index_if_exists("vessel_route_segment_match_sample", "ix_vessel_route_segment_match_sample_match_status_code")
    _drop_index_if_exists("vessel_route_segment_match_sample", "ix_vessel_route_segment_match_sample_mmsi")
    _drop_index_if_exists("vessel_route_segment_match_sample", "ix_vessel_route_segment_match_sample_vessel_profile_id")
    _drop_index_if_exists("vessel_route_segment_match_sample", "ix_vessel_route_segment_match_sample_segment_id")
    _drop_index_if_exists("vessel_route_segment_match_sample", "ix_vessel_route_segment_match_sample_snapshot_id")
    if _has_table("vessel_route_segment_match_sample"):
        op.drop_table("vessel_route_segment_match_sample")

    _drop_index_if_exists("vessel_route_segment_observation_item", "ix_vessel_route_segment_observation_item_segment_id")
    _drop_index_if_exists("vessel_route_segment_observation_item", "ix_vessel_route_segment_observation_item_line_id")
    _drop_index_if_exists("vessel_route_segment_observation_item", "ix_vessel_route_segment_observation_item_route_id")
    _drop_index_if_exists("vessel_route_segment_observation_item", "ix_vessel_route_segment_observation_item_snapshot_id")
    if _has_table("vessel_route_segment_observation_item"):
        op.drop_table("vessel_route_segment_observation_item")

    _drop_index_if_exists("vessel_node_observation_vessel", "ix_vessel_node_observation_vessel_match_status_code")
    _drop_index_if_exists("vessel_node_observation_vessel", "ix_vessel_node_observation_vessel_position_time")
    _drop_index_if_exists("vessel_node_observation_vessel", "ix_vessel_node_observation_vessel_mmsi")
    _drop_index_if_exists("vessel_node_observation_vessel", "ix_vessel_node_observation_vessel_vessel_profile_id")
    _drop_index_if_exists("vessel_node_observation_vessel", "ix_vessel_node_observation_vessel_node_id")
    _drop_index_if_exists("vessel_node_observation_vessel", "ix_vessel_node_observation_vessel_snapshot_id")
    if _has_table("vessel_node_observation_vessel"):
        op.drop_table("vessel_node_observation_vessel")

    _drop_index_if_exists("vessel_node_observation_item", "ix_vessel_node_observation_item_city_code")
    _drop_index_if_exists("vessel_node_observation_item", "ix_vessel_node_observation_item_node_id")
    _drop_index_if_exists("vessel_node_observation_item", "ix_vessel_node_observation_item_snapshot_id")
    if _has_table("vessel_node_observation_item"):
        op.drop_table("vessel_node_observation_item")

    _drop_index_if_exists("vessel_spatial_observation_snapshot", "ix_vessel_spatial_observation_snapshot_expires_at")
    _drop_index_if_exists("vessel_spatial_observation_snapshot", "ix_vessel_spatial_observation_snapshot_generated_at")
    _drop_index_if_exists("vessel_spatial_observation_snapshot", "ix_vessel_spatial_observation_snapshot_status_code")
    _drop_index_if_exists("vessel_spatial_observation_snapshot", "ix_vessel_spatial_observation_snapshot_query_hash")
    _drop_index_if_exists("vessel_spatial_observation_snapshot", "ix_vessel_spatial_observation_snapshot_observation_type_code")
    _drop_index_if_exists("vessel_spatial_observation_snapshot", "ix_vessel_spatial_observation_snapshot_source_snapshot_id")
    if _has_table("vessel_spatial_observation_snapshot"):
        op.drop_table("vessel_spatial_observation_snapshot")
