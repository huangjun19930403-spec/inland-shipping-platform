"""vessel relation evidence attachments

Revision ID: 0036_vessel_relation_evidence_attachment
Revises: 0035_vessel_p0_governance_closure
Create Date: 2026-05-10
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import BigInteger


@compiles(BigInteger, "sqlite")
def _compile_bigint_sqlite(_type, _compiler, **_kw):
    return "INTEGER"


revision: str = "0036_vessel_relation_evidence_attachment"
down_revision: Union[str, None] = "0035_vessel_p0_governance_closure"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vessel_relation_evidence_attachment",
        sa.Column("id", BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("vessel_profile_id", BigInteger(), sa.ForeignKey("vessel_profile.id"), nullable=False),
        sa.Column("evidence_type_code", sa.String(length=64), nullable=False),
        sa.Column("evidence_id", BigInteger(), nullable=False),
        sa.Column("storage_file_id", BigInteger(), sa.ForeignKey("storage_file.id"), nullable=False),
        sa.Column("file_name", sa.String(length=256), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("file_size", BigInteger(), nullable=False),
        sa.Column("uploaded_by", BigInteger(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.Column("voided_by", BigInteger(), nullable=True),
        sa.Column("void_reason", sa.String(length=256), nullable=True),
    )
    op.create_index(
        "ix_vessel_relation_evidence_attachment_vessel_profile_id",
        "vessel_relation_evidence_attachment",
        ["vessel_profile_id"],
    )
    op.create_index(
        "ix_vessel_relation_evidence_attachment_object",
        "vessel_relation_evidence_attachment",
        ["evidence_type_code", "evidence_id"],
    )
    op.create_index(
        "ix_vessel_relation_evidence_attachment_storage_file_id",
        "vessel_relation_evidence_attachment",
        ["storage_file_id"],
    )
    op.create_index(
        "ux_vessel_relation_evidence_attachment_file",
        "vessel_relation_evidence_attachment",
        ["evidence_type_code", "evidence_id", "storage_file_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ux_vessel_relation_evidence_attachment_file", table_name="vessel_relation_evidence_attachment")
    op.drop_index("ix_vessel_relation_evidence_attachment_storage_file_id", table_name="vessel_relation_evidence_attachment")
    op.drop_index("ix_vessel_relation_evidence_attachment_object", table_name="vessel_relation_evidence_attachment")
    op.drop_index("ix_vessel_relation_evidence_attachment_vessel_profile_id", table_name="vessel_relation_evidence_attachment")
    op.drop_table("vessel_relation_evidence_attachment")
