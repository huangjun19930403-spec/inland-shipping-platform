"""Add navigation HiFleet route cache.

Revision ID: 015_navigation_hifleet_route_cache
Revises: 014_navigation_centerline_control_points
Create Date: 2026-06-02 11:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "015_navigation_hifleet_route_cache"
down_revision = "014_navigation_centerline_control_points"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "navigation_hifleet_route_cache",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("route_key", sa.String(length=192), nullable=False),
        sa.Column("normalized_pair_key", sa.String(length=192), nullable=False),
        sa.Column("provider_code", sa.String(length=64), nullable=False),
        sa.Column("transport_mode_code", sa.String(length=64), nullable=False),
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
        sa.Column("geometry_json", sa.JSON(), nullable=True),
        sa.Column("geometry_hash", sa.String(length=64), nullable=True),
        sa.Column("distance_km", sa.Numeric(14, 4), nullable=True),
        sa.Column("estimated_duration_hour", sa.Numeric(12, 2), nullable=True),
        sa.Column("point_count", sa.Integer(), nullable=False),
        sa.Column("provider_trace_id", sa.String(length=128), nullable=True),
        sa.Column("status_code", sa.String(length=64), nullable=False),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("raw_summary_json", sa.JSON(), nullable=True),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("route_key", name="uk_navigation_hifleet_route_cache_key"),
    )
    op.create_index("ix_navigation_hifleet_route_cache_route_key", "navigation_hifleet_route_cache", ["route_key"])
    op.create_index(
        "ix_navigation_hifleet_route_cache_pair",
        "navigation_hifleet_route_cache",
        ["normalized_pair_key"],
    )
    op.create_index(
        "ix_navigation_hifleet_route_cache_origin",
        "navigation_hifleet_route_cache",
        ["origin_ref_type_code", "origin_ref_id"],
    )
    op.create_index(
        "ix_navigation_hifleet_route_cache_destination",
        "navigation_hifleet_route_cache",
        ["destination_ref_type_code", "destination_ref_id"],
    )
    op.create_index("ix_navigation_hifleet_route_cache_status", "navigation_hifleet_route_cache", ["status_code"])
    op.create_index("ix_navigation_hifleet_route_cache_provider_code", "navigation_hifleet_route_cache", ["provider_code"])
    op.create_index(
        "ix_navigation_hifleet_route_cache_transport_mode_code",
        "navigation_hifleet_route_cache",
        ["transport_mode_code"],
    )
    op.create_index(
        "ix_navigation_hifleet_route_cache_origin_ref_type_code",
        "navigation_hifleet_route_cache",
        ["origin_ref_type_code"],
    )
    op.create_index(
        "ix_navigation_hifleet_route_cache_origin_ref_id",
        "navigation_hifleet_route_cache",
        ["origin_ref_id"],
    )
    op.create_index(
        "ix_navigation_hifleet_route_cache_destination_ref_type_code",
        "navigation_hifleet_route_cache",
        ["destination_ref_type_code"],
    )
    op.create_index(
        "ix_navigation_hifleet_route_cache_destination_ref_id",
        "navigation_hifleet_route_cache",
        ["destination_ref_id"],
    )
    op.create_index(
        "ix_navigation_hifleet_route_cache_geometry_hash",
        "navigation_hifleet_route_cache",
        ["geometry_hash"],
    )
    op.create_index(
        "ix_navigation_hifleet_route_cache_provider_trace_id",
        "navigation_hifleet_route_cache",
        ["provider_trace_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_navigation_hifleet_route_cache_provider_trace_id", table_name="navigation_hifleet_route_cache")
    op.drop_index("ix_navigation_hifleet_route_cache_geometry_hash", table_name="navigation_hifleet_route_cache")
    op.drop_index("ix_navigation_hifleet_route_cache_destination_ref_id", table_name="navigation_hifleet_route_cache")
    op.drop_index(
        "ix_navigation_hifleet_route_cache_destination_ref_type_code",
        table_name="navigation_hifleet_route_cache",
    )
    op.drop_index("ix_navigation_hifleet_route_cache_origin_ref_id", table_name="navigation_hifleet_route_cache")
    op.drop_index("ix_navigation_hifleet_route_cache_origin_ref_type_code", table_name="navigation_hifleet_route_cache")
    op.drop_index("ix_navigation_hifleet_route_cache_transport_mode_code", table_name="navigation_hifleet_route_cache")
    op.drop_index("ix_navigation_hifleet_route_cache_provider_code", table_name="navigation_hifleet_route_cache")
    op.drop_index("ix_navigation_hifleet_route_cache_status", table_name="navigation_hifleet_route_cache")
    op.drop_index("ix_navigation_hifleet_route_cache_destination", table_name="navigation_hifleet_route_cache")
    op.drop_index("ix_navigation_hifleet_route_cache_origin", table_name="navigation_hifleet_route_cache")
    op.drop_index("ix_navigation_hifleet_route_cache_pair", table_name="navigation_hifleet_route_cache")
    op.drop_index("ix_navigation_hifleet_route_cache_route_key", table_name="navigation_hifleet_route_cache")
    op.drop_table("navigation_hifleet_route_cache")
