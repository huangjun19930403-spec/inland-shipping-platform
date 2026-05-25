from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
import pytest_asyncio
import shapefile
import sqlalchemy as sa
from shapely.geometry import GeometryCollection, LineString, Polygon
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.models import NavigationWaterArea
from app.models.address import NavigationChannelBoundary
from app.models.base import Base
from scripts.navigation.import_river_shapefile import _repair_polygonal_geometry, import_river_shapefile, iter_layer_rows


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


def _write_polygon_layer(base_path: Path, records: list[dict]) -> None:
    writer = shapefile.Writer(str(base_path), shapeType=shapefile.POLYGON)
    writer.field("OBJECTID", "N")
    writer.field("NAME", "C", size=128)
    writer.field("REMARK", "C", size=128)
    writer.field("Shape_Leng", "F", decimal=8)
    writer.field("Shape_Area", "F", decimal=8)
    for item in records:
        writer.poly([item["ring"]])
        writer.record(
            item["object_id"],
            item.get("name", ""),
            item.get("remark", ""),
            item.get("shape_length", 0.0),
            item.get("shape_area", 0.0),
        )
    writer.close()
    base_path.with_suffix(".cpg").write_text("UTF-8", encoding="utf-8")
    base_path.with_suffix(".prj").write_text(
        'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
        'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]',
        encoding="utf-8",
    )


def _sample_layer(tmp_path: Path, layer_name: str = "rx") -> Path:
    base_path = tmp_path / layer_name
    _write_polygon_layer(
        base_path,
        [
            {
                "object_id": 1,
                "name": "测试运河",
                "remark": "fixture",
                "shape_length": 1.2,
                "shape_area": 0.02,
                "ring": [
                    [120.0, 31.0],
                    [120.1, 31.0],
                    [120.1, 31.1],
                    [120.0, 31.1],
                    [120.0, 31.0],
                ],
            },
            {
                "object_id": 2,
                "name": "修复河",
                "remark": "self crossing",
                "shape_length": 1.0,
                "shape_area": 0.01,
                "ring": [
                    [120.2, 31.0],
                    [120.3, 31.1],
                    [120.2, 31.1],
                    [120.3, 31.0],
                    [120.2, 31.0],
                ],
            },
        ],
    )
    return base_path.with_suffix(".shp")


def test_iter_layer_rows_reads_attrs_bbox_and_repairs_geometry(tmp_path: Path) -> None:
    shp_path = _sample_layer(tmp_path)

    rows = list(
        iter_layer_rows(
            shp_path=shp_path,
            source_code="TEST_RIVER",
            layer_name="rx",
        )
    )

    assert len(rows) == 2
    first = rows[0]
    assert first.source_object_id == "1"
    assert first.water_name == "测试运河"
    assert first.water_type_code == "CANAL"
    assert first.geometry_status_code == "VALID"
    assert first.bbox_min_lng == 120.0
    assert first.bbox_max_lat == 31.1
    assert first.area_km2 and first.area_km2 > 0

    repaired = rows[1]
    assert repaired.geometry_status_code == "REPAIRED"
    assert repaired.is_enabled is True
    assert repaired.simplified_geometry_low_json is not None


def test_repair_polygonal_geometry_extracts_polygons_from_geometry_collection() -> None:
    collection = GeometryCollection(
        [
            LineString([(120.0, 31.0), (120.1, 31.1)]),
            Polygon(
                [
                    (120.0, 31.0),
                    (120.2, 31.0),
                    (120.2, 31.2),
                    (120.0, 31.2),
                    (120.0, 31.0),
                ]
            ),
        ]
    )

    geometry, status = _repair_polygonal_geometry(collection)

    assert status == "REPAIRED"
    assert geometry.geom_type == "Polygon"
    assert geometry.is_valid


def test_iter_layer_rows_classifies_double_line_river_as_river(tmp_path: Path) -> None:
    base_path = tmp_path / "一级水系"
    _write_polygon_layer(
        base_path,
        [
            {
                "object_id": 1,
                "name": "红水河",
                "remark": "一级常年双线河",
                "shape_length": 1.2,
                "shape_area": 0.02,
                "ring": [
                    [120.0, 31.0],
                    [120.1, 31.0],
                    [120.1, 31.1],
                    [120.0, 31.1],
                    [120.0, 31.0],
                ],
            }
        ],
    )
    rows = list(
        iter_layer_rows(
            shp_path=base_path.with_suffix(".shp"),
            source_code="TEST_RIVER",
            layer_name="一级水系",
        )
    )

    assert rows[0].source_layer_code == "LEVEL_1"
    assert rows[0].source_layer_display_name == "一级水系"
    assert rows[0].source_layer_order == 1
    assert rows[0].water_type_code == "RIVER"


def test_iter_layer_rows_supports_geometry_only_layer_without_dbf(tmp_path: Path) -> None:
    shp_path = _sample_layer(tmp_path, "rx8")
    shp_path.with_suffix(".dbf").unlink()

    rows = list(
        iter_layer_rows(
            shp_path=shp_path,
            source_code="TEST_RIVER",
            layer_name="rx8",
        )
    )

    assert len(rows) == 2
    assert rows[0].source_layer_name == "rx8"
    assert rows[0].source_object_id == "1"
    assert rows[0].water_name is None
    assert rows[0].water_level == 8
    assert rows[0].geometry_status_code == "VALID"


@pytest.mark.asyncio
async def test_import_zip_reads_rx8_double_dot_dbf(tmp_path: Path) -> None:
    shp_path = _sample_layer(tmp_path, "rx8")
    zip_path = tmp_path / "revier-rx8-test.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in tmp_path.glob("rx8.*"):
            arcname = path.name
            if path.suffix == ".dbf":
                arcname = "rx8..dbf"
            elif path.suffix == ".prj":
                arcname = "rx8..prj"
            archive.write(path, arcname=arcname)

    summary = await import_river_shapefile(
        input_path=zip_path,
        source_code="TEST_RIVER",
        layers=["rx8"],
        dry_run=True,
    )

    assert summary.layers[0].rows_read == 2
    assert summary.layers[0].rows_valid == 1
    assert summary.layers[0].rows_repaired == 1


@pytest.mark.asyncio
async def test_import_dry_run_reads_zip_and_reports_missing_layer(tmp_path: Path) -> None:
    _sample_layer(tmp_path, "rx")
    zip_path = tmp_path / "revier-test.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in tmp_path.glob("rx.*"):
            archive.write(path, arcname=path.name)

    summary = await import_river_shapefile(
        input_path=zip_path,
        source_code="TEST_RIVER",
        layers=["rx", "一级水系"],
        dry_run=True,
    )

    payload = summary.as_dict()
    assert payload["dry_run"] is True
    assert payload["totals"]["rows_read"] == 2
    assert payload["layers"][0]["status"] == "OK"
    assert payload["layers"][1]["status"] == "MISSING"


@pytest.mark.asyncio
async def test_import_upserts_water_area_without_touching_channel_boundary(
    tmp_path: Path,
    session_maker,
) -> None:
    _sample_layer(tmp_path, "rx")

    first = await import_river_shapefile(
        input_path=tmp_path,
        source_code="TEST_RIVER",
        layers=["rx"],
        dry_run=False,
        session_factory=session_maker,
        prepare_schema=False,
    )
    second = await import_river_shapefile(
        input_path=tmp_path,
        source_code="TEST_RIVER",
        layers=["rx"],
        dry_run=False,
        session_factory=session_maker,
        prepare_schema=False,
    )

    async with session_maker() as session:
        water_area_count = await session.scalar(select(func.count()).select_from(NavigationWaterArea))
        boundary_count = await session.scalar(select(func.count()).select_from(NavigationChannelBoundary))
        first_row = (await session.execute(select(NavigationWaterArea).order_by(NavigationWaterArea.source_object_id))).scalars().first()

    assert first.layers[0].rows_inserted == 2
    assert second.layers[0].rows_updated == 2
    assert water_area_count == 2
    assert boundary_count == 0
    assert first_row is not None
    assert first_row.source_code == "TEST_RIVER"
    assert first_row.source_layer_name == "rx"
    assert first_row.geometry_json["type"] == "Polygon"


def test_fixture_json_files_remain_valid() -> None:
    fixture_dir = Path("tests/fixtures/navigation")
    files = sorted(fixture_dir.glob("*.json")) + sorted(fixture_dir.glob("*.geojson"))
    assert files
    for path in files:
        json.loads(path.read_text(encoding="utf-8"))
