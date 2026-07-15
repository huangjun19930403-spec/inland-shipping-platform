from __future__ import annotations

import pytest
import pytest_asyncio
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import BigInteger

import app.models  # noqa: F401
from app.models import NavigationGraphVersion, NavigationRouteQualityIssue, NavigationRouteRequest, NavigationRouteResult, NavigationRouteTrajectoryCache
from app.models.base import Base
from app.modules.navigation.engine.types import RoutePoint
from app.modules.navigation.schemas import (
    NavigationEndpointRequest,
    NavigationRouteGenerateRequest,
    NavigationRouteGenerateResponse,
    NavigationRouteIssueResponse,
)
from app.modules.navigation.services.trajectory_cache_service import NavigationTrajectoryCacheService


@compiles(BigInteger, "sqlite")
def _compile_bigint_sqlite(element, compiler, **kw) -> str:
    _ = element, compiler, kw
    return "INTEGER"


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


def _body() -> NavigationRouteGenerateRequest:
    return NavigationRouteGenerateRequest(
        origin=NavigationEndpointRequest(endpoint_type_code="LNG_LAT", longitude=120.0, latitude=31.0),
        destination=NavigationEndpointRequest(endpoint_type_code="LNG_LAT", longitude=120.2, latitude=31.0),
        include_explain=True,
    )


def _origin() -> RoutePoint:
    return RoutePoint(120.0, 31.0, name="A", ref_type_code="LNG_LAT")


def _destination() -> RoutePoint:
    return RoutePoint(120.2, 31.0, name="B", ref_type_code="LNG_LAT")


def _line() -> dict:
    return {"type": "LineString", "coordinates": [[120.0, 31.0], [120.1, 31.02], [120.2, 31.0]]}


async def _route_rows(session: AsyncSession, *, status_code: str = "SUCCESS") -> tuple[NavigationRouteRequest, NavigationRouteResult]:
    request = await _request_row(session, status_code=status_code)
    result = NavigationRouteResult(
        request_id=request.id,
        result_no=1,
        result_type_code="RECOMMENDED",
        status_code=status_code,
        quality_code="READY" if status_code == "SUCCESS" else "FAILED",
        quality_score=95 if status_code == "SUCCESS" else 0,
        geometry_json=_line() if status_code == "SUCCESS" else None,
        provider_code="NAVIGATION_ENGINE",
        engine_code="NAVIGATION_ROUTING_ENGINE_V2",
    )
    session.add(result)
    await session.flush()
    return request, result


async def _request_row(session: AsyncSession, *, status_code: str = "SUCCESS") -> NavigationRouteRequest:
    request = NavigationRouteRequest(
        request_no=f"CACHE-REQ-{uuid4().hex[:8]}",
        origin_lng=120.0,
        origin_lat=31.0,
        destination_lng=120.2,
        destination_lat=31.0,
        routing_preference_code="RECOMMENDED",
        status_code=status_code,
    )
    session.add(request)
    await session.flush()
    return request


def _response(
    request: NavigationRouteRequest,
    result: NavigationRouteResult,
    *,
    graph_version_id: int | None = None,
    provider_code: str = "NAVIGATION_ENGINE",
    source_type_code: str = "NAVIGATION_ROUTING_ENGINE_V2",
    quality_code: str = "READY",
    issue: NavigationRouteIssueResponse | None = None,
) -> NavigationRouteGenerateResponse:
    return NavigationRouteGenerateResponse(
        request_id=request.id,
        result_id=result.id,
        graph_version_id=graph_version_id,
        status_code="SUCCESS",
        provider_code=provider_code,
        source_type_code=source_type_code,
        cache_hit=False,
        quality_code=quality_code,
        quality_score=95,
        geometry_json=_line(),
        distance_km=22.5,
        estimated_duration_hour=2.25,
        edge_ids=[1, 2],
        channel_ids=[10],
        passed_node_ids=[1, 2, 3],
        issues=[issue] if issue else [],
    )


@pytest.mark.asyncio
async def test_valid_navigation_trajectory_cache_can_be_returned(session_maker) -> None:
    async with session_maker() as session:
        request, result = await _route_rows(session)
        service = NavigationTrajectoryCacheService(session)
        stored = await service.store_response(
            origin=_origin(),
            destination=_destination(),
            body=_body(),
            planning_mode_code="RECOMMENDED",
            vessel_profile=None,
            response=_response(request, result),
            request_row=request,
        )
        await session.commit()

        cached = await service.get_returnable(
            origin=_origin(),
            destination=_destination(),
            body=_body(),
            planning_mode_code="RECOMMENDED",
            vessel_profile=None,
        )
        cache_request = await _request_row(session)
        hit = await service.persist_cache_hit_response(
            request_row=cache_request,
            cache_row=cached,
            include_explain=True,
        )
        issues = list(
            (
                await session.execute(
                    select(NavigationRouteQualityIssue).where(NavigationRouteQualityIssue.route_result_id == hit.result_id)
                )
            ).scalars()
        )

    assert stored.cache_status_code == "VALID"
    assert cached is not None
    assert hit.cache_hit is True
    assert hit.trajectory_cache_id == stored.id
    assert hit.provider_code == "NAVIGATION_ENGINE"
    assert hit.geometry_json == _line()
    assert issues == []


@pytest.mark.asyncio
async def test_auto_active_cache_is_scoped_to_current_default_graph(session_maker) -> None:
    async with session_maker() as session:
        session.add_all(
            [
                NavigationGraphVersion(
                    id=1,
                    version_code="GRAPH-OLD",
                    version_name="Old graph",
                    scope_code="REAL-OLD",
                    status_code="READY",
                    is_active=True,
                    node_count=2,
                    edge_count=1,
                    channel_count=1,
                ),
                NavigationGraphVersion(
                    id=2,
                    version_code="GRAPH-NEW",
                    version_name="New graph",
                    scope_code="REAL-NEW",
                    status_code="READY",
                    is_active=False,
                    node_count=4,
                    edge_count=3,
                    channel_count=2,
                ),
            ]
        )
        request, result = await _route_rows(session)
        service = NavigationTrajectoryCacheService(session)
        stored = await service.store_response(
            origin=_origin(),
            destination=_destination(),
            body=_body(),
            planning_mode_code="RECOMMENDED",
            vessel_profile=None,
            response=_response(request, result, graph_version_id=1),
            request_row=request,
        )
        old_cached = await service.get_returnable(
            origin=_origin(),
            destination=_destination(),
            body=_body(),
            planning_mode_code="RECOMMENDED",
            vessel_profile=None,
        )
        old_graph = await session.get(NavigationGraphVersion, 1)
        new_graph = await session.get(NavigationGraphVersion, 2)
        assert old_graph is not None and new_graph is not None
        old_graph.is_active = False
        new_graph.is_active = True
        await session.commit()

        new_cached = await service.get_returnable(
            origin=_origin(),
            destination=_destination(),
            body=_body(),
            planning_mode_code="RECOMMENDED",
            vessel_profile=None,
        )

    assert stored.cache_status_code == "VALID"
    assert stored.graph_context_code == "AUTO_ACTIVE:1"
    assert old_cached is not None
    assert new_cached is None


@pytest.mark.asyncio
async def test_hard_issue_navigation_trajectory_cache_is_recorded_but_not_returned(session_maker) -> None:
    async with session_maker() as session:
        request, result = await _route_rows(session)
        service = NavigationTrajectoryCacheService(session)
        issue = NavigationRouteIssueResponse(
            issue_type_code="ROUTE_LONG_STRAIGHT_SEGMENT_REVIEW",
            severity_code="WARNING",
            message="Route contains a long straight segment",
        )
        stored = await service.store_response(
            origin=_origin(),
            destination=_destination(),
            body=_body(),
            planning_mode_code="RECOMMENDED",
            vessel_profile=None,
            response=_response(request, result, quality_code="NEED_REVIEW", issue=issue),
            request_row=request,
        )
        await session.commit()

        cached = await service.get_returnable(
            origin=_origin(),
            destination=_destination(),
            body=_body(),
            planning_mode_code="RECOMMENDED",
            vessel_profile=None,
        )

    assert stored.cache_status_code == "NEED_REVIEW"
    assert cached is None


@pytest.mark.asyncio
async def test_hifleet_trajectory_cache_is_reference_ready_but_not_returned_before_self_route(session_maker) -> None:
    async with session_maker() as session:
        request, result = await _route_rows(session)
        service = NavigationTrajectoryCacheService(session)
        stored = await service.store_response(
            origin=_origin(),
            destination=_destination(),
            body=_body(),
            planning_mode_code="RECOMMENDED",
            vessel_profile=None,
            response=_response(
                request,
                result,
                provider_code="HIFLEET",
                source_type_code="HIFLEET_API",
                quality_code="READY_WITH_WARNING",
            ).model_copy(update={"hifleet_cache_id": 88}),
            request_row=request,
        )
        await session.commit()

        cached = await service.get_returnable(
            origin=_origin(),
            destination=_destination(),
            body=_body(),
            planning_mode_code="RECOMMENDED",
            vessel_profile=None,
        )

    assert stored.cache_status_code == "REFERENCE_READY"
    assert cached is None


@pytest.mark.asyncio
async def test_valid_own_route_overwrites_hifleet_reference_for_same_route_key(session_maker) -> None:
    async with session_maker() as session:
        request, result = await _route_rows(session)
        service = NavigationTrajectoryCacheService(session)
        hifleet = await service.store_response(
            origin=_origin(),
            destination=_destination(),
            body=_body(),
            planning_mode_code="RECOMMENDED",
            vessel_profile=None,
            response=_response(
                request,
                result,
                provider_code="HIFLEET",
                source_type_code="HIFLEET_API",
                quality_code="READY_WITH_WARNING",
            ).model_copy(update={"hifleet_cache_id": 88}),
            request_row=request,
        )
        own_request, own_result = await _route_rows(session)
        own = await service.store_response(
            origin=_origin(),
            destination=_destination(),
            body=_body(),
            planning_mode_code="RECOMMENDED",
            vessel_profile=None,
            response=_response(
                own_request,
                own_result,
                provider_code="NAVIGATION_ENGINE",
                source_type_code="NAVIGATION_ROUTING_ENGINE_V2",
                quality_code="READY",
            ),
            request_row=own_request,
        )
        await session.commit()

        cached = await service.get_returnable(
            origin=_origin(),
            destination=_destination(),
            body=_body(),
            planning_mode_code="RECOMMENDED",
            vessel_profile=None,
        )

    assert hifleet.id == own.id
    assert own.cache_status_code == "VALID"
    assert cached is not None
    assert cached.provider_code == "NAVIGATION_ENGINE"
    assert cached.source_type_code == "NAVIGATION_ROUTING_ENGINE_V2"
    assert cached.hifleet_cache_id is None


@pytest.mark.asyncio
async def test_centerline_seed_fallback_cache_is_recorded_but_not_returned(session_maker) -> None:
    async with session_maker() as session:
        request, result = await _route_rows(session)
        service = NavigationTrajectoryCacheService(session)
        stored = await service.store_response(
            origin=_origin(),
            destination=_destination(),
            body=_body(),
            planning_mode_code="RECOMMENDED",
            vessel_profile=None,
            response=_response(
                request,
                result,
                provider_code="NAVIGATION_ENGINE",
                source_type_code="CENTERLINE_SEED_FALLBACK",
                quality_code="READY",
            ),
            request_row=request,
        )
        await session.commit()

        cached = await service.get_returnable(
            origin=_origin(),
            destination=_destination(),
            body=_body(),
            planning_mode_code="RECOMMENDED",
            vessel_profile=None,
        )

    assert stored.cache_status_code == "NEED_REVIEW"
    assert cached is None
