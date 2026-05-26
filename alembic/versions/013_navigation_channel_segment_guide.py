"""Add navigation channel guide geometry fields.

Revision ID: 013_navigation_channel_segment_guide
Revises: 012_navigation_centerline_segment
Create Date: 2026-05-26 22:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "013_navigation_channel_segment_guide"
down_revision = "012_navigation_centerline_segment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("navigation_channel_segment", sa.Column("guide_geometry_json", sa.JSON(), nullable=True))
    op.add_column("navigation_channel_segment", sa.Column("guide_source_type_code", sa.String(length=64), nullable=True))
    op.add_column("navigation_channel_segment", sa.Column("guide_quality_code", sa.String(length=64), nullable=True))
    op.add_column("navigation_channel_segment", sa.Column("guide_length_m", sa.Numeric(14, 2), nullable=True))
    op.add_column("navigation_channel_segment", sa.Column("guide_bbox_min_lng", sa.Numeric(24, 15), nullable=True))
    op.add_column("navigation_channel_segment", sa.Column("guide_bbox_min_lat", sa.Numeric(24, 15), nullable=True))
    op.add_column("navigation_channel_segment", sa.Column("guide_bbox_max_lng", sa.Numeric(24, 15), nullable=True))
    op.add_column("navigation_channel_segment", sa.Column("guide_bbox_max_lat", sa.Numeric(24, 15), nullable=True))
    op.add_column("navigation_channel_segment", sa.Column("guide_trace_json", sa.JSON(), nullable=True))
    op.create_index(
        "ix_navigation_channel_segment_guide_source_type_code",
        "navigation_channel_segment",
        ["guide_source_type_code"],
    )
    op.create_index(
        "ix_navigation_channel_segment_guide_quality_code",
        "navigation_channel_segment",
        ["guide_quality_code"],
    )


def downgrade() -> None:
    op.drop_index("ix_navigation_channel_segment_guide_quality_code", table_name="navigation_channel_segment")
    op.drop_index("ix_navigation_channel_segment_guide_source_type_code", table_name="navigation_channel_segment")
    op.drop_column("navigation_channel_segment", "guide_trace_json")
    op.drop_column("navigation_channel_segment", "guide_bbox_max_lat")
    op.drop_column("navigation_channel_segment", "guide_bbox_max_lng")
    op.drop_column("navigation_channel_segment", "guide_bbox_min_lat")
    op.drop_column("navigation_channel_segment", "guide_bbox_min_lng")
    op.drop_column("navigation_channel_segment", "guide_length_m")
    op.drop_column("navigation_channel_segment", "guide_quality_code")
    op.drop_column("navigation_channel_segment", "guide_source_type_code")
    op.drop_column("navigation_channel_segment", "guide_geometry_json")
