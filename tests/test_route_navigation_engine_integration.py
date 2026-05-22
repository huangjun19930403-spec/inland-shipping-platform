from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.exceptions import ValidationError
from app.integrations.http.route_geometry_types import RouteGeometryResult
from app.models import NavigationGraphEdge, NavigationGraphNode, NavigationGraphVersion, NavigationRouteResult
from app.models.base import Base
from app.models.route import ShippingRoute, ShippingRoutePlan, ShippingRoutePlanPoint, ShippingRoutePlanSegment
from app.modules.route.schemas import RouteTrackGenerateRequest
from app.modules.route.service import ShippingRoutePlanStructureService


@pytest_asyncio.fixture
async def session_maker():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield maker
    finally:
        await engine.dispose()


def _line(*points: tuple[float, float]) -> dict:
    return {"type": "LineString", "coordinates": [[lng, lat] for lng, lat in points]}


def _manual_point(*, point_id: int, lng: float, lat: float, name: str) -> ShippingRoutePlanPoint:
    return ShippingRoutePlanPoint(
        id=point_id,
        plan_id=1,
        point_order=point_id,
        point_type_code="MANUAL_POINT",
        manual_name=name,
        longitude=lng,
        latitude=lat,
        display_name=name,
        transport_mode_after_code="WATER",
    )


def _water_segment() -> ShippingRoutePlanSegment:
    return ShippingRoutePlanSegment(
        id=11,
        plan_id=1,
        segment_no=1,
        start_plan_point_id=1,
        end_plan_point_id=2,
        transport_mode_code="WATER",
        generation_status_code="NOT_GENERATED",
    )


def _road_segment() -> ShippingRoutePlanSegment:
    segment = _water_segment()
    segment.transport_mode_code = "ROAD"
    return segment


async def _seed_graph(session: AsyncSession) -> None:
    session.add(
        NavigationGraphVersion(
            id=1,
            version_code="ROUTE-INTEGRATION-GRAPH",
            version_name="Route integration graph",
            scope_code="TEST",
            node_count=2,
            edge_count=1,
            channel_count=1,
            quality_score=90,
            status_code="READY",
            is_active=True,
        )
    )
    session.add_all(
        [
            NavigationGraphNode(
                id=1,
                graph_version_id=1,
                node_code="N1",
                node_name="N1",
                node_type_code="CENTERLINE_VERTEX",
                longitude=120.0,
                latitude=31.0,
                geometry_json={"type": "Point", "coordinates": [120.0, 31.0]},
                is_enabled=True,
                quality_code="READY",
                source_type_code="CENTERLINE_VERTEX",
            ),
            NavigationGraphNode(
                id=2,
                graph_version_id=1,
                node_code="N2",
                node_name="N2",
                node_type_code="CENTERLINE_VERTEX",
                longitude=120.1,
                latitude=31.0,
                geometry_json={"type": "Point", "coordinates": [120.1, 31.0]},
                is_enabled=True,
                quality_code="READY",
                source_type_code="CENTERLINE_VERTEX",
            ),
        ]
    )
    session.add(
        NavigationGraphEdge(
            id=1,
            graph_version_id=1,
            edge_code="E1",
            from_node_id=1,
            to_node_id=2,
            channel_id=88,
            geometry_json=_line((120.0, 31.0), (120.1, 31.0)),
            length_km=11.1,
            direction_code="BIDIRECTIONAL",
            lock_required=False,
            bridge_count=0,
            base_cost=11.1,
            routing_enabled=True,
            quality_code="READY",
            source_type_code="MANUAL",
            confidence_score=95,
            unknown_constraint_flag=True,
        )
    )
    await session.commit()


def _points() -> tuple[ShippingRoutePlanPoint, ShippingRoutePlanPoint]:
    return (
        _manual_point(point_id=1, lng=120.0, lat=31.0, name="A"),
        _manual_point(point_id=2, lng=120.1, lat=31.0, name="B"),
    )


async def _seed_route_plan(session: AsyncSession) -> int:
    session.add_all(
        [
            ShippingRoute(
                id=1,
                code="R-NE-1",
                name="自研航道引擎测试航线",
                origin_endpoint_type_code="NODE",
                destination_endpoint_type_code="NODE",
                transport_org_type_code="WATERWAY",
                status_code="ACTIVE",
            ),
            ShippingRoutePlan(
                id=1,
                route_id=1,
                plan_code="RP-NE-1",
                plan_name="默认方案",
                plan_type_code="STANDARD",
                is_default=True,
                status_code="ACTIVE",
                display_order=1,
                structure_revision=1,
            ),
            _manual_point(point_id=1, lng=120.0, lat=31.0, name="A"),
            _manual_point(point_id=2, lng=120.1, lat=31.0, name="B"),
            _water_segment(),
        ]
    )
    await session.commit()
    return 1


def test_auto_water_provider_selects_navigation_engine() -> None:
    service = ShippingRoutePlanStructureService(SimpleNamespace())

    assert service._provider_for_segment("WATER", None) == "NAVIGATION_ENGINE"
    assert service._provider_for_segment("WATER", "AUTO") == "NAVIGATION_ENGINE"
    assert service._provider_for_segment("ROAD", None) == "AMAP"
    assert service._provider_for_segment("WATER", "HIFLEET") == "HIFLEET"


@pytest.mark.asyncio
async def test_water_auto_calls_navigation_engine_and_persists_route_result(session_maker) -> None:
    async with session_maker() as session:
        await _seed_graph(session)
        service = ShippingRoutePlanStructureService(session)
        start, end = _points()

        result = await service._call_geometry_provider(
            segment=_water_segment(),
            start_point=start,
            end_point=end,
            provider_code=None,
        )
        persisted_result = (await session.execute(select(NavigationRouteResult))).scalar_one()

    assert result.source == "navigation_engine"
    assert result.provider == "NAVIGATION_ENGINE"
    assert result.geometry["coordinates"][0] == [120.0, 31.0]
    assert result.raw_summary is not None
    assert result.raw_summary["navigation_route_result_id"] == persisted_result.id
    assert result.raw_summary["graph_version_id"] == 1
    assert result.raw_summary["edge_ids"] == [1]


@pytest.mark.asyncio
async def test_generate_track_version_stores_navigation_engine_quality_summary(session_maker) -> None:
    async with session_maker() as session:
        await _seed_graph(session)
        plan_id = await _seed_route_plan(session)

        response = await ShippingRoutePlanStructureService(session).generate_track_version(
            plan_id,
            RouteTrackGenerateRequest(provider_code="AUTO"),
        )

    assert response.status == "READY"
    assert response.version is not None
    assert response.version.source_type_code == "NAVIGATION_ENGINE"
    assert response.version.is_current is False
    assert response.version.segment_count == 1
    assert response.version.summary_json["navigation_route_results"][0]["graph_version_id"] == 1
    assert response.version.summary_json["navigation_route_results"][0]["edge_ids"] == [1]
    assert response.version.summary_json["navigation_route_results"][0]["quality_code"] == "READY_WITH_WARNING"


@pytest.mark.asyncio
async def test_water_auto_fails_without_graph_instead_of_using_fallback(session_maker) -> None:
    async with session_maker() as session:
        service = ShippingRoutePlanStructureService(session)
        start, end = _points()

        with pytest.raises(ValidationError, match="NO_ACTIVE_GRAPH_VERSION"):
            await service._call_geometry_provider(
                segment=_water_segment(),
                start_point=start,
                end_point=end,
                provider_code=None,
            )


@pytest.mark.asyncio
async def test_explicit_hifleet_is_reference_source(session_maker) -> None:
    class FakeHifleetClient:
        provider_name = "HIFLEET"

        async def generate(self, query):  # noqa: ANN001
            return RouteGeometryResult(
                geometry=_line((query.origin_lon, query.origin_lat), (120.05, 31.02), (query.dest_lon, query.dest_lat)),
                source="hifleet",
                provider="HIFLEET",
                provider_trace_id="hf-reference-1",
                status="ready",
            )

    async with session_maker() as session:
        service = ShippingRoutePlanStructureService(session)
        service._geometry_client_for_segment = lambda *_args, **_kwargs: FakeHifleetClient()  # type: ignore[method-assign]
        start, end = _points()

        result = await service._call_geometry_provider(
            segment=_water_segment(),
            start_point=start,
            end_point=end,
            provider_code="HIFLEET",
        )

    assert result.source == "reference_hifleet"
    assert result.provider == "HIFLEET"
    assert result.raw_summary is not None
    assert result.raw_summary["reference_only"] is True
    assert result.raw_summary["centerline_publish_allowed"] is False


@pytest.mark.asyncio
async def test_water_hifleet_fallback_is_disabled_by_default(session_maker) -> None:
    class TimeoutHifleetClient:
        provider_name = "HIFLEET"

        async def generate(self, query):  # noqa: ANN001
            raise httpx.ReadTimeout("mock hifleet timeout")

    async with session_maker() as session:
        service = ShippingRoutePlanStructureService(session)
        service._geometry_client_for_segment = lambda *_args, **_kwargs: TimeoutHifleetClient()  # type: ignore[method-assign]
        start, end = _points()

        with pytest.raises(httpx.ReadTimeout):
            await service._call_geometry_provider(
                segment=_water_segment(),
                start_point=start,
                end_point=end,
                provider_code="HIFLEET",
            )


@pytest.mark.asyncio
async def test_road_fallback_still_uses_existing_external_provider_behavior(session_maker) -> None:
    class TimeoutAmapClient:
        provider_name = "AMAP"

        async def generate(self, query):  # noqa: ANN001
            raise httpx.ReadTimeout("mock amap timeout")

    async with session_maker() as session:
        service = ShippingRoutePlanStructureService(session)
        service._geometry_client_for_segment = lambda *_args, **_kwargs: TimeoutAmapClient()  # type: ignore[method-assign]
        start, end = _points()

        result = await service._call_geometry_provider(
            segment=_road_segment(),
            start_point=start,
            end_point=end,
            provider_code="AMAP",
        )

    assert result.source == "fallback"
    assert result.provider == "AMAP"
