from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.integrations.config_keys import AMAP_ROUTE_GEOMETRY_MODE
from scripts import seed_system_init
from scripts.seed_system_base import MENUS, ROLE_MENU_CODES, _should_preserve_existing_config_value


@pytest.mark.asyncio
async def test_seed_system_init_requires_explicit_profile(monkeypatch) -> None:
    monkeypatch.delenv("SEED_PROFILE", raising=False)

    with pytest.raises(RuntimeError, match="SEED_PROFILE must be set explicitly"):
        await seed_system_init.seed_system_init()


@pytest.mark.asyncio
async def test_seed_system_init_dispatches_profiles(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_production() -> None:
        calls.append("production")

    async def fake_local_demo() -> None:
        calls.append("local-demo")

    monkeypatch.setattr(seed_system_init, "seed_production_preset", fake_production)
    monkeypatch.setattr(seed_system_init, "seed_local_demo", fake_local_demo)

    await seed_system_init.seed_system_init(profile="production")
    await seed_system_init.seed_system_init(profile="local-demo")

    assert calls == ["production", "local-demo"]


def test_system_base_preserves_existing_non_empty_config_values() -> None:
    config = SimpleNamespace(config_key="HIFLEET_ENABLED", config_value="true")
    config_item = {
        "config_key": "HIFLEET_ENABLED",
        "config_value": "false",
        "sensitive_flag": 0,
    }

    assert _should_preserve_existing_config_value(
        config=config,
        config_item=config_item,
        preserve_existing_config_values=True,
    )


def test_system_base_upgrades_legacy_route_geometry_fallback() -> None:
    config = SimpleNamespace(
        config_key=AMAP_ROUTE_GEOMETRY_MODE,
        config_value="fallback",
    )
    config_item = {
        "config_key": AMAP_ROUTE_GEOMETRY_MODE,
        "config_value": "real",
        "sensitive_flag": 0,
    }

    assert not _should_preserve_existing_config_value(
        config=config,
        config_item=config_item,
        preserve_existing_config_values=True,
    )


def test_system_base_includes_rate_estimator_menu() -> None:
    menu_by_code = {item["menu_code"]: item for item in MENUS}

    assert menu_by_code["ANALYSIS_RATE_ESTIMATOR"]["route_path"] == "/analysis/rate-estimator"
    assert "ANALYSIS_RATE_ESTIMATOR" in ROLE_MENU_CODES["OPS_ANALYST"]
