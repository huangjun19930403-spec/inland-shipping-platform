from __future__ import annotations

from typing import Any

from shapely.geometry import LineString, shape
from shapely.validation import make_valid

from app.models import NavigationCenterlineSegment
from app.modules.navigation.schemas import (
    NavigationGeometryDraftValidationIssueResponse,
    NavigationGeometryDraftValidationResponse,
)
from app.modules.navigation.services.centerline_segments.types import (
    BOUNDARY_TOLERANCE_DEGREE,
    ENDPOINT_AUTO_SNAP_M,
    ENDPOINT_WARN_M,
    MIN_SEGMENT_LENGTH_M,
    SHARP_TURN_DEGREE,
)


class NavigationCenterlineSegmentValidatorMixin:
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
        elif row.source_type_code == "CHANNEL_GUIDE_WITH_BOUNDARY_CLIP":
            trace = row.source_trace_json if isinstance(row.source_trace_json, dict) else {}
            coverage_ratio = trace.get("coverage_ratio")
            if isinstance(coverage_ratio, (int, float)) and float(coverage_ratio) < 0.98:
                issues.append(
                    self._issue(
                        "SEGMENT_BOUNDARY_CLIP_REVIEW",
                        "WARNING",
                        "区段来自导向线与边界裁剪，覆盖率未达到 98%，请人工复核局部缺口。",
                    )
                )
        else:
            boundary_geometry = self._cached_boundary_geometry(boundary)
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
        await self._append_endpoint_issues(row, line, issues)
        return self._validation_response(
            issues=issues,
            bbox=self._public_bbox(self._bbox(row.geometry_json)),
            length_m=length_m,
            point_count=len(coords),
        )

    def _cached_boundary_geometry(self, boundary: Any):
        cache = getattr(self, "_boundary_geometry_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            setattr(self, "_boundary_geometry_cache", cache)
        key = int(boundary.id)
        geometry = cache.get(key)
        if geometry is None:
            geometry = make_valid(shape(self._geojson_geometry(boundary.geometry_json)))
            cache[key] = geometry
        return geometry

    async def _append_endpoint_issues(
        self,
        row: NavigationCenterlineSegment,
        line: LineString,
        issues: list[NavigationGeometryDraftValidationIssueResponse],
    ) -> None:
        coords = list(line.coords)
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

    def _apply_validation(
        self,
        row: NavigationCenterlineSegment,
        validation: NavigationGeometryDraftValidationResponse,
        *,
        generated_from_boundary: bool,
    ) -> None:
        row.validation_summary_json = self._validation_summary(validation)
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
