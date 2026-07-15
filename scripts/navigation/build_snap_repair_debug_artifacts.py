"""Build GeoJSON/HTML debug artifacts for SNAP_REPAIR tasks."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import and_, or_, select
from shapely.geometry import LineString, Point, Polygon, mapping, shape
from shapely.ops import nearest_points

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models import (
    NavigationAnnotationTask,
    NavigationGraphEdge,
    NavigationGraphVersion,
    NavigationRouteQualityIssue,
    NavigationRouteRequest,
    NavigationRouteResult,
)
from app.models.navigation import NavigationRouteTrajectoryCache, NavigationWaterArea
from app.modules.navigation.engine.geo import line_length_km, nearest_point_on_line, point_distance_m


OUTPUT_DIR = Path("runtime/navigation-production/debug")
MAX_WATER_GEOMETRY_JSON_CHARS = 120_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create debug GeoJSON/HTML for a SNAP_REPAIR annotation task.")
    parser.add_argument("--task-id", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--nearest-graph-limit", type=int, default=5)
    parser.add_argument("--nearest-water-limit", type=int, default=5)
    parser.add_argument("--hifleet-line-limit", type=int, default=3)
    parser.add_argument("--hifleet-access-point-count", type=int, default=30)
    parser.add_argument("--hifleet-access-max-km", type=float, default=20.0)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    async with AsyncSessionLocal() as session:
        task = await session.get(NavigationAnnotationTask, args.task_id)
        if task is None:
            raise SystemExit(f"NavigationAnnotationTask not found: {args.task_id}")
        if task.task_type_code != "SNAP_REPAIR":
            raise SystemExit(f"Task {args.task_id} is {task.task_type_code}, not SNAP_REPAIR")
        issue = await session.get(NavigationRouteQualityIssue, task.target_id) if task.target_id else None
        result = await session.get(NavigationRouteResult, issue.route_result_id) if issue else None
        request = await session.get(NavigationRouteRequest, result.request_id) if result else None
        endpoint = _endpoint_point(task, issue, request)
        if endpoint is None:
            raise SystemExit(f"Task {args.task_id} has no endpoint geometry")
        role = _issue_role(issue.issue_type_code if issue else task.issue_summary)
        graph_version = await _active_graph_version(session, task.graph_version_id)
        features: list[dict[str, Any]] = []
        features.append(
            _feature(
                endpoint,
                {
                    "kind": "snap_repair_endpoint",
                    "task_id": task.id,
                    "role": role,
                    "issue_code": issue.issue_type_code if issue else None,
                    "issue_summary": task.issue_summary,
                },
            )
        )
        nearest_graph = await _nearest_graph_edges(
            session,
            endpoint,
            graph_version.id if graph_version else None,
            limit=max(1, int(args.nearest_graph_limit or 1)),
        )
        for item in nearest_graph:
            features.extend(item["features"])
        nearest_water = await _nearest_water_areas(
            session,
            endpoint,
            limit=max(1, int(args.nearest_water_limit or 1)),
        )
        for item in nearest_water:
            features.append(item["feature"])
        hifleet_refs = await _hifleet_references(
            session,
            request,
            endpoint=endpoint,
            limit=max(0, int(args.hifleet_line_limit or 0)),
            access_point_count=max(2, int(args.hifleet_access_point_count or 2)),
            access_max_km=max(0.0, float(args.hifleet_access_max_km or 0.0)),
        )
        for item in hifleet_refs:
            features.extend(item["features"])
        summary = _summary(
            task=task,
            issue=issue,
            result=result,
            request=request,
            graph_version=graph_version,
            endpoint=endpoint,
            role=role,
            nearest_graph=nearest_graph,
            nearest_water=nearest_water,
            hifleet_refs=hifleet_refs,
        )
        payload = {
            "type": "FeatureCollection",
            "properties": {
                "generated_at": datetime.now(UTC).isoformat(),
                "task_id": task.id,
                "task_type_code": task.task_type_code,
                "issue_summary": task.issue_summary,
                "graph_version_id": graph_version.id if graph_version else None,
                "graph_version_code": graph_version.version_code if graph_version else None,
                "repair_strategy_code": (task.suggestion_json or {}).get("repair_strategy_code"),
                "candidate_operation_code": (task.suggestion_json or {}).get("candidate_operation_code"),
                "guardrails": (task.suggestion_json or {}).get("guardrails"),
            },
            "features": features,
        }
        args.output_dir.mkdir(parents=True, exist_ok=True)
        base = args.output_dir / f"snap_repair_task_{task.id}"
        geojson_path = base.with_suffix(".geojson")
        summary_path = base.with_suffix(".summary.json")
        html_path = base.with_suffix(".html")
        geojson_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        html_path.write_text(_html(task.id, payload, summary), encoding="utf-8")
        report = {
            "task_id": task.id,
            "geojson_path": str(geojson_path),
            "summary_path": str(summary_path),
            "html_path": str(html_path),
            "feature_count": len(features),
            "nearest_graph_edge_count": len(nearest_graph),
            "nearest_water_area_count": len(nearest_water),
            "hifleet_reference_count": len(hifleet_refs),
            "closest_graph_edge_distance_m": summary["nearest_graph_edges"][0]["distance_m"] if summary["nearest_graph_edges"] else None,
            "closest_water_area": summary["nearest_water_areas"][0] if summary["nearest_water_areas"] else None,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))


async def _active_graph_version(session, graph_version_id: int | None) -> NavigationGraphVersion | None:
    if graph_version_id:
        row = await session.get(NavigationGraphVersion, graph_version_id)
        if row is not None:
            return row
    return (
        await session.execute(
            select(NavigationGraphVersion)
            .where(
                NavigationGraphVersion.is_active.is_(True),
                NavigationGraphVersion.status_code == "READY",
                NavigationGraphVersion.scope_code.not_like("MVP%"),
                NavigationGraphVersion.edge_count > 0,
            )
            .order_by(NavigationGraphVersion.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _endpoint_point(
    task: NavigationAnnotationTask,
    issue: NavigationRouteQualityIssue | None,
    request: NavigationRouteRequest | None,
) -> Point | None:
    geometry_json = task.geometry_json or (task.suggestion_json or {}).get("candidate_endpoint_geometry_json")
    if isinstance(geometry_json, dict):
        try:
            geometry = shape(geometry_json)
            if isinstance(geometry, Point):
                return geometry
        except Exception:  # noqa: BLE001
            pass
    role = _issue_role(issue.issue_type_code if issue else task.issue_summary)
    if request is not None and role == "ORIGIN":
        return Point(float(request.origin_lng), float(request.origin_lat))
    if request is not None and role == "DESTINATION":
        return Point(float(request.destination_lng), float(request.destination_lat))
    return None


def _issue_role(issue_code: str | None) -> str:
    code = str(issue_code or "").upper()
    if code.startswith("DESTINATION"):
        return "DESTINATION"
    return "ORIGIN"


async def _nearest_graph_edges(session, endpoint: Point, graph_version_id: int | None, *, limit: int) -> list[dict[str, Any]]:
    if graph_version_id is None:
        return []
    rows = list(
        (
            await session.execute(
                select(NavigationGraphEdge)
                .where(
                    NavigationGraphEdge.graph_version_id == graph_version_id,
                    NavigationGraphEdge.routing_enabled.is_(True),
                    NavigationGraphEdge.geometry_json.is_not(None),
                )
                .order_by(NavigationGraphEdge.id)
            )
        ).scalars()
    )
    candidates: list[tuple[float, NavigationGraphEdge, Point, LineString]] = []
    for row in rows:
        try:
            geometry = shape(row.geometry_json)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(geometry, LineString) or geometry.is_empty:
            continue
        projected = nearest_point_on_line(geometry, endpoint)
        candidates.append((point_distance_m(endpoint, projected), row, projected, geometry))
    output: list[dict[str, Any]] = []
    for distance_m, row, projected, geometry in sorted(candidates, key=lambda item: item[0])[:limit]:
        output.append(
            {
                "distance_m": distance_m,
                "edge_id": row.id,
                "edge_code": row.edge_code,
                "channel_id": row.channel_id,
                "snap_point": [float(projected.x), float(projected.y)],
                "features": [
                    _feature(
                        geometry,
                        {
                            "kind": "nearest_graph_edge",
                            "edge_id": row.id,
                            "edge_code": row.edge_code,
                            "channel_id": row.channel_id,
                            "quality_code": row.quality_code,
                            "distance_m": round(distance_m, 1),
                        },
                    ),
                    _feature(
                        LineString([(endpoint.x, endpoint.y), (projected.x, projected.y)]),
                        {
                            "kind": "endpoint_to_nearest_graph_edge_reference",
                            "edge_id": row.id,
                            "distance_m": round(distance_m, 1),
                            "not_for_navigation": True,
                        },
                    ),
                ],
            }
        )
    return output


async def _nearest_water_areas(session, endpoint: Point, *, limit: int) -> list[dict[str, Any]]:
    lng = float(endpoint.x)
    lat = float(endpoint.y)
    rows = list(
        (
            await session.execute(
                select(NavigationWaterArea)
                .where(
                    NavigationWaterArea.is_enabled.is_(True),
                    NavigationWaterArea.bbox_min_lng <= lng + 0.3,
                    NavigationWaterArea.bbox_max_lng >= lng - 0.3,
                    NavigationWaterArea.bbox_min_lat <= lat + 0.3,
                    NavigationWaterArea.bbox_max_lat >= lat - 0.3,
                )
                .order_by(NavigationWaterArea.source_layer_order, NavigationWaterArea.id)
                .limit(1000)
            )
        ).scalars()
    )
    candidates: list[tuple[float, NavigationWaterArea, Any]] = []
    for row in rows:
        try:
            geometry = shape(row.geometry_json)
        except Exception:  # noqa: BLE001
            continue
        candidates.append((float(geometry.distance(endpoint)), row, geometry))
    output: list[dict[str, Any]] = []
    for degree_distance, row, geometry in sorted(candidates, key=lambda item: item[0])[:limit]:
        display_geometry, geometry_source = _water_area_display_geometry(row, geometry)
        distance_m = _geometry_distance_m(endpoint, geometry)
        output.append(
            {
                "degree_distance": degree_distance,
                "distance_m": distance_m,
                "water_area_id": row.id,
                "water_name": row.water_name,
                "water_type_code": row.water_type_code,
                "geometry_source": geometry_source,
                "feature": _feature(
                    display_geometry,
                    {
                        "kind": "nearest_water_area",
                        "water_area_id": row.id,
                        "water_name": row.water_name,
                        "water_type_code": row.water_type_code,
                        "source_layer_name": row.source_layer_name,
                        "degree_distance": degree_distance,
                        "distance_m": round(distance_m, 1) if distance_m is not None else None,
                        "geometry_source": geometry_source,
                    },
                ),
            }
        )
    return output


async def _hifleet_references(
    session,
    request: NavigationRouteRequest | None,
    *,
    endpoint: Point,
    limit: int,
    access_point_count: int,
    access_max_km: float,
) -> list[dict[str, Any]]:
    if request is None or limit <= 0:
        return []
    eps = 0.000001
    forward = and_(
        NavigationRouteTrajectoryCache.origin_lng.between(float(request.origin_lng) - eps, float(request.origin_lng) + eps),
        NavigationRouteTrajectoryCache.origin_lat.between(float(request.origin_lat) - eps, float(request.origin_lat) + eps),
        NavigationRouteTrajectoryCache.destination_lng.between(
            float(request.destination_lng) - eps, float(request.destination_lng) + eps
        ),
        NavigationRouteTrajectoryCache.destination_lat.between(
            float(request.destination_lat) - eps, float(request.destination_lat) + eps
        ),
    )
    reverse = and_(
        NavigationRouteTrajectoryCache.origin_lng.between(
            float(request.destination_lng) - eps,
            float(request.destination_lng) + eps,
        ),
        NavigationRouteTrajectoryCache.origin_lat.between(
            float(request.destination_lat) - eps,
            float(request.destination_lat) + eps,
        ),
        NavigationRouteTrajectoryCache.destination_lng.between(float(request.origin_lng) - eps, float(request.origin_lng) + eps),
        NavigationRouteTrajectoryCache.destination_lat.between(float(request.origin_lat) - eps, float(request.origin_lat) + eps),
    )
    ref_conditions = [forward, reverse]
    if request.origin_ref_type_code and request.origin_ref_id:
        ref_conditions.append(
            or_(
                and_(
                    NavigationRouteTrajectoryCache.origin_ref_type_code == request.origin_ref_type_code,
                    NavigationRouteTrajectoryCache.origin_ref_id == request.origin_ref_id,
                ),
                and_(
                    NavigationRouteTrajectoryCache.destination_ref_type_code == request.origin_ref_type_code,
                    NavigationRouteTrajectoryCache.destination_ref_id == request.origin_ref_id,
                ),
            )
        )
    if request.destination_ref_type_code and request.destination_ref_id:
        ref_conditions.append(
            or_(
                and_(
                    NavigationRouteTrajectoryCache.origin_ref_type_code == request.destination_ref_type_code,
                    NavigationRouteTrajectoryCache.origin_ref_id == request.destination_ref_id,
                ),
                and_(
                    NavigationRouteTrajectoryCache.destination_ref_type_code == request.destination_ref_type_code,
                    NavigationRouteTrajectoryCache.destination_ref_id == request.destination_ref_id,
                ),
            )
        )
    row_limit = max(limit * 4, limit)
    rows = list(
        (
            await session.execute(
                select(NavigationRouteTrajectoryCache)
                .where(
                    NavigationRouteTrajectoryCache.provider_code == "HIFLEET",
                    NavigationRouteTrajectoryCache.geometry_json.is_not(None),
                    or_(*ref_conditions),
                )
                .order_by(NavigationRouteTrajectoryCache.id.desc())
                .limit(row_limit)
            )
        ).scalars()
    )
    output: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for row in rows:
        if row.id in seen_ids:
            continue
        seen_ids.add(row.id)
        try:
            geometry = shape(row.geometry_json)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(geometry, LineString) or len(geometry.coords) < 2:
            continue
        access_line, access_side, endpoint_gap_m, access_truncated = _hifleet_access_candidate(
            geometry,
            endpoint,
            access_point_count=access_point_count,
            access_max_km=access_max_km,
        )
        features = [
            _feature(
                geometry,
                {
                    "kind": "hifleet_reference_route",
                    "trajectory_cache_id": row.id,
                    "hifleet_cache_id": row.hifleet_cache_id,
                    "distance_km": float(row.distance_km) if row.distance_km is not None else None,
                    "point_count": row.point_count,
                    "reference_only": True,
                },
            )
        ]
        if access_line is not None:
            access_length_km = line_length_km(access_line)
            features.append(
                _feature(
                    access_line,
                    {
                        "kind": "hifleet_access_candidate",
                        "trajectory_cache_id": row.id,
                        "side": access_side,
                        "endpoint_gap_m": round(endpoint_gap_m, 1),
                        "point_count": len(access_line.coords),
                        "length_km": round(access_length_km, 3),
                        "truncated_by_max_km": access_truncated,
                        "max_candidate_km": access_max_km,
                        "requires_densification": access_length_km > access_max_km if access_max_km > 0 else False,
                        "draft_only": True,
                        "requires_validation": True,
                    },
                )
            )
        output.append(
            {
                "cache_id": row.id,
                "hifleet_cache_id": row.hifleet_cache_id,
                "distance_km": float(row.distance_km) if row.distance_km is not None else None,
                "point_count": row.point_count,
                "access_side": access_side,
                "access_endpoint_gap_m": endpoint_gap_m,
                "access_length_km": line_length_km(access_line) if access_line is not None else None,
                "access_truncated_by_max_km": access_truncated,
                "access_max_km": access_max_km,
                "access_requires_densification": (
                    line_length_km(access_line) > access_max_km if access_line is not None and access_max_km > 0 else False
                ),
                "features": features,
            }
        )
        if len(output) >= limit:
            break
    return output


def _water_area_display_geometry(row: NavigationWaterArea, geometry) -> tuple[Any, str]:
    for source, geometry_json in (
        ("simplified_low", row.simplified_geometry_low_json),
        ("simplified_mid", row.simplified_geometry_mid_json),
        ("simplified_high", row.simplified_geometry_high_json),
    ):
        if not isinstance(geometry_json, dict):
            continue
        try:
            return shape(geometry_json), source
        except Exception:  # noqa: BLE001
            continue
    try:
        if len(json.dumps(row.geometry_json, ensure_ascii=False)) <= MAX_WATER_GEOMETRY_JSON_CHARS:
            return geometry, "full"
    except Exception:  # noqa: BLE001
        pass
    return _bbox_polygon(row, geometry), "bbox"


def _bbox_polygon(row: NavigationWaterArea, fallback_geometry) -> Polygon:
    values = [row.bbox_min_lng, row.bbox_min_lat, row.bbox_max_lng, row.bbox_max_lat]
    if all(value is not None for value in values):
        min_lng, min_lat, max_lng, max_lat = [float(value) for value in values]
    else:
        min_lng, min_lat, max_lng, max_lat = fallback_geometry.bounds
    return Polygon([(min_lng, min_lat), (max_lng, min_lat), (max_lng, max_lat), (min_lng, max_lat), (min_lng, min_lat)])


def _geometry_distance_m(endpoint: Point, geometry) -> float | None:
    try:
        if geometry.contains(endpoint) or geometry.touches(endpoint):
            return 0.0
        nearest, _ = nearest_points(geometry, endpoint)
        return point_distance_m(endpoint, nearest)
    except Exception:  # noqa: BLE001
        return None


def _hifleet_access_candidate(
    line: LineString,
    endpoint: Point,
    *,
    access_point_count: int,
    access_max_km: float,
) -> tuple[LineString | None, str, float, bool]:
    coords = [(float(lng), float(lat)) for lng, lat, *_ in line.coords]
    if len(coords) < 2:
        return None, "NONE", 0.0, False
    start_gap_m = point_distance_m(endpoint, Point(coords[0]))
    end_gap_m = point_distance_m(endpoint, Point(coords[-1]))
    point_count = max(2, min(access_point_count, len(coords)))
    if start_gap_m <= end_gap_m:
        raw_access_coords = coords[:point_count]
        side = "ROUTE_START"
        endpoint_gap_m = start_gap_m
    else:
        raw_access_coords = list(reversed(coords[-point_count:]))
        side = "ROUTE_END"
        endpoint_gap_m = end_gap_m
    access_coords, truncated = _limit_access_coords(raw_access_coords, access_max_km=access_max_km)
    if len(access_coords) < 2:
        return None, side, endpoint_gap_m, truncated
    return LineString(access_coords), side, endpoint_gap_m, truncated


def _limit_access_coords(coords: list[tuple[float, float]], *, access_max_km: float) -> tuple[list[tuple[float, float]], bool]:
    if access_max_km <= 0 or len(coords) <= 2:
        return coords, False
    limited = [coords[0]]
    for coord in coords[1:]:
        limited.append(coord)
        if len(limited) >= 2 and line_length_km(LineString(limited)) >= access_max_km:
            return limited, len(limited) < len(coords)
    return limited, False


def _summary(
    *,
    task: NavigationAnnotationTask,
    issue: NavigationRouteQualityIssue | None,
    result: NavigationRouteResult | None,
    request: NavigationRouteRequest | None,
    graph_version: NavigationGraphVersion | None,
    endpoint: Point,
    role: str,
    nearest_graph: list[dict[str, Any]],
    nearest_water: list[dict[str, Any]],
    hifleet_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "task": {
            "id": task.id,
            "task_no": task.task_no,
            "task_type_code": task.task_type_code,
            "status_code": task.status_code,
            "priority_code": task.priority_code,
            "issue_summary": task.issue_summary,
            "repair_strategy_code": (task.suggestion_json or {}).get("repair_strategy_code"),
            "candidate_operation_code": (task.suggestion_json or {}).get("candidate_operation_code"),
        },
        "issue": {
            "id": issue.id if issue else None,
            "issue_type_code": issue.issue_type_code if issue else None,
            "severity_code": issue.severity_code if issue else None,
            "message": issue.message if issue else None,
        },
        "route_result": {
            "id": result.id if result else None,
            "provider_code": result.provider_code if result else None,
            "quality_code": result.quality_code if result else None,
            "distance_km": float(result.distance_km) if result and result.distance_km is not None else None,
        },
        "route_request": {
            "id": request.id if request else None,
            "origin": _request_endpoint(request, "ORIGIN") if request else None,
            "destination": _request_endpoint(request, "DESTINATION") if request else None,
        },
        "endpoint": {
            "role": role,
            "lng": float(endpoint.x),
            "lat": float(endpoint.y),
        },
        "graph_version": {
            "id": graph_version.id if graph_version else None,
            "version_code": graph_version.version_code if graph_version else None,
            "status_code": graph_version.status_code if graph_version else None,
            "edge_count": graph_version.edge_count if graph_version else None,
        },
        "nearest_graph_edges": [
            {
                "edge_id": item.get("edge_id"),
                "edge_code": item.get("edge_code"),
                "channel_id": item.get("channel_id"),
                "distance_m": round(float(item.get("distance_m") or 0), 1),
                "snap_point": item.get("snap_point"),
                "not_for_navigation": True,
            }
            for item in nearest_graph
        ],
        "nearest_water_areas": [
            {
                "water_area_id": item.get("water_area_id"),
                "water_name": item.get("water_name"),
                "water_type_code": item.get("water_type_code"),
                "degree_distance": item.get("degree_distance"),
                "distance_m": round(float(item["distance_m"]), 1) if item.get("distance_m") is not None else None,
                "geometry_source": item.get("geometry_source"),
            }
            for item in nearest_water
        ],
        "hifleet_references": [
            {
                "trajectory_cache_id": item.get("cache_id"),
                "hifleet_cache_id": item.get("hifleet_cache_id"),
                "distance_km": item.get("distance_km"),
                "point_count": item.get("point_count"),
                "access_side": item.get("access_side"),
                "access_endpoint_gap_m": round(float(item["access_endpoint_gap_m"]), 1)
                if item.get("access_endpoint_gap_m") is not None
                else None,
                "access_length_km": round(float(item["access_length_km"]), 3)
                if item.get("access_length_km") is not None
                else None,
                "access_truncated_by_max_km": bool(item.get("access_truncated_by_max_km")),
                "access_max_km": item.get("access_max_km"),
                "access_requires_densification": bool(item.get("access_requires_densification")),
                "draft_only": True,
            }
            for item in hifleet_refs
        ],
        "operator_notes": [
            "Endpoint-to-graph straight lines are distance references only and must not be published as navigation geometry.",
            "Use HiFleet access candidates together with local water areas and centerline drafts, then rebuild the graph and rerun the route matrix.",
            "Do not fix this class of issue by widening the graph snap threshold.",
        ],
    }


def _request_endpoint(request: NavigationRouteRequest, role: str) -> dict[str, Any]:
    if role == "ORIGIN":
        return {
            "lng": float(request.origin_lng),
            "lat": float(request.origin_lat),
            "name": request.origin_name,
            "ref_type_code": request.origin_ref_type_code,
            "ref_id": request.origin_ref_id,
        }
    return {
        "lng": float(request.destination_lng),
        "lat": float(request.destination_lat),
        "name": request.destination_name,
        "ref_type_code": request.destination_ref_type_code,
        "ref_id": request.destination_ref_id,
    }


def _feature(geometry, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": mapping(geometry),
        "properties": properties,
    }


def _html(task_id: int, payload: dict[str, Any], summary: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
    summary_json = json.dumps(summary, ensure_ascii=False, indent=2)
    return """<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <title>SNAP_REPAIR Task __TASK_ID__</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, \"Segoe UI\", sans-serif; margin: 24px; color: #111827; }
    h1 { font-size: 20px; margin-bottom: 8px; }
    h2 { font-size: 16px; margin: 24px 0 8px; }
    pre { background: #f8fafc; border: 1px solid #dbe3ef; padding: 16px; overflow: auto; border-radius: 6px; }
    .note { max-width: 1040px; line-height: 1.6; color: #374151; }
    .panel { max-width: 1120px; }
    .map { width: 100%; max-width: 1120px; height: 560px; border: 1px solid #dbe3ef; background: #f8fafc; border-radius: 6px; }
    .legend { display: flex; flex-wrap: wrap; gap: 12px; margin: 10px 0 0; font-size: 12px; color: #4b5563; }
    .dot { display: inline-block; width: 10px; height: 10px; margin-right: 4px; border-radius: 999px; vertical-align: -1px; }
    table { border-collapse: collapse; width: 100%; max-width: 1120px; font-size: 13px; }
    td, th { border: 1px solid #dbe3ef; padding: 8px 10px; text-align: left; vertical-align: top; }
    th { background: #f8fafc; }
  </style>
</head>
<body>
  <h1>SNAP_REPAIR Task __TASK_ID__</h1>
  <p class=\"note\">该文件是人工修复 seed/Graph 接入段的调试包。GeoJSON 中的 endpoint_to_nearest_graph_edge_reference 只是测距参考线，不能作为可发布航线；应结合 HiFleet 参考线、水域面、中心线草稿重新生产接入段。</p>
  <svg class=\"map\" id=\"map\" viewBox=\"0 0 1120 560\" role=\"img\" aria-label=\"SNAP_REPAIR debug map\"></svg>
  <div class=\"legend\">
    <span><span class=\"dot\" style=\"background:#dc2626\"></span>Endpoint</span>
    <span><span class=\"dot\" style=\"background:#2563eb\"></span>HiFleet route</span>
    <span><span class=\"dot\" style=\"background:#16a34a\"></span>Access candidate</span>
    <span><span class=\"dot\" style=\"background:#f97316\"></span>Nearest graph</span>
    <span><span class=\"dot\" style=\"background:#94a3b8\"></span>Distance reference</span>
    <span><span class=\"dot\" style=\"background:#38bdf8\"></span>Water area</span>
  </div>
  <h2>Summary</h2>
  <div class=\"panel\" id=\"summary-table\"></div>
  <h2>GeoJSON</h2>
  <pre id=\"geojson\"></pre>
  <script type=\"application/json\" id=\"payload\">__PAYLOAD_JSON__</script>
  <script type=\"application/json\" id=\"summary\">__SUMMARY_JSON__</script>
  <script>
    const payload = JSON.parse(document.getElementById('payload').textContent);
    const summary = JSON.parse(document.getElementById('summary').textContent);
    document.getElementById('geojson').textContent = JSON.stringify(payload, null, 2);

    function flattenCoords(geometry) {
      if (!geometry) return [];
      const type = geometry.type;
      const coords = geometry.coordinates || [];
      if (type === 'Point') return [coords];
      if (type === 'LineString') return coords;
      if (type === 'Polygon') return coords.flat();
      if (type === 'MultiLineString') return coords.flat();
      if (type === 'MultiPolygon') return coords.flat(2);
      return [];
    }

    const allCoords = payload.features.flatMap((feature) => flattenCoords(feature.geometry));
    const lngs = allCoords.map((item) => item[0]);
    const lats = allCoords.map((item) => item[1]);
    const minLng = Math.min(...lngs);
    const maxLng = Math.max(...lngs);
    const minLat = Math.min(...lats);
    const maxLat = Math.max(...lats);
    const padLng = Math.max((maxLng - minLng) * 0.08, 0.01);
    const padLat = Math.max((maxLat - minLat) * 0.08, 0.01);
    const bounds = { minLng: minLng - padLng, maxLng: maxLng + padLng, minLat: minLat - padLat, maxLat: maxLat + padLat };
    const width = 1120;
    const height = 560;

    function project(coord) {
      const x = ((coord[0] - bounds.minLng) / (bounds.maxLng - bounds.minLng || 1)) * width;
      const y = height - ((coord[1] - bounds.minLat) / (bounds.maxLat - bounds.minLat || 1)) * height;
      return [x, y];
    }

    function pathForCoords(coords, closePath = false) {
      return coords.map((coord, index) => {
        const [x, y] = project(coord);
        return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(' ') + (closePath ? ' Z' : '');
    }

    function styleFor(kind) {
      if (kind === 'snap_repair_endpoint') return { stroke: '#dc2626', fill: '#dc2626', width: 2, dash: '' };
      if (kind === 'hifleet_reference_route') return { stroke: '#2563eb', fill: 'none', width: 3, dash: '' };
      if (kind === 'hifleet_access_candidate') return { stroke: '#16a34a', fill: 'none', width: 5, dash: '' };
      if (kind === 'nearest_graph_edge') return { stroke: '#f97316', fill: 'none', width: 3, dash: '' };
      if (kind === 'endpoint_to_nearest_graph_edge_reference') return { stroke: '#64748b', fill: 'none', width: 2, dash: '8 8' };
      if (kind === 'nearest_water_area') return { stroke: '#0284c7', fill: '#bae6fd', width: 1, dash: '' };
      return { stroke: '#111827', fill: 'none', width: 1, dash: '' };
    }

    function addPath(svg, d, style, title) {
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', d);
      path.setAttribute('fill', style.fill);
      path.setAttribute('stroke', style.stroke);
      path.setAttribute('stroke-width', style.width);
      if (style.dash) path.setAttribute('stroke-dasharray', style.dash);
      path.setAttribute('opacity', style.fill === 'none' ? '0.92' : '0.45');
      const titleNode = document.createElementNS('http://www.w3.org/2000/svg', 'title');
      titleNode.textContent = title;
      path.appendChild(titleNode);
      svg.appendChild(path);
    }

    const svg = document.getElementById('map');
    for (const feature of payload.features) {
      const kind = feature.properties.kind;
      const style = styleFor(kind);
      const title = `${kind} ${JSON.stringify(feature.properties)}`;
      const geometry = feature.geometry || {};
      if (geometry.type === 'Point') {
        const [x, y] = project(geometry.coordinates);
        const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        circle.setAttribute('cx', x.toFixed(1));
        circle.setAttribute('cy', y.toFixed(1));
        circle.setAttribute('r', kind === 'snap_repair_endpoint' ? '7' : '4');
        circle.setAttribute('fill', style.fill);
        circle.setAttribute('stroke', '#ffffff');
        circle.setAttribute('stroke-width', '2');
        const titleNode = document.createElementNS('http://www.w3.org/2000/svg', 'title');
        titleNode.textContent = title;
        circle.appendChild(titleNode);
        svg.appendChild(circle);
      } else if (geometry.type === 'LineString') {
        addPath(svg, pathForCoords(geometry.coordinates), style, title);
      } else if (geometry.type === 'Polygon') {
        for (const ring of geometry.coordinates) addPath(svg, pathForCoords(ring, true), style, title);
      } else if (geometry.type === 'MultiLineString') {
        for (const line of geometry.coordinates) addPath(svg, pathForCoords(line), style, title);
      } else if (geometry.type === 'MultiPolygon') {
        for (const polygon of geometry.coordinates) {
          for (const ring of polygon) addPath(svg, pathForCoords(ring, true), style, title);
        }
      }
    }

    const closestGraph = summary.nearest_graph_edges?.[0];
    const closestWater = summary.nearest_water_areas?.[0];
    const hifleet = summary.hifleet_references?.[0];
    document.getElementById('summary-table').innerHTML = `
      <table>
        <tbody>
          <tr><th>Endpoint</th><td>${summary.endpoint.role} ${summary.endpoint.lng}, ${summary.endpoint.lat}</td></tr>
          <tr><th>Issue</th><td>${summary.issue.issue_type_code || ''} ${summary.issue.message || ''}</td></tr>
          <tr><th>Graph</th><td>${summary.graph_version.version_code || ''}, edges=${summary.graph_version.edge_count || 0}</td></tr>
          <tr><th>Closest graph edge</th><td>${closestGraph ? `${closestGraph.edge_code} / ${closestGraph.distance_m} m` : 'none'}</td></tr>
          <tr><th>Closest water area</th><td>${closestWater ? `${closestWater.water_name || closestWater.water_area_id} / ${closestWater.distance_m} m` : 'none'}</td></tr>
          <tr><th>HiFleet access</th><td>${hifleet ? `cache=${hifleet.trajectory_cache_id}, side=${hifleet.access_side}, length=${hifleet.access_length_km} km` : 'none'}</td></tr>
        </tbody>
      </table>`;
  </script>
</body>
</html>
""".replace("__TASK_ID__", str(task_id)).replace("__PAYLOAD_JSON__", payload_json).replace("__SUMMARY_JSON__", summary_json)


if __name__ == "__main__":
    asyncio.run(main())
