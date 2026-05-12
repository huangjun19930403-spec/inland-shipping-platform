from __future__ import annotations

from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import BigInteger

import app.models  # noqa: F401
from app.core.exceptions import ValidationError
from app.models.address import AdminRegion
from app.models.base import Base
from app.models.common import CodeSequence
from app.models.freight import Freight
from app.models.route import ShippingRoute, ShippingRouteLine, ShippingRouteLineTrack, ShippingRoutePlan
from app.modules.address.schemas import TransportNodeCreateRequest
from app.modules.address.service import TransportNodeService
from app.modules.freight.service import FreightService
from app.modules.route.schemas import RouteListQuery
from app.modules.route.service import ShippingRouteService


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


def _node_sequence() -> CodeSequence:
    return CodeSequence(
        biz_code="NODE_CODE",
        biz_name="节点编码",
        target_table="transport_node",
        target_column="code",
        prefix="ND",
        current_value=0,
        value_length=4,
        step=1,
        reset_rule="NONE",
        is_enabled=True,
    )


async def _seed_regions(session: AsyncSession) -> None:
    session.add_all(
        [
            AdminRegion(code="320000", name="江苏省", level=1, status=1),
            AdminRegion(code="340000", name="安徽省", level=1, status=1),
            AdminRegion(code="320100", name="南京市", level=2, parent_code="320000", province_code="320000", city_code="320100", status=1),
            AdminRegion(code="340200", name="芜湖市", level=2, parent_code="340000", province_code="340000", city_code="340200", status=1),
        ]
    )
    await session.commit()


@pytest.mark.asyncio
async def test_transport_node_rejects_mismatched_province_city(session: AsyncSession) -> None:
    await _seed_regions(session)
    session.add(_node_sequence())
    await session.commit()

    payload = TransportNodeCreateRequest(
        name="审计测试错配节点",
        node_type_code="PORT",
        province_code="320000",
        city_code="340200",
        lifecycle_status_code="ACTIVE",
    )

    with pytest.raises(ValidationError, match="行政区层级不一致"):
        await TransportNodeService(session).create_node(payload)


@pytest.mark.asyncio
async def test_route_list_filters_and_totals_are_query_level(session: AsyncSession) -> None:
    route_a = ShippingRoute(
        code="RT-A",
        name="审计测试有主路线",
        transport_org_type_code="SINGLE_MODE",
        origin_region_id=1,
        destination_region_id=2,
        audit_status="APPROVED",
    )
    route_b = ShippingRoute(
        code="RT-B",
        name="审计测试失败轨迹",
        transport_org_type_code="SINGLE_MODE",
        origin_region_id=1,
        destination_region_id=3,
        audit_status="APPROVED",
    )
    route_c = ShippingRoute(
        code="RT-C",
        name="审计测试无方案",
        transport_org_type_code="SINGLE_MODE",
        origin_region_id=2,
        destination_region_id=3,
        audit_status="APPROVED",
    )
    session.add_all([route_a, route_b, route_c])
    await session.flush()
    plan_a = ShippingRoutePlan(route_id=route_a.id, plan_code="PA", plan_name="标准方案", plan_type_code="STANDARD")
    plan_b = ShippingRoutePlan(route_id=route_b.id, plan_code="PB", plan_name="低水位方案", plan_type_code="SEASONAL")
    session.add_all([plan_a, plan_b])
    await session.flush()
    line_a = ShippingRouteLine(
        plan_id=plan_a.id,
        line_code="LA",
        line_name="主路线",
        line_role_code="MAIN",
        track_status="READY",
        track_generated_at=datetime(2026, 5, 1, 8, 0, 0),
    )
    line_b = ShippingRouteLine(
        plan_id=plan_b.id,
        line_code="LB",
        line_name="失败路线",
        line_role_code="ALTERNATE",
        track_status="FAILED",
        track_generated_at=datetime(2026, 5, 2, 8, 0, 0),
    )
    session.add_all([line_a, line_b])
    await session.flush()
    session.add(ShippingRouteLineTrack(line_id=line_b.id, track_status="FAILED", error_message="AMMS 返回失败", generated_at=datetime(2026, 5, 2, 8, 0, 0)))
    await session.commit()

    service = ShippingRouteService(session)
    has_plan_page = await service.list_routes(RouteListQuery(has_plan=True, page=1, page_size=1))
    assert has_plan_page.total == 2
    assert len(has_plan_page.items) == 1

    failed_page = await service.list_routes(RouteListQuery(track_status="FAILED", page=1, page_size=10))
    assert failed_page.total == 1
    assert failed_page.items[0].track_error_message == "AMMS 返回失败"

    main_line_page = await service.list_routes(RouteListQuery(has_main_line=True, page=1, page_size=10))
    assert main_line_page.total == 1
    assert main_line_page.items[0].main_line_name == "主路线"


@pytest.mark.asyncio
async def test_freight_status_change_uses_allowed_business_transitions(session: AsyncSession) -> None:
    freight = Freight(
        freight_no="FR-REMEDIATION",
        source_type_code="MANUAL",
        cargo_title="审计测试货源",
        raw_commodity_name="煤炭",
        raw_origin_text="南京",
        raw_destination_text="芜湖",
        status_code="PUBLISHED",
        hall_status_code="NOT_LISTED",
        audit_status="APPROVED",
    )
    closed = Freight(
        freight_no="FR-REMEDIATION-CLOSED",
        source_type_code="MANUAL",
        cargo_title="审计测试已关闭货源",
        raw_commodity_name="煤炭",
        raw_origin_text="南京",
        raw_destination_text="芜湖",
        status_code="CLOSED",
        hall_status_code="NOT_LISTED",
        audit_status="APPROVED",
    )
    session.add_all([freight, closed])
    await session.commit()

    service = FreightService(session)
    await service.change_freight_status(freight.id, "CLOSED")
    assert freight.status_code == "CLOSED"

    with pytest.raises(ValidationError, match="不能直接变更"):
        await service.change_freight_status(closed.id, "PUBLISHED")
