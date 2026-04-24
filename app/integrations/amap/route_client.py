"""高德路径服务客户端。"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.core.exceptions import InternalError, ValidationError
from app.core.status_enums import RouteGeometrySource, RouteGeometryStatus
from app.integrations.http import get_shared_http_client
from app.integrations.http.route_geometry_types import RouteGeometryQuery, RouteGeometryResult


class AmapRouteClient:
    provider_name = "AMAP"

    def __init__(
        self,
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        max_retries: int = 1,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self._transport = transport
        self._max_retries = max(0, max_retries)
        self._retry_backoff_seconds = max(0.0, retry_backoff_seconds)

    async def _client(self) -> httpx.AsyncClient:
        return await get_shared_http_client("amap-route", transport=self._transport)

    @staticmethod
    def _key() -> str:
        return (settings.ROUTE_AMAP_WEB_API_KEY or "").strip()

    @staticmethod
    def _timeout() -> float:
        return float(settings.ROUTE_GEOMETRY_TIMEOUT_SECONDS or 8.0)

    @staticmethod
    def _parse_polyline(raw_path: dict[str, Any]) -> list[list[float]]:
        points: list[list[float]] = []
        for step in raw_path.get("steps") or []:
            polyline = str(step.get("polyline") or "").strip()
            if not polyline:
                continue
            for pair in polyline.split(";"):
                if not pair:
                    continue
                lon_text, lat_text = pair.split(",")
                lon = float(lon_text)
                lat = float(lat_text)
                if not points or points[-1] != [lon, lat]:
                    points.append([lon, lat])
        return points

    async def generate(self, query: RouteGeometryQuery) -> RouteGeometryResult:
        if not self._key():
            raise ValidationError("未配置 ROUTE_AMAP_WEB_API_KEY，无法生成高德轨迹")

        client = await self._client()
        params = {
            "key": self._key(),
            "origin": f"{query.origin_lon},{query.origin_lat}",
            "destination": f"{query.dest_lon},{query.dest_lat}",
            "show_fields": "polyline",
        }
        url = "https://restapi.amap.com/v5/direction/driving"

        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await client.get(url, params=params, timeout=self._timeout())
                response.raise_for_status()
                payload = response.json()
                break
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt >= self._max_retries:
                    raise InternalError(f"高德轨迹请求失败: {exc}") from exc
                await asyncio.sleep(self._retry_backoff_seconds * (attempt + 1))
        else:
            raise InternalError(f"高德轨迹请求失败: {last_error}")

        if str(payload.get("status")) != "1":
            info = payload.get("info") or payload.get("infocode") or "unknown"
            raise ValidationError(f"高德轨迹返回失败: {info}")

        route = (payload.get("route") or {}).get("paths") or []
        if not route:
            raise ValidationError("高德轨迹返回为空")

        points = self._parse_polyline(route[0])
        if len(points) < 2:
            raise ValidationError("高德轨迹点不足，无法生成有效线路")

        return RouteGeometryResult(
            geometry={"type": "LineString", "coordinates": points},
            source=RouteGeometrySource.AMAP.value,
            provider=self.provider_name,
            provider_trace_id=None,
            status=RouteGeometryStatus.READY.value,
        )
