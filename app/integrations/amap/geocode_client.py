"""高德逆地理编码集成客户端。"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import httpx

from app.core.config import settings
from app.core.exceptions import InternalError, ValidationError
from app.integrations.http import get_shared_http_client

logger = logging.getLogger(__name__)


@dataclass
class ReverseGeocodeResult:
    longitude: float
    latitude: float
    formatted_address: Optional[str]
    province: Optional[str]
    city: Optional[str]
    district: Optional[str]
    adcode: Optional[str]
    source: str
    resolved_at: datetime
    status: str
    raw_payload: Optional[dict] = None


class AmapGeocodeClient:
    """统一封装高德 WebService 逆地理编码。"""

    def __init__(
        self,
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.4,
    ) -> None:
        self._transport = transport
        self._max_retries = max(0, max_retries)
        self._retry_backoff_seconds = max(0.0, retry_backoff_seconds)

    async def _client(self) -> httpx.AsyncClient:
        return await get_shared_http_client(
            "amap-webservice",
            transport=self._transport,
        )

    @staticmethod
    def _key() -> str:
        return (settings.ROUTE_AMAP_WEB_API_KEY or "").strip()

    @staticmethod
    def _timeout() -> float:
        return 8.0

    @staticmethod
    def _extract_text(value: object) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    async def reverse_geocode(self, *, longitude: float, latitude: float) -> ReverseGeocodeResult:
        key = self._key()
        if not key:
            raise ValidationError("未配置高德 Web 服务 Key，无法进行逆地理编码")

        url = "https://restapi.amap.com/v3/geocode/regeo"
        params = {
            "key": key,
            "location": f"{longitude},{latitude}",
            "extensions": "base",
        }
        client = await self._client()
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
                    raise InternalError(f"高德逆地理编码请求失败: {exc}") from exc
                await asyncio.sleep(self._retry_backoff_seconds * (attempt + 1))
        else:
            raise InternalError(f"高德逆地理编码请求失败: {last_error}")

        if str(payload.get("status")) != "1":
            info = payload.get("info") or payload.get("infocode") or "unknown"
            raise ValidationError(f"高德逆地理编码返回失败: {info}")

        regeo = payload.get("regeocode") or {}
        component = regeo.get("addressComponent") or {}
        city = component.get("city")
        if isinstance(city, list):
            city = city[0] if city else None
        formatted_address = self._extract_text(regeo.get("formatted_address"))
        if not formatted_address:
            parts = [
                self._extract_text(component.get("province")),
                self._extract_text(city),
                self._extract_text(component.get("district")),
                self._extract_text(component.get("township")),
            ]
            formatted_address = "".join(part for part in parts if part) or None

        return ReverseGeocodeResult(
            longitude=longitude,
            latitude=latitude,
            formatted_address=formatted_address,
            province=self._extract_text(component.get("province")),
            city=self._extract_text(city) or self._extract_text(component.get("province")),
            district=self._extract_text(component.get("district")),
            adcode=self._extract_text(component.get("adcode")),
            source="AMAP_REVERSE_GEOCODE",
            resolved_at=datetime.utcnow(),
            status="SUCCESS",
            raw_payload=payload,
        )
