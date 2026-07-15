from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import BigInteger

import app.models  # noqa: F401
from app.api.v1 import api_router
from app.models import (
    NavigationAnnotationTask,
    NavigationChannelBoundary,
    NavigationChannelCenterline,
    NavigationGraphEdge,
    NavigationGraphEdgeConstraint,
    NavigationGraphNode,
    NavigationGraphVersion,
    NavigationRouteQualityIssue,
    NavigationRouteRequest,
    NavigationRouteResult,
)
from app.models.address import NavigationChannel
from app.models.base import Base
from app.modules.navigation.annotation_service import NavigationAnnotationTaskService
from app.modules.navigation.schemas import NavigationAnnotationTaskResolveRequest, NavigationGraphEdgeConstraintRepairRequest


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


def _line(*points: tuple[float, float]) -> dict:
    return {"type": "LineString", "coordinates": [[lng, lat] for lng, lat in points]}


async def _seed_channel(session: AsyncSession) -> None:
    session.add(
        NavigationChannel(
            id=1,
            channel_code="ANN-CHANNEL",
            channel_name="标注测试航道",
            channel_type_code="CANAL",
            planning_level_code="REGIONAL_IMPORTANT",
            source_version="TEST",
            is_enabled=True,
        )
    )
    await session.flush()


async def _seed_graph(session: AsyncSession) -> None:
    await _seed_channel(session)
    session.add(
        NavigationGraphVersion(
            id=1,
            version_code="ANN-GRAPH",
            version_name="Annotation graph",
            scope_code="TEST",
            status_code="READY",
            is_active=True,
            node_count=2,
            edge_count=1,
            channel_count=1,
            validation_report_json={
                "annotation_task_candidates": [
                    {
                        "task_type_code": "GRAPH_QUALITY_REPAIR",
                        "target_type_code": "GRAPH_VERSION",
                        "target_id": 1,
                        "issue_code": "GRAPH_DISCONNECTED",
                        "issue_summary": "Graph has disconnected components",
                        "priority_code": "HIGH",
                    }
                ]
            },
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
                latitude=31.0,
                geometry_json={"type": "Point", "coordinates": [120.1, 31.0]},
                is_enabled=True,
                quality_code="READY",
                source_type_code="CENTERLINE_VERTEX",
            ),
        ]
    )
    session.add(
        NavigationGraphEdge(
            id=1,
            graph_version_id=1,
            edge_code="E1",
            from_node_id=1,
            to_node_id=2,
            channel_id=1,
            geometry_json=_line((120.0, 31.0), (120.1, 31.0)),
            length_km=11.1,
            direction_code="BIDIRECTIONAL",
            routing_enabled=True,
            quality_code="LOW_CONFIDENCE",
            source_type_code="OSM_WATERWAY",
            confidence_score=45,
            unknown_constraint_flag=True,
        )
    )
    await session.commit()


async def _seed_route_issue(session: AsyncSession) -> None:
    await _seed_graph(session)
    session.add(
        NavigationRouteRequest(
            id=1,
            request_no="ANN-REQ",
            origin_lng=120.0,
            origin_lat=31.0,
            destination_lng=120.1,
            destination_lat=31.0,
            routing_preference_code="RECOMMENDED",
            graph_version_id=1,
            status_code="SUCCESS",
        )
    )
    session.add(
        NavigationRouteResult(
            id=1,
            request_id=1,
            result_no=1,
            result_type_code="RECOMMENDED",
            status_code="READY_WITH_WARNING",
            geometry_json=_line((120.0, 31.0), (120.1, 31.0)),
            edge_ids=[1],
            channel_ids=[1],
            quality_score=86,
            quality_code="READY_WITH_WARNING",
        )
    )
    session.add(
        NavigationRouteQualityIssue(
            id=1,
            route_result_id=1,
            issue_type_code="UNKNOWN_CONSTRAINT_DATA",
            severity_code="WARNING",
            geometry_json={"type": "Point", "coordinates": [120.05, 31.0]},
            message="Constraint data is incomplete",
            related_edge_id=1,
        )
    )
    await session.commit()


async def _seed_boundary_route_issue(session: AsyncSession) -> None:
    await _seed_graph(session)
    session.add(
        NavigationRouteRequest(
            id=2,
            request_no="ANN-BOUNDARY-REQ",
            origin_lng=120.0,
            origin_lat=31.0,
            destination_lng=120.1,
            destination_lat=31.0,
            routing_preference_code="RECOMMENDED",
            graph_version_id=1,
            status_code="FAILED",
        )
    )
    route_line = _line((120.0, 31.0), (120.05, 31.01), (120.1, 31.0))
    session.add(
        NavigationRouteResult(
            id=2,
            request_id=2,
            result_no=1,
            result_type_code="RECOMMENDED",
            status_code="FAILED",
            geometry_json=route_line,
            edge_ids=[1],
            channel_ids=[1],
            quality_score=0,
            quality_code="FAILED",
            provider_code="NAVIGATION_ENGINE",
        )
    )
    session.add(
        NavigationRouteQualityIssue(
            id=2,
            route_result_id=2,
            issue_type_code="PATH_OUT_OF_CHANNEL_BOUNDARY",
            severity_code="ERROR",
            geometry_json=route_line,
            message="Route channel-boundary coverage is too low: 40.0%",
        )
    )
    await session.commit()


async def _seed_duplicate_boundary_route_issue(session: AsyncSession) -> None:
    route_line = _line((120.0, 31.0), (120.05, 31.01), (120.1, 31.0))
    session.add(
        NavigationRouteRequest(
            id=3,
            request_no="ANN-BOUNDARY-REQ-2",
            origin_lng=120.0,
            origin_lat=31.0,
            destination_lng=120.1,
            destination_lat=31.0,
            routing_preference_code="RECOMMENDED",
            graph_version_id=1,
            status_code="FAILED",
        )
    )
    session.add(
        NavigationRouteResult(
            id=3,
            request_id=3,
            result_no=1,
            result_type_code="RECOMMENDED",
            status_code="FAILED",
            geometry_json=route_line,
            edge_ids=[1],
            channel_ids=[1],
            quality_score=0,
            quality_code="FAILED",
            provider_code="NAVIGATION_ENGINE",
        )
    )
    session.add(
        NavigationRouteQualityIssue(
            id=3,
            route_result_id=3,
            issue_type_code="PATH_OUT_OF_CHANNEL_BOUNDARY",
            severity_code="ERROR",
            geometry_json=route_line,
            message="Route channel-boundary coverage is too low: 40.0%",
        )
    )
    await session.commit()


async def _seed_non_repair_route_warning(session: AsyncSession) -> None:
    await _seed_graph(session)
    route_line = _line((120.0, 31.0), (120.00001, 31.0), (120.1, 31.0))
    session.add(
        NavigationRouteRequest(
            id=4,
            request_no="ANN-WARNING-REQ",
            origin_lng=120.0,
            origin_lat=31.0,
            destination_lng=120.1,
            destination_lat=31.0,
            routing_preference_code="RECOMMENDED",
            graph_version_id=1,
            status_code="SUCCESS",
        )
    )
    session.add(
        NavigationRouteResult(
            id=4,
            request_id=4,
            result_no=1,
            result_type_code="RECOMMENDED",
            status_code="READY_WITH_WARNING",
            geometry_json=route_line,
            edge_ids=[1],
            channel_ids=[1],
            quality_score=80,
            quality_code="READY_WITH_WARNING",
            provider_code="NAVIGATION_ENGINE",
        )
    )
    session.add(
        NavigationRouteQualityIssue(
            id=4,
            route_result_id=4,
            issue_type_code="ROUTE_TOO_SHORT_SEGMENT",
            severity_code="WARNING",
            geometry_json={"type": "Point", "coordinates": [120.00001, 31.0]},
            message="Route contains a segment shorter than 5m",
        )
    )
    await session.commit()


async def _seed_boundary_trust_route_issue(session: AsyncSession) -> None:
    await _seed_graph(session)
    route_line = _line((120.0, 31.0), (120.04, 31.01), (120.1, 31.0))
    session.add(
        NavigationRouteRequest(
            id=7,
            request_no="ANN-BOUNDARY-TRUST-REQ",
            origin_lng=120.0,
            origin_lat=31.0,
            destination_lng=120.1,
            destination_lat=31.0,
            routing_preference_code="RECOMMENDED",
            graph_version_id=1,
            status_code="SUCCESS",
        )
    )
    session.add(
        NavigationRouteResult(
            id=7,
            request_id=7,
            result_no=1,
            result_type_code="RECOMMENDED",
            status_code="SUCCESS",
            geometry_json=route_line,
            edge_ids=[],
            channel_ids=[1],
            quality_score=85,
            quality_code="READY_WITH_WARNING",
            provider_code="NAVIGATION_ENGINE",
        )
    )
    session.add(
        NavigationRouteQualityIssue(
            id=7,
            route_result_id=7,
            issue_type_code="CHANNEL_BOUNDARY_TRUST_NEEDS_REVIEW",
            severity_code="WARNING",
            geometry_json=None,
            message="当前路径经过的航道边界完整性未达高置信标准。",
        )
    )
    await session.commit()


async def _seed_duplicate_origin_snap_route_issues(session: AsyncSession) -> None:
    await _seed_graph(session)
    rows = [
        (
            5,
            "ANN-SNAP-REQ-1",
            120.0,
            31.0,
            120.1,
            31.0,
            "Origin endpoint is too far from graph: 80000.0m",
        ),
        (
            6,
            "ANN-SNAP-REQ-2",
            120.0,
            31.0,
            120.2,
            31.0,
            "Origin endpoint is too far from graph: 80000.0m",
        ),
    ]
    for route_id, request_no, origin_lng, origin_lat, dest_lng, dest_lat, message in rows:
        session.add(
            NavigationRouteRequest(
                id=route_id,
                request_no=request_no,
                origin_lng=origin_lng,
                origin_lat=origin_lat,
                destination_lng=dest_lng,
                destination_lat=dest_lat,
                routing_preference_code="RECOMMENDED",
                graph_version_id=1,
                status_code="FAILED",
            )
        )
        session.add(
            NavigationRouteResult(
                id=route_id,
                request_id=route_id,
                result_no=1,
                result_type_code="RECOMMENDED",
                status_code="FAILED",
                geometry_json=None,
                edge_ids=[],
                channel_ids=[],
                quality_score=0,
                quality_code="FAILED",
                provider_code="NAVIGATION_ENGINE",
            )
        )
        session.add(
            NavigationRouteQualityIssue(
                id=route_id,
                route_result_id=route_id,
                issue_type_code="ORIGIN_TOO_FAR_FROM_GRAPH",
                severity_code="ERROR",
                geometry_json=None,
                message=message,
            )
        )
    await session.commit()


def test_navigation_annotation_task_api_is_registered() -> None:
    paths = {getattr(route, "path", None) for route in api_router.routes}

    assert "/navigation/annotation-tasks" in paths
    assert "/navigation/annotation-tasks/from-route-result/{route_result_id}" in paths
    assert "/navigation/annotation-tasks/from-boundary-integrity" in paths
    assert "/navigation/annotation-tasks/{task_id}/resolve" in paths


@pytest.mark.asyncio
async def test_create_tasks_from_route_quality_issue_links_issue_and_is_idempotent(session_maker) -> None:
    async with session_maker() as session:
        await _seed_route_issue(session)
        service = NavigationAnnotationTaskService(session)

        first = await service.create_from_route_result(1, created_by=7)
        second = await service.create_from_route_result(1, created_by=7)
        issue = await session.get(NavigationRouteQualityIssue, 1)
        task = await session.get(NavigationAnnotationTask, first.task_ids[0])

    assert first.created_count == 1
    assert second.existing_count == 1
    assert issue is not None
    assert issue.related_annotation_task_id == first.task_ids[0]
    assert task is not None
    assert task.task_type_code == "CONSTRAINT_DATA_REPAIR"
    assert task.target_type_code == "ROUTE_QUALITY_ISSUE"
    assert task.channel_id == 1
    assert task.graph_version_id == 1
    assert task.suggestion_json["publish_allowed"] is False


@pytest.mark.asyncio
async def test_route_out_of_boundary_creates_seed_boundary_expansion_task(session_maker) -> None:
    async with session_maker() as session:
        await _seed_boundary_route_issue(session)

        response = await NavigationAnnotationTaskService(session).create_from_route_result(2, created_by=7)
        issue = await session.get(NavigationRouteQualityIssue, 2)
        task = await session.get(NavigationAnnotationTask, response.task_ids[0])

    assert response.created_count == 1
    assert issue is not None
    assert issue.related_annotation_task_id == response.task_ids[0]
    assert task is not None
    assert task.task_type_code == "SEED_BOUNDARY_REPAIR"
    assert task.channel_id == 1
    assert task.priority_code == "HIGH"
    assert task.suggestion_json["candidate_operation_code"] == "UNION_PATCH"
    assert task.suggestion_json["candidate_boundary_patch_geometry_json"]["type"] == "Polygon"
    assert task.suggestion_json["publish_allowed"] is False


@pytest.mark.asyncio
async def test_route_snap_issue_creates_seed_access_repair_suggestion(session_maker) -> None:
    async with session_maker() as session:
        await _seed_duplicate_origin_snap_route_issues(session)

        response = await NavigationAnnotationTaskService(session).create_from_route_result(5, created_by=7)
        issue = await session.get(NavigationRouteQualityIssue, 5)
        task = await session.get(NavigationAnnotationTask, response.task_ids[0])

    assert response.created_count == 1
    assert issue is not None
    assert issue.related_annotation_task_id == response.task_ids[0]
    assert task is not None
    assert task.task_type_code == "SNAP_REPAIR"
    assert task.priority_code == "HIGH"
    assert task.geometry_json == {"type": "Point", "coordinates": [120.0, 31.0]}
    assert task.suggestion_json["repair_strategy_code"] == "ENDPOINT_SNAP_AND_SEED_ACCESS_REPAIR"
    assert task.suggestion_json["candidate_operation_code"] == "CREATE_ACCESS_CENTERLINE_AND_REBUILD_GRAPH"
    assert task.suggestion_json["publish_allowed"] is False
    assert any("不要通过放大吸附阈值" in item for item in task.suggestion_json["guardrails"])


@pytest.mark.asyncio
async def test_duplicate_route_boundary_issue_reuses_open_repair_task(session_maker) -> None:
    async with session_maker() as session:
        await _seed_boundary_route_issue(session)
        await _seed_duplicate_boundary_route_issue(session)
        service = NavigationAnnotationTaskService(session)

        first = await service.create_from_route_result(2, created_by=7)
        second = await service.create_from_route_result(3, created_by=7)
        duplicate_issue = await session.get(NavigationRouteQualityIssue, 3)

    assert first.created_count == 1
    assert second.created_count == 0
    assert second.existing_count == 1
    assert duplicate_issue is not None
    assert duplicate_issue.related_annotation_task_id == first.task_ids[0]


@pytest.mark.asyncio
async def test_route_warning_without_repair_code_does_not_create_task(session_maker) -> None:
    async with session_maker() as session:
        await _seed_non_repair_route_warning(session)

        response = await NavigationAnnotationTaskService(session).create_from_route_result(4, created_by=7)

    assert response.created_count == 0
    assert response.existing_count == 0
    assert response.task_ids == []


@pytest.mark.asyncio
async def test_boundary_trust_route_issue_creates_seed_boundary_task(session_maker) -> None:
    async with session_maker() as session:
        await _seed_boundary_trust_route_issue(session)

        response = await NavigationAnnotationTaskService(session).create_from_route_result(7, created_by=7)
        issue = await session.get(NavigationRouteQualityIssue, 7)
        task = await session.get(NavigationAnnotationTask, response.task_ids[0])

    assert response.created_count == 1
    assert issue is not None
    assert issue.related_annotation_task_id == response.task_ids[0]
    assert task is not None
    assert task.task_type_code == "SEED_BOUNDARY_REPAIR"
    assert task.channel_id == 1
    assert task.priority_code == "HIGH"
    assert task.suggestion_json["publish_allowed"] is False


@pytest.mark.asyncio
async def test_duplicate_origin_snap_issue_reuses_endpoint_repair_task(session_maker) -> None:
    async with session_maker() as session:
        await _seed_duplicate_origin_snap_route_issues(session)
        service = NavigationAnnotationTaskService(session)

        first = await service.create_from_route_result(5, created_by=7)
        second = await service.create_from_route_result(6, created_by=7)
        task = await session.get(NavigationAnnotationTask, first.task_ids[0])
        duplicate_issue = await session.get(NavigationRouteQualityIssue, 6)

    assert first.created_count == 1
    assert second.created_count == 0
    assert second.existing_count == 1
    assert duplicate_issue is not None
    assert duplicate_issue.related_annotation_task_id == first.task_ids[0]
    assert task is not None
    assert task.geometry_json == {"type": "Point", "coordinates": [120.0, 31.0]}


@pytest.mark.asyncio
async def test_create_tasks_from_graph_validation_and_edge_quality(session_maker) -> None:
    async with session_maker() as session:
        await _seed_graph(session)

        response = await NavigationAnnotationTaskService(session).create_from_graph_version(1, created_by=11)
        rows = list((await session.execute(select(NavigationAnnotationTask).order_by(NavigationAnnotationTask.id))).scalars())

    assert response.source_type_code == "GRAPH_VALIDATION"
    assert response.created_count >= 2
    assert {"GRAPH_QUALITY_REPAIR", "CONSTRAINT_DATA_REPAIR"} <= {row.task_type_code for row in rows}
    assert any(row.target_type_code == "GRAPH_EDGE" and row.target_id == 1 for row in rows)
    assert all(row.suggestion_json["publish_allowed"] is False for row in rows)


@pytest.mark.asyncio
async def test_low_confidence_centerline_generates_repair_task(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        session.add(
            NavigationChannelCenterline(
                id=1,
                channel_id=1,
                centerline_code="CL-REPAIR",
                centerline_name="待复核中心线",
                geometry_json=_line((120.0, 31.0), (120.1, 31.0)),
                source_type_code="OSM_WATERWAY",
                quality_code="LOW_CONFIDENCE",
                review_status_code="NEED_REVIEW",
                confidence_score=40,
                is_current=True,
            )
        )
        await session.commit()

        response = await NavigationAnnotationTaskService(session).create_from_centerline_quality(created_by=9)
        task = await session.get(NavigationAnnotationTask, response.task_ids[0])

    assert response.created_count == 1
    assert task is not None
    assert task.task_type_code == "CENTERLINE_REPAIR"
    assert task.target_type_code == "CENTERLINE"
    assert task.target_id == 1
    assert "中心线版本" in " ".join(task.suggestion_json["next_actions"])


@pytest.mark.asyncio
async def test_boundary_integrity_audit_generates_boundary_repair_task(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        session.add(
            NavigationChannelBoundary(
                id=1,
                channel_id=1,
                geometry_json={
                    "type": "Polygon",
                    "coordinates": [[
                        [120.0, 31.0],
                        [120.1, 31.0],
                        [120.1, 31.1],
                        [120.0, 31.1],
                        [120.0, 31.0],
                    ]],
                },
                ring_count=1,
                point_count=5,
                geometry_status_code="AVAILABLE",
                boundary_quality_code="REVIEW",
                connectivity_status_code="UNKNOWN",
                repair_status_code="REVIEW_REQUIRED",
                coverage_policy_code="CHANNEL_CORRIDOR_ENVELOPE",
                source_trace_json={
                    "boundary_integrity_audit": {
                        "trust_code": "NEEDS_REVIEW",
                        "issue_codes": [
                            "SOURCE_GEOMETRY_FRAGMENTED",
                            "BOUNDARY_NOT_INDEPENDENTLY_BASEMAP_VERIFIED",
                            "NAVIGATION_TECHNICAL_GRADE_UNKNOWN",
                        ],
                        "component_count": 3,
                    }
                },
                is_current=True,
            )
        )
        await session.commit()

        response = await NavigationAnnotationTaskService(session).create_from_boundary_integrity(created_by=9)
        task = await session.get(NavigationAnnotationTask, response.task_ids[0])

    assert response.created_count == 1
    assert response.source_type_code == "BOUNDARY_INTEGRITY"
    assert task is not None
    assert task.task_type_code == "SEED_BOUNDARY_REPAIR"
    assert task.target_type_code == "CHANNEL_BOUNDARY"
    assert task.target_id == 1
    assert task.suggestion_json["repair_strategy_code"] == "REAL_WATERWAY_BOUNDARY_REPAIR"
    assert "SOURCE_GEOMETRY_FRAGMENTED" in task.suggestion_json["issue_codes"]
    assert task.suggestion_json["publish_allowed"] is False


@pytest.mark.asyncio
async def test_suggestion_and_resolve_record_traceable_target_without_publishing_graph(session_maker) -> None:
    async with session_maker() as session:
        await _seed_graph(session)
        service = NavigationAnnotationTaskService(session)
        created = await service.create_from_graph_version(1, created_by=3)
        task_id = created.task_ids[0]

        suggestion = await service.generate_suggestion(task_id)
        resolved = await service.resolve_task(
            task_id,
            NavigationAnnotationTaskResolveRequest(
                resolution_type_code="CENTERLINE_VERSION_CREATED",
                resolution_target_type_code="CENTERLINE",
                resolution_target_id=100,
                suggestion_json={"operator_note": "已生成新中心线版本，待后续发布"},
            ),
            reviewed_by=5,
        )
        edge = await session.get(NavigationGraphEdge, 1)

    assert suggestion.suggestion_json["publish_allowed"] is False
    assert resolved.status_code == "RESOLVED"
    assert resolved.resolution_target_type_code == "CENTERLINE"
    assert resolved.resolution_target_id == 100
    assert edge is not None
    assert edge.quality_code == "LOW_CONFIDENCE"


@pytest.mark.asyncio
async def test_resolve_constraint_annotation_repairs_graph_edge_and_records_evidence(session_maker) -> None:
    async with session_maker() as session:
        await _seed_graph(session)
        service = NavigationAnnotationTaskService(session)
        created = await service.create_from_graph_version(1, created_by=3)
        rows = list((await session.execute(select(NavigationAnnotationTask).order_by(NavigationAnnotationTask.id))).scalars())
        task = next(row for row in rows if row.task_type_code == "CONSTRAINT_DATA_REPAIR")

        resolved = await service.resolve_task(
            task.id,
            NavigationAnnotationTaskResolveRequest(
                resolution_type_code="MANUAL_CONFIRMED",
                status_code="RESOLVED",
                constraint_repair=NavigationGraphEdgeConstraintRepairRequest(
                    min_depth_m=7.2,
                    min_width_m=160,
                    max_allowed_draft_m=5.8,
                    max_allowed_tonnage=3000,
                    warning_message="资料来自人工核验",
                ),
                source_evidence_json={
                    "source_name": "测试航道通航资料",
                    "source_ref": "ANN-EDGE-EVIDENCE",
                    "operator_note": "已核验该图边约束",
                },
            ),
            reviewed_by=5,
        )
        edge = await session.get(NavigationGraphEdge, 1)
        constraints = list(
            (
                await session.execute(
                    select(NavigationGraphEdgeConstraint).where(NavigationGraphEdgeConstraint.edge_id == 1)
                )
            ).scalars()
        )
        open_tasks = await service.list_tasks(
            status_code="OPEN",
            task_type_code="CONSTRAINT_DATA_REPAIR",
            channel_id=1,
        )

    assert created.created_count >= 1
    assert resolved.status_code == "RESOLVED"
    assert resolved.resolution_type_code == "CONSTRAINT_CREATED"
    assert resolved.resolution_target_type_code == "GRAPH_EDGE"
    assert resolved.resolution_target_id == 1
    assert resolved.suggestion_json["manual_resolution"]["source_evidence_json"]["source_ref"] == "ANN-EDGE-EVIDENCE"
    assert resolved.suggestion_json["manual_resolution"]["constraint_repair_result"]["unknown_constraint_flag"] is False
    assert edge is not None
    assert edge.unknown_constraint_flag is False
    assert float(edge.max_allowed_draft_m or 0) == 5.8
    assert len(constraints) == 1
    assert constraints[0].data_completeness_code == "COMPLETE"
    assert constraints[0].source_trace_json["source_evidence_json"]["annotation_task_id"] == task.id
    assert constraints[0].source_trace_json["source_evidence_json"]["source_ref"] == "ANN-EDGE-EVIDENCE"
    assert open_tasks.total == 0
