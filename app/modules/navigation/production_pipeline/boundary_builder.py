from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, unary_union
from shapely.validation import make_valid

from app.modules.navigation.production_pipeline.centerline_builder import point_distance_m

BRIDGE_WATER_TYPES = {
    "CANAL",
    "PERENNIAL_DOUBLE_LINE_RIVER",
    "PERENNIAL_SINGLE_LINE_RIVER",
    "RIVER",
    "LAKE",
    "RESERVOIR",
}
DIRECT_MATCH_ROLES = {"HIERARCHY_LEVEL", "STANDARD"}
BRIDGE_MATCH_ROLES = {"HIERARCHY_LEVEL", "STANDARD"}
MIN_BRIDGE_INTERSECTION_AREA_DEGREE = 0.00001
MIN_COMPONENT_GAP_M = 1000.0
MAX_BRIDGE_BUFFER_DEGREE = 0.10
MIN_BRIDGE_BUFFER_DEGREE = 0.03
MAX_BRIDGE_ROWS_PER_GAP = 10


def load_navigation_channel_records(channel_seed_path: Path) -> list[dict[str, Any]]:
    payload = json.loads(channel_seed_path.read_text(encoding="utf-8"))
    return list(payload.get("records") or [])


def load_revier_water_area_seed_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def build_boundary_seed_rows(
    channel_records: list[dict[str, Any]],
    *,
    water_area_rows: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if water_area_rows:
        return _build_revier_water_boundary_rows(channel_records, water_area_rows)
    return _build_legacy_boundary_seed_rows(channel_records)


def _build_legacy_boundary_seed_rows(channel_records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    annotation_tasks: list[dict[str, Any]] = []
    for record in channel_records:
        channel = dict(record.get("channel") or {})
        boundary = dict(record.get("boundary") or {})
        channel_code = channel.get("channel_code")
        if not channel_code:
            continue
        if boundary.get("geometry_status_code") != "AVAILABLE" or not boundary.get("geometry_json"):
            annotation_tasks.append(
                {
                    "task_no": f"REV-BND-MISSING-{channel_code}",
                    "task_type_code": "BOUNDARY_REVIEW",
                    "target_type_code": "NAVIGATION_CHANNEL",
                    "target_code": channel_code,
                    "priority_code": "HIGH",
                    "status_code": "OPEN",
                    "issue_summary": "航道没有可用边界，revier 生产 seed 未生成该航道中心线。",
                    "suggestion_json": {"issue_code": "CHANNEL_BOUNDARY_MISSING"},
                }
            )
            continue
        boundary["channel_code"] = channel_code
        boundary["boundary_quality_code"] = boundary.get("boundary_quality_code") or "READY_WITH_WARNING"
        boundary["source_trace_json"] = {
            **(boundary.get("source_trace_json") or {}),
            "source": "navigation_revier_production_seed",
            "source_channel_seed_version": channel.get("source_version"),
            "revier_boundary_policy": "reuse_current_curated_channel_boundary",
        }
        rows.append(boundary)
    return rows, annotation_tasks


def _build_revier_water_boundary_rows(
    channel_records: list[dict[str, Any]],
    water_area_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    prepared_rows = _prepared_water_rows(water_area_rows)
    rows: list[dict[str, Any]] = []
    annotation_tasks: list[dict[str, Any]] = []
    for record in channel_records:
        channel = dict(record.get("channel") or {})
        channel_code = str(channel.get("channel_code") or "")
        if not channel_code:
            continue
        terms = _channel_terms(channel)
        direct_rows = _direct_water_rows(prepared_rows, terms)
        if not direct_rows:
            annotation_tasks.append(_boundary_task(channel_code, "CHANNEL_REVIER_WATER_BODY_MISSING"))
            continue
        selected_rows = _select_bridge_rows(prepared_rows, direct_rows, terms)
        boundary = _boundary_row_from_water_rows(channel=channel, rows=selected_rows)
        if boundary is None:
            annotation_tasks.append(_boundary_task(channel_code, "CHANNEL_REVIER_BOUNDARY_UNION_FAILED"))
            continue
        rows.append(boundary)
    return rows, annotation_tasks


def _boundary_task(channel_code: str, issue_code: str) -> dict[str, Any]:
    return {
        "task_no": f"REV-BND-MISSING-{channel_code}",
        "task_type_code": "BOUNDARY_REVIEW",
        "target_type_code": "NAVIGATION_CHANNEL",
        "target_code": channel_code,
        "priority_code": "HIGH",
        "status_code": "OPEN",
        "issue_summary": "revier 生产 seed 未能从真实水域面生成可用航道边界。",
        "suggestion_json": {"issue_code": issue_code},
    }


def _norm(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    for token in (" ", "\t", "\n", "—", "-", "_", "（", "）", "(", ")", "/", "·"):
        text = text.replace(token, "")
    return text or None


def _channel_terms(channel: dict[str, Any]) -> set[str]:
    terms: set[str] = set()
    for value in (
        channel.get("channel_name"),
        channel.get("official_name"),
        channel.get("display_name"),
        *(channel.get("alias_names") or []),
    ):
        normalized = _norm(value)
        if normalized:
            terms.add(normalized)
    return terms


def _row_terms(row: dict[str, Any]) -> set[str]:
    terms: set[str] = set()
    for value in (row.get("normalized_water_name"), row.get("water_name"), *(row.get("alias_names") or [])):
        normalized = _norm(value)
        if normalized:
            terms.add(normalized)
    return terms


def _source_key(row: dict[str, Any]) -> str:
    return f"{row.get('source_code') or ''}:{row.get('source_layer_name') or ''}:{row.get('source_object_id') or ''}"


def _dedupe_prefer_hierarchy(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_object: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("source_code") or ""), str(row.get("source_object_id") or _source_key(row)))
        current = best_by_object.get(key)
        if current is None or _row_rank(row) < _row_rank(current):
            best_by_object[key] = row
    return list(best_by_object.values())


def _row_rank(row: dict[str, Any]) -> tuple[int, int]:
    role = str(row.get("source_layer_role_code") or "")
    layer_order = int(row.get("source_layer_order") or 999)
    if role in {"HIERARCHY_LEVEL", "STANDARD"}:
        return (0, layer_order)
    if str(row.get("source_layer_code") or "").startswith("RX"):
        return (2, layer_order)
    return (1, layer_order)


def _prepared_water_rows(water_area_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in water_area_rows:
        if row.get("geometry_status_code") == "INVALID" or bool(row.get("is_low_value")):
            continue
        geometry = _safe_polygonal(row.get("geometry_json"))
        if geometry is None:
            continue
        output.append(
            {
                **row,
                "_terms": _row_terms(row),
                "_geometry": geometry,
                "_bbox": tuple(float(value) for value in geometry.bounds),
                "_source_key": _source_key(row),
            }
        )
    return output


def _direct_water_rows(rows: list[dict[str, Any]], terms: set[str]) -> list[dict[str, Any]]:
    matches = [
        row
        for row in rows
        if row.get("source_layer_role_code") in DIRECT_MATCH_ROLES and terms.intersection(row.get("_terms") or set())
    ]
    if not matches:
        matches = [row for row in rows if terms.intersection(row.get("_terms") or set())]
    return _dedupe_prefer_hierarchy(matches)


def _select_bridge_rows(
    rows: list[dict[str, Any]],
    direct_rows: list[dict[str, Any]],
    terms: set[str],
) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {row["_source_key"]: row for row in direct_rows}
    direct_sorted = sorted(direct_rows, key=lambda row: (row["_geometry"].centroid.y, row["_geometry"].centroid.x))
    for left, right in zip(direct_sorted, direct_sorted[1:]):
        left_point, right_point = nearest_points(left["_geometry"], right["_geometry"])
        gap_m = point_distance_m(left_point, right_point)
        if gap_m < MIN_COMPONENT_GAP_M:
            continue
        gap_line = _line_between_points(left_point, right_point)
        gap_span = max(abs(left_point.x - right_point.x), abs(left_point.y - right_point.y))
        buffer_degree = max(MIN_BRIDGE_BUFFER_DEGREE, min(MAX_BRIDGE_BUFFER_DEGREE, gap_span * 0.35))
        gap_buffer = gap_line.buffer(buffer_degree)
        gap_bbox = tuple(float(value) for value in gap_buffer.bounds)
        candidates: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            if row["_source_key"] in selected:
                continue
            if row.get("source_layer_role_code") not in BRIDGE_MATCH_ROLES:
                continue
            if str(row.get("water_type_code") or "") not in BRIDGE_WATER_TYPES:
                continue
            if terms.intersection(row.get("_terms") or set()):
                continue
            if not _bbox_intersects(row.get("_bbox"), gap_bbox):
                continue
            geometry = row["_geometry"]
            if not geometry.intersects(gap_buffer):
                continue
            intersection_area = geometry.intersection(gap_buffer).area
            if intersection_area < MIN_BRIDGE_INTERSECTION_AREA_DEGREE:
                continue
            area_km2 = _float(row.get("area_km2")) or 0.0
            large_lake_penalty = 1.0 + max(area_km2 - 20.0, 0.0) / 20.0
            candidates.append((intersection_area / large_lake_penalty, row))
        candidates.sort(key=lambda item: item[0], reverse=True)
        for _score, row in candidates[:MAX_BRIDGE_ROWS_PER_GAP]:
            selected[row["_source_key"]] = row
    return list(selected.values())


def _line_between_points(left: Any, right: Any) -> Any:
    from shapely.geometry import LineString

    return LineString([(float(left.x), float(left.y)), (float(right.x), float(right.y))])


def _boundary_row_from_water_rows(channel: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    polygons = [polygon for row in rows if row.get("_geometry") is not None for polygon in _geometry_polygons(row["_geometry"])]
    if not polygons:
        return None
    geometry: BaseGeometry = polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)
    geometry_json = json.loads(json.dumps(mapping(geometry)))
    min_lng, min_lat, max_lng, max_lat = geometry.bounds
    selected_summary = [
        {
            "source_key": row.get("_source_key"),
            "source_layer_name": row.get("source_layer_name"),
            "source_object_id": row.get("source_object_id"),
            "water_name": row.get("water_name") or row.get("normalized_water_name"),
            "water_type_code": row.get("water_type_code"),
            "source_layer_role_code": row.get("source_layer_role_code"),
            "area_km2": row.get("area_km2"),
            "bbox": list(row.get("_bbox") or ()),
            "direct_match": _norm(row.get("water_name") or row.get("normalized_water_name")) in _channel_terms(channel),
        }
        for row in sorted(rows, key=lambda item: (item.get("source_layer_order") or 999, str(item.get("source_object_id") or "")))[:120]
    ]
    direct_count = sum(1 for row in rows if _norm(row.get("water_name") or row.get("normalized_water_name")) in _channel_terms(channel))
    return {
        "channel_code": channel["channel_code"],
        "geometry_json": geometry_json,
        "boundary_paths_low": _polygon_paths(geometry_json),
        "boundary_paths_medium": _polygon_paths(geometry_json),
        "boundary_paths_high": _polygon_paths(geometry_json),
        "center_longitude": (min_lng + max_lng) / 2.0,
        "center_latitude": (min_lat + max_lat) / 2.0,
        "display_center_longitude": (min_lng + max_lng) / 2.0,
        "display_center_latitude": (min_lat + max_lat) / 2.0,
        "bbox_min_lng": min_lng,
        "bbox_min_lat": min_lat,
        "bbox_max_lng": max_lng,
        "bbox_max_lat": max_lat,
        "source_shape_length_degree": float(geometry.length),
        "source_shape_area_degree": float(geometry.area),
        "ring_count": _ring_count(geometry_json),
        "point_count": _point_count(geometry_json),
        "geometry_status_code": "AVAILABLE",
        "boundary_quality_code": "READY_WITH_WARNING" if len(rows) > direct_count else "READY",
        "connectivity_status_code": "CONNECTED" if len(rows) == direct_count else "CONNECTED_WITH_BRIDGES",
        "repair_status_code": "NONE",
        "coverage_policy_code": "REVIER_WATER_BODY_UNION_WITH_SPATIAL_BRIDGES",
        "geometry_coordinate_system_code": "WGS84",
        "boundary_coordinate_system_code": "WGS84",
        "source_trace_json": {
            "source": "navigation_revier_production_seed",
            "source_channel_seed_version": channel.get("source_version"),
            "revier_boundary_policy": "direct_named_water_areas_with_spatial_bridge_candidates",
            "direct_water_area_count": direct_count,
            "selected_water_area_count": len(rows),
            "bridge_water_area_count": max(len(rows) - direct_count, 0),
            "selected_water_areas": selected_summary,
        },
        "is_current": True,
        "imported_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _safe_polygonal(geometry_json: Any) -> BaseGeometry | None:
    if not isinstance(geometry_json, dict):
        return None
    try:
        geometry = make_valid(shape(geometry_json))
    except Exception:
        return None
    if geometry.is_empty:
        return None
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    if isinstance(geometry, GeometryCollection):
        parts = [part for part in geometry.geoms if isinstance(part, (Polygon, MultiPolygon)) and not part.is_empty]
        if not parts:
            return None
        try:
            merged = unary_union(parts)
        except Exception:
            merged = MultiPolygon([poly for part in parts for poly in (part.geoms if isinstance(part, MultiPolygon) else [part])])
        return make_valid(merged)
    return None


def _geometry_polygons(geometry: BaseGeometry) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        return [part for item in geometry.geoms for part in _geometry_polygons(item)]
    return []


def _polygon_paths(geometry_json: dict[str, Any]) -> list[list[list[float]]]:
    geometry_type = geometry_json.get("type")
    coordinates = geometry_json.get("coordinates") or []
    if geometry_type == "Polygon":
        return [coordinates[0]] if coordinates else []
    if geometry_type == "MultiPolygon":
        return [polygon[0] for polygon in coordinates if polygon]
    return []


def _ring_count(geometry_json: dict[str, Any]) -> int:
    geometry_type = geometry_json.get("type")
    coordinates = geometry_json.get("coordinates") or []
    if geometry_type == "Polygon":
        return len(coordinates)
    if geometry_type == "MultiPolygon":
        return sum(len(polygon) for polygon in coordinates)
    return 0


def _point_count(geometry_json: dict[str, Any]) -> int:
    geometry_type = geometry_json.get("type")
    coordinates = geometry_json.get("coordinates") or []
    if geometry_type == "Polygon":
        return sum(len(ring) for ring in coordinates)
    if geometry_type == "MultiPolygon":
        return sum(len(ring) for polygon in coordinates for ring in polygon)
    return 0


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _bbox_intersects(left: Any, right: tuple[float, float, float, float]) -> bool:
    if not left:
        return False
    min_lng, min_lat, max_lng, max_lat = left
    return not (min_lng > right[2] or max_lng < right[0] or min_lat > right[3] or max_lat < right[1])
