from __future__ import annotations

import inspect

import app.modules.route.service as compatibility_service
from app.modules.route.services import (
    ShippingRoutePlanService,
    ShippingRoutePlanStructureService,
    ShippingRouteService,
)
from app.modules.route.services.common import _line_string_points, _track_status


def test_route_service_compatibility_exports_remain_available() -> None:
    assert compatibility_service.ShippingRouteService is ShippingRouteService
    assert compatibility_service.ShippingRoutePlanService is ShippingRoutePlanService
    assert compatibility_service.ShippingRoutePlanStructureService is ShippingRoutePlanStructureService
    assert compatibility_service._line_string_points is _line_string_points
    assert compatibility_service._track_status is _track_status


def test_route_service_implementation_is_split_by_responsibility() -> None:
    assert inspect.getmodule(ShippingRouteService).__name__.endswith("route_crud_service")
    assert inspect.getmodule(ShippingRoutePlanService).__name__.endswith("route_plan_service")
    assert inspect.getmodule(ShippingRoutePlanStructureService).__name__.endswith("route_structure_service")

    for method_name in (
        "get_structure",
        "replace_structure",
        "generate_track_version",
        "enqueue_generate_track_version",
        "list_track_versions",
        "save_track_version",
        "set_current_track_version",
        "delete_track_version",
    ):
        assert hasattr(ShippingRoutePlanStructureService, method_name)
