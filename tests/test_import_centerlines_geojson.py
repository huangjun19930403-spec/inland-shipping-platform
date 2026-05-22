from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.models import NavigationChannelCenterline
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.models.base import Base
from app.modules.navigation.service import NavigationCenterlineService
from scripts.navigation.import_centerlines_geojson import import_centerlines_geojson


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


def _line(*points: tuple[float, float]) -> dict:
    return {"type": "LineString", "coordinates": [[lng, lat] for lng, lat in points]}


def _point(lng: float, lat: float) -> dict:
    return {"type": "Point", "coordinates": [lng, lat]}


def _multi_line(*lines: list[tuple[float, float]]) -> dict:
    return {
        "type": "MultiLineString",
        "coordinates": [[[lng, lat] for lng, lat in line] for line in lines],
    }


def _feature(properties: dict, geometry: dict) -> dict:
    return {"type": "Feature", "properties": properties, "geometry": geometry}


def _write_geojson(path: Path, features: list[dict]) -> Path:
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _channel(*, id: int, code: str) -> NavigationChannel:
    return NavigationChannel(
        id=id,
        channel_code=code,
        channel_name=code,
        alias_names=[],
        channel_type_code="CANAL",
        planning_level_code="NATIONAL_CORE",
        ais_scope_code="INCLUDED",
        source_version="test",
        is_enabled=True,
    )


def _boundary(
    *,
    channel_id: int,
    min_lng: float = 120.0,
    min_lat: float = 31.0,
    max_lng: float = 120.4,
    max_lat: float = 31.4,
) -> NavigationChannelBoundary:
    return NavigationChannelBoundary(
        channel_id=channel_id,
        geometry_json=_polygon(min_lng, min_lat, max_lng, max_lat),
        geometry_status_code="AVAILABLE",
        boundary_quality_code="HIGH_CONFIDENCE",
        repair_status_code="NONE",
        is_current=True,
    )


async def _seed_channels(session: AsyncSession) -> None:
    session.add_all(
        [
            _channel(id=1, code="TEST-MAIN"),
            _channel(id=2, code="TEST-BRANCH"),
            _channel(id=3, code="TEST-NO-CENTERLINE"),
            _boundary(channel_id=1),
            _boundary(channel_id=2),
            _boundary(channel_id=3),
        ]
    )
    await session.commit()


@pytest.mark.asyncio
async def test_import_approved_manual_centerline_and_query_graph_ready(
    tmp_path: Path,
    session_maker,
) -> None:
    input_path = _write_geojson(
        tmp_path / "centerlines.geojson",
        [
            _feature(
                {
                    "centerline_code": "CL-MANUAL-001",
                    "centerline_name": "manual ready",
                    "channel_code": "TEST-MAIN",
                    "source_type_code": "MANUAL",
                    "quality_code": "READY",
                    "review_status_code": "APPROVED",
                    "confidence_score": 96,
                    "is_current": True,
                },
                _line((120.05, 31.05), (120.15, 31.15), (120.25, 31.2)),
            )
        ],
    )

    async with session_maker() as session:
        await _seed_channels(session)

        summary = await import_centerlines_geojson(input_path=input_path, session=session)
        service = NavigationCenterlineService(session)
        ready_rows = await service.list_graph_ready_centerlines(channel_codes=["TEST-MAIN", "TEST-NO-CENTERLINE"])
        missing_codes = await service.list_channel_codes_without_graph_ready_centerline(
            ["TEST-MAIN", "TEST-NO-CENTERLINE"]
        )

    assert summary.rows_read == 1
    assert summary.rows_inserted == 1
    assert summary.rows_need_review == 0
    assert [row.centerline_code for row in ready_rows] == ["CL-MANUAL-001"]
    assert missing_codes == ["TEST-NO-CENTERLINE"]


@pytest.mark.asyncio
async def test_import_blocks_hifleet_reference_from_becoming_current(
    tmp_path: Path,
    session_maker,
) -> None:
    input_path = _write_geojson(
        tmp_path / "hifleet-reference.geojson",
        [
            _feature(
                {
                    "centerline_code": "CL-HIFLEET-001",
                    "channel_code": "TEST-MAIN",
                    "source_type_code": "HIFLEET_REFERENCE",
                    "quality_code": "READY",
                    "review_status_code": "APPROVED",
                    "confidence_score": 99,
                    "is_current": True,
                },
                _line((120.05, 31.05), (120.15, 31.15)),
            )
        ],
    )

    async with session_maker() as session:
        await _seed_channels(session)

        summary = await import_centerlines_geojson(input_path=input_path, session=session)
        row = (
            await session.execute(
                select(NavigationChannelCenterline).where(
                    NavigationChannelCenterline.centerline_code == "CL-HIFLEET-001"
                )
            )
        ).scalar_one()
        ready_rows = await NavigationCenterlineService(session).list_graph_ready_centerlines(channel_codes=["TEST-MAIN"])

    assert row.source_type_code == "HIFLEET_REFERENCE"
    assert row.review_status_code == "NEED_REVIEW"
    assert row.quality_code == "NEED_REVIEW"
    assert row.is_current is False
    assert ready_rows == []
    assert "SOURCE_NOT_AUTO_APPROVABLE" in {issue.issue_code for issue in summary.issues}


@pytest.mark.asyncio
async def test_import_marks_centerline_out_of_boundary(
    tmp_path: Path,
    session_maker,
) -> None:
    input_path = _write_geojson(
        tmp_path / "out-of-boundary.geojson",
        [
            _feature(
                {
                    "centerline_code": "CL-OUTSIDE-001",
                    "channel_code": "TEST-MAIN",
                    "source_type_code": "MANUAL",
                    "quality_code": "READY",
                    "review_status_code": "APPROVED",
                    "confidence_score": 92,
                    "is_current": True,
                },
                _line((121.0, 32.0), (121.1, 32.1)),
            )
        ],
    )

    async with session_maker() as session:
        await _seed_channels(session)

        summary = await import_centerlines_geojson(input_path=input_path, session=session)
        row = (
            await session.execute(
                select(NavigationChannelCenterline).where(
                    NavigationChannelCenterline.centerline_code == "CL-OUTSIDE-001"
                )
            )
        ).scalar_one()

    assert summary.rows_out_of_boundary == 1
    assert row.review_status_code == "NEED_REVIEW"
    assert row.quality_code == "OUT_OF_BOUNDARY"
    assert row.is_current is False


@pytest.mark.asyncio
async def test_import_marks_non_line_geometry_as_broken(
    tmp_path: Path,
    session_maker,
) -> None:
    input_path = _write_geojson(
        tmp_path / "broken.geojson",
        [
            _feature(
                {
                    "centerline_code": "CL-BROKEN-001",
                    "channel_code": "TEST-MAIN",
                    "source_type_code": "MANUAL",
                    "quality_code": "READY",
                    "review_status_code": "APPROVED",
                    "confidence_score": 92,
                    "is_current": True,
                },
                _point(120.1, 31.1),
            )
        ],
    )

    async with session_maker() as session:
        await _seed_channels(session)

        summary = await import_centerlines_geojson(input_path=input_path, session=session)
        row = (
            await session.execute(
                select(NavigationChannelCenterline).where(
                    NavigationChannelCenterline.centerline_code == "CL-BROKEN-001"
                )
            )
        ).scalar_one()

    assert summary.rows_need_review == 1
    assert row.review_status_code == "NEED_REVIEW"
    assert row.quality_code == "BROKEN"
    assert row.is_current is False


@pytest.mark.asyncio
async def test_import_detects_same_channel_duplicate_geometry_in_same_file(
    tmp_path: Path,
    session_maker,
) -> None:
    duplicate_geometry = _line((120.05, 31.05), (120.2, 31.2))
    input_path = _write_geojson(
        tmp_path / "duplicates.geojson",
        [
            _feature(
                {
                    "centerline_code": "CL-DUP-001",
                    "channel_code": "TEST-MAIN",
                    "source_type_code": "MANUAL",
                    "quality_code": "READY",
                    "review_status_code": "APPROVED",
                    "confidence_score": 90,
                    "is_current": True,
                },
                duplicate_geometry,
            ),
            _feature(
                {
                    "centerline_code": "CL-DUP-002",
                    "channel_code": "TEST-MAIN",
                    "source_type_code": "MANUAL",
                    "quality_code": "READY",
                    "review_status_code": "APPROVED",
                    "confidence_score": 90,
                    "is_current": True,
                },
                duplicate_geometry,
            ),
        ],
    )

    async with session_maker() as session:
        await _seed_channels(session)

        summary = await import_centerlines_geojson(input_path=input_path, session=session)
        rows = (
            await session.execute(
                select(NavigationChannelCenterline).order_by(NavigationChannelCenterline.centerline_code)
            )
        ).scalars().all()

    assert summary.rows_inserted == 2
    assert summary.rows_duplicated == 1
    assert rows[0].centerline_code == "CL-DUP-001"
    assert rows[0].review_status_code == "APPROVED"
    assert rows[0].is_current is True
    assert rows[1].centerline_code == "CL-DUP-002"
    assert rows[1].review_status_code == "REJECTED"
    assert rows[1].quality_code == "DUPLICATED"
    assert rows[1].is_current is False


@pytest.mark.asyncio
async def test_import_same_centerline_code_updates_without_duplicate_flag(
    tmp_path: Path,
    session_maker,
) -> None:
    input_path = _write_geojson(
        tmp_path / "upsert.geojson",
        [
            _feature(
                {
                    "centerline_code": "CL-UPSERT-001",
                    "centerline_name": "first name",
                    "channel_code": "TEST-MAIN",
                    "source_type_code": "MANUAL",
                    "quality_code": "READY",
                    "review_status_code": "APPROVED",
                    "confidence_score": 90,
                    "is_current": True,
                },
                _line((120.05, 31.05), (120.2, 31.2)),
            )
        ],
    )
    second_path = _write_geojson(
        tmp_path / "upsert-second.geojson",
        [
            _feature(
                {
                    "centerline_code": "CL-UPSERT-001",
                    "centerline_name": "updated name",
                    "channel_code": "TEST-MAIN",
                    "source_type_code": "MANUAL",
                    "quality_code": "READY",
                    "review_status_code": "APPROVED",
                    "confidence_score": 94,
                    "is_current": True,
                },
                _line((120.05, 31.05), (120.2, 31.2)),
            )
        ],
    )

    async with session_maker() as session:
        await _seed_channels(session)

        first_summary = await import_centerlines_geojson(input_path=input_path, session=session)
        second_summary = await import_centerlines_geojson(input_path=second_path, session=session)
        row = (
            await session.execute(
                select(NavigationChannelCenterline).where(
                    NavigationChannelCenterline.centerline_code == "CL-UPSERT-001"
                )
            )
        ).scalar_one()

    assert first_summary.rows_inserted == 1
    assert second_summary.rows_updated == 1
    assert second_summary.rows_duplicated == 0
    assert row.centerline_name == "updated name"
    assert row.confidence_score == 94
    assert row.review_status_code == "APPROVED"


@pytest.mark.asyncio
async def test_import_splits_multilinestring_parts_with_stable_codes(
    tmp_path: Path,
    session_maker,
) -> None:
    input_path = _write_geojson(
        tmp_path / "multi.geojson",
        [
            _feature(
                {
                    "centerline_code": "CL-MULTI",
                    "channel_code": "TEST-BRANCH",
                    "source_type_code": "SEED_CENTERLINE",
                    "quality_code": "READY",
                    "review_status_code": "APPROVED",
                    "confidence_score": 95,
                    "is_current": True,
                },
                _multi_line(
                    [(120.05, 31.05), (120.1, 31.1)],
                    [(120.2, 31.2), (120.3, 31.3)],
                ),
            )
        ],
    )

    async with session_maker() as session:
        await _seed_channels(session)

        summary = await import_centerlines_geojson(input_path=input_path, session=session)
        rows = (
            await session.execute(
                select(NavigationChannelCenterline).order_by(NavigationChannelCenterline.centerline_code)
            )
        ).scalars().all()

    assert summary.rows_read == 1
    assert summary.rows_prepared == 2
    assert [row.centerline_code for row in rows] == ["CL-MULTI-part-001", "CL-MULTI-part-002"]
    assert all(row.source_type_code == "SEED_CENTERLINE" for row in rows)
    assert all(row.review_status_code == "APPROVED" for row in rows)
