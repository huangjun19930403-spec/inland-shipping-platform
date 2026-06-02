"""AMMS/HiFleet shared cookie-session adapter."""
from __future__ import annotations

import hashlib
import json
import logging
import random
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import urljoin

import httpx

from app.core.config import settings
from app.core.exceptions import InternalError, ValidationError
from app.integrations.config_keys import (
    HIFLEET_BASE_URL,
    HIFLEET_CHECK_LOGIN_COOLDOWN_SECONDS,
    HIFLEET_CHECK_LOGIN_URL,
    HIFLEET_CONFIG_PROFILE,
    HIFLEET_DUPLICATE_LOGIN_RECOVERY_ENABLED,
    HIFLEET_ENABLED,
    HIFLEET_LOGIN_URL,
    HIFLEET_LOGOUT_URL,
    HIFLEET_PASSWORD,
    HIFLEET_RELOGIN_CHECK_ENABLED,
    HIFLEET_SESSION_COOKIE_TTL_SECONDS,
    HIFLEET_SESSION_LOCK_TTL_SECONDS,
    HIFLEET_SESSION_LOGOUT_ON_SHUTDOWN,
    HIFLEET_SESSION_WARMUP_ON_START,
    HIFLEET_TIMEOUT_SECONDS,
    HIFLEET_USERNAME,
)
from app.integrations.external_session import ExternalCookieSessionManager
from app.integrations.http import get_shared_http_client

if TYPE_CHECKING:
    from app.modules.system.runtime_config import RuntimeConfigService

logger = logging.getLogger(__name__)

_DUPLICATE_LOGIN_KEYWORDS = (
    "重复登录",
    "重复登陆",
    "已经登录",
    "已登录",
    "已在线",
    "账号在线",
    "帐号同时使用人数已达到上限",
    "账号同时使用人数已达到上限",
    "同时使用人数已达到上限",
    "同时使用人数达到上限",
    "使用人数已达到上限",
    "already login",
    "already logged",
    "duplicate login",
    "logged in elsewhere",
)

_AUTH_EXPIRED_KEYWORDS = (
    "未登录",
    "登录失效",
    "请登录",
    "session",
    "cookie",
    "auth",
)


class HifleetSessionManager:
    """Provider adapter plus legacy-compatible AMMS session facade."""

    provider_code = "AMMS"

    def __init__(
        self,
        *,
        runtime_config: RuntimeConfigService | None = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        login_failure_backoff_seconds: float = 30.0,
        check_login_cooldown_seconds: float = 180.0,
        max_retries: int = 1,
        redis_client: Any | None = None,
    ) -> None:
        self._runtime_config = runtime_config
        self._transport = transport
        self._login_failure_backoff_seconds = max(1.0, login_failure_backoff_seconds)
        self._check_login_cooldown_seconds = max(1.0, check_login_cooldown_seconds)
        self._max_retries = max(0, max_retries)
        self._external_session = ExternalCookieSessionManager(
            self,
            login_failure_backoff_seconds=self._login_failure_backoff_seconds,
            check_login_cooldown_seconds=self._check_login_cooldown_seconds,
            lock_ttl_seconds=self._initial_lock_ttl_seconds(),
            cookie_ttl_seconds=self._initial_cookie_ttl_seconds(),
            duplicate_login_recovery_enabled=self._initial_duplicate_recovery_enabled(),
            logout_on_shutdown=self._initial_logout_on_shutdown(),
            redis_client=redis_client,
        )

    def _initial_lock_ttl_seconds(self) -> int:
        return int(settings.HIFLEET_SESSION_LOCK_TTL_SECONDS or 45)

    def _initial_cookie_ttl_seconds(self) -> int:
        return int(settings.HIFLEET_SESSION_COOKIE_TTL_SECONDS or 86400)

    def _initial_duplicate_recovery_enabled(self) -> bool:
        return bool(settings.HIFLEET_DUPLICATE_LOGIN_RECOVERY_ENABLED)

    def _initial_logout_on_shutdown(self) -> bool:
        return bool(settings.HIFLEET_SESSION_LOGOUT_ON_SHUTDOWN)

    async def _client(self) -> httpx.AsyncClient:
        client_name = "hifleet-session"
        if self._transport is None:
            client_name = f"hifleet-session:{await self.session_key()}"
        return await get_shared_http_client(
            client_name,
            follow_redirects=True,
            transport=self._transport,
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
            },
        )

    async def _get_runtime_bool(self, key: str, default: bool) -> bool:
        if self._runtime_config is not None:
            return await self._runtime_config.get_bool(key, default, profile_code=HIFLEET_CONFIG_PROFILE)
        return default

    async def _get_runtime_float(self, key: str, default: float) -> float:
        if self._runtime_config is not None:
            return await self._runtime_config.get_float(key, default, profile_code=HIFLEET_CONFIG_PROFILE)
        return default

    async def _get_runtime_int(self, key: str, default: int) -> int:
        if self._runtime_config is not None:
            return await self._runtime_config.get_int(key, default, profile_code=HIFLEET_CONFIG_PROFILE)
        return default

    async def _get_runtime_value(self, key: str, default: str) -> str:
        if self._runtime_config is not None:
            value = await self._runtime_config.get_value(key, default, profile_code=HIFLEET_CONFIG_PROFILE)
            return value or ""
        return default

    async def enabled(self) -> bool:
        return await self._get_runtime_bool(HIFLEET_ENABLED, bool(settings.HIFLEET_ENABLED))

    async def _base_url(self) -> str:
        value = await self._get_runtime_value(HIFLEET_BASE_URL, settings.HIFLEET_BASE_URL or "")
        return value.strip().rstrip("/")

    async def _login_url(self) -> str:
        value = await self._get_runtime_value(HIFLEET_LOGIN_URL, settings.HIFLEET_LOGIN_URL or "")
        return value.strip()

    async def _logout_url(self) -> str:
        value = await self._get_runtime_value(HIFLEET_LOGOUT_URL, settings.HIFLEET_LOGOUT_URL or "")
        return value.strip()

    async def _check_login_url(self) -> str:
        value = await self._get_runtime_value(HIFLEET_CHECK_LOGIN_URL, settings.HIFLEET_CHECK_LOGIN_URL or "")
        return value.strip()

    async def _username(self) -> str:
        value = await self._get_runtime_value(HIFLEET_USERNAME, settings.HIFLEET_USERNAME or "")
        return value.strip()

    async def _password(self) -> str:
        return await self._get_runtime_value(HIFLEET_PASSWORD, settings.HIFLEET_PASSWORD or "")

    async def _timeout(self) -> float:
        default_timeout = float(settings.HIFLEET_TIMEOUT_SECONDS or settings.ROUTE_GEOMETRY_TIMEOUT_SECONDS or 8.0)
        return float(await self._get_runtime_float(HIFLEET_TIMEOUT_SECONDS, default_timeout))

    async def _check_basic_config(self) -> None:
        enabled = await self.enabled()
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

    async def session_key(self) -> str:
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
    def _version() -> str:
        return "5.3.703"

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
        response = await client.post(
            url,
            data=data,
            params={"_v": self._version()},
            headers=request_headers,
            timeout=await self._timeout(),
        )
        if response.status_code >= 400:
            raise InternalError(
                f"AMMS {context} 请求失败: status={response.status_code}, body={(response.text or '')[:240]}"
            )
        return self._decode_response_json(response, context)

    async def _get_json(self, url: str, *, context: str) -> dict[str, Any]:
        client = await self._client()
        response = await client.get(
            url,
            params={"_v": self._version()},
            headers=await self._default_headers(),
            timeout=await self._timeout(),
        )
        if response.status_code >= 400:
            raise InternalError(
                f"AMMS {context} 请求失败: status={response.status_code}, body={(response.text or '')[:240]}"
            )
        return self._decode_response_json(response, context)

    async def login(self) -> dict[str, Any]:
        await self._check_basic_config()
        default_headers = await self._default_headers()
        return await self._post_form(
            await self._url(await self._login_url()),
            {
                "id": str(random.random()),
                "email": await self._username(),
                "password": await self._password(),
            },
            headers={
                **default_headers,
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            },
            context="登录",
        )

    async def logout(self) -> None:
        logout_url = await self._logout_url()
        if not logout_url:
            return
        await self._get_json(await self._url(logout_url), context="退出登录")
        try:
            client = await self._client()
            client.cookies.clear()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[HifleetSessionManager] clear cookies after logout failed: %s", exc)

    async def check(self) -> bool:
        await self._check_basic_config()
        if not await self._get_runtime_bool(HIFLEET_RELOGIN_CHECK_ENABLED, bool(settings.HIFLEET_RELOGIN_CHECK_ENABLED)):
            return True
        payload = await self._get_json(await self._url(await self._check_login_url()), context="登录态校验")
        return str(payload.get("status")) != "0"

    @staticmethod
    def is_login_success(payload: dict[str, Any]) -> bool:
        return str(payload.get("flag")) == "1"

    @staticmethod
    def _message_text(payload: dict[str, Any]) -> str:
        return str(payload.get("msg") or payload.get("message") or payload).lower()

    def is_duplicate_login_error(self, payload: dict[str, Any]) -> bool:
        text = self._message_text(payload)
        return any(keyword.lower() in text for keyword in _DUPLICATE_LOGIN_KEYWORDS)

    def is_auth_expired_error(self, exc: Exception) -> bool:
        text = str(exc or "").lower()
        return any(keyword.lower() in text for keyword in _AUTH_EXPIRED_KEYWORDS)

    async def export_cookies(self) -> list[dict[str, Any]]:
        client = await self._client()
        cookies: list[dict[str, Any]] = []
        for cookie in client.cookies.jar:
            cookies.append(
                {
                    "name": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain,
                    "path": cookie.path,
                }
            )
        return cookies

    async def import_cookies(self, cookies: list[dict[str, Any]]) -> None:
        client = await self._client()
        client.cookies.clear()
        for item in cookies:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            client.cookies.set(
                name,
                str(item.get("value") or ""),
                domain=str(item.get("domain") or ""),
                path=str(item.get("path") or "/"),
            )

    async def ensure_session(self, *, force_login: bool = False) -> None:
        self._external_session.check_login_cooldown_seconds = float(
            await self._get_runtime_float(HIFLEET_CHECK_LOGIN_COOLDOWN_SECONDS, self._check_login_cooldown_seconds)
        )
        self._external_session.lock_ttl_seconds = int(
            await self._get_runtime_int(HIFLEET_SESSION_LOCK_TTL_SECONDS, self._initial_lock_ttl_seconds())
        )
        self._external_session.cookie_ttl_seconds = int(
            await self._get_runtime_int(HIFLEET_SESSION_COOKIE_TTL_SECONDS, self._initial_cookie_ttl_seconds())
        )
        self._external_session.duplicate_login_recovery_enabled = await self._get_runtime_bool(
            HIFLEET_DUPLICATE_LOGIN_RECOVERY_ENABLED,
            self._initial_duplicate_recovery_enabled(),
        )
        await self._external_session.ensure_session(force_login=force_login)

    async def warmup(self) -> None:
        if not await self.enabled():
            return
        if not await self._get_runtime_bool(HIFLEET_SESSION_WARMUP_ON_START, bool(settings.HIFLEET_SESSION_WARMUP_ON_START)):
            return
        await self.ensure_session(force_login=False)

    async def check_session(self) -> bool:
        return await self._external_session.check_session()

    async def logout_if_last_holder(self) -> None:
        if not await self.enabled():
            return
        self._external_session.logout_on_shutdown = await self._get_runtime_bool(
            HIFLEET_SESSION_LOGOUT_ON_SHUTDOWN,
            self._initial_logout_on_shutdown(),
        )
        await self._external_session.logout_if_last_holder()

    async def shutdown(self) -> None:
        await self.logout_if_last_holder()

    def invalidate(self) -> None:
        self._external_session.invalidate()

    async def invalidate_async(self) -> None:
        await self._external_session.invalidate_async()

    async def status(self) -> dict[str, Any]:
        return await self._external_session.status()
