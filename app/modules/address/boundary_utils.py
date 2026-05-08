"""Shared helpers for administrative boundary polygon rendering."""

from __future__ import annotations

from typing import Any

LngLat = tuple[float, float]
BoundaryRing = list[LngLat]
BoundaryPolygon = list[BoundaryRing]
BoundaryPolygons = list[BoundaryPolygon]

BOUNDARY_SIMPLIFY_TOLERANCE = {
    "low": 0.02,
    "medium": 0.006,
}


def extract_geojson_polygons(geometry: dict[str, Any]) -> BoundaryPolygons:
    geometry_type = str(geometry.get("type") or "").strip()
    if geometry_type == "Feature":
        return extract_geojson_polygons(geometry.get("geometry") or {})
    if geometry_type == "FeatureCollection":
        polygons: BoundaryPolygons = []
        for feature in geometry.get("features") or []:
            if isinstance(feature, dict):
                polygons.extend(extract_geojson_polygons(feature))
        return polygons
    if geometry_type == "Polygon":
        polygon = _normalize_polygon_coordinates(geometry.get("coordinates") or [])
        return [polygon] if polygon else []
    if geometry_type == "MultiPolygon":
        polygons: BoundaryPolygons = []
        for polygon_coordinates in geometry.get("coordinates") or []:
            polygon = _normalize_polygon_coordinates(polygon_coordinates)
            if polygon:
                polygons.append(polygon)
        return polygons
    return []


def polygons_bbox(polygons: BoundaryPolygons) -> tuple[float, float, float, float] | None:
    points = [point for polygon in polygons for ring in polygon for point in ring]
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def bbox_contains(bbox: tuple[float, float, float, float], longitude: float, latitude: float) -> bool:
    min_x, min_y, max_x, max_y = bbox
    return min_x <= longitude <= max_x and min_y <= latitude <= max_y


def point_in_polygon_with_holes(longitude: float, latitude: float, polygon: BoundaryPolygon) -> bool:
    if not polygon or not _point_in_ring(longitude, latitude, polygon[0]):
        return False
    return not any(_point_in_ring(longitude, latitude, hole) for hole in polygon[1:])


def boundary_paths_for_precision(polygons: BoundaryPolygons, precision: str) -> list[BoundaryRing]:
    paths: list[BoundaryRing] = []
    for polygon in polygons:
        if not polygon:
            continue
        exterior = polygon[0]
        simplified = _simplify_ring(exterior, precision)
        if len(simplified) >= 4:
            paths.append(simplified)
    return paths


def serialize_boundary_paths(paths: list[BoundaryRing] | None) -> list[list[list[float]]] | None:
    if not paths:
        return None
    return [[[float(lng), float(lat)] for lng, lat in ring] for ring in paths if len(ring) >= 4] or None


def _normalize_polygon_coordinates(value: Any) -> BoundaryPolygon:
    rings: BoundaryPolygon = []
    if not isinstance(value, list):
        return rings
    for raw_ring in value:
        ring: BoundaryRing = []
        if not isinstance(raw_ring, list):
            continue
        for raw_point in raw_ring:
            if not isinstance(raw_point, (list, tuple)) or len(raw_point) < 2:
                continue
            try:
                ring.append((float(raw_point[0]), float(raw_point[1])))
            except (TypeError, ValueError):
                continue
        if len(ring) >= 3:
            rings.append(ring)
    return rings


def _point_in_ring(longitude: float, latitude: float, ring: BoundaryRing) -> bool:
    inside = False
    count = len(ring)
    if count < 3:
        return False
    j = count - 1
    for i in range(count):
        xi, yi = ring[i]
        xj, yj = ring[j]
        intersects = ((yi > latitude) != (yj > latitude)) and (
            longitude < (xj - xi) * (latitude - yi) / ((yj - yi) or 1e-12) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def _perpendicular_distance(point: LngLat, start: LngLat, end: LngLat) -> float:
    x, y = point
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    return abs(dy * x - dx * y + x2 * y1 - y2 * x1) / ((dx * dx + dy * dy) ** 0.5)


def _rdp_simplify(points: BoundaryRing, tolerance: float) -> BoundaryRing:
    if len(points) <= 3:
        return points
    first = points[0]
    last = points[-1]
    max_distance = -1.0
    index = 0
    for idx in range(1, len(points) - 1):
        distance = _perpendicular_distance(points[idx], first, last)
        if distance > max_distance:
            max_distance = distance
            index = idx
    if max_distance > tolerance:
        left = _rdp_simplify(points[: index + 1], tolerance)
        right = _rdp_simplify(points[index:], tolerance)
        return left[:-1] + right
    return [first, last]


def _simplify_ring(ring: BoundaryRing, precision: str) -> BoundaryRing:
    tolerance = BOUNDARY_SIMPLIFY_TOLERANCE.get(precision, BOUNDARY_SIMPLIFY_TOLERANCE["low"])
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
