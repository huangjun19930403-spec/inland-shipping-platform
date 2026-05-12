from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.integrations import external_session
from app.integrations.external_session import ExternalCookieSessionManager


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        _ = ex
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def setex(self, key: str, ttl: int, value: str) -> None:
        _ = ttl
        self.values[key] = value

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.values.pop(key, None)

    async def sadd(self, key: str, value: str) -> None:
        self.sets.setdefault(key, set()).add(value)

    async def srem(self, key: str, value: str) -> None:
        self.sets.setdefault(key, set()).discard(value)

    async def smembers(self, key: str) -> set[str]:
        return set(self.sets.get(key, set()))

    async def exists(self, key: str) -> bool:
        return key in self.values

    async def expire(self, key: str, ttl: int) -> None:
        _ = key, ttl


class BrokenRedis(FakeRedis):
    async def get(self, key: str) -> str | None:
        _ = key
        raise RuntimeError("redis down")

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        _ = key, value, nx, ex
        raise RuntimeError("redis down")

    async def setex(self, key: str, ttl: int, value: str) -> None:
        _ = key, ttl, value
        raise RuntimeError("redis down")

    async def sadd(self, key: str, value: str) -> None:
        _ = key, value
        raise RuntimeError("redis down")


class FakeProvider:
    provider_code = "FAKE"

    def __init__(self, *, duplicate_first: bool = False, check_ok: bool = True) -> None:
        self.duplicate_first = duplicate_first
        self.check_ok = check_ok
        self.login_count = 0
        self.logout_count = 0
        self.check_count = 0
        self.cookies: list[dict[str, Any]] = []

    async def session_key(self) -> str:
        return "same-session"

    async def enabled(self) -> bool:
        return True

    async def login(self) -> dict[str, Any]:
        self.login_count += 1
        if self.duplicate_first and self.login_count == 1:
            return {"flag": "0", "msg": "重复登录"}
        self.cookies = [{"name": "sid", "value": f"cookie-{self.login_count}", "domain": "example.test", "path": "/"}]
        return {"flag": "1"}

    async def logout(self) -> None:
        self.logout_count += 1
        self.cookies = []

    async def check(self) -> bool:
        self.check_count += 1
        return self.check_ok and bool(self.cookies)

    def is_login_success(self, payload: dict[str, Any]) -> bool:
        return payload.get("flag") == "1"

    def is_duplicate_login_error(self, payload: dict[str, Any]) -> bool:
        return "重复登录" in str(payload.get("msg") or "")

    def is_auth_expired_error(self, exc: Exception) -> bool:
        return "登录" in str(exc)

    async def export_cookies(self) -> list[dict[str, Any]]:
        return list(self.cookies)

    async def import_cookies(self, cookies: list[dict[str, Any]]) -> None:
        self.cookies = list(cookies)


@pytest.fixture(autouse=True)
def clear_external_session_state():
    external_session._LOCAL_STATES.clear()
    yield
    external_session._LOCAL_STATES.clear()


@pytest.mark.asyncio
async def test_external_cookie_session_singleflights_same_process_login() -> None:
    provider = FakeProvider()
    manager = ExternalCookieSessionManager(provider, redis_url="")

    await asyncio.gather(*(manager.ensure_session() for _ in range(8)))

    assert provider.login_count == 1
    assert provider.check_count == 0


@pytest.mark.asyncio
async def test_external_cookie_session_restores_cookies_from_redis_without_relogin() -> None:
    redis = FakeRedis()
    first_provider = FakeProvider()
    first_manager = ExternalCookieSessionManager(first_provider, redis_client=redis, process_id="p1")
    await first_manager.ensure_session()
    assert first_provider.login_count == 1

    external_session._LOCAL_STATES.clear()
    second_provider = FakeProvider()
    second_manager = ExternalCookieSessionManager(second_provider, redis_client=redis, process_id="p2")
    await second_manager.ensure_session()

    assert second_provider.login_count == 0
    assert second_provider.check_count == 1
    assert second_provider.cookies[0]["value"] == "cookie-1"


@pytest.mark.asyncio
async def test_external_cookie_session_recovers_duplicate_login_once() -> None:
    provider = FakeProvider(duplicate_first=True)
    manager = ExternalCookieSessionManager(provider, redis_client=FakeRedis())

    await manager.ensure_session()

    assert provider.login_count == 2
    assert provider.logout_count == 1


@pytest.mark.asyncio
async def test_external_cookie_session_falls_back_when_redis_unavailable() -> None:
    provider = FakeProvider()
    manager = ExternalCookieSessionManager(provider, redis_client=BrokenRedis(), lock_wait_timeout_seconds=1)

    await manager.ensure_session()

    assert provider.login_count == 1


@pytest.mark.asyncio
async def test_external_cookie_session_shutdown_skips_remote_logout_when_other_holder_active() -> None:
    redis = FakeRedis()
    provider = FakeProvider()
    manager = ExternalCookieSessionManager(provider, redis_client=redis, process_id="p1")
    await manager.ensure_session()

    await redis.sadd(await manager._holders_key(), "p2")
    await redis.setex(await manager._holder_key("p2"), 60, "active")
    await manager.logout_if_last_holder()

    assert provider.logout_count == 0


@pytest.mark.asyncio
async def test_external_cookie_session_shutdown_logs_out_when_last_holder() -> None:
    redis = FakeRedis()
    provider = FakeProvider()
    manager = ExternalCookieSessionManager(provider, redis_client=redis, process_id="p1")
    await manager.ensure_session()

    await manager.logout_if_last_holder()

    assert provider.logout_count == 1
