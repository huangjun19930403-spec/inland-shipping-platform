from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from app.integrations.amap.route_client import AmapRouteClient
from app.integrations.config_keys import (
    AMAP_ROUTE_GEOMETRY_TIMEOUT_SECONDS,
    AMAP_ROUTE_WEB_API_KEY,
    HIFLEET_BASE_URL,
    HIFLEET_ROUTE_URL,
    HIFLEET_TIMEOUT_SECONDS,
)
from app.integrations.hifleet.client import HifleetRouteClient
from app.integrations.http.route_geometry_types import RouteGeometryQuery
from app.modules.route.service import _line_string_points, _to_point_response, _track_status


class FakeRuntimeConfig:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    async def get_value(self, key: str, default: str | None = None, *, profile_code: str | None = None) -> str | None:
        _ = profile_code
        return self.values.get(key, default)

    async def get_float(self, key: str, default: float = 0.0, *, profile_code: str | None = None) -> float:
        _ = profile_code
        return float(self.values.get(key, default))


class FakeHifleetSession:
    def __init__(self, transport: httpx.AsyncBaseTransport) -> None:
        self.transport = transport

    async def ensure_session(self, *, force_login: bool = False) -> None:
        _ = force_login

    async def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport)

    async def _default_headers(self) -> dict[str, str]:
        return {}

    @staticmethod
    def _version() -> str:
        return "test"

    @staticmethod
    def _decode_response_json(response: httpx.Response, context: str) -> dict:
        _ = context
        return response.json()

    def invalidate(self) -> None:
        pass


def route_query() -> RouteGeometryQuery:
    return RouteGeometryQuery(
        origin_lon=120.0,
        origin_lat=31.0,
        dest_lon=121.0,
        dest_lat=32.0,
        transport_mode="ROAD",
        segment_type="ROUTE_PLAN_SEGMENT",
    )


@pytest.mark.asyncio
async def test_amap_route_client_parses_polyline_distance_and_duration() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v5/direction/driving"
        return httpx.Response(
            200,
            json={
                "status": "1",
                "route": {
                    "paths": [
                        {
                            "distance": "12000",
                            "duration": "3600",
                            "steps": [
                                {"polyline": "120.0,31.0;120.5,31.5"},
                                {"polyline": "120.5,31.5;121.0,32.0"},
                            ],
                        }
                    ]
                },
            },
        )

    client = AmapRouteClient(
        runtime_config=FakeRuntimeConfig(
            {
                AMAP_ROUTE_WEB_API_KEY: "local-test-key",
                AMAP_ROUTE_GEOMETRY_TIMEOUT_SECONDS: "1",
            }
        ),
        transport=httpx.MockTransport(handler),
    )
    result = await client.generate(route_query())

    assert result.source == "amap"
    assert result.distance_km == 12
    assert result.estimated_duration_hour == 1
    assert result.geometry == {
        "type": "LineString",
        "coordinates": [[120.0, 31.0], [120.5, 31.5], [121.0, 32.0]],
    }


@pytest.mark.asyncio
async def test_hifleet_route_client_parses_mock_route_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/hifleetrouteapi/getNewRoute"
        return httpx.Response(
            200,
            json={
                "status": "success",
                "routeId": "hf-1",
                "distanceKm": 88.5,
                "durationHour": 7.25,
                "waypoints": [
                    {"lon": 120.0, "lat": 31.0},
                    {"lon": 120.4, "lat": 31.4},
                    {"lon": 121.0, "lat": 32.0},
                ],
            },
        )

    client = HifleetRouteClient(
        runtime_config=FakeRuntimeConfig(
            {
                HIFLEET_BASE_URL: "https://www.hifleet.com",
                HIFLEET_ROUTE_URL: "/hifleetrouteapi/getNewRoute",
                HIFLEET_TIMEOUT_SECONDS: "1",
            }
        ),
        session_manager=FakeHifleetSession(httpx.MockTransport(handler)),
    )
    result = await client.generate(route_query())

    assert result.source == "hifleet"
    assert result.provider_trace_id == "hf-1"
    assert result.distance_km == 88.5
    assert result.estimated_duration_hour == 7.25
    assert result.geometry["coordinates"] == [[120.0, 31.0], [120.4, 31.4], [121.0, 32.0]]


@pytest.mark.asyncio
async def test_hifleet_route_client_parses_nested_polyline_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/hifleetrouteapi/getNewRoute"
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "result": {
                        "geometry": {
                            "polyline": "120.0,31.0;120.3,31.2;121.0,32.0",
                        }
                    }
                },
            },
        )

    client = HifleetRouteClient(
        runtime_config=FakeRuntimeConfig(
            {
                HIFLEET_BASE_URL: "https://www.hifleet.com",
                HIFLEET_ROUTE_URL: "/hifleetrouteapi/getNewRoute",
                HIFLEET_TIMEOUT_SECONDS: "1",
            }
        ),
        session_manager=FakeHifleetSession(httpx.MockTransport(handler)),
    )
    result = await client.generate(route_query())

    assert result.geometry["coordinates"] == [[120.0, 31.0], [120.3, 31.2], [121.0, 32.0]]


def test_route_track_status_from_selected_segment_counts() -> None:
    assert _track_status(2, 2) == "READY"
    assert _track_status(2, 1) == "PARTIAL"
    assert _track_status(2, 0) == "NOT_GENERATED"
    assert _track_status(2, 1, failed_count=1) == "FAILED"


def test_line_string_points_deduplicates_invalid_coordinates() -> None:
    points = _line_string_points(
        {
            "type": "LineString",
            "coordinates": [[120, 31], [120, 31], ["bad", 31], [121, 32]],
        }
    )
    assert points == [[120.0, 31.0], [121.0, 32.0]]


def _route_point(**overrides):
    now = datetime.utcnow()
    values = {
        "id": 1,
        "plan_id": 10,
        "point_order": 1,
        "point_type_code": "MANUAL_POINT",
        "transport_node_id": None,
        "constraint_point_id": None,
        "manual_name": "手工点",
        "longitude": Decimal("120.10000000"),
        "latitude": Decimal("31.10000000"),
        "display_name": "手工点",
        "transport_mode_after_code": "WATER",
        "remark": "手工备注",
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_point_response_resolves_transport_node_coordinate_and_info() -> None:
    response = _to_point_response(
        _route_point(
            point_type_code="TRANSPORT_NODE",
            transport_node_id=88,
            manual_name=None,
            longitude=None,
            latitude=None,
            display_name="运输节点占位",
            remark=None,
        ),
        transport_node=SimpleNamespace(
            id=88,
            code="NODE_TEST",
            name="测试港口",
            node_type_code="PORT",
            address="测试地址",
            longitude=Decimal("121.20000000"),
            latitude=Decimal("32.20000000"),
        ),
    )

    assert response.longitude == Decimal("121.20000000")
    assert response.latitude == Decimal("32.20000000")
    assert response.resolved_name == "测试港口"
    assert response.resolved_code == "NODE_TEST"
    assert response.resolved_node_type_code == "PORT"
    assert response.resolved_address == "测试地址"


def test_point_response_resolves_constraint_point_coordinate_and_info() -> None:
    response = _to_point_response(
        _route_point(
            point_type_code="CONSTRAINT_POINT",
            constraint_point_id=66,
            manual_name=None,
            longitude=None,
            latitude=None,
            display_name="约束点占位",
            remark="节点备注",
        ),
        constraint_point=SimpleNamespace(
            id=66,
            code="LIMIT_TEST",
            name="测试桥区",
            constraint_type_code="BRIDGE",
            description="桥区限高",
            longitude=Decimal("122.30000000"),
            latitude=Decimal("33.30000000"),
        ),
    )

    assert response.longitude == Decimal("122.30000000")
    assert response.latitude == Decimal("33.30000000")
    assert response.resolved_name == "测试桥区"
    assert response.resolved_code == "LIMIT_TEST"
    assert response.resolved_node_type_code == "BRIDGE"
    assert response.resolved_address == "桥区限高"
