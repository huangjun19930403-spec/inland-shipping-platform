from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.models import NavigationGeometryDraft
from app.models.address import NavigationChannel
from app.models.base import Base
from app.modules.navigation.schemas import (
    NavigationBoundaryDraftOperationRequest,
    NavigationGeometryDraftCreateRequest,
)
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


def _multipolygon() -> dict:
    return {
        "type": "MultiPolygon",
        "coordinates": [
            _polygon()["coordinates"],
            _polygon(120.30, 31.00, 120.36, 31.04)["coordinates"],
        ],
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


async def _create_boundary_draft(session: AsyncSession, geometry_json: dict | None = None):
    service = NavigationWorkbenchService(session)
    return await service.create_geometry_draft(
        NavigationGeometryDraftCreateRequest(
            draft_type_code="BOUNDARY",
            draft_name="边界修复草稿",
            channel_id=1,
            geometry_json=geometry_json or _multipolygon(),
            source_type_code="BOUNDARY_CANDIDATE",
        ),
        created_by=7,
    )


@pytest.mark.asyncio
async def test_boundary_ops_delete_part_revalidates(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        draft = await _create_boundary_draft(session)

        response = await NavigationWorkbenchService(session).apply_boundary_draft_operation(
            draft.id,
            NavigationBoundaryDraftOperationRequest(operation_code="DELETE_PART", part_index=1),
        )
        row = await session.get(NavigationGeometryDraft, draft.id)

    assert response.draft.geometry_json["type"] == "Polygon"
    assert response.validation.issue_count >= 0
    assert row.source_trace_json["boundary_operation_history"][-1]["operation_code"] == "DELETE_PART"


@pytest.mark.asyncio
async def test_boundary_ops_keep_only_part_revalidates(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        draft = await _create_boundary_draft(session)

        response = await NavigationWorkbenchService(session).apply_boundary_draft_operation(
            draft.id,
            NavigationBoundaryDraftOperationRequest(operation_code="KEEP_ONLY_PART", part_index=0),
        )

    assert response.draft.geometry_json["type"] == "Polygon"
    assert response.validation.area_m2 is not None
    assert "点数" in response.message


@pytest.mark.asyncio
async def test_boundary_ops_union_patch_and_subtract_patch_revalidate(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        draft = await _create_boundary_draft(session, _polygon())
        service = NavigationWorkbenchService(session)

        union_response = await service.apply_boundary_draft_operation(
            draft.id,
            NavigationBoundaryDraftOperationRequest(
                operation_code="UNION_PATCH",
                operation_geometry_json=_polygon(120.22, 31.00, 120.32, 31.08),
            ),
        )
        subtract_response = await service.apply_boundary_draft_operation(
            draft.id,
            NavigationBoundaryDraftOperationRequest(
                operation_code="SUBTRACT_PATCH",
                operation_geometry_json=_polygon(120.30, 31.02, 120.32, 31.04),
            ),
        )
        row = await session.get(NavigationGeometryDraft, draft.id)

    assert union_response.validation.area_m2 is not None
    assert subtract_response.validation.area_m2 is not None
    assert [item["operation_code"] for item in row.source_trace_json["boundary_operation_history"][-2:]] == [
        "UNION_PATCH",
        "SUBTRACT_PATCH",
    ]


@pytest.mark.asyncio
async def test_boundary_ops_clean_small_parts_revalidates(session_maker) -> None:
    geometry = {
        "type": "MultiPolygon",
        "coordinates": [
            _polygon()["coordinates"],
            _polygon(121.0, 32.0, 121.00001, 32.00001)["coordinates"],
        ],
    }
    async with session_maker() as session:
        await _seed_channel(session)
        draft = await _create_boundary_draft(session, geometry)

        response = await NavigationWorkbenchService(session).apply_boundary_draft_operation(
            draft.id,
            NavigationBoundaryDraftOperationRequest(
                operation_code="CLEAN_SMALL_PARTS",
                options={"min_area_m2": 1000},
            ),
        )

    assert response.draft.geometry_json["type"] == "Polygon"
    assert "已清理 1 个小碎面" in response.message
    assert response.validation.area_m2 is not None


@pytest.mark.asyncio
async def test_boundary_ops_simplify_revalidates_and_reports_point_change(session_maker) -> None:
    detailed = {
        "type": "Polygon",
        "coordinates": [[
            [119.98, 30.98],
            [120.02, 30.9802],
            [120.08, 30.98],
            [120.14, 30.9802],
            [120.24, 30.98],
            [120.24, 31.12],
            [120.12, 31.1202],
            [119.98, 31.12],
            [119.98, 30.98],
        ]],
    }
    async with session_maker() as session:
        await _seed_channel(session)
        draft = await _create_boundary_draft(session, detailed)

        response = await NavigationWorkbenchService(session).apply_boundary_draft_operation(
            draft.id,
            NavigationBoundaryDraftOperationRequest(
                operation_code="SIMPLIFY",
                options={"tolerance_degree": 0.0005, "preserve_topology": True},
            ),
        )

    assert response.validation.area_m2 is not None
    assert "点数" in response.message
    assert response.draft.source_trace_json["boundary_operation_history"][-1]["operation_code"] == "SIMPLIFY"


@pytest.mark.asyncio
async def test_boundary_ops_invalid_operation_returns_explicit_error_code(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        draft = await _create_boundary_draft(session)

        with pytest.raises(Exception) as exc_info:
            await NavigationWorkbenchService(session).apply_boundary_draft_operation(
                draft.id,
                NavigationBoundaryDraftOperationRequest(operation_code="UNKNOWN_OP"),
            )

    assert exc_info.value.code == "BOUNDARY_OP_INVALID_OPERATION"
    assert exc_info.value.detail["error_code"] == "BOUNDARY_OP_INVALID_OPERATION"


@pytest.mark.asyncio
async def test_boundary_ops_empty_result_returns_explicit_error_code(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        draft = await _create_boundary_draft(session, _polygon())

        with pytest.raises(Exception) as exc_info:
            await NavigationWorkbenchService(session).apply_boundary_draft_operation(
                draft.id,
                NavigationBoundaryDraftOperationRequest(
                    operation_code="SUBTRACT_PATCH",
                    operation_geometry_json=_polygon(),
                ),
            )

    assert exc_info.value.code == "BOUNDARY_OP_EMPTY_RESULT"
    assert exc_info.value.detail["error_code"] == "BOUNDARY_OP_EMPTY_RESULT"


@pytest.mark.asyncio
async def test_boundary_ops_rejects_non_boundary_draft(session_maker) -> None:
    async with session_maker() as session:
        await _seed_channel(session)
        draft = await NavigationWorkbenchService(session).create_geometry_draft(
            NavigationGeometryDraftCreateRequest(
                draft_type_code="CENTERLINE",
                draft_name="中心线草稿",
                channel_id=1,
                geometry_json={"type": "LineString", "coordinates": [[120.0, 31.0], [120.1, 31.1]]},
                source_type_code="MAP_EDIT",
            ),
            created_by=7,
        )

        with pytest.raises(Exception) as exc_info:
            await NavigationWorkbenchService(session).apply_boundary_draft_operation(
                draft.id,
                NavigationBoundaryDraftOperationRequest(operation_code="DELETE_PART", part_index=0),
            )

    assert exc_info.value.code == "BOUNDARY_OP_NOT_BOUNDARY_DRAFT"
