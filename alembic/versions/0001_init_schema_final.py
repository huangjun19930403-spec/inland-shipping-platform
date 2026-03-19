"""Final consolidated schema init.

Revision ID: 0001_final
Revises:
Create Date: 2026-03-19
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_final"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create all tables from current ORM metadata."""
    from app.core.database import Base
    from app.models import system, address, cargo, vessel, route, analysis, audit  # noqa: F401

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    """Drop all tables from current ORM metadata."""
    from app.core.database import Base
    from app.models import system, address, cargo, vessel, route, analysis, audit  # noqa: F401

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, checkfirst=True)
