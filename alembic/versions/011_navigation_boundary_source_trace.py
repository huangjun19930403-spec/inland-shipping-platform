"""Add source trace to navigation channel boundary.

Revision ID: 011_navigation_boundary_source_trace
Revises: 010_navigation_centerline_publish_status
Create Date: 2026-05-26 10:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "011_navigation_boundary_source_trace"
down_revision = "010_navigation_centerline_publish_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("navigation_channel_boundary") as batch_op:
        batch_op.add_column(sa.Column("source_trace_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("navigation_channel_boundary") as batch_op:
        batch_op.drop_column("source_trace_json")
