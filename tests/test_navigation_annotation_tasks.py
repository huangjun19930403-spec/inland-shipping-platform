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
    NavigationChannelCenterline,
    NavigationGraphEdge,
    NavigationGraphNode,
    NavigationGraphVersion,
    NavigationRouteQualityIssue,
    NavigationRouteRequest,
    NavigationRouteResult,
)
from app.models.address import NavigationChannel
from app.models.base import Base
from app.modules.navigation.annotation_service import NavigationAnnotationTaskService
from app.modules.navigation.schemas import NavigationAnnotationTaskResolveRequest


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
                        "task_type_code": "GRAPH_QUALITY_REVIEW",
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


def test_navigation_annotation_task_api_is_registered() -> None:
    paths = {getattr(route, "path", None) for route in api_router.routes}

    assert "/navigation/annotation-tasks" in paths
    assert "/navigation/annotation-tasks/from-route-result/{route_result_id}" in paths
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
    assert task.task_type_code == "CONSTRAINT_DATA_REVIEW"
    assert task.target_type_code == "ROUTE_QUALITY_ISSUE"
    assert task.channel_id == 1
    assert task.graph_version_id == 1
    assert task.suggestion_json["publish_allowed"] is False


@pytest.mark.asyncio
async def test_create_tasks_from_graph_validation_and_edge_quality(session_maker) -> None:
    async with session_maker() as session:
        await _seed_graph(session)

        response = await NavigationAnnotationTaskService(session).create_from_graph_version(1, created_by=11)
        rows = list((await session.execute(select(NavigationAnnotationTask).order_by(NavigationAnnotationTask.id))).scalars())

    assert response.source_type_code == "GRAPH_VALIDATION"
    assert response.created_count >= 2
    assert {"GRAPH_QUALITY_REVIEW", "CONSTRAINT_DATA_REVIEW"} <= {row.task_type_code for row in rows}
    assert any(row.target_type_code == "GRAPH_EDGE" and row.target_id == 1 for row in rows)
    assert all(row.suggestion_json["publish_allowed"] is False for row in rows)


@pytest.mark.asyncio
async def test_low_confidence_centerline_generates_review_task(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        session.add(
            NavigationChannelCenterline(
                id=1,
                channel_id=1,
                centerline_code="CL-REVIEW",
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
    assert task.task_type_code == "CENTERLINE_REVIEW"
    assert task.target_type_code == "CENTERLINE"
    assert task.target_id == 1
    assert "centerline version" in " ".join(task.suggestion_json["next_actions"]).lower()


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
                suggestion_json={"operator_note": "已生成新中心线版本，待后续审核发布"},
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
