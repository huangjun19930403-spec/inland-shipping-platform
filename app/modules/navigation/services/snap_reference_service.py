from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NavigationChannelCenterline
from app.modules.navigation.schemas import NavigationSnapReferencePointResponse


SNAP_REFERENCE_LIMIT = 500


class NavigationSnapReferenceService:
    """Collect map-visible endpoint/node references for centerline editing."""

    def __init__(self, session: AsyncSession, helpers: Any) -> None:
        self.session = session
        self.helpers = helpers

    async def snap_references(
        self,
        channel_id: int,
        *,
        limit: int = SNAP_REFERENCE_LIMIT,
    ) -> list[NavigationSnapReferencePointResponse]:
        await self.helpers._ensure_channel(channel_id)
        limit_value = self.helpers._limit(limit, default=SNAP_REFERENCE_LIMIT, max_value=SNAP_REFERENCE_LIMIT)
        references: list[NavigationSnapReferencePointResponse] = []
        centerlines = list(
            (
                await self.session.execute(
                    select(NavigationChannelCenterline)
                    .where(NavigationChannelCenterline.channel_id == channel_id)
                    .order_by(NavigationChannelCenterline.is_current.desc(), NavigationChannelCenterline.id.desc())
                    .limit(200)
                )
            ).scalars()
        )
        for centerline in centerlines:
            references.extend(self.helpers._centerline_snap_points(centerline))
            if len(references) >= limit_value:
                return references[:limit_value]

        context_bbox = await self.helpers._snap_context_bbox(channel_id)
        if context_bbox is None:
            return references[:limit_value]

        remaining = limit_value - len(references)
        if remaining > 0:
            references.extend(await self.helpers._transport_node_snap_points(context_bbox, limit=remaining))
        remaining = limit_value - len(references)
        if remaining > 0:
            references.extend(await self.helpers._constraint_point_snap_points(context_bbox, limit=remaining))
        return references[:limit_value]
