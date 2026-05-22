from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.models import (
    NavigationChannelCenterline,
    NavigationGraphEdge,
    NavigationGraphVersion,
    NavigationRouteQualityIssue,
    NavigationRouteResult,
    NavigationWaterArea,
)
from app.models.address import NavigationChannel, TransportNode
from app.models.base import Base
from scripts.navigation.run_mvp_acceptance import run_mvp_acceptance
from scripts.navigation.seed_mvp_navigation_data import DEFAULT_DATA_PATH, seed_mvp_navigation_data


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


def _channel(id: int, code: str, name: str) -> NavigationChannel:
    return NavigationChannel(
        id=id,
        channel_code=code,
        channel_name=name,
        alias_names=[],
        channel_type_code="CANAL",
        planning_level_code="MVP",
        ais_scope_code="INCLUDED",
        source_version="test",
        is_enabled=True,
    )


def _transport_node(id: int, name: str, lng: float, lat: float, *, node_type_code: str = "TERMINAL") -> TransportNode:
    return TransportNode(
        id=id,
        code=f"TN{id}",
        name=name,
        node_type_code=node_type_code,
        province_code="32",
        city_code="320000",
        district_code=None,
        city_region_id=1,
        address=None,
        longitude=lng,
        latitude=lat,
        status=1,
        lifecycle_status_code="ACTIVE",
        sort_order=0,
        is_hot_node=False,
    )


async def _seed_mvp_prerequisites(session: AsyncSession) -> None:
    session.add_all(
        [
            _channel(1, "NC-YANGTZE", "长江干线"),
            _channel(3, "NC-GRAND-CANAL", "京杭运河"),
            _channel(46, "NC-SUNAN-CANAL", "苏南运河"),
            _transport_node(1, "靖江永益码头", 120.2193, 31.94489),
            _transport_node(11, "靖江苏通港务", 120.34265, 32.00218),
            _transport_node(25, "扬州海昌港务", 119.81034, 32.32482),
            _transport_node(37, "常州中天特钢", 120.07399, 31.71087),
            _transport_node(103, "苏州渭塘华东材料", 120.63105, 31.4515),
            _transport_node(295, "无锡惠山锚地", 120.206125, 31.606669, node_type_code="ANCHORAGE"),
        ]
    )
    await session.commit()


@pytest.mark.asyncio
async def test_seed_mvp_navigation_data_creates_ready_graph_without_boundaries(session_maker) -> None:
    async with session_maker() as session:
        await _seed_mvp_prerequisites(session)

        summary = await seed_mvp_navigation_data(
            session=session,
            data_path=DEFAULT_DATA_PATH,
            version_code="TEST-MVP-GRAPH",
            activate=True,
        )
        version = (
            await session.execute(
                select(NavigationGraphVersion).where(NavigationGraphVersion.version_code == "TEST-MVP-GRAPH")
            )
        ).scalar_one()
        water_area_count = await session.scalar(select(func.count()).select_from(NavigationWaterArea))
        centerline_count = await session.scalar(select(func.count()).select_from(NavigationChannelCenterline))
        edge_count = await session.scalar(select(func.count()).select_from(NavigationGraphEdge))

    assert summary.status_code == "READY"
    assert summary.is_active is True
    assert summary.node_count == 7
    assert summary.edge_count == 6
    assert summary.channel_codes == ["NC-GRAND-CANAL", "NC-SUNAN-CANAL", "NC-YANGTZE"]
    assert version.status_code == "READY"
    assert water_area_count == 6
    assert centerline_count == 6
    assert edge_count == 6
    assert "UNKNOWN_CONSTRAINT_DATA" in {
        issue["issue_code"] for issue in summary.validation_report["issues"]
    }


@pytest.mark.asyncio
async def test_run_mvp_acceptance_routes_are_graph_based_and_calibrated(session_maker) -> None:
    async with session_maker() as session:
        await _seed_mvp_prerequisites(session)
        await seed_mvp_navigation_data(
            session=session,
            data_path=DEFAULT_DATA_PATH,
            version_code="TEST-MVP-GRAPH",
            activate=True,
        )

        report = await run_mvp_acceptance(
            session=session,
            data_path=DEFAULT_DATA_PATH,
            graph_version_code="TEST-MVP-GRAPH",
        )
        result_count = await session.scalar(select(func.count()).select_from(NavigationRouteResult))
        issue_count = await session.scalar(select(func.count()).select_from(NavigationRouteQualityIssue))

    assert report.passed_count == 6
    assert report.failed_count == 0
    assert result_count == 6
    assert issue_count >= 6
    for case in report.cases:
        assert case.status_code == "SUCCESS"
        assert case.quality_code == "READY_WITH_WARNING"
        assert case.distance_km and case.distance_km > 0
        assert case.calibrated_distance_min_km is not None
        assert case.calibrated_distance_max_km is not None
        assert case.edge_ids
        assert case.provider_code == "NAVIGATION_ENGINE"
        assert "UNKNOWN_CONSTRAINT_DATA" in case.issue_types


@pytest.mark.asyncio
async def test_seed_mvp_navigation_data_requires_replace_for_existing_version(session_maker) -> None:
    async with session_maker() as session:
        await _seed_mvp_prerequisites(session)
        await seed_mvp_navigation_data(
            session=session,
            data_path=DEFAULT_DATA_PATH,
            version_code="TEST-MVP-GRAPH",
            activate=True,
        )

        with pytest.raises(ValueError, match="Graph version already exists"):
            await seed_mvp_navigation_data(
                session=session,
                data_path=DEFAULT_DATA_PATH,
                version_code="TEST-MVP-GRAPH",
                activate=True,
            )
