from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.models import NavigationChannelWaterBodyMatch, NavigationWaterBody
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.models.base import Base
from app.modules.navigation.production_service import NavigationProductionService
from app.modules.navigation.schemas import NavigationCandidateGenerateRequest


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
    min_lng: float = 119.98,
    min_lat: float = 30.98,
    max_lng: float = 120.24,
    max_lat: float = 31.12,
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


async def _seed_matched_water_body(session: AsyncSession, water_body_id: int = 1) -> None:
    geometry = _polygon()
    session.add(
        NavigationWaterBody(
            id=water_body_id,
            water_body_code=f"WB-{water_body_id}",
            water_body_name="测试水体",
            normalized_water_name="测试水体",
            display_name="测试水体",
            production_name="测试生产水体",
            source_code="RIVER_SHAPEFILE_2026",
            body_role_code="PRIMARY_HIERARCHY",
            dedupe_status_code="DEDUPED",
            source_layer_name="一级水系",
            source_layer_order=1,
            water_type_code="RIVER",
            geometry_wgs84_json=geometry,
            bbox_min_lng=119.98,
            bbox_min_lat=30.98,
            bbox_max_lng=120.24,
            bbox_max_lat=31.12,
            feature_count=1,
            enabled_feature_count=1,
            source_water_area_ids_json=[water_body_id],
            is_enabled=True,
        )
    )
    session.add(
        NavigationChannelWaterBodyMatch(
            id=water_body_id,
            channel_id=1,
            water_body_id=water_body_id,
            match_batch_code=f"TEST-BODY-MATCH-{water_body_id}",
            match_type_code="MANUAL_ADD",
            score=96,
            confidence_code="MANUAL_CONFIRMED",
            issue_codes=[],
            is_current=True,
            source_water_area_ids_json=[water_body_id],
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_generate_boundary_candidates_blocks_without_matched_water_body(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)

        response = await NavigationProductionService(session).generate_boundary_candidates(
            channel_id=1,
            body=NavigationCandidateGenerateRequest(),
        )
        boundary_rows = list((await session.execute(select(NavigationChannelBoundary))).scalars())

    assert response.status_code == "BLOCKED"
    assert response.created_count == 0
    assert response.matched_water_body_count == 0
    assert "NO_WATER_BODY_MATCH" in response.blocker_codes
    assert "航道水系规划" in response.message
    assert boundary_rows == []


@pytest.mark.asyncio
async def test_generate_boundary_candidates_creates_raw_cleaned_and_simplified_with_source_trace(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        await _seed_matched_water_body(session)

        response = await NavigationProductionService(session).generate_boundary_candidates(
            channel_id=1,
            body=NavigationCandidateGenerateRequest(),
        )
        boundaries = list(
            (await session.execute(select(NavigationChannelBoundary).order_by(NavigationChannelBoundary.coverage_policy_code))).scalars()
        )

    policies = {row.coverage_policy_code for row in boundaries}
    assert response.status_code == "CREATED"
    assert response.created_count == 3
    assert response.matched_water_body_count == 1
    assert set(response.candidate_types) == {
        "WATER_BODY_UNION_RAW",
        "WATER_BODY_UNION_CLEANED",
        "WATER_BODY_UNION_SIMPLIFIED",
    }
    assert policies == set(response.candidate_types)
    for row in boundaries:
        assert row.is_current is False
        assert row.source_trace_json["source"] == "MATCHED_WATER_BODY"
        assert row.source_trace_json["matched_water_body_count"] == 1
        assert row.source_trace_json["candidate_type"] == row.coverage_policy_code
        assert row.source_trace_json["point_count_before"] >= row.source_trace_json["point_count_after"]
        assert row.source_trace_json["area_m2"] > 0
    simplified = next(row for row in boundaries if row.coverage_policy_code == "WATER_BODY_UNION_SIMPLIFIED")
    assert simplified.source_trace_json["simplified"] is True
    assert simplified.boundary_quality_code == "READY_WITH_WARNING"


@pytest.mark.asyncio
async def test_generate_boundary_candidates_exists_message_includes_source_summary(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        await _seed_matched_water_body(session)
        service = NavigationProductionService(session)
        first = await service.generate_boundary_candidates(channel_id=1, body=NavigationCandidateGenerateRequest())

        response = await service.generate_boundary_candidates(channel_id=1, body=NavigationCandidateGenerateRequest())

    assert first.created_count == 3
    assert response.status_code == "EXISTS"
    assert response.created_count == 0
    assert response.candidate_count == 3
    assert len(response.boundary_ids) == 3
    assert response.matched_water_body_count == 1
    assert set(response.candidate_types) == {
        "WATER_BODY_UNION_RAW",
        "WATER_BODY_UNION_CLEANED",
        "WATER_BODY_UNION_SIMPLIFIED",
    }
    assert response.next_path == "/navigation/production/boundaries?channel_id=1"
    assert "已存在 3 个边界候选" in response.message
    assert "可以直接载入候选边界修正" in response.message


@pytest.mark.asyncio
async def test_generated_boundary_candidates_drive_production_channel_counts_and_stage(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        await _seed_matched_water_body(session)
        service = NavigationProductionService(session)

        generated = await service.generate_boundary_candidates(
            channel_id=1,
            body=NavigationCandidateGenerateRequest(),
        )
        channels = await service.channels()
        workspace = await service.production_workspace(channel_id=1, step="boundary")
        candidates = await service.boundary_candidates(channel_id=1)

    row = channels[0]
    boundary_step = next(step for step in row.steps if step.step_code == "BOUNDARY")
    candidate_types = {item.coverage_policy_code for item in candidates}
    assert generated.created_count == 3
    assert row.candidate_boundary_count >= 3
    assert row.production_stage_code == "BOUNDARY_CANDIDATE"
    assert row.next_action_label == "修正并确认边界"
    assert boundary_step.status_code == "NEED_REVIEW"
    assert boundary_step.count >= 3
    assert workspace.channel.candidate_boundary_count >= 3
    assert workspace.channel.production_stage_code == "BOUNDARY_CANDIDATE"
    assert len(workspace.boundaries) >= 3
    assert {
        "WATER_BODY_UNION_RAW",
        "WATER_BODY_UNION_CLEANED",
        "WATER_BODY_UNION_SIMPLIFIED",
    }.issubset(candidate_types)
