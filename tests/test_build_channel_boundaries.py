from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.models import NavigationWaterArea
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.models.base import Base
from scripts.navigation.build_channel_boundaries import build_channel_boundary_report


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
        "coordinates": [
            [
                [min_lng, min_lat],
                [max_lng, min_lat],
                [max_lng, max_lat],
                [min_lng, max_lat],
                [min_lng, min_lat],
            ]
        ],
    }


def _channel(
    *,
    id: int,
    code: str,
    name: str,
    review_required: bool = False,
) -> NavigationChannel:
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


def _boundary(
    *,
    channel_id: int,
    geometry_status_code: str = "AVAILABLE",
    boundary_quality_code: str = "HIGH_CONFIDENCE",
    repair_status_code: str = "NONE",
    is_current: bool = True,
) -> NavigationChannelBoundary:
    return NavigationChannelBoundary(
        channel_id=channel_id,
        geometry_json=_polygon(120.0, 31.0, 120.3, 31.3),
        geometry_status_code=geometry_status_code,
        boundary_quality_code=boundary_quality_code,
        repair_status_code=repair_status_code,
        is_current=is_current,
    )


def _water_area(
    *,
    id: int,
    name: str,
    min_lng: float = 120.0,
    min_lat: float = 31.0,
    max_lng: float = 120.3,
    max_lat: float = 31.3,
) -> NavigationWaterArea:
    return NavigationWaterArea(
        id=id,
        source_code="TEST_RIVER",
        source_layer_name="rx",
        source_object_id=str(id),
        water_name=name,
        normalized_water_name=name,
        water_type_code="RIVER",
        geometry_json=_polygon(min_lng, min_lat, max_lng, max_lat),
        geometry_status_code="VALID",
        bbox_min_lng=min_lng,
        bbox_min_lat=min_lat,
        bbox_max_lng=max_lng,
        bbox_max_lat=max_lat,
        center_lng=(min_lng + max_lng) / 2,
        center_lat=(min_lat + max_lat) / 2,
        area_km2=1,
        is_low_value=False,
        is_enabled=True,
    )


async def _seed_match_data(session: AsyncSession) -> None:
    session.add_all(
        [
            _channel(id=1, code="NC-YANGTZE", name="长江干线"),
            _channel(id=2, code="NC-SHAYING-RIVER", name="沙颍河航道", review_required=True),
            _channel(id=3, code="NC-LIANSHEN-LINE", name="连申线", review_required=True),
            _boundary(channel_id=1),
            _boundary(
                channel_id=2,
                geometry_status_code="MISSING",
                boundary_quality_code="MISSING",
                repair_status_code="MISSING",
            ),
            _water_area(id=101, name="长江"),
            _water_area(id=102, name="颖河"),
            _water_area(id=103, name="无关河流", min_lng=121.0, min_lat=31.0, max_lng=121.1, max_lat=31.1),
        ]
    )
    await session.commit()


@pytest.mark.asyncio
async def test_build_channel_boundary_report_matches_aliases_and_preserves_seed_boundary(
    tmp_path: Path,
    session_maker,
) -> None:
    output_path = tmp_path / "match-report.json"
    async with session_maker() as session:
        await _seed_match_data(session)

        report = await build_channel_boundary_report(
            session=session,
            output_path=output_path,
            source_code="TEST_RIVER",
            dry_run=True,
            write_candidate_boundaries=True,
        )

        boundary_count = await session.scalar(select(func.count()).select_from(NavigationChannelBoundary))

    by_code = {item.channel_code: item for item in report.channels}
    assert by_code["NC-YANGTZE"].matched_water_area_count == 1
    assert by_code["NC-YANGTZE"].confidence_code == "HIGH_CONFIDENCE"
    assert by_code["NC-YANGTZE"].review_status_code == "APPROVED"
    assert by_code["NC-SHAYING-RIVER"].matched_terms == ["颖河"]
    assert by_code["NC-SHAYING-RIVER"].review_status_code == "NEED_REVIEW"
    assert "SEED_BOUNDARY_MISSING" in by_code["NC-SHAYING-RIVER"].issue_codes
    assert by_code["NC-LIANSHEN-LINE"].matched_water_area_count == 0
    assert "NO_WATER_AREA_MATCH" in by_code["NC-LIANSHEN-LINE"].issue_codes
    assert boundary_count == 2

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["summary"]["matched_channels"] == 2
    assert payload["summary"]["missing_match_channels"] == 1


@pytest.mark.asyncio
async def test_write_candidate_boundaries_only_for_missing_seed_boundary(
    tmp_path: Path,
    session_maker,
) -> None:
    async with session_maker() as session:
        await _seed_match_data(session)

        report = await build_channel_boundary_report(
            session=session,
            output_path=tmp_path / "match-report.json",
            source_code="TEST_RIVER",
            dry_run=False,
            write_candidate_boundaries=True,
        )

        boundaries = (
            await session.execute(
                select(NavigationChannelBoundary).order_by(
                    NavigationChannelBoundary.channel_id,
                    NavigationChannelBoundary.is_current.desc(),
                )
            )
        ).scalars().all()

    by_code = {item.channel_code: item for item in report.channels}
    assert by_code["NC-YANGTZE"].candidate_boundary_written is False
    assert by_code["NC-SHAYING-RIVER"].candidate_boundary_written is True
    assert report.candidate_boundaries_written == 1
    assert len(boundaries) == 3

    candidate = next(row for row in boundaries if row.channel_id == 2 and row.is_current is False)
    assert candidate.boundary_quality_code == "REVIEW"
    assert candidate.repair_status_code == "REVIEW_CANDIDATE"
    assert candidate.coverage_policy_code == "RIVER_NAME_MATCH_CANDIDATE"


@pytest.mark.asyncio
async def test_report_does_not_force_unmatched_planned_channel_ready(
    tmp_path: Path,
    session_maker,
) -> None:
    async with session_maker() as session:
        await _seed_match_data(session)

        report = await build_channel_boundary_report(
            session=session,
            output_path=tmp_path / "match-report.json",
            source_code="TEST_RIVER",
            channel_codes=["NC-LIANSHEN-LINE"],
            dry_run=False,
            write_candidate_boundaries=True,
        )

        boundary_count = await session.scalar(select(func.count()).select_from(NavigationChannelBoundary))

    assert len(report.channels) == 1
    only = report.channels[0]
    assert only.channel_code == "NC-LIANSHEN-LINE"
    assert only.confidence_code == "MISSING"
    assert only.review_status_code == "NEED_REVIEW"
    assert only.candidate_boundary_written is False
    assert boundary_count == 2
