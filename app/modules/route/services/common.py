"""Shared helpers for route services."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import math
from typing import Any

import httpx
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
from app.modules.tasks.repository import ACTIVE_STATUSES
from app.modules.tasks.schemas import AsyncTaskRunResponse
from app.modules.tasks.service import AsyncTaskRunService

ENDPOINT_TYPES = {"REGION", "CITY", "NODE"}
PLAN_TYPES = {"STANDARD", "SEASONAL", "EMERGENCY", "MANUAL"}
PLAN_STATUSES = {"DRAFT", "ACTIVE", "PAUSED", "ARCHIVED"}
POINT_TYPES = {"TRANSPORT_NODE", "CONSTRAINT_POINT", "MANUAL_POINT"}
TRANSPORT_MODES = {"WATER", "ROAD", "RAIL"}
TRACK_STATUSES = {"NOT_GENERATED", "READY", "PARTIAL", "FAILED"}
GEOMETRY_SOURCES = {"AMAP", "HIFLEET", "REFERENCE_HIFLEET", "NAVIGATION_ENGINE", "MANUAL", "FALLBACK"}
TRACK_VERSION_SOURCES = {"AMAP", "HIFLEET", "REFERENCE_HIFLEET", "NAVIGATION_ENGINE", "MANUAL", "FALLBACK"}
TRACK_VERSION_STATUSES = {"READY", "PARTIAL", "FAILED"}
TRACK_EDIT_STATUSES = {"ORIGINAL", "EDITED", "REDRAWN"}
ROUTE_TRACK_GENERATION_TASK_NAME = "route.generate_track_version"
ROUTE_TRACK_GENERATION_BUSINESS_TYPE = "ROUTE_PLAN_TRACK_VERSION"
ROUTE_TRACK_GENERATION_STALE_SECONDS = 900
ROUTE_WATER_FALLBACK_MODE_KEY = "ROUTE_WATER_FALLBACK_MODE"
ROUTE_WATER_FALLBACK_ALLOWED_MODES = {"local_demo", "test"}
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
    if isinstance(exc, httpx.TimeoutException):
        return "外部轨迹服务请求超时"
    if isinstance(exc, httpx.NetworkError):
        return "外部轨迹服务网络连接失败"
    if isinstance(exc, TimeoutError):
        return "外部轨迹服务请求超时"
    message = getattr(exc, "message", None)
    if message:
        return str(message).replace("\r", " ").replace("\n", " ").strip()[:180]
    text = str(exc or "").replace("\r", " ").replace("\n", " ").strip()
    return (text or "未知错误")[:180]


def _track_source_display(value: str | None) -> str:
    source = str(value or "").strip().upper()
    return {
        "HIFLEET": "AMMS",
        "REFERENCE_HIFLEET": "AMMS参考",
        "NAVIGATION_ENGINE": "自研航道引擎",
        "AMAP": "高德",
        "FALLBACK": "降级轨迹",
        "MANUAL": "人工修线",
    }.get(source, source or "轨迹")


def _fallback_geometry(start: tuple[float, float], end: tuple[float, float]) -> dict[str, Any]:
    start_lon, start_lat = float(start[0]), float(start[1])
    end_lon, end_lat = float(end[0]), float(end[1])
    mid_lon = (start_lon + end_lon) / 2
    mid_lat = (start_lat + end_lat) / 2
    dx = end_lon - start_lon
    dy = end_lat - start_lat
    length = math.hypot(dx, dy)
    if length < 0.000001:
        offset = 0.02
        return _line_string_geometry(
            [
                [start_lon, start_lat],
                [start_lon + offset * 0.45, start_lat + offset * 0.12],
                [start_lon + offset, start_lat + offset * 0.55],
                [start_lon + offset * 0.35, start_lat + offset],
                [end_lon, end_lat],
            ]
        )
    offset = min(0.18, max(0.03, length * 0.08))
    control = [mid_lon - dy / length * offset, mid_lat + dx / length * offset]
    return _line_string_geometry(
        [
            [start_lon, start_lat],
            [(start_lon + control[0]) / 2, (start_lat + control[1]) / 2],
            control,
            [(control[0] + end_lon) / 2, (control[1] + end_lat) / 2],
            [end_lon, end_lat],
        ]
    )


def _should_use_fallback_track(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, TimeoutError)):
        return True
    text = str(exc or "").lower()
    fallback_markers = (
        "userkey_plat_nomatch",
        "userkey",
        "未配置 route_amap_web_api_key",
        "amms 路径服务未启用",
        "未配置 amms",
        "登录退避",
        "登录失败",
        "请求失败",
        "nodename",
        "network",
        "timeout",
        "timed out",
        "connection",
        "event loop is closed",
    )
    return any(marker in text for marker in fallback_markers)


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
    active_track_generation_task: AsyncTaskRunResponse | None = None,
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
        active_track_generation_task=active_track_generation_task,
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
    active_track_generation_task: AsyncTaskRunResponse | None = None,
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
        structure_revision=int(entity.structure_revision or 1),
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
        active_track_generation_task=active_track_generation_task,
    )


def _normalize_provider_code(provider_code: str | None) -> str:
    return str(provider_code or "AUTO").strip().upper() or "AUTO"


def _track_generation_idempotency_key(plan, provider_code: str | None = None) -> str:
    return f"{ROUTE_TRACK_GENERATION_TASK_NAME}:{plan.id}:{int(plan.structure_revision or 1)}:{_normalize_provider_code(provider_code)}"


def _track_generation_idempotency_key_prefix(plan) -> str:
    return f"{ROUTE_TRACK_GENERATION_TASK_NAME}:{plan.id}:{int(plan.structure_revision or 1)}:"


async def _latest_track_generation_task(
    db: AsyncSession,
    plan,
    *,
    provider_code: str | None = None,
) -> AsyncTaskRunResponse | None:
    return await AsyncTaskRunService(db).get_latest_by_idempotency_key(
        _track_generation_idempotency_key(plan, provider_code),
        stale_seconds=ROUTE_TRACK_GENERATION_STALE_SECONDS,
        recover_stale=True,
    )


async def _active_track_generation_task(
    db: AsyncSession,
    plan,
    *,
    provider_code: str | None = None,
) -> AsyncTaskRunResponse | None:
    if provider_code is None:
        task = await AsyncTaskRunService(db).get_latest_by_idempotency_key_prefix(
            _track_generation_idempotency_key_prefix(plan),
            status_codes=ACTIVE_STATUSES,
            stale_seconds=ROUTE_TRACK_GENERATION_STALE_SECONDS,
            recover_stale=True,
        )
    else:
        task = await _latest_track_generation_task(db, plan, provider_code=provider_code)
    if task is None or task.status_code not in ACTIVE_STATUSES:
        return None
    return task


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
    current_structure_revision: int | None = None,
) -> RoutePlanTrackVersionResponse:
    structure_revision = int(entity.structure_revision or 1)
    compatible_revision = current_structure_revision is None or structure_revision == int(current_structure_revision or 1)
    return RoutePlanTrackVersionResponse(
        id=entity.id,
        plan_id=entity.plan_id,
        structure_revision=structure_revision,
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
        is_compatible_with_current_structure=compatible_revision,
        segments=[_to_track_version_segment_response(item) for item in (segments or [])],
    )


__all__ = [name for name in globals() if not name.startswith("__")]
