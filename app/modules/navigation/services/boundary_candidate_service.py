from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pyproj import Geod
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping, shape
from shapely.ops import unary_union
from shapely.validation import make_valid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models import NavigationChannelWaterBodyMatch, NavigationWaterBody
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.modules.navigation.schemas import (
    NavigationBoundaryListItemResponse,
    NavigationCandidateGenerateRequest,
    NavigationCandidateGenerateResponse,
)


GEOD = Geod(ellps="WGS84")
BOUNDARY_CANDIDATE_TYPES = (
    "WATER_BODY_UNION_RAW",
    "WATER_BODY_UNION_CLEANED",
    "WATER_BODY_UNION_SIMPLIFIED",
)
BOUNDARY_CANDIDATE_POLICIES = {
    "RIVER_MATCH_CANDIDATE",
    "WATER_BODY_UNION_RAW",
    "WATER_BODY_UNION_CLEANED",
    "WATER_BODY_UNION_SIMPLIFIED",
    "CENTERLINE_BUFFER",
    "AIS_INFERRED",
    "MANUAL_DRAW",
}
MIN_CLEAN_PART_AREA_M2 = 1000.0
MIN_CLEAN_HOLE_AREA_M2 = 500.0
SIMPLIFY_TOLERANCE_DEGREE = 0.00005


@dataclass(slots=True)
class BoundaryCandidateGeometry:
    candidate_type: str
    geometry_json: dict[str, Any]
    point_count_before: int
    point_count_after: int
    area_m2: float | None
    simplified: bool = False
    cleaned: bool = False
    warning: str | None = None


class NavigationBoundaryCandidateService:
    def __init__(self, session: AsyncSession, helpers: Any) -> None:
        self.session = session
        self.helpers = helpers

    async def boundary_candidates(self, channel_id: int, limit: int = 120) -> list[NavigationBoundaryListItemResponse]:
        rows = list(
            (
                await self.session.execute(
                    select(NavigationChannelBoundary, NavigationChannel)
                    .join(NavigationChannel, NavigationChannel.id == NavigationChannelBoundary.channel_id)
                    .where(
                        NavigationChannelBoundary.channel_id == channel_id,
                        NavigationChannelBoundary.is_current.is_(False),
                        NavigationChannelBoundary.coverage_policy_code.in_(BOUNDARY_CANDIDATE_POLICIES),
                    )
                    .order_by(NavigationChannelBoundary.id.desc())
                    .limit(max(1, min(limit, 300)))
                )
            ).all()
        )
        return [self._boundary_response(boundary, channel) for boundary, channel in rows]

    async def generate_boundary_candidates(
        self,
        *,
        channel_id: int,
        body: NavigationCandidateGenerateRequest,
    ) -> NavigationCandidateGenerateResponse:
        channel = await self.session.get(NavigationChannel, channel_id)
        if channel is None:
            raise NotFoundError("NavigationChannel", channel_id)

        existing = await self.boundary_candidates(channel_id, limit=300)
        matched_rows = await self._matched_water_bodies(channel_id)
        source_summary = self._source_summary([row for row, _match in matched_rows])
        if existing and not body.force:
            return NavigationCandidateGenerateResponse(
                status_code="EXISTS",
                message=(
                    f"已存在 {len(existing)} 个边界候选，它们来自当前航道已归属水体。"
                    "可以直接载入候选边界修正；如果水体归属发生变化，请点击重新生成。"
                ),
                created_count=0,
                candidate_count=len(existing),
                next_path=f"/navigation/production/boundaries?channel_id={channel_id}",
                boundary_ids=[item.id for item in existing],
                matched_water_body_count=source_summary["matched_water_body_count"],
                candidate_types=sorted({item.coverage_policy_code for item in existing}),
                source_summary=source_summary,
            )

        if not matched_rows:
            return NavigationCandidateGenerateResponse(
                status_code="BLOCKED",
                message="当前航道还没有已归属水体，请先进入“航道水系规划”确认水体。",
                blocker_codes=["NO_WATER_BODY_MATCH"],
                next_path=f"/navigation/production/water-matches?channel_id={channel_id}",
                matched_water_body_count=0,
            )

        candidates = self._candidate_geometries([row for row, _match in matched_rows])
        if not candidates:
            return NavigationCandidateGenerateResponse(
                status_code="BLOCKED",
                message="已归属水体缺少可用 Polygon/MultiPolygon geometry，暂不能生成边界候选。",
                blocker_codes=["NO_WATER_BODY_GEOMETRY"],
                next_path=f"/navigation/production/water-matches?channel_id={channel_id}",
                matched_water_body_count=source_summary["matched_water_body_count"],
                source_summary=source_summary,
            )

        created_ids: list[int] = []
        for candidate in candidates:
            boundary = self._new_boundary(channel_id=channel_id, candidate=candidate, source_summary=source_summary)
            self.session.add(boundary)
            await self.session.flush()
            created_ids.append(int(boundary.id))
        await self.session.commit()
        return NavigationCandidateGenerateResponse(
            status_code="CREATED",
            message=(
                "已根据已归属水体生成原始合并边界、清理后边界和简化预览边界。"
                "请优先载入候选边界修正，不建议从零绘制完整边界。"
            ),
            created_count=len(created_ids),
            candidate_count=len(existing) + len(created_ids),
            boundary_ids=created_ids,
            next_path=f"/navigation/production/boundaries?channel_id={channel_id}",
            matched_water_body_count=source_summary["matched_water_body_count"],
            candidate_types=[candidate.candidate_type for candidate in candidates],
            source_summary=source_summary,
        )

    async def _matched_water_bodies(
        self,
        channel_id: int,
    ) -> list[tuple[NavigationWaterBody, NavigationChannelWaterBodyMatch]]:
        return list(
            (
                await self.session.execute(
                    select(NavigationWaterBody, NavigationChannelWaterBodyMatch)
                    .join(
                        NavigationChannelWaterBodyMatch,
                        NavigationChannelWaterBodyMatch.water_body_id == NavigationWaterBody.id,
                    )
                    .where(
                        NavigationChannelWaterBodyMatch.channel_id == channel_id,
                        NavigationChannelWaterBodyMatch.is_current.is_(True),
                        NavigationWaterBody.is_enabled.is_(True),
                        NavigationWaterBody.body_role_code.in_({"PRIMARY_HIERARCHY", "RX_FILL_GAP", "STANDARD"}),
                    )
                    .order_by(
                        NavigationChannelWaterBodyMatch.score.desc(),
                        NavigationWaterBody.source_layer_order,
                        NavigationWaterBody.id,
                    )
                    .limit(80)
                )
            ).all()
        )

    def _candidate_geometries(self, bodies: list[NavigationWaterBody]) -> list[BoundaryCandidateGeometry]:
        polygons = self._body_polygons(bodies)
        if not polygons:
            return []
        raw_geometry = self._polygonal(unary_union(polygons))
        if raw_geometry is None or raw_geometry.is_empty:
            return []
        raw_json = self._geometry_json(raw_geometry)
        raw_points = self.helpers._point_count(raw_json)
        candidates = [
            BoundaryCandidateGeometry(
                candidate_type="WATER_BODY_UNION_RAW",
                geometry_json=raw_json,
                point_count_before=raw_points,
                point_count_after=raw_points,
                area_m2=self._area_m2(raw_geometry),
                simplified=False,
                cleaned=False,
            )
        ]

        cleaned = self._clean_geometry(raw_geometry)
        if cleaned is not None and not cleaned.is_empty:
            cleaned_json = self._geometry_json(cleaned)
            candidates.append(
                BoundaryCandidateGeometry(
                    candidate_type="WATER_BODY_UNION_CLEANED",
                    geometry_json=cleaned_json,
                    point_count_before=raw_points,
                    point_count_after=self.helpers._point_count(cleaned_json),
                    area_m2=self._area_m2(cleaned),
                    cleaned=True,
                )
            )

        simplified = self._polygonal(raw_geometry.simplify(SIMPLIFY_TOLERANCE_DEGREE, preserve_topology=True))
        if simplified is not None and not simplified.is_empty and simplified.is_valid:
            simplified_json = self._geometry_json(simplified)
            candidates.append(
                BoundaryCandidateGeometry(
                    candidate_type="WATER_BODY_UNION_SIMPLIFIED",
                    geometry_json=simplified_json,
                    point_count_before=raw_points,
                    point_count_after=self.helpers._point_count(simplified_json),
                    area_m2=self._area_m2(simplified),
                    simplified=True,
                )
            )
        return candidates

    def _new_boundary(
        self,
        *,
        channel_id: int,
        candidate: BoundaryCandidateGeometry,
        source_summary: dict[str, Any],
    ) -> NavigationChannelBoundary:
        geometry = candidate.geometry_json
        bbox = self.helpers._geometry_bbox(geometry)
        bbox_dict = {
            "min_lng": bbox["bbox_min_lng"],
            "min_lat": bbox["bbox_min_lat"],
            "max_lng": bbox["bbox_max_lng"],
            "max_lat": bbox["bbox_max_lat"],
        }
        trace = {
            **source_summary,
            "source": "MATCHED_WATER_BODY",
            "candidate_type": candidate.candidate_type,
            "point_count_before": candidate.point_count_before,
            "point_count_after": candidate.point_count_after,
            "area_m2": round(candidate.area_m2, 2) if candidate.area_m2 is not None else None,
            "simplified": candidate.simplified,
            "cleaned": candidate.cleaned,
            "generated_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
        }
        if candidate.warning:
            trace["warning"] = candidate.warning
        quality = "READY_WITH_WARNING" if candidate.candidate_type == "WATER_BODY_UNION_SIMPLIFIED" else "REVIEW"
        return NavigationChannelBoundary(
            channel_id=channel_id,
            geometry_json=geometry,
            boundary_paths_low=self.helpers._polygon_paths(geometry),
            boundary_paths_medium=self.helpers._polygon_paths(geometry),
            boundary_paths_high=self.helpers._polygon_paths(geometry),
            center_longitude=self.helpers._center_lng(bbox_dict),
            center_latitude=self.helpers._center_lat(bbox_dict),
            display_center_longitude=self.helpers._center_lng(bbox_dict),
            display_center_latitude=self.helpers._center_lat(bbox_dict),
            bbox_min_lng=bbox["bbox_min_lng"],
            bbox_min_lat=bbox["bbox_min_lat"],
            bbox_max_lng=bbox["bbox_max_lng"],
            bbox_max_lat=bbox["bbox_max_lat"],
            ring_count=self.helpers._ring_count(geometry),
            point_count=self.helpers._point_count(geometry),
            geometry_status_code="AVAILABLE",
            boundary_quality_code=quality,
            connectivity_status_code="NEED_REVIEW",
            repair_status_code="NONE",
            coverage_policy_code=candidate.candidate_type,
            geometry_coordinate_system_code="WGS84",
            boundary_coordinate_system_code="WGS84",
            source_trace_json=trace,
            is_current=False,
            imported_at=self.helpers._now(),
        )

    def _body_polygons(self, bodies: list[NavigationWaterBody]) -> list[Polygon | MultiPolygon]:
        polygons: list[Polygon | MultiPolygon] = []
        for body in bodies:
            geometry = body.geometry_wgs84_json
            if not isinstance(geometry, dict):
                continue
            try:
                parsed = self._polygonal(shape(geometry))
            except Exception:
                parsed = None
            if parsed is not None and not parsed.is_empty:
                polygons.append(parsed)
        return polygons

    def _clean_geometry(self, geometry: Polygon | MultiPolygon) -> Polygon | MultiPolygon | None:
        cleaned = self._polygonal(make_valid(geometry))
        if cleaned is None:
            return None
        parts = self._polygon_parts(cleaned)
        kept = [self._clean_polygon_holes(part) for part in parts if self._area_m2(part) >= MIN_CLEAN_PART_AREA_M2]
        if not kept:
            return cleaned
        return self._polygonal(unary_union(kept))

    def _clean_polygon_holes(self, polygon: Polygon) -> Polygon:
        holes = [
            list(ring.coords)
            for ring in polygon.interiors
            if self._area_m2(Polygon(ring)) >= MIN_CLEAN_HOLE_AREA_M2
        ]
        return Polygon(polygon.exterior.coords, holes)

    def _polygonal(self, geometry: Any) -> Polygon | MultiPolygon | None:
        if geometry is None or geometry.is_empty:
            return None
        if isinstance(geometry, (Polygon, MultiPolygon)):
            return geometry if geometry.is_valid else self._polygonal(make_valid(geometry))
        if isinstance(geometry, GeometryCollection):
            parts = [part for part in geometry.geoms if isinstance(part, (Polygon, MultiPolygon)) and not part.is_empty]
            if not parts:
                return None
            return self._polygonal(unary_union(parts))
        return None

    def _polygon_parts(self, geometry: Polygon | MultiPolygon) -> list[Polygon]:
        if isinstance(geometry, Polygon):
            return [geometry]
        return list(geometry.geoms)

    def _geometry_json(self, geometry: Polygon | MultiPolygon) -> dict[str, Any]:
        return json.loads(json.dumps(mapping(geometry)))

    def _area_m2(self, geometry: Polygon | MultiPolygon) -> float | None:
        if geometry.is_empty:
            return None
        return abs(float(GEOD.geometry_area_perimeter(geometry)[0]))

    def _source_summary(self, bodies: list[NavigationWaterBody]) -> dict[str, Any]:
        return {
            "matched_water_body_count": len(bodies),
            "matched_water_body_ids": [int(body.id) for body in bodies],
            "matched_water_body_names": [
                body.production_name or body.display_name or body.water_body_name or body.water_body_code
                for body in bodies
            ],
        }

    def _boundary_response(
        self,
        boundary: NavigationChannelBoundary,
        channel: NavigationChannel,
    ) -> NavigationBoundaryListItemResponse:
        return NavigationBoundaryListItemResponse(
            id=boundary.id,
            channel_id=boundary.channel_id,
            channel_code=channel.channel_code,
            channel_name=channel.channel_name,
            boundary_quality_code=boundary.boundary_quality_code,
            geometry_status_code=boundary.geometry_status_code,
            connectivity_status_code=boundary.connectivity_status_code,
            repair_status_code=boundary.repair_status_code,
            coverage_policy_code=boundary.coverage_policy_code,
            is_current=boundary.is_current,
            geometry_json=boundary.geometry_json,
            source_trace_json=boundary.source_trace_json,
        )
