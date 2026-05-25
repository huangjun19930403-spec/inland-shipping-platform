from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import BigInteger

import app.models  # noqa: F401
from app.models import NavigationAnnotationTask, NavigationChannelWaterBodyMatch, NavigationWaterArea, NavigationWaterBody, NavigationWaterBodyFeatureLink
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.models.base import Base
from app.modules.navigation.diagnostic_service import NavigationDiagnosticService
from app.modules.navigation.production_service import NavigationProductionService
from app.modules.navigation.schemas import NavigationCandidateConfirmRequest


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


def _polygon(min_lng: float = 110.8, min_lat: float = 22.1, max_lng: float = 111.2, max_lat: float = 22.5) -> dict:
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


async def _seed_xijiang(session: AsyncSession) -> None:
    session.add(
        NavigationChannel(
            id=1,
            channel_code="NC-XIJIANG",
            channel_name="西江航运干线",
            channel_type_code="RIVER",
            planning_level_code="NATIONAL_HIGH_GRADE",
            ais_scope_code="INCLUDED",
            source_version="revier_navigation_channel_v7",
            source_summary="Seed boundary generated from cleaned channel corridor assets",
            is_enabled=True,
        )
    )
    session.add(
        NavigationChannelBoundary(
            id=1,
            channel_id=1,
            geometry_json=_polygon(),
            bbox_min_lng=110.8,
            bbox_min_lat=22.1,
            bbox_max_lng=111.2,
            bbox_max_lat=22.5,
            ring_count=1,
            point_count=5,
            geometry_status_code="AVAILABLE",
            boundary_quality_code="HIGH_CONFIDENCE",
            connectivity_status_code="CONNECTED",
            repair_status_code="NONE",
            coverage_policy_code="CHANNEL_CORRIDOR_ENVELOPE",
            is_current=True,
        )
    )
    session.add_all(
        [
            NavigationWaterArea(
                id=1,
                source_code="RIVER_SHAPEFILE_2026",
                source_layer_name="rx",
                source_object_id="28674",
                water_name="西江",
                normalized_water_name="西江",
                water_type_code="RIVER",
                geometry_json=_polygon(110.84, 22.2, 110.9, 22.3),
                geometry_status_code="VALID",
                bbox_min_lng=110.84,
                bbox_min_lat=22.2,
                bbox_max_lng=110.9,
                bbox_max_lat=22.3,
                area_km2=2.5,
                is_enabled=True,
            ),
            NavigationWaterArea(
                id=2,
                source_code="RIVER_SHAPEFILE_2026",
                source_layer_name="rx",
                source_object_id="9",
                water_name="浔江",
                normalized_water_name="浔江",
                water_type_code="RIVER",
                geometry_json=_polygon(110.1, 23.35, 111.4, 23.6),
                geometry_status_code="VALID",
                bbox_min_lng=110.1,
                bbox_min_lat=23.35,
                bbox_max_lng=111.4,
                bbox_max_lat=23.6,
                area_km2=156.5,
                is_enabled=True,
            ),
            NavigationWaterArea(
                id=3,
                source_code="RIVER_SHAPEFILE_2026",
                source_layer_name="rx",
                source_object_id="999",
                water_name="无关湖",
                normalized_water_name="无关湖",
                water_type_code="LAKE",
                geometry_json=_polygon(120.0, 31.0, 120.1, 31.1),
                geometry_status_code="VALID",
                bbox_min_lng=120.0,
                bbox_min_lat=31.0,
                bbox_max_lng=120.1,
                bbox_max_lat=31.1,
                area_km2=1.0,
                is_enabled=True,
            ),
        ]
    )
    session.add_all(
        [
            NavigationWaterBody(
                id=1,
                water_body_code="WB-XIJIANG",
                water_body_name="西江",
                normalized_water_name="西江",
                source_code="RIVER_SHAPEFILE_2026",
                body_role_code="PRIMARY_HIERARCHY",
                dedupe_status_code="DEDUPED",
                source_layer_name="rx",
                water_type_code="RIVER",
                geometry_wgs84_json=_polygon(110.84, 22.2, 110.9, 22.3),
                bbox_min_lng=110.84,
                bbox_min_lat=22.2,
                bbox_max_lng=110.9,
                bbox_max_lat=22.3,
                area_km2=2.5,
                feature_count=1,
                enabled_feature_count=1,
                source_water_area_ids_json=[1],
                is_enabled=True,
            ),
            NavigationWaterBody(
                id=2,
                water_body_code="WB-XUNJIANG",
                water_body_name="浔江",
                normalized_water_name="浔江",
                source_code="RIVER_SHAPEFILE_2026",
                body_role_code="PRIMARY_HIERARCHY",
                dedupe_status_code="DEDUPED",
                source_layer_name="rx",
                water_type_code="RIVER",
                geometry_wgs84_json=_polygon(110.1, 23.35, 111.4, 23.6),
                bbox_min_lng=110.1,
                bbox_min_lat=23.35,
                bbox_max_lng=111.4,
                bbox_max_lat=23.6,
                area_km2=156.5,
                feature_count=1,
                enabled_feature_count=1,
                source_water_area_ids_json=[2],
                is_enabled=True,
            ),
        ]
    )
    session.add_all(
        [
            NavigationWaterBodyFeatureLink(water_body_id=1, water_area_id=1, link_role_code="PRIMARY_HIERARCHY", is_primary=True),
            NavigationWaterBodyFeatureLink(water_body_id=2, water_area_id=2, link_role_code="PRIMARY_HIERARCHY", is_primary=True),
        ]
    )
    await session.commit()


async def _add_current_water_body_match(session: AsyncSession, channel_id: int = 1, water_body_id: int = 1) -> None:
    session.add(
        NavigationChannelWaterBodyMatch(
            channel_id=channel_id,
            water_body_id=water_body_id,
            match_batch_code=f"TEST-MATCH-{channel_id}-{water_body_id}",
            match_type_code="CONFIRMED_MATCH",
            matched_term="西江",
            score=95,
            confidence_code="MANUAL_CONFIRMED",
            source_water_area_ids_json=[water_body_id],
            is_current=True,
        )
    )
    await session.commit()


async def _add_candidate_boundary(session: AsyncSession, boundary_id: int = 2) -> None:
    session.add(
        NavigationChannelBoundary(
            id=boundary_id,
            channel_id=1,
            geometry_json=_polygon(110.82, 22.18, 110.96, 22.34),
            bbox_min_lng=110.82,
            bbox_min_lat=22.18,
            bbox_max_lng=110.96,
            bbox_max_lat=22.34,
            ring_count=1,
            point_count=5,
            geometry_status_code="AVAILABLE",
            boundary_quality_code="REVIEW",
            connectivity_status_code="CONNECTED",
            repair_status_code="NONE",
            coverage_policy_code="RIVER_MATCH_CANDIDATE",
            is_current=False,
        )
    )
    await session.commit()


async def _add_manual_published_boundary(session: AsyncSession, boundary_id: int = 3) -> None:
    session.add(
        NavigationChannelBoundary(
            id=boundary_id,
            channel_id=1,
            geometry_json=_polygon(110.83, 22.19, 110.97, 22.35),
            bbox_min_lng=110.83,
            bbox_min_lat=22.19,
            bbox_max_lng=110.97,
            bbox_max_lat=22.35,
            ring_count=1,
            point_count=5,
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
async def test_xijiang_diagnostics_explain_seed_source_and_candidate_water_bodies(session_maker) -> None:
    async with session_maker() as session:
        await _seed_xijiang(session)
        service = NavigationDiagnosticService(session)

        diagnostics = await service.channel_diagnostics(1, include_spatial=True)
        candidates = await service.water_body_candidates(1)

    assert diagnostics.boundary_source_code == "SEED_BOUNDARY"
    assert "不是网络查询" in diagnostics.boundary_source_explanation
    assert "NO_WATER_BODY_MATCH" in diagnostics.issue_codes
    assert "CENTERLINE_MISSING" in diagnostics.issue_codes
    assert diagnostics.water_body_candidate_count > 0
    assert {"西江", "浔江"} <= {item.water_name for item in candidates.items}
    assert candidates.items[0].candidate_type_code in {"NAME_ALIAS_CANDIDATE", "SEED_BOUNDARY_NEARBY"}
    assert candidates.items[0].source_water_area_ids


@pytest.mark.asyncio
async def test_confirm_water_body_candidate_creates_current_match(session_maker) -> None:
    async with session_maker() as session:
        await _seed_xijiang(session)
        service = NavigationDiagnosticService(session)

        response = await service.confirm_water_body_candidate(
            1,
            1,
            NavigationCandidateConfirmRequest(reason_codes=["NAME_OR_ALIAS_MATCH"]),
        )
        rows = list((await session.execute(select(NavigationChannelWaterBodyMatch))).scalars())

    assert response.current_match_count == 1
    assert response.items[0].water_name == "西江"
    assert response.items[0].match_type_code == "CONFIRMED_MATCH"
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_published_manual_boundary_takes_precedence_over_old_candidate(session_maker) -> None:
    async with session_maker() as session:
        await _seed_xijiang(session)
        await _add_current_water_body_match(session)
        await _add_candidate_boundary(session)
        await _add_manual_published_boundary(session)

        production_row = (await NavigationProductionService(session).channels())[0]
        diagnostics = await NavigationDiagnosticService(session).channel_diagnostics(1, include_spatial=False)

    assert production_row.production_stage_code == "BOUNDARY_PUBLISHED"
    assert production_row.production_stage_name == "中心线待生产"
    assert production_row.current_boundary_count == 1
    assert production_row.candidate_boundary_count == 1
    assert "NO_PUBLISHED_CENTERLINE" in production_row.blocker_codes
    assert "BOUNDARY_CANDIDATE_TO_PUBLISH" not in production_row.blocker_codes
    assert diagnostics.production_stage_code == production_row.production_stage_code
    assert diagnostics.production_stage_name == production_row.production_stage_name
    assert diagnostics.current_boundary_count == 1


@pytest.mark.asyncio
async def test_seed_current_boundary_does_not_count_as_published_boundary(session_maker) -> None:
    async with session_maker() as session:
        await _seed_xijiang(session)
        await _add_current_water_body_match(session)

        production_row = (await NavigationProductionService(session).channels())[0]
        diagnostics = await NavigationDiagnosticService(session).channel_diagnostics(1, include_spatial=False)

    assert production_row.production_stage_code == "WATER_MATCH_READY"
    assert production_row.production_stage_name == "边界待生成"
    assert production_row.current_boundary_count == 0
    assert production_row.blocker_codes == ["NO_PUBLISHED_BOUNDARY"]
    assert diagnostics.production_stage_code == production_row.production_stage_code
    assert diagnostics.current_boundary_count == 0


@pytest.mark.asyncio
async def test_candidate_boundary_blocks_only_when_no_published_boundary(session_maker) -> None:
    async with session_maker() as session:
        await _seed_xijiang(session)
        await _add_current_water_body_match(session)
        await _add_candidate_boundary(session)

        production_row = (await NavigationProductionService(session).channels())[0]
        diagnostics = await NavigationDiagnosticService(session).channel_diagnostics(1, include_spatial=False)

    assert production_row.production_stage_code == "BOUNDARY_CANDIDATE"
    assert production_row.production_stage_name == "边界待发布"
    assert production_row.current_boundary_count == 0
    assert production_row.candidate_boundary_count == 1
    assert production_row.blocker_codes == ["BOUNDARY_CANDIDATE_TO_PUBLISH"]
    assert diagnostics.production_stage_code == production_row.production_stage_code
    assert "BOUNDARY_CANDIDATE_TO_PUBLISH" in diagnostics.blocker_codes


@pytest.mark.asyncio
async def test_create_annotation_tasks_from_channel_diagnostics(session_maker) -> None:
    async with session_maker() as session:
        await _seed_xijiang(session)

        response = await NavigationDiagnosticService(session).create_annotation_tasks_from_diagnostics(channel_id=1, created_by=7)
        rows = list((await session.execute(select(NavigationAnnotationTask).order_by(NavigationAnnotationTask.id))).scalars())

    assert response.source_type_code == "CHANNEL_DIAGNOSTICS"
    assert response.created_count >= 2
    assert {"WATER_BODY_MATCH_REPAIR", "CENTERLINE_REPAIR"} <= {row.task_type_code for row in rows}
    assert all(row.target_type_code == "NAVIGATION_CHANNEL" for row in rows)
