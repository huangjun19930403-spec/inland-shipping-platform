"""vessel_person_certificate_files_ai

Revision ID: 0023_vessel_person_certificate_files_ai
Revises: 0022_vessel_business_model_cleanup
Create Date: 2026-05-08 23:50:00.000000

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


revision: str = "0023_vessel_person_certificate_files_ai"
down_revision: Union[str, None] = "0022_vessel_business_model_cleanup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return column in {item["name"] for item in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if _has_table("vessel_person_certificate"):
        with op.batch_alter_table("vessel_person_certificate") as batch_op:
            if not _has_column("vessel_person_certificate", "is_long_term_valid"):
                batch_op.add_column(
                    sa.Column("is_long_term_valid", sa.Boolean(), nullable=False, server_default=sa.false())
                )
            if not _has_column("vessel_person_certificate", "validity_text_raw"):
                batch_op.add_column(sa.Column("validity_text_raw", sa.String(length=256), nullable=True))
            if not _has_column("vessel_person_certificate", "structured_payload_json"):
                batch_op.add_column(sa.Column("structured_payload_json", sa.JSON(), nullable=True))
        with op.batch_alter_table("vessel_person_certificate") as batch_op:
            if _has_column("vessel_person_certificate", "is_long_term_valid"):
                batch_op.alter_column("is_long_term_valid", server_default=None)

    if not _has_table("vessel_person_certificate_file"):
        op.create_table(
            "vessel_person_certificate_file",
            sa.Column("id", BigInteger(), autoincrement=True, nullable=False),
            sa.Column("vessel_person_certificate_id", BigInteger(), nullable=False),
            sa.Column("storage_file_id", BigInteger(), nullable=False),
            sa.Column("file_name", sa.String(length=256), nullable=False),
            sa.Column("content_type", sa.String(length=128), nullable=False),
            sa.Column("file_size", BigInteger(), nullable=False),
            sa.Column("uploaded_by", BigInteger(), nullable=True),
            sa.Column("uploaded_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["storage_file_id"], ["storage_file.id"]),
            sa.ForeignKeyConstraint(["vessel_person_certificate_id"], ["vessel_person_certificate.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_vessel_person_certificate_file_storage_file_id",
            "vessel_person_certificate_file",
            ["storage_file_id"],
        )
        op.create_index(
            "ix_vessel_person_certificate_file_vessel_person_certificate_id",
            "vessel_person_certificate_file",
            ["vessel_person_certificate_id"],
        )

    if not _has_table("vessel_person_certificate_image_recognition"):
        op.create_table(
            "vessel_person_certificate_image_recognition",
            sa.Column("id", BigInteger(), autoincrement=True, nullable=False),
            sa.Column("vessel_profile_id", BigInteger(), nullable=False),
            sa.Column("vessel_person_certificate_id", BigInteger(), nullable=False),
            sa.Column("person_certificate_file_id", BigInteger(), nullable=False),
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
            sa.ForeignKeyConstraint(["person_certificate_file_id"], ["vessel_person_certificate_file.id"]),
            sa.ForeignKeyConstraint(["storage_file_id"], ["storage_file.id"]),
            sa.ForeignKeyConstraint(["vessel_person_certificate_id"], ["vessel_person_certificate.id"]),
            sa.ForeignKeyConstraint(["vessel_profile_id"], ["vessel_profile.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_vessel_person_certificate_image_recognition_person_certificate_file_id",
            "vessel_person_certificate_image_recognition",
            ["person_certificate_file_id"],
        )
        op.create_index(
            "ix_vessel_person_certificate_image_recognition_storage_file_id",
            "vessel_person_certificate_image_recognition",
            ["storage_file_id"],
        )
        op.create_index(
            "ix_vessel_person_certificate_image_recognition_vessel_person_certificate_id",
            "vessel_person_certificate_image_recognition",
            ["vessel_person_certificate_id"],
        )
        op.create_index(
            "ix_vessel_person_certificate_image_recognition_vessel_profile_id",
            "vessel_person_certificate_image_recognition",
            ["vessel_profile_id"],
        )


def downgrade() -> None:
    if _has_table("vessel_person_certificate_image_recognition"):
        op.drop_index(
            "ix_vessel_person_certificate_image_recognition_vessel_profile_id",
            table_name="vessel_person_certificate_image_recognition",
        )
        op.drop_index(
            "ix_vessel_person_certificate_image_recognition_vessel_person_certificate_id",
            table_name="vessel_person_certificate_image_recognition",
        )
        op.drop_index(
            "ix_vessel_person_certificate_image_recognition_storage_file_id",
            table_name="vessel_person_certificate_image_recognition",
        )
        op.drop_index(
            "ix_vessel_person_certificate_image_recognition_person_certificate_file_id",
            table_name="vessel_person_certificate_image_recognition",
        )
        op.drop_table("vessel_person_certificate_image_recognition")

    if _has_table("vessel_person_certificate_file"):
        op.drop_index(
            "ix_vessel_person_certificate_file_vessel_person_certificate_id",
            table_name="vessel_person_certificate_file",
        )
        op.drop_index(
            "ix_vessel_person_certificate_file_storage_file_id",
            table_name="vessel_person_certificate_file",
        )
        op.drop_table("vessel_person_certificate_file")

    if _has_table("vessel_person_certificate"):
        with op.batch_alter_table("vessel_person_certificate") as batch_op:
            if _has_column("vessel_person_certificate", "structured_payload_json"):
                batch_op.drop_column("structured_payload_json")
            if _has_column("vessel_person_certificate", "validity_text_raw"):
                batch_op.drop_column("validity_text_raw")
            if _has_column("vessel_person_certificate", "is_long_term_valid"):
                batch_op.drop_column("is_long_term_valid")
