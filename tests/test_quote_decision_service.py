from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import BigInteger

import app.models  # noqa: F401
from app.models.address import TransportNode
from app.models.analysis import PricingDecisionRecord
from app.models.base import Base
from app.models.commodity import CommodityStandard
from app.models.freight import Freight, FreightBatchTask
from app.modules.analysis.pricing_decision_service import PricingDecisionService
from app.modules.analysis.schemas import QuoteDecisionRequest


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


async def _seed_quote_freight(session: AsyncSession, *, owner_quote: str = "55") -> None:
    now = datetime.utcnow()
    session.add_all(
        [
            TransportNode(
                id=11,
                code="N-11",
                name="太仓港",
                node_type_code="PORT",
                province_code="320000",
                city_code="320500",
                city_region_id=1,
                longitude=Decimal("121.10"),
                latitude=Decimal("31.45"),
                lifecycle_status_code="ACTIVE",
            ),
            TransportNode(
                id=22,
                code="N-22",
                name="芜湖朱家桥",
                node_type_code="PORT",
                province_code="340000",
                city_code="340200",
                city_region_id=2,
                longitude=Decimal("118.36"),
                latitude=Decimal("31.34"),
                lifecycle_status_code="ACTIVE",
            ),
            CommodityStandard(id=33, type_id=1, code="SAND", name="机制砂", main_unit_code="TON", source_type_code="SEED"),
            FreightBatchTask(
                id=44,
                batch_no="FBT-DEMO-Q1",
                source_type_code="WECHAT",
                source_channel_code="WECHAT_TEXT",
                raw_text=f"太仓港到芜湖朱家桥机制砂，2200吨，货主报价88元/吨，船主/船户报价{owner_quote}元/吨；高级配置：账期15天，保险0.3元/吨，服务费2%。",
                status_code="PARSED",
                ai_semantic_map_json={"owner_quote_evidence": f"船主/船户报价{owner_quote}元/吨"},
            ),
            Freight(
                id=55,
                freight_no="FR-DEMO-Q1",
                source_type_code="LOCAL_DEMO",
                source_channel_code="WECHAT_TEXT",
                source_batch_id=44,
                cargo_title="太仓港到芜湖朱家桥机制砂",
                commodity_standard_id=33,
                commodity_match_level_code="STANDARD",
                estimated_tonnage=Decimal("2200"),
                unit_price=Decimal("88"),
                price_unit="元/吨",
                origin_node_id=11,
                destination_node_id=22,
                origin_city_code="320500",
                destination_city_code="340200",
                origin_match_level_code="NODE",
                destination_match_level_code="NODE",
                status_code="PUBLISHED",
                hall_status_code="NOT_LISTED",
                audit_status="APPROVED",
                loading_time_from=now,
            ),
        ]
    )
    await session.commit()


@pytest.mark.asyncio
async def test_quote_context_parses_owner_quote_and_decision_persists_record(session: AsyncSession) -> None:
    await _seed_quote_freight(session)
    service = PricingDecisionService(session)

    context = await service.quote_context(55)
    assert context.owner_quote == 55
    assert context.advanced_config_text is not None
    assert context.advanced_config == {"credit_days": 15, "insurance_fee_per_ton": 0.3, "service_fee_rate": 0.02}

    response = await service.decide_quote(
        QuoteDecisionRequest(
            freight_id=55,
            owner_quote=context.owner_quote,
            route_status_code="READY",
            route_distance_km=120,
            route_geometry_source="AMMS",
        )
    )

    assert response.record_id
    assert response.record_id > 0
    assert response.record_type_code == "QUOTE_DECISION"
    assert response.decision_code == "ACCEPT"
    assert response.cost_floor is not None
    assert response.recommended_quote is not None
    record = await session.scalar(select(PricingDecisionRecord).where(PricingDecisionRecord.id == response.record_id))
    assert record is not None
    assert record.record_type_code == "QUOTE_DECISION"
    assert record.freight_id == 55
    assert record.route_evidence_json["distance_km"] == 120


@pytest.mark.asyncio
async def test_quote_decision_rejects_when_owner_quote_breaks_margin(session: AsyncSession) -> None:
    await _seed_quote_freight(session, owner_quote="96")
    response = await PricingDecisionService(session).decide_quote(
        QuoteDecisionRequest(
            freight_id=55,
            owner_quote=96,
            route_status_code="READY",
            route_distance_km=120,
            route_geometry_source="AMMS",
        )
    )

    assert response.decision_code == "REJECT"
    assert response.gross_profit is not None
    assert response.gross_profit < 0


@pytest.mark.asyncio
async def test_quote_decision_requires_route_tonnage_and_commodity(session: AsyncSession) -> None:
    response = await PricingDecisionService(session).decide_quote(
        QuoteDecisionRequest(
            origin_node_id=11,
            destination_node_id=22,
            current_quote=88,
            owner_quote=55,
        )
    )

    assert response.decision_code == "NOT_COMPUTABLE"
    assert {"COMMODITY_STANDARD_MISSING", "TONNAGE_MISSING"}.issubset(set(response.not_computable_reasons))


@pytest.mark.asyncio
async def test_quote_decision_requires_owner_quote_but_still_persists_record(session: AsyncSession) -> None:
    await _seed_quote_freight(session, owner_quote="55")

    response = await PricingDecisionService(session).decide_quote(
        QuoteDecisionRequest(
            freight_id=55,
            route_status_code="READY",
            route_distance_km=120,
            route_geometry_source="AMMS",
        )
    )

    assert response.record_id > 0
    assert response.decision_code == "NOT_COMPUTABLE"
    assert "OWNER_QUOTE_MISSING" in response.not_computable_reasons
