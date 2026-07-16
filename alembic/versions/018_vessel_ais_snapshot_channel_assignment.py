"""persist AIS snapshot channel assignments

Revision ID: 018_vessel_ais_snapshot_channel_assignment
Revises: 017_freight_candidate_long_text_fields
Create Date: 2026-07-16 10:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "018_vessel_ais_snapshot_channel_assignment"
down_revision = "017_freight_candidate_long_text_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vessel_latest_position_snapshot",
        sa.Column("current_channel_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "vessel_latest_position_snapshot",
        sa.Column("current_channel_name", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "vessel_latest_position_snapshot",
        sa.Column("current_channel_source", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "vessel_latest_position_snapshot",
        sa.Column("channel_match_distance_m", sa.Numeric(precision=12, scale=2), nullable=True),
    )
    op.create_index(
        "ix_vessel_latest_position_snapshot_snapshot_channel",
        "vessel_latest_position_snapshot",
        ["snapshot_id", "current_channel_code"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_vessel_latest_position_snapshot_snapshot_channel",
        table_name="vessel_latest_position_snapshot",
    )
    op.drop_column("vessel_latest_position_snapshot", "channel_match_distance_m")
    op.drop_column("vessel_latest_position_snapshot", "current_channel_source")
    op.drop_column("vessel_latest_position_snapshot", "current_channel_name")
    op.drop_column("vessel_latest_position_snapshot", "current_channel_code")
