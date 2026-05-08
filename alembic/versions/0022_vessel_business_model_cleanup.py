"""vessel_business_model_cleanup

Revision ID: 0022_vessel_business_model_cleanup
Revises: 0021_vessel_party_type_and_image_ai
Create Date: 2026-05-08 22:30:00.000000

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


revision: str = "0022_vessel_business_model_cleanup"
down_revision: Union[str, None] = "0021_vessel_party_type_and_image_ai"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    return inspect(op.get_bind()).has_table(name)


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return column in {item["name"] for item in inspect(op.get_bind()).get_columns(table)}


def _has_index(table: str, index_name: str) -> bool:
    if not _has_table(table):
        return False
    return index_name in {item["name"] for item in inspect(op.get_bind()).get_indexes(table)}


def _drop_index_if_exists(table: str, index_name: str) -> None:
    if _has_index(table, index_name):
        op.drop_index(index_name, table_name=table)


def _drop_columns(table: str, columns: list[str]) -> None:
    existing = [column for column in columns if _has_column(table, column)]
    if not existing:
        return
    with op.batch_alter_table(table) as batch_op:
        for column in existing:
            batch_op.drop_column(column)


def upgrade() -> None:
    for table_name in [
        "vessel_identity_candidate",
        "vessel_quality_issue",
        "vessel_quality_snapshot",
        "vessel_behavior_profile",
        "vessel_manual_preference",
        "vessel_cargo_capability",
    ]:
        if _has_table(table_name):
            op.drop_table(table_name)

    _drop_index_if_exists("vessel_profile", "ix_vessel_profile_ais_id")
    _drop_columns(
        "vessel_profile",
        [
            "ais_id",
            "navigation_power_type_code",
            "quality_level_code",
            "owner_name",
            "building_year",
        ],
    )
    _drop_columns("vessel_owner_period", ["party_relation_type_code"])
    _drop_columns(
        "vessel_operator_period",
        [
            "operator_role_code",
            "manager_name",
            "main_navigation_area_desc",
            "usual_route_desc",
            "dispatch_contact_name",
            "dispatch_contact_phone",
            "risk_level_code",
            "last_active_at",
        ],
    )

    if _has_column("vessel_profile", "profile_status_code"):
        op.execute(
            sa.text(
                "update vessel_profile set profile_status_code = 'ACTIVE' "
                "where profile_status_code = 'NEED_GOVERNANCE'"
            )
        )
    if _has_table("vessel_identifier_history"):
        op.execute(sa.text("delete from vessel_identifier_history where identifier_type_code = 'AIS'"))
    if _has_table("std_dict") and _has_table("std_dict_item"):
        obsolete_codes = [
            "NAVIGATION_POWER_TYPE",
            "PARTY_RELATION_TYPE",
            "VESSEL_QUALITY_LEVEL",
            "VESSEL_OPERATOR_ROLE",
            "VESSEL_OPERATOR_RISK_LEVEL",
            "VESSEL_QUALITY_ISSUE_TYPE",
            "VESSEL_QUALITY_ISSUE_STATUS",
            "VESSEL_ISSUE_SEVERITY",
            "VESSEL_IDENTITY_CANDIDATE_TYPE",
            "VESSEL_IDENTITY_CANDIDATE_STATUS",
        ]
        bind = op.get_bind()
        bind.execute(
            sa.text(
                "delete from std_dict_item where dict_id in "
                "(select id from std_dict where dict_code in :codes)"
            ).bindparams(sa.bindparam("codes", expanding=True)),
            {"codes": obsolete_codes},
        )
        bind.execute(
            sa.text("delete from std_dict where dict_code in :codes").bindparams(
                sa.bindparam("codes", expanding=True)
            ),
            {"codes": obsolete_codes},
        )
        op.execute(
            sa.text(
                "update std_dict_item set status = 0 where dict_id in "
                "(select id from std_dict where dict_code = 'VESSEL_PROFILE_STATUS') "
                "and item_code = 'NEED_GOVERNANCE'"
            )
        )
        op.execute(
            sa.text(
                "update std_dict_item set status = 0 where dict_id in "
                "(select id from std_dict where dict_code = 'CERTIFICATE_TYPE') "
                "and item_code = 'AIS_CERT'"
            )
        )


def downgrade() -> None:
    if _has_table("vessel_profile"):
        with op.batch_alter_table("vessel_profile") as batch_op:
            if not _has_column("vessel_profile", "ais_id"):
                batch_op.add_column(sa.Column("ais_id", sa.String(length=32), nullable=True))
            if not _has_column("vessel_profile", "navigation_power_type_code"):
                batch_op.add_column(sa.Column("navigation_power_type_code", sa.String(length=64), nullable=True))
            if not _has_column("vessel_profile", "quality_level_code"):
                batch_op.add_column(sa.Column("quality_level_code", sa.String(length=64), nullable=False, server_default="LOW"))
            if not _has_column("vessel_profile", "owner_name"):
                batch_op.add_column(sa.Column("owner_name", sa.String(length=128), nullable=True))
            if not _has_column("vessel_profile", "building_year"):
                batch_op.add_column(sa.Column("building_year", sa.Integer(), nullable=True))
        _drop_index_if_exists("vessel_profile", "ix_vessel_profile_ais_id")
        op.create_index("ix_vessel_profile_ais_id", "vessel_profile", ["ais_id"])

    if _has_table("vessel_owner_period") and not _has_column("vessel_owner_period", "party_relation_type_code"):
        with op.batch_alter_table("vessel_owner_period") as batch_op:
            batch_op.add_column(sa.Column("party_relation_type_code", sa.String(length=64), nullable=False, server_default="OWNER"))

    if _has_table("vessel_operator_period"):
        with op.batch_alter_table("vessel_operator_period") as batch_op:
            if not _has_column("vessel_operator_period", "operator_role_code"):
                batch_op.add_column(sa.Column("operator_role_code", sa.String(length=64), nullable=False, server_default="OPERATOR"))
            if not _has_column("vessel_operator_period", "manager_name"):
                batch_op.add_column(sa.Column("manager_name", sa.String(length=128), nullable=True))
            if not _has_column("vessel_operator_period", "main_navigation_area_desc"):
                batch_op.add_column(sa.Column("main_navigation_area_desc", sa.String(length=256), nullable=True))
            if not _has_column("vessel_operator_period", "usual_route_desc"):
                batch_op.add_column(sa.Column("usual_route_desc", sa.String(length=256), nullable=True))
            if not _has_column("vessel_operator_period", "dispatch_contact_name"):
                batch_op.add_column(sa.Column("dispatch_contact_name", sa.String(length=64), nullable=True))
            if not _has_column("vessel_operator_period", "dispatch_contact_phone"):
                batch_op.add_column(sa.Column("dispatch_contact_phone", sa.String(length=32), nullable=True))
            if not _has_column("vessel_operator_period", "risk_level_code"):
                batch_op.add_column(sa.Column("risk_level_code", sa.String(length=64), nullable=True))
            if not _has_column("vessel_operator_period", "last_active_at"):
                batch_op.add_column(sa.Column("last_active_at", sa.DateTime(), nullable=True))
