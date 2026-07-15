from __future__ import annotations

from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.models import (
    NavigationChannelCenterline,
    NavigationChannelWaterBodyMatch,
    NavigationGraphEdge,
    NavigationGraphEdgeConstraint,
    NavigationGraphNode,
    NavigationGraphVersion,
    NavigationWaterBody,
)
from app.models.address import (
    NavigationChannel,
    NavigationChannelBoundary,
    NavigationConstraintPoint,
    TransportNode,
)
from app.models.base import Base
from scripts.navigation.build_graph_from_centerline import build_graph_from_centerlines


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


def _channel(*, id: int, code: str, technical_grade_current_code: str | None = None) -> NavigationChannel:
    return NavigationChannel(
        id=id,
        channel_code=code,
        channel_name=code,
        alias_names=[],
        channel_type_code="CANAL",
        planning_level_code="NATIONAL_CORE",
        technical_grade_current_code=technical_grade_current_code,
        ais_scope_code="INCLUDED",
        source_version="test",
        is_enabled=True,
    )


def _boundary(
    *,
    channel_id: int,
    min_lng: float = 119.9,
    min_lat: float = 30.9,
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


def _centerline(
    *,
    id: int,
    channel_id: int,
    code: str,
    geometry: dict,
    source_type_code: str = "MANUAL",
    review_status_code: str = "PUBLISHED",
    quality_code: str = "READY",
    is_current: bool = True,
) -> NavigationChannelCenterline:
    return NavigationChannelCenterline(
        id=id,
        channel_id=channel_id,
        centerline_code=code,
        centerline_name=code,
        geometry_json=geometry,
        source_type_code=source_type_code,
        direction_code="BIDIRECTIONAL",
        is_main_line=True,
        confidence_score=95,
        quality_code=quality_code,
        review_status_code=review_status_code,
        version_no=1,
        is_current=is_current,
    )


async def _seed_channel_with_centerline(
    session: AsyncSession,
    *,
    centerline: NavigationChannelCenterline,
    boundary: NavigationChannelBoundary | None = None,
    channel_id: int = 1,
    channel_code: str = "TEST-MAIN",
) -> None:
    session.add(_channel(id=channel_id, code=channel_code))
    if boundary is None:
        session.add(_boundary(channel_id=channel_id))
    else:
        session.add(boundary)
    session.add(centerline)
    await session.commit()


@pytest.mark.asyncio
async def test_build_graph_from_single_approved_centerline(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel_with_centerline(
            session,
            centerline=_centerline(
                id=1,
                channel_id=1,
                code="CL-READY-001",
                geometry=_line((120.0, 31.0), (120.2, 31.2)),
            ),
        )

        summary = await build_graph_from_centerlines(
            session=session,
            version_code="TEST-GRAPH-READY",
            scope_code="TEST",
            channel_codes=["TEST-MAIN"],
        )
        version = (
            await session.execute(
                select(NavigationGraphVersion).where(NavigationGraphVersion.version_code == "TEST-GRAPH-READY")
            )
        ).scalar_one()
        edge = (await session.execute(select(NavigationGraphEdge))).scalar_one()

    assert summary.status_code == "READY"
    assert summary.centerline_count == 1
    assert version.node_count == 2
    assert version.edge_count == 1
    assert version.channel_count == 1
    assert version.quality_score and version.quality_score < 100
    assert edge.centerline_id == 1
    assert edge.routing_enabled is True
    assert edge.source_type_code == "MANUAL"
    assert edge.length_km > 0


@pytest.mark.asyncio
async def test_graph_edge_inherits_channel_grade_vessel_limits(session_maker) -> None:
    async with session_maker() as session:
        session.add(_channel(id=1, code="TEST-GRADE", technical_grade_current_code="IV"))
        session.add(_boundary(channel_id=1))
        session.add(
            _centerline(
                id=1,
                channel_id=1,
                code="CL-GRADE-001",
                geometry=_line((120.0, 31.0), (120.2, 31.2)),
            )
        )
        await session.commit()

        await build_graph_from_centerlines(
            session=session,
            version_code="TEST-GRAPH-GRADE",
            scope_code="TEST",
            channel_codes=["TEST-GRADE"],
        )
        edge = (await session.execute(select(NavigationGraphEdge))).scalar_one()

    assert edge.technical_grade_code == "IV"
    assert float(edge.max_allowed_tonnage) == 500.0
    assert float(edge.max_allowed_draft_m) == 2.5
    assert float(edge.min_width_m) == 45.0
    assert edge.unknown_constraint_flag is False
    assert edge.validation_summary_json["vessel_limit_profile"]["source_code"] == "TECHNICAL_GRADE_RULE_DERIVED"


@pytest.mark.asyncio
async def test_build_graph_accepts_auto_water_body_medial_axis_centerline(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel_with_centerline(
            session,
            centerline=_centerline(
                id=1,
                channel_id=1,
                code="CL-AUTO-MEDIAL-001",
                geometry=_line((120.0, 31.0), (120.2, 31.2)),
                source_type_code="AUTO_WATER_BODY_MEDIAL_AXIS",
                quality_code="READY_WITH_WARNING",
            ),
        )

        summary = await build_graph_from_centerlines(
            session=session,
            version_code="TEST-GRAPH-AUTO-MEDIAL",
            scope_code="TEST",
            channel_codes=["TEST-MAIN"],
        )
        edge = (await session.execute(select(NavigationGraphEdge))).scalar_one()
        version = (
            await session.execute(
                select(NavigationGraphVersion).where(NavigationGraphVersion.version_code == "TEST-GRAPH-AUTO-MEDIAL")
            )
        ).scalar_one()

    assert summary.status_code == "READY"
    assert summary.centerline_count == 1
    assert version.source_summary_json["source_type_counts"] == {"AUTO_WATER_BODY_MEDIAL_AXIS": 1}
    assert edge.source_type_code == "AUTO_WATER_BODY_MEDIAL_AXIS"
    assert edge.routing_enabled is True


@pytest.mark.asyncio
async def test_build_graph_fails_without_approved_current_centerline(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel_with_centerline(
            session,
            centerline=_centerline(
                id=1,
                channel_id=1,
                code="CL-DRAFT-001",
                geometry=_line((120.0, 31.0), (120.2, 31.2)),
                review_status_code="NEED_REVIEW",
                is_current=False,
            ),
        )

        summary = await build_graph_from_centerlines(
            session=session,
            version_code="TEST-GRAPH-NO-CENTERLINE",
            scope_code="TEST",
            channel_codes=["TEST-MAIN"],
        )

    assert summary.status_code == "FAILED"
    assert summary.edge_count == 0
    assert "NO_PUBLISHED_CENTERLINE" in {issue.issue_code for issue in summary.issues}


@pytest.mark.asyncio
async def test_same_channel_intersection_creates_junction_and_split_edges(session_maker) -> None:
    async with session_maker() as session:
        session.add_all(
            [
                _channel(id=1, code="TEST-MAIN"),
                _boundary(channel_id=1),
                _centerline(
                    id=1,
                    channel_id=1,
                    code="CL-H-001",
                    geometry=_line((120.0, 31.1), (120.2, 31.1)),
                ),
                _centerline(
                    id=2,
                    channel_id=1,
                    code="CL-V-001",
                    geometry=_line((120.1, 31.0), (120.1, 31.2)),
                ),
            ]
        )
        await session.commit()

        summary = await build_graph_from_centerlines(
            session=session,
            version_code="TEST-GRAPH-JUNCTION",
            scope_code="TEST",
            channel_codes=["TEST-MAIN"],
        )
        junction_count = await session.scalar(
            select(func.count()).select_from(NavigationGraphNode).where(NavigationGraphNode.node_type_code == "CHANNEL_JUNCTION")
        )
        edge_count = await session.scalar(select(func.count()).select_from(NavigationGraphEdge))

    assert summary.status_code == "READY"
    assert junction_count == 1
    assert edge_count == 4


@pytest.mark.asyncio
async def test_different_channel_crossing_is_not_auto_connected(session_maker) -> None:
    async with session_maker() as session:
        session.add_all(
            [
                _channel(id=1, code="TEST-A"),
                _channel(id=2, code="TEST-B"),
                _boundary(channel_id=1),
                _boundary(channel_id=2),
                _centerline(
                    id=1,
                    channel_id=1,
                    code="CL-A-001",
                    geometry=_line((120.0, 31.1), (120.2, 31.1)),
                ),
                _centerline(
                    id=2,
                    channel_id=2,
                    code="CL-B-001",
                    geometry=_line((120.1, 31.0), (120.1, 31.2)),
                ),
            ]
        )
        await session.commit()

        summary = await build_graph_from_centerlines(
            session=session,
            version_code="TEST-GRAPH-CROSSING",
            scope_code="TEST",
            channel_codes=["TEST-A", "TEST-B"],
        )

    assert summary.status_code == "READY"
    assert "CROSSING_NOT_NAVIGABLE" in {issue.issue_code for issue in summary.issues}
    assert summary.validation_report is not None
    assert "GRAPH_DISCONNECTED" in {issue["issue_code"] for issue in summary.validation_report["issues"]}


@pytest.mark.asyncio
async def test_boundary_covered_endpoint_confluence_creates_cross_channel_junction(session_maker) -> None:
    async with session_maker() as session:
        session.add_all(
            [
                _channel(id=1, code="TEST-MAIN-RIVER"),
                _channel(id=2, code="TEST-TRIBUTARY"),
                _boundary(channel_id=1),
                _boundary(channel_id=2),
                _centerline(
                    id=1,
                    channel_id=1,
                    code="CL-MAIN-001",
                    geometry=_line((120.0, 31.1), (120.2, 31.1)),
                ),
                _centerline(
                    id=2,
                    channel_id=2,
                    code="CL-TRIBUTARY-001",
                    geometry=_line((120.1, 31.1), (120.1, 31.2)),
                ),
            ]
        )
        await session.commit()

        summary = await build_graph_from_centerlines(
            session=session,
            version_code="TEST-GRAPH-BOUNDARY-CONFLUENCE",
            scope_code="TEST",
            channel_codes=["TEST-MAIN-RIVER", "TEST-TRIBUTARY"],
        )
        junction = (
            await session.execute(
                select(NavigationGraphNode).where(
                    NavigationGraphNode.node_type_code == "CHANNEL_JUNCTION",
                    NavigationGraphNode.source_type_code == "CROSS_CHANNEL_BOUNDARY_CONFLUENCE",
                )
            )
        ).scalar_one()
        edge_count = await session.scalar(select(func.count()).select_from(NavigationGraphEdge))

    assert summary.status_code == "READY"
    assert float(junction.longitude) == pytest.approx(120.1)
    assert float(junction.latitude) == pytest.approx(31.1)
    assert edge_count == 3
    assert "CROSSING_NOT_NAVIGABLE" not in {issue.issue_code for issue in summary.issues}
    assert summary.validation_report is not None
    assert "GRAPH_DISCONNECTED" not in {issue["issue_code"] for issue in summary.validation_report["issues"]}


@pytest.mark.asyncio
async def test_near_endpoint_boundary_confluence_creates_connector_edge(session_maker) -> None:
    async with session_maker() as session:
        session.add_all(
            [
                _channel(id=1, code="TEST-MAIN-RIVER"),
                _channel(id=2, code="TEST-NEAR-TRIBUTARY"),
                _boundary(channel_id=1),
                _boundary(channel_id=2),
                _centerline(
                    id=1,
                    channel_id=1,
                    code="CL-MAIN-NEAR",
                    geometry=_line((120.0, 31.1), (120.1, 31.1)),
                ),
                _centerline(
                    id=2,
                    channel_id=2,
                    code="CL-TRIBUTARY-NEAR",
                    geometry=_line((120.1001, 31.1), (120.2, 31.1)),
                ),
            ]
        )
        await session.commit()

        summary = await build_graph_from_centerlines(
            session=session,
            version_code="TEST-GRAPH-NEAR-BOUNDARY-CONFLUENCE",
            scope_code="TEST",
            channel_codes=["TEST-MAIN-RIVER", "TEST-NEAR-TRIBUTARY"],
        )
        connector = (
            await session.execute(
                select(NavigationGraphEdge).where(
                    NavigationGraphEdge.source_type_code == "CROSS_CHANNEL_BOUNDARY_CONFLUENCE_CONNECTOR"
                )
            )
        ).scalar_one()

    assert summary.status_code == "READY"
    assert connector.routing_enabled is True
    assert float(connector.length_km) < 0.02
    assert summary.validation_report is not None
    assert "GRAPH_DISCONNECTED" not in {issue["issue_code"] for issue in summary.validation_report["issues"]}


@pytest.mark.asyncio
async def test_shared_water_body_cross_channel_intersection_creates_junction(session_maker) -> None:
    async with session_maker() as session:
        session.add_all(
            [
                _channel(id=1, code="TEST-A"),
                _channel(id=2, code="TEST-B"),
                _boundary(channel_id=1),
                _boundary(channel_id=2),
                NavigationWaterBody(
                    id=1,
                    water_body_code="WB-SHARED",
                    water_body_name="共享水体",
                    normalized_water_name="共享水体",
                    source_code="TEST",
                    body_role_code="PRIMARY_HIERARCHY",
                    dedupe_status_code="UNIQUE",
                    water_type_code="PERENNIAL_DOUBLE_LINE_RIVER",
                    geometry_wgs84_json=_polygon(119.9, 30.9, 120.4, 31.4),
                    bbox_min_lng=119.9,
                    bbox_min_lat=30.9,
                    bbox_max_lng=120.4,
                    bbox_max_lat=31.4,
                    is_enabled=True,
                ),
                NavigationChannelWaterBodyMatch(
                    channel_id=1,
                    water_body_id=1,
                    match_batch_code="TEST-SHARED-A",
                    match_type_code="TEST_SHARED_WATER",
                    score=100,
                    confidence_code="HIGH_CONFIDENCE",
                    is_current=True,
                ),
                NavigationChannelWaterBodyMatch(
                    channel_id=2,
                    water_body_id=1,
                    match_batch_code="TEST-SHARED-B",
                    match_type_code="TEST_SHARED_WATER",
                    score=100,
                    confidence_code="HIGH_CONFIDENCE",
                    is_current=True,
                ),
                _centerline(
                    id=1,
                    channel_id=1,
                    code="CL-A-SHARED",
                    geometry=_line((120.0, 31.1), (120.2, 31.1)),
                ),
                _centerline(
                    id=2,
                    channel_id=2,
                    code="CL-B-SHARED",
                    geometry=_line((120.1, 31.0), (120.1, 31.2)),
                ),
                TransportNode(
                    id=10,
                    code="PORT-SHARED-JUNCTION",
                    name="交汇口码头",
                    node_type_code="PORT",
                    province_code="320000",
                    city_code="320100",
                    city_region_id=1,
                    longitude=120.1,
                    latitude=31.1,
                    status=1,
                    lifecycle_status_code="ACTIVE",
                ),
            ]
        )
        await session.commit()

        summary = await build_graph_from_centerlines(
            session=session,
            version_code="TEST-GRAPH-SHARED-JUNCTION",
            scope_code="TEST",
            channel_codes=["TEST-A", "TEST-B"],
        )
        junction_count = await session.scalar(
            select(func.count()).select_from(NavigationGraphNode).where(NavigationGraphNode.node_type_code == "CHANNEL_JUNCTION")
        )
        edge_count = await session.scalar(select(func.count()).select_from(NavigationGraphEdge))
        junction = (
            await session.execute(select(NavigationGraphNode).where(NavigationGraphNode.node_type_code == "CHANNEL_JUNCTION"))
        ).scalar_one()
        connector = (
            await session.execute(
                select(NavigationGraphEdge).where(NavigationGraphEdge.source_type_code == "SNAP_CONNECTOR")
            )
        ).scalar_one()

    assert summary.status_code == "READY"
    assert junction_count == 1
    assert edge_count == 5
    assert connector.to_node_id == junction.id
    assert "CROSSING_NOT_NAVIGABLE" not in {issue.issue_code for issue in summary.issues}


@pytest.mark.asyncio
async def test_transport_node_creates_snap_connector_edge(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel_with_centerline(
            session,
            centerline=_centerline(
                id=1,
                channel_id=1,
                code="CL-PORT-001",
                geometry=_line((120.0, 31.0), (120.2, 31.0)),
            ),
        )
        session.add(
            TransportNode(
                id=10,
                code="PORT-001",
                name="测试码头",
                node_type_code="PORT",
                province_code="320000",
                city_code="320100",
                city_region_id=1,
                longitude=120.1,
                latitude=31.0005,
                status=1,
                lifecycle_status_code="ACTIVE",
            )
        )
        await session.commit()

        summary = await build_graph_from_centerlines(
            session=session,
            version_code="TEST-GRAPH-PORT",
            scope_code="TEST",
            channel_codes=["TEST-MAIN"],
        )
        connector = (
            await session.execute(
                select(NavigationGraphEdge).where(NavigationGraphEdge.source_type_code == "SNAP_CONNECTOR")
            )
        ).scalar_one()
        port_node = (
            await session.execute(
                select(NavigationGraphNode).where(NavigationGraphNode.related_transport_node_id == 10)
            )
        ).scalar_one()

    assert summary.status_code == "READY"
    assert summary.connector_edge_count == 1
    assert connector.quality_code == "READY"
    assert connector.routing_enabled is True
    assert port_node.node_type_code == "PORT"


@pytest.mark.asyncio
async def test_transport_connector_within_review_distance_routes_when_boundary_verified(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel_with_centerline(
            session,
            centerline=_centerline(
                id=1,
                channel_id=1,
                code="CL-PORT-BOUNDARY-001",
                geometry=_line((120.0, 31.0), (120.2, 31.0)),
            ),
        )
        session.add(
            TransportNode(
                id=10,
                code="PORT-BOUNDARY-001",
                name="边界内码头",
                node_type_code="PORT",
                province_code="320000",
                city_code="320100",
                city_region_id=1,
                longitude=120.1,
                latitude=31.003,
                status=1,
                lifecycle_status_code="ACTIVE",
            )
        )
        await session.commit()

        summary = await build_graph_from_centerlines(
            session=session,
            version_code="TEST-GRAPH-PORT-BOUNDARY",
            scope_code="TEST",
            channel_codes=["TEST-MAIN"],
        )
        connector = (
            await session.execute(
                select(NavigationGraphEdge).where(NavigationGraphEdge.source_type_code == "SNAP_CONNECTOR")
            )
        ).scalar_one()

    assert summary.status_code == "READY"
    assert connector.quality_code == "READY_WITH_WARNING"
    assert connector.routing_enabled is True
    assert connector.validation_summary_json["issue_codes"] == ["SNAP_CONNECTOR_BOUNDARY_VERIFIED"]


@pytest.mark.asyncio
async def test_transport_connector_within_review_distance_stays_disabled_outside_boundary(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel_with_centerline(
            session,
            boundary=_boundary(channel_id=1, min_lng=119.9, min_lat=30.99, max_lng=120.4, max_lat=31.001),
            centerline=_centerline(
                id=1,
                channel_id=1,
                code="CL-PORT-OUTSIDE-001",
                geometry=_line((120.0, 31.0), (120.2, 31.0)),
            ),
        )
        session.add(
            TransportNode(
                id=10,
                code="PORT-OUTSIDE-001",
                name="边界外码头",
                node_type_code="PORT",
                province_code="320000",
                city_code="320100",
                city_region_id=1,
                longitude=120.1,
                latitude=31.003,
                status=1,
                lifecycle_status_code="ACTIVE",
            )
        )
        await session.commit()

        summary = await build_graph_from_centerlines(
            session=session,
            version_code="TEST-GRAPH-PORT-OUTSIDE",
            scope_code="TEST",
            channel_codes=["TEST-MAIN"],
        )
        connector = (
            await session.execute(
                select(NavigationGraphEdge).where(NavigationGraphEdge.source_type_code == "SNAP_CONNECTOR")
            )
        ).scalar_one()

    assert summary.status_code == "READY"
    assert connector.quality_code == "NEED_REVIEW"
    assert connector.routing_enabled is False
    assert connector.validation_summary_json["issue_codes"] == ["SNAP_CONNECTOR_NEED_REVIEW"]


@pytest.mark.asyncio
async def test_out_of_boundary_edge_is_disabled_and_fails_validation(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel_with_centerline(
            session,
            boundary=_boundary(channel_id=1, min_lng=121.0, min_lat=32.0, max_lng=121.2, max_lat=32.2),
            centerline=_centerline(
                id=1,
                channel_id=1,
                code="CL-OUT-001",
                geometry=_line((120.0, 31.0), (120.2, 31.2)),
            ),
        )

        summary = await build_graph_from_centerlines(
            session=session,
            version_code="TEST-GRAPH-OUT",
            scope_code="TEST",
            channel_codes=["TEST-MAIN"],
        )
        edge = (await session.execute(select(NavigationGraphEdge))).scalar_one()

    assert summary.status_code == "FAILED"
    assert edge.quality_code == "OUT_OF_BOUNDARY"
    assert edge.routing_enabled is False


@pytest.mark.asyncio
async def test_near_boundary_edge_is_warning_not_intersects_pass(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel_with_centerline(
            session,
            boundary=_boundary(channel_id=1, min_lng=120.0, min_lat=31.0, max_lng=120.2, max_lat=31.2),
            centerline=_centerline(
                id=1,
                channel_id=1,
                code="CL-NEAR-001",
                geometry=_line((120.0, 31.0), (120.2001, 31.2)),
            ),
        )

        summary = await build_graph_from_centerlines(
            session=session,
            version_code="TEST-GRAPH-NEAR",
            scope_code="TEST",
            channel_codes=["TEST-MAIN"],
        )
        edge = (await session.execute(select(NavigationGraphEdge))).scalar_one()

    assert summary.status_code == "READY"
    assert edge.quality_code == "READY_WITH_WARNING"
    assert edge.routing_enabled is True
    assert "EDGE_NEAR_BOUNDARY_TOLERATED" in {issue.issue_code for issue in summary.issues}


@pytest.mark.asyncio
async def test_constraint_point_splits_edge_and_creates_edge_constraints(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel_with_centerline(
            session,
            centerline=_centerline(
                id=1,
                channel_id=1,
                code="CL-LOCK-001",
                geometry=_line((120.0, 31.0), (120.2, 31.0)),
            ),
        )
        session.add(
            NavigationConstraintPoint(
                id=20,
                code="LOCK-001",
                name="测试船闸",
                constraint_type_code="LOCK",
                longitude=120.1,
                latitude=31.0,
                status=1,
            )
        )
        await session.commit()

        summary = await build_graph_from_centerlines(
            session=session,
            version_code="TEST-GRAPH-LOCK",
            scope_code="TEST",
            channel_codes=["TEST-MAIN"],
        )
        lock_count = await session.scalar(
            select(func.count()).select_from(NavigationGraphNode).where(NavigationGraphNode.node_type_code == "LOCK")
        )
        edge_constraints = (
            await session.execute(
                select(NavigationGraphEdgeConstraint).order_by(NavigationGraphEdgeConstraint.id)
            )
        ).scalars().all()
        lock_edges = (
            await session.execute(select(NavigationGraphEdge).where(NavigationGraphEdge.lock_required.is_(True)))
        ).scalars().all()

    assert summary.status_code == "READY"
    assert lock_count == 1
    assert len(edge_constraints) == 2
    assert len(lock_edges) == 2
    assert all(item.constraint_type_code == "LOCK_SCHEDULE" for item in edge_constraints)
