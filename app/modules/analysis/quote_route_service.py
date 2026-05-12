"""Quote route estimation service with explicit map-state semantics."""

from __future__ import annotations

from datetime import UTC, datetime
import math
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.integrations.hifleet.client import HifleetRouteClient
from app.integrations.http.route_geometry_types import RouteGeometryQuery
from app.models.address import TransportNode, TransportNodeBusinessCategory
from app.modules.analysis.map_state import build_map_state, default_retry_action
from app.modules.analysis.schemas import QuoteRouteEstimateNode, QuoteRouteEstimateRequest, QuoteRouteEstimateResponse
from app.modules.system.runtime_config import RuntimeConfigService


def _to_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _node_snapshot(node: TransportNode | None) -> QuoteRouteEstimateNode | None:
    if node is None:
        return None
    return QuoteRouteEstimateNode(
        id=int(node.id),
        code=node.code,
        name=node.name,
        node_type_code=node.node_type_code,
        city_code=node.city_code,
        city_name=getattr(node, "city_name", None),
        longitude=_to_optional_float(node.longitude),
        latitude=_to_optional_float(node.latitude),
    )


def _line_string_points(geometry: dict | None) -> list[tuple[float, float]]:
    if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
        return []
    points: list[tuple[float, float]] = []
    for item in geometry.get("coordinates") or []:
        if not isinstance(item, list | tuple) or len(item) < 2:
            continue
        lon = _to_optional_float(item[0])
        lat = _to_optional_float(item[1])
        if lon is None or lat is None:
            continue
        if -180 <= lon <= 180 and -90 <= lat <= 90:
            point = (lon, lat)
            if not points or points[-1] != point:
                points.append(point)
    return points


def _haversine_distance_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    radius_km = 6371.0088
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _line_length_km(points: list[tuple[float, float]]) -> float | None:
    if len(points) < 2:
        return None
    distance = 0.0
    for index in range(len(points) - 1):
        start = points[index]
        end = points[index + 1]
        distance += _haversine_distance_km(start[0], start[1], end[0], end[1])
    return round(distance, 3)


def _safe_reason(exc: Exception) -> str:
    if isinstance(exc, AppException):
        text = exc.message
    else:
        text = str(exc)
    return (text or "AMMS 航线测算失败").replace("HiFleet", "AMMS").replace("HIFLEET", "AMMS").replace("\r", " ").replace("\n", " ").strip()[:180]


class QuoteRouteEstimateService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.runtime_config = RuntimeConfigService(db)

    async def _get_node(self, node_id: int) -> TransportNode | None:
        return await self.db.scalar(
            select(TransportNode).where(TransportNode.id == node_id, TransportNode.deleted_at.is_(None))
        )

    async def _category_codes(self, node_id: int) -> set[str]:
        rows = (
            await self.db.execute(
                select(TransportNodeBusinessCategory.business_category_code).where(
                    TransportNodeBusinessCategory.node_id == node_id
                )
            )
        ).scalars().all()
        return {str(row) for row in rows}

    def _route_client(self) -> HifleetRouteClient:
        return HifleetRouteClient(runtime_config=self.runtime_config)

    @staticmethod
    def _node_validation_reasons(node: TransportNode | None, *, role: str) -> list[str]:
        if node is None:
            return [f"{role}节点不存在"]
        reasons: list[str] = []
        if node.status != 1:
            reasons.append(f"{role}节点未启用")
        if _to_optional_float(node.longitude) is None or _to_optional_float(node.latitude) is None:
            reasons.append(f"{role}节点缺少经纬度")
        return reasons

    @staticmethod
    def _response(
        status_code: str,
        origin_node: TransportNode | None,
        destination_node: TransportNode | None,
        *,
        reasons: list[str] | None = None,
        distance_km: float | None = None,
        geometry_json: dict | None = None,
        geometry_source: str | None = None,
        provider_trace_id: str | None = None,
        point_count: int | None = None,
    ) -> QuoteRouteEstimateResponse:
        generated_at = datetime.now(UTC)
        query = {
            "origin_node_id": getattr(origin_node, "id", None),
            "destination_node_id": getattr(destination_node, "id", None),
        }
        return QuoteRouteEstimateResponse(
            status_code=status_code,
            origin_node=_node_snapshot(origin_node),
            destination_node=_node_snapshot(destination_node),
            distance_km=round(distance_km, 3) if distance_km is not None else None,
            geometry_json=geometry_json,
            geometry_source=geometry_source or "AMMS",
            provider_trace_id=provider_trace_id,
            point_count=point_count,
            not_computable_reasons=reasons or [],
            map_state=build_map_state(
                status_code,
                provider_code="AMMS",
                cache_status="GENERATED" if status_code == "READY" else None,
                last_updated_at=generated_at,
                reasons=reasons or [],
                retry_action=default_retry_action(status_code, target_route="/analysis/quote-simulator", query=query),
            ),
            generated_at=generated_at,
        )

    async def estimate_route(self, payload: QuoteRouteEstimateRequest) -> QuoteRouteEstimateResponse:
        origin = await self._get_node(payload.origin_node_id)
        destination = await self._get_node(payload.destination_node_id)
        reasons: list[str] = []
        reasons.extend(self._node_validation_reasons(origin, role="装货"))
        reasons.extend(self._node_validation_reasons(destination, role="卸货"))

        if origin is not None and destination is not None and origin.id == destination.id:
            reasons.append("装货节点和卸货节点不能相同")

        if origin is not None:
            origin_categories = await self._category_codes(origin.id)
            if "LOADING" not in origin_categories:
                reasons.append("装货节点未配置装货业务类别")
        if destination is not None:
            destination_categories = await self._category_codes(destination.id)
            if "UNLOADING" not in destination_categories:
                reasons.append("卸货节点未配置卸货业务类别")

        if reasons:
            return self._response("NOT_COMPUTABLE", origin, destination, reasons=reasons)

        assert origin is not None and destination is not None
        origin_lon = float(origin.longitude)
        origin_lat = float(origin.latitude)
        destination_lon = float(destination.longitude)
        destination_lat = float(destination.latitude)

        try:
            result = await self._route_client().generate(
                RouteGeometryQuery(
                    origin_lon=origin_lon,
                    origin_lat=origin_lat,
                    dest_lon=destination_lon,
                    dest_lat=destination_lat,
                    transport_mode="WATER",
                    segment_type="QUOTE_SIMULATOR",
                )
            )
        except Exception as exc:  # noqa: BLE001
            reason = _safe_reason(exc)
            status = "NOT_COMPUTABLE" if "未配置" in reason else "FAILED"
            return self._response(status, origin, destination, reasons=[reason])

        points = _line_string_points(result.geometry)
        distance_km = result.distance_km if result.distance_km is not None else _line_length_km(points)
        if len(points) < 2 or distance_km is None:
            return self._response("FAILED", origin, destination, reasons=["AMMS 返回轨迹为空或无法计算距离"])

        return self._response(
            "READY",
            origin,
            destination,
            distance_km=distance_km,
            geometry_json=result.geometry,
            geometry_source="AMMS",
            provider_trace_id=result.provider_trace_id,
            point_count=len(points),
        )
