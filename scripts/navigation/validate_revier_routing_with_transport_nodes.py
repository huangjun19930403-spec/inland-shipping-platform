from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pyproj import Geod
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.integrations.config_keys import HIFLEET_CONFIG_PROFILE, HIFLEET_ENABLED
from app.integrations.hifleet.client import HifleetRouteClient
from app.integrations.http.route_geometry_types import RouteGeometryQuery
from app.models import NavigationGraphEdge, NavigationGraphNode, NavigationGraphVersion
from app.models.address import TransportNode
from app.modules.navigation.production_pipeline.constants import DEFAULT_RUNTIME_DIR, REVIER_GRAPH_VERSION_CODE
from app.modules.navigation.routing_service import NavigationRoutingEngineService
from app.modules.navigation.schemas import NavigationEndpointRequest, NavigationRouteGenerateRequest
from app.modules.system.runtime_config import RuntimeConfigService

GEOD = Geod(ellps="WGS84")
DEFAULT_REPORT_PATH = DEFAULT_RUNTIME_DIR / "reports" / "transport_node_routing_validation_report.json"
HIFLEET_DISTANCE_RATIO_MIN = 0.94
HIFLEET_DISTANCE_RATIO_MAX = 1.12
HIFLEET_MAX_DEVIATION_KM = 5.0
HIFLEET_P90_DEVIATION_KM = 4.0


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    _, _, meters = GEOD.inv(a[0], a[1], b[0], b[1])
    return abs(float(meters)) / 1000.0


def _line_length_km(points: list[tuple[float, float]]) -> float:
    total = 0.0
    for start, end in zip(points, points[1:]):
        total += _distance_km(start, end)
    return total


def _components(node_ids: set[int], edges: list[NavigationGraphEdge]) -> dict[int, int]:
    adjacency: dict[int, set[int]] = {node_id: set() for node_id in node_ids}
    for edge in edges:
        if not edge.routing_enabled:
            continue
        adjacency.setdefault(int(edge.from_node_id), set()).add(int(edge.to_node_id))
        adjacency.setdefault(int(edge.to_node_id), set()).add(int(edge.from_node_id))
    output: dict[int, int] = {}
    component_id = 0
    for node_id in sorted(adjacency):
        if node_id in output:
            continue
        component_id += 1
        queue = deque([node_id])
        output[node_id] = component_id
        while queue:
            current = queue.popleft()
            for neighbor in adjacency.get(current, set()):
                if neighbor not in output:
                    output[neighbor] = component_id
                    queue.append(neighbor)
    return output


def _candidate_pairs(nodes: list[NavigationGraphNode], *, sample_count: int) -> list[tuple[NavigationGraphNode, NavigationGraphNode]]:
    pairs: list[tuple[float, NavigationGraphNode, NavigationGraphNode]] = []
    for left_index, left in enumerate(nodes):
        for right in nodes[left_index + 1 :]:
            if left.related_transport_node_id == right.related_transport_node_id:
                continue
            distance = _distance_km((float(left.longitude), float(left.latitude)), (float(right.longitude), float(right.latitude)))
            if distance < 0.1:
                continue
            pairs.append((distance, left, right))
    pairs.sort(key=lambda item: item[0], reverse=True)
    selected: list[tuple[NavigationGraphNode, NavigationGraphNode]] = []
    used_pairs: set[tuple[int, int]] = set()
    for _, left, right in pairs:
        key = tuple(sorted((int(left.related_transport_node_id or 0), int(right.related_transport_node_id or 0))))
        if key in used_pairs:
            continue
        used_pairs.add(key)
        selected.append((left, right))
        if len(selected) >= sample_count:
            break
    return selected


def _line_points(geometry: dict[str, Any] | None) -> list[tuple[float, float]]:
    if not geometry or geometry.get("type") != "LineString":
        return []
    points: list[tuple[float, float]] = []
    for item in geometry.get("coordinates") or []:
        if not isinstance(item, list | tuple) or len(item) < 2:
            continue
        try:
            point = (float(item[0]), float(item[1]))
        except (TypeError, ValueError):
            continue
        if not points or points[-1] != point:
            points.append(point)
    return points


def _point_segment_distance_km(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    ref_lat = point[1]
    km_per_lng = 111.32 * __import__("math").cos(ref_lat * __import__("math").pi / 180)
    km_per_lat = 111.32
    px, py = point[0] * km_per_lng, point[1] * km_per_lat
    ax, ay = start[0] * km_per_lng, start[1] * km_per_lat
    bx, by = end[0] * km_per_lng, end[1] * km_per_lat
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    denom = vx * vx + vy * vy
    ratio = 0.0 if denom <= 0 else max(0.0, min(1.0, (wx * vx + wy * vy) / denom))
    nearest_x = ax + ratio * vx
    nearest_y = ay + ratio * vy
    return float(((px - nearest_x) ** 2 + (py - nearest_y) ** 2) ** 0.5)


def _point_line_distance_km(point: tuple[float, float], line: list[tuple[float, float]]) -> float | None:
    if len(line) < 2:
        return None
    return min(_point_segment_distance_km(point, start, end) for start, end in zip(line, line[1:]))


def _deviation_stats_km(
    candidate: list[tuple[float, float]],
    reference: list[tuple[float, float]],
) -> dict[str, float | None]:
    distances = [
        distance
        for point in candidate
        if (distance := _point_line_distance_km(point, reference)) is not None
    ]
    if not distances:
        return {"max": None, "mean": None, "p90": None}
    distances.sort()
    return {
        "max": round(float(distances[-1]), 3),
        "mean": round(float(sum(distances) / len(distances)), 3),
        "p90": round(float(distances[min(len(distances) - 1, int(len(distances) * 0.9))]), 3),
    }


def _hifleet_item_gate(distance_ratio: float | None, nav_to_ref: dict[str, float | None], ref_to_nav: dict[str, float | None]) -> list[str]:
    issues: list[str] = []
    if distance_ratio is None:
        issues.append("HIFLEET_DISTANCE_RATIO_UNAVAILABLE")
    elif distance_ratio < HIFLEET_DISTANCE_RATIO_MIN or distance_ratio > HIFLEET_DISTANCE_RATIO_MAX:
        issues.append("HIFLEET_DISTANCE_RATIO_OUT_OF_RANGE")
    for prefix, stats in (("NAV_TO_HIFLEET", nav_to_ref), ("HIFLEET_TO_NAV", ref_to_nav)):
        max_value = stats.get("max")
        p90_value = stats.get("p90")
        if max_value is None or p90_value is None:
            issues.append(f"{prefix}_DEVIATION_UNAVAILABLE")
            continue
        if max_value > HIFLEET_MAX_DEVIATION_KM:
            issues.append(f"{prefix}_MAX_DEVIATION_TOO_HIGH")
        if p90_value > HIFLEET_P90_DEVIATION_KM:
            issues.append(f"{prefix}_P90_DEVIATION_TOO_HIGH")
    return issues


async def _hifleet_benchmark(
    *,
    session,
    enabled: bool,
    successes: list[dict[str, Any]],
) -> dict[str, Any]:
    if not enabled:
        return {"status": "HIFLEET_SKIPPED", "reason": "use_es_if_available=false"}
    runtime_config = RuntimeConfigService(session)
    hifleet_enabled = await runtime_config.get_bool(
        HIFLEET_ENABLED,
        bool(settings.HIFLEET_ENABLED),
        profile_code=HIFLEET_CONFIG_PROFILE,
    )
    if not hifleet_enabled:
        return {"status": "HIFLEET_SKIPPED", "reason": "HIFLEET_ENABLED=false"}
    client = HifleetRouteClient(runtime_config=runtime_config, max_retries=0, concurrency_limit=1)
    rows: list[dict[str, Any]] = []
    for item in successes[:5]:
        try:
            result = await client.generate(
                RouteGeometryQuery(
                    origin_lon=item["origin_lng"],
                    origin_lat=item["origin_lat"],
                    dest_lon=item["destination_lng"],
                    dest_lat=item["destination_lat"],
                    transport_mode="WATER",
                    segment_type="REVIER_PRODUCTION_VALIDATION",
                )
            )
            hifleet_points = _line_points(result.geometry)
            navigation_points = _line_points(item.get("geometry_json"))
            hifleet_distance_km = (
                float(result.distance_km)
                if result.distance_km and float(result.distance_km) > 0
                else _line_length_km(hifleet_points)
            )
            distance_ratio = (
                float(item["distance_km"]) / hifleet_distance_km
                if hifleet_distance_km > 0
                else None
            )
            nav_to_hifleet = _deviation_stats_km(navigation_points, hifleet_points)
            hifleet_to_nav = _deviation_stats_km(hifleet_points, navigation_points)
            issues = _hifleet_item_gate(distance_ratio, nav_to_hifleet, hifleet_to_nav)
            rows.append(
                {
                    "origin_transport_node_id": item["origin_transport_node_id"],
                    "destination_transport_node_id": item["destination_transport_node_id"],
                    "status": "SUCCESS" if not issues else "FAILED",
                    "hifleet_point_count": len(hifleet_points),
                    "hifleet_distance_km": round(float(hifleet_distance_km), 3),
                    "navigation_distance_km": item["distance_km"],
                    "distance_ratio": round(float(distance_ratio), 4) if distance_ratio is not None else None,
                    "navigation_points_to_hifleet_line_km": nav_to_hifleet,
                    "hifleet_points_to_navigation_line_km": hifleet_to_nav,
                    "issues": issues,
                    "provider_trace_id": result.provider_trace_id,
                }
            )
        except Exception as exc:  # noqa: BLE001
            rows.append(
                {
                    "origin_transport_node_id": item["origin_transport_node_id"],
                    "destination_transport_node_id": item["destination_transport_node_id"],
                    "status": "FAILED",
                    "error": str(exc)[:240],
                }
            )
    validated_count = sum(1 for row in rows if row["status"] == "SUCCESS")
    failed_count = sum(1 for row in rows if row["status"] == "FAILED")
    return {
        "status": "HIFLEET_VALIDATED" if validated_count else "HIFLEET_FAILED",
        "validated_route_count": validated_count,
        "failed_route_count": failed_count,
        "production_gate_passed": bool(rows) and failed_count == 0,
        "thresholds": {
            "distance_ratio_min": HIFLEET_DISTANCE_RATIO_MIN,
            "distance_ratio_max": HIFLEET_DISTANCE_RATIO_MAX,
            "max_deviation_km": HIFLEET_MAX_DEVIATION_KM,
            "p90_deviation_km": HIFLEET_P90_DEVIATION_KM,
        },
        "items": rows,
    }


async def validate_revier_routing_with_transport_nodes(
    *,
    graph_version_code: str = REVIER_GRAPH_VERSION_CODE,
    min_success_count: int = 5,
    sample_count: int = 10,
    use_es_if_available: bool = False,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        graph_version = await session.scalar(
            select(NavigationGraphVersion).where(NavigationGraphVersion.version_code == graph_version_code)
        )
        if graph_version is None:
            report = _failure_report(graph_version_code, "GRAPH_VERSION_NOT_FOUND")
            _write_report(report_path, report)
            return report
        nodes = list(
            (
                await session.execute(
                    select(NavigationGraphNode).where(
                        NavigationGraphNode.graph_version_id == graph_version.id,
                        NavigationGraphNode.related_transport_node_id.is_not(None),
                        NavigationGraphNode.is_enabled.is_(True),
                    )
                )
            ).scalars()
        )
        edges = list(
            (
                await session.execute(
                    select(NavigationGraphEdge).where(NavigationGraphEdge.graph_version_id == graph_version.id)
                )
            ).scalars()
        )
        edge_by_id = {int(edge.id): edge for edge in edges}
        transport_ids = {int(node.related_transport_node_id or 0) for node in nodes if node.related_transport_node_id}
        transports = {
            int(row.id): row
            for row in (
                await session.execute(select(TransportNode).where(TransportNode.id.in_(transport_ids)))
            ).scalars()
        } if transport_ids else {}
        component_by_node = _components({int(node.id) for node in nodes}, edges)
        grouped_nodes: dict[int, list[NavigationGraphNode]] = defaultdict(list)
        for node in nodes:
            grouped_nodes[component_by_node.get(int(node.id), 0)].append(node)
        largest_nodes = max(grouped_nodes.values(), key=len, default=[])
        pairs = _candidate_pairs(largest_nodes, sample_count=sample_count)
        successes: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        benchmark_candidates: list[dict[str, Any]] = []
        service = NavigationRoutingEngineService(session)
        for origin_node, destination_node in pairs:
            origin_transport = transports.get(int(origin_node.related_transport_node_id or 0))
            destination_transport = transports.get(int(destination_node.related_transport_node_id or 0))
            if origin_transport is None or destination_transport is None:
                continue
            response = await service.generate_route(
                NavigationRouteGenerateRequest(
                    origin=NavigationEndpointRequest(
                        endpoint_type_code="TRANSPORT_NODE",
                        transport_node_id=int(origin_transport.id),
                        name=origin_transport.name,
                    ),
                    destination=NavigationEndpointRequest(
                        endpoint_type_code="TRANSPORT_NODE",
                        transport_node_id=int(destination_transport.id),
                        name=destination_transport.name,
                    ),
                    graph_version_id=int(graph_version.id),
                    routing_preference_code="RECOMMENDED",
                    planning_mode_code="RECOMMENDED",
                    include_explain=True,
                )
            )
            non_connector_edges = [
                edge_by_id[edge_id]
                for edge_id in response.edge_ids
                if edge_id in edge_by_id and edge_by_id[edge_id].source_type_code != "TRANSPORT_NODE_CONNECTOR"
            ]
            common = {
                "origin_transport_node_id": int(origin_transport.id),
                "origin_name": origin_transport.name,
                "origin_lng": float(origin_transport.longitude),
                "origin_lat": float(origin_transport.latitude),
                "destination_transport_node_id": int(destination_transport.id),
                "destination_name": destination_transport.name,
                "destination_lng": float(destination_transport.longitude),
                "destination_lat": float(destination_transport.latitude),
                "result_id": response.result_id,
                "request_id": response.request_id,
                "graph_version_id": response.graph_version_id,
                "distance_km": response.distance_km,
                "edge_count": len(response.edge_ids),
                "edge_ids": response.edge_ids,
                "quality_score": response.quality_score,
                "quality_code": response.quality_code,
                "origin_snap_distance_m": response.origin_snap.snap_distance_m if response.origin_snap else None,
                "destination_snap_distance_m": response.destination_snap.snap_distance_m if response.destination_snap else None,
                "geometry_json": response.geometry_json,
                "issues": [
                    item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
                    for item in (response.issues or [])
                ],
            }
            has_route_geometry = bool(response.geometry_json and response.edge_ids and float(response.distance_km or 0) > 0 and non_connector_edges)
            if has_route_geometry:
                benchmark_candidates.append(common)
            if (
                response.status_code == "SUCCESS"
                and response.geometry_json
                and response.edge_ids
                and float(response.distance_km or 0) > 0
                and non_connector_edges
            ):
                successes.append(common)
            else:
                failures.append(
                    {
                        **common,
                        "status_code": response.status_code,
                        "error_code": response.error_code or "ROUTE_VALIDATION_FAILED",
                        "error_message": response.error_message,
                        "non_connector_edge_count": len(non_connector_edges),
                    }
                )
        hifleet_report = await _hifleet_benchmark(session=session, enabled=use_es_if_available, successes=benchmark_candidates)

    hifleet_gate_passed = bool(hifleet_report.get("production_gate_passed", True))
    public_successes = [{key: value for key, value in item.items() if key != "geometry_json"} for item in successes[:sample_count]]
    public_failures = [{key: value for key, value in item.items() if key != "geometry_json"} for item in failures[:sample_count]]
    report = {
        "report_version": "REVIER_TRANSPORT_NODE_ROUTING_VALIDATION_V1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "graph_version_code": graph_version_code,
        "graph_version_id": int(graph_version.id) if graph_version else None,
        "graph_status_code": graph_version.status_code if graph_version else None,
        "transport_node_count": len(transports),
        "snapped_transport_node_count": len(nodes),
        "candidate_od_count": len(pairs),
        "route_validation_total": len(successes) + len(failures),
        "route_validation_success": len(successes),
        "route_validation_failed": len(failures),
        "min_success_count": min_success_count,
        "production_seed_allowed": len(successes) >= min_success_count and hifleet_gate_passed,
        "successes": public_successes,
        "failures": public_failures,
        "hifleet_benchmark": hifleet_report,
        "quality_gates": {
            "edge_ids_non_empty": True,
            "non_connector_edge_required": True,
            "straight_line_fallback_allowed": False,
            "graph_version_required": graph_version_code,
            "hifleet_gate_required_when_enabled": bool(use_es_if_available),
            "hifleet_gate_passed": hifleet_gate_passed,
        },
    }
    _write_report(report_path, report)
    return report


def _failure_report(graph_version_code: str, reason: str) -> dict[str, Any]:
    return {
        "report_version": "REVIER_TRANSPORT_NODE_ROUTING_VALIDATION_V1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "graph_version_code": graph_version_code,
        "production_seed_allowed": False,
        "blocking_issues": [reason],
        "route_validation_success": 0,
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate revier production graph with current TransportNode rows.")
    parser.add_argument("--graph-version-code", default=REVIER_GRAPH_VERSION_CODE)
    parser.add_argument("--min-success-count", type=int, default=5)
    parser.add_argument("--sample-count", type=int, default=10)
    parser.add_argument("--use-es-if-available", action="store_true", help="Also try optional HiFleet benchmark when configured.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report = asyncio.run(
        validate_revier_routing_with_transport_nodes(
            graph_version_code=args.graph_version_code,
            min_success_count=args.min_success_count,
            sample_count=args.sample_count,
            use_es_if_available=args.use_es_if_available,
            report_path=args.report,
        )
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report.get("production_seed_allowed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
