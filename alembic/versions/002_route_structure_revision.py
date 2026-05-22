"""add route plan structure revision

Revision ID: 002_route_structure_revision
Revises: 001_initial_schema
Create Date: 2026-05-20 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "002_route_structure_revision"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("shipping_route_plan") as batch_op:
        batch_op.add_column(sa.Column("structure_revision", sa.Integer(), nullable=False, server_default="1"))
        batch_op.create_index(batch_op.f("ix_shipping_route_plan_structure_revision"), ["structure_revision"])

    with op.batch_alter_table("shipping_route_plan_point") as batch_op:
        batch_op.add_column(sa.Column("structure_revision", sa.Integer(), nullable=False, server_default="1"))
        batch_op.drop_constraint("uk_route_plan_point_order", type_="unique")
        batch_op.create_unique_constraint(
            "uk_route_plan_point_order",
            ["plan_id", "structure_revision", "point_order"],
        )
        batch_op.create_index(batch_op.f("ix_shipping_route_plan_point_structure_revision"), ["structure_revision"])

    with op.batch_alter_table("shipping_route_plan_segment") as batch_op:
        batch_op.add_column(sa.Column("structure_revision", sa.Integer(), nullable=False, server_default="1"))
        batch_op.drop_constraint("uk_route_plan_segment_no", type_="unique")
        batch_op.create_unique_constraint(
            "uk_route_plan_segment_no",
            ["plan_id", "structure_revision", "segment_no"],
        )
        batch_op.create_index(batch_op.f("ix_shipping_route_plan_segment_structure_revision"), ["structure_revision"])

    with op.batch_alter_table("shipping_route_plan_track_version") as batch_op:
        batch_op.add_column(sa.Column("structure_revision", sa.Integer(), nullable=False, server_default="1"))
        batch_op.create_index(batch_op.f("ix_shipping_route_plan_track_version_structure_revision"), ["structure_revision"])


def downgrade() -> None:
    with op.batch_alter_table("shipping_route_plan_track_version") as batch_op:
        batch_op.drop_index(batch_op.f("ix_shipping_route_plan_track_version_structure_revision"))
        batch_op.drop_column("structure_revision")

    with op.batch_alter_table("shipping_route_plan_segment") as batch_op:
        batch_op.drop_index(batch_op.f("ix_shipping_route_plan_segment_structure_revision"))
        batch_op.drop_constraint("uk_route_plan_segment_no", type_="unique")
        batch_op.create_unique_constraint("uk_route_plan_segment_no", ["plan_id", "segment_no"])
        batch_op.drop_column("structure_revision")

    with op.batch_alter_table("shipping_route_plan_point") as batch_op:
        batch_op.drop_index(batch_op.f("ix_shipping_route_plan_point_structure_revision"))
        batch_op.drop_constraint("uk_route_plan_point_order", type_="unique")
        batch_op.create_unique_constraint("uk_route_plan_point_order", ["plan_id", "point_order"])
        batch_op.drop_column("structure_revision")

    with op.batch_alter_table("shipping_route_plan") as batch_op:
        batch_op.drop_index(batch_op.f("ix_shipping_route_plan_structure_revision"))
        batch_op.drop_column("structure_revision")
