from __future__ import annotations

import math
from collections import defaultdict
from heapq import heappop, heappush
from typing import Any

from sqlalchemy import or_, select
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPoint, Point, shape
from shapely.ops import voronoi_diagram
from shapely.validation import make_valid

from app.models import NavigationCenterlineSegment, NavigationChannelCenterline, NavigationChannelSegment
from app.modules.navigation.schemas import (
    NavigationCenterlineSegmentGenerateRequest,
    NavigationCenterlineSegmentGenerateResponse,
)
from app.modules.navigation.services.centerline_point_sets import NavigationCenterlinePointSetService
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
                confirmed_count=self._operator_confirmed_count(active_segments),
                segment_ids=[int(item.id) for item in active_segments],
                next_path=f"/navigation/production/centerlines?channel_id={channel_id}",
            )
        source_mode = (body.source_mode or "CHANNEL_GUIDE_WITH_BOUNDARY_CLIP").upper()
        if source_mode == "BOUNDARY":
            source_mode = "BOUNDARY_ROUGH_LOCAL"
        if source_mode not in {"CHANNEL_GUIDE_WITH_BOUNDARY_CLIP", "BOUNDARY_ROUGH_LOCAL", "CURRENT_CENTERLINE", "CONTROL_POINTS"}:
            return self._generation_blocked(
                channel_id,
                "中心线区段来源模式无效，请选择基于控制点、航道导向线、边界局部粗生成或从当前中心线切段。",
                ["CENTERLINE_SOURCE_MODE_INVALID"],
            )

        source_meta: dict[str, Any] = {}
        point_set_id: int | None = None
        if source_mode == "CONTROL_POINTS":
            if body.point_set_id is None:
                return self._generation_blocked(
                    channel_id,
                    "基于控制点生成区段必须选择中心线点位版本。",
                    ["CENTERLINE_POINT_SET_REQUIRED"],
                )
            point_service = NavigationCenterlinePointSetService(self.session)
            line, point_set, _points, point_meta, message, blockers = await point_service.line_for_generation(
                channel_id=channel_id,
                point_set_id=int(body.point_set_id),
                boundary=boundary,
            )
            if line is None or point_set is None:
                return self._generation_blocked(channel_id, message, blockers)
            lines = [line]
            centerline_id = None
            source_type = "CONTROL_POINTS_AUTOLINK"
            algorithm = "CONTROL_POINT_AUTOLINK_V1"
            point_set_id = int(point_set.id)
            source_meta = point_meta
        elif source_mode == "CURRENT_CENTERLINE":
            source = await self._source_lines(channel_id)
            if source is None:
                return self._generation_blocked(
                    channel_id,
                    "当前航道没有可切段的已发布中心线，请改用基于当前边界和航道导向线生成。",
                    ["CURRENT_CENTERLINE_MISSING"],
                )
            lines, centerline_id, source_type = source
            algorithm = "CURRENT_CENTERLINE_SPLIT"
        elif source_mode == "CHANNEL_GUIDE_WITH_BOUNDARY_CLIP":
            guide_result = await self._guide_lines_from_boundary(channel_id, boundary)
            if guide_result[0] is None:
                return self._generation_blocked(channel_id, guide_result[1], guide_result[2])
            lines, source_meta = guide_result[0]
            centerline_id = None
            source_type = "CHANNEL_GUIDE_WITH_BOUNDARY_CLIP"
            algorithm = "SEED_GUIDE_BOUNDARY_CLIP_V1"
        else:
            lines, algorithm = self._rough_lines_from_boundary(boundary.geometry_json)
            if not lines:
                return self._generation_blocked(
                    channel_id,
                    "当前边界无法抽取局部粗中心线，请使用“重画当前区段”或手工补画首段开始。",
                    ["BOUNDARY_ROUGH_CENTERLINE_FAILED"],
                )
            centerline_id = None
            source_type = "BOUNDARY_ROUGH_LOCAL"

        segment_lines = self._split_source_lines(lines, float(body.segment_length_km or 5.0))
        if not segment_lines:
            return self._generation_blocked(
                channel_id,
                "当前来源无法拆分为有效中心线区段，请使用“重画当前区段”或手工补画首段开始。",
                ["CENTERLINE_SEGMENT_SPLIT_FAILED"],
            )

        rows: list[NavigationCenterlineSegment] = []
        for index, line in enumerate(segment_lines, start=1):
            row = NavigationCenterlineSegment(
                channel_id=channel_id,
                centerline_id=centerline_id,
                segment_no=f"{index:03d}",
                segment_name=f"{channel.channel_name}中心线区段 {index:03d}",
                segment_status_code="NEED_REPAIR" if source_type in {"BOUNDARY_ROUGH_LOCAL", "CHANNEL_GUIDE_WITH_BOUNDARY_CLIP", "CONTROL_POINTS_AUTOLINK"} else "CANDIDATE",
                geometry_json=self._geometry_json(line),
                source_type_code=source_type,
                quality_code="READY_WITH_WARNING" if source_type in {"BOUNDARY_ROUGH_LOCAL", "CHANNEL_GUIDE_WITH_BOUNDARY_CLIP", "CONTROL_POINTS_AUTOLINK"} else "READY",
                source_trace_json={
                    "source_mode": source_mode,
                    "source_type_code": source_type,
                    "source_centerline_id": centerline_id,
                    "source_boundary_id": int(boundary.id),
                    "based_on_boundary_id": int(boundary.id),
                    "algorithm": algorithm,
                    "segment_length_km": body.segment_length_km,
                    "generated_at": self._now().isoformat(),
                    "force": body.force,
                    **source_meta,
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
            self._apply_validation(row, validation, generated_from_boundary=source_type in {"BOUNDARY_ROUGH_LOCAL", "CHANNEL_GUIDE_WITH_BOUNDARY_CLIP", "CONTROL_POINTS_AUTOLINK"})
        for item in active_segments:
            item.segment_status_code = "ARCHIVED"
            trace = dict(item.source_trace_json or {})
            trace["archived_at"] = self._now().isoformat()
            trace["archive_reason"] = "replaced_by_centerline_segment_generation"
            item.source_trace_json = trace
        if point_set_id is not None:
            await NavigationCenterlinePointSetService(self.session).mark_current(point_set_id)
        await self.session.commit()

        created_rows = await self._active_segments(channel_id)
        return NavigationCenterlineSegmentGenerateResponse(
            status_code="CREATED",
            message=f"已生成 {len(created_rows)} 个中心线区段，请逐段修复确认后合并发布。",
            channel_id=channel_id,
            segment_count=len(created_rows),
            need_repair_count=self._need_repair_count(created_rows),
            confirmed_count=self._operator_confirmed_count(created_rows),
            segment_ids=[int(item.id) for item in created_rows],
            next_path=f"/navigation/production/centerlines?channel_id={channel_id}",
        )

    def _generation_blocked(
        self,
        channel_id: int,
        message: str,
        blocker_codes: list[str] | None = None,
    ) -> NavigationCenterlineSegmentGenerateResponse:
        return NavigationCenterlineSegmentGenerateResponse(
            status_code="BLOCKED",
            message=message,
            channel_id=channel_id,
            blocker_codes=blocker_codes or ["CENTERLINE_SEGMENT_GENERATION_FAILED"],
            next_path=f"/navigation/production/centerlines?channel_id={channel_id}",
        )

    async def _guide_lines_from_boundary(
        self,
        channel_id: int,
        boundary: Any,
    ) -> tuple[tuple[list[LineString], dict[str, Any]] | None, str, list[str]]:
        rows = list(
            (
                await self.session.execute(
                    select(NavigationChannelSegment)
                    .where(
                        NavigationChannelSegment.channel_id == channel_id,
                        NavigationChannelSegment.guide_geometry_json.is_not(None),
                        NavigationChannelSegment.geometry_status_code != "ARCHIVED",
                    )
                    .order_by(
                        NavigationChannelSegment.sequence_no,
                        NavigationChannelSegment.sort_order,
                        NavigationChannelSegment.id,
                    )
                )
            ).scalars()
        )
        guide_lines: list[tuple[NavigationChannelSegment, LineString]] = []
        for row in rows:
            for line in self._lines_from_json(row.guide_geometry_json or {}):
                if self._length_m(line) >= 100.0:
                    guide_lines.append((row, line))
        if not guide_lines:
            return None, "当前航道缺少生产导向线，不能生成完整长航道中心线。请先重置/补齐航道图生产 seed 导向线。", ["CENTERLINE_GUIDE_MISSING"]
        if all((row.guide_source_type_code or "").startswith("SEED_BOUNDARY_") for row, _line in guide_lines):
            expected_length_m = sum(self._length_m(line) for _row, line in guide_lines)
            return (
                [line for _row, line in guide_lines],
                {
                    "source_guide_segment_ids": [int(row.id) for row, _line in guide_lines],
                    "source_guide_segment_codes": [row.segment_code for row, _line in guide_lines],
                    "expected_length_m": round(expected_length_m, 2),
                    "clipped_length_m": round(expected_length_m, 2),
                    "coverage_ratio": 1.0,
                    "bbox_coverage_ratio": 1.0,
                    "boundary_clip_mode": "SEED_BOUNDARY_GUIDE_PASSTHROUGH",
                    "boundary_clip_warning": "Guide was derived from the current boundary and is kept contiguous for seed Graph generation.",
                },
            ), "", []

        boundary_geometry = self._boundary_geometry(boundary.geometry_json)
        if boundary_geometry is None:
            return None, "当前发布边界几何无效，不能基于边界裁剪中心线。", ["PUBLISHED_BOUNDARY_GEOMETRY_INVALID"]

        all_guide_bounds = self._bounds_for_lines([line for _row, line in guide_lines])
        boundary_bounds = self._bounds_dict(boundary_geometry.bounds)
        bbox_ratio = self._bbox_coverage_ratio(all_guide_bounds, boundary_bounds)
        expected_length_m = sum(self._length_m(line) for _row, line in guide_lines)
        clipped_lines = self._clip_guides_to_boundary(guide_lines, boundary_geometry)
        clipped_length_m = sum(self._length_m(line) for line in clipped_lines)
        length_ratio = clipped_length_m / expected_length_m if expected_length_m > 0 else 0.0
        min_ratio = 0.65 if expected_length_m >= 200_000 else 0.35
        if bbox_ratio >= 0.9 and length_ratio < 0.95:
            return (
                [line for _row, line in guide_lines],
                {
                    "source_guide_segment_ids": [int(row.id) for row, _line in guide_lines],
                    "source_guide_segment_codes": [row.segment_code for row, _line in guide_lines],
                    "expected_length_m": round(expected_length_m, 2),
                    "clipped_length_m": round(clipped_length_m, 2),
                    "coverage_ratio": round(length_ratio, 6),
                    "bbox_coverage_ratio": round(bbox_ratio, 6),
                    "boundary_clip_mode": "GUIDE_PASSTHROUGH_BBOX_READY",
                    "boundary_clip_warning": "Boundary bbox covers the guide, but polygon clipping fragmented the long-channel guide.",
                },
            ), "", []
        if bbox_ratio < min_ratio or length_ratio < min_ratio:
            return (
                None,
                (
                    "当前发布边界覆盖范围小于航道导向线，中心线生成已阻断。"
                    f"边界覆盖率 bbox={bbox_ratio:.0%} / 裁剪长度={length_ratio:.0%}，请先发布完整边界版本。"
                ),
                ["BOUNDARY_COVERAGE_INCOMPLETE"],
            )
        if not clipped_lines:
            return None, "当前发布边界没有覆盖航道导向线，不能生成中心线区段。", ["CENTERLINE_GUIDE_OUT_OF_BOUNDARY"]
        return (
            clipped_lines,
            {
                "source_guide_segment_ids": [int(row.id) for row, _line in guide_lines],
                "source_guide_segment_codes": [row.segment_code for row, _line in guide_lines],
                "expected_length_m": round(expected_length_m, 2),
                "clipped_length_m": round(clipped_length_m, 2),
                "coverage_ratio": round(length_ratio, 6),
                "bbox_coverage_ratio": round(bbox_ratio, 6),
            },
        ), "", []

    def _boundary_geometry(self, geometry_json: dict[str, Any]) -> Any | None:
        try:
            geometry = make_valid(shape(self._geojson_geometry(geometry_json)))
        except Exception:
            return None
        return None if geometry.is_empty else geometry

    def _clip_guides_to_boundary(
        self,
        guide_lines: list[tuple[NavigationChannelSegment, LineString]],
        boundary_geometry: Any,
    ) -> list[LineString]:
        output: list[tuple[int, float, LineString]] = []
        working_boundary = boundary_geometry.buffer(0.0005)
        for source_index, (_row, guide_line) in enumerate(guide_lines):
            intersection = guide_line.intersection(working_boundary)
            for line in self._flatten_lines(intersection):
                cleaned = self._clean_line(line)
                if self._length_m(cleaned) < 100.0:
                    continue
                midpoint = cleaned.interpolate(0.5, normalized=True)
                output.append((source_index, guide_line.project(midpoint), cleaned))
        output.sort(key=lambda item: (item[0], item[1]))
        return [item[2] for item in output]

    def _bounds_for_lines(self, lines: list[LineString]) -> dict[str, float]:
        return {
            "min_lng": min(line.bounds[0] for line in lines),
            "min_lat": min(line.bounds[1] for line in lines),
            "max_lng": max(line.bounds[2] for line in lines),
            "max_lat": max(line.bounds[3] for line in lines),
        }

    def _bounds_dict(self, bounds: tuple[float, float, float, float]) -> dict[str, float]:
        return {"min_lng": bounds[0], "min_lat": bounds[1], "max_lng": bounds[2], "max_lat": bounds[3]}

    def _bbox_coverage_ratio(self, expected: dict[str, float], actual: dict[str, float]) -> float:
        inter_lng = max(0.0, min(expected["max_lng"], actual["max_lng"]) - max(expected["min_lng"], actual["min_lng"]))
        inter_lat = max(0.0, min(expected["max_lat"], actual["max_lat"]) - max(expected["min_lat"], actual["min_lat"]))
        expected_lng = max(expected["max_lng"] - expected["min_lng"], 0.0)
        expected_lat = max(expected["max_lat"] - expected["min_lat"], 0.0)
        if expected_lat < 1e-9 and expected_lng > 0:
            return max(0.0, min(1.0, inter_lng / expected_lng))
        if expected_lng < 1e-9 and expected_lat > 0:
            return max(0.0, min(1.0, inter_lat / expected_lat))
        expected_area = max(expected_lng * expected_lat, 1e-9)
        return max(0.0, min(1.0, (inter_lng * inter_lat) / expected_area))

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

    def _rough_lines_from_boundary(self, geometry_json: dict[str, Any]) -> tuple[list[LineString], str | None]:
        try:
            geometry = make_valid(shape(self._geojson_geometry(geometry_json)))
        except Exception:
            return [], None
        if geometry.is_empty:
            return [], None
        polygons = []
        if geometry.geom_type == "Polygon":
            polygons = [geometry]
        elif geometry.geom_type == "MultiPolygon":
            polygons = list(geometry.geoms)
        elif isinstance(geometry, GeometryCollection):
            polygons = [part for part in geometry.geoms if part.geom_type == "Polygon"]
        if not polygons:
            return [], None
        polygons = sorted(polygons, key=lambda item: item.area, reverse=True)
        max_area = float(polygons[0].area)
        min_area = max(max_area * 0.01, 1e-10)
        lines: list[LineString] = []
        algorithms: set[str] = set()
        for polygon in polygons[:40]:
            if float(polygon.area) < min_area:
                continue
            line = self._medial_axis_line_from_polygon(polygon)
            if line is not None and self._length_m(line) >= 20.0:
                lines.append(line)
                algorithms.add("VORONOI_MEDIAL_AXIS_V1")
                continue
            line = self._bbox_line_from_polygon(polygon)
            if line is not None and self._length_m(line) >= 20.0:
                lines.append(line)
                algorithms.add("BOUNDARY_BBOX_CENTERLINE_FALLBACK")
        if not lines:
            return [], None
        algorithm = "BOUNDARY_COMPONENT_MEDIAL_AXIS_V1" if len(algorithms) > 1 or len(lines) > 1 else next(iter(algorithms))
        return lines, algorithm

    def _rough_line_from_boundary(self, geometry_json: dict[str, Any]) -> tuple[LineString | None, str | None]:
        lines, algorithm = self._rough_lines_from_boundary(geometry_json)
        if not lines:
            return None, None
        return max(lines, key=self._length_m), algorithm

    def _bbox_line_from_polygon(self, polygon: Any) -> LineString | None:
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

    def _medial_axis_line_from_polygon(self, polygon: Any) -> LineString | None:
        min_lng, min_lat, max_lng, max_lat = polygon.bounds
        span = max(max_lng - min_lng, max_lat - min_lat)
        if span <= 0:
            return None
        tolerance = max(span / 900.0, 0.00008)
        working = make_valid(polygon.simplify(tolerance, preserve_topology=True))
        if working.is_empty:
            working = polygon
        points = self._sample_polygon_boundary_points(working, max_points=260)
        if len(points) < 4:
            return None
        try:
            diagram = voronoi_diagram(
                MultiPoint(points),
                envelope=working.envelope.buffer(span * 0.05),
                edges=True,
            )
        except Exception:
            return None
        candidates = self._internal_voronoi_lines(diagram, working)
        if not candidates:
            return None
        return self._longest_graph_path(candidates)

    def _sample_polygon_boundary_points(self, polygon: Any, *, max_points: int) -> list[tuple[float, float]]:
        rings = [polygon.exterior, *list(getattr(polygon, "interiors", []))]
        weighted = [(ring, max(float(ring.length), 0.0)) for ring in rings if ring and ring.length > 0]
        total = sum(length for _ring, length in weighted)
        if total <= 0:
            return []
        points: list[tuple[float, float]] = []
        for ring, length in weighted:
            count = max(8, int(max_points * (length / total)))
            count = min(count, max_points - len(points))
            if count <= 0:
                break
            for index in range(count):
                point = ring.interpolate(index / count, normalized=True)
                points.append((float(point.x), float(point.y)))
        return self._dedupe_coords(points)

    def _internal_voronoi_lines(self, diagram: Any, polygon: Any) -> list[LineString]:
        raw_lines = self._flatten_lines(diagram)
        lines: list[LineString] = []
        min_lng, min_lat, max_lng, max_lat = polygon.bounds
        min_span = max(min(max_lng - min_lng, max_lat - min_lat), 0.00001)
        boundary_distance_floor = min_span * 0.002
        for line in raw_lines:
            clipped = line.intersection(polygon)
            for candidate in self._flatten_lines(clipped):
                if len(candidate.coords) < 2:
                    continue
                midpoint = candidate.interpolate(0.5, normalized=True)
                if not polygon.contains(midpoint):
                    continue
                if midpoint.distance(polygon.boundary) < boundary_distance_floor:
                    continue
                cleaned_coords = self._clean_coords([(float(lng), float(lat)) for lng, lat, *_rest in candidate.coords])
                if len(cleaned_coords) < 2:
                    continue
                cleaned = LineString(cleaned_coords)
                if self._length_m(cleaned) >= 10.0:
                    lines.append(cleaned)
        return lines

    def _flatten_lines(self, geometry: Any) -> list[LineString]:
        if geometry is None or geometry.is_empty:
            return []
        if isinstance(geometry, LineString):
            return [geometry] if len(geometry.coords) >= 2 else []
        if isinstance(geometry, MultiLineString):
            return [line for line in geometry.geoms if len(line.coords) >= 2]
        if isinstance(geometry, GeometryCollection):
            lines: list[LineString] = []
            for part in geometry.geoms:
                lines.extend(self._flatten_lines(part))
            return lines
        return []

    def _longest_graph_path(self, lines: list[LineString]) -> LineString | None:
        graph: dict[tuple[float, float], list[tuple[tuple[float, float], float]]] = defaultdict(list)
        for line in lines:
            coords = self._dedupe_coords([(float(lng), float(lat)) for lng, lat, *_rest in line.coords])
            for start, end in zip(coords, coords[1:]):
                if start == end:
                    continue
                weight = self._distance_m(start, end)
                graph[start].append((end, weight))
                graph[end].append((start, weight))
        if not graph:
            return None
        best_path: list[tuple[float, float]] = []
        best_distance = 0.0
        visited: set[tuple[float, float]] = set()
        for node in list(graph):
            if node in visited:
                continue
            component = self._component_nodes(graph, node)
            visited.update(component)
            farthest, _distance, _parents = self._dijkstra_farthest(graph, node, component)
            other, distance, parents = self._dijkstra_farthest(graph, farthest, component)
            path = self._restore_path(parents, farthest, other)
            if distance > best_distance and len(path) >= 2:
                best_distance = distance
                best_path = path
        if len(best_path) < 2:
            return None
        return LineString(self._clean_coords(best_path))

    def _component_nodes(
        self,
        graph: dict[tuple[float, float], list[tuple[tuple[float, float], float]]],
        start: tuple[float, float],
    ) -> set[tuple[float, float]]:
        stack = [start]
        seen = {start}
        while stack:
            node = stack.pop()
            for neighbor, _weight in graph[node]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        return seen

    def _dijkstra_farthest(
        self,
        graph: dict[tuple[float, float], list[tuple[tuple[float, float], float]]],
        start: tuple[float, float],
        allowed: set[tuple[float, float]],
    ) -> tuple[tuple[float, float], float, dict[tuple[float, float], tuple[float, float] | None]]:
        distances = {start: 0.0}
        parents: dict[tuple[float, float], tuple[float, float] | None] = {start: None}
        heap = [(0.0, start)]
        while heap:
            distance, node = heappop(heap)
            if distance > distances.get(node, math.inf):
                continue
            for neighbor, weight in graph[node]:
                if neighbor not in allowed:
                    continue
                next_distance = distance + weight
                if next_distance < distances.get(neighbor, math.inf):
                    distances[neighbor] = next_distance
                    parents[neighbor] = node
                    heappush(heap, (next_distance, neighbor))
        farthest = max(distances, key=lambda item: distances[item])
        return farthest, distances[farthest], parents

    def _restore_path(
        self,
        parents: dict[tuple[float, float], tuple[float, float] | None],
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> list[tuple[float, float]]:
        path = [end]
        current = end
        while current != start:
            parent = parents.get(current)
            if parent is None:
                return []
            path.append(parent)
            current = parent
        path.reverse()
        return path

    def _dedupe_coords(self, coords: list[tuple[float, float]]) -> list[tuple[float, float]]:
        output: list[tuple[float, float]] = []
        seen: set[tuple[float, float]] = set()
        for lng, lat in coords:
            coord = (round(float(lng), 8), round(float(lat), 8))
            if coord in seen:
                continue
            seen.add(coord)
            output.append(coord)
        return output

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
