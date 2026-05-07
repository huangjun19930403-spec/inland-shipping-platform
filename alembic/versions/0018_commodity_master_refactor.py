"""commodity_master_refactor

Revision ID: 0018_commodity_master_refactor
Revises: 0017_node_contacts_photos_cos_storage
Create Date: 2026-05-07 21:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0018_commodity_master_refactor"
down_revision: Union[str, None] = "0017_node_contacts_photos_cos_storage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "commodity_attribute_definition",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("attribute_code", sa.String(length=64), nullable=False),
        sa.Column("attribute_name", sa.String(length=128), nullable=False),
        sa.Column("attribute_group_code", sa.String(length=64), nullable=False),
        sa.Column("value_type_code", sa.String(length=64), nullable=False),
        sa.Column("unit_code", sa.String(length=32), nullable=True),
        sa.Column("option_dict_code", sa.String(length=64), nullable=True),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("is_required_default", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attribute_code", name="uk_commodity_attribute_definition_code"),
    )

    with op.batch_alter_table("commodity_standard", schema=None) as batch_op:
        batch_op.add_column(sa.Column("category_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("specification", sa.String(length=256), nullable=True))
        batch_op.add_column(sa.Column("cargo_form_code", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("is_bulk_cargo", sa.Boolean(), nullable=False, server_default=sa.text("1")))
        batch_op.add_column(sa.Column("is_container_suitable", sa.Boolean(), nullable=False, server_default=sa.text("0")))
        batch_op.add_column(sa.Column("is_hazardous", sa.Boolean(), nullable=False, server_default=sa.text("0")))
        batch_op.add_column(sa.Column("pollution_risk_level_code", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("loading_requirement", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("unloading_requirement", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("storage_requirement", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("source_type_code", sa.String(length=64), nullable=False, server_default="MANUAL"))
        batch_op.add_column(sa.Column("recognition_priority", sa.Integer(), nullable=False, server_default="50"))
        batch_op.add_column(sa.Column("remark", sa.Text(), nullable=True))
        batch_op.create_index(batch_op.f("ix_commodity_standard_category_id"), ["category_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_commodity_standard_category_id",
            "commodity_category",
            ["category_id"],
            ["id"],
        )

    op.execute(
        """
        UPDATE commodity_standard
        SET category_id = (
            SELECT commodity_type.category_id
            FROM commodity_type
            WHERE commodity_type.id = commodity_standard.type_id
        )
        WHERE category_id IS NULL
        """
    )

    with op.batch_alter_table("commodity_alias", schema=None) as batch_op:
        batch_op.add_column(sa.Column("alias_type_code", sa.String(length=64), nullable=False, server_default="COMMON_NAME"))
        batch_op.add_column(sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")))
        batch_op.add_column(sa.Column("match_weight", sa.Integer(), nullable=False, server_default="80"))
        batch_op.add_column(sa.Column("remark", sa.String(length=512), nullable=True))

    with op.batch_alter_table("commodity_standard_attribute", schema=None) as batch_op:
        batch_op.add_column(sa.Column("attribute_definition_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("attribute_value", sa.String(length=512), nullable=True))
        batch_op.alter_column("attribute_code", existing_type=sa.String(length=64), nullable=True)
        batch_op.alter_column("attribute_name", existing_type=sa.String(length=128), nullable=True)
        batch_op.alter_column("attribute_value_type_code", existing_type=sa.String(length=64), nullable=True)
        batch_op.create_index(
            batch_op.f("ix_commodity_standard_attribute_attribute_definition_id"),
            ["attribute_definition_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_commodity_standard_attribute_definition_id",
            "commodity_attribute_definition",
            ["attribute_definition_id"],
            ["id"],
        )

    with op.batch_alter_table("commodity_packaging_form", schema=None) as batch_op:
        batch_op.add_column(sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")))
        batch_op.add_column(sa.Column("remark", sa.String(length=512), nullable=True))

    with op.batch_alter_table("commodity_transport_mode", schema=None) as batch_op:
        batch_op.add_column(sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")))
        batch_op.add_column(sa.Column("remark", sa.String(length=512), nullable=True))

    for table_name in ("commodity_ship_type_rule", "commodity_node_type_rule", "commodity_handling_mode_rule"):
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            if table_name == "commodity_node_type_rule":
                batch_op.add_column(sa.Column("operation_side_code", sa.String(length=64), nullable=True))
            batch_op.add_column(sa.Column("rule_type_code", sa.String(length=64), nullable=False, server_default="ALLOWED"))
            batch_op.add_column(sa.Column("priority", sa.Integer(), nullable=False, server_default="50"))
            batch_op.add_column(sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")))
        op.execute(
            f"""
            UPDATE {table_name}
            SET rule_type_code = CASE
                WHEN allow_flag = 0 THEN 'FORBIDDEN'
                ELSE 'ALLOWED'
            END
            """
        )

    op.create_table(
        "commodity_standard_image",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("commodity_standard_id", sa.BigInteger(), nullable=False),
        sa.Column("file_id", sa.BigInteger(), nullable=False),
        sa.Column("image_type_code", sa.String(length=64), nullable=False),
        sa.Column("image_name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["commodity_standard_id"], ["commodity_standard.id"]),
        sa.ForeignKeyConstraint(["file_id"], ["storage_file.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("commodity_standard_image", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_commodity_standard_image_commodity_standard_id"), ["commodity_standard_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_commodity_standard_image_file_id"), ["file_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("commodity_standard_image", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_commodity_standard_image_file_id"))
        batch_op.drop_index(batch_op.f("ix_commodity_standard_image_commodity_standard_id"))
    op.drop_table("commodity_standard_image")

    for table_name in ("commodity_handling_mode_rule", "commodity_node_type_rule", "commodity_ship_type_rule"):
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.drop_column("is_enabled")
            batch_op.drop_column("priority")
            batch_op.drop_column("rule_type_code")
            if table_name == "commodity_node_type_rule":
                batch_op.drop_column("operation_side_code")

    with op.batch_alter_table("commodity_transport_mode", schema=None) as batch_op:
        batch_op.drop_column("remark")
        batch_op.drop_column("is_enabled")

    with op.batch_alter_table("commodity_packaging_form", schema=None) as batch_op:
        batch_op.drop_column("remark")
        batch_op.drop_column("is_enabled")

    with op.batch_alter_table("commodity_standard_attribute", schema=None) as batch_op:
        batch_op.drop_constraint("fk_commodity_standard_attribute_definition_id", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_commodity_standard_attribute_attribute_definition_id"))
        batch_op.alter_column("attribute_value_type_code", existing_type=sa.String(length=64), nullable=False)
        batch_op.alter_column("attribute_name", existing_type=sa.String(length=128), nullable=False)
        batch_op.alter_column("attribute_code", existing_type=sa.String(length=64), nullable=False)
        batch_op.drop_column("attribute_value")
        batch_op.drop_column("attribute_definition_id")

    with op.batch_alter_table("commodity_alias", schema=None) as batch_op:
        batch_op.drop_column("remark")
        batch_op.drop_column("match_weight")
        batch_op.drop_column("is_enabled")
        batch_op.drop_column("alias_type_code")

    with op.batch_alter_table("commodity_standard", schema=None) as batch_op:
        batch_op.drop_constraint("fk_commodity_standard_category_id", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_commodity_standard_category_id"))
        batch_op.drop_column("remark")
        batch_op.drop_column("recognition_priority")
        batch_op.drop_column("source_type_code")
        batch_op.drop_column("storage_requirement")
        batch_op.drop_column("unloading_requirement")
        batch_op.drop_column("loading_requirement")
        batch_op.drop_column("pollution_risk_level_code")
        batch_op.drop_column("is_hazardous")
        batch_op.drop_column("is_container_suitable")
        batch_op.drop_column("is_bulk_cargo")
        batch_op.drop_column("cargo_form_code")
        batch_op.drop_column("specification")
        batch_op.drop_column("category_id")

    op.drop_table("commodity_attribute_definition")
