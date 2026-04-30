"""Geometry helpers for foundation address boundary data."""

from __future__ import annotations

from typing import Any


GEOJSON_GEOMETRY_TYPES = {"Polygon", "MultiPolygon", "Feature", "FeatureCollection"}
SOURCE_TYPE_ALIASES = {
    "AMAP": "STANDARD_MAP_EXTRACTION",
    "MANUAL": "PLATFORM_DEFINED",
}


def normalize_boundary_source_type(code: str | None) -> str:
    text = (code or "").strip().upper()
    if not text:
        return "STANDARD_MAP_EXTRACTION"
    return SOURCE_TYPE_ALIASES.get(text, text)


def normalize_boundary_geometry(value: Any) -> dict[str, Any]:
    """Return a renderable GeoJSON object for existing boundary payload shapes."""

    if isinstance(value, dict):
        geometry_type = str(value.get("type") or "").strip()
        if geometry_type in GEOJSON_GEOMETRY_TYPES:
            return value
        wkt = value.get("wkt") or value.get("geometry_wkt")
        if isinstance(wkt, str) and wkt.strip():
            try:
                return wkt_to_geojson(wkt)
            except ValueError:
                return {}
        return value

    if isinstance(value, str) and value.strip():
        try:
            return wkt_to_geojson(value)
        except ValueError:
            return {}

    return {}


def wkt_to_geojson(wkt: str) -> dict[str, Any]:
    """Parse the POLYGON/MULTIPOLYGON WKT forms used by seeded admin boundaries."""

    text = _strip_srid(wkt).strip()
    upper = text.upper()
    if upper.startswith("POLYGON"):
        body = _strip_outer_parentheses(text[text.find("(") :])
        return {
            "type": "Polygon",
            "coordinates": [_parse_ring(ring) for ring in _split_parenthesized_groups(body)],
        }

    if upper.startswith("MULTIPOLYGON"):
        body = _strip_outer_parentheses(text[text.find("(") :])
        polygons = []
        for polygon_text in _split_parenthesized_groups(body):
            rings = [_parse_ring(ring) for ring in _split_parenthesized_groups(polygon_text)]
            if rings:
                polygons.append(rings)
        return {
            "type": "MultiPolygon",
            "coordinates": polygons,
        }

    raise ValueError("only POLYGON and MULTIPOLYGON WKT are supported")


def _strip_srid(wkt: str) -> str:
    if wkt.upper().startswith("SRID=") and ";" in wkt:
        return wkt.split(";", 1)[1]
    return wkt


def _strip_outer_parentheses(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("(") and stripped.endswith(")"):
        return stripped[1:-1].strip()
    return stripped


def _split_parenthesized_groups(text: str) -> list[str]:
    groups: list[str] = []
    depth = 0
    start: int | None = None
    for index, char in enumerate(text):
        if char == "(":
            if depth == 0:
                start = index + 1
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0 and start is not None:
                groups.append(text[start:index].strip())
                start = None
    if groups:
        return groups
    return [text.strip()] if text.strip() else []


def _parse_ring(text: str) -> list[list[float]]:
    points: list[list[float]] = []
    for raw_point in text.split(","):
        parts = raw_point.strip().split()
        if len(parts) < 2:
            continue
        try:
            points.append([float(parts[0]), float(parts[1])])
        except ValueError:
            continue
    return points
