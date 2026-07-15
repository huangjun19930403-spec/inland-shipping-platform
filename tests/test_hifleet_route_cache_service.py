from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.integrations.http.route_geometry_types import RouteGeometryQuery, RouteGeometryResult
from app.models.base import Base
from app.models.navigation import NavigationHifleetRouteCache
from app.modules.navigation.services.hifleet_route_cache_service import HifleetRouteCacheService


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


def _query(origin=(120.0, 31.0), destination=(120.2, 31.0)) -> RouteGeometryQuery:
    return RouteGeometryQuery(
        origin_lon=origin[0],
        origin_lat=origin[1],
        dest_lon=destination[0],
        dest_lat=destination[1],
        transport_mode="WATER",
        segment_type="TEST",
    )


@pytest.mark.asyncio
async def test_hifleet_route_cache_uses_direct_and_reverse_hits(session_maker) -> None:
    class FakeHifleetClient:
        calls = 0

        async def generate(self, query):  # noqa: ANN001
            self.calls += 1
            return RouteGeometryResult(
                geometry={
                    "type": "LineString",
                    "coordinates": [
                        [query.origin_lon, query.origin_lat],
                        [120.1, 31.02],
                        [query.dest_lon, query.dest_lat],
                    ],
                },
                source="hifleet",
                provider="HIFLEET",
                provider_trace_id="hf-cache-test",
                status="ready",
                distance_km=22.5,
                raw_summary={"status": "success"},
            )

    async with session_maker() as session:
        client = FakeHifleetClient()
        service = HifleetRouteCacheService(session, route_client=client)

        first = await service.get_or_generate(
            _query(),
            origin_ref_type_code="TRANSPORT_NODE",
            origin_ref_id=1,
            origin_name="A",
            destination_ref_type_code="TRANSPORT_NODE",
            destination_ref_id=2,
            destination_name="B",
        )
        second = await service.get_or_generate(
            _query(),
            origin_ref_type_code="TRANSPORT_NODE",
            origin_ref_id=1,
            origin_name="A",
            destination_ref_type_code="TRANSPORT_NODE",
            destination_ref_id=2,
            destination_name="B",
        )
        reverse = await service.get_or_generate(
            _query(origin=(120.2, 31.0), destination=(120.0, 31.0)),
            origin_ref_type_code="TRANSPORT_NODE",
            origin_ref_id=2,
            origin_name="B",
            destination_ref_type_code="TRANSPORT_NODE",
            destination_ref_id=1,
            destination_name="A",
        )
        row = (await session.execute(select(NavigationHifleetRouteCache))).scalar_one()

    assert client.calls == 1
    assert first.raw_summary["cache_hit"] is False
    assert second.raw_summary["cache_hit"] is True
    assert second.raw_summary["cache_direction"] == "FORWARD"
    assert reverse.raw_summary["cache_hit"] is True
    assert reverse.raw_summary["cache_direction"] == "REVERSED"
    assert reverse.geometry["coordinates"][0] == [120.2, 31.0]
    assert row.use_count == 3


@pytest.mark.asyncio
async def test_hifleet_route_cache_coordinate_query_reuses_legacy_node_cache(session_maker) -> None:
    class FakeHifleetClient:
        calls = 0

        async def generate(self, query):  # noqa: ANN001
            self.calls += 1
            return RouteGeometryResult(
                geometry={
                    "type": "LineString",
                    "coordinates": [
                        [query.origin_lon, query.origin_lat],
                        [120.1, 31.02],
                        [query.dest_lon, query.dest_lat],
                    ],
                },
                source="hifleet",
                provider="HIFLEET",
                provider_trace_id="hf-cache-test",
                status="ready",
                distance_km=22.5,
                raw_summary={"status": "success"},
            )

    class FailingHifleetClient:
        async def generate(self, query):  # noqa: ANN001
            raise AssertionError("coordinate query should use existing cache")

    async with session_maker() as session:
        client = FakeHifleetClient()
        service = HifleetRouteCacheService(session, route_client=client)

        await service.get_or_generate(
            _query(),
            origin_ref_type_code="TRANSPORT_NODE",
            origin_ref_id=1,
            origin_name="A",
            destination_ref_type_code="TRANSPORT_NODE",
            destination_ref_id=2,
            destination_name="B",
        )
        row = (await session.execute(select(NavigationHifleetRouteCache))).scalar_one()
        row.route_key = "HIFLEET|WATER|TRANSPORT_NODE:1|TRANSPORT_NODE:2"
        row.normalized_pair_key = "HIFLEET|WATER|TRANSPORT_NODE:1||TRANSPORT_NODE:2"
        await session.commit()

        coordinate_hit = await HifleetRouteCacheService(session, route_client=FailingHifleetClient()).get_or_generate(_query())
        rows = list((await session.execute(select(NavigationHifleetRouteCache))).scalars())

    assert client.calls == 1
    assert coordinate_hit.raw_summary["cache_hit"] is True
    assert coordinate_hit.raw_summary["hifleet_cache_id"] == row.id
    assert len(rows) == 1
