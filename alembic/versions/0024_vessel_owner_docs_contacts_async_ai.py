"""vessel_owner_docs_contacts_async_ai

Revision ID: 0024_vessel_owner_docs_contacts_async_ai
Revises: 0023_vessel_person_certificate_files_ai
Create Date: 2026-05-09 00:20:00.000000

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


revision: str = "0024_vessel_owner_docs_contacts_async_ai"
down_revision: Union[str, None] = "0023_vessel_person_certificate_files_ai"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return column in {item["name"] for item in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if _has_table("vessel_contact"):
        with op.batch_alter_table("vessel_contact") as batch_op:
            if not _has_column("vessel_contact", "contact_scope_code"):
                batch_op.add_column(sa.Column("contact_scope_code", sa.String(length=64), nullable=False, server_default="GENERAL"))
            if not _has_column("vessel_contact", "owner_period_id"):
                batch_op.add_column(sa.Column("owner_period_id", BigInteger(), nullable=True))
            if not _has_column("vessel_contact", "operator_period_id"):
                batch_op.add_column(sa.Column("operator_period_id", BigInteger(), nullable=True))
            if not _has_column("vessel_contact", "crew_assignment_id"):
                batch_op.add_column(sa.Column("crew_assignment_id", BigInteger(), nullable=True))
        with op.batch_alter_table("vessel_contact") as batch_op:
            if _has_column("vessel_contact", "contact_scope_code"):
                batch_op.alter_column("contact_scope_code", server_default=None)

    if not _has_table("vessel_owner_document"):
        op.create_table(
            "vessel_owner_document",
            sa.Column("id", BigInteger(), autoincrement=True, nullable=False),
            sa.Column("vessel_profile_id", BigInteger(), nullable=False),
            sa.Column("vessel_owner_period_id", BigInteger(), nullable=False),
            sa.Column("document_type_code", sa.String(length=64), nullable=False),
            sa.Column("storage_file_id", BigInteger(), nullable=False),
            sa.Column("file_name", sa.String(length=256), nullable=False),
            sa.Column("content_type", sa.String(length=128), nullable=False),
            sa.Column("file_size", BigInteger(), nullable=False),
            sa.Column("uploaded_by", BigInteger(), nullable=True),
            sa.Column("uploaded_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["storage_file_id"], ["storage_file.id"]),
            sa.ForeignKeyConstraint(["vessel_owner_period_id"], ["vessel_owner_period.id"]),
            sa.ForeignKeyConstraint(["vessel_profile_id"], ["vessel_profile.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_vessel_owner_document_storage_file_id", "vessel_owner_document", ["storage_file_id"])
        op.create_index("ix_vessel_owner_document_vessel_owner_period_id", "vessel_owner_document", ["vessel_owner_period_id"])
        op.create_index("ix_vessel_owner_document_vessel_profile_id", "vessel_owner_document", ["vessel_profile_id"])

    if not _has_table("vessel_owner_document_image_recognition"):
        op.create_table(
            "vessel_owner_document_image_recognition",
            sa.Column("id", BigInteger(), autoincrement=True, nullable=False),
            sa.Column("vessel_profile_id", BigInteger(), nullable=False),
            sa.Column("vessel_owner_period_id", BigInteger(), nullable=False),
            sa.Column("owner_document_id", BigInteger(), nullable=False),
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
            sa.ForeignKeyConstraint(["owner_document_id"], ["vessel_owner_document.id"]),
            sa.ForeignKeyConstraint(["storage_file_id"], ["storage_file.id"]),
            sa.ForeignKeyConstraint(["vessel_owner_period_id"], ["vessel_owner_period.id"]),
            sa.ForeignKeyConstraint(["vessel_profile_id"], ["vessel_profile.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_vessel_owner_document_image_recognition_owner_document_id", "vessel_owner_document_image_recognition", ["owner_document_id"])
        op.create_index("ix_vessel_owner_document_image_recognition_storage_file_id", "vessel_owner_document_image_recognition", ["storage_file_id"])
        op.create_index("ix_vessel_owner_document_image_recognition_vessel_owner_period_id", "vessel_owner_document_image_recognition", ["vessel_owner_period_id"])
        op.create_index("ix_vessel_owner_document_image_recognition_vessel_profile_id", "vessel_owner_document_image_recognition", ["vessel_profile_id"])

    if _has_table("vessel_contact") and _has_column("vessel_owner_period", "mobile_phone"):
        op.execute(
            """
            INSERT INTO vessel_contact (
                vessel_profile_id, contact_scope_code, owner_period_id, contact_name, contact_role_code,
                mobile_phone, is_primary, is_available, remark, created_at, updated_at
            )
            SELECT vessel_profile_id, 'OWNER', id, party_name, 'OWNER_CONTACT',
                   NULLIF(mobile_phone, ''), is_primary, 1, '由所有方联系电话迁移', created_at, updated_at
            FROM vessel_owner_period
            WHERE NULLIF(mobile_phone, '') IS NOT NULL
            """
        )
    if _has_table("vessel_contact") and _has_column("vessel_operator_period", "contact_phone"):
        op.execute(
            """
            INSERT INTO vessel_contact (
                vessel_profile_id, contact_scope_code, operator_period_id, contact_name, contact_role_code,
                mobile_phone, is_primary, is_available, remark, created_at, updated_at
            )
            SELECT vessel_profile_id, 'OPERATOR', id, operator_name, 'OPERATOR_CONTACT',
                   NULLIF(contact_phone, ''), is_primary, 1, '由运营方联系电话迁移', created_at, updated_at
            FROM vessel_operator_period
            WHERE NULLIF(contact_phone, '') IS NOT NULL
            """
        )
    if _has_table("vessel_contact") and _has_column("vessel_crew_assignment", "mobile_phone"):
        op.execute(
            """
            INSERT INTO vessel_contact (
                vessel_profile_id, contact_scope_code, crew_assignment_id, contact_name, contact_role_code,
                mobile_phone, is_primary, is_available, remark, created_at, updated_at
            )
            SELECT vessel_profile_id, 'CREW', id, crew_name, 'CREW_CONTACT',
                   NULLIF(mobile_phone, ''), 0, 1, '由船员联系电话迁移', created_at, updated_at
            FROM vessel_crew_assignment
            WHERE NULLIF(mobile_phone, '') IS NOT NULL
            """
        )
    if _has_table("vessel_person_certificate") and _has_column("vessel_crew_assignment", "certificate_no"):
        op.execute(
            """
            INSERT INTO vessel_person_certificate (
                vessel_profile_id, crew_assignment_id, holder_name, certificate_type_code, certificate_no,
                verify_status_code, is_long_term_valid, remark, created_at, updated_at
            )
            SELECT vessel_profile_id, id, crew_name, 'CREW_COMPETENCY_CERT', NULLIF(certificate_no, ''),
                   'PENDING', 0, '由船员任职证书号迁移', created_at, updated_at
            FROM vessel_crew_assignment
            WHERE NULLIF(certificate_no, '') IS NOT NULL
            """
        )

    if _has_table("vessel_owner_period"):
        with op.batch_alter_table("vessel_owner_period") as batch_op:
            if _has_column("vessel_owner_period", "mobile_phone"):
                batch_op.drop_column("mobile_phone")
            if _has_column("vessel_owner_period", "landline_phone"):
                batch_op.drop_column("landline_phone")
    if _has_table("vessel_operator_period") and _has_column("vessel_operator_period", "contact_phone"):
        with op.batch_alter_table("vessel_operator_period") as batch_op:
            batch_op.drop_column("contact_phone")
    if _has_table("vessel_crew_assignment"):
        with op.batch_alter_table("vessel_crew_assignment") as batch_op:
            if _has_column("vessel_crew_assignment", "certificate_no"):
                batch_op.drop_column("certificate_no")
            if _has_column("vessel_crew_assignment", "mobile_phone"):
                batch_op.drop_column("mobile_phone")


def downgrade() -> None:
    if _has_table("vessel_owner_period"):
        with op.batch_alter_table("vessel_owner_period") as batch_op:
            if not _has_column("vessel_owner_period", "mobile_phone"):
                batch_op.add_column(sa.Column("mobile_phone", sa.String(length=32), nullable=True))
            if not _has_column("vessel_owner_period", "landline_phone"):
                batch_op.add_column(sa.Column("landline_phone", sa.String(length=32), nullable=True))
    if _has_table("vessel_operator_period") and not _has_column("vessel_operator_period", "contact_phone"):
        with op.batch_alter_table("vessel_operator_period") as batch_op:
            batch_op.add_column(sa.Column("contact_phone", sa.String(length=32), nullable=True))
    if _has_table("vessel_crew_assignment"):
        with op.batch_alter_table("vessel_crew_assignment") as batch_op:
            if not _has_column("vessel_crew_assignment", "certificate_no"):
                batch_op.add_column(sa.Column("certificate_no", sa.String(length=64), nullable=True))
            if not _has_column("vessel_crew_assignment", "mobile_phone"):
                batch_op.add_column(sa.Column("mobile_phone", sa.String(length=32), nullable=True))

    if _has_table("vessel_owner_document_image_recognition"):
        op.drop_index("ix_vessel_owner_document_image_recognition_vessel_profile_id", table_name="vessel_owner_document_image_recognition")
        op.drop_index("ix_vessel_owner_document_image_recognition_vessel_owner_period_id", table_name="vessel_owner_document_image_recognition")
        op.drop_index("ix_vessel_owner_document_image_recognition_storage_file_id", table_name="vessel_owner_document_image_recognition")
        op.drop_index("ix_vessel_owner_document_image_recognition_owner_document_id", table_name="vessel_owner_document_image_recognition")
        op.drop_table("vessel_owner_document_image_recognition")
    if _has_table("vessel_owner_document"):
        op.drop_index("ix_vessel_owner_document_vessel_profile_id", table_name="vessel_owner_document")
        op.drop_index("ix_vessel_owner_document_vessel_owner_period_id", table_name="vessel_owner_document")
        op.drop_index("ix_vessel_owner_document_storage_file_id", table_name="vessel_owner_document")
        op.drop_table("vessel_owner_document")
    if _has_table("vessel_contact"):
        with op.batch_alter_table("vessel_contact") as batch_op:
            if _has_column("vessel_contact", "crew_assignment_id"):
                batch_op.drop_column("crew_assignment_id")
            if _has_column("vessel_contact", "operator_period_id"):
                batch_op.drop_column("operator_period_id")
            if _has_column("vessel_contact", "owner_period_id"):
                batch_op.drop_column("owner_period_id")
            if _has_column("vessel_contact", "contact_scope_code"):
                batch_op.drop_column("contact_scope_code")
