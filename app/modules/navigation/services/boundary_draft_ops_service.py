from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from pyproj import Geod
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping, shape
from shapely.ops import unary_union
from shapely.validation import make_valid
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.models import NavigationGeometryDraft
from app.modules.navigation.schemas import (
    NavigationBoundaryDraftOperationRequest,
    NavigationBoundaryDraftOperationResponse,
)
from app.modules.navigation.services.geometry_validation_service import NavigationGeometryValidationService


GEOD = Geod(ellps="WGS84")
DEFAULT_SMALL_PART_AREA_M2 = 1000.0


class NavigationBoundaryDraftOpsService:
    def __init__(self, session: AsyncSession, helpers: Any) -> None:
        self.session = session
        self.helpers = helpers
        self.validation_service = NavigationGeometryValidationService(session, helpers)

    async def apply_operation(
        self,
        draft_id: int,
        body: NavigationBoundaryDraftOperationRequest,
    ) -> NavigationBoundaryDraftOperationResponse:
        draft = await self.session.get(NavigationGeometryDraft, draft_id)
        if draft is None:
            self._fail("BOUNDARY_OP_DRAFT_NOT_FOUND", "边界草稿不存在")
        if draft.draft_type_code != "BOUNDARY":
            self._fail("BOUNDARY_OP_NOT_BOUNDARY_DRAFT", "该操作只适用于边界草稿")

        operation = body.operation_code.upper()
        before_geometry = self._polygonal_from_json(draft.geometry_json, "BOUNDARY_OP_GEOMETRY_INVALID_AFTER_OPERATION")
        before_points = self.helpers._point_count(draft.geometry_json)
        next_geometry: Polygon | MultiPolygon | None
        message: str
        detail: dict[str, Any] = {}

        if operation == "DELETE_PART":
            next_geometry, detail = self._delete_part(before_geometry, body.part_index)
            message = f"已删除第 {body.part_index} 个分面。"
        elif operation == "KEEP_ONLY_PART":
            next_geometry, detail = self._keep_only_part(before_geometry, body.part_index)
            message = f"已只保留第 {body.part_index} 个分面。"
        elif operation == "UNION_PATCH":
            patch = self._patch_geometry(body.operation_geometry_json)
            next_geometry = self._polygonal(unary_union([before_geometry, patch]))
            detail = {"patch_area_m2": self._area_m2(patch)}
            message = "已补画缺口并合并到边界草稿。"
        elif operation == "SUBTRACT_PATCH":
            patch = self._patch_geometry(body.operation_geometry_json)
            next_geometry = self._polygonal(before_geometry.difference(patch))
            detail = {"patch_area_m2": self._area_m2(patch)}
            message = "已裁剪多余区域。"
        elif operation == "CLEAN_SMALL_PARTS":
            min_area_m2 = float(body.options.get("min_area_m2") or DEFAULT_SMALL_PART_AREA_M2)
            next_geometry, detail = self._clean_small_parts(before_geometry, min_area_m2)
            message = f"已清理 {detail['removed_count']} 个小碎面。"
        elif operation == "SIMPLIFY":
            tolerance = float(body.options.get("tolerance_degree") or 0.00005)
            preserve_topology = bool(body.options.get("preserve_topology", True))
            next_geometry = self._polygonal(before_geometry.simplify(tolerance, preserve_topology=preserve_topology))
            detail = {"tolerance_degree": tolerance, "preserve_topology": preserve_topology}
            message = "已简化边界。"
        else:
            self._fail("BOUNDARY_OP_INVALID_OPERATION", f"不支持的边界操作：{operation}")

        if next_geometry is None or next_geometry.is_empty:
            self._fail("BOUNDARY_OP_EMPTY_RESULT", "操作结果为空，已取消保存")
        next_geometry = self._polygonal(make_valid(next_geometry))
        if next_geometry is None or next_geometry.is_empty:
            self._fail("BOUNDARY_OP_EMPTY_RESULT", "操作结果为空，已取消保存")
        if not next_geometry.is_valid:
            self._fail("BOUNDARY_OP_GEOMETRY_INVALID_AFTER_OPERATION", "操作后边界几何不合法，已取消保存")

        geometry_json = self._geometry_json(next_geometry)
        after_points = self.helpers._point_count(geometry_json)
        for key, value in self.helpers._geometry_bbox(geometry_json).items():
            setattr(draft, key, value)
        draft.geometry_json = geometry_json
        draft.geometry_type_code = str(geometry_json.get("type") or "").upper()
        draft.source_type_code = "MAP_EDIT"
        draft.status_code = "DRAFT" if draft.status_code == "PUBLISH_BLOCKED" else draft.status_code
        validation = await self.validation_service.validate_draft_geometry(
            draft_type="BOUNDARY",
            channel_id=draft.channel_id,
            geometry=geometry_json,
        )
        trace = dict(draft.source_trace_json or {})
        history = list(trace.get("boundary_operation_history") or [])
        history.append(
            {
                "operation_code": operation,
                "part_index": body.part_index,
                "options": body.options,
                "point_count_before": before_points,
                "point_count_after": after_points,
                "area_m2": self._area_m2(next_geometry),
                "detail": detail,
                "operated_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
            }
        )
        trace["boundary_operation_history"] = history[-50:]
        draft.source_trace_json = self.helpers._source_trace_with_validation_summary(trace, validation)
        draft.quality_code = validation.quality_code
        draft.review_comment = self.helpers._validation_review_comment(validation)
        await self.session.commit()
        return NavigationBoundaryDraftOperationResponse(
            draft=await self.helpers._draft_response_by_id(draft.id),
            validation=validation,
            message=f"{message} 点数：{before_points} → {after_points}",
        )

    def _delete_part(
        self,
        geometry: Polygon | MultiPolygon,
        part_index: int | None,
    ) -> tuple[Polygon | MultiPolygon | None, dict[str, Any]]:
        parts = self._parts(geometry)
        index = self._part_index(part_index, parts)
        if len(parts) <= 1:
            self._fail("BOUNDARY_OP_PART_INDEX_INVALID", "至少需要保留一个边界分面")
        kept = [part for idx, part in enumerate(parts) if idx != index]
        return self._polygonal(unary_union(kept)), {"removed_count": 1}

    def _keep_only_part(
        self,
        geometry: Polygon | MultiPolygon,
        part_index: int | None,
    ) -> tuple[Polygon | MultiPolygon | None, dict[str, Any]]:
        parts = self._parts(geometry)
        index = self._part_index(part_index, parts)
        return parts[index], {"removed_count": len(parts) - 1}

    def _clean_small_parts(
        self,
        geometry: Polygon | MultiPolygon,
        min_area_m2: float,
    ) -> tuple[Polygon | MultiPolygon | None, dict[str, Any]]:
        parts = self._parts(geometry)
        kept = [part for part in parts if self._area_m2(part) >= min_area_m2]
        if not kept:
            self._fail("BOUNDARY_OP_EMPTY_RESULT", "清理阈值会删除全部分面，已取消保存")
        removed_count = len(parts) - len(kept)
        return self._polygonal(unary_union(kept)), {"removed_count": removed_count, "min_area_m2": min_area_m2}

    def _patch_geometry(self, geometry_json: dict[str, Any] | None) -> Polygon | MultiPolygon:
        if not isinstance(geometry_json, dict):
            self._fail("BOUNDARY_OP_PATCH_GEOMETRY_INVALID", "补丁几何不能为空")
        return self._polygonal_from_json(geometry_json, "BOUNDARY_OP_PATCH_GEOMETRY_INVALID")

    def _polygonal_from_json(self, geometry_json: dict[str, Any], code: str) -> Polygon | MultiPolygon:
        try:
            source = geometry_json.get("geometry") if geometry_json.get("type") == "Feature" else geometry_json
            geometry = self._polygonal(shape(source))
        except Exception:
            geometry = None
        if geometry is None or geometry.is_empty or not isinstance(geometry, (Polygon, MultiPolygon)):
            self._fail(code, "边界操作只支持 Polygon 或 MultiPolygon")
        return geometry

    def _polygonal(self, geometry: Any) -> Polygon | MultiPolygon | None:
        if geometry is None or geometry.is_empty:
            return None
        if isinstance(geometry, (Polygon, MultiPolygon)):
            return geometry
        if isinstance(geometry, GeometryCollection):
            parts = [part for part in geometry.geoms if isinstance(part, (Polygon, MultiPolygon)) and not part.is_empty]
            if not parts:
                return None
            return self._polygonal(unary_union(parts))
        return None

    def _parts(self, geometry: Polygon | MultiPolygon) -> list[Polygon]:
        return [geometry] if isinstance(geometry, Polygon) else list(geometry.geoms)

    def _part_index(self, part_index: int | None, parts: list[Polygon]) -> int:
        if part_index is None or part_index < 0 or part_index >= len(parts):
            self._fail("BOUNDARY_OP_PART_INDEX_INVALID", "分面索引无效")
        return int(part_index)

    def _geometry_json(self, geometry: Polygon | MultiPolygon) -> dict[str, Any]:
        return json.loads(json.dumps(mapping(geometry)))

    def _area_m2(self, geometry: Polygon | MultiPolygon) -> float:
        return abs(float(GEOD.geometry_area_perimeter(geometry)[0]))

    def _fail(self, code: str, message: str) -> None:
        raise ValidationError(message, code=code, detail={"error_code": code, "message": message})
