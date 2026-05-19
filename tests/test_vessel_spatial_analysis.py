from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import BigInteger

import app.models  # noqa: F401
from main import app
from app.core.config import settings
from app.models.address import NavigationConstraintPoint, NavigationConstraintProfile, TransportNode
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
    VesselAisSnapshot,
    VesselCapacityDimension,
    VesselLatestPositionSnapshot,
    VesselProfile,
    VesselProfileSummary,
)
from app.modules.vessel.schemas import (
    VesselAisNodeSituationQuery,
    VesselAisNodeVesselsQuery,
    VesselAisRouteSituationQuery,
    VesselNavigationConstraintQuery,
)
from app.modules.vessel.spatial_service import _HistorySearchResult, VesselSpatialAnalysisService
from scripts.seeds.loaders.builtin_dicts import BUILTIN_DICTS


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


def test_round7_openapi_contracts_exist() -> None:
    paths = app.openapi()["paths"]

    for path in [
        "/api/v1/vessels/ais/node-situation",
        "/api/v1/vessels/ais/node-vessels",
        "/api/v1/vessels/ais/route-situation",
        "/api/v1/vessels/ais/route-segment-vessels",
        "/api/v1/vessels/navigation-constraints",
        "/api/v1/vessels/ais/spatial-snapshots/{snapshot_id}",
    ]:
        assert "get" in paths[path]

    node_params = {item["name"] for item in paths["/api/v1/vessels/ais/node-situation"]["get"]["parameters"]}
    assert {"node_id", "radius_km", "time_window_hours", "reported_within_minutes"}.issubset(node_params)
    route_params = {item["name"] for item in paths["/api/v1/vessels/ais/route-situation"]["get"]["parameters"]}
    assert {"route_id", "plan_id", "time_window_hours"}.issubset(route_params)


def test_round7_dict_and_config_defaults_are_seeded() -> None:
    dict_codes = {item["dict_code"] for item in BUILTIN_DICTS}

    assert {
        "VESSEL_SPATIAL_OBSERVATION_TYPE",
        "VESSEL_SPATIAL_OBSERVATION_STATUS",
        "VESSEL_SPATIAL_MATCH_STATUS",
        "VESSEL_SPATIAL_NOT_COMPUTABLE_REASON",
        "VESSEL_NAVIGATION_CONSTRAINT_STATUS",
    }.issubset(dict_codes)
    assert settings.VESSEL_SPATIAL_NODE_DEFAULT_RADIUS_KM == 2.0
    assert settings.VESSEL_SPATIAL_NODE_STAY_MINUTES == 120
    assert settings.VESSEL_SPATIAL_SNAPSHOT_TTL_SECONDS > 0


@pytest.mark.asyncio
async def test_node_without_coordinates_is_not_computable(session: AsyncSession) -> None:
    node = await _seed_node(session, longitude=None, latitude=None)
    await session.commit()

    response = await VesselSpatialAnalysisService(session).node_situation(
        VesselAisNodeSituationQuery(node_id=node.id, radius_km=Decimal("2"))
    )

    assert response.snapshot.status_code == "NOT_COMPUTABLE"
    assert response.snapshot.source_status_code == "EMPTY"
    assert response.summary.not_computable_reasons == ["NODE_COORD_MISSING"]
    assert response.constraints[0].status_code == "MISSING_SOURCE"


@pytest.mark.asyncio
async def test_node_snapshot_drilldown_reuses_same_snapshot_and_failed_batches(session: AsyncSession) -> None:
    now = datetime.utcnow()
    node = await _seed_node(session)
    await _seed_vessel_with_position(session, now=now)
    await session.commit()
    service = VesselSpatialAnalysisService(session)

    async def fake_history(mmsi_values, start_at, end_at):  # noqa: ANN001
        return _HistorySearchResult(
            points_by_mmsi={
                "412000001": [
                    {"mmsi": "412000001", "longitude": 118.781, "latitude": 32.041, "position_time": now - timedelta(hours=3), "source_index": "hist-1"},
                    {"mmsi": "412000001", "longitude": 118.782, "latitude": 32.042, "position_time": now - timedelta(minutes=20), "source_index": "hist-1"},
                ]
            },
            partial=True,
            error_message="history batch failed",
            failed_batches=[{"batch_index": 2, "mmsi_count": 1, "error_code": "ES_PARTIAL"}],
            source_status_code="PARTIAL",
            source_indices=["hist-1"],
        )

    service._search_history_positions = fake_history  # type: ignore[method-assign]

    response = await service.node_situation(VesselAisNodeSituationQuery(node_id=node.id, radius_km=Decimal("2")))

    assert response.snapshot.status_code == "PARTIAL"
    assert response.snapshot.source_snapshot_id == "ais-1"
    assert response.snapshot.failed_batch_count == 1
    assert response.summary.active_vessel_count == 1
    assert response.vessels[0].mmsi == "412000001"

    drilldown = await service.node_vessels(
        VesselAisNodeVesselsQuery(
            node_id=node.id,
            query_snapshot_id=response.snapshot.snapshot_id,
            radius_km=Decimal("2"),
        )
    )

    assert drilldown.snapshot_hit is True
    assert drilldown.refresh_required is False
    assert drilldown.total == 1
    assert drilldown.items[0].mmsi == "412000001"

    snapshot = await service.spatial_snapshot(response.snapshot.snapshot_id)
    assert snapshot.snapshot.failed_batches[0]["error_code"] == "ES_PARTIAL"
    assert snapshot.node is not None
    assert snapshot.node.node_id == node.id


@pytest.mark.asyncio
async def test_route_without_ready_geometry_is_not_computable(session: AsyncSession) -> None:
    now = datetime.utcnow()
    route_id = await _seed_route_with_segment(session, generation_status_code="NOT_GENERATED", geometry_json=None)
    await _seed_vessel_with_position(session, now=now)
    await session.commit()
    service = VesselSpatialAnalysisService(session)

    async def fake_history(mmsi_values, start_at, end_at):  # noqa: ANN001
        return _HistorySearchResult({}, False, None, [], "AVAILABLE", [])

    service._search_history_positions = fake_history  # type: ignore[method-assign]

    response = await service.route_situation(VesselAisRouteSituationQuery(route_id=route_id))

    assert response.snapshot.status_code == "NOT_COMPUTABLE"
    assert "ROUTE_GEOMETRY_MISSING" in response.summary.not_computable_reasons
    assert response.segments[0].geometry_status_code == "MISSING"
    assert response.segments[0].not_computable_reasons == ["ROUTE_GEOMETRY_MISSING"]


@pytest.mark.asyncio
async def test_route_reverse_track_is_low_confidence_not_reliable_match(session: AsyncSession) -> None:
    now = datetime.utcnow()
    route_id = await _seed_route_with_segment(session)
    await _seed_vessel_with_position(session, now=now)
    await session.commit()
    service = VesselSpatialAnalysisService(session)

    async def fake_history(mmsi_values, start_at, end_at):  # noqa: ANN001
        assert mmsi_values == ["412000001"]
        return _HistorySearchResult(
            points_by_mmsi={
                "412000001": [
                    {"mmsi": "412000001", "longitude": 118.90, "latitude": 32.08, "position_time": now - timedelta(hours=3), "source_index": "hist-1", "course_deg": 240},
                    {"mmsi": "412000001", "longitude": 118.70, "latitude": 32.00, "position_time": now - timedelta(hours=2), "source_index": "hist-1", "course_deg": 240},
                ]
            },
            partial=False,
            error_message=None,
            failed_batches=[],
            source_status_code="AVAILABLE",
            source_indices=["hist-1"],
        )

    service._search_history_positions = fake_history  # type: ignore[method-assign]

    response = await service.route_situation(VesselAisRouteSituationQuery(route_id=route_id))

    assert response.samples[0].direction_consistency is not None
    assert response.samples[0].direction_consistency < Decimal("100")
    assert response.samples[0].match_status_code == "LOW_CONFIDENCE"
    assert response.samples[0].confidence_level == "LOW"
    assert response.summary.matched_vessel_count == 0
    assert response.segments[0].matched_vessel_count == 0
    assert "TRACK_SAMPLE_INSUFFICIENT" in response.summary.not_computable_reasons


@pytest.mark.asyncio
async def test_route_reported_within_filters_stale_latest_positions(session: AsyncSession) -> None:
    now = datetime.utcnow()
    route_id = await _seed_route_with_segment(session)
    await _seed_vessel_with_position(
        session,
        now=now,
        position_time=now - timedelta(days=2),
        freshness_level="EXPIRED",
    )
    await session.commit()
    service = VesselSpatialAnalysisService(session)

    async def fake_history(mmsi_values, start_at, end_at):  # noqa: ANN001
        assert mmsi_values == []
        return _HistorySearchResult({}, False, None, [], "EMPTY", [])

    service._search_history_positions = fake_history  # type: ignore[method-assign]

    response = await service.route_situation(
        VesselAisRouteSituationQuery(route_id=route_id, reported_within_minutes=60)
    )

    assert response.snapshot.status_code == "NOT_COMPUTABLE"
    assert response.snapshot.active_vessel_count == 0
    assert response.snapshot.stale_position_count == 1
    assert response.summary.active_vessel_count == 0
    assert "TRACK_SAMPLE_INSUFFICIENT" in response.summary.not_computable_reasons
    assert response.samples == []


@pytest.mark.asyncio
async def test_short_node_passby_does_not_count_as_inflow(session: AsyncSession) -> None:
    now = datetime.utcnow()
    node = await _seed_node(session)
    await _seed_vessel_with_position(session, now=now)
    await session.commit()
    service = VesselSpatialAnalysisService(session)

    async def fake_history(mmsi_values, start_at, end_at):  # noqa: ANN001
        return _HistorySearchResult(
            points_by_mmsi={
                "412000001": [
                    {"mmsi": "412000001", "longitude": 118.70, "latitude": 32.00, "position_time": now - timedelta(minutes=30), "source_index": "hist-1"},
                    {"mmsi": "412000001", "longitude": 118.781, "latitude": 32.041, "position_time": now - timedelta(minutes=5), "source_index": "hist-1"},
                ]
            },
            partial=False,
            error_message=None,
            failed_batches=[],
            source_status_code="AVAILABLE",
            source_indices=["hist-1"],
        )

    service._search_history_positions = fake_history  # type: ignore[method-assign]

    response = await service.node_situation(VesselAisNodeSituationQuery(node_id=node.id, radius_km=Decimal("2")))

    assert response.vessels[0].match_status_code == "PASSBY"
    assert response.vessels[0].direction_status_code == "PASSBY"
    assert response.summary.inflow_count == 0
    assert response.summary.outflow_count == 0


@pytest.mark.asyncio
async def test_navigation_constraints_missing_source_stays_unknown(session: AsyncSession) -> None:
    node = await _seed_node(session)
    await session.commit()

    response = await VesselSpatialAnalysisService(session).navigation_constraints(
        VesselNavigationConstraintQuery(context_type="NODE", node_id=node.id)
    )

    assert response.source_status == "EMPTY"
    assert response.items[0].status_code == "MISSING_SOURCE"
    assert response.items[0].confidence_level == "UNKNOWN"


@pytest.mark.asyncio
async def test_navigation_constraint_expired_source_is_stale(session: AsyncSession) -> None:
    now = datetime.utcnow()
    node = await _seed_node(session)
    await _seed_constraint_point(session, valid_to=now - timedelta(days=1), with_profile=True)
    await session.commit()

    response = await VesselSpatialAnalysisService(session).navigation_constraints(
        VesselNavigationConstraintQuery(context_type="NODE", node_id=node.id)
    )

    assert response.source_status == "AVAILABLE"
    assert response.items[0].status_code == "STALE"
    assert response.items[0].confidence_level == "LOW"
    assert response.items[0].unavailable_reason == "EXPIRED"


@pytest.mark.asyncio
async def test_navigation_constraint_without_profile_is_unknown(session: AsyncSession) -> None:
    node = await _seed_node(session)
    await _seed_constraint_point(session, with_profile=False)
    await session.commit()

    response = await VesselSpatialAnalysisService(session).navigation_constraints(
        VesselNavigationConstraintQuery(context_type="NODE", node_id=node.id)
    )

    assert response.source_status == "AVAILABLE"
    assert response.items[0].status_code == "UNKNOWN"
    assert response.items[0].confidence_level == "UNKNOWN"
    assert response.items[0].unavailable_reason == "PROFILE_MISSING"


async def _seed_node(
    session: AsyncSession,
    *,
    node_id: int = 1,
    longitude: float | None = 118.7801,
    latitude: float | None = 32.0402,
) -> TransportNode:
    node = TransportNode(
        id=node_id,
        code=f"NODE{node_id:03d}",
        name="南京港节点",
        node_type_code="PORT",
        province_code="320000",
        city_code="320100",
        city_region_id=1,
        longitude=longitude,
        latitude=latitude,
        status=1,
        lifecycle_status_code="ACTIVE",
        audit_status="APPROVED",
    )
    session.add(node)
    await session.flush()
    return node


async def _seed_constraint_point(
    session: AsyncSession,
    *,
    point_id: int = 300,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    with_profile: bool = True,
) -> NavigationConstraintPoint:
    point = NavigationConstraintPoint(
        id=point_id,
        code=f"LIMIT{point_id:03d}",
        name="南京桥区测试约束",
        constraint_type_code="BRIDGE",
        province_code="320000",
        city_code="320100",
        longitude=Decimal("118.78100000"),
        latitude=Decimal("32.04100000"),
        valid_from=valid_from,
        valid_to=valid_to,
        severity_level=2,
        description="测试约束",
        status=1,
    )
    session.add(point)
    await session.flush()

    if with_profile:
        session.add(
            NavigationConstraintProfile(
                id=point_id,
                constraint_point_id=point.id,
                max_allowed_draft_m=Decimal("3.50"),
                rule_description="测试通航规则",
            )
        )
        await session.flush()

    return point


async def _seed_vessel_with_position(
    session: AsyncSession,
    *,
    now: datetime,
    profile_id: int = 100,
    position_id: int = 1,
    mmsi: str = "412000001",
    longitude: Decimal = Decimal("118.781000"),
    latitude: Decimal = Decimal("32.041000"),
    course_deg: Decimal = Decimal("90"),
    position_time: datetime | None = None,
    freshness_level: str = "FRESH",
) -> None:
    session.add_all(
        [
            VesselProfile(
                id=profile_id,
                vessel_profile_code=f"VP{profile_id}",
                ship_name="江海一号",
                current_mmsi=mmsi,
                ship_type_code="DRY_BULK",
                profile_status_code="ACTIVE",
                identity_status_code="LINKED",
                source_type_code="MANUAL",
                audit_status="APPROVED",
            ),
            VesselCapacityDimension(
                id=profile_id,
                vessel_profile_id=profile_id,
                deadweight_ton=Decimal("3000"),
                design_draft_m=Decimal("3.20"),
                updated_at=now,
            ),
            VesselProfileSummary(
                id=profile_id,
                vessel_profile_id=profile_id,
                ship_name="江海一号",
                current_mmsi=mmsi,
                ship_type_code="DRY_BULK",
                ship_type_name="干散货船",
                deadweight_ton=Decimal("3000"),
                design_draft_m=Decimal("3.20"),
                data_quality_level="HIGH",
                identity_confidence_level="HIGH",
                contact_trust_level="UNKNOWN",
                subject_consistency_level="UNKNOWN",
                quality_issue_count=0,
                missing_field_count=0,
                conflict_count=0,
                risk_level="LOW",
                certificate_missing_count=0,
                certificate_expiring_count=0,
                certificate_expired_count=0,
                ais_freshness_level="FRESH",
                source_layer="PROFILE_SUMMARY",
                summary_status_code="READY",
                summary_version="ROUND_7_TEST",
                created_at=now,
                updated_at=now,
            ),
            VesselAisSnapshot(
                id=1,
                snapshot_id="ais-1",
                query_hash="hash",
                query_params_json={},
                status_code="READY",
                generated_at=now,
                expires_at=now + timedelta(hours=1),
                cache_backend_code="database",
                scanned_profile_count=1,
                queried_mmsi_count=1,
                matched_profile_count=1,
                matched_position_count=1,
                unmatched_mmsi_count=0,
                invalid_position_count=0,
                unknown_city_count=0,
                failed_batch_count=0,
                failed_batches_json=[],
                coverage_rate=Decimal("100"),
                freshness_distribution_json={"FRESH": 1},
                source_indices_json=["rt-1"],
                uncertainty_notes_json=[],
                created_at=now,
                updated_at=now,
            ),
            VesselLatestPositionSnapshot(
                id=position_id,
                snapshot_id="ais-1",
                vessel_profile_id=profile_id,
                mmsi=mmsi,
                longitude=longitude,
                latitude=latitude,
                speed_kn=Decimal("5.2"),
                course_deg=course_deg,
                position_time=position_time or now - timedelta(minutes=10),
                source_index="rt-1",
                freshness_level=freshness_level,
                match_status_code="MATCHED_PROFILE",
                city_code="320100",
                city_name="南京市",
                valid_position_flag=True,
                created_at=now,
            ),
        ]
    )
    await session.flush()


async def _seed_route_with_segment(
    session: AsyncSession,
    *,
    generation_status_code: str = "READY",
    geometry_json: dict | None = None,
) -> int:
    now = datetime.utcnow()
    geometry = geometry_json if geometry_json is not None else {"type": "LineString", "coordinates": [[118.70, 32.00], [118.90, 32.08]]}
    session.add_all(
        [
            ShippingRoute(
                id=200,
                code="R200",
                name="南京-镇江",
                origin_endpoint_type_code="REGION",
                destination_endpoint_type_code="REGION",
                transport_org_type_code="WATER",
                origin_region_id=1,
                destination_region_id=2,
                audit_status="APPROVED",
            ),
            ShippingRoutePlan(
                id=201,
                route_id=200,
                plan_code="P200",
                plan_name="主方案",
                plan_type_code="STANDARD",
                is_default=True,
                status_code="ACTIVE",
                display_order=1,
            ),
            ShippingRoutePlanPoint(
                id=203,
                plan_id=201,
                point_order=1,
                point_type_code="MANUAL_POINT",
                display_name="起点",
                manual_name="起点",
                longitude=Decimal("118.70"),
                latitude=Decimal("32.00"),
                transport_mode_after_code="WATER",
            ),
            ShippingRoutePlanPoint(
                id=204,
                plan_id=201,
                point_order=2,
                point_type_code="MANUAL_POINT",
                display_name="终点",
                manual_name="终点",
                longitude=Decimal("118.90"),
                latitude=Decimal("32.08"),
            ),
            ShippingRoutePlanSegment(
                id=205,
                plan_id=201,
                segment_no=1,
                start_plan_point_id=203,
                end_plan_point_id=204,
                transport_mode_code="WATER",
                generation_status_code=generation_status_code,
            ),
        ]
    )
    await session.flush()
    if generation_status_code == "READY":
        result = ShippingRoutePlanSegmentResult(
            segment_id=205,
            result_no=1,
            provider_type_code="TEST",
            result_status_code="READY",
            is_selected=True,
            geometry_json=geometry,
        )
        session.add(result)
        await session.flush()
        segment = await session.get(ShippingRoutePlanSegment, 205)
        segment.selected_result_id = result.id
        version = ShippingRoutePlanTrackVersion(
            plan_id=201,
            version_no=1,
            source_type_code="TEST",
            provider_type_code="TEST",
            is_current=True,
            version_status_code="READY",
            point_count=len(geometry.get("coordinates") or []),
            segment_count=1,
            generated_at=now,
        )
        session.add(version)
        await session.flush()
        session.add(
            ShippingRoutePlanTrackVersionSegment(
                version_id=version.id,
                segment_id=205,
                segment_no=1,
                geometry_json=geometry,
                point_count=len(geometry.get("coordinates") or []),
                edit_status_code="ORIGINAL",
            )
        )
        plan = await session.get(ShippingRoutePlan, 201)
        plan.current_track_version_id = version.id
    _ = now, geometry
    return 200
