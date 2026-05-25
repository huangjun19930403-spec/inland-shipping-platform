from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.models import (
    NavigationChannelCenterline,
    NavigationChannelWaterBodyMatch,
    NavigationGeometryDraft,
    NavigationGraphVersion,
    NavigationWaterArea,
    NavigationWaterBody,
    NavigationWaterBodyFeatureLink,
)
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.models.base import Base
from app.modules.navigation.schemas import (
    NavigationGeometryDraftCreateRequest,
    NavigationGraphBuildRequest,
    NavigationWaterBodyMatchCreateRequest,
    NavigationWaterBodyNameUpdateRequest,
)
from app.modules.navigation.workbench_service import NavigationWorkbenchService


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


def _line() -> dict:
    return {"type": "LineString", "coordinates": [[120.0, 31.0], [120.12, 31.06], [120.22, 31.1]]}


def _polygon() -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[
            [119.98, 30.98],
            [120.24, 30.98],
            [120.24, 31.12],
            [119.98, 31.12],
            [119.98, 30.98],
        ]],
    }


async def _seed_channel(session: AsyncSession) -> None:
    session.add(
        NavigationChannel(
            id=1,
            channel_code="TEST-CHANNEL",
            channel_name="测试航道",
            channel_type_code="CANAL",
            planning_level_code="REAL_TEST",
            ais_scope_code="INCLUDED",
            source_version="test",
            is_enabled=True,
            display_priority=10,
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_geometry_draft_publish_centerline_and_manual_graph_build(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        service = NavigationWorkbenchService(session)

        draft = await service.create_geometry_draft(
            NavigationGeometryDraftCreateRequest(
                draft_type_code="CENTERLINE",
                draft_name="测试中心线草稿",
                channel_id=1,
                geometry_json=_line(),
                source_type_code="GEOJSON_PASTE",
            ),
            created_by=7,
        )
        assert draft.status_code == "DRAFT"

        published = await service.publish_geometry_draft(draft.id, published_by=8)
        centerline_count = await session.scalar(select(func.count()).select_from(NavigationChannelCenterline))

        build = await service.build_graph_version(
            NavigationGraphBuildRequest(version_code="TEST-WORKBENCH-GRAPH", scope_code="TEST", activate=False),
            created_by=8,
        )
        graph_version = await session.get(NavigationGraphVersion, build.graph_version_id)

    assert published.status_code == "PUBLISHED"
    assert published.publish_target_type_code == "CENTERLINE"
    assert centerline_count == 1
    assert build.status_code == "READY"
    assert build.edge_count >= 1
    assert graph_version is not None
    assert graph_version.is_active is False


@pytest.mark.asyncio
async def test_boundary_publish_preserves_seed_history_and_switches_current(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        session.add(
            NavigationChannelBoundary(
                id=1,
                channel_id=1,
                geometry_json=_polygon(),
                boundary_paths_low=_polygon()["coordinates"],
                bbox_min_lng=119.98,
                bbox_min_lat=30.98,
                bbox_max_lng=120.24,
                bbox_max_lat=31.12,
                geometry_status_code="AVAILABLE",
                boundary_quality_code="SEED_APPROVED",
                connectivity_status_code="CONNECTED",
                repair_status_code="NONE",
                coverage_policy_code="SEED_BOUNDARY",
                is_current=True,
            )
        )
        await session.commit()
        service = NavigationWorkbenchService(session)

        draft = await service.create_geometry_draft(
            NavigationGeometryDraftCreateRequest(
                draft_type_code="BOUNDARY",
                draft_name="测试边界草稿",
                channel_id=1,
                geometry_json=_polygon(),
                source_type_code="GEOJSON_PASTE",
            ),
            created_by=7,
        )
        published = await service.publish_geometry_draft(draft.id, published_by=8)
        boundaries = list((await session.execute(select(NavigationChannelBoundary).order_by(NavigationChannelBoundary.id))).scalars())
        drafts = list((await session.execute(select(NavigationGeometryDraft))).scalars())

    assert published.publish_target_type_code == "BOUNDARY"
    assert len(boundaries) == 2
    assert boundaries[0].coverage_policy_code == "SEED_BOUNDARY"
    assert boundaries[0].is_current is False
    assert boundaries[1].coverage_policy_code == "MANUAL_DRAW"
    assert boundaries[1].is_current is True
    assert drafts[0].status_code == "PUBLISHED"


@pytest.mark.asyncio
async def test_geometry_draft_can_be_archived_before_publish(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        service = NavigationWorkbenchService(session)

        draft = await service.create_geometry_draft(
            NavigationGeometryDraftCreateRequest(
                draft_type_code="CENTERLINE",
                draft_name="待删除中心线草稿",
                channel_id=1,
                geometry_json=_line(),
                source_type_code="GEOJSON_PASTE",
            ),
            created_by=7,
        )
        archived = await service.archive_geometry_draft(draft.id)
        drafts = await service.list_geometry_drafts(channel_id=1)

    assert archived.status_code == "ARCHIVED"
    assert drafts == []


@pytest.mark.asyncio
async def test_graph_build_without_approved_centerline_fails_with_real_scope(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        service = NavigationWorkbenchService(session)

        build = await service.build_graph_version(
            NavigationGraphBuildRequest(version_code="TEST-REAL-NO-CENTERLINE", activate=False),
            created_by=8,
        )
        graph_version = await session.get(NavigationGraphVersion, build.graph_version_id)

    assert build.status_code == "FAILED"
    assert build.node_count == 0
    assert build.edge_count == 0
    assert graph_version is not None
    assert graph_version.scope_code == "REAL-JS-YRD"
    assert graph_version.validation_report_json["issues"][0]["issue_code"] == "NO_APPROVED_CENTERLINE"


@pytest.mark.asyncio
async def test_workbench_lists_channel_water_body_matches(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        session.add(
            NavigationWaterArea(
                id=1,
                source_code="TEST_RIVER",
                source_layer_name="rx",
                source_object_id="1",
                water_name="测试水域",
                normalized_water_name="测试水域",
                water_type_code="RIVER",
                geometry_json=_polygon(),
                geometry_status_code="VALID",
                bbox_min_lng=119.98,
                bbox_min_lat=30.98,
                bbox_max_lng=120.24,
                bbox_max_lat=31.12,
                is_enabled=True,
            )
        )
        session.add(
            NavigationWaterBody(
                id=1,
                water_body_code="WB-1",
                water_body_name="测试水域",
                normalized_water_name="测试水域",
                source_code="RIVER_SHAPEFILE_2026",
                body_role_code="PRIMARY_HIERARCHY",
                dedupe_status_code="DEDUPED",
                source_layer_name="rx",
                water_type_code="RIVER",
                geometry_wgs84_json=_polygon(),
                bbox_min_lng=119.98,
                bbox_min_lat=30.98,
                bbox_max_lng=120.24,
                bbox_max_lat=31.12,
                feature_count=1,
                enabled_feature_count=1,
                source_water_area_ids_json=[1],
                is_enabled=True,
            )
        )
        session.add(NavigationWaterBodyFeatureLink(water_body_id=1, water_area_id=1, link_role_code="PRIMARY_HIERARCHY"))
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

        service = NavigationWorkbenchService(session)
        summary = await service.summary()
        matches = await service.list_water_body_matches(channel_id=1)
        water_bodies = await service.list_water_bodies(channel_id=1, page=1, page_size=20)

    assert summary.channels[0].current_water_body_match_count == 1
    assert summary.channels[0].water_body_match_status_code == "READY"
    assert matches.current_match_count == 1
    assert matches.items[0].water_name == "测试水域"
    assert water_bodies.total == 1
    assert water_bodies.items[0].water_name == "测试水域"
    assert water_bodies.items[0].is_matched is True
    assert water_bodies.items[0].match_count == 1
    assert water_bodies.items[0].matched_channels[0]["channel_code"] == "TEST-CHANNEL"


@pytest.mark.asyncio
async def test_workbench_water_area_summary_and_unmatched_filter(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        session.add_all(
            [
                NavigationWaterArea(
                    id=1,
                    source_code="RIVER_SHAPEFILE_2026",
                    source_layer_name="rx",
                    source_object_id="1",
                    water_name="已归属水域",
                    normalized_water_name="已归属水域",
                    water_type_code="RIVER",
                    geometry_json=_polygon(),
                    geometry_status_code="VALID",
                    bbox_min_lng=119.98,
                    bbox_min_lat=30.98,
                    bbox_max_lng=120.24,
                    bbox_max_lat=31.12,
                    center_lng=120.11,
                    center_lat=31.05,
                    is_enabled=True,
                ),
                NavigationWaterArea(
                    id=2,
                    source_code="RIVER_SHAPEFILE_2026",
                    source_layer_name="五级水系",
                    source_object_id="2",
                    water_name=None,
                    normalized_water_name=None,
                    water_type_code="RIVER",
                    geometry_json=_polygon(),
                    geometry_status_code="VALID",
                    bbox_min_lng=119.98,
                    bbox_min_lat=30.98,
                    bbox_max_lng=120.24,
                    bbox_max_lat=31.12,
                    is_enabled=True,
                ),
            ]
        )
        session.add_all(
            [
                NavigationWaterBody(
                    id=1,
                    water_body_code="WB-MATCHED",
                    water_body_name="已归属水域",
                    normalized_water_name="已归属水域",
                    source_code="RIVER_SHAPEFILE_2026",
                    body_role_code="PRIMARY_HIERARCHY",
                    dedupe_status_code="DEDUPED",
                    source_layer_name="rx",
                    water_type_code="RIVER",
                    feature_count=1,
                    enabled_feature_count=1,
                    source_water_area_ids_json=[1],
                    is_enabled=True,
                ),
                NavigationWaterBody(
                    id=2,
                    water_body_code="WB-UNMATCHED",
                    water_body_name=None,
                    normalized_water_name=None,
                    source_code="RIVER_SHAPEFILE_2026",
                    body_role_code="PRIMARY_HIERARCHY",
                    dedupe_status_code="DEDUPED",
                    source_layer_name="五级水系",
                    water_type_code="RIVER",
                    feature_count=1,
                    enabled_feature_count=1,
                    source_water_area_ids_json=[2],
                    name_status_code="UNNAMED",
                    is_enabled=True,
                ),
            ]
        )
        session.add_all(
            [
                NavigationWaterBodyFeatureLink(water_body_id=1, water_area_id=1, link_role_code="PRIMARY_HIERARCHY"),
                NavigationWaterBodyFeatureLink(water_body_id=2, water_area_id=2, link_role_code="PRIMARY_HIERARCHY"),
            ]
        )
        session.add(
            NavigationChannelWaterBodyMatch(
                id=1,
                channel_id=1,
                water_body_id=1,
                match_batch_code="TEST-BATCH",
                match_type_code="MANUAL_ADD",
                score=90,
                confidence_code="MANUAL_CONFIRMED",
                issue_codes=[],
                is_current=True,
                source_water_area_ids_json=[1],
            )
        )
        await session.commit()

        service = NavigationWorkbenchService(session)
        summary = await service.water_area_summary()
        unmatched = await service.list_water_bodies(only_unmatched=True, page=1, page_size=20)

    assert summary.real_count == 2
    assert summary.named_count == 1
    assert summary.unnamed_count == 1
    assert summary.matched_water_body_count == 1
    assert summary.unmatched_water_body_count == 1
    assert {item.source_layer_name: item.count for item in summary.layer_counts} == {"rx": 1, "五级水系": 1}
    assert unmatched.total == 1
    assert unmatched.items[0].id == 2


@pytest.mark.asyncio
async def test_workbench_water_bodies_group_named_features_and_features_endpoint(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        session.add_all(
            [
                NavigationWaterArea(
                    id=1,
                    source_code="RIVER_SHAPEFILE_2026",
                    source_layer_name="一级水系",
                    source_layer_code="LEVEL_1",
                    source_layer_display_name="一级水系",
                    source_layer_role_code="HIERARCHY_LEVEL",
                    source_layer_order=1,
                    source_object_id="1",
                    water_name="长江",
                    normalized_water_name="长江",
                    water_type_code="RIVER",
                    geometry_json=_polygon(),
                    geometry_status_code="REPAIRED",
                    bbox_min_lng=104.0,
                    bbox_min_lat=28.0,
                    bbox_max_lng=112.0,
                    bbox_max_lat=31.0,
                    area_km2=10,
                    is_enabled=True,
                ),
                NavigationWaterArea(
                    id=2,
                    source_code="RIVER_SHAPEFILE_2026",
                    source_layer_name="一级水系",
                    source_layer_code="LEVEL_1",
                    source_layer_display_name="一级水系",
                    source_layer_role_code="HIERARCHY_LEVEL",
                    source_layer_order=1,
                    source_object_id="2",
                    water_name="长江",
                    normalized_water_name="长江",
                    water_type_code="RIVER",
                    geometry_json=_polygon(),
                    geometry_status_code="REPAIRED",
                    bbox_min_lng=112.0,
                    bbox_min_lat=29.0,
                    bbox_max_lng=122.0,
                    bbox_max_lat=32.0,
                    area_km2=20,
                    is_enabled=True,
                ),
                NavigationWaterArea(
                    id=3,
                    source_code="RIVER_SHAPEFILE_2026",
                    source_layer_name="五级水系",
                    source_layer_code="LEVEL_5",
                    source_layer_display_name="五级水系",
                    source_layer_role_code="HIERARCHY_LEVEL",
                    source_layer_order=5,
                    source_object_id="3",
                    water_name="长江故道",
                    normalized_water_name="长江故道",
                    water_type_code="RIVER",
                    geometry_json=_polygon(),
                    geometry_status_code="VALID",
                    bbox_min_lng=119.0,
                    bbox_min_lat=31.0,
                    bbox_max_lng=120.0,
                    bbox_max_lat=32.0,
                    area_km2=1,
                    is_enabled=True,
                ),
            ]
        )
        await session.commit()

        service = NavigationWorkbenchService(session)
        bodies = await service.list_water_bodies(keyword="长江", layer_role_code="HIERARCHY_LEVEL", page=1, page_size=20)
        features = await service.list_water_body_features(group_key=bodies.items[0].group_key, page=1, page_size=20)

    assert bodies.total == 2
    assert bodies.items[0].water_name == "长江"
    assert bodies.items[0].source_layer_display_name == "一级水系"
    assert bodies.items[0].feature_count == 2
    assert bodies.items[0].repaired_count == 2
    assert bodies.items[0].bbox["min_lng"] == 104.0
    assert bodies.items[0].bbox["max_lng"] == 122.0
    assert bodies.items[0].match_count == 0
    assert features.total == 2
    assert [item.id for item in features.items] == [1, 2]


@pytest.mark.asyncio
async def test_workbench_assigns_and_renames_production_water_body_without_touching_raw(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        session.add(
            NavigationWaterArea(
                id=1,
                source_code="RIVER_SHAPEFILE_2026",
                source_layer_name="一级水系",
                source_layer_code="LEVEL_1",
                source_object_id="1",
                water_name=None,
                normalized_water_name=None,
                water_type_code="RIVER",
                geometry_json=_polygon(),
                geometry_status_code="VALID",
                bbox_min_lng=119.98,
                bbox_min_lat=30.98,
                bbox_max_lng=120.24,
                bbox_max_lat=31.12,
                is_enabled=True,
            )
        )
        session.add(
            NavigationWaterBody(
                id=10,
                water_body_code="NWB-TEST",
                water_body_name="未命名水域 一级水系-1",
                normalized_water_name=None,
                display_name="未命名水域 一级水系-1",
                production_name=None,
                name_status_code="UNNAMED",
                source_code="RIVER_SHAPEFILE_2026",
                body_role_code="PRIMARY_HIERARCHY",
                dedupe_status_code="CANONICAL",
                source_layer_code="LEVEL_1",
                source_layer_name="一级水系",
                water_type_code="RIVER",
                geometry_wgs84_json=_polygon(),
                bbox_min_lng=119.98,
                bbox_min_lat=30.98,
                bbox_max_lng=120.24,
                bbox_max_lat=31.12,
                feature_count=1,
                enabled_feature_count=1,
                source_water_area_ids_json=[1],
                is_enabled=True,
            )
        )
        session.add(
            NavigationWaterBodyFeatureLink(
                water_body_id=10,
                water_area_id=1,
                link_role_code="PRIMARY_HIERARCHY",
                is_primary=True,
            )
        )
        await session.commit()

        service = NavigationWorkbenchService(session)
        renamed = await service.update_water_body_name(
            water_body_id=10,
            body=NavigationWaterBodyNameUpdateRequest(production_name="测试生产水体", name_note="人工补名"),
        )
        created = await service.create_water_body_match(
            channel_id=1,
            body=NavigationWaterBodyMatchCreateRequest(water_body_id=10),
        )
        raw = await session.get(NavigationWaterArea, 1)
        listed = await service.list_water_bodies(only_matched=True, page=1, page_size=20)
        removed = await service.remove_water_body_match(channel_id=1, match_id=created.items[0].id)

    assert renamed.production_name == "测试生产水体"
    assert renamed.name_status_code == "PRODUCTION_NAMED"
    assert raw is not None
    assert raw.water_name is None
    assert created.current_match_count == 1
    assert created.items[0].water_body_id == 10
    assert created.items[0].source_water_area_ids == [1]
    assert listed.total == 1
    assert removed.current_match_count == 0
