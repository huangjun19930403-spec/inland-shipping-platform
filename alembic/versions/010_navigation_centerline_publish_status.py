"""navigation_centerline_publish_status

Revision ID: 010_navigation_centerline_publish_status
Revises: 009_navigation_water_body_production
Create Date: 2026-05-25 00:00:00.000000

This migration maps legacy APPROVED centerline rows to PUBLISHED after the
navigation production flow removed approval semantics. It is a production
publish-state compatibility migration, not an approval workflow decision.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "010_navigation_centerline_publish_status"
down_revision: Union[str, None] = "009_navigation_water_body_production"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE navigation_channel_centerline
        SET review_status_code = 'PUBLISHED'
        WHERE review_status_code = 'APPROVED'
          AND quality_code IN ('READY', 'READY_WITH_WARNING')
          AND is_current = true
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE navigation_channel_centerline
        SET review_status_code = 'APPROVED'
        WHERE review_status_code = 'PUBLISHED'
          AND source_type_code IN ('MANUAL', 'SEED_CENTERLINE', 'OSM_WATERWAY')
        """
    )
