"""统一历史 ES 客户端。"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Optional

import httpx

from app.core.config import settings
from app.core.exceptions import InternalError
from app.integrations.config_keys import (
    ES_HISTORY_CONFIG_PROFILE,
    ES_HISTORY_INDEX_PREFIX,
    ES_HISTORY_TIMEOUT_SECONDS,
    ES_HOST,
    ES_PASSWORD,
    ES_PORT,
    ES_SCHEME,
    ES_TIMEOUT_SECONDS,
    ES_USER,
)
from app.integrations.http import get_shared_http_client

if TYPE_CHECKING:
    from app.modules.system.runtime_config import RuntimeConfigService


class HistoryEsClient:
    def __init__(
        self,
        *,
        runtime_config: RuntimeConfigService | None = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        max_retries: int = 1,
        retry_backoff_seconds: float = 0.4,
        concurrency_limit: int = 4,
    ) -> None:
        self._runtime_config = runtime_config
        self._transport = transport
        self._max_retries = max(0, max_retries)
        self._retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self._semaphore = asyncio.Semaphore(max(1, concurrency_limit))

    @property
    def index_prefix(self) -> str:
        return settings.ES_HISTORY_INDEX_PREFIX

    async def _index_prefix(self) -> str:
        if self._runtime_config is not None:
            value = await self._runtime_config.get_value(
                ES_HISTORY_INDEX_PREFIX,
                settings.ES_HISTORY_INDEX_PREFIX or "",
                profile_code=ES_HISTORY_CONFIG_PROFILE,
            )
            return (value or "").strip()
        return (settings.ES_HISTORY_INDEX_PREFIX or "").strip()

    async def _scheme(self) -> str:
        if self._runtime_config is not None:
            value = await self._runtime_config.get_value(
                ES_SCHEME,
                settings.ES_SCHEME or "http",
                profile_code=ES_HISTORY_CONFIG_PROFILE,
            )
            return (value or "http").strip() or "http"
        return (settings.ES_SCHEME or "http").strip() or "http"

    async def _host(self) -> str:
        if self._runtime_config is not None:
            value = await self._runtime_config.get_value(
                ES_HOST,
                settings.ES_HOST or "",
                profile_code=ES_HISTORY_CONFIG_PROFILE,
            )
            return (value or "").strip()
        return (settings.ES_HOST or "").strip()

    async def _port(self) -> int:
        default_port = int(settings.ES_PORT or 80)
        if self._runtime_config is not None:
            value = await self._runtime_config.get_int(
                ES_PORT,
                default_port,
                profile_code=ES_HISTORY_CONFIG_PROFILE,
            )
            return int(value)
        return int(settings.ES_PORT or 80)

    async def _user(self) -> str:
        if self._runtime_config is not None:
            value = await self._runtime_config.get_value(
                ES_USER,
                settings.ES_USER or "",
                profile_code=ES_HISTORY_CONFIG_PROFILE,
            )
            return (value or "").strip()
        return (settings.ES_USER or "").strip()

    async def _password(self) -> str:
        if self._runtime_config is not None:
            value = await self._runtime_config.get_value(
                ES_PASSWORD,
                settings.ES_PASSWORD or "",
                profile_code=ES_HISTORY_CONFIG_PROFILE,
            )
            return value or ""
        return settings.ES_PASSWORD or ""

    async def _timeout(self) -> float:
        default_timeout = float(settings.ES_HISTORY_TIMEOUT_SECONDS or settings.ES_TIMEOUT_SECONDS or 30.0)
        if self._runtime_config is not None:
            timeout_value = await self._runtime_config.get_float(
                ES_HISTORY_TIMEOUT_SECONDS,
                default_timeout,
                profile_code=ES_HISTORY_CONFIG_PROFILE,
            )
            if timeout_value > 0:
                return float(timeout_value)
            fallback_timeout = await self._runtime_config.get_float(
                ES_TIMEOUT_SECONDS,
                float(settings.ES_TIMEOUT_SECONDS or default_timeout),
            )
            return float(fallback_timeout if fallback_timeout > 0 else default_timeout)
        return float(settings.ES_HISTORY_TIMEOUT_SECONDS or settings.ES_TIMEOUT_SECONDS or 30.0)

    async def _auth(self) -> Optional[tuple[str, str]]:
        user = await self._user()
        password = await self._password()
        return (user, password) if user else None

    async def _check_config(self) -> None:
        host = await self._host()
        if not host:
            raise InternalError("History ES host 未配置（请设置 ES_HOST）")

    async def _base_url(self) -> str:
        scheme = await self._scheme()
        host = await self._host()
        port = await self._port()
        return f"{scheme}://{host}:{port}"

    async def _client(self) -> httpx.AsyncClient:
        return await get_shared_http_client("es-history", transport=self._transport)

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
                            f"History ES 请求失败: status={response.status_code}, body={(response.text or '')[:240]}"
                        )
                    return response.json()
                except (httpx.HTTPError, ValueError, InternalError) as exc:
                    last_error = exc
                    if attempt >= self._max_retries:
                        raise InternalError(f"History ES 请求失败: {exc}") from exc
                    await asyncio.sleep(self._retry_backoff_seconds * (attempt + 1))
        raise InternalError(f"History ES 请求失败: {last_error}")

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
        index_prefix = await self._index_prefix()
        payload = await self._request_json(
            "GET",
            base_url,
            auth=auth,
        )
        return {
            "host": host,
            "port": port,
            "index_prefix": index_prefix,
            "cluster": payload.get("cluster_name") if isinstance(payload, dict) else None,
            "status": "ok",
        }
