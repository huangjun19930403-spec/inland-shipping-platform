from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.models import NavigationChannelCenterline, NavigationChannelWaterAreaMatch, NavigationGeometryDraft, NavigationGraphVersion, NavigationWaterArea
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.models.base import Base
from app.modules.navigation.schemas import (
    NavigationGeometryDraftApproveRequest,
    NavigationGeometryDraftCreateRequest,
    NavigationGraphBuildRequest,
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

        submitted = await service.submit_geometry_draft(draft.id, submitted_by=7)
        approved = await service.approve_geometry_draft(
            submitted.id,
            NavigationGeometryDraftApproveRequest(review_comment="ok"),
            reviewed_by=8,
        )
        published = await service.publish_geometry_draft(approved.id, published_by=8)
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
        await service.submit_geometry_draft(draft.id, submitted_by=7)
        await service.approve_geometry_draft(draft.id, NavigationGeometryDraftApproveRequest(), reviewed_by=8)
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
async def test_workbench_lists_channel_water_area_matches(session_maker) -> None:
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
            NavigationChannelWaterAreaMatch(
                id=1,
                channel_id=1,
                water_area_id=1,
                match_batch_code="TEST-BATCH",
                match_type_code="EXACT_NAME",
                matched_term="测试水域",
                score=95,
                confidence_code="HIGH_CONFIDENCE",
                review_status_code="APPROVED",
                issue_codes=[],
                is_current=True,
            )
        )
        await session.commit()

        service = NavigationWorkbenchService(session)
        summary = await service.summary()
        matches = await service.list_water_area_matches(channel_id=1)

    assert summary.channels[0].current_water_area_match_count == 1
    assert summary.channels[0].water_area_match_status_code == "READY"
    assert matches.current_match_count == 1
    assert matches.items[0].water_name == "测试水域"
