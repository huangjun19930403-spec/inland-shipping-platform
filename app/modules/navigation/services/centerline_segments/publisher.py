from __future__ import annotations

from sqlalchemy import select
from shapely.geometry import LineString

from app.models import NavigationChannelCenterline
from app.modules.navigation.schemas import (
    NavigationCenterlineSegmentPublishRequest,
    NavigationCenterlineSegmentPublishResponse,
)
from app.modules.navigation.services.centerline_segments.types import ENDPOINT_AUTO_SNAP_M


class NavigationCenterlineSegmentPublisherMixin:
    async def publish_segments(
        self,
        channel_id: int,
        body: NavigationCenterlineSegmentPublishRequest,
    ) -> NavigationCenterlineSegmentPublishResponse:
        channel = await self._ensure_channel(channel_id)
        rows = await self._active_segments(channel_id, limit=1000)
        if not rows:
            return NavigationCenterlineSegmentPublishResponse(
                status_code="BLOCKED",
                message="当前航道还没有中心线区段，请先生成区段。",
                channel_id=channel_id,
                blocker_codes=["NO_CENTERLINE_SEGMENT"],
                next_path=f"/navigation/production/centerlines?channel_id={channel_id}",
            )
        unconfirmed = [item for item in rows if item.segment_status_code != "CONFIRMED"]
        if unconfirmed:
            return NavigationCenterlineSegmentPublishResponse(
                status_code="BLOCKED",
                message=f"还有 {len(unconfirmed)} 个中心线区段未确认，不能合并发布。",
                channel_id=channel_id,
                segment_count=len(rows),
                blocker_codes=["CENTERLINE_SEGMENT_NOT_CONFIRMED"],
                next_path=f"/navigation/production/centerlines?channel_id={channel_id}",
            )

        lines = [self._line_from_json(row.geometry_json or {}, code="SEGMENT_GEOMETRY_INVALID") for row in rows]
        merged_line = self._merge_confirmed_lines(lines)
        if merged_line is None:
            return NavigationCenterlineSegmentPublishResponse(
                status_code="BLOCKED",
                message="相邻区段端点未连接，不能合并发布中心线。",
                channel_id=channel_id,
                segment_count=len(rows),
                blocker_codes=["SEGMENT_ENDPOINT_DISCONNECTED"],
                next_path=f"/navigation/production/centerlines?channel_id={channel_id}",
            )
        geometry_json = self._geometry_json(merged_line)
        bbox = self._bbox(geometry_json)
        existing_current = list(
            (
                await self.session.execute(
                    select(NavigationChannelCenterline).where(
                        NavigationChannelCenterline.channel_id == channel_id,
                        NavigationChannelCenterline.is_current.is_(True),
                        NavigationChannelCenterline.is_main_line.is_(True),
                    )
                )
            ).scalars()
        )
        for item in existing_current:
            item.is_current = False
        current_boundary = await self._current_boundary(channel_id)
        source_boundary_id = int(current_boundary.id) if current_boundary is not None else None
        previous_centerline_id = int(existing_current[0].id) if existing_current else None

        quality_code = "READY_WITH_WARNING" if any((row.issue_summary_json or {}).get("warning_count") for row in rows) else "READY"
        centerline = NavigationChannelCenterline(
            channel_id=channel_id,
            centerline_code=f"SEG-CL-{channel_id}-{self._now().strftime('%Y%m%d%H%M%S')}",
            centerline_name=body.publish_name or f"{channel.channel_name}中心线",
            geometry_json=geometry_json,
            source_type_code="CENTERLINE_SEGMENT_MERGE",
            direction_code="BIDIRECTIONAL",
            is_main_line=True,
            confidence_score=90,
            quality_code=quality_code,
            review_status_code="PUBLISHED",
            version_no=(max((int(row.version_no or 1) for row in existing_current), default=0) + 1),
            parent_centerline_id=previous_centerline_id,
            is_current=True,
            source_trace_json={
                "source": "CENTERLINE_SEGMENT",
                "segment_count": len(rows),
                "segment_ids": [int(row.id) for row in rows],
                "source_boundary_id": source_boundary_id,
                "based_on_boundary_id": source_boundary_id,
                "previous_centerline_id": previous_centerline_id,
                "published_at": self._now().isoformat(),
                "no_approval_task_created": True,
            },
            bbox_min_lng=bbox["bbox_min_lng"],
            bbox_min_lat=bbox["bbox_min_lat"],
            bbox_max_lng=bbox["bbox_max_lng"],
            bbox_max_lat=bbox["bbox_max_lat"],
        )
        self.session.add(centerline)
        await self.session.flush()
        for row in rows:
            row.centerline_id = int(centerline.id)
            row.segment_status_code = "PUBLISHED"
        await self.session.commit()
        await self.session.refresh(centerline)
        return NavigationCenterlineSegmentPublishResponse(
            status_code="PUBLISHED",
            message="已将确认区段合并发布为当前中心线。发布后需要重新构建并激活 Graph，路径规划才会更新。",
            channel_id=channel_id,
            centerline_id=int(centerline.id),
            segment_count=len(rows),
            quality_code=quality_code,
            next_path="/navigation/production/graphs",
        )

    def _merge_confirmed_lines(self, lines: list[LineString]) -> LineString | None:
        if not lines:
            return None
        coords = [(float(lng), float(lat)) for lng, lat, *_rest in lines[0].coords]
        for line in lines[1:]:
            next_coords = [(float(lng), float(lat)) for lng, lat, *_rest in line.coords]
            if not coords or not next_coords:
                return None
            distance = self._distance_m(coords[-1], next_coords[0])
            if distance > ENDPOINT_AUTO_SNAP_M:
                return None
            next_coords[0] = coords[-1]
            coords.extend(next_coords[1:])
        cleaned = self._clean_coords(coords)
        return LineString(cleaned) if len(cleaned) >= 2 else None
