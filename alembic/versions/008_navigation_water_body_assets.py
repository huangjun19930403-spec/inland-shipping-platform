"""navigation_water_body_assets

Revision ID: 008_navigation_water_body_assets
Revises: 007_navigation_water_area_layer_metadata
Create Date: 2026-05-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "008_navigation_water_body_assets"
down_revision: Union[str, None] = "007_navigation_water_area_layer_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "navigation_water_body",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("water_body_code", sa.String(length=160), nullable=False),
        sa.Column("water_body_name", sa.String(length=128), nullable=True),
        sa.Column("normalized_water_name", sa.String(length=128), nullable=True),
        sa.Column("source_code", sa.String(length=64), nullable=False),
        sa.Column("body_role_code", sa.String(length=64), nullable=False),
        sa.Column("dedupe_status_code", sa.String(length=64), nullable=False),
        sa.Column("source_layer_code", sa.String(length=64), nullable=True),
        sa.Column("source_layer_name", sa.String(length=128), nullable=True),
        sa.Column("source_layer_display_name", sa.String(length=128), nullable=True),
        sa.Column("source_layer_role_code", sa.String(length=64), nullable=True),
        sa.Column("source_layer_order", sa.Integer(), nullable=True),
        sa.Column("water_level_min", sa.Integer(), nullable=True),
        sa.Column("water_level_max", sa.Integer(), nullable=True),
        sa.Column("water_type_code", sa.String(length=64), nullable=False),
        sa.Column("geometry_wgs84_json", sa.JSON(), nullable=True),
        sa.Column("geometry_gcj02_json", sa.JSON(), nullable=True),
        sa.Column("bbox_min_lng", sa.Numeric(24, 15), nullable=True),
        sa.Column("bbox_min_lat", sa.Numeric(24, 15), nullable=True),
        sa.Column("bbox_max_lng", sa.Numeric(24, 15), nullable=True),
        sa.Column("bbox_max_lat", sa.Numeric(24, 15), nullable=True),
        sa.Column("display_bbox_min_lng", sa.Numeric(24, 15), nullable=True),
        sa.Column("display_bbox_min_lat", sa.Numeric(24, 15), nullable=True),
        sa.Column("display_bbox_max_lng", sa.Numeric(24, 15), nullable=True),
        sa.Column("display_bbox_max_lat", sa.Numeric(24, 15), nullable=True),
        sa.Column("center_lng", sa.Numeric(24, 15), nullable=True),
        sa.Column("center_lat", sa.Numeric(24, 15), nullable=True),
        sa.Column("display_center_lng", sa.Numeric(24, 15), nullable=True),
        sa.Column("display_center_lat", sa.Numeric(24, 15), nullable=True),
        sa.Column("area_km2", sa.Numeric(18, 4), nullable=True),
        sa.Column("feature_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled_feature_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repaired_feature_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid_feature_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_layer_summary_json", sa.JSON(), nullable=True),
        sa.Column("source_water_area_ids_json", sa.JSON(), nullable=True),
        sa.Column("quality_code", sa.String(length=64), nullable=False, server_default="READY"),
        sa.Column("coordinate_system_code", sa.String(length=32), nullable=False, server_default="WGS84"),
        sa.Column("display_coordinate_system_code", sa.String(length=32), nullable=False, server_default="GCJ02_AMAP"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("water_body_code", name="uk_navigation_water_body_code"),
    )
    op.create_index("ix_navigation_water_body_body_role_code", "navigation_water_body", ["body_role_code"])
    op.create_index("ix_navigation_water_body_dedupe_status_code", "navigation_water_body", ["dedupe_status_code"])
    op.create_index("ix_navigation_water_body_is_enabled", "navigation_water_body", ["is_enabled"])
    op.create_index("ix_navigation_water_body_layer_order", "navigation_water_body", ["source_layer_order"])
    op.create_index("ix_navigation_water_body_name", "navigation_water_body", ["normalized_water_name"])
    op.create_index("ix_navigation_water_body_normalized_water_name", "navigation_water_body", ["normalized_water_name"])
    op.create_index("ix_navigation_water_body_quality_code", "navigation_water_body", ["quality_code"])
    op.create_index("ix_navigation_water_body_role_enabled", "navigation_water_body", ["body_role_code", "is_enabled"])
    op.create_index("ix_navigation_water_body_source_code", "navigation_water_body", ["source_code"])
    op.create_index("ix_navigation_water_body_source_layer_code", "navigation_water_body", ["source_layer_code"])
    op.create_index("ix_navigation_water_body_source_layer_name", "navigation_water_body", ["source_layer_name"])
    op.create_index("ix_navigation_water_body_source_layer_order", "navigation_water_body", ["source_layer_order"])
    op.create_index("ix_navigation_water_body_source_layer_role_code", "navigation_water_body", ["source_layer_role_code"])
    op.create_index("ix_navigation_water_body_water_body_code", "navigation_water_body", ["water_body_code"])
    op.create_index("ix_navigation_water_body_water_body_name", "navigation_water_body", ["water_body_name"])
    op.create_index("ix_navigation_water_body_water_level_max", "navigation_water_body", ["water_level_max"])
    op.create_index("ix_navigation_water_body_water_level_min", "navigation_water_body", ["water_level_min"])
    op.create_index("ix_navigation_water_body_water_type_code", "navigation_water_body", ["water_type_code"])

    op.create_table(
        "navigation_water_body_feature_link",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("water_body_id", sa.BigInteger(), nullable=False),
        sa.Column("water_area_id", sa.BigInteger(), nullable=False),
        sa.Column("link_role_code", sa.String(length=64), nullable=False),
        sa.Column("source_layer_name", sa.String(length=128), nullable=True),
        sa.Column("source_layer_code", sa.String(length=64), nullable=True),
        sa.Column("overlap_ratio", sa.Numeric(8, 6), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_trace_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["water_area_id"], ["navigation_water_area.id"]),
        sa.ForeignKeyConstraint(["water_body_id"], ["navigation_water_body.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("water_body_id", "water_area_id", name="uk_navigation_water_body_feature_link_body_area"),
    )
    op.create_index("ix_navigation_water_body_feature_link_area", "navigation_water_body_feature_link", ["water_area_id"])
    op.create_index("ix_navigation_water_body_feature_link_is_primary", "navigation_water_body_feature_link", ["is_primary"])
    op.create_index("ix_navigation_water_body_feature_link_link_role_code", "navigation_water_body_feature_link", ["link_role_code"])
    op.create_index("ix_navigation_water_body_feature_link_role", "navigation_water_body_feature_link", ["link_role_code"])
    op.create_index("ix_navigation_water_body_feature_link_source_layer_code", "navigation_water_body_feature_link", ["source_layer_code"])
    op.create_index("ix_navigation_water_body_feature_link_source_layer_name", "navigation_water_body_feature_link", ["source_layer_name"])
    op.create_index("ix_navigation_water_body_feature_link_water_area_id", "navigation_water_body_feature_link", ["water_area_id"])
    op.create_index("ix_navigation_water_body_feature_link_water_body_id", "navigation_water_body_feature_link", ["water_body_id"])


def downgrade() -> None:
    op.drop_index("ix_navigation_water_body_feature_link_water_body_id", table_name="navigation_water_body_feature_link")
    op.drop_index("ix_navigation_water_body_feature_link_water_area_id", table_name="navigation_water_body_feature_link")
    op.drop_index("ix_navigation_water_body_feature_link_source_layer_name", table_name="navigation_water_body_feature_link")
    op.drop_index("ix_navigation_water_body_feature_link_source_layer_code", table_name="navigation_water_body_feature_link")
    op.drop_index("ix_navigation_water_body_feature_link_role", table_name="navigation_water_body_feature_link")
    op.drop_index("ix_navigation_water_body_feature_link_link_role_code", table_name="navigation_water_body_feature_link")
    op.drop_index("ix_navigation_water_body_feature_link_is_primary", table_name="navigation_water_body_feature_link")
    op.drop_index("ix_navigation_water_body_feature_link_area", table_name="navigation_water_body_feature_link")
    op.drop_table("navigation_water_body_feature_link")

    op.drop_index("ix_navigation_water_body_water_type_code", table_name="navigation_water_body")
    op.drop_index("ix_navigation_water_body_water_level_min", table_name="navigation_water_body")
    op.drop_index("ix_navigation_water_body_water_level_max", table_name="navigation_water_body")
    op.drop_index("ix_navigation_water_body_water_body_name", table_name="navigation_water_body")
    op.drop_index("ix_navigation_water_body_water_body_code", table_name="navigation_water_body")
    op.drop_index("ix_navigation_water_body_source_layer_role_code", table_name="navigation_water_body")
    op.drop_index("ix_navigation_water_body_source_layer_order", table_name="navigation_water_body")
    op.drop_index("ix_navigation_water_body_source_layer_name", table_name="navigation_water_body")
    op.drop_index("ix_navigation_water_body_source_layer_code", table_name="navigation_water_body")
    op.drop_index("ix_navigation_water_body_source_code", table_name="navigation_water_body")
    op.drop_index("ix_navigation_water_body_role_enabled", table_name="navigation_water_body")
    op.drop_index("ix_navigation_water_body_quality_code", table_name="navigation_water_body")
    op.drop_index("ix_navigation_water_body_normalized_water_name", table_name="navigation_water_body")
    op.drop_index("ix_navigation_water_body_name", table_name="navigation_water_body")
    op.drop_index("ix_navigation_water_body_layer_order", table_name="navigation_water_body")
    op.drop_index("ix_navigation_water_body_is_enabled", table_name="navigation_water_body")
    op.drop_index("ix_navigation_water_body_dedupe_status_code", table_name="navigation_water_body")
    op.drop_index("ix_navigation_water_body_body_role_code", table_name="navigation_water_body")
    op.drop_table("navigation_water_body")
