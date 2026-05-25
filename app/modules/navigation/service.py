from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NavigationChannelCenterline
from app.models.address import NavigationChannel

GRAPH_READY_CENTERLINE_QUALITIES = {"READY", "READY_WITH_WARNING"}
GRAPH_READY_CENTERLINE_SOURCES = {"MANUAL", "SEED_CENTERLINE", "OSM_WATERWAY"}


class NavigationCenterlineService:
    """Minimal centerline query service for future graph-building rounds."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_graph_ready_centerlines(
        self,
        *,
        channel_ids: list[int] | None = None,
        channel_codes: list[str] | None = None,
    ) -> list[NavigationChannelCenterline]:
        stmt = (
            select(NavigationChannelCenterline)
            .join(NavigationChannel, NavigationChannel.id == NavigationChannelCenterline.channel_id)
            .where(
                NavigationChannel.is_enabled.is_(True),
                NavigationChannelCenterline.review_status_code == "PUBLISHED",
                NavigationChannelCenterline.is_current.is_(True),
                NavigationChannelCenterline.quality_code.in_(GRAPH_READY_CENTERLINE_QUALITIES),
                NavigationChannelCenterline.source_type_code.in_(GRAPH_READY_CENTERLINE_SOURCES),
            )
            .order_by(NavigationChannelCenterline.channel_id, NavigationChannelCenterline.id)
        )
        if channel_ids:
            stmt = stmt.where(NavigationChannelCenterline.channel_id.in_(channel_ids))
        if channel_codes:
            stmt = stmt.where(NavigationChannel.channel_code.in_(channel_codes))
        return list((await self.session.execute(stmt)).scalars())

    async def list_channel_codes_without_graph_ready_centerline(
        self,
        channel_codes: list[str],
    ) -> list[str]:
        ready_rows = await self.list_graph_ready_centerlines(channel_codes=channel_codes)
        ready_channel_ids = {row.channel_id for row in ready_rows}
        channels = (
            await self.session.execute(
                select(NavigationChannel).where(
                    NavigationChannel.channel_code.in_(channel_codes),
                    NavigationChannel.is_enabled.is_(True),
                )
            )
        ).scalars()
        return sorted(channel.channel_code for channel in channels if channel.id not in ready_channel_ids)
