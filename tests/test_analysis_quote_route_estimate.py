from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.exceptions import ValidationError
from app.core.config import settings
from app.integrations.http.route_geometry_types import RouteGeometryResult
from app.modules.analysis.schemas import FlowMapItem, QuoteRouteEstimateRequest
from app.modules.analysis import service as analysis_service
from app.modules.analysis.service import AnalysisDashboardService, QuoteRouteEstimateService, _FLOW_ROUTE_GEOMETRY_CACHE


def _node(**overrides):
    values = {
        "id": 1,
        "code": "NODE_A",
        "name": "测试装货港",
        "node_type_code": "PORT",
        "city_code": "320100",
        "longitude": 120.0,
        "latitude": 31.0,
        "status": 1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _service(nodes: dict[int, object], categories: dict[int, set[str]], result: RouteGeometryResult | Exception):
    service = QuoteRouteEstimateService.__new__(QuoteRouteEstimateService)
    service.db = None
    service.runtime_config = None

    async def get_node(node_id: int):
        return nodes.get(node_id)

    async def category_codes(node_id: int):
        return categories.get(node_id, set())

    class FakeClient:
        async def generate(self, query):
            assert query.transport_mode == "WATER"
            assert query.segment_type == "QUOTE_SIMULATOR"
            if isinstance(result, Exception):
                raise result
            return result

    service._get_node = get_node
    service._category_codes = category_codes
    service._route_client = lambda: FakeClient()
    return service


@pytest.mark.asyncio
async def test_quote_route_estimate_success_uses_hifleet_distance() -> None:
    origin = _node(id=1)
    destination = _node(id=2, code="NODE_B", name="测试卸货港", longitude=121.0, latitude=32.0)
    service = _service(
        {1: origin, 2: destination},
        {1: {"LOADING"}, 2: {"UNLOADING"}},
        RouteGeometryResult(
            geometry={"type": "LineString", "coordinates": [[120.0, 31.0], [120.5, 31.5], [121.0, 32.0]]},
            source="hifleet",
            provider="hifleet",
            provider_trace_id="hf-quote-1",
            status="ready",
            distance_km=88.5,
        ),
    )

    response = await service.estimate_route(QuoteRouteEstimateRequest(origin_node_id=1, destination_node_id=2))

    assert response.status_code == "READY"
    assert response.distance_km == 88.5
    assert response.geometry_source == "AMMS"
    assert response.provider_trace_id == "hf-quote-1"
    assert response.point_count == 3
    assert response.not_computable_reasons == []
    assert response.map_state.status_code == "READY"
    assert response.map_state.provider_code == "AMMS"


@pytest.mark.asyncio
async def test_quote_route_estimate_computes_distance_from_geometry_when_provider_distance_missing() -> None:
    service = _service(
        {1: _node(id=1), 2: _node(id=2, longitude=120.5, latitude=31.5)},
        {1: {"LOADING"}, 2: {"UNLOADING"}},
        RouteGeometryResult(
            geometry={"type": "LineString", "coordinates": [[120.0, 31.0], [120.5, 31.5]]},
            source="hifleet",
            provider="hifleet",
            provider_trace_id=None,
            status="ready",
            distance_km=None,
        ),
    )

    response = await service.estimate_route(QuoteRouteEstimateRequest(origin_node_id=1, destination_node_id=2))

    assert response.status_code == "READY"
    assert response.distance_km is not None
    assert response.distance_km > 0


@pytest.mark.asyncio
async def test_quote_route_estimate_node_without_coordinate_is_not_computable() -> None:
    service = _service(
        {1: _node(id=1, longitude=None), 2: _node(id=2, longitude=121.0, latitude=32.0)},
        {1: {"LOADING"}, 2: {"UNLOADING"}},
        ValidationError("should not call hifleet"),
    )

    response = await service.estimate_route(QuoteRouteEstimateRequest(origin_node_id=1, destination_node_id=2))

    assert response.status_code == "NOT_COMPUTABLE"
    assert "装货节点缺少经纬度" in response.not_computable_reasons
    assert response.map_state.missing_fields == ["origin_latitude", "origin_longitude"]


@pytest.mark.asyncio
async def test_quote_route_estimate_category_mismatch_is_not_computable() -> None:
    service = _service(
        {1: _node(id=1), 2: _node(id=2, longitude=121.0, latitude=32.0)},
        {1: {"UNLOADING"}, 2: {"LOADING"}},
        ValidationError("should not call hifleet"),
    )

    response = await service.estimate_route(QuoteRouteEstimateRequest(origin_node_id=1, destination_node_id=2))

    assert response.status_code == "NOT_COMPUTABLE"
    assert "装货节点未配置装货业务类别" in response.not_computable_reasons
    assert "卸货节点未配置卸货业务类别" in response.not_computable_reasons


@pytest.mark.asyncio
async def test_quote_route_estimate_hifleet_failure_is_returned_as_failed_reason() -> None:
    service = _service(
        {1: _node(id=1), 2: _node(id=2, longitude=121.0, latitude=32.0)},
        {1: {"LOADING"}, 2: {"UNLOADING"}},
        ValidationError("AMMS getNewRoute 返回失败: no route"),
    )

    response = await service.estimate_route(QuoteRouteEstimateRequest(origin_node_id=1, destination_node_id=2))

    assert response.status_code == "FAILED"
    assert response.distance_km is None
    assert response.not_computable_reasons == ["AMMS getNewRoute 返回失败: no route"]
    assert response.map_state.error_reason == "AMMS getNewRoute 返回失败: no route"
    assert response.map_state.retry_action is not None
    assert response.map_state.retry_action.action_code == "RETRY_ROUTE_GEOMETRY"


@pytest.mark.asyncio
async def test_flow_map_items_use_amms_geometry_without_public_hifleet_label(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ANALYSIS_FLOW_ROUTE_CACHE_BACKEND", "memory")
    monkeypatch.setattr(analysis_service, "_FLOW_ROUTE_GEOMETRY_REDIS_CLIENT", None)
    _FLOW_ROUTE_GEOMETRY_CACHE.clear()
    service = AnalysisDashboardService.__new__(AnalysisDashboardService)
    calls: list[str] = []

    class FakeClient:
        async def generate(self, query):
            calls.append(query.segment_type)
            assert query.transport_mode == "WATER"
            return RouteGeometryResult(
                geometry={"type": "LineString", "coordinates": [[120.0, 31.0], [120.5, 31.5], [121.0, 32.0]]},
                source="HIFLEET",
                provider="HIFLEET",
                provider_trace_id="trace-flow",
                status="READY",
                distance_km=120.25,
            )

    service._route_client = lambda: FakeClient()

    result = await service._attach_flow_route_geometries(
        [
            FlowMapItem(
                origin_id=1,
                origin_name="南京港",
                origin_longitude=120.0,
                origin_latitude=31.0,
                destination_id=2,
                destination_name="上海港",
                destination_longitude=121.0,
                destination_latitude=32.0,
                value=10,
            )
        ],
        segment_type="ANALYSIS_FREIGHT_FLOW_MAP",
        generate_missing=True,
    )

    assert calls == ["ANALYSIS_FREIGHT_FLOW_MAP"]
    assert result[0].route_status_code == "READY"
    assert result[0].geometry_source == "AMMS"
    assert result[0].geometry_json == {"type": "LineString", "coordinates": [[120.0, 31.0], [120.5, 31.5], [121.0, 32.0]]}
    assert result[0].route_distance_km == 120.25
    assert result[0].route_point_count == 3
    assert result[0].map_state is not None
    assert result[0].map_state.status_code == "READY"


@pytest.mark.asyncio
async def test_flow_map_items_fallback_when_amms_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ANALYSIS_FLOW_ROUTE_CACHE_BACKEND", "memory")
    monkeypatch.setattr(analysis_service, "_FLOW_ROUTE_GEOMETRY_REDIS_CLIENT", None)
    _FLOW_ROUTE_GEOMETRY_CACHE.clear()
    service = AnalysisDashboardService.__new__(AnalysisDashboardService)

    class FakeClient:
        async def generate(self, _query):
            raise ValidationError("未配置 AMMS 路径服务基础地址")

    service._route_client = lambda: FakeClient()

    result = await service._attach_flow_route_geometries(
        [
            FlowMapItem(
                origin_id=1,
                origin_name="南京港",
                origin_longitude=120.0,
                origin_latitude=31.0,
                destination_id=2,
                destination_name="上海港",
                destination_longitude=121.0,
                destination_latitude=32.0,
                value=10,
            )
        ],
        segment_type="ANALYSIS_FREIGHT_FLOW_MAP",
        generate_missing=True,
    )

    assert result[0].route_status_code == "NOT_COMPUTABLE"
    assert result[0].geometry_json is None
    assert result[0].geometry_source == "AMMS"
    assert result[0].route_not_computable_reasons == ["未配置 AMMS 路径服务基础地址"]
    assert result[0].map_state is not None
    assert result[0].map_state.status_code == "NOT_COMPUTABLE"
    assert result[0].map_state.missing_fields == ["AMMS_API_KEY", "AMMS_BASE_URL"]


@pytest.mark.asyncio
async def test_flow_map_items_read_cache_only_without_generating(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ANALYSIS_FLOW_ROUTE_CACHE_BACKEND", "memory")
    monkeypatch.setattr(analysis_service, "_FLOW_ROUTE_GEOMETRY_REDIS_CLIENT", None)
    _FLOW_ROUTE_GEOMETRY_CACHE.clear()
    service = AnalysisDashboardService.__new__(AnalysisDashboardService)
    calls = 0

    class FakeClient:
        async def generate(self, _query):
            nonlocal calls
            calls += 1
            raise AssertionError("cache-only flow map should not call AMMS")

    service._route_client = lambda: FakeClient()

    result = await service._attach_flow_route_geometries(
        [
            FlowMapItem(
                origin_id=1,
                origin_name="南京港",
                origin_longitude=120.0,
                origin_latitude=31.0,
                destination_id=2,
                destination_name="上海港",
                destination_longitude=121.0,
                destination_latitude=32.0,
                value=10,
            )
        ],
        segment_type="ANALYSIS_FREIGHT_FLOW_MAP",
    )

    assert calls == 0
    assert result[0].route_status_code == "PENDING"
    assert result[0].route_cache_status == "MISS"
    assert result[0].geometry_json is None
    assert result[0].map_state is not None
    assert result[0].map_state.status_code == "PENDING"
    assert result[0].map_state.retry_action is not None
