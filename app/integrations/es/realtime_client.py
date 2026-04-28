"""统一实时 ES 客户端。"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Optional

import httpx

from app.core.config import settings
from app.core.exceptions import InternalError
from app.integrations.config_keys import (
    ES_R_HOST,
    ES_R_INDEX,
    ES_R_PASSWORD,
    ES_R_PORT,
    ES_R_SCHEME,
    ES_R_USER,
    ES_REALTIME_CONFIG_PROFILE,
    ES_TIMEOUT_SECONDS,
)
from app.integrations.http import get_shared_http_client

if TYPE_CHECKING:
    from app.modules.system.runtime_config import RuntimeConfigService


class RealtimeEsClient:
    def __init__(
        self,
        *,
        runtime_config: RuntimeConfigService | None = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        max_retries: int = 1,
        retry_backoff_seconds: float = 0.4,
        concurrency_limit: int = 6,
    ) -> None:
        self._runtime_config = runtime_config
        self._transport = transport
        self._max_retries = max(0, max_retries)
        self._retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self._semaphore = asyncio.Semaphore(max(1, concurrency_limit))

    @property
    def index_name(self) -> str:
        return settings.ES_R_INDEX

    async def _index_name(self) -> str:
        if self._runtime_config is not None:
            value = await self._runtime_config.get_value(
                ES_R_INDEX,
                settings.ES_R_INDEX or "",
                profile_code=ES_REALTIME_CONFIG_PROFILE,
            )
            return (value or "").strip()
        return (settings.ES_R_INDEX or "").strip()

    async def _scheme(self) -> str:
        if self._runtime_config is not None:
            value = await self._runtime_config.get_value(
                ES_R_SCHEME,
                settings.ES_R_SCHEME or "http",
                profile_code=ES_REALTIME_CONFIG_PROFILE,
            )
            return (value or "http").strip() or "http"
        return (settings.ES_R_SCHEME or "http").strip() or "http"

    async def _host(self) -> str:
        if self._runtime_config is not None:
            value = await self._runtime_config.get_value(
                ES_R_HOST,
                settings.ES_R_HOST or "",
                profile_code=ES_REALTIME_CONFIG_PROFILE,
            )
            return (value or "").strip()
        return (settings.ES_R_HOST or "").strip()

    async def _port(self) -> int:
        default_port = int(settings.ES_R_PORT or 80)
        if self._runtime_config is not None:
            value = await self._runtime_config.get_int(
                ES_R_PORT,
                default_port,
                profile_code=ES_REALTIME_CONFIG_PROFILE,
            )
            return int(value)
        return int(settings.ES_R_PORT or 80)

    async def _user(self) -> str:
        if self._runtime_config is not None:
            value = await self._runtime_config.get_value(
                ES_R_USER,
                settings.ES_R_USER or "",
                profile_code=ES_REALTIME_CONFIG_PROFILE,
            )
            return (value or "").strip()
        return (settings.ES_R_USER or "").strip()

    async def _password(self) -> str:
        if self._runtime_config is not None:
            value = await self._runtime_config.get_value(
                ES_R_PASSWORD,
                settings.ES_R_PASSWORD or "",
                profile_code=ES_REALTIME_CONFIG_PROFILE,
            )
            return value or ""
        return settings.ES_R_PASSWORD or ""

    async def _timeout(self) -> float:
        default_timeout = float(settings.ES_TIMEOUT_SECONDS or 10.0)
        if self._runtime_config is not None:
            timeout_value = await self._runtime_config.get_float(
                ES_TIMEOUT_SECONDS,
                default_timeout,
            )
            return float(timeout_value if timeout_value > 0 else default_timeout)
        return float(settings.ES_TIMEOUT_SECONDS or 10.0)

    async def _auth(self) -> Optional[tuple[str, str]]:
        user = await self._user()
        password = await self._password()
        return (user, password) if user else None

    async def _check_config(self) -> None:
        host = await self._host()
        if not host:
            raise InternalError("Realtime ES host 未配置（请设置 ES_R_HOST）")

    async def _base_url(self) -> str:
        scheme = await self._scheme()
        host = await self._host()
        port = await self._port()
        return f"{scheme}://{host}:{port}"

    async def _client(self) -> httpx.AsyncClient:
        return await get_shared_http_client("es-realtime", transport=self._transport)

    async def _request_json(self, method: str, url: str, **kwargs) -> dict[str, Any]:
        client = await self._client()
        last_error: Exception | None = None
        timeout = await self._timeout()
        async with self._semaphore:
            for attempt in range(self._max_retries + 1):
                try:
                    response = await client.request(
                        method,
                        url,
                        timeout=timeout,
                        **kwargs,
                    )
                    if response.status_code >= 400:
                        raise InternalError(
                            f"Realtime ES 请求失败: status={response.status_code}, body={(response.text or '')[:240]}"
                        )
                    return response.json()
                except (httpx.HTTPError, ValueError, InternalError) as exc:
                    last_error = exc
                    if attempt >= self._max_retries:
                        raise InternalError(f"Realtime ES 请求失败: {exc}") from exc
                    await asyncio.sleep(self._retry_backoff_seconds * (attempt + 1))
        raise InternalError(f"Realtime ES 请求失败: {last_error}")

    async def search(self, index: str, query_body: dict[str, Any]) -> dict[str, Any]:
        await self._check_config()
        base_url = await self._base_url()
        auth = await self._auth()
        return await self._request_json(
            "POST",
            f"{base_url}/{index}/_search",
            json=query_body,
            auth=auth,
        )

    async def ping(self) -> dict[str, Any]:
        await self._check_config()
        base_url = await self._base_url()
        auth = await self._auth()
        host = await self._host()
        port = await self._port()
        index_name = await self._index_name()
        payload = await self._request_json(
            "GET",
            base_url,
            auth=auth,
        )
        return {
            "host": host,
            "port": port,
            "index": index_name,
            "cluster": payload.get("cluster_name") if isinstance(payload, dict) else None,
            "status": "ok",
        }
