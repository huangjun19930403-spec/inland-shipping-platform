"""统一历史 ES 客户端。"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.core.exceptions import InternalError
from app.integrations.http import get_shared_http_client


class HistoryEsClient:
    def __init__(
        self,
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        max_retries: int = 1,
        retry_backoff_seconds: float = 0.4,
        concurrency_limit: int = 4,
    ) -> None:
        self._transport = transport
        self._max_retries = max(0, max_retries)
        self._retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self._semaphore = asyncio.Semaphore(max(1, concurrency_limit))

    @property
    def index_prefix(self) -> str:
        return settings.ES_HISTORY_INDEX_PREFIX

    def _auth(self) -> Optional[tuple[str, str]]:
        return (settings.ES_USER, settings.ES_PASSWORD or "") if (settings.ES_USER or "").strip() else None

    def _check_config(self) -> None:
        if not (settings.ES_HOST or "").strip():
            raise InternalError("History ES host 未配置（请设置 ES_HOST）")

    def _base_url(self) -> str:
        return f"{settings.ES_SCHEME or 'http'}://{settings.ES_HOST}:{settings.ES_PORT}"

    async def _client(self) -> httpx.AsyncClient:
        return await get_shared_http_client("es-history", transport=self._transport)

    async def _request_json(self, method: str, url: str, **kwargs) -> dict[str, Any]:
        client = await self._client()
        last_error: Exception | None = None
        async with self._semaphore:
            for attempt in range(self._max_retries + 1):
                try:
                    response = await client.request(
                        method,
                        url,
                        timeout=float(settings.ES_HISTORY_TIMEOUT_SECONDS or settings.ES_TIMEOUT_SECONDS or 30.0),
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
        self._check_config()
        return await self._request_json(
            "POST",
            f"{self._base_url()}/{index}/_search",
            json=query_body,
            auth=self._auth(),
        )

    async def ping(self) -> dict[str, Any]:
        self._check_config()
        payload = await self._request_json(
            "GET",
            self._base_url(),
            auth=self._auth(),
        )
        return {
            "host": settings.ES_HOST,
            "port": settings.ES_PORT,
            "index_prefix": self.index_prefix,
            "cluster": payload.get("cluster_name") if isinstance(payload, dict) else None,
            "status": "ok",
        }
