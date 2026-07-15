"""widen freight candidate review text fields

Revision ID: 017_freight_candidate_long_text_fields
Revises: 016_navigation_route_trajectory_cache
Create Date: 2026-06-25 14:35:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "017_freight_candidate_long_text_fields"
down_revision = "016_navigation_route_trajectory_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "freight_candidate",
        "manual_review_reason",
        existing_type=sa.String(length=512),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "freight_candidate_manual_feedback",
        "feedback_remark",
        existing_type=sa.String(length=512),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "freight_candidate_manual_feedback",
        "feedback_remark",
        existing_type=sa.Text(),
        type_=sa.String(length=512),
        existing_nullable=True,
    )
    op.alter_column(
        "freight_candidate",
        "manual_review_reason",
        existing_type=sa.Text(),
        type_=sa.String(length=512),
        existing_nullable=True,
    )
