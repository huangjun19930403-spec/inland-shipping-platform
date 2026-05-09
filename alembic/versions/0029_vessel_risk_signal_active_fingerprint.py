"""vessel risk signal active fingerprint uniqueness

Revision ID: 0029_vessel_risk_signal_active_fingerprint
Revises: 0028_vessel_compliance_risk_ocr_workbench
Create Date: 2026-05-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0029_vessel_risk_signal_active_fingerprint"
down_revision = "0028_vessel_compliance_risk_ocr_workbench"
branch_labels = None
depends_on = None


ACTIVE_STATUS_SQL = "'OPEN', 'IN_REVIEW', 'EVIDENCE_ADDED'"
INDEX_NAME = "uq_vessel_risk_signal_active_fingerprint"


def _has_index(table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(index.get("name") == index_name for index in inspector.get_indexes(table_name))


def _dedupe_active_fingerprints() -> None:
    bind = op.get_bind()
    duplicates = bind.execute(
        sa.text(
            f"""
            SELECT fingerprint, MIN(id) AS keep_id
            FROM vessel_risk_signal
            WHERE status_code IN ({ACTIVE_STATUS_SQL})
            GROUP BY fingerprint
            HAVING COUNT(*) > 1
            """
        )
    ).mappings()
    for row in duplicates:
        bind.execute(
            sa.text(
                f"""
                UPDATE vessel_risk_signal
                SET status_code = 'MITIGATED',
                    resolved_at = CURRENT_TIMESTAMP,
                    resolution_reason = COALESCE(resolution_reason, 'active fingerprint deduped by migration'),
                    updated_at = CURRENT_TIMESTAMP,
                    revision = revision + 1
                WHERE fingerprint = :fingerprint
                  AND status_code IN ({ACTIVE_STATUS_SQL})
                  AND id <> :keep_id
                """
            ),
            {"fingerprint": row["fingerprint"], "keep_id": row["keep_id"]},
        )


def upgrade() -> None:
    _dedupe_active_fingerprints()
    if not _has_index("vessel_risk_signal", INDEX_NAME):
        op.create_index(
            INDEX_NAME,
            "vessel_risk_signal",
            ["fingerprint"],
            unique=True,
            sqlite_where=sa.text(f"status_code IN ({ACTIVE_STATUS_SQL})"),
            postgresql_where=sa.text(f"status_code IN ({ACTIVE_STATUS_SQL})"),
        )


def downgrade() -> None:
    if _has_index("vessel_risk_signal", INDEX_NAME):
        op.drop_index(INDEX_NAME, table_name="vessel_risk_signal")
