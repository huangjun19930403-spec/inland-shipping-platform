"""system 外部集成配置连接测试服务。"""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.integrations.amap.geocode_client import AmapGeocodeClient
from app.integrations.config_keys import (
    AMAP_CONFIG_PROFILE,
    AMAP_ROUTE_WEB_API_KEY,
    ES_HISTORY_CONFIG_PROFILE,
    ES_REALTIME_CONFIG_PROFILE,
    HIFLEET_CONFIG_PROFILE,
    HIFLEET_ENABLED,
)
from app.integrations.es.history_client import HistoryEsClient
from app.integrations.es.realtime_client import RealtimeEsClient
from app.integrations.hifleet.session_manager import HifleetSessionManager
from app.modules.system.repository import SystemConfigRepository
from app.modules.system.runtime_config import RuntimeConfigService
from app.modules.system.schemas import ConfigTestRequest, ConfigTestResponse

SUPPORTED_CONFIG_TEST_PROFILES = {
    AMAP_CONFIG_PROFILE,
    HIFLEET_CONFIG_PROFILE,
    ES_REALTIME_CONFIG_PROFILE,
    ES_HISTORY_CONFIG_PROFILE,
}


def _safe_message(prefix: str, exc: Exception | str) -> str:
    text = str(exc or "").replace("\r", " ").replace("\n", " ").strip()
    if not text:
        text = "未知错误"
    for keyword in ("password", "token", "key", "secret"):
        text = re.sub(
            rf"(?i)({keyword}\s*[:=]\s*)([^,\s;\"']+)",
            r"\1***",
            text,
        )
    text = text[:240]
    return f"{prefix}: {text}"


class ConfigTestService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.runtime_config = RuntimeConfigService(db)
        self.repo = SystemConfigRepository(db)

    async def test_profile(self, profile_code: str, payload: ConfigTestRequest) -> ConfigTestResponse:
        _ = payload
        profile_code_clean = (profile_code or "").strip().upper()
        if profile_code_clean not in SUPPORTED_CONFIG_TEST_PROFILES:
            raise ValidationError(f"不支持的 profile_code: {profile_code_clean}")

        tested_at = datetime.utcnow()
        status_code, message = await self._run_test(profile_code_clean)
        affected_config_count = await self.repo.update_test_result_by_profile(
            profile_code=profile_code_clean,
            status_code=status_code,
            message=message,
            tested_at=tested_at,
        )
        await self.db.commit()
        return ConfigTestResponse(
            profile_code=profile_code_clean,
            status_code=status_code,
            message=message,
            tested_at=tested_at,
            affected_config_count=affected_config_count,
        )

    async def _run_test(self, profile_code: str) -> tuple[str, str]:
        if profile_code == AMAP_CONFIG_PROFILE:
            return await self._test_amap()
        if profile_code == HIFLEET_CONFIG_PROFILE:
            return await self._test_hifleet()
        if profile_code == ES_REALTIME_CONFIG_PROFILE:
            return await self._test_es_realtime()
        if profile_code == ES_HISTORY_CONFIG_PROFILE:
            return await self._test_es_history()
        raise ValidationError(f"不支持的 profile_code: {profile_code}")

    async def _test_amap(self) -> tuple[str, str]:
        key = await self.runtime_config.get_value(
            AMAP_ROUTE_WEB_API_KEY,
            "",
            profile_code=AMAP_CONFIG_PROFILE,
        )
        if not (key or "").strip():
            return "FAILED", "高德 Web 服务 Key 未配置"

        client = AmapGeocodeClient(runtime_config=self.runtime_config)
        try:
            await client.reverse_geocode(longitude=120.5853, latitude=31.2989)
            return "SUCCESS", "高德逆地理编码测试成功"
        except Exception as exc:  # noqa: BLE001
            return "FAILED", _safe_message("高德逆地理编码测试失败", exc)

    async def _test_hifleet(self) -> tuple[str, str]:
        enabled = await self.runtime_config.get_bool(
            HIFLEET_ENABLED,
            default=False,
            profile_code=HIFLEET_CONFIG_PROFILE,
        )
        if not enabled:
            return "SKIPPED", "AMMS 路径服务未启用，跳过连接测试"

        manager = HifleetSessionManager(runtime_config=self.runtime_config)
        try:
            await manager.ensure_session(force_login=True)
            return "SUCCESS", "AMMS 登录测试成功"
        except Exception as exc:  # noqa: BLE001
            return "FAILED", _safe_message("AMMS 登录测试失败", exc)

    async def _test_es_realtime(self) -> tuple[str, str]:
        client = RealtimeEsClient(runtime_config=self.runtime_config)
        try:
            await client.ping()
            return "SUCCESS", "实时 ES 连接测试成功"
        except Exception as exc:  # noqa: BLE001
            return "FAILED", _safe_message("实时 ES 连接测试失败", exc)

    async def _test_es_history(self) -> tuple[str, str]:
        client = HistoryEsClient(runtime_config=self.runtime_config)
        try:
            await client.ping()
            return "SUCCESS", "历史 ES 连接测试成功"
        except Exception as exc:  # noqa: BLE001
            return "FAILED", _safe_message("历史 ES 连接测试失败", exc)
