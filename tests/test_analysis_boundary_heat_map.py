from __future__ import annotations

from datetime import date, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import BigInteger

import app.models  # noqa: F401
from app.models.address import AdminRegion, AdminRegionBoundary, Region
from app.models.analysis import FactFreightCityDaily
from app.models.base import Base
from app.modules.analysis.service import AnalysisDashboardService
from main import app


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
        await _seed_region_heat_data(db)
        yield db
    await engine.dispose()


async def _seed_region_heat_data(session: AsyncSession) -> None:
    now = datetime(2026, 1, 1, 8, 0, 0)
    session.add(Region(id=1, code="R-1", name="测试区域", region_type_code="CITY_GROUP", status=1))
    for index in range(85):
        city_code = f"32{index:04d}"
        session.add(
            AdminRegion(
                id=1000 + index,
                code=city_code,
                name=f"测试城市{index}",
                level=2,
                longitude=120 + index / 100,
                latitude=31 + index / 100,
                status=1,
            )
        )
        session.add(
            FactFreightCityDaily(
                stat_date=date(2026, 1, 1),
                city_code=city_code,
                city_name=f"统计城市{index}",
                primary_region_id=1,
                freight_count=10 + index,
                inbound_count=2 + index,
                outbound_count=3 + index,
                total_tonnage=100 + index,
                avg_unit_price=50 + index,
                heat_value=index + 1,
                data_version="test",
                generated_at=now,
            )
        )
    session.add(
        AdminRegionBoundary(
            admin_region_id=1000,
            version_no=1,
            boundary_source_type_code="TEST",
            geometry_json={
                "type": "Polygon",
                "coordinates": [
                    [
                        [120.0, 31.0],
                        [120.2, 31.0],
                        [120.2, 31.2],
                        [120.0, 31.2],
                        [120.0, 31.0],
                    ]
                ],
            },
            center_longitude=120.1,
            center_latitude=31.1,
            is_current=True,
            imported_at=now,
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_region_heat_map_returns_all_city_rows_without_top_80_limit(session: AsyncSession) -> None:
    service = AnalysisDashboardService(session)

    items = await service.region_heat_map(date(2026, 1, 1), date(2026, 1, 1), include_boundary=False)

    assert len(items) == 85
    assert items[0].city_code == "320084"
    assert all(item.boundary_paths is None for item in items)


@pytest.mark.asyncio
async def test_region_heat_map_boundary_payload_is_opt_in_and_preserves_missing_boundary_stats(
    session: AsyncSession,
) -> None:
    service = AnalysisDashboardService(session)

    without_boundary = await service.region_heat_map(date(2026, 1, 1), date(2026, 1, 1), include_boundary=False)
    with_boundary = await service.region_heat_map(date(2026, 1, 1), date(2026, 1, 1), include_boundary=True)

    opt_in_city = next(item for item in with_boundary if item.city_code == "320000")
    lightweight_city = next(item for item in without_boundary if item.city_code == "320000")
    missing_boundary_city = next(item for item in with_boundary if item.city_code == "320001")

    assert lightweight_city.boundary_paths is None
    assert opt_in_city.has_boundary is True
    assert opt_in_city.boundary_paths
    assert opt_in_city.boundary_precision == "low"
    assert opt_in_city.center_longitude == 120.1
    assert opt_in_city.center_latitude == 31.1
    assert missing_boundary_city.has_boundary is False
    assert missing_boundary_city.boundary_paths is None
    assert missing_boundary_city.freight_count == 11


def test_region_heat_map_openapi_uses_boundary_response_and_query_params() -> None:
    operation = app.openapi()["paths"]["/api/v1/analysis/regions/heat-map"]["get"]
    parameters = {item["name"] for item in operation.get("parameters", [])}

    assert "include_boundary" in parameters
    assert "boundary_precision" in parameters
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    item_ref = schema["items"]["$ref"]
    assert item_ref.endswith("/BoundaryHeatMapItem")
