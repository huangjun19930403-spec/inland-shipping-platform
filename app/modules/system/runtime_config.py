"""system 运行时配置读取服务。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.system.repository import SystemConfigRepository


@dataclass(frozen=True)
class RuntimeConfigResolvedValue:
    key: str
    profile_code: str | None
    value: str | None
    source: str
    sensitive_flag: int = 0


class RuntimeConfigService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = SystemConfigRepository(db)

    async def resolve_value(
        self,
        key: str,
        default: str | None = None,
        *,
        profile_code: str | None = None,
    ) -> RuntimeConfigResolvedValue:
        key_clean = (key or "").strip()
        profile_clean = (profile_code or "").strip() or None

        if not key_clean:
            return RuntimeConfigResolvedValue(
                key="",
                profile_code=profile_clean,
                value=default,
                source="DEFAULT" if default is not None else "EMPTY",
                sensitive_flag=0,
            )

        row = await self.repo.get_config_for_runtime(key_clean, profile_code=profile_clean)
        if row is not None and row.config_value != "":
            return RuntimeConfigResolvedValue(
                key=key_clean,
                profile_code=profile_clean,
                value=row.config_value,
                source="DB",
                sensitive_flag=int(row.sensitive_flag or 0),
            )

        if hasattr(settings, key_clean):
            settings_value = getattr(settings, key_clean)
            return RuntimeConfigResolvedValue(
                key=key_clean,
                profile_code=profile_clean,
                value=str(settings_value),
                source="ENV",
                sensitive_flag=0,
            )

        return RuntimeConfigResolvedValue(
            key=key_clean,
            profile_code=profile_clean,
            value=default,
            source="DEFAULT" if default is not None else "EMPTY",
            sensitive_flag=0,
        )

    async def get_value(
        self,
        key: str,
        default: str | None = None,
        *,
        profile_code: str | None = None,
    ) -> str | None:
        resolved = await self.resolve_value(key, default, profile_code=profile_code)
        return resolved.value

    async def get_bool(
        self,
        key: str,
        default: bool = False,
        *,
        profile_code: str | None = None,
    ) -> bool:
        resolved = await self.resolve_value(key, None, profile_code=profile_code)
        raw_value = resolved.value
        if raw_value is None:
            return default

        normalized = raw_value.strip().lower()
        true_values = {"true", "1", "yes", "y", "on", "enabled"}
        false_values = {"false", "0", "no", "n", "off", "disabled"}

        if normalized in true_values:
            return True
        if normalized in false_values:
            return False
        return default

    async def get_int(
        self,
        key: str,
        default: int = 0,
        *,
        profile_code: str | None = None,
    ) -> int:
        resolved = await self.resolve_value(key, None, profile_code=profile_code)
        raw_value = resolved.value
        if raw_value is None:
            return default
        try:
            return int(str(raw_value).strip())
        except (TypeError, ValueError):
            return default

    async def get_float(
        self,
        key: str,
        default: float = 0.0,
        *,
        profile_code: str | None = None,
    ) -> float:
        resolved = await self.resolve_value(key, None, profile_code=profile_code)
        raw_value = resolved.value
        if raw_value is None:
            return default
        try:
            return float(str(raw_value).strip())
        except (TypeError, ValueError):
            return default

    async def get_json(
        self,
        key: str,
        default: Any = None,
        *,
        profile_code: str | None = None,
    ) -> Any:
        resolved = await self.resolve_value(key, None, profile_code=profile_code)
        raw_value = resolved.value
        if raw_value is None or raw_value == "":
            return default
        try:
            return json.loads(raw_value)
        except (TypeError, ValueError):
            return default

    async def get_group(
        self,
        group_code: str,
        *,
        profile_code: str | None = None,
        include_inactive: bool = False,
    ) -> dict[str, str]:
        group_code_clean = (group_code or "").strip()
        profile_clean = (profile_code or "").strip() or None
        if not group_code_clean:
            return {}

        rows = await self.repo.list_configs_by_group_for_runtime(
            group_code_clean,
            profile_code=profile_clean,
            include_inactive=include_inactive,
        )
        return {row.config_key: row.config_value for row in rows}
