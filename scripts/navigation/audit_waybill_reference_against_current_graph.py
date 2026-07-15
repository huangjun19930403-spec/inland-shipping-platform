"""Audit real waybill track references against current navigation seed data.

The source CSV is operational evidence, not automatically valid route geometry.
This script uses only geometry-grade waybill references and compares them with
the currently active graph, channel boundaries, published centerlines, and local
water geometry. Output candidates are repair evidence for seed/boundary work;
they are not user-returnable route cache records.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from pyproj import Geod
from shapely.geometry import GeometryCollection, LineString, MultiLineString, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree
from shapely.validation import make_valid
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.models.navigation import (
    NavigationChannelCenterline,
    NavigationGraphEdge,
    NavigationGraphVersion,
    NavigationWaterArea,
    NavigationWaterBody,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = PROJECT_ROOT / "runtime/navigation-production/reports"
DEFAULT_JSONL = REPORT_DIR / "waybill_route_reference_candidates_constraints_20260608.jsonl"
DEFAULT_ANALYSIS = REPORT_DIR / "waybill_route_reference_analysis_constraints_20260608.json"
DEFAULT_OUTPUT = REPORT_DIR / "waybill_current_graph_boundary_audit_20260611.json"
DEFAULT_CANDIDATES_OUTPUT = REPORT_DIR / "waybill_current_graph_boundary_repair_candidates_20260611.jsonl"
DEFAULT_GEOJSON_OUTPUT = REPORT_DIR / "waybill_current_graph_boundary_audit_20260611.geojson"
GEOD = Geod(ellps="WGS84")


@dataclass(frozen=True)
class ChannelRef:
    id: int
    code: str
    name: str
    names: tuple[str, ...]
    technical_grade_current_code: str | None
    technical_grade_planned_code: str | None


@dataclass(frozen=True)
class GeometryRef:
    geometry: BaseGeometry
    source_type_code: str
    source_id: int
    channel_id: int | None
    names: tuple[str, ...] = ()


class GeometryIndex:
    def __init__(self, refs: list[GeometryRef]) -> None:
        self.refs = refs
        self.geometries = [ref.geometry for ref in refs]
        self.tree = STRtree(self.geometries) if self.geometries else None

    def query(self, geometry: BaseGeometry, *, predicate: str = "intersects") -> list[GeometryRef]:
        if self.tree is None:
            return []
        try:
            hits = self.tree.query(geometry, predicate=predicate)
        except TypeError:
            hits = self.tree.query(geometry)
        output: list[GeometryRef] = []
        for hit in hits:
            if hasattr(hit, "__index__"):
                ref = self.refs[int(hit)]
            else:
                ref = self.refs[self.geometries.index(hit)]
                if predicate == "intersects" and not ref.geometry.intersects(geometry):
                    continue
            output.append(ref)
        return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit geometry-grade waybill tracks against current navigation boundaries and graph."
    )
    parser.add_argument("--jsonl", type=Path, default=DEFAULT_JSONL)
    parser.add_argument("--analysis-report", type=Path, default=DEFAULT_ANALYSIS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--candidate-jsonl-output", type=Path, default=DEFAULT_CANDIDATES_OUTPUT)
    parser.add_argument("--geojson-output", type=Path, default=DEFAULT_GEOJSON_OUTPUT)
    parser.add_argument("--graph-version-id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--boundary-tolerance-m", type=float, default=80.0)
    parser.add_argument("--centerline-tolerance-m", type=float, default=160.0)
    parser.add_argument("--graph-tolerance-m", type=float, default=160.0)
    parser.add_argument("--water-tolerance-m", type=float, default=120.0)
    parser.add_argument("--min-boundary-coverage", type=float, default=0.9)
    parser.add_argument("--min-graph-coverage", type=float, default=0.85)
    parser.add_argument("--min-local-water-coverage", type=float, default=0.75)
    parser.add_argument("--min-candidate-segment-km", type=float, default=0.3)
    parser.add_argument("--repair-buffer-m", type=float, default=220.0)
    parser.add_argument("--geojson-limit", type=int, default=600)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    rows = _read_geometry_rows(args.jsonl, limit=max(0, int(args.limit)))
    analysis = _read_json(args.analysis_report)
    async with AsyncSessionLocal() as session:
        graph = await _resolve_graph(session, args.graph_version_id)
        channels = await _load_channels(session)
        boundaries_by_channel = await _load_boundaries_by_channel(session)
        centerlines_by_channel = await _load_centerlines_by_channel(session)
        graph_edges_by_channel = await _load_graph_edges_by_channel(session, graph_id=int(graph.id))
        water_index = GeometryIndex(await _load_water_geometry_refs(session))

    audit = _audit_rows(
        rows,
        channels=channels,
        boundaries_by_channel=boundaries_by_channel,
        centerlines_by_channel=centerlines_by_channel,
        graph_edges_by_channel=graph_edges_by_channel,
        water_index=water_index,
        analysis=analysis,
        graph=graph,
        args=args,
    )
    _write_outputs(audit, args)
    print(json.dumps(audit["summary"], ensure_ascii=False, indent=2))
    print(f"report_path={args.output}")
    print(f"candidate_jsonl_path={args.candidate_jsonl_output}")
    if args.geojson_output:
        print(f"geojson_path={args.geojson_output}")


def _read_geometry_rows(path: Path, *, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            metrics = row.get("track_metrics") if isinstance(row.get("track_metrics"), dict) else {}
            if not metrics.get("usable_as_geometry_reference"):
                continue
            if _line(row.get("geometry_json")) is None:
                continue
            rows.append(row)
            if limit and len(rows) >= limit:
                break
    return rows


async def _resolve_graph(session, graph_version_id: int | None) -> NavigationGraphVersion:
    if graph_version_id is not None:
        row = await session.get(NavigationGraphVersion, graph_version_id)
        if row is None:
            raise RuntimeError(f"graph_version_id={graph_version_id} not found")
        return row
    row = await session.scalar(
        select(NavigationGraphVersion)
        .where(
            NavigationGraphVersion.is_active.is_(True),
            NavigationGraphVersion.status_code == "READY",
            NavigationGraphVersion.version_code.not_like("MVP%"),
            NavigationGraphVersion.edge_count > 0,
        )
        .order_by(NavigationGraphVersion.id.desc())
        .limit(1)
    )
    if row is None:
        raise RuntimeError("No active READY non-MVP navigation graph with edges")
    return row


async def _load_channels(session) -> list[ChannelRef]:
    rows = list(
        (
            await session.execute(
                select(NavigationChannel).where(NavigationChannel.is_enabled.is_(True)).order_by(NavigationChannel.id)
            )
        ).scalars()
    )
    channels: list[ChannelRef] = []
    for row in rows:
        names: list[str] = []
        for value in (row.channel_name, row.official_name, row.display_name):
            if value:
                names.append(str(value))
        for value in row.alias_names or []:
            if value:
                names.append(str(value))
        channels.append(
            ChannelRef(
                id=int(row.id),
                code=str(row.channel_code),
                name=str(row.channel_name),
                names=tuple(dict.fromkeys(names)),
                technical_grade_current_code=row.technical_grade_current_code,
                technical_grade_planned_code=row.technical_grade_planned_code,
            )
        )
    return channels


async def _load_boundaries_by_channel(session) -> dict[int, BaseGeometry]:
    rows = list(
        (
            await session.execute(
                select(NavigationChannelBoundary).where(
                    NavigationChannelBoundary.is_current.is_(True),
                    NavigationChannelBoundary.geometry_status_code == "AVAILABLE",
                    NavigationChannelBoundary.geometry_json.is_not(None),
                )
            )
        ).scalars()
    )
    grouped: dict[int, list[BaseGeometry]] = defaultdict(list)
    for row in rows:
        geometry = _geometry(row.geometry_json)
        if geometry is not None:
            grouped[int(row.channel_id)].append(geometry)
    return {channel_id: make_valid(unary_union(geoms)) for channel_id, geoms in grouped.items() if geoms}


async def _load_centerlines_by_channel(session) -> dict[int, BaseGeometry]:
    rows = list(
        (
            await session.execute(
                select(NavigationChannelCenterline).where(
                    NavigationChannelCenterline.is_current.is_(True),
                    NavigationChannelCenterline.geometry_json.is_not(None),
                )
            )
        ).scalars()
    )
    grouped: dict[int, list[BaseGeometry]] = defaultdict(list)
    for row in rows:
        line = _line(row.geometry_json)
        if line is not None:
            grouped[int(row.channel_id)].append(line)
    return {channel_id: make_valid(unary_union(lines)) for channel_id, lines in grouped.items() if lines}


async def _load_graph_edges_by_channel(session, *, graph_id: int) -> dict[int, BaseGeometry]:
    rows = list(
        (
            await session.execute(
                select(NavigationGraphEdge).where(
                    NavigationGraphEdge.graph_version_id == graph_id,
                    NavigationGraphEdge.routing_enabled.is_(True),
                    NavigationGraphEdge.geometry_json.is_not(None),
                )
            )
        ).scalars()
    )
    grouped: dict[int, list[BaseGeometry]] = defaultdict(list)
    for row in rows:
        if row.channel_id is None:
            continue
        line = _line(row.geometry_json)
        if line is not None:
            grouped[int(row.channel_id)].append(line)
    return {channel_id: make_valid(unary_union(lines)) for channel_id, lines in grouped.items() if lines}


async def _load_water_geometry_refs(session) -> list[GeometryRef]:
    refs: list[GeometryRef] = []
    area_rows = list(
        (
            await session.execute(
                select(NavigationWaterArea).where(
                    NavigationWaterArea.is_enabled.is_(True),
                    NavigationWaterArea.geometry_json.is_not(None),
                )
            )
        ).scalars()
    )
    for row in area_rows:
        geometry = _geometry(row.geometry_json)
        if geometry is None:
            continue
        refs.append(
            GeometryRef(
                geometry=geometry,
                source_type_code="WATER_AREA",
                source_id=int(row.id),
                channel_id=None,
                names=tuple(name for name in [row.water_name, row.normalized_water_name] if name),
            )
        )
    body_rows = list(
        (
            await session.execute(
                select(NavigationWaterBody).where(
                    NavigationWaterBody.is_enabled.is_(True),
                    NavigationWaterBody.geometry_wgs84_json.is_not(None),
                )
            )
        ).scalars()
    )
    for row in body_rows:
        geometry = _geometry(row.geometry_wgs84_json)
        if geometry is None:
            continue
        refs.append(
            GeometryRef(
                geometry=geometry,
                source_type_code="WATER_BODY",
                source_id=int(row.id),
                channel_id=None,
                names=tuple(
                    name
                    for name in [
                        row.production_name,
                        row.display_name,
                        row.water_body_name,
                        row.normalized_water_name,
                    ]
                    if name
                ),
            )
        )
    return refs


def _audit_rows(
    rows: list[dict[str, Any]],
    *,
    channels: list[ChannelRef],
    boundaries_by_channel: dict[int, BaseGeometry],
    centerlines_by_channel: dict[int, BaseGeometry],
    graph_edges_by_channel: dict[int, BaseGeometry],
    water_index: GeometryIndex,
    analysis: dict[str, Any],
    graph: NavigationGraphVersion,
    args: argparse.Namespace,
) -> dict[str, Any]:
    boundary_union_cache: dict[tuple[int, ...], BaseGeometry | None] = {}
    centerline_union_cache: dict[tuple[int, ...], BaseGeometry | None] = {}
    graph_union_cache: dict[tuple[int, ...], BaseGeometry | None] = {}
    constraint_by_water = _constraint_summary_by_water(analysis)

    items: list[dict[str, Any]] = []
    repair_candidates: list[dict[str, Any]] = []
    for row in rows:
        item, candidates = _audit_one_row(
            row,
            channels=channels,
            boundaries_by_channel=boundaries_by_channel,
            centerlines_by_channel=centerlines_by_channel,
            graph_edges_by_channel=graph_edges_by_channel,
            water_index=water_index,
            boundary_union_cache=boundary_union_cache,
            centerline_union_cache=centerline_union_cache,
            graph_union_cache=graph_union_cache,
            args=args,
        )
        items.append(item)
        repair_candidates.extend(candidates)

    return {
        "report_version": "WAYBILL_CURRENT_GRAPH_BOUNDARY_AUDIT_V1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_jsonl": str(args.jsonl),
        "source_analysis_report": str(args.analysis_report),
        "graph_version": {
            "id": int(graph.id),
            "version_code": graph.version_code,
            "status_code": graph.status_code,
            "is_active": bool(graph.is_active),
            "node_count": int(graph.node_count or 0),
            "edge_count": int(graph.edge_count or 0),
        },
        "args": {
            "limit": int(args.limit),
            "boundary_tolerance_m": float(args.boundary_tolerance_m),
            "centerline_tolerance_m": float(args.centerline_tolerance_m),
            "graph_tolerance_m": float(args.graph_tolerance_m),
            "water_tolerance_m": float(args.water_tolerance_m),
            "min_boundary_coverage": float(args.min_boundary_coverage),
            "min_graph_coverage": float(args.min_graph_coverage),
            "min_local_water_coverage": float(args.min_local_water_coverage),
            "min_candidate_segment_km": float(args.min_candidate_segment_km),
            "repair_buffer_m": float(args.repair_buffer_m),
        },
        "summary": _summary(items, repair_candidates),
        "water_system_summary": _water_system_summary(items, repair_candidates, constraint_by_water),
        "top_repair_candidates": _top_candidates(repair_candidates, limit=80),
        "items": items,
        "repair_candidates": repair_candidates,
        "usage_policy": {
            "route_generation": (
                "Use geometry-grade waybill tracks as reference/evaluation targets only. A generated route can be "
                "accepted when it is graph-backed and stays inside validated channel/water boundaries; raw waybill "
                "geometry remains REFERENCE_ONLY."
            ),
            "boundary_repair": (
                "Boundary expansion candidates require a geometry-grade track, matched channel label, local water "
                "coverage, and an uncovered segment outside the current boundary."
            ),
            "seed_centerline": (
                "Graph/centerline seed candidates require the current boundary to already cover the waterway; if the "
                "boundary is also missing, boundary repair must run first."
            ),
            "condition_rules": (
                "Condition-only rows update observed cargo, tonnage, ship width, and ship length evidence, but do not "
                "create centerline geometry."
            ),
            "missing_water_names": (
                "Unmatched water labels produce missing-channel or alias-backfill candidates. Multi-water-system "
                "routes must be split before publishing seed."
            ),
        },
    }


def _audit_one_row(
    row: dict[str, Any],
    *,
    channels: list[ChannelRef],
    boundaries_by_channel: dict[int, BaseGeometry],
    centerlines_by_channel: dict[int, BaseGeometry],
    graph_edges_by_channel: dict[int, BaseGeometry],
    water_index: GeometryIndex,
    boundary_union_cache: dict[tuple[int, ...], BaseGeometry | None],
    centerline_union_cache: dict[tuple[int, ...], BaseGeometry | None],
    graph_union_cache: dict[tuple[int, ...], BaseGeometry | None],
    args: argparse.Namespace,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    line = _line(row.get("geometry_json"))
    if line is None:
        raise ValueError("geometry row without line")
    water_systems = [str(item).strip() for item in row.get("water_systems") or [] if str(item).strip()]
    route_label_matched_channels = _match_channels(water_systems, channels)
    local_water_coverage, water_names = _local_water_coverage(line, water_index, tolerance_m=float(args.water_tolerance_m))
    local_water_matched_channels = _match_channels(water_names, channels)
    matched_by_id = {
        channel.id: channel
        for channel in [*route_label_matched_channels, *local_water_matched_channels]
    }
    matched_channels = [matched_by_id[key] for key in sorted(matched_by_id)]
    channel_ids = tuple(sorted({channel.id for channel in matched_channels}))
    boundary_geometry = _union_for_channels(channel_ids, boundaries_by_channel, boundary_union_cache)
    centerline_geometry = _union_for_channels(channel_ids, centerlines_by_channel, centerline_union_cache)
    graph_geometry = _union_for_channels(channel_ids, graph_edges_by_channel, graph_union_cache)

    boundary_coverage = _coverage_ratio(line, boundary_geometry, tolerance_m=float(args.boundary_tolerance_m))
    centerline_coverage = _coverage_ratio(line, centerline_geometry, tolerance_m=float(args.centerline_tolerance_m))
    graph_coverage = _coverage_ratio(line, graph_geometry, tolerance_m=float(args.graph_tolerance_m))

    boundary_gaps = _uncovered_segments(line, boundary_geometry, tolerance_m=float(args.boundary_tolerance_m))
    graph_gaps = _uncovered_segments(line, graph_geometry, tolerance_m=float(args.graph_tolerance_m))
    boundary_gap_km = round(sum(_line_length_km(segment) for segment in boundary_gaps), 3)
    graph_gap_km = round(sum(_line_length_km(segment) for segment in graph_gaps), 3)
    status, issues = _status(
        water_systems=water_systems,
        matched_channel_ids=channel_ids,
        boundary_coverage=boundary_coverage,
        graph_coverage=graph_coverage,
        local_water_coverage=local_water_coverage,
        args=args,
    )
    item = {
        "row_no": row.get("row_no"),
        "waybill_code": row.get("waybill_code"),
        "route_code": row.get("route_code"),
        "route_name": row.get("route_name"),
        "origin": row.get("origin"),
        "destination": row.get("destination"),
        "water_systems": water_systems,
        "matched_channels": [_channel_payload(channel) for channel in matched_channels],
        "route_label_matched_channels": [_channel_payload(channel) for channel in route_label_matched_channels],
        "local_water_matched_channels": [_channel_payload(channel) for channel in local_water_matched_channels],
        "audit_status_code": status,
        "issue_codes": issues,
        "track_length_km": round(_line_length_km(line), 3),
        "declared_distance_km": row.get("declared_distance_km"),
        "quality_score": row.get("quality_score"),
        "boundary_coverage_ratio": round(boundary_coverage, 6),
        "centerline_coverage_ratio": round(centerline_coverage, 6),
        "graph_coverage_ratio": round(graph_coverage, 6),
        "local_water_coverage_ratio": round(local_water_coverage, 6),
        "boundary_gap_km": boundary_gap_km,
        "graph_gap_km": graph_gap_km,
        "local_water_names": water_names[:20],
        "observed_constraints": {
            "tonnage_max": row.get("tonnage_max"),
            "ship_width_max_m": row.get("ship_width_max_m"),
            "ship_length_max_m": row.get("ship_length_max_m"),
            "cargo_codes": row.get("cargo_codes") or [],
        },
    }
    candidates = _repair_candidates_for_row(
        row,
        line=line,
        item=item,
        boundary_gaps=boundary_gaps,
        graph_gaps=graph_gaps,
        args=args,
    )
    return item, candidates


def _status(
    *,
    water_systems: list[str],
    matched_channel_ids: tuple[int, ...],
    boundary_coverage: float,
    graph_coverage: float,
    local_water_coverage: float,
    args: argparse.Namespace,
) -> tuple[str, list[str]]:
    issues: list[str] = []
    if not matched_channel_ids:
        issues.append("UNMATCHED_WATER_SYSTEM_LABEL")
        return "MISSING_CHANNEL_OR_ALIAS_BACKFILL_CANDIDATE", issues
    if len(water_systems) > 1 and len(matched_channel_ids) > 1:
        issues.append("MULTI_WATER_SYSTEM_ROUTE_NEEDS_SEGMENT_SPLIT")
    if local_water_coverage < float(args.min_local_water_coverage):
        issues.append("LOW_LOCAL_WATER_COVERAGE")
    if boundary_coverage < float(args.min_boundary_coverage):
        issues.append("TRACK_OUTSIDE_CURRENT_CHANNEL_BOUNDARY")
        if local_water_coverage >= float(args.min_local_water_coverage):
            return "BOUNDARY_EXPANSION_CANDIDATE", issues
        return "BOUNDARY_GAP_BLOCKED_LOW_WATER_EVIDENCE", issues
    if graph_coverage < float(args.min_graph_coverage):
        issues.append("TRACK_NOT_COVERED_BY_ACTIVE_GRAPH")
        return "SEED_OR_GRAPH_GAP_CANDIDATE", issues
    if issues:
        return "REFERENCE_USABLE_WITH_SPLIT_OR_REVIEW", issues
    return "CURRENT_GRAPH_BOUNDARY_COVERS_REFERENCE", issues


def _repair_candidates_for_row(
    row: dict[str, Any],
    *,
    line: LineString,
    item: dict[str, Any],
    boundary_gaps: list[LineString],
    graph_gaps: list[LineString],
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    min_km = float(args.min_candidate_segment_km)
    if item["audit_status_code"] == "MISSING_CHANNEL_OR_ALIAS_BACKFILL_CANDIDATE":
        candidates.append(_candidate_payload(row, item, "MISSING_CHANNEL_OR_ALIAS_BACKFILL", line, args=args))
        return candidates
    if item["audit_status_code"] == "BOUNDARY_EXPANSION_CANDIDATE":
        for segment in boundary_gaps:
            if _line_length_km(segment) >= min_km:
                candidates.append(_candidate_payload(row, item, "BOUNDARY_EXPANSION", segment, args=args))
    if item["audit_status_code"] == "SEED_OR_GRAPH_GAP_CANDIDATE":
        for segment in graph_gaps:
            if _line_length_km(segment) >= min_km:
                candidates.append(_candidate_payload(row, item, "CENTERLINE_OR_GRAPH_SEED", segment, args=args))
    return candidates


def _candidate_payload(
    row: dict[str, Any],
    item: dict[str, Any],
    candidate_type_code: str,
    geometry: LineString,
    *,
    args: argparse.Namespace,
) -> dict[str, Any]:
    payload = {
        "candidate_type_code": candidate_type_code,
        "candidate_status_code": _candidate_status(candidate_type_code, item),
        "waybill_code": row.get("waybill_code"),
        "route_code": row.get("route_code"),
        "route_name": row.get("route_name"),
        "row_no": row.get("row_no"),
        "origin": row.get("origin"),
        "destination": row.get("destination"),
        "water_systems": item.get("water_systems") or [],
        "matched_channels": item.get("matched_channels") or [],
        "local_water_names": item.get("local_water_names") or [],
        "segment_length_km": round(_line_length_km(geometry), 3),
        "audit_status_code": item.get("audit_status_code"),
        "issue_codes": item.get("issue_codes") or [],
        "boundary_coverage_ratio": item.get("boundary_coverage_ratio"),
        "centerline_coverage_ratio": item.get("centerline_coverage_ratio"),
        "graph_coverage_ratio": item.get("graph_coverage_ratio"),
        "local_water_coverage_ratio": item.get("local_water_coverage_ratio"),
        "observed_constraints": item.get("observed_constraints") or {},
        "geometry_json": mapping(geometry),
    }
    if candidate_type_code == "BOUNDARY_EXPANSION":
        payload["buffer_geometry_json"] = mapping(
            geometry.buffer(_degree_buffer(float(args.repair_buffer_m)), cap_style=2, join_style=2)
        )
        payload["repair_rule"] = "UNION_CURRENT_BOUNDARY_WITH_WATER_BACKED_WAYBILL_CORRIDOR_BEFORE_GRAPH_REBUILD"
    elif candidate_type_code == "CENTERLINE_OR_GRAPH_SEED":
        payload["repair_rule"] = "CREATE_OR_EXTEND_CENTERLINE_SEED_INSIDE_VALIDATED_BOUNDARY_THEN_REBUILD_GRAPH"
    else:
        payload["repair_rule"] = "BACKFILL_CHANNEL_ALIAS_OR_CREATE_MISSING_WATER_SYSTEM_AFTER_SEGMENT_SPLIT"
    return payload


def _candidate_status(candidate_type_code: str, item: dict[str, Any]) -> str:
    issues = set(item.get("issue_codes") or [])
    if "MULTI_WATER_SYSTEM_ROUTE_NEEDS_SEGMENT_SPLIT" in issues:
        return "NEEDS_SEGMENT_LEVEL_SPLIT"
    if "LOW_LOCAL_WATER_COVERAGE" in issues:
        return "BLOCKED_LOW_LOCAL_WATER_EVIDENCE"
    if candidate_type_code == "BOUNDARY_EXPANSION":
        return "AUTO_BOUNDARY_REPAIR_CANDIDATE"
    if candidate_type_code == "CENTERLINE_OR_GRAPH_SEED":
        return "AUTO_SEED_REPAIR_CANDIDATE"
    return "MISSING_CHANNEL_OR_ALIAS_CANDIDATE"


def _match_channels(water_systems: list[str], channels: list[ChannelRef]) -> list[ChannelRef]:
    matches: dict[int, ChannelRef] = {}
    for water_name in water_systems:
        for channel in channels:
            if any(_name_matches(water_name, channel_name) for channel_name in channel.names):
                matches[channel.id] = channel
    return [matches[key] for key in sorted(matches)]


def _union_for_channels(
    channel_ids: tuple[int, ...],
    geometries_by_channel: dict[int, BaseGeometry],
    cache: dict[tuple[int, ...], BaseGeometry | None],
) -> BaseGeometry | None:
    if channel_ids in cache:
        return cache[channel_ids]
    geoms = [geometries_by_channel[channel_id] for channel_id in channel_ids if channel_id in geometries_by_channel]
    cache[channel_ids] = make_valid(unary_union(geoms)) if geoms else None
    return cache[channel_ids]


def _local_water_coverage(line: LineString, water_index: GeometryIndex, *, tolerance_m: float) -> tuple[float, list[str]]:
    query_geometry = line.buffer(_degree_buffer(tolerance_m), cap_style=2, join_style=2)
    refs = water_index.query(query_geometry)
    covered_parts: list[LineString] = []
    name_counter: Counter[str] = Counter()
    for ref in refs:
        if not ref.geometry.intersects(query_geometry):
            continue
        try:
            clipped = line.intersection(ref.geometry.buffer(_degree_buffer(tolerance_m), cap_style=2, join_style=2))
        except Exception:
            continue
        covered_parts.extend(_extract_lines(clipped))
        for name in ref.names:
            usable = _usable_name(name)
            if usable:
                name_counter[usable] += 1
    if not covered_parts:
        return 0.0, []
    try:
        covered = unary_union(covered_parts).length
    except Exception:
        covered = sum(part.length for part in covered_parts)
    ratio = max(0.0, min(1.0, covered / max(line.length, 1e-12)))
    return ratio, [name for name, _ in name_counter.most_common(20)]


def _uncovered_segments(line: LineString, cover_geometry: BaseGeometry | None, *, tolerance_m: float) -> list[LineString]:
    if cover_geometry is None or cover_geometry.is_empty:
        return [line]
    try:
        diff = line.difference(cover_geometry.buffer(_degree_buffer(tolerance_m), cap_style=2, join_style=2))
    except Exception:
        return [line]
    return _extract_lines(diff)


def _extract_lines(geometry: BaseGeometry) -> list[LineString]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry] if len(geometry.coords) >= 2 else []
    if isinstance(geometry, MultiLineString):
        return [line for line in geometry.geoms if len(line.coords) >= 2]
    if isinstance(geometry, GeometryCollection):
        lines: list[LineString] = []
        for part in geometry.geoms:
            lines.extend(_extract_lines(part))
        return lines
    return []


def _summary(items: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = Counter(item.get("audit_status_code") for item in items)
    issues = Counter(code for item in items for code in item.get("issue_codes") or [])
    candidate_types = Counter(item.get("candidate_type_code") for item in candidates)
    return {
        "geometry_reference_audited_count": len(items),
        "status_counts": dict(sorted(statuses.items())),
        "issue_counts": dict(sorted(issues.items())),
        "repair_candidate_count": len(candidates),
        "repair_candidate_type_counts": dict(sorted(candidate_types.items())),
        "repair_candidate_length_km_by_type": {
            key: round(sum(float(item.get("segment_length_km") or 0) for item in candidates if item.get("candidate_type_code") == key), 3)
            for key in sorted(candidate_types)
        },
        "avg_boundary_coverage_ratio": _avg(item.get("boundary_coverage_ratio") for item in items),
        "avg_centerline_coverage_ratio": _avg(item.get("centerline_coverage_ratio") for item in items),
        "avg_graph_coverage_ratio": _avg(item.get("graph_coverage_ratio") for item in items),
        "avg_local_water_coverage_ratio": _avg(item.get("local_water_coverage_ratio") for item in items),
        "total_boundary_gap_km": round(sum(float(item.get("boundary_gap_km") or 0) for item in items), 3),
        "total_graph_gap_km": round(sum(float(item.get("graph_gap_km") or 0) for item in items), 3),
    }


def _water_system_summary(
    items: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    constraint_by_water: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for item in items:
        for water_name in item.get("water_systems") or ["-"]:
            group = groups.setdefault(
                water_name,
                {
                    "water_system_name": water_name,
                    "geometry_reference_count": 0,
                    "status_counts": Counter(),
                    "issue_counts": Counter(),
                    "boundary_coverages": [],
                    "graph_coverages": [],
                    "local_water_coverages": [],
                    "boundary_gap_km": 0.0,
                    "graph_gap_km": 0.0,
                },
            )
            group["geometry_reference_count"] += 1
            group["status_counts"].update([item.get("audit_status_code")])
            group["issue_counts"].update(item.get("issue_codes") or [])
            group["boundary_coverages"].append(item.get("boundary_coverage_ratio"))
            group["graph_coverages"].append(item.get("graph_coverage_ratio"))
            group["local_water_coverages"].append(item.get("local_water_coverage_ratio"))
            group["boundary_gap_km"] += float(item.get("boundary_gap_km") or 0)
            group["graph_gap_km"] += float(item.get("graph_gap_km") or 0)
    candidate_counter: dict[str, Counter[str]] = defaultdict(Counter)
    candidate_length: dict[tuple[str, str], float] = defaultdict(float)
    for candidate in candidates:
        for water_name in candidate.get("water_systems") or ["-"]:
            candidate_type = str(candidate.get("candidate_type_code") or "-")
            candidate_counter[water_name].update([candidate_type])
            candidate_length[(water_name, candidate_type)] += float(candidate.get("segment_length_km") or 0)
    output: list[dict[str, Any]] = []
    for water_name, group in groups.items():
        type_counts = candidate_counter.get(water_name, Counter())
        output.append(
            {
                "water_system_name": water_name,
                "geometry_reference_count": group["geometry_reference_count"],
                "status_counts": dict(sorted(group["status_counts"].items())),
                "issue_counts": dict(sorted(group["issue_counts"].items())),
                "repair_candidate_type_counts": dict(sorted(type_counts.items())),
                "repair_candidate_length_km_by_type": {
                    key: round(candidate_length[(water_name, key)], 3) for key in sorted(type_counts)
                },
                "avg_boundary_coverage_ratio": _avg(group["boundary_coverages"]),
                "avg_graph_coverage_ratio": _avg(group["graph_coverages"]),
                "avg_local_water_coverage_ratio": _avg(group["local_water_coverages"]),
                "boundary_gap_km": round(group["boundary_gap_km"], 3),
                "graph_gap_km": round(group["graph_gap_km"], 3),
                "observed_condition_constraints": constraint_by_water.get(water_name),
            }
        )
    output.sort(
        key=lambda item: (
            sum(item.get("repair_candidate_type_counts", {}).values()),
            item.get("boundary_gap_km") or 0,
            item.get("graph_gap_km") or 0,
        ),
        reverse=True,
    )
    return output


def _top_candidates(candidates: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    rows = sorted(
        candidates,
        key=lambda item: (float(item.get("segment_length_km") or 0), str(item.get("candidate_type_code") or "")),
        reverse=True,
    )[:limit]
    return [{key: value for key, value in row.items() if key not in {"geometry_json", "buffer_geometry_json"}} for row in rows]


def _constraint_summary_by_water(analysis: dict[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for item in analysis.get("condition_constraints_by_water_system") or []:
        water_name = str(item.get("water_system_name") or "").strip()
        if not water_name:
            continue
        output[water_name] = {
            "condition_reference_count": item.get("condition_reference_count"),
            "geometry_reference_count": item.get("geometry_reference_count"),
            "od_count": item.get("od_count"),
            "route_count": item.get("route_count"),
            "observed_max_tonnage": item.get("observed_max_tonnage"),
            "observed_max_ship_width_m": item.get("observed_max_ship_width_m"),
            "observed_max_ship_length_m": item.get("observed_max_ship_length_m"),
            "source_policy_code": item.get("source_policy_code"),
        }
    return output


def _write_outputs(audit: dict[str, Any], args: argparse.Namespace) -> None:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {key: value for key, value in audit.items() if key != "repair_candidates"}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.candidate_jsonl_output.parent.mkdir(parents=True, exist_ok=True)
    with args.candidate_jsonl_output.open("w", encoding="utf-8") as handle:
        for candidate in audit["repair_candidates"]:
            handle.write(json.dumps(candidate, ensure_ascii=False, separators=(",", ":")) + "\n")
    if args.geojson_output:
        args.geojson_output.parent.mkdir(parents=True, exist_ok=True)
        args.geojson_output.write_text(
            json.dumps(_geojson(audit["repair_candidates"], limit=max(0, int(args.geojson_limit))), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )


def _geojson(candidates: list[dict[str, Any]], *, limit: int) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    selected = sorted(candidates, key=lambda item: float(item.get("segment_length_km") or 0), reverse=True)
    if limit:
        selected = selected[:limit]
    for candidate in selected:
        props = {
            key: value
            for key, value in candidate.items()
            if key not in {"geometry_json", "buffer_geometry_json", "origin", "destination", "observed_constraints"}
        }
        geometry = candidate.get("geometry_json")
        if isinstance(geometry, dict):
            features.append({"type": "Feature", "properties": {**props, "feature_role": "candidate_segment"}, "geometry": geometry})
        buffer_geometry = candidate.get("buffer_geometry_json")
        if isinstance(buffer_geometry, dict):
            features.append({"type": "Feature", "properties": {**props, "feature_role": "candidate_buffer"}, "geometry": buffer_geometry})
    return {"type": "FeatureCollection", "features": features}


def _channel_payload(channel: ChannelRef) -> dict[str, Any]:
    return {
        "id": channel.id,
        "channel_code": channel.code,
        "channel_name": channel.name,
        "technical_grade_current_code": channel.technical_grade_current_code,
        "technical_grade_planned_code": channel.technical_grade_planned_code,
    }


def _geometry(value: Any) -> BaseGeometry | None:
    if not isinstance(value, dict):
        return None
    try:
        geometry = make_valid(shape(value))
    except Exception:
        return None
    return None if geometry.is_empty else geometry


def _line(value: Any) -> LineString | None:
    geometry = _geometry(value)
    if isinstance(geometry, LineString) and len(geometry.coords) >= 2:
        return geometry
    return None


def _coverage_ratio(line: LineString, geometry: BaseGeometry | None, *, tolerance_m: float) -> float:
    if geometry is None or geometry.is_empty:
        return 0.0
    try:
        cover = geometry.buffer(_degree_buffer(tolerance_m), cap_style=2, join_style=2)
        covered = line.intersection(cover).length
    except Exception:
        return 0.0
    return max(0.0, min(1.0, covered / max(line.length, 1e-12)))


def _line_length_km(line: LineString) -> float:
    coords = list(line.coords)
    total_m = 0.0
    for start, end in zip(coords[:-1], coords[1:]):
        _, _, distance_m = GEOD.inv(float(start[0]), float(start[1]), float(end[0]), float(end[1]))
        total_m += abs(distance_m)
    return total_m / 1000.0


def _degree_buffer(meters: float) -> float:
    return float(meters) / 111_320.0


def _avg(values: Iterable[Any]) -> float | None:
    parsed = [float(value) for value in values if value is not None]
    if not parsed:
        return None
    return round(sum(parsed) / len(parsed), 6)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _usable_name(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text.startswith("未命名"):
        return None
    return text


def _name_matches(left: str, right: str) -> bool:
    left_variants = _name_variants(left)
    right_variants = _name_variants(right)
    if left_variants & right_variants:
        return True
    for left_item in left_variants:
        for right_item in right_variants:
            if len(left_item) >= 3 and len(right_item) >= 3 and (left_item in right_item or right_item in left_item):
                return True
    return False


def _name_variants(value: str) -> set[str]:
    text = str(value or "").strip()
    if not text:
        return set()
    no_paren = re.sub(r"[（(].*?[）)]", "", text)
    variants = {
        _norm_name(text),
        _norm_name(no_paren),
        _norm_name(text.replace("干流", "")),
        _norm_name(no_paren.replace("干流", "")),
        _norm_name(text.replace("航道", "").replace("水道", "")),
        _norm_name(no_paren.replace("航道", "").replace("水道", "")),
    }
    return {item for item in variants if item}


def _norm_name(value: str) -> str:
    return re.sub(r"[\s,，、·.。:：;；/\\（）()\\[\\]【】{}<>《》\"'“”‘’-]+", "", str(value or "").lower())


if __name__ == "__main__":
    asyncio.run(main())
