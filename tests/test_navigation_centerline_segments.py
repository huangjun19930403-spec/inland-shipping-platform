from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.models import NavigationCenterlineSegment, NavigationChannelCenterline
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.models.base import Base
from app.modules.navigation.schemas import (
    NavigationCenterlineSegmentGenerateRequest,
    NavigationCenterlineSegmentPublishRequest,
    NavigationCenterlineSegmentUpdateRequest,
)
from app.modules.navigation.service import NavigationCenterlineService
from app.modules.navigation.services.centerline_segments import NavigationCenterlineSegmentService


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


def _polygon(
    min_lng: float = 120.00,
    min_lat: float = 31.00,
    max_lng: float = 120.24,
    max_lat: float = 31.05,
) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[
            [min_lng, min_lat],
            [max_lng, min_lat],
            [max_lng, max_lat],
            [min_lng, max_lat],
            [min_lng, min_lat],
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


async def _seed_current_boundary(session: AsyncSession) -> None:
    geometry = _polygon()
    session.add(
        NavigationChannelBoundary(
            id=1,
            channel_id=1,
            geometry_json=geometry,
            boundary_paths_low=geometry["coordinates"],
            boundary_paths_medium=geometry["coordinates"],
            boundary_paths_high=geometry["coordinates"],
            bbox_min_lng=120.00,
            bbox_min_lat=31.00,
            bbox_max_lng=120.24,
            bbox_max_lat=31.05,
            geometry_status_code="AVAILABLE",
            boundary_quality_code="MANUAL_PUBLISHED",
            connectivity_status_code="CONNECTED",
            repair_status_code="NONE",
            coverage_policy_code="MANUAL_DRAW",
            is_current=True,
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_generate_centerline_segments_blocks_without_current_boundary(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)

        response = await NavigationCenterlineSegmentService(session).generate_segments(
            1,
            NavigationCenterlineSegmentGenerateRequest(),
        )

    assert response.status_code == "BLOCKED"
    assert response.segment_count == 0
    assert "NO_PUBLISHED_BOUNDARY" in response.blocker_codes


@pytest.mark.asyncio
async def test_generate_centerline_segments_from_boundary_rough_line(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        await _seed_current_boundary(session)

        response = await NavigationCenterlineSegmentService(session).generate_segments(
            1,
            NavigationCenterlineSegmentGenerateRequest(segment_length_km=3.0),
        )
        rows = list((await session.execute(select(NavigationCenterlineSegment))).scalars())

    assert response.status_code == "CREATED"
    assert response.segment_count >= 2
    assert response.need_repair_count == response.segment_count
    assert {row.source_type_code for row in rows} == {"BOUNDARY_DERIVED_ROUGH"}
    assert all(row.segment_no for row in rows)
    assert all(row.length_m and row.length_m > 0 for row in rows)
    assert all(row.bbox_min_lng is not None for row in rows)


@pytest.mark.asyncio
async def test_generate_centerline_segments_exists_without_force(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        await _seed_current_boundary(session)
        service = NavigationCenterlineSegmentService(session)
        created = await service.generate_segments(1, NavigationCenterlineSegmentGenerateRequest(segment_length_km=3.0))

        response = await service.generate_segments(1, NavigationCenterlineSegmentGenerateRequest(segment_length_km=3.0))

    assert created.status_code == "CREATED"
    assert response.status_code == "EXISTS"
    assert response.segment_count == created.segment_count
    assert "已存在" in response.message


@pytest.mark.asyncio
async def test_list_centerline_segments_returns_counts(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        await _seed_current_boundary(session)
        service = NavigationCenterlineSegmentService(session)
        await service.generate_segments(1, NavigationCenterlineSegmentGenerateRequest(segment_length_km=3.0))

        response = await service.list_segments(1)

    assert response.total_count >= 2
    assert response.need_repair_count == response.total_count
    assert response.confirmed_count == 0
    assert response.publishable is False
    assert len(response.items) == response.total_count


@pytest.mark.asyncio
async def test_update_centerline_segment_geometry_revalidates(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        await _seed_current_boundary(session)
        service = NavigationCenterlineSegmentService(session)
        await service.generate_segments(1, NavigationCenterlineSegmentGenerateRequest(segment_length_km=50.0))
        row = (await service.list_segments(1)).items[0]

        updated = await service.update_segment(
            row.id,
            NavigationCenterlineSegmentUpdateRequest(
                geometry_json={"type": "LineString", "coordinates": [[120.02, 31.025], [120.20, 31.025]]},
                source_type_code="MAP_EDIT",
            ),
        )

    assert updated.source_type_code == "MAP_EDIT"
    assert updated.validation_summary_json is not None
    assert updated.validation_summary_json["error_count"] == 0
    assert updated.length_m and updated.length_m > 20


@pytest.mark.asyncio
async def test_out_of_boundary_centerline_segment_cannot_confirm(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        await _seed_current_boundary(session)
        service = NavigationCenterlineSegmentService(session)
        await service.generate_segments(1, NavigationCenterlineSegmentGenerateRequest(segment_length_km=50.0))
        row = (await service.list_segments(1)).items[0]
        await service.update_segment(
            row.id,
            NavigationCenterlineSegmentUpdateRequest(
                geometry_json={"type": "LineString", "coordinates": [[121.00, 32.00], [121.10, 32.00]]},
                source_type_code="MAP_EDIT",
            ),
        )

        with pytest.raises(Exception) as exc_info:
            await service.confirm_segment(row.id)
        stored = await session.get(NavigationCenterlineSegment, row.id)

    assert exc_info.value.code == "CENTERLINE_SEGMENT_CONFIRM_BLOCKED"
    assert stored is not None
    assert stored.segment_status_code == "PUBLISH_BLOCKED"
    assert "SEGMENT_OUT_OF_BOUNDARY" in stored.issue_summary_json["issue_codes"]


@pytest.mark.asyncio
async def test_legal_centerline_segment_can_confirm(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        await _seed_current_boundary(session)
        service = NavigationCenterlineSegmentService(session)
        await service.generate_segments(1, NavigationCenterlineSegmentGenerateRequest(segment_length_km=50.0))
        row = (await service.list_segments(1)).items[0]

        confirmed = await service.confirm_segment(row.id)

    assert confirmed.segment_status_code == "CONFIRMED"
    assert confirmed.quality_code in {"READY", "READY_WITH_WARNING"}


@pytest.mark.asyncio
async def test_publish_centerline_segments_blocks_until_all_confirmed(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        await _seed_current_boundary(session)
        service = NavigationCenterlineSegmentService(session)
        await service.generate_segments(1, NavigationCenterlineSegmentGenerateRequest(segment_length_km=3.0))
        rows = (await service.list_segments(1)).items
        assert len(rows) >= 2
        await service.confirm_segment(rows[0].id)

        response = await service.publish_segments(1, NavigationCenterlineSegmentPublishRequest())

    assert response.status_code == "BLOCKED"
    assert "CENTERLINE_SEGMENT_NOT_CONFIRMED" in response.blocker_codes


@pytest.mark.asyncio
async def test_publish_confirmed_centerline_segments_creates_published_centerline(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        await _seed_current_boundary(session)
        service = NavigationCenterlineSegmentService(session)
        await service.generate_segments(1, NavigationCenterlineSegmentGenerateRequest(segment_length_km=3.0))
        rows = (await service.list_segments(1)).items
        for row in rows:
            await service.confirm_segment(row.id)

        response = await service.publish_segments(1, NavigationCenterlineSegmentPublishRequest(publish_name="测试合并中心线"))
        centerline = await session.get(NavigationChannelCenterline, response.centerline_id)
        stored_segments = list((await session.execute(select(NavigationCenterlineSegment))).scalars())
        graph_ready = await NavigationCenterlineService(session).list_graph_ready_centerlines(channel_codes=["TEST-CHANNEL"])

    assert response.status_code == "PUBLISHED"
    assert response.centerline_id is not None
    assert centerline is not None
    assert centerline.review_status_code == "PUBLISHED"
    assert centerline.is_current is True
    assert centerline.source_type_code == "CENTERLINE_SEGMENT_MERGE"
    assert [row.id for row in graph_ready] == [centerline.id]
    assert all(row.segment_status_code == "PUBLISHED" for row in stored_segments)
