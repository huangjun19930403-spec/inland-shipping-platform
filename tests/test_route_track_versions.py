from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import BigInteger

import app.models  # noqa: F401
from app.integrations.http.route_geometry_types import RouteGeometryResult
from app.models.analysis import FactVesselRouteSegmentDaily
from app.models.address import Region
from app.models.base import Base
from app.models.route import (
    ShippingRoute,
    ShippingRoutePlan,
    ShippingRoutePlanPoint,
    ShippingRoutePlanSegment,
    ShippingRoutePlanSegmentResult,
    ShippingRoutePlanTrackVersion,
    ShippingRoutePlanTrackVersionSegment,
)
from app.models.vessel import (
    VesselCandidateAnalysis,
    VesselCandidateAnalysisAnnotation,
    VesselCandidateAnalysisItem,
    VesselNavigationConstraintEvidence,
    VesselRouteSegmentMatchSample,
    VesselRouteSegmentObservationItem,
)
from app.modules.route.schemas import (
    RoutePlanPointUpsertItem,
    RoutePlanStructureReplaceRequest,
    RouteTrackGenerateRequest,
    RouteTrackVersionSaveRequest,
    RouteTrackVersionSegmentSaveItem,
)
from app.modules.route.service import ShippingRoutePlanStructureService, ShippingRouteService


@compiles(BigInteger, "sqlite")
def _compile_bigint_sqlite(element, compiler, **kw) -> str:
    _ = element, compiler, kw
    return "INTEGER"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


async def _seed_plan(session: AsyncSession) -> int:
    session.add_all(
        [
            Region(id=1, code="R1", name="起点区域", region_type_code="PORT_CLUSTER", audit_status="APPROVED"),
            Region(id=2, code="R2", name="终点区域", region_type_code="PORT_CLUSTER", audit_status="APPROVED"),
            ShippingRoute(
                id=10,
                code="RT-10",
                name="测试航线",
                origin_endpoint_type_code="REGION",
                origin_region_id=1,
                destination_endpoint_type_code="REGION",
                destination_region_id=2,
                transport_org_type_code="WATERWAY",
                audit_status="APPROVED",
            ),
            ShippingRoutePlan(
                id=11,
                route_id=10,
                plan_code="RP-11",
                plan_name="默认方案",
                plan_type_code="STANDARD",
                is_default=True,
                status_code="ACTIVE",
                display_order=1,
            ),
            ShippingRoutePlanPoint(
                id=12,
                plan_id=11,
                point_order=1,
                point_type_code="MANUAL_POINT",
                manual_name="A",
                longitude=Decimal("120.00000000"),
                latitude=Decimal("31.00000000"),
                display_name="A",
                transport_mode_after_code="WATER",
            ),
            ShippingRoutePlanPoint(
                id=13,
                plan_id=11,
                point_order=2,
                point_type_code="MANUAL_POINT",
                manual_name="B",
                longitude=Decimal("120.50000000"),
                latitude=Decimal("31.20000000"),
                display_name="B",
                transport_mode_after_code="WATER",
            ),
            ShippingRoutePlanPoint(
                id=14,
                plan_id=11,
                point_order=3,
                point_type_code="MANUAL_POINT",
                manual_name="C",
                longitude=Decimal("121.00000000"),
                latitude=Decimal("31.50000000"),
                display_name="C",
            ),
            ShippingRoutePlanSegment(
                id=15,
                plan_id=11,
                segment_no=1,
                start_plan_point_id=12,
                end_plan_point_id=13,
                transport_mode_code="WATER",
                generation_status_code="NOT_GENERATED",
            ),
            ShippingRoutePlanSegment(
                id=16,
                plan_id=11,
                segment_no=2,
                start_plan_point_id=13,
                end_plan_point_id=14,
                transport_mode_code="WATER",
                generation_status_code="NOT_GENERATED",
            ),
        ]
    )
    await session.commit()
    return 11


@pytest.mark.asyncio
async def test_generate_provider_version_does_not_replace_current_plan_version(session: AsyncSession) -> None:
    plan_id = await _seed_plan(session)
    service = ShippingRoutePlanStructureService(session)

    async def fake_provider(**kwargs):  # noqa: ANN003
        segment = kwargs["segment"]
        if segment.id == 15:
            coordinates = [[120.0, 31.0], [120.25, 31.15], [120.5, 31.2]]
        else:
            coordinates = [[120.5, 31.2], [120.8, 31.35], [121.0, 31.5]]
        return RouteGeometryResult(
            geometry={"type": "LineString", "coordinates": coordinates},
            source="hifleet",
            provider="HIFLEET",
            provider_trace_id=f"hf-{segment.id}",
            status="ready",
            distance_km=12.5,
            estimated_duration_hour=1.25,
        )

    service._call_geometry_provider = fake_provider  # type: ignore[method-assign]

    response = await service.generate_track_version(plan_id, RouteTrackGenerateRequest(provider_code="HIFLEET"))
    plan = await session.get(ShippingRoutePlan, plan_id)

    assert response.status == "READY"
    assert response.version is not None
    assert response.version.is_current is False
    assert response.version.segment_count == 2
    assert plan.current_track_version_id is None


@pytest.mark.asyncio
async def test_save_manual_track_version_sets_current_and_preserves_provider_version(session: AsyncSession) -> None:
    plan_id = await _seed_plan(session)
    service = ShippingRoutePlanStructureService(session)

    async def fake_provider(**kwargs):  # noqa: ANN003
        segment = kwargs["segment"]
        coordinates = (
            [[120.0, 31.0], [120.25, 31.12], [120.5, 31.2]]
            if segment.id == 15
            else [[120.5, 31.2], [120.75, 31.36], [121.0, 31.5]]
        )
        return RouteGeometryResult(
            geometry={"type": "LineString", "coordinates": coordinates},
            source="hifleet",
            provider="HIFLEET",
            provider_trace_id=f"hf-{segment.id}",
            status="ready",
        )

    service._call_geometry_provider = fake_provider  # type: ignore[method-assign]
    provider_response = await service.generate_track_version(plan_id, RouteTrackGenerateRequest(provider_code="HIFLEET"))
    provider_version = provider_response.version
    assert provider_version is not None

    saved = await service.save_track_version(
        plan_id,
        RouteTrackVersionSaveRequest(
            parent_version_id=provider_version.id,
            segments=[
                RouteTrackVersionSegmentSaveItem(
                    segment_id=item.segment_id,
                    geometry_json={
                        "type": "LineString",
                        "coordinates": item.geometry_json["coordinates"][:1] + [[120.35, 31.18]] + item.geometry_json["coordinates"][1:],
                    },
                    edit_status_code="EDITED",
                )
                for item in provider_version.segments
            ],
        ),
    )
    plan = await session.get(ShippingRoutePlan, plan_id)
    versions = await service.list_track_versions(plan_id)

    assert saved.source_type_code == "MANUAL"
    assert saved.is_current is True
    assert plan.current_track_version_id == saved.id
    assert len(versions) == 2
    assert any(item.id == provider_version.id and not item.is_current for item in versions)


@pytest.mark.asyncio
async def test_generate_provider_version_rejects_anchor_only_segments(session: AsyncSession) -> None:
    plan_id = await _seed_plan(session)
    service = ShippingRoutePlanStructureService(session)

    async def fake_provider(**kwargs):  # noqa: ANN003
        segment = kwargs["segment"]
        coordinates = (
            [[120.0, 31.0], [120.5, 31.2]]
            if segment.id == 15
            else [[120.5, 31.2], [121.0, 31.5]]
        )
        return RouteGeometryResult(
            geometry={"type": "LineString", "coordinates": coordinates},
            source="hifleet",
            provider="HIFLEET",
            provider_trace_id=f"hf-{segment.id}",
            status="ready",
        )

    service._call_geometry_provider = fake_provider  # type: ignore[method-assign]
    response = await service.generate_track_version(plan_id, RouteTrackGenerateRequest(provider_code="HIFLEET"))

    assert response.status == "FAILED"
    assert response.version is not None
    assert response.version.segment_count == 0
    assert "仅包含起终点" in (response.version.error_message or "")


@pytest.mark.asyncio
async def test_generate_provider_version_rejects_same_coordinate_segment_without_fallback(session: AsyncSession) -> None:
    plan_id = await _seed_plan(session)
    duplicate_point = await session.get(ShippingRoutePlanPoint, 13)
    extra_segment = await session.get(ShippingRoutePlanSegment, 16)
    assert duplicate_point is not None
    assert extra_segment is not None
    duplicate_point.longitude = Decimal("120.00000000")
    duplicate_point.latitude = Decimal("31.00000000")
    await session.delete(extra_segment)
    await session.commit()

    response = await ShippingRoutePlanStructureService(session).generate_track_version(
        plan_id,
        RouteTrackGenerateRequest(provider_code="HIFLEET"),
    )

    assert response.status == "FAILED"
    assert response.version is not None
    assert response.version.source_type_code == "HIFLEET"
    assert response.version.segment_count == 0
    assert response.version.summary_json.get("fallback_notes") == []
    assert "起终点坐标相同" in (response.version.error_message or "")


@pytest.mark.asyncio
async def test_delete_current_track_version_clears_plan_current_and_keeps_history(session: AsyncSession) -> None:
    plan_id = await _seed_plan(session)
    service = ShippingRoutePlanStructureService(session)

    async def fake_provider(**kwargs):  # noqa: ANN003
        segment = kwargs["segment"]
        coordinates = (
            [[120.0, 31.0], [120.25, 31.12], [120.5, 31.2]]
            if segment.id == 15
            else [[120.5, 31.2], [120.75, 31.36], [121.0, 31.5]]
        )
        return RouteGeometryResult(
            geometry={"type": "LineString", "coordinates": coordinates},
            source="hifleet",
            provider="HIFLEET",
            provider_trace_id=f"hf-{segment.id}",
            status="ready",
        )

    service._call_geometry_provider = fake_provider  # type: ignore[method-assign]
    provider_response = await service.generate_track_version(plan_id, RouteTrackGenerateRequest(provider_code="HIFLEET"))
    provider_version = provider_response.version
    assert provider_version is not None

    saved = await service.save_track_version(
        plan_id,
        RouteTrackVersionSaveRequest(
            parent_version_id=provider_version.id,
            segments=[
                RouteTrackVersionSegmentSaveItem(
                    segment_id=item.segment_id,
                    geometry_json=item.geometry_json,
                    edit_status_code="EDITED",
                )
                for item in provider_version.segments
            ],
        ),
    )
    await service.delete_track_version(plan_id, saved.id)
    plan = await session.get(ShippingRoutePlan, plan_id)
    versions = await service.list_track_versions(plan_id)

    assert plan.current_track_version_id is None
    assert [item.id for item in versions] == [provider_version.id]
    assert versions[0].is_current is False
    with pytest.raises(Exception, match="ShippingRoutePlanTrackVersion"):
        await service.get_track_version(plan_id, saved.id)


@pytest.mark.asyncio
async def test_delete_route_hard_deletes_plans_tracks_and_route_derivatives(session: AsyncSession) -> None:
    await _seed_plan(session)
    now = datetime.utcnow()
    plan = await session.get(ShippingRoutePlan, 11)
    assert plan is not None
    plan.current_track_version_id = 20
    session.add_all(
        [
            ShippingRoutePlanSegmentResult(
                id=17,
                segment_id=15,
                result_no=1,
                provider_type_code="HIFLEET",
                result_status_code="READY",
                is_selected=True,
                geometry_json={"type": "LineString", "coordinates": [[120.0, 31.0], [120.5, 31.2]]},
            ),
            ShippingRoutePlanTrackVersion(
                id=20,
                plan_id=11,
                version_no=1,
                source_type_code="HIFLEET",
                provider_type_code="HIFLEET",
                is_current=True,
                version_status_code="READY",
                point_count=3,
                segment_count=1,
                generated_at=now,
            ),
            ShippingRoutePlanTrackVersionSegment(
                id=21,
                version_id=20,
                segment_id=15,
                segment_no=1,
                geometry_json={"type": "LineString", "coordinates": [[120.0, 31.0], [120.5, 31.2]]},
                point_count=2,
            ),
            VesselRouteSegmentObservationItem(
                id=30,
                snapshot_id="snap-route-delete",
                route_id=10,
                plan_id=11,
                segment_id=15,
                segment_no=1,
                created_at=now,
            ),
            VesselRouteSegmentMatchSample(
                id=31,
                snapshot_id="snap-route-delete",
                segment_id=15,
                mmsi="412000001",
                created_at=now,
            ),
            FactVesselRouteSegmentDaily(
                id=32,
                stat_date=date.today(),
                route_id=10,
                plan_id=11,
                segment_id=15,
                generated_at=now,
            ),
            VesselNavigationConstraintEvidence(
                id=33,
                snapshot_id="snap-route-delete",
                context_type_code="ROUTE_PLAN",
                context_id=11,
                created_at=now,
            ),
            VesselNavigationConstraintEvidence(
                id=34,
                snapshot_id="snap-route-delete",
                context_type_code="ROUTE_SEGMENT",
                context_id=15,
                created_at=now,
            ),
            VesselCandidateAnalysis(
                id=40,
                context_type_code="ROUTE",
                route_id=10,
                plan_id=11,
                query_hash="route-delete",
                generated_at=now,
                created_at=now,
                updated_at=now,
            ),
            VesselCandidateAnalysisItem(
                id=41,
                analysis_id=40,
                mmsi="412000001",
                fit_score=Decimal("88.00"),
                created_at=now,
            ),
            VesselCandidateAnalysisAnnotation(
                id=42,
                analysis_id=40,
                item_id=41,
                annotation_type_code="NEEDS_REVIEW",
                created_at=now,
            ),
        ]
    )
    await session.commit()

    await ShippingRouteService(session).delete_route(10)

    for model in (
        ShippingRoute,
        ShippingRoutePlan,
        ShippingRoutePlanPoint,
        ShippingRoutePlanSegment,
        ShippingRoutePlanSegmentResult,
        ShippingRoutePlanTrackVersion,
        ShippingRoutePlanTrackVersionSegment,
        VesselRouteSegmentObservationItem,
        VesselRouteSegmentMatchSample,
        FactVesselRouteSegmentDaily,
        VesselNavigationConstraintEvidence,
        VesselCandidateAnalysis,
        VesselCandidateAnalysisItem,
        VesselCandidateAnalysisAnnotation,
    ):
        assert await session.scalar(select(func.count(model.id))) == 0
    assert await session.scalar(select(func.count(Region.id))) == 2


@pytest.mark.asyncio
async def test_replace_structure_preserves_history_and_invalidates_current_on_change(session: AsyncSession) -> None:
    plan_id = await _seed_plan(session)
    service = ShippingRoutePlanStructureService(session)
    structure = await service.get_structure(plan_id)
    saved = await service.save_track_version(
        plan_id,
        RouteTrackVersionSaveRequest(
            segments=[
                RouteTrackVersionSegmentSaveItem(
                    segment_id=segment.id,
                    geometry_json={
                        "type": "LineString",
                        "coordinates": (
                            [[120.0, 31.0], [120.25, 31.12], [120.5, 31.2]]
                            if segment.segment_no == 1
                            else [[120.5, 31.2], [120.75, 31.36], [121.0, 31.5]]
                        ),
                    },
                    edit_status_code="EDITED",
                )
                for segment in structure.segments
            ],
        ),
    )

    same_payload = RoutePlanStructureReplaceRequest(
        points=[
            RoutePlanPointUpsertItem(
                point_type_code=point.point_type_code,
                transport_node_id=point.transport_node_id,
                constraint_point_id=point.constraint_point_id,
                manual_name=point.manual_name,
                longitude=point.longitude,
                latitude=point.latitude,
                display_name=point.display_name,
                transport_mode_after_code=point.transport_mode_after_code,
                remark=point.remark,
            )
            for point in structure.points
        ]
    )
    await service.replace_structure(plan_id, same_payload)
    plan = await session.get(ShippingRoutePlan, plan_id)
    versions_after_same_save = await service.list_track_versions(plan_id)

    assert plan.current_track_version_id == saved.id
    assert len(versions_after_same_save) == 1
    assert plan.structure_revision == 1

    changed_payload = RoutePlanStructureReplaceRequest(
        points=[
            RoutePlanPointUpsertItem(
                point_type_code=structure.points[0].point_type_code,
                manual_name=structure.points[0].manual_name,
                longitude=structure.points[0].longitude,
                latitude=structure.points[0].latitude,
                display_name=structure.points[0].display_name,
                transport_mode_after_code="WATER",
                remark=structure.points[0].remark,
            ),
            RoutePlanPointUpsertItem(
                point_type_code=structure.points[2].point_type_code,
                manual_name=structure.points[2].manual_name,
                longitude=structure.points[2].longitude,
                latitude=structure.points[2].latitude,
                display_name=structure.points[2].display_name,
                remark=structure.points[2].remark,
            ),
        ]
    )
    new_structure = await service.replace_structure(plan_id, changed_payload)
    await session.refresh(plan)
    version_count = await session.scalar(select(func.count(ShippingRoutePlanTrackVersion.id)))
    version_segment_count = await session.scalar(select(func.count(ShippingRoutePlanTrackVersionSegment.id)))
    point_count = await session.scalar(select(func.count(ShippingRoutePlanPoint.id)))
    segment_count = await session.scalar(select(func.count(ShippingRoutePlanSegment.id)))
    versions_after_change = await service.list_track_versions(plan_id)

    assert plan.current_track_version_id is None
    assert plan.structure_revision == 2
    assert new_structure.plan.structure_revision == 2
    assert len(new_structure.points) == 2
    assert len(new_structure.segments) == 1
    assert len(versions_after_change) == 1
    assert versions_after_change[0].id == saved.id
    assert versions_after_change[0].is_current is False
    assert versions_after_change[0].is_compatible_with_current_structure is False
    assert version_count == 1
    assert version_segment_count == 2
    assert point_count == 5
    assert segment_count == 3

    with pytest.raises(Exception, match="历史结构轨迹不能设为当前"):
        await service.set_current_track_version(plan_id, saved.id)

    new_saved = await service.save_track_version(
        plan_id,
        RouteTrackVersionSaveRequest(
            segments=[
                RouteTrackVersionSegmentSaveItem(
                    segment_id=new_structure.segments[0].id,
                    geometry_json={
                        "type": "LineString",
                        "coordinates": [[120.0, 31.0], [120.5, 31.25], [121.0, 31.5]],
                    },
                    edit_status_code="REDRAWN",
                )
            ],
        ),
    )
    await session.refresh(plan)
    final_versions = await service.list_track_versions(plan_id)

    assert new_saved.is_current is True
    assert new_saved.structure_revision == 2
    assert plan.current_track_version_id == new_saved.id
    assert len(final_versions) == 2
    assert any(item.id == saved.id and not item.is_current and not item.is_compatible_with_current_structure for item in final_versions)


@pytest.mark.asyncio
async def test_adding_structure_point_preserves_history_until_new_track_saved(session: AsyncSession) -> None:
    plan_id = await _seed_plan(session)
    service = ShippingRoutePlanStructureService(session)
    structure = await service.get_structure(plan_id)
    saved = await service.save_track_version(
        plan_id,
        RouteTrackVersionSaveRequest(
            segments=[
                RouteTrackVersionSegmentSaveItem(
                    segment_id=segment.id,
                    geometry_json={
                        "type": "LineString",
                        "coordinates": (
                            [[120.0, 31.0], [120.25, 31.12], [120.5, 31.2]]
                            if segment.segment_no == 1
                            else [[120.5, 31.2], [120.75, 31.36], [121.0, 31.5]]
                        ),
                    },
                    edit_status_code="EDITED",
                )
                for segment in structure.segments
            ],
        ),
    )

    changed_payload = RoutePlanStructureReplaceRequest(
        points=[
            RoutePlanPointUpsertItem(
                point_type_code=structure.points[0].point_type_code,
                manual_name=structure.points[0].manual_name,
                longitude=structure.points[0].longitude,
                latitude=structure.points[0].latitude,
                display_name=structure.points[0].display_name,
                transport_mode_after_code="WATER",
                remark=structure.points[0].remark,
            ),
            RoutePlanPointUpsertItem(
                point_type_code=structure.points[1].point_type_code,
                manual_name=structure.points[1].manual_name,
                longitude=structure.points[1].longitude,
                latitude=structure.points[1].latitude,
                display_name=structure.points[1].display_name,
                transport_mode_after_code="WATER",
                remark=structure.points[1].remark,
            ),
            RoutePlanPointUpsertItem(
                point_type_code="MANUAL_POINT",
                manual_name="B2",
                longitude=Decimal("120.75000000"),
                latitude=Decimal("31.35000000"),
                display_name="B2",
                transport_mode_after_code="WATER",
            ),
            RoutePlanPointUpsertItem(
                point_type_code=structure.points[2].point_type_code,
                manual_name=structure.points[2].manual_name,
                longitude=structure.points[2].longitude,
                latitude=structure.points[2].latitude,
                display_name=structure.points[2].display_name,
                remark=structure.points[2].remark,
            ),
        ]
    )
    new_structure = await service.replace_structure(plan_id, changed_payload)
    plan = await session.get(ShippingRoutePlan, plan_id)
    versions = await service.list_track_versions(plan_id)

    assert plan.current_track_version_id is None
    assert plan.structure_revision == 2
    assert len(new_structure.points) == 4
    assert len(new_structure.segments) == 3
    assert len(versions) == 1
    assert versions[0].id == saved.id
    assert versions[0].is_current is False
    assert versions[0].is_compatible_with_current_structure is False


@pytest.mark.asyncio
async def test_enqueue_generate_track_version_creates_idempotent_async_task(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    plan_id = await _seed_plan(session)
    service = ShippingRoutePlanStructureService(session)
    calls: list[tuple[int, dict, int | None, int | None]] = []

    class FakeAsyncResult:
        id = "celery-route-test-1"

    def fake_delay(plan_id_arg: int, payload: dict, requested_by: int | None, task_run_id: int | None) -> FakeAsyncResult:
        calls.append((plan_id_arg, payload, requested_by, task_run_id))
        return FakeAsyncResult()

    from app.tasks import route_tasks

    monkeypatch.setattr(route_tasks.generate_route_track_version_task, "delay", fake_delay)

    first = await service.enqueue_generate_track_version(
        plan_id,
        RouteTrackGenerateRequest(provider_code="HIFLEET"),
        requested_by=99,
    )
    second = await service.enqueue_generate_track_version(
        plan_id,
        RouteTrackGenerateRequest(provider_code="HIFLEET"),
        requested_by=99,
    )

    assert first.id == second.id
    assert first.status_code == "QUEUED"
    assert first.celery_task_id == "celery-route-test-1"
    assert first.business_type == "ROUTE_PLAN_TRACK_VERSION"
    assert first.extra_json["structure_revision"] == 1
    assert calls == [(plan_id, {"provider_code": "HIFLEET"}, 99, first.id)]


@pytest.mark.asyncio
async def test_save_track_version_requires_every_logical_segment(session: AsyncSession) -> None:
    plan_id = await _seed_plan(session)
    service = ShippingRoutePlanStructureService(session)

    with pytest.raises(Exception, match="补齐所有逻辑段"):
        await service.save_track_version(
            plan_id,
            RouteTrackVersionSaveRequest(
                segments=[
                    RouteTrackVersionSegmentSaveItem(
                        segment_id=15,
                        geometry_json={"type": "LineString", "coordinates": [[120.0, 31.0], [120.5, 31.2]]},
                    )
                ],
            ),
        )
