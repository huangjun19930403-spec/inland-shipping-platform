from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.models import NavigationWaterArea
from app.models.address import NavigationChannelBoundary
from app.models.base import Base
from scripts.seeds.loaders.navigation_water_areas import seed_navigation_water_areas


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


def _polygon() -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[[120.0, 31.0], [120.1, 31.0], [120.1, 31.1], [120.0, 31.1], [120.0, 31.0]]],
    }


def _payload(name: str, *, area_km2: float = 1.0) -> dict:
    return {
        "source_code": "TEST_RIVER",
        "source_layer_name": "rx",
        "source_object_id": "1",
        "water_name": name,
        "normalized_water_name": name,
        "alias_names": None,
        "water_level": 1,
        "water_type_code": "RIVER",
        "remark": None,
        "geometry_json": _polygon(),
        "geometry_status_code": "VALID",
        "simplified_geometry_low_json": _polygon(),
        "simplified_geometry_mid_json": None,
        "simplified_geometry_high_json": None,
        "bbox_min_lng": 120.0,
        "bbox_min_lat": 31.0,
        "bbox_max_lng": 120.1,
        "bbox_max_lat": 31.1,
        "center_lng": 120.05,
        "center_lat": 31.05,
        "shape_length_degree": 0.4,
        "shape_area_degree": 0.01,
        "area_km2": area_km2,
        "is_low_value": False,
        "is_enabled": True,
    }


def _write_seed(path: Path, row: dict) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False))
        handle.write("\n")


@pytest.mark.asyncio
async def test_navigation_water_area_seed_upserts_without_touching_boundaries(tmp_path: Path, session_maker) -> None:
    seed_path = tmp_path / "navigation_water_areas.jsonl.gz"
    _write_seed(seed_path, _payload("第一次"))

    first = await seed_navigation_water_areas(seed_path, session_factory=session_maker, prepare_schema=False)
    _write_seed(seed_path, _payload("第二次", area_km2=2.0))
    second = await seed_navigation_water_areas(seed_path, session_factory=session_maker, prepare_schema=False)

    async with session_maker() as session:
        water_count = await session.scalar(select(func.count()).select_from(NavigationWaterArea))
        boundary_count = await session.scalar(select(func.count()).select_from(NavigationChannelBoundary))
        row = (await session.execute(select(NavigationWaterArea))).scalars().one()

    assert first == {"created": 1, "updated": 0, "total": 1}
    assert second == {"created": 0, "updated": 1, "total": 1}
    assert water_count == 1
    assert boundary_count == 0
    assert row.water_name == "第二次"
    assert float(row.area_km2) == 2.0
