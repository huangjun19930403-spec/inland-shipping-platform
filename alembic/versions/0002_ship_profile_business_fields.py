"""ship_profile_business_fields

Revision ID: 0002_ship_profile_business_fields
Revises: 0001_initial_schema
Create Date: 2026-04-30 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002_ship_profile_business_fields"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ship_profile", schema=None) as batch_op:
        batch_op.add_column(sa.Column("building_year", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("registry_city_code", sa.String(length=12), nullable=True))
        batch_op.add_column(sa.Column("business_region_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("operation_status_code", sa.String(length=64), nullable=True))
        batch_op.create_index("ix_ship_profile_registry_city_code", ["registry_city_code"], unique=False)
        batch_op.create_index("ix_ship_profile_business_region_id", ["business_region_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("ship_profile", schema=None) as batch_op:
        batch_op.drop_index("ix_ship_profile_business_region_id")
        batch_op.drop_index("ix_ship_profile_registry_city_code")
        batch_op.drop_column("operation_status_code")
        batch_op.drop_column("business_region_id")
        batch_op.drop_column("registry_city_code")
        batch_op.drop_column("building_year")
