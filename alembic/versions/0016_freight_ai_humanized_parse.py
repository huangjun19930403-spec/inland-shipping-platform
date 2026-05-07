"""freight_ai_humanized_parse

Revision ID: 0016_freight_ai_humanized_parse
Revises: 0015_freight_normalization_task
Create Date: 2026-05-07 21:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016_freight_ai_humanized_parse"
down_revision: Union[str, None] = "0015_freight_normalization_task"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("freight_batch_task", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ai_pipeline_version", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("ai_semantic_map_json", sa.JSON(), nullable=True))

    with op.batch_alter_table("freight_clue", schema=None) as batch_op:
        batch_op.add_column(sa.Column("semantic_role_code", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("line_refs_json", sa.JSON(), nullable=True))

    with op.batch_alter_table("freight_candidate", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ai_understanding_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("ai_tool_match_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("ai_review_json", sa.JSON(), nullable=True))
        batch_op.add_column(
            sa.Column("ai_review_status_code", sa.String(length=64), nullable=False, server_default="PASS")
        )
        batch_op.create_index(batch_op.f("ix_freight_candidate_ai_review_status_code"), ["ai_review_status_code"])


def downgrade() -> None:
    with op.batch_alter_table("freight_candidate", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_freight_candidate_ai_review_status_code"))
        batch_op.drop_column("ai_review_status_code")
        batch_op.drop_column("ai_review_json")
        batch_op.drop_column("ai_tool_match_json")
        batch_op.drop_column("ai_understanding_json")

    with op.batch_alter_table("freight_clue", schema=None) as batch_op:
        batch_op.drop_column("line_refs_json")
        batch_op.drop_column("semantic_role_code")

    with op.batch_alter_table("freight_batch_task", schema=None) as batch_op:
        batch_op.drop_column("ai_semantic_map_json")
        batch_op.drop_column("ai_pipeline_version")
