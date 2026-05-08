"""vessel_party_type_and_image_ai

Revision ID: 0021_vessel_party_type_and_image_ai
Revises: 0020_vessel_module_rebuild
Create Date: 2026-05-08 18:30:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import BigInteger


@compiles(BigInteger, "sqlite")
def _compile_bigint_sqlite(_type, _compiler, **_kw):
    return "INTEGER"


revision: str = "0021_vessel_party_type_and_image_ai"
down_revision: Union[str, None] = "0020_vessel_module_rebuild"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return column in {item["name"] for item in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if _has_table("vessel_owner_period") and not _has_column("vessel_owner_period", "party_type_code"):
        with op.batch_alter_table("vessel_owner_period") as batch_op:
            batch_op.add_column(sa.Column("party_type_code", sa.String(length=64), nullable=False, server_default="UNKNOWN"))
        with op.batch_alter_table("vessel_owner_period") as batch_op:
            batch_op.alter_column("party_type_code", server_default=None)

    if _has_table("vessel_operator_period") and not _has_column("vessel_operator_period", "party_type_code"):
        with op.batch_alter_table("vessel_operator_period") as batch_op:
            batch_op.add_column(sa.Column("party_type_code", sa.String(length=64), nullable=False, server_default="UNKNOWN"))
        with op.batch_alter_table("vessel_operator_period") as batch_op:
            batch_op.alter_column("party_type_code", server_default=None)

    if not _has_table("vessel_certificate_image_recognition"):
        op.create_table(
            "vessel_certificate_image_recognition",
            sa.Column("id", BigInteger(), autoincrement=True, nullable=False),
            sa.Column("vessel_profile_id", BigInteger(), nullable=False),
            sa.Column("vessel_certificate_id", BigInteger(), nullable=False),
            sa.Column("certificate_file_id", BigInteger(), nullable=False),
            sa.Column("storage_file_id", BigInteger(), nullable=False),
            sa.Column("status_code", sa.String(length=64), nullable=False),
            sa.Column("provider_code", sa.String(length=64), nullable=True),
            sa.Column("model_name", sa.String(length=128), nullable=True),
            sa.Column("candidate_payload_json", sa.JSON(), nullable=True),
            sa.Column("confirmed_payload_json", sa.JSON(), nullable=True),
            sa.Column("raw_text", sa.Text(), nullable=True),
            sa.Column("raw_response_json", sa.JSON(), nullable=True),
            sa.Column("confidence_score", sa.Integer(), nullable=True),
            sa.Column("error_message", sa.String(length=512), nullable=True),
            sa.Column("created_by", BigInteger(), nullable=True),
            sa.Column("confirmed_by", BigInteger(), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["certificate_file_id"], ["vessel_certificate_file.id"]),
            sa.ForeignKeyConstraint(["storage_file_id"], ["storage_file.id"]),
            sa.ForeignKeyConstraint(["vessel_certificate_id"], ["vessel_certificate.id"]),
            sa.ForeignKeyConstraint(["vessel_profile_id"], ["vessel_profile.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_vessel_certificate_image_recognition_certificate_file_id", "vessel_certificate_image_recognition", ["certificate_file_id"])
        op.create_index("ix_vessel_certificate_image_recognition_storage_file_id", "vessel_certificate_image_recognition", ["storage_file_id"])
        op.create_index("ix_vessel_certificate_image_recognition_vessel_certificate_id", "vessel_certificate_image_recognition", ["vessel_certificate_id"])
        op.create_index("ix_vessel_certificate_image_recognition_vessel_profile_id", "vessel_certificate_image_recognition", ["vessel_profile_id"])


def downgrade() -> None:
    if _has_table("vessel_certificate_image_recognition"):
        op.drop_index("ix_vessel_certificate_image_recognition_vessel_profile_id", table_name="vessel_certificate_image_recognition")
        op.drop_index("ix_vessel_certificate_image_recognition_vessel_certificate_id", table_name="vessel_certificate_image_recognition")
        op.drop_index("ix_vessel_certificate_image_recognition_storage_file_id", table_name="vessel_certificate_image_recognition")
        op.drop_index("ix_vessel_certificate_image_recognition_certificate_file_id", table_name="vessel_certificate_image_recognition")
        op.drop_table("vessel_certificate_image_recognition")

    if _has_column("vessel_operator_period", "party_type_code"):
        with op.batch_alter_table("vessel_operator_period") as batch_op:
            batch_op.drop_column("party_type_code")
    if _has_column("vessel_owner_period", "party_type_code"):
        with op.batch_alter_table("vessel_owner_period") as batch_op:
            batch_op.drop_column("party_type_code")
