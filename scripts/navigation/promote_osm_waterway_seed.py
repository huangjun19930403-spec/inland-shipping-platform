"""Promote named OSM navigable waterways into audited navigation seed geometry."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, mapping, shape
from shapely.ops import unary_union
from shapely.validation import make_valid
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import NavigationChannelCenterline
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.modules.navigation.production_pipeline.boundary_quality_audit import audit_boundary_integrity


DEFAULT_OUTPUT = Path("runtime/navigation-production/reports/osm_waterway_seed_promotion_report.json")
GEOD_SCALE = Decimal("0.000000000000001")
MEASURE_SCALE = Decimal("0.000000000000000001")


@dataclass(slots=True)
class OSMWay:
    way_id: int
    name: str | None
    tags: dict[str, Any]
    coordinates: list[tuple[float, float]]


@dataclass(slots=True)
class PromotionReport:
    generated_at: str
    dry_run: bool
    channel_code: str
    channel_id: int | None = None
    waterway_name: str | None = None
    selected_way_ids: list[int] = field(default_factory=list)
    promoted_boundary_id: int | None = None
    promoted_centerline_id: int | None = None
    validation: dict[str, Any] = field(default_factory=dict)
    boundary_audit: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Promote named OSM waterway geometry into navigation seed.")
    parser.add_argument("--channel-code", required=True)
    parser.add_argument("--osm-json", type=Path, required=True)
    parser.add_argument("--waterway-name", required=True)
    parser.add_argument("--way-id", action="append", type=int, default=[])
    parser.add_argument("--centerline-code", default=None)
    parser.add_argument("--centerline-name", default=None)
    parser.add_argument("--corridor-buffer-degree", type=float, default=0.0012)
    parser.add_argument("--max-way-gap-m", type=float, default=1000.0)
    parser.add_argument("--confidence-score", type=int, default=82)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _q(value: Any, scale: Decimal = GEOD_SCALE) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(scale, rounding=ROUND_HALF_UP)


def _safe_geometry(value: Any):
    if not isinstance(value, dict):
        return None
    try:
        geometry = make_valid(shape(value))
    except Exception:
        return None
    return None if geometry.is_empty else geometry


def _clean_coords(coords: list[tuple[float, float]]) -> list[tuple[float, float]]:
    output: list[tuple[float, float]] = []
    previous: tuple[float, float] | None = None
    for lng, lat in coords:
        coord = (round(float(lng), 8), round(float(lat), 8))
        if coord == previous:
            continue
        output.append(coord)
        previous = coord
    return output


def _distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    return (((a[0] - b[0]) * 111_320) ** 2 + ((a[1] - b[1]) * 110_540) ** 2) ** 0.5


def _line_length_km(coords: list[tuple[float, float]]) -> float:
    return sum(_distance_m(a, b) for a, b in zip(coords[:-1], coords[1:])) / 1000.0


def _max_step_km(coords: list[tuple[float, float]]) -> float:
    if len(coords) < 2:
        return 0.0
    return max(_distance_m(a, b) for a, b in zip(coords[:-1], coords[1:])) / 1000.0


def _load_osm_ways(path: Path, *, waterway_name: str, way_ids: list[int]) -> list[OSMWay]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    selected_ids = {int(item) for item in way_ids}
    ways: list[OSMWay] = []
    for element in payload.get("elements") or []:
        if element.get("type") != "way" or not isinstance(element.get("geometry"), list):
            continue
        tags = element.get("tags") if isinstance(element.get("tags"), dict) else {}
        name = tags.get("name:zh") or tags.get("name") or tags.get("name:en")
        way_id = int(element.get("id"))
        if selected_ids:
            matched = way_id in selected_ids
        else:
            matched = name == waterway_name
        if not matched:
            continue
        coords = _clean_coords([(float(item["lon"]), float(item["lat"])) for item in element["geometry"]])
        if len(coords) >= 2:
            ways.append(OSMWay(way_id=way_id, name=name, tags=tags, coordinates=coords))
    if selected_ids and selected_ids != {way.way_id for way in ways}:
        missing = sorted(selected_ids - {way.way_id for way in ways})
        raise SystemExit(f"OSM way ids not found in input: {missing}")
    if not ways:
        raise SystemExit(f"No OSM waterway ways matched {waterway_name}")
    return ways


def _chain_ways(ways: list[OSMWay]) -> tuple[LineString, dict[str, Any]]:
    remaining = list(ways)
    endpoints = [
        (way.coordinates[0][0], way.coordinates[0][1], index, False)
        for index, way in enumerate(remaining)
    ] + [
        (way.coordinates[-1][0], way.coordinates[-1][1], index, True)
        for index, way in enumerate(remaining)
    ]
    _x, _y, start_index, reverse = min(endpoints, key=lambda item: (item[0], item[1]))
    start = remaining.pop(start_index)
    coords = list(reversed(start.coordinates)) if reverse else list(start.coordinates)
    ordered_way_ids = [start.way_id]
    gaps: list[dict[str, Any]] = []
    while remaining:
        current = coords[-1]
        best: tuple[float, int, bool] | None = None
        for index, way in enumerate(remaining):
            forward_gap = _distance_m(current, way.coordinates[0])
            reverse_gap = _distance_m(current, way.coordinates[-1])
            candidate = (forward_gap, index, False) if forward_gap <= reverse_gap else (reverse_gap, index, True)
            if best is None or candidate[0] < best[0]:
                best = candidate
        assert best is not None
        gap_m, index, use_reverse = best
        way = remaining.pop(index)
        next_coords = list(reversed(way.coordinates)) if use_reverse else list(way.coordinates)
        if gap_m > 1:
            gaps.append(
                {
                    "from": [round(coords[-1][0], 8), round(coords[-1][1], 8)],
                    "to": [round(next_coords[0][0], 8), round(next_coords[0][1], 8)],
                    "gap_m": round(gap_m, 2),
                    "next_way_id": way.way_id,
                }
            )
        coords.extend(next_coords[1:] if _distance_m(coords[-1], next_coords[0]) <= 1 else next_coords)
        ordered_way_ids.append(way.way_id)
    coords = _clean_coords(coords)
    return LineString(coords), {
        "ordered_way_ids": ordered_way_ids,
        "way_join_gaps": gaps,
        "point_count": len(coords),
        "line_length_km": round(_line_length_km(coords), 3),
        "max_step_km": round(_max_step_km(coords), 3),
    }


def _geometry_counts(geometry) -> tuple[int, int]:
    polygons = []
    if geometry.geom_type == "Polygon":
        polygons = [geometry]
    elif geometry.geom_type == "MultiPolygon":
        polygons = list(geometry.geoms)
    ring_count = 0
    point_count = 0
    for polygon in polygons:
        rings = [polygon.exterior, *list(polygon.interiors)]
        ring_count += len(rings)
        point_count += sum(len(ring.coords) for ring in rings)
    return ring_count, point_count


async def main() -> None:
    args = parse_args()
    report = PromotionReport(
        generated_at=datetime.now(UTC).isoformat(),
        dry_run=bool(args.dry_run),
        channel_code=str(args.channel_code),
        waterway_name=str(args.waterway_name),
    )
    ways = _load_osm_ways(args.osm_json, waterway_name=str(args.waterway_name), way_ids=list(args.way_id or []))
    line, validation = _chain_ways(ways)
    report.selected_way_ids = validation["ordered_way_ids"]
    max_gap = max((item["gap_m"] for item in validation["way_join_gaps"]), default=0.0)
    validation["max_way_gap_m"] = max_gap
    validation["max_way_gap_allowed_m"] = float(args.max_way_gap_m)
    validation["source_tags"] = [
        {"way_id": way.way_id, "name": way.name, "tags": way.tags}
        for way in ways
    ]
    if max_gap > float(args.max_way_gap_m):
        validation["status"] = "BLOCKED"
        validation["issue_code"] = "OSM_WAY_GAP_TOO_LARGE"
        report.validation = validation
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
        raise SystemExit("OSM way chain has an untrusted gap")
    validation["status"] = "READY"
    report.validation = validation

    async with AsyncSessionLocal() as session:
        channel = await session.scalar(select(NavigationChannel).where(NavigationChannel.channel_code == args.channel_code))
        if channel is None:
            raise SystemExit(f"Navigation channel not found: {args.channel_code}")
        report.channel_id = int(channel.id)
        current_boundaries = list(
            (
                await session.execute(
                    select(NavigationChannelBoundary).where(
                        NavigationChannelBoundary.channel_id == int(channel.id),
                        NavigationChannelBoundary.is_current.is_(True),
                    )
                )
            ).scalars()
        )
        existing_geometries = [
            geometry
            for row in current_boundaries
            if (geometry := _safe_geometry(row.geometry_json)) is not None
        ]
        corridor = line.buffer(float(args.corridor_buffer_degree), cap_style=1, join_style=2)
        boundary_geometry = make_valid(unary_union([corridor, *existing_geometries]))
        centerline_code = args.centerline_code or f"OSM-WATERWAY-{channel.channel_code}-{args.waterway_name}"[:96]
        centerline_name = args.centerline_name or f"{channel.channel_name} OSM {args.waterway_name}中心线"
        source_trace = {
            "source": "promote_osm_waterway_seed",
            "osm_json": str(args.osm_json),
            "waterway_name": args.waterway_name,
            "selected_way_ids": report.selected_way_ids,
            "validation": validation,
            "corridor_buffer_degree": float(args.corridor_buffer_degree),
            "previous_boundary_ids": [int(row.id) for row in current_boundaries],
            "basemap_verification": {
                "status_code": "AUTO_VERIFIED_BY_OSM_NAMED_NAVIGABLE_WATERWAY",
                "source_code": "OSM_WATERWAY_WITH_SHIP_OR_BOAT_TAG",
            },
            "generated_at": datetime.now(UTC).isoformat(),
        }
        audit = audit_boundary_integrity(
            channel={
                "technical_grade_current_code": channel.technical_grade_current_code,
                "technical_grade_planned_code": channel.technical_grade_planned_code,
            },
            boundary={
                "geometry_status_code": "AVAILABLE",
                "geometry_json": mapping(boundary_geometry),
                "coverage_policy_code": "OSM_WATERWAY_CORRIDOR",
                "source_trace_json": source_trace,
            },
            centerline_geometries=[mapping(line)],
            require_centerline=True,
        )
        report.boundary_audit = audit
        if audit.get("blocking_issue_codes"):
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
            raise SystemExit(f"Boundary audit blocked promotion: {audit.get('blocking_issue_codes')}")
        if not args.dry_run:
            for row in current_boundaries:
                row.is_current = False
            centroid = boundary_geometry.centroid
            min_lng, min_lat, max_lng, max_lat = boundary_geometry.bounds
            ring_count, point_count = _geometry_counts(boundary_geometry)
            boundary = NavigationChannelBoundary(
                channel_id=int(channel.id),
                geometry_json=mapping(boundary_geometry),
                center_longitude=_q(centroid.x),
                center_latitude=_q(centroid.y),
                display_center_longitude=_q(centroid.x),
                display_center_latitude=_q(centroid.y),
                bbox_min_lng=_q(min_lng),
                bbox_min_lat=_q(min_lat),
                bbox_max_lng=_q(max_lng),
                bbox_max_lat=_q(max_lat),
                source_shape_length_degree=_q(boundary_geometry.length, MEASURE_SCALE),
                source_shape_area_degree=_q(boundary_geometry.area, MEASURE_SCALE),
                ring_count=ring_count,
                point_count=point_count,
                geometry_status_code="AVAILABLE",
                boundary_quality_code="AUTO_PUBLISHED",
                connectivity_status_code="CONNECTED_WITH_BRIDGES" if boundary_geometry.geom_type == "MultiPolygon" else "CONNECTED",
                repair_status_code="AUTO_REPAIRED",
                coverage_policy_code="OSM_WATERWAY_CORRIDOR",
                geometry_coordinate_system_code="WGS84",
                boundary_coordinate_system_code="WGS84",
                source_trace_json={**source_trace, "boundary_integrity_audit": audit},
                is_current=True,
                imported_at=datetime.now(UTC).replace(tzinfo=None),
            )
            session.add(boundary)
            await session.flush()
            report.promoted_boundary_id = int(boundary.id)
            existing = await session.scalar(
                select(NavigationChannelCenterline).where(NavigationChannelCenterline.centerline_code == centerline_code)
            )
            min_lng, min_lat, max_lng, max_lat = line.bounds
            payload = {
                "channel_id": int(channel.id),
                "segment_id": None,
                "centerline_code": centerline_code,
                "centerline_name": centerline_name,
                "geometry_json": mapping(line),
                "source_type_code": "OSM_WATERWAY",
                "direction_code": "BIDIRECTIONAL",
                "is_main_line": True,
                "confidence_score": max(0, min(100, int(args.confidence_score))),
                "quality_code": "READY_WITH_WARNING",
                "review_status_code": "PUBLISHED",
                "version_no": 1,
                "parent_centerline_id": None,
                "is_current": True,
                "source_trace_json": source_trace,
                "approved_by": None,
                "approved_at": datetime.now(UTC).replace(tzinfo=None),
                "bbox_min_lng": _q(min_lng),
                "bbox_min_lat": _q(min_lat),
                "bbox_max_lng": _q(max_lng),
                "bbox_max_lat": _q(max_lat),
            }
            if existing is None:
                centerline = NavigationChannelCenterline(**payload)
                session.add(centerline)
                await session.flush()
                report.promoted_centerline_id = int(centerline.id)
            else:
                for key, value in payload.items():
                    setattr(existing, key, value)
                await session.flush()
                report.promoted_centerline_id = int(existing.id)
            await session.commit()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    print(f"report_path={args.output}")


if __name__ == "__main__":
    asyncio.run(main())
