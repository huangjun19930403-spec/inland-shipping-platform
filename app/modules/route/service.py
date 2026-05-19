"""route 模块 service。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import math
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.integrations.amap.route_client import AmapRouteClient
from app.integrations.hifleet.client import HifleetRouteClient
from app.integrations.http.route_geometry_types import RouteGeometryQuery, RouteGeometryResult
from app.models.address import NavigationConstraintPoint, Region, TransportNode
from app.models.route import (
    ShippingRoutePlanPoint,
    ShippingRoutePlanSegment,
    ShippingRoutePlanTrackVersion,
    ShippingRoutePlanTrackVersionSegment,
)
from app.modules.dictionary.service import CodeSequenceService
from app.modules.route.repository import (
    ShippingRoutePlanRepository,
    ShippingRoutePlanStructureRepository,
    ShippingRouteRepository,
)
from app.modules.route.schemas import (
    PageResponse,
    RouteDetailResponse,
    RoutePlanPointResponse,
    RoutePlanResponse,
    RoutePlanSegmentResponse,
    RoutePlanStructureResponse,
    RoutePlanTrackVersionResponse,
    RoutePlanTrackVersionSegmentResponse,
    RouteResponse,
    RouteTrackVersionGenerateResponse,
)
from app.modules.system.runtime_config import RuntimeConfigService

ENDPOINT_TYPES = {"REGION", "CITY", "NODE"}
PLAN_TYPES = {"STANDARD", "SEASONAL", "EMERGENCY", "MANUAL"}
PLAN_STATUSES = {"DRAFT", "ACTIVE", "PAUSED", "ARCHIVED"}
POINT_TYPES = {"TRANSPORT_NODE", "CONSTRAINT_POINT", "MANUAL_POINT"}
TRANSPORT_MODES = {"WATER", "ROAD", "RAIL"}
TRACK_STATUSES = {"NOT_GENERATED", "READY", "PARTIAL", "FAILED"}
GEOMETRY_SOURCES = {"AMAP", "HIFLEET", "MANUAL", "FALLBACK"}
TRACK_VERSION_SOURCES = {"AMAP", "HIFLEET", "MANUAL", "FALLBACK"}
TRACK_VERSION_STATUSES = {"READY", "PARTIAL", "FAILED"}
TRACK_EDIT_STATUSES = {"ORIGINAL", "EDITED", "REDRAWN"}
PLAN_POINT_COMPARE_FIELDS = (
    "point_order",
    "point_type_code",
    "transport_node_id",
    "constraint_point_id",
    "manual_name",
    "longitude",
    "latitude",
    "display_name",
    "transport_mode_after_code",
    "remark",
)


def _status_from_provider_status(value: str | None) -> str:
    return "READY" if str(value or "").lower() == "ready" else "FAILED"


def _geometry_source_from_provider(value: str | None) -> str | None:
    source = str(value or "").strip().upper()
    return source if source in GEOMETRY_SOURCES else None


def _line_string_points(geometry: dict | None) -> list[list[float]]:
    if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
        return []
    points: list[list[float]] = []
    for item in geometry.get("coordinates") or []:
        if not isinstance(item, list | tuple) or len(item) < 2:
            continue
        try:
            lon = float(item[0])
            lat = float(item[1])
        except (TypeError, ValueError):
            continue
        if -180 <= lon <= 180 and -90 <= lat <= 90 and (not points or points[-1] != [lon, lat]):
            points.append([lon, lat])
    return points


def _line_string_geometry(points: list[list[float]]) -> dict[str, Any]:
    return {"type": "LineString", "coordinates": [[float(lon), float(lat)] for lon, lat in points]}


def _snap_line_string_to_anchors(
    geometry: dict | None,
    start: tuple[float, float],
    end: tuple[float, float],
) -> dict[str, Any]:
    points = _line_string_points(geometry)
    if len(points) < 2:
        raise ValidationError("轨迹段必须是至少包含 2 个点的 LineString")
    snapped = [list(item) for item in points]
    snapped[0] = [float(start[0]), float(start[1])]
    snapped[-1] = [float(end[0]), float(end[1])]
    compact: list[list[float]] = []
    for point in snapped:
        if not compact or compact[-1] != point:
            compact.append(point)
    if len(compact) < 2:
        compact = [[float(start[0]), float(start[1])], [float(end[0]), float(end[1])]]
    return _line_string_geometry(compact)


def _haversine_km(a: list[float], b: list[float]) -> float:
    lon1, lat1 = math.radians(float(a[0])), math.radians(float(a[1]))
    lon2, lat2 = math.radians(float(b[0])), math.radians(float(b[1]))
    d_lon = lon2 - lon1
    d_lat = lat2 - lat1
    value = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
    return 6371.0088 * 2 * math.atan2(math.sqrt(value), math.sqrt(max(0.0, 1 - value)))


def _line_distance_km(geometry: dict | None) -> Decimal | None:
    points = _line_string_points(geometry)
    if len(points) < 2:
        return None
    distance = sum(_haversine_km(points[index - 1], points[index]) for index in range(1, len(points)))
    return Decimal(str(round(distance, 2)))


def _line_point_count(geometry: dict | None) -> int:
    return len(_line_string_points(geometry))


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _safe_error_message(exc: Exception) -> str:
    text = str(exc or "").replace("\r", " ").replace("\n", " ").strip()
    return (text or "未知错误")[:180]


def _point_compare_value(field: str, value: Any) -> Any:
    if value is None:
        return None
    if field in {"longitude", "latitude"}:
        return str(Decimal(str(value)).quantize(Decimal("0.00000001")))
    if isinstance(value, str):
        return value.strip()
    return value


def _point_compare_signature(item: Any) -> tuple[Any, ...]:
    return tuple(
        _point_compare_value(field, item.get(field) if isinstance(item, dict) else getattr(item, field, None))
        for field in PLAN_POINT_COMPARE_FIELDS
    )


def _track_status(segment_count: int, selected_result_count: int, failed_count: int = 0) -> str:
    if failed_count > 0:
        return "FAILED"
    if segment_count <= 0:
        return "NOT_GENERATED"
    if selected_result_count == segment_count:
        return "READY"
    if selected_result_count > 0:
        return "PARTIAL"
    return "NOT_GENERATED"


def _track_status_from_current_version(segment_count: int, current_segment_count: int, current_failed_count: int = 0) -> str:
    if current_failed_count > 0:
        return "FAILED"
    if segment_count <= 0:
        return "NOT_GENERATED"
    if current_segment_count == segment_count:
        return "READY"
    if current_segment_count > 0:
        return "PARTIAL"
    return "NOT_GENERATED"


def _to_route_response(
    entity,
    *,
    plan_count: int = 0,
    point_count: int = 0,
    segment_count: int = 0,
    selected_result_count: int = 0,
    current_track_version_id: int | None = None,
    current_track_version_no: int | None = None,
    current_track_source_type_code: str | None = None,
    track_version_count: int = 0,
    default_plan_id: int | None = None,
    default_plan_name: str | None = None,
    track_status: str = "NOT_GENERATED",
    track_error_message: str | None = None,
    track_generated_at: datetime | None = None,
) -> RouteResponse:
    return RouteResponse(
        id=entity.id,
        code=entity.code,
        name=entity.name,
        origin_endpoint_type_code=entity.origin_endpoint_type_code,
        origin_region_id=entity.origin_region_id,
        origin_city_code=entity.origin_city_code,
        origin_node_id=entity.origin_node_id,
        destination_endpoint_type_code=entity.destination_endpoint_type_code,
        destination_region_id=entity.destination_region_id,
        destination_city_code=entity.destination_city_code,
        destination_node_id=entity.destination_node_id,
        transport_org_type_code=entity.transport_org_type_code,
        multimodal_combination_code=entity.multimodal_combination_code,
        status_code=entity.status_code,
        description=entity.description,
        audit_status=entity.audit_status,
        submitter_id=entity.submitter_id,
        auditor_id=entity.auditor_id,
        audited_at=entity.audited_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        plan_count=plan_count,
        point_count=point_count,
        segment_count=segment_count,
        selected_result_count=selected_result_count,
        current_track_version_id=current_track_version_id,
        current_track_version_no=current_track_version_no,
        current_track_source_type_code=current_track_source_type_code,
        track_version_count=track_version_count,
        default_plan_id=default_plan_id,
        default_plan_name=default_plan_name,
        track_status=track_status,
        track_error_message=track_error_message,
        track_generated_at=track_generated_at,
    )


def _to_plan_response(
    entity,
    *,
    point_count: int = 0,
    segment_count: int = 0,
    selected_result_count: int = 0,
    failed_count: int = 0,
    current_track_version: ShippingRoutePlanTrackVersion | None = None,
    track_version_count: int = 0,
) -> RoutePlanResponse:
    return RoutePlanResponse(
        id=entity.id,
        route_id=entity.route_id,
        plan_code=entity.plan_code,
        plan_name=entity.plan_name,
        plan_type_code=entity.plan_type_code,
        is_default=entity.is_default,
        status_code=entity.status_code,
        display_order=entity.display_order,
        applicable_condition=entity.applicable_condition,
        remark=entity.remark,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        point_count=point_count,
        segment_count=segment_count,
        selected_result_count=selected_result_count,
        current_track_version_id=entity.current_track_version_id,
        current_track_version_no=current_track_version.version_no if current_track_version else None,
        current_track_source_type_code=current_track_version.source_type_code if current_track_version else None,
        track_version_count=track_version_count,
        track_status=_track_status_from_current_version(segment_count, selected_result_count, failed_count),
    )


def _to_point_response(
    entity: ShippingRoutePlanPoint,
    *,
    transport_node: TransportNode | None = None,
    constraint_point: NavigationConstraintPoint | None = None,
) -> RoutePlanPointResponse:
    longitude = entity.longitude
    latitude = entity.latitude
    resolved_name = entity.display_name
    resolved_code = None
    resolved_node_type_code = entity.point_type_code
    resolved_address = entity.remark

    if transport_node is not None:
        longitude = transport_node.longitude
        latitude = transport_node.latitude
        resolved_name = transport_node.name
        resolved_code = transport_node.code
        resolved_node_type_code = transport_node.node_type_code
        resolved_address = transport_node.address
    elif constraint_point is not None:
        longitude = constraint_point.longitude
        latitude = constraint_point.latitude
        resolved_name = constraint_point.name
        resolved_code = constraint_point.code
        resolved_node_type_code = constraint_point.constraint_type_code
        resolved_address = constraint_point.description or entity.remark
    elif entity.point_type_code == "MANUAL_POINT":
        resolved_name = entity.manual_name or entity.display_name
        resolved_node_type_code = "MANUAL_POINT"

    return RoutePlanPointResponse(
        id=entity.id,
        plan_id=entity.plan_id,
        point_order=entity.point_order,
        point_type_code=entity.point_type_code,
        transport_node_id=entity.transport_node_id,
        constraint_point_id=entity.constraint_point_id,
        manual_name=entity.manual_name,
        longitude=longitude,
        latitude=latitude,
        display_name=entity.display_name,
        transport_mode_after_code=entity.transport_mode_after_code,
        resolved_name=resolved_name,
        resolved_code=resolved_code,
        resolved_node_type_code=resolved_node_type_code,
        resolved_address=resolved_address,
        remark=entity.remark,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_segment_response(
    entity: ShippingRoutePlanSegment,
    *,
    point_by_id: dict[int, ShippingRoutePlanPoint] | None = None,
) -> RoutePlanSegmentResponse:
    point_by_id = point_by_id or {}
    start = point_by_id.get(entity.start_plan_point_id)
    end = point_by_id.get(entity.end_plan_point_id)
    return RoutePlanSegmentResponse(
        id=entity.id,
        plan_id=entity.plan_id,
        segment_no=entity.segment_no,
        start_plan_point_id=entity.start_plan_point_id,
        end_plan_point_id=entity.end_plan_point_id,
        start_point_order=start.point_order if start else None,
        end_point_order=end.point_order if end else None,
        transport_mode_code=entity.transport_mode_code,
        generation_status_code=entity.generation_status_code,
        error_message=entity.error_message,
        generated_at=entity.generated_at,
        remark=entity.remark,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_track_version_segment_response(
    entity: ShippingRoutePlanTrackVersionSegment,
) -> RoutePlanTrackVersionSegmentResponse:
    return RoutePlanTrackVersionSegmentResponse(
        id=entity.id,
        version_id=entity.version_id,
        segment_id=entity.segment_id,
        segment_no=entity.segment_no,
        geometry_json=entity.geometry_json,
        distance_km=entity.distance_km,
        estimated_duration_hour=entity.estimated_duration_hour,
        point_count=entity.point_count,
        edit_status_code=entity.edit_status_code,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_track_version_response(
    entity: ShippingRoutePlanTrackVersion,
    *,
    segments: list[ShippingRoutePlanTrackVersionSegment] | None = None,
) -> RoutePlanTrackVersionResponse:
    return RoutePlanTrackVersionResponse(
        id=entity.id,
        plan_id=entity.plan_id,
        version_no=entity.version_no,
        version_name=entity.version_name,
        source_type_code=entity.source_type_code,
        provider_type_code=entity.provider_type_code,
        parent_version_id=entity.parent_version_id,
        is_current=entity.is_current,
        version_status_code=entity.version_status_code,
        distance_km=entity.distance_km,
        estimated_duration_hour=entity.estimated_duration_hour,
        point_count=entity.point_count,
        segment_count=entity.segment_count,
        summary_json=entity.summary_json,
        error_message=entity.error_message,
        generated_at=entity.generated_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        segments=[_to_track_version_segment_response(item) for item in (segments or [])],
    )


class ShippingRouteService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.route_repo = ShippingRouteRepository(db)
        self.plan_repo = ShippingRoutePlanRepository(db)
        self.structure_repo = ShippingRoutePlanStructureRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def _route_stats(self, route_id: int) -> dict[str, Any]:
        plans = await self.plan_repo.list_all_plans(route_id)
        plan_count = len(plans)
        point_count = 0
        segment_count = 0
        selected_result_count = 0
        failed_count = 0
        track_version_count = 0
        current_track_version_id = None
        current_track_version_no = None
        current_track_source_type_code = None
        default_plan_id = None
        default_plan_name = None
        track_generated_at = None
        track_error_message = None
        for plan in plans:
            if plan.is_default and default_plan_id is None:
                default_plan_id = plan.id
                default_plan_name = plan.plan_name
                current_track_version_id = plan.current_track_version_id
            points = await self.structure_repo.list_points(plan.id)
            segments = await self.structure_repo.list_segments(plan.id)
            versions = await self.structure_repo.list_track_versions(plan.id)
            track_version_count += len(versions)
            current_version = next((item for item in versions if item.id == plan.current_track_version_id), None)
            current_version_segments = await self.structure_repo.list_track_version_segments([current_version.id]) if current_version else []
            point_count += len(points)
            segment_count += len(segments)
            selected_result_count += len(current_version_segments)
            failed_count += 1 if current_version and current_version.version_status_code == "FAILED" else 0
            if current_version:
                if plan.is_default and current_track_version_no is None:
                    current_track_version_no = current_version.version_no
                    current_track_source_type_code = current_version.source_type_code
                if current_version.generated_at and (track_generated_at is None or current_version.generated_at > track_generated_at):
                    track_generated_at = current_version.generated_at
                if current_version.error_message:
                    track_error_message = current_version.error_message
        return {
            "plan_count": plan_count,
            "point_count": point_count,
            "segment_count": segment_count,
            "selected_result_count": selected_result_count,
            "current_track_version_id": current_track_version_id,
            "current_track_version_no": current_track_version_no,
            "current_track_source_type_code": current_track_source_type_code,
            "track_version_count": track_version_count,
            "default_plan_id": default_plan_id,
            "default_plan_name": default_plan_name,
            "track_status": _track_status_from_current_version(segment_count, selected_result_count, failed_count),
            "track_error_message": track_error_message,
            "track_generated_at": track_generated_at,
        }

    async def _plan_response(self, plan) -> RoutePlanResponse:
        points = await self.structure_repo.list_points(plan.id)
        segments = await self.structure_repo.list_segments(plan.id)
        versions = await self.structure_repo.list_track_versions(plan.id)
        current_version = next((item for item in versions if item.id == plan.current_track_version_id), None)
        current_version_segments = await self.structure_repo.list_track_version_segments([current_version.id]) if current_version else []
        selected_count = len(current_version_segments)
        failed_count = 1 if current_version and current_version.version_status_code == "FAILED" else 0
        return _to_plan_response(
            plan,
            point_count=len(points),
            segment_count=len(segments),
            selected_result_count=selected_count,
            failed_count=failed_count,
            current_track_version=current_version,
            track_version_count=len(versions),
        )

    async def list_routes(self, query) -> PageResponse[RouteResponse]:
        rows, total = await self.route_repo.list_routes_with_stats(
            keyword=query.keyword,
            origin_endpoint_type_code=query.origin_endpoint_type_code,
            origin_region_id=query.origin_region_id,
            origin_city_code=query.origin_city_code,
            origin_node_id=query.origin_node_id,
            destination_endpoint_type_code=query.destination_endpoint_type_code,
            destination_region_id=query.destination_region_id,
            destination_city_code=query.destination_city_code,
            destination_node_id=query.destination_node_id,
            transport_org_type_code=query.transport_org_type_code,
            plan_type_code=query.plan_type_code,
            has_plan=query.has_plan,
            has_default_plan=query.has_default_plan,
            track_status=query.track_status,
            page=query.page,
            page_size=query.page_size,
        )
        responses: list[RouteResponse] = []
        for (
            row,
            plan_count,
            point_count,
            segment_count,
            selected_count,
            current_version_id,
            current_version_no,
            current_source,
            track_version_count,
            default_id,
            default_name,
            status,
            error,
            generated_at,
        ) in rows:
            responses.append(
                _to_route_response(
                    row,
                    plan_count=plan_count,
                    point_count=point_count,
                    segment_count=segment_count,
                    selected_result_count=selected_count,
                    current_track_version_id=current_version_id,
                    current_track_version_no=current_version_no,
                    current_track_source_type_code=current_source,
                    track_version_count=track_version_count,
                    default_plan_id=default_id,
                    default_plan_name=default_name,
                    track_status=status,
                    track_error_message=error,
                    track_generated_at=generated_at,
                )
            )
        return PageResponse[RouteResponse](total=total, page=query.page, page_size=query.page_size, items=responses)

    async def create_route(self, payload) -> RouteResponse:
        data = payload.model_dump(exclude_none=True)
        code = (payload.code or "").strip() or await self.sequence_service.next_code("ROUTE_CODE")
        data["code"] = code
        data["audit_status"] = "APPROVED"
        data["name"] = payload.name.strip()
        data = await self._normalize_route_endpoint_data(data)
        if await self.route_repo.exists_route_code(code):
            raise ConflictError(f"route code already exists: {code}")
        row = await self.route_repo.create_route(data)
        await self.db.commit()
        return _to_route_response(row)

    async def update_route(self, route_id: int, payload) -> RouteResponse:
        route = await self.route_repo.get_route_by_id(route_id)
        if route is None:
            raise NotFoundError("ShippingRoute", route_id)
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            raise ValidationError("no update fields provided")
        merged = {
            "origin_endpoint_type_code": route.origin_endpoint_type_code,
            "origin_region_id": route.origin_region_id,
            "origin_city_code": route.origin_city_code,
            "origin_node_id": route.origin_node_id,
            "destination_endpoint_type_code": route.destination_endpoint_type_code,
            "destination_region_id": route.destination_region_id,
            "destination_city_code": route.destination_city_code,
            "destination_node_id": route.destination_node_id,
        }
        merged.update({key: value for key, value in updates.items() if key in merged})
        normalized_endpoint = await self._normalize_route_endpoint_data(merged)
        updates.update(normalized_endpoint)
        if "name" in updates and updates["name"] is not None:
            updates["name"] = updates["name"].strip()
        row = await self.route_repo.update_route(route_id, updates)
        await self.db.commit()
        stats = await self._route_stats(row.id)
        return _to_route_response(row, **stats)

    async def get_route_detail(self, route_id: int) -> RouteDetailResponse:
        route = await self.route_repo.get_route_by_id(route_id)
        if route is None:
            raise NotFoundError("ShippingRoute", route_id)
        plans = await self.plan_repo.list_all_plans(route_id)
        return RouteDetailResponse(
            route=_to_route_response(route, **await self._route_stats(route_id)),
            plans=[await self._plan_response(plan) for plan in plans],
        )

    async def delete_route(self, route_id: int) -> None:
        ok = await self.route_repo.hard_delete_route(route_id)
        if not ok:
            raise NotFoundError("ShippingRoute", route_id)
        await self.db.commit()

    async def _normalize_route_endpoint_data(self, data: dict[str, Any]) -> dict[str, Any]:
        for side in ("origin", "destination"):
            type_key = f"{side}_endpoint_type_code"
            endpoint_type = str(data.get(type_key) or "REGION").upper()
            if endpoint_type not in ENDPOINT_TYPES:
                raise ValidationError(f"invalid {type_key}")
            data[type_key] = endpoint_type
            region_key = f"{side}_region_id"
            city_key = f"{side}_city_code"
            node_key = f"{side}_node_id"
            if endpoint_type == "REGION":
                if data.get(region_key) is None:
                    raise ValidationError(f"{region_key} is required")
                exists = await self.db.scalar(select(Region.id).where(Region.id == data[region_key], Region.deleted_at.is_(None)))
                if exists is None:
                    raise NotFoundError("Region", data[region_key])
                data[city_key] = None
                data[node_key] = None
            elif endpoint_type == "CITY":
                if not data.get(city_key):
                    raise ValidationError(f"{city_key} is required")
                data[region_key] = None
                data[node_key] = None
            else:
                if data.get(node_key) is None:
                    raise ValidationError(f"{node_key} is required")
                exists = await self.db.scalar(select(TransportNode.id).where(TransportNode.id == data[node_key], TransportNode.deleted_at.is_(None)))
                if exists is None:
                    raise NotFoundError("TransportNode", data[node_key])
                data[region_key] = None
                data[city_key] = None
        return data


class ShippingRoutePlanService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.route_repo = ShippingRouteRepository(db)
        self.plan_repo = ShippingRoutePlanRepository(db)
        self.structure_repo = ShippingRoutePlanStructureRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def _plan_response(self, plan) -> RoutePlanResponse:
        points = await self.structure_repo.list_points(plan.id)
        segments = await self.structure_repo.list_segments(plan.id)
        versions = await self.structure_repo.list_track_versions(plan.id)
        current_version = next((item for item in versions if item.id == plan.current_track_version_id), None)
        current_version_segments = await self.structure_repo.list_track_version_segments([current_version.id]) if current_version else []
        selected_count = len(current_version_segments)
        failed_count = 1 if current_version and current_version.version_status_code == "FAILED" else 0
        return _to_plan_response(
            plan,
            point_count=len(points),
            segment_count=len(segments),
            selected_result_count=selected_count,
            failed_count=failed_count,
            current_track_version=current_version,
            track_version_count=len(versions),
        )

    async def list_plans(self, route_id: int, query) -> PageResponse[RoutePlanResponse]:
        route = await self.route_repo.get_route_by_id(route_id)
        if route is None:
            raise NotFoundError("ShippingRoute", route_id)
        rows, total = await self.plan_repo.list_plans(route_id, query.plan_type_code, query.status_code, query.page, query.page_size)
        items = [await self._plan_response(row) for row in rows]
        return PageResponse[RoutePlanResponse](total=total, page=query.page, page_size=query.page_size, items=items)

    async def create_plan(self, route_id: int, payload) -> RoutePlanResponse:
        route = await self.route_repo.get_route_by_id(route_id)
        if route is None:
            raise NotFoundError("ShippingRoute", route_id)
        if payload.plan_type_code not in PLAN_TYPES:
            raise ValidationError("invalid plan_type_code")
        if payload.status_code not in PLAN_STATUSES:
            raise ValidationError("invalid status_code")
        field_set = getattr(payload, "model_fields_set", set())
        data = payload.model_dump(exclude_none=True)
        data["plan_code"] = (payload.plan_code or "").strip() or await self.sequence_service.next_code("ROUTE_PLAN_CODE")
        if "display_order" not in field_set:
            data["display_order"] = await self.plan_repo.next_display_order(route_id)
        existing = await self.plan_repo.list_all_plans(route_id)
        if not existing:
            data["is_default"] = True
        if data.get("is_default"):
            await self.plan_repo.clear_default_for_route(route_id)
        if await self.plan_repo.exists_plan_code(data["plan_code"]):
            raise ConflictError(f"plan code already exists: {data['plan_code']}")
        row = await self.plan_repo.create_plan(route_id, data)
        await self.db.commit()
        return await self._plan_response(row)

    async def update_plan(self, plan_id: int, payload) -> RoutePlanResponse:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        updates = payload.model_dump(exclude_unset=True)
        if "plan_type_code" in updates and updates["plan_type_code"] not in PLAN_TYPES:
            raise ValidationError("invalid plan_type_code")
        if "status_code" in updates and updates["status_code"] not in PLAN_STATUSES:
            raise ValidationError("invalid status_code")
        if not updates:
            raise ValidationError("no update fields provided")
        if updates.get("is_default"):
            await self.plan_repo.clear_default_for_route(plan.route_id, exclude_plan_id=plan_id)
        row = await self.plan_repo.update_plan(plan_id, updates)
        await self.db.commit()
        return await self._plan_response(row)

    async def delete_plan(self, plan_id: int) -> None:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        route_id = plan.route_id
        was_default = plan.is_default
        await self.structure_repo.delete_plan_structure(plan_id)
        await self.plan_repo.delete_plan(plan_id)
        if was_default:
            remaining = await self.plan_repo.list_all_plans(route_id)
            if remaining:
                remaining[0].is_default = True
                await self.db.flush()
        await self.db.commit()


class ShippingRoutePlanStructureService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.plan_repo = ShippingRoutePlanRepository(db)
        self.structure_repo = ShippingRoutePlanStructureRepository(db)
        self.runtime_config = RuntimeConfigService(db)

    async def get_structure(self, plan_id: int) -> RoutePlanStructureResponse:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        return await self._structure_response(plan)

    async def replace_structure(self, plan_id: int, payload) -> RoutePlanStructureResponse:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        points = self._normalize_points(payload.points)
        await self._validate_point_refs(points)
        existing_points = await self.structure_repo.list_points(plan_id)
        if [_point_compare_signature(point) for point in existing_points] == [_point_compare_signature(point) for point in points]:
            return await self._structure_response(plan)
        await self.structure_repo.replace_structure(plan_id, points)
        await self.db.commit()
        await self.db.refresh(plan)
        return await self._structure_response(plan)

    async def list_track_versions(self, plan_id: int) -> list[RoutePlanTrackVersionResponse]:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        versions = await self.structure_repo.list_track_versions(plan_id)
        return [_to_track_version_response(item) for item in versions]

    async def get_track_version(self, plan_id: int, version_id: int) -> RoutePlanTrackVersionResponse:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        version = await self.structure_repo.get_track_version_by_id(version_id)
        if version is None or version.plan_id != plan_id:
            raise NotFoundError("ShippingRoutePlanTrackVersion", version_id)
        segments = await self.structure_repo.list_track_version_segments([version.id])
        return _to_track_version_response(version, segments=segments)

    async def generate_track_version(self, plan_id: int, payload) -> RouteTrackVersionGenerateResponse:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        points = await self.structure_repo.list_points(plan_id)
        segments = await self.structure_repo.list_segments(plan_id)
        if not segments:
            raise ValidationError("请先维护至少两个点位，系统才能生成逻辑段")
        point_by_id = {point.id: point for point in points}
        now = datetime.utcnow()
        version_segments: list[dict[str, Any]] = []
        errors: list[str] = []
        provider_codes: set[str] = set()
        total_distance = Decimal("0")
        total_duration = Decimal("0")
        total_points = 0
        for segment in segments:
            start = point_by_id.get(segment.start_plan_point_id)
            end = point_by_id.get(segment.end_plan_point_id)
            if start is None or end is None:
                errors.append(f"航段 {segment.segment_no} 缺少起终点")
                continue
            try:
                result = await self._call_geometry_provider(
                    segment=segment,
                    start_point=start,
                    end_point=end,
                    provider_code=payload.provider_code,
                )
                status = _status_from_provider_status(result.status)
                source = _geometry_source_from_provider(result.source)
                if status != "READY" or not source:
                    raise ValidationError(f"provider 返回状态无效: {result.status}")
                raw_point_count = _line_point_count(result.geometry)
                if raw_point_count < 3:
                    raise ValidationError("provider 返回轨迹仅包含起终点，未形成可编辑轨迹")
                start_anchor = await self._resolve_point(start)
                end_anchor = await self._resolve_point(end)
                geometry = _snap_line_string_to_anchors(result.geometry, start_anchor, end_anchor)
                point_count = _line_point_count(geometry)
                if point_count < 3:
                    raise ValidationError("provider 返回轨迹仅包含起终点，未形成可编辑轨迹")
                distance = _to_decimal(result.distance_km) or _line_distance_km(geometry)
                duration = _to_decimal(result.estimated_duration_hour)
                total_distance += distance or Decimal("0")
                total_duration += duration or Decimal("0")
                total_points += point_count
                provider_codes.add(result.provider or source)
                version_segments.append(
                    {
                        "segment_id": segment.id,
                        "segment_no": segment.segment_no,
                        "geometry_json": geometry,
                        "distance_km": distance,
                        "estimated_duration_hour": duration,
                        "point_count": point_count,
                        "edit_status_code": "ORIGINAL",
                    }
                )
                segment.generation_status_code = "READY"
                segment.error_message = None
                segment.generated_at = now
            except Exception as exc:  # noqa: BLE001
                error_text = _safe_error_message(exc)
                errors.append(f"航段 {segment.segment_no}: {error_text}")
                segment.generation_status_code = "FAILED"
                segment.error_message = error_text
                segment.generated_at = now
        status = _track_status(len(segments), len(version_segments), len(errors))
        source_type = str(payload.provider_code or "").strip().upper()
        if source_type not in TRACK_VERSION_SOURCES:
            source_type = next(iter(provider_codes), None) or "HIFLEET"
        provider_type = ",".join(sorted(provider_codes)) if provider_codes else source_type
        version = await self.structure_repo.create_track_version(
            plan_id,
            {
                "version_name": f"{source_type} 生成 V{await self.structure_repo.next_track_version_no(plan_id)}",
                "source_type_code": source_type,
                "provider_type_code": provider_type,
                "parent_version_id": None,
                "is_current": False,
                "version_status_code": status if status in TRACK_VERSION_STATUSES else "FAILED",
                "distance_km": total_distance if version_segments else None,
                "estimated_duration_hour": total_duration if total_duration > 0 else None,
                "point_count": total_points,
                "segment_count": len(version_segments),
                "summary_json": {
                    "provider_codes": sorted(provider_codes),
                    "success_count": len(version_segments),
                    "segment_count": len(segments),
                    "errors": errors[:5],
                },
                "error_message": "；".join(errors)[:512] if errors else None,
                "generated_at": now,
            },
            version_segments,
        )
        await self.db.commit()
        response = await self.get_track_version(plan_id, version.id)
        if status == "READY":
            message = "轨迹版本生成完成，可进入全屏编辑后保存为当前轨迹"
        elif status == "PARTIAL":
            message = f"轨迹版本部分生成：成功 {len(version_segments)}/{len(segments)} 段"
        else:
            message = "轨迹版本生成失败"
        return RouteTrackVersionGenerateResponse(plan_id=plan_id, status=status, message=message, version=response)

    async def save_track_version(self, plan_id: int, payload) -> RoutePlanTrackVersionResponse:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        points = await self.structure_repo.list_points(plan_id)
        segments = await self.structure_repo.list_segments(plan_id)
        if not segments:
            raise ValidationError("请先维护至少两个点位，系统才能保存轨迹")
        if len(payload.segments) != len(segments):
            raise ValidationError("保存轨迹前必须补齐所有逻辑段")
        segment_by_id = {segment.id: segment for segment in segments}
        point_by_id = {point.id: point for point in points}
        seen_segment_ids: set[int] = set()
        version_segments: list[dict[str, Any]] = []
        total_distance = Decimal("0")
        total_duration = Decimal("0")
        total_points = 0
        for item in payload.segments:
            segment = segment_by_id.get(item.segment_id)
            if segment is None or item.segment_id in seen_segment_ids:
                raise ValidationError("保存轨迹包含非法或重复的逻辑段")
            seen_segment_ids.add(item.segment_id)
            start = point_by_id.get(segment.start_plan_point_id)
            end = point_by_id.get(segment.end_plan_point_id)
            if start is None or end is None:
                raise ValidationError(f"航段 {segment.segment_no} 缺少起终点")
            start_anchor = await self._resolve_point(start)
            end_anchor = await self._resolve_point(end)
            geometry = _snap_line_string_to_anchors(item.geometry_json, start_anchor, end_anchor)
            point_count = _line_point_count(geometry)
            if point_count < 2:
                raise ValidationError(f"航段 {segment.segment_no} 轨迹点不足")
            distance = item.distance_km or _line_distance_km(geometry)
            duration = item.estimated_duration_hour
            total_distance += distance or Decimal("0")
            total_duration += duration or Decimal("0")
            total_points += point_count
            edit_status = str(item.edit_status_code or "EDITED").upper()
            if edit_status not in TRACK_EDIT_STATUSES:
                edit_status = "EDITED"
            version_segments.append(
                {
                    "segment_id": segment.id,
                    "segment_no": segment.segment_no,
                    "geometry_json": geometry,
                    "distance_km": distance,
                    "estimated_duration_hour": duration,
                    "point_count": point_count,
                    "edit_status_code": edit_status,
                }
            )
        version = await self.structure_repo.create_track_version(
            plan_id,
            {
                "version_name": (payload.version_name or "").strip() or f"人工修线 V{await self.structure_repo.next_track_version_no(plan_id)}",
                "source_type_code": "MANUAL",
                "provider_type_code": None,
                "parent_version_id": payload.parent_version_id,
                "is_current": False,
                "version_status_code": "READY",
                "distance_km": total_distance,
                "estimated_duration_hour": total_duration if total_duration > 0 else None,
                "point_count": total_points,
                "segment_count": len(version_segments),
                "summary_json": payload.summary_json or {"save_mode": "MANUAL_EDIT"},
                "error_message": None,
                "generated_at": datetime.utcnow(),
            },
            version_segments,
        )
        await self.structure_repo.set_current_track_version(plan, version)
        await self.db.commit()
        return await self.get_track_version(plan_id, version.id)

    async def set_current_track_version(self, plan_id: int, version_id: int) -> RoutePlanTrackVersionResponse:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        version = await self.structure_repo.get_track_version_by_id(version_id)
        if version is None or version.plan_id != plan_id:
            raise NotFoundError("ShippingRoutePlanTrackVersion", version_id)
        if version.version_status_code != "READY":
            raise ValidationError("只能把 READY 状态的轨迹版本设为当前")
        expected_count = len(await self.structure_repo.list_segments(plan_id))
        version_segment_count = len(await self.structure_repo.list_track_version_segments([version.id]))
        if expected_count <= 0 or version_segment_count != expected_count:
            raise ValidationError("该轨迹版本没有覆盖全部逻辑段，不能设为当前")
        await self.structure_repo.set_current_track_version(plan, version)
        await self.db.commit()
        return await self.get_track_version(plan_id, version.id)

    async def delete_track_version(self, plan_id: int, version_id: int) -> None:
        plan = await self.plan_repo.get_plan_by_id(plan_id)
        if plan is None:
            raise NotFoundError("ShippingRoutePlan", plan_id)
        version = await self.structure_repo.get_track_version_by_id(version_id)
        if version is None or version.plan_id != plan_id:
            raise NotFoundError("ShippingRoutePlanTrackVersion", version_id)
        await self.structure_repo.delete_track_version(plan, version)
        await self.db.commit()

    async def _structure_response(self, plan) -> RoutePlanStructureResponse:
        points = await self.structure_repo.list_points(plan.id)
        segments = await self.structure_repo.list_segments(plan.id)
        point_responses = await self._point_responses(points)
        versions = await self.structure_repo.list_track_versions(plan.id)
        current_version = next((item for item in versions if item.id == plan.current_track_version_id), None)
        current_version_segments = await self.structure_repo.list_track_version_segments([current_version.id]) if current_version else []
        selected_count = len(current_version_segments)
        failed_count = 1 if current_version and current_version.version_status_code == "FAILED" else 0
        return RoutePlanStructureResponse(
            plan=_to_plan_response(
                plan,
                point_count=len(points),
                segment_count=len(segments),
                selected_result_count=selected_count,
                failed_count=failed_count,
                current_track_version=current_version,
                track_version_count=len(versions),
            ),
            points=point_responses,
            segments=[
                _to_segment_response(
                    segment,
                    point_by_id={point.id: point for point in points},
                )
                for segment in segments
            ],
        )

    async def _point_responses(self, points: list[ShippingRoutePlanPoint]) -> list[RoutePlanPointResponse]:
        transport_ids = {
            point.transport_node_id
            for point in points
            if point.point_type_code == "TRANSPORT_NODE" and point.transport_node_id is not None
        }
        constraint_ids = {
            point.constraint_point_id
            for point in points
            if point.point_type_code == "CONSTRAINT_POINT" and point.constraint_point_id is not None
        }
        transport_by_id: dict[int, TransportNode] = {}
        constraint_by_id: dict[int, NavigationConstraintPoint] = {}
        if transport_ids:
            rows = (
                await self.db.execute(
                    select(TransportNode).where(TransportNode.id.in_(transport_ids), TransportNode.deleted_at.is_(None))
                )
            ).scalars()
            transport_by_id = {row.id: row for row in rows}
        if constraint_ids:
            rows = (
                await self.db.execute(select(NavigationConstraintPoint).where(NavigationConstraintPoint.id.in_(constraint_ids)))
            ).scalars()
            constraint_by_id = {row.id: row for row in rows}
        return [
            _to_point_response(
                point,
                transport_node=transport_by_id.get(point.transport_node_id),
                constraint_point=constraint_by_id.get(point.constraint_point_id),
            )
            for point in points
        ]

    def _normalize_points(self, items) -> list[dict[str, Any]]:
        rows = []
        total = len(items)
        for idx, item in enumerate(items, start=1):
            data = item.model_dump(exclude_none=True)
            data["point_order"] = idx
            point_type = data.get("point_type_code")
            if point_type not in POINT_TYPES:
                raise ValidationError("invalid point_type_code")
            has_transport = data.get("transport_node_id") is not None
            has_constraint = data.get("constraint_point_id") is not None
            if point_type == "TRANSPORT_NODE":
                if not has_transport or has_constraint or data.get("manual_name") or data.get("longitude") is not None or data.get("latitude") is not None:
                    raise ValidationError("TRANSPORT_NODE must only reference transport_node_id")
            elif point_type == "CONSTRAINT_POINT":
                if not has_constraint or has_transport or data.get("manual_name") or data.get("longitude") is not None or data.get("latitude") is not None:
                    raise ValidationError("CONSTRAINT_POINT must only reference constraint_point_id")
            else:
                if has_transport or has_constraint:
                    raise ValidationError("MANUAL_POINT must not reference existing nodes")
                if not data.get("manual_name") or data.get("longitude") is None or data.get("latitude") is None:
                    raise ValidationError("MANUAL_POINT requires name and lng/lat")
                lng = Decimal(str(data["longitude"]))
                lat = Decimal(str(data["latitude"]))
                if lng < Decimal("-180") or lng > Decimal("180") or lat < Decimal("-90") or lat > Decimal("90"):
                    raise ValidationError("invalid manual point coordinates")
            if idx < total:
                mode = data.get("transport_mode_after_code")
                if mode not in TRANSPORT_MODES:
                    raise ValidationError("transport_mode_after_code is required before the next point")
            else:
                data["transport_mode_after_code"] = None
            rows.append(data)
        return rows

    async def _validate_point_refs(self, points: list[dict[str, Any]]) -> None:
        for item in points:
            if item["point_type_code"] == "TRANSPORT_NODE":
                exists = await self.db.scalar(
                    select(TransportNode.id).where(TransportNode.id == item["transport_node_id"], TransportNode.deleted_at.is_(None))
                )
                if exists is None:
                    raise NotFoundError("TransportNode", item["transport_node_id"])
            elif item["point_type_code"] == "CONSTRAINT_POINT":
                exists = await self.db.scalar(
                    select(NavigationConstraintPoint.id).where(NavigationConstraintPoint.id == item["constraint_point_id"])
                )
                if exists is None:
                    raise NotFoundError("NavigationConstraintPoint", item["constraint_point_id"])

    async def _resolve_point(self, point: ShippingRoutePlanPoint) -> tuple[float, float]:
        longitude = point.longitude
        latitude = point.latitude
        if point.point_type_code == "TRANSPORT_NODE":
            transport_node = await self.db.scalar(
                select(TransportNode).where(TransportNode.id == point.transport_node_id, TransportNode.deleted_at.is_(None))
            )
            if transport_node is None:
                raise NotFoundError("TransportNode", point.transport_node_id)
            longitude = transport_node.longitude
            latitude = transport_node.latitude
        elif point.point_type_code == "CONSTRAINT_POINT":
            constraint_point = await self.db.scalar(
                select(NavigationConstraintPoint).where(NavigationConstraintPoint.id == point.constraint_point_id)
            )
            if constraint_point is None:
                raise NotFoundError("NavigationConstraintPoint", point.constraint_point_id)
            longitude = constraint_point.longitude
            latitude = constraint_point.latitude
        if longitude is None or latitude is None:
            raise ValidationError(f"点位缺少经纬度: {point.display_name}")
        lon = float(longitude)
        lat = float(latitude)
        if lon < -180 or lon > 180 or lat < -90 or lat > 90:
            raise ValidationError(f"点位经纬度非法: {point.display_name}")
        return lon, lat

    def _geometry_client_for_segment(self, transport_mode_code: str, provider_code: str | None):
        provider_override = str(provider_code or "").strip().upper()
        if provider_override in {"AMAP", "HIFLEET"}:
            provider = provider_override
        elif provider_override and provider_override != "AUTO":
            raise ValidationError(f"不支持的轨迹 provider_code: {provider_override}")
        elif transport_mode_code == "WATER":
            provider = "HIFLEET"
        elif transport_mode_code == "ROAD":
            provider = "AMAP"
        elif transport_mode_code == "RAIL":
            raise ValidationError("铁路段暂不支持真实轨迹生成")
        else:
            raise ValidationError(f"不支持的运输方式: {transport_mode_code}")
        if provider == "HIFLEET":
            return HifleetRouteClient(runtime_config=self.runtime_config)
        return AmapRouteClient(runtime_config=self.runtime_config)

    async def _call_geometry_provider(
        self,
        *,
        segment: ShippingRoutePlanSegment,
        start_point: ShippingRoutePlanPoint,
        end_point: ShippingRoutePlanPoint,
        provider_code: str | None,
    ) -> RouteGeometryResult:
        origin_lon, origin_lat = await self._resolve_point(start_point)
        dest_lon, dest_lat = await self._resolve_point(end_point)
        client = self._geometry_client_for_segment(segment.transport_mode_code, provider_code)
        return await client.generate(
            RouteGeometryQuery(
                origin_lon=origin_lon,
                origin_lat=origin_lat,
                dest_lon=dest_lon,
                dest_lat=dest_lat,
                transport_mode=segment.transport_mode_code,
                segment_type="ROUTE_PLAN_SEGMENT",
            )
        )
