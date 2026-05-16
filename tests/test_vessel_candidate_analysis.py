from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import BigInteger

import app.models  # noqa: F401
from main import app
from app.core.exceptions import ValidationError
from app.models.address import TransportNode
from app.models.base import Base
from app.models.freight import Freight, FreightCandidate
from app.models.vessel import (
    VesselAisSnapshot,
    VesselCandidateAnalysis,
    VesselCandidateAnalysisAnnotation,
    VesselCandidateAnalysisItem,
    VesselLatestPositionSnapshot,
    VesselNavigationConstraintEvidence,
    VesselNodeObservationVessel,
    VesselProfile,
    VesselProfileSummary,
    VesselSpatialObservationSnapshot,
)
from app.modules.vessel.candidate_service import VesselCandidateAnalysisService
from app.modules.vessel.schemas import (
    VesselCandidateAnalysisAnnotationRequest,
    VesselCandidateAnalysisCreateRequest,
    VesselCandidateAnalysisFilters,
)
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


def test_round8_openapi_models_and_dicts_exist() -> None:
    paths = app.openapi()["paths"]

    assert "post" in paths["/api/v1/vessels/candidate-analyses"]
    assert "get" in paths["/api/v1/vessels/candidate-analyses"]
    assert "get" in paths["/api/v1/vessels/candidate-analyses/{analysis_id}"]
    assert "post" in paths["/api/v1/vessels/candidate-analyses/{analysis_id}/items/{item_id}/annotations"]

    assert VesselCandidateAnalysis.__tablename__ == "vessel_candidate_analysis"
    assert VesselCandidateAnalysisItem.__tablename__ == "vessel_candidate_analysis_item"
    assert VesselCandidateAnalysisAnnotation.__tablename__ == "vessel_candidate_analysis_annotation"
    dict_codes = {item["dict_code"] for item in BUILTIN_DICTS}
    assert {
        "VESSEL_CANDIDATE_CONTEXT_TYPE",
        "VESSEL_CANDIDATE_ANALYSIS_STATUS",
        "VESSEL_CANDIDATE_VALUE_LEVEL",
        "VESSEL_CANDIDATE_SCORE_DIMENSION",
        "VESSEL_CANDIDATE_NOT_COMPUTABLE_REASON",
        "VESSEL_ANALYSIS_ANNOTATION_TYPE",
    }.issubset(dict_codes)


@pytest.mark.asyncio
async def test_formal_freight_analysis_reuses_spatial_snapshot_and_excludes_execution_fields(session: AsyncSession) -> None:
    now = datetime.utcnow()
    await _seed_node(session)
    await _seed_freight(session)
    await _seed_candidate_fixture(session, now=now)
    await session.commit()

    response = await VesselCandidateAnalysisService(session).create_analysis(
        VesselCandidateAnalysisCreateRequest(
            context_type_code="FREIGHT_SAMPLE",
            freight_id=500,
            source_spatial_snapshot_id="spatial-1",
            filters=VesselCandidateAnalysisFilters(ship_type_codes=["DRY_BULK"], min_deadweight_ton=Decimal("2000")),
        ),
        operator_id=7,
    )

    assert response.source_ais_snapshot_id == "ais-1"
    assert response.source_spatial_snapshot_id == "spatial-1"
    assert response.candidate_count == 1
    assert response.items[0].candidate_value_level == "HIGH"
    assert response.items[0].score_parts["SPATIAL_DISTANCE"] > 0

    detail = await VesselCandidateAnalysisService(session).get_analysis(response.id)
    assert detail.source_spatial_snapshot_id == response.source_spatial_snapshot_id
    assert detail.items[0].id == response.items[0].id
    _assert_no_execution_fields(detail.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_candidate_freight_context_does_not_mutate_candidate_or_return_price_contact(session: AsyncSession) -> None:
    now = datetime.utcnow()
    await _seed_node(session)
    await _seed_freight_candidate(session)
    await _seed_candidate_fixture(session, now=now)
    await session.commit()

    response = await VesselCandidateAnalysisService(session).create_analysis(
        VesselCandidateAnalysisCreateRequest(
            context_type_code="FREIGHT_CANDIDATE",
            freight_candidate_id=501,
            source_spatial_snapshot_id="spatial-1",
        )
    )

    refreshed = await session.get(FreightCandidate, 501)
    assert refreshed is not None
    assert refreshed.status_code == "PENDING"
    assert refreshed.confirmed_freight_id is None
    assert response.source_layer_code == "FREIGHT_CANDIDATE"
    _assert_no_execution_fields(response.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_node_without_coordinates_is_not_computable(session: AsyncSession) -> None:
    await _seed_node(session, longitude=None, latitude=None)
    await session.commit()

    response = await VesselCandidateAnalysisService(session).create_analysis(
        VesselCandidateAnalysisCreateRequest(context_type_code="NODE", origin_node_id=1)
    )

    assert response.status_code == "NOT_COMPUTABLE"
    assert "NODE_COORD_MISSING" in response.not_computable_reasons


@pytest.mark.asyncio
async def test_expired_ais_and_unknown_constraint_never_become_high_value(session: AsyncSession) -> None:
    now = datetime.utcnow()
    await _seed_node(session)
    await _seed_candidate_fixture(
        session,
        now=now,
        freshness_level="EXPIRED",
        position_time=now - timedelta(days=4),
        constraint_status="MISSING_SOURCE",
    )
    await session.commit()

    response = await VesselCandidateAnalysisService(session).create_analysis(
        VesselCandidateAnalysisCreateRequest(context_type_code="NODE", origin_node_id=1, source_spatial_snapshot_id="spatial-1")
    )

    assert response.items
    assert response.items[0].candidate_value_level != "HIGH"
    assert response.items[0].confidence_level in {"LOW", "UNKNOWN"}
    assert "CONSTRAINT_SOURCE_MISSING" in response.items[0].not_computable_reasons
    assert "AIS_EXPIRED" in response.items[0].uncertainty_reasons


@pytest.mark.asyncio
async def test_high_risk_or_unknown_risk_is_capped(session: AsyncSession) -> None:
    now = datetime.utcnow()
    await _seed_node(session)
    await _seed_candidate_fixture(session, now=now, risk_level="UNKNOWN")
    await session.commit()

    response = await VesselCandidateAnalysisService(session).create_analysis(
        VesselCandidateAnalysisCreateRequest(context_type_code="NODE", origin_node_id=1, source_spatial_snapshot_id="spatial-1")
    )

    assert response.items[0].candidate_value_level != "HIGH"
    assert "RISK_UNKNOWN" in response.items[0].not_computable_reasons


@pytest.mark.asyncio
async def test_annotation_allows_analysis_terms_and_rejects_execution_terms(session: AsyncSession) -> None:
    now = datetime.utcnow()
    await _seed_node(session)
    await _seed_candidate_fixture(session, now=now)
    await session.commit()
    service = VesselCandidateAnalysisService(session)
    response = await service.create_analysis(
        VesselCandidateAnalysisCreateRequest(context_type_code="NODE", origin_node_id=1, source_spatial_snapshot_id="spatial-1"),
        operator_id=7,
    )

    annotation = await service.add_annotation(
        response.id,
        response.items[0].id,
        VesselCandidateAnalysisAnnotationRequest(annotation_type_code="SAMPLE_REFERENCEABLE", comment="样本可参考"),
        operator_id=7,
    )
    assert annotation.annotation_type_code == "SAMPLE_REFERENCEABLE"

    with pytest.raises(ValidationError):
        await service.add_annotation(
            response.id,
            response.items[0].id,
            VesselCandidateAnalysisAnnotationRequest(annotation_type_code="NEEDS_REVIEW", comment="请派船"),
        )


async def _seed_node(
    session: AsyncSession,
    *,
    node_id: int = 1,
    longitude: float | None = 118.7801,
    latitude: float | None = 32.0402,
) -> None:
    session.add(
        TransportNode(
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
    )
    await session.flush()


async def _seed_freight(session: AsyncSession) -> None:
    session.add(
        Freight(
            id=500,
            freight_no="FR-ROUND8",
            source_type_code="MANUAL",
            source_channel_code="MANUAL",
            cargo_title="动力煤",
            estimated_tonnage=Decimal("2500"),
            unit_price=Decimal("88"),
            origin_node_id=1,
            destination_node_id=2,
            origin_city_code="320100",
            destination_city_code="320200",
            status_code="PUBLISHED",
            hall_status_code="NOT_LISTED",
            audit_status="APPROVED",
        )
    )
    await session.flush()


async def _seed_freight_candidate(session: AsyncSession) -> None:
    session.add(
        FreightCandidate(
            id=501,
            candidate_no="FCA-ROUND8",
            source_type_code="WECHAT",
            source_channel_code="WECHAT_TEXT",
            cargo_title="砂石",
            estimated_tonnage=Decimal("2000"),
            unit_price=Decimal("66"),
            origin_node_id=1,
            destination_node_id=2,
            origin_city_code="320100",
            destination_city_code="320200",
            contact_name="不应返回",
            contact_phone="13800000000",
            ai_review_status_code="PASS",
            availability_status_code="READY",
            status_code="PENDING",
        )
    )
    await session.flush()


async def _seed_candidate_fixture(
    session: AsyncSession,
    *,
    now: datetime,
    freshness_level: str = "FRESH",
    position_time: datetime | None = None,
    risk_level: str = "LOW",
    constraint_status: str = "AVAILABLE",
) -> None:
    session.add_all(
        [
            VesselProfile(
                id=100,
                vessel_profile_code="VP100",
                ship_name="江海一号",
                current_mmsi="412000001",
                ship_type_code="DRY_BULK",
                profile_status_code="ACTIVE",
                identity_status_code="LINKED",
                source_type_code="MANUAL",
                audit_status="APPROVED",
            ),
            VesselProfileSummary(
                id=100,
                vessel_profile_id=100,
                ship_name="江海一号",
                current_mmsi="412000001",
                ship_type_code="DRY_BULK",
                ship_type_name="干散货船",
                deadweight_ton=Decimal("3000"),
                design_draft_m=Decimal("3.20"),
                data_quality_level="HIGH",
                identity_confidence_level="HIGH",
                contact_trust_level="HIGH",
                subject_consistency_level="HIGH",
                quality_issue_count=0,
                missing_field_count=0,
                conflict_count=0,
                risk_level=risk_level,
                certificate_missing_count=0,
                certificate_expiring_count=0,
                certificate_expired_count=0,
                latest_position_time=position_time or now - timedelta(minutes=10),
                ais_freshness_level=freshness_level,
                source_layer="PROFILE_SUMMARY",
                coverage_rate=Decimal("100"),
                summary_status_code="READY",
                summary_version="ROUND_8_TEST",
                refreshed_at=now,
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
                freshness_distribution_json={freshness_level: 1},
                source_indices_json=["rt-1"],
                uncertainty_notes_json=[],
                created_at=now,
                updated_at=now,
            ),
            VesselLatestPositionSnapshot(
                id=1,
                snapshot_id="ais-1",
                vessel_profile_id=100,
                mmsi="412000001",
                longitude=Decimal("118.781000"),
                latitude=Decimal("32.041000"),
                speed_kn=Decimal("5.2"),
                course_deg=Decimal("90"),
                position_time=position_time or now - timedelta(minutes=10),
                source_index="rt-1",
                freshness_level=freshness_level,
                match_status_code="MATCHED_PROFILE",
                city_code="320100",
                city_name="南京市",
                valid_position_flag=True,
                created_at=now,
            ),
            VesselSpatialObservationSnapshot(
                id=1,
                snapshot_id="spatial-1",
                source_snapshot_id="ais-1",
                observation_type_code="NODE",
                query_hash="spatial-hash",
                query_params_json={"node_id": 1},
                status_code="READY",
                source_status_code="AVAILABLE",
                stat_time=now,
                generated_at=now,
                expires_at=now + timedelta(hours=1),
                coverage_rate=Decimal("100"),
                confidence_level="HIGH",
                freshness_distribution_json={freshness_level: 1},
                source_indices_json=["rt-1"],
                failed_batch_count=0,
                failed_batches_json=[],
                unmatched_mmsi_count=0,
                invalid_position_count=0,
                stale_position_count=0 if freshness_level in {"FRESH", "RECENT"} else 1,
                matched_position_count=1,
                active_vessel_count=1 if freshness_level in {"FRESH", "RECENT"} else 0,
                not_computable_reasons_json=[],
                quality_warnings_json=[],
                uncertainty_notes_json=[],
                created_at=now,
                updated_at=now,
            ),
            VesselNodeObservationVessel(
                id=1,
                snapshot_id="spatial-1",
                node_id=1,
                vessel_profile_id=100,
                mmsi="412000001",
                ship_name="江海一号",
                ship_type_code="DRY_BULK",
                deadweight_ton=Decimal("3000"),
                longitude=Decimal("118.781000"),
                latitude=Decimal("32.041000"),
                distance_km=Decimal("1.2"),
                position_time=position_time or now - timedelta(minutes=10),
                source_index="rt-1",
                freshness_level=freshness_level,
                match_status_code="NEARBY",
                direction_status_code="UNKNOWN",
                risk_level=risk_level,
                quality_level="HIGH",
                created_at=now,
            ),
            VesselNavigationConstraintEvidence(
                id=1,
                snapshot_id="spatial-1",
                context_type_code="NODE",
                context_id=1,
                constraint_name="测试通航约束",
                status_code=constraint_status,
                source_type_code="BASE_DATA",
                source_ref="TEST",
                observed_at=now,
                expires_at=now + timedelta(days=1),
                value_json={"max_allowed_draft_m": 3.5, "longitude": 118.781, "latitude": 32.041},
                confidence_level="HIGH" if constraint_status == "AVAILABLE" else "UNKNOWN",
                unavailable_reason=None if constraint_status == "AVAILABLE" else "MISSING_SOURCE",
                created_at=now,
            ),
        ]
    )
    await session.flush()


def _assert_no_execution_fields(payload: Any) -> None:
    forbidden = {
        "contact_name",
        "contact_phone",
        "contact_wechat",
        "unit_price",
        "total_price",
        "price_unit",
        "settlement_method_code",
        "dispatch",
        "quote",
        "deal",
        "order",
        "settlement",
    }
    if isinstance(payload, dict):
        assert forbidden.isdisjoint(payload.keys())
        for value in payload.values():
            _assert_no_execution_fields(value)
    elif isinstance(payload, list):
        for value in payload:
            _assert_no_execution_fields(value)
