"""AMMS 水路路径客户端。"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.core.exceptions import InternalError, ValidationError
from app.core.status_enums import RouteGeometrySource, RouteGeometryStatus
from app.integrations.hifleet.session_manager import HifleetSessionManager
from app.integrations.http.route_geometry_types import RouteGeometryQuery, RouteGeometryResult

_DEFAULT_SESSION_MANAGER = HifleetSessionManager()


class HifleetRouteClient:
    provider_name = "HIFLEET"

    def __init__(
        self,
        *,
        session_manager: Optional[HifleetSessionManager] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        max_retries: int = 1,
        concurrency_limit: int = 2,
    ) -> None:
        self._transport = transport
        self._session = session_manager or (
            HifleetSessionManager(transport=transport) if transport is not None else _DEFAULT_SESSION_MANAGER
        )
        self._max_retries = max(0, max_retries)
        self._semaphore = asyncio.Semaphore(max(1, concurrency_limit))

    @staticmethod
    def _route_url() -> str:
        route_url = (settings.HIFLEET_ROUTE_URL or "").strip()
        if not route_url:
            raise ValidationError("未配置 AMMS 路径接口地址")
        if route_url.startswith("http://") or route_url.startswith("https://"):
            return route_url
        base = (settings.HIFLEET_BASE_URL or "").strip().rstrip("/")
        return f"{base}/{route_url.lstrip('/')}"

    @staticmethod
    def _timeout() -> float:
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
    def _extract_points(cls, payload: Any) -> list[list[float]]:
        points: list[list[float]] = []

        def walk(item: Any) -> None:
            if isinstance(item, dict):
                point = cls._extract_point_from_dict(item)
                if point:
                    points.append(point)
                for key in ("waypoints", "points", "path", "route", "data", "list"):
                    if key in item:
                        walk(item.get(key))
            elif isinstance(item, list):
                if len(item) >= 2 and cls._to_float(item[0]) is not None and cls._to_float(item[1]) is not None:
                    points.append([float(item[0]), float(item[1])])
                else:
                    for sub in item:
                        walk(sub)

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

    async def _call_route_api(self, query: RouteGeometryQuery) -> dict[str, Any]:
        client = await self._session._client()
        response = await client.post(
            self._route_url(),
            data={
                "start": f"{query.origin_lon},{query.origin_lat}",
                "end": f"{query.dest_lon},{query.dest_lat}",
                "arcticroute": "0",
            },
            params={"_v": self._session._version()},
            headers=self._session._default_headers(),
            timeout=self._timeout(),
        )
        if response.status_code >= 400:
            raise InternalError(
                f"AMMS 路径请求失败: status={response.status_code}, body={(response.text or '')[:240]}"
            )
        return self._session._decode_response_json(response, "getNewRoute")

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
                    )
                except ValidationError as exc:
                    message = str(exc)
                    if "登录" in message and attempt < self._max_retries:
                        self._session.invalidate()
                        await self._session.ensure_session(force_login=True)
                        last_error = exc
                        continue
                    raise
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    if attempt < self._max_retries:
                        self._session.invalidate()
                        await self._session.ensure_session(force_login=True)
                        continue
                    raise
            raise InternalError(f"AMMS getNewRoute 失败: {last_error}")
