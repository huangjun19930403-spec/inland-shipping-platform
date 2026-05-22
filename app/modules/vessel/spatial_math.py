"""Pure helpers for vessel spatial observations."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import datetime
from decimal import Decimal
from typing import Any


def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    return value


def query_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(jsonable(payload), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None


def to_float(value: Any) -> float | None:
    decimal_value = to_decimal(value)
    return float(decimal_value) if decimal_value is not None else None


def source_status_name(code: str) -> str:
    return {"AVAILABLE": "可用", "EMPTY": "无数据", "UNCONFIGURED": "未配置", "PARTIAL": "部分可用", "ERROR": "异常"}.get(code, code)


def ais_freshness_level(age_minutes: int | None) -> str:
    if age_minutes is None:
        return "UNKNOWN"
    if age_minutes <= 120:
        return "FRESH"
    if age_minutes <= 720:
        return "RECENT"
    if age_minutes <= 4320:
        return "STALE"
    return "EXPIRED"


def valid_lon_lat(longitude: Any, latitude: Any) -> bool:
    lon = to_float(longitude)
    lat = to_float(latitude)
    return lon is not None and lat is not None and -180 <= lon <= 180 and -90 <= lat <= 90


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value is None:
        return None
    if isinstance(value, (int, float)):
        raw = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
        return datetime.utcfromtimestamp(raw)
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def first_value(source: dict[str, Any], keys: list[str]) -> Any:
    return next((source[key] for key in keys if source.get(key) is not None), None)


def distance_km(lon1: Any, lat1: Any, lon2: Any, lat2: Any) -> float | None:
    a_lon, a_lat, b_lon, b_lat = map(to_float, (lon1, lat1, lon2, lat2))
    if a_lon is None or a_lat is None or b_lon is None or b_lat is None:
        return None
    delta_phi = math.radians(b_lat - a_lat)
    delta_lambda = math.radians(b_lon - a_lon)
    phi1 = math.radians(a_lat)
    phi2 = math.radians(b_lat)
    hav = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return 2 * 6371.0088 * math.atan2(math.sqrt(hav), math.sqrt(1 - hav))


def within_distance_km(lon1: Any, lat1: Any, lon2: Any, lat2: Any, radius_km: float) -> bool:
    distance = distance_km(lon1, lat1, lon2, lat2)
    return distance is not None and distance <= radius_km


def point_segment_distance_km(point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]) -> float:
    lon0, lat0 = point
    lon1, lat1 = start
    lon2, lat2 = end
    ref_lat = math.radians((lat0 + lat1 + lat2) / 3)
    km_per_deg_lat = 111.32
    km_per_deg_lon = 111.32 * max(math.cos(ref_lat), 0.0001)
    px, py = lon0 * km_per_deg_lon, lat0 * km_per_deg_lat
    ax, ay = lon1 * km_per_deg_lon, lat1 * km_per_deg_lat
    bx, by = lon2 * km_per_deg_lon, lat2 * km_per_deg_lat
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    ratio = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + ratio * dx), py - (ay + ratio * dy))


def point_line_distance_km(point: tuple[float, float], line: list[tuple[float, float]]) -> float | None:
    return None if len(line) < 2 else min(point_segment_distance_km(point, line[index], line[index + 1]) for index in range(len(line) - 1))


def line_length_km(line: list[tuple[float, float]]) -> float:
    return sum((distance_km(*line[index], *line[index + 1]) or 0.0) for index in range(len(line) - 1))


def bearing_deg(start: tuple[float, float], end: tuple[float, float]) -> float | None:
    lon1, lat1 = map(math.radians, start)
    lon2, lat2 = map(math.radians, end)
    delta_lon = lon2 - lon1
    x = math.sin(delta_lon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
    return None if x == 0 and y == 0 else (math.degrees(math.atan2(x, y)) + 360) % 360


def angle_difference_deg(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def route_direction_consistency(line: list[tuple[float, float]], points: list[dict[str, Any]]) -> float | None:
    segment_bearing = bearing_deg(line[0], line[-1]) if len(line) >= 2 else None
    if segment_bearing is None:
        return None
    bearings: list[float] = []
    for point in points:
        heading = to_float(point.get("course_deg"))
        if heading is None:
            heading = to_float(point.get("heading_deg"))
        if heading is not None:
            bearings.append(heading % 360)
    ordered = sorted((point for point in points if point.get("position_time")), key=lambda item: item["position_time"])
    for index in range(len(ordered) - 1):
        start = (to_float(ordered[index].get("longitude")), to_float(ordered[index].get("latitude")))
        end = (to_float(ordered[index + 1].get("longitude")), to_float(ordered[index + 1].get("latitude")))
        if None in start or None in end:
            continue
        bearing = bearing_deg((start[0], start[1]), (end[0], end[1]))  # type: ignore[arg-type]
        if bearing is not None:
            bearings.append(bearing)
    if not bearings:
        return None
    avg_deviation = sum(angle_difference_deg(segment_bearing, bearing) for bearing in bearings) / len(bearings)
    return round(max(0.0, 100.0 - avg_deviation / 180.0 * 100.0), 2)


def parse_linestring(geometry: dict[str, Any] | None) -> list[tuple[float, float]]:
    if not isinstance(geometry, dict):
        return []
    coordinates = geometry["geometry"].get("coordinates") if geometry.get("type") == "Feature" and isinstance(geometry.get("geometry"), dict) else geometry.get("coordinates")
    raw_points = coordinates if geometry.get("type") == "LineString" and isinstance(coordinates, list) else geometry.get("path") or (geometry.get("paths") or [[]])[0]
    result: list[tuple[float, float]] = []
    for item in raw_points if isinstance(raw_points, list) else []:
        lon = to_float(item.get("longitude") or item.get("lng") or item.get("lon")) if isinstance(item, dict) else to_float(item[0]) if isinstance(item, (list, tuple)) and len(item) >= 2 else None
        lat = to_float(item.get("latitude") or item.get("lat")) if isinstance(item, dict) else to_float(item[1]) if isinstance(item, (list, tuple)) and len(item) >= 2 else None
        if lon is not None and lat is not None and valid_lon_lat(lon, lat):
            result.append((lon, lat))
    return result


def freshness_distribution(positions: list[Any]) -> dict[str, int]:
    result = {"FRESH": 0, "RECENT": 0, "STALE": 0, "EXPIRED": 0, "UNKNOWN": 0}
    for position in positions:
        level = getattr(position, "freshness_level", None) or "UNKNOWN"
        result[level] = result.get(level, 0) + 1
    return result


def code_distribution(items: list[Any], attr: str, *, code_key: str = "code", name_key: str = "name") -> list[dict[str, Any]]:
    total = max(len(items), 1)
    counts = Counter(getattr(item, attr) or "UNKNOWN" for item in items)
    return [{code_key: code, name_key: code, "count": count, "rate": round(count / total * 100, 2)} for code, count in counts.items()]


def coverage_rate(numerator: int, denominator: int | None) -> float | None:
    return None if not denominator else round(numerator / denominator * 100, 2)


def confidence_level(coverage_rate_value: float | None, has_sample: bool, partial: bool) -> str:
    if not has_sample:
        return "UNKNOWN"
    if partial:
        return "LOW"
    if coverage_rate_value is None:
        return "MEDIUM"
    return "HIGH" if coverage_rate_value >= 80 else "MEDIUM" if coverage_rate_value >= 40 else "LOW"


def avg(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    return round(sum(clean) / len(clean), 2) if clean else None
