"""Build an actionable repair queue from route-pair audit reports.

The audit report tells us which OD pairs fail. This script turns that into the
next production queue: which endpoint needs access seed, which pair needs graph
connectivity repair, which water body is unnamed, and what local map/water
evidence can safely be used for an automatic name supplement.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from shapely.geometry import LineString, Point, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points
from shapely.validation import make_valid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.address import NavigationChannel
from app.models.navigation import (
    NavigationGraphEdge,
    NavigationGraphNode,
    NavigationGraphVersion,
    NavigationWaterArea,
    NavigationWaterBody,
    NavigationWaterBodyFeatureLink,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUDIT_REPORT = PROJECT_ROOT / "runtime/navigation-production/reports/transport_node_pair_audit_graph50_limit50_20260608.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "runtime/navigation-production/reports/route_repair_queue_graph50_20260608.json"
DEFAULT_GEOJSON_OUTPUT = PROJECT_ROOT / "runtime/navigation-production/reports/route_repair_queue_graph50_20260608.geojson"
AUTO_NAME_SOURCE = "MAP_LABEL_OR_CHANNEL_INFERRED"
READY_GRAPH_STATUSES = {"READY", "READY_WITH_WARNING"}
TOO_FAR_ISSUES = {"ORIGIN_TOO_FAR_FROM_GRAPH", "DESTINATION_TOO_FAR_FROM_GRAPH"}
CONNECTIVITY_ISSUES = {"GRAPH_DISCONNECTED", "NO_PATH_FOUND", "NO_ROUTING_EDGE_IN_EXPANDED_BBOX"}
WATER_GEOMETRY_ISSUES = {
    "PATH_OUT_OF_WATER",
    "PATH_WATER_COVERAGE_WARNING",
    "PATH_OUT_OF_CHANNEL_BOUNDARY",
    "PATH_CHANNEL_BOUNDARY_WARNING",
    "ROUTE_STRAIGHT_LINE_FALLBACK",
    "ROUTE_LONG_STRAIGHT_SEGMENT_REVIEW",
}
UNNAMED_PATTERNS = (
    re.compile(r"^未命名"),
    re.compile(r"^unnamed", re.IGNORECASE),
    re.compile(r"^unknown", re.IGNORECASE),
)


@dataclass(slots=True)
class AuditEndpoint:
    id: int
    code: str
    name: str
    longitude: float
    latitude: float


@dataclass(slots=True)
class EndpointAggregate:
    endpoint: AuditEndpoint
    issue_codes: set[str] = field(default_factory=set)
    pair_refs: list[dict[str, Any]] = field(default_factory=list)
    implicated_as: set[str] = field(default_factory=set)


@dataclass(slots=True)
class GraphEdgeContext:
    edge_id: int
    channel_id: int | None
    channel_name: str | None
    source_type_code: str
    quality_code: str
    distance_m: float
    nearest_lng: float
    nearest_lat: float
    geometry_json: dict[str, Any]


@dataclass(slots=True)
class WaterContext:
    source_type_code: str
    ref_id: int
    name: str | None
    name_status_code: str | None
    source_layer_name: str | None
    water_level: int | None
    water_type_code: str | None
    distance_m: float
    nearest_lng: float
    nearest_lat: float
    geometry_json: dict[str, Any]
    raw: NavigationWaterBody | NavigationWaterArea


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify route audit failures into automatic seed repair queues.")
    parser.add_argument("--audit-report", type=Path, default=DEFAULT_AUDIT_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--geojson-output", type=Path, default=DEFAULT_GEOJSON_OUTPUT)
    parser.add_argument("--graph-version-id", type=int, default=None)
    parser.add_argument("--water-search-radius-km", type=float, default=25.0)
    parser.add_argument("--access-water-threshold-m", type=float, default=750.0)
    parser.add_argument("--graph-near-threshold-m", type=float, default=500.0)
    parser.add_argument("--graph-snap-threshold-m", type=float, default=2000.0)
    parser.add_argument("--non-water-threshold-m", type=float, default=2000.0)
    parser.add_argument("--apply-name-updates", action="store_true")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    report = json.loads(args.audit_report.read_text(encoding="utf-8"))
    endpoint_aggregates, pair_actions = _collect_problem_endpoints(report)
    async with AsyncSessionLocal() as session:
        active_graph = await _resolve_graph_version(session, args.graph_version_id)
        graph_edges = await _load_graph_edges(session, active_graph.id if active_graph else None)
        classified: list[dict[str, Any]] = []
        name_updates: list[dict[str, Any]] = []
        for aggregate in endpoint_aggregates.values():
            item, update = await _classify_endpoint(
                session=session,
                aggregate=aggregate,
                graph_edges=graph_edges,
                access_water_threshold_m=float(args.access_water_threshold_m),
                graph_near_threshold_m=float(args.graph_near_threshold_m),
                graph_snap_threshold_m=float(args.graph_snap_threshold_m),
                non_water_threshold_m=float(args.non_water_threshold_m),
                water_search_radius_km=float(args.water_search_radius_km),
                apply_name_update=bool(args.apply_name_updates),
            )
            classified.append(item)
            if update:
                name_updates.append(update)
        if args.apply_name_updates:
            await session.commit()

    summary = _summary(
        report=report,
        active_graph=active_graph,
        endpoint_items=classified,
        pair_actions=pair_actions,
        name_updates=name_updates,
    )
    output = {
        "report_version": "ROUTE_REPAIR_QUEUE_V1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_audit_report": str(args.audit_report),
        "args": {
            "graph_version_id": args.graph_version_id,
            "water_search_radius_km": float(args.water_search_radius_km),
            "access_water_threshold_m": float(args.access_water_threshold_m),
            "graph_near_threshold_m": float(args.graph_near_threshold_m),
            "graph_snap_threshold_m": float(args.graph_snap_threshold_m),
            "non_water_threshold_m": float(args.non_water_threshold_m),
            "apply_name_updates": bool(args.apply_name_updates),
        },
        "active_graph_version": _graph_payload(active_graph),
        "summary": summary,
        "endpoint_repair_queue": sorted(classified, key=_endpoint_sort_key),
        "pair_repair_actions": pair_actions,
        "name_updates": name_updates,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.geojson_output:
        args.geojson_output.parent.mkdir(parents=True, exist_ok=True)
        args.geojson_output.write_text(
            json.dumps(_geojson(classified), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"report_path={args.output}")
    if args.geojson_output:
        print(f"geojson_path={args.geojson_output}")


def _collect_problem_endpoints(report: dict[str, Any]) -> tuple[dict[int, EndpointAggregate], list[dict[str, Any]]]:
    endpoints: dict[int, EndpointAggregate] = {}
    pair_actions: list[dict[str, Any]] = []
    for index, item in enumerate(report.get("items") or [], start=1):
        origin = _endpoint_from_payload(item.get("origin"))
        destination = _endpoint_from_payload(item.get("destination"))
        if origin is None or destination is None:
            continue
        route = item.get("route") if isinstance(item.get("route"), dict) else {}
        audit = item.get("audit") if isinstance(item.get("audit"), dict) else {}
        issue_codes = {
            str(code).upper()
            for code in audit.get("repair_issue_codes") or audit.get("issue_codes") or []
            if str(code or "").strip()
        }
        error_code = str(route.get("error_code") or item.get("error_code") or "").upper()
        if error_code:
            issue_codes.add(error_code)
        hard_issue = bool(audit.get("hard_issue") or route.get("status_code") != "SUCCESS" or issue_codes)
        if not hard_issue:
            continue
        pair_ref = {
            "pair_index": index,
            "origin_id": origin.id,
            "origin_code": origin.code,
            "origin_name": origin.name,
            "destination_id": destination.id,
            "destination_code": destination.code,
            "destination_name": destination.name,
            "route_result_id": route.get("result_id"),
            "route_status_code": route.get("status_code"),
            "route_quality_code": route.get("quality_code"),
            "provider_code": route.get("provider_code"),
            "issue_codes": sorted(issue_codes),
        }
        implicated = _implicated_roles(issue_codes)
        if "origin" in implicated:
            _aggregate(endpoints, origin, issue_codes, pair_ref, "ORIGIN")
        if "destination" in implicated:
            _aggregate(endpoints, destination, issue_codes, pair_ref, "DESTINATION")
        pair_actions.append(_pair_action(item, pair_ref, issue_codes))
    return endpoints, pair_actions


def _endpoint_from_payload(payload: Any) -> AuditEndpoint | None:
    if not isinstance(payload, dict):
        return None
    try:
        lng = float(payload.get("longitude"))
        lat = float(payload.get("latitude"))
        endpoint_id = int(payload.get("id"))
    except (TypeError, ValueError):
        return None
    if not _valid_lng_lat(lng, lat):
        return None
    return AuditEndpoint(
        id=endpoint_id,
        code=str(payload.get("code") or endpoint_id),
        name=str(payload.get("name") or endpoint_id),
        longitude=lng,
        latitude=lat,
    )


def _implicated_roles(issue_codes: set[str]) -> set[str]:
    roles: set[str] = set()
    if "ORIGIN_TOO_FAR_FROM_GRAPH" in issue_codes:
        roles.add("origin")
    if "DESTINATION_TOO_FAR_FROM_GRAPH" in issue_codes:
        roles.add("destination")
    if issue_codes.intersection(CONNECTIVITY_ISSUES | WATER_GEOMETRY_ISSUES) or not roles:
        roles.update({"origin", "destination"})
    return roles


def _aggregate(
    endpoints: dict[int, EndpointAggregate],
    endpoint: AuditEndpoint,
    issue_codes: set[str],
    pair_ref: dict[str, Any],
    role: str,
) -> None:
    aggregate = endpoints.get(endpoint.id)
    if aggregate is None:
        aggregate = EndpointAggregate(endpoint=endpoint)
        endpoints[endpoint.id] = aggregate
    aggregate.issue_codes.update(issue_codes)
    aggregate.implicated_as.add(role)
    aggregate.pair_refs.append(pair_ref)


def _pair_action(item: dict[str, Any], pair_ref: dict[str, Any], issue_codes: set[str]) -> dict[str, Any]:
    route = item.get("route") if isinstance(item.get("route"), dict) else {}
    if issue_codes.intersection(TOO_FAR_ISSUES):
        action = "ENDPOINT_ACCESS_SEED_REPAIR"
    elif issue_codes.intersection(CONNECTIVITY_ISSUES):
        action = "GRAPH_CONNECTIVITY_REPAIR"
    elif issue_codes.intersection(WATER_GEOMETRY_ISSUES):
        action = "BOUNDARY_AND_WATER_COVERAGE_REPAIR"
    else:
        action = "ROUTE_QUALITY_REPAIR"
    return {
        **pair_ref,
        "repair_action_code": action,
        "straight_distance_km": item.get("straight_distance_km"),
        "final_route_distance_km": route.get("distance_km"),
        "final_route_result_id": route.get("result_id"),
        "original_self_result_id": ((item.get("original_self_route") or {}).get("result") or {}).get("result_id"),
    }


async def _resolve_graph_version(session: AsyncSession, graph_version_id: int | None) -> NavigationGraphVersion | None:
    if graph_version_id is not None:
        return await session.get(NavigationGraphVersion, int(graph_version_id))
    return (
        await session.execute(
            select(NavigationGraphVersion)
            .where(
                NavigationGraphVersion.is_active.is_(True),
                NavigationGraphVersion.status_code == "READY",
                NavigationGraphVersion.scope_code.not_like("MVP%"),
                NavigationGraphVersion.edge_count > 0,
            )
            .order_by(
                NavigationGraphVersion.channel_count.desc(),
                NavigationGraphVersion.edge_count.desc(),
                NavigationGraphVersion.node_count.desc(),
                NavigationGraphVersion.id.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()


async def _load_graph_edges(session: AsyncSession, graph_version_id: int | None) -> list[tuple[NavigationGraphEdge, NavigationChannel | None, BaseGeometry]]:
    if graph_version_id is None:
        return []
    rows = list(
        (
            await session.execute(
                select(NavigationGraphEdge, NavigationChannel)
                .outerjoin(NavigationChannel, NavigationChannel.id == NavigationGraphEdge.channel_id)
                .where(
                    NavigationGraphEdge.graph_version_id == graph_version_id,
                    NavigationGraphEdge.routing_enabled.is_(True),
                    NavigationGraphEdge.quality_code.in_(READY_GRAPH_STATUSES),
                )
            )
        ).all()
    )
    output: list[tuple[NavigationGraphEdge, NavigationChannel | None, BaseGeometry]] = []
    for edge, channel in rows:
        geometry = _geometry(edge.geometry_json)
        if geometry is None:
            continue
        output.append((edge, channel, geometry))
    return output


async def _classify_endpoint(
    *,
    session: AsyncSession,
    aggregate: EndpointAggregate,
    graph_edges: list[tuple[NavigationGraphEdge, NavigationChannel | None, BaseGeometry]],
    access_water_threshold_m: float,
    graph_near_threshold_m: float,
    graph_snap_threshold_m: float,
    non_water_threshold_m: float,
    water_search_radius_km: float,
    apply_name_update: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    point = Point(aggregate.endpoint.longitude, aggregate.endpoint.latitude)
    nearest_graph = _nearest_graph_edge(point, graph_edges)
    nearest_water_body = await _nearest_water_body(session, point, radius_km=water_search_radius_km)
    nearest_water_area = await _nearest_water_area(session, point, radius_km=water_search_radius_km)
    name_candidate = await _water_name_candidate(
        session=session,
        nearest_water_body=nearest_water_body,
        nearest_water_area=nearest_water_area,
        nearest_graph=nearest_graph,
    )
    action_code, reason_code = _endpoint_action(
        issue_codes=aggregate.issue_codes,
        nearest_graph=nearest_graph,
        nearest_water=nearest_water_body or nearest_water_area,
        access_water_threshold_m=access_water_threshold_m,
        graph_near_threshold_m=graph_near_threshold_m,
        graph_snap_threshold_m=graph_snap_threshold_m,
        non_water_threshold_m=non_water_threshold_m,
    )
    name_update = await _maybe_apply_name_update(
        nearest_water_body=nearest_water_body,
        name_candidate=name_candidate,
        apply_name_update=apply_name_update,
    )
    if name_update and apply_name_update:
        session.add(nearest_water_body.raw)
    item = {
        "endpoint": {
            "type_code": "TRANSPORT_NODE",
            "id": aggregate.endpoint.id,
            "code": aggregate.endpoint.code,
            "name": aggregate.endpoint.name,
            "longitude": round(aggregate.endpoint.longitude, 7),
            "latitude": round(aggregate.endpoint.latitude, 7),
        },
        "repair_action_code": action_code,
        "reason_code": reason_code,
        "issue_codes": sorted(aggregate.issue_codes),
        "implicated_as": sorted(aggregate.implicated_as),
        "pair_count": len(aggregate.pair_refs),
        "pair_refs": aggregate.pair_refs[:20],
        "nearest_graph": _graph_context_payload(nearest_graph),
        "nearest_water_body": _water_context_payload(nearest_water_body),
        "nearest_water_area": _water_context_payload(nearest_water_area),
        "water_name_candidate": name_candidate,
        "name_update_applied": bool(name_update and apply_name_update),
        "map_review_hint": {
            "amap_search_url": f"https://ditu.amap.com/search?query={aggregate.endpoint.longitude:.7f},{aggregate.endpoint.latitude:.7f}",
            "note": "Use only when local Revier/OSM/channel evidence cannot infer a water-system name.",
        },
    }
    return item, name_update if name_update else None


def _nearest_graph_edge(
    point: Point,
    graph_edges: list[tuple[NavigationGraphEdge, NavigationChannel | None, BaseGeometry]],
) -> GraphEdgeContext | None:
    best: GraphEdgeContext | None = None
    for edge, channel, geometry in graph_edges:
        distance_m = _distance_approx_m(point, geometry)
        if best is not None and distance_m >= best.distance_m:
            continue
        nearest = _nearest_point_on_geometry(point, geometry)
        best = GraphEdgeContext(
            edge_id=int(edge.id),
            channel_id=int(edge.channel_id) if edge.channel_id is not None else None,
            channel_name=(channel.channel_name if channel else None),
            source_type_code=edge.source_type_code,
            quality_code=edge.quality_code,
            distance_m=distance_m,
            nearest_lng=float(nearest.x),
            nearest_lat=float(nearest.y),
            geometry_json=edge.geometry_json,
        )
    return best


async def _nearest_water_body(session: AsyncSession, point: Point, *, radius_km: float) -> WaterContext | None:
    margin = max(0.001, float(radius_km) / 111.32)
    rows = list(
        (
            await session.execute(
                select(NavigationWaterBody).where(
                    NavigationWaterBody.is_enabled.is_(True),
                    NavigationWaterBody.geometry_wgs84_json.is_not(None),
                    NavigationWaterBody.bbox_min_lng <= point.x + margin,
                    NavigationWaterBody.bbox_max_lng >= point.x - margin,
                    NavigationWaterBody.bbox_min_lat <= point.y + margin,
                    NavigationWaterBody.bbox_max_lat >= point.y - margin,
                )
            )
        ).scalars()
    )
    return _nearest_water_context(point, rows, source_type_code="WATER_BODY")


async def _nearest_water_area(session: AsyncSession, point: Point, *, radius_km: float) -> WaterContext | None:
    margin = max(0.001, float(radius_km) / 111.32)
    rows = list(
        (
            await session.execute(
                select(NavigationWaterArea).where(
                    NavigationWaterArea.is_enabled.is_(True),
                    NavigationWaterArea.geometry_json.is_not(None),
                    NavigationWaterArea.bbox_min_lng <= point.x + margin,
                    NavigationWaterArea.bbox_max_lng >= point.x - margin,
                    NavigationWaterArea.bbox_min_lat <= point.y + margin,
                    NavigationWaterArea.bbox_max_lat >= point.y - margin,
                )
            )
        ).scalars()
    )
    return _nearest_water_context(point, rows, source_type_code="WATER_AREA")


def _nearest_water_context(
    point: Point,
    rows: Iterable[NavigationWaterBody | NavigationWaterArea],
    *,
    source_type_code: str,
) -> WaterContext | None:
    best: WaterContext | None = None
    for row in rows:
        geometry_json = row.geometry_wgs84_json if isinstance(row, NavigationWaterBody) else row.geometry_json
        geometry = _geometry(geometry_json)
        if geometry is None:
            continue
        distance_m = _distance_approx_m(point, geometry)
        if best is not None and distance_m >= best.distance_m:
            continue
        nearest = _nearest_point_on_geometry(point, geometry)
        if isinstance(row, NavigationWaterBody):
            name = _water_body_name(row)
            name_status = row.name_status_code
            water_level = row.water_level_min
            ref_id = int(row.id)
            source_layer = row.source_layer_name
            water_type = row.water_type_code
        else:
            name = _water_area_name(row)
            name_status = row.geometry_status_code
            water_level = row.water_level
            ref_id = int(row.id)
            source_layer = row.source_layer_name
            water_type = row.water_type_code
        best = WaterContext(
            source_type_code=source_type_code,
            ref_id=ref_id,
            name=name,
            name_status_code=name_status,
            source_layer_name=source_layer,
            water_level=int(water_level) if water_level is not None else None,
            water_type_code=water_type,
            distance_m=distance_m,
            nearest_lng=float(nearest.x),
            nearest_lat=float(nearest.y),
            geometry_json=geometry_json,
            raw=row,
        )
    return best


async def _water_name_candidate(
    *,
    session: AsyncSession,
    nearest_water_body: WaterContext | None,
    nearest_water_area: WaterContext | None,
    nearest_graph: GraphEdgeContext | None,
) -> dict[str, Any]:
    if nearest_water_body and _usable_name(nearest_water_body.name):
        return {
            "candidate_name": nearest_water_body.name,
            "confidence_score": 100,
            "source_code": "NEAREST_WATER_BODY_NAME",
            "source_ref_type_code": "WATER_BODY",
            "source_ref_id": nearest_water_body.ref_id,
            "apply_allowed": False,
            "reason": "nearest water body already has production/map name",
        }
    linked_area_candidate = await _linked_area_name_candidate(session, nearest_water_body)
    if linked_area_candidate:
        return linked_area_candidate
    if nearest_water_area and _usable_name(nearest_water_area.name):
        return {
            "candidate_name": nearest_water_area.name,
            "confidence_score": 90 if nearest_water_area.distance_m <= 100 else 82,
            "source_code": "NEAREST_WATER_AREA_MAP_LABEL",
            "source_ref_type_code": "WATER_AREA",
            "source_ref_id": nearest_water_area.ref_id,
            "apply_allowed": bool(nearest_water_body and nearest_water_area.distance_m <= 500),
            "reason": "nearest local water-area layer has a usable map/source label",
        }
    if nearest_graph and _usable_name(nearest_graph.channel_name) and nearest_graph.distance_m <= 500:
        candidate = _strip_water_suffix(str(nearest_graph.channel_name))
        return {
            "candidate_name": candidate,
            "confidence_score": 76,
            "source_code": "NEAREST_CHANNEL_INFERRED",
            "source_ref_type_code": "GRAPH_EDGE",
            "source_ref_id": nearest_graph.edge_id,
            "apply_allowed": bool(nearest_water_body),
            "reason": "endpoint is near an existing graph edge; channel name is used as conservative water-system label",
        }
    return {
        "candidate_name": None,
        "confidence_score": 0,
        "source_code": "MAP_LABEL_LOOKUP_REQUIRED",
        "source_ref_type_code": None,
        "source_ref_id": None,
        "apply_allowed": False,
        "reason": "local water body/area/channel evidence has no usable name",
    }


async def _linked_area_name_candidate(session: AsyncSession, nearest_water_body: WaterContext | None) -> dict[str, Any] | None:
    if nearest_water_body is None or not isinstance(nearest_water_body.raw, NavigationWaterBody):
        return None
    body = nearest_water_body.raw
    area_ids = [int(item) for item in (body.source_water_area_ids_json or []) if _is_int_like(item)]
    if not area_ids:
        link_rows = list(
            (
                await session.execute(
                    select(NavigationWaterBodyFeatureLink.water_area_id).where(
                        NavigationWaterBodyFeatureLink.water_body_id == int(body.id)
                    )
                )
            ).scalars()
        )
        area_ids = [int(item) for item in link_rows if item is not None]
    if not area_ids:
        return None
    rows = list((await session.execute(select(NavigationWaterArea).where(NavigationWaterArea.id.in_(area_ids)))).scalars())
    for row in rows:
        name = _water_area_name(row)
        if _usable_name(name):
            return {
                "candidate_name": name,
                "confidence_score": 94,
                "source_code": "LINKED_WATER_AREA_MAP_LABEL",
                "source_ref_type_code": "WATER_AREA",
                "source_ref_id": int(row.id),
                "apply_allowed": True,
                "reason": "unnamed production water body is linked to a named local water-area feature",
            }
    return None


async def _maybe_apply_name_update(
    *,
    nearest_water_body: WaterContext | None,
    name_candidate: dict[str, Any],
    apply_name_update: bool,
) -> dict[str, Any] | None:
    if nearest_water_body is None or not isinstance(nearest_water_body.raw, NavigationWaterBody):
        return None
    body = nearest_water_body.raw
    if _usable_name(_water_body_name(body)):
        return None
    candidate = str(name_candidate.get("candidate_name") or "").strip()
    score = int(name_candidate.get("confidence_score") or 0)
    if not candidate or score < 80 or not name_candidate.get("apply_allowed"):
        return None
    update = {
        "water_body_id": int(body.id),
        "old_name": _water_body_name(body),
        "new_name": candidate,
        "confidence_score": score,
        "name_source_code": AUTO_NAME_SOURCE,
        "candidate_source_code": name_candidate.get("source_code"),
        "applied": bool(apply_name_update),
    }
    if apply_name_update:
        body.production_name = candidate
        body.display_name = candidate
        body.name_status_code = "PRODUCTION_NAMED"
        body.name_source_code = AUTO_NAME_SOURCE
        body.name_note = (
            "Auto named by classify_route_repair_queue from linked/local map water evidence "
            f"({name_candidate.get('source_code')})."
        )
    return update


def _endpoint_action(
    *,
    issue_codes: set[str],
    nearest_graph: GraphEdgeContext | None,
    nearest_water: WaterContext | None,
    access_water_threshold_m: float,
    graph_near_threshold_m: float,
    graph_snap_threshold_m: float,
    non_water_threshold_m: float,
) -> tuple[str, str]:
    graph_distance = nearest_graph.distance_m if nearest_graph else math.inf
    water_distance = nearest_water.distance_m if nearest_water else math.inf
    if water_distance > non_water_threshold_m and graph_distance > graph_snap_threshold_m:
        return "NODE_COORDINATE_OR_NON_WATER_DATA_REPAIR", "ENDPOINT_NOT_NEAR_LOCAL_WATER_OR_GRAPH"
    if issue_codes.intersection(CONNECTIVITY_ISSUES) and graph_distance <= graph_near_threshold_m:
        return "GRAPH_CONNECTIVITY_REPAIR_CANDIDATE", "ENDPOINT_NEAR_GRAPH_BUT_COMPONENT_DISCONNECTED"
    if issue_codes.intersection(TOO_FAR_ISSUES) and water_distance <= access_water_threshold_m and graph_distance > graph_near_threshold_m:
        return "AUTO_ACCESS_SEED_CANDIDATE", "ENDPOINT_NEAR_WATER_BUT_MISSING_GRAPH_ACCESS"
    if water_distance <= access_water_threshold_m and graph_distance > graph_snap_threshold_m:
        return "AUTO_BRANCH_CENTERLINE_AND_BOUNDARY_SEED_CANDIDATE", "LOCAL_WATER_EXISTS_BUT_GRAPH_COVERAGE_MISSING"
    if graph_distance <= graph_snap_threshold_m:
        return "SNAP_OR_CONNECTOR_REPAIR_CANDIDATE", "ENDPOINT_WITHIN_GRAPH_SNAP_RANGE"
    return "NEED_MORE_SEED_DATA", "NO_SAFE_LOCAL_REPAIR_CLASSIFICATION"


def _graph_context_payload(value: GraphEdgeContext | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "edge_id": value.edge_id,
        "channel_id": value.channel_id,
        "channel_name": value.channel_name,
        "source_type_code": value.source_type_code,
        "quality_code": value.quality_code,
        "distance_m": round(value.distance_m, 2),
        "nearest_point": [round(value.nearest_lng, 7), round(value.nearest_lat, 7)],
    }


def _water_context_payload(value: WaterContext | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "source_type_code": value.source_type_code,
        "ref_id": value.ref_id,
        "name": value.name,
        "name_status_code": value.name_status_code,
        "source_layer_name": value.source_layer_name,
        "water_level": value.water_level,
        "water_type_code": value.water_type_code,
        "distance_m": round(value.distance_m, 2),
        "nearest_point": [round(value.nearest_lng, 7), round(value.nearest_lat, 7)],
    }


def _summary(
    *,
    report: dict[str, Any],
    active_graph: NavigationGraphVersion | None,
    endpoint_items: list[dict[str, Any]],
    pair_actions: list[dict[str, Any]],
    name_updates: list[dict[str, Any]],
) -> dict[str, Any]:
    endpoint_action_counts = Counter(item["repair_action_code"] for item in endpoint_items)
    endpoint_reason_counts = Counter(item["reason_code"] for item in endpoint_items)
    pair_action_counts = Counter(item["repair_action_code"] for item in pair_actions)
    unnamed_candidates = [
        item
        for item in endpoint_items
        if (item.get("water_name_candidate") or {}).get("candidate_name")
        and item.get("nearest_water_body")
        and not _usable_name((item.get("nearest_water_body") or {}).get("name"))
    ]
    return {
        "source_selected_pair_count": ((report.get("summary") or {}).get("selected_pair_count")),
        "source_success_count": ((report.get("summary") or {}).get("success_count")),
        "source_failed_count": ((report.get("summary") or {}).get("failed_count")),
        "source_hard_issue_count": ((report.get("summary") or {}).get("hard_issue_count")),
        "active_graph_version_id": int(active_graph.id) if active_graph else None,
        "problem_endpoint_count": len(endpoint_items),
        "pair_action_count": len(pair_actions),
        "endpoint_action_counts": dict(sorted(endpoint_action_counts.items())),
        "endpoint_reason_counts": dict(sorted(endpoint_reason_counts.items())),
        "pair_action_counts": dict(sorted(pair_action_counts.items())),
        "unnamed_water_name_candidate_count": len(unnamed_candidates),
        "name_update_candidate_count": len(name_updates),
        "name_update_applied_count": sum(1 for item in name_updates if item.get("applied")),
    }


def _geojson(endpoint_items: list[dict[str, Any]]) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for item in endpoint_items:
        endpoint = item["endpoint"]
        lng = float(endpoint["longitude"])
        lat = float(endpoint["latitude"])
        properties = {
            "feature_role": "problem_endpoint",
            "endpoint_id": endpoint["id"],
            "endpoint_name": endpoint["name"],
            "repair_action_code": item["repair_action_code"],
            "reason_code": item["reason_code"],
            "issue_codes": ",".join(item["issue_codes"]),
            "nearest_graph_distance_m": ((item.get("nearest_graph") or {}).get("distance_m")),
            "nearest_water_body_name": ((item.get("nearest_water_body") or {}).get("name")),
            "nearest_water_body_distance_m": ((item.get("nearest_water_body") or {}).get("distance_m")),
            "nearest_water_area_name": ((item.get("nearest_water_area") or {}).get("name")),
            "nearest_water_area_distance_m": ((item.get("nearest_water_area") or {}).get("distance_m")),
            "water_name_candidate": ((item.get("water_name_candidate") or {}).get("candidate_name")),
        }
        features.append({"type": "Feature", "properties": properties, "geometry": {"type": "Point", "coordinates": [lng, lat]}})
        graph_point = (item.get("nearest_graph") or {}).get("nearest_point")
        if graph_point:
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "feature_role": "endpoint_to_nearest_graph",
                        "endpoint_id": endpoint["id"],
                        "repair_action_code": item["repair_action_code"],
                    },
                    "geometry": {"type": "LineString", "coordinates": [[lng, lat], graph_point]},
                }
            )
        water_point = (item.get("nearest_water_body") or item.get("nearest_water_area") or {}).get("nearest_point")
        if water_point:
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "feature_role": "endpoint_to_nearest_water",
                        "endpoint_id": endpoint["id"],
                        "repair_action_code": item["repair_action_code"],
                    },
                    "geometry": {"type": "LineString", "coordinates": [[lng, lat], water_point]},
                }
            )
    return {"type": "FeatureCollection", "features": features}


def _graph_payload(row: NavigationGraphVersion | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": int(row.id),
        "version_code": row.version_code,
        "version_name": row.version_name,
        "scope_code": row.scope_code,
        "node_count": row.node_count,
        "edge_count": row.edge_count,
        "status_code": row.status_code,
        "is_active": row.is_active,
    }


def _geometry(value: Any) -> BaseGeometry | None:
    if not isinstance(value, dict):
        return None
    try:
        geometry = make_valid(shape(value))
    except Exception:
        return None
    return None if geometry.is_empty else geometry


def _distance_approx_m(left: BaseGeometry, right: BaseGeometry) -> float:
    try:
        p1, p2 = nearest_points(left, right)
        lat = math.radians((float(p1.y) + float(p2.y)) / 2.0)
        dx = (float(p1.x) - float(p2.x)) * 111_320.0 * math.cos(lat)
        dy = (float(p1.y) - float(p2.y)) * 110_540.0
        return math.hypot(dx, dy)
    except Exception:
        return 999_999_999.0


def _nearest_point_on_geometry(point: Point, geometry: BaseGeometry) -> Point:
    try:
        _left, right = nearest_points(point, geometry)
        return Point(float(right.x), float(right.y))
    except Exception:
        return point


def _water_body_name(row: NavigationWaterBody) -> str | None:
    return _first_usable_name(row.production_name, row.display_name, row.water_body_name, row.normalized_water_name)


def _water_area_name(row: NavigationWaterArea) -> str | None:
    return _first_usable_name(row.water_name, row.normalized_water_name, *_raw_property_names(row.raw_properties_json))


def _raw_property_names(properties: Any) -> list[str]:
    if not isinstance(properties, dict):
        return []
    keys = (
        "name",
        "Name",
        "NAME",
        "water_name",
        "WATER_NAME",
        "river_name",
        "RIVER_NAME",
        "名称",
        "水系名称",
        "河流名称",
    )
    values = [str(properties.get(key) or "").strip() for key in keys]
    return [value for value in values if value]


def _first_usable_name(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if _usable_name(text):
            return text
    return None


def _usable_name(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return not any(pattern.search(text) for pattern in UNNAMED_PATTERNS)


def _strip_water_suffix(value: str) -> str:
    text = value.strip()
    for suffix in ("航运干线", "高等级航道网", "相关水域", "航道", "水道", "河道"):
        if text.endswith(suffix) and len(text) > len(suffix) + 1:
            return text[: -len(suffix)]
    return text


def _valid_lng_lat(lng: float, lat: float) -> bool:
    return -180.0 <= float(lng) <= 180.0 and -90.0 <= float(lat) <= 90.0


def _is_int_like(value: Any) -> bool:
    try:
        int(value)
        return True
    except (TypeError, ValueError):
        return False


def _endpoint_sort_key(item: dict[str, Any]) -> tuple[int, float, int]:
    priority = {
        "AUTO_ACCESS_SEED_CANDIDATE": 0,
        "AUTO_BRANCH_CENTERLINE_AND_BOUNDARY_SEED_CANDIDATE": 1,
        "GRAPH_CONNECTIVITY_REPAIR_CANDIDATE": 2,
        "SNAP_OR_CONNECTOR_REPAIR_CANDIDATE": 3,
        "NEED_MORE_SEED_DATA": 4,
        "NODE_COORDINATE_OR_NON_WATER_DATA_REPAIR": 5,
    }.get(item.get("repair_action_code"), 9)
    water_distance = ((item.get("nearest_water_body") or item.get("nearest_water_area") or {}).get("distance_m"))
    return priority, float(water_distance if water_distance is not None else 999_999), int((item.get("endpoint") or {}).get("id") or 0)


if __name__ == "__main__":
    asyncio.run(main())
