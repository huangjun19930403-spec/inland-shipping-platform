"""HiFleet route geometry cache for navigation and route-plan generation."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.integrations.hifleet.client import HifleetRouteClient
from app.integrations.http.route_geometry_types import RouteGeometryQuery, RouteGeometryResult
from app.models.navigation import NavigationHifleetRouteCache


class HifleetRouteCacheService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        runtime_config=None,
        route_client=None,
    ) -> None:
        self.session = session
        self.runtime_config = runtime_config
        self.route_client = route_client

    async def get_or_generate(
        self,
        query: RouteGeometryQuery,
        *,
        origin_ref_type_code: str | None = None,
        origin_ref_id: int | None = None,
        origin_name: str | None = None,
        destination_ref_type_code: str | None = None,
        destination_ref_id: int | None = None,
        destination_name: str | None = None,
    ) -> RouteGeometryResult:
        keys = _route_keys(
            query,
            origin_ref_type_code=origin_ref_type_code,
            origin_ref_id=origin_ref_id,
            destination_ref_type_code=destination_ref_type_code,
            destination_ref_id=destination_ref_id,
        )
        for route_key in keys["direct_route_keys"]:
            direct = await self._get_ready_cache(route_key)
            if direct is not None:
                return await self._cache_result(direct, reversed_geometry=False)

        for route_key in keys["reverse_route_keys"]:
            reverse = await self._get_ready_cache(route_key)
            if reverse is not None:
                return await self._cache_result(reverse, reversed_geometry=True)

        direct_by_coordinates = await self._get_ready_cache_by_coordinates(query, reversed_geometry=False)
        if direct_by_coordinates is not None:
            return await self._cache_result(direct_by_coordinates, reversed_geometry=False)

        reverse_by_coordinates = await self._get_ready_cache_by_coordinates(query, reversed_geometry=True)
        if reverse_by_coordinates is not None:
            return await self._cache_result(reverse_by_coordinates, reversed_geometry=True)

        client = self.route_client or HifleetRouteClient(runtime_config=self.runtime_config)
        result = await client.generate(query)
        geometry = _valid_line_string(result.geometry)
        points = _line_string_points(geometry)
        if len(points) < 3:
            raise ValidationError("HiFleet 返回轨迹点不足，拒绝写入本地轨迹缓存")
        now = datetime.utcnow()
        raw_summary = result.raw_summary if isinstance(result.raw_summary, dict) else {}
        cache_row = NavigationHifleetRouteCache(
            route_key=keys["route_key"],
            normalized_pair_key=keys["normalized_pair_key"],
            provider_code="HIFLEET",
            transport_mode_code=str(query.transport_mode or "WATER").upper(),
            origin_ref_type_code=origin_ref_type_code,
            origin_ref_id=origin_ref_id,
            origin_name=origin_name,
            origin_lng=query.origin_lon,
            origin_lat=query.origin_lat,
            destination_ref_type_code=destination_ref_type_code,
            destination_ref_id=destination_ref_id,
            destination_name=destination_name,
            destination_lng=query.dest_lon,
            destination_lat=query.dest_lat,
            geometry_json=geometry,
            geometry_hash=_geometry_hash(geometry),
            distance_km=result.distance_km if result.distance_km is not None else float(_line_distance_km(geometry)),
            estimated_duration_hour=result.estimated_duration_hour,
            point_count=len(points),
            provider_trace_id=result.provider_trace_id,
            status_code="READY",
            raw_summary_json=raw_summary,
            generated_at=now,
            last_used_at=now,
            use_count=1,
        )
        self.session.add(cache_row)
        await self.session.flush()
        return RouteGeometryResult(
            geometry=geometry,
            source="hifleet",
            provider="HIFLEET",
            provider_trace_id=result.provider_trace_id,
            status="ready",
            distance_km=float(cache_row.distance_km) if cache_row.distance_km is not None else result.distance_km,
            estimated_duration_hour=result.estimated_duration_hour,
            raw_summary={
                **raw_summary,
                "cache_hit": False,
                "cache_direction": "FORWARD",
                "hifleet_cache_id": cache_row.id,
                "route_key": cache_row.route_key,
                "normalized_pair_key": cache_row.normalized_pair_key,
                "point_count": len(points),
            },
        )

    async def _get_ready_cache(self, route_key: str) -> NavigationHifleetRouteCache | None:
        return await self.session.scalar(
            select(NavigationHifleetRouteCache).where(
                NavigationHifleetRouteCache.route_key == route_key,
                NavigationHifleetRouteCache.status_code == "READY",
                NavigationHifleetRouteCache.geometry_json.is_not(None),
            )
        )

    async def _get_ready_cache_by_coordinates(
        self,
        query: RouteGeometryQuery,
        *,
        reversed_geometry: bool,
    ) -> NavigationHifleetRouteCache | None:
        mode = str(query.transport_mode or "WATER").upper()
        origin_lng = query.dest_lon if reversed_geometry else query.origin_lon
        origin_lat = query.dest_lat if reversed_geometry else query.origin_lat
        dest_lng = query.origin_lon if reversed_geometry else query.dest_lon
        dest_lat = query.origin_lat if reversed_geometry else query.dest_lat
        epsilon = 0.000001
        return await self.session.scalar(
            select(NavigationHifleetRouteCache)
            .where(
                NavigationHifleetRouteCache.transport_mode_code == mode,
                NavigationHifleetRouteCache.status_code == "READY",
                NavigationHifleetRouteCache.geometry_json.is_not(None),
                NavigationHifleetRouteCache.origin_lng.between(origin_lng - epsilon, origin_lng + epsilon),
                NavigationHifleetRouteCache.origin_lat.between(origin_lat - epsilon, origin_lat + epsilon),
                NavigationHifleetRouteCache.destination_lng.between(dest_lng - epsilon, dest_lng + epsilon),
                NavigationHifleetRouteCache.destination_lat.between(dest_lat - epsilon, dest_lat + epsilon),
            )
            .order_by(NavigationHifleetRouteCache.id.desc())
            .limit(1)
        )

    async def _cache_result(self, cache_row: NavigationHifleetRouteCache, *, reversed_geometry: bool) -> RouteGeometryResult:
        geometry = _valid_line_string(cache_row.geometry_json)
        if reversed_geometry:
            geometry = {"type": "LineString", "coordinates": list(reversed(geometry["coordinates"]))}
        points = _line_string_points(geometry)
        if len(points) < 3:
            raise ValidationError("本地 HiFleet 缓存轨迹点不足，拒绝返回")
        cache_row.last_used_at = datetime.utcnow()
        cache_row.use_count = int(cache_row.use_count or 0) + 1
        await self.session.flush()
        raw_summary = cache_row.raw_summary_json if isinstance(cache_row.raw_summary_json, dict) else {}
        return RouteGeometryResult(
            geometry=geometry,
            source="hifleet",
            provider="HIFLEET",
            provider_trace_id=cache_row.provider_trace_id,
            status="ready",
            distance_km=float(cache_row.distance_km) if cache_row.distance_km is not None else None,
            estimated_duration_hour=float(cache_row.estimated_duration_hour)
            if cache_row.estimated_duration_hour is not None
            else None,
            raw_summary={
                **raw_summary,
                "cache_hit": True,
                "cache_direction": "REVERSED" if reversed_geometry else "FORWARD",
                "hifleet_cache_id": cache_row.id,
                "route_key": cache_row.route_key,
                "normalized_pair_key": cache_row.normalized_pair_key,
                "point_count": len(points),
            },
        )


def _route_keys(
    query: RouteGeometryQuery,
    *,
    origin_ref_type_code: str | None,
    origin_ref_id: int | None,
    destination_ref_type_code: str | None,
    destination_ref_id: int | None,
) -> dict[str, Any]:
    coordinate_origin_key = _endpoint_key(
        query.origin_lon,
        query.origin_lat,
        ref_type_code=None,
        ref_id=None,
    )
    coordinate_destination_key = _endpoint_key(
        query.dest_lon,
        query.dest_lat,
        ref_type_code=None,
        ref_id=None,
    )
    coordinate_keys = _endpoint_route_keys(
        coordinate_origin_key,
        coordinate_destination_key,
        transport_mode=query.transport_mode,
    )
    ref_origin_key = _endpoint_key(
        query.origin_lon,
        query.origin_lat,
        ref_type_code=origin_ref_type_code,
        ref_id=origin_ref_id,
    )
    ref_destination_key = _endpoint_key(
        query.dest_lon,
        query.dest_lat,
        ref_type_code=destination_ref_type_code,
        ref_id=destination_ref_id,
    )
    ref_keys = _endpoint_route_keys(
        ref_origin_key,
        ref_destination_key,
        transport_mode=query.transport_mode,
    )
    return {
        **coordinate_keys,
        "direct_route_keys": _dedupe_strings([coordinate_keys["route_key"], ref_keys["route_key"]]),
        "reverse_route_keys": _dedupe_strings([coordinate_keys["reverse_route_key"], ref_keys["reverse_route_key"]]),
    }


def _endpoint_route_keys(
    origin_key: str,
    destination_key: str,
    *,
    transport_mode: str | None,
) -> dict[str, str]:
    mode = str(transport_mode or "WATER").upper()
    pair = "||".join(sorted([origin_key, destination_key]))
    return {
        "route_key": f"HIFLEET|{mode}|{origin_key}|{destination_key}",
        "reverse_route_key": f"HIFLEET|{mode}|{destination_key}|{origin_key}",
        "normalized_pair_key": f"HIFLEET|{mode}|{pair}",
    }


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        items.append(value)
    return items


def _endpoint_key(
    lng: float,
    lat: float,
    *,
    ref_type_code: str | None,
    ref_id: int | None,
) -> str:
    ref_type = str(ref_type_code or "").strip().upper()
    if ref_type and ref_id is not None:
        return f"{ref_type}:{int(ref_id)}"
    return f"POINT:{float(lng):.6f},{float(lat):.6f}"


def _valid_line_string(geometry: dict | None) -> dict[str, Any]:
    points = _line_string_points(geometry)
    if len(points) < 2:
        raise ValidationError("轨迹必须是至少包含两个点的 LineString")
    return {"type": "LineString", "coordinates": points}


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


def _geometry_hash(geometry: dict[str, Any]) -> str:
    raw = json.dumps(geometry, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _line_distance_km(geometry: dict | None) -> Decimal:
    points = _line_string_points(geometry)
    if len(points) < 2:
        return Decimal("0")
    distance = sum(_haversine_km(points[index - 1], points[index]) for index in range(1, len(points)))
    return Decimal(str(round(distance, 4)))


def _haversine_km(a: list[float], b: list[float]) -> float:
    lon1, lat1 = math.radians(float(a[0])), math.radians(float(a[1]))
    lon2, lat2 = math.radians(float(b[0])), math.radians(float(b[1]))
    d_lon = lon2 - lon1
    d_lat = lat2 - lat1
    value = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
    return 6371.0088 * 2 * math.atan2(math.sqrt(value), math.sqrt(max(0.0, 1 - value)))
