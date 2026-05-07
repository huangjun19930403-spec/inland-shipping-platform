"""node_contacts_photos_cos_storage

Revision ID: 0017_node_contacts_photos_cos_storage
Revises: 0016_freight_ai_humanized_parse
Create Date: 2026-05-07 23:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.types import BigInteger


@compiles(BigInteger, "sqlite")
def _compile_bigint_sqlite(_type, _compiler, **_kw):
    return "INTEGER"


revision: str = "0017_node_contacts_photos_cos_storage"
down_revision: Union[str, None] = "0016_freight_ai_humanized_parse"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "storage_file",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("bucket_name", sa.String(length=128), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("original_file_name", sa.String(length=256), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("storage_provider_code", sa.String(length=64), nullable=False),
        sa.Column("uploaded_by", sa.BigInteger(), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
    )

    op.create_table(
        "transport_node_contact",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("node_id", sa.BigInteger(), nullable=False),
        sa.Column("contact_name", sa.String(length=64), nullable=False),
        sa.Column("contact_type_code", sa.String(length=64), nullable=False),
        sa.Column("mobile_phone", sa.String(length=32), nullable=True),
        sa.Column("wechat", sa.String(length=64), nullable=True),
        sa.Column("email", sa.String(length=128), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("remark", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["node_id"], ["transport_node.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("transport_node_contact", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_transport_node_contact_node_id"), ["node_id"], unique=False)

    op.execute(
        """
        INSERT INTO transport_node_contact (
            node_id,
            contact_name,
            contact_type_code,
            mobile_phone,
            wechat,
            email,
            is_primary,
            remark,
            created_at,
            updated_at
        )
        SELECT
            node_id,
            CASE
                WHEN TRIM(COALESCE(contact_person, '')) <> '' THEN TRIM(contact_person)
                ELSE '节点联系人'
            END,
            'OPERATIONS',
            NULLIF(TRIM(COALESCE(contact_phone, '')), ''),
            NULL,
            NULL,
            1,
            '由历史节点档案联系人迁移生成',
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM transport_node_profile
        WHERE TRIM(COALESCE(contact_person, '')) <> ''
           OR TRIM(COALESCE(contact_phone, '')) <> ''
        """
    )

    op.create_table(
        "transport_node_photo",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("node_id", sa.BigInteger(), nullable=False),
        sa.Column("file_id", sa.BigInteger(), nullable=False),
        sa.Column("photo_type_code", sa.String(length=64), nullable=False),
        sa.Column("photo_name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["storage_file.id"]),
        sa.ForeignKeyConstraint(["node_id"], ["transport_node.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("transport_node_photo", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_transport_node_photo_file_id"), ["file_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_transport_node_photo_node_id"), ["node_id"], unique=False)

    with op.batch_alter_table("transport_node_profile", schema=None) as batch_op:
        batch_op.drop_column("contact_phone")
        batch_op.drop_column("contact_person")


def downgrade() -> None:
    with op.batch_alter_table("transport_node_profile", schema=None) as batch_op:
        batch_op.add_column(sa.Column("contact_person", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("contact_phone", sa.String(length=32), nullable=True))

    op.execute(
        """
        UPDATE transport_node_profile
        SET
            contact_person = (
                SELECT contact_name
                FROM transport_node_contact
                WHERE transport_node_contact.node_id = transport_node_profile.node_id
                ORDER BY is_primary DESC, id ASC
                LIMIT 1
            ),
            contact_phone = (
                SELECT mobile_phone
                FROM transport_node_contact
                WHERE transport_node_contact.node_id = transport_node_profile.node_id
                ORDER BY is_primary DESC, id ASC
                LIMIT 1
            )
        WHERE EXISTS (
            SELECT 1
            FROM transport_node_contact
            WHERE transport_node_contact.node_id = transport_node_profile.node_id
        )
        """
    )

    with op.batch_alter_table("transport_node_photo", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_transport_node_photo_node_id"))
        batch_op.drop_index(batch_op.f("ix_transport_node_photo_file_id"))
    op.drop_table("transport_node_photo")

    with op.batch_alter_table("transport_node_contact", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_transport_node_contact_node_id"))
    op.drop_table("transport_node_contact")
    op.drop_table("storage_file")
