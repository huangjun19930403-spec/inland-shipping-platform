"""foundation_dictionary_codes

Revision ID: 0007_foundation_dictionary_codes
Revises: 0006_final_legacy_cleanup
Create Date: 2026-04-30 23:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_foundation_dictionary_codes"
down_revision: Union[str, None] = "0006_final_legacy_cleanup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("commodity_standard") as batch_op:
        batch_op.alter_column(
            "main_unit",
            new_column_name="main_unit_code",
            existing_type=sa.String(length=32),
            existing_nullable=False,
        )

    op.execute(
        """
        UPDATE commodity_standard
        SET main_unit_code = CASE TRIM(main_unit_code)
            WHEN '吨' THEN 'TON'
            WHEN 'TON' THEN 'TON'
            WHEN '立方米' THEN 'CUBIC_METER'
            WHEN 'CUBIC_METER' THEN 'CUBIC_METER'
            WHEN '件' THEN 'PIECE'
            WHEN 'PIECE' THEN 'PIECE'
            WHEN '箱' THEN 'BOX'
            WHEN 'BOX' THEN 'BOX'
            WHEN '车' THEN 'TRUCK'
            WHEN 'TRUCK' THEN 'TRUCK'
            WHEN '船次' THEN 'VOYAGE'
            WHEN 'VOYAGE' THEN 'VOYAGE'
            ELSE 'OTHER'
        END
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE commodity_standard
        SET main_unit_code = CASE TRIM(main_unit_code)
            WHEN 'TON' THEN '吨'
            WHEN 'CUBIC_METER' THEN '立方米'
            WHEN 'PIECE' THEN '件'
            WHEN 'BOX' THEN '箱'
            WHEN 'TRUCK' THEN '车'
            WHEN 'VOYAGE' THEN '船次'
            ELSE '其他'
        END
        """
    )

    with op.batch_alter_table("commodity_standard") as batch_op:
        batch_op.alter_column(
            "main_unit_code",
            new_column_name="main_unit",
            existing_type=sa.String(length=32),
            existing_nullable=False,
        )
