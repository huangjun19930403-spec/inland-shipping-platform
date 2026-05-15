"""Build v6 channel water-system seed data from the audited v5 baseline.

v6 treats every row as a channel/waterway business object. Natural water-system
polygons remain source material, but route-like channels are rebuilt from source
features that can be explained by the planned channel catalogue instead of
using broad spatial carrier water bodies.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import io
import json
import zipfile
import zlib
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.modules.address.boundary_utils import (
    BoundaryPolygons,
    extract_geojson_polygons,
    polygons_bbox,
    serialize_boundary_paths,
)
from scripts import seed_water_systems as seed_utils
from scripts.seed_data import navigation_water_systems_v5


DATA_VERSION = "revier_navigation_channel_v6"
DEFAULT_SOURCE_ZIP = Path("/Users/hj/Documents/河道数据/revier.zip")
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "seed_data" / "navigation_water_systems_v6.py"
DEFAULT_AUDIT_OUTPUT = Path(__file__).resolve().parent / "seed_data" / "water_system_source_assignment_v6.jsonl"
DEFAULT_QUALITY_OUTPUT = Path(__file__).resolve().parent / "seed_data" / "water_system_quality_report_v6.json"

CHANNEL_BUSINESS_REMARK = (
    "航道水系基础数据以官方/规划航道名称为主；边界为业务可用的航道水域包络，"
    "自然水系面仅作为航道边界贴合、补洞和空间校验素材，不代表法定航道保护范围或官方电子航道图成果。"
)
CHANNEL_FALLBACK_REMARK = (
    "暂保留 v5 预览边界待补官方航道骨架；该范围只用于业务查看和 AIS 空间归属过渡，不代表航道边界。"
)

BRIDGE_REPAIR_WIDTH_DEGREES = {
    "WS-GRAND-CANAL": 0.018,
}

CORE_NAME_OVERRIDES = {
    "WS-YANGTZE": {"长江"},
    "WS-GRAND-CANAL": {"京杭运河"},
}


def _decimal_to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_v5_rows() -> list[dict[str, Any]]:
    payload = "".join(navigation_water_systems_v5.COMPRESSED_ROWS)
    raw = zlib.decompress(base64.b64decode(payload)).decode("utf-8")
    return [
        dict(zip(navigation_water_systems_v5.FIELDS, record, strict=True))
        for record in json.loads(raw)
    ]


def _load_v5_assignments(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _source_key(layer_name: str, object_id: int) -> tuple[str, int]:
    return (layer_name, object_id)


def _load_source_index(source_zip: Path) -> dict[tuple[str, int], seed_utils.SourceFeature]:
    index: dict[tuple[str, int], seed_utils.SourceFeature] = {}
    with zipfile.ZipFile(source_zip) as zip_file:
        for level, layer_name in seed_utils.LEVEL_LAYER_NAMES.items():
            # pyshp emits noisy geometry warnings for several upstream records;
            # the generated rows still keep the usable rings, matching v5.
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                features = seed_utils._read_layer_features(zip_file, layer_name)
            for feature in features:
                object_id = seed_utils._int_or_zero(feature.attributes.get("OBJECTID"))
                if object_id:
                    index[_source_key(layer_name, object_id)] = feature
    return index


def _assignment_source_key(assignment: dict[str, Any]) -> tuple[str, int] | None:
    layer = str(assignment.get("source_layer") or "")
    object_id = seed_utils._int_or_zero(assignment.get("object_id"))
    if not layer or not object_id:
        return None
    return _source_key(layer, object_id)


def _is_water_body_remark(remark: str) -> bool:
    return "湖" in remark or "水库" in remark


def _is_water_body_name(name: str) -> bool:
    return any(token in name for token in ("湖", "水库", "水泡", "泡", "荡", "漾"))


def _is_channel_like_remark(remark: str) -> bool:
    return any(token in remark for token in ("河", "江", "运河", "渠道", "水道", "港线", "航道"))


def _keep_assignment_for_channel(
    row: dict[str, Any],
    assignment: dict[str, Any],
    prefer_exact: bool = False,
) -> tuple[bool, str]:
    if assignment.get("assignment_status") != "ASSIGNED":
        return False, "SOURCE_NOT_ASSIGNED"

    reason = str(assignment.get("assignment_reason") or "")
    name = str(assignment.get("name") or "")
    remark = str(assignment.get("remark") or "")
    code = str(row["water_system_code"])
    category = str(row.get("navigation_category_code") or "")

    if code in CORE_NAME_OVERRIDES:
        if name in CORE_NAME_OVERRIDES[code] and _is_channel_like_remark(remark) and not _is_water_body_remark(remark):
            return True, "CHANNEL_NAME_CORE"
        return False, "CHANNEL_CORE_REJECT_NATURAL_CARRIER"

    if prefer_exact and reason != "EXACT":
        return False, "CHANNEL_REJECT_NON_CORE_ALIAS"

    if reason not in {"EXACT", "ALIAS"}:
        return False, "CHANNEL_REJECT_SPATIAL_CARRIER"

    if category in {"MAIN_RIVER", "TRIBUTARY", "CANAL", "DELTA_NETWORK"}:
        if _is_channel_like_remark(remark) and not _is_water_body_remark(remark) and not _is_water_body_name(name):
            return True, "CHANNEL_NAME_OR_ALIAS"
        return False, "CHANNEL_REJECT_WATER_BODY"

    if category == "LAKE":
        if _is_water_body_remark(remark):
            return True, "CHANNEL_CONNECTED_WATER_AREA"
        return False, "CHANNEL_REJECT_NON_WATER_AREA"

    return True, "CHANNEL_NAME_OR_ALIAS"


def _combine_feature_polygons(features: list[seed_utils.SourceFeature]) -> BoundaryPolygons:
    polygons: BoundaryPolygons = []
    for feature in features:
        polygons.extend(extract_geojson_polygons(feature.geometry))
    return polygons


def _ring_centroid(ring: list[tuple[float, float]]) -> tuple[float, float] | None:
    if not ring:
        return None
    lng = sum(point[0] for point in ring) / len(ring)
    lat = sum(point[1] for point in ring) / len(ring)
    return lng, lat


def _polygon_center(polygon: list[list[tuple[float, float]]]) -> tuple[float, float] | None:
    if not polygon:
        return None
    return _ring_centroid(polygon[0])


def _bridge_ring(start: tuple[float, float], end: tuple[float, float], width: float) -> list[tuple[float, float]]:
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    length = (dx * dx + dy * dy) ** 0.5
    if length <= 0:
        half = width / 2
        return [(sx - half, sy - half), (sx + half, sy - half), (sx + half, sy + half), (sx - half, sy + half), (sx - half, sy - half)]
    px = -dy / length * width / 2
    py = dx / length * width / 2
    ring = [
        (sx + px, sy + py),
        (ex + px, ey + py),
        (ex - px, ey - py),
        (sx - px, sy - py),
        (sx + px, sy + py),
    ]
    return ring


def _bridge_polygons_for_channel(code: str, polygons: BoundaryPolygons) -> BoundaryPolygons:
    width = BRIDGE_REPAIR_WIDTH_DEGREES.get(code)
    if not width:
        return []
    centers = [center for polygon in polygons if (center := _polygon_center(polygon)) is not None]
    if len(centers) < 2:
        return []
    # Grand Canal source segments in revier are ordered well by latitude in the
    # available source; bridge between visible segment centers to avoid the
    # broken middle section while keeping the repair narrow and reviewable.
    centers = sorted(centers, key=lambda point: (point[1], point[0]), reverse=True)
    repairs: BoundaryPolygons = []
    for start, end in zip(centers, centers[1:], strict=False):
        repairs.append([_bridge_ring(start, end, width)])
    return repairs


def _geometry_from_polygons(polygons: BoundaryPolygons) -> dict[str, Any]:
    return {
        "type": "MultiPolygon",
        "coordinates": [
            [[[float(lng), float(lat)] for lng, lat in ring] for ring in polygon]
            for polygon in polygons
            if polygon
        ],
    }


def _geometry_counts(polygons: BoundaryPolygons) -> tuple[int, int]:
    return (
        sum(len(polygon) for polygon in polygons),
        sum(len(ring) for polygon in polygons for ring in polygon),
    )


def _geometry_center(polygons: BoundaryPolygons) -> tuple[float | None, float | None]:
    bbox = polygons_bbox(polygons)
    if bbox is None:
        return None, None
    min_lng, min_lat, max_lng, max_lat = bbox
    return (min_lng + max_lng) / 2, (min_lat + max_lat) / 2


def _shape_metric(features: list[seed_utils.SourceFeature], field: str) -> float | None:
    values = [_decimal_to_float(feature.attributes.get(field)) for feature in features]
    filtered = [value for value in values if value is not None]
    if not filtered:
        return None
    return float(sum(filtered))


def _source_level(source_key: tuple[str, int]) -> int:
    layer_name, _ = source_key
    for level, name in seed_utils.LEVEL_LAYER_NAMES.items():
        if name == layer_name:
            return level
    return 0


def _rebuild_row_from_features(
    row: dict[str, Any],
    kept_assignments: list[dict[str, Any]],
    source_index: dict[tuple[str, int], seed_utils.SourceFeature],
) -> dict[str, Any]:
    keys = [key for assignment in kept_assignments if (key := _assignment_source_key(assignment)) in source_index]
    features = [source_index[key] for key in keys]
    polygons = _combine_feature_polygons(features)
    repair_polygons = _bridge_polygons_for_channel(str(row["water_system_code"]), polygons)
    if repair_polygons:
        polygons = polygons + repair_polygons

    bbox = polygons_bbox(polygons)
    center_lng, center_lat = _geometry_center(polygons)
    ring_count, point_count = _geometry_counts(polygons)
    source_levels = sorted({_source_level(key) for key in keys if _source_level(key)})
    source_layer_names = sorted({key[0] for key in keys})
    if repair_polygons:
        source_layer_names.append("航道走廊修复")

    source_names = sorted({str(item.get("name")) for item in kept_assignments if item.get("name")})
    source_remarks = sorted({str(item.get("remark")) for item in kept_assignments if item.get("remark")})
    if repair_polygons:
        source_names.append("航道缺口修复走廊")
        source_remarks.append("按航道骨架连续性生成的窄走廊修复面")

    rebuilt = dict(row)
    rebuilt.update(
        {
            "source_version": DATA_VERSION,
            "source_feature_count": len(features) + len(repair_polygons),
            "source_object_ids": [key[1] for key in keys],
            "source_levels": source_levels,
            "source_layer_names": source_layer_names,
            "source_names": source_names,
            "source_remarks": source_remarks,
            "geometry_union_status": "CHANNEL_CORRIDOR_REPAIRED" if repair_polygons else "CHANNEL_ENVELOPE",
            "business_remark": CHANNEL_BUSINESS_REMARK,
            "source_remark": (
                f"航道水系 v6：采纳 {len(features)} 个自然水系源面作为航道边界素材"
                + (f"，并生成 {len(repair_polygons)} 个航道缺口修复面" if repair_polygons else "")
                + "；已剔除不满足航道骨架/名称/水域类型约束的自然水体承载面。"
            ),
            "source_layer_name": "航道水系v6",
            "geometry_json": _geometry_from_polygons(polygons),
            "boundary_paths_low": serialize_boundary_paths(
                seed_utils._boundary_paths_for_tolerance(polygons, seed_utils.BOUNDARY_SIMPLIFY_TOLERANCE["low"])
            )
            or [],
            "boundary_paths_medium": serialize_boundary_paths(
                seed_utils._boundary_paths_for_tolerance(polygons, seed_utils.BOUNDARY_SIMPLIFY_TOLERANCE["medium"])
            )
            or [],
            "boundary_paths_high": serialize_boundary_paths(
                seed_utils._boundary_paths_for_tolerance(polygons, seed_utils.BOUNDARY_SIMPLIFY_TOLERANCE["high"])
            )
            or [],
            "center_longitude": center_lng,
            "center_latitude": center_lat,
            "display_center_longitude": center_lng,
            "display_center_latitude": center_lat,
            "bbox_min_lng": bbox[0] if bbox else None,
            "bbox_min_lat": bbox[1] if bbox else None,
            "bbox_max_lng": bbox[2] if bbox else None,
            "bbox_max_lat": bbox[3] if bbox else None,
            "source_shape_length_degree": _shape_metric(features, "Shape_Leng"),
            "source_shape_area_degree": _shape_metric(features, "Shape_Area"),
            "ring_count": ring_count,
            "point_count": point_count,
            "geometry_status_code": "AVAILABLE" if polygons else "MISSING",
            "boundary_quality_code": "REVIEW" if repair_polygons else "HIGH_CONFIDENCE",
            "geometry_coordinate_system_code": "WGS84",
            "boundary_coordinate_system_code": "GCJ02",
            "match_level_code": "OFFICIAL_TARGET",
            "match_confidence_code": "MEDIUM" if repair_polygons else "HIGH",
            "review_required": bool(repair_polygons),
        }
    )
    return rebuilt


def _fallback_channel_row(row: dict[str, Any]) -> dict[str, Any]:
    rebuilt = dict(row)
    rebuilt.update(
        {
            "source_version": DATA_VERSION,
            "geometry_union_status": "CHANNEL_REVIEW_FALLBACK" if row.get("geometry_status_code") == "AVAILABLE" else "MISSING",
            "business_remark": f"{CHANNEL_BUSINESS_REMARK}；{CHANNEL_FALLBACK_REMARK}",
            "source_remark": f"航道水系 v6：未找到足够的航道名称/骨架源面，{CHANNEL_FALLBACK_REMARK}",
            "source_layer_name": "航道水系v6",
            "boundary_quality_code": "REVIEW" if row.get("geometry_status_code") == "AVAILABLE" else "MISSING",
            "match_level_code": row.get("match_level_code") or "OFFICIAL_TARGET",
            "match_confidence_code": "LOW" if row.get("geometry_status_code") == "AVAILABLE" else row.get("match_confidence_code"),
            "review_required": True if row.get("geometry_status_code") == "AVAILABLE" else row.get("review_required"),
        }
    )
    return rebuilt


def _channelize_passthrough_row(row: dict[str, Any]) -> dict[str, Any]:
    rebuilt = dict(row)
    rebuilt.update(
        {
            "source_version": DATA_VERSION,
            "business_remark": CHANNEL_BUSINESS_REMARK,
            "source_layer_name": "航道水系v6",
        }
    )
    return rebuilt


def _record_values(row: dict[str, Any]) -> list[Any]:
    values: list[Any] = []
    for field in navigation_water_systems_v5.FIELDS:
        value = row.get(field)
        if isinstance(value, Decimal):
            value = float(value)
        values.append(value)
    return values


def _chunk_text(value: str, size: int = 120) -> list[str]:
    return [value[index : index + size] for index in range(0, len(value), size)]


def _write_seed_module(rows: list[dict[str, Any]], quality: dict[str, Any], output: Path) -> None:
    records = [_record_values(row) for row in rows]
    payload = base64.b64encode(zlib.compress(json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9)).decode("ascii")
    chunks = _chunk_text(payload)
    scope_counts = dict(Counter(row.get("navigation_scope_code") for row in rows if row.get("navigation_scope_code")))
    category_counts = dict(Counter(row.get("navigation_category_code") for row in rows if row.get("navigation_category_code")))
    ais_counts = dict(Counter(row.get("ais_situation_scope") for row in rows if row.get("ais_situation_scope")))
    level_counts = Counter()
    for row in rows:
        for level in row.get("source_levels") or []:
            level_counts[int(level)] += 1

    lines = [
        '"""Channel water-system seed data derived from revier.zip.',
        "",
        "This module stores audited, precomputed v6 seed rows only. Runtime seeding reads",
        "these rows directly and must not re-clean the original Shapefile.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        f"DATA_VERSION = {DATA_VERSION!r}",
        f"ROW_COUNT = {len(rows)!r}",
        f"AVAILABLE_BOUNDARY_COUNT = {sum(1 for row in rows if row.get('geometry_status_code') == 'AVAILABLE')!r}",
        f"SCOPE_COUNTS = {scope_counts!r}",
        f"CATEGORY_COUNTS = {category_counts!r}",
        f"AIS_SCOPE_COUNTS = {ais_counts!r}",
        f"SOURCE_LEVEL_COUNTS = {dict(sorted(level_counts.items()))!r}",
        f"SOURCE_ASSIGNMENT_COUNTS = {quality['assignment_counts']!r}",
        f"SOURCE_FEATURE_COUNT = {navigation_water_systems_v5.SOURCE_FEATURE_COUNT!r}",
        f"SOURCE_ZIP_BASENAME = {navigation_water_systems_v5.SOURCE_ZIP_BASENAME!r}",
        f"SOURCE_LAYERS = {navigation_water_systems_v5.SOURCE_LAYERS!r}",
        "CHANNEL_USAGE_NOTE = 'v6 主对象为航道水系；自然水系面仅作为航道水域包络生成素材，不能直接视为航道边界。'",
        "ELECTRONIC_CHANNEL_CHART_NOTE = '暂未发现可直接合法下载的官方内河电子航道图 GIS 成果；生成器保留后续导入入口。'",
        f"COORDINATE_SYSTEMS = {navigation_water_systems_v5.COORDINATE_SYSTEMS!r}",
        f"FIELDS = {navigation_water_systems_v5.FIELDS!r}",
        "COMPRESSED_ROWS = (",
    ]
    lines.extend(f"    {chunk!r}," for chunk in chunks)
    lines.append(")")
    lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")


def _write_audit(
    assignments: list[dict[str, Any]],
    row_by_code: dict[str, dict[str, Any]],
    kept_source_keys: dict[str, set[tuple[str, int]]],
    prefer_exact_by_code: dict[str, bool],
    review_fallback_codes: set[str],
    water_area_passthrough_codes: set[str],
    audit_output: Path,
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    with audit_output.open("w", encoding="utf-8") as handle:
        for assignment in assignments:
            item = dict(assignment)
            code = item.get("target_water_system_code")
            row = row_by_code.get(code or "")
            key = _assignment_source_key(item)
            if row and key in kept_source_keys.get(code or "", set()):
                item["assignment_status"] = "ASSIGNED"
                item["assignment_reason"] = (
                    "WATER_AREA_BOUNDARY_SOURCE"
                    if code in water_area_passthrough_codes
                    else "CHANNEL_BOUNDARY_CORE"
                )
            elif row and code in review_fallback_codes and item.get("assignment_status") == "ASSIGNED":
                item["assignment_status"] = "REVIEW"
                item["assignment_reason"] = "CHANNEL_REVIEW_FALLBACK_SOURCE"
            elif row and item.get("assignment_status") == "ASSIGNED":
                _, reason = _keep_assignment_for_channel(row, assignment, prefer_exact_by_code.get(str(code), False))
                item["assignment_status"] = "EXCLUDED"
                item["assignment_reason"] = reason
            counts[str(item.get("assignment_reason") or "UNKNOWN")] += 1
            handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")

        for code, repair_count in {"WS-GRAND-CANAL": len(BRIDGE_REPAIR_WIDTH_DEGREES)}.items():
            if repair_count and code in row_by_code:
                item = {
                    "source_layer": "航道走廊修复",
                    "source_level": 0,
                    "object_id": 0,
                    "source_key": f"{code}-GAP-REPAIR",
                    "name": "航道缺口修复走廊",
                    "remark": "按航道骨架连续性生成的窄走廊修复面",
                    "assignment_status": "REVIEW",
                    "assignment_reason": "CHANNEL_GAP_REPAIR_CORRIDOR",
                    "target_water_system_code": code,
                    "target_water_system_name": row_by_code[code]["water_system_name"],
                    "secondary_trace_targets": [],
                }
                counts[item["assignment_reason"]] += 1
                handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
    return dict(counts)


def _has_sufficient_channel_coverage(row: dict[str, Any], kept_keys: set[tuple[str, int]]) -> bool:
    if not kept_keys:
        return False
    code = str(row["water_system_code"])
    if code in CORE_NAME_OVERRIDES:
        return True
    original_source_count = int(row.get("source_feature_count") or 0)
    is_low_confidence_carrier = (
        row.get("geometry_union_status") == "CARRIER_COMPOSITE"
        and row.get("boundary_quality_code") == "LOW_CONFIDENCE_CARRIER"
    )
    if is_low_confidence_carrier and original_source_count > len(kept_keys) and len(kept_keys) < 2:
        return False
    return True


def build(source_zip: Path, output: Path, audit_output: Path, quality_output: Path) -> dict[str, Any]:
    rows = _load_v5_rows()
    assignments_path = Path(__file__).resolve().parent / "seed_data" / "water_system_source_assignment_v5.jsonl"
    assignments = _load_v5_assignments(assignments_path)
    assignments_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for assignment in assignments:
        code = assignment.get("target_water_system_code")
        if code:
            assignments_by_code[str(code)].append(assignment)

    source_index = _load_source_index(source_zip)
    output_rows: list[dict[str, Any]] = []
    kept_source_keys: dict[str, set[tuple[str, int]]] = {}
    prefer_exact_by_code: dict[str, bool] = {}
    quality_rows: list[dict[str, Any]] = []
    review_fallback_codes: set[str] = set()
    water_area_passthrough_codes: set[str] = set()

    for row in rows:
        code = str(row["water_system_code"])
        row_assignments = assignments_by_code.get(code, [])
        if row.get("navigation_category_code") == "LAKE":
            kept_keys = {
                key
                for assignment in row_assignments
                if assignment.get("assignment_status") == "ASSIGNED"
                and (key := _assignment_source_key(assignment)) in source_index
            }
            kept_source_keys[code] = kept_keys
            prefer_exact_by_code[code] = False
            rebuilt = _channelize_passthrough_row(row)
            status = "WATER_AREA_PASSTHROUGH"
            water_area_passthrough_codes.add(code)
            output_rows.append(rebuilt)
            quality_rows.append(
                {
                    "water_system_code": code,
                    "water_system_name": row.get("water_system_name"),
                    "status": status,
                    "v5_source_feature_count": row.get("source_feature_count"),
                    "v6_source_feature_count": rebuilt.get("source_feature_count"),
                    "geometry_union_status": rebuilt.get("geometry_union_status"),
                    "boundary_quality_code": rebuilt.get("boundary_quality_code"),
                    "review_required": rebuilt.get("review_required"),
                    "source_names": rebuilt.get("source_names"),
                }
            )
            continue
        prefer_exact = code not in CORE_NAME_OVERRIDES and any(
            assignment.get("assignment_status") == "ASSIGNED"
            and assignment.get("assignment_reason") == "EXACT"
            and (key := _assignment_source_key(assignment)) in source_index
            for assignment in row_assignments
        )
        prefer_exact_by_code[code] = prefer_exact
        kept_assignments = [
            assignment
            for assignment in row_assignments
            if _keep_assignment_for_channel(row, assignment, prefer_exact)[0]
        ]
        kept_keys = {key for assignment in kept_assignments if (key := _assignment_source_key(assignment)) in source_index}
        kept_source_keys[code] = kept_keys

        if kept_assignments and _has_sufficient_channel_coverage(row, kept_keys):
            rebuilt = _rebuild_row_from_features(row, kept_assignments, source_index)
            status = "REBUILT_FROM_CHANNEL_CORE"
        elif row.get("geometry_status_code") == "AVAILABLE":
            kept_source_keys[code] = set()
            rebuilt = _fallback_channel_row(row)
            status = "INSUFFICIENT_CHANNEL_COVERAGE_FALLBACK" if kept_keys else "V5_REVIEW_FALLBACK"
            review_fallback_codes.add(code)
        else:
            rebuilt = _channelize_passthrough_row(row)
            status = "MISSING_BOUNDARY"
        output_rows.append(rebuilt)
        quality_rows.append(
            {
                "water_system_code": code,
                "water_system_name": row.get("water_system_name"),
                "status": status,
                "v5_source_feature_count": row.get("source_feature_count"),
                "v6_source_feature_count": rebuilt.get("source_feature_count"),
                "geometry_union_status": rebuilt.get("geometry_union_status"),
                "boundary_quality_code": rebuilt.get("boundary_quality_code"),
                "review_required": rebuilt.get("review_required"),
                "source_names": rebuilt.get("source_names"),
            }
        )

    row_by_code = {str(row["water_system_code"]): row for row in output_rows}
    assignment_counts = _write_audit(
        assignments,
        row_by_code,
        kept_source_keys,
        prefer_exact_by_code,
        review_fallback_codes,
        water_area_passthrough_codes,
        audit_output,
    )
    quality = {
        "data_version": DATA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source_zip": str(source_zip),
        "row_count": len(output_rows),
        "available_boundary_count": sum(1 for row in output_rows if row.get("geometry_status_code") == "AVAILABLE"),
        "assignment_counts": assignment_counts,
        "rows": quality_rows,
    }
    quality_output.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_seed_module(output_rows, quality, output)
    return quality


def _main() -> None:
    parser = argparse.ArgumentParser(description="Build v6 channel water-system seed data.")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE_ZIP), help="revier.zip source path")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="generated Python seed module")
    parser.add_argument("--audit-output", default=str(DEFAULT_AUDIT_OUTPUT), help="generated source assignment audit jsonl")
    parser.add_argument("--quality-output", default=str(DEFAULT_QUALITY_OUTPUT), help="generated quality report json")
    args = parser.parse_args()

    quality = build(
        Path(args.source).expanduser(),
        Path(args.output).expanduser(),
        Path(args.audit_output).expanduser(),
        Path(args.quality_output).expanduser(),
    )
    print(
        "build_navigation_channel_water_systems_v6 completed: "
        f"rows={quality['row_count']} available={quality['available_boundary_count']} "
        f"version={quality['data_version']}"
    )


if __name__ == "__main__":
    _main()
