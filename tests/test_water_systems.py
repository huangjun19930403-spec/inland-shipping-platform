from __future__ import annotations

import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

from main import app
from app.modules.vessel.ais.service import VesselAisService
from app.modules.vessel.service import _WaterSystemBoundary, _build_city_boundary_grid
from scripts import seed_water_systems as seed_water_systems_module
from scripts.seed_system_base import MENUS, ROLE_MENU_CODES
from scripts.seed_water_systems import (
    LEVEL_LAYER_NAMES,
    _feature_codes,
    _read_layer_features,
    load_embedded_water_system_rows,
)


SOURCE_ZIP = Path("/Users/hj/Documents/河道数据/revier.zip")


def test_water_system_openapi_routes_are_read_only() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/address/water-systems/summary": {"get"},
        "/api/v1/address/water-systems": {"get"},
        "/api/v1/address/water-systems/{water_system_code}": {"get"},
        "/api/v1/address/water-systems/{water_system_code}/boundary": {"get"},
        "/api/v1/vessels/ais/water-system-situation": {"get"},
        "/api/v1/vessels/ais/water-system-vessels": {"get"},
        "/api/v1/vessels/ais/water-system-boundaries": {"get"},
    }

    for path, methods in expected.items():
        assert path in paths
        assert methods.issubset(paths[path])

    write_methods = {"post", "put", "patch", "delete"}
    for path, operations in paths.items():
        if path.startswith("/api/v1/address/water-systems"):
            assert not write_methods.intersection(operations)

    page_schema_ref = paths["/api/v1/address/water-systems"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    page_schema = app.openapi()["components"]["schemas"][page_schema_ref.rsplit("/", 1)[-1]]
    list_schema_ref = page_schema["properties"]["items"]["items"]["$ref"]
    list_schema = app.openapi()["components"]["schemas"][list_schema_ref.rsplit("/", 1)[-1]]
    assert "geometry_json" not in list_schema["properties"]
    assert "bbox_min_lng" not in list_schema["properties"]
    assert "source_object_id" not in list_schema["properties"]
    boundary_param_names = {
        item["name"] for item in paths["/api/v1/vessels/ais/water-system-boundaries"]["get"].get("parameters", [])
    }
    assert "water_system_name" in boundary_param_names


def test_water_system_backend_menus_are_initialized_for_visible_routes() -> None:
    menu_by_code = {item["menu_code"]: item for item in MENUS}

    assert menu_by_code["ADDRESS_WATER_SYSTEMS"] == {
        "menu_code": "ADDRESS_WATER_SYSTEMS",
        "menu_name": "水系基础数据",
        "menu_type_code": "MENU",
        "parent_code": "DICTIONARY_ROOT",
        "route_path": "/address/water-systems",
        "component_path": "modules/address/pages/WaterSystemListPage",
        "icon": "MapLocation",
        "sort_order": 5,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    }
    assert menu_by_code["VESSEL_WATER_SYSTEM_SITUATION"] == {
        "menu_code": "VESSEL_WATER_SYSTEM_SITUATION",
        "menu_name": "水系态势",
        "menu_type_code": "MENU",
        "parent_code": "VESSEL_ANALYSIS_GROUP",
        "route_path": "/vessels/water-system-situation",
        "component_path": "modules/vessel/pages/VesselWaterSystemSituationPage",
        "icon": "MapLocation",
        "sort_order": 2,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    }
    assert menu_by_code["VESSEL_NODE_ROUTE_ANALYSIS"]["sort_order"] == 3

    assert "ADDRESS_WATER_SYSTEMS" in ROLE_MENU_CODES["DATA_STEWARD"]
    assert "ADDRESS_WATER_SYSTEMS" in ROLE_MENU_CODES["OPS_ANALYST"]
    assert "ADDRESS_WATER_SYSTEMS" in ROLE_MENU_CODES["BUSINESS_INPUTTER"]
    assert "VESSEL_WATER_SYSTEM_SITUATION" in ROLE_MENU_CODES["DATA_STEWARD"]
    assert "VESSEL_WATER_SYSTEM_SITUATION" in ROLE_MENU_CODES["OPS_ANALYST"]

    for role_code, menu_codes in ROLE_MENU_CODES.items():
        visible_codes = set(menu_codes)
        for menu_code in visible_codes:
            parent_code = menu_by_code.get(menu_code, {}).get("parent_code")
            if parent_code:
                assert parent_code in visible_codes, f"{role_code}:{menu_code} missing parent {parent_code}"


def test_embedded_water_system_seed_data_has_expected_counts_and_geometry() -> None:
    rows = load_embedded_water_system_rows()
    counts: dict[int, int] = {}
    for row in rows:
        level = int(row["water_level"])
        counts[level] = counts.get(level, 0) + 1
        assert row["geometry_json"]["type"] in {"Polygon", "MultiPolygon"}
        assert row["boundary_paths_low"]
        assert row["boundary_paths_medium"]
        assert row["boundary_paths_high"]

    assert len(rows) == 2534
    assert counts == {1: 234, 2: 285, 3: 608, 4: 1407}


def test_default_water_system_seed_uses_embedded_rows_without_zip_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_resolve_source_path(source: str) -> Path:
        raise AssertionError(f"default seed should not resolve zip source: {source}")

    monkeypatch.setattr(seed_water_systems_module, "_resolve_source_path", fail_resolve_source_path)
    rows = seed_water_systems_module._seed_rows_from_embedded((1, 2))
    counts: dict[int, int] = {}
    for row in rows:
        level = int(row["water_level"])
        counts[level] = counts.get(level, 0) + 1

    assert counts == {1: 234, 2: 285}


def test_seed_water_systems_reads_level_1_to_4_from_source_zip() -> None:
    if not SOURCE_ZIP.exists():
        pytest.skip("local revier.zip is not available")

    expected_counts = {1: 234, 2: 285, 3: 608, 4: 1407}
    with zipfile.ZipFile(SOURCE_ZIP) as zip_file:
        for level, layer_name in LEVEL_LAYER_NAMES.items():
            features = _read_layer_features(zip_file, layer_name)
            assert len(features) == expected_counts[level]
            assert all(feature.geometry.get("type") in {"Polygon", "MultiPolygon"} for feature in features)


def test_water_system_seed_parses_business_tags() -> None:
    assert _feature_codes("常年淡水双线河") == ("RIVER", "PERENNIAL", "FRESH", "DOUBLE_LINE_RIVER")
    assert _feature_codes("时令咸水湖") == ("LAKE", "SEASONAL", "SALINE", "WATER_BODY")
    assert _feature_codes("界河") == ("RIVER", "UNKNOWN", "UNKNOWN", "BOUNDARY_RIVER")


def test_water_system_match_selects_smallest_area_per_level_and_respects_filter() -> None:
    service = VesselAisService.__new__(VesselAisService)
    big = _water_boundary("big", 1, Decimal("10"), 0, 0, 4, 4)
    small = _water_boundary("small", 1, Decimal("1"), 0, 0, 2, 2)
    level_two = _water_boundary("level-two", 2, Decimal("3"), 0, 0, 3, 3)
    grid_index = _build_city_boundary_grid([big, small, level_two])

    matches = service._resolve_current_water_systems_from_boundaries(
        Decimal("1"),
        Decimal("1"),
        [big, small, level_two],
        grid_index,
    )
    assert {match.water_level: match.water_system_code for match in matches} == {
        1: "small",
        2: "level-two",
    }

    filtered = service._resolve_current_water_systems_from_boundaries(
        Decimal("1"),
        Decimal("1"),
        [big],
        grid_index,
    )
    assert [match.water_system_code for match in filtered] == ["big"]


def _water_boundary(
    code: str,
    level: int,
    area: Decimal,
    min_lng: float,
    min_lat: float,
    max_lng: float,
    max_lat: float,
) -> _WaterSystemBoundary:
    ring = [
        (min_lng, min_lat),
        (max_lng, min_lat),
        (max_lng, max_lat),
        (min_lng, max_lat),
        (min_lng, min_lat),
    ]
    return _WaterSystemBoundary(
        code=code,
        name=code,
        level=level,
        feature_type_code="RIVER",
        hydrology_period_code="UNKNOWN",
        salinity_type_code="UNKNOWN",
        water_boundary_type_code="STANDARD",
        center_longitude=None,
        center_latitude=None,
        shape_area_degree=area,
        bbox=(min_lng, min_lat, max_lng, max_lat),
        bbox_area=(max_lng - min_lng) * (max_lat - min_lat),
        polygons=[[ring]],
        boundary_paths_by_precision=None,
    )
