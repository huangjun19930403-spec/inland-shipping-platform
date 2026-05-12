"""Local demo/debug seed entrypoint.

This entrypoint is intentionally strict: it fully resets a local database,
loads production presets, imports local private integration config, verifies
the real external integrations, and only then creates demo data.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.integrations.config_keys import (
    AMAP_CONFIG_PROFILE,
    AMAP_JS_API_KEY,
    AMAP_ROUTE_GEOMETRY_MODE,
    AMAP_ROUTE_WEB_API_KEY,
    AMAP_SECURITY_JS_CODE,
    COS_ACCESS_KEY,
    COS_BUCKET_NAME,
    COS_ENABLED,
    COS_ENDPOINT,
    COS_REGION,
    COS_SECRET_KEY,
    DASHSCOPE_API_KEY,
    ES_HISTORY_CONFIG_PROFILE,
    ES_HISTORY_INDEX_PREFIX,
    ES_HOST,
    ES_PASSWORD,
    ES_PORT,
    ES_R_HOST,
    ES_R_INDEX,
    ES_R_PASSWORD,
    ES_R_PORT,
    ES_R_USER,
    ES_REALTIME_CONFIG_PROFILE,
    ES_USER,
    HIFLEET_CONFIG_PROFILE,
    HIFLEET_ENABLED,
    HIFLEET_PASSWORD,
    HIFLEET_USERNAME,
)
from app.models.base import Base
from app.models.system import SystemConfig
from app.modules.system.config_test import ConfigTestService
from app.modules.system.schemas import ConfigTestRequest
from scripts.purge_legacy_e2e_data import purge_legacy_e2e_data
from scripts.seed_analysis_samples import seed_analysis_samples
from scripts.seed_audit_samples import seed_audit_samples
from scripts.seed_foundation_samples import seed_foundation_samples
from scripts.seed_freight_samples import seed_freight_samples
from scripts.seed_local_private_config import seed_local_private_config
from scripts.seed_production_preset import seed_production_preset
from scripts.seed_route_samples import seed_route_samples
from scripts.seed_vessel_samples import seed_vessel_samples
from scripts.verify_local_acceptance import verify


LOCAL_DEMO_ENVIRONMENTS = {"local", "dev", "development", "test", "testing"}
LOCAL_DATABASE_HOSTS = {"", "localhost", "127.0.0.1", "::1", "0.0.0.0"}

LOCAL_DEMO_REQUIRED_NON_EMPTY_CONFIG_KEYS = {
    AMAP_ROUTE_WEB_API_KEY,
    AMAP_JS_API_KEY,
    AMAP_SECURITY_JS_CODE,
    DASHSCOPE_API_KEY,
    COS_BUCKET_NAME,
    COS_REGION,
    COS_ENDPOINT,
    COS_ACCESS_KEY,
    COS_SECRET_KEY,
    ES_R_HOST,
    ES_R_PORT,
    ES_R_USER,
    ES_R_PASSWORD,
    ES_R_INDEX,
    ES_HOST,
    ES_PORT,
    ES_USER,
    ES_PASSWORD,
    ES_HISTORY_INDEX_PREFIX,
    HIFLEET_USERNAME,
    HIFLEET_PASSWORD,
}

LOCAL_DEMO_CONFIG_TEST_PROFILES = (
    AMAP_CONFIG_PROFILE,
    HIFLEET_CONFIG_PROFILE,
    ES_REALTIME_CONFIG_PROFILE,
    ES_HISTORY_CONFIG_PROFILE,
)


def _assert_local_demo_reset_safe() -> None:
    app_env = (settings.APP_ENV or "").strip().lower()
    if app_env not in LOCAL_DEMO_ENVIRONMENTS:
        raise RuntimeError(
            "local demo seed can only reset a local/dev/test environment "
            f"(current APP_ENV={settings.APP_ENV!r})"
        )

    db_url = make_url(settings.DATABASE_URL)
    if db_url.drivername.startswith("sqlite"):
        return

    host = (db_url.host or "").strip().lower()
    if host not in LOCAL_DATABASE_HOSTS and not host.endswith(".local"):
        raise RuntimeError(
            "local demo seed refuses to reset a non-local database "
            f"(host={host or 'unknown'})"
        )


async def reset_local_database() -> None:
    _assert_local_demo_reset_safe()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    print("local demo database reset completed")


def _blank_keys(config_values: dict[str, str], keys: Iterable[str]) -> list[str]:
    return sorted(key for key in keys if not str(config_values.get(key) or "").strip())


async def assert_local_demo_runtime_config() -> None:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(select(SystemConfig.config_key, SystemConfig.config_value))
        ).all()
        config_values = {key: value for key, value in rows}

    failures: list[str] = []
    missing = _blank_keys(config_values, LOCAL_DEMO_REQUIRED_NON_EMPTY_CONFIG_KEYS)
    if missing:
        failures.append(f"missing required local demo config values: {', '.join(missing)}")

    hifleet_enabled = str(config_values.get(HIFLEET_ENABLED) or "").strip().lower()
    if hifleet_enabled != "true":
        failures.append("HIFLEET_ENABLED must be true for local-demo")

    route_mode = str(config_values.get(AMAP_ROUTE_GEOMETRY_MODE) or "").strip().lower()
    if route_mode != "real":
        failures.append("ROUTE_GEOMETRY_MODE must be real for local-demo")

    cos_enabled = str(config_values.get(COS_ENABLED) or "").strip().lower()
    if cos_enabled != "true":
        failures.append("COS_ENABLED must be true for local-demo")

    if failures:
        raise RuntimeError("; ".join(failures))


async def run_external_connection_tests() -> None:
    failures: list[str] = []
    async with AsyncSessionLocal() as session:
        service = ConfigTestService(session)
        for profile_code in LOCAL_DEMO_CONFIG_TEST_PROFILES:
            result = await service.test_profile(profile_code, ConfigTestRequest())
            print(f"config test {profile_code}: {result.status_code} {result.message}")
            if result.status_code != "SUCCESS":
                failures.append(f"{profile_code}: {result.message}")

    if failures:
        raise RuntimeError("local demo external config tests failed: " + "; ".join(failures))


async def run_local_acceptance() -> None:
    results = await verify()
    failed = [item for item in results if not item.ok]
    for item in results:
        status = "OK" if item.ok else "FAIL"
        print(f"[{status}] {item.name}: {item.detail}")
    if failed:
        raise RuntimeError(
            "local demo acceptance failed: "
            + "; ".join(f"{item.name}={item.detail}" for item in failed[:10])
        )


async def seed_local_demo() -> None:
    os.environ.setdefault("SEED_PROFILE", "local-demo")
    await reset_local_database()
    await seed_production_preset()
    await seed_local_private_config(
        source="auto",
        create_vault_from_env=True,
        require_values=True,
    )
    await assert_local_demo_runtime_config()
    await run_external_connection_tests()
    await seed_foundation_samples()
    await purge_legacy_e2e_data()
    await seed_vessel_samples()
    await seed_freight_samples()
    await seed_analysis_samples()
    await seed_audit_samples()
    await seed_route_samples()
    await run_local_acceptance()


if __name__ == "__main__":
    asyncio.run(seed_local_demo())
