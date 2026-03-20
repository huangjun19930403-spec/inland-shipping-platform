"""initial schema baseline

Revision ID: 0001
Revises: None
Create Date: 2026-03-19

将当前主线模型收敛为单一可执行初始迁移：
- 业务表/统计表/审核表/AI表由 ORM 元数据创建
- code_sequence 表由 SQL 显式创建（当前无 ORM 模型）
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.core.database import Base
    from app.models import system, address, cargo, vessel, route, analysis, audit, ai  # noqa: F401

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS code_sequence (
            scope VARCHAR(64) PRIMARY KEY,
            next_val INTEGER NOT NULL DEFAULT 1
        )
        """
    )


def downgrade() -> None:
    from app.core.database import Base
    from app.models import system, address, cargo, vessel, route, analysis, audit, ai  # noqa: F401

    op.execute("DROP TABLE IF EXISTS code_sequence")

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, checkfirst=True)
