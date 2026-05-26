"""Add navigation centerline segment table.

Revision ID: 012_navigation_centerline_segment
Revises: 011_navigation_boundary_source_trace
Create Date: 2026-05-26 17:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "012_navigation_centerline_segment"
down_revision = "011_navigation_boundary_source_trace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "navigation_centerline_segment",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("centerline_id", sa.BigInteger(), nullable=True),
        sa.Column("segment_no", sa.String(length=32), nullable=False),
        sa.Column("segment_name", sa.String(length=128), nullable=False),
        sa.Column("segment_status_code", sa.String(length=64), nullable=False),
        sa.Column("geometry_json", sa.JSON(), nullable=True),
        sa.Column("source_type_code", sa.String(length=64), nullable=False),
        sa.Column("quality_code", sa.String(length=64), nullable=False),
        sa.Column("length_m", sa.Numeric(14, 2), nullable=True),
        sa.Column("start_lng", sa.Numeric(24, 15), nullable=True),
        sa.Column("start_lat", sa.Numeric(24, 15), nullable=True),
        sa.Column("end_lng", sa.Numeric(24, 15), nullable=True),
        sa.Column("end_lat", sa.Numeric(24, 15), nullable=True),
        sa.Column("bbox_min_lng", sa.Numeric(24, 15), nullable=True),
        sa.Column("bbox_min_lat", sa.Numeric(24, 15), nullable=True),
        sa.Column("bbox_max_lng", sa.Numeric(24, 15), nullable=True),
        sa.Column("bbox_max_lat", sa.Numeric(24, 15), nullable=True),
        sa.Column("previous_segment_id", sa.BigInteger(), nullable=True),
        sa.Column("next_segment_id", sa.BigInteger(), nullable=True),
        sa.Column("start_connected_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("end_connected_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("issue_summary_json", sa.JSON(), nullable=True),
        sa.Column("validation_summary_json", sa.JSON(), nullable=True),
        sa.Column("source_trace_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["channel_id"], ["navigation_channel.id"]),
        sa.ForeignKeyConstraint(["centerline_id"], ["navigation_channel_centerline.id"]),
        sa.ForeignKeyConstraint(["previous_segment_id"], ["navigation_centerline_segment.id"]),
        sa.ForeignKeyConstraint(["next_segment_id"], ["navigation_centerline_segment.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_navigation_centerline_segment_channel_id", "navigation_centerline_segment", ["channel_id"])
    op.create_index("ix_navigation_centerline_segment_centerline_id", "navigation_centerline_segment", ["centerline_id"])
    op.create_index("ix_navigation_centerline_segment_segment_no", "navigation_centerline_segment", ["segment_no"])
    op.create_index(
        "ix_navigation_centerline_segment_channel_no",
        "navigation_centerline_segment",
        ["channel_id", "segment_no"],
    )
    op.create_index(
        "ix_navigation_centerline_segment_channel_status",
        "navigation_centerline_segment",
        ["channel_id", "segment_status_code"],
    )
    op.create_index(
        "ix_navigation_centerline_segment_source_type_code",
        "navigation_centerline_segment",
        ["source_type_code"],
    )
    op.create_index(
        "ix_navigation_centerline_segment_quality_code",
        "navigation_centerline_segment",
        ["quality_code"],
    )


def downgrade() -> None:
    op.drop_index("ix_navigation_centerline_segment_quality_code", table_name="navigation_centerline_segment")
    op.drop_index("ix_navigation_centerline_segment_source_type_code", table_name="navigation_centerline_segment")
    op.drop_index("ix_navigation_centerline_segment_channel_status", table_name="navigation_centerline_segment")
    op.drop_index("ix_navigation_centerline_segment_channel_no", table_name="navigation_centerline_segment")
    op.drop_index("ix_navigation_centerline_segment_segment_no", table_name="navigation_centerline_segment")
    op.drop_index("ix_navigation_centerline_segment_centerline_id", table_name="navigation_centerline_segment")
    op.drop_index("ix_navigation_centerline_segment_channel_id", table_name="navigation_centerline_segment")
    op.drop_table("navigation_centerline_segment")
