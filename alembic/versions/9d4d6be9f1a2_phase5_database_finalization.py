"""phase5 database finalization

Revision ID: 9d4d6be9f1a2
Revises: c878ba817509
Create Date: 2026-03-19

Phase 5 收口目标：
1. 删除地址域遗留兼容字段：
   - region.main_rivers/main_rivers_names/main_cities/main_cities_names
   - transport_node.region_id
2. 路线方案增强约束：
   - shipping_route_path_node(path_id, sequence) 唯一
   - shipping_route_path_segment(path_id, sequence) 唯一
3. 审核目标类型统一：CARGO_OPPORTUNITY -> CARGO_FREIGHT
4. 清理历史遗留统计/业务旧表（若存在）
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9d4d6be9f1a2"
down_revision = "c878ba817509"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) 地址域：删除遗留兼容字段
    with op.batch_alter_table("region") as batch_op:
        batch_op.drop_column("main_rivers")
        batch_op.drop_column("main_rivers_names")
        batch_op.drop_column("main_cities")
        batch_op.drop_column("main_cities_names")

    with op.batch_alter_table("transport_node") as batch_op:
        batch_op.drop_column("region_id")

    # 2) 路径完整性约束
    with op.batch_alter_table("shipping_route_path_node") as batch_op:
        batch_op.create_unique_constraint(
            "uk_route_path_node_sequence", ["path_id", "sequence"]
        )

    with op.batch_alter_table("shipping_route_path_segment") as batch_op:
        batch_op.create_unique_constraint(
            "uk_route_path_segment_sequence", ["path_id", "sequence"]
        )

    # 3) 审核 target_type 收口
    op.execute(
        sa.text(
            "UPDATE audit_task "
            "SET target_type = 'CARGO_FREIGHT' "
            "WHERE target_type = 'CARGO_OPPORTUNITY'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE audit_record "
            "SET target_type = 'CARGO_FREIGHT' "
            "WHERE target_type = 'CARGO_OPPORTUNITY'"
        )
    )

    # 4) 历史遗留旧表清理（若存在则删除）
    legacy_tables = [
        "cargo_opportunity",
        "cargo_heatmap_daily",
        "ship_heatmap_daily",
        "heatmap_stat_daily",
        "cargo_region_stat_daily",
        "ship_capacity_region_daily",
        "ship_type_stat_daily",
        "ship_age_stat_daily",
    ]
    for table_name in legacy_tables:
        op.execute(sa.text(f"DROP TABLE IF EXISTS {table_name}"))


def downgrade() -> None:
    # 1) 恢复遗留字段（仅结构回滚）
    with op.batch_alter_table("region") as batch_op:
        batch_op.add_column(
            sa.Column(
                "main_rivers",
                sa.JSON(),
                nullable=True,
                comment="(弃用) 主要水系ID数组，正式关系见 region_waterway_relation",
            )
        )
        batch_op.add_column(
            sa.Column(
                "main_rivers_names",
                sa.JSON(),
                nullable=True,
                comment="(弃用) 主要水系名称数组",
            )
        )
        batch_op.add_column(
            sa.Column(
                "main_cities",
                sa.JSON(),
                nullable=True,
                comment="(弃用) 主要城市ID数组，正式关系见 region_city_relation",
            )
        )
        batch_op.add_column(
            sa.Column(
                "main_cities_names",
                sa.JSON(),
                nullable=True,
                comment="(弃用) 主要城市名称数组",
            )
        )

    with op.batch_alter_table("transport_node") as batch_op:
        batch_op.add_column(
            sa.Column(
                "region_id",
                sa.BigInteger(),
                nullable=True,
                comment="(弃用) 单值区域归属",
            )
        )
        batch_op.create_foreign_key(
            "fk_transport_node_region_id_region",
            "region",
            ["region_id"],
            ["id"],
        )

    # 2) 回滚路径约束
    with op.batch_alter_table("shipping_route_path_segment") as batch_op:
        batch_op.drop_constraint("uk_route_path_segment_sequence", type_="unique")

    with op.batch_alter_table("shipping_route_path_node") as batch_op:
        batch_op.drop_constraint("uk_route_path_node_sequence", type_="unique")

    # 3) 审核 target_type 回滚
    op.execute(
        sa.text(
            "UPDATE audit_task "
            "SET target_type = 'CARGO_OPPORTUNITY' "
            "WHERE target_type = 'CARGO_FREIGHT'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE audit_record "
            "SET target_type = 'CARGO_OPPORTUNITY' "
            "WHERE target_type = 'CARGO_FREIGHT'"
        )
    )
