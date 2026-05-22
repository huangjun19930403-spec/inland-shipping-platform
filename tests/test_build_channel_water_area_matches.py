from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.models import NavigationChannelWaterAreaMatch, NavigationWaterArea
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.models.base import Base
from scripts.navigation.build_channel_water_area_matches import build_channel_water_area_matches


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


def _polygon(min_lng: float, min_lat: float, max_lng: float, max_lat: float) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[[min_lng, min_lat], [max_lng, min_lat], [max_lng, max_lat], [min_lng, max_lat], [min_lng, min_lat]]],
    }


def _channel(id: int, code: str, name: str, *, review_required: bool = False) -> NavigationChannel:
    return NavigationChannel(
        id=id,
        channel_code=code,
        channel_name=name,
        alias_names=[],
        channel_type_code="CANAL",
        planning_level_code="NATIONAL_CORE",
        ais_scope_code="INCLUDED",
        review_required=review_required,
        source_version="test",
        is_enabled=True,
    )


def _boundary(channel_id: int) -> NavigationChannelBoundary:
    return NavigationChannelBoundary(
        channel_id=channel_id,
        geometry_json=_polygon(120.0, 31.0, 120.4, 31.4),
        bbox_min_lng=120.0,
        bbox_min_lat=31.0,
        bbox_max_lng=120.4,
        bbox_max_lat=31.4,
        geometry_status_code="AVAILABLE",
        boundary_quality_code="HIGH_CONFIDENCE",
        connectivity_status_code="CONNECTED",
        repair_status_code="NONE",
        coverage_policy_code="SEED_BOUNDARY",
        is_current=True,
    )


def _water_area(id: int, name: str, layer: str, object_id: str) -> NavigationWaterArea:
    return NavigationWaterArea(
        id=id,
        source_code="TEST_RIVER",
        source_layer_name=layer,
        source_object_id=object_id,
        water_name=name,
        normalized_water_name=name,
        water_type_code="RIVER",
        geometry_json=_polygon(120.05, 31.05, 120.2, 31.2),
        geometry_status_code="VALID",
        bbox_min_lng=120.05,
        bbox_min_lat=31.05,
        bbox_max_lng=120.2,
        bbox_max_lat=31.2,
        is_enabled=True,
    )


async def _seed(session: AsyncSession) -> None:
    session.add_all(
        [
            _channel(1, "NC-YANGTZE", "长江干线"),
            _channel(2, "NC-SHAYING-RIVER", "沙颍河航道", review_required=True),
            _channel(3, "NC-LIANSHEN-LINE", "连申线", review_required=True),
            _boundary(1),
            _boundary(2),
            _water_area(101, "长江", "rx", "88"),
            _water_area(102, "长江", "一级水系", "88"),
            _water_area(103, "颖河", "rx", "99"),
            _water_area(104, "无关河流", "rx", "100"),
        ]
    )
    await session.commit()


@pytest.mark.asyncio
async def test_build_channel_water_area_matches_persists_rows_and_candidate_boundaries(
    tmp_path: Path,
    session_maker,
) -> None:
    async with session_maker() as session:
        await _seed(session)

        report = await build_channel_water_area_matches(
            session=session,
            output_path=tmp_path / "match-report.json",
            source_code="TEST_RIVER",
            match_batch_code="TEST-BATCH",
            dry_run=False,
            write_candidate_boundaries=True,
        )

        match_count = await session.scalar(select(func.count()).select_from(NavigationChannelWaterAreaMatch))
        boundaries = list((await session.execute(select(NavigationChannelBoundary))).scalars())

    by_code = {item.channel_code: item for item in report.channels}
    assert by_code["NC-YANGTZE"].matched_water_area_count == 1
    assert by_code["NC-YANGTZE"].candidates[0].source_layer_name == "rx"
    assert by_code["NC-YANGTZE"].candidates[0].duplicate_layer_names == ["一级水系"]
    assert by_code["NC-SHAYING-RIVER"].matched_water_area_count == 1
    assert by_code["NC-LIANSHEN-LINE"].matched_water_area_count == 0
    assert "NO_WATER_AREA_MATCH" in by_code["NC-LIANSHEN-LINE"].issue_codes
    assert match_count == 2
    assert report.candidate_boundaries_written == 2
    assert sum(1 for item in boundaries if item.coverage_policy_code == "RIVER_MATCH_CANDIDATE") == 2
    assert all(item.is_current for item in boundaries if item.coverage_policy_code == "SEED_BOUNDARY")


@pytest.mark.asyncio
async def test_build_channel_water_area_matches_same_batch_is_idempotent(session_maker) -> None:
    async with session_maker() as session:
        await _seed(session)

        for _ in range(2):
            await build_channel_water_area_matches(
                session=session,
                output_path=None,
                source_code="TEST_RIVER",
                match_batch_code="TEST-BATCH",
                dry_run=False,
                write_candidate_boundaries=False,
            )

        match_rows = list((await session.execute(select(NavigationChannelWaterAreaMatch))).scalars())

    assert len(match_rows) == 2
    assert {row.match_batch_code for row in match_rows} == {"TEST-BATCH"}
