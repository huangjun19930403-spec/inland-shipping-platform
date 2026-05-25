from __future__ import annotations

import asyncio

from sqlalchemy import func, select, update

from app.core.database import AsyncSessionLocal
from app.models import NavigationGeometryDraft


async def cleanup_navigation_geometry_draft_statuses() -> dict[str, int]:
    """Remove the retired navigation draft submit/approve states.

    Navigation geometry production now uses DRAFT -> PUBLISHED directly. Older
    local records in SUBMITTED or APPROVED are editable production drafts again.
    """

    async with AsyncSessionLocal() as session:
        before = int(
            await session.scalar(
                select(func.count())
                .select_from(NavigationGeometryDraft)
                .where(NavigationGeometryDraft.status_code.in_({"SUBMITTED", "APPROVED"}))
            )
            or 0
        )
        await session.execute(
            update(NavigationGeometryDraft)
            .where(NavigationGeometryDraft.status_code.in_({"SUBMITTED", "APPROVED"}))
            .values(status_code="DRAFT", quality_code="NEED_REVIEW")
        )
        await session.commit()
        after = int(
            await session.scalar(
                select(func.count())
                .select_from(NavigationGeometryDraft)
                .where(NavigationGeometryDraft.status_code.in_({"SUBMITTED", "APPROVED"}))
            )
            or 0
        )
    return {"converted_to_draft": before, "remaining_retired_statuses": after}


if __name__ == "__main__":
    print(asyncio.run(cleanup_navigation_geometry_draft_statuses()))
