"""Analyze real waybill route CSV data as navigation seed evidence.

The CSV is not treated as automatically correct route geometry. It can contain
sparse AIS samples, partial tracks, endpoint drift, and operational detours.
This script separates geometry-grade evidence from condition-only evidence so
the routing/seed pipeline can use it safely.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from shapely.geometry import LineString, mapping
from shapely.validation import make_valid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.address import NavigationChannel
from app.models.navigation import NavigationWaterArea, NavigationWaterBody


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = Path("/Users/hj/Downloads/路线.csv")
DEFAULT_OUTPUT = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_route_reference_analysis_20260608.json"
DEFAULT_GEOJSON_OUTPUT = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_route_reference_samples_20260608.geojson"
DEFAULT_JSONL_OUTPUT = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_route_reference_candidates_20260608.jsonl"

CSV_FIELDS = {
    "route_area_name": 0,
    "route_area_code": 1,
    "route_name": 2,
    "route_code": 3,
    "origin_code": 4,
    "origin_name": 5,
    "origin_lng": 6,
    "origin_lat": 7,
    "destination_code": 8,
    "destination_name": 9,
    "destination_lng": 10,
    "destination_lat": 11,
    "declared_distance_km": 12,
    "tonnage_range": 13,
    "cargo_codes": 14,
    "water_systems": 15,
    "ship_width_range": 16,
    "ship_length_range": 17,
    "waybill_code": 18,
    "waybill_started_at": 19,
    "waybill_ended_at": 20,
    "track_points_json": 21,
}


@dataclass(slots=True)
class TrackMetrics:
    point_count: int
    cleaned_point_count: int
    line_length_km: float | None
    direct_distance_km: float | None
    length_to_direct_ratio: float | None
    max_segment_km: float | None
    first_to_origin_km: float | None
    last_to_destination_km: float | None
    first_to_destination_km: float | None
    last_to_origin_km: float | None
    direction_code: str
    endpoint_max_offset_km: float | None
    quality_code: str
    issue_codes: list[str]
    usable_as_geometry_reference: bool
    usable_as_condition_reference: bool
    quality_score: int


@dataclass(slots=True)
class RouteReference:
    row_no: int
    route_area_name: str
    route_area_code: str
    route_name: str
    route_code: str
    origin_code: str
    origin_name: str
    origin_lng: float | None
    origin_lat: float | None
    destination_code: str
    destination_name: str
    destination_lng: float | None
    destination_lat: float | None
    declared_distance_km: float | None
    tonnage_min: float | None
    tonnage_max: float | None
    cargo_codes: list[str]
    water_systems: list[str]
    ship_width_min_m: float | None
    ship_width_max_m: float | None
    ship_length_min_m: float | None
    ship_length_max_m: float | None
    waybill_code: str
    waybill_started_at: str
    waybill_ended_at: str
    track_points: list[list[float]]
    track_metrics: TrackMetrics


@dataclass(slots=True)
class OdAggregate:
    origin_code: str
    origin_name: str
    destination_code: str
    destination_name: str
    row_count: int = 0
    geometry_reference_count: int = 0
    condition_reference_count: int = 0
    route_codes: Counter[str] = field(default_factory=Counter)
    water_systems: Counter[str] = field(default_factory=Counter)
    cargo_codes: Counter[str] = field(default_factory=Counter)
    quality_codes: Counter[str] = field(default_factory=Counter)
    tonnage_min_values: list[float] = field(default_factory=list)
    tonnage_max_values: list[float] = field(default_factory=list)
    width_max_values: list[float] = field(default_factory=list)
    length_max_values: list[float] = field(default_factory=list)
    best_reference: dict[str, Any] | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze real waybill route tracks from CSV as navigation evidence.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--geojson-output", type=Path, default=DEFAULT_GEOJSON_OUTPUT)
    parser.add_argument("--jsonl-output", type=Path, default=DEFAULT_JSONL_OUTPUT)
    parser.add_argument("--min-geometry-points", type=int, default=5)
    parser.add_argument("--max-reference-segment-km", type=float, default=15.0)
    parser.add_argument("--max-endpoint-offset-km", type=float, default=10.0)
    parser.add_argument("--geojson-limit", type=int, default=500)
    parser.add_argument("--od-sample-limit", type=int, default=100)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    references = _read_references(
        args.input,
        min_geometry_points=max(2, int(args.min_geometry_points)),
        max_reference_segment_km=float(args.max_reference_segment_km),
        max_endpoint_offset_km=float(args.max_endpoint_offset_km),
    )
    async with AsyncSessionLocal() as session:
        water_name_match = await _match_water_names(session, _all_water_names(references))
    od_groups = _aggregate_by_od(references)
    report = {
        "report_version": "WAYBILL_ROUTE_REFERENCE_ANALYSIS_V1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_csv": str(args.input),
        "args": {
            "min_geometry_points": int(args.min_geometry_points),
            "max_reference_segment_km": float(args.max_reference_segment_km),
            "max_endpoint_offset_km": float(args.max_endpoint_offset_km),
        },
        "summary": _summary(references, od_groups),
        "water_system_match_summary": water_name_match["summary"],
        "water_system_matches": water_name_match["items"],
        "condition_constraints_by_water_system": _condition_constraints_by_water_system(references),
        "top_od_groups": _top_od_groups(od_groups, limit=max(0, int(args.od_sample_limit))),
        "recommended_usage": _recommended_usage(references, od_groups, water_name_match),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.jsonl_output:
        args.jsonl_output.parent.mkdir(parents=True, exist_ok=True)
        _write_reference_jsonl(args.jsonl_output, references)
    if args.geojson_output:
        args.geojson_output.parent.mkdir(parents=True, exist_ok=True)
        args.geojson_output.write_text(
            json.dumps(
                _geojson(references, geojson_limit=max(0, int(args.geojson_limit))),
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"report_path={args.output}")
    if args.jsonl_output:
        print(f"jsonl_path={args.jsonl_output}")
    if args.geojson_output:
        print(f"geojson_path={args.geojson_output}")


def _read_references(
    path: Path,
    *,
    min_geometry_points: int,
    max_reference_segment_km: float,
    max_endpoint_offset_km: float,
) -> list[RouteReference]:
    csv.field_size_limit(1024 * 1024 * 1024)
    references: list[RouteReference] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        for row_no, row in enumerate(reader, start=2):
            if not row or not any(str(cell).strip() for cell in row[:22]):
                continue
            row = row + [""] * max(0, 22 - len(row))
            origin_lng = _float_or_none(row[CSV_FIELDS["origin_lng"]])
            origin_lat = _float_or_none(row[CSV_FIELDS["origin_lat"]])
            destination_lng = _float_or_none(row[CSV_FIELDS["destination_lng"]])
            destination_lat = _float_or_none(row[CSV_FIELDS["destination_lat"]])
            raw_points, point_issue = _track_points_from_row(row)
            cleaned_points = _clean_track_points(raw_points)
            metrics = _track_metrics(
                point_count=len(raw_points),
                cleaned_points=cleaned_points,
                point_issue=point_issue,
                origin=(origin_lng, origin_lat),
                destination=(destination_lng, destination_lat),
                min_geometry_points=min_geometry_points,
                max_reference_segment_km=max_reference_segment_km,
                max_endpoint_offset_km=max_endpoint_offset_km,
            )
            if metrics.direction_code == "REVERSED_TRACK":
                cleaned_points = list(reversed(cleaned_points))
            tonnage_min, tonnage_max = _range_values(row[CSV_FIELDS["tonnage_range"]])
            width_min, width_max = _range_values(row[CSV_FIELDS["ship_width_range"]])
            length_min, length_max = _range_values(row[CSV_FIELDS["ship_length_range"]])
            references.append(
                RouteReference(
                    row_no=row_no,
                    route_area_name=row[CSV_FIELDS["route_area_name"]].strip(),
                    route_area_code=row[CSV_FIELDS["route_area_code"]].strip(),
                    route_name=row[CSV_FIELDS["route_name"]].strip(),
                    route_code=row[CSV_FIELDS["route_code"]].strip(),
                    origin_code=row[CSV_FIELDS["origin_code"]].strip(),
                    origin_name=row[CSV_FIELDS["origin_name"]].strip(),
                    origin_lng=origin_lng,
                    origin_lat=origin_lat,
                    destination_code=row[CSV_FIELDS["destination_code"]].strip(),
                    destination_name=row[CSV_FIELDS["destination_name"]].strip(),
                    destination_lng=destination_lng,
                    destination_lat=destination_lat,
                    declared_distance_km=_float_or_none(row[CSV_FIELDS["declared_distance_km"]]),
                    tonnage_min=tonnage_min,
                    tonnage_max=tonnage_max,
                    cargo_codes=_split_csv_cell(row[CSV_FIELDS["cargo_codes"]]),
                    water_systems=_split_water_systems(row[CSV_FIELDS["water_systems"]]),
                    ship_width_min_m=width_min,
                    ship_width_max_m=width_max,
                    ship_length_min_m=length_min,
                    ship_length_max_m=length_max,
                    waybill_code=row[CSV_FIELDS["waybill_code"]].strip(),
                    waybill_started_at=row[CSV_FIELDS["waybill_started_at"]].strip(),
                    waybill_ended_at=row[CSV_FIELDS["waybill_ended_at"]].strip(),
                    track_points=cleaned_points,
                    track_metrics=metrics,
                )
            )
    return references


def _track_points_from_row(row: list[str]) -> tuple[list[list[float]], str | None]:
    primary = row[CSV_FIELDS["track_points_json"]] if len(row) > CSV_FIELDS["track_points_json"] else ""
    points, issue = _track_points(primary)
    if issue != "INVALID_TRACK_JSON" or points:
        return points, issue
    tail = [str(cell).strip() for cell in row[CSV_FIELDS["track_points_json"] :] if str(cell).strip()]
    if len(tail) <= 1:
        return points, issue
    joined = ",".join(tail)
    repaired_points, repaired_issue = _track_points(joined)
    if repaired_issue is None or repaired_points:
        return repaired_points, repaired_issue
    return points, issue


def _track_points(value: str) -> tuple[list[list[float]], str | None]:
    text = str(value or "").strip()
    if not text:
        return [], "EMPTY_TRACK_JSON"
    payload = _loads_track_json(text)
    if payload is None:
        return [], "INVALID_TRACK_JSON"
    if not isinstance(payload, list):
        return [], "TRACK_JSON_NOT_LIST"
    points: list[list[float]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        lng = _float_or_none(item.get("longitude"))
        lat = _float_or_none(item.get("latitude"))
        if lng is None or lat is None or not _valid_lng_lat(lng, lat):
            continue
        points.append([lng, lat])
    return points, None


def _loads_track_json(text: str) -> Any | None:
    candidates = [text]
    if '""' in text:
        candidates.append(text.replace('""', '"'))
    if "]" in text:
        trimmed = text[: text.rfind("]") + 1]
        candidates.append(trimmed)
        if '""' in trimmed:
            candidates.append(trimmed.replace('""', '"'))
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return None


def _clean_track_points(points: list[list[float]]) -> list[list[float]]:
    output: list[list[float]] = []
    previous: list[float] | None = None
    for lng, lat in points:
        current = [round(float(lng), 7), round(float(lat), 7)]
        if previous is not None and current == previous:
            continue
        output.append(current)
        previous = current
    return output


def _track_metrics(
    *,
    point_count: int,
    cleaned_points: list[list[float]],
    point_issue: str | None,
    origin: tuple[float | None, float | None],
    destination: tuple[float | None, float | None],
    min_geometry_points: int,
    max_reference_segment_km: float,
    max_endpoint_offset_km: float,
) -> TrackMetrics:
    issue_codes: list[str] = []
    if point_issue:
        issue_codes.append(point_issue)
    cleaned_count = len(cleaned_points)
    if cleaned_count == 0:
        issue_codes.append("NO_VALID_TRACK_POINT")
    elif cleaned_count == 1:
        issue_codes.append("SINGLE_POINT_TRACK")
    elif cleaned_count < min_geometry_points:
        issue_codes.append("TOO_FEW_TRACK_POINTS")
    line_length = _line_length_km(cleaned_points) if cleaned_count >= 2 else None
    direct_distance = _haversine_km(cleaned_points[0], cleaned_points[-1]) if cleaned_count >= 2 else None
    ratio = line_length / direct_distance if line_length is not None and direct_distance and direct_distance > 0 else None
    max_segment = _max_segment_km(cleaned_points) if cleaned_count >= 2 else None
    if max_segment is not None and max_segment > max_reference_segment_km:
        issue_codes.append("TRACK_LONG_SAMPLE_GAP")
    origin_point = _point_or_none(origin)
    destination_point = _point_or_none(destination)
    first_to_origin = _haversine_km(cleaned_points[0], origin_point) if cleaned_count and origin_point else None
    last_to_destination = _haversine_km(cleaned_points[-1], destination_point) if cleaned_count and destination_point else None
    first_to_destination = _haversine_km(cleaned_points[0], destination_point) if cleaned_count and destination_point else None
    last_to_origin = _haversine_km(cleaned_points[-1], origin_point) if cleaned_count and origin_point else None
    normal_offset = _max_or_none(first_to_origin, last_to_destination)
    reversed_offset = _max_or_none(first_to_destination, last_to_origin)
    direction_code = "UNKNOWN"
    endpoint_offset = normal_offset
    if normal_offset is not None and reversed_offset is not None:
        if reversed_offset + 0.5 < normal_offset:
            direction_code = "REVERSED_TRACK"
            endpoint_offset = reversed_offset
        else:
            direction_code = "OD_DIRECTION"
            endpoint_offset = normal_offset
    elif cleaned_count >= 2:
        direction_code = "OD_DIRECTION"
    if endpoint_offset is not None and endpoint_offset > max_endpoint_offset_km:
        issue_codes.append("TRACK_ENDPOINT_OFFSET_REVIEW")
    usable_geometry = (
        cleaned_count >= min_geometry_points
        and max_segment is not None
        and max_segment <= max_reference_segment_km
        and (endpoint_offset is None or endpoint_offset <= max_endpoint_offset_km)
    )
    usable_condition = bool(origin_point and destination_point)
    quality_code = "GEOMETRY_REFERENCE_READY" if usable_geometry else "CONDITION_REFERENCE_ONLY" if usable_condition else "INVALID_REFERENCE"
    quality_score = _quality_score(
        usable_geometry=usable_geometry,
        cleaned_count=cleaned_count,
        max_segment=max_segment,
        endpoint_offset=endpoint_offset,
        issue_codes=issue_codes,
    )
    return TrackMetrics(
        point_count=point_count,
        cleaned_point_count=cleaned_count,
        line_length_km=_round(line_length, 3),
        direct_distance_km=_round(direct_distance, 3),
        length_to_direct_ratio=_round(ratio, 4),
        max_segment_km=_round(max_segment, 3),
        first_to_origin_km=_round(first_to_origin, 3),
        last_to_destination_km=_round(last_to_destination, 3),
        first_to_destination_km=_round(first_to_destination, 3),
        last_to_origin_km=_round(last_to_origin, 3),
        direction_code=direction_code,
        endpoint_max_offset_km=_round(endpoint_offset, 3),
        quality_code=quality_code,
        issue_codes=sorted(set(issue_codes)),
        usable_as_geometry_reference=usable_geometry,
        usable_as_condition_reference=usable_condition,
        quality_score=quality_score,
    )


def _quality_score(
    *,
    usable_geometry: bool,
    cleaned_count: int,
    max_segment: float | None,
    endpoint_offset: float | None,
    issue_codes: list[str],
) -> int:
    score = 100 if usable_geometry else 62
    if cleaned_count < 2:
        score = min(score, 35)
    elif cleaned_count < 5:
        score = min(score, 55)
    if max_segment is not None:
        score -= min(35, int(max(0.0, max_segment - 5.0) * 2))
    if endpoint_offset is not None:
        score -= min(25, int(max(0.0, endpoint_offset - 2.0) * 2))
    score -= 8 * len({code for code in issue_codes if code not in {"TRACK_ENDPOINT_OFFSET_REVIEW"}})
    return max(0, min(100, score))


def _aggregate_by_od(references: list[RouteReference]) -> dict[str, OdAggregate]:
    groups: dict[str, OdAggregate] = {}
    for ref in references:
        key = f"{ref.origin_code}|{ref.destination_code}"
        group = groups.get(key)
        if group is None:
            group = OdAggregate(
                origin_code=ref.origin_code,
                origin_name=ref.origin_name,
                destination_code=ref.destination_code,
                destination_name=ref.destination_name,
            )
            groups[key] = group
        group.row_count += 1
        group.route_codes.update([ref.route_code or "-"])
        group.water_systems.update(ref.water_systems)
        group.cargo_codes.update(ref.cargo_codes)
        group.quality_codes.update([ref.track_metrics.quality_code])
        if ref.track_metrics.usable_as_geometry_reference:
            group.geometry_reference_count += 1
        if ref.track_metrics.usable_as_condition_reference:
            group.condition_reference_count += 1
        for target, value in (
            (group.tonnage_min_values, ref.tonnage_min),
            (group.tonnage_max_values, ref.tonnage_max),
            (group.width_max_values, ref.ship_width_max_m),
            (group.length_max_values, ref.ship_length_max_m),
        ):
            if value is not None:
                target.append(value)
        candidate = _reference_payload(ref, include_geometry=False)
        if group.best_reference is None or candidate["quality_score"] > group.best_reference["quality_score"]:
            group.best_reference = candidate
    return groups


async def _match_water_names(session: AsyncSession, water_names: list[str]) -> dict[str, Any]:
    channels = list((await session.execute(select(NavigationChannel))).scalars())
    bodies = list((await session.execute(select(NavigationWaterBody))).scalars())
    areas = list((await session.execute(select(NavigationWaterArea))).scalars())
    channel_names = _name_index(
        (int(row.id), row.channel_code, row.channel_name, row.official_name, row.display_name, *(row.alias_names or []))
        for row in channels
    )
    body_names = _name_index(
        (
            int(row.id),
            row.water_body_code,
            row.production_name,
            row.display_name,
            row.water_body_name,
            row.normalized_water_name,
        )
        for row in bodies
    )
    area_names = _name_index(
        (
            int(row.id),
            row.source_object_id,
            row.water_name,
            row.normalized_water_name,
            *(_raw_property_names(row.raw_properties_json)),
        )
        for row in areas
    )
    items: list[dict[str, Any]] = []
    counter = Counter()
    for name in water_names:
        normalized_variants = _norm_variants(name)
        matched = []
        for source_type, index in (
            ("NAVIGATION_CHANNEL", channel_names),
            ("WATER_BODY", body_names),
            ("WATER_AREA", area_names),
        ):
            for normalized in normalized_variants:
                if normalized in index:
                    matched.extend({"source_type_code": source_type, "match_rule": "EXACT_OR_ALIAS", **payload} for payload in index[normalized][:10])
            if not matched:
                matched.extend(
                    {"source_type_code": source_type, "match_rule": "CONTAINS_ALIAS", **payload}
                    for payload in _contains_matches(index, normalized_variants)[:10]
                )
        matched = _dedupe_match_payloads(matched)
        status = "MATCHED" if matched else "UNMATCHED"
        counter[status] += 1
        items.append({"water_name": name, "match_status_code": status, "matches": matched[:20]})
    return {
        "summary": {
            "water_name_count": len(water_names),
            "matched_count": counter["MATCHED"],
            "unmatched_count": counter["UNMATCHED"],
        },
        "items": items,
    }


def _name_index(rows: Iterable[tuple[Any, ...]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        ref_id = int(row[0])
        ref_code = str(row[1] or "")
        for name in row[2:]:
            text = str(name or "").strip()
            payload = {"ref_id": ref_id, "ref_code": ref_code, "matched_name": text}
            for normalized in _norm_variants(text):
                if payload not in index[normalized]:
                    index[normalized].append(payload)
    return index


def _contains_matches(index: dict[str, list[dict[str, Any]]], query_variants: set[str]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    useful_queries = {item for item in query_variants if len(item) >= 3}
    for key, payloads in index.items():
        if len(key) < 3:
            continue
        if not any(query in key or key in query for query in useful_queries):
            continue
        for payload in payloads:
            seen_key = (str(payload.get("ref_code")), int(payload.get("ref_id") or 0))
            if seen_key in seen:
                continue
            seen.add(seen_key)
            output.append(payload)
    return output


def _dedupe_match_payloads(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for item in items:
        key = (
            item.get("source_type_code"),
            item.get("ref_id"),
            item.get("ref_code"),
            item.get("matched_name"),
            item.get("match_rule"),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _summary(references: list[RouteReference], od_groups: dict[str, OdAggregate]) -> dict[str, Any]:
    quality_counts = Counter(ref.track_metrics.quality_code for ref in references)
    issue_counts = Counter(code for ref in references for code in ref.track_metrics.issue_codes)
    point_counts = [ref.track_metrics.cleaned_point_count for ref in references]
    max_segments = [ref.track_metrics.max_segment_km for ref in references if ref.track_metrics.max_segment_km is not None]
    endpoint_offsets = [ref.track_metrics.endpoint_max_offset_km for ref in references if ref.track_metrics.endpoint_max_offset_km is not None]
    tonnage_max_values = [ref.tonnage_max for ref in references if ref.tonnage_max is not None]
    width_max_values = [ref.ship_width_max_m for ref in references if ref.ship_width_max_m is not None]
    length_max_values = [ref.ship_length_max_m for ref in references if ref.ship_length_max_m is not None]
    geometry_refs = [ref for ref in references if ref.track_metrics.usable_as_geometry_reference]
    condition_refs = [ref for ref in references if ref.track_metrics.usable_as_condition_reference]
    return {
        "row_count": len(references),
        "unique_route_count": len({ref.route_code for ref in references if ref.route_code}),
        "unique_od_count": len(od_groups),
        "unique_waybill_count": len({ref.waybill_code for ref in references if ref.waybill_code}),
        "origin_node_count": len({ref.origin_code for ref in references if ref.origin_code}),
        "destination_node_count": len({ref.destination_code for ref in references if ref.destination_code}),
        "water_system_count": len(_all_water_names(references)),
        "quality_counts": dict(sorted(quality_counts.items())),
        "issue_counts": dict(sorted(issue_counts.items())),
        "geometry_reference_count": len(geometry_refs),
        "condition_reference_count": len(condition_refs),
        "track_point_stats": _stats(point_counts),
        "max_segment_km_stats": _stats(max_segments),
        "endpoint_offset_km_stats": _stats(endpoint_offsets),
        "observed_tonnage_max_stats": _stats(tonnage_max_values),
        "observed_ship_width_max_m_stats": _stats(width_max_values),
        "observed_ship_length_max_m_stats": _stats(length_max_values),
        "top_water_systems": Counter(name for ref in references for name in ref.water_systems).most_common(30),
        "top_routes": Counter(ref.route_code for ref in references if ref.route_code).most_common(20),
    }


def _condition_constraints_by_water_system(references: list[RouteReference], *, limit: int = 50) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for ref in references:
        if not ref.track_metrics.usable_as_condition_reference:
            continue
        for water_name in ref.water_systems:
            group = groups.setdefault(
                water_name,
                {
                    "water_system_name": water_name,
                    "condition_reference_count": 0,
                    "geometry_reference_count": 0,
                    "route_codes": Counter(),
                    "od_keys": set(),
                    "cargo_codes": Counter(),
                    "tonnage_max_values": [],
                    "ship_width_max_values": [],
                    "ship_length_max_values": [],
                    "quality_codes": Counter(),
                },
            )
            group["condition_reference_count"] += 1
            if ref.track_metrics.usable_as_geometry_reference:
                group["geometry_reference_count"] += 1
            group["route_codes"].update([ref.route_code or "-"])
            group["od_keys"].add(f"{ref.origin_code}|{ref.destination_code}")
            group["cargo_codes"].update(ref.cargo_codes)
            group["quality_codes"].update([ref.track_metrics.quality_code])
            if ref.tonnage_max is not None:
                group["tonnage_max_values"].append(ref.tonnage_max)
            if ref.ship_width_max_m is not None:
                group["ship_width_max_values"].append(ref.ship_width_max_m)
            if ref.ship_length_max_m is not None:
                group["ship_length_max_values"].append(ref.ship_length_max_m)
    rows = sorted(
        groups.values(),
        key=lambda item: (item["geometry_reference_count"], item["condition_reference_count"]),
        reverse=True,
    )[:limit]
    output: list[dict[str, Any]] = []
    for item in rows:
        output.append(
            {
                "water_system_name": item["water_system_name"],
                "condition_reference_count": item["condition_reference_count"],
                "geometry_reference_count": item["geometry_reference_count"],
                "od_count": len(item["od_keys"]),
                "route_count": len([code for code in item["route_codes"] if code and code != "-"]),
                "observed_max_tonnage": _round(max(item["tonnage_max_values"]), 2) if item["tonnage_max_values"] else None,
                "observed_max_ship_width_m": _round(max(item["ship_width_max_values"]), 2) if item["ship_width_max_values"] else None,
                "observed_max_ship_length_m": _round(max(item["ship_length_max_values"]), 2) if item["ship_length_max_values"] else None,
                "observed_tonnage_stats": _stats(item["tonnage_max_values"]),
                "observed_ship_width_m_stats": _stats(item["ship_width_max_values"]),
                "observed_ship_length_m_stats": _stats(item["ship_length_max_values"]),
                "top_cargo_codes": item["cargo_codes"].most_common(10),
                "quality_codes": dict(sorted(item["quality_codes"].items())),
                "source_policy_code": "OBSERVED_WAYBILL_CONSTRAINT_NOT_OFFICIAL_GRADE",
            }
        )
    return output


def _top_od_groups(od_groups: dict[str, OdAggregate], *, limit: int) -> list[dict[str, Any]]:
    rows = sorted(
        od_groups.values(),
        key=lambda item: (item.geometry_reference_count, item.condition_reference_count, item.row_count),
        reverse=True,
    )[:limit]
    output: list[dict[str, Any]] = []
    for group in rows:
        output.append(
            {
                "origin_code": group.origin_code,
                "origin_name": group.origin_name,
                "destination_code": group.destination_code,
                "destination_name": group.destination_name,
                "row_count": group.row_count,
                "geometry_reference_count": group.geometry_reference_count,
                "condition_reference_count": group.condition_reference_count,
                "route_codes": group.route_codes.most_common(10),
                "water_systems": group.water_systems.most_common(10),
                "cargo_codes": group.cargo_codes.most_common(10),
                "quality_codes": dict(sorted(group.quality_codes.items())),
                "tonnage_min": _round(min(group.tonnage_min_values), 2) if group.tonnage_min_values else None,
                "tonnage_max": _round(max(group.tonnage_max_values), 2) if group.tonnage_max_values else None,
                "ship_width_max_m": _round(max(group.width_max_values), 2) if group.width_max_values else None,
                "ship_length_max_m": _round(max(group.length_max_values), 2) if group.length_max_values else None,
                "best_reference": group.best_reference,
            }
        )
    return output


def _recommended_usage(
    references: list[RouteReference],
    od_groups: dict[str, OdAggregate],
    water_name_match: dict[str, Any],
) -> dict[str, Any]:
    geometry_od_count = sum(1 for group in od_groups.values() if group.geometry_reference_count > 0)
    condition_only_od_count = sum(
        1 for group in od_groups.values() if group.geometry_reference_count == 0 and group.condition_reference_count > 0
    )
    unmatched_water = [item["water_name"] for item in water_name_match["items"] if item["match_status_code"] == "UNMATCHED"]
    return {
        "route_cache": {
            "candidate_count": sum(1 for ref in references if ref.track_metrics.usable_as_geometry_reference),
            "status_code": "REFERENCE_ONLY_UNTIL_WATER_AND_ENDPOINT_VALIDATED",
            "rule": "Only promote to VALID route cache after water coverage, endpoint snap, long-jump, and foldback validation pass.",
        },
        "seed_centerline": {
            "candidate_od_count": geometry_od_count,
            "rule": "Cluster geometry-grade tracks by OD and water-system labels, then promote only the shared corridor/medial path as seed centerline evidence.",
        },
        "boundary_repair": {
            "candidate_od_count": geometry_od_count,
            "rule": "Use buffered high-quality real tracks as boundary-expansion candidates only where local water bodies already support the corridor.",
        },
        "condition_rules": {
            "candidate_od_count": condition_only_od_count,
            "rule": "Use sparse tracks for OD, cargo, tonnage, vessel width/length, and main-water-system constraints; do not use them as geometry.",
        },
        "water_name_backfill": {
            "unmatched_name_count": len(unmatched_water),
            "unmatched_names": unmatched_water[:50],
            "rule": "Unmatched water-system labels should be added to alias config or used to name local unnamed water bodies when spatial evidence agrees.",
        },
    }


def _write_reference_jsonl(path: Path, references: list[RouteReference]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for ref in references:
            if not ref.track_metrics.usable_as_condition_reference:
                continue
            handle.write(json.dumps(_reference_payload(ref, include_geometry=True), ensure_ascii=False, separators=(",", ":")) + "\n")


def _reference_payload(ref: RouteReference, *, include_geometry: bool) -> dict[str, Any]:
    payload = {
        "row_no": ref.row_no,
        "waybill_code": ref.waybill_code,
        "route_code": ref.route_code,
        "route_name": ref.route_name,
        "origin": {
            "code": ref.origin_code,
            "name": ref.origin_name,
            "longitude": ref.origin_lng,
            "latitude": ref.origin_lat,
        },
        "destination": {
            "code": ref.destination_code,
            "name": ref.destination_name,
            "longitude": ref.destination_lng,
            "latitude": ref.destination_lat,
        },
        "water_systems": ref.water_systems,
        "cargo_codes": ref.cargo_codes,
        "declared_distance_km": ref.declared_distance_km,
        "tonnage_min": ref.tonnage_min,
        "tonnage_max": ref.tonnage_max,
        "ship_width_max_m": ref.ship_width_max_m,
        "ship_length_max_m": ref.ship_length_max_m,
        "quality_code": ref.track_metrics.quality_code,
        "quality_score": ref.track_metrics.quality_score,
        "track_metrics": asdict(ref.track_metrics),
    }
    if include_geometry:
        payload["geometry_json"] = _line_geojson(ref.track_points)
    return payload


def _geojson(references: list[RouteReference], *, geojson_limit: int) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    selected = sorted(
        references,
        key=lambda ref: (ref.track_metrics.usable_as_geometry_reference, ref.track_metrics.quality_score, ref.track_metrics.cleaned_point_count),
        reverse=True,
    )[:geojson_limit]
    for ref in selected:
        line = _line_geojson(ref.track_points)
        if line:
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "feature_role": "waybill_track_reference",
                        "waybill_code": ref.waybill_code,
                        "route_code": ref.route_code,
                        "route_name": ref.route_name,
                        "origin_name": ref.origin_name,
                        "destination_name": ref.destination_name,
                        "water_systems": ",".join(ref.water_systems),
                        "quality_code": ref.track_metrics.quality_code,
                        "quality_score": ref.track_metrics.quality_score,
                        "point_count": ref.track_metrics.cleaned_point_count,
                        "max_segment_km": ref.track_metrics.max_segment_km,
                    },
                    "geometry": line,
                }
            )
        for role, lng, lat in (
            ("origin", ref.origin_lng, ref.origin_lat),
            ("destination", ref.destination_lng, ref.destination_lat),
        ):
            if lng is None or lat is None:
                continue
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "feature_role": f"waybill_{role}",
                        "waybill_code": ref.waybill_code,
                        "route_code": ref.route_code,
                        "node_name": ref.origin_name if role == "origin" else ref.destination_name,
                    },
                    "geometry": {"type": "Point", "coordinates": [lng, lat]},
                }
            )
    return {"type": "FeatureCollection", "features": features}


def _line_geojson(points: list[list[float]]) -> dict[str, Any] | None:
    if len(points) < 2:
        return None
    try:
        line = make_valid(LineString(points))
    except Exception:
        return None
    if line.is_empty or not isinstance(line, LineString):
        return None
    return mapping(line)


def _all_water_names(references: list[RouteReference]) -> list[str]:
    return sorted({name for ref in references for name in ref.water_systems if name})


def _range_values(value: str) -> tuple[float | None, float | None]:
    text = str(value or "").strip()
    numbers: list[float] = []
    token = ""
    for char in text:
        if char.isdigit() or char in {".", "-"}:
            token += char
        elif token:
            parsed = _float_or_none(token)
            if parsed is not None:
                numbers.append(parsed)
            token = ""
    if token:
        parsed = _float_or_none(token)
        if parsed is not None:
            numbers.append(parsed)
    if not numbers:
        return None, None
    if len(numbers) == 1:
        return numbers[0], numbers[0]
    return min(numbers[0], numbers[1]), max(numbers[0], numbers[1])


def _split_csv_cell(value: str) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for part in str(value or "").replace("，", ",").replace("、", ",").split(","):
        text = part.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def _split_water_systems(value: str) -> list[str]:
    return [item for item in _split_csv_cell(value) if _looks_like_water_name(item)]


def _looks_like_water_name(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if text.upper() in {"NULL", "NONE", "N/A", "NA", "-"}:
        return False
    lowered = text.lower()
    if any(token in lowered for token in ("latitude", "longitude", "createtime")):
        return False
    if any(token in text for token in ("{", "}", "[", "]", "\"\"", ":")):
        return False
    return any(token in text for token in ("江", "河", "湖", "港", "运河", "水道", "干流", "溪", "渠"))


def _raw_property_names(properties: Any) -> list[str]:
    if not isinstance(properties, dict):
        return []
    keys = ("name", "Name", "NAME", "water_name", "WATER_NAME", "river_name", "RIVER_NAME", "名称", "水系名称", "河流名称")
    return [str(properties.get(key) or "").strip() for key in keys if str(properties.get(key) or "").strip()]


def _norm(value: Any) -> str:
    text = str(value or "").strip().lower()
    for token in (" ", "\t", "\n", "—", "-", "_", "（", "）", "(", ")", "/", "·"):
        text = text.replace(token, "")
    return text


def _norm_variants(value: Any) -> set[str]:
    raw = str(value or "").strip()
    if not raw:
        return set()
    variants = {raw}
    no_region = raw
    for left, right in (("(", ")"), ("（", "）")):
        while left in no_region and right in no_region and no_region.index(left) < no_region.rindex(right):
            start = no_region.index(left)
            end = no_region.rindex(right)
            no_region = (no_region[:start] + no_region[end + 1 :]).strip()
            variants.add(no_region)
    for suffix in ("干流", "航运干线", "高等级航道网", "相关水域", "航道", "水道", "河道"):
        for item in list(variants):
            if item.endswith(suffix) and len(item) > len(suffix) + 1:
                variants.add(item[: -len(suffix)])
    for suffix in ("上游", "中游", "下游"):
        for item in list(variants):
            if item.endswith(suffix) and len(item) > len(suffix) + 1:
                variants.add(item[: -len(suffix)])
    if "长江" in raw:
        variants.update({"长江", "长江干流"})
    if "京杭" in raw and "运河" in raw:
        variants.update({"京杭运河", "京杭大运河"})
    if raw in {"沙颖河", "沙颍河"}:
        variants.update({"沙颖河", "沙颍河", "颖河", "颍河"})
    return {item for item in (_norm(variant) for variant in variants) if item}


def _stats(values: list[float | int]) -> dict[str, Any]:
    values = [float(value) for value in values if value is not None]
    if not values:
        return {"count": 0, "min": None, "p50": None, "p90": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": _round(min(values), 3),
        "p50": _round(_percentile(values, 0.5), 3),
        "p90": _round(_percentile(values, 0.9), 3),
        "max": _round(max(values), 3),
        "mean": _round(statistics.fmean(values), 3),
    }


def _percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = (len(ordered) - 1) * p
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[int(index)]
    return ordered[lower] * (upper - index) + ordered[upper] * (index - lower)


def _line_length_km(points: list[list[float]]) -> float:
    return sum(_haversine_km(left, right) for left, right in zip(points[:-1], points[1:]))


def _max_segment_km(points: list[list[float]]) -> float:
    return max((_haversine_km(left, right) for left, right in zip(points[:-1], points[1:])), default=0.0)


def _haversine_km(left: Iterable[float], right: Iterable[float]) -> float:
    lng1, lat1 = [float(item) for item in left]
    lng2, lat2 = [float(item) for item in right]
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _point_or_none(value: tuple[float | None, float | None]) -> list[float] | None:
    lng, lat = value
    if lng is None or lat is None or not _valid_lng_lat(lng, lat):
        return None
    return [float(lng), float(lat)]


def _valid_lng_lat(lng: float, lat: float) -> bool:
    return -180 <= float(lng) <= 180 and -90 <= float(lat) <= 90


def _float_or_none(value: Any) -> float | None:
    try:
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _max_or_none(*values: float | None) -> float | None:
    numbers = [value for value in values if value is not None]
    return max(numbers) if numbers else None


def _round(value: float | None, digits: int) -> float | None:
    return round(float(value), digits) if value is not None else None


if __name__ == "__main__":
    asyncio.run(main())
