from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from shapely.geometry import GeometryCollection, LineString, MultiLineString, mapping, shape

from app.core.exceptions import ValidationError
from app.models import NavigationCenterlineSegment
from app.modules.navigation.schemas import (
    NavigationCenterlineSegmentResponse,
    NavigationGeometryDraftValidationResponse,
)
from app.modules.navigation.services.centerline_segments.types import GEOD


class NavigationCenterlineSegmentGeometryMixin:
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
            source_boundary_id=self._trace_int(row.source_trace_json, "source_boundary_id", "based_on_boundary_id"),
            based_on_boundary_id=self._trace_int(row.source_trace_json, "source_boundary_id", "based_on_boundary_id"),
            source_mode=self._trace_str(row.source_trace_json, "source_mode"),
            source_algorithm=self._trace_str(row.source_trace_json, "algorithm", "source_algorithm"),
            created_at=self._iso_datetime(row.created_at),
            updated_at=self._iso_datetime(row.updated_at),
        )

    def _iso_datetime(self, value: Any) -> str | None:
        return value.isoformat() if value else None

    def _trace_int(self, source_trace_json: dict[str, Any] | None, *keys: str) -> int | None:
        trace = source_trace_json if isinstance(source_trace_json, dict) else {}
        for key in keys:
            value = trace.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
        return None

    def _trace_str(self, source_trace_json: dict[str, Any] | None, *keys: str) -> str | None:
        trace = source_trace_json if isinstance(source_trace_json, dict) else {}
        for key in keys:
            value = trace.get(key)
            if isinstance(value, str) and value:
                return value
        return None

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

    def _line_from_json(self, geometry_json: dict[str, Any], *, code: str) -> LineString:
        try:
            geometry = shape(self._geojson_geometry(geometry_json))
        except Exception:
            self._fail(code, "中心线区段几何解析失败")
        if not isinstance(geometry, LineString) or len(geometry.coords) < 2:
            self._fail(code, "中心线区段只支持 LineString")
        return self._clean_line(geometry)

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

    def _point_geometry(self, coord: Any) -> dict[str, Any]:
        return {"type": "Point", "coordinates": [float(coord[0]), float(coord[1])]}

    def _turn_angle_degree(self, a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
        ab = (a[0] - b[0], a[1] - b[1])
        cb = (c[0] - b[0], c[1] - b[1])
        ab_len = math.hypot(*ab)
        cb_len = math.hypot(*cb)
        if ab_len == 0 or cb_len == 0:
            return 180.0
        cos_value = max(-1.0, min(1.0, (ab[0] * cb[0] + ab[1] * cb[1]) / (ab_len * cb_len)))
        return math.degrees(math.acos(cos_value))

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

    def _operator_confirmed_count(self, rows: list[NavigationCenterlineSegment]) -> int:
        return sum(1 for item in rows if item.segment_status_code in {"CONFIRMED", "PUBLISHED"})

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
