from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import BigInteger

import app.models  # noqa: F401
from app.models.address import TransportNode
from app.models.base import Base
from app.models.commodity import CommodityStandard
from app.models.freight import (
    Freight,
    FreightBatchTask,
    FreightCandidate,
    FreightCandidateManualFeedback,
    FreightClue,
    FreightNormalizationSuggestion,
)
from app.models.route import ShippingRoute
from app.models.vessel import VesselCandidateAnalysis
from app.modules.freight.opportunity_service import ShippingOpportunityService


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


@pytest.mark.asyncio
async def test_opportunity_detail_includes_source_quality_route_capacity_and_price(session: AsyncSession) -> None:
    now = datetime.utcnow()
    session.add_all(
        [
            TransportNode(
                id=11,
                code="N-11",
                name="南京港",
                node_type_code="PORT",
                province_code="320000",
                city_code="320100",
                city_region_id=1,
                lifecycle_status_code="ACTIVE",
            ),
            TransportNode(
                id=22,
                code="N-22",
                name="芜湖港",
                node_type_code="PORT",
                province_code="340000",
                city_code="340200",
                city_region_id=2,
                lifecycle_status_code="ACTIVE",
            ),
            CommodityStandard(id=33, type_id=1, code="COAL", name="动力煤", main_unit_code="TON", source_type_code="SEED"),
            ShippingRoute(
                id=44,
                code="R-44",
                name="南京-芜湖",
                transport_org_type_code="WATERWAY",
                origin_region_id=101,
                destination_region_id=202,
            ),
            FreightBatchTask(
                id=55,
                batch_no="FBT-55",
                raw_text="南京港装动力煤到芜湖港，2000吨，88元/吨",
                status_code="PARSED",
                prompt_version="prompt-v5",
                ai_pipeline_version="pipeline-v5",
            ),
            FreightClue(
                id=66,
                clue_no="FCL-66",
                source_type_code="WECHAT",
                source_channel_code="WECHAT_TEXT",
                source_batch_id=55,
                segment_index=1,
                raw_text="南京港装动力煤到芜湖港",
                context_summary="微信群发布货源",
                status_code="CONFIRMED",
            ),
            FreightCandidate(
                id=77,
                candidate_no="FCA-77",
                source_type_code="WECHAT",
                source_channel_code="WECHAT_TEXT",
                source_batch_id=55,
                clue_id=66,
                cargo_title="南京港到芜湖动力煤",
                commodity_standard_id=33,
                commodity_match_level_code="STANDARD",
                estimated_tonnage=Decimal("2000"),
                unit_price=Decimal("88"),
                origin_node_id=11,
                destination_node_id=22,
                origin_match_level_code="NODE",
                destination_match_level_code="NODE",
                origin_region_id_cache=101,
                destination_region_id_cache=202,
                confidence_score=Decimal("0.92"),
                completeness_score=Decimal("0.95"),
                ai_review_status_code="PASS",
                ai_warning_json={"warnings": ["吨位上限需确认"]},
                availability_status_code="READY",
                status_code="CONFIRMED",
                confirmed_freight_id=88,
                confirmed_at=now,
            ),
            Freight(
                id=88,
                freight_no="FR-88",
                source_type_code="WECHAT",
                source_channel_code="WECHAT_TEXT",
                source_batch_id=55,
                source_clue_id=66,
                source_candidate_id=77,
                cargo_title="南京港到芜湖动力煤",
                commodity_standard_id=33,
                commodity_match_level_code="STANDARD",
                estimated_tonnage=Decimal("2000"),
                unit_price=Decimal("88"),
                price_unit="元/吨",
                origin_node_id=11,
                destination_node_id=22,
                origin_match_level_code="NODE",
                destination_match_level_code="NODE",
                origin_region_id_cache=101,
                destination_region_id_cache=202,
                status_code="PUBLISHED",
                hall_status_code="NOT_LISTED",
                audit_status="APPROVED",
            ),
            FreightCandidateManualFeedback(
                id=99,
                candidate_id=77,
                action_code="CONFIRM",
                feedback_remark="确认入库",
                operator_id=7,
                operated_at=now,
                created_at=now,
            ),
            VesselCandidateAnalysis(
                id=111,
                context_type_code="FREIGHT_SAMPLE",
                source_layer_code="AIS",
                freight_id=88,
                query_hash="hash-111",
                status_code="READY",
                coverage_rate=Decimal("0.85"),
                confidence_level="HIGH",
                candidate_count=3,
                low_confidence_count=1,
                generated_at=now,
                created_at=now,
                updated_at=now,
            ),
            FreightNormalizationSuggestion(
                id=222,
                freight_id=88,
                suggestion_type_code="ORIGIN",
                raw_text="南京",
                current_level_code="CITY",
                suggested_level_code="NODE",
                suggested_node_id=11,
                confidence_score=Decimal("0.78"),
                status_code="PENDING",
                match_basis_json={"basis": "节点别名命中"},
            ),
        ]
    )
    await session.commit()

    detail = await ShippingOpportunityService(session).get_opportunity(88)

    assert detail.route_evidence.status_code == "READY"
    assert detail.route_evidence.route_id == 44
    assert detail.capacity_evidence.analysis_id == 111
    assert detail.capacity_evidence.candidate_count == 3
    assert detail.pricing_evidence.status_code == "HAS_PRICE_EVIDENCE"
    assert detail.pricing_evidence.uses_demo_data is False
    assert detail.source_evidence.batch_no == "FBT-55"
    assert detail.source_evidence.candidate_no == "FCA-77"
    assert detail.source_evidence.ai_warning_count == 1
    assert detail.source_evidence.confirmation_count == 1
    assert detail.cleaning_issues[0].impact_field_code == "origin_node_id"
    cleaning_action = next(item for item in detail.actions if item.action_code == "OPEN_FREIGHT_CLEANING")
    quote_action = next(item for item in detail.actions if item.action_code == "OPEN_QUOTE_SIMULATOR")
    assert cleaning_action.query["keyword"] == "FR-88"
    assert cleaning_action.enabled is True
    assert quote_action.query["current_quote"] == Decimal("88")
    assert quote_action.enabled is True
    assert "commodity_standard_id" in quote_action.required_fields


@pytest.mark.asyncio
async def test_opportunity_detail_explains_not_computable_fields(session: AsyncSession) -> None:
    session.add(
        Freight(
            id=188,
            freight_no="FR-188",
            source_type_code="MANUAL",
            source_channel_code="MANUAL",
            raw_origin_text="未知码头",
            raw_destination_text="未知港",
            cargo_title="缺字段货源",
            raw_commodity_name="砂石",
            commodity_match_level_code="RAW",
            raw_tonnage_text="待定",
            status_code="PUBLISHED",
            hall_status_code="NOT_LISTED",
            audit_status="PENDING",
        )
    )
    await session.commit()

    detail = await ShippingOpportunityService(session).get_opportunity(188)

    assert detail.route_evidence.status_code == "NOT_COMPUTABLE"
    assert "ORIGIN_NODE_MISSING" in detail.route_evidence.not_computable_reasons
    assert detail.capacity_evidence.status_code == "NOT_COMPUTABLE"
    assert detail.pricing_evidence.status_code == "NOT_COMPUTABLE"
    assert detail.quality.confidence_level == "LOW"
    assert {"ORIGIN_NODE_MISSING", "DESTINATION_NODE_MISSING", "COMMODITY_STANDARD_MISSING", "TONNAGE_MISSING", "PRICE_MISSING"}.issubset(
        set(detail.quality.not_computable_reasons)
    )
    disabled = next(item for item in detail.actions if item.action_code == "OPEN_CANDIDATE_VESSELS")
    assert disabled.enabled is False
    assert disabled.disabled_reason
