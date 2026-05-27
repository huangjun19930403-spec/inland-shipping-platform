"""Add navigation centerline control point assets.

Revision ID: 014_navigation_centerline_control_points
Revises: 013_navigation_channel_segment_guide
Create Date: 2026-05-27 10:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "014_navigation_centerline_control_points"
down_revision = "013_navigation_channel_segment_guide"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "navigation_centerline_point_set",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("based_on_boundary_id", sa.BigInteger(), nullable=False),
        sa.Column("point_set_name", sa.String(length=128), nullable=True),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("status_code", sa.String(length=32), nullable=False),
        sa.Column("point_count", sa.Integer(), nullable=False),
        sa.Column("length_m", sa.Numeric(14, 2), nullable=True),
        sa.Column("bbox_min_lng", sa.Numeric(24, 15), nullable=True),
        sa.Column("bbox_min_lat", sa.Numeric(24, 15), nullable=True),
        sa.Column("bbox_max_lng", sa.Numeric(24, 15), nullable=True),
        sa.Column("bbox_max_lat", sa.Numeric(24, 15), nullable=True),
        sa.Column("generated_geometry_json", sa.JSON(), nullable=True),
        sa.Column("validation_summary_json", sa.JSON(), nullable=True),
        sa.Column("source_trace_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["based_on_boundary_id"], ["navigation_channel_boundary.id"]),
        sa.ForeignKeyConstraint(["channel_id"], ["navigation_channel.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_navigation_centerline_point_set_channel_id", "navigation_centerline_point_set", ["channel_id"])
    op.create_index(
        "ix_navigation_centerline_point_set_channel_status",
        "navigation_centerline_point_set",
        ["channel_id", "status_code"],
    )
    op.create_index(
        "ix_navigation_centerline_point_set_boundary",
        "navigation_centerline_point_set",
        ["based_on_boundary_id"],
    )
    op.create_index("ix_navigation_centerline_point_set_version_no", "navigation_centerline_point_set", ["version_no"])
    op.create_index("ix_navigation_centerline_point_set_status_code", "navigation_centerline_point_set", ["status_code"])

    op.create_table(
        "navigation_centerline_control_point",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("point_set_id", sa.BigInteger(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("longitude", sa.Numeric(24, 15), nullable=False),
        sa.Column("latitude", sa.Numeric(24, 15), nullable=False),
        sa.Column("point_type_code", sa.String(length=32), nullable=False),
        sa.Column("point_name", sa.String(length=128), nullable=True),
        sa.Column("source_trace_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["point_set_id"], ["navigation_centerline_point_set.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("point_set_id", "sequence_no", name="uk_navigation_centerline_control_point_seq"),
    )
    op.create_index(
        "ix_navigation_centerline_control_point_point_set",
        "navigation_centerline_control_point",
        ["point_set_id"],
    )
    op.create_index("ix_navigation_centerline_control_point_sequence_no", "navigation_centerline_control_point", ["sequence_no"])
    op.create_index(
        "ix_navigation_centerline_control_point_point_type_code",
        "navigation_centerline_control_point",
        ["point_type_code"],
    )


def downgrade() -> None:
    op.drop_index("ix_navigation_centerline_control_point_point_type_code", table_name="navigation_centerline_control_point")
    op.drop_index("ix_navigation_centerline_control_point_sequence_no", table_name="navigation_centerline_control_point")
    op.drop_index("ix_navigation_centerline_control_point_point_set", table_name="navigation_centerline_control_point")
    op.drop_table("navigation_centerline_control_point")
    op.drop_index("ix_navigation_centerline_point_set_status_code", table_name="navigation_centerline_point_set")
    op.drop_index("ix_navigation_centerline_point_set_version_no", table_name="navigation_centerline_point_set")
    op.drop_index("ix_navigation_centerline_point_set_boundary", table_name="navigation_centerline_point_set")
    op.drop_index("ix_navigation_centerline_point_set_channel_status", table_name="navigation_centerline_point_set")
    op.drop_index("ix_navigation_centerline_point_set_channel_id", table_name="navigation_centerline_point_set")
    op.drop_table("navigation_centerline_point_set")
