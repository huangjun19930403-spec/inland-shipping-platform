"""统一外部 HTTP client 工厂。"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_LIMITS = httpx.Limits(
    max_connections=32,
    max_keepalive_connections=16,
    keepalive_expiry=30.0,
)
_DEFAULT_TIMEOUT = httpx.Timeout(timeout=None)
_DEFAULT_HEADERS = {
    "User-Agent": "InlandShippingPlatform/2.0 ExternalIntegrationLayer",
}

_client_lock = asyncio.Lock()
_shared_clients: dict[tuple[int, int, str], httpx.AsyncClient] = {}


def _client_key(name: str) -> tuple[int, int, str]:
    loop = asyncio.get_running_loop()
    return (os.getpid(), id(loop), name)


async def get_shared_http_client(
    name: str,
    *,
    follow_redirects: bool = False,
    transport: Optional[httpx.AsyncBaseTransport] = None,
    headers: Optional[dict[str, str]] = None,
) -> httpx.AsyncClient:
    """返回统一长生命周期 AsyncClient。

    - 生产路径：按 name 复用单例 client
    - 测试路径：传入 transport 时返回独立 client，避免污染共享池
    """

    if transport is not None:
        return httpx.AsyncClient(
            timeout=_DEFAULT_TIMEOUT,
            follow_redirects=follow_redirects,
            limits=_DEFAULT_LIMITS,
            headers={**_DEFAULT_HEADERS, **(headers or {})},
            transport=transport,
        )

    key = _client_key(name)
    existing = _shared_clients.get(key)
    if existing is not None:
        return existing

    async with _client_lock:
        existing = _shared_clients.get(key)
        if existing is not None:
            return existing

        client = httpx.AsyncClient(
            timeout=_DEFAULT_TIMEOUT,
            follow_redirects=follow_redirects,
            limits=_DEFAULT_LIMITS,
            headers={**_DEFAULT_HEADERS, **(headers or {})},
        )
        _shared_clients[key] = client
        logger.info("[ExternalHttpClientFactory] created shared client name=%s pid=%s loop=%s", name, key[0], key[1])
        return client


async def close_shared_http_clients() -> None:
    if not _shared_clients:
        return

    async with _client_lock:
        clients = list(_shared_clients.items())
        _shared_clients.clear()

    for key, client in clients:
        try:
            await client.aclose()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[ExternalHttpClientFactory] close client failed name=%s error=%s", key[2], exc)
