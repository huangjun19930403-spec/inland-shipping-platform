"""phase1 schema alignment for standard-data + analysis platform

Revision ID: 0012
Revises: 0011
Create Date: 2026-03-19
"""
from __future__ import annotations

import json
from typing import Iterable

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def _to_id_list(value) -> list[int]:
    if value is None:
        return []
    if isinstance(value, list):
        return [int(v) for v in value if v is not None]
    if isinstance(value, str):
        try:
            data = json.loads(value)
            if isinstance(data, list):
                return [int(v) for v in data if v is not None]
        except Exception:
            return []
    return []


def _dedup(items: Iterable[int]) -> list[int]:
    out: list[int] = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def upgrade() -> None:
    bind = op.get_bind()

    # 1) 新增区域关系表
    op.create_table(
        "region_waterway_relation",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("region_id", sa.BigInteger(), nullable=False),
        sa.Column("waterway_id", sa.BigInteger(), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False, server_default="MAIN"),
        sa.Column("is_primary", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="RULE"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["region_id"], ["region.id"]),
        sa.ForeignKeyConstraint(["waterway_id"], ["waterway.id"]),
        sa.UniqueConstraint("region_id", "waterway_id", name="uk_region_waterway_relation"),
    )
    op.create_index("ix_region_waterway_region", "region_waterway_relation", ["region_id"])

    op.create_table(
        "region_city_relation",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("region_id", sa.BigInteger(), nullable=False),
        sa.Column("admin_region_id", sa.BigInteger(), nullable=False),
        sa.Column("relation_type", sa.String(length=32), nullable=False, server_default="COVERED"),
        sa.Column("is_primary", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="RULE"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["region_id"], ["region.id"]),
        sa.ForeignKeyConstraint(["admin_region_id"], ["admin_region.id"]),
        sa.UniqueConstraint("region_id", "admin_region_id", name="uk_region_city_relation"),
    )
    op.create_index("ix_region_city_region", "region_city_relation", ["region_id"])

    # 2) 增强 region_address_relation
    with op.batch_alter_table("region_address_relation") as batch:
        batch.add_column(sa.Column("relation_type", sa.String(length=32), nullable=False, server_default="PRIMARY"))
        batch.add_column(sa.Column("source", sa.String(length=32), nullable=False, server_default="RULE"))
    op.create_index("ix_region_address_node", "region_address_relation", ["transport_node_id"])

    # 3) transport_node 增加行政编码字段
    with op.batch_alter_table("transport_node") as batch:
        batch.add_column(sa.Column("province_code", sa.String(length=12), nullable=True))
        batch.add_column(sa.Column("city_code", sa.String(length=12), nullable=True))
        batch.add_column(sa.Column("district_code", sa.String(length=12), nullable=True))

    # 4) commodity_standard / alias 增强匹配字段
    with op.batch_alter_table("commodity_standard") as batch:
        batch.add_column(sa.Column("default_density", sa.DECIMAL(8, 4), nullable=True))
        batch.add_column(sa.Column("danger_level", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("common_unit", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("match_keywords", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("match_regex", sa.String(length=256), nullable=True))
        batch.add_column(sa.Column("source", sa.String(length=32), nullable=True, server_default="MANUAL"))
        batch.add_column(sa.Column("confidence", sa.DECIMAL(5, 2), nullable=True, server_default="100"))
        batch.add_column(sa.Column("is_ai_generated", sa.SmallInteger(), nullable=False, server_default="0"))

    with op.batch_alter_table("commodity_alias") as batch:
        batch.add_column(sa.Column("match_keywords", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("match_regex", sa.String(length=256), nullable=True))
        batch.add_column(sa.Column("source", sa.String(length=32), nullable=True, server_default="MANUAL"))
        batch.add_column(sa.Column("confidence", sa.DECIMAL(5, 2), nullable=True, server_default="100"))
        batch.add_column(sa.Column("is_ai_generated", sa.SmallInteger(), nullable=False, server_default="0"))

    # 5) vessel_dynamic 增加分析型字段
    with op.batch_alter_table("vessel_dynamic") as batch:
        batch.add_column(sa.Column("data_source", sa.String(length=32), nullable=False, server_default="AIS"))
        batch.add_column(sa.Column("reported_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("ingested_at", sa.DateTime(), nullable=True, server_default=sa.func.now()))
        batch.add_column(sa.Column("current_region_id", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("current_city_code", sa.String(length=12), nullable=True))
        batch.add_column(sa.Column("position_match_type", sa.String(length=32), nullable=True, server_default="UNKNOWN"))
        batch.add_column(sa.Column("position_match_distance_m", sa.DECIMAL(12, 2), nullable=True))

    # 6) cargo_freight 增加分析记录字段
    with op.batch_alter_table("cargo_freight") as batch:
        batch.add_column(sa.Column("record_source", sa.String(length=32), nullable=False, server_default="MANUAL"))
        batch.add_column(sa.Column("record_status", sa.String(length=32), nullable=False, server_default="ACTIVE"))
        batch.add_column(sa.Column("analysis_status", sa.String(length=32), nullable=False, server_default="READY"))
        batch.add_column(sa.Column("data_quality_score", sa.DECIMAL(5, 2), nullable=True))
        batch.add_column(sa.Column("location_match_score", sa.DECIMAL(5, 2), nullable=True))
        batch.add_column(sa.Column("commodity_match_score", sa.DECIMAL(5, 2), nullable=True))
        batch.add_column(sa.Column("is_test_data", sa.SmallInteger(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("is_long_term_info", sa.SmallInteger(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("source_message_time", sa.DateTime(), nullable=True))

    # 7) 路线分段表
    op.create_table(
        "shipping_route_path_segment",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("path_id", sa.BigInteger(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("segment_type", sa.String(length=32), nullable=False, server_default="WATERWAY"),
        sa.Column("from_node_id", sa.BigInteger(), nullable=True),
        sa.Column("to_node_id", sa.BigInteger(), nullable=True),
        sa.Column("distance_km", sa.DECIMAL(10, 2), nullable=True),
        sa.Column("estimated_duration_hours", sa.DECIMAL(8, 2), nullable=True),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["path_id"], ["shipping_route_path.id"]),
        sa.ForeignKeyConstraint(["from_node_id"], ["transport_node.id"]),
        sa.ForeignKeyConstraint(["to_node_id"], ["transport_node.id"]),
    )

    # 8) 数据回填：cargo_freight record 字段
    bind.execute(
        sa.text(
            """
            UPDATE cargo_freight
            SET record_source = COALESCE(source_type, 'MANUAL'),
                record_status = CASE
                    WHEN status IN ('CONFIRMED', 'PENDING') THEN 'ACTIVE'
                    ELSE 'INVALID'
                END,
                analysis_status = 'READY'
            """
        )
    )

    # 9) 数据回填：根据旧字段生成 region_address_relation
    rows = bind.execute(
        sa.text("SELECT id, region_id FROM transport_node WHERE region_id IS NOT NULL")
    ).fetchall()
    for node_id, region_id in rows:
        exists = bind.execute(
            sa.text(
                "SELECT 1 FROM region_address_relation WHERE region_id=:rid AND transport_node_id=:nid LIMIT 1"
            ),
            {"rid": region_id, "nid": node_id},
        ).fetchone()
        if not exists:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO region_address_relation
                    (region_id, transport_node_id, relation_type, is_primary, source, created_at, updated_at)
                    VALUES (:rid, :nid, 'PRIMARY', 1, 'SYNC', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """
                ),
                {"rid": region_id, "nid": node_id},
            )

    # 10) 数据回填：region JSON -> 关系表
    region_rows = bind.execute(
        sa.text("SELECT id, main_rivers, main_cities FROM region")
    ).fetchall()
    waterway_ids_exists = {
        row[0] for row in bind.execute(sa.text("SELECT id FROM waterway")).fetchall()
    }
    city_ids_exists = {
        row[0] for row in bind.execute(sa.text("SELECT id FROM admin_region")).fetchall()
    }
    for region_id, main_rivers, main_cities in region_rows:
        river_ids = _dedup(_to_id_list(main_rivers))
        city_ids = _dedup(_to_id_list(main_cities))

        for idx, waterway_id in enumerate(river_ids):
            if waterway_id not in waterway_ids_exists:
                continue
            bind.execute(
                sa.text(
                    """
                    INSERT INTO region_waterway_relation
                    (region_id, waterway_id, relation_type, is_primary, source, created_at, updated_at)
                    VALUES (:rid, :wid, 'MAIN', :is_primary, 'SYNC', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """
                ),
                {"rid": region_id, "wid": waterway_id, "is_primary": 1 if idx == 0 else 0},
            )

        for idx, city_id in enumerate(city_ids):
            if city_id not in city_ids_exists:
                continue
            bind.execute(
                sa.text(
                    """
                    INSERT INTO region_city_relation
                    (region_id, admin_region_id, relation_type, is_primary, source, created_at, updated_at)
                    VALUES (:rid, :cid, 'COVERED', :is_primary, 'SYNC', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """
                ),
                {"rid": region_id, "cid": city_id, "is_primary": 1 if idx == 0 else 0},
            )


def downgrade() -> None:
    op.drop_table("shipping_route_path_segment")

    with op.batch_alter_table("cargo_freight") as batch:
        batch.drop_column("source_message_time")
        batch.drop_column("is_long_term_info")
        batch.drop_column("is_test_data")
        batch.drop_column("commodity_match_score")
        batch.drop_column("location_match_score")
        batch.drop_column("data_quality_score")
        batch.drop_column("analysis_status")
        batch.drop_column("record_status")
        batch.drop_column("record_source")

    with op.batch_alter_table("vessel_dynamic") as batch:
        batch.drop_column("position_match_distance_m")
        batch.drop_column("position_match_type")
        batch.drop_column("current_city_code")
        batch.drop_column("current_region_id")
        batch.drop_column("ingested_at")
        batch.drop_column("reported_at")
        batch.drop_column("data_source")

    with op.batch_alter_table("commodity_alias") as batch:
        batch.drop_column("is_ai_generated")
        batch.drop_column("confidence")
        batch.drop_column("source")
        batch.drop_column("match_regex")
        batch.drop_column("match_keywords")

    with op.batch_alter_table("commodity_standard") as batch:
        batch.drop_column("is_ai_generated")
        batch.drop_column("confidence")
        batch.drop_column("source")
        batch.drop_column("match_regex")
        batch.drop_column("match_keywords")
        batch.drop_column("common_unit")
        batch.drop_column("danger_level")
        batch.drop_column("default_density")

    with op.batch_alter_table("transport_node") as batch:
        batch.drop_column("district_code")
        batch.drop_column("city_code")
        batch.drop_column("province_code")

    op.drop_index("ix_region_address_node", table_name="region_address_relation")
    with op.batch_alter_table("region_address_relation") as batch:
        batch.drop_column("source")
        batch.drop_column("relation_type")

    op.drop_index("ix_region_city_region", table_name="region_city_relation")
    op.drop_table("region_city_relation")

    op.drop_index("ix_region_waterway_region", table_name="region_waterway_relation")
    op.drop_table("region_waterway_relation")
