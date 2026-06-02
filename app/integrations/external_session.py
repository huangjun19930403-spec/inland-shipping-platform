"""Shared external cookie-session management.

This module keeps external provider login state usable across API and worker
processes without making provider-specific assumptions beyond a small adapter
protocol.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Optional, Protocol, runtime_checkable

from app.core.config import settings
from app.core.exceptions import ValidationError

try:  # pragma: no cover - optional dependency guard
    from redis.asyncio import Redis
except Exception:  # pragma: no cover
    Redis = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_PROCESS_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex}"


@runtime_checkable
class ExternalCookieSessionProvider(Protocol):
    provider_code: str

    async def session_key(self) -> str: ...

    async def enabled(self) -> bool: ...

    async def login(self) -> dict[str, Any]: ...

    async def logout(self) -> None: ...

    async def check(self) -> bool: ...

    def is_login_success(self, payload: dict[str, Any]) -> bool: ...

    def is_duplicate_login_error(self, payload: dict[str, Any]) -> bool: ...

    def is_auth_expired_error(self, exc: Exception) -> bool: ...

    async def export_cookies(self) -> list[dict[str, Any]]: ...

    async def import_cookies(self, cookies: list[dict[str, Any]]) -> None: ...


@dataclass(slots=True)
class _LocalExternalSessionState:
    login_state_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    logged_in: bool = False
    last_check_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    backoff_until: Optional[datetime] = None
    redis_warning_logged: bool = False


@dataclass(slots=True)
class _RedisLock:
    key: str
    token: str


_LOCAL_STATE_LOCK = asyncio.Lock()
_LOCAL_STATES: dict[str, _LocalExternalSessionState] = {}


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ExternalCookieSessionManager:
    """Coordinate one cookie-based external login across local and worker processes."""

    def __init__(
        self,
        provider: ExternalCookieSessionProvider,
        *,
        redis_url: str | None = None,
        redis_client: Any | None = None,
        process_id: str | None = None,
        login_failure_backoff_seconds: float = 30.0,
        check_login_cooldown_seconds: float = 180.0,
        lock_ttl_seconds: int = 45,
        cookie_ttl_seconds: int = 86400,
        holder_ttl_seconds: int = 3600,
        lock_wait_timeout_seconds: float | None = None,
        duplicate_login_recovery_enabled: bool = True,
        logout_on_shutdown: bool = True,
    ) -> None:
        self.provider = provider
        self.redis_url = (
            (settings.EXTERNAL_SESSION_REDIS_URL or settings.CELERY_BROKER_URL or "")
            if redis_url is None
            else redis_url
        ).strip()
        self._redis_client = redis_client
        self._redis_created = False
        self.process_id = process_id or _PROCESS_ID
        self.login_failure_backoff_seconds = max(1.0, float(login_failure_backoff_seconds))
        self.check_login_cooldown_seconds = max(1.0, float(check_login_cooldown_seconds))
        self.lock_ttl_seconds = max(1, int(lock_ttl_seconds))
        self.cookie_ttl_seconds = max(60, int(cookie_ttl_seconds))
        self.holder_ttl_seconds = max(60, int(holder_ttl_seconds))
        self.lock_wait_timeout_seconds = (
            max(1.0, float(lock_wait_timeout_seconds))
            if lock_wait_timeout_seconds is not None
            else min(60.0, max(5.0, float(self.lock_ttl_seconds)))
        )
        self.duplicate_login_recovery_enabled = bool(duplicate_login_recovery_enabled)
        self.logout_on_shutdown = bool(logout_on_shutdown)

    async def _state_key(self) -> str:
        return f"{self.provider.provider_code.lower()}:{await self.provider.session_key()}"

    async def _state(self) -> _LocalExternalSessionState:
        key = await self._state_key()
        existing = _LOCAL_STATES.get(key)
        if existing is not None:
            return existing
        async with _LOCAL_STATE_LOCK:
            existing = _LOCAL_STATES.get(key)
            if existing is not None:
                return existing
            state = _LocalExternalSessionState()
            _LOCAL_STATES[key] = state
            return state

    async def _base_key(self) -> str:
        return f"external-session:{await self._state_key()}"

    async def _redis(self) -> Any | None:
        if self._redis_client is not None:
            return self._redis_client
        if not self.redis_url or Redis is None:
            return None
        if not self._redis_created:
            self._redis_client = Redis.from_url(self.redis_url, encoding="utf-8", decode_responses=True)
            self._redis_created = True
        return self._redis_client

    async def _warn_redis_unavailable(self, exc: Exception) -> None:
        state = await self._state()
        if state.redis_warning_logged:
            return
        state.redis_warning_logged = True
        logger.warning(
            "[ExternalCookieSessionManager] Redis session coordination unavailable provider=%s error=%s; "
            "falling back to process-local protection",
            self.provider.provider_code,
            exc,
        )

    async def _redis_get(self, key: str) -> str | None:
        client = await self._redis()
        if client is None:
            return None
        try:
            return await client.get(key)
        except Exception as exc:  # noqa: BLE001
            await self._warn_redis_unavailable(exc)
            return None

    async def _redis_setex(self, key: str, ttl: int, value: str) -> bool:
        client = await self._redis()
        if client is None:
            return False
        try:
            await client.setex(key, ttl, value)
            return True
        except Exception as exc:  # noqa: BLE001
            await self._warn_redis_unavailable(exc)
            return False

    async def _redis_delete(self, *keys: str) -> None:
        client = await self._redis()
        if client is None or not keys:
            return
        try:
            await client.delete(*keys)
        except Exception as exc:  # noqa: BLE001
            await self._warn_redis_unavailable(exc)

    async def _cookies_key(self) -> str:
        return f"{await self._base_key()}:cookies"

    async def _health_key(self) -> str:
        return f"{await self._base_key()}:health"

    async def _lock_key(self) -> str:
        return f"{await self._base_key()}:lock"

    async def _holders_key(self) -> str:
        return f"{await self._base_key()}:holders"

    async def _holder_key(self, holder_id: str | None = None) -> str:
        return f"{await self._base_key()}:holder:{holder_id or self.process_id}"

    async def _register_holder(self) -> None:
        client = await self._redis()
        if client is None:
            return
        holders_key = await self._holders_key()
        holder_key = await self._holder_key()
        try:
            await client.sadd(holders_key, self.process_id)
            await client.setex(holder_key, self.holder_ttl_seconds, _utcnow().isoformat())
            await client.expire(holders_key, self.holder_ttl_seconds)
        except Exception as exc:  # noqa: BLE001
            await self._warn_redis_unavailable(exc)

    async def _unregister_holder(self) -> None:
        client = await self._redis()
        if client is None:
            return
        try:
            await client.srem(await self._holders_key(), self.process_id)
            await client.delete(await self._holder_key())
        except Exception as exc:  # noqa: BLE001
            await self._warn_redis_unavailable(exc)

    async def _active_holder_count(self) -> int:
        client = await self._redis()
        if client is None:
            return 0
        holders_key = await self._holders_key()
        try:
            holder_ids = await client.smembers(holders_key)
            active_count = 0
            for holder_id in list(holder_ids or []):
                if await client.exists(await self._holder_key(str(holder_id))):
                    active_count += 1
                else:
                    await client.srem(holders_key, holder_id)
            return active_count
        except Exception as exc:  # noqa: BLE001
            await self._warn_redis_unavailable(exc)
            return 0

    async def _acquire_lock(self) -> _RedisLock | None:
        client = await self._redis()
        if client is None:
            return None
        key = await self._lock_key()
        token = f"{self.process_id}:{uuid.uuid4().hex}"
        try:
            ok = await client.set(key, token, nx=True, ex=self.lock_ttl_seconds)
        except Exception as exc:  # noqa: BLE001
            await self._warn_redis_unavailable(exc)
            return None
        return _RedisLock(key=key, token=token) if ok else None

    async def _release_lock(self, lock: _RedisLock | None) -> None:
        if lock is None:
            return
        client = await self._redis()
        if client is None:
            return
        try:
            current = await client.get(lock.key)
            if current == lock.token:
                await client.delete(lock.key)
        except Exception as exc:  # noqa: BLE001
            await self._warn_redis_unavailable(exc)

    async def _save_cookies(self) -> None:
        cookies = await self.provider.export_cookies()
        if not cookies:
            return
        payload = json.dumps(cookies, ensure_ascii=False)
        await self._redis_setex(await self._cookies_key(), self.cookie_ttl_seconds, payload)

    async def _clear_persisted_session(self) -> None:
        await self._redis_delete(await self._cookies_key(), await self._health_key())

    async def _restore_persisted_session(self, state: _LocalExternalSessionState) -> bool:
        raw = await self._redis_get(await self._cookies_key())
        if not raw:
            return False
        try:
            cookies = json.loads(raw)
            if not isinstance(cookies, list):
                return False
            await self.provider.import_cookies(cookies)
            alive = await self.provider.check()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[ExternalCookieSessionManager] persisted session restore failed provider=%s error=%s",
                self.provider.provider_code,
                exc,
            )
            await self._clear_persisted_session()
            state.logged_in = False
            return False
        if not alive:
            await self._clear_persisted_session()
            state.logged_in = False
            return False
        now = _utcnow()
        state.logged_in = True
        state.last_check_at = now
        state.last_used_at = now
        state.backoff_until = None
        await self._write_health("READY", "restored")
        return True

    async def _write_health(self, status: str, message: str | None = None) -> None:
        payload = {
            "provider_code": self.provider.provider_code,
            "status": status,
            "message": message,
            "checked_at": _utcnow().isoformat(),
            "process_id": self.process_id,
        }
        await self._redis_setex(await self._health_key(), self.cookie_ttl_seconds, json.dumps(payload, ensure_ascii=False))

    async def _check_local_session(self, state: _LocalExternalSessionState, *, force: bool = False) -> bool:
        if not state.logged_in:
            return False
        if not force and state.last_check_at:
            age = (_utcnow() - state.last_check_at).total_seconds()
            if age < self.check_login_cooldown_seconds:
                return True
        try:
            alive = await self.provider.check()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[ExternalCookieSessionManager] session check failed provider=%s error=%s",
                self.provider.provider_code,
                exc,
            )
            alive = False
        state.last_check_at = _utcnow()
        if not alive:
            state.logged_in = False
            await self._clear_persisted_session()
            return False
        return True

    async def _wait_for_peer_session(self, state: _LocalExternalSessionState) -> bool:
        deadline = _utcnow() + timedelta(seconds=self.lock_wait_timeout_seconds)
        while _utcnow() < deadline:
            if await self._restore_persisted_session(state):
                return True
            await asyncio.sleep(0.25)
        return False

    @staticmethod
    def _payload_message(payload: dict[str, Any]) -> str:
        msg = payload.get("msg") or payload.get("message") or payload.get("error") or payload
        return str(msg).replace("\r", " ").replace("\n", " ").strip()[:240]

    async def _login_with_duplicate_recovery(self) -> None:
        payload = await self.provider.login()
        if self.provider.is_login_success(payload):
            await self._save_cookies()
            await self._write_health("READY", "login")
            return

        if self.duplicate_login_recovery_enabled and self.provider.is_duplicate_login_error(payload):
            logger.warning(
                "[ExternalCookieSessionManager] duplicate login detected provider=%s; attempting logout and one relogin",
                self.provider.provider_code,
            )
            try:
                await self.provider.logout()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[ExternalCookieSessionManager] duplicate-login recovery logout failed provider=%s error=%s",
                    self.provider.provider_code,
                    exc,
                )
            await self._clear_persisted_session()
            payload = await self.provider.login()
            if self.provider.is_login_success(payload):
                await self._save_cookies()
                await self._write_health("READY", "recovered_duplicate_login")
                return

        raise ValidationError(f"{self.provider.provider_code} 登录失败: {self._payload_message(payload)}")

    async def _establish_session(self, state: _LocalExternalSessionState, *, force_login: bool = False) -> None:
        if await self._redis() is None:
            try:
                await self._login_with_duplicate_recovery()
                now = _utcnow()
                state.logged_in = True
                state.last_check_at = now
                state.last_used_at = now
                state.backoff_until = None
                return
            except Exception:
                state.logged_in = False
                state.backoff_until = _utcnow() + timedelta(seconds=self.login_failure_backoff_seconds)
                raise

        lock = await self._acquire_lock()
        if lock is None and state.redis_warning_logged:
            try:
                await self._login_with_duplicate_recovery()
                now = _utcnow()
                state.logged_in = True
                state.last_check_at = now
                state.last_used_at = now
                state.backoff_until = None
                return
            except Exception:
                state.logged_in = False
                state.backoff_until = _utcnow() + timedelta(seconds=self.login_failure_backoff_seconds)
                raise

        if lock is None:
            if await self._wait_for_peer_session(state):
                return
            lock = await self._acquire_lock()

        try:
            if lock is not None and not force_login and await self._restore_persisted_session(state):
                return
            if force_login:
                await self._clear_persisted_session()
            await self._login_with_duplicate_recovery()
            now = _utcnow()
            state.logged_in = True
            state.last_check_at = now
            state.last_used_at = now
            state.backoff_until = None
        except Exception as exc:
            state.logged_in = False
            state.backoff_until = _utcnow() + timedelta(seconds=self.login_failure_backoff_seconds)
            await self._write_health("FAILED", str(exc)[:240])
            raise
        finally:
            await self._release_lock(lock)

    async def ensure_session(self, *, force_login: bool = False) -> None:
        if not await self.provider.enabled():
            raise ValidationError(f"{self.provider.provider_code} 路径服务未启用")

        state = await self._state()
        await self._register_holder()
        now = _utcnow()
        if state.backoff_until and now < state.backoff_until and not force_login:
            remaining = int((state.backoff_until - now).total_seconds())
            raise ValidationError(f"{self.provider.provider_code} 登录退避中，请 {remaining} 秒后重试")

        async with state.login_state_lock:
            if force_login:
                state.logged_in = False
                state.backoff_until = None
            if not force_login and await self._check_local_session(state):
                state.last_used_at = _utcnow()
                return
            if not force_login and await self._restore_persisted_session(state):
                state.last_used_at = _utcnow()
                return
            await self._establish_session(state, force_login=force_login)
            state.last_used_at = _utcnow()

    async def warmup(self) -> None:
        await self.ensure_session(force_login=False)

    async def check_session(self) -> bool:
        if not await self.provider.enabled():
            return False
        state = await self._state()
        if await self._check_local_session(state, force=True):
            return True
        return await self._restore_persisted_session(state)

    def invalidate(self) -> None:
        async def _mark() -> None:
            state = await self._state()
            state.logged_in = False
            state.last_check_at = None

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_mark())
            return
        loop.create_task(_mark())

    async def invalidate_async(self) -> None:
        state = await self._state()
        state.logged_in = False
        state.last_check_at = None
        await self._clear_persisted_session()

    async def logout_if_last_holder(self) -> None:
        await self._unregister_holder()
        state = await self._state()
        state.logged_in = False
        state.last_check_at = None
        if not self.logout_on_shutdown:
            return
        if await self._redis() is not None and state.redis_warning_logged:
            logger.warning(
                "[ExternalCookieSessionManager] skip remote logout provider=%s because Redis holder state is unavailable",
                self.provider.provider_code,
            )
            return

        active_holders = await self._active_holder_count()
        if active_holders > 0:
            logger.info(
                "[ExternalCookieSessionManager] skip remote logout provider=%s active_holders=%s",
                self.provider.provider_code,
                active_holders,
            )
            return

        lock = await self._acquire_lock()
        try:
            await self._restore_persisted_session(state)
            try:
                await self.provider.logout()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[ExternalCookieSessionManager] remote logout failed provider=%s error=%s",
                    self.provider.provider_code,
                    exc,
                )
            await self._clear_persisted_session()
            await self._write_health("LOGGED_OUT", "shutdown")
        finally:
            await self._release_lock(lock)

    async def status(self) -> dict[str, Any]:
        state = await self._state()
        health_raw = await self._redis_get(await self._health_key())
        health: dict[str, Any] | None = None
        if health_raw:
            try:
                parsed = json.loads(health_raw)
                health = parsed if isinstance(parsed, dict) else None
            except ValueError:
                health = None
        return {
            "provider_code": self.provider.provider_code,
            "logged_in": state.logged_in,
            "last_check_at": state.last_check_at.isoformat() if state.last_check_at else None,
            "last_used_at": state.last_used_at.isoformat() if state.last_used_at else None,
            "redis_enabled": bool(await self._redis()),
            "health": health,
        }
