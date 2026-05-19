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
from app.models.route import (
    ShippingRoute,
    ShippingRoutePlan,
    ShippingRoutePlanPoint,
    ShippingRoutePlanSegment,
    ShippingRoutePlanSegmentResult,
    ShippingRoutePlanTrackVersion,
    ShippingRoutePlanTrackVersionSegment,
)
from app.modules.address.schemas import TransportNodeCreateRequest
from app.modules.address.service import TransportNodeService
from app.modules.freight.service import FreightService
from app.modules.route.schemas import RouteCreateRequest, RouteListQuery
from app.modules.route.service import ShippingRouteService


def test_legacy_freight_list_route_is_not_business_entrypoint() -> None:
    from main import app

    paths = app.openapi()["paths"]
    assert "get" not in paths.get("/api/v1/freight", {})
    assert "get" in paths["/api/v1/freight/opportunities"]


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


def _route_sequence() -> CodeSequence:
    return CodeSequence(
        biz_code="ROUTE_CODE",
        biz_name="航线编码",
        target_table="shipping_route",
        target_column="code",
        prefix="RT",
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
async def test_route_create_returns_loaded_response_after_commit(session: AsyncSession) -> None:
    session.add(_route_sequence())
    await session.commit()

    response = await ShippingRouteService(session).create_route(
        RouteCreateRequest(
            name="审计测试新增航线",
            origin_endpoint_type_code="CITY",
            origin_city_code="320100",
            destination_endpoint_type_code="CITY",
            destination_city_code="340200",
            transport_org_type_code="SINGLE_MODE",
            description="创建后应直接返回完整响应",
        )
    )

    assert response.code == "RT0001"
    assert response.audit_status == "APPROVED"
    assert response.created_at is not None
    assert response.updated_at is not None


@pytest.mark.asyncio
async def test_route_list_filters_and_totals_are_query_level(session: AsyncSession) -> None:
    route_a = ShippingRoute(
        code="RT-A",
        name="审计测试有默认方案",
        origin_endpoint_type_code="REGION",
        destination_endpoint_type_code="REGION",
        transport_org_type_code="SINGLE_MODE",
        origin_region_id=1,
        destination_region_id=2,
        audit_status="APPROVED",
    )
    route_b = ShippingRoute(
        code="RT-B",
        name="审计测试失败轨迹",
        origin_endpoint_type_code="REGION",
        destination_endpoint_type_code="REGION",
        transport_org_type_code="SINGLE_MODE",
        origin_region_id=1,
        destination_region_id=3,
        audit_status="APPROVED",
    )
    route_c = ShippingRoute(
        code="RT-C",
        name="审计测试无方案",
        origin_endpoint_type_code="REGION",
        destination_endpoint_type_code="REGION",
        transport_org_type_code="SINGLE_MODE",
        origin_region_id=2,
        destination_region_id=3,
        audit_status="APPROVED",
    )
    session.add_all([route_a, route_b, route_c])
    await session.flush()
    plan_a = ShippingRoutePlan(route_id=route_a.id, plan_code="PA", plan_name="标准方案", plan_type_code="STANDARD", is_default=True, status_code="ACTIVE", display_order=1)
    plan_b = ShippingRoutePlan(route_id=route_b.id, plan_code="PB", plan_name="低水位方案", plan_type_code="SEASONAL", is_default=True, status_code="ACTIVE", display_order=1)
    session.add_all([plan_a, plan_b])
    await session.flush()
    point_a1 = ShippingRoutePlanPoint(
        plan_id=plan_a.id,
        point_order=1,
        point_type_code="MANUAL_POINT",
        manual_name="A",
        longitude=120,
        latitude=31,
        display_name="A",
        transport_mode_after_code="WATER",
    )
    point_a2 = ShippingRoutePlanPoint(
        plan_id=plan_a.id,
        point_order=2,
        point_type_code="MANUAL_POINT",
        manual_name="B",
        longitude=121,
        latitude=32,
        display_name="B",
    )
    point_b1 = ShippingRoutePlanPoint(
        plan_id=plan_b.id,
        point_order=1,
        point_type_code="MANUAL_POINT",
        manual_name="C",
        longitude=120,
        latitude=31,
        display_name="C",
        transport_mode_after_code="WATER",
    )
    point_b2 = ShippingRoutePlanPoint(
        plan_id=plan_b.id,
        point_order=2,
        point_type_code="MANUAL_POINT",
        manual_name="D",
        longitude=121,
        latitude=32,
        display_name="D",
    )
    session.add_all([point_a1, point_a2, point_b1, point_b2])
    await session.flush()
    seg_a = ShippingRoutePlanSegment(
        plan_id=plan_a.id,
        segment_no=1,
        start_plan_point_id=point_a1.id,
        end_plan_point_id=point_a2.id,
        transport_mode_code="WATER",
        generation_status_code="READY",
        generated_at=datetime(2026, 5, 1, 8, 0, 0),
    )
    seg_b = ShippingRoutePlanSegment(
        plan_id=plan_b.id,
        segment_no=1,
        start_plan_point_id=point_b1.id,
        end_plan_point_id=point_b2.id,
        transport_mode_code="WATER",
        generation_status_code="FAILED",
        error_message="AMMS 返回失败",
        generated_at=datetime(2026, 5, 2, 8, 0, 0),
    )
    session.add_all([seg_a, seg_b])
    await session.flush()
    result_a = ShippingRoutePlanSegmentResult(segment_id=seg_a.id, result_no=1, provider_type_code="HIFLEET", result_status_code="READY", is_selected=True)
    session.add(result_a)
    await session.flush()
    seg_a.selected_result_id = result_a.id
    version_a = ShippingRoutePlanTrackVersion(
        plan_id=plan_a.id,
        version_no=1,
        source_type_code="HIFLEET",
        provider_type_code="HIFLEET",
        is_current=True,
        version_status_code="READY",
        point_count=2,
        segment_count=1,
        generated_at=datetime(2026, 5, 1, 8, 0, 0),
    )
    version_b = ShippingRoutePlanTrackVersion(
        plan_id=plan_b.id,
        version_no=1,
        source_type_code="HIFLEET",
        provider_type_code="HIFLEET",
        is_current=True,
        version_status_code="FAILED",
        point_count=0,
        segment_count=0,
        error_message="AMMS 返回失败",
        generated_at=datetime(2026, 5, 2, 8, 0, 0),
    )
    session.add_all([version_a, version_b])
    await session.flush()
    session.add(
        ShippingRoutePlanTrackVersionSegment(
            version_id=version_a.id,
            segment_id=seg_a.id,
            segment_no=1,
            geometry_json={"type": "LineString", "coordinates": [[120, 31], [121, 32]]},
            point_count=2,
            edit_status_code="ORIGINAL",
        )
    )
    plan_a.current_track_version_id = version_a.id
    plan_b.current_track_version_id = version_b.id
    await session.commit()

    service = ShippingRouteService(session)
    has_plan_page = await service.list_routes(RouteListQuery(has_plan=True, page=1, page_size=1))
    assert has_plan_page.total == 2
    assert len(has_plan_page.items) == 1

    failed_page = await service.list_routes(RouteListQuery(track_status="FAILED", page=1, page_size=10))
    assert failed_page.total == 1
    assert failed_page.items[0].track_error_message == "AMMS 返回失败"

    default_plan_page = await service.list_routes(RouteListQuery(has_default_plan=True, page=1, page_size=10))
    assert default_plan_page.total == 2
    assert default_plan_page.items[0].default_plan_name in {"标准方案", "低水位方案"}


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
