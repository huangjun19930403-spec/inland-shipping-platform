"""navigation_channel_water_area_match

Revision ID: 004_navigation_channel_water_area_match
Revises: 003_navigation_geometry_draft
Create Date: 2026-05-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "004_navigation_channel_water_area_match"
down_revision: Union[str, None] = "003_navigation_geometry_draft"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "navigation_channel_water_area_match",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("water_area_id", sa.BigInteger(), nullable=False),
        sa.Column("match_batch_code", sa.String(length=96), nullable=False),
        sa.Column("match_type_code", sa.String(length=64), nullable=False),
        sa.Column("matched_term", sa.String(length=128), nullable=True),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("confidence_code", sa.String(length=64), nullable=False),
        sa.Column("review_status_code", sa.String(length=64), nullable=False),
        sa.Column("issue_codes", sa.JSON(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("source_trace_json", sa.JSON(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["channel_id"], ["navigation_channel.id"]),
        sa.ForeignKeyConstraint(["water_area_id"], ["navigation_water_area.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "match_batch_code",
            "channel_id",
            "water_area_id",
            name="uk_navigation_channel_water_area_match_batch_channel_area",
        ),
    )
    op.create_index(
        "ix_navigation_channel_water_area_match_area_current",
        "navigation_channel_water_area_match",
        ["water_area_id", "is_current"],
    )
    op.create_index(
        "ix_navigation_channel_water_area_match_channel_current",
        "navigation_channel_water_area_match",
        ["channel_id", "is_current"],
    )
    op.create_index(
        "ix_navigation_channel_water_area_match_channel_id",
        "navigation_channel_water_area_match",
        ["channel_id"],
    )
    op.create_index(
        "ix_navigation_channel_water_area_match_confidence_code",
        "navigation_channel_water_area_match",
        ["confidence_code"],
    )
    op.create_index(
        "ix_navigation_channel_water_area_match_is_current",
        "navigation_channel_water_area_match",
        ["is_current"],
    )
    op.create_index(
        "ix_navigation_channel_water_area_match_match_batch_code",
        "navigation_channel_water_area_match",
        ["match_batch_code"],
    )
    op.create_index(
        "ix_navigation_channel_water_area_match_match_type_code",
        "navigation_channel_water_area_match",
        ["match_type_code"],
    )
    op.create_index(
        "ix_navigation_channel_water_area_match_matched_term",
        "navigation_channel_water_area_match",
        ["matched_term"],
    )
    op.create_index(
        "ix_navigation_channel_water_area_match_review_status_code",
        "navigation_channel_water_area_match",
        ["review_status_code"],
    )
    op.create_index(
        "ix_navigation_channel_water_area_match_score",
        "navigation_channel_water_area_match",
        ["score"],
    )
    op.create_index(
        "ix_navigation_channel_water_area_match_water_area_id",
        "navigation_channel_water_area_match",
        ["water_area_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_navigation_channel_water_area_match_water_area_id", table_name="navigation_channel_water_area_match")
    op.drop_index("ix_navigation_channel_water_area_match_score", table_name="navigation_channel_water_area_match")
    op.drop_index("ix_navigation_channel_water_area_match_review_status_code", table_name="navigation_channel_water_area_match")
    op.drop_index("ix_navigation_channel_water_area_match_matched_term", table_name="navigation_channel_water_area_match")
    op.drop_index("ix_navigation_channel_water_area_match_match_type_code", table_name="navigation_channel_water_area_match")
    op.drop_index("ix_navigation_channel_water_area_match_match_batch_code", table_name="navigation_channel_water_area_match")
    op.drop_index("ix_navigation_channel_water_area_match_is_current", table_name="navigation_channel_water_area_match")
    op.drop_index("ix_navigation_channel_water_area_match_confidence_code", table_name="navigation_channel_water_area_match")
    op.drop_index("ix_navigation_channel_water_area_match_channel_id", table_name="navigation_channel_water_area_match")
    op.drop_index("ix_navigation_channel_water_area_match_channel_current", table_name="navigation_channel_water_area_match")
    op.drop_index("ix_navigation_channel_water_area_match_area_current", table_name="navigation_channel_water_area_match")
    op.drop_table("navigation_channel_water_area_match")
