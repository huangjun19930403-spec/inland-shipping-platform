"""Load local-only integration credentials into system_config.

The values are read from .env.local and process environment variables.  The
file is git-ignored, so real credentials can be used for local bootstrap
without entering the remote repository.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.integrations.config_keys import (
    AMAP_JS_API_KEY,
    AMAP_ROUTE_GEOMETRY_MODE,
    AMAP_ROUTE_GEOMETRY_TIMEOUT_SECONDS,
    AMAP_ROUTE_WEB_API_KEY,
    AMAP_SECURITY_JS_CODE,
    AI_PROVIDER,
    DASHSCOPE_API_KEY,
    DASHSCOPE_BASE_URL,
    DASHSCOPE_MODEL,
    DASHSCOPE_TIMEOUT_SECONDS,
    HIFLEET_ENABLED,
    HIFLEET_PASSWORD,
    HIFLEET_USERNAME,
)
from app.models.system import SystemConfig
from scripts.seed_system_base import SYSTEM_CONFIGS


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENV_FILE = PROJECT_ROOT / ".env.local"

LOCAL_PRIVATE_CONFIG_KEYS = {
    AMAP_ROUTE_WEB_API_KEY,
    AMAP_ROUTE_GEOMETRY_TIMEOUT_SECONDS,
    AMAP_ROUTE_GEOMETRY_MODE,
    AMAP_JS_API_KEY,
    AMAP_SECURITY_JS_CODE,
    AI_PROVIDER,
    DASHSCOPE_BASE_URL,
    DASHSCOPE_MODEL,
    DASHSCOPE_API_KEY,
    DASHSCOPE_TIMEOUT_SECONDS,
    HIFLEET_ENABLED,
    HIFLEET_USERNAME,
    HIFLEET_PASSWORD,
}

CONFIG_METADATA_BY_KEY = {item["config_key"]: item for item in SYSTEM_CONFIGS}


def _merged_local_values() -> dict[str, str]:
    values: dict[str, str] = {}
    if LOCAL_ENV_FILE.exists():
        for key, value in dotenv_values(LOCAL_ENV_FILE).items():
            if value is not None:
                values[key] = value

    for key in LOCAL_PRIVATE_CONFIG_KEYS:
        env_value = os.getenv(key)
        if env_value is not None:
            values[key] = env_value
    return values


def _normalize_config_value(key: str, value: str, value_type_code: str) -> str:
    value_clean = str(value).strip()
    if not value_clean:
        return ""

    if value_type_code == "BOOLEAN":
        normalized = value_clean.lower()
        if normalized in {"true", "1", "yes", "y", "on", "enabled"}:
            return "true"
        if normalized in {"false", "0", "no", "n", "off", "disabled"}:
            return "false"
        raise RuntimeError(f"invalid boolean local private config: {key}")

    if value_type_code == "INTEGER":
        try:
            return str(int(value_clean))
        except ValueError as exc:
            raise RuntimeError(f"invalid integer local private config: {key}") from exc

    if value_type_code == "FLOAT":
        try:
            return str(float(value_clean))
        except ValueError as exc:
            raise RuntimeError(f"invalid float local private config: {key}") from exc

    return value_clean


async def seed_local_private_config() -> None:
    local_values = _merged_local_values()
    target_values = {
        key: value for key, value in local_values.items() if key in LOCAL_PRIVATE_CONFIG_KEYS
    }
    if not target_values:
        print("seed_local_private_config skipped: no local private values found")
        return

    async with AsyncSessionLocal() as session:
        now = datetime.now(timezone.utc)
        applied_keys: list[str] = []

        for key, raw_value in sorted(target_values.items()):
            metadata = CONFIG_METADATA_BY_KEY.get(key)
            if metadata is None:
                continue

            value = _normalize_config_value(key, raw_value, metadata["value_type_code"])
            config = await session.scalar(
                select(SystemConfig).where(SystemConfig.config_key == key)
            )
            if config is None:
                config = SystemConfig(
                    config_key=key,
                    config_name=metadata["config_name"],
                    config_value=value,
                    value_type_code=metadata["value_type_code"],
                    config_group_code=metadata["config_group_code"],
                    config_profile_code=metadata["config_profile_code"],
                    sensitive_flag=metadata["sensitive_flag"],
                    encrypted_flag=metadata["encrypted_flag"],
                    editable_flag=metadata["editable_flag"],
                    sort_order=metadata["sort_order"],
                    config_status_code=metadata["config_status_code"],
                    last_test_status_code=None,
                    last_test_message=None,
                    last_tested_at=None,
                    description=metadata["description"],
                    updated_by=None,
                    updated_at=now,
                    created_at=now,
                )
                session.add(config)
            else:
                config.config_value = value
                config.value_type_code = metadata["value_type_code"]
                config.config_group_code = metadata["config_group_code"]
                config.config_profile_code = metadata["config_profile_code"]
                config.sensitive_flag = metadata["sensitive_flag"]
                config.encrypted_flag = metadata["encrypted_flag"]
                config.editable_flag = metadata["editable_flag"]
                config.config_status_code = "ACTIVE"
                config.updated_at = now

            applied_keys.append(key)

        await session.commit()

    print(f"seed_local_private_config completed: applied={len(applied_keys)}")


if __name__ == "__main__":
    asyncio.run(seed_local_private_config())
