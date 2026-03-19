"""add code_sequence table for atomic code generation

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-18

新增 code_sequence 表，用于替代"先查 MAX 再 +1"的编码生成方案。

动机：
  原方案通过 SELECT MAX(code) + 重试解决并发冲突，存在竞态条件；
  新方案使用 INSERT ... ON CONFLICT DO UPDATE SET next_val = next_val + 1
  原子地分配序号，天然保证并发安全，无需重试逻辑。

升级逻辑：
  1. 创建 code_sequence 表。
  2. 扫描现有 region 表，初始化 'region' scope 的 next_val，
     使其从当前最大序号 + 1 开始，避免与历史编码冲突。
  3. 扫描现有 waterway 表，按 parent_id 分组初始化各自的 next_val。

兼容性：
  SQL 语句使用 SQLite / PostgreSQL 通用写法（substr、LIKE、length）。
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. 建表 ──────────────────────────────────────────────────────────
    op.create_table(
        "code_sequence",
        sa.Column(
            "scope",
            sa.String(64),
            primary_key=True,
            comment="序号命名空间，如 'region'、'ww:root'、'ww:42'",
        ),
        sa.Column(
            "next_val",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="下次调用时将使用并返回的序号值（从 1 开始）",
        ),
    )

    # ── 2. 初始化 region 序号 ─────────────────────────────────────────────
    # region 编码格式 RG-NNN，NNN 从第 4 个字符开始（substr 从 1 计数）。
    # 兼容 SQLite / PostgreSQL：使用 substr、LIKE、CAST。
    op.execute("""
        INSERT INTO code_sequence (scope, next_val)
        SELECT
            'region' AS scope,
            COALESCE(
                MAX(CAST(substr(code, 4) AS INTEGER)) + 1,
                1
            ) AS next_val
        FROM region
        WHERE code LIKE 'RG-%'
        ON CONFLICT (scope) DO UPDATE
            SET next_val = EXCLUDED.next_val
    """)

    # ── 3. 初始化 waterway 序号（按 parent_id 分组） ────────────────────────
    # waterway 编码格式 WW-LL-NNN（固定 9 字符，如 01-01-001），
    # NNN 从第 7 个字符开始（2+1+2+1 = 6 前缀后）。
    # scope：parent_id IS NULL → 'ww:root'，否则 'ww:{parent_id}'。
    op.execute("""
        INSERT INTO code_sequence (scope, next_val)
        SELECT
            CASE
                WHEN parent_id IS NULL THEN 'ww:root'
                ELSE 'ww:' || CAST(parent_id AS TEXT)
            END AS scope,
            COALESCE(
                MAX(CAST(substr(code, 7) AS INTEGER)) + 1,
                1
            ) AS next_val
        FROM waterway
        WHERE length(code) = 9 AND code LIKE '__-__-___'
        GROUP BY parent_id
        ON CONFLICT (scope) DO UPDATE
            SET next_val = EXCLUDED.next_val
    """)


def downgrade() -> None:
    op.drop_table("code_sequence")
