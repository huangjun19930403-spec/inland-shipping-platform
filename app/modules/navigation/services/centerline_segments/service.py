from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from shapely.geometry import LineString, Point

from app.core.exceptions import NotFoundError
from app.models import NavigationCenterlineSegment
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.modules.navigation.schemas import (
    NavigationCenterlineSegmentIssueStatResponse,
    NavigationCenterlineSegmentListResponse,
    NavigationCenterlineSegmentResponse,
    NavigationCenterlineSegmentSplitRequest,
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
        issue_code: str | None = None,
        limit: int | None = None,
        page: int = 1,
        page_size: int = 50,
        include_geometry: bool = True,
    ) -> NavigationCenterlineSegmentListResponse:
        await self._ensure_channel(channel_id)
        all_rows = await self._active_segments(channel_id, limit=10000)
        rows = list(all_rows)
        if status_code:
            status = status_code.upper()
            rows = [item for item in rows if item.segment_status_code == status]
        if only_problem:
            rows = [
                item
                for item in rows
                if item.segment_status_code in {"NEED_REPAIR", "PUBLISH_BLOCKED"}
                or self._segment_issue_count(item) > 0
            ]
        if issue_code:
            target_issue = issue_code.upper()
            rows = [item for item in rows if target_issue in self._segment_issue_codes(item)]
        if limit is not None:
            page = 1
            page_size = self._limit(limit, 300, 10000)
        else:
            page = max(1, int(page or 1))
            page_size = self._limit(page_size, 50, 500)
        start = (page - 1) * page_size
        page_rows = rows[start : start + page_size]
        confirmed_count = self._operator_confirmed_count(all_rows)
        items = [self._response(item) for item in page_rows]
        if not include_geometry:
            items = [item.model_copy(update={"geometry_json": None}) for item in items]
        return NavigationCenterlineSegmentListResponse(
            channel_id=channel_id,
            total_count=len(rows),
            page=page,
            page_size=page_size,
            need_repair_count=self._need_repair_count(all_rows),
            confirmed_count=confirmed_count,
            publishable=bool(all_rows) and all(item.segment_status_code == "CONFIRMED" for item in all_rows),
            issue_stats=self._issue_stats(all_rows),
            items=items,
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

    async def archive_segment(self, segment_id: int) -> NavigationCenterlineSegmentListResponse:
        row = await self._segment(segment_id)
        row.segment_status_code = "ARCHIVED"
        trace = dict(row.source_trace_json or {})
        trace["archived_at"] = self._now().isoformat()
        trace["archive_reason"] = "operator_deleted_segment"
        row.source_trace_json = trace
        await self.session.flush()
        await self._rechain_active_segments(int(row.channel_id))
        await self.session.commit()
        return await self.list_segments(int(row.channel_id))

    async def split_segment(
        self,
        segment_id: int,
        body: NavigationCenterlineSegmentSplitRequest,
    ) -> NavigationCenterlineSegmentListResponse:
        row = await self._segment(segment_id)
        if row.geometry_json is None:
            self._fail("SEGMENT_GEOMETRY_INVALID", "中心线区段缺少几何，无法拆分")
        line = self._line_from_json(row.geometry_json, code="SEGMENT_GEOMETRY_INVALID")
        first_line, second_line = self._split_line_at_ratio(line, float(body.split_ratio))
        if first_line is None or second_line is None:
            self._fail("SEGMENT_SPLIT_FAILED", "当前区段太短或几何无效，无法拆分")
        ordered = await self._active_segments(int(row.channel_id))
        insert_at = next((index for index, item in enumerate(ordered) if int(item.id) == int(row.id)), len(ordered) - 1)
        row.geometry_json = self._geometry_json(first_line)
        row.source_type_code = "MAP_EDIT"
        row.centerline_id = None
        row.source_trace_json = {
            **(row.source_trace_json or {}),
            "split_at": self._now().isoformat(),
            "split_ratio": body.split_ratio,
            "last_edit_source_type_code": "MAP_EDIT",
        }
        self._apply_geometry_metrics(row, first_line)
        new_row = NavigationCenterlineSegment(
            channel_id=row.channel_id,
            centerline_id=None,
            segment_no=row.segment_no,
            segment_name=f"{row.segment_name} 拆分段",
            segment_status_code="NEED_REPAIR",
            geometry_json=self._geometry_json(second_line),
            source_type_code="MAP_EDIT",
            quality_code="READY_WITH_WARNING",
            source_trace_json={
                **(row.source_trace_json or {}),
                "split_from_segment_id": int(row.id),
                "split_at": self._now().isoformat(),
                "source_mode": "MAP_EDIT",
                "source_type_code": "MAP_EDIT",
            },
        )
        self._apply_geometry_metrics(new_row, second_line)
        self.session.add(new_row)
        await self.session.flush()
        ordered = [item for item in ordered if int(item.id) != int(row.id)]
        ordered[insert_at:insert_at] = [row, new_row]
        self._rechain_rows(ordered)
        await self._validate_mutated_segment(row)
        await self._validate_mutated_segment(new_row)
        await self.session.commit()
        return await self.list_segments(int(row.channel_id))

    async def merge_next_segment(self, segment_id: int) -> NavigationCenterlineSegmentListResponse:
        row = await self._segment(segment_id)
        if row.next_segment_id is None:
            self._fail("SEGMENT_MERGE_FAILED", "当前区段没有下一段，无法合并")
        next_row = await self._segment(int(row.next_segment_id))
        if row.geometry_json is None or next_row.geometry_json is None:
            self._fail("SEGMENT_GEOMETRY_INVALID", "中心线区段缺少几何，无法合并")
        line = self._line_from_json(row.geometry_json, code="SEGMENT_GEOMETRY_INVALID")
        next_line = self._line_from_json(next_row.geometry_json, code="SEGMENT_GEOMETRY_INVALID")
        coords = [(float(lng), float(lat)) for lng, lat, *_rest in line.coords]
        next_coords = [(float(lng), float(lat)) for lng, lat, *_rest in next_line.coords]
        if coords and next_coords and self._distance_m(coords[-1], next_coords[0]) <= ENDPOINT_AUTO_SNAP_M:
            next_coords[0] = coords[-1]
        merged_line = LineString(self._clean_coords([*coords, *next_coords]))
        row.geometry_json = self._geometry_json(merged_line)
        row.source_type_code = "MAP_EDIT"
        row.centerline_id = None
        trace = dict(row.source_trace_json or {})
        trace["merged_next_segment_id"] = int(next_row.id)
        trace["merged_at"] = self._now().isoformat()
        trace["last_edit_source_type_code"] = "MAP_EDIT"
        row.source_trace_json = trace
        self._apply_geometry_metrics(row, merged_line)
        next_row.segment_status_code = "ARCHIVED"
        next_trace = dict(next_row.source_trace_json or {})
        next_trace["archived_at"] = self._now().isoformat()
        next_trace["archive_reason"] = f"merged_into_segment:{row.id}"
        next_row.source_trace_json = next_trace
        await self.session.flush()
        await self._rechain_active_segments(int(row.channel_id))
        await self._validate_mutated_segment(row)
        await self.session.commit()
        return await self.list_segments(int(row.channel_id))

    async def reverse_segment(self, segment_id: int) -> NavigationCenterlineSegmentResponse:
        row = await self._segment(segment_id)
        if row.geometry_json is None:
            self._fail("SEGMENT_GEOMETRY_INVALID", "中心线区段缺少几何，无法反向")
        line = self._line_from_json(row.geometry_json, code="SEGMENT_GEOMETRY_INVALID")
        reversed_line = LineString(list(line.coords)[::-1])
        row.geometry_json = self._geometry_json(reversed_line)
        row.source_type_code = "MAP_EDIT"
        row.centerline_id = None
        trace = dict(row.source_trace_json or {})
        trace["reversed_at"] = self._now().isoformat()
        trace["last_edit_source_type_code"] = "MAP_EDIT"
        row.source_trace_json = trace
        self._apply_geometry_metrics(row, reversed_line)
        await self._validate_mutated_segment(row)
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
                    .limit(self._limit(limit, 1000, 10000))
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

    async def _validate_mutated_segment(self, row: NavigationCenterlineSegment) -> None:
        validation = await self._validate_row(row)
        self._apply_validation(row, validation, generated_from_boundary=False)
        row.segment_status_code = "PUBLISH_BLOCKED" if validation.error_count else "NEED_REPAIR" if validation.warning_count else "CANDIDATE"
        row.quality_code = validation.quality_code

    def _split_line_at_ratio(self, line: LineString, ratio: float) -> tuple[LineString | None, LineString | None]:
        coords = [(float(lng), float(lat)) for lng, lat, *_rest in line.coords]
        if len(coords) < 2:
            return None, None
        split_point = line.interpolate(ratio, normalized=True)
        split_coord = (float(split_point.x), float(split_point.y))
        first_coords = [coords[0]]
        second_coords = [split_coord]
        for coord in coords[1:-1]:
            projected = line.project(Point(coord), normalized=True)
            if projected < ratio:
                first_coords.append(coord)
            else:
                second_coords.append(coord)
        first_coords.append(split_coord)
        second_coords.append(coords[-1])
        first_clean = self._clean_coords(first_coords)
        second_clean = self._clean_coords(second_coords)
        first = LineString(first_clean) if len(first_clean) >= 2 else None
        second = LineString(second_clean) if len(second_clean) >= 2 else None
        if first is None or second is None or self._length_m(first) < 1.0 or self._length_m(second) < 1.0:
            return None, None
        return first, second

    async def _rechain_active_segments(self, channel_id: int) -> None:
        self._rechain_rows(await self._active_segments(channel_id, limit=1000))

    def _rechain_rows(self, rows: list[NavigationCenterlineSegment]) -> None:
        for index, item in enumerate(rows):
            item.segment_no = f"{index + 1:03d}"
            item.previous_segment_id = int(rows[index - 1].id) if index > 0 else None
            item.next_segment_id = int(rows[index + 1].id) if index + 1 < len(rows) else None

    def _segment_issue_count(self, row: NavigationCenterlineSegment) -> int:
        issue_summary = row.issue_summary_json if isinstance(row.issue_summary_json, dict) else {}
        count = issue_summary.get("issue_count")
        if isinstance(count, int):
            return count
        entries = self._segment_issue_entries(row)
        return len(entries)

    def _segment_issue_codes(self, row: NavigationCenterlineSegment) -> set[str]:
        return {code for code, _severity in self._segment_issue_entries(row)}

    def _segment_issue_entries(self, row: NavigationCenterlineSegment) -> list[tuple[str, str]]:
        validation_summary = row.validation_summary_json if isinstance(row.validation_summary_json, dict) else {}
        entries = self._issues_from_raw(validation_summary.get("issues"))
        if entries:
            return entries
        issue_summary = row.issue_summary_json if isinstance(row.issue_summary_json, dict) else {}
        entries = self._issues_from_raw(issue_summary.get("issues"))
        if entries:
            return entries
        codes = issue_summary.get("issue_codes")
        if not isinstance(codes, list):
            return []
        severity = "ERROR" if int(issue_summary.get("error_count") or 0) > 0 else "WARNING"
        return [(str(code).upper(), severity) for code in codes if code]

    def _issues_from_raw(self, raw_issues: object) -> list[tuple[str, str]]:
        if not isinstance(raw_issues, list):
            return []
        entries: list[tuple[str, str]] = []
        for item in raw_issues:
            if not isinstance(item, dict):
                continue
            code = item.get("issue_code") or item.get("issue_type_code") or item.get("code")
            if not code:
                continue
            severity = item.get("severity_code") or item.get("severity") or "WARNING"
            entries.append((str(code).upper(), str(severity).upper()))
        return entries

    def _issue_stats(self, rows: list[NavigationCenterlineSegment]) -> list[NavigationCenterlineSegmentIssueStatResponse]:
        counts: dict[str, dict[str, int | str]] = {}
        for row in rows:
            seen_for_row: set[str] = set()
            for code, severity in self._segment_issue_entries(row):
                if code in seen_for_row:
                    continue
                seen_for_row.add(code)
                stat = counts.setdefault(code, {"count": 0, "severity_code": "WARNING"})
                stat["count"] = int(stat["count"]) + 1
                if severity == "ERROR":
                    stat["severity_code"] = "ERROR"
        severity_rank = {"ERROR": 0, "WARNING": 1}
        return [
            NavigationCenterlineSegmentIssueStatResponse(
                issue_type_code=code,
                severity_code=str(payload["severity_code"]),
                count=int(payload["count"]),
            )
            for code, payload in sorted(
                counts.items(),
                key=lambda item: (severity_rank.get(str(item[1]["severity_code"]), 2), -int(item[1]["count"]), item[0]),
            )
        ]
