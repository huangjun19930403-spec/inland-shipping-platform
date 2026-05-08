"""vessel_certificate_ledger_refactor

Revision ID: 0025_vessel_certificate_ledger_refactor
Revises: 0024_vessel_owner_docs_contacts_async_ai
Create Date: 2026-05-08 17:40:00.000000

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


revision: str = "0025_vessel_certificate_ledger_refactor"
down_revision: Union[str, None] = "0024_vessel_owner_docs_contacts_async_ai"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return column in {item["name"] for item in inspect(op.get_bind()).get_columns(table)}


def _add_void_columns(table_name: str) -> None:
    if not _has_table(table_name):
        return
    with op.batch_alter_table(table_name) as batch_op:
        if not _has_column(table_name, "voided_at"):
            batch_op.add_column(sa.Column("voided_at", sa.DateTime(), nullable=True))
        if not _has_column(table_name, "voided_by"):
            batch_op.add_column(sa.Column("voided_by", BigInteger(), nullable=True))
        if not _has_column(table_name, "void_reason"):
            batch_op.add_column(sa.Column("void_reason", sa.String(length=256), nullable=True))


def _drop_void_columns(table_name: str) -> None:
    if not _has_table(table_name):
        return
    with op.batch_alter_table(table_name) as batch_op:
        if _has_column(table_name, "void_reason"):
            batch_op.drop_column("void_reason")
        if _has_column(table_name, "voided_by"):
            batch_op.drop_column("voided_by")
        if _has_column(table_name, "voided_at"):
            batch_op.drop_column("voided_at")


def upgrade() -> None:
    for table_name in (
        "vessel_certificate",
        "vessel_certificate_file",
        "vessel_person_certificate",
        "vessel_person_certificate_file",
        "vessel_owner_document",
    ):
        _add_void_columns(table_name)


def downgrade() -> None:
    for table_name in (
        "vessel_owner_document",
        "vessel_person_certificate_file",
        "vessel_person_certificate",
        "vessel_certificate_file",
        "vessel_certificate",
    ):
        _drop_void_columns(table_name)
