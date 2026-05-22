from __future__ import annotations

from typing import Iterable

from pyproj import Geod
from shapely.geometry import LineString, Point
from shapely.ops import substring

GEOD = Geod(ellps="WGS84")


def point_distance_m(a: Point, b: Point) -> float:
    _, _, distance_m = GEOD.inv(a.x, a.y, b.x, b.y)
    return abs(float(distance_m))


def line_length_km(line: LineString) -> float:
    if line.is_empty or len(line.coords) < 2:
        return 0.0
    lons = [float(coord[0]) for coord in line.coords]
    lats = [float(coord[1]) for coord in line.coords]
    return abs(float(GEOD.line_length(lons, lats))) / 1000.0


def nearest_point_on_line(line: LineString, point: Point) -> Point:
    return line.interpolate(line.project(point))


def line_segment_between(line: LineString, start_point: Point, end_point: Point) -> LineString:
    start = line.project(start_point)
    end = line.project(end_point)
    segment = substring(line, start, end)
    if isinstance(segment, Point) or segment.is_empty:
        return LineString([(start_point.x, start_point.y), (end_point.x, end_point.y)])
    if isinstance(segment, LineString):
        return segment
    return LineString(segment.coords)


def reverse_line(line: LineString) -> LineString:
    return LineString(list(line.coords)[::-1])


def merge_coordinates(lines: Iterable[LineString]) -> list[list[float]]:
    merged: list[list[float]] = []
    for line in lines:
        coords = [[float(lng), float(lat)] for lng, lat, *_ in line.coords]
        if not coords:
            continue
        if merged and merged[-1] == coords[0]:
            merged.extend(coords[1:])
        else:
            merged.extend(coords)
    return merged


def bbox_for_points(points: list[tuple[float, float]], margin_degree: float) -> dict[str, float]:
    min_lng = min(point[0] for point in points)
    min_lat = min(point[1] for point in points)
    max_lng = max(point[0] for point in points)
    max_lat = max(point[1] for point in points)
    return {
        "min_lng": min_lng - margin_degree,
        "min_lat": min_lat - margin_degree,
        "max_lng": max_lng + margin_degree,
        "max_lat": max_lat + margin_degree,
    }


def geometry_intersects_bbox(bounds: tuple[float, float, float, float], bbox: dict[str, float]) -> bool:
    min_lng, min_lat, max_lng, max_lat = bounds
    return bool(
        max_lng >= bbox["min_lng"]
        and min_lng <= bbox["max_lng"]
        and max_lat >= bbox["min_lat"]
        and min_lat <= bbox["max_lat"]
    )
