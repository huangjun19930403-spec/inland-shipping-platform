from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.v1 import api_router
from app.models import (
    NavigationChannelCenterline,
    NavigationChannelWaterBodyMatch,
    NavigationGraphEdge,
    NavigationGraphNode,
    NavigationGraphVersion,
    NavigationRouteQualityIssue,
    NavigationRouteRequest,
    NavigationRouteResult,
    NavigationWaterArea,
    NavigationWaterBody,
    NavigationWaterBodyFeatureLink,
)
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.models.base import Base
from app.modules.navigation.coordinate_transform import bbox_to_gcj02
from app.modules.navigation.map_layer_service import NavigationMapLayerService


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


def _polygon() -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[
            [120.0, 31.0],
            [120.2, 31.0],
            [120.2, 31.2],
            [120.0, 31.2],
            [120.0, 31.0],
        ]],
    }


async def _seed_layers(session: AsyncSession) -> None:
    session.add(
        NavigationWaterArea(
            id=1,
            source_code="TEST_RIVER",
            source_layer_name="rx",
            source_object_id="1",
            water_name="测试水域",
            normalized_water_name="测试水域",
            water_level=1,
            water_type_code="RIVER",
            geometry_json=_polygon(),
            simplified_geometry_low_json=_polygon(),
            geometry_status_code="VALID",
            bbox_min_lng=120.0,
            bbox_min_lat=31.0,
            bbox_max_lng=120.2,
            bbox_max_lat=31.2,
            is_enabled=True,
        )
    )
    session.add(
        NavigationWaterBody(
            id=1,
            water_body_code="WB-TEST",
            water_body_name="测试水域",
            normalized_water_name="测试水域",
            source_code="TEST_RIVER",
            body_role_code="PRIMARY_HIERARCHY",
            dedupe_status_code="DEDUPED",
            source_layer_name="rx",
            water_type_code="RIVER",
            geometry_wgs84_json=_polygon(),
            bbox_min_lng=120.0,
            bbox_min_lat=31.0,
            bbox_max_lng=120.2,
            bbox_max_lat=31.2,
            feature_count=1,
            enabled_feature_count=1,
            source_water_area_ids_json=[1],
            is_enabled=True,
        )
    )
    session.add(NavigationWaterBodyFeatureLink(water_body_id=1, water_area_id=1, link_role_code="PRIMARY_HIERARCHY", is_primary=True))
    session.add(
        NavigationChannel(
            id=1,
            channel_code="TEST-CHANNEL",
            channel_name="测试航道",
            channel_type_code="CANAL",
            planning_level_code="REGIONAL_IMPORTANT",
            source_version="TEST",
            is_enabled=True,
            display_priority=10,
        )
    )
    session.add(
        NavigationChannelBoundary(
            id=1,
            channel_id=1,
            geometry_json=_polygon(),
            boundary_paths_low=[[
                [120.0, 31.0],
                [120.2, 31.0],
                [120.2, 31.2],
                [120.0, 31.2],
                [120.0, 31.0],
            ]],
            bbox_min_lng=120.0,
            bbox_min_lat=31.0,
            bbox_max_lng=120.2,
            bbox_max_lat=31.2,
            geometry_status_code="AVAILABLE",
            boundary_quality_code="HIGH_CONFIDENCE",
            connectivity_status_code="CONNECTED",
            repair_status_code="NONE",
            is_current=True,
        )
    )
    session.add(
        NavigationChannelCenterline(
            id=1,
            channel_id=1,
            centerline_code="CL-1",
            centerline_name="测试中心线",
            geometry_json=_line((120.0, 31.1), (120.2, 31.1)),
            source_type_code="MANUAL",
            quality_code="READY",
            review_status_code="PUBLISHED",
            confidence_score=95,
            is_current=True,
            bbox_min_lng=120.0,
            bbox_min_lat=31.1,
            bbox_max_lng=120.2,
            bbox_max_lat=31.1,
        )
    )
    session.add(
        NavigationGraphVersion(
            id=1,
            version_code="GV-1",
            version_name="Graph fixture",
            scope_code="TEST",
            node_count=2,
            edge_count=1,
            channel_count=1,
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
                node_type_code="CENTERLINE_VERTEX",
                longitude=120.0,
                latitude=31.1,
                geometry_json={"type": "Point", "coordinates": [120.0, 31.1]},
                is_enabled=True,
                quality_code="READY",
                source_type_code="CENTERLINE_VERTEX",
            ),
            NavigationGraphNode(
                id=2,
                graph_version_id=1,
                node_code="N2",
                node_type_code="CENTERLINE_VERTEX",
                longitude=120.2,
                latitude=31.1,
                geometry_json={"type": "Point", "coordinates": [120.2, 31.1]},
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
            channel_id=1,
            geometry_json=_line((120.0, 31.1), (120.2, 31.1)),
            length_km=22.2,
            direction_code="BIDIRECTIONAL",
            routing_enabled=True,
            quality_code="READY",
            source_type_code="MANUAL",
            confidence_score=95,
            unknown_constraint_flag=True,
        )
    )
    session.add(
        NavigationRouteRequest(
            id=1,
            request_no="REQ-1",
            origin_lng=120.0,
            origin_lat=31.1,
            destination_lng=120.2,
            destination_lat=31.1,
            routing_preference_code="RECOMMENDED",
            status_code="SUCCESS",
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    session.add(
        NavigationRouteResult(
            id=1,
            request_id=1,
            result_no=1,
            result_type_code="RECOMMENDED",
            status_code="READY_WITH_WARNING",
            geometry_json=_line((120.0, 31.1), (120.2, 31.1)),
            distance_km=22.2,
            edge_ids=[1],
            channel_ids=[1],
            quality_score=86,
            quality_code="READY_WITH_WARNING",
            provider_code="NAVIGATION_ENGINE",
            engine_code="NAVIGATION_ROUTING_ENGINE_V1",
        )
    )
    session.add(
        NavigationRouteQualityIssue(
            id=1,
            route_result_id=1,
            issue_type_code="UNKNOWN_CONSTRAINT_DATA",
            severity_code="WARNING",
            geometry_json={"type": "Point", "coordinates": [120.1, 31.1]},
            message="约束数据缺失",
        )
    )
    await session.commit()


def test_navigation_map_layers_api_is_registered() -> None:
    assert "/navigation/map-layers" in {getattr(route, "path", None) for route in api_router.routes}


@pytest.mark.asyncio
async def test_map_layers_loads_bbox_limited_features(session_maker) -> None:
    async with session_maker() as session:
        await _seed_layers(session)

        response = await NavigationMapLayerService(session).get_layers(
            min_lng=119.9,
            min_lat=30.9,
            max_lng=120.3,
            max_lat=31.3,
            channel_id=None,
            route_result_id=1,
            include_water_area=True,
            include_boundary=True,
            include_centerline=True,
            include_graph_edge=True,
            limit=20,
        )

    assert response.coordinate_system_code == "WGS84"
    assert response.display_coordinate_system_code == "GCJ02_AMAP"
    assert response.bbox == bbox_to_gcj02({"min_lng": 119.9, "min_lat": 30.9, "max_lng": 120.3, "max_lat": 31.3})
    assert [item.layer_type_code for item in response.water_areas] == ["WATER_AREA"]
    assert [item.layer_type_code for item in response.channel_boundaries] == ["CHANNEL_BOUNDARY"]
    assert [item.layer_type_code for item in response.centerlines] == ["CENTERLINE"]
    assert [item.layer_type_code for item in response.graph_edges] == ["GRAPH_EDGE"]
    assert response.route_results[0].properties["quality_code"] == "READY_WITH_WARNING"
    assert response.quality_issues[0].properties["issue_type_code"] == "UNKNOWN_CONSTRAINT_DATA"


@pytest.mark.asyncio
async def test_map_layers_only_show_active_ready_graph_edges(session_maker) -> None:
    async with session_maker() as session:
        await _seed_layers(session)
        session.add(
            NavigationGraphVersion(
                id=2,
                version_code="GV-OLD",
                version_name="Old graph",
                scope_code="TEST",
                node_count=2,
                edge_count=1,
                channel_count=1,
                status_code="READY",
                is_active=False,
            )
        )
        session.add_all(
            [
                NavigationGraphNode(
                    id=3,
                    graph_version_id=2,
                    node_code="OLD-N1",
                    node_type_code="CENTERLINE_VERTEX",
                    longitude=120.0,
                    latitude=31.12,
                    geometry_json={"type": "Point", "coordinates": [120.0, 31.12]},
                    is_enabled=True,
                    quality_code="READY",
                    source_type_code="CENTERLINE_VERTEX",
                ),
                NavigationGraphNode(
                    id=4,
                    graph_version_id=2,
                    node_code="OLD-N2",
                    node_type_code="CENTERLINE_VERTEX",
                    longitude=120.2,
                    latitude=31.12,
                    geometry_json={"type": "Point", "coordinates": [120.2, 31.12]},
                    is_enabled=True,
                    quality_code="READY",
                    source_type_code="CENTERLINE_VERTEX",
                ),
                NavigationGraphEdge(
                    id=2,
                    graph_version_id=2,
                    edge_code="OLD-E1",
                    from_node_id=3,
                    to_node_id=4,
                    channel_id=1,
                    geometry_json=_line((120.0, 31.12), (120.2, 31.12)),
                    length_km=22.2,
                    direction_code="BIDIRECTIONAL",
                    routing_enabled=True,
                    quality_code="READY",
                    source_type_code="MANUAL",
                    confidence_score=95,
                ),
            ]
        )
        await session.commit()

        response = await NavigationMapLayerService(session).get_layers(
            min_lng=119.9,
            min_lat=30.9,
            max_lng=120.3,
            max_lat=31.3,
            channel_id=None,
            route_result_id=None,
            include_water_area=False,
            include_boundary=False,
            include_centerline=False,
            include_graph_edge=True,
            limit=20,
        )

    assert [item.id for item in response.graph_edges] == [1]
    assert response.warnings == []


@pytest.mark.asyncio
async def test_map_layers_warns_without_active_ready_graph_version(session_maker) -> None:
    async with session_maker() as session:
        await _seed_layers(session)
        version = await session.get(NavigationGraphVersion, 1)
        assert version is not None
        version.is_active = False
        await session.commit()

        response = await NavigationMapLayerService(session).get_layers(
            min_lng=119.9,
            min_lat=30.9,
            max_lng=120.3,
            max_lat=31.3,
            channel_id=None,
            route_result_id=1,
            include_water_area=False,
            include_boundary=False,
            include_centerline=False,
            include_graph_edge=True,
            limit=20,
        )

    assert response.graph_edges == []
    assert response.route_results
    assert "NO_ACTIVE_READY_GRAPH_VERSION" in response.warnings


@pytest.mark.asyncio
async def test_map_layers_requires_bbox_for_background_layers(session_maker) -> None:
    async with session_maker() as session:
        await _seed_layers(session)

        response = await NavigationMapLayerService(session).get_layers(
            min_lng=None,
            min_lat=None,
            max_lng=None,
            max_lat=None,
            channel_id=None,
            route_result_id=None,
            include_water_area=True,
            include_boundary=True,
            include_centerline=True,
            include_graph_edge=True,
            limit=20,
        )

    assert response.water_areas == []
    assert response.graph_edges == []
    assert response.warnings == ["MAP_LAYER_BBOX_REQUIRED"]


@pytest.mark.asyncio
async def test_map_layers_can_load_selected_water_area_ids_without_channel_or_bbox(session_maker) -> None:
    async with session_maker() as session:
        await _seed_layers(session)

        response = await NavigationMapLayerService(session).get_layers(
            min_lng=None,
            min_lat=None,
            max_lng=None,
            max_lat=None,
            channel_id=None,
            route_result_id=None,
            include_water_area=True,
            include_boundary=False,
            include_centerline=False,
            include_graph_edge=False,
            limit=20,
            water_area_ids=[1],
        )

    assert response.warnings == []
    assert response.bbox is not None
    assert [item.id for item in response.water_areas] == [1]
    assert response.water_areas[0].layer_type_code == "SELECTED_WATER_AREA"
    assert response.channel_boundaries == []


@pytest.mark.asyncio
async def test_map_layers_with_channel_id_uses_persisted_matches_not_fixed_bbox(session_maker) -> None:
    async with session_maker() as session:
        await _seed_layers(session)
        session.add(
            NavigationWaterArea(
                id=2,
                source_code="TEST_RIVER",
                source_layer_name="rx",
                source_object_id="2",
                water_name="远处水域",
                normalized_water_name="远处水域",
                water_level=1,
                water_type_code="RIVER",
                geometry_json={
                    "type": "Polygon",
                    "coordinates": [[[122.0, 32.0], [122.1, 32.0], [122.1, 32.1], [122.0, 32.1], [122.0, 32.0]]],
                },
                geometry_status_code="VALID",
                bbox_min_lng=122.0,
                bbox_min_lat=32.0,
                bbox_max_lng=122.1,
                bbox_max_lat=32.1,
                is_enabled=True,
            )
        )
        session.add(
            NavigationChannelWaterBodyMatch(
                id=1,
                channel_id=1,
                water_body_id=1,
                match_batch_code="TEST-BATCH",
                match_type_code="EXACT_NAME",
                matched_term="测试水域",
                score=95,
                confidence_code="HIGH_CONFIDENCE",
                issue_codes=[],
                is_current=True,
                source_water_area_ids_json=[1],
            )
        )
        await session.commit()

        response = await NavigationMapLayerService(session).get_layers(
            min_lng=None,
            min_lat=None,
            max_lng=None,
            max_lat=None,
            channel_id=1,
            route_result_id=None,
            include_water_area=True,
            include_boundary=True,
            include_centerline=True,
            include_graph_edge=True,
            limit=20,
        )

    assert response.warnings == []
    assert [item.id for item in response.water_areas] == [1]
    assert response.water_areas[0].layer_type_code == "MATCHED_WATER_AREA"
    assert response.water_areas[0].properties["match_batch_code"] == "TEST-BATCH"
    assert [item.properties["channel_id"] for item in response.channel_boundaries] == [1]
