from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from pyproj import Geod
from shapely.geometry import LineString, mapping, shape
from shapely.validation import make_valid

from app.core.exceptions import NotFoundError, ValidationError
from app.models import NavigationCenterlineControlPoint, NavigationCenterlinePointSet, NavigationChannelSegment
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.modules.navigation.schemas import (
    NavigationCenterlineControlPointInput,
    NavigationCenterlineControlPointResponse,
    NavigationCenterlinePointSetCreateRequest,
    NavigationCenterlinePointSetListResponse,
    NavigationCenterlinePointSetPreviewResponse,
    NavigationCenterlinePointSetResponse,
    NavigationCenterlinePointSetUpdatePointsRequest,
    NavigationGeometryDraftValidationIssueResponse,
    NavigationGeometryDraftValidationResponse,
)


GEOD = Geod(ellps="WGS84")
BOUNDARY_TOLERANCE_DEGREE = 0.0002


class NavigationCenterlinePointSetService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_sets(self, channel_id: int, *, include_archived: bool = False) -> NavigationCenterlinePointSetListResponse:
        await self._ensure_channel(channel_id)
        stmt = select(NavigationCenterlinePointSet).where(NavigationCenterlinePointSet.channel_id == channel_id)
        if not include_archived:
            stmt = stmt.where(NavigationCenterlinePointSet.status_code != "ARCHIVED")
        rows = list(
            (
                await self.session.execute(
                    stmt.order_by(
                        NavigationCenterlinePointSet.version_no.desc(),
                        NavigationCenterlinePointSet.id.desc(),
                    )
                )
            ).scalars()
        )
        rows.sort(key=lambda row: (0 if row.status_code == "CURRENT" else 1 if row.status_code == "DRAFT" else 2, -int(row.version_no or 0), -int(row.id or 0)))
        points_by_set = await self._points_by_set([int(row.id) for row in rows])
        return NavigationCenterlinePointSetListResponse(
            channel_id=channel_id,
            total_count=len(rows),
            items=[self._response(row, points_by_set.get(int(row.id), [])) for row in rows],
        )

    async def create_set(
        self,
        channel_id: int,
        body: NavigationCenterlinePointSetCreateRequest,
    ) -> NavigationCenterlinePointSetResponse:
        channel = await self._ensure_channel(channel_id)
        boundary = await self._current_boundary(channel_id)
        if boundary is None:
            self._fail("NO_PUBLISHED_BOUNDARY", "当前航道还没有已发布边界，不能创建中心线点位草稿。")
        version_no = int(
            (
                await self.session.execute(
                    select(func.coalesce(func.max(NavigationCenterlinePointSet.version_no), 0)).where(
                        NavigationCenterlinePointSet.channel_id == channel_id
                    )
                )
            ).scalar_one()
            or 0
        ) + 1
        source_type = (body.source_type_code or "EMPTY").upper()
        row = NavigationCenterlinePointSet(
            channel_id=channel_id,
            based_on_boundary_id=int(boundary.id),
            point_set_name=body.point_set_name or f"{channel.channel_name}中心线控制点 V{version_no}",
            version_no=version_no,
            status_code="DRAFT",
            point_count=0,
            source_trace_json={
                "source": source_type,
                "created_at": self._now().isoformat(),
                "based_on_boundary_id": int(boundary.id),
            },
        )
        self.session.add(row)
        await self.session.flush()
        imported_points: list[NavigationCenterlineControlPointInput] = []
        if source_type == "IMPORT_GUIDE":
            imported_points = await self._points_from_guide(channel_id, max_points=body.max_import_points)
            if not imported_points:
                await self.session.rollback()
                self._fail("CENTERLINE_GUIDE_MISSING", "当前航道没有可导入的生产导向线。")
        if imported_points:
            await self._replace_points(row, imported_points)
        await self._recalculate(row)
        await self.session.commit()
        await self.session.refresh(row)
        return self._response(row, await self._points(int(row.id)))

    async def update_points(
        self,
        point_set_id: int,
        body: NavigationCenterlinePointSetUpdatePointsRequest,
    ) -> NavigationCenterlinePointSetResponse:
        row = await self._point_set(point_set_id)
        if row.status_code == "ARCHIVED":
            self._fail("CENTERLINE_POINT_SET_ARCHIVED", "已归档的中心线点位版本不能修改。")
        await self._replace_points(row, body.points)
        trace = dict(row.source_trace_json or {})
        trace["last_points_saved_at"] = self._now().isoformat()
        row.source_trace_json = trace
        await self._recalculate(row)
        await self.session.commit()
        await self.session.refresh(row)
        return self._response(row, await self._points(int(row.id)))

    async def preview(self, point_set_id: int) -> NavigationCenterlinePointSetPreviewResponse:
        row = await self._point_set(point_set_id)
        await self._recalculate(row)
        await self.session.commit()
        validation = row.validation_summary_json if isinstance(row.validation_summary_json, dict) else {}
        error_count = int(validation.get("error_count") or 0)
        blockers = [
            str(item.get("issue_code"))
            for item in validation.get("issues", [])
            if isinstance(item, dict) and item.get("severity_code") == "ERROR"
        ]
        return NavigationCenterlinePointSetPreviewResponse(
            point_set_id=int(row.id),
            status_code="BLOCKED" if error_count else "READY",
            message="点位连线校验通过，可以生成中心线区段。" if not error_count else "点位连线存在阻断问题，不能生成中心线区段。",
            point_count=int(row.point_count or 0),
            length_m=self._float(row.length_m),
            bbox=self._public_bbox(row),
            geometry_json=row.generated_geometry_json,
            validation_summary_json=row.validation_summary_json,
            blocker_codes=blockers,
        )

    async def archive(self, point_set_id: int) -> NavigationCenterlinePointSetResponse:
        row = await self._point_set(point_set_id)
        if row.status_code == "CURRENT":
            self._fail("CENTERLINE_POINT_SET_CURRENT_ARCHIVE_BLOCKED", "当前点位版本不能归档，请先生成并切换到新的点位版本。")
        row.status_code = "ARCHIVED"
        trace = dict(row.source_trace_json or {})
        trace["archived_at"] = self._now().isoformat()
        trace["archive_reason"] = "operator_hidden_point_set"
        row.source_trace_json = trace
        await self.session.commit()
        await self.session.refresh(row)
        return self._response(row, await self._points(int(row.id)))

    async def line_for_generation(
        self,
        *,
        channel_id: int,
        point_set_id: int,
        boundary: NavigationChannelBoundary,
    ) -> tuple[LineString | None, NavigationCenterlinePointSet | None, list[NavigationCenterlineControlPoint], dict[str, Any], str, list[str]]:
        row = await self._point_set(point_set_id, allow_archived=False)
        if int(row.channel_id) != int(channel_id):
            return None, None, [], {}, "中心线点位版本不属于当前航道。", ["CENTERLINE_POINT_SET_CHANNEL_MISMATCH"]
        if int(row.based_on_boundary_id) != int(boundary.id):
            return None, row, [], {}, "中心线点位版本不是基于当前发布边界，请重新创建点位草稿。", ["CENTERLINE_POINT_SET_BOUNDARY_STALE"]
        await self._recalculate(row, boundary=boundary)
        validation = row.validation_summary_json if isinstance(row.validation_summary_json, dict) else {}
        blockers = [
            str(item.get("issue_code"))
            for item in validation.get("issues", [])
            if isinstance(item, dict) and item.get("severity_code") == "ERROR"
        ]
        if blockers:
            return None, row, [], {}, "中心线点位连线校验未通过，不能生成区段。", blockers
        points = await self._points(int(row.id))
        line = self._line_from_points(points)
        if line is None:
            return None, row, points, {}, "中心线点位少于 2 个，不能生成区段。", ["CENTERLINE_CONTROL_POINT_TOO_FEW"]
        point_ids = [int(point.id) for point in points if point.id is not None]
        source_meta = {
            "source_point_set_id": int(row.id),
            "source_point_set_version_no": int(row.version_no),
            "source_control_point_ids": point_ids,
            "source_control_point_count": len(points),
            "source_control_point_hash": self._point_hash(points),
            "point_set_validation_summary": row.validation_summary_json,
        }
        return line, row, points, source_meta, "", []

    async def mark_current(self, point_set_id: int) -> None:
        row = await self._point_set(point_set_id, allow_archived=False)
        current_rows = list(
            (
                await self.session.execute(
                    select(NavigationCenterlinePointSet).where(
                        NavigationCenterlinePointSet.channel_id == row.channel_id,
                        NavigationCenterlinePointSet.status_code == "CURRENT",
                    )
                )
            ).scalars()
        )
        for item in current_rows:
            if int(item.id) != int(row.id):
                item.status_code = "DRAFT"
        row.status_code = "CURRENT"
        trace = dict(row.source_trace_json or {})
        trace["last_used_for_segment_generation_at"] = self._now().isoformat()
        row.source_trace_json = trace

    async def _replace_points(
        self,
        row: NavigationCenterlinePointSet,
        points: list[NavigationCenterlineControlPointInput],
    ) -> None:
        await self.session.execute(
            delete(NavigationCenterlineControlPoint).where(NavigationCenterlineControlPoint.point_set_id == row.id)
        )
        for index, point in enumerate(points, start=1):
            self._validate_lnglat(point.longitude, point.latitude)
            self.session.add(
                NavigationCenterlineControlPoint(
                    point_set_id=int(row.id),
                    sequence_no=int(point.sequence_no or index),
                    longitude=float(point.longitude),
                    latitude=float(point.latitude),
                    point_type_code=(point.point_type_code or "MANUAL").upper(),
                    point_name=point.point_name,
                    source_trace_json=point.source_trace_json,
                )
            )
        await self.session.flush()

    async def _recalculate(
        self,
        row: NavigationCenterlinePointSet,
        *,
        boundary: NavigationChannelBoundary | None = None,
    ) -> None:
        boundary = boundary or await self._current_boundary(int(row.channel_id))
        points = await self._points(int(row.id))
        line = self._line_from_points(points)
        row.point_count = len(points)
        if line is None:
            row.generated_geometry_json = None
            row.length_m = None
            row.bbox_min_lng = row.bbox_min_lat = row.bbox_max_lng = row.bbox_max_lat = None
            validation = self._validate_line(row, None, points, boundary)
            row.validation_summary_json = self._validation_summary(validation)
            return
        geometry_json = self._geometry_json(line)
        min_lng, min_lat, max_lng, max_lat = line.bounds
        row.generated_geometry_json = geometry_json
        row.length_m = round(self._length_m(line), 2)
        row.bbox_min_lng = min_lng
        row.bbox_min_lat = min_lat
        row.bbox_max_lng = max_lng
        row.bbox_max_lat = max_lat
        validation = self._validate_line(row, line, points, boundary)
        row.validation_summary_json = self._validation_summary(validation)

    def _validate_line(
        self,
        row: NavigationCenterlinePointSet,
        line: LineString | None,
        points: list[NavigationCenterlineControlPoint],
        boundary: NavigationChannelBoundary | None,
    ) -> NavigationGeometryDraftValidationResponse:
        issues: list[NavigationGeometryDraftValidationIssueResponse] = []
        if len(points) < 2 or line is None:
            issues.append(self._issue("CENTERLINE_CONTROL_POINT_TOO_FEW", "ERROR", "中心线控制点至少需要 2 个。"))
        if any(not self._coord_legal((point.longitude, point.latitude)) for point in points):
            issues.append(self._issue("CENTERLINE_CONTROL_POINT_INVALID", "ERROR", "中心线控制点坐标超出合法经纬度范围。"))
        if boundary is None:
            issues.append(self._issue("NO_PUBLISHED_BOUNDARY", "ERROR", "当前航道缺少已发布边界。"))
        elif int(row.based_on_boundary_id) != int(boundary.id):
            issues.append(self._issue("CENTERLINE_POINT_SET_BOUNDARY_STALE", "ERROR", "点位版本不是基于当前发布边界。"))
        elif line is not None:
            boundary_geometry = make_valid(shape(boundary.geometry_json))
            coverage_ratio = self._line_boundary_bbox_coverage_ratio(line, boundary_geometry.bounds)
            if not boundary_geometry.buffer(BOUNDARY_TOLERANCE_DEGREE).covers(line):
                if coverage_ratio >= 0.9:
                    issues.append(
                        self._issue(
                            "CENTERLINE_CONTROL_LINE_BOUNDARY_REVIEW",
                            "WARNING",
                            "控制点连线主轴覆盖当前边界，但局部与边界 polygon 存在偏差，请人工复核。",
                            "长干线边界 polygon 可能存在局部碎裂，允许先生成区段后逐段复核。",
                            self._geometry_json(line),
                        )
                    )
                else:
                    issues.append(
                        self._issue(
                            "CENTERLINE_CONTROL_LINE_OUT_OF_BOUNDARY",
                            "ERROR",
                            "控制点自动连线明显超出当前发布边界。",
                            "请移动或删除越界点位。",
                            self._geometry_json(line),
                        )
                    )
            elif not boundary_geometry.covers(line):
                issues.append(self._issue("CENTERLINE_CONTROL_LINE_NEAR_BOUNDARY", "WARNING", "控制点自动连线贴近边界，请人工复核。"))
            if coverage_ratio < 0.25:
                issues.append(
                    self._issue(
                        "CENTERLINE_CONTROL_LINE_COVERAGE_INCOMPLETE",
                        "ERROR",
                        f"控制点连线覆盖当前边界主轴比例过低，约 {coverage_ratio:.0%}。",
                        "请补齐全航道控制点后再生成区段。",
                    )
                )
        bbox = self._public_bbox(row)
        return NavigationGeometryDraftValidationResponse(
            valid=not any(item.severity_code == "ERROR" for item in issues),
            publishable=not any(item.severity_code == "ERROR" for item in issues),
            quality_code="PUBLISH_BLOCKED" if any(item.severity_code == "ERROR" for item in issues) else "READY_WITH_WARNING" if issues else "READY",
            issue_count=len(issues),
            error_count=sum(1 for item in issues if item.severity_code == "ERROR"),
            warning_count=sum(1 for item in issues if item.severity_code == "WARNING"),
            length_m=round(self._length_m(line), 2) if line is not None else None,
            area_m2=None,
            point_count=len(points),
            ring_count=0,
            bbox=bbox,
            issues=issues,
        )

    async def _points_from_guide(self, channel_id: int, *, max_points: int) -> list[NavigationCenterlineControlPointInput]:
        rows = list(
            (
                await self.session.execute(
                    select(NavigationChannelSegment)
                    .where(
                        NavigationChannelSegment.channel_id == channel_id,
                        NavigationChannelSegment.guide_geometry_json.is_not(None),
                        NavigationChannelSegment.geometry_status_code != "ARCHIVED",
                    )
                    .order_by(NavigationChannelSegment.sequence_no, NavigationChannelSegment.sort_order, NavigationChannelSegment.id)
                )
            ).scalars()
        )
        coords: list[tuple[float, float]] = []
        source_ids: list[int] = []
        for row in rows:
            for line in self._lines_from_json(row.guide_geometry_json or {}):
                source_ids.append(int(row.id))
                line_coords = [(float(lng), float(lat)) for lng, lat, *_rest in line.coords]
                if coords and line_coords and self._distance_m(coords[-1], line_coords[0]) < 1.0:
                    coords.extend(line_coords[1:])
                else:
                    coords.extend(line_coords)
        clean_coords = self._clean_coords(coords)
        sampled = self._sample_coords(clean_coords, max_points=max_points)
        return [
            NavigationCenterlineControlPointInput(
                sequence_no=index,
                longitude=lng,
                latitude=lat,
                point_type_code="IMPORTED_GUIDE",
                point_name=f"导入点 {index:03d}",
                source_trace_json={"source": "navigation_channel_segment.guide_geometry_json", "source_segment_ids": source_ids},
            )
            for index, (lng, lat) in enumerate(sampled, start=1)
        ]

    def _sample_coords(self, coords: list[tuple[float, float]], *, max_points: int) -> list[tuple[float, float]]:
        if len(coords) <= max_points:
            return coords
        line = LineString(coords)
        return [
            (float(line.interpolate(index / max(max_points - 1, 1), normalized=True).x), float(line.interpolate(index / max(max_points - 1, 1), normalized=True).y))
            for index in range(max_points)
        ]

    async def _ensure_channel(self, channel_id: int) -> NavigationChannel:
        channel = await self.session.get(NavigationChannel, channel_id)
        if channel is None:
            raise NotFoundError("NavigationChannel", channel_id)
        return channel

    async def _point_set(self, point_set_id: int, *, allow_archived: bool = True) -> NavigationCenterlinePointSet:
        row = await self.session.get(NavigationCenterlinePointSet, point_set_id)
        if row is None or (not allow_archived and row.status_code == "ARCHIVED"):
            raise NotFoundError("NavigationCenterlinePointSet", point_set_id)
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

    async def _points(self, point_set_id: int) -> list[NavigationCenterlineControlPoint]:
        return list(
            (
                await self.session.execute(
                    select(NavigationCenterlineControlPoint)
                    .where(NavigationCenterlineControlPoint.point_set_id == point_set_id)
                    .order_by(NavigationCenterlineControlPoint.sequence_no, NavigationCenterlineControlPoint.id)
                )
            ).scalars()
        )

    async def _points_by_set(self, point_set_ids: list[int]) -> dict[int, list[NavigationCenterlineControlPoint]]:
        if not point_set_ids:
            return {}
        rows = list(
            (
                await self.session.execute(
                    select(NavigationCenterlineControlPoint)
                    .where(NavigationCenterlineControlPoint.point_set_id.in_(point_set_ids))
                    .order_by(NavigationCenterlineControlPoint.point_set_id, NavigationCenterlineControlPoint.sequence_no)
                )
            ).scalars()
        )
        result: dict[int, list[NavigationCenterlineControlPoint]] = {}
        for row in rows:
            result.setdefault(int(row.point_set_id), []).append(row)
        return result

    def _response(
        self,
        row: NavigationCenterlinePointSet,
        points: list[NavigationCenterlineControlPoint],
    ) -> NavigationCenterlinePointSetResponse:
        return NavigationCenterlinePointSetResponse(
            id=int(row.id),
            channel_id=int(row.channel_id),
            based_on_boundary_id=int(row.based_on_boundary_id),
            point_set_name=row.point_set_name,
            version_no=int(row.version_no or 1),
            status_code=row.status_code,
            point_count=int(row.point_count or 0),
            length_m=self._float(row.length_m),
            bbox_min_lng=self._float(row.bbox_min_lng),
            bbox_min_lat=self._float(row.bbox_min_lat),
            bbox_max_lng=self._float(row.bbox_max_lng),
            bbox_max_lat=self._float(row.bbox_max_lat),
            generated_geometry_json=row.generated_geometry_json,
            validation_summary_json=row.validation_summary_json,
            source_trace_json=row.source_trace_json,
            points=[self._point_response(point) for point in points],
            created_at=self._iso_datetime(row.created_at),
            updated_at=self._iso_datetime(row.updated_at),
        )

    def _point_response(self, row: NavigationCenterlineControlPoint) -> NavigationCenterlineControlPointResponse:
        return NavigationCenterlineControlPointResponse(
            id=int(row.id),
            point_set_id=int(row.point_set_id),
            sequence_no=int(row.sequence_no),
            longitude=float(row.longitude),
            latitude=float(row.latitude),
            point_type_code=row.point_type_code,
            point_name=row.point_name,
            source_trace_json=row.source_trace_json,
            created_at=self._iso_datetime(row.created_at),
            updated_at=self._iso_datetime(row.updated_at),
        )

    def _line_from_points(self, points: list[NavigationCenterlineControlPoint]) -> LineString | None:
        coords = self._clean_coords([(float(point.longitude), float(point.latitude)) for point in points])
        return LineString(coords) if len(coords) >= 2 else None

    def _lines_from_json(self, geometry_json: dict[str, Any]) -> list[LineString]:
        try:
            geometry = shape(geometry_json.get("geometry") if geometry_json.get("type") == "Feature" else geometry_json)
        except Exception:
            return []
        if isinstance(geometry, LineString) and len(geometry.coords) >= 2:
            return [LineString(self._clean_coords([(float(lng), float(lat)) for lng, lat, *_ in geometry.coords]))]
        if hasattr(geometry, "geoms"):
            lines: list[LineString] = []
            for item in geometry.geoms:
                if isinstance(item, LineString) and len(item.coords) >= 2:
                    lines.append(LineString(self._clean_coords([(float(lng), float(lat)) for lng, lat, *_ in item.coords])))
            return lines
        return []

    def _geometry_json(self, line: LineString) -> dict[str, Any]:
        return json.loads(json.dumps(mapping(line)))

    def _validation_summary(self, validation: NavigationGeometryDraftValidationResponse) -> dict[str, Any]:
        return validation.model_dump() if hasattr(validation, "model_dump") else validation.dict()

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

    def _line_boundary_bbox_coverage_ratio(self, line: LineString, boundary_bounds: tuple[float, float, float, float]) -> float:
        min_lng, min_lat, max_lng, max_lat = boundary_bounds
        line_min_lng, line_min_lat, line_max_lng, line_max_lat = line.bounds
        boundary_span = max(float(max_lng - min_lng), float(max_lat - min_lat))
        if boundary_span <= 0:
            return 1.0
        line_span = max(float(line_max_lng - line_min_lng), float(line_max_lat - line_min_lat))
        return max(0.0, min(1.0, line_span / boundary_span))

    def _public_bbox(self, row: NavigationCenterlinePointSet) -> dict[str, float | None]:
        return {
            "min_lng": self._float(row.bbox_min_lng),
            "min_lat": self._float(row.bbox_min_lat),
            "max_lng": self._float(row.bbox_max_lng),
            "max_lat": self._float(row.bbox_max_lat),
        }

    def _point_hash(self, points: list[NavigationCenterlineControlPoint]) -> str:
        payload = "|".join(f"{point.sequence_no}:{float(point.longitude):.8f},{float(point.latitude):.8f}" for point in points)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _clean_coords(self, coords: list[tuple[float, float]]) -> list[tuple[float, float]]:
        output: list[tuple[float, float]] = []
        for lng, lat in coords:
            point = (float(lng), float(lat))
            if not output or self._distance_m(output[-1], point) > 0.01:
                output.append(point)
        return output

    def _length_m(self, line: LineString) -> float:
        coords = list(line.coords)
        if len(coords) < 2:
            return 0.0
        return abs(float(GEOD.line_length([float(coord[0]) for coord in coords], [float(coord[1]) for coord in coords])))

    def _distance_m(self, start: Any, end: Any) -> float:
        _, _, distance = GEOD.inv(float(start[0]), float(start[1]), float(end[0]), float(end[1]))
        return abs(float(distance))

    def _coord_legal(self, coord: Any) -> bool:
        try:
            lng = float(coord[0])
            lat = float(coord[1])
        except Exception:
            return False
        return -180 <= lng <= 180 and -90 <= lat <= 90

    def _validate_lnglat(self, longitude: float, latitude: float) -> None:
        if not self._coord_legal((longitude, latitude)):
            self._fail("CENTERLINE_CONTROL_POINT_INVALID", "中心线控制点坐标超出合法经纬度范围。")

    def _float(self, value: Any) -> float | None:
        return float(value) if value is not None else None

    def _iso_datetime(self, value: Any) -> str | None:
        return value.isoformat() if value else None

    def _now(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    def _fail(self, code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        raise ValidationError(
            message,
            code=code,
            detail={"error_code": code, "message": message, **(detail or {})},
        )
