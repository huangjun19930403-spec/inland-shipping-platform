"""AMMS 水路路径客户端。"""
from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any, Optional

import httpx

from app.core.config import settings
from app.core.exceptions import InternalError, ValidationError
from app.core.status_enums import RouteGeometrySource, RouteGeometryStatus
from app.integrations.config_keys import (
    AMAP_ROUTE_GEOMETRY_TIMEOUT_SECONDS,
    HIFLEET_BASE_URL,
    HIFLEET_CONFIG_PROFILE,
    HIFLEET_ROUTE_URL,
    HIFLEET_TIMEOUT_SECONDS,
)
from app.integrations.hifleet.session_manager import HifleetSessionManager
from app.integrations.http.route_geometry_types import RouteGeometryQuery, RouteGeometryResult

if TYPE_CHECKING:
    from app.modules.system.runtime_config import RuntimeConfigService

_DEFAULT_SESSION_MANAGER = HifleetSessionManager()


class HifleetRouteClient:
    provider_name = "HIFLEET"

    def __init__(
        self,
        *,
        runtime_config: RuntimeConfigService | None = None,
        session_manager: Optional[HifleetSessionManager] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        max_retries: int = 1,
        concurrency_limit: int = 2,
    ) -> None:
        self._runtime_config = runtime_config
        self._transport = transport
        if session_manager is not None:
            self._session = session_manager
        elif runtime_config is not None:
            self._session = HifleetSessionManager(transport=transport, runtime_config=runtime_config)
        elif transport is not None:
            self._session = HifleetSessionManager(transport=transport)
        else:
            self._session = _DEFAULT_SESSION_MANAGER
        self._max_retries = max(0, max_retries)
        self._semaphore = asyncio.Semaphore(max(1, concurrency_limit))

    async def _route_url(self) -> str:
        if self._runtime_config is not None:
            route_url = (
                await self._runtime_config.get_value(
                    HIFLEET_ROUTE_URL,
                    settings.HIFLEET_ROUTE_URL or "",
                    profile_code=HIFLEET_CONFIG_PROFILE,
                )
                or ""
            ).strip()
            base_url = (
                await self._runtime_config.get_value(
                    HIFLEET_BASE_URL,
                    settings.HIFLEET_BASE_URL or "",
                    profile_code=HIFLEET_CONFIG_PROFILE,
                )
                or ""
            ).strip().rstrip("/")
        else:
            route_url = (settings.HIFLEET_ROUTE_URL or "").strip()
            base_url = (settings.HIFLEET_BASE_URL or "").strip().rstrip("/")

        if not route_url:
            raise ValidationError("未配置 AMMS 路径接口地址")
        if route_url.startswith("http://") or route_url.startswith("https://"):
            return route_url
        return f"{base_url}/{route_url.lstrip('/')}"

    async def _timeout(self) -> float:
        default_timeout = float(settings.HIFLEET_TIMEOUT_SECONDS or settings.ROUTE_GEOMETRY_TIMEOUT_SECONDS or 8.0)
        if self._runtime_config is not None:
            timeout = await self._runtime_config.get_float(
                HIFLEET_TIMEOUT_SECONDS,
                default_timeout,
                profile_code=HIFLEET_CONFIG_PROFILE,
            )
            if timeout > 0:
                return float(timeout)
            fallback_timeout = await self._runtime_config.get_float(
                AMAP_ROUTE_GEOMETRY_TIMEOUT_SECONDS,
                float(settings.ROUTE_GEOMETRY_TIMEOUT_SECONDS or 8.0),
            )
            return float(fallback_timeout)
        return float(settings.HIFLEET_TIMEOUT_SECONDS or settings.ROUTE_GEOMETRY_TIMEOUT_SECONDS or 8.0)

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _extract_point_from_dict(cls, item: dict[str, Any]) -> Optional[list[float]]:
        for lon_key, lat_key in (
            ("lon", "lat"),
            ("lng", "lat"),
            ("longitude", "latitude"),
            ("x", "y"),
        ):
            lon = cls._to_float(item.get(lon_key))
            lat = cls._to_float(item.get(lat_key))
            if lon is not None and lat is not None:
                return [lon, lat]

        for point_key in ("point", "coord", "location", "position"):
            raw = item.get(point_key)
            if isinstance(raw, str) and "," in raw:
                try:
                    lon_text, lat_text = raw.split(",", 1)
                    return [float(lon_text.strip()), float(lat_text.strip())]
                except ValueError:
                    continue
        return None

    @classmethod
    def _extract_points_from_text(cls, value: str) -> list[list[float]]:
        text = value.strip()
        if "," not in text:
            return []
        points: list[list[float]] = []
        for pair in re.split(r"[;|]", text):
            if "," not in pair:
                continue
            lon_text, lat_text, *_ = pair.split(",")
            lon = cls._to_float(lon_text.strip())
            lat = cls._to_float(lat_text.strip())
            if lon is not None and lat is not None:
                points.append([lon, lat])
        return points

    @classmethod
    def _extract_points(cls, payload: Any) -> list[list[float]]:
        points: list[list[float]] = []

        def walk(item: Any) -> None:
            if isinstance(item, dict):
                point = cls._extract_point_from_dict(item)
                if point:
                    points.append(point)
                for value in item.values():
                    if isinstance(value, dict | list | str):
                        walk(value)
            elif isinstance(item, list):
                if len(item) >= 2 and cls._to_float(item[0]) is not None and cls._to_float(item[1]) is not None:
                    points.append([float(item[0]), float(item[1])])
                else:
                    for sub in item:
                        walk(sub)
            elif isinstance(item, str):
                points.extend(cls._extract_points_from_text(item))

        walk(payload)

        deduped: list[list[float]] = []
        for lon, lat in points:
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                continue
            if not deduped or deduped[-1] != [lon, lat]:
                deduped.append([lon, lat])
        return deduped

    @staticmethod
    def _extract_trace_id(payload: dict[str, Any]) -> Optional[str]:
        for key in ("routeId", "route_id", "traceId", "trace_id", "id"):
            value = payload.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("routeId", "route_id", "traceId", "trace_id", "id"):
                value = data.get(key)
                if value is not None and str(value).strip():
                    return str(value).strip()
        return None

    @classmethod
    def _find_numeric(cls, payload: Any, keys: set[str]) -> float | None:
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key in keys:
                    parsed = cls._to_float(value)
                    if parsed is not None:
                        return parsed
                nested = cls._find_numeric(value, keys)
                if nested is not None:
                    return nested
        elif isinstance(payload, list):
            for item in payload:
                nested = cls._find_numeric(item, keys)
                if nested is not None:
                    return nested
        return None

    @classmethod
    def _extract_distance_km(cls, payload: dict[str, Any]) -> float | None:
        distance_nm = cls._find_numeric(payload, {"distanceNm", "distance_nm", "nm", "nmi"})
        if distance_nm is not None:
            return round(distance_nm * 1.852, 3)
        distance_km = cls._find_numeric(payload, {"distanceKm", "distance_km", "kilometers", "km"})
        if distance_km is not None:
            return round(distance_km, 3)
        distance_m = cls._find_numeric(payload, {"distanceM", "distance_m", "meters", "distance"})
        if distance_m is not None:
            return round(distance_m / 1000, 3)
        return None

    @classmethod
    def _extract_duration_hour(cls, payload: dict[str, Any]) -> float | None:
        duration_hour = cls._find_numeric(payload, {"durationHour", "duration_hour", "hours", "hour"})
        if duration_hour is not None:
            return round(duration_hour, 3)
        duration_seconds = cls._find_numeric(payload, {"durationSeconds", "duration_seconds", "seconds"})
        if duration_seconds is not None:
            return round(duration_seconds / 3600, 3)
        duration_minutes = cls._find_numeric(payload, {"durationMinutes", "duration_minutes", "minutes", "duration"})
        if duration_minutes is not None:
            return round(duration_minutes / 60, 3)
        return None

    async def _call_route_api(self, query: RouteGeometryQuery) -> dict[str, Any]:
        client = await self._session._client()
        route_url = await self._route_url()
        timeout = await self._timeout()
        headers = await self._session._default_headers()
        version = self._session._version()
        response = await client.post(
            route_url,
            data={
                "start": f"{query.origin_lon},{query.origin_lat}",
                "end": f"{query.dest_lon},{query.dest_lat}",
                "arcticroute": "0",
            },
            params={"_v": version},
            headers=headers,
            timeout=timeout,
        )
        if response.status_code >= 400:
            raise InternalError(
                f"AMMS 路径请求失败: status={response.status_code}, body={(response.text or '')[:240]}"
            )
        return self._session._decode_response_json(response, "getNewRoute")

    async def _invalidate_session(self) -> None:
        invalidate_async = getattr(self._session, "invalidate_async", None)
        if callable(invalidate_async):
            await invalidate_async()
            return
        self._session.invalidate()

    def _is_auth_expired_error(self, exc: Exception) -> bool:
        checker = getattr(self._session, "is_auth_expired_error", None)
        if callable(checker):
            return bool(checker(exc))
        return "登录" in str(exc)

    async def generate(self, query: RouteGeometryQuery) -> RouteGeometryResult:
        async with self._semaphore:
            await self._session.ensure_session()
            last_error: Exception | None = None
            for attempt in range(self._max_retries + 1):
                try:
                    payload = await self._call_route_api(query)
                    if str(payload.get("status")).lower() != "success":
                        msg = payload.get("msg") or payload.get("message") or payload
                        raise ValidationError(f"AMMS getNewRoute 返回失败: {msg}")

                    points = self._extract_points(payload.get("waypoints") or payload)
                    if len(points) < 2:
                        raise ValidationError("AMMS getNewRoute 返回空轨迹或点位不足")

                    return RouteGeometryResult(
                        geometry={"type": "LineString", "coordinates": points},
                        source=RouteGeometrySource.HIFLEET.value,
                        provider=self.provider_name,
                        provider_trace_id=self._extract_trace_id(payload),
                        status=RouteGeometryStatus.READY.value,
                        distance_km=self._extract_distance_km(payload),
                        estimated_duration_hour=self._extract_duration_hour(payload),
                        raw_summary={
                            "status": payload.get("status"),
                            "message": payload.get("msg") or payload.get("message"),
                            "point_count": len(points),
                        },
                    )
                except ValidationError as exc:
                    if self._is_auth_expired_error(exc) and attempt < self._max_retries:
                        await self._invalidate_session()
                        await self._session.ensure_session(force_login=True)
                        last_error = exc
                        continue
                    raise
                except (httpx.TimeoutException, httpx.NetworkError):
                    raise
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    if attempt < self._max_retries:
                        await self._invalidate_session()
                        await self._session.ensure_session(force_login=True)
                        continue
                    raise
            raise InternalError(f"AMMS getNewRoute 失败: {last_error}")
