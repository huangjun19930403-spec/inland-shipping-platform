"""AMMS 单会话管理。"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import json
import logging
import random
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import urljoin

import httpx

from app.core.config import settings
from app.core.exceptions import InternalError, ValidationError
from app.integrations.config_keys import (
    HIFLEET_BASE_URL,
    HIFLEET_CHECK_LOGIN_URL,
    HIFLEET_CHECK_LOGIN_COOLDOWN_SECONDS,
    HIFLEET_CONFIG_PROFILE,
    HIFLEET_ENABLED,
    HIFLEET_LOGOUT_URL,
    HIFLEET_LOGIN_URL,
    HIFLEET_PASSWORD,
    HIFLEET_RELOGIN_CHECK_ENABLED,
    HIFLEET_SESSION_IDLE_LOGOUT_SECONDS,
    HIFLEET_TIMEOUT_SECONDS,
    HIFLEET_USERNAME,
)
from app.integrations.http import get_shared_http_client

if TYPE_CHECKING:
    from app.modules.system.runtime_config import RuntimeConfigService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _SharedHifleetSessionState:
    login_task: Optional[asyncio.Task[None]] = None
    login_state_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    logged_in: bool = False
    last_check_at: Optional[datetime] = None
    backoff_until: Optional[datetime] = None
    last_used_at: Optional[datetime] = None


_SHARED_STATE_LOCK = asyncio.Lock()
_SHARED_SESSION_STATES: dict[str, _SharedHifleetSessionState] = {}


class HifleetSessionManager:
    """统一 AMMS 登录态管理。

    特性：
    - 单会话复用
    - 单飞登录
    - 失败退避
    - 轻量 check-login
    - 会话失效后的受控重登录
    """

    def __init__(
        self,
        *,
        runtime_config: RuntimeConfigService | None = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        login_failure_backoff_seconds: float = 30.0,
        check_login_cooldown_seconds: float = 180.0,
        max_retries: int = 1,
    ) -> None:
        self._runtime_config = runtime_config
        self._transport = transport
        self._login_failure_backoff_seconds = max(1.0, login_failure_backoff_seconds)
        self._check_login_cooldown_seconds = max(1.0, check_login_cooldown_seconds)
        self._max_retries = max(0, max_retries)
        self._current_state_key: str | None = None

    async def _client(self) -> httpx.AsyncClient:
        client_name = "hifleet-session"
        if self._transport is None:
            client_name = f"hifleet-session:{await self._session_key()}"
        return await get_shared_http_client(
            client_name,
            follow_redirects=True,
            transport=self._transport,
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
            },
        )

    async def _enabled(self) -> bool:
        if self._runtime_config is not None:
            return await self._runtime_config.get_bool(
                HIFLEET_ENABLED,
                bool(settings.HIFLEET_ENABLED),
                profile_code=HIFLEET_CONFIG_PROFILE,
            )
        return bool(settings.HIFLEET_ENABLED)

    async def _base_url(self) -> str:
        if self._runtime_config is not None:
            value = await self._runtime_config.get_value(
                HIFLEET_BASE_URL,
                settings.HIFLEET_BASE_URL or "",
                profile_code=HIFLEET_CONFIG_PROFILE,
            )
            return (value or "").strip().rstrip("/")
        return (settings.HIFLEET_BASE_URL or "").strip().rstrip("/")

    async def _login_url(self) -> str:
        if self._runtime_config is not None:
            value = await self._runtime_config.get_value(
                HIFLEET_LOGIN_URL,
                settings.HIFLEET_LOGIN_URL or "",
                profile_code=HIFLEET_CONFIG_PROFILE,
            )
            return (value or "").strip()
        return (settings.HIFLEET_LOGIN_URL or "").strip()

    async def _logout_url(self) -> str:
        if self._runtime_config is not None:
            value = await self._runtime_config.get_value(
                HIFLEET_LOGOUT_URL,
                settings.HIFLEET_LOGOUT_URL or "",
                profile_code=HIFLEET_CONFIG_PROFILE,
            )
            return (value or "").strip()
        return (settings.HIFLEET_LOGOUT_URL or "").strip()

    async def _check_login_url(self) -> str:
        if self._runtime_config is not None:
            value = await self._runtime_config.get_value(
                HIFLEET_CHECK_LOGIN_URL,
                settings.HIFLEET_CHECK_LOGIN_URL or "",
                profile_code=HIFLEET_CONFIG_PROFILE,
            )
            return (value or "").strip()
        return (settings.HIFLEET_CHECK_LOGIN_URL or "").strip()

    async def _username(self) -> str:
        if self._runtime_config is not None:
            value = await self._runtime_config.get_value(
                HIFLEET_USERNAME,
                settings.HIFLEET_USERNAME or "",
                profile_code=HIFLEET_CONFIG_PROFILE,
            )
            return (value or "").strip()
        return (settings.HIFLEET_USERNAME or "").strip()

    async def _password(self) -> str:
        if self._runtime_config is not None:
            value = await self._runtime_config.get_value(
                HIFLEET_PASSWORD,
                settings.HIFLEET_PASSWORD or "",
                profile_code=HIFLEET_CONFIG_PROFILE,
            )
            return value or ""
        return settings.HIFLEET_PASSWORD or ""

    async def _timeout(self) -> float:
        default_timeout = float(settings.HIFLEET_TIMEOUT_SECONDS or settings.ROUTE_GEOMETRY_TIMEOUT_SECONDS or 8.0)
        if self._runtime_config is not None:
            return float(
                await self._runtime_config.get_float(
                    HIFLEET_TIMEOUT_SECONDS,
                    default_timeout,
                    profile_code=HIFLEET_CONFIG_PROFILE,
                )
            )
        return float(settings.HIFLEET_TIMEOUT_SECONDS or settings.ROUTE_GEOMETRY_TIMEOUT_SECONDS or 8.0)

    async def _runtime_check_login_cooldown_seconds(self) -> float:
        default_value = float(settings.HIFLEET_CHECK_LOGIN_COOLDOWN_SECONDS or self._check_login_cooldown_seconds)
        if self._runtime_config is not None:
            value = await self._runtime_config.get_float(
                HIFLEET_CHECK_LOGIN_COOLDOWN_SECONDS,
                default_value,
                profile_code=HIFLEET_CONFIG_PROFILE,
            )
            return max(1.0, float(value))
        return max(1.0, default_value)

    async def _idle_logout_seconds(self) -> float:
        default_value = float(settings.HIFLEET_SESSION_IDLE_LOGOUT_SECONDS or 0)
        if self._runtime_config is not None:
            value = await self._runtime_config.get_float(
                HIFLEET_SESSION_IDLE_LOGOUT_SECONDS,
                default_value,
                profile_code=HIFLEET_CONFIG_PROFILE,
            )
            return max(0.0, float(value))
        return max(0.0, default_value)

    async def _relogin_check_enabled(self) -> bool:
        if self._runtime_config is not None:
            return await self._runtime_config.get_bool(
                HIFLEET_RELOGIN_CHECK_ENABLED,
                bool(settings.HIFLEET_RELOGIN_CHECK_ENABLED),
                profile_code=HIFLEET_CONFIG_PROFILE,
            )
        return bool(settings.HIFLEET_RELOGIN_CHECK_ENABLED)

    @staticmethod
    def _version() -> str:
        return "5.3.703"

    async def _check_basic_config(self) -> None:
        enabled = await self._enabled()
        base_url = await self._base_url()
        login_url = await self._login_url()
        check_login_url = await self._check_login_url()
        username = await self._username()
        password = await self._password()

        if not enabled:
            raise ValidationError("AMMS 路径服务未启用")
        if not base_url:
            raise ValidationError("未配置 AMMS 路径服务基础地址")
        if not login_url:
            raise ValidationError("未配置 AMMS 登录地址")
        if not check_login_url:
            raise ValidationError("未配置 AMMS 登录校验地址")
        if not (username and password):
            raise ValidationError("未配置 AMMS 登录账号或密码，当前路径服务不可用")

    async def _session_key(self) -> str:
        password_fingerprint = hashlib.sha1((await self._password()).encode("utf-8")).hexdigest()
        raw = "|".join(
            [
                await self._base_url(),
                await self._login_url(),
                await self._check_login_url(),
                await self._username(),
                password_fingerprint,
            ]
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    async def _state(self) -> _SharedHifleetSessionState:
        key = await self._session_key()
        self._current_state_key = key
        existing = _SHARED_SESSION_STATES.get(key)
        if existing is not None:
            return existing
        async with _SHARED_STATE_LOCK:
            existing = _SHARED_SESSION_STATES.get(key)
            if existing is not None:
                return existing
            state = _SharedHifleetSessionState()
            _SHARED_SESSION_STATES[key] = state
            return state

    async def _url(self, endpoint: str) -> str:
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            return endpoint
        base_url = await self._base_url()
        return urljoin(f"{base_url}/", endpoint.lstrip("/"))

    async def _default_headers(self) -> dict[str, str]:
        base_url = await self._base_url()
        return {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": f"{base_url}/",
        }

    @staticmethod
    def _parse_json_like(text: str) -> Optional[dict[str, Any]]:
        raw = (text or "").strip().lstrip("\ufeff")
        if not raw:
            return None
        if raw.startswith("{") or raw.startswith("["):
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {"data": parsed}
            except ValueError:
                pass

        first_brace = raw.find("{")
        last_brace = raw.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            candidate = raw[first_brace:last_brace + 1]
            try:
                parsed = json.loads(candidate)
                return parsed if isinstance(parsed, dict) else {"data": parsed}
            except ValueError:
                return None
        return None

    def _decode_response_json(self, response: httpx.Response, context: str) -> dict[str, Any]:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            return {"data": payload}
        except ValueError:
            parsed = self._parse_json_like(response.text)
            if parsed is not None:
                return parsed
            body_preview = (response.text or "").strip().replace("\n", " ")
            raise InternalError(f"AMMS {context} 返回非 JSON 响应: {body_preview[:240]}")

    async def _post_form(
        self,
        url: str,
        data: dict[str, Any],
        *,
        headers: Optional[dict[str, str]] = None,
        context: str,
    ) -> dict[str, Any]:
        client = await self._client()
        request_headers = headers or await self._default_headers()
        timeout = await self._timeout()
        response = await client.post(
            url,
            data=data,
            params={"_v": self._version()},
            headers=request_headers,
            timeout=timeout,
        )
        if response.status_code >= 400:
            raise InternalError(
                f"AMMS {context} 请求失败: status={response.status_code}, body={(response.text or '')[:240]}"
            )
        return self._decode_response_json(response, context)

    async def _get_json(self, url: str, *, context: str) -> dict[str, Any]:
        client = await self._client()
        request_headers = await self._default_headers()
        timeout = await self._timeout()
        response = await client.get(
            url,
            params={"_v": self._version()},
            headers=request_headers,
            timeout=timeout,
        )
        if response.status_code >= 400:
            raise InternalError(
                f"AMMS {context} 请求失败: status={response.status_code}, body={(response.text or '')[:240]}"
            )
        return self._decode_response_json(response, context)

    async def _login_once(self) -> None:
        state = await self._state()
        await self._check_basic_config()
        login_url = await self._login_url()
        username = await self._username()
        password = await self._password()
        default_headers = await self._default_headers()
        payload = await self._post_form(
            await self._url(login_url),
            {
                "id": str(random.random()),
                "email": username,
                "password": password,
            },
            headers={
                **default_headers,
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            },
            context="登录",
        )
        if str(payload.get("flag")) != "1":
            msg = payload.get("msg") or payload.get("message") or payload
            raise ValidationError(f"AMMS 登录失败: {msg}")
        state.logged_in = True
        state.last_check_at = datetime.utcnow()
        state.last_used_at = state.last_check_at
        state.backoff_until = None

    async def _run_login(self, state: _SharedHifleetSessionState) -> None:
        try:
            await self._login_once()
        except Exception:
            state.logged_in = False
            state.backoff_until = datetime.utcnow() + timedelta(seconds=self._login_failure_backoff_seconds)
            raise

    async def _ensure_singleflight_login(self) -> None:
        state = await self._state()
        now = datetime.utcnow()
        if state.backoff_until and now < state.backoff_until:
            remaining = int((state.backoff_until - now).total_seconds())
            raise ValidationError(f"AMMS 登录退避中，请 {remaining} 秒后重试")

        async with state.login_state_lock:
            if state.login_task is None or state.login_task.done():
                state.login_task = asyncio.create_task(self._run_login(state))
            task = state.login_task

        await task

    async def _logout_idle_session(self, state: _SharedHifleetSessionState) -> None:
        logout_url = await self._logout_url()
        if logout_url:
            try:
                await self._get_json(await self._url(logout_url), context="退出登录")
            except Exception as exc:  # noqa: BLE001
                logger.warning("[HifleetSessionManager] idle logout request failed: %s", exc)
        try:
            client = await self._client()
            client.cookies.clear()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[HifleetSessionManager] clear idle cookies failed: %s", exc)
        state.logged_in = False
        state.last_check_at = None
        state.last_used_at = None

    async def _logout_if_idle(self, state: _SharedHifleetSessionState) -> None:
        idle_seconds = await self._idle_logout_seconds()
        if idle_seconds <= 0 or not state.logged_in or state.last_used_at is None:
            return
        now = datetime.utcnow()
        if (now - state.last_used_at).total_seconds() < idle_seconds:
            return
        async with state.login_state_lock:
            if not state.logged_in or state.last_used_at is None:
                return
            if (datetime.utcnow() - state.last_used_at).total_seconds() < idle_seconds:
                return
            await self._logout_idle_session(state)

    async def _mark_used(self) -> None:
        state = await self._state()
        state.last_used_at = datetime.utcnow()

    async def check_session(self) -> bool:
        state = await self._state()
        await self._check_basic_config()
        if not state.logged_in:
            return False
        if not await self._relogin_check_enabled():
            return True

        now = datetime.utcnow()
        cooldown_seconds = await self._runtime_check_login_cooldown_seconds()
        if state.last_check_at and (now - state.last_check_at).total_seconds() < cooldown_seconds:
            return True

        check_login_url = await self._check_login_url()
        payload = await self._get_json(await self._url(check_login_url), context="登录态校验")
        state.last_check_at = now
        if str(payload.get("status")) == "0":
            state.logged_in = False
            return False
        return True

    async def ensure_session(self, *, force_login: bool = False) -> None:
        state = await self._state()
        await self._check_basic_config()
        if force_login:
            state.logged_in = False
            state.backoff_until = None

        await self._logout_if_idle(state)

        if not state.logged_in:
            await self._ensure_singleflight_login()
            await self._mark_used()
            return

        try:
            alive = await self.check_session()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[HifleetSessionManager] check session failed, relogin: %s", exc)
            alive = False

        if not alive:
            await self._ensure_singleflight_login()
        await self._mark_used()

    def invalidate(self) -> None:
        keys = [self._current_state_key] if self._current_state_key else list(_SHARED_SESSION_STATES)
        for key in keys:
            if not key:
                continue
            state = _SHARED_SESSION_STATES.get(key)
            if state is None:
                continue
            state.logged_in = False
            state.last_check_at = None
