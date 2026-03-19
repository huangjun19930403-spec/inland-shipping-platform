"""phase6 add code_sequence table

Revision ID: 6b4b44f84a6a
Revises: 9d4d6be9f1a2
Create Date: 2026-03-19 20:10:00.000000

目的：
1. 将 code_sequence 纳入主迁移链，修复“仅执行主链迁移后缺表”的问题。
2. 为 region / waterway 初始化序号 scope，保证历史数据平滑接入原子序列。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6b4b44f84a6a"
down_revision: Union[str, None] = "9d4d6be9f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("code_sequence"):
        op.create_table(
            "code_sequence",
            sa.Column(
                "scope",
                sa.String(length=64),
                primary_key=True,
                nullable=False,
                comment="序号命名空间，如 region / ww:root / ww:42",
            ),
            sa.Column(
                "next_val",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
                comment="下次分配的序号值（从1开始）",
            ),
        )

    # 初始化 region scope：编码格式 RG-NNN
    op.execute(
        """
        INSERT INTO code_sequence (scope, next_val)
        SELECT
            'region' AS scope,
            COALESCE(MAX(CAST(substr(code, 4) AS INTEGER)) + 1, 1) AS next_val
        FROM region
        WHERE code LIKE 'RG-%'
        ON CONFLICT (scope) DO UPDATE
            SET next_val = EXCLUDED.next_val
        """
    )

    # 初始化 waterway scope：编码格式 WW-LL-NNN，按 parent_id 分组
    op.execute(
        """
        INSERT INTO code_sequence (scope, next_val)
        SELECT
            CASE
                WHEN parent_id IS NULL THEN 'ww:root'
                ELSE 'ww:' || CAST(parent_id AS TEXT)
            END AS scope,
            COALESCE(MAX(CAST(substr(code, 7) AS INTEGER)) + 1, 1) AS next_val
        FROM waterway
        WHERE length(code) = 9 AND code LIKE '__-__-___'
        GROUP BY parent_id
        ON CONFLICT (scope) DO UPDATE
            SET next_val = EXCLUDED.next_val
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("code_sequence"):
        op.drop_table("code_sequence")
