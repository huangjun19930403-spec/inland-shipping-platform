"""Add unified navigation route trajectory cache.

Revision ID: 016_navigation_route_trajectory_cache
Revises: 015_navigation_hifleet_route_cache
Create Date: 2026-06-03 01:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "016_navigation_route_trajectory_cache"
down_revision = "015_navigation_hifleet_route_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "navigation_route_trajectory_cache",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("route_key", sa.String(length=256), nullable=False),
        sa.Column("normalized_pair_key", sa.String(length=256), nullable=False),
        sa.Column("transport_mode_code", sa.String(length=64), nullable=False),
        sa.Column("planning_mode_code", sa.String(length=64), nullable=False),
        sa.Column("graph_version_id", sa.BigInteger(), nullable=True),
        sa.Column("graph_context_code", sa.String(length=64), nullable=True),
        sa.Column("vessel_profile_hash", sa.String(length=64), nullable=True),
        sa.Column("origin_ref_type_code", sa.String(length=64), nullable=True),
        sa.Column("origin_ref_id", sa.BigInteger(), nullable=True),
        sa.Column("origin_name", sa.String(length=128), nullable=True),
        sa.Column("origin_lng", sa.Numeric(24, 15), nullable=False),
        sa.Column("origin_lat", sa.Numeric(24, 15), nullable=False),
        sa.Column("destination_ref_type_code", sa.String(length=64), nullable=True),
        sa.Column("destination_ref_id", sa.BigInteger(), nullable=True),
        sa.Column("destination_name", sa.String(length=128), nullable=True),
        sa.Column("destination_lng", sa.Numeric(24, 15), nullable=False),
        sa.Column("destination_lat", sa.Numeric(24, 15), nullable=False),
        sa.Column("provider_code", sa.String(length=64), nullable=True),
        sa.Column("source_type_code", sa.String(length=64), nullable=True),
        sa.Column("engine_code", sa.String(length=64), nullable=True),
        sa.Column("cache_status_code", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.String(length=64), nullable=False),
        sa.Column("quality_code", sa.String(length=64), nullable=False),
        sa.Column("quality_score", sa.Integer(), nullable=True),
        sa.Column("geometry_json", sa.JSON(), nullable=True),
        sa.Column("geometry_hash", sa.String(length=64), nullable=True),
        sa.Column("distance_km", sa.Numeric(14, 4), nullable=True),
        sa.Column("estimated_duration_hour", sa.Numeric(12, 2), nullable=True),
        sa.Column("point_count", sa.Integer(), nullable=False),
        sa.Column("max_segment_km", sa.Numeric(12, 4), nullable=True),
        sa.Column("edge_ids", sa.JSON(), nullable=True),
        sa.Column("channel_ids", sa.JSON(), nullable=True),
        sa.Column("passed_node_ids", sa.JSON(), nullable=True),
        sa.Column("passed_lock_count", sa.Integer(), nullable=False),
        sa.Column("passed_bridge_count", sa.Integer(), nullable=False),
        sa.Column("issue_summary_json", sa.JSON(), nullable=True),
        sa.Column("validation_summary_json", sa.JSON(), nullable=True),
        sa.Column("own_algorithm_summary_json", sa.JSON(), nullable=True),
        sa.Column("hifleet_summary_json", sa.JSON(), nullable=True),
        sa.Column("hifleet_cache_id", sa.BigInteger(), nullable=True),
        sa.Column("original_route_request_id", sa.BigInteger(), nullable=True),
        sa.Column("original_route_result_id", sa.BigInteger(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("raw_request_json", sa.JSON(), nullable=True),
        sa.Column("raw_response_json", sa.JSON(), nullable=True),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["original_route_request_id"], ["navigation_route_request.id"]),
        sa.ForeignKeyConstraint(["original_route_result_id"], ["navigation_route_result.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("route_key", name="uk_navigation_route_trajectory_cache_key"),
    )
    op.create_index("ix_navigation_route_trajectory_cache_route_key", "navigation_route_trajectory_cache", ["route_key"])
    op.create_index("ix_navigation_route_trajectory_cache_pair", "navigation_route_trajectory_cache", ["normalized_pair_key"])
    op.create_index(
        "ix_navigation_route_trajectory_cache_origin",
        "navigation_route_trajectory_cache",
        ["origin_ref_type_code", "origin_ref_id"],
    )
    op.create_index(
        "ix_navigation_route_trajectory_cache_destination",
        "navigation_route_trajectory_cache",
        ["destination_ref_type_code", "destination_ref_id"],
    )
    op.create_index("ix_navigation_route_trajectory_cache_status", "navigation_route_trajectory_cache", ["cache_status_code"])
    op.create_index(
        "ix_navigation_route_trajectory_cache_provider",
        "navigation_route_trajectory_cache",
        ["provider_code", "source_type_code"],
    )
    for column in (
        "transport_mode_code",
        "planning_mode_code",
        "graph_version_id",
        "graph_context_code",
        "vessel_profile_hash",
        "origin_ref_type_code",
        "origin_ref_id",
        "destination_ref_type_code",
        "destination_ref_id",
        "provider_code",
        "source_type_code",
        "engine_code",
        "status_code",
        "quality_code",
        "quality_score",
        "geometry_hash",
        "hifleet_cache_id",
        "original_route_request_id",
        "original_route_result_id",
        "error_code",
    ):
        op.create_index(f"ix_navigation_route_trajectory_cache_{column}", "navigation_route_trajectory_cache", [column])


def downgrade() -> None:
    for column in reversed(
        (
            "transport_mode_code",
            "planning_mode_code",
            "graph_version_id",
            "graph_context_code",
            "vessel_profile_hash",
            "origin_ref_type_code",
            "origin_ref_id",
            "destination_ref_type_code",
            "destination_ref_id",
            "provider_code",
            "source_type_code",
            "engine_code",
            "status_code",
            "quality_code",
            "quality_score",
            "geometry_hash",
            "hifleet_cache_id",
            "original_route_request_id",
            "original_route_result_id",
            "error_code",
        )
    ):
        op.drop_index(f"ix_navigation_route_trajectory_cache_{column}", table_name="navigation_route_trajectory_cache")
    op.drop_index("ix_navigation_route_trajectory_cache_provider", table_name="navigation_route_trajectory_cache")
    op.drop_index("ix_navigation_route_trajectory_cache_status", table_name="navigation_route_trajectory_cache")
    op.drop_index("ix_navigation_route_trajectory_cache_destination", table_name="navigation_route_trajectory_cache")
    op.drop_index("ix_navigation_route_trajectory_cache_origin", table_name="navigation_route_trajectory_cache")
    op.drop_index("ix_navigation_route_trajectory_cache_pair", table_name="navigation_route_trajectory_cache")
    op.drop_index("ix_navigation_route_trajectory_cache_route_key", table_name="navigation_route_trajectory_cache")
    op.drop_table("navigation_route_trajectory_cache")
