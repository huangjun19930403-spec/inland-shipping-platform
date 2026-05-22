"""navigation_geometry_draft

Revision ID: 003_navigation_geometry_draft
Revises: 002_navigation_engine_models
Create Date: 2026-05-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "003_navigation_geometry_draft"
down_revision: Union[str, None] = "002_navigation_engine_models"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "navigation_geometry_draft",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("draft_no", sa.String(length=96), nullable=False),
        sa.Column("draft_name", sa.String(length=128), nullable=True),
        sa.Column("draft_type_code", sa.String(length=64), nullable=False),
        sa.Column("geometry_type_code", sa.String(length=64), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=True),
        sa.Column("target_type_code", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.BigInteger(), nullable=True),
        sa.Column("geometry_json", sa.JSON(), nullable=False),
        sa.Column("source_type_code", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.String(length=64), nullable=False),
        sa.Column("quality_code", sa.String(length=64), nullable=False),
        sa.Column("review_comment", sa.String(length=512), nullable=True),
        sa.Column("publish_target_type_code", sa.String(length=64), nullable=True),
        sa.Column("publish_target_id", sa.BigInteger(), nullable=True),
        sa.Column("bbox_min_lng", sa.Numeric(precision=11, scale=8), nullable=True),
        sa.Column("bbox_min_lat", sa.Numeric(precision=10, scale=8), nullable=True),
        sa.Column("bbox_max_lng", sa.Numeric(precision=11, scale=8), nullable=True),
        sa.Column("bbox_max_lat", sa.Numeric(precision=10, scale=8), nullable=True),
        sa.Column("source_trace_json", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("submitted_by", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
        sa.Column("published_by", sa.BigInteger(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["channel_id"], ["navigation_channel.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_no", name="uk_navigation_geometry_draft_no"),
    )
    op.create_index("ix_navigation_geometry_draft_bbox", "navigation_geometry_draft", ["bbox_min_lng", "bbox_min_lat", "bbox_max_lng", "bbox_max_lat"])
    op.create_index("ix_navigation_geometry_draft_channel", "navigation_geometry_draft", ["channel_id"])
    op.create_index("ix_navigation_geometry_draft_created_by", "navigation_geometry_draft", ["created_by"])
    op.create_index("ix_navigation_geometry_draft_draft_no", "navigation_geometry_draft", ["draft_no"])
    op.create_index("ix_navigation_geometry_draft_publish_target", "navigation_geometry_draft", ["publish_target_type_code", "publish_target_id"])
    op.create_index("ix_navigation_geometry_draft_status", "navigation_geometry_draft", ["status_code"])
    op.create_index("ix_navigation_geometry_draft_target", "navigation_geometry_draft", ["target_type_code", "target_id"])
    op.create_index("ix_navigation_geometry_draft_type", "navigation_geometry_draft", ["draft_type_code", "geometry_type_code"])


def downgrade() -> None:
    op.drop_index("ix_navigation_geometry_draft_type", table_name="navigation_geometry_draft")
    op.drop_index("ix_navigation_geometry_draft_target", table_name="navigation_geometry_draft")
    op.drop_index("ix_navigation_geometry_draft_status", table_name="navigation_geometry_draft")
    op.drop_index("ix_navigation_geometry_draft_publish_target", table_name="navigation_geometry_draft")
    op.drop_index("ix_navigation_geometry_draft_draft_no", table_name="navigation_geometry_draft")
    op.drop_index("ix_navigation_geometry_draft_created_by", table_name="navigation_geometry_draft")
    op.drop_index("ix_navigation_geometry_draft_channel", table_name="navigation_geometry_draft")
    op.drop_index("ix_navigation_geometry_draft_bbox", table_name="navigation_geometry_draft")
    op.drop_table("navigation_geometry_draft")
