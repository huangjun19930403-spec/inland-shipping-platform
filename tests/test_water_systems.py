from __future__ import annotations

import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

from main import app
from app.modules.vessel.ais.service import VesselAisService
from app.modules.vessel.service import _WaterSystemBoundary, _build_water_system_boundary_grid
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
    assert "VESSEL_WATER_SYSTEM_SITUATION" not in menu_by_code
    assert menu_by_code["VESSEL_NODE_ROUTE_ANALYSIS"]["sort_order"] == 2

    assert "ADDRESS_WATER_SYSTEMS" in ROLE_MENU_CODES["DATA_STEWARD"]
    assert "ADDRESS_WATER_SYSTEMS" in ROLE_MENU_CODES["OPS_ANALYST"]
    assert "ADDRESS_WATER_SYSTEMS" in ROLE_MENU_CODES["BUSINESS_INPUTTER"]
    assert "VESSEL_WATER_SYSTEM_SITUATION" not in ROLE_MENU_CODES["DATA_STEWARD"]
    assert "VESSEL_WATER_SYSTEM_SITUATION" not in ROLE_MENU_CODES["OPS_ANALYST"]

    for role_code, menu_codes in ROLE_MENU_CODES.items():
        visible_codes = set(menu_codes)
        for menu_code in visible_codes:
            parent_code = menu_by_code.get(menu_code, {}).get("parent_code")
            if parent_code:
                assert parent_code in visible_codes, f"{role_code}:{menu_code} missing parent {parent_code}"


def test_embedded_water_system_seed_data_has_expected_counts_and_geometry() -> None:
    rows = load_embedded_water_system_rows()
    scope_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    ais_counts: dict[str, int] = {}
    for row in rows:
        assert not row["water_system_code"].startswith(
            ("WS-L1-", "WS-L2-", "WS-L3-", "WS-L4-", "WS-L5-", "WS-L6-", "WS-L7-")
        )
        assert row["navigation_category_code"] in {"MAIN_RIVER", "TRIBUTARY", "CANAL", "LAKE", "DELTA_NETWORK"}
        scope_counts[row["navigation_scope_code"]] = scope_counts.get(row["navigation_scope_code"], 0) + 1
        category_counts[row["navigation_category_code"]] = category_counts.get(row["navigation_category_code"], 0) + 1
        ais_counts[row["ais_situation_scope"]] = ais_counts.get(row["ais_situation_scope"], 0) + 1
        if row["geometry_status_code"] == "AVAILABLE":
            assert row["geometry_json"]["type"] == "MultiPolygon"
            assert row["boundary_paths_low"]
            assert row["boundary_paths_medium"]
            assert row["boundary_paths_high"]
        else:
            assert row["navigation_scope_code"] == "MISSING"
            assert row["ais_situation_scope"] == "EXCLUDED"
            assert not row["boundary_paths_low"]

    by_code = {row["water_system_code"]: row for row in rows}
    by_name = {row["water_system_name"]: row for row in rows}
    assert len(rows) == 120
    assert sum(1 for row in rows if row["geometry_status_code"] == "AVAILABLE") == 111
    assert scope_counts == {"CORE": 12, "IMPORTANT": 79, "WATER_AREA": 18, "REVIEW": 2, "MISSING": 9}
    assert category_counts == {"MAIN_RIVER": 16, "TRIBUTARY": 40, "CANAL": 31, "LAKE": 18, "DELTA_NETWORK": 15}
    assert ais_counts == {"INCLUDED": 109, "EXCLUDED": 11}
    assert {row["water_system_code"] for row in rows} >= {"WS-YANGTZE", "WS-GRAND-CANAL", "WS-TAIHU", "WS-FUCHUN-RIVER", "WS-BAIYANGDIAN"}
    assert by_code["WS-YANGTZE"]["water_system_name"] == "长江干线"
    assert by_code["WS-XIJIANG"]["water_system_name"] == "西江航运干线"
    assert Decimal("113") < Decimal(str(by_code["WS-YANGTZE"]["display_center_longitude"])) < Decimal("116")
    assert Decimal("29") < Decimal(str(by_code["WS-YANGTZE"]["display_center_latitude"])) < Decimal("32")
    assert Decimal("125") < Decimal(str(by_name["松花江"]["display_center_longitude"])) < Decimal("128")
    assert Decimal("45") < Decimal(str(by_name["松花江"]["display_center_latitude"])) < Decimal("47")
    assert Decimal("119") < Decimal(str(by_name["太湖"]["display_center_longitude"])) < Decimal("121")
    assert Decimal("30") < Decimal(str(by_name["太湖"]["display_center_latitude"])) < Decimal("32")
    assert by_name["富春江"]["parent_water_system_code"] == "WS-QIANTANG-RIVER"
    assert by_name["富春江"]["ais_situation_scope"] == "INCLUDED"
    assert "富春江水库" not in by_name["富春江"]["source_names"]
    assert by_name["白洋淀"]["navigation_category_code"] == "LAKE"
    assert by_name["白洋淀"]["navigation_scope_code"] == "WATER_AREA"
    assert "新通扬运河" in by_name["通扬线"]["source_names"]
    assert "锡澄河" in by_name["锡澄运河"]["source_names"]
    assert "盐邵河" in by_name["盐邵线"]["source_names"]
    assert by_name["京杭运河"]["boundary_coordinate_system_code"] == "GCJ02"
    assert by_name["京杭运河"]["geometry_coordinate_system_code"] == "WGS84"
    assert by_name["京杭运河"]["display_center_longitude"] != by_name["京杭运河"]["center_longitude"]
    for name in ["淀山湖", "泖河", "横潦泾", "竖潦泾", "通吕运河", "九圩港"]:
        assert by_name[name]["geometry_status_code"] == "AVAILABLE"
        assert by_name[name]["ais_situation_scope"] == "INCLUDED"
    assert by_name["长湖申线—黄浦江—大浦线"]["geometry_union_status"] == "CARRIER_COMPOSITE"
    assert by_name["长湖申线—黄浦江—大浦线"]["match_confidence_code"] == "MEDIUM"
    assert by_name["苏申外港线—苏申内港线"]["source_feature_count"] >= 4
    assert {"黄浦江", "泖河", "浏河", "元和塘"}.issubset(
        set(by_name["苏申外港线—苏申内港线"]["source_names"])
    )
    assert {"曹娥江", "余姚江", "甬江", "杭甬运河"}.issubset(set(by_name["杭甬运河"]["source_names"]))
    assert "红旗塘" in by_name["杭申线"]["source_names"]
    assert "闸港" in by_name["杭平申线"]["source_names"]
    assert by_name["杭湖锡线"]["source_feature_count"] >= 4
    assert by_name["宿连航道相关水域"]["source_feature_count"] >= 1
    assert by_name["宿连航道相关水域"]["boundary_quality_code"] == "LOW_CONFIDENCE_CARRIER"
    assert by_name["南阳湖"]["navigation_category_code"] == "LAKE"
    assert by_name["黄墩湖"]["navigation_scope_code"] == "WATER_AREA"
    assert by_code["WS-YAMEN-WATERWAY"]["ais_situation_scope"] == "EXCLUDED"
    assert by_code["WS-SHUNDE-WATERWAY"]["ais_situation_scope"] == "EXCLUDED"
    assert by_code["WS-YAMEN-WATERWAY"]["geometry_status_code"] == "AVAILABLE"
    assert by_code["WS-SHUNDE-WATERWAY"]["geometry_status_code"] == "AVAILABLE"
    for name in ["乌苏里江", "太浦河", "望虞河", "德胜河", "蕉门水道", "横门水道", "小榄水道", "虎跳门水道"]:
        assert by_name[name]["geometry_status_code"] == "AVAILABLE"
        assert by_name[name]["ais_situation_scope"] == "INCLUDED"
    assert by_name["合裕线"]["geometry_status_code"] == "AVAILABLE"
    assert by_name["合裕线"]["boundary_quality_code"] == "LOW_CONFIDENCE_CARRIER"
    assert {"南淝河", "巢湖", "裕溪河"}.issubset(set(by_name["合裕线"]["source_names"]))
    missing_names = {
        "苏南运河", "苏北运河", "江汉运河", "沙颍河",
        "徐宿连通道", "赵家沟", "大芦线", "大浦线",
    }
    assert all(by_name[name]["navigation_scope_code"] == "MISSING" for name in missing_names)
    assert {"杨林塘", "通榆运河"}.isdisjoint(by_name)

    assignment_path = Path("docs/water_system_source_assignment_v5.jsonl")
    assert assignment_path.exists()
    assert sum(1 for _ in assignment_path.open(encoding="utf-8")) == 39431


def test_default_water_system_seed_uses_embedded_rows_without_zip_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_resolve_source_path(source: str) -> Path:
        raise AssertionError(f"default seed should not resolve zip source: {source}")

    monkeypatch.setattr(seed_water_systems_module, "_resolve_source_path", fail_resolve_source_path)
    rows = seed_water_systems_module._seed_rows_from_embedded((1, 2))
    counts: dict[int, int] = {}
    for row in rows:
        for level in row.get("source_levels") or []:
            if int(level) in {1, 2}:
                counts[int(level)] = counts.get(int(level), 0) + 1

    assert rows
    assert all(row["source_levels"] for row in rows)
    assert set(counts).issubset({1, 2})


def test_seed_water_systems_reads_level_1_to_7_from_source_zip() -> None:
    if not SOURCE_ZIP.exists():
        pytest.skip("local revier.zip is not available")

    expected_counts = {1: 234, 2: 285, 3: 608, 4: 1407, 5: 4541, 6: 5175, 7: 27181}
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
    canal = _water_boundary("canal", 4, Decimal("3"), 0, 0, 3, 3, category="CANAL")
    grid_index = _build_water_system_boundary_grid([big, small, canal])

    matches = service._resolve_current_water_systems_from_boundaries(
        Decimal("1"),
        Decimal("1"),
        [big, small],
        grid_index,
    )
    assert [match.water_system_code for match in matches] == ["small"]

    priority_matches = service._resolve_current_water_systems_from_boundaries(
        Decimal("1"),
        Decimal("1"),
        [big, small, canal],
        grid_index,
    )
    assert [match.water_system_code for match in priority_matches] == ["canal"]

    filtered = service._resolve_current_water_systems_from_boundaries(
        Decimal("1"),
        Decimal("1"),
        [big],
        grid_index,
    )
    assert [match.water_system_code for match in filtered] == ["big"]


def test_water_system_match_uses_near_boundary_fallback() -> None:
    service = VesselAisService.__new__(VesselAisService)
    boundary = _water_boundary("lake", 4, Decimal("1"), 116.0, 29.0, 116.01, 29.01, category="LAKE")

    matches = service._resolve_current_water_systems_from_boundaries(
        Decimal("116.014"),
        Decimal("29.005"),
        [boundary],
        _build_water_system_boundary_grid([boundary]),
    )

    assert [match.water_system_code for match in matches] == ["lake"]
    assert matches[0].current_water_system_source == "NEAR_BOUNDARY"
    assert matches[0].match_distance_m is not None
    assert matches[0].match_distance_m <= Decimal("5000")


def _water_boundary(
    code: str,
    level: int,
    area: Decimal,
    min_lng: float,
    min_lat: float,
    max_lng: float,
    max_lat: float,
    *,
    category: str = "MAIN_RIVER",
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
        parent_water_system_code=None,
        level=level,
        feature_type_code="RIVER",
        hydrology_period_code="UNKNOWN",
        salinity_type_code="UNKNOWN",
        water_boundary_type_code="STANDARD",
        navigation_category_code=category,
        navigation_scope_code="CORE",
        ais_situation_scope="INCLUDED",
        center_longitude=None,
        center_latitude=None,
        display_center_longitude=None,
        display_center_latitude=None,
        boundary_quality_code="HIGH_CONFIDENCE",
        geometry_coordinate_system_code="WGS84",
        boundary_coordinate_system_code="GCJ02",
        shape_area_degree=area,
        bbox=(min_lng, min_lat, max_lng, max_lat),
        bbox_area=(max_lng - min_lng) * (max_lat - min_lat),
        polygons=[[ring]],
        boundary_paths_by_precision=None,
    )
