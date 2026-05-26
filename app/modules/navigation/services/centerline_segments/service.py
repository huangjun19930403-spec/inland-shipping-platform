from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from shapely.geometry import LineString

from app.core.exceptions import NotFoundError
from app.models import NavigationCenterlineSegment
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.modules.navigation.schemas import (
    NavigationCenterlineSegmentListResponse,
    NavigationCenterlineSegmentResponse,
    NavigationCenterlineSegmentUpdateRequest,
)
from app.modules.navigation.services.centerline_segments.generator import NavigationCenterlineSegmentGeneratorMixin
from app.modules.navigation.services.centerline_segments.geometry import NavigationCenterlineSegmentGeometryMixin
from app.modules.navigation.services.centerline_segments.publisher import NavigationCenterlineSegmentPublisherMixin
from app.modules.navigation.services.centerline_segments.types import ACTIVE_SEGMENT_STATUSES, ENDPOINT_AUTO_SNAP_M
from app.modules.navigation.services.centerline_segments.validator import NavigationCenterlineSegmentValidatorMixin


class NavigationCenterlineSegmentService(
    NavigationCenterlineSegmentGeneratorMixin,
    NavigationCenterlineSegmentPublisherMixin,
    NavigationCenterlineSegmentValidatorMixin,
    NavigationCenterlineSegmentGeometryMixin,
):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_segments(
        self,
        channel_id: int,
        *,
        status_code: str | None = None,
        only_problem: bool = False,
        limit: int = 300,
    ) -> NavigationCenterlineSegmentListResponse:
        await self._ensure_channel(channel_id)
        rows = await self._active_segments(channel_id, limit=limit)
        if status_code:
            status = status_code.upper()
            rows = [item for item in rows if item.segment_status_code == status]
        if only_problem:
            rows = [
                item
                for item in rows
                if item.segment_status_code in {"NEED_REPAIR", "PUBLISH_BLOCKED"}
                or int((item.issue_summary_json or {}).get("issue_count") or 0) > 0
            ]
        all_rows = await self._active_segments(channel_id, limit=1000)
        confirmed_count = sum(1 for item in all_rows if item.segment_status_code == "CONFIRMED")
        return NavigationCenterlineSegmentListResponse(
            channel_id=channel_id,
            total_count=len(all_rows),
            need_repair_count=self._need_repair_count(all_rows),
            confirmed_count=confirmed_count,
            publishable=bool(all_rows) and confirmed_count == len(all_rows),
            items=[self._response(item) for item in rows[: self._limit(limit, 300, 1000)]],
        )

    async def update_segment(
        self,
        segment_id: int,
        body: NavigationCenterlineSegmentUpdateRequest,
    ) -> NavigationCenterlineSegmentResponse:
        row = await self._segment(segment_id)
        line = self._line_from_json(body.geometry_json, code="SEGMENT_GEOMETRY_INVALID")
        line = await self._snap_line_to_neighbors(row, line)
        row.geometry_json = self._geometry_json(line)
        row.source_type_code = body.source_type_code.upper()
        self._apply_geometry_metrics(row, line)
        validation = await self._validate_row(row)
        self._apply_validation(row, validation, generated_from_boundary=False)
        row.segment_status_code = "NEED_REPAIR" if validation.issue_count else "CANDIDATE"
        trace = dict(row.source_trace_json or {})
        trace["last_edit_source_type_code"] = row.source_type_code
        trace["last_edited_at"] = self._now().isoformat()
        row.source_trace_json = trace
        await self.session.commit()
        await self.session.refresh(row)
        return self._response(row)

    async def confirm_segment(self, segment_id: int) -> NavigationCenterlineSegmentResponse:
        row = await self._segment(segment_id)
        if row.geometry_json is None:
            self._fail("SEGMENT_GEOMETRY_INVALID", "中心线区段缺少几何，无法确认")
        line = self._line_from_json(row.geometry_json, code="SEGMENT_GEOMETRY_INVALID")
        line = await self._snap_line_to_neighbors(row, line)
        row.geometry_json = self._geometry_json(line)
        self._apply_geometry_metrics(row, line)
        validation = await self._validate_row(row)
        self._apply_validation(row, validation, generated_from_boundary=False)
        if validation.error_count:
            row.segment_status_code = "PUBLISH_BLOCKED"
            await self.session.commit()
            self._fail(
                "CENTERLINE_SEGMENT_CONFIRM_BLOCKED",
                "中心线区段强校验未通过，不能确认。",
                {"validation": self._dump_model(validation), "error_code": "CENTERLINE_SEGMENT_CONFIRM_BLOCKED"},
            )
        row.segment_status_code = "CONFIRMED"
        row.quality_code = "READY_WITH_WARNING" if validation.warning_count else "READY"
        trace = dict(row.source_trace_json or {})
        trace["confirmed_at"] = self._now().isoformat()
        row.source_trace_json = trace
        await self.session.commit()
        await self.session.refresh(row)
        return self._response(row)

    async def _ensure_channel(self, channel_id: int) -> NavigationChannel:
        channel = await self.session.get(NavigationChannel, channel_id)
        if channel is None:
            raise NotFoundError("NavigationChannel", channel_id)
        return channel

    async def _segment(self, segment_id: int) -> NavigationCenterlineSegment:
        row = await self.session.get(NavigationCenterlineSegment, segment_id)
        if row is None or row.segment_status_code == "ARCHIVED":
            raise NotFoundError("NavigationCenterlineSegment", segment_id)
        return row

    async def _current_boundary(self, channel_id: int) -> NavigationChannelBoundary | None:
        return (
            await self.session.execute(
                select(NavigationChannelBoundary)
                .where(
                    NavigationChannelBoundary.channel_id == channel_id,
                    NavigationChannelBoundary.is_current.is_(True),
                    NavigationChannelBoundary.geometry_status_code == "AVAILABLE",
                )
                .order_by(NavigationChannelBoundary.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _active_segments(self, channel_id: int, *, limit: int = 1000) -> list[NavigationCenterlineSegment]:
        return list(
            (
                await self.session.execute(
                    select(NavigationCenterlineSegment)
                    .where(
                        NavigationCenterlineSegment.channel_id == channel_id,
                        NavigationCenterlineSegment.segment_status_code.in_(ACTIVE_SEGMENT_STATUSES),
                    )
                    .order_by(NavigationCenterlineSegment.segment_no, NavigationCenterlineSegment.id)
                    .limit(self._limit(limit, 300, 1000))
                )
            ).scalars()
        )

    async def _neighbor_rows(
        self,
        row: NavigationCenterlineSegment,
    ) -> tuple[NavigationCenterlineSegment | None, NavigationCenterlineSegment | None]:
        previous_row = await self.session.get(NavigationCenterlineSegment, row.previous_segment_id) if row.previous_segment_id else None
        next_row = await self.session.get(NavigationCenterlineSegment, row.next_segment_id) if row.next_segment_id else None
        return previous_row, next_row

    async def _snap_line_to_neighbors(self, row: NavigationCenterlineSegment, line: LineString) -> LineString:
        coords = [(float(lng), float(lat)) for lng, lat, *_rest in line.coords]
        if len(coords) < 2:
            return line
        previous_row, next_row = await self._neighbor_rows(row)
        if previous_row is not None and previous_row.geometry_json:
            previous_line = self._line_from_json(previous_row.geometry_json, code="SEGMENT_GEOMETRY_INVALID")
            previous_end = (float(previous_line.coords[-1][0]), float(previous_line.coords[-1][1]))
            if self._distance_m(previous_end, coords[0]) <= ENDPOINT_AUTO_SNAP_M:
                coords[0] = previous_end
        if next_row is not None and next_row.geometry_json:
            next_line = self._line_from_json(next_row.geometry_json, code="SEGMENT_GEOMETRY_INVALID")
            next_start = (float(next_line.coords[0][0]), float(next_line.coords[0][1]))
            if self._distance_m(coords[-1], next_start) <= ENDPOINT_AUTO_SNAP_M:
                coords[-1] = next_start
        return LineString(self._clean_coords(coords))
