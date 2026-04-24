"""AMMS 单会话管理。"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urljoin

import httpx

from app.core.config import settings
from app.core.exceptions import InternalError, ValidationError
from app.integrations.http import get_shared_http_client

logger = logging.getLogger(__name__)


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
        transport: Optional[httpx.AsyncBaseTransport] = None,
        login_failure_backoff_seconds: float = 30.0,
        check_login_cooldown_seconds: float = 180.0,
        max_retries: int = 1,
    ) -> None:
        self._transport = transport
        self._login_failure_backoff_seconds = max(1.0, login_failure_backoff_seconds)
        self._check_login_cooldown_seconds = max(1.0, check_login_cooldown_seconds)
        self._max_retries = max(0, max_retries)
        self._login_task: Optional[asyncio.Task[None]] = None
        self._login_state_lock = asyncio.Lock()
        self._logged_in = False
        self._last_check_at: Optional[datetime] = None
        self._backoff_until: Optional[datetime] = None

    async def _client(self) -> httpx.AsyncClient:
        return await get_shared_http_client(
            "hifleet-session",
            follow_redirects=True,
            transport=self._transport,
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
            },
        )

    @staticmethod
    def _enabled() -> bool:
        return bool(settings.HIFLEET_ENABLED)

    @staticmethod
    def _base_url() -> str:
        return (settings.HIFLEET_BASE_URL or "").strip().rstrip("/")

    @staticmethod
    def _login_url() -> str:
        return (settings.HIFLEET_LOGIN_URL or "").strip()

    @staticmethod
    def _check_login_url() -> str:
        return (settings.HIFLEET_CHECK_LOGIN_URL or "").strip()

    @staticmethod
    def _username() -> str:
        return (settings.HIFLEET_USERNAME or "").strip()

    @staticmethod
    def _password() -> str:
        return settings.HIFLEET_PASSWORD or ""

    @staticmethod
    def _timeout() -> float:
        return float(settings.HIFLEET_TIMEOUT_SECONDS or settings.ROUTE_GEOMETRY_TIMEOUT_SECONDS or 8.0)

    @staticmethod
    def _relogin_check_enabled() -> bool:
        return bool(settings.HIFLEET_RELOGIN_CHECK_ENABLED)

    @staticmethod
    def _version() -> str:
        return "5.3.703"

    def _check_basic_config(self) -> None:
        if not self._enabled():
            raise ValidationError("AMMS 路径服务未启用")
        if not self._base_url():
            raise ValidationError("未配置 AMMS 路径服务基础地址")
        if not self._login_url():
            raise ValidationError("未配置 AMMS 登录地址")
        if not self._check_login_url():
            raise ValidationError("未配置 AMMS 登录校验地址")
        if not (self._username() and self._password()):
            raise ValidationError("未配置 AMMS 登录账号或密码，当前路径服务不可用")

    def _url(self, endpoint: str) -> str:
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            return endpoint
        return urljoin(f"{self._base_url()}/", endpoint.lstrip("/"))

    def _default_headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": f"{self._base_url()}/",
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
        response = await client.post(
            url,
            data=data,
            params={"_v": self._version()},
            headers=headers or self._default_headers(),
            timeout=self._timeout(),
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
            headers=self._default_headers(),
            timeout=self._timeout(),
        )
        if response.status_code >= 400:
            raise InternalError(
                f"AMMS {context} 请求失败: status={response.status_code}, body={(response.text or '')[:240]}"
            )
        return self._decode_response_json(response, context)

    async def _login_once(self) -> None:
        self._check_basic_config()
        payload = await self._post_form(
            self._url(self._login_url()),
            {
                "id": str(random.random()),
                "email": self._username(),
                "password": self._password(),
            },
            headers={
                **self._default_headers(),
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            },
            context="登录",
        )
        if str(payload.get("flag")) != "1":
            msg = payload.get("msg") or payload.get("message") or payload
            raise ValidationError(f"AMMS 登录失败: {msg}")
        self._logged_in = True
        self._last_check_at = datetime.utcnow()
        self._backoff_until = None

    async def _run_login(self) -> None:
        try:
            await self._login_once()
        except Exception:
            self._logged_in = False
            self._backoff_until = datetime.utcnow() + timedelta(seconds=self._login_failure_backoff_seconds)
            raise

    async def _ensure_singleflight_login(self) -> None:
        now = datetime.utcnow()
        if self._backoff_until and now < self._backoff_until:
            remaining = int((self._backoff_until - now).total_seconds())
            raise ValidationError(f"AMMS 登录退避中，请 {remaining} 秒后重试")

        async with self._login_state_lock:
            if self._login_task is None or self._login_task.done():
                self._login_task = asyncio.create_task(self._run_login())
            task = self._login_task

        await task

    async def check_session(self) -> bool:
        self._check_basic_config()
        if not self._logged_in:
            return False
        if not self._relogin_check_enabled():
            return True

        now = datetime.utcnow()
        if self._last_check_at and (now - self._last_check_at).total_seconds() < self._check_login_cooldown_seconds:
            return True

        payload = await self._get_json(self._url(self._check_login_url()), context="登录态校验")
        self._last_check_at = now
        if str(payload.get("status")) == "0":
            self._logged_in = False
            return False
        return True

    async def ensure_session(self, *, force_login: bool = False) -> None:
        self._check_basic_config()
        if force_login:
            self._logged_in = False

        if not self._logged_in:
            await self._ensure_singleflight_login()
            return

        try:
            alive = await self.check_session()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[HifleetSessionManager] check session failed, relogin: %s", exc)
            alive = False

        if not alive:
            await self._ensure_singleflight_login()

    def invalidate(self) -> None:
        self._logged_in = False
        self._last_check_at = None
