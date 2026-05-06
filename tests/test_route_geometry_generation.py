from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.core.exceptions import ValidationError
from app.integrations.amap.route_client import AmapRouteClient
from app.integrations.config_keys import (
    AMAP_ROUTE_GEOMETRY_TIMEOUT_SECONDS,
    AMAP_ROUTE_WEB_API_KEY,
    HIFLEET_BASE_URL,
    HIFLEET_ROUTE_URL,
    HIFLEET_TIMEOUT_SECONDS,
)
from app.integrations.hifleet.client import HifleetRouteClient
from app.integrations.http.route_geometry_types import RouteGeometryQuery, RouteGeometryResult
from app.modules.route.service import ShippingRouteLineService, _combine_line_strings, _track_status_from_success_count


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
        segment_type="ROUTE_LINE_SEGMENT",
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

    transport = httpx.MockTransport(handler)
    client = HifleetRouteClient(
        runtime_config=FakeRuntimeConfig(
            {
                HIFLEET_BASE_URL: "https://www.hifleet.com",
                HIFLEET_ROUTE_URL: "/hifleetrouteapi/getNewRoute",
                HIFLEET_TIMEOUT_SECONDS: "1",
            }
        ),
        session_manager=FakeHifleetSession(transport),
    )
    result = await client.generate(route_query())

    assert result.source == "hifleet"
    assert result.provider_trace_id == "hf-1"
    assert result.distance_km == 88.5
    assert result.estimated_duration_hour == 7.25
    assert result.geometry["coordinates"] == [[120.0, 31.0], [120.4, 31.4], [121.0, 32.0]]


def test_track_status_success_partial_and_failed() -> None:
    assert _track_status_from_success_count(2, 2) == "READY"
    assert _track_status_from_success_count(1, 2) == "PARTIAL"
    assert _track_status_from_success_count(0, 2) == "FAILED"


def test_combine_line_strings_deduplicates_segment_boundaries() -> None:
    combined = _combine_line_strings(
        [
            {"type": "LineString", "coordinates": [[120, 31], [120.5, 31.5]]},
            {"type": "LineString", "coordinates": [[120.5, 31.5], [121, 32]]},
        ]
    )
    assert combined == {
        "type": "LineString",
        "coordinates": [[120.0, 31.0], [120.5, 31.5], [121.0, 32.0]],
    }


class FakeRouteLineRepository:
    def __init__(self, *, line, nodes, segments) -> None:
        self.line = line
        self.nodes = nodes
        self.segments = segments
        self.track = None

    async def get_line_by_id(self, line_id: int):
        return self.line if self.line.id == line_id else None

    async def list_nodes(self, line_id: int):
        _ = line_id
        return self.nodes

    async def list_segments(self, line_id: int):
        _ = line_id
        return self.segments

    async def upsert_track(self, line_id: int, values: dict):
        self.track = SimpleNamespace(id=1, line_id=line_id, **values)
        return self.track


class FakeDbSession:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


def _line_service_for_segments(segment_count: int = 2):
    line = SimpleNamespace(id=10, track_status="NOT_GENERATED", track_generated_at=None)
    nodes = [
        SimpleNamespace(id=idx + 1, display_name=f"节点{idx + 1}")
        for idx in range(segment_count + 1)
    ]
    segments = [
        SimpleNamespace(
            id=idx + 1,
            segment_no=idx + 1,
            start_line_node_id=idx + 1,
            end_line_node_id=idx + 2,
            transport_mode_code="WATER",
            segment_track_status="NOT_GENERATED",
            geometry_source="LOCAL_SAMPLE",
            geometry_json={"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
            distance_km=99,
            estimated_duration_hour=9,
        )
        for idx in range(segment_count)
    ]
    db = FakeDbSession()
    service = ShippingRouteLineService.__new__(ShippingRouteLineService)
    service.db = db
    service.line_repo = FakeRouteLineRepository(line=line, nodes=nodes, segments=segments)
    return service, line, segments, db


def _ready_result(segment_no: int) -> RouteGeometryResult:
    start_lon = 120.0 + segment_no
    return RouteGeometryResult(
        geometry={
            "type": "LineString",
            "coordinates": [[start_lon, 31.0], [start_lon + 0.5, 31.5]],
        },
        source="hifleet",
        provider="hifleet",
        provider_trace_id=f"hf-{segment_no}",
        status="ready",
        distance_km=10 + segment_no,
        estimated_duration_hour=1 + segment_no,
        raw_summary={"segment_no": segment_no},
    )


@pytest.mark.asyncio
async def test_generate_track_success_persists_real_segment_and_line_geometry(monkeypatch: pytest.MonkeyPatch) -> None:
    service, line, segments, db = _line_service_for_segments()

    async def fake_generate(**kwargs):
        return _ready_result(kwargs["segment"].segment_no)

    monkeypatch.setattr(service, "_generate_segment_geometry", fake_generate)
    response = await service.generate_track(10, SimpleNamespace(provider_code=None))

    assert response.status == "READY"
    assert line.track_status == "READY"
    assert db.committed is True
    assert [segment.segment_track_status for segment in segments] == ["READY", "READY"]
    assert [segment.geometry_source for segment in segments] == ["HIFLEET", "HIFLEET"]
    assert response.track is not None
    assert response.track.geometry_json["type"] == "LineString"
    assert response.track.provider_summary_json["success_count"] == 2


@pytest.mark.asyncio
async def test_generate_track_partial_failure_does_not_write_straight_line_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    service, line, segments, _ = _line_service_for_segments()

    async def fake_generate(**kwargs):
        segment_no = kwargs["segment"].segment_no
        if segment_no == 2:
            raise ValidationError("provider failed")
        return _ready_result(segment_no)

    monkeypatch.setattr(service, "_generate_segment_geometry", fake_generate)
    response = await service.generate_track(10, SimpleNamespace(provider_code=None))

    assert response.status == "PARTIAL"
    assert line.track_status == "PARTIAL"
    assert segments[0].segment_track_status == "READY"
    assert segments[1].segment_track_status == "FAILED"
    assert segments[1].geometry_json is None
    assert segments[1].distance_km is None
    assert response.track is not None
    assert response.track.provider_summary_json["success_count"] == 1
    assert response.track.provider_summary_json["failed_count"] == 1
    assert response.track.error_message is not None


@pytest.mark.asyncio
async def test_generate_track_all_failed_keeps_track_geometry_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    service, line, segments, _ = _line_service_for_segments()

    async def fake_generate(**kwargs):
        _ = kwargs
        raise ValidationError("provider failed")

    monkeypatch.setattr(service, "_generate_segment_geometry", fake_generate)
    response = await service.generate_track(10, SimpleNamespace(provider_code=None))

    assert response.status == "FAILED"
    assert line.track_status == "FAILED"
    assert all(segment.segment_track_status == "FAILED" for segment in segments)
    assert all(segment.geometry_json is None for segment in segments)
    assert response.track is not None
    assert response.track.geometry_json is None
    assert response.track.provider_summary_json["success_count"] == 0
