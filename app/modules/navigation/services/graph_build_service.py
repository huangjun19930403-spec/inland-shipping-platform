"""Build navigation graph versions from published centerlines.

Round 7 creates graph versions, nodes, edges, and edge constraints. It never
creates route requests/results and never uses polygon or boundary assets as
route geometry.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from pyproj import Geod
from shapely.geometry import LineString, MultiLineString, Point, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import substring
from shapely.strtree import STRtree
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    NavigationChannelCenterline,
    NavigationChannelWaterBodyMatch,
    NavigationCenterlineSegment,
    NavigationGraphEdge,
    NavigationGraphEdgeConstraint,
    NavigationGraphNode,
    NavigationGraphVersion,
)
from app.models.address import (
    NavigationChannel,
    NavigationChannelBoundary,
    NavigationConstraintPoint,
    NavigationConstraintProfile,
    TransportNode,
)
from app.modules.navigation.production_pipeline.boundary_quality_audit import vessel_limit_profile
from app.modules.navigation.service import NavigationCenterlineService
from app.modules.navigation.services.graph_validation_service import validate_navigation_graph

GEOD = Geod(ellps="WGS84")
PROTECTED_NODE_TYPES = {"LOCK", "BRIDGE", "PORT", "TERMINAL", "ANCHORAGE", "CHANNEL_JUNCTION", "CONSTRAINT"}
NODE_TYPE_PRIORITY = {
    "CENTERLINE_VERTEX": 0,
    "SNAP_CONNECTOR": 1,
    "CHANNEL_JUNCTION": 2,
    "BRIDGE": 3,
    "CONSTRAINT": 3,
    "LOCK": 4,
    "PORT": 5,
    "TERMINAL": 5,
    "ANCHORAGE": 5,
}
LOCK_TYPES = {"LOCK", "SHIP_LOCK", "船闸"}
BRIDGE_TYPES = {"BRIDGE", "BRIDGE_CLEARANCE", "桥梁"}


@dataclass(slots=True)
class GraphBuildConfig:
    endpoint_auto_snap_m: float = 20.0
    endpoint_review_snap_m: float = 80.0
    transport_auto_snap_m: float = 200.0
    transport_review_snap_m: float = 500.0
    constraint_snap_m: float = 100.0
    short_edge_merge_m: float = 20.0
    short_edge_review_m: float = 50.0
    bbox_margin_degree: float = 0.02
    boundary_tolerance_degree: float = 0.0002

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class GraphBuildIssue:
    issue_code: str
    severity_code: str
    message: str
    centerline_id: int | None = None
    channel_id: int | None = None
    node_code: str | None = None
    edge_code: str | None = None
    distance_m: float | None = None


@dataclass(slots=True)
class GraphBuildSummary:
    version_code: str
    graph_version_id: int | None
    status_code: str
    node_count: int
    edge_count: int
    channel_count: int
    quality_score: int | None
    centerline_count: int
    connector_edge_count: int
    constraint_count: int
    issues: list[GraphBuildIssue] = field(default_factory=list)
    validation_report: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["issues"] = [asdict(issue) for issue in self.issues]
        return payload


@dataclass(slots=True)
class CenterlineAsset:
    asset_id: int
    row: NavigationChannelCenterline
    geometry: LineString
    segment_id: int | None = None
    boundary_validation_required: bool = True


@dataclass(slots=True)
class SplitPointSpec:
    point: Point
    node_type_code: str = "CENTERLINE_VERTEX"
    source_type_code: str = "CENTERLINE_VERTEX"
    related_transport_node_id: int | None = None
    related_constraint_point_id: int | None = None
    snap_distance_m: float | None = None
    snap_confidence: int | None = None
    is_endpoint: bool = False


@dataclass(slots=True)
class ConnectorSpec:
    from_node: NavigationGraphNode
    to_node: NavigationGraphNode
    channel_id: int | None
    geometry: LineString
    source_type_code: str
    quality_code: str
    routing_enabled: bool
    snap_distance_m: float
    issue_codes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CrossChannelConnectorSpec:
    left: CenterlineAsset
    right: CenterlineAsset
    left_point: Point
    right_point: Point
    distance_m: float
    source_type_code: str


def _clean_code(value: str, max_len: int = 64) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_-]+", "-", value).strip("-")
    return (cleaned or "GRAPH")[:max_len]


def _point_key(point: Point) -> tuple[int, int]:
    return (round(point.x, 8), round(point.y, 8))


def _point_distance_m(a: Point, b: Point) -> float:
    _, _, distance_m = GEOD.inv(a.x, a.y, b.x, b.y)
    return abs(float(distance_m))


def _line_length_km(line: LineString) -> float:
    if line.is_empty or len(line.coords) < 2:
        return 0.0
    lons = [float(coord[0]) for coord in line.coords]
    lats = [float(coord[1]) for coord in line.coords]
    return abs(float(GEOD.line_length(lons, lats))) / 1000.0


def _round_float(value: float | None, digits: int) -> float | None:
    return None if value is None else round(float(value), digits)


def _nearest_point_on_line(line: LineString, point: Point) -> Point:
    return line.interpolate(line.project(point))


def _intersection_points(geometry: BaseGeometry) -> list[Point]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, Point):
        return [geometry]
    if geometry.geom_type == "MultiPoint":
        return list(geometry.geoms)
    if isinstance(geometry, LineString):
        coords = list(geometry.coords)
        return [Point(coords[0]), Point(coords[-1])] if len(coords) >= 2 else []
    if isinstance(geometry, MultiLineString):
        points: list[Point] = []
        for line in geometry.geoms:
            coords = list(line.coords)
            if len(coords) >= 2:
                points.extend([Point(coords[0]), Point(coords[-1])])
        return points
    if geometry.geom_type == "GeometryCollection":
        points: list[Point] = []
        for part in geometry.geoms:
            points.extend(_intersection_points(part))
        return points
    return []


def _node_kind_for_transport(node: TransportNode) -> str:
    value = (node.node_type_code or "").upper()
    if "ANCHOR" in value or "锚" in value:
        return "ANCHORAGE"
    if "TERMINAL" in value or "码头" in value:
        return "TERMINAL"
    return "PORT"


def _node_kind_for_constraint(point: NavigationConstraintPoint) -> str:
    value = (point.constraint_type_code or "").upper()
    if value in LOCK_TYPES:
        return "LOCK"
    if value in BRIDGE_TYPES:
        return "BRIDGE"
    return "CONSTRAINT"


def _constraint_type_for_node(node_type_code: str) -> str:
    if node_type_code == "LOCK":
        return "LOCK_SCHEDULE"
    if node_type_code == "BRIDGE":
        return "AIR_DRAFT_LIMIT"
    return "UNKNOWN_CONSTRAINT_DATA"


def _constraint_complete(node_type_code: str, profile: NavigationConstraintProfile | None) -> bool:
    if profile is None:
        return False
    if node_type_code == "LOCK":
        return any(
            value is not None
            for value in (
                profile.max_tonnage,
                profile.max_allowed_draft_m,
                profile.max_beam_m,
                profile.max_length_m,
            )
        )
    if node_type_code == "BRIDGE":
        return profile.max_air_draft_m is not None
    return bool(profile.restriction_rule_json)


def _source_summary(centerlines: list[CenterlineAsset]) -> dict[str, Any]:
    by_source: dict[str, int] = defaultdict(int)
    channel_ids: set[int] = set()
    centerline_ids: list[int] = []
    centerline_segment_ids: list[int] = []
    source_boundary_ids: set[int] = set()
    for item in centerlines:
        by_source[item.row.source_type_code] += 1
        channel_ids.add(item.row.channel_id)
        centerline_ids.append(item.row.id)
        if item.segment_id is not None:
            centerline_segment_ids.append(item.segment_id)
        trace = item.row.source_trace_json if isinstance(item.row.source_trace_json, dict) else {}
        boundary_id = trace.get("source_boundary_id") or trace.get("based_on_boundary_id")
        if isinstance(boundary_id, int):
            source_boundary_ids.add(boundary_id)
        elif isinstance(boundary_id, str) and boundary_id.isdigit():
            source_boundary_ids.add(int(boundary_id))
    return {
        "centerline_count": len(centerlines),
        "centerline_ids": sorted(set(centerline_ids)),
        "centerline_segment_ids": sorted(centerline_segment_ids),
        "source_segment_topology_preserved": bool(centerline_segment_ids),
        "channel_ids": sorted(channel_ids),
        "source_boundary_ids": sorted(source_boundary_ids),
        "source_type_counts": dict(sorted(by_source.items())),
    }


def _bbox_from_centerlines(centerlines: list[CenterlineAsset]) -> dict[str, float] | None:
    if not centerlines:
        return None
    min_lng = min(item.geometry.bounds[0] for item in centerlines)
    min_lat = min(item.geometry.bounds[1] for item in centerlines)
    max_lng = max(item.geometry.bounds[2] for item in centerlines)
    max_lat = max(item.geometry.bounds[3] for item in centerlines)
    return {"min_lng": min_lng, "min_lat": min_lat, "max_lng": max_lng, "max_lat": max_lat}


def _bbox_with_margin(bbox: dict[str, float], margin_degree: float) -> dict[str, float]:
    return {
        "min_lng": bbox["min_lng"] - margin_degree,
        "min_lat": bbox["min_lat"] - margin_degree,
        "max_lng": bbox["max_lng"] + margin_degree,
        "max_lat": bbox["max_lat"] + margin_degree,
    }


def _bounds_tuple_with_margin(bounds: tuple[float, float, float, float], margin_degree: float) -> tuple[float, float, float, float]:
    return (bounds[0] - margin_degree, bounds[1] - margin_degree, bounds[2] + margin_degree, bounds[3] + margin_degree)


def _bounds_intersect(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> bool:
    return not (left[2] < right[0] or right[2] < left[0] or left[3] < right[1] or right[3] < left[1])


def _append_cross_channel_junctions(
    centerlines: list[CenterlineAsset],
    boundaries: dict[int, BaseGeometry],
    water_body_ids_by_channel: dict[int, set[int]],
    split_points: dict[int, list[SplitPointSpec]],
    issues: list[GraphBuildIssue],
    config: GraphBuildConfig,
) -> list[CrossChannelConnectorSpec]:
    if len(centerlines) <= 1:
        return []
    connector_specs: list[CrossChannelConnectorSpec] = []
    geometries = [asset.geometry for asset in centerlines]
    tree = STRtree(geometries)
    endpoint_margin_degree = max(config.endpoint_review_snap_m / 90_000.0, config.boundary_tolerance_degree)
    for left_index, left in enumerate(centerlines):
        for right_index_raw in tree.query(left.geometry.buffer(endpoint_margin_degree)):
            right_index = int(right_index_raw)
            if right_index <= left_index:
                continue
            right = centerlines[right_index]
            if left.row.channel_id == right.row.channel_id:
                continue
            if not _bounds_intersect(_bounds_tuple_with_margin(left.geometry.bounds, endpoint_margin_degree), right.geometry.bounds):
                continue
            intersection = left.geometry.intersection(right.geometry)
            if not intersection.is_empty:
                points = _intersection_points(intersection)
                navigable_points = [
                    (point, source_type_code)
                    for point in points
                    if (
                        source_type_code := _cross_channel_intersection_source_type(
                            point=point,
                            left=left,
                            right=right,
                            boundaries=boundaries,
                            water_body_ids_by_channel=water_body_ids_by_channel,
                            config=config,
                        )
                    )
                ]
                if navigable_points:
                    for point, source_type_code in navigable_points:
                        split_points[left.asset_id].append(
                            SplitPointSpec(
                                point=point,
                                node_type_code="CHANNEL_JUNCTION",
                                source_type_code=source_type_code,
                            )
                        )
                        split_points[right.asset_id].append(
                            SplitPointSpec(
                                point=point,
                                node_type_code="CHANNEL_JUNCTION",
                                source_type_code=source_type_code,
                            )
                        )
                    continue
                issues.append(
                    GraphBuildIssue(
                        "CROSSING_NOT_NAVIGABLE",
                        "WARNING",
                        "Centerlines intersect across different channels and were not connected",
                        centerline_id=left.row.id,
                        channel_id=left.row.channel_id,
                    )
                )
                continue
            connector = _near_cross_channel_confluence_connector(
                left=left,
                right=right,
                boundaries=boundaries,
                config=config,
            )
            if connector is None:
                continue
            split_points[left.asset_id].append(
                SplitPointSpec(
                    point=connector.left_point,
                    node_type_code="CHANNEL_JUNCTION",
                    source_type_code=connector.source_type_code,
                )
            )
            split_points[right.asset_id].append(
                SplitPointSpec(
                    point=connector.right_point,
                    node_type_code="CHANNEL_JUNCTION",
                    source_type_code=connector.source_type_code,
                )
            )
            connector_specs.append(connector)
    return connector_specs


def _near_cross_channel_confluence_connector(
    *,
    left: CenterlineAsset,
    right: CenterlineAsset,
    boundaries: dict[int, BaseGeometry],
    config: GraphBuildConfig,
) -> CrossChannelConnectorSpec | None:
    left_boundary = boundaries.get(int(left.row.channel_id))
    right_boundary = boundaries.get(int(right.row.channel_id))
    if left_boundary is None or right_boundary is None:
        return None
    candidates: list[tuple[float, Point, Point]] = []
    for point in _line_endpoints(left.geometry):
        right_point = _nearest_point_on_line(right.geometry, point)
        candidates.append((_point_distance_m(point, right_point), point, right_point))
    for point in _line_endpoints(right.geometry):
        left_point = _nearest_point_on_line(left.geometry, point)
        candidates.append((_point_distance_m(left_point, point), left_point, point))
    if not candidates:
        return None
    distance_m, left_point, right_point = min(candidates, key=lambda item: item[0])
    if distance_m > config.endpoint_review_snap_m:
        return None
    tolerance = config.boundary_tolerance_degree
    connector = LineString([(left_point.x, left_point.y), (right_point.x, right_point.y)])
    if not left_boundary.buffer(tolerance).covers(left_point):
        return None
    if not right_boundary.buffer(tolerance).covers(right_point):
        return None
    if not left_boundary.union(right_boundary).buffer(tolerance).covers(connector):
        return None
    return CrossChannelConnectorSpec(
        left=left,
        right=right,
        left_point=left_point,
        right_point=right_point,
        distance_m=distance_m,
        source_type_code="CROSS_CHANNEL_BOUNDARY_CONFLUENCE_CONNECTOR",
    )


def _line_endpoints(line: LineString) -> list[Point]:
    coords = list(line.coords)
    if len(coords) < 2:
        return []
    return [Point(coords[0]), Point(coords[-1])]


def _cross_channel_intersection_source_type(
    *,
    point: Point,
    left: CenterlineAsset,
    right: CenterlineAsset,
    boundaries: dict[int, BaseGeometry],
    water_body_ids_by_channel: dict[int, set[int]],
    config: GraphBuildConfig,
) -> str | None:
    left_channel_id = int(left.row.channel_id)
    right_channel_id = int(right.row.channel_id)
    left_boundary = boundaries.get(left_channel_id)
    right_boundary = boundaries.get(right_channel_id)
    if left_boundary is None or right_boundary is None:
        return None
    tolerance = config.boundary_tolerance_degree
    if not (left_boundary.buffer(tolerance).covers(point) and right_boundary.buffer(tolerance).covers(point)):
        return None

    shared_water_body_ids = water_body_ids_by_channel.get(left_channel_id, set()).intersection(
        water_body_ids_by_channel.get(right_channel_id, set())
    )
    if shared_water_body_ids:
        return "CROSS_CHANNEL_WATER_JUNCTION"

    left_endpoint_near = _point_near_centerline_endpoint(point, left.geometry, config.endpoint_review_snap_m)
    right_endpoint_near = _point_near_centerline_endpoint(point, right.geometry, config.endpoint_review_snap_m)
    if left_endpoint_near or right_endpoint_near:
        return "CROSS_CHANNEL_BOUNDARY_CONFLUENCE"
    return None


def _point_near_centerline_endpoint(point: Point, line: LineString, max_distance_m: float) -> bool:
    coords = list(line.coords)
    if len(coords) < 2:
        return False
    return min(_point_distance_m(point, Point(coords[0])), _point_distance_m(point, Point(coords[-1]))) <= max_distance_m


def _cross_channel_intersection_is_navigable(
    *,
    point: Point,
    left: CenterlineAsset,
    right: CenterlineAsset,
    boundaries: dict[int, BaseGeometry],
    water_body_ids_by_channel: dict[int, set[int]],
    config: GraphBuildConfig,
) -> bool:
    return (
        _cross_channel_intersection_source_type(
            point=point,
            left=left,
            right=right,
            boundaries=boundaries,
            water_body_ids_by_channel=water_body_ids_by_channel,
            config=config,
        )
        is not None
    )


async def _load_channel_water_body_ids(session: AsyncSession, channel_ids: set[int]) -> dict[int, set[int]]:
    if not channel_ids:
        return {}
    rows = list(
        (
            await session.execute(
                select(NavigationChannelWaterBodyMatch).where(
                    NavigationChannelWaterBodyMatch.channel_id.in_(channel_ids),
                    NavigationChannelWaterBodyMatch.is_current.is_(True),
                )
            )
        ).scalars()
    )
    output: dict[int, set[int]] = defaultdict(set)
    for row in rows:
        output[int(row.channel_id)].add(int(row.water_body_id))
    return output


async def _load_centerline_assets(
    session: AsyncSession,
    *,
    channel_codes: list[str] | None,
) -> tuple[list[CenterlineAsset], list[GraphBuildIssue]]:
    rows = await NavigationCenterlineService(session).list_graph_ready_centerlines(channel_codes=channel_codes)
    assets: list[CenterlineAsset] = []
    issues: list[GraphBuildIssue] = []
    for row in rows:
        trace = row.source_trace_json if isinstance(row.source_trace_json, dict) else {}
        segment_ids = [
            int(item)
            for item in (trace.get("segment_ids") or [])
            if isinstance(item, int) or (isinstance(item, str) and item.isdigit())
        ]
        segment_assets = await _load_segment_assets(session, row, segment_ids)
        if segment_assets:
            assets.extend(segment_assets)
            continue
        geometry = shape(row.geometry_json)
        if not isinstance(geometry, LineString) or geometry.is_empty or len(geometry.coords) < 2:
            issues.append(
                GraphBuildIssue(
                    "CENTERLINE_BROKEN",
                    "BLOCKING",
                    f"Centerline {row.centerline_code} is not a valid LineString",
                    centerline_id=row.id,
                    channel_id=row.channel_id,
                )
            )
            continue
        assets.append(CenterlineAsset(asset_id=int(row.id), row=row, geometry=geometry))
    return assets, issues


async def _load_segment_assets(
    session: AsyncSession,
    centerline: NavigationChannelCenterline,
    segment_ids: list[int],
) -> list[CenterlineAsset]:
    if not segment_ids:
        return []
    rows = list(
        (
            await session.execute(
                select(NavigationCenterlineSegment).where(
                    NavigationCenterlineSegment.id.in_(segment_ids),
                    NavigationCenterlineSegment.channel_id == centerline.channel_id,
                    NavigationCenterlineSegment.geometry_json.is_not(None),
                    NavigationCenterlineSegment.segment_status_code.in_(("PUBLISHED", "CONFIRMED", "CANDIDATE", "NEED_REPAIR")),
                )
            )
        ).scalars()
    )
    by_id = {int(row.id): row for row in rows}
    assets: list[CenterlineAsset] = []
    for segment_id in segment_ids:
        row = by_id.get(int(segment_id))
        if row is None:
            continue
        geometry = shape(row.geometry_json)
        if isinstance(geometry, LineString) and not geometry.is_empty and len(geometry.coords) >= 2:
            assets.append(
                CenterlineAsset(
                    asset_id=-int(row.id),
                    row=centerline,
                    geometry=geometry,
                    segment_id=int(row.id),
                    boundary_validation_required=not _segment_allows_boundary_passthrough(row),
                )
            )
    return assets


def _segment_allows_boundary_passthrough(row: NavigationCenterlineSegment) -> bool:
    trace = row.source_trace_json if isinstance(row.source_trace_json, dict) else {}
    return (
        row.source_type_code == "CHANNEL_GUIDE_WITH_BOUNDARY_CLIP"
        and trace.get("boundary_clip_mode") in {"GUIDE_PASSTHROUGH_BBOX_READY", "SEED_BOUNDARY_GUIDE_PASSTHROUGH"}
        and float(trace.get("bbox_coverage_ratio") or 0) >= 0.9
    )


async def _load_boundaries(session: AsyncSession, channel_ids: set[int]) -> dict[int, BaseGeometry]:
    if not channel_ids:
        return {}
    rows = (
        await session.execute(
            select(NavigationChannelBoundary).where(
                NavigationChannelBoundary.channel_id.in_(channel_ids),
                NavigationChannelBoundary.is_current.is_(True),
                NavigationChannelBoundary.geometry_status_code == "AVAILABLE",
            )
        )
    ).scalars()
    return {row.channel_id: shape(row.geometry_json) for row in rows if row.geometry_json}


async def _load_channel_vessel_profiles(session: AsyncSession, channel_ids: set[int]) -> dict[int, dict[str, Any]]:
    if not channel_ids:
        return {}
    rows = (
        await session.execute(select(NavigationChannel).where(NavigationChannel.id.in_(channel_ids)))
    ).scalars()
    return {
        int(row.id): vessel_limit_profile(
            current_grade_code=row.technical_grade_current_code,
            planned_grade_code=row.technical_grade_planned_code,
        )
        for row in rows
    }


async def _load_transport_nodes(session: AsyncSession, bbox: dict[str, float]) -> list[TransportNode]:
    rows = (
        await session.execute(
            select(TransportNode).where(
                TransportNode.longitude.is_not(None),
                TransportNode.latitude.is_not(None),
                TransportNode.status == 1,
                TransportNode.longitude >= bbox["min_lng"],
                TransportNode.longitude <= bbox["max_lng"],
                TransportNode.latitude >= bbox["min_lat"],
                TransportNode.latitude <= bbox["max_lat"],
            )
        )
    ).scalars()
    return list(rows)


async def _load_constraint_points(session: AsyncSession, bbox: dict[str, float]) -> list[NavigationConstraintPoint]:
    rows = (
        await session.execute(
            select(NavigationConstraintPoint).where(
                NavigationConstraintPoint.longitude >= bbox["min_lng"],
                NavigationConstraintPoint.longitude <= bbox["max_lng"],
                NavigationConstraintPoint.latitude >= bbox["min_lat"],
                NavigationConstraintPoint.latitude <= bbox["max_lat"],
                NavigationConstraintPoint.status == 1,
            )
        )
    ).scalars()
    return list(rows)


async def _load_constraint_profiles(
    session: AsyncSession,
    constraint_point_ids: set[int],
) -> dict[int, NavigationConstraintProfile]:
    if not constraint_point_ids:
        return {}
    rows = (
        await session.execute(
            select(NavigationConstraintProfile).where(
                NavigationConstraintProfile.constraint_point_id.in_(constraint_point_ids)
            )
        )
    ).scalars()
    return {row.constraint_point_id: row for row in rows}


def _nearest_centerline(
    point: Point,
    centerlines: list[CenterlineAsset],
) -> tuple[CenterlineAsset, Point, float] | None:
    best: tuple[CenterlineAsset, Point, float] | None = None
    for asset in centerlines:
        projected = _nearest_point_on_line(asset.geometry, point)
        distance_m = _point_distance_m(point, projected)
        if best is None or distance_m < best[2]:
            best = (asset, projected, distance_m)
    return best


def _dedupe_split_points(points: list[SplitPointSpec], line: LineString) -> list[SplitPointSpec]:
    by_key: dict[tuple[int, int], SplitPointSpec] = {}
    for point in points:
        key = _point_key(point.point)
        existing = by_key.get(key)
        if existing is None or NODE_TYPE_PRIORITY.get(point.node_type_code, 0) > NODE_TYPE_PRIORITY.get(existing.node_type_code, 0):
            by_key[key] = point
    return sorted(by_key.values(), key=lambda item: line.project(item.point))


def _merge_short_nonprotected_points(
    points: list[SplitPointSpec],
    line: LineString,
    config: GraphBuildConfig,
    issues: list[GraphBuildIssue],
    centerline: NavigationChannelCenterline,
) -> list[SplitPointSpec]:
    if len(points) <= 2:
        return points
    merged: list[SplitPointSpec] = [points[0]]
    for point in points[1:]:
        previous = merged[-1]
        if (
            not previous.is_endpoint
            and not point.is_endpoint
            and previous.node_type_code not in PROTECTED_NODE_TYPES
            and point.node_type_code not in PROTECTED_NODE_TYPES
            and _point_distance_m(previous.point, point.point) < config.short_edge_merge_m
        ):
            issues.append(
                GraphBuildIssue(
                    "SHORT_EDGE_MERGED",
                    "INFO",
                    f"Merged short non-protected split near centerline {centerline.centerline_code}",
                    centerline_id=centerline.id,
                    channel_id=centerline.channel_id,
                    distance_m=_point_distance_m(previous.point, point.point),
                )
            )
            continue
        merged.append(point)
    return merged


def _split_segment(line: LineString, start_point: Point, end_point: Point) -> LineString | None:
    start = line.project(start_point)
    end = line.project(end_point)
    if end < start:
        start, end = end, start
    if abs(end - start) < 1e-12:
        return None
    segment = substring(line, start, end)
    if isinstance(segment, Point) or segment.is_empty:
        return None
    if isinstance(segment, LineString):
        return segment
    return LineString(segment.coords)


def _edge_quality_for_segment(
    *,
    segment: LineString,
    from_node: NavigationGraphNode,
    to_node: NavigationGraphNode,
    boundary: BaseGeometry | None,
    length_m: float,
    config: GraphBuildConfig,
) -> tuple[str, bool, list[str]]:
    issues: list[str] = []
    quality = "READY"
    routing_enabled = True
    if boundary is not None:
        if boundary.covers(segment):
            pass
        elif boundary.buffer(config.boundary_tolerance_degree).covers(segment):
            quality = "READY_WITH_WARNING"
            issues.append("EDGE_NEAR_BOUNDARY_TOLERATED")
        else:
            return "OUT_OF_BOUNDARY", False, ["EDGE_OUT_OF_BOUNDARY"]
    protected = from_node.node_type_code in PROTECTED_NODE_TYPES or to_node.node_type_code in PROTECTED_NODE_TYPES
    if length_m < config.short_edge_merge_m and not protected:
        return "DISABLED", False, ["SHORT_EDGE_DISABLED"]
    if length_m < config.short_edge_review_m and not protected:
        quality = "SHORT_EDGE_REVIEW"
        routing_enabled = False
        issues.append("SHORT_EDGE_REVIEW")
    elif length_m < config.short_edge_review_m:
        quality = "READY_WITH_WARNING"
        issues.append("SHORT_PROTECTED_EDGE")
    return quality, routing_enabled, issues


def _transport_connector_quality(
    *,
    geometry: LineString,
    boundary: BaseGeometry | None,
    distance_m: float,
    config: GraphBuildConfig,
) -> tuple[str, bool, list[str]]:
    if distance_m <= config.transport_auto_snap_m:
        return "READY", True, []
    issue_codes = ["SNAP_CONNECTOR_NEED_REVIEW"]
    if boundary is not None:
        if boundary.covers(geometry) or boundary.buffer(config.boundary_tolerance_degree).covers(geometry):
            return "READY_WITH_WARNING", True, ["SNAP_CONNECTOR_BOUNDARY_VERIFIED"]
    return "NEED_REVIEW", False, issue_codes


async def build_graph_from_centerlines(
    *,
    session: AsyncSession,
    version_code: str,
    version_name: str | None = None,
    scope_code: str = "REAL-JS-YRD",
    channel_codes: list[str] | None = None,
    activate: bool = False,
    config: GraphBuildConfig | None = None,
) -> GraphBuildSummary:
    config = config or GraphBuildConfig()
    clean_version_code = _clean_code(version_code, max_len=96)
    existing = (
        await session.execute(
            select(NavigationGraphVersion).where(NavigationGraphVersion.version_code == clean_version_code)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ValueError(f"Graph version already exists: {clean_version_code}")

    centerlines, issues = await _load_centerline_assets(session, channel_codes=channel_codes)
    bbox = _bbox_from_centerlines(centerlines)
    graph_version = NavigationGraphVersion(
        version_code=clean_version_code,
        version_name=version_name or clean_version_code,
        scope_code=scope_code,
        source_summary_json=_source_summary(centerlines),
        node_count=0,
        edge_count=0,
        channel_count=len({item.row.channel_id for item in centerlines}),
        status_code="BUILDING",
        is_active=False,
        built_at=datetime.now(UTC).replace(tzinfo=None),
        build_scope_bbox_json=bbox,
        build_config_json=config.as_dict(),
    )
    session.add(graph_version)
    await session.flush()

    if not centerlines:
        issues.append(
            GraphBuildIssue(
                "NO_PUBLISHED_CENTERLINE",
                "BLOCKING",
                "No published current centerline is available for graph building",
            )
        )
        graph_version.status_code = "FAILED"
        graph_version.quality_score = 0
        graph_version.validation_report_json = {
            "issues": [asdict(issue) for issue in issues],
            "annotation_task_candidates": [],
        }
        await session.commit()
        return GraphBuildSummary(
            version_code=clean_version_code,
            graph_version_id=graph_version.id,
            status_code="FAILED",
            node_count=0,
            edge_count=0,
            channel_count=0,
            quality_score=0,
            centerline_count=0,
            connector_edge_count=0,
            constraint_count=0,
            issues=issues,
            validation_report=graph_version.validation_report_json,
        )

    channel_ids = {item.row.channel_id for item in centerlines}
    boundaries = await _load_boundaries(session, channel_ids)
    channel_vessel_profiles = await _load_channel_vessel_profiles(session, channel_ids)
    expanded_bbox = _bbox_with_margin(bbox, config.bbox_margin_degree) if bbox else None
    transport_nodes = await _load_transport_nodes(session, expanded_bbox) if expanded_bbox else []
    constraint_points = await _load_constraint_points(session, expanded_bbox) if expanded_bbox else []
    constraint_profiles = await _load_constraint_profiles(session, {point.id for point in constraint_points})
    split_points: dict[int, list[SplitPointSpec]] = defaultdict(list)
    connector_specs: list[ConnectorSpec] = []

    for asset in centerlines:
        coords = list(asset.geometry.coords)
        split_points[asset.asset_id].append(SplitPointSpec(point=Point(coords[0]), is_endpoint=True))
        split_points[asset.asset_id].append(SplitPointSpec(point=Point(coords[-1]), is_endpoint=True))

    water_body_ids_by_channel = await _load_channel_water_body_ids(session, channel_ids)
    cross_channel_connector_specs = _append_cross_channel_junctions(
        centerlines,
        boundaries,
        water_body_ids_by_channel,
        split_points,
        issues,
        config,
    )

    centerlines_by_channel: dict[int, list[CenterlineAsset]] = defaultdict(list)
    for asset in centerlines:
        centerlines_by_channel[int(asset.row.channel_id)].append(asset)

    for channel_assets in centerlines_by_channel.values():
        for index, left in enumerate(channel_assets):
            for right in channel_assets[index + 1 :]:
                if not _bounds_intersect(left.geometry.bounds, right.geometry.bounds):
                    continue
                intersection = left.geometry.intersection(right.geometry)
                if intersection.is_empty:
                    continue
                for point in _intersection_points(intersection):
                    split_points[left.asset_id].append(
                        SplitPointSpec(point=point, node_type_code="CHANNEL_JUNCTION", source_type_code="CENTERLINE_INTERSECTION")
                    )
                    split_points[right.asset_id].append(
                        SplitPointSpec(point=point, node_type_code="CHANNEL_JUNCTION", source_type_code="CENTERLINE_INTERSECTION")
                    )

    node_sequence = 0
    edge_sequence = 0
    node_registry: dict[tuple[Any, ...], NavigationGraphNode] = {}

    def add_node(
        *,
        point: Point,
        node_type_code: str,
        source_type_code: str,
        channel_id: int | None,
        related_transport_node_id: int | None = None,
        related_constraint_point_id: int | None = None,
        node_name: str | None = None,
        snap_distance_m: float | None = None,
        snap_confidence: int | None = None,
    ) -> NavigationGraphNode:
        nonlocal node_sequence
        if related_transport_node_id is not None:
            key = ("transport", related_transport_node_id)
            alias_keys: list[tuple[Any, ...]] = []
        elif related_constraint_point_id is not None:
            key = ("constraint", related_constraint_point_id)
            alias_keys = []
        elif node_type_code == "CHANNEL_JUNCTION":
            normalized_point_key = _point_key(point)
            key = ("junction", normalized_point_key)
            alias_keys = [("channel-point", channel_id, normalized_point_key)]
        else:
            normalized_point_key = _point_key(point)
            key = ("channel-point", channel_id, normalized_point_key)
            alias_keys = [("junction", normalized_point_key)]
        existing_node = node_registry.get(key)
        if existing_node is None:
            for alias_key in alias_keys:
                existing_node = node_registry.get(alias_key)
                if existing_node is not None:
                    node_registry[key] = existing_node
                    break
        if existing_node is not None:
            if NODE_TYPE_PRIORITY.get(node_type_code, 0) > NODE_TYPE_PRIORITY.get(existing_node.node_type_code, 0):
                existing_node.node_type_code = node_type_code
                existing_node.source_type_code = source_type_code
            for alias_key in alias_keys:
                node_registry.setdefault(alias_key, existing_node)
            return existing_node
        node_sequence += 1
        node = NavigationGraphNode(
            graph_version_id=graph_version.id,
            node_code=f"{clean_version_code[:72]}-N-{node_sequence:05d}",
            node_name=node_name,
            node_type_code=node_type_code,
            longitude=float(point.x),
            latitude=float(point.y),
            geometry_json=mapping(point),
            channel_id=channel_id,
            related_transport_node_id=related_transport_node_id,
            related_constraint_point_id=related_constraint_point_id,
            is_enabled=True,
            quality_code="READY",
            source_type_code=source_type_code,
            snap_distance_m=_round_float(snap_distance_m, 3),
            snap_confidence=snap_confidence,
        )
        session.add(node)
        node_registry[key] = node
        return node

    for node in transport_nodes:
        node_point = Point(float(node.longitude), float(node.latitude))
        nearest = _nearest_centerline(node_point, centerlines)
        if nearest is None:
            continue
        centerline, split_point, distance_m = nearest
        if distance_m > config.transport_review_snap_m:
            issues.append(
                GraphBuildIssue(
                    "NO_GRAPH_NEAR_TRANSPORT_NODE",
                    "WARNING",
                    f"Transport node {node.code} is too far from published centerline",
                    channel_id=centerline.row.channel_id,
                    distance_m=distance_m,
                )
            )
            continue
        snap_confidence = 95 if distance_m <= config.transport_auto_snap_m else 70
        split_points[centerline.asset_id].append(
            SplitPointSpec(
                point=split_point,
                node_type_code="SNAP_CONNECTOR",
                source_type_code="SNAP_CONNECTOR",
                related_transport_node_id=None,
                snap_distance_m=distance_m,
                snap_confidence=snap_confidence,
            )
        )
        transport_graph_node = add_node(
            point=node_point,
            node_type_code=_node_kind_for_transport(node),
            source_type_code="TRANSPORT_NODE",
            channel_id=centerline.row.channel_id,
            related_transport_node_id=node.id,
            node_name=node.name,
            snap_distance_m=distance_m,
            snap_confidence=snap_confidence,
        )
        centerline_graph_node = add_node(
            point=split_point,
            node_type_code="SNAP_CONNECTOR",
            source_type_code="SNAP_CONNECTOR",
            channel_id=centerline.row.channel_id,
            snap_distance_m=distance_m,
            snap_confidence=snap_confidence,
        )
        connector_geometry = LineString([(node_point.x, node_point.y), (split_point.x, split_point.y)])
        connector_quality, connector_enabled, connector_issue_codes = _transport_connector_quality(
            geometry=connector_geometry,
            boundary=boundaries.get(centerline.row.channel_id),
            distance_m=distance_m,
            config=config,
        )
        connector_specs.append(
            ConnectorSpec(
                from_node=transport_graph_node,
                to_node=centerline_graph_node,
                channel_id=centerline.row.channel_id,
                geometry=connector_geometry,
                source_type_code="SNAP_CONNECTOR",
                quality_code=connector_quality,
                routing_enabled=connector_enabled,
                snap_distance_m=distance_m,
                issue_codes=connector_issue_codes,
            )
        )

    for point in constraint_points:
        constraint_point = Point(float(point.longitude), float(point.latitude))
        nearest = _nearest_centerline(constraint_point, centerlines)
        if nearest is None:
            continue
        centerline, split_point, distance_m = nearest
        if distance_m > config.constraint_snap_m:
            issues.append(
                GraphBuildIssue(
                    "CONSTRAINT_POINT_NOT_SNAPPED",
                    "WARNING",
                    f"Constraint point {point.code} is too far from published centerline",
                    channel_id=centerline.row.channel_id,
                    distance_m=distance_m,
                )
            )
            continue
        node_type = _node_kind_for_constraint(point)
        split_points[centerline.asset_id].append(
            SplitPointSpec(
                point=split_point,
                node_type_code=node_type,
                source_type_code="CONSTRAINT_POINT",
                related_constraint_point_id=point.id,
                snap_distance_m=distance_m,
                snap_confidence=95,
            )
        )

    centerline_nodes: dict[tuple[int, tuple[int, int]], NavigationGraphNode] = {}
    split_points_by_centerline: dict[int, list[SplitPointSpec]] = {}
    for asset in centerlines:
        points = _dedupe_split_points(split_points[asset.asset_id], asset.geometry)
        points = _merge_short_nonprotected_points(points, asset.geometry, config, issues, asset.row)
        split_points_by_centerline[asset.asset_id] = points
        for point in points:
            node = add_node(
                point=point.point,
                node_type_code=point.node_type_code,
                source_type_code=point.source_type_code,
                channel_id=asset.row.channel_id,
                related_constraint_point_id=point.related_constraint_point_id,
                snap_distance_m=point.snap_distance_m,
                snap_confidence=point.snap_confidence,
            )
            centerline_nodes[(asset.asset_id, _point_key(point.point))] = node

    for connector in cross_channel_connector_specs:
        left_node = centerline_nodes.get((connector.left.asset_id, _point_key(connector.left_point)))
        right_node = centerline_nodes.get((connector.right.asset_id, _point_key(connector.right_point)))
        if left_node is None or right_node is None or left_node is right_node:
            continue
        connector_specs.append(
            ConnectorSpec(
                from_node=left_node,
                to_node=right_node,
                channel_id=None,
                geometry=LineString(
                    [
                        (connector.left_point.x, connector.left_point.y),
                        (connector.right_point.x, connector.right_point.y),
                    ]
                ),
                source_type_code=connector.source_type_code,
                quality_code="READY_WITH_WARNING",
                routing_enabled=True,
                snap_distance_m=connector.distance_m,
                issue_codes=["CROSS_CHANNEL_CONFLUENCE_CONNECTOR"],
            )
        )

    await session.flush()
    edge_constraint_pairs: list[tuple[NavigationGraphEdge, NavigationGraphNode]] = []

    def add_edge(
        *,
        from_node: NavigationGraphNode,
        to_node: NavigationGraphNode,
        channel_id: int | None,
        centerline_id: int | None,
        geometry: LineString,
        direction_code: str,
        technical_grade_code: str | None,
        source_type_code: str,
        confidence_score: int,
        quality_code: str,
        routing_enabled: bool,
        validation_summary: dict[str, Any],
        lock_required: bool = False,
        bridge_count: int = 0,
    ) -> NavigationGraphEdge:
        nonlocal edge_sequence
        edge_sequence += 1
        edge_code = f"{clean_version_code[:72]}-E-{edge_sequence:05d}"
        length_km = _round_float(_line_length_km(geometry), 4) or 0.0
        vessel_profile = channel_vessel_profiles.get(int(channel_id)) if channel_id is not None else None
        validation_payload = dict(validation_summary)
        if vessel_profile is not None:
            validation_payload.setdefault("vessel_limit_profile", vessel_profile)
        edge = NavigationGraphEdge(
            graph_version_id=graph_version.id,
            edge_code=edge_code,
            from_node_id=from_node.id,
            to_node_id=to_node.id,
            channel_id=channel_id,
            centerline_id=centerline_id,
            geometry_json=mapping(geometry),
            length_km=length_km,
            direction_code=direction_code,
            technical_grade_code=technical_grade_code or (vessel_profile or {}).get("technical_grade_code"),
            min_width_m=(vessel_profile or {}).get("min_width_m"),
            max_allowed_draft_m=(vessel_profile or {}).get("max_allowed_draft_m"),
            max_allowed_tonnage=(vessel_profile or {}).get("max_allowed_tonnage"),
            lock_required=lock_required,
            bridge_count=bridge_count,
            base_cost=length_km,
            routing_enabled=routing_enabled,
            quality_code=quality_code,
            source_type_code=source_type_code,
            confidence_score=confidence_score,
            version_no=1,
            unknown_constraint_flag=bool((vessel_profile or {}).get("unknown_constraint_flag", True)),
            validation_summary_json=validation_payload,
        )
        session.add(edge)
        return edge

    for asset in centerlines:
        row = asset.row
        points = split_points_by_centerline[asset.asset_id]
        for index in range(len(points) - 1):
            from_point = points[index]
            to_point = points[index + 1]
            segment = _split_segment(asset.geometry, from_point.point, to_point.point)
            if segment is None:
                continue
            from_node = centerline_nodes[(asset.asset_id, _point_key(from_point.point))]
            to_node = centerline_nodes[(asset.asset_id, _point_key(to_point.point))]
            length_m = _line_length_km(segment) * 1000
            quality, routing_enabled, edge_issue_codes = _edge_quality_for_segment(
                segment=segment,
                from_node=from_node,
                to_node=to_node,
                boundary=boundaries.get(row.channel_id) if asset.boundary_validation_required else None,
                length_m=length_m,
                config=config,
            )
            if not asset.boundary_validation_required:
                quality = "READY_WITH_WARNING" if quality == "READY" else quality
                edge_issue_codes = [*edge_issue_codes, "GUIDE_PASSTHROUGH_BOUNDARY_REVIEW"]
            for issue_code in edge_issue_codes:
                severity = "WARNING" if (
                    issue_code.startswith("SHORT")
                    or issue_code in {"EDGE_NEAR_BOUNDARY_TOLERATED", "GUIDE_PASSTHROUGH_BOUNDARY_REVIEW"}
                ) else "BLOCKING"
                issues.append(
                    GraphBuildIssue(
                        issue_code,
                        severity,
                        f"Edge candidate from centerline {row.centerline_code}: {issue_code}",
                        centerline_id=row.id,
                        channel_id=row.channel_id,
                    )
                )
            edge = add_edge(
                from_node=from_node,
                to_node=to_node,
                channel_id=row.channel_id,
                centerline_id=row.id,
                geometry=segment,
                direction_code=row.direction_code,
                technical_grade_code=None,
                source_type_code=row.source_type_code,
                confidence_score=row.confidence_score,
                quality_code=quality,
                routing_enabled=routing_enabled,
                validation_summary={"issue_codes": edge_issue_codes},
            )
            for node in (from_node, to_node):
                if node.related_constraint_point_id is not None:
                    edge_constraint_pairs.append((edge, node))

    for connector in connector_specs:
        issue_codes = list(connector.issue_codes)
        if "SNAP_CONNECTOR_NEED_REVIEW" in issue_codes:
            issues.append(
                GraphBuildIssue(
                    "SNAP_CONNECTOR_NEED_REVIEW",
                    "WARNING",
                    "Transport node connector needs manual review",
                    channel_id=connector.channel_id,
                    distance_m=connector.snap_distance_m,
                )
            )
        add_edge(
            from_node=connector.from_node,
            to_node=connector.to_node,
            channel_id=connector.channel_id,
            centerline_id=None,
            geometry=connector.geometry,
            direction_code="BIDIRECTIONAL",
            technical_grade_code=None,
            source_type_code=connector.source_type_code,
            confidence_score=95 if connector.routing_enabled else 70,
            quality_code=connector.quality_code,
            routing_enabled=connector.routing_enabled,
            validation_summary={"snap_distance_m": connector.snap_distance_m, "issue_codes": issue_codes},
        )

    await session.flush()

    constraint_count = 0
    for edge, node in edge_constraint_pairs:
        node_type = node.node_type_code
        profile = constraint_profiles.get(node.related_constraint_point_id or 0)
        complete = _constraint_complete(node_type, profile)
        edge.unknown_constraint_flag = not complete
        if node_type == "LOCK":
            edge.lock_required = True
        if node_type == "BRIDGE":
            edge.bridge_count = max(edge.bridge_count, 1)
        if profile:
            edge.max_allowed_tonnage = profile.max_tonnage
            edge.max_allowed_draft_m = profile.max_allowed_draft_m
            edge.max_air_draft_m = profile.max_air_draft_m
            edge.max_beam_m = profile.max_beam_m
            edge.max_length_m = profile.max_length_m
        constraint_count += 1
        session.add(
            NavigationGraphEdgeConstraint(
                edge_id=edge.id,
                constraint_type_code=_constraint_type_for_node(node_type),
                constraint_name=node.node_name,
                rule_json=profile.restriction_rule_json if profile else None,
                severity_level="WARNING",
                warning_message=profile.warning_message if profile else "Constraint profile is incomplete",
                is_blocking=False,
                is_enabled=True,
                data_completeness_code="COMPLETE" if complete else "UNKNOWN",
                source_trace_json={
                    "related_constraint_point_id": node.related_constraint_point_id,
                    "node_type_code": node_type,
                },
            )
        )

    await session.flush()
    graph_version.node_count = node_sequence
    graph_version.edge_count = edge_sequence
    graph_version.channel_count = len(channel_ids)
    graph_version.source_summary_json = {
        **(graph_version.source_summary_json or {}),
        "build_issue_counts": dict(
            sorted(
                {
                    issue.issue_code: sum(1 for item in issues if item.issue_code == issue.issue_code)
                    for issue in issues
                }.items()
            )
        ),
    }
    graph_version.validation_report_json = {"build_issues": [asdict(issue) for issue in issues]}
    await session.commit()

    validation = await validate_navigation_graph(session=session, graph_version_id=graph_version.id, update_version=True)
    if activate and validation.status_code == "READY":
        active_versions = (
            await session.execute(
                select(NavigationGraphVersion).where(
                    NavigationGraphVersion.scope_code == scope_code,
                    NavigationGraphVersion.is_active.is_(True),
                    NavigationGraphVersion.id != graph_version.id,
                )
            )
        ).scalars()
        for row in active_versions:
            row.is_active = False
        graph_version.is_active = True
        await session.commit()

    merged_report = validation.as_dict()
    merged_report["build_issues"] = [asdict(issue) for issue in issues]
    graph_version.validation_report_json = merged_report
    await session.commit()

    return GraphBuildSummary(
        version_code=clean_version_code,
        graph_version_id=graph_version.id,
        status_code=validation.status_code,
        node_count=validation.node_count,
        edge_count=validation.edge_count,
        channel_count=len(channel_ids),
        quality_score=validation.quality_score,
        centerline_count=len(centerlines),
        connector_edge_count=len(connector_specs),
        constraint_count=constraint_count,
        issues=issues,
        validation_report=merged_report,
    )
