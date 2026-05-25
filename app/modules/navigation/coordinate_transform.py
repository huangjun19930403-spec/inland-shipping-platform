from __future__ import annotations

import math
from collections.abc import Callable
from copy import deepcopy
from typing import Any


WGS84 = "WGS84"
GCJ02_AMAP = "GCJ02_AMAP"

_A = 6378245.0
_EE = 0.00669342162296594323


def _out_of_china(lng: float, lat: float) -> bool:
    return lng < 72.004 or lng > 137.8347 or lat < 0.8293 or lat > 55.8271


def _transform_lat(lng: float, lat: float) -> float:
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * math.pi) + 40.0 * math.sin(lat / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * math.pi) + 320 * math.sin(lat * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(lng: float, lat: float) -> float:
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * math.pi) + 40.0 * math.sin(lng / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * math.pi) + 300.0 * math.sin(lng / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    if _out_of_china(lng, lat):
        return lng, lat
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - _EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrt_magic) * math.pi)
    dlng = (dlng * 180.0) / (_A / sqrt_magic * math.cos(radlat) * math.pi)
    return lng + dlng, lat + dlat


def gcj02_to_wgs84(lng: float, lat: float) -> tuple[float, float]:
    gcj_lng, gcj_lat = wgs84_to_gcj02(lng, lat)
    return lng * 2 - gcj_lng, lat * 2 - gcj_lat


def _transform_position(position: Any, fn: Callable[[float, float], tuple[float, float]]) -> Any:
    if not isinstance(position, list) or len(position) < 2:
        return position
    try:
        lng = float(position[0])
        lat = float(position[1])
    except (TypeError, ValueError):
        return position
    out_lng, out_lat = fn(lng, lat)
    transformed = [out_lng, out_lat]
    if len(position) > 2:
        transformed.extend(position[2:])
    return transformed


def _transform_coordinates(value: Any, fn: Callable[[float, float], tuple[float, float]]) -> Any:
    if not isinstance(value, list):
        return value
    if len(value) >= 2 and not isinstance(value[0], list):
        return _transform_position(value, fn)
    return [_transform_coordinates(item, fn) for item in value]


def transform_geojson_coordinates(
    geometry: dict[str, Any] | None,
    fn: Callable[[float, float], tuple[float, float]],
) -> dict[str, Any] | None:
    if not isinstance(geometry, dict):
        return geometry
    result = deepcopy(geometry)
    geometry_type = str(result.get("type") or "")
    if geometry_type == "Feature":
        feature_geometry = result.get("geometry")
        result["geometry"] = transform_geojson_coordinates(feature_geometry, fn) if isinstance(feature_geometry, dict) else feature_geometry
        return result
    if geometry_type == "FeatureCollection":
        features = result.get("features")
        if isinstance(features, list):
            result["features"] = [transform_geojson_coordinates(feature, fn) if isinstance(feature, dict) else feature for feature in features]
        return result
    if geometry_type == "GeometryCollection":
        geometries = result.get("geometries")
        if isinstance(geometries, list):
            result["geometries"] = [transform_geojson_coordinates(item, fn) if isinstance(item, dict) else item for item in geometries]
        return result
    if "coordinates" in result:
        result["coordinates"] = _transform_coordinates(result.get("coordinates"), fn)
    return result


def geometry_to_gcj02_json(geometry: dict[str, Any] | None) -> dict[str, Any] | None:
    return transform_geojson_coordinates(geometry, wgs84_to_gcj02)


def geometry_to_wgs84_json(geometry: dict[str, Any] | None) -> dict[str, Any] | None:
    return transform_geojson_coordinates(geometry, gcj02_to_wgs84)


def bbox_to_gcj02(bbox: dict[str, float] | None) -> dict[str, float] | None:
    if not bbox:
        return None
    values = [bbox.get("min_lng"), bbox.get("min_lat"), bbox.get("max_lng"), bbox.get("max_lat")]
    if any(value is None for value in values):
        return None
    min_lng, min_lat, max_lng, max_lat = (float(value) for value in values)
    points = [
        wgs84_to_gcj02(min_lng, min_lat),
        wgs84_to_gcj02(min_lng, max_lat),
        wgs84_to_gcj02(max_lng, min_lat),
        wgs84_to_gcj02(max_lng, max_lat),
    ]
    lngs = [point[0] for point in points]
    lats = [point[1] for point in points]
    return {"min_lng": min(lngs), "min_lat": min(lats), "max_lng": max(lngs), "max_lat": max(lats)}
