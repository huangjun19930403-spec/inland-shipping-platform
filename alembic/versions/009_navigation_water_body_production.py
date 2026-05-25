"""navigation_water_body_production

Revision ID: 009_navigation_water_body_production
Revises: 008_navigation_water_body_assets
Create Date: 2026-05-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "009_navigation_water_body_production"
down_revision: Union[str, None] = "008_navigation_water_body_assets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("navigation_water_body", sa.Column("display_name", sa.String(length=128), nullable=True))
    op.add_column("navigation_water_body", sa.Column("production_name", sa.String(length=128), nullable=True))
    op.add_column(
        "navigation_water_body",
        sa.Column("name_status_code", sa.String(length=64), nullable=False, server_default="RAW_NAMED"),
    )
    op.add_column("navigation_water_body", sa.Column("name_source_code", sa.String(length=64), nullable=True))
    op.add_column("navigation_water_body", sa.Column("name_note", sa.String(length=512), nullable=True))
    op.create_index("ix_navigation_water_body_display_name", "navigation_water_body", ["display_name"])
    op.create_index("ix_navigation_water_body_production_name", "navigation_water_body", ["production_name"])
    op.create_index("ix_navigation_water_body_name_status_code", "navigation_water_body", ["name_status_code"])
    op.create_index("ix_navigation_water_body_name_source_code", "navigation_water_body", ["name_source_code"])

    op.execute(
        """
        UPDATE navigation_water_body
        SET
            display_name = water_body_name,
            production_name = water_body_name,
            name_status_code = CASE
                WHEN water_body_name IS NULL
                  OR water_body_name = ''
                  OR water_body_name LIKE '未命名水域%%'
                THEN 'UNNAMED'
                ELSE 'RAW_NAMED'
            END,
            name_source_code = CASE
                WHEN water_body_name IS NULL
                  OR water_body_name = ''
                  OR water_body_name LIKE '未命名水域%%'
                THEN NULL
                ELSE 'REVIER_RAW'
            END
        """
    )

    op.create_table(
        "navigation_channel_water_body_match",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("water_body_id", sa.BigInteger(), nullable=False),
        sa.Column("match_batch_code", sa.String(length=96), nullable=False),
        sa.Column("match_type_code", sa.String(length=64), nullable=False),
        sa.Column("matched_term", sa.String(length=128), nullable=True),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence_code", sa.String(length=64), nullable=False, server_default="LOW_CONFIDENCE"),
        sa.Column("issue_codes", sa.JSON(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source_water_area_ids_json", sa.JSON(), nullable=True),
        sa.Column("source_trace_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["navigation_channel.id"]),
        sa.ForeignKeyConstraint(["water_body_id"], ["navigation_water_body.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "match_batch_code",
            "channel_id",
            "water_body_id",
            name="uk_navigation_channel_water_body_match_batch_channel_body",
        ),
    )
    op.create_index("ix_navigation_channel_water_body_match_channel_id", "navigation_channel_water_body_match", ["channel_id"])
    op.create_index("ix_navigation_channel_water_body_match_water_body_id", "navigation_channel_water_body_match", ["water_body_id"])
    op.create_index("ix_navigation_channel_water_body_match_match_batch_code", "navigation_channel_water_body_match", ["match_batch_code"])
    op.create_index("ix_navigation_channel_water_body_match_match_type_code", "navigation_channel_water_body_match", ["match_type_code"])
    op.create_index("ix_navigation_channel_water_body_match_matched_term", "navigation_channel_water_body_match", ["matched_term"])
    op.create_index("ix_navigation_channel_water_body_match_score", "navigation_channel_water_body_match", ["score"])
    op.create_index("ix_navigation_channel_water_body_match_confidence_code", "navigation_channel_water_body_match", ["confidence_code"])
    op.create_index("ix_navigation_channel_water_body_match_is_current", "navigation_channel_water_body_match", ["is_current"])
    op.create_index(
        "ix_navigation_channel_water_body_match_channel_current",
        "navigation_channel_water_body_match",
        ["channel_id", "is_current"],
    )
    op.create_index(
        "ix_navigation_channel_water_body_match_body_current",
        "navigation_channel_water_body_match",
        ["water_body_id", "is_current"],
    )


def downgrade() -> None:
    op.drop_index("ix_navigation_channel_water_body_match_body_current", table_name="navigation_channel_water_body_match")
    op.drop_index("ix_navigation_channel_water_body_match_channel_current", table_name="navigation_channel_water_body_match")
    op.drop_index("ix_navigation_channel_water_body_match_is_current", table_name="navigation_channel_water_body_match")
    op.drop_index("ix_navigation_channel_water_body_match_confidence_code", table_name="navigation_channel_water_body_match")
    op.drop_index("ix_navigation_channel_water_body_match_score", table_name="navigation_channel_water_body_match")
    op.drop_index("ix_navigation_channel_water_body_match_matched_term", table_name="navigation_channel_water_body_match")
    op.drop_index("ix_navigation_channel_water_body_match_match_type_code", table_name="navigation_channel_water_body_match")
    op.drop_index("ix_navigation_channel_water_body_match_match_batch_code", table_name="navigation_channel_water_body_match")
    op.drop_index("ix_navigation_channel_water_body_match_water_body_id", table_name="navigation_channel_water_body_match")
    op.drop_index("ix_navigation_channel_water_body_match_channel_id", table_name="navigation_channel_water_body_match")
    op.drop_table("navigation_channel_water_body_match")

    op.drop_index("ix_navigation_water_body_name_source_code", table_name="navigation_water_body")
    op.drop_index("ix_navigation_water_body_name_status_code", table_name="navigation_water_body")
    op.drop_index("ix_navigation_water_body_production_name", table_name="navigation_water_body")
    op.drop_index("ix_navigation_water_body_display_name", table_name="navigation_water_body")
    op.drop_column("navigation_water_body", "name_note")
    op.drop_column("navigation_water_body", "name_source_code")
    op.drop_column("navigation_water_body", "name_status_code")
    op.drop_column("navigation_water_body", "production_name")
    op.drop_column("navigation_water_body", "display_name")
