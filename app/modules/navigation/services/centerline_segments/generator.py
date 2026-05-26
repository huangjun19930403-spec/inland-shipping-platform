from __future__ import annotations

import math
from typing import Any

from sqlalchemy import or_, select
from shapely.geometry import GeometryCollection, LineString, Point, shape
from shapely.validation import make_valid

from app.models import NavigationCenterlineSegment, NavigationChannelCenterline
from app.modules.navigation.schemas import (
    NavigationCenterlineSegmentGenerateRequest,
    NavigationCenterlineSegmentGenerateResponse,
)
from app.modules.navigation.services.centerline_segments.types import SOURCE_CENTERLINE_TYPES


class NavigationCenterlineSegmentGeneratorMixin:
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
                return self._generation_blocked(channel_id, "当前边界无法自动生成粗中心线，请在区段工作台中补画起始区段。")
            lines = [line]
            centerline_id = None
            source_type = "BOUNDARY_DERIVED_ROUGH"
        else:
            lines, centerline_id, source_type = source

        segment_lines = self._split_source_lines(lines, float(body.segment_length_km or 5.0))
        if not segment_lines:
            return self._generation_blocked(channel_id, "当前中心线来源无法拆分为有效区段，请补画起始区段。")

        rows: list[NavigationCenterlineSegment] = []
        for index, line in enumerate(segment_lines, start=1):
            row = NavigationCenterlineSegment(
                channel_id=channel_id,
                centerline_id=centerline_id,
                segment_no=f"{index:03d}",
                segment_name=f"{channel.channel_name}中心线区段 {index:03d}",
                segment_status_code="NEED_REPAIR" if source_type == "BOUNDARY_DERIVED_ROUGH" else "CANDIDATE",
                geometry_json=self._geometry_json(line),
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

    def _generation_blocked(self, channel_id: int, message: str) -> NavigationCenterlineSegmentGenerateResponse:
        return NavigationCenterlineSegmentGenerateResponse(
            status_code="BLOCKED",
            message=message,
            channel_id=channel_id,
            blocker_codes=["CENTERLINE_SEGMENT_GENERATION_FAILED"],
            next_path=f"/navigation/production/centerlines?channel_id={channel_id}",
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
            geometry = make_valid(shape(self._geojson_geometry(geometry_json)))
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
