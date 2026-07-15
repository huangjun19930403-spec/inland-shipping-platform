from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from shapely.geometry import shape

import app.models  # noqa: F401
from app.api.v1 import api_router
from app.integrations.http.route_geometry_types import RouteGeometryResult
from app.models import (
    NavigationChannelCenterline,
    NavigationGraphEdge,
    NavigationGraphNode,
    NavigationGraphVersion,
    NavigationRouteQualityIssue,
    NavigationRouteRequest,
    NavigationRouteResult,
)
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.models.base import Base
from app.modules.navigation.routing_service import NavigationRoutingEngineService
from app.modules.navigation.engine.path_validator import PathValidator
from app.modules.navigation.engine.quality_scoring import QualityScorer
from app.modules.navigation.engine.types import RouteIssue, SearchResult, SnapResult
from app.modules.navigation.schemas import (
    NavigationEndpointRequest,
    NavigationRouteGenerateRequest,
    NavigationRouteGenerateResponse,
    NavigationRouteIssueResponse,
    VesselProfileRequest,
)


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


def _node(
    *,
    id: int,
    graph_version_id: int,
    lng: float,
    lat: float,
    code: str,
    node_type_code: str = "CENTERLINE_VERTEX",
) -> NavigationGraphNode:
    return NavigationGraphNode(
        id=id,
        graph_version_id=graph_version_id,
        node_code=code,
        node_name=code,
        node_type_code=node_type_code,
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
    length_km: float = 11.1,
    max_allowed_tonnage: float | None = None,
    unknown_constraint_flag: bool = False,
    lock_required: bool = False,
    bridge_count: int = 0,
    quality_code: str = "READY",
    confidence_score: int = 95,
    source_type_code: str = "MANUAL",
    validation_summary_json: dict | None = None,
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
        length_km=length_km,
        direction_code="BIDIRECTIONAL",
        max_allowed_tonnage=max_allowed_tonnage,
        lock_required=lock_required,
        bridge_count=bridge_count,
        base_cost=length_km,
        routing_enabled=True,
        quality_code=quality_code,
        source_type_code=source_type_code,
        confidence_score=confidence_score,
        unknown_constraint_flag=unknown_constraint_flag,
        validation_summary_json=validation_summary_json or {},
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


async def _seed_bending_graph_requires_expanded_bbox(session: AsyncSession) -> None:
    session.add(
        NavigationGraphVersion(
            id=1,
            version_code="TEST-BENDING-GRAPH",
            version_name="Test bending graph",
            scope_code="TEST",
            node_count=3,
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
            _node(id=2, graph_version_id=1, lng=120.5, lat=33.0, code="N2"),
            _node(id=3, graph_version_id=1, lng=121.0, lat=31.0, code="N3"),
            _edge(
                id=1,
                graph_version_id=1,
                from_node_id=1,
                to_node_id=2,
                code="E1",
                geometry=_line((120.0, 31.0), (120.5, 33.0)),
            ),
            _edge(
                id=2,
                graph_version_id=1,
                from_node_id=2,
                to_node_id=3,
                code="E2",
                geometry=_line((120.5, 33.0), (121.0, 31.0)),
            ),
        ]
    )
    await session.commit()


def _request(
    *,
    origin: tuple[float, float] = (120.0, 31.0),
    destination: tuple[float, float] = (120.2, 31.0),
    vessel_profile: VesselProfileRequest | None = None,
    graph_version_id: int | None = None,
    planning_mode_code: str = "RECOMMENDED",
    include_alternatives: bool = False,
    alternative_count: int = 1,
) -> NavigationRouteGenerateRequest:
    return NavigationRouteGenerateRequest(
        origin=NavigationEndpointRequest(endpoint_type_code="LNG_LAT", longitude=origin[0], latitude=origin[1]),
        destination=NavigationEndpointRequest(endpoint_type_code="LNG_LAT", longitude=destination[0], latitude=destination[1]),
        vessel_profile=vessel_profile,
        graph_version_id=graph_version_id,
        planning_mode_code=planning_mode_code,
        include_alternatives=include_alternatives,
        alternative_count=alternative_count,
    )


async def _seed_far_active_graph(session: AsyncSession) -> None:
    session.add(
        NavigationGraphVersion(
            id=2,
            version_code="TEST-FAR-GRAPH",
            version_name="Far graph",
            scope_code="OTHER",
            node_count=2,
            edge_count=3,
            channel_count=2,
            quality_score=95,
            status_code="READY",
            is_active=True,
        )
    )
    session.add_all(
        [
            _node(id=20, graph_version_id=2, lng=132.0, lat=43.0, code="FAR-N1"),
            _node(id=21, graph_version_id=2, lng=132.2, lat=43.0, code="FAR-N2"),
            _edge(
                id=20,
                graph_version_id=2,
                from_node_id=20,
                to_node_id=21,
                code="FAR-E1",
                geometry=_line((132.0, 43.0), (132.2, 43.0)),
                channel_id=20,
            ),
        ]
    )
    await session.commit()


async def _seed_disconnected_large_active_graph_and_far_fallback(session: AsyncSession) -> None:
    session.add_all(
        [
            NavigationGraphVersion(
                id=2,
                version_code="TEST-LARGE-DISCONNECTED-GRAPH",
                version_name="Large disconnected graph",
                scope_code="TEST",
                node_count=4,
                edge_count=3,
                channel_count=2,
                quality_score=80,
                status_code="READY",
                is_active=True,
            ),
            NavigationGraphVersion(
                id=3,
                version_code="TEST-FAR-FALLBACK-GRAPH",
                version_name="Far fallback graph",
                scope_code="OTHER",
                node_count=2,
                edge_count=1,
                channel_count=1,
                quality_score=80,
                status_code="READY",
                is_active=True,
            ),
        ]
    )
    session.add_all(
        [
            _node(id=20, graph_version_id=2, lng=120.0, lat=31.0, code="DG-N1"),
            _node(id=21, graph_version_id=2, lng=120.1, lat=31.0, code="DG-N2"),
            _node(id=22, graph_version_id=2, lng=120.2, lat=31.0, code="DG-N3"),
            _node(id=23, graph_version_id=2, lng=120.3, lat=31.0, code="DG-N4"),
            _edge(
                id=20,
                graph_version_id=2,
                from_node_id=20,
                to_node_id=21,
                code="DG-E1",
                geometry=_line((120.0, 31.0), (120.1, 31.0)),
            ),
            _edge(
                id=21,
                graph_version_id=2,
                from_node_id=22,
                to_node_id=23,
                code="DG-E2",
                geometry=_line((120.2, 31.0), (120.3, 31.0)),
            ),
            _node(id=30, graph_version_id=3, lng=132.0, lat=43.0, code="FAR2-N1"),
            _node(id=31, graph_version_id=3, lng=132.2, lat=43.0, code="FAR2-N2"),
            _edge(
                id=30,
                graph_version_id=3,
                from_node_id=30,
                to_node_id=31,
                code="FAR2-E1",
                geometry=_line((132.0, 43.0), (132.2, 43.0)),
                channel_id=30,
            ),
        ]
    )
    await session.commit()


async def _seed_strategy_graph(
    session: AsyncSession,
    *,
    direct_quality: str = "LOW_CONFIDENCE",
    direct_unknown: bool = True,
    direct_lock: bool = False,
) -> None:
    session.add(
        NavigationGraphVersion(
            id=1,
            version_code="TEST-STRATEGY-GRAPH",
            version_name="Strategy graph",
            scope_code="TEST",
            node_count=4,
            edge_count=5,
            channel_count=1,
            quality_score=95,
            status_code="READY",
            is_active=True,
        )
    )
    session.add_all(
        [
            _node(id=1, graph_version_id=1, lng=120.0, lat=31.0, code="N1", node_type_code="PORT"),
            _node(id=2, graph_version_id=1, lng=120.2, lat=31.0, code="N2", node_type_code="PORT"),
            _node(id=3, graph_version_id=1, lng=120.1, lat=31.08, code="N3"),
            _node(id=4, graph_version_id=1, lng=120.1, lat=30.94, code="N4"),
        ]
    )
    session.add_all(
        [
            _edge(
                id=1,
                graph_version_id=1,
                from_node_id=1,
                to_node_id=2,
                code="E-DIRECT",
                geometry=_line((120.0, 31.0), (120.1, 31.01), (120.2, 31.0)),
                length_km=10.0,
                quality_code=direct_quality,
                unknown_constraint_flag=direct_unknown,
                lock_required=direct_lock,
                confidence_score=50 if direct_quality == "LOW_CONFIDENCE" else 95,
            ),
            _edge(
                id=2,
                graph_version_id=1,
                from_node_id=1,
                to_node_id=3,
                code="E-SAFE-A",
                geometry=_line((120.0, 31.0), (120.1, 31.08)),
                length_km=6.0,
            ),
            _edge(
                id=3,
                graph_version_id=1,
                from_node_id=3,
                to_node_id=2,
                code="E-SAFE-B",
                geometry=_line((120.1, 31.08), (120.2, 31.0)),
                length_km=6.0,
            ),
            _edge(
                id=4,
                graph_version_id=1,
                from_node_id=1,
                to_node_id=4,
                code="E-ALT-LOWER",
                geometry=_line((120.0, 31.0), (120.1, 30.94)),
                length_km=6.5,
            ),
            _edge(
                id=5,
                graph_version_id=1,
                from_node_id=4,
                to_node_id=2,
                code="E-ALT-LOWER-B",
                geometry=_line((120.1, 30.94), (120.2, 31.0)),
                length_km=6.5,
            ),
        ]
    )
    await session.commit()


def test_navigation_route_generate_api_is_registered() -> None:
    assert "/navigation/routes/generate" in {getattr(route, "path", None) for route in api_router.routes}


def test_path_validator_reports_missing_production_water_and_boundary_context() -> None:
    issues = PathValidator().validate_spatial_context(
        _line((120.0, 31.0), (120.1, 31.0)),
        water_geometries=[],
        boundary_geometries=[],
    )

    assert {issue.issue_type_code for issue in issues} == {
        "UNKNOWN_WATER_AREA_CONTEXT",
        "UNKNOWN_CHANNEL_BOUNDARY_CONTEXT",
    }


def test_path_validator_fails_when_route_leaves_matched_water_body() -> None:
    water = {
        "type": "Polygon",
        "coordinates": [[
            [120.0, 31.01],
            [120.1, 31.01],
            [120.1, 31.02],
            [120.0, 31.02],
            [120.0, 31.01],
        ]],
    }
    boundary = {
        "type": "Polygon",
        "coordinates": [[
            [119.99, 30.99],
            [120.11, 30.99],
            [120.11, 31.03],
            [119.99, 31.03],
            [119.99, 30.99],
        ]],
    }

    issues = PathValidator().validate_spatial_context(
        _line((120.0, 31.0), (120.1, 31.0)),
        water_geometries=[shape(water)],
        boundary_geometries=[shape(boundary)],
    )

    assert "PATH_OUT_OF_WATER" in {issue.issue_type_code for issue in issues}


def test_audited_boundary_merge_counts_as_water_context() -> None:
    service = NavigationRoutingEngineService.__new__(NavigationRoutingEngineService)
    boundary = NavigationChannelBoundary(
        channel_id=1,
        geometry_json={"type": "Polygon", "coordinates": []},
        coverage_policy_code="AUTO_BOUNDARY_MERGE",
        source_trace_json={
            "boundary_integrity_audit": {"trust_code": "READY_WITH_WARNING"},
            "basemap_verification": {"status_code": "AUTO_VERIFIED_BY_LOCAL_WATER_BODY_AND_HIFLEET_TRAJECTORY_BOUNDARY_MERGE"},
            "selected_water_bodies": [{"water_body_id": 1, "water_name": "长江"}],
        },
    )

    assert service._boundary_counts_as_water_context(boundary)


def test_boundary_merge_without_ready_audit_stays_out_of_water_context() -> None:
    service = NavigationRoutingEngineService.__new__(NavigationRoutingEngineService)
    boundary = NavigationChannelBoundary(
        channel_id=1,
        geometry_json={"type": "Polygon", "coordinates": []},
        coverage_policy_code="AUTO_BOUNDARY_MERGE",
        source_trace_json={
            "boundary_integrity_audit": {"trust_code": "NEEDS_REVIEW"},
            "basemap_verification": {"status_code": "AUTO_VERIFIED_BY_LOCAL_WATER_BODY_AND_HIFLEET_TRAJECTORY_BOUNDARY_MERGE"},
            "selected_water_bodies": [{"water_body_id": 1, "water_name": "长江"}],
        },
    )

    assert not service._boundary_counts_as_water_context(boundary)


def test_osm_waterway_corridor_counts_as_water_context_with_ready_audit() -> None:
    service = NavigationRoutingEngineService.__new__(NavigationRoutingEngineService)
    boundary = NavigationChannelBoundary(
        channel_id=1,
        geometry_json={"type": "Polygon", "coordinates": []},
        coverage_policy_code="OSM_WATERWAY_CORRIDOR",
        source_trace_json={"boundary_integrity_audit": {"trust_code": "READY_WITH_WARNING"}},
    )

    assert service._boundary_counts_as_water_context(boundary)


def test_mixed_osm_corridor_counts_as_water_context_only_after_seed_validation() -> None:
    service = NavigationRoutingEngineService.__new__(NavigationRoutingEngineService)
    boundary = NavigationChannelBoundary(
        channel_id=1,
        geometry_json={"type": "Polygon", "coordinates": []},
        coverage_policy_code="MIXED_LOCAL_OSM_WATERWAY_CORRIDOR",
        source_trace_json={
            "boundary_integrity_audit": {"trust_code": "NEEDS_REVIEW"},
            "validation": {
                "line_is_simple": True,
                "boundary_coverage_ratio": 1.0,
                "blockers": [],
            },
        },
    )
    invalid_boundary = NavigationChannelBoundary(
        channel_id=1,
        geometry_json={"type": "Polygon", "coordinates": []},
        coverage_policy_code="MIXED_LOCAL_OSM_WATERWAY_CORRIDOR",
        source_trace_json={
            "validation": {
                "line_is_simple": False,
                "boundary_coverage_ratio": 1.0,
                "blockers": ["CENTERLINE_SELF_INTERSECTION"],
            },
        },
    )

    assert service._boundary_counts_as_water_context(boundary)
    assert not service._boundary_counts_as_water_context(invalid_boundary)


def test_quality_scorer_penalizes_validation_errors() -> None:
    snap = SnapResult(
        role="origin",
        snap_type="NODE",
        snap_distance_m=0,
        snap_confidence=100,
        snap_point=(120.0, 31.0),
    )

    result = QualityScorer().score(
        origin_snap=snap,
        destination_snap=SnapResult(
            role="destination",
            snap_type="NODE",
            snap_distance_m=0,
            snap_confidence=100,
            snap_point=(120.1, 31.0),
        ),
        search_result=SearchResult(node_path=[], segments=[], total_cost=0),
        validation_issues=[
            RouteIssue(
                "PATH_OUT_OF_WATER",
                "ERROR",
                "Route water-area coverage is too low",
            )
        ],
    )

    assert result.quality_code == "FAILED"
    assert result.quality_score < 75


def test_quality_scorer_keeps_warning_only_routes_reviewable() -> None:
    snap = SnapResult(
        role="origin",
        snap_type="NODE",
        snap_distance_m=900,
        snap_confidence=70,
        snap_point=(120.0, 31.0),
    )
    result = QualityScorer().score(
        origin_snap=snap,
        destination_snap=SnapResult(
            role="destination",
            snap_type="NODE",
            snap_distance_m=900,
            snap_confidence=70,
            snap_point=(120.1, 31.0),
        ),
        search_result=SearchResult(node_path=[], segments=[], total_cost=0),
        validation_issues=[
            RouteIssue(f"REVIEW_WARNING_{index}", "WARNING", "Route requires production review")
            for index in range(12)
        ],
    )

    assert result.quality_score < 60
    assert result.quality_code == "NEED_REVIEW"


@pytest.mark.asyncio
async def test_route_allows_boundary_review_for_boundary_derived_edges_and_connectors(session_maker) -> None:
    async with session_maker() as session:
        session.add(
            NavigationGraphVersion(
                id=1,
                version_code="TEST-BOUNDARY-REVIEW",
                version_name="Test boundary review",
                scope_code="TEST",
                node_count=3,
                edge_count=2,
                channel_count=1,
                quality_score=88,
                status_code="READY",
                is_active=True,
            )
        )
        session.add_all(
            [
                _node(id=1, graph_version_id=1, lng=120.0, lat=31.0, code="TN"),
                _node(id=2, graph_version_id=1, lng=120.01, lat=31.0, code="SNAP"),
                _node(id=3, graph_version_id=1, lng=120.1, lat=31.0, code="NEXT"),
                _edge(
                    id=1,
                    graph_version_id=1,
                    from_node_id=1,
                    to_node_id=2,
                    code="C-TN",
                    geometry=_line((120.0, 31.0), (120.01, 31.0)),
                    source_type_code="TRANSPORT_NODE_CONNECTOR",
                ),
                _edge(
                    id=2,
                    graph_version_id=1,
                    from_node_id=2,
                    to_node_id=3,
                    code="E-BOUNDARY-DERIVED",
                    geometry=_line((120.01, 31.0), (120.1, 31.0)),
                    source_type_code="BOUNDARY_DERIVED_CENTERLINE",
                    validation_summary_json={"issue_codes": ["BOUNDARY_DERIVED_NEEDS_OPERATOR_REVIEW"]},
                ),
            ]
        )
        await session.commit()

        service = NavigationRoutingEngineService(session)

        assert await service._route_allows_boundary_review([1, 2]) is True
        assert await service._route_allows_boundary_review([1]) is False


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
    assert response.alternatives == []
    assert response.explain is not None
    assert result.quality_summary_json["graph_load_margin_degree"] == 0.5
    assert result.quality_summary_json["loaded_edge_count"] == 2
    assert result.quality_summary_json["duration_detail"]["default_speed_kmh"] == 10.0
    assert result.quality_summary_json["planning_mode_code"] == "RECOMMENDED"
    assert "cost_breakdown_summary" in result.quality_summary_json
    assert result.quality_summary_json["edge_cost_breakdowns"]


@pytest.mark.asyncio
async def test_generate_route_shortest_prefers_distance_even_with_low_quality(session_maker) -> None:
    async with session_maker() as session:
        await _seed_strategy_graph(session)

        response = await NavigationRoutingEngineService(session).generate_route(
            _request(planning_mode_code="SHORTEST")
        )
        result = (await session.execute(select(NavigationRouteResult))).scalar_one()

    assert response.status_code == "SUCCESS"
    assert response.edge_ids == [1]
    assert result.quality_summary_json["planning_mode_code"] == "SHORTEST"
    assert result.quality_summary_json["edge_cost_breakdowns"][0]["quality_penalty"] == 0


@pytest.mark.asyncio
async def test_generate_route_safest_avoids_low_confidence_unknown_edge(session_maker) -> None:
    async with session_maker() as session:
        await _seed_strategy_graph(session)

        response = await NavigationRoutingEngineService(session).generate_route(
            _request(planning_mode_code="SAFEST")
    )

    assert response.status_code == "SUCCESS"
    assert 1 not in response.edge_ids
    assert response.explain is not None
    assert response.explain["planning_mode_code"] == "SAFEST"


@pytest.mark.asyncio
async def test_generate_route_lock_avoiding_reduces_lock_edges_when_alternative_exists(session_maker) -> None:
    async with session_maker() as session:
        await _seed_strategy_graph(session, direct_quality="READY", direct_unknown=False, direct_lock=True)

        response = await NavigationRoutingEngineService(session).generate_route(
            _request(planning_mode_code="LOCK_AVOIDING")
        )

    assert response.status_code == "SUCCESS"
    assert 1 not in response.edge_ids
    assert response.passed_lock_count == 0


@pytest.mark.asyncio
async def test_generate_route_returns_and_persists_deduped_alternatives(session_maker) -> None:
    async with session_maker() as session:
        await _seed_strategy_graph(session)

        response = await NavigationRoutingEngineService(session).generate_route(
            _request(include_alternatives=True, alternative_count=3)
        )
        rows = list((await session.execute(select(NavigationRouteResult).order_by(NavigationRouteResult.result_no))).scalars())

    assert response.status_code == "SUCCESS"
    assert len(response.alternatives) >= 1
    assert [row.result_no for row in rows] == list(range(1, len(rows) + 1))
    assert rows[0].result_type_code == "RECOMMENDED"
    assert all(row.result_type_code == "ALTERNATIVE" for row in rows[1:])
    assert rows[0].quality_summary_json["alternative_count"] == len(rows)
    assert response.alternatives[0].geometry_json is not None


@pytest.mark.asyncio
async def test_generate_route_expands_bbox_until_edges_are_loaded(session_maker) -> None:
    async with session_maker() as session:
        await _seed_bending_graph_requires_expanded_bbox(session)

        response = await NavigationRoutingEngineService(session).generate_route(
            _request(origin=(120.0, 31.0), destination=(121.0, 31.0))
        )
        result = (await session.execute(select(NavigationRouteResult))).scalar_one()

    assert response.status_code == "SUCCESS"
    assert result.quality_summary_json["graph_load_margin_degree"] >= 2.0
    assert result.quality_summary_json["loaded_edge_count"] == 2


@pytest.mark.asyncio
async def test_generate_route_falls_back_from_larger_active_graph_versions(session_maker) -> None:
    async with session_maker() as session:
        await _seed_ready_graph(session)
        await _seed_far_active_graph(session)

        response = await NavigationRoutingEngineService(session).generate_route(_request())
        result = (await session.execute(select(NavigationRouteResult))).scalar_one()

    assert response.status_code == "SUCCESS"
    assert response.graph_version_id == 1
    assert result.quality_summary_json["attempted_graph_version_ids"] == [2, 1]


@pytest.mark.asyncio
async def test_generate_route_respects_explicit_graph_version_without_fallback(session_maker) -> None:
    async with session_maker() as session:
        await _seed_ready_graph(session)
        await _seed_far_active_graph(session)

        response = await NavigationRoutingEngineService(session).generate_route(_request(graph_version_id=2))
        result = (await session.execute(select(NavigationRouteResult))).scalar_one()

    assert response.status_code == "FAILED"
    assert response.graph_version_id == 2
    assert response.error_code == "NO_ROUTING_EDGE_IN_EXPANDED_BBOX"
    assert result.quality_summary_json["attempted_graph_version_ids"] == [2]


@pytest.mark.asyncio
async def test_generate_route_preserves_preferred_graph_failure_after_all_candidates_fail(session_maker) -> None:
    async with session_maker() as session:
        await _seed_disconnected_large_active_graph_and_far_fallback(session)

        response = await NavigationRoutingEngineService(session).generate_route(
            _request(origin=(120.0, 31.0), destination=(120.3, 31.0))
        )
        request_row = (await session.execute(select(NavigationRouteRequest))).scalar_one()
        result = (await session.execute(select(NavigationRouteResult))).scalar_one()

    assert response.status_code == "FAILED"
    assert response.graph_version_id == 2
    assert response.error_code == "GRAPH_DISCONNECTED"
    assert request_row.graph_version_id == 2
    assert result.quality_summary_json["attempted_graph_version_ids"] == [2, 3]
    assert "later graph attempt ended with" in response.error_message


@pytest.mark.asyncio
async def test_successful_route_persists_blocked_edge_warning(session_maker) -> None:
    async with session_maker() as session:
        await _seed_ready_graph(session)
        session.add(
            _edge(
                id=3,
                graph_version_id=1,
                from_node_id=1,
                to_node_id=3,
                code="E-BLOCKED-DIRECT",
                geometry=_line((120.0, 31.0), (120.1, 31.01), (120.2, 31.0)),
                max_allowed_tonnage=100,
            )
        )
        await session.commit()

        response = await NavigationRoutingEngineService(session).generate_route(
            _request(vessel_profile=VesselProfileRequest(deadweight_ton=500))
        )
        issues = list((await session.execute(select(NavigationRouteQualityIssue))).scalars())

    assert response.status_code == "SUCCESS"
    assert "VSL_TONNAGE_EXCEEDS_LIMIT" in {issue.issue_type_code for issue in response.issues}
    assert "VSL_TONNAGE_EXCEEDS_LIMIT" in {issue.issue_type_code for issue in issues}


@pytest.mark.asyncio
async def test_duration_estimate_adds_lock_wait(session_maker) -> None:
    async with session_maker() as session:
        await _seed_ready_graph(session)
        edge = await session.get(NavigationGraphEdge, 1)
        assert edge is not None
        edge.lock_required = True
        await session.commit()

        response = await NavigationRoutingEngineService(session).generate_route(_request())
        result = (await session.execute(select(NavigationRouteResult))).scalar_one()

    detail = result.quality_summary_json["duration_detail"]
    assert response.passed_lock_count == 1
    assert detail["lock_wait_total_hour"] == 1.0
    assert response.estimated_duration_hour == detail["estimated_duration_hour"]
    assert response.estimated_duration_hour > detail["base_sailing_hour"]


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
    assert response.explain is not None
    assert response.explain["next_actions"]
    assert result_row.quality_summary_json["failure_explain"]["next_actions"]


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
async def test_hifleet_fallback_rejects_long_jump_reference_geometry(session_maker) -> None:
    async with session_maker() as session:
        request_row = NavigationRouteRequest(
            request_no="HIFLEET-LONG-JUMP",
            origin_lng=120.0,
            origin_lat=31.0,
            destination_lng=120.5,
            destination_lat=31.2,
            routing_preference_code="RECOMMENDED",
            status_code="FAILED",
            error_code="GRAPH_DISCONNECTED",
            error_message="local graph disconnected",
        )
        session.add(request_row)
        await session.flush()
        original_result = NavigationRouteResult(
            request_id=request_row.id,
            result_no=1,
            result_type_code="RECOMMENDED",
            status_code="FAILED",
            quality_code="FAILED",
            quality_score=0,
            provider_code="NAVIGATION_ENGINE",
            engine_code="NAVIGATION_ROUTING_ENGINE_V2",
        )
        session.add(original_result)
        await session.flush()
        original_response = NavigationRouteGenerateResponse(
            request_id=request_row.id,
            result_id=original_result.id,
            graph_version_id=1,
            status_code="FAILED",
            provider_code="NAVIGATION_ENGINE",
            source_type_code="NAVIGATION_ROUTING_ENGINE_V2",
            quality_code="FAILED",
            quality_score=0,
            issues=[
                NavigationRouteIssueResponse(
                    issue_type_code="GRAPH_DISCONNECTED",
                    severity_code="ERROR",
                    message="local graph disconnected",
                )
            ],
            error_code="GRAPH_DISCONNECTED",
            error_message="local graph disconnected",
        )
        hifleet = RouteGeometryResult(
            geometry=_line((120.0, 31.0), (120.01, 31.01), (120.5, 31.2)),
            source="hifleet",
            provider="HIFLEET",
            provider_trace_id=None,
            status="ready",
            distance_km=80,
            estimated_duration_hour=8,
            raw_summary={"cache_hit": True, "hifleet_cache_id": 88, "point_count": 3},
        )

        response = await NavigationRoutingEngineService(session)._persist_hifleet_fallback(
            request_row=request_row,
            original_response=original_response,
            hifleet=hifleet,
            planning_mode_code="RECOMMENDED",
            include_explain=True,
        )
        request_row = await session.get(NavigationRouteRequest, request_row.id)
        fallback_result = (
            await session.execute(
                select(NavigationRouteResult).where(NavigationRouteResult.result_type_code == "HIFLEET_REFERENCE_REJECTED")
            )
        ).scalar_one()
        issues = list(
            (
                await session.execute(
                    select(NavigationRouteQualityIssue).where(NavigationRouteQualityIssue.route_result_id == fallback_result.id)
                )
            ).scalars()
        )

    assert response.status_code == "FAILED"
    assert response.geometry_json is None
    assert response.error_code == "HIFLEET_REFERENCE_LONG_JUMP"
    assert request_row is not None
    assert request_row.status_code == "FAILED"
    assert fallback_result.provider_code == "HIFLEET"
    assert fallback_result.quality_code == "FAILED"
    assert fallback_result.geometry_json is None
    assert fallback_result.quality_summary_json["hifleet_geometry_returnable"] is False
    assert fallback_result.quality_summary_json["hifleet_geometry_quality"]["max_segment_km"] >= 15
    assert "HIFLEET_REFERENCE_LONG_JUMP" in {issue.issue_type_code for issue in issues}


@pytest.mark.asyncio
async def test_centerline_seed_fallback_is_diagnostic_not_user_returnable(session_maker) -> None:
    async with session_maker() as session:
        session.add(
            NavigationChannel(
                id=1,
                channel_code="NC-SEED-DIAG",
                channel_name="Seed diagnostic channel",
                channel_type_code="RIVER",
                planning_level_code="LOCAL",
                source_version="TEST",
            )
        )
        centerline_geometry = _line((120.0, 31.0), (120.1, 31.0), (120.2, 31.0))
        centerline = NavigationChannelCenterline(
            id=10,
            channel_id=1,
            centerline_code="CL-SEED-DIAG",
            centerline_name="Seed diagnostic centerline",
            geometry_json=centerline_geometry,
            source_type_code="WAYBILL_ROUTE_REFERENCE",
            direction_code="BIDIRECTIONAL",
            is_main_line=True,
            confidence_score=95,
            quality_code="READY",
            review_status_code="PUBLISHED",
            is_current=True,
            bbox_min_lng=120.0,
            bbox_min_lat=31.0,
            bbox_max_lng=120.2,
            bbox_max_lat=31.0,
        )
        session.add(centerline)
        request_row = NavigationRouteRequest(
            request_no="CENTERLINE-SEED-DIAG",
            origin_lng=120.0,
            origin_lat=31.0,
            destination_lng=120.2,
            destination_lat=31.0,
            routing_preference_code="RECOMMENDED",
            status_code="FAILED",
            error_code="GRAPH_DISCONNECTED",
            error_message="local graph disconnected",
        )
        session.add(request_row)
        await session.flush()
        original_result = NavigationRouteResult(
            request_id=request_row.id,
            result_no=1,
            result_type_code="RECOMMENDED",
            status_code="FAILED",
            quality_code="FAILED",
            quality_score=0,
            provider_code="NAVIGATION_ENGINE",
            engine_code="NAVIGATION_ROUTING_ENGINE_V2",
        )
        session.add(original_result)
        await session.flush()
        original_response = NavigationRouteGenerateResponse(
            request_id=request_row.id,
            result_id=original_result.id,
            graph_version_id=1,
            status_code="FAILED",
            provider_code="NAVIGATION_ENGINE",
            source_type_code="NAVIGATION_ROUTING_ENGINE_V2",
            quality_code="FAILED",
            quality_score=0,
            issues=[
                NavigationRouteIssueResponse(
                    issue_type_code="GRAPH_DISCONNECTED",
                    severity_code="ERROR",
                    message="local graph disconnected",
                )
            ],
            error_code="GRAPH_DISCONNECTED",
            error_message="local graph disconnected",
        )
        candidate_geometry = _line((120.0, 31.0), (120.1, 31.0), (120.2, 31.0))
        candidate = {
            "centerline": centerline,
            "geometry_json": candidate_geometry,
            "distance_km": 22.2,
            "origin_snap": SnapResult(
                role="ORIGIN",
                snap_type="CENTERLINE_SEED",
                snap_distance_m=0,
                snap_confidence=95,
                snap_point=(120.0, 31.0),
                quality_code="HIGH",
            ),
            "destination_snap": SnapResult(
                role="DESTINATION",
                snap_type="CENTERLINE_SEED",
                snap_distance_m=0,
                snap_confidence=95,
                snap_point=(120.2, 31.0),
                quality_code="HIGH",
            ),
            "quality_score": 95,
            "quality_code": "READY",
            "issues": [],
        }

        response = await NavigationRoutingEngineService(session)._persist_centerline_seed_fallback(
            request_row=request_row,
            original_response=original_response,
            candidate=candidate,
            planning_mode_code="RECOMMENDED",
            include_explain=True,
        )
        request_row = await session.get(NavigationRouteRequest, request_row.id)
        fallback_result = (
            await session.execute(
                select(NavigationRouteResult).where(NavigationRouteResult.result_type_code == "CENTERLINE_SEED_FALLBACK")
            )
        ).scalar_one()
        issue = (
            await session.execute(
                select(NavigationRouteQualityIssue).where(
                    NavigationRouteQualityIssue.route_result_id == fallback_result.id,
                    NavigationRouteQualityIssue.issue_type_code == "CENTERLINE_SEED_NOT_GRAPH_VALIDATED",
                )
            )
        ).scalar_one()

    assert response.status_code == "FAILED"
    assert response.geometry_json is None
    assert response.error_code == "CENTERLINE_SEED_NOT_GRAPH_VALIDATED"
    assert response.explain is not None
    assert response.explain["centerline_seed_returnable"] is False
    assert request_row is not None
    assert request_row.status_code == "FAILED"
    assert fallback_result.geometry_json is None
    assert fallback_result.quality_code == "FAILED"
    assert fallback_result.quality_summary_json["candidate_geometry_json"] == candidate_geometry
    assert issue.geometry_json == candidate_geometry


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
    assert response.explain is not None
    assert response.explain["blocked_edge_summary"]["VSL_TONNAGE_EXCEEDS_LIMIT"] == 2
