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
from app.core.config import settings
from app.models.address import TransportNode
from app.models.base import Base
from app.models.commodity import CommodityStandard
from app.models.freight import Freight
from app.modules.analysis.pricing_decision_service import PricingDecisionService
from app.modules.analysis.schemas import RateEstimateRequest


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


async def _seed_foundation(session: AsyncSession) -> None:
    session.add_all(
        [
            TransportNode(id=1, code="N1", name="太仓港", node_type_code="PORT", province_code="320000", city_code="320500", city_region_id=1, longitude=Decimal("121.10"), latitude=Decimal("31.45"), lifecycle_status_code="ACTIVE"),
            TransportNode(id=2, code="N2", name="芜湖港", node_type_code="PORT", province_code="340000", city_code="340200", city_region_id=2, longitude=Decimal("118.36"), latitude=Decimal("31.34"), lifecycle_status_code="ACTIVE"),
            TransportNode(id=3, code="N3", name="苏州码头", node_type_code="PORT", province_code="320000", city_code="320500", city_region_id=1, longitude=Decimal("120.62"), latitude=Decimal("31.31"), lifecycle_status_code="ACTIVE"),
            TransportNode(id=4, code="N4", name="芜湖散货码头", node_type_code="PORT", province_code="340000", city_code="340200", city_region_id=2, longitude=Decimal("118.42"), latitude=Decimal("31.29"), lifecycle_status_code="ACTIVE"),
            TransportNode(id=5, code="N5", name="湖州港", node_type_code="PORT", province_code="330000", city_code="330500", city_region_id=3, longitude=Decimal("120.10"), latitude=Decimal("30.90"), lifecycle_status_code="ACTIVE"),
            TransportNode(id=6, code="N6", name="南京港", node_type_code="PORT", province_code="320000", city_code="320100", city_region_id=4, longitude=Decimal("118.80"), latitude=Decimal("32.05"), lifecycle_status_code="ACTIVE"),
            CommodityStandard(id=10, type_id=1, code="SAND", name="机制砂", main_unit_code="TON", source_type_code="SEED"),
            CommodityStandard(id=20, type_id=1, code="STEEL", name="钢材", main_unit_code="TON", source_type_code="SEED"),
        ]
    )
    await session.commit()


def _freight(
    freight_id: int,
    *,
    origin_node_id: int,
    destination_node_id: int,
    commodity_id: int,
    price: str,
    tonnage: str = "2000",
    origin_city_code: str = "320500",
    destination_city_code: str = "340200",
    freight_no: str | None = None,
) -> Freight:
    now = datetime.utcnow() - timedelta(days=freight_id)
    return Freight(
        id=freight_id,
        freight_no=freight_no or f"FR-SAMPLE-{freight_id}",
        source_type_code="WECHAT",
        source_channel_code="WECHAT_TEXT",
        cargo_title=f"样本货源 {freight_id}",
        commodity_standard_id=commodity_id,
        commodity_match_level_code="STANDARD",
        estimated_tonnage=Decimal(tonnage),
        unit_price=Decimal(price),
        price_unit="元/吨",
        origin_node_id=origin_node_id,
        destination_node_id=destination_node_id,
        origin_city_code=origin_city_code,
        destination_city_code=destination_city_code,
        origin_match_level_code="NODE",
        destination_match_level_code="NODE",
        status_code="PUBLISHED",
        hall_status_code="NOT_LISTED",
        audit_status="APPROVED",
        published_at=now,
    )


@pytest.mark.asyncio
async def test_rate_estimator_uses_exact_node_commodity_samples(session: AsyncSession) -> None:
    await _seed_foundation(session)
    session.add_all(
        [
            _freight(101, origin_node_id=1, destination_node_id=2, commodity_id=10, price="82"),
            _freight(102, origin_node_id=1, destination_node_id=2, commodity_id=10, price="86"),
            _freight(103, origin_node_id=1, destination_node_id=2, commodity_id=10, price="90"),
        ]
    )
    await session.commit()

    response = await PricingDecisionService(session).estimate_rate(
        RateEstimateRequest(
            origin_node_id=1,
            destination_node_id=2,
            commodity_standard_id=10,
            tonnage=2100,
            route_status_code="READY",
            route_distance_km=220,
        )
    )

    assert response.record_type_code == "RATE_ESTIMATE"
    assert response.computable is True
    assert response.fallback_level_code == "EXACT_NODE_COMMODITY"
    assert response.sample_size == 3
    assert response.estimated_low_quote is not None
    assert response.estimated_high_quote is not None
    assert response.factor_breakdown
    assert response.comparable_samples
    assert response.fallback_trace[0]["level_code"] == "EXACT_NODE_COMMODITY"


@pytest.mark.asyncio
async def test_rate_estimator_falls_back_to_city_flow_samples(session: AsyncSession) -> None:
    await _seed_foundation(session)
    session.add(
        _freight(200, origin_node_id=1, destination_node_id=2, commodity_id=10, price="88", freight_no="FR-TARGET-200")
    )
    session.add_all(
        [
            _freight(201, origin_node_id=3, destination_node_id=4, commodity_id=10, price="80"),
            _freight(202, origin_node_id=3, destination_node_id=4, commodity_id=10, price="83"),
            _freight(203, origin_node_id=3, destination_node_id=4, commodity_id=10, price="84"),
            _freight(204, origin_node_id=3, destination_node_id=4, commodity_id=10, price="87"),
            _freight(205, origin_node_id=3, destination_node_id=4, commodity_id=10, price="89"),
        ]
    )
    await session.commit()

    response = await PricingDecisionService(session).estimate_rate(RateEstimateRequest(freight_id=200, tonnage=2100))

    assert response.computable is True
    assert response.fallback_level_code == "CITY_COMMODITY"
    assert response.coverage_rate == 80
    assert response.factor_breakdown


@pytest.mark.asyncio
async def test_rate_estimator_falls_back_to_distance_band(session: AsyncSession) -> None:
    await _seed_foundation(session)
    session.add_all(
        [
            _freight(301, origin_node_id=5, destination_node_id=6, commodity_id=20, price="70", origin_city_code="330500", destination_city_code="320100"),
            _freight(302, origin_node_id=5, destination_node_id=6, commodity_id=20, price="72", origin_city_code="330500", destination_city_code="320100"),
            _freight(303, origin_node_id=5, destination_node_id=6, commodity_id=20, price="74", origin_city_code="330500", destination_city_code="320100"),
            _freight(304, origin_node_id=5, destination_node_id=6, commodity_id=20, price="76", origin_city_code="330500", destination_city_code="320100"),
            _freight(305, origin_node_id=5, destination_node_id=6, commodity_id=20, price="78", origin_city_code="330500", destination_city_code="320100"),
        ]
    )
    await session.commit()

    response = await PricingDecisionService(session).estimate_rate(
        RateEstimateRequest(
            origin_node_id=1,
            destination_node_id=2,
            commodity_standard_id=10,
            tonnage=2000,
            route_status_code="READY",
            route_distance_km=230,
        )
    )

    assert response.computable is True
    assert response.fallback_level_code == "DISTANCE_BAND"
    assert response.sample_size == 5
    assert any(item["code"] == "distance_similarity" for item in response.factor_breakdown)


@pytest.mark.asyncio
async def test_rate_estimator_returns_not_computable_when_samples_are_unusable(session: AsyncSession, monkeypatch) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "production")
    await _seed_foundation(session)
    session.add(
        _freight(
            401,
            origin_node_id=1,
            destination_node_id=2,
            commodity_id=10,
            price="88",
            freight_no="FR-DEMO-PROD-401",
        )
    )
    await session.commit()

    response = await PricingDecisionService(session).estimate_rate(
        RateEstimateRequest(
            origin_node_id=1,
            destination_node_id=2,
            commodity_standard_id=10,
            tonnage=2000,
            route_status_code="READY",
            route_distance_km=220,
        )
    )

    assert response.computable is False
    assert "PRICE_SAMPLE_MISSING" in response.not_computable_reasons


@pytest.mark.asyncio
async def test_rate_estimator_excludes_price_outliers_and_reports_quality(session: AsyncSession) -> None:
    await _seed_foundation(session)
    session.add_all(
        [
            _freight(501, origin_node_id=1, destination_node_id=2, commodity_id=10, price="82"),
            _freight(502, origin_node_id=1, destination_node_id=2, commodity_id=10, price="84"),
            _freight(503, origin_node_id=1, destination_node_id=2, commodity_id=10, price="85"),
            _freight(504, origin_node_id=1, destination_node_id=2, commodity_id=10, price="86"),
            _freight(505, origin_node_id=1, destination_node_id=2, commodity_id=10, price="87"),
            _freight(506, origin_node_id=1, destination_node_id=2, commodity_id=10, price="220"),
        ]
    )
    await session.commit()

    response = await PricingDecisionService(session).estimate_rate(
        RateEstimateRequest(
            origin_node_id=1,
            destination_node_id=2,
            commodity_standard_id=10,
            tonnage=2000,
            route_status_code="READY",
            route_distance_km=220,
        )
    )

    assert response.computable is True
    assert response.recommended_quote is not None
    assert response.recommended_quote < 120
    assert "PRICE_OUTLIER_EXCLUDED" in response.quality_warnings
