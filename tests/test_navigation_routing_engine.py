from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.v1 import api_router
from app.models import (
    NavigationGraphEdge,
    NavigationGraphNode,
    NavigationGraphVersion,
    NavigationRouteQualityIssue,
    NavigationRouteRequest,
    NavigationRouteResult,
)
from app.models.base import Base
from app.modules.navigation.routing_service import NavigationRoutingEngineService
from app.modules.navigation.schemas import NavigationEndpointRequest, NavigationRouteGenerateRequest, VesselProfileRequest


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


def _node(*, id: int, graph_version_id: int, lng: float, lat: float, code: str) -> NavigationGraphNode:
    return NavigationGraphNode(
        id=id,
        graph_version_id=graph_version_id,
        node_code=code,
        node_name=code,
        node_type_code="CENTERLINE_VERTEX",
        longitude=lng,
        latitude=lat,
        geometry_json={"type": "Point", "coordinates": [lng, lat]},
        is_enabled=True,
        quality_code="READY",
        source_type_code="CENTERLINE_VERTEX",
    )


def _edge(
    *,
    id: int,
    graph_version_id: int,
    from_node_id: int,
    to_node_id: int,
    code: str,
    geometry: dict,
    channel_id: int = 1,
    max_allowed_tonnage: float | None = None,
    unknown_constraint_flag: bool = False,
) -> NavigationGraphEdge:
    return NavigationGraphEdge(
        id=id,
        graph_version_id=graph_version_id,
        edge_code=code,
        from_node_id=from_node_id,
        to_node_id=to_node_id,
        channel_id=channel_id,
        centerline_id=None,
        geometry_json=geometry,
        length_km=11.1,
        direction_code="BIDIRECTIONAL",
        max_allowed_tonnage=max_allowed_tonnage,
        lock_required=False,
        bridge_count=0,
        base_cost=11.1,
        routing_enabled=True,
        quality_code="READY",
        source_type_code="MANUAL",
        confidence_score=95,
        unknown_constraint_flag=unknown_constraint_flag,
    )


async def _seed_ready_graph(session: AsyncSession, *, disconnected: bool = False, blocked: bool = False) -> None:
    session.add(
        NavigationGraphVersion(
            id=1,
            version_code="TEST-ACTIVE-GRAPH",
            version_name="Test active graph",
            scope_code="TEST",
            node_count=4 if disconnected else 3,
            edge_count=2,
            channel_count=1,
            quality_score=95,
            status_code="READY",
            is_active=True,
        )
    )
    session.add_all(
        [
            _node(id=1, graph_version_id=1, lng=120.0, lat=31.0, code="N1"),
            _node(id=2, graph_version_id=1, lng=120.1, lat=31.0, code="N2"),
            _node(id=3, graph_version_id=1, lng=120.2, lat=31.0, code="N3"),
        ]
    )
    if disconnected:
        session.add(_node(id=4, graph_version_id=1, lng=120.3, lat=31.0, code="N4"))
        session.add_all(
            [
                _edge(id=1, graph_version_id=1, from_node_id=1, to_node_id=2, code="E1", geometry=_line((120.0, 31.0), (120.1, 31.0))),
                _edge(id=2, graph_version_id=1, from_node_id=3, to_node_id=4, code="E2", geometry=_line((120.2, 31.0), (120.3, 31.0))),
            ]
        )
    else:
        session.add_all(
            [
                _edge(
                    id=1,
                    graph_version_id=1,
                    from_node_id=1,
                    to_node_id=2,
                    code="E1",
                    geometry=_line((120.0, 31.0), (120.1, 31.0)),
                    max_allowed_tonnage=100 if blocked else None,
                    unknown_constraint_flag=not blocked,
                ),
                _edge(
                    id=2,
                    graph_version_id=1,
                    from_node_id=2,
                    to_node_id=3,
                    code="E2",
                    geometry=_line((120.1, 31.0), (120.2, 31.0)),
                    max_allowed_tonnage=100 if blocked else None,
                    unknown_constraint_flag=not blocked,
                ),
            ]
        )
    await session.commit()


def _request(
    *,
    origin: tuple[float, float] = (120.0, 31.0),
    destination: tuple[float, float] = (120.2, 31.0),
    vessel_profile: VesselProfileRequest | None = None,
) -> NavigationRouteGenerateRequest:
    return NavigationRouteGenerateRequest(
        origin=NavigationEndpointRequest(endpoint_type_code="LNG_LAT", longitude=origin[0], latitude=origin[1]),
        destination=NavigationEndpointRequest(endpoint_type_code="LNG_LAT", longitude=destination[0], latitude=destination[1]),
        vessel_profile=vessel_profile,
    )


def test_navigation_route_generate_api_is_registered() -> None:
    assert "/navigation/routes/generate" in {getattr(route, "path", None) for route in api_router.routes}


@pytest.mark.asyncio
async def test_generate_route_success_persists_request_result_and_issues(session_maker) -> None:
    async with session_maker() as session:
        await _seed_ready_graph(session)

        response = await NavigationRoutingEngineService(session).generate_route(_request())
        request_count = await session.scalar(select(func.count()).select_from(NavigationRouteRequest))
        result = (await session.execute(select(NavigationRouteResult))).scalar_one()
        issue_count = await session.scalar(select(func.count()).select_from(NavigationRouteQualityIssue))

    assert response.status_code == "SUCCESS"
    assert response.quality_code == "READY_WITH_WARNING"
    assert response.graph_version_id == 1
    assert response.edge_ids == [1, 2]
    assert response.channel_ids == [1]
    assert response.geometry_json is not None
    assert response.distance_km and response.distance_km > 0
    assert request_count == 1
    assert result.provider_code == "NAVIGATION_ENGINE"
    assert issue_count >= 1
    assert "UNKNOWN_CONSTRAINT_DATA" in {issue.issue_type_code for issue in response.issues}


@pytest.mark.asyncio
async def test_generate_route_fails_without_active_graph_and_persists_failure(session_maker) -> None:
    async with session_maker() as session:
        response = await NavigationRoutingEngineService(session).generate_route(_request())
        request_row = (await session.execute(select(NavigationRouteRequest))).scalar_one()
        result_row = (await session.execute(select(NavigationRouteResult))).scalar_one()
        issue_row = (await session.execute(select(NavigationRouteQualityIssue))).scalar_one()

    assert response.status_code == "FAILED"
    assert response.error_code == "NO_ACTIVE_GRAPH_VERSION"
    assert request_row.status_code == "FAILED"
    assert result_row.quality_code == "FAILED"
    assert issue_row.issue_type_code == "NO_ACTIVE_GRAPH_VERSION"


@pytest.mark.asyncio
async def test_generate_route_fails_when_endpoint_too_far_from_graph(session_maker) -> None:
    async with session_maker() as session:
        await _seed_ready_graph(session)

        response = await NavigationRoutingEngineService(session).generate_route(
            _request(origin=(120.0, 31.03), destination=(120.2, 31.0))
        )

    assert response.status_code == "FAILED"
    assert response.error_code == "ORIGIN_TOO_FAR_FROM_GRAPH"


@pytest.mark.asyncio
async def test_generate_route_reports_disconnected_graph(session_maker) -> None:
    async with session_maker() as session:
        await _seed_ready_graph(session, disconnected=True)

        response = await NavigationRoutingEngineService(session).generate_route(
            _request(origin=(120.0, 31.0), destination=(120.3, 31.0))
        )

    assert response.status_code == "FAILED"
    assert response.error_code == "GRAPH_DISCONNECTED"


@pytest.mark.asyncio
async def test_generate_route_reports_vessel_constraint_blocked(session_maker) -> None:
    async with session_maker() as session:
        await _seed_ready_graph(session, blocked=True)

        response = await NavigationRoutingEngineService(session).generate_route(
            _request(vessel_profile=VesselProfileRequest(deadweight_ton=500))
        )

    assert response.status_code == "FAILED"
    assert response.error_code == "VESSEL_CONSTRAINT_BLOCKED"
    assert "VSL_TONNAGE_EXCEEDS_LIMIT" in {issue.issue_type_code for issue in response.issues}
