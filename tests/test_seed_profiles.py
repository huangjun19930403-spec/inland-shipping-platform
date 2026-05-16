from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.integrations.config_keys import AMAP_ROUTE_GEOMETRY_MODE
from scripts.seeds import cli as seed_cli
from scripts.seeds import profiles
from scripts.seeds.manifest import load_seed_manifest, validate_seed_manifest
from scripts.seeds.loaders.system_base import MENUS, ROLE_MENU_CODES, _should_preserve_existing_config_value


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read_seed_json(relative_path: str) -> list[dict]:
    return json.loads((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_seed_system_init_requires_explicit_profile(monkeypatch) -> None:
    monkeypatch.delenv("SEED_PROFILE", raising=False)

    with pytest.raises(RuntimeError, match="SEED_PROFILE must be set explicitly"):
        await seed_cli.seed_system_init()


@pytest.mark.asyncio
async def test_seed_system_init_dispatches_profiles(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_production() -> None:
        calls.append("production")

    async def fake_local_demo() -> None:
        calls.append("local-demo")

    monkeypatch.setattr(
        profiles,
        "PROFILE_RUNNERS",
        {
            "production": fake_production,
            "local-demo": fake_local_demo,
        },
    )

    await seed_cli.seed_system_init(profile="production")
    await seed_cli.seed_system_init(profile="local-demo")

    assert calls == ["production", "local-demo"]


def test_seed_profile_aliases_demo_to_local_demo(monkeypatch) -> None:
    monkeypatch.setenv("SEED_PROFILE", "demo")

    assert seed_cli.resolve_seed_profile() == "local-demo"


def test_production_seed_runner_does_not_import_demo_or_sample_layers() -> None:
    import scripts.seeds.production as production

    text = production.__loader__.get_source(production.__name__) or ""
    banned_tokens = [
        "seed_local_demo",
        "seed_foundation_samples",
        "seed_vessel_samples",
        "seed_freight_samples",
        "seed_route_samples",
        "seed_analysis_samples",
        "seed_audit_samples",
        "seed_experience_scenarios",
        "experience_seed",
    ]

    assert not [token for token in banned_tokens if token in text]


def test_production_seed_manifest_lists_result_data_files() -> None:
    manifest = load_seed_manifest()
    resources = {item["resource"]: item["path"] for item in manifest["resources"]}

    assert resources["navigation_channels"] == "scripts/seed_data/navigation/navigation_channels.json"
    assert resources["navigation_constraints"] == "scripts/seed_data/navigation_constraints/constraint_points.json"
    assert resources["commodity_standards"] == "scripts/seed_data/commodity/commodity_standards.json"
    assert resources["business_regions"] == "scripts/seed_data/address/business_regions.json"
    assert resources["transport_nodes"] == "scripts/seed_data/address/transport_nodes.json"
    assert resources["production_vessels"] == "scripts/seed_data/vessel/production_vessels.json"
    assert resources["tms_freights"] == "scripts/seed_data/freight/tms_freights.json"
    assert validate_seed_manifest()["profile"] == "production"


def test_production_seed_runner_orders_vessels_before_freights() -> None:
    from scripts.seeds.production import PRODUCTION_SEED_STEPS

    step_names = [name for name, _step in PRODUCTION_SEED_STEPS]

    assert step_names.index("transport_nodes") < step_names.index("production_vessels")
    assert step_names.index("production_vessels") < step_names.index("production_freights")


def test_demo_profile_runner_does_not_call_legacy_sample_scripts() -> None:
    demo_text = (PROJECT_ROOT / "scripts" / "seeds" / "demo" / "profile.py").read_text(encoding="utf-8")
    banned_tokens = [
        "seed_foundation_samples",
        "seed_vessel_samples",
        "seed_freight_samples",
        "seed_route_samples",
    ]

    assert not [token for token in banned_tokens if token in demo_text]


def test_demo_scenario_config_references_production_seed_data() -> None:
    config = json.loads(
        (PROJECT_ROOT / "scripts/seed_data/demo/demo_scenarios.json").read_text(encoding="utf-8")
    )
    nodes = {row["code"] for row in _read_seed_json("scripts/seed_data/address/transport_nodes.json")}
    regions = {row["code"] for row in _read_seed_json("scripts/seed_data/address/business_regions.json")}
    commodities = {
        row["code"] for row in _read_seed_json("scripts/seed_data/commodity/commodity_standards.json")
    }
    constraints = {
        row["point"]["code"]
        for row in _read_seed_json("scripts/seed_data/navigation_constraints/constraint_points.json")
    }

    assert set(config["nodes"].values()) <= nodes
    assert set(config["constraints"].values()) <= constraints
    assert sum(int(row["count"]) for row in config["scenarios"]) == 42
    assert {row["code"] for row in config["routes"]} == {
        "DEMO_ROUTE_TAICANG_WUHU",
        "DEMO_ROUTE_TAICANG_NANJING",
        "DEMO_ROUTE_CHANGXING_WUHU",
    }
    for route in config["routes"]:
        assert route["origin_region_code"] in regions
        assert route["destination_region_code"] in regions
        assert set(route["node_codes"]) <= nodes | constraints
        assert route["code"].startswith("DEMO_ROUTE_")
        assert route["plan_code"].startswith("DEMO_PLAN_")
        assert route["line_code"].startswith("DEMO_LINE_")
    for scenario in config["scenarios"]:
        assert scenario["origin_node_code"] in nodes
        assert scenario["destination_node_code"] in nodes
        assert set(scenario["commodity_codes"]) <= commodities


def test_demo_and_test_fixture_dictionary_items_exist() -> None:
    from scripts.seeds.loaders.builtin_dicts import BUILTIN_DICTS

    dict_items = {
        row["dict_code"]: {item["item_code"] for item in row["items"]}
        for row in BUILTIN_DICTS
    }

    assert {"LOCAL_DEMO", "TEST_FIXTURE"} <= dict_items["SOURCE_TYPE"]
    assert {"LOCAL_DEMO", "TEST_FIXTURE"} <= dict_items["ANALYSIS_SOURCE_LAYER"]
    assert {"LOCAL_DEMO", "TEST_FIXTURE"} <= dict_items["ROUTE_PLAN_TYPE"]


def test_test_profile_appends_only_test_fixtures() -> None:
    test_profile_text = (PROJECT_ROOT / "scripts" / "seeds" / "test" / "profile.py").read_text(encoding="utf-8")
    test_fixture_text = (PROJECT_ROOT / "scripts" / "seeds" / "test" / "fixtures.py").read_text(encoding="utf-8")
    test_config = json.loads(
        (PROJECT_ROOT / "scripts" / "seed_data" / "test" / "test_scenarios.json").read_text(encoding="utf-8")
    )

    assert "seed_production_preset" in test_profile_text
    assert "seed_test_fixture_overlay" in test_profile_text
    assert "TEST-FR-" in test_fixture_text
    assert "TEST_ROUTE_" in test_fixture_text
    assert test_config["source_type_code"] == "TEST_FIXTURE"
    assert test_config["freight"]["freight_no"].startswith("TEST-FR-")
    assert test_config["route"]["code"].startswith("TEST_ROUTE_")
    assert "FR-DEMO-" not in test_fixture_text
    assert "LOCAL_DEMO" not in test_fixture_text


def test_profile_vessel_limit_can_be_overridden_to_full(monkeypatch) -> None:
    from scripts.seeds.loaders import production_vessels

    rows = [
        {
            "source_type_code": "HIGH_VALUE_INLAND",
            "mmsi": "413000002",
            "ship_name": "AQUA-2",
            "capacity": {},
        },
        {
            "source_type_code": "TMS",
            "mmsi": "413000001",
            "ship_name": "测试船1",
            "capacity": {"deadweight_ton": 1000},
            "contacts": [{"contact_name": "张三"}],
        },
    ]

    monkeypatch.setenv("SEED_PROFILE", "test")
    monkeypatch.delenv("SEED_VESSEL_LIMIT", raising=False)
    assert len(production_vessels._profile_limited_rows(rows * 1000)) == 1500

    monkeypatch.setenv("SEED_VESSEL_LIMIT", "full")
    assert len(production_vessels._profile_limited_rows(rows)) == 2


def test_root_scripts_do_not_contain_seed_entrypoints() -> None:
    root_seed_files = sorted(
        path.name
        for path in (PROJECT_ROOT / "scripts").glob("seed_*.py")
    )

    assert root_seed_files == []


def test_admin_region_city_boundaries_cover_all_city_regions() -> None:
    regions = _read_seed_json("scripts/seed_data/admin_region/admin_region_raw.json")
    boundaries = _read_seed_json(
        "scripts/seed_data/admin_region/admin_region_boundary_city_raw.json"
    )

    city_codes = {row["adcode"] for row in regions if row.get("level") == "city"}
    boundary_city_codes = {row["adcode"] for row in boundaries if row.get("level") == "city"}

    assert len(regions) == 3244
    assert len(boundaries) == 404
    assert len(city_codes) == 370
    assert city_codes - boundary_city_codes == set()
    assert all(row.get("geometry_wkt") and row.get("bbox_json") for row in boundaries)


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


def test_system_base_uses_analysis_platform_information_architecture() -> None:
    menu_by_code = {item["menu_code"]: item for item in MENUS}
    visible_roots = [
        item
        for item in MENUS
        if item.get("visible_flag") == 1 and not item.get("parent_code")
    ]
    root_names = [item["menu_name"] for item in sorted(visible_roots, key=lambda item: item["sort_order"])]

    assert root_names == ["经营总览", "数据资产中心", "分析中心", "数据质量与治理", "系统管理"]
    assert menu_by_code["COMMODITY_STANDARDS"]["parent_code"] == "DATA_MASTER_GROUP"
    assert menu_by_code["FREIGHT_LIST"]["parent_code"] == "DATA_BUSINESS_GROUP"
    assert menu_by_code["VESSEL_AIS_SITUATION"]["parent_code"] == "ANALYSIS_SITUATION_GROUP"
    assert menu_by_code["FREIGHT_SUPPLY_DEMAND_FIT"]["parent_code"] == "ANALYSIS_OPERATION_GROUP"
    assert menu_by_code["FREIGHT_NORMALIZATION"]["parent_code"] == "AUDIT_ROOT"
    assert menu_by_code["SYSTEM_MENU"]["parent_code"] == "SYSTEM_SECURITY_GROUP"
    assert menu_by_code["FREIGHT_MANUAL_CREATE"]["visible_flag"] == 0
    assert menu_by_code["FREIGHT_MANUAL_CREATE"]["menu_name"] == "补录样本"
    assert menu_by_code["FREIGHT_SUPPLY_DEMAND_FIT"]["route_path"] == "/freight/supply-demand-fit"
    assert menu_by_code["FREIGHT_SUPPLY_DEMAND_FIT"]["permission_code"] == "VESSEL:READ"
    assert "FREIGHT_SUPPLY_DEMAND_FIT" in ROLE_MENU_CODES["DATA_STEWARD"]
    assert "FREIGHT_SUPPLY_DEMAND_FIT" in ROLE_MENU_CODES["OPS_ANALYST"]
    assert "FREIGHT_SUPPLY_DEMAND_FIT" not in ROLE_MENU_CODES["BUSINESS_INPUTTER"]
