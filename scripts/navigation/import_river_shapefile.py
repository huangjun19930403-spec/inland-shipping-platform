"""Import revier river shapefiles into navigation_water_area.

This script only creates raw water-area assets. It never updates seed channel
boundaries, centerlines, graph nodes, graph edges, or route results.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import tempfile
import zipfile
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import shapefile
from pyproj import CRS, Geod, Transformer
from shapely import make_valid
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, engine
from app.models import NavigationWaterArea
from app.models.base import Base
from app.modules.navigation.water_area_layers import water_area_layer_meta

DEFAULT_LAYERS = (
    "rx",
    "rx8",
    "一级水系",
    "二级水系",
    "三级水系",
    "四级水系",
    "五级水系",
    "六级水系",
    "七级水系",
)

WGS84 = CRS.from_epsg(4326)
GEOD = Geod(ellps="WGS84")


@dataclass(slots=True)
class WaterAreaRow:
    source_code: str
    source_layer_name: str
    source_layer_code: str | None
    source_layer_display_name: str | None
    source_layer_role_code: str | None
    source_layer_order: int | None
    source_file_name: str | None
    source_object_id: str
    has_attributes: bool
    raw_properties_json: dict[str, Any] | None
    water_name: str | None
    normalized_water_name: str | None
    alias_names: list[str] | None
    water_level: int | None
    water_type_code: str
    remark: str | None
    geometry_json: dict[str, Any]
    geometry_status_code: str
    simplified_geometry_low_json: dict[str, Any] | None
    simplified_geometry_mid_json: dict[str, Any] | None
    simplified_geometry_high_json: dict[str, Any] | None
    bbox_min_lng: float | None
    bbox_min_lat: float | None
    bbox_max_lng: float | None
    bbox_max_lat: float | None
    center_lng: float | None
    center_lat: float | None
    shape_length_degree: float | None
    shape_area_degree: float | None
    area_km2: float | None
    is_low_value: bool
    is_enabled: bool

    def model_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LayerImportSummary:
    layer_name: str
    status: str = "OK"
    rows_read: int = 0
    rows_valid: int = 0
    rows_repaired: int = 0
    rows_invalid: int = 0
    rows_low_value: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    message: str | None = None


@dataclass(slots=True)
class ImportSummary:
    source_code: str
    dry_run: bool
    layers: list[LayerImportSummary] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        layer_dicts = [asdict(layer) for layer in self.layers]
        return {
            "source_code": self.source_code,
            "dry_run": self.dry_run,
            "layers": layer_dicts,
            "totals": {
                "layers": len(layer_dicts),
                "rows_read": sum(layer.rows_read for layer in self.layers),
                "rows_valid": sum(layer.rows_valid for layer in self.layers),
                "rows_repaired": sum(layer.rows_repaired for layer in self.layers),
                "rows_invalid": sum(layer.rows_invalid for layer in self.layers),
                "rows_low_value": sum(layer.rows_low_value for layer in self.layers),
                "rows_inserted": sum(layer.rows_inserted for layer in self.layers),
                "rows_updated": sum(layer.rows_updated for layer in self.layers),
            },
        }


@contextmanager
def _materialized_input(input_path: Path) -> Iterator[Path]:
    if input_path.is_dir():
        yield input_path
        return

    if not input_path.exists():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")

    if input_path.suffix.lower() != ".zip":
        raise ValueError(f"Input must be a directory or zip file: {input_path}")

    with tempfile.TemporaryDirectory(prefix="navigation-river-") as temp_dir:
        with zipfile.ZipFile(input_path) as archive:
            archive.extractall(temp_dir)
        yield Path(temp_dir)


def _index_shapefiles(root: Path) -> dict[str, Path]:
    return {path.stem: path for path in root.rglob("*.shp")}


def _index_zip_shapefiles(archive: zipfile.ZipFile) -> dict[str, str]:
    return {Path(name).stem: name for name in archive.namelist() if name.lower().endswith(".shp")}


def _zip_component(names: set[str], base: str, suffix: str) -> str | None:
    suffix = suffix.lstrip(".")
    candidates = (f"{base}.{suffix}", f"{base}..{suffix}")
    for candidate in candidates:
        if candidate in names:
            return candidate
    return None


def _zip_reader(archive: zipfile.ZipFile, shp_entry: str) -> tuple[shapefile.Reader, CRS | None, bool]:
    names = set(archive.namelist())
    base = shp_entry[:-4]
    shx_entry = _zip_component(names, base, "shx")
    dbf_entry = _zip_component(names, base, "dbf")
    cpg_entry = _zip_component(names, base, "cpg")
    prj_entry = _zip_component(names, base, "prj")
    encoding = "utf-8"
    if cpg_entry:
        encoding = archive.read(cpg_entry).decode("utf-8", errors="ignore").strip() or "utf-8"
    kwargs: dict[str, Any] = {"shp": io.BytesIO(archive.read(shp_entry)), "encoding": encoding}
    if shx_entry:
        kwargs["shx"] = io.BytesIO(archive.read(shx_entry))
    if dbf_entry:
        kwargs["dbf"] = io.BytesIO(archive.read(dbf_entry))
    source_crs = None
    if prj_entry:
        try:
            source_crs = CRS.from_wkt(archive.read(prj_entry).decode("utf-8", errors="ignore"))
        except Exception:
            source_crs = None
    return shapefile.Reader(**kwargs), source_crs, bool(dbf_entry)


def _component_path(shp_path: Path, suffix: str) -> Path | None:
    suffix = suffix.lstrip(".")
    candidates = (
        shp_path.with_suffix(f".{suffix}"),
        shp_path.parent / f"{shp_path.stem}..{suffix}",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _open_reader(shp_path: Path) -> shapefile.Reader:
    shx_path = _component_path(shp_path, "shx")
    dbf_path = _component_path(shp_path, "dbf")
    kwargs: dict[str, Any] = {"shp": str(shp_path), "encoding": _read_encoding(shp_path)}
    if shx_path is not None:
        kwargs["shx"] = str(shx_path)
    if dbf_path is not None:
        kwargs["dbf"] = str(dbf_path)
    return shapefile.Reader(**kwargs)


def _read_encoding(shp_path: Path) -> str:
    cpg_path = _component_path(shp_path, "cpg")
    if cpg_path is None:
        cpg_path = shp_path.with_suffix(".cpg")
    if not cpg_path.exists():
        return "utf-8"
    value = cpg_path.read_text(encoding="utf-8", errors="ignore").strip()
    return value or "utf-8"


def _read_crs(shp_path: Path) -> CRS | None:
    prj_path = _component_path(shp_path, "prj")
    if prj_path is None or not prj_path.exists():
        return None
    try:
        return CRS.from_wkt(prj_path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None


def _to_wgs84(geometry: BaseGeometry, source_crs: CRS | None) -> BaseGeometry:
    if source_crs is None or source_crs == WGS84:
        return geometry
    transformer = Transformer.from_crs(source_crs, WGS84, always_xy=True)
    return shapely_transform(transformer.transform, geometry)


def _polygonal_geometry(geometry: BaseGeometry) -> BaseGeometry:
    if geometry.is_empty:
        return GeometryCollection()
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    parts: list[Polygon] = []
    if hasattr(geometry, "geoms"):
        for item in geometry.geoms:
            polygonal = _polygonal_geometry(item)
            if isinstance(polygonal, Polygon):
                parts.append(polygonal)
            elif isinstance(polygonal, MultiPolygon):
                parts.extend(list(polygonal.geoms))
    if not parts:
        return GeometryCollection()
    if len(parts) == 1:
        return parts[0]
    return MultiPolygon(parts)


def _repair_polygonal_geometry(geometry: BaseGeometry) -> tuple[BaseGeometry, str]:
    if geometry.is_empty:
        return geometry, "INVALID"

    status = "VALID"
    if not geometry.is_valid:
        geometry = make_valid(geometry)
        status = "REPAIRED"

    polygonal = _polygonal_geometry(geometry)
    if polygonal.is_empty:
        return geometry, "INVALID"
    if polygonal is not geometry and status == "VALID":
        status = "REPAIRED"
    geometry = polygonal

    if not geometry.is_valid:
        geometry = make_valid(geometry)
        status = "REPAIRED"
        geometry = _polygonal_geometry(geometry)
        if geometry.is_empty or not geometry.is_valid:
            return geometry, "INVALID"

    if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        return geometry, "INVALID"
    return geometry, status


def _normalise_name(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return " ".join(text.split())


def _water_level_from_layer(layer_name: str) -> int | None:
    return water_area_layer_meta(layer_name).water_level


def _water_type(name: str | None, remark: str | None) -> str:
    text = f"{name or ''} {remark or ''}"
    if any(token in text for token in ("水库", "库区")):
        return "RESERVOIR"
    if any(token in text for token in ("湖", "荡", "淀", "泡", "海子", "淖尔")):
        return "LAKE"
    if any(token in text for token in ("运河", "漕河", "渠道", "灌渠", "干渠", "支渠")):
        return "CANAL"
    if any(token in text for token in ("江", "河", "溪", "水道", "涌", "港", "双线河", "单线河")):
        return "RIVER"
    return "UNKNOWN"


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _geometry_area_km2(geometry: BaseGeometry) -> float | None:
    try:
        area_m2, _ = GEOD.geometry_area_perimeter(geometry)
    except Exception:
        return None
    return abs(area_m2) / 1_000_000


def _simplify_json(geometry: BaseGeometry, tolerance: float) -> dict[str, Any] | None:
    if geometry.is_empty:
        return None
    simplified = geometry.simplify(tolerance, preserve_topology=True)
    return mapping(simplified)


def _shape_record_attrs(shape_record: Any) -> dict[str, Any]:
    try:
        return dict(shape_record.record.as_dict())
    except Exception:
        return {}


def _json_safe_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in attrs.items()}


def iter_layer_rows(
    *,
    shp_path: Path,
    source_code: str,
    layer_name: str,
    limit: int | None = None,
    low_value_area_km2: float = 0.001,
) -> Iterator[WaterAreaRow]:
    reader = _open_reader(shp_path)
    source_crs = _read_crs(shp_path)
    has_dbf = _component_path(shp_path, "dbf") is not None
    yield from _iter_reader_rows(
        reader=reader,
        source_crs=source_crs,
        has_dbf=has_dbf,
        source_file_name=shp_path.name,
        source_code=source_code,
        layer_name=layer_name,
        limit=limit,
        low_value_area_km2=low_value_area_km2,
    )


def iter_zip_layer_rows(
    *,
    archive: zipfile.ZipFile,
    shp_entry: str,
    source_code: str,
    layer_name: str,
    limit: int | None = None,
    low_value_area_km2: float = 0.001,
) -> Iterator[WaterAreaRow]:
    reader, source_crs, has_dbf = _zip_reader(archive, shp_entry)
    yield from _iter_reader_rows(
        reader=reader,
        source_crs=source_crs,
        has_dbf=has_dbf,
        source_file_name=Path(shp_entry).name,
        source_code=source_code,
        layer_name=layer_name,
        limit=limit,
        low_value_area_km2=low_value_area_km2,
    )


def _iter_reader_rows(
    *,
    reader: shapefile.Reader,
    source_crs: CRS | None,
    has_dbf: bool,
    source_file_name: str,
    source_code: str,
    layer_name: str,
    limit: int | None,
    low_value_area_km2: float,
) -> Iterator[WaterAreaRow]:
    layer_meta = water_area_layer_meta(layer_name)

    shape_iterable: Iterator[tuple[Any, dict[str, Any]]]
    if has_dbf:
        shape_iterable = ((item.shape, _shape_record_attrs(item)) for item in reader.iterShapeRecords())
    else:
        shape_iterable = ((item, {}) for item in reader.iterShapes())

    for index, (shape_item, attrs) in enumerate(shape_iterable, start=1):
        if limit is not None and index > limit:
            break

        object_id = attrs.get("OBJECTID") or attrs.get("objectid") or index
        water_name = _normalise_name(attrs.get("NAME") or attrs.get("name"))
        remark = _normalise_name(attrs.get("REMARK") or attrs.get("remark"))

        try:
            geometry = shape(shape_item.__geo_interface__)
            geometry = _to_wgs84(geometry, source_crs)
        except Exception:
            geometry = shape({"type": "GeometryCollection", "geometries": []})

        geometry, geometry_status = _repair_polygonal_geometry(geometry)

        bounds = geometry.bounds if not geometry.is_empty else (None, None, None, None)
        bbox_min_lng, bbox_min_lat, bbox_max_lng, bbox_max_lat = bounds
        centroid = geometry.centroid if not geometry.is_empty else None
        area_km2 = _geometry_area_km2(geometry) if geometry_status != "INVALID" else None
        is_low_value = bool(area_km2 is not None and area_km2 < low_value_area_km2)

        yield WaterAreaRow(
            source_code=source_code,
            source_layer_name=layer_name,
            source_layer_code=layer_meta.source_layer_code,
            source_layer_display_name=layer_meta.source_layer_display_name,
            source_layer_role_code=layer_meta.source_layer_role_code,
            source_layer_order=layer_meta.source_layer_order,
            source_file_name=source_file_name,
            source_object_id=str(object_id),
            has_attributes=has_dbf,
            raw_properties_json=_json_safe_attrs(attrs) if attrs else None,
            water_name=water_name,
            normalized_water_name=_normalise_name(water_name),
            alias_names=None,
            water_level=_water_level_from_layer(layer_name),
            water_type_code=_water_type(water_name, remark),
            remark=remark,
            geometry_json=mapping(geometry),
            geometry_status_code=geometry_status,
            simplified_geometry_low_json=_simplify_json(geometry, 0.01) if geometry_status != "INVALID" else None,
            simplified_geometry_mid_json=_simplify_json(geometry, 0.003) if geometry_status != "INVALID" else None,
            simplified_geometry_high_json=_simplify_json(geometry, 0.001) if geometry_status != "INVALID" else None,
            bbox_min_lng=_float_or_none(bbox_min_lng),
            bbox_min_lat=_float_or_none(bbox_min_lat),
            bbox_max_lng=_float_or_none(bbox_max_lng),
            bbox_max_lat=_float_or_none(bbox_max_lat),
            center_lng=_float_or_none(centroid.x if centroid else None),
            center_lat=_float_or_none(centroid.y if centroid else None),
            shape_length_degree=_float_or_none(attrs.get("Shape_Leng") or attrs.get("shape_leng") or geometry.length),
            shape_area_degree=_float_or_none(attrs.get("Shape_Area") or attrs.get("shape_area") or geometry.area),
            area_km2=area_km2,
            is_low_value=is_low_value,
            is_enabled=geometry_status != "INVALID",
        )


async def _prepare_schema() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _upsert_row(session: AsyncSession, row: WaterAreaRow) -> str:
    existing = (
        await session.execute(
            select(NavigationWaterArea).where(
                NavigationWaterArea.source_code == row.source_code,
                NavigationWaterArea.source_layer_name == row.source_layer_name,
                NavigationWaterArea.source_object_id == row.source_object_id,
            )
        )
    ).scalar_one_or_none()
    payload = row.model_payload()
    if existing is None:
        session.add(NavigationWaterArea(**payload))
        return "inserted"
    for key, value in payload.items():
        setattr(existing, key, value)
    return "updated"


async def _consume_layers(
    *,
    summary: ImportSummary,
    layers: Sequence[str],
    row_iter_factory: Callable[[str], Iterator[WaterAreaRow] | None],
    dry_run: bool,
    strict_layers: bool,
    batch_size: int,
    session: AsyncSession | None,
) -> None:
    for layer_name in layers:
        layer_summary = LayerImportSummary(layer_name=layer_name)
        summary.layers.append(layer_summary)
        rows_iter = row_iter_factory(layer_name)
        if rows_iter is None:
            layer_summary.status = "MISSING"
            layer_summary.message = f"Layer shapefile not found: {layer_name}"
            if strict_layers:
                raise FileNotFoundError(layer_summary.message)
            continue

        pending = 0
        for row in rows_iter:
            layer_summary.rows_read += 1
            if row.geometry_status_code == "REPAIRED":
                layer_summary.rows_repaired += 1
            elif row.geometry_status_code == "INVALID":
                layer_summary.rows_invalid += 1
            else:
                layer_summary.rows_valid += 1
            if row.is_low_value:
                layer_summary.rows_low_value += 1

            if dry_run or session is None:
                continue

            action = await _upsert_row(session, row)
            if action == "inserted":
                layer_summary.rows_inserted += 1
            else:
                layer_summary.rows_updated += 1
            pending += 1
            if pending >= batch_size:
                await session.commit()
                pending = 0

        if session is not None and pending:
            await session.commit()


async def import_river_shapefile(
    *,
    input_path: Path,
    source_code: str,
    layers: Sequence[str] = DEFAULT_LAYERS,
    dry_run: bool = False,
    strict_layers: bool = False,
    limit_per_layer: int | None = None,
    batch_size: int = 500,
    low_value_area_km2: float = 0.001,
    session_factory: Callable[[], AsyncIterator[AsyncSession]] = AsyncSessionLocal,
    prepare_schema: bool = True,
) -> ImportSummary:
    summary = ImportSummary(source_code=source_code, dry_run=dry_run)

    if not dry_run and prepare_schema:
        await _prepare_schema()

    session_cm = session_factory() if not dry_run else None
    session: AsyncSession | None = None
    try:
        if session_cm is not None:
            session = await session_cm.__aenter__()

        if input_path.is_file() and input_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(input_path) as archive:
                shapefiles = _index_zip_shapefiles(archive)

                def row_iter_for_zip(layer_name: str) -> Iterator[WaterAreaRow] | None:
                    shp_entry = shapefiles.get(layer_name)
                    if shp_entry is None:
                        return None
                    return iter_zip_layer_rows(
                        archive=archive,
                        shp_entry=shp_entry,
                        source_code=source_code,
                        layer_name=layer_name,
                        limit=limit_per_layer,
                        low_value_area_km2=low_value_area_km2,
                    )

                await _consume_layers(
                    summary=summary,
                    layers=layers,
                    row_iter_factory=row_iter_for_zip,
                    dry_run=dry_run,
                    strict_layers=strict_layers,
                    batch_size=batch_size,
                    session=session,
                )
        else:
            with _materialized_input(input_path) as root:
                shapefiles = _index_shapefiles(root)

                def row_iter_for_dir(layer_name: str) -> Iterator[WaterAreaRow] | None:
                    shp_path = shapefiles.get(layer_name)
                    if shp_path is None:
                        return None
                    return iter_layer_rows(
                        shp_path=shp_path,
                        source_code=source_code,
                        layer_name=layer_name,
                        limit=limit_per_layer,
                        low_value_area_km2=low_value_area_km2,
                    )

                await _consume_layers(
                    summary=summary,
                    layers=layers,
                    row_iter_factory=row_iter_for_dir,
                    dry_run=dry_run,
                    strict_layers=strict_layers,
                    batch_size=batch_size,
                    session=session,
                )
    except Exception:
        if session is not None:
            await session.rollback()
        raise
    finally:
        if session_cm is not None:
            await session_cm.__aexit__(None, None, None)

    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import river shapefiles into navigation_water_area.")
    parser.add_argument("--input", required=True, help="Path to revier.zip or an extracted shapefile directory.")
    parser.add_argument("--source-code", required=True, help="Source batch code, e.g. RIVER_SHAPEFILE_2026.")
    parser.add_argument("--layers", nargs="*", default=list(DEFAULT_LAYERS), help="Layer names to import.")
    parser.add_argument("--dry-run", action="store_true", help="Read and validate shapefiles without writing database rows.")
    parser.add_argument("--strict-layers", action="store_true", help="Fail when a requested layer is missing.")
    parser.add_argument("--limit-per-layer", type=int, default=None, help="Limit rows read from each layer.")
    parser.add_argument("--batch-size", type=int, default=500, help="Database commit batch size.")
    parser.add_argument("--low-value-area-km2", type=float, default=0.001, help="Area threshold for LOW_VALUE marking.")
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    summary = await import_river_shapefile(
        input_path=Path(args.input),
        source_code=args.source_code,
        layers=args.layers,
        dry_run=args.dry_run,
        strict_layers=args.strict_layers,
        limit_per_layer=args.limit_per_layer,
        batch_size=args.batch_size,
        low_value_area_km2=args.low_value_area_km2,
    )
    print(json.dumps(summary.as_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
