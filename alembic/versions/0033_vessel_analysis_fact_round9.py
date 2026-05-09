"""vessel analysis fact loop round9

Revision ID: 0033_vessel_analysis_fact_round9
Revises: 0032_vessel_candidate_analysis_round8
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


revision: str = "0033_vessel_analysis_fact_round9"
down_revision: Union[str, None] = "0032_vessel_candidate_analysis_round8"
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


def _create_index_if_missing(table: str, index_name: str, columns: list[str]) -> None:
    if _has_table(table) and not _has_index(table, index_name):
        op.create_index(index_name, table, columns)


def _drop_index_if_exists(table: str, index_name: str) -> None:
    if _has_index(table, index_name):
        op.drop_index(index_name, table_name=table)


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if _has_table(table) and column.name not in _columns(table):
        op.add_column(table, column)


def _drop_column_if_exists(table: str, column_name: str) -> None:
    if _has_table(table) and column_name in _columns(table):
        op.drop_column(table, column_name)


def _provenance_columns(default_source_layer: str) -> list[sa.Column]:
    return [
        sa.Column("source_layer_code", sa.String(64), nullable=False, server_default=default_source_layer),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("coverage_rate", sa.Numeric(5, 2), nullable=True),
        sa.Column("confidence_level", sa.String(32), nullable=False, server_default="UNKNOWN"),
        sa.Column("not_computable_reasons_json", sa.JSON(), nullable=True),
        sa.Column("uncertainty_reasons_json", sa.JSON(), nullable=True),
        sa.Column("source_versions_json", sa.JSON(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(), nullable=True),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("job_run_id", BigInteger(), sa.ForeignKey("analysis_job_run.id"), nullable=True),
    ]


def _legacy_provenance_columns() -> list[sa.Column]:
    return [
        sa.Column("source_layer_code", sa.String(64), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=True),
        sa.Column("coverage_rate", sa.Numeric(5, 2), nullable=True),
        sa.Column("confidence_level", sa.String(32), nullable=True),
        sa.Column("not_computable_reasons_json", sa.JSON(), nullable=True),
        sa.Column("uncertainty_reasons_json", sa.JSON(), nullable=True),
        sa.Column("source_versions_json", sa.JSON(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(), nullable=True),
    ]


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


def _seed_round9_dicts() -> None:
    _seed_dict(
        "ANALYSIS_FACT_TYPE",
        "分析事实类型",
        [
            _dict_item("VESSEL_ASSET", "船舶资产事实", color="primary", sort_order=10),
            _dict_item("AIS_FRESHNESS", "AIS 新鲜度事实", color="primary", sort_order=20),
            _dict_item("TRAJECTORY", "轨迹事实", color="success", sort_order=30),
            _dict_item("NODE", "节点观测事实", color="success", sort_order=40),
            _dict_item("ROUTE_SEGMENT", "航段观测事实", color="success", sort_order=50),
            _dict_item("QUALITY", "质量事实", color="warning", sort_order=60),
            _dict_item("RISK", "风险事实", color="danger", sort_order=70),
            _dict_item("CANDIDATE_FIT", "候选适配事实", color="info", sort_order=80),
            _dict_item("SUPPLY_DEMAND", "区域供需事实", color="info", sort_order=90),
        ],
        470,
    )
    _seed_dict(
        "ANALYSIS_SOURCE_LAYER",
        "分析来源层级",
        [
            _dict_item("VESSEL_PROFILE_SUMMARY", "船舶资产摘要", color="primary", sort_order=10),
            _dict_item("AIS_SNAPSHOT", "AIS 快照", color="primary", sort_order=20),
            _dict_item("SPATIAL_OBSERVATION", "空间观测快照", color="success", sort_order=30),
            _dict_item("QUALITY_ISSUE", "质量问题", color="warning", sort_order=40),
            _dict_item("RISK_SIGNAL", "风险信号", color="danger", sort_order=50),
            _dict_item("CANDIDATE_ANALYSIS", "候选适配分析", color="info", sort_order=60),
            _dict_item("STANDARD_FREIGHT_SAMPLE", "标准货源样本", color="primary", sort_order=70),
            _dict_item("REGION_SUPPLY_DEMAND", "区域供需分层", color="info", sort_order=80),
            _dict_item("LOCAL_SAMPLE", "本地样例", color="warning", sort_order=90),
            _dict_item("NOT_AVAILABLE", "来源不可用", color="danger", sort_order=100),
        ],
        471,
    )
    _seed_dict(
        "ANALYSIS_NOT_COMPUTABLE_REASON",
        "分析不可计算原因",
        [
            _dict_item("SOURCE_MISSING", "来源缺失", color="warning", sort_order=10),
            _dict_item("COVERAGE_TOO_LOW", "覆盖率过低", color="warning", sort_order=20),
            _dict_item("HISTORICAL_AIS_UNCONFIGURED", "历史 AIS 未配置", color="info", sort_order=30),
            _dict_item("EXTERNAL_RESULT_MISSING", "外部结果缺失", color="info", sort_order=40),
            _dict_item("RISK_RULE_NOT_RUN", "风险规则未运行", color="warning", sort_order=50),
            _dict_item("NO_ANALYSIS_SAMPLE", "无分析样本", color="info", sort_order=60),
            _dict_item("DEMAND_LAYER_MISSING", "需求层缺失", color="warning", sort_order=70),
            _dict_item("SUPPLY_LAYER_MISSING", "供给层缺失", color="warning", sort_order=80),
            _dict_item("PROFILE_COVERAGE_GAP", "档案覆盖缺口", color="warning", sort_order=90),
        ],
        472,
    )
    _seed_dict(
        "ANALYSIS_DEMAND_LAYER",
        "分析需求层级",
        [
            _dict_item("FREIGHT_CLUE", "货源线索", color="info", sort_order=10),
            _dict_item("STANDARD_FREIGHT_SAMPLE", "标准货源样本", color="primary", is_default=True, sort_order=20),
            _dict_item("HISTORICAL_BUSINESS_SAMPLE", "历史业务样本", color="warning", sort_order=30),
            _dict_item("EXTERNAL_TMS", "外部 TMS", color="success", sort_order=40),
            _dict_item("NOT_AVAILABLE", "不可用", color="danger", sort_order=50),
        ],
        473,
    )
    _seed_dict(
        "ANALYSIS_SUPPLY_LAYER",
        "分析供给层级",
        [
            _dict_item("AIS_SUPPLY_SAMPLE", "AIS 供给样本", color="primary", is_default=True, sort_order=10),
            _dict_item("TRUSTED_PROFILE_SAMPLE", "可信档案样本", color="success", sort_order=20),
            _dict_item("ACTIVE_VESSEL_SAMPLE", "活跃船舶样本", color="primary", sort_order=30),
            _dict_item("LOW_RISK_SAMPLE", "低风险样本", color="success", sort_order=40),
            _dict_item("NOT_AVAILABLE", "不可用", color="danger", sort_order=50),
        ],
        474,
    )

    if _has_table("std_dict") and _has_table("std_dict_item"):
        bind = op.get_bind()
        dict_row = bind.execute(
            sa.text("select id from std_dict where dict_code = 'VESSEL_AIS_FRESHNESS_LEVEL'")
        ).first()
        if dict_row is not None:
            updates = {
                "FRESH": "2 小时内",
                "RECENT": "2-12 小时",
                "STALE": "12-72 小时",
                "EXPIRED": "超过 72 小时",
            }
            for item_code, item_name in updates.items():
                bind.execute(
                    sa.text(
                        "update std_dict_item set item_name = :name where dict_id = :dict_id and item_code = :code"
                    ),
                    {"name": item_name, "dict_id": dict_row[0], "code": item_code},
                )


def _create_fact_tables() -> None:
    if not _has_table("fact_vessel_asset_daily"):
        op.create_table(
            "fact_vessel_asset_daily",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("stat_date", sa.Date(), nullable=False),
            sa.Column("ship_type_code", sa.String(64), nullable=True),
            sa.Column("quality_level", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("risk_level", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("profile_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("trusted_profile_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("low_quality_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("active_sample_count", sa.Integer(), nullable=False, server_default="0"),
            *_provenance_columns("VESSEL_PROFILE_SUMMARY"),
        )
    if not _has_table("fact_vessel_ais_freshness_daily"):
        op.create_table(
            "fact_vessel_ais_freshness_daily",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("stat_date", sa.Date(), nullable=False),
            sa.Column("city_code", sa.String(12), nullable=True),
            sa.Column("city_name", sa.String(128), nullable=True),
            sa.Column("ship_type_code", sa.String(64), nullable=True),
            sa.Column("freshness_level", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("match_status_code", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("vessel_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("matched_profile_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unmatched_mmsi_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("invalid_position_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("source_snapshot_id", sa.String(64), sa.ForeignKey("vessel_ais_snapshot.snapshot_id"), nullable=True),
            *_provenance_columns("AIS_SNAPSHOT"),
        )
    if not _has_table("fact_vessel_trajectory_daily"):
        op.create_table(
            "fact_vessel_trajectory_daily",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("stat_date", sa.Date(), nullable=False),
            sa.Column("vessel_profile_id", BigInteger(), sa.ForeignKey("vessel_profile.id"), nullable=True),
            sa.Column("mmsi", sa.String(16), nullable=True),
            sa.Column("ship_type_code", sa.String(64), nullable=True),
            sa.Column("track_coverage_rate", sa.Numeric(5, 2), nullable=True),
            sa.Column("gap_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("anomaly_point_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("stay_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("route_match_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("latest_position_time", sa.DateTime(), nullable=True),
            *_provenance_columns("SPATIAL_OBSERVATION"),
        )
    if not _has_table("fact_vessel_node_daily"):
        op.create_table(
            "fact_vessel_node_daily",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("stat_date", sa.Date(), nullable=False),
            sa.Column("node_id", BigInteger(), sa.ForeignKey("transport_node.id"), nullable=True),
            sa.Column("node_name", sa.String(128), nullable=True),
            sa.Column("city_code", sa.String(12), nullable=True),
            sa.Column("radius_km", sa.Numeric(8, 2), nullable=True),
            sa.Column("ship_type_code", sa.String(64), nullable=True),
            sa.Column("deadweight_bucket_code", sa.String(64), nullable=True),
            sa.Column("active_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("stay_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("passby_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("low_confidence_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("source_spatial_snapshot_id", sa.String(64), sa.ForeignKey("vessel_spatial_observation_snapshot.snapshot_id"), nullable=True),
            *_provenance_columns("SPATIAL_OBSERVATION"),
        )
    if not _has_table("fact_vessel_route_segment_daily"):
        op.create_table(
            "fact_vessel_route_segment_daily",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("stat_date", sa.Date(), nullable=False),
            sa.Column("route_id", BigInteger(), sa.ForeignKey("shipping_route.id"), nullable=True),
            sa.Column("line_id", BigInteger(), sa.ForeignKey("shipping_route_line.id"), nullable=True),
            sa.Column("route_segment_id", BigInteger(), sa.ForeignKey("shipping_route_line_segment.id"), nullable=True),
            sa.Column("segment_name", sa.String(128), nullable=True),
            sa.Column("direction_code", sa.String(32), nullable=True),
            sa.Column("ship_type_code", sa.String(64), nullable=True),
            sa.Column("matched_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reliable_match_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("covered_ratio", sa.Numeric(5, 2), nullable=True),
            sa.Column("avg_direction_consistency", sa.Numeric(5, 2), nullable=True),
            sa.Column("gap_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("low_confidence_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("source_spatial_snapshot_id", sa.String(64), sa.ForeignKey("vessel_spatial_observation_snapshot.snapshot_id"), nullable=True),
            *_provenance_columns("SPATIAL_OBSERVATION"),
        )
    if not _has_table("fact_vessel_quality_daily"):
        op.create_table(
            "fact_vessel_quality_daily",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("stat_date", sa.Date(), nullable=False),
            sa.Column("issue_type_code", sa.String(64), nullable=False),
            sa.Column("severity_code", sa.String(32), nullable=False),
            sa.Column("status_code", sa.String(32), nullable=False),
            sa.Column("opened_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("closed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("resolved_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("voided_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("avg_close_hours", sa.Numeric(10, 2), nullable=True),
            *_provenance_columns("QUALITY_ISSUE"),
        )
    if not _has_table("fact_vessel_risk_daily"):
        op.create_table(
            "fact_vessel_risk_daily",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("stat_date", sa.Date(), nullable=False),
            sa.Column("risk_type_code", sa.String(64), nullable=False),
            sa.Column("risk_level", sa.String(32), nullable=False, server_default="UNKNOWN"),
            sa.Column("status_code", sa.String(32), nullable=False),
            sa.Column("risk_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unknown_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("closed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("high_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("avg_close_hours", sa.Numeric(10, 2), nullable=True),
            *_provenance_columns("RISK_SIGNAL"),
        )
    if not _has_table("fact_candidate_fit_daily"):
        op.create_table(
            "fact_candidate_fit_daily",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("stat_date", sa.Date(), nullable=False),
            sa.Column("context_type_code", sa.String(32), nullable=False),
            sa.Column("candidate_value_level", sa.String(32), nullable=False, server_default="LOW"),
            sa.Column("analysis_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("candidate_item_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("not_computable_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("low_confidence_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("annotation_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("annotation_distribution_json", sa.JSON(), nullable=True),
            sa.Column("risk_reason_distribution_json", sa.JSON(), nullable=True),
            sa.Column("avg_fit_score", sa.Numeric(8, 2), nullable=True),
            sa.Column("avg_coverage_rate", sa.Numeric(5, 2), nullable=True),
            *_provenance_columns("CANDIDATE_ANALYSIS"),
        )
    if not _has_table("fact_region_supply_demand_daily"):
        op.create_table(
            "fact_region_supply_demand_daily",
            sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("stat_date", sa.Date(), nullable=False),
            sa.Column("region_id", BigInteger(), sa.ForeignKey("region.id"), nullable=True),
            sa.Column("city_code", sa.String(12), nullable=True),
            sa.Column("cargo_category_code", sa.String(64), nullable=True),
            sa.Column("ship_type_code", sa.String(64), nullable=True),
            sa.Column("demand_layer_code", sa.String(64), nullable=False, server_default="STANDARD_FREIGHT_SAMPLE"),
            sa.Column("supply_layer_code", sa.String(64), nullable=False, server_default="AIS_SUPPLY_SAMPLE"),
            sa.Column("demand_sample_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("demand_tonnage", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("ais_supply_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("trusted_profile_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("low_risk_supply_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unmatched_mmsi_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("trusted_supply", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("tension_index", sa.Numeric(10, 4), nullable=True),
            *_provenance_columns("REGION_SUPPLY_DEMAND"),
        )


def _create_indexes() -> None:
    for table, columns in {
        "fact_vessel_asset_daily": ["stat_date", "ship_type_code", "quality_level", "risk_level", "source_layer_code", "confidence_level", "job_run_id"],
        "fact_vessel_ais_freshness_daily": ["stat_date", "city_code", "ship_type_code", "freshness_level", "match_status_code", "source_snapshot_id", "source_layer_code", "confidence_level", "job_run_id"],
        "fact_vessel_trajectory_daily": ["stat_date", "vessel_profile_id", "mmsi", "ship_type_code", "source_layer_code", "confidence_level", "job_run_id"],
        "fact_vessel_node_daily": ["stat_date", "node_id", "city_code", "ship_type_code", "deadweight_bucket_code", "source_spatial_snapshot_id", "source_layer_code", "confidence_level", "job_run_id"],
        "fact_vessel_route_segment_daily": ["stat_date", "route_id", "line_id", "route_segment_id", "direction_code", "ship_type_code", "source_spatial_snapshot_id", "source_layer_code", "confidence_level", "job_run_id"],
        "fact_vessel_quality_daily": ["stat_date", "issue_type_code", "severity_code", "status_code", "source_layer_code", "confidence_level", "job_run_id"],
        "fact_vessel_risk_daily": ["stat_date", "risk_type_code", "risk_level", "status_code", "source_layer_code", "confidence_level", "job_run_id"],
        "fact_candidate_fit_daily": ["stat_date", "context_type_code", "candidate_value_level", "source_layer_code", "confidence_level", "job_run_id"],
        "fact_region_supply_demand_daily": ["stat_date", "region_id", "city_code", "cargo_category_code", "ship_type_code", "demand_layer_code", "supply_layer_code", "source_layer_code", "confidence_level", "job_run_id"],
    }.items():
        for column in columns:
            _create_index_if_missing(table, f"ix_{table}_{column}", [column])


def upgrade() -> None:
    for table in ("fact_ship_daily", "fact_ship_city_daily", "fact_ship_flow_daily", "fact_region_daily"):
        for column in _legacy_provenance_columns():
            _add_column_if_missing(table, column)
        _create_index_if_missing(table, f"ix_{table}_source_layer_code", ["source_layer_code"])
        _create_index_if_missing(table, f"ix_{table}_confidence_level", ["confidence_level"])
    _create_fact_tables()
    _create_indexes()
    _seed_round9_dicts()


def downgrade() -> None:
    for table in (
        "fact_region_supply_demand_daily",
        "fact_candidate_fit_daily",
        "fact_vessel_risk_daily",
        "fact_vessel_quality_daily",
        "fact_vessel_route_segment_daily",
        "fact_vessel_node_daily",
        "fact_vessel_trajectory_daily",
        "fact_vessel_ais_freshness_daily",
        "fact_vessel_asset_daily",
    ):
        if _has_table(table):
            op.drop_table(table)
    for table in ("fact_ship_daily", "fact_ship_city_daily", "fact_ship_flow_daily", "fact_region_daily"):
        _drop_index_if_exists(table, f"ix_{table}_source_layer_code")
        _drop_index_if_exists(table, f"ix_{table}_confidence_level")
        for column_name in (
            "source_layer_code",
            "sample_count",
            "coverage_rate",
            "confidence_level",
            "not_computable_reasons_json",
            "uncertainty_reasons_json",
            "source_versions_json",
            "source_updated_at",
        ):
            _drop_column_if_exists(table, column_name)
