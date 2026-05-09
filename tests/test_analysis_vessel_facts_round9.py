from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import BigInteger

import app.models  # noqa: F401
from main import app
from app.models.analysis import (
    FactCandidateFitDaily,
    FactFreightCityDaily,
    FactRegionSupplyDemandDaily,
    FactVesselAisFreshnessDaily,
    FactVesselAssetDaily,
    FactVesselNodeDaily,
    FactVesselQualityDaily,
    FactVesselRiskDaily,
    FactVesselRouteSegmentDaily,
    FactVesselTrajectoryDaily,
)
from app.models.base import Base
from app.models.vessel import (
    VesselAisSnapshot,
    VesselCandidateAnalysis,
    VesselCandidateAnalysisAnnotation,
    VesselCandidateAnalysisItem,
    VesselDataQualityIssue,
    VesselLatestPositionSnapshot,
    VesselNodeObservationItem,
    VesselNodeObservationVessel,
    VesselProfileSummary,
    VesselRiskSignal,
    VesselRouteSegmentMatchSample,
    VesselRouteSegmentObservationItem,
    VesselSpatialObservationSnapshot,
)
from app.modules.analysis.job_catalog import ANALYSIS_JOB_SPEC_BY_CODE
from app.modules.analysis.service import AnalysisDashboardService
from app.modules.analysis.statistics import AnalysisStatisticsService
from scripts.seed_builtin_dicts import BUILTIN_DICTS


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


def test_round9_openapi_models_jobs_and_dicts_exist() -> None:
    paths = app.openapi()["paths"]
    for path in [
        "/api/v1/analysis/vessels/assets",
        "/api/v1/analysis/vessels/trajectory",
        "/api/v1/analysis/vessels/quality",
        "/api/v1/analysis/vessels/risks",
        "/api/v1/analysis/vessels/candidate-fit",
        "/api/v1/analysis/regions/supply-demand",
    ]:
        assert "get" in paths[path]

    assert FactVesselAssetDaily.__tablename__ == "fact_vessel_asset_daily"
    assert FactRegionSupplyDemandDaily.__tablename__ == "fact_region_supply_demand_daily"
    assert {
        "ANALYSIS_VESSEL_ASSET_DAILY",
        "ANALYSIS_VESSEL_AIS_FRESHNESS_DAILY",
        "ANALYSIS_CANDIDATE_FIT_DAILY",
        "ANALYSIS_REGION_SUPPLY_DEMAND_DAILY",
    }.issubset(ANALYSIS_JOB_SPEC_BY_CODE)
    dict_codes = {item["dict_code"] for item in BUILTIN_DICTS}
    assert {
        "ANALYSIS_FACT_TYPE",
        "ANALYSIS_SOURCE_LAYER",
        "ANALYSIS_NOT_COMPUTABLE_REASON",
        "ANALYSIS_DEMAND_LAYER",
        "ANALYSIS_SUPPLY_LAYER",
    }.issubset(dict_codes)
    freshness = next(item for item in BUILTIN_DICTS if item["dict_code"] == "VESSEL_AIS_FRESHNESS_LEVEL")
    labels = {item["item_code"]: item["item_name"] for item in freshness["items"]}
    assert labels["STALE"] == "12-72 小时"
    assert labels["EXPIRED"] == "超过 72 小时"


@pytest.mark.asyncio
async def test_round9_fact_jobs_generate_source_coverage_and_not_computable_controls(session: AsyncSession) -> None:
    stat_date = date(2026, 5, 9)
    now = datetime(2026, 5, 9, 8, 0, 0)
    await _seed_round9_inputs(session, now)
    await session.commit()

    service = AnalysisStatisticsService(session)
    for job_code in [
        "ANALYSIS_VESSEL_ASSET_DAILY",
        "ANALYSIS_VESSEL_AIS_FRESHNESS_DAILY",
        "ANALYSIS_VESSEL_TRAJECTORY_DAILY",
        "ANALYSIS_VESSEL_NODE_DAILY",
        "ANALYSIS_VESSEL_ROUTE_SEGMENT_DAILY",
        "ANALYSIS_VESSEL_QUALITY_DAILY",
        "ANALYSIS_VESSEL_RISK_DAILY",
        "ANALYSIS_CANDIDATE_FIT_DAILY",
        "ANALYSIS_REGION_SUPPLY_DEMAND_DAILY",
    ]:
        result = await service.run(job_code, stat_date, stat_date)
        assert result.output_rows > 0

    asset = (await session.execute(select(FactVesselAssetDaily))).scalars().first()
    assert asset is not None
    assert asset.source_layer_code == "VESSEL_PROFILE_SUMMARY"
    assert asset.coverage_rate == Decimal("100.00")

    ais_rows = (await session.execute(select(FactVesselAisFreshnessDaily))).scalars().all()
    assert any(row.freshness_level == "EXPIRED" and row.confidence_level == "LOW" for row in ais_rows)
    assert any(row.unmatched_mmsi_count == 1 for row in ais_rows)

    trajectory = (await session.execute(select(FactVesselTrajectoryDaily))).scalars().first()
    assert trajectory is not None
    assert trajectory.gap_count == 2
    assert trajectory.confidence_level == "LOW"

    node = (await session.execute(select(FactVesselNodeDaily))).scalars().first()
    assert node is not None
    assert node.source_spatial_snapshot_id == "spatial-node-1"

    route_segment = (await session.execute(select(FactVesselRouteSegmentDaily))).scalars().first()
    assert route_segment is not None
    assert route_segment.direction_code == "FORWARD"
    assert route_segment.avg_direction_consistency == Decimal("35.00")
    assert route_segment.low_confidence_count == 1

    quality = (await session.execute(select(FactVesselQualityDaily))).scalars().first()
    assert quality is not None
    assert quality.opened_count + quality.closed_count >= 1

    risk_rows = (await session.execute(select(FactVesselRiskDaily))).scalars().all()
    assert any(row.risk_level == "UNKNOWN" and row.unknown_count == 1 for row in risk_rows)
    assert not any(row.risk_level == "LOW" and row.unknown_count for row in risk_rows)

    candidate_rows = (await session.execute(select(FactCandidateFitDaily))).scalars().all()
    assert not any(row.candidate_value_level == "HIGH" and row.candidate_item_count > 0 for row in candidate_rows)
    assert any(row.candidate_value_level == "LOW" and row.low_confidence_count == 1 for row in candidate_rows)

    supply_rows = (await session.execute(select(FactRegionSupplyDemandDaily))).scalars().all()
    assert supply_rows
    assert any("PROFILE_COVERAGE_GAP" in (row.not_computable_reasons_json or []) for row in supply_rows)
    assert any(row.tension_index is None for row in supply_rows)
    city_supply = next(row for row in supply_rows if row.city_code == "320100")
    assert city_supply.region_id == 99
    assert city_supply.demand_sample_count == 8
    assert city_supply.ais_supply_count == 2
    assert city_supply.trusted_supply == 1
    assert "SUPPLY_LAYER_MISSING" not in (city_supply.not_computable_reasons_json or [])
    assert not any(row.city_code is None and row.trusted_supply > 0 for row in supply_rows)

    asset_count = await session.scalar(select(func.count()).select_from(FactVesselAssetDaily))
    skip_result = await service.run("ANALYSIS_VESSEL_ASSET_DAILY", stat_date, stat_date)
    assert skip_result.extra["reason"] == "EXISTING_SOURCE_VERSION_PRESERVED"
    assert await session.scalar(select(func.count()).select_from(FactVesselAssetDaily)) == asset_count
    rebuild_result = await service.run("ANALYSIS_VESSEL_ASSET_DAILY", stat_date, stat_date, force_rebuild=True)
    assert rebuild_result.output_rows == asset_count


@pytest.mark.asyncio
async def test_round9_api_responses_surface_metric_evidence(session: AsyncSession) -> None:
    stat_date = date(2026, 5, 9)
    now = datetime(2026, 5, 9, 8, 0, 0)
    await _seed_round9_inputs(session, now)
    await session.commit()
    service = AnalysisStatisticsService(session)
    await service.run("ANALYSIS_VESSEL_ASSET_DAILY", stat_date, stat_date)
    await service.run("ANALYSIS_VESSEL_AIS_FRESHNESS_DAILY", stat_date, stat_date)
    await service.run("ANALYSIS_REGION_SUPPLY_DEMAND_DAILY", stat_date, stat_date)

    dashboard = AnalysisDashboardService(session)
    asset_response = await dashboard.vessel_asset_analysis(stat_date, stat_date)
    supply_response = await dashboard.region_supply_demand_analysis(stat_date, stat_date)

    assert asset_response.metrics[0].source_layer_code == "VESSEL_PROFILE_SUMMARY"
    assert asset_response.metrics[0].coverage_rate == 100
    assert asset_response.source_status
    assert asset_response.source_status[0].coverage_rate == 100
    assert supply_response.metrics
    assert any("PROFILE_COVERAGE_GAP" in item.not_computable_reasons for item in supply_response.source_status)


@pytest.mark.asyncio
async def test_round9_all_daily_orchestrates_children_and_isolates_failure(session: AsyncSession) -> None:
    stat_date = date(2026, 5, 9)
    now = datetime(2026, 5, 9, 8, 0, 0)
    await _seed_round9_inputs(session, now)
    await session.commit()
    service = AnalysisStatisticsService(session)

    async def fail_quality(*args, **kwargs):
        _ = args, kwargs
        raise RuntimeError("quality source offline")

    service.run_vessel_quality_daily = fail_quality  # type: ignore[method-assign]

    result = await service.run("ANALYSIS_ALL_DAILY", stat_date, stat_date, force_rebuild=True)
    child_codes = {item["job_code"] for item in result.extra["children"]}
    failures = result.extra["failures"]

    assert "ANALYSIS_VESSEL_ASSET_DAILY" in child_codes
    assert "ANALYSIS_REGION_SUPPLY_DEMAND_DAILY" in child_codes
    assert any(item["job_code"] == "ANALYSIS_VESSEL_QUALITY_DAILY" for item in failures)
    assert "fact_region_supply_demand_daily" in result.target_tables
    assert result.output_rows > 0


async def _seed_round9_inputs(session: AsyncSession, now: datetime) -> None:
    stat_date = now.date()
    session.add_all(
        [
            VesselProfileSummary(
                vessel_profile_id=1,
                ship_name="测试船一",
                current_mmsi="412000001",
                ship_type_code="DRY_BULK",
                ship_type_name="干散货船",
                deadweight_ton=Decimal("3500"),
                profile_completeness_rate=Decimal("95.00"),
                data_quality_score=Decimal("92.00"),
                data_quality_level="HIGH",
                identity_confidence_level="HIGH",
                contact_trust_level="HIGH",
                subject_consistency_level="HIGH",
                quality_issue_count=0,
                missing_field_count=0,
                conflict_count=0,
                risk_level="LOW",
                certificate_missing_count=0,
                certificate_expiring_count=0,
                certificate_expired_count=0,
                latest_position_time=now - timedelta(hours=1),
                latest_city_code="320100",
                latest_city_name="南京市",
                ais_freshness_level="FRESH",
                source_layer="PROFILE_SUMMARY",
                coverage_rate=Decimal("95.00"),
                summary_status_code="READY",
                summary_version="ROUND_3_V1",
                refreshed_at=now,
                source_updated_at=now,
                created_at=now,
                updated_at=now,
            ),
            VesselProfileSummary(
                vessel_profile_id=2,
                ship_name="测试船二",
                current_mmsi="412000002",
                ship_type_code="DRY_BULK",
                data_quality_level="LOW",
                identity_confidence_level="LOW",
                contact_trust_level="UNKNOWN",
                subject_consistency_level="UNKNOWN",
                quality_issue_count=2,
                missing_field_count=1,
                conflict_count=1,
                risk_level="UNKNOWN",
                certificate_missing_count=1,
                certificate_expiring_count=0,
                certificate_expired_count=0,
                latest_position_time=now - timedelta(days=4),
                latest_city_code="320100",
                latest_city_name="南京市",
                ais_freshness_level="EXPIRED",
                source_layer="PROFILE_SUMMARY",
                coverage_rate=Decimal("45.00"),
                summary_status_code="READY",
                summary_version="ROUND_3_V1",
                refreshed_at=now,
                source_updated_at=now,
                created_at=now,
                updated_at=now,
            ),
            VesselAisSnapshot(
                snapshot_id="ais-1",
                query_hash="q1",
                status_code="READY",
                generated_at=now,
                expires_at=now + timedelta(hours=1),
                scanned_profile_count=2,
                queried_mmsi_count=3,
                matched_profile_count=1,
                matched_position_count=1,
                unmatched_mmsi_count=1,
                invalid_position_count=1,
                coverage_rate=Decimal("45.00"),
                freshness_distribution_json={"FRESH": 1, "EXPIRED": 1},
                uncertainty_notes_json=["覆盖率不足"],
                created_at=now,
                updated_at=now,
            ),
            VesselLatestPositionSnapshot(
                snapshot_id="ais-1",
                vessel_profile_id=1,
                mmsi="412000001",
                position_time=now - timedelta(hours=1),
                freshness_level="FRESH",
                match_status_code="MATCHED_PROFILE",
                city_code="320100",
                city_name="南京市",
                valid_position_flag=True,
                created_at=now,
            ),
            VesselLatestPositionSnapshot(
                snapshot_id="ais-1",
                vessel_profile_id=None,
                mmsi="412000999",
                position_time=now - timedelta(days=4),
                freshness_level="EXPIRED",
                match_status_code="UNMATCHED_MMSI",
                city_code="320100",
                city_name="南京市",
                valid_position_flag=True,
                created_at=now,
            ),
            VesselSpatialObservationSnapshot(
                snapshot_id="spatial-node-1",
                source_snapshot_id="ais-1",
                observation_type_code="NODE",
                query_hash="node-q",
                status_code="READY",
                stat_time=now,
                generated_at=now,
                expires_at=now + timedelta(hours=1),
                coverage_rate=Decimal("80.00"),
                confidence_level="HIGH",
                active_vessel_count=1,
                matched_position_count=1,
                created_at=now,
                updated_at=now,
            ),
            VesselNodeObservationItem(
                snapshot_id="spatial-node-1",
                node_id=10,
                node_name="测试码头",
                city_code="320100",
                radius_km=Decimal("2.00"),
                active_vessel_count=1,
                stay_vessel_count=1,
                passby_vessel_count=0,
                coverage_rate=Decimal("80.00"),
                confidence_level="HIGH",
                latest_position_time=now,
                created_at=now,
            ),
            VesselNodeObservationVessel(
                snapshot_id="spatial-node-1",
                node_id=10,
                vessel_profile_id=1,
                mmsi="412000001",
                ship_name="测试船一",
                ship_type_code="DRY_BULK",
                deadweight_ton=Decimal("3500"),
                freshness_level="FRESH",
                match_status_code="STAY",
                stay_duration_minutes=180,
                position_time=now,
                created_at=now,
            ),
            VesselSpatialObservationSnapshot(
                snapshot_id="spatial-route-1",
                source_snapshot_id="ais-1",
                observation_type_code="ROUTE",
                query_hash="route-q",
                status_code="PARTIAL",
                stat_time=now,
                generated_at=now,
                expires_at=now + timedelta(hours=1),
                coverage_rate=Decimal("40.00"),
                confidence_level="LOW",
                active_vessel_count=1,
                not_computable_reasons_json=["TRACK_SAMPLE_INSUFFICIENT"],
                created_at=now,
                updated_at=now,
            ),
            VesselRouteSegmentObservationItem(
                snapshot_id="spatial-route-1",
                route_id=20,
                line_id=21,
                segment_id=22,
                segment_no=1,
                segment_name="测试航段",
                geometry_status_code="READY",
                matched_vessel_count=1,
                active_vessel_count=1,
                point_count=2,
                gap_count=2,
                covered_ratio=Decimal("40.00"),
                average_match_score=Decimal("45.00"),
                coverage_rate=Decimal("40.00"),
                confidence_level="LOW",
                not_computable_reasons_json=["TRACK_SAMPLE_INSUFFICIENT"],
                created_at=now,
            ),
            VesselRouteSegmentMatchSample(
                snapshot_id="spatial-route-1",
                segment_id=22,
                vessel_profile_id=2,
                mmsi="412000002",
                ship_name="测试船二",
                ship_type_code="DRY_BULK",
                match_score=Decimal("45.00"),
                covered_ratio=Decimal("40.00"),
                direction_consistency=Decimal("35.00"),
                point_count=2,
                gap_count=2,
                latest_position_time=now,
                freshness_level="EXPIRED",
                confidence_level="LOW",
                match_status_code="MATCHED",
                created_at=now,
            ),
            VesselDataQualityIssue(
                issue_type_code="MMSI_CONFLICT",
                severity_code="HIGH",
                affected_object_type="VESSEL_PROFILE",
                affected_object_id="2",
                vessel_profile_id=2,
                fingerprint="quality-1",
                evidence_source="TEST",
                status_code="OPEN",
                created_at=now,
                updated_at=now,
            ),
            VesselRiskSignal(
                vessel_profile_id=2,
                risk_type_code="CERTIFICATE_MISSING",
                risk_level="UNKNOWN",
                status_code="OPEN",
                confidence_level="UNKNOWN",
                fingerprint="risk-1",
                first_detected_at=now,
                last_detected_at=now,
                created_at=now,
                updated_at=now,
            ),
            VesselCandidateAnalysis(
                id=100,
                context_type_code="NODE",
                source_layer_code="MANUAL",
                origin_node_id=10,
                query_hash="candidate-q",
                status_code="READY",
                source_ais_snapshot_id="ais-1",
                source_spatial_snapshot_id="spatial-node-1",
                coverage_rate=Decimal("40.00"),
                confidence_level="LOW",
                candidate_count=1,
                low_confidence_count=1,
                generated_at=now,
                created_at=now,
                updated_at=now,
            ),
            VesselCandidateAnalysisItem(
                analysis_id=100,
                vessel_profile_id=2,
                mmsi="412000002",
                ship_name="测试船二",
                ship_type_code="DRY_BULK",
                latest_position_time=now - timedelta(days=4),
                ais_freshness_level="EXPIRED",
                risk_level="UNKNOWN",
                quality_level="LOW",
                fit_score=Decimal("91.00"),
                candidate_value_level="HIGH",
                confidence_level="LOW",
                not_computable_reasons_json=["RISK_UNKNOWN"],
                risk_reasons_json=["RISK_UNKNOWN"],
                created_at=now,
            ),
            VesselCandidateAnalysisAnnotation(
                analysis_id=100,
                item_id=1,
                annotation_type_code="DATA_INSUFFICIENT",
                comment="数据不足",
                created_at=now,
            ),
            FactFreightCityDaily(
                stat_date=stat_date,
                city_code="320100",
                city_name="南京市",
                primary_region_id=99,
                freight_count=8,
                inbound_count=4,
                outbound_count=4,
                total_tonnage=Decimal("1000.00"),
                avg_unit_price=Decimal("50.00"),
                heat_value=Decimal("10.00"),
                data_version="TEST",
                generated_at=now,
            ),
        ]
    )
    await session.flush()
