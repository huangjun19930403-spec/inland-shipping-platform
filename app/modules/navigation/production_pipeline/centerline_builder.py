from __future__ import annotations

from typing import Any

from pyproj import Geod
from shapely import make_valid
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Point, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry

GEOD = Geod(ellps="WGS84")


def line_length_m(line: LineString) -> float:
    coords = list(line.coords)
    if len(coords) < 2:
        return 0.0
    lngs = [float(coord[0]) for coord in coords]
    lats = [float(coord[1]) for coord in coords]
    return abs(float(GEOD.line_length(lngs, lats)))


def point_distance_m(a: Point, b: Point) -> float:
    _, _, distance_m = GEOD.inv(a.x, a.y, b.x, b.y)
    return abs(float(distance_m))


def clean_line_coords(coords: list[tuple[float, float]]) -> list[tuple[float, float]]:
    cleaned: list[tuple[float, float]] = []
    for lng, lat in coords:
        point = (round(float(lng), 7), round(float(lat), 7))
        if cleaned and abs(cleaned[-1][0] - point[0]) < 1e-9 and abs(cleaned[-1][1] - point[1]) < 1e-9:
            continue
        cleaned.append(point)
    return cleaned


def longest_line(geometry: BaseGeometry) -> LineString | None:
    if geometry.is_empty:
        return None
    if isinstance(geometry, LineString):
        return geometry if len(geometry.coords) >= 2 else None
    if isinstance(geometry, MultiLineString):
        lines = [item for item in geometry.geoms if len(item.coords) >= 2]
        return max(lines, key=line_length_m) if lines else None
    if isinstance(geometry, GeometryCollection):
        lines = [line for part in geometry.geoms if (line := longest_line(part)) is not None]
        return max(lines, key=line_length_m) if lines else None
    return None


def _polygon_parts(geometry: BaseGeometry) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        parts: list[Polygon] = []
        for item in geometry.geoms:
            parts.extend(_polygon_parts(item))
        return parts
    return []


def _ring_path_between(coords: list[tuple[float, float]], start: int, end: int) -> list[tuple[float, float]]:
    output: list[tuple[float, float]] = []
    index = start
    size = len(coords)
    while True:
        output.append(coords[index])
        if index == end:
            break
        index = (index + 1) % size
    return output


def _farthest_ring_pair(coords: list[tuple[float, float]]) -> tuple[int, int] | None:
    if len(coords) < 2:
        return None
    step = max(1, len(coords) // 450)
    sampled_indexes = list(range(0, len(coords), step))
    best: tuple[float, int, int] | None = None
    for left_pos, left_index in enumerate(sampled_indexes):
        left = coords[left_index]
        for right_index in sampled_indexes[left_pos + 1 :]:
            right = coords[right_index]
            distance = (left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2
            if best is None or distance > best[0]:
                best = (distance, left_index, right_index)
    if best is None:
        return None
    return best[1], best[2]


def _bank_paired_centerline(polygon: Polygon) -> LineString | None:
    coords = [(float(lng), float(lat)) for lng, lat, *_rest in polygon.exterior.coords[:-1]]
    if len(coords) < 4:
        return None
    farthest = _farthest_ring_pair(coords)
    if farthest is None:
        return None
    start_index, end_index = farthest
    if len(coords) < 6:
        start = Point(coords[start_index])
        end = Point(coords[end_index])
        chord = LineString([start, end])
        line = LineString(
            clean_line_coords(
                [
                    tuple(chord.interpolate(index / 7.0, normalized=True).coords[0])
                    for index in range(8)
                ]
            )
        )
        return line if len(line.coords) >= 2 and line_length_m(line) >= 100.0 else None

    left_bank = LineString(_ring_path_between(coords, start_index, end_index))
    right_bank = LineString(_ring_path_between(coords, end_index, start_index))
    bank_length_m = max(line_length_m(left_bank), line_length_m(right_bank))
    if bank_length_m < 100.0:
        return None
    sample_count = max(8, min(240, int(bank_length_m / 1200.0)))
    center_coords: list[tuple[float, float]] = []
    for index in range(sample_count):
        ratio = index / max(sample_count - 1, 1)
        left_point = left_bank.interpolate(ratio, normalized=True)
        right_point = right_bank.interpolate(1.0 - ratio, normalized=True)
        center_coords.append(
            (
                (float(left_point.x) + float(right_point.x)) / 2.0,
                (float(left_point.y) + float(right_point.y)) / 2.0,
            )
        )
    cleaned = clean_line_coords(center_coords)
    if len(cleaned) < 2:
        return None
    line = LineString(cleaned)
    min_lng, min_lat, max_lng, max_lat = polygon.bounds
    if (max_lat - min_lat) >= (max_lng - min_lng):
        if line.coords[0][1] > line.coords[-1][1]:
            line = LineString(list(line.coords)[::-1])
    elif line.coords[0][0] > line.coords[-1][0]:
        line = LineString(list(line.coords)[::-1])
    return line if line_length_m(line) >= 100.0 else None


def _cross_section_centerline(polygon: Polygon, *, axis: str = "auto") -> LineString | None:
    geometry = make_valid(polygon)
    if geometry.is_empty:
        return None
    min_lng, min_lat, max_lng, max_lat = geometry.bounds
    span_lng = float(max_lng - min_lng)
    span_lat = float(max_lat - min_lat)
    span = max(span_lng, span_lat)
    if span <= 0:
        return None

    sample_count = 240 if span > 0.2 else 160
    margin = span * 0.03
    coords: list[tuple[float, float]] = []
    scan_lng = span_lng >= span_lat if axis == "auto" else axis == "lng"
    if scan_lng:
        for index in range(sample_count):
            lng = min_lng + span_lng * index / max(sample_count - 1, 1)
            cutter = LineString([(lng, min_lat - margin), (lng, max_lat + margin)])
            section = longest_line(geometry.intersection(cutter))
            if section is None:
                continue
            point = section.interpolate(0.5, normalized=True)
            coords.append((float(point.x), float(point.y)))
    else:
        for index in range(sample_count):
            lat = min_lat + span_lat * index / max(sample_count - 1, 1)
            cutter = LineString([(min_lng - margin, lat), (max_lng + margin, lat)])
            section = longest_line(geometry.intersection(cutter))
            if section is None:
                continue
            point = section.interpolate(0.5, normalized=True)
            coords.append((float(point.x), float(point.y)))

    cleaned = clean_line_coords(coords)
    if len(cleaned) < 2:
        return None
    line = LineString(cleaned)
    return line if line_length_m(line) >= 100.0 else None


def _candidate_rank(line: LineString, validation: dict[str, Any]) -> tuple[float, int, float, float]:
    blocking_count = len(validation.get("blocking_issue_codes") or [])
    foldback_count = int(validation.get("foldback_count") or 0)
    outside_ratio = float(validation.get("outside_ratio") or 0.0)
    return (
        float(blocking_count),
        foldback_count,
        outside_ratio,
        -line_length_m(line),
    )


def _best_polygon_centerline(polygon: Polygon) -> LineString | None:
    candidates: list[LineString] = []
    seen: set[tuple[tuple[float, float], tuple[float, float], int]] = set()
    for candidate in (
        _bank_paired_centerline(polygon),
        _cross_section_centerline(polygon, axis="auto"),
        _cross_section_centerline(polygon, axis="lng"),
        _cross_section_centerline(polygon, axis="lat"),
    ):
        if candidate is None:
            continue
        key = (
            (round(float(candidate.coords[0][0]), 7), round(float(candidate.coords[0][1]), 7)),
            (round(float(candidate.coords[-1][0]), 7), round(float(candidate.coords[-1][1]), 7)),
            len(candidate.coords),
        )
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    if not candidates:
        return None
    boundary_json = mapping(polygon)
    ranked = [
        (_candidate_rank(candidate, validate_centerline_against_boundary(candidate, boundary_json)), candidate)
        for candidate in candidates
    ]
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1]


def derive_boundary_centerlines(boundary_geometry_json: dict[str, Any]) -> list[LineString]:
    try:
        raw_geometry = shape(boundary_geometry_json)
    except Exception:
        return []
    if raw_geometry.is_empty:
        return []
    geometry = raw_geometry if isinstance(raw_geometry, (Polygon, MultiPolygon)) else make_valid(raw_geometry)
    lines: list[LineString] = []
    for polygon in sorted(_polygon_parts(geometry), key=lambda item: item.area, reverse=True):
        if polygon.is_empty or polygon.area <= 0:
            continue
        valid_polygon = polygon if polygon.is_valid else make_valid(polygon)
        for part in _polygon_parts(valid_polygon):
            line = _best_polygon_centerline(part)
            if line is None:
                continue
            lines.append(line)
    return lines


def derive_boundary_centerline(boundary_geometry_json: dict[str, Any]) -> LineString | None:
    component_lines = derive_boundary_centerlines(boundary_geometry_json)
    if component_lines:
        ordered = _connect_component_lines(component_lines)
        if ordered is not None:
            return ordered

    try:
        geometry = make_valid(shape(boundary_geometry_json))
    except Exception:
        return None
    if geometry.is_empty:
        return None
    min_lng, min_lat, max_lng, max_lat = geometry.bounds
    span_lng = float(max_lng - min_lng)
    span_lat = float(max_lat - min_lat)
    span = max(span_lng, span_lat)
    if span <= 0:
        return None

    try:
        simplified = make_valid(geometry.simplify(max(span / 1600.0, 0.00005), preserve_topology=True))
        if not simplified.is_empty:
            geometry = simplified
            min_lng, min_lat, max_lng, max_lat = geometry.bounds
            span_lng = float(max_lng - min_lng)
            span_lat = float(max_lat - min_lat)
            span = max(span_lng, span_lat)
    except Exception:
        pass

    sample_count = 220 if span > 10 else 160 if span > 4 else 96
    margin = max(span_lng, span_lat) * 0.03
    coords: list[tuple[float, float]] = []
    if span_lng >= span_lat:
        for index in range(sample_count):
            lng = min_lng + span_lng * index / max(sample_count - 1, 1)
            cutter = LineString([(lng, min_lat - margin), (lng, max_lat + margin)])
            section = longest_line(geometry.intersection(cutter))
            if section is None:
                continue
            point = section.interpolate(0.5, normalized=True)
            coords.append((float(point.x), float(point.y)))
    else:
        for index in range(sample_count):
            lat = min_lat + span_lat * index / max(sample_count - 1, 1)
            cutter = LineString([(min_lng - margin, lat), (max_lng + margin, lat)])
            section = longest_line(geometry.intersection(cutter))
            if section is None:
                continue
            point = section.interpolate(0.5, normalized=True)
            coords.append((float(point.x), float(point.y)))

    cleaned = clean_line_coords(coords)
    if len(cleaned) < 2:
        return None
    line = LineString(cleaned)
    if line_length_m(line) < 100.0:
        return None
    return line


def _connect_component_lines(lines: list[LineString]) -> LineString | None:
    if not lines:
        return None
    remaining = list(lines)
    first = min(remaining, key=lambda item: min(item.coords[0][1], item.coords[-1][1], item.coords[0][0], item.coords[-1][0]))
    remaining.remove(first)
    coords = list(first.coords)
    while remaining:
        end_point = Point(coords[-1])
        best: tuple[float, int, bool] | None = None
        for index, line in enumerate(remaining):
            start_distance = point_distance_m(end_point, Point(line.coords[0]))
            end_distance = point_distance_m(end_point, Point(line.coords[-1]))
            candidate = (min(start_distance, end_distance), index, end_distance < start_distance)
            if best is None or candidate[0] < best[0]:
                best = candidate
        if best is None:
            break
        _distance_m, index, reverse = best
        line = remaining.pop(index)
        line_coords = list(line.coords)
        if reverse:
            line_coords.reverse()
        coords.extend(line_coords)
    cleaned = clean_line_coords([(float(lng), float(lat)) for lng, lat in coords])
    if len(cleaned) < 2:
        return None
    return LineString(cleaned)


def validate_centerline_against_boundary(
    line: LineString,
    boundary_geometry_json: dict[str, Any],
    *,
    min_point_count: int = 8,
    max_outside_ratio: float = 0.02,
) -> dict[str, Any]:
    issues: list[str] = []
    point_count = len(line.coords)
    length_m = line_length_m(line)
    if point_count < min_point_count:
        issues.append("CENTERLINE_POINT_COUNT_TOO_LOW")
    if length_m <= 100.0:
        issues.append("CENTERLINE_LENGTH_TOO_SHORT")

    endpoint_distance_m = 0.0
    if point_count >= 2:
        endpoint_distance_m = point_distance_m(Point(line.coords[0]), Point(line.coords[-1]))
        directness_ratio = endpoint_distance_m / length_m if length_m > 0 else 1.0
        if length_m > 5000.0 and directness_ratio > 0.985:
            issues.append("CENTERLINE_NEAR_STRAIGHT_REFERENCE")
    else:
        directness_ratio = 1.0

    try:
        boundary = make_valid(shape(boundary_geometry_json))
        tolerance = max(max(boundary.bounds[2] - boundary.bounds[0], boundary.bounds[3] - boundary.bounds[1]) / 5000.0, 0.00003)
        buffered = boundary.buffer(tolerance)
        sample_count = min(max(point_count * 2, 16), 160)
        outside_count = 0
        for index in range(sample_count):
            point = line.interpolate(index / max(sample_count - 1, 1), normalized=True)
            if not buffered.covers(point):
                outside_count += 1
        outside_ratio = outside_count / sample_count if sample_count else 1.0
        if outside_ratio > max_outside_ratio:
            issues.append("CENTERLINE_OUTSIDE_BOUNDARY")
    except Exception:
        outside_count = 0
        outside_ratio = 0.0
        issues.append("CENTERLINE_BOUNDARY_VALIDATION_FAILED")

    foldback_count = _foldback_count(line)
    if foldback_count:
        issues.append("CENTERLINE_FOLDBACK_DETECTED")

    blocking = {
        "CENTERLINE_POINT_COUNT_TOO_LOW",
        "CENTERLINE_LENGTH_TOO_SHORT",
        "CENTERLINE_OUTSIDE_BOUNDARY",
        "CENTERLINE_BOUNDARY_VALIDATION_FAILED",
        "CENTERLINE_FOLDBACK_DETECTED",
    }
    blocking_issues = sorted(set(issues) & blocking)
    return {
        "status_code": "READY" if not blocking_issues else "FAILED",
        "quality_code": "READY_WITH_WARNING" if issues and not blocking_issues else "READY" if not issues else "FAILED",
        "issue_codes": sorted(set(issues)),
        "blocking_issue_codes": blocking_issues,
        "point_count": point_count,
        "length_m": round(length_m, 2),
        "endpoint_distance_m": round(endpoint_distance_m, 2),
        "directness_ratio": round(float(directness_ratio), 6),
        "outside_sample_count": outside_count,
        "outside_ratio": round(outside_ratio, 6),
        "foldback_count": foldback_count,
        "benchmark_policy": "no straight-line fallback; line must stay inside curated channel boundary",
    }


def _foldback_count(line: LineString) -> int:
    coords = list(line.coords)
    if len(coords) < 4:
        return 0
    reversals = 0
    previous: tuple[float, float] | None = None
    for index in range(1, len(coords)):
        dx = float(coords[index][0] - coords[index - 1][0])
        dy = float(coords[index][1] - coords[index - 1][1])
        norm = (dx * dx + dy * dy) ** 0.5
        if norm <= 1e-10:
            continue
        vector = (dx / norm, dy / norm)
        if previous is not None and (previous[0] * vector[0] + previous[1] * vector[1]) < -0.92:
            reversals += 1
        previous = vector
    return reversals


def line_seed_fields(line: LineString) -> dict[str, Any]:
    min_lng, min_lat, max_lng, max_lat = line.bounds
    coords = list(line.coords)
    return {
        "geometry_json": mapping(line),
        "length_m": round(line_length_m(line), 2),
        "start_lng": float(coords[0][0]),
        "start_lat": float(coords[0][1]),
        "end_lng": float(coords[-1][0]),
        "end_lat": float(coords[-1][1]),
        "bbox_min_lng": float(min_lng),
        "bbox_min_lat": float(min_lat),
        "bbox_max_lng": float(max_lng),
        "bbox_max_lat": float(max_lat),
    }
