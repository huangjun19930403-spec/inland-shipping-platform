from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pyproj import Geod
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point, mapping, shape
from shapely.validation import make_valid

from app.core.exceptions import NotFoundError, ValidationError
from app.models import NavigationCenterlineSegment, NavigationChannelCenterline
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.modules.navigation.schemas import (
    NavigationCenterlineSegmentGenerateRequest,
    NavigationCenterlineSegmentGenerateResponse,
    NavigationCenterlineSegmentListResponse,
    NavigationCenterlineSegmentPublishRequest,
    NavigationCenterlineSegmentPublishResponse,
    NavigationCenterlineSegmentResponse,
    NavigationCenterlineSegmentUpdateRequest,
    NavigationGeometryDraftValidationIssueResponse,
    NavigationGeometryDraftValidationResponse,
)


GEOD = Geod(ellps="WGS84")
ACTIVE_SEGMENT_STATUSES = {"CANDIDATE", "NEED_REPAIR", "CONFIRMED", "PUBLISH_BLOCKED", "PUBLISHED"}
SOURCE_CENTERLINE_TYPES = {"OSM_WATERWAY", "AIS_INFERRED", "MANUAL_IMPORT", "EXTERNAL_WATERWAY", "PUBLISHED"}
MIN_SEGMENT_LENGTH_M = 20.0
ENDPOINT_AUTO_SNAP_M = 30.0
ENDPOINT_WARN_M = 100.0
BOUNDARY_TOLERANCE_DEGREE = 0.0002
SHARP_TURN_DEGREE = 25.0


class NavigationCenterlineSegmentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def generate_segments(
        self,
        channel_id: int,
        body: NavigationCenterlineSegmentGenerateRequest,
    ) -> NavigationCenterlineSegmentGenerateResponse:
        channel = await self._ensure_channel(channel_id)
        boundary = await self._current_boundary(channel_id)
        if boundary is None:
            return NavigationCenterlineSegmentGenerateResponse(
                status_code="BLOCKED",
                message="当前航道还没有已发布边界，无法生成中心线区段。",
                channel_id=channel_id,
                blocker_codes=["NO_PUBLISHED_BOUNDARY"],
                next_path=f"/navigation/production/boundaries?channel_id={channel_id}",
            )

        active_segments = await self._active_segments(channel_id)
        if active_segments and not body.force:
            return NavigationCenterlineSegmentGenerateResponse(
                status_code="EXISTS",
                message=f"已存在 {len(active_segments)} 个中心线区段，请逐段修复确认；如边界或候选中心线已变化，请重新生成。",
                channel_id=channel_id,
                segment_count=len(active_segments),
                need_repair_count=self._need_repair_count(active_segments),
                confirmed_count=sum(1 for item in active_segments if item.segment_status_code == "CONFIRMED"),
                segment_ids=[int(item.id) for item in active_segments],
                next_path=f"/navigation/production/centerlines?channel_id={channel_id}",
            )
        for item in active_segments:
            item.segment_status_code = "ARCHIVED"

        source = await self._source_lines(channel_id)
        if source is None:
            line = self._rough_line_from_boundary(boundary.geometry_json)
            if line is None:
                return NavigationCenterlineSegmentGenerateResponse(
                    status_code="BLOCKED",
                    message="当前边界无法自动生成粗中心线，请在区段工作台中补画起始区段。",
                    channel_id=channel_id,
                    blocker_codes=["CENTERLINE_SEGMENT_GENERATION_FAILED"],
                    next_path=f"/navigation/production/centerlines?channel_id={channel_id}",
                )
            lines = [line]
            centerline_id = None
            source_type = "BOUNDARY_DERIVED_ROUGH"
        else:
            lines, centerline_id, source_type = source

        segment_lines = self._split_source_lines(lines, float(body.segment_length_km or 5.0))
        if not segment_lines:
            return NavigationCenterlineSegmentGenerateResponse(
                status_code="BLOCKED",
                message="当前中心线来源无法拆分为有效区段，请补画起始区段。",
                channel_id=channel_id,
                blocker_codes=["CENTERLINE_SEGMENT_GENERATION_FAILED"],
                next_path=f"/navigation/production/centerlines?channel_id={channel_id}",
            )

        rows: list[NavigationCenterlineSegment] = []
        for index, line in enumerate(segment_lines, start=1):
            geometry_json = self._geometry_json(line)
            row = NavigationCenterlineSegment(
                channel_id=channel_id,
                centerline_id=centerline_id,
                segment_no=f"{index:03d}",
                segment_name=f"{channel.channel_name}中心线区段 {index:03d}",
                segment_status_code="NEED_REPAIR" if source_type == "BOUNDARY_DERIVED_ROUGH" else "CANDIDATE",
                geometry_json=geometry_json,
                source_type_code=source_type,
                quality_code="READY_WITH_WARNING" if source_type == "BOUNDARY_DERIVED_ROUGH" else "READY",
                source_trace_json={
                    "source_type_code": source_type,
                    "source_centerline_id": centerline_id,
                    "segment_length_km": body.segment_length_km,
                    "generated_at": self._now().isoformat(),
                    "force": body.force,
                },
            )
            self._apply_geometry_metrics(row, line)
            self.session.add(row)
            rows.append(row)
        await self.session.flush()

        for index, row in enumerate(rows):
            row.previous_segment_id = int(rows[index - 1].id) if index > 0 else None
            row.next_segment_id = int(rows[index + 1].id) if index + 1 < len(rows) else None
        await self.session.flush()

        for row in rows:
            validation = await self._validate_row(row)
            self._apply_validation(row, validation, generated_from_boundary=source_type == "BOUNDARY_DERIVED_ROUGH")
        await self.session.commit()

        created_rows = await self._active_segments(channel_id)
        return NavigationCenterlineSegmentGenerateResponse(
            status_code="CREATED",
            message=f"已生成 {len(created_rows)} 个中心线区段，请逐段修复确认后合并发布。",
            channel_id=channel_id,
            segment_count=len(created_rows),
            need_repair_count=self._need_repair_count(created_rows),
            confirmed_count=sum(1 for item in created_rows if item.segment_status_code == "CONFIRMED"),
            segment_ids=[int(item.id) for item in created_rows],
            next_path=f"/navigation/production/centerlines?channel_id={channel_id}",
        )

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
            version_no=1,
            is_current=True,
            source_trace_json={
                "source": "CENTERLINE_SEGMENT",
                "segment_count": len(rows),
                "segment_ids": [int(row.id) for row in rows],
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

    async def _source_lines(self, channel_id: int) -> tuple[list[LineString], int, str] | None:
        rows = list(
            (
                await self.session.execute(
                    select(NavigationChannelCenterline)
                    .where(
                        NavigationChannelCenterline.channel_id == channel_id,
                        NavigationChannelCenterline.geometry_json.is_not(None),
                        or_(
                            NavigationChannelCenterline.source_type_code.in_(SOURCE_CENTERLINE_TYPES),
                            NavigationChannelCenterline.review_status_code == "PUBLISHED",
                        ),
                    )
                    .order_by(
                        NavigationChannelCenterline.is_current.desc(),
                        NavigationChannelCenterline.review_status_code.desc(),
                        NavigationChannelCenterline.id.desc(),
                    )
                    .limit(20)
                )
            ).scalars()
        )
        for row in rows:
            lines = self._lines_from_json(row.geometry_json)
            if lines:
                source_type = "PUBLISHED" if row.review_status_code == "PUBLISHED" else row.source_type_code
                return lines, int(row.id), source_type
        return None

    def _rough_line_from_boundary(self, geometry_json: dict[str, Any]) -> LineString | None:
        try:
            geometry = shape(self._geojson_geometry(geometry_json))
            geometry = make_valid(geometry)
        except Exception:
            return None
        if geometry.is_empty:
            return None
        polygons = []
        if geometry.geom_type == "Polygon":
            polygons = [geometry]
        elif geometry.geom_type == "MultiPolygon":
            polygons = list(geometry.geoms)
        elif isinstance(geometry, GeometryCollection):
            polygons = [part for part in geometry.geoms if part.geom_type == "Polygon"]
        if not polygons:
            return None
        polygon = max(polygons, key=lambda item: item.area)
        min_lng, min_lat, max_lng, max_lat = polygon.bounds
        if max_lng <= min_lng or max_lat <= min_lat:
            return None
        if (max_lng - min_lng) >= (max_lat - min_lat):
            mid_lat = (min_lat + max_lat) / 2
            guide = LineString([(min_lng, mid_lat), (max_lng, mid_lat)])
        else:
            mid_lng = (min_lng + max_lng) / 2
            guide = LineString([(mid_lng, min_lat), (mid_lng, max_lat)])
        return self._longest_line(guide.intersection(polygon))

    def _split_source_lines(self, lines: list[LineString], segment_length_km: float) -> list[LineString]:
        output: list[LineString] = []
        for line in lines:
            output.extend(self._split_line(line, max(segment_length_km, 0.1) * 1000.0))
        return [line for line in output if self._length_m(line) >= 1.0]

    def _split_line(self, line: LineString, target_length_m: float) -> list[LineString]:
        length_m = self._length_m(line)
        if length_m <= 0:
            return []
        count = max(1, int(math.ceil(length_m / target_length_m)))
        if count == 1:
            return [self._clean_line(line)]
        parts: list[LineString] = []
        interior = [(Point(coord), line.project(Point(coord), normalized=True)) for coord in line.coords[1:-1]]
        for index in range(count):
            start_ratio = index / count
            end_ratio = (index + 1) / count
            coords: list[tuple[float, float]] = []
            start = line.interpolate(start_ratio, normalized=True)
            end = line.interpolate(end_ratio, normalized=True)
            coords.append((float(start.x), float(start.y)))
            coords.extend(
                (float(point.x), float(point.y))
                for point, ratio in interior
                if start_ratio < ratio < end_ratio
            )
            coords.append((float(end.x), float(end.y)))
            cleaned = self._clean_coords(coords)
            if len(cleaned) >= 2:
                parts.append(LineString(cleaned))
        return parts

    async def _validate_row(self, row: NavigationCenterlineSegment) -> NavigationGeometryDraftValidationResponse:
        if row.geometry_json is None:
            issues = [
                self._issue("SEGMENT_GEOMETRY_INVALID", "ERROR", "中心线区段缺少几何。", "请补画当前区段。")
            ]
            return self._validation_response(issues=issues, bbox={}, length_m=None, point_count=0)
        line = self._line_from_json(row.geometry_json, code="SEGMENT_GEOMETRY_INVALID")
        boundary = await self._current_boundary(row.channel_id)
        issues: list[NavigationGeometryDraftValidationIssueResponse] = []
        coords = list(line.coords)
        if len(coords) < 2:
            issues.append(self._issue("SEGMENT_GEOMETRY_INVALID", "ERROR", "中心线区段至少需要 2 个点。"))
        if any(not self._coord_legal(coord) for coord in coords):
            issues.append(self._issue("SEGMENT_GEOMETRY_INVALID", "ERROR", "中心线区段坐标超出合法经纬度范围。"))
        length_m = self._length_m(line)
        if length_m < MIN_SEGMENT_LENGTH_M:
            issues.append(
                self._issue(
                    "SEGMENT_TOO_SHORT",
                    "ERROR",
                    f"中心线区段长度低于 {MIN_SEGMENT_LENGTH_M:.0f} 米。",
                    "请补画或延长当前区段。",
                    self._point_geometry(coords[0]) if coords else None,
                )
            )
        if boundary is None:
            issues.append(self._issue("NO_PUBLISHED_BOUNDARY", "ERROR", "当前航道缺少已发布边界。"))
        else:
            boundary_geometry = make_valid(shape(self._geojson_geometry(boundary.geometry_json)))
            if not boundary_geometry.buffer(BOUNDARY_TOLERANCE_DEGREE).covers(line):
                issues.append(
                    self._issue(
                        "SEGMENT_OUT_OF_BOUNDARY",
                        "ERROR",
                        "中心线区段明显超出当前航道边界。",
                        "请将区段修回已发布边界范围内。",
                        self._geometry_json(line),
                    )
                )
            elif not boundary_geometry.covers(line):
                issues.append(
                    self._issue(
                        "SEGMENT_NEAR_BOUNDARY_TOLERATED",
                        "WARNING",
                        "中心线区段贴近或轻微越过边界容差，请人工复核。",
                    )
                )
        issues.extend(self._sharp_turn_issues(line))
        previous_row, next_row = await self._neighbor_rows(row)
        start_connected, end_connected = True, True
        if previous_row is not None and previous_row.geometry_json:
            previous_line = self._line_from_json(previous_row.geometry_json, code="SEGMENT_GEOMETRY_INVALID")
            distance = self._distance_m(previous_line.coords[-1], coords[0])
            start_connected = distance <= ENDPOINT_AUTO_SNAP_M
            if distance > ENDPOINT_WARN_M:
                issues.append(
                    self._issue(
                        "SEGMENT_ENDPOINT_DISCONNECTED",
                        "ERROR",
                        f"当前区段起点与上一段终点距离 {distance:.1f} 米，超过允许阈值。",
                        "请吸附到上一段终点或重新补画。",
                        self._point_geometry(coords[0]),
                    )
                )
            elif distance > ENDPOINT_AUTO_SNAP_M:
                issues.append(
                    self._issue(
                        "SEGMENT_ENDPOINT_DISCONNECTED",
                        "WARNING",
                        f"当前区段起点与上一段终点距离 {distance:.1f} 米，建议吸附。",
                        "保存或确认前请执行端点吸附。",
                        self._point_geometry(coords[0]),
                    )
                )
        if next_row is not None and next_row.geometry_json:
            next_line = self._line_from_json(next_row.geometry_json, code="SEGMENT_GEOMETRY_INVALID")
            distance = self._distance_m(coords[-1], next_line.coords[0])
            end_connected = distance <= ENDPOINT_AUTO_SNAP_M
            if distance > ENDPOINT_WARN_M:
                issues.append(
                    self._issue(
                        "SEGMENT_ENDPOINT_DISCONNECTED",
                        "ERROR",
                        f"当前区段终点与下一段起点距离 {distance:.1f} 米，超过允许阈值。",
                        "请吸附到下一段起点或重新补画。",
                        self._point_geometry(coords[-1]),
                    )
                )
            elif distance > ENDPOINT_AUTO_SNAP_M:
                issues.append(
                    self._issue(
                        "SEGMENT_ENDPOINT_DISCONNECTED",
                        "WARNING",
                        f"当前区段终点与下一段起点距离 {distance:.1f} 米，建议吸附。",
                        "保存或确认前请执行端点吸附。",
                        self._point_geometry(coords[-1]),
                    )
                )
        row.start_connected_flag = start_connected
        row.end_connected_flag = end_connected
        return self._validation_response(
            issues=issues,
            bbox=self._public_bbox(self._bbox(row.geometry_json)),
            length_m=length_m,
            point_count=len(coords),
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

    def _lines_from_json(self, geometry_json: dict[str, Any]) -> list[LineString]:
        try:
            geometry = shape(self._geojson_geometry(geometry_json))
        except Exception:
            return []
        if isinstance(geometry, LineString):
            return [self._clean_line(geometry)]
        if isinstance(geometry, MultiLineString):
            return [self._clean_line(item) for item in geometry.geoms if len(item.coords) >= 2]
        if isinstance(geometry, GeometryCollection):
            lines: list[LineString] = []
            for part in geometry.geoms:
                if isinstance(part, LineString) and len(part.coords) >= 2:
                    lines.append(self._clean_line(part))
                if isinstance(part, MultiLineString):
                    lines.extend(self._clean_line(item) for item in part.geoms if len(item.coords) >= 2)
            return lines
        return []

    def _line_from_json(self, geometry_json: dict[str, Any], *, code: str) -> LineString:
        try:
            geometry = shape(self._geojson_geometry(geometry_json))
        except Exception:
            self._fail(code, "中心线区段几何解析失败")
        if not isinstance(geometry, LineString) or len(geometry.coords) < 2:
            self._fail(code, "中心线区段只支持 LineString")
        return self._clean_line(geometry)

    def _longest_line(self, geometry: Any) -> LineString | None:
        if geometry is None or geometry.is_empty:
            return None
        if isinstance(geometry, LineString):
            return self._clean_line(geometry) if len(geometry.coords) >= 2 else None
        if isinstance(geometry, MultiLineString):
            lines = [item for item in geometry.geoms if len(item.coords) >= 2]
            return self._clean_line(max(lines, key=self._length_m)) if lines else None
        if isinstance(geometry, GeometryCollection):
            lines = []
            for part in geometry.geoms:
                line = self._longest_line(part)
                if line is not None:
                    lines.append(line)
            return max(lines, key=self._length_m) if lines else None
        return None

    def _apply_geometry_metrics(self, row: NavigationCenterlineSegment, line: LineString) -> None:
        geometry_json = self._geometry_json(line)
        bbox = self._bbox(geometry_json)
        coords = list(line.coords)
        row.length_m = round(self._length_m(line), 2)
        row.start_lng = float(coords[0][0])
        row.start_lat = float(coords[0][1])
        row.end_lng = float(coords[-1][0])
        row.end_lat = float(coords[-1][1])
        row.bbox_min_lng = bbox["bbox_min_lng"]
        row.bbox_min_lat = bbox["bbox_min_lat"]
        row.bbox_max_lng = bbox["bbox_max_lng"]
        row.bbox_max_lat = bbox["bbox_max_lat"]

    def _apply_validation(
        self,
        row: NavigationCenterlineSegment,
        validation: NavigationGeometryDraftValidationResponse,
        *,
        generated_from_boundary: bool,
    ) -> None:
        summary = self._validation_summary(validation)
        row.validation_summary_json = summary
        row.issue_summary_json = {
            "issue_count": validation.issue_count,
            "error_count": validation.error_count,
            "warning_count": validation.warning_count,
            "issue_codes": [item.issue_code for item in validation.issues],
        }
        if generated_from_boundary:
            row.segment_status_code = "NEED_REPAIR"
            row.quality_code = "NEED_REPAIR" if validation.error_count else "READY_WITH_WARNING"
        else:
            row.quality_code = validation.quality_code

    def _sharp_turn_issues(self, line: LineString) -> list[NavigationGeometryDraftValidationIssueResponse]:
        coords = [(float(lng), float(lat)) for lng, lat, *_rest in line.coords]
        issues: list[NavigationGeometryDraftValidationIssueResponse] = []
        for index in range(1, len(coords) - 1):
            a, b, c = coords[index - 1], coords[index], coords[index + 1]
            turn = self._turn_angle_degree(a, b, c)
            if turn < SHARP_TURN_DEGREE:
                issues.append(
                    self._issue(
                        "SEGMENT_SHARP_TURN_REVIEW",
                        "WARNING",
                        f"区段第 {index + 1} 个点附近存在急转弯，请复核。",
                        "必要时调整顶点使中心线更顺滑。",
                        self._point_geometry(b),
                    )
                )
                break
        return issues

    def _turn_angle_degree(self, a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
        ab = (a[0] - b[0], a[1] - b[1])
        cb = (c[0] - b[0], c[1] - b[1])
        ab_len = math.hypot(*ab)
        cb_len = math.hypot(*cb)
        if ab_len == 0 or cb_len == 0:
            return 180.0
        cos_value = max(-1.0, min(1.0, (ab[0] * cb[0] + ab[1] * cb[1]) / (ab_len * cb_len)))
        return math.degrees(math.acos(cos_value))

    def _validation_response(
        self,
        *,
        issues: list[NavigationGeometryDraftValidationIssueResponse],
        bbox: dict[str, float | None],
        length_m: float | None,
        point_count: int,
    ) -> NavigationGeometryDraftValidationResponse:
        error_count = sum(1 for issue in issues if issue.severity_code == "ERROR")
        warning_count = sum(1 for issue in issues if issue.severity_code == "WARNING")
        quality_code = "PUBLISH_BLOCKED" if error_count else "READY_WITH_WARNING" if warning_count else "READY"
        return NavigationGeometryDraftValidationResponse(
            valid=error_count == 0,
            publishable=error_count == 0,
            quality_code=quality_code,
            issue_count=len(issues),
            error_count=error_count,
            warning_count=warning_count,
            length_m=round(length_m, 2) if length_m is not None else None,
            area_m2=None,
            point_count=point_count,
            ring_count=0,
            bbox=bbox,
            issues=issues,
        )

    def _response(self, row: NavigationCenterlineSegment) -> NavigationCenterlineSegmentResponse:
        return NavigationCenterlineSegmentResponse(
            id=int(row.id),
            channel_id=int(row.channel_id),
            centerline_id=int(row.centerline_id) if row.centerline_id is not None else None,
            segment_no=row.segment_no,
            segment_name=row.segment_name,
            segment_status_code=row.segment_status_code,
            source_type_code=row.source_type_code,
            quality_code=row.quality_code,
            length_m=self._float(row.length_m),
            start_lng=self._float(row.start_lng),
            start_lat=self._float(row.start_lat),
            end_lng=self._float(row.end_lng),
            end_lat=self._float(row.end_lat),
            bbox_min_lng=self._float(row.bbox_min_lng),
            bbox_min_lat=self._float(row.bbox_min_lat),
            bbox_max_lng=self._float(row.bbox_max_lng),
            bbox_max_lat=self._float(row.bbox_max_lat),
            previous_segment_id=int(row.previous_segment_id) if row.previous_segment_id is not None else None,
            next_segment_id=int(row.next_segment_id) if row.next_segment_id is not None else None,
            start_connected_flag=bool(row.start_connected_flag),
            end_connected_flag=bool(row.end_connected_flag),
            geometry_json=row.geometry_json,
            issue_summary_json=row.issue_summary_json,
            validation_summary_json=row.validation_summary_json,
            source_trace_json=row.source_trace_json,
        )

    def _geometry_json(self, geometry: LineString) -> dict[str, Any]:
        return json.loads(json.dumps(mapping(geometry)))

    def _geojson_geometry(self, geometry_json: dict[str, Any]) -> dict[str, Any]:
        if geometry_json.get("type") == "Feature":
            geometry = geometry_json.get("geometry")
            if isinstance(geometry, dict):
                return geometry
        return geometry_json

    def _bbox(self, geometry_json: dict[str, Any] | None) -> dict[str, float | None]:
        coords = self._coordinate_pairs((geometry_json or {}).get("coordinates"))
        if not coords:
            return {"bbox_min_lng": None, "bbox_min_lat": None, "bbox_max_lng": None, "bbox_max_lat": None}
        return {
            "bbox_min_lng": min(point[0] for point in coords),
            "bbox_min_lat": min(point[1] for point in coords),
            "bbox_max_lng": max(point[0] for point in coords),
            "bbox_max_lat": max(point[1] for point in coords),
        }

    def _public_bbox(self, bbox: dict[str, float | None]) -> dict[str, float | None]:
        return {
            "min_lng": bbox.get("bbox_min_lng"),
            "min_lat": bbox.get("bbox_min_lat"),
            "max_lng": bbox.get("bbox_max_lng"),
            "max_lat": bbox.get("bbox_max_lat"),
        }

    def _coordinate_pairs(self, value: Any) -> list[tuple[float, float]]:
        pairs: list[tuple[float, float]] = []

        def walk(item: Any) -> None:
            if not isinstance(item, list):
                return
            if len(item) >= 2 and all(isinstance(item[index], (int, float)) for index in (0, 1)):
                pairs.append((float(item[0]), float(item[1])))
                return
            for child in item:
                walk(child)

        walk(value)
        return pairs

    def _clean_line(self, line: LineString) -> LineString:
        coords = [(float(lng), float(lat)) for lng, lat, *_rest in line.coords]
        return LineString(self._clean_coords(coords))

    def _clean_coords(self, coords: list[tuple[float, float]]) -> list[tuple[float, float]]:
        cleaned: list[tuple[float, float]] = []
        for lng, lat in coords:
            point = (float(lng), float(lat))
            if not cleaned or self._distance_m(cleaned[-1], point) > 0.01:
                cleaned.append(point)
        return cleaned

    def _coord_legal(self, coord: Any) -> bool:
        try:
            lng = float(coord[0])
            lat = float(coord[1])
        except Exception:
            return False
        return -180 <= lng <= 180 and -90 <= lat <= 90

    def _length_m(self, line: LineString) -> float:
        coords = list(line.coords)
        if len(coords) < 2:
            return 0.0
        lngs = [float(coord[0]) for coord in coords]
        lats = [float(coord[1]) for coord in coords]
        return abs(float(GEOD.line_length(lngs, lats)))

    def _distance_m(self, start: Any, end: Any) -> float:
        _, _, distance = GEOD.inv(float(start[0]), float(start[1]), float(end[0]), float(end[1]))
        return abs(float(distance))

    def _issue(
        self,
        issue_code: str,
        severity_code: str,
        message: str,
        suggestion: str | None = None,
        geometry_json: dict[str, Any] | None = None,
    ) -> NavigationGeometryDraftValidationIssueResponse:
        return NavigationGeometryDraftValidationIssueResponse(
            issue_code=issue_code,
            severity_code=severity_code,
            message=message,
            suggestion=suggestion,
            geometry_json=geometry_json,
        )

    def _point_geometry(self, coord: Any) -> dict[str, Any]:
        return {"type": "Point", "coordinates": [float(coord[0]), float(coord[1])]}

    def _validation_summary(self, validation: NavigationGeometryDraftValidationResponse) -> dict[str, Any]:
        return {
            "quality_code": validation.quality_code,
            "issue_count": validation.issue_count,
            "error_count": validation.error_count,
            "warning_count": validation.warning_count,
            "length_m": validation.length_m,
            "point_count": validation.point_count,
            "issues": [self._dump_model(item) for item in validation.issues],
        }

    def _need_repair_count(self, rows: list[NavigationCenterlineSegment]) -> int:
        return sum(1 for item in rows if item.segment_status_code in {"NEED_REPAIR", "PUBLISH_BLOCKED"})

    def _dump_model(self, model: Any) -> dict[str, Any]:
        if hasattr(model, "model_dump"):
            return model.model_dump()
        return model.dict()

    def _float(self, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return float(value)
        return float(value)

    def _limit(self, value: int, default: int, max_value: int) -> int:
        return max(1, min(int(value or default), max_value))

    def _now(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    def _fail(self, code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        payload = detail or {"error_code": code, "message": message}
        payload.setdefault("error_code", code)
        raise ValidationError(message, code=code, detail=payload)
