"""vessel candidate analysis round8

Revision ID: 0032_vessel_candidate_analysis_round8
Revises: 0031_vessel_spatial_observation_round7
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


revision: str = "0032_vessel_candidate_analysis_round8"
down_revision: Union[str, None] = "0031_vessel_spatial_observation_round7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _has_index(table: str, index_name: str) -> bool:
    if not _has_table(table):
        return False
    return index_name in {item["name"] for item in inspect(op.get_bind()).get_indexes(table)}


def _create_index_if_missing(table: str, index_name: str, columns: list[str]) -> None:
    if _has_table(table) and not _has_index(table, index_name):
        op.create_index(index_name, table, columns)


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


def _seed_round8_dicts() -> None:
    if not (_has_table("std_dict") and _has_table("std_dict_item")):
        return
    dicts = [
        {
            "dict_code": "VESSEL_CANDIDATE_CONTEXT_TYPE",
            "dict_name": "船舶候选适配上下文类型",
            "items": [
                _dict_item("FREIGHT_SAMPLE", "正式货源样本", color="primary", is_default=True, sort_order=10),
                _dict_item("FREIGHT_SAMPLE_SET", "货源样本集合", color="primary", sort_order=20),
                _dict_item("FREIGHT_CANDIDATE", "候选货源样本", color="warning", sort_order=30),
                _dict_item("NODE", "节点条件", color="success", sort_order=40),
                _dict_item("ROUTE", "航线条件", color="success", sort_order=50),
                _dict_item("REGION", "区域条件", color="info", sort_order=60),
                _dict_item("MANUAL", "手工条件", color="info", sort_order=70),
            ],
        },
        {
            "dict_code": "VESSEL_CANDIDATE_ANALYSIS_STATUS",
            "dict_name": "船舶候选适配分析状态",
            "items": [
                _dict_item("READY", "已生成", color="success", is_default=True, sort_order=10),
                _dict_item("PARTIAL", "部分生成", color="warning", sort_order=20),
                _dict_item("NOT_COMPUTABLE", "不可计算", color="info", sort_order=30),
                _dict_item("FAILED", "生成失败", color="danger", sort_order=40),
                _dict_item("EXPIRED", "已过期", color="info", sort_order=50),
            ],
        },
        {
            "dict_code": "VESSEL_CANDIDATE_VALUE_LEVEL",
            "dict_name": "船舶候选分析价值等级",
            "items": [
                _dict_item("HIGH", "高分析价值", color="success", sort_order=10),
                _dict_item("MEDIUM", "中分析价值", color="warning", is_default=True, sort_order=20),
                _dict_item("LOW", "低分析价值", color="info", sort_order=30),
            ],
        },
        {
            "dict_code": "VESSEL_CANDIDATE_SCORE_DIMENSION",
            "dict_name": "船舶候选适配评分维度",
            "items": [
                _dict_item("SPATIAL_DISTANCE", "空间距离", color="primary", sort_order=10),
                _dict_item("ROUTE_TRAJECTORY", "航线轨迹", color="primary", sort_order=20),
                _dict_item("DEADWEIGHT", "吨位", color="success", sort_order=30),
                _dict_item("SHIP_TYPE_CARGO", "船型货类", color="success", sort_order=40),
                _dict_item("DRAFT_NAVIGATION", "吃水通航", color="warning", sort_order=50),
                _dict_item("RISK_COMPLIANCE", "合规风险", color="danger", sort_order=60),
                _dict_item("DATA_QUALITY", "数据质量", color="info", sort_order=70),
                _dict_item("CONTACT_TRUST", "联系可信", color="info", sort_order=80),
            ],
        },
        {
            "dict_code": "VESSEL_CANDIDATE_NOT_COMPUTABLE_REASON",
            "dict_name": "船舶候选适配不可计算原因",
            "items": [
                _dict_item("NODE_COORD_MISSING", "节点缺少经纬度", color="warning", sort_order=10),
                _dict_item("AIS_SNAPSHOT_MISSING", "AIS 快照缺失", color="info", sort_order=20),
                _dict_item("SPATIAL_SNAPSHOT_MISSING", "空间快照缺失", color="info", sort_order=30),
                _dict_item("ROUTE_GEOMETRY_MISSING", "航线几何缺失", color="warning", sort_order=40),
                _dict_item("CONSTRAINT_SOURCE_MISSING", "通航约束来源缺失", color="warning", sort_order=50),
                _dict_item("DEADWEIGHT_MISSING", "船舶吨位缺失", color="warning", sort_order=60),
                _dict_item("SHIP_TYPE_MISSING", "船型缺失", color="warning", sort_order=70),
                _dict_item("RISK_UNKNOWN", "风险未知", color="info", sort_order=80),
                _dict_item("TRACK_COVERAGE_INSUFFICIENT", "轨迹覆盖不足", color="info", sort_order=90),
            ],
        },
        {
            "dict_code": "VESSEL_ANALYSIS_ANNOTATION_TYPE",
            "dict_name": "船舶分析标注类型",
            "items": [
                _dict_item("DATA_TRUSTED", "数据可信", color="success", sort_order=10),
                _dict_item("DATA_INSUFFICIENT", "数据不足", color="warning", sort_order=20),
                _dict_item("SAMPLE_REFERENCEABLE", "样本可参考", color="success", sort_order=30),
                _dict_item("SAMPLE_NOT_REFERENCEABLE", "样本不宜参考", color="danger", sort_order=40),
                _dict_item("CONTACT_SUSPECTED_INVALID", "联系人疑似失效", color="warning", sort_order=50),
                _dict_item("CERTIFICATE_RISK", "证照风险", color="danger", sort_order=60),
                _dict_item("POSITION_ABNORMAL", "位置异常", color="warning", sort_order=70),
                _dict_item("TONNAGE_MISMATCH", "吨位不适配", color="warning", sort_order=80),
                _dict_item("NEEDS_REVIEW", "需复核", color="info", is_default=True, sort_order=90),
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
    for sort_order, payload in enumerate(dicts, start=430):
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
    if not _has_table("vessel_candidate_analysis"):
        op.create_table(
            "vessel_candidate_analysis",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("context_type_code", sa.String(32), nullable=False),
            sa.Column("source_layer_code", sa.String(64), nullable=False, server_default="MANUAL"),
            sa.Column("freight_id", BigInteger(), sa.ForeignKey("freight.id"), nullable=True),
            sa.Column("freight_candidate_id", BigInteger(), sa.ForeignKey("freight_candidate.id"), nullable=True),
            sa.Column("origin_node_id", BigInteger(), sa.ForeignKey("transport_node.id"), nullable=True),
            sa.Column("destination_node_id", BigInteger(), sa.ForeignKey("transport_node.id"), nullable=True),
            sa.Column("route_id", BigInteger(), sa.ForeignKey("shipping_route.id"), nullable=True),
            sa.Column("line_id", BigInteger(), sa.ForeignKey("shipping_route_line.id"), nullable=True),
            sa.Column("origin_city_code", sa.String(12), nullable=True),
            sa.Column("destination_city_code", sa.String(12), nullable=True),
            sa.Column("region_id", BigInteger(), sa.ForeignKey("region.id"), nullable=True),
            sa.Column("context_json", sa.JSON(), nullable=True),
            sa.Column("filters_json", sa.JSON(), nullable=True),
            sa.Column("source_ais_snapshot_id", sa.String(64), sa.ForeignKey("vessel_ais_snapshot.snapshot_id"), nullable=True),
            sa.Column(
                "source_spatial_snapshot_id",
                sa.String(64),
                sa.ForeignKey("vessel_spatial_observation_snapshot.snapshot_id"),
                nullable=True,
            ),
            sa.Column("query_hash", sa.String(64), nullable=False),
            sa.Column("status_code", sa.String(32), nullable=False, server_default="READY"),
            sa.Column("coverage_rate", sa.Numeric(5, 2), nullable=True),
            sa.Column("confidence_level", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("low_confidence_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("not_computable_reasons_json", sa.JSON(), nullable=True),
            sa.Column("uncertainty_notes_json", sa.JSON(), nullable=True),
            sa.Column("data_sources_json", sa.JSON(), nullable=True),
            sa.Column("generated_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("created_by", BigInteger(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )

    if not _has_table("vessel_candidate_analysis_item"):
        op.create_table(
            "vessel_candidate_analysis_item",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("analysis_id", BigInteger(), sa.ForeignKey("vessel_candidate_analysis.id"), nullable=False),
            sa.Column("vessel_profile_id", BigInteger(), sa.ForeignKey("vessel_profile.id"), nullable=True),
            sa.Column("mmsi", sa.String(16), nullable=True),
            sa.Column("ship_name", sa.String(128), nullable=True),
            sa.Column("ship_type_code", sa.String(64), nullable=True),
            sa.Column("deadweight_ton", sa.Numeric(18, 2), nullable=True),
            sa.Column("design_draft_m", sa.Numeric(10, 2), nullable=True),
            sa.Column("latest_position_time", sa.DateTime(), nullable=True),
            sa.Column("ais_freshness_level", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("risk_level", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("quality_level", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("fit_score", sa.Numeric(8, 2), nullable=False, server_default="0"),
            sa.Column("candidate_value_level", sa.String(32), nullable=False, server_default="LOW"),
            sa.Column("confidence_level", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("node_distance_km", sa.Numeric(10, 3), nullable=True),
            sa.Column("route_match_score", sa.Numeric(8, 2), nullable=True),
            sa.Column("direction_consistency", sa.Numeric(8, 2), nullable=True),
            sa.Column("constraint_status_code", sa.String(32), nullable=True),
            sa.Column("score_parts_json", sa.JSON(), nullable=True),
            sa.Column("risk_reasons_json", sa.JSON(), nullable=True),
            sa.Column("uncertainty_reasons_json", sa.JSON(), nullable=True),
            sa.Column("not_computable_reasons_json", sa.JSON(), nullable=True),
            sa.Column("data_sources_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    if not _has_table("vessel_candidate_analysis_annotation"):
        op.create_table(
            "vessel_candidate_analysis_annotation",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("analysis_id", BigInteger(), sa.ForeignKey("vessel_candidate_analysis.id"), nullable=False),
            sa.Column("item_id", BigInteger(), sa.ForeignKey("vessel_candidate_analysis_item.id"), nullable=False),
            sa.Column("annotation_type_code", sa.String(64), nullable=False),
            sa.Column("comment", sa.String(1000), nullable=True),
            sa.Column("created_by", BigInteger(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("source_version_json", sa.JSON(), nullable=True),
        )

    for table, indexes in {
        "vessel_candidate_analysis": [
            ("ix_vessel_candidate_analysis_context_type_code", ["context_type_code"]),
            ("ix_vessel_candidate_analysis_status_code", ["status_code"]),
            ("ix_vessel_candidate_analysis_query_hash", ["query_hash"]),
            ("ix_vessel_candidate_analysis_source_ais_snapshot_id", ["source_ais_snapshot_id"]),
            ("ix_vessel_candidate_analysis_source_spatial_snapshot_id", ["source_spatial_snapshot_id"]),
        ],
        "vessel_candidate_analysis_item": [
            ("ix_vessel_candidate_analysis_item_analysis_id", ["analysis_id"]),
            ("ix_vessel_candidate_analysis_item_vessel_profile_id", ["vessel_profile_id"]),
            ("ix_vessel_candidate_analysis_item_candidate_value_level", ["candidate_value_level"]),
            ("ix_vessel_candidate_analysis_item_confidence_level", ["confidence_level"]),
        ],
        "vessel_candidate_analysis_annotation": [
            ("ix_vessel_candidate_analysis_annotation_analysis_id", ["analysis_id"]),
            ("ix_vessel_candidate_analysis_annotation_item_id", ["item_id"]),
            ("ix_vessel_candidate_analysis_annotation_annotation_type_code", ["annotation_type_code"]),
        ],
    }.items():
        for index_name, columns in indexes:
            _create_index_if_missing(table, index_name, columns)

    _seed_round8_dicts()


def downgrade() -> None:
    for table, indexes in {
        "vessel_candidate_analysis_annotation": [
            "ix_vessel_candidate_analysis_annotation_annotation_type_code",
            "ix_vessel_candidate_analysis_annotation_item_id",
            "ix_vessel_candidate_analysis_annotation_analysis_id",
        ],
        "vessel_candidate_analysis_item": [
            "ix_vessel_candidate_analysis_item_confidence_level",
            "ix_vessel_candidate_analysis_item_candidate_value_level",
            "ix_vessel_candidate_analysis_item_vessel_profile_id",
            "ix_vessel_candidate_analysis_item_analysis_id",
        ],
        "vessel_candidate_analysis": [
            "ix_vessel_candidate_analysis_source_spatial_snapshot_id",
            "ix_vessel_candidate_analysis_source_ais_snapshot_id",
            "ix_vessel_candidate_analysis_query_hash",
            "ix_vessel_candidate_analysis_status_code",
            "ix_vessel_candidate_analysis_context_type_code",
        ],
    }.items():
        for index_name in indexes:
            _drop_index_if_exists(table, index_name)
    for table in [
        "vessel_candidate_analysis_annotation",
        "vessel_candidate_analysis_item",
        "vessel_candidate_analysis",
    ]:
        if _has_table(table):
            op.drop_table(table)
