"""高德地理编码集成客户端。"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import httpx

from app.core.config import settings
from app.core.exceptions import InternalError, ValidationError
from app.integrations.config_keys import AMAP_CONFIG_PROFILE, AMAP_ROUTE_WEB_API_KEY
from app.integrations.http import get_shared_http_client

if TYPE_CHECKING:
    from app.modules.system.runtime_config import RuntimeConfigService

logger = logging.getLogger(__name__)


@dataclass
class GeocodeCandidate:
    longitude: float
    latitude: float
    formatted_address: Optional[str]
    province: Optional[str]
    city: Optional[str]
    district: Optional[str]
    adcode: Optional[str]
    level: Optional[str]
    source: str
    resolved_at: datetime
    status: str
    confidence: Optional[float] = None
    raw_payload: Optional[dict] = None


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
    level: Optional[str] = None
    confidence: Optional[float] = None
    raw_payload: Optional[dict] = None


class AmapGeocodeClient:
    """统一封装高德 WebService 地理编码。"""

    def __init__(
        self,
        *,
        runtime_config: RuntimeConfigService | None = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.4,
    ) -> None:
        self._runtime_config = runtime_config
        self._transport = transport
        self._max_retries = max(0, max_retries)
        self._retry_backoff_seconds = max(0.0, retry_backoff_seconds)

    async def _client(self) -> httpx.AsyncClient:
        return await get_shared_http_client(
            "amap-webservice",
            transport=self._transport,
        )

    async def _key(self) -> str:
        if self._runtime_config is not None:
            value = await self._runtime_config.get_value(
                AMAP_ROUTE_WEB_API_KEY,
                settings.ROUTE_AMAP_WEB_API_KEY or "",
                profile_code=AMAP_CONFIG_PROFILE,
            )
            return (value or "").strip()
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

    @staticmethod
    def _extract_city(component: dict | None) -> Optional[str]:
        if not component:
            return None
        city = component.get("city")
        if isinstance(city, list):
            city = city[0] if city else None
        return AmapGeocodeClient._extract_text(city) or AmapGeocodeClient._extract_text(component.get("province"))

    @staticmethod
    def _parse_location(value: object) -> tuple[float, float] | None:
        if value is None:
            return None
        if isinstance(value, str):
            parts = value.split(",")
            if len(parts) != 2:
                return None
            try:
                return float(parts[0]), float(parts[1])
            except ValueError:
                return None
        if isinstance(value, dict):
            lng = value.get("lng")
            lat = value.get("lat")
            try:
                return float(lng), float(lat)
            except (TypeError, ValueError):
                return None
        return None

    async def geocode(self, *, keyword: str, city_code: str | None = None) -> list[GeocodeCandidate]:
        keyword_text = keyword.strip()
        if not keyword_text:
            raise ValidationError("请输入地址或节点名称")

        key = await self._key()
        if not key:
            raise ValidationError("未配置高德 Web 服务 Key，无法进行地理编码")

        url = "https://restapi.amap.com/v3/geocode/geo"
        params = {
            "key": key,
            "address": keyword_text,
            "output": "JSON",
        }
        if city_code:
            params["city"] = city_code
            params["citylimit"] = "false"

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
                    raise InternalError(f"高德地理编码请求失败: {exc}") from exc
                await asyncio.sleep(self._retry_backoff_seconds * (attempt + 1))
        else:
            raise InternalError(f"高德地理编码请求失败: {last_error}")

        if str(payload.get("status")) != "1":
            info = payload.get("info") or payload.get("infocode") or "unknown"
            raise ValidationError(f"高德地理编码返回失败: {info}")

        candidates: list[GeocodeCandidate] = []
        for item in payload.get("geocodes") or []:
            if not isinstance(item, dict):
                continue
            point = self._parse_location(item.get("location"))
            if point is None:
                continue
            formatted_address = self._extract_text(item.get("formatted_address"))
            province = self._extract_text(item.get("province"))
            city = self._extract_city(item)
            district = self._extract_text(item.get("district"))
            if not formatted_address:
                formatted_address = "".join(part for part in [province, city, district, self._extract_text(item.get("township"))] if part) or keyword_text
            candidates.append(
                GeocodeCandidate(
                    longitude=point[0],
                    latitude=point[1],
                    formatted_address=formatted_address,
                    province=province,
                    city=city,
                    district=district,
                    adcode=self._extract_text(item.get("adcode")),
                    level=self._extract_text(item.get("level")),
                    source="AMAP_GEOCODE",
                    resolved_at=datetime.utcnow(),
                    status="SUCCESS",
                    raw_payload=item,
                )
            )

        logger.info(
            "amap geocode completed keyword=%s city_code=%s candidates=%s",
            keyword_text[:32],
            city_code,
            len(candidates),
        )
        return candidates

    async def reverse_geocode(self, *, longitude: float, latitude: float) -> ReverseGeocodeResult:
        key = await self._key()
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
        city = self._extract_city(component)
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
            city=city,
            district=self._extract_text(component.get("district")),
            adcode=self._extract_text(component.get("adcode")),
            source="AMAP_REVERSE_GEOCODE",
            resolved_at=datetime.utcnow(),
            status="SUCCESS",
            level="逆地理编码",
            raw_payload=payload,
        )
