from __future__ import annotations

from decimal import Decimal

from main import app
from app.modules.vessel.service import (
    CURRENT_CHANNEL_SOURCE_NEAR_BOUNDARY,
    VesselService,
    _NavigationChannelBoundary,
    _build_channel_boundary_grid,
)
from scripts.seeds.loaders.navigation_channels import (
    BOUNDARY_COUNT,
    CHANNEL_COUNT,
    DATA_VERSION,
    NAVIGATION_CHANNEL_DATA_FILE,
    SEGMENT_COUNT,
    SOURCE_AUDIT_COUNT,
    load_navigation_channel_seed,
)
from scripts.seeds.loaders.system_base import MENUS, ROLE_MENU_CODES


def test_navigation_channel_openapi_replaces_legacy_routes() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/address/navigation-channels/summary": {"get"},
        "/api/v1/address/navigation-channels": {"get"},
        "/api/v1/address/navigation-channels/{channel_code}": {"get"},
        "/api/v1/address/navigation-channels/{channel_code}/boundary": {"get"},
        "/api/v1/address/navigation-channels/{channel_code}/segments": {"get"},
        "/api/v1/address/navigation-channels/{channel_code}/source-audit": {"get"},
        "/api/v1/vessels/ais/channel-situation": {"get"},
        "/api/v1/vessels/ais/channel-vessels": {"get"},
        "/api/v1/vessels/ais/channel-boundaries": {"get"},
    }
    for path, methods in expected.items():
        assert path in paths
        assert methods <= set(paths[path])
    assert not any("water-system" in path or "water-systems" in path for path in paths)


def test_navigation_channel_backend_menus_are_initialized_for_visible_routes() -> None:
    menu_by_code = {item["menu_code"]: item for item in MENUS}
    assert menu_by_code["ADDRESS_NAVIGATION_CHANNELS"] == {
        "menu_code": "ADDRESS_NAVIGATION_CHANNELS",
        "menu_name": "航道基础数据",
        "menu_type_code": "MENU",
        "parent_code": "ROUTE_REGION_FOUNDATION_GROUP",
        "route_path": "/address/navigation-channels",
        "component_path": "modules/address/pages/NavigationChannelListPage",
        "icon": "MapLocation",
        "sort_order": 3,
        "visible_flag": 1,
        "status_code": "ACTIVE",
    }
    assert "ADDRESS_NAVIGATION_CHANNELS" in ROLE_MENU_CODES["DATA_STEWARD"]
    assert "ADDRESS_NAVIGATION_CHANNELS" in ROLE_MENU_CODES["OPS_ANALYST"]
    assert "ADDRESS_NAVIGATION_CHANNELS" in ROLE_MENU_CODES["BUSINESS_INPUTTER"]


def test_navigation_channel_seed_is_final_business_seed() -> None:
    payload = load_navigation_channel_seed()
    records = payload["records"]
    audits = payload["excluded_source_audit"]
    assert DATA_VERSION == "revier_navigation_channel_v7"
    assert NAVIGATION_CHANNEL_DATA_FILE.name == "navigation_channels.json"
    assert NAVIGATION_CHANNEL_DATA_FILE.exists()
    assert len(records) == CHANNEL_COUNT
    assert sum(1 for item in records if item["boundary"]["geometry_status_code"] == "AVAILABLE") == BOUNDARY_COUNT
    assert sum(len(item["segments"]) for item in records) == SEGMENT_COUNT
    assert sum(len(item["source_audit"]) for item in records) + len(audits) == SOURCE_AUDIT_COUNT

    by_code = {item["channel"]["channel_code"]: item for item in records}
    names = {item["channel"]["channel_name"] for item in records}
    assert {"长江干线", "京杭运河", "合裕线", "长三角高等级航道网", "苏北运河"} <= names
    assert not {"太湖", "洪泽湖", "巢湖", "白洋淀"} & names
    assert by_code["NC-GRAND-CANAL"]["boundary"]["repair_status_code"] == "REVIEW_CORRIDOR"
    assert by_code["NC-HEYU-LINE"]["segments"][1]["segment_name"] == "巢湖通道"
    assert by_code["NC-YANGTZE"]["boundary"]["connectivity_status_code"] in {"CONNECTED", "REPAIRED", "PARTIAL"}
    assert any(audit["decision_code"] == "EXCLUDED_TOP_LEVEL_NATURAL_WATER_AREA" for audit in audits)


def test_channel_match_prefers_planning_level_and_near_boundary_fallback() -> None:
    service = VesselService.__new__(VesselService)
    large = _boundary("large", "区域重要航道", "REGIONAL_IMPORTANT", 0, (0, 0, 10, 10))
    core = _boundary("core", "核心航道", "NATIONAL_CORE", 10, (0, 0, 10, 10))
    grid_index = _build_channel_boundary_grid([large, core])

    matches = service._resolve_current_channels_from_boundaries(Decimal("1"), Decimal("1"), [large, core], grid_index)

    assert [match.channel_code for match in matches] == ["core"]

    near = _boundary("near", "修复走廊", "PROVINCIAL_HIGH_GRADE", 5, (0, 0, 1, 1))
    near_matches = service._resolve_current_channels_from_boundaries(
        Decimal("1.02"),
        Decimal("0.5"),
        [near],
        _build_channel_boundary_grid([near]),
    )

    assert [match.channel_code for match in near_matches] == ["near"]
    assert near_matches[0].current_channel_source == CURRENT_CHANNEL_SOURCE_NEAR_BOUNDARY


def _boundary(
    code: str,
    name: str,
    planning_level_code: str,
    display_priority: int,
    bbox: tuple[float, float, float, float],
) -> _NavigationChannelBoundary:
    min_lng, min_lat, max_lng, max_lat = bbox
    ring = [(min_lng, min_lat), (max_lng, min_lat), (max_lng, max_lat), (min_lng, max_lat), (min_lng, min_lat)]
    return _NavigationChannelBoundary(
        code=code,
        name=name,
        parent_channel_code=None,
        channel_type_code="CANAL",
        planning_level_code=planning_level_code,
        ais_scope_code="INCLUDED",
        center_longitude=Decimal(str((min_lng + max_lng) / 2)),
        center_latitude=Decimal(str((min_lat + max_lat) / 2)),
        display_center_longitude=Decimal(str((min_lng + max_lng) / 2)),
        display_center_latitude=Decimal(str((min_lat + max_lat) / 2)),
        boundary_quality_code="HIGH_CONFIDENCE",
        connectivity_status_code="CONNECTED",
        repair_status_code="NONE",
        geometry_coordinate_system_code="WGS84",
        boundary_coordinate_system_code="GCJ02",
        shape_area_degree=Decimal(str((max_lng - min_lng) * (max_lat - min_lat))),
        display_priority=display_priority,
        bbox=bbox,
        bbox_area=(max_lng - min_lng) * (max_lat - min_lat),
        polygons=[[ring]],
        boundary_paths_by_precision={"low": [ring]},
    )
