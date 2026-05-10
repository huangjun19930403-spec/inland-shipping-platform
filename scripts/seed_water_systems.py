"""预置水系基础数据初始化脚本。"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import struct
import zipfile
import zlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import and_, delete, or_, select

from app.core.database import AsyncSessionLocal
from app.models.address import WaterSystem, WaterSystemBoundary
from app.modules.address.boundary_utils import (
    BoundaryPolygons,
    extract_geojson_polygons,
    polygons_bbox,
    serialize_boundary_paths,
)
from scripts.seed_data import navigation_water_systems_v1 as embedded_water_systems

try:
    import shapefile  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - dependency guard for bootstrap environments.
    shapefile = None  # type: ignore[assignment]


SOURCE_VERSION = embedded_water_systems.DATA_VERSION
OLD_SOURCE_VERSION = "revier_wgs84_l1_l4_v1"
DEFAULT_LEVELS = (1, 2, 3, 4)
LEVEL_LAYER_NAMES = {
    1: "一级水系",
    2: "二级水系",
    3: "三级水系",
    4: "四级水系",
}
BOUNDARY_SIMPLIFY_TOLERANCE = {
    "low": 0.02,
    "medium": 0.006,
    "high": 0.001,
}
_EMBEDDED_ROWS_CACHE: list[dict[str, Any]] | None = None


@dataclass(slots=True)
class SourceFeature:
    layer_name: str
    attributes: dict[str, Any]
    geometry: dict[str, Any]


def _resolve_source_path(source: str) -> Path:
    candidate = Path(source).expanduser()
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"未找到水系 Shapefile zip：{candidate}")


def _zip_member(zip_file: zipfile.ZipFile, layer_name: str, suffix: str) -> str | None:
    expected = f"{layer_name}.{suffix}".lower()
    for name in zip_file.namelist():
        if Path(name).name.lower() == expected:
            return name
    return None


def _read_layer_features(zip_file: zipfile.ZipFile, layer_name: str) -> list[SourceFeature]:
    shp_name = _zip_member(zip_file, layer_name, "shp")
    dbf_name = _zip_member(zip_file, layer_name, "dbf")
    shx_name = _zip_member(zip_file, layer_name, "shx")
    cpg_name = _zip_member(zip_file, layer_name, "cpg")
    if not shp_name or not dbf_name:
        return []
    encoding = "utf-8"
    if cpg_name:
        raw_encoding = zip_file.read(cpg_name).decode("ascii", "ignore").strip()
        if raw_encoding:
            encoding = "utf-8" if raw_encoding.upper() in {"UTF-8", "65001"} else raw_encoding
    if shapefile is not None:
        return _read_with_pyshp(
            layer_name,
            zip_file.read(shp_name),
            zip_file.read(dbf_name),
            zip_file.read(shx_name) if shx_name else None,
            encoding,
        )
    return _read_with_minimal_parser(layer_name, zip_file.read(shp_name), zip_file.read(dbf_name), encoding)


def _read_with_pyshp(
    layer_name: str,
    shp_bytes: bytes,
    dbf_bytes: bytes,
    shx_bytes: bytes | None,
    encoding: str,
) -> list[SourceFeature]:
    reader = shapefile.Reader(  # type: ignore[union-attr]
        shp=io.BytesIO(shp_bytes),
        shx=io.BytesIO(shx_bytes) if shx_bytes else None,
        dbf=io.BytesIO(dbf_bytes),
        encoding=encoding,
    )
    field_names = [field[0] for field in reader.fields if field[0] != "DeletionFlag"]
    features: list[SourceFeature] = []
    for shape_record in reader.iterShapeRecords():
        attributes = dict(zip(field_names, list(shape_record.record), strict=False))
        geometry = _jsonable_geometry(shape_record.shape.__geo_interface__)
        if geometry:
            features.append(SourceFeature(layer_name=layer_name, attributes=attributes, geometry=geometry))
    return features


def _read_with_minimal_parser(
    layer_name: str,
    shp_bytes: bytes,
    dbf_bytes: bytes,
    encoding: str,
) -> list[SourceFeature]:
    records = _parse_dbf_records(dbf_bytes, encoding)
    geometries = _parse_polygon_shp(shp_bytes)
    return [
        SourceFeature(layer_name=layer_name, attributes=attributes, geometry=geometry)
        for attributes, geometry in zip(records, geometries, strict=False)
        if geometry
    ]


def _parse_dbf_records(data: bytes, encoding: str) -> list[dict[str, str]]:
    if len(data) < 32:
        return []
    record_count = struct.unpack("<I", data[4:8])[0]
    header_length = struct.unpack("<H", data[8:10])[0]
    record_length = struct.unpack("<H", data[10:12])[0]
    fields: list[tuple[str, int]] = []
    offset = 32
    while offset + 32 <= header_length and data[offset] != 0x0D:
        descriptor = data[offset : offset + 32]
        name = descriptor[:11].split(b"\x00", 1)[0].decode("ascii", "replace").strip()
        fields.append((name, descriptor[16]))
        offset += 32
    rows: list[dict[str, str]] = []
    for index in range(record_count):
        record = data[header_length + index * record_length : header_length + (index + 1) * record_length]
        if not record or record[0:1] == b"*":
            continue
        cursor = 1
        row: dict[str, str] = {}
        for name, field_length in fields:
            raw = record[cursor : cursor + field_length]
            cursor += field_length
            row[name] = raw.decode(encoding, "replace").strip()
        rows.append(row)
    return rows


def _parse_polygon_shp(data: bytes) -> list[dict[str, Any]]:
    geometries: list[dict[str, Any]] = []
    offset = 100
    while offset + 8 <= len(data):
        _, content_length_words = struct.unpack(">2i", data[offset : offset + 8])
        offset += 8
        record = data[offset : offset + content_length_words * 2]
        offset += content_length_words * 2
        if len(record) < 44 or struct.unpack("<i", record[:4])[0] != 5:
            geometries.append({})
            continue
        part_count, point_count = struct.unpack("<2i", record[36:44])
        parts = list(struct.unpack(f"<{part_count}i", record[44 : 44 + 4 * part_count])) if part_count else []
        points_offset = 44 + 4 * part_count
        points = [
            list(struct.unpack("<2d", record[points_offset + index * 16 : points_offset + index * 16 + 16]))
            for index in range(point_count)
        ]
        rings: list[list[list[float]]] = []
        ends = parts[1:] + [point_count]
        for start, end in zip(parts, ends, strict=False):
            ring = points[start:end]
            if len(ring) >= 3:
                rings.append(ring)
        geometries.append({"type": "MultiPolygon", "coordinates": [[ring] for ring in rings]})
    return geometries


def _jsonable_geometry(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    geometry_type = str(value.get("type") or "")
    coordinates = value.get("coordinates")
    if geometry_type == "Polygon":
        return {"type": "Polygon", "coordinates": _jsonable_coordinates(coordinates)}
    if geometry_type == "MultiPolygon":
        return {"type": "MultiPolygon", "coordinates": _jsonable_coordinates(coordinates)}
    return {}


def _jsonable_coordinates(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return [_jsonable_coordinates(item) for item in value]
    if isinstance(value, (int, float)):
        return float(value)
    return value


def _feature_codes(remark: str) -> tuple[str, str, str, str]:
    feature_type = "OTHER"
    if "湖" in remark:
        feature_type = "LAKE"
    elif "水库" in remark:
        feature_type = "RESERVOIR"
    elif "河" in remark or "江" in remark:
        feature_type = "RIVER"

    hydrology_period = "UNKNOWN"
    if "常年" in remark:
        hydrology_period = "PERENNIAL"
    elif "时令" in remark:
        hydrology_period = "SEASONAL"

    salinity = "UNKNOWN"
    if "咸" in remark:
        salinity = "SALINE"
    elif "淡" in remark:
        salinity = "FRESH"

    boundary_type = "OTHER"
    if "界河" in remark:
        boundary_type = "BOUNDARY_RIVER"
    elif "双线河" in remark:
        boundary_type = "DOUBLE_LINE_RIVER"
    elif feature_type in {"LAKE", "RESERVOIR"}:
        boundary_type = "WATER_BODY"
    elif feature_type == "RIVER":
        boundary_type = "STANDARD"
    return feature_type, hydrology_period, salinity, boundary_type


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _int_or_zero(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _boundary_paths_for_tolerance(polygons: BoundaryPolygons, tolerance: float) -> list[list[tuple[float, float]]]:
    paths: list[list[tuple[float, float]]] = []
    for polygon in polygons:
        if not polygon:
            continue
        exterior = polygon[0]
        simplified = _simplify_ring(exterior, tolerance)
        if len(simplified) >= 4:
            paths.append(simplified)
    return paths


def _simplify_ring(ring: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    if len(ring) < 4:
        return ring
    closed = ring[0] == ring[-1]
    source = ring[:-1] if closed else ring
    simplified = _rdp_simplify(source, tolerance)
    if len(simplified) < 3:
        simplified = source[:3]
    if simplified[0] != simplified[-1]:
        simplified.append(simplified[0])
    return simplified


def _rdp_simplify(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    if len(points) <= 3:
        return points
    first = points[0]
    last = points[-1]
    max_distance = -1.0
    split_index = 0
    for index in range(1, len(points) - 1):
        distance = _perpendicular_distance(points[index], first, last)
        if distance > max_distance:
            max_distance = distance
            split_index = index
    if max_distance > tolerance:
        left = _rdp_simplify(points[: split_index + 1], tolerance)
        right = _rdp_simplify(points[split_index:], tolerance)
        return left[:-1] + right
    return [first, last]


def _perpendicular_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    x, y = point
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    return abs(dy * x - dx * y + x2 * y1 - y2 * x1) / ((dx * dx + dy * dy) ** 0.5)


def _geometry_counts(polygons: BoundaryPolygons) -> tuple[int, int]:
    ring_count = sum(len(polygon) for polygon in polygons)
    point_count = sum(len(ring) for polygon in polygons for ring in polygon)
    return ring_count, point_count


def _geometry_center(polygons: BoundaryPolygons) -> tuple[float | None, float | None]:
    bbox = polygons_bbox(polygons)
    if bbox is None:
        return None, None
    min_lng, min_lat, max_lng, max_lat = bbox
    return (min_lng + max_lng) / 2, (min_lat + max_lat) / 2


def load_embedded_water_system_rows() -> list[dict[str, Any]]:
    global _EMBEDDED_ROWS_CACHE
    if _EMBEDDED_ROWS_CACHE is None:
        payload = "".join(embedded_water_systems.COMPRESSED_ROWS)
        raw = zlib.decompress(base64.b64decode(payload)).decode("utf-8")
        records = json.loads(raw)
        _EMBEDDED_ROWS_CACHE = [
            dict(zip(embedded_water_systems.FIELDS, record, strict=True))
            for record in records
        ]
    return list(_EMBEDDED_ROWS_CACHE)


def _seed_rows_from_embedded(levels: tuple[int, ...]) -> list[dict[str, Any]]:
    requested_levels = {level for level in levels if level in LEVEL_LAYER_NAMES}
    if requested_levels == set(DEFAULT_LEVELS):
        return load_embedded_water_system_rows()
    return [
        row for row in load_embedded_water_system_rows()
        if requested_levels.intersection({int(level) for level in row.get("source_levels") or []})
    ]


def _seed_rows_from_zip(source: str, levels: tuple[int, ...]) -> list[dict[str, Any]]:
    source_path = _resolve_source_path(source)
    requested_levels = tuple(level for level in levels if level in LEVEL_LAYER_NAMES)
    rows: list[dict[str, Any]] = []
    with zipfile.ZipFile(source_path) as zip_file:
        for level in requested_levels:
            layer_name = LEVEL_LAYER_NAMES[level]
            for feature in _read_layer_features(zip_file, layer_name):
                row = _seed_row_from_feature(level, layer_name, feature)
                if row is not None:
                    rows.append(row)
    return rows


def _seed_row_from_feature(level: int, layer_name: str, feature: SourceFeature) -> dict[str, Any] | None:
    attrs = feature.attributes
    object_id = _int_or_zero(attrs.get("OBJECTID"))
    if not object_id:
        return None
    raw_name = str(attrs.get("NAME") or "").strip()
    source_remark = str(attrs.get("REMARK") or "").strip() or None
    feature_type, hydrology_period, salinity, boundary_type = _feature_codes(source_remark or "")
    polygons = extract_geojson_polygons(feature.geometry)
    bbox = polygons_bbox(polygons)
    if not polygons or bbox is None:
        geometry_status_code = "MISSING"
        min_lng = min_lat = max_lng = max_lat = None
    else:
        geometry_status_code = "AVAILABLE"
        min_lng, min_lat, max_lng, max_lat = bbox
    center_lng, center_lat = _geometry_center(polygons)
    ring_count, point_count = _geometry_counts(polygons)
    return {
        "water_system_code": f"WS-L{level}-{object_id}",
        "water_system_name": raw_name or f"未命名水系-L{level}-{object_id}",
        "water_level": level,
        "feature_type_code": feature_type,
        "hydrology_period_code": hydrology_period,
        "salinity_type_code": salinity,
        "water_boundary_type_code": boundary_type,
        "source_remark": source_remark,
        "source_layer_name": layer_name,
        "source_version": SOURCE_VERSION,
        "sort_order": level * 100000 + object_id,
        "geometry_json": feature.geometry,
        "boundary_paths_low": serialize_boundary_paths(
            _boundary_paths_for_tolerance(polygons, BOUNDARY_SIMPLIFY_TOLERANCE["low"])
        )
        or [],
        "boundary_paths_medium": serialize_boundary_paths(
            _boundary_paths_for_tolerance(polygons, BOUNDARY_SIMPLIFY_TOLERANCE["medium"])
        )
        or [],
        "boundary_paths_high": serialize_boundary_paths(
            _boundary_paths_for_tolerance(polygons, BOUNDARY_SIMPLIFY_TOLERANCE["high"])
        )
        or [],
        "center_longitude": center_lng,
        "center_latitude": center_lat,
        "bbox_min_lng": min_lng,
        "bbox_min_lat": min_lat,
        "bbox_max_lng": max_lng,
        "bbox_max_lat": max_lat,
        "source_shape_length_degree": _decimal_or_none(attrs.get("Shape_Leng")),
        "source_shape_area_degree": _decimal_or_none(attrs.get("Shape_Area")),
        "ring_count": ring_count,
        "point_count": point_count,
        "geometry_status_code": geometry_status_code,
    }


async def seed_water_systems(source: str | None = None, levels: tuple[int, ...] = DEFAULT_LEVELS) -> dict[str, int]:
    if source:
        _resolve_source_path(source)
    rows = _seed_rows_from_embedded(levels)
    now = datetime.utcnow()
    inserted = 0
    updated = 0
    skipped = 0
    removed = 0
    async with AsyncSessionLocal() as session:
        current_codes: set[str] = set()
        for row in rows:
            water_system_code = str(row.get("water_system_code") or "").strip()
            if not water_system_code:
                skipped += 1
                continue
            current_codes.add(water_system_code)
            water_system = await session.scalar(
                select(WaterSystem).where(WaterSystem.water_system_code == water_system_code)
            )
            payload = {
                "water_system_name": row["water_system_name"],
                "standard_name": row.get("standard_name") or row["water_system_name"],
                "display_name": row.get("display_name") or row["water_system_name"],
                "water_level": int(row["water_level"]),
                "feature_type_code": row["feature_type_code"],
                "hydrology_period_code": row["hydrology_period_code"],
                "salinity_type_code": row["salinity_type_code"],
                "water_boundary_type_code": row["water_boundary_type_code"],
                "navigation_category_code": row.get("navigation_category_code"),
                "navigation_scope_code": row.get("navigation_scope_code"),
                "ais_situation_scope": row.get("ais_situation_scope"),
                "display_priority": int(row.get("display_priority") or row["sort_order"]),
                "match_level_code": row.get("match_level_code"),
                "match_confidence_code": row.get("match_confidence_code"),
                "review_required": bool(row.get("review_required")),
                "source_feature_count": int(row.get("source_feature_count") or 0),
                "source_object_ids": row.get("source_object_ids") or [],
                "source_levels": row.get("source_levels") or [],
                "source_layer_names": row.get("source_layer_names") or [],
                "source_names": row.get("source_names") or [],
                "source_remarks": row.get("source_remarks") or [],
                "geometry_union_status": row.get("geometry_union_status"),
                "business_remark": row.get("business_remark"),
                "source_remark": row.get("source_remark"),
                "source_layer_name": row["source_layer_name"],
                "source_version": row.get("source_version") or SOURCE_VERSION,
                "is_enabled": True,
                "sort_order": int(row["sort_order"]),
            }
            if water_system is None:
                water_system = WaterSystem(water_system_code=water_system_code, **payload)
                session.add(water_system)
                await session.flush()
                inserted += 1
            else:
                for key, value in payload.items():
                    setattr(water_system, key, value)
                updated += 1

            boundary = await session.scalar(
                select(WaterSystemBoundary).where(
                    WaterSystemBoundary.water_system_id == water_system.id,
                    WaterSystemBoundary.is_current.is_(True),
                )
            )
            boundary_payload = {
                "geometry_json": row["geometry_json"],
                "boundary_paths_low": row.get("boundary_paths_low") or [],
                "boundary_paths_medium": row.get("boundary_paths_medium") or [],
                "boundary_paths_high": row.get("boundary_paths_high") or [],
                "center_longitude": row.get("center_longitude"),
                "center_latitude": row.get("center_latitude"),
                "bbox_min_lng": row.get("bbox_min_lng"),
                "bbox_min_lat": row.get("bbox_min_lat"),
                "bbox_max_lng": row.get("bbox_max_lng"),
                "bbox_max_lat": row.get("bbox_max_lat"),
                "source_shape_length_degree": _decimal_or_none(row.get("source_shape_length_degree")),
                "source_shape_area_degree": _decimal_or_none(row.get("source_shape_area_degree")),
                "ring_count": int(row.get("ring_count") or 0),
                "point_count": int(row.get("point_count") or 0),
                "geometry_status_code": row.get("geometry_status_code") or "AVAILABLE",
                "is_current": True,
                "imported_at": now,
            }
            if boundary is None:
                session.add(WaterSystemBoundary(water_system_id=water_system.id, **boundary_payload))
            else:
                for key, value in boundary_payload.items():
                    setattr(boundary, key, value)
        stale_condition = or_(
            WaterSystem.source_version == OLD_SOURCE_VERSION,
            WaterSystem.water_system_code.like("WS-L1-%"),
            WaterSystem.water_system_code.like("WS-L2-%"),
            WaterSystem.water_system_code.like("WS-L3-%"),
            WaterSystem.water_system_code.like("WS-L4-%"),
        )
        if set(levels) == set(DEFAULT_LEVELS) and current_codes:
            stale_condition = or_(
                stale_condition,
                and_(
                    WaterSystem.source_version == SOURCE_VERSION,
                    WaterSystem.water_system_code.not_in(current_codes),
                ),
            )
        stale_ids = select(WaterSystem.id).where(stale_condition)
        await session.execute(
            delete(WaterSystemBoundary).where(WaterSystemBoundary.water_system_id.in_(stale_ids))
        )
        delete_result = await session.execute(delete(WaterSystem).where(stale_condition))
        removed = int(delete_result.rowcount or 0)
        await session.commit()
    return {"inserted": inserted, "updated": updated, "skipped": skipped, "removed": removed}


def _parse_levels(value: str | None) -> tuple[int, ...]:
    if not value:
        return DEFAULT_LEVELS
    levels: list[int] = []
    for part in value.split(","):
        text = part.strip()
        if not text:
            continue
        level = int(text)
        if level not in LEVEL_LAYER_NAMES:
            raise ValueError("levels 仅支持 1,2,3,4")
        levels.append(level)
    return tuple(levels) or DEFAULT_LEVELS


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Seed preset water system boundaries.")
    parser.add_argument("--source", default=None, help="校验 revier.zip 是否存在；正式导入始终使用内置清洗预制数据")
    parser.add_argument("--levels", default="1,2,3,4", help="导入层级，逗号分隔，默认 1,2,3,4")
    args = parser.parse_args()
    result = await seed_water_systems(args.source, _parse_levels(args.levels))
    print(
        "seed_water_systems completed: "
        f"inserted={result['inserted']} updated={result['updated']} "
        f"skipped={result['skipped']} removed={result['removed']}"
    )


if __name__ == "__main__":
    asyncio.run(_main())
