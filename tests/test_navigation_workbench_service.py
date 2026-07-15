from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.exceptions import ConflictError
from app.models import (
    NavigationChannelCenterline,
    NavigationChannelWaterBodyMatch,
    NavigationGeometryDraft,
    NavigationGraphEdge,
    NavigationGraphEdgeConstraint,
    NavigationGraphNode,
    NavigationGraphVersion,
    NavigationWaterArea,
    NavigationWaterBody,
    NavigationWaterBodyFeatureLink,
)
from app.models.address import NavigationChannel, NavigationChannelBoundary, NavigationConstraintPoint, TransportNode
from app.models.base import Base
from app.modules.navigation.schemas import (
    NavigationCandidateGenerateRequest,
    NavigationGraphEdgeConstraintRepairRequest,
    NavigationGeometryDraftCreateRequest,
    NavigationGeometryDraftValidateRequest,
    NavigationGraphBuildRequest,
    NavigationWaterBodyMatchCreateRequest,
    NavigationWaterBodyNameUpdateRequest,
)
from app.modules.navigation.production_service import NavigationProductionService
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
    assert build.diagnostics is not None
    assert build.diagnostics["can_activate"] is True
    assert build.diagnostics["routing_edge_count"] >= 1
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
                boundary_quality_code="SEED_PUBLISHED",
                connectivity_status_code="CONNECTED",
                repair_status_code="NONE",
                coverage_policy_code="SEED_BOUNDARY",
                is_current=True,
            )
        )
        session.add(
            NavigationChannelCenterline(
                id=1,
                channel_id=1,
                centerline_code="LEGACY-CENTERLINE",
                centerline_name="legacy centerline",
                geometry_json=_line(),
                source_type_code="MANUAL",
                direction_code="BIDIRECTIONAL",
                is_main_line=True,
                confidence_score=90,
                quality_code="READY",
                review_status_code="PUBLISHED",
                version_no=1,
                is_current=True,
            )
        )
        session.add(
            NavigationGraphVersion(
                id=1,
                version_code="LEGACY-GRAPH",
                version_name="legacy graph",
                scope_code="TEST",
                status_code="READY",
                is_active=True,
                node_count=2,
                edge_count=1,
                channel_count=1,
            )
        )
        session.add(
            NavigationGraphEdge(
                id=1,
                graph_version_id=1,
                edge_code="LEGACY-E1",
                from_node_id=1,
                to_node_id=2,
                channel_id=1,
                geometry_json=_line(),
                length_km=1,
                direction_code="BIDIRECTIONAL",
                routing_enabled=True,
                quality_code="READY",
                source_type_code="MANUAL",
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
        workspace = await NavigationProductionService(session).production_workspace(channel_id=1, step="boundary")
        boundaries = list((await session.execute(select(NavigationChannelBoundary).order_by(NavigationChannelBoundary.id))).scalars())
        drafts = list((await session.execute(select(NavigationGeometryDraft))).scalars())

    assert published.publish_target_type_code == "BOUNDARY"
    assert len(boundaries) == 2
    assert boundaries[0].coverage_policy_code == "SEED_BOUNDARY"
    assert boundaries[0].is_current is False
    assert boundaries[1].coverage_policy_code == "MANUAL_DRAW"
    assert boundaries[1].is_current is True
    assert boundaries[1].source_trace_json["previous_boundary_id"] == 1
    assert boundaries[1].source_trace_json["caused_downstream_stale"] is True
    assert workspace.downstream_stale["centerline_stale"] is True
    assert workspace.downstream_stale["graph_stale"] is True
    assert workspace.current_boundary_bbox is not None
    assert workspace.current_centerline_bbox is not None
    assert workspace.boundary_water_bbox_coverage_ratio is not None
    assert workspace.centerline_boundary_bbox_coverage_ratio is not None
    assert drafts[0].status_code == "PUBLISHED"


@pytest.mark.asyncio
async def test_publish_rejects_too_short_centerline_without_formal_asset(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        service = NavigationWorkbenchService(session)
        draft = await service.create_geometry_draft(
            NavigationGeometryDraftCreateRequest(
                draft_type_code="CENTERLINE",
                draft_name="过短中心线",
                channel_id=1,
                geometry_json={"type": "LineString", "coordinates": [[120.0, 31.0], [120.00001, 31.0]]},
                source_type_code="GEOJSON_PASTE",
            ),
            created_by=7,
        )

        with pytest.raises(Exception) as exc_info:
            await service.publish_geometry_draft(draft.id, published_by=8)
        centerline_count = await session.scalar(select(func.count()).select_from(NavigationChannelCenterline))
        draft_row = await session.get(NavigationGeometryDraft, draft.id)

    assert "CENTERLINE_TOO_SHORT" in str(exc_info.value)
    assert exc_info.value.detail["error_code"] == "CENTERLINE_TOO_SHORT"
    assert exc_info.value.detail["issues"][0]["issue_code"] == "CENTERLINE_TOO_SHORT"
    assert centerline_count == 0
    assert draft_row is not None
    assert draft_row.status_code == "PUBLISH_BLOCKED"
    assert draft_row.source_trace_json["validation_summary"]["error_count"] == 1


@pytest.mark.asyncio
async def test_publish_rejects_centerline_out_of_current_boundary(session_maker) -> None:
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
                boundary_quality_code="MANUAL_PUBLISHED",
                connectivity_status_code="CONNECTED",
                repair_status_code="NONE",
                coverage_policy_code="MANUAL_DRAW",
                is_current=True,
            )
        )
        await session.commit()
        service = NavigationWorkbenchService(session)
        draft = await service.create_geometry_draft(
            NavigationGeometryDraftCreateRequest(
                draft_type_code="CENTERLINE",
                draft_name="越界中心线",
                channel_id=1,
                geometry_json={"type": "LineString", "coordinates": [[121.0, 32.0], [121.2, 32.2]]},
                source_type_code="GEOJSON_PASTE",
            ),
            created_by=7,
        )

        with pytest.raises(Exception) as exc_info:
            await service.publish_geometry_draft(draft.id, published_by=8)
        centerline_count = await session.scalar(select(func.count()).select_from(NavigationChannelCenterline))

    assert "CENTERLINE_OUT_OF_BOUNDARY" in str(exc_info.value)
    assert centerline_count == 0


@pytest.mark.asyncio
async def test_publish_rejects_unclosed_boundary_ring(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        service = NavigationWorkbenchService(session)
        draft = await service.create_geometry_draft(
            NavigationGeometryDraftCreateRequest(
                draft_type_code="BOUNDARY",
                draft_name="未闭合边界",
                channel_id=1,
                geometry_json={
                    "type": "Polygon",
                    "coordinates": [[[120.0, 31.0], [120.2, 31.0], [120.2, 31.2], [120.0, 31.2]]],
                },
                source_type_code="GEOJSON_PASTE",
            ),
            created_by=7,
        )

        with pytest.raises(Exception) as exc_info:
            await service.publish_geometry_draft(draft.id, published_by=8)
        boundary_count = await session.scalar(select(func.count()).select_from(NavigationChannelBoundary))

    assert "BOUNDARY_RING_NOT_CLOSED" in str(exc_info.value)
    assert boundary_count == 0


@pytest.mark.asyncio
async def test_validate_centerline_ready(session_maker) -> None:
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
                boundary_quality_code="MANUAL_PUBLISHED",
                connectivity_status_code="CONNECTED",
                repair_status_code="NONE",
                coverage_policy_code="MANUAL_DRAW",
                is_current=True,
            )
        )
        await session.commit()

        response = await NavigationWorkbenchService(session).validate_geometry_draft(
            NavigationGeometryDraftValidateRequest(draft_type_code="CENTERLINE", channel_id=1, geometry_json=_line())
        )

    assert response.valid is True
    assert response.publishable is True
    assert response.quality_code == "READY"
    assert response.length_m is not None and response.length_m > 0
    assert response.point_count == 3
    assert response.error_count == 0


@pytest.mark.asyncio
async def test_validate_centerline_accepts_tuple_coordinates_from_mapping(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        geometry = {
            "type": "LineString",
            "coordinates": ((120.0, 31.0), (120.12, 31.06), (120.22, 31.1)),
        }

        response = await NavigationWorkbenchService(session).validate_geometry_draft(
            NavigationGeometryDraftValidateRequest(draft_type_code="CENTERLINE", channel_id=1, geometry_json=geometry)
        )

    issue_codes = [issue.issue_code for issue in response.issues]
    assert "CENTERLINE_GEOMETRY_INVALID" not in issue_codes
    assert "CENTERLINE_COORDINATE_INVALID" not in issue_codes
    assert response.point_count == 3
    assert response.length_m is not None and response.length_m > 0


@pytest.mark.asyncio
async def test_validate_centerline_too_short(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)

        response = await NavigationWorkbenchService(session).validate_geometry_draft(
            NavigationGeometryDraftValidateRequest(
                draft_type_code="CENTERLINE",
                channel_id=1,
                geometry_json={"type": "LineString", "coordinates": [[120.0, 31.0], [120.00001, 31.0]]},
            )
        )

    assert response.publishable is False
    assert response.quality_code == "PUBLISH_BLOCKED"
    assert "CENTERLINE_TOO_SHORT" in [issue.issue_code for issue in response.issues]


@pytest.mark.asyncio
async def test_validate_centerline_out_of_boundary(session_maker) -> None:
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
                boundary_quality_code="MANUAL_PUBLISHED",
                connectivity_status_code="CONNECTED",
                repair_status_code="NONE",
                coverage_policy_code="MANUAL_DRAW",
                is_current=True,
            )
        )
        await session.commit()

        response = await NavigationWorkbenchService(session).validate_geometry_draft(
            NavigationGeometryDraftValidateRequest(
                draft_type_code="CENTERLINE",
                channel_id=1,
                geometry_json={"type": "LineString", "coordinates": [[121.0, 32.0], [121.2, 32.2]]},
            )
        )

    assert response.publishable is False
    assert "CENTERLINE_OUT_OF_BOUNDARY" in [issue.issue_code for issue in response.issues]


@pytest.mark.asyncio
async def test_validate_boundary_ready(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)

        response = await NavigationWorkbenchService(session).validate_geometry_draft(
            NavigationGeometryDraftValidateRequest(draft_type_code="BOUNDARY", channel_id=1, geometry_json=_polygon())
        )

    assert response.valid is True
    assert response.publishable is True
    assert response.quality_code == "READY"
    assert response.area_m2 is not None and response.area_m2 > 100
    assert response.ring_count == 1


@pytest.mark.asyncio
async def test_validate_boundary_ring_not_closed(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)

        response = await NavigationWorkbenchService(session).validate_geometry_draft(
            NavigationGeometryDraftValidateRequest(
                draft_type_code="BOUNDARY",
                channel_id=1,
                geometry_json={
                    "type": "Polygon",
                    "coordinates": [[[120.0, 31.0], [120.2, 31.0], [120.2, 31.2], [120.0, 31.2]]],
                },
            )
        )

    assert response.publishable is False
    assert "BOUNDARY_RING_NOT_CLOSED" in [issue.issue_code for issue in response.issues]


@pytest.mark.asyncio
async def test_validate_boundary_area_too_small(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)

        response = await NavigationWorkbenchService(session).validate_geometry_draft(
            NavigationGeometryDraftValidateRequest(
                draft_type_code="BOUNDARY",
                channel_id=1,
                geometry_json={
                    "type": "Polygon",
                    "coordinates": [[
                        [120.0, 31.0],
                        [120.00001, 31.0],
                        [120.00001, 31.00001],
                        [120.0, 31.00001],
                        [120.0, 31.0],
                    ]],
                },
            )
        )

    assert response.publishable is False
    assert "BOUNDARY_AREA_TOO_SMALL" in [issue.issue_code for issue in response.issues]


@pytest.mark.asyncio
async def test_snap_references_return_current_channel_context_points(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        session.add_all(
            [
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
                    boundary_quality_code="MANUAL_PUBLISHED",
                    connectivity_status_code="CONNECTED",
                    repair_status_code="NONE",
                    coverage_policy_code="MANUAL_DRAW",
                    is_current=True,
                ),
                NavigationChannelCenterline(
                    id=1,
                    channel_id=1,
                    centerline_code="CL-CURRENT",
                    geometry_json=_line(),
                    source_type_code="MANUAL",
                    quality_code="READY",
                    review_status_code="PUBLISHED",
                    confidence_score=90,
                    is_current=True,
                ),
                NavigationChannelCenterline(
                    id=2,
                    channel_id=1,
                    centerline_code="CL-CANDIDATE",
                    geometry_json={"type": "LineString", "coordinates": [[120.01, 31.01], [120.05, 31.05]]},
                    source_type_code="IMPORTED",
                    quality_code="NEED_REPAIR",
                    review_status_code="DRAFT",
                    confidence_score=50,
                    is_current=False,
                ),
                TransportNode(
                    id=1,
                    code="NODE-1",
                    name="测试码头",
                    node_type_code="PORT",
                    province_code="320000",
                    city_code="320500",
                    city_region_id=1,
                    longitude=120.10,
                    latitude=31.05,
                    status=1,
                    lifecycle_status_code="ACTIVE",
                ),
                NavigationConstraintPoint(
                    id=1,
                    code="LOCK-1",
                    name="测试船闸",
                    constraint_type_code="LOCK",
                    longitude=120.11,
                    latitude=31.06,
                    status=1,
                ),
            ]
        )
        await session.commit()

        references = await NavigationWorkbenchService(session).snap_references(1)

    ref_types = {row.ref_type_code for row in references}
    assert "CENTERLINE_ENDPOINT" in ref_types
    assert "CANDIDATE_ENDPOINT" in ref_types
    assert "TRANSPORT_NODE" in ref_types
    assert "CONSTRAINT_POINT" in ref_types
    assert all(119.98 <= row.longitude <= 120.24 for row in references if row.ref_type_code in {"TRANSPORT_NODE", "CONSTRAINT_POINT"})


@pytest.mark.asyncio
async def test_create_geometry_draft_writes_validation_summary(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)

        draft = await NavigationWorkbenchService(session).create_geometry_draft(
            NavigationGeometryDraftCreateRequest(
                draft_type_code="CENTERLINE",
                draft_name="带校验摘要草稿",
                channel_id=1,
                geometry_json={"type": "LineString", "coordinates": [[120.0, 31.0], [120.00001, 31.0]]},
                source_type_code="MANUAL_DRAW",
            ),
            created_by=7,
        )
        row = await session.get(NavigationGeometryDraft, draft.id)

    assert draft.status_code == "DRAFT"
    assert draft.quality_code == "PUBLISH_BLOCKED"
    assert row is not None
    summary = row.source_trace_json["validation_summary"]
    assert summary["error_count"] == 1
    assert "CENTERLINE_TOO_SHORT" in summary["issue_codes"]


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
async def test_graph_build_without_published_centerline_fails_with_real_scope(session_maker) -> None:
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
    assert graph_version.validation_report_json["issues"][0]["issue_code"] == "NO_PUBLISHED_CENTERLINE"


@pytest.mark.asyncio
async def test_production_workspace_returns_graph_diagnostics(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        session.add(
            NavigationGraphVersion(
                id=1,
                version_code="TEST-GRAPH-DIAG",
                version_name="Graph diagnostics",
                scope_code="TEST",
                status_code="READY",
                is_active=True,
                node_count=2,
                edge_count=2,
                channel_count=1,
                quality_score=91,
                validation_report_json={
                    "component_count": 1,
                    "blocking_issue_count": 0,
                    "warning_issue_count": 1,
                    "issues": [
                        {
                            "issue_code": "UNKNOWN_CONSTRAINT_DATA",
                            "severity_code": "WARNING",
                            "message": "constraint data missing",
                        }
                    ],
                },
                source_summary_json={"source_boundary_ids": [7]},
            )
        )
        session.add_all(
            [
                NavigationGraphNode(
                    id=1,
                    graph_version_id=1,
                    node_code="N1",
                    node_type_code="CENTERLINE_VERTEX",
                    longitude=120.0,
                    latitude=31.0,
                    geometry_json={"type": "Point", "coordinates": [120.0, 31.0]},
                    is_enabled=True,
                    quality_code="READY",
                    source_type_code="CENTERLINE_VERTEX",
                ),
                NavigationGraphNode(
                    id=2,
                    graph_version_id=1,
                    node_code="N2",
                    node_type_code="CENTERLINE_VERTEX",
                    longitude=120.1,
                    latitude=31.1,
                    geometry_json={"type": "Point", "coordinates": [120.1, 31.1]},
                    is_enabled=True,
                    quality_code="READY",
                    source_type_code="CENTERLINE_VERTEX",
                ),
            ]
        )
        session.add_all(
            [
                NavigationGraphEdge(
                    id=1,
                    graph_version_id=1,
                    edge_code="E1",
                    from_node_id=1,
                    to_node_id=2,
                    channel_id=1,
                    geometry_json=_line(),
                    length_km=1,
                    direction_code="BIDIRECTIONAL",
                    routing_enabled=True,
                    quality_code="READY_WITH_WARNING",
                    source_type_code="CENTERLINE_SEGMENT_MERGE",
                    unknown_constraint_flag=True,
                ),
                NavigationGraphEdge(
                    id=2,
                    graph_version_id=1,
                    edge_code="E2",
                    from_node_id=2,
                    to_node_id=1,
                    channel_id=1,
                    geometry_json=_line(),
                    length_km=1,
                    direction_code="BIDIRECTIONAL",
                    routing_enabled=False,
                    quality_code="READY",
                    source_type_code="CENTERLINE_SEGMENT_MERGE",
                    unknown_constraint_flag=False,
                ),
                NavigationGraphEdgeConstraint(
                    id=1,
                    edge_id=2,
                    constraint_type_code="LOCK",
                    constraint_name="测试船闸",
                    severity_level="WARNING",
                    is_blocking=False,
                    is_enabled=True,
                    data_completeness_code="COMPLETE",
                ),
            ]
        )
        await session.commit()

        workspace = await NavigationProductionService(session).production_workspace(channel_id=1, step="route")

    diagnostics = workspace.graph_diagnostics
    assert diagnostics is not None
    assert diagnostics["graph_version_id"] == 1
    assert diagnostics["routing_edge_count"] == 1
    assert diagnostics["unknown_constraint_edge_count"] == 1
    assert diagnostics["constraint_edge_count"] == 1
    assert diagnostics["constraint_completeness_ratio"] == 0.5
    assert diagnostics["issue_counts"]["UNKNOWN_CONSTRAINT_DATA"] == 1
    assert diagnostics["source_boundary_ids"] == [7]
    assert diagnostics["can_activate"] is True
    assert diagnostics["activation_warnings"] == ["UNKNOWN_CONSTRAINT_DATA", "HAS_WARNING_ISSUES"]

    async with session_maker() as session:
        versions = await NavigationWorkbenchService(session).list_graph_versions(limit=5)
        issue_edges = await NavigationWorkbenchService(session).list_graph_issue_edges(
            1,
            issue_code="UNKNOWN_CONSTRAINT_DATA",
            include_geometry=False,
        )
        all_issue_edges = await NavigationWorkbenchService(session).list_graph_issue_edges(1, include_geometry=True)

    assert versions[0].diagnostics is not None
    assert versions[0].diagnostics["graph_version_id"] == 1
    assert versions[0].diagnostics["routing_edge_count"] == 1
    assert issue_edges.total == 1
    assert issue_edges.items[0].id == 1
    assert issue_edges.items[0].geometry_json is None
    assert issue_edges.items[0].center["lng"] is not None
    assert "UNKNOWN_CONSTRAINT_DATA" in issue_edges.items[0].issue_codes
    assert all_issue_edges.total == 2
    assert all_issue_edges.items[0].geometry_json is not None

    async with session_maker() as session:
        service = NavigationWorkbenchService(session)
        repaired = await service.repair_graph_edge_constraint(
            1,
            NavigationGraphEdgeConstraintRepairRequest(
                min_depth_m=8.5,
                min_width_m=180,
                max_allowed_draft_m=6.2,
                max_allowed_tonnage=5000,
                bridge_count=0,
                warning_message="人工补齐测试约束",
            ),
            repaired_by=9,
        )
        edge = await session.get(NavigationGraphEdge, 1)
        constraints = list(
            (
                await session.execute(
                    select(NavigationGraphEdgeConstraint).where(NavigationGraphEdgeConstraint.edge_id == 1)
                )
            ).scalars()
        )
        issue_edges_after_repair = await service.list_graph_issue_edges(
            1,
            issue_code="UNKNOWN_CONSTRAINT_DATA",
            include_geometry=False,
        )

    assert repaired.unknown_constraint_flag is False
    assert repaired.min_depth_m == 8.5
    assert repaired.max_allowed_draft_m == 6.2
    assert repaired.constraint_count == 1
    assert edge is not None
    assert edge.unknown_constraint_flag is False
    assert float(edge.min_depth_m or 0) == 8.5
    assert constraints[0].constraint_type_code == "MANUAL_NAVIGATION_LIMIT"
    assert constraints[0].data_completeness_code == "COMPLETE"
    assert constraints[0].source_trace_json["repaired_by"] == 9
    assert issue_edges_after_repair.total == 0


@pytest.mark.asyncio
async def test_graph_activation_blocks_stale_ready_version_without_routing_edges(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        session.add(
            NavigationGraphVersion(
                id=1,
                version_code="TEST-GRAPH-NO-ROUTING",
                version_name="No routing graph",
                scope_code="TEST",
                status_code="READY",
                is_active=False,
                node_count=2,
                edge_count=1,
                channel_count=1,
                quality_score=100,
                validation_report_json={
                    "component_count": 0,
                    "blocking_issue_count": 0,
                    "warning_issue_count": 0,
                    "issues": [],
                },
            )
        )
        await session.commit()

        with pytest.raises(ConflictError) as exc:
            await NavigationWorkbenchService(session).activate_graph_version(1)

    assert exc.value.detail["activation_blockers"] == ["NO_ROUTING_EDGE"]
    assert exc.value.detail["diagnostics"]["can_activate"] is False


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
async def test_workbench_summary_active_graph_version_uses_production_ready_filter(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        session.add_all(
            [
                NavigationGraphVersion(
                    id=1,
                    version_code="GV-READY",
                    version_name="Ready graph",
                    scope_code="REAL-READY",
                    status_code="READY",
                    is_active=True,
                    node_count=2,
                    edge_count=1,
                    channel_count=1,
                    quality_score=90,
                ),
                NavigationGraphVersion(
                    id=2,
                    version_code="GV-FAILED",
                    version_name="Failed graph",
                    scope_code="REAL-FAILED",
                    status_code="FAILED",
                    is_active=True,
                    node_count=2,
                    edge_count=1,
                    channel_count=1,
                    quality_score=10,
                ),
                NavigationGraphVersion(
                    id=3,
                    version_code="GV-MVP",
                    version_name="MVP graph",
                    scope_code="MVP-TEST",
                    status_code="READY",
                    is_active=True,
                    node_count=2,
                    edge_count=1,
                    channel_count=1,
                    quality_score=70,
                ),
                NavigationGraphVersion(
                    id=4,
                    version_code="GV-EMPTY",
                    version_name="Empty graph",
                    scope_code="REAL-EMPTY",
                    status_code="READY",
                    is_active=True,
                    node_count=0,
                    edge_count=0,
                    channel_count=0,
                    quality_score=0,
                ),
            ]
        )
        await session.commit()

        summary = await NavigationWorkbenchService(session).summary()
        ready_graph = await session.get(NavigationGraphVersion, 1)
        assert ready_graph is not None
        ready_graph.is_active = False
        await session.commit()

        invalid_only_summary = await NavigationWorkbenchService(session).summary()

    assert summary.active_graph_version is not None
    assert summary.active_graph_version["version_code"] == "GV-READY"
    assert summary.active_graph_version["status_code"] == "READY"
    assert summary.active_graph_version["scope_code"] == "REAL-READY"
    assert summary.active_graph_version["edge_count"] == 1
    assert invalid_only_summary.active_graph_version is None


@pytest.mark.asyncio
async def test_workbench_active_graph_counts_use_default_active_graph_only(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        session.add_all(
            [
                NavigationGraphVersion(
                    id=1,
                    version_code="GV-ONE",
                    version_name="Graph one",
                    scope_code="REAL-ONE",
                    status_code="READY",
                    is_active=True,
                    node_count=4,
                    edge_count=2,
                    channel_count=2,
                    quality_score=90,
                ),
                NavigationGraphVersion(
                    id=2,
                    version_code="GV-TWO",
                    version_name="Graph two",
                    scope_code="REAL-TWO",
                    status_code="READY",
                    is_active=True,
                    node_count=2,
                    edge_count=1,
                    channel_count=1,
                    quality_score=90,
                ),
                NavigationGraphEdge(
                    id=1,
                    graph_version_id=1,
                    edge_code="E1",
                    from_node_id=1,
                    to_node_id=2,
                    channel_id=1,
                    geometry_json=_line(),
                    length_km=1,
                    direction_code="BIDIRECTIONAL",
                    routing_enabled=True,
                    quality_code="READY",
                    source_type_code="MANUAL",
                ),
                NavigationGraphEdge(
                    id=2,
                    graph_version_id=2,
                    edge_code="E2",
                    from_node_id=3,
                    to_node_id=4,
                    channel_id=1,
                    geometry_json=_line(),
                    length_km=1,
                    direction_code="BIDIRECTIONAL",
                    routing_enabled=True,
                    quality_code="READY",
                    source_type_code="MANUAL",
                ),
            ]
        )
        await session.commit()

        summary = await NavigationWorkbenchService(session).summary()

    assert summary.channels[0].active_graph_edge_count == 1


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


@pytest.mark.asyncio
async def test_production_boundary_candidate_generation_uses_water_body_without_overwriting_seed(session_maker) -> None:
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
                boundary_quality_code="SEED_REFERENCE",
                connectivity_status_code="UNKNOWN",
                repair_status_code="NONE",
                coverage_policy_code="CHANNEL_CORRIDOR_ENVELOPE",
                is_current=True,
            )
        )
        session.add(
            NavigationWaterBody(
                id=1,
                water_body_code="WB-CANDIDATE",
                water_body_name="测试水体",
                normalized_water_name="测试水体",
                source_code="RIVER_SHAPEFILE_2026",
                body_role_code="PRIMARY_HIERARCHY",
                dedupe_status_code="DEDUPED",
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
            NavigationChannelWaterBodyMatch(
                id=1,
                channel_id=1,
                water_body_id=1,
                match_batch_code="TEST-BODY-MATCH",
                match_type_code="MANUAL_ADD",
                score=96,
                confidence_code="MANUAL_CONFIRMED",
                issue_codes=[],
                is_current=True,
                source_water_area_ids_json=[1],
            )
        )
        await session.commit()

        response = await NavigationProductionService(session).generate_boundary_candidates(
            channel_id=1,
            body=NavigationCandidateGenerateRequest(),
        )
        boundaries = list((await session.execute(select(NavigationChannelBoundary).order_by(NavigationChannelBoundary.id))).scalars())

    assert response.status_code == "CREATED"
    assert response.created_count == 3
    assert response.matched_water_body_count == 1
    assert len(boundaries) == 4
    assert boundaries[0].is_current is True
    assert boundaries[0].coverage_policy_code == "CHANNEL_CORRIDOR_ENVELOPE"
    candidate_policies = {row.coverage_policy_code for row in boundaries[1:]}
    assert candidate_policies == {
        "WATER_BODY_UNION_RAW",
        "WATER_BODY_UNION_CLEANED",
        "WATER_BODY_UNION_SIMPLIFIED",
    }
    assert all(row.is_current is False for row in boundaries[1:])


@pytest.mark.asyncio
async def test_boundary_archive_hides_non_current_and_blocks_current(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        geometry = _polygon()
        session.add_all(
            [
                NavigationChannelBoundary(
                    id=1,
                    channel_id=1,
                    geometry_json=geometry,
                    boundary_paths_low=geometry["coordinates"],
                    bbox_min_lng=119.98,
                    bbox_min_lat=30.98,
                    bbox_max_lng=120.24,
                    bbox_max_lat=31.12,
                    geometry_status_code="AVAILABLE",
                    boundary_quality_code="MANUAL_PUBLISHED",
                    connectivity_status_code="CONNECTED",
                    repair_status_code="NONE",
                    coverage_policy_code="MANUAL_DRAW",
                    is_current=True,
                ),
                NavigationChannelBoundary(
                    id=2,
                    channel_id=1,
                    geometry_json=geometry,
                    boundary_paths_low=geometry["coordinates"],
                    bbox_min_lng=119.98,
                    bbox_min_lat=30.98,
                    bbox_max_lng=120.24,
                    bbox_max_lat=31.12,
                    geometry_status_code="AVAILABLE",
                    boundary_quality_code="AUTO_CANDIDATE",
                    connectivity_status_code="CONNECTED",
                    repair_status_code="NONE",
                    coverage_policy_code="WATER_BODY_UNION_SIMPLIFIED",
                    is_current=False,
                ),
            ]
        )
        await session.commit()
        service = NavigationWorkbenchService(session)

        with pytest.raises(Exception) as exc_info:
            await service.archive_boundary(1, reason="current should stay")
        archived = await service.archive_boundary(2, reason="hide noisy candidate")
        visible = await service.list_boundaries(channel_id=1)
        all_rows = await service.list_boundaries(channel_id=1, include_archived=True)

    assert exc_info.value.code == "CURRENT_BOUNDARY_ARCHIVE_BLOCKED"
    assert archived.geometry_status_code == "ARCHIVED"
    assert archived.source_trace_json["archive_reason"] == "hide noisy candidate"
    assert [item.id for item in visible] == [1]
    assert {item.id for item in all_rows} == {1, 2}


@pytest.mark.asyncio
async def test_production_centerline_candidate_generation_does_not_create_fake_line(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        response = await NavigationProductionService(session).generate_centerline_candidates(
            channel_id=1,
            body=NavigationCandidateGenerateRequest(),
        )
        centerline_count = await session.scalar(select(func.count()).select_from(NavigationChannelCenterline))

    assert response.status_code == "WAITING_FOR_SOURCE"
    assert response.created_count == 0
    assert centerline_count == 0
