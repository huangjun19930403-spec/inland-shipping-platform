"""Audit TransportNode OD pairs with the real navigation routing chain.

The script is intentionally batchable. A full local database can contain hundreds
of thousands of OD pairs, so use --limit/--offset or distance filters and keep
the generated report as the repair queue input.

Examples:
    python -m scripts.navigation.audit_transport_node_route_pairs --limit 20 --max-distance-km 350
    python -m scripts.navigation.audit_transport_node_route_pairs --origin-node-id 645 --destination-node-id 724
    python -m scripts.navigation.audit_transport_node_route_pairs --limit 50 --create-annotation-tasks
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from shapely.geometry import LineString, Point, mapping, shape
from shapely.validation import make_valid

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal, engine
from app.integrations.http.route_geometry_types import RouteGeometryQuery
from app.models.address import TransportNode
from app.models.base import Base
from app.models.navigation import NavigationRouteQualityIssue, NavigationRouteResult
from app.modules.navigation.annotation_service import NavigationAnnotationTaskService
from app.modules.navigation.engine.geo import line_length_km, point_distance_m
from app.modules.navigation.routing_service import NavigationRoutingEngineService
from app.modules.navigation.schemas import NavigationEndpointRequest, NavigationRouteGenerateRequest
from app.modules.navigation.services.hifleet_route_cache_service import HifleetRouteCacheService
from app.modules.system.runtime_config import RuntimeConfigService


REPORT_PATH = Path("runtime/navigation-production/reports/transport_node_pair_audit_report.json")
REPAIR_ISSUE_CODES = {
    "PATH_OUT_OF_WATER",
    "PATH_WATER_COVERAGE_WARNING",
    "PATH_OUT_OF_CHANNEL_BOUNDARY",
    "PATH_CHANNEL_BOUNDARY_WARNING",
    "ROUTE_STRAIGHT_LINE_FALLBACK",
    "ROUTE_LONG_STRAIGHT_SEGMENT_REVIEW",
    "ROUTE_FOLDBACK_REVIEW",
    "ROUTE_SELF_INTERSECTION_REVIEW",
    "GRAPH_DISCONNECTED",
    "NO_PATH_FOUND",
    "NO_ACTIVE_GRAPH_VERSION",
    "NO_ROUTING_EDGE_IN_EXPANDED_BBOX",
    "ORIGIN_TOO_FAR_FROM_GRAPH",
    "DESTINATION_TOO_FAR_FROM_GRAPH",
}
BOUNDARY_REPAIR_ISSUE_CODES = {
    "PATH_OUT_OF_WATER",
    "PATH_WATER_COVERAGE_WARNING",
    "PATH_OUT_OF_CHANNEL_BOUNDARY",
    "PATH_CHANNEL_BOUNDARY_WARNING",
    "ROUTE_STRAIGHT_LINE_FALLBACK",
    "ROUTE_LONG_STRAIGHT_SEGMENT_REVIEW",
}


@dataclass(frozen=True)
class NodeItem:
    id: int
    code: str
    name: str
    longitude: float
    latitude: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit TransportNode route pairs using navigation engine and HiFleet cache fallback.")
    parser.add_argument("--origin-node-id", type=int, default=None)
    parser.add_argument("--destination-node-id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--max-distance-km", type=float, default=None)
    parser.add_argument("--min-distance-km", type=float, default=None)
    parser.add_argument("--create-annotation-tasks", action="store_true")
    parser.add_argument("--hifleet-reference-on-issues", action="store_true")
    parser.add_argument(
        "--pair-source-report",
        type=Path,
        default=None,
        help="Reuse origin/destination TransportNode ids from a previous audit report.",
    )
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    parser.add_argument("--pair-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--stop-on-error", action="store_true")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        nodes = await _load_nodes(session)
        total_pairs = len(nodes) * (len(nodes) - 1) // 2
        if args.pair_source_report is not None:
            pairs = _pairs_from_report(nodes, args.pair_source_report)
        elif args.origin_node_id is not None or args.destination_node_id is not None:
            pairs = [_explicit_pair(nodes, args.origin_node_id, args.destination_node_id)]
        else:
            pairs = list(
                _iter_pairs(
                    nodes,
                    offset=max(0, args.offset),
                    limit=max(0, args.limit),
                    min_distance_km=args.min_distance_km,
                    max_distance_km=args.max_distance_km,
                )
            )

        items: list[dict[str, Any]] = []
        summary = {
            "active_transport_nodes": len(nodes),
            "candidate_pair_count": total_pairs,
            "selected_pair_count": len(pairs),
            "success_count": 0,
            "failed_count": 0,
            "hard_issue_count": 0,
            "annotation_task_created_count": 0,
            "annotation_task_existing_count": 0,
            "boundary_repair_candidate_count": 0,
            "hifleet_reference_success_count": 0,
            "hifleet_reference_failed_count": 0,
        }

        routing_service = NavigationRoutingEngineService(session)
        annotation_service = NavigationAnnotationTaskService(session)
        hifleet_cache = HifleetRouteCacheService(session, runtime_config=RuntimeConfigService(session))

        for origin, destination in pairs:
            try:
                item = await _audit_pair(
                    session=session,
                    routing_service=routing_service,
                    annotation_service=annotation_service,
                    hifleet_cache=hifleet_cache,
                    origin=origin,
                    destination=destination,
                    create_annotation_tasks=bool(args.create_annotation_tasks),
                    hifleet_reference_on_issues=bool(args.hifleet_reference_on_issues),
                    pair_timeout_seconds=max(1.0, float(args.pair_timeout_seconds or 120.0)),
                )
                items.append(item)
                if item["route"]["status_code"] == "SUCCESS":
                    summary["success_count"] += 1
                else:
                    summary["failed_count"] += 1
                if item["audit"]["hard_issue"]:
                    summary["hard_issue_count"] += 1
                task_summary = item.get("annotation_tasks") or {}
                summary["annotation_task_created_count"] += int(task_summary.get("created_count") or 0)
                summary["annotation_task_existing_count"] += int(task_summary.get("existing_count") or 0)
                summary["boundary_repair_candidate_count"] += len(item.get("boundary_repair_candidates") or [])
                hifleet_summary = item.get("hifleet_reference") or {}
                if hifleet_summary.get("status") == "SUCCESS":
                    summary["hifleet_reference_success_count"] += 1
                elif hifleet_summary:
                    summary["hifleet_reference_failed_count"] += 1
                print(
                    "pair_audited="
                    f"{origin.id}:{origin.name}->{destination.id}:{destination.name} "
                    f"status={item['route']['status_code']} quality={item['route']['quality_code']} "
                    f"provider={item['route'].get('provider_code')} hard_issue={item['audit']['hard_issue']} "
                    f"issues={','.join(item['audit']['repair_issue_codes']) or '-'}"
                )
            except asyncio.TimeoutError:
                await session.rollback()
                summary["failed_count"] += 1
                failure = {
                    "origin": asdict(origin),
                    "destination": asdict(destination),
                    "error_code": "PAIR_TIMEOUT",
                    "error": f"Pair audit exceeded {float(args.pair_timeout_seconds or 120.0):.1f}s",
                }
                items.append(failure)
                print(f"pair_failed={origin.id}:{origin.name}->{destination.id}:{destination.name} error=PAIR_TIMEOUT")
                if args.stop_on_error:
                    raise
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                summary["failed_count"] += 1
                failure = {
                    "origin": asdict(origin),
                    "destination": asdict(destination),
                    "error_code": exc.__class__.__name__,
                    "error": str(exc),
                }
                items.append(failure)
                print(f"pair_failed={origin.id}:{origin.name}->{destination.id}:{destination.name} error={exc}")
                if args.stop_on_error:
                    raise

        report = {
            "report_version": "TRANSPORT_NODE_ROUTE_PAIR_AUDIT_V2",
            "generated_at": datetime.now(UTC).isoformat(),
            "args": {
                "limit": args.limit,
                "offset": args.offset,
                "min_distance_km": args.min_distance_km,
                "max_distance_km": args.max_distance_km,
                "create_annotation_tasks": bool(args.create_annotation_tasks),
                "hifleet_reference_on_issues": bool(args.hifleet_reference_on_issues),
                "pair_source_report": str(args.pair_source_report) if args.pair_source_report else None,
                "pair_timeout_seconds": float(args.pair_timeout_seconds or 120.0),
            },
            "summary": summary,
            "items": items,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report_path={args.output}")
        print(json.dumps(summary, ensure_ascii=False))


async def _audit_pair(
    *,
    session,
    routing_service: NavigationRoutingEngineService,
    annotation_service: NavigationAnnotationTaskService,
    hifleet_cache: HifleetRouteCacheService,
    origin: NodeItem,
    destination: NodeItem,
    create_annotation_tasks: bool,
    hifleet_reference_on_issues: bool,
    pair_timeout_seconds: float,
) -> dict[str, Any]:
    return await asyncio.wait_for(
        _audit_pair_inner(
            session=session,
            routing_service=routing_service,
            annotation_service=annotation_service,
            hifleet_cache=hifleet_cache,
            origin=origin,
            destination=destination,
            create_annotation_tasks=create_annotation_tasks,
            hifleet_reference_on_issues=hifleet_reference_on_issues,
        ),
        timeout=pair_timeout_seconds,
    )


async def _audit_pair_inner(
    *,
    session,
    routing_service: NavigationRoutingEngineService,
    annotation_service: NavigationAnnotationTaskService,
    hifleet_cache: HifleetRouteCacheService,
    origin: NodeItem,
    destination: NodeItem,
    create_annotation_tasks: bool,
    hifleet_reference_on_issues: bool,
) -> dict[str, Any]:
    request = NavigationRouteGenerateRequest(
        origin=NavigationEndpointRequest(endpoint_type_code="TRANSPORT_NODE", transport_node_id=origin.id),
        destination=NavigationEndpointRequest(endpoint_type_code="TRANSPORT_NODE", transport_node_id=destination.id),
        include_explain=True,
    )
    response = await routing_service.generate_route(request)
    final_audit = _audit_response_geometry(response.geometry_json, response.issues)
    original_self_route = await _load_fallback_original_route(session, response)
    original_repair_codes = (
        set(original_self_route["audit"]["repair_issue_codes"]) if original_self_route else set()
    )
    effective_repair_codes = sorted(set(final_audit["repair_issue_codes"]).union(original_repair_codes))
    audit = {
        **final_audit,
        "final_repair_issue_codes": final_audit["repair_issue_codes"],
        "original_self_repair_issue_codes": sorted(original_repair_codes),
        "repair_issue_codes": effective_repair_codes,
        "hard_issue": bool(effective_repair_codes or not response.geometry_json),
    }
    boundary_repair_candidates = _boundary_repair_candidates(
        response_result_id=response.result_id,
        response_geometry_json=response.geometry_json,
        response_provider_code=response.provider_code,
        response_quality_code=response.quality_code,
        response_channel_ids=list(response.channel_ids or []),
        response_edge_ids=list(response.edge_ids or []),
        response_issues=response.issues,
        original_self_route=original_self_route,
    )
    task_summary: dict[str, Any] | None = None
    if create_annotation_tasks and audit["repair_issue_codes"]:
        task_source_result_id = (
            int(original_self_route["result"]["result_id"])
            if original_self_route and original_self_route["audit"]["repair_issue_codes"]
            else response.result_id
        )
        created = await annotation_service.create_from_route_result(task_source_result_id)
        task_summary = {
            "created_count": created.created_count,
            "existing_count": created.existing_count,
            "task_ids": created.task_ids,
            "source_result_id": task_source_result_id,
        }
    hifleet_reference: dict[str, Any] | None = None
    if hifleet_reference_on_issues and audit["repair_issue_codes"]:
        try:
            result = await hifleet_cache.get_or_generate(
                RouteGeometryQuery(
                    origin_lon=origin.longitude,
                    origin_lat=origin.latitude,
                    dest_lon=destination.longitude,
                    dest_lat=destination.latitude,
                    transport_mode="WATER",
                    segment_type="TRANSPORT_NODE_ROUTE_AUDIT",
                ),
                origin_ref_type_code="TRANSPORT_NODE",
                origin_ref_id=origin.id,
                origin_name=origin.name,
                destination_ref_type_code="TRANSPORT_NODE",
                destination_ref_id=destination.id,
                destination_name=destination.name,
            )
            await session.commit()
            hifleet_reference = {
                "status": "SUCCESS",
                "cache_hit": (result.raw_summary or {}).get("cache_hit"),
                "hifleet_cache_id": (result.raw_summary or {}).get("hifleet_cache_id"),
                "distance_km": result.distance_km,
                "point_count": len((result.geometry or {}).get("coordinates") or []),
            }
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            hifleet_reference = {"status": "FAILED", "error": str(exc)}
    return {
        "origin": asdict(origin),
        "destination": asdict(destination),
        "straight_distance_km": round(_haversine_km([origin.longitude, origin.latitude], [destination.longitude, destination.latitude]), 3),
        "route": {
            "request_id": response.request_id,
            "result_id": response.result_id,
            "graph_version_id": response.graph_version_id,
            "status_code": response.status_code,
            "quality_code": response.quality_code,
            "quality_score": response.quality_score,
            "provider_code": response.provider_code,
            "source_type_code": response.source_type_code,
            "cache_hit": response.cache_hit,
            "hifleet_cache_id": response.hifleet_cache_id,
            "trajectory_cache_id": response.trajectory_cache_id,
            "distance_km": response.distance_km,
            "error_code": response.error_code,
            "error_message": response.error_message,
        },
        "audit": audit,
        "original_self_route": original_self_route,
        "boundary_repair_candidates": boundary_repair_candidates,
        "annotation_tasks": task_summary,
        "hifleet_reference": hifleet_reference,
    }


async def _load_fallback_original_route(session, response) -> dict[str, Any] | None:
    result_id = await _fallback_original_result_id(session, response)
    if result_id is None:
        return None
    result = await session.get(NavigationRouteResult, result_id)
    if result is None:
        return None
    issues = list(
        (
            await session.execute(
                select(NavigationRouteQualityIssue)
                .where(NavigationRouteQualityIssue.route_result_id == result.id)
                .order_by(NavigationRouteQualityIssue.id)
            )
        ).scalars()
    )
    audit = _audit_response_geometry(result.geometry_json, issues)
    issue_payloads = [_issue_payload(issue) for issue in issues]
    return {
        "result": {
            "result_id": result.id,
            "request_id": result.request_id,
            "status_code": result.status_code,
            "quality_code": result.quality_code,
            "quality_score": result.quality_score,
            "provider_code": result.provider_code,
            "engine_code": result.engine_code,
            "graph_version_id": _quality_summary_value(result, "graph_version_id"),
            "distance_km": float(result.distance_km) if result.distance_km is not None else None,
        },
        "audit": audit,
        "issues": issue_payloads,
        "boundary_repair_candidates": _boundary_repair_candidates_for_issue_set(
            route_result_id=result.id,
            geometry_json=result.geometry_json,
            provider_code=result.provider_code,
            quality_code=result.quality_code,
            channel_ids=list(result.channel_ids or []),
            edge_ids=list(result.edge_ids or []),
            issues=issues,
            source_code="ORIGINAL_SELF_ROUTE",
        ),
    }


async def _fallback_original_result_id(session, response) -> int | None:
    explain = response.explain if isinstance(response.explain, dict) else {}
    own_summary = explain.get("own_algorithm_summary") if isinstance(explain.get("own_algorithm_summary"), dict) else {}
    candidate_ids = [
        _int_or_none(explain.get("original_result_id")),
        _int_or_none(own_summary.get("original_result_id")),
        _int_or_none(explain.get("cached_from_route_result_id")),
        _int_or_none(response.result_id),
    ]
    for candidate_id in candidate_ids:
        result_id = await _trace_original_self_result_id(session, candidate_id)
        if result_id is not None:
            return result_id
    return None


async def _trace_original_self_result_id(session, result_id: int | None) -> int | None:
    seen: set[int] = set()
    current_id = result_id
    for _ in range(5):
        if current_id is None or current_id in seen:
            return None
        seen.add(current_id)
        row = await session.get(NavigationRouteResult, current_id)
        if row is None:
            return None
        provider = (row.provider_code or "").upper()
        result_type = (row.result_type_code or "").upper()
        if provider != "HIFLEET" and result_type != "HIFLEET_FALLBACK":
            return int(row.id)
        current_id = _int_or_none(row.reference_result_id)
    return None


def _boundary_repair_candidates(
    *,
    response_result_id: int,
    response_geometry_json: dict[str, Any] | None,
    response_provider_code: str | None,
    response_quality_code: str | None,
    response_channel_ids: list[int],
    response_edge_ids: list[int],
    response_issues,
    original_self_route: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    candidates = _boundary_repair_candidates_for_issue_set(
        route_result_id=response_result_id,
        geometry_json=response_geometry_json,
        provider_code=response_provider_code,
        quality_code=response_quality_code,
        channel_ids=response_channel_ids,
        edge_ids=response_edge_ids,
        issues=response_issues,
        source_code="FINAL_ROUTE",
    )
    if original_self_route:
        candidates.extend(original_self_route.get("boundary_repair_candidates") or [])
    return candidates


def _boundary_repair_candidates_for_issue_set(
    *,
    route_result_id: int,
    geometry_json: dict[str, Any] | None,
    provider_code: str | None,
    quality_code: str | None,
    channel_ids: list[int],
    edge_ids: list[int],
    issues,
    source_code: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for issue in issues or []:
        issue_code = str(getattr(issue, "issue_type_code", "") or "").upper()
        if issue_code not in BOUNDARY_REPAIR_ISSUE_CODES:
            continue
        patch = _boundary_expansion_patch(getattr(issue, "geometry_json", None) or geometry_json)
        candidates.append(
            {
                "source_code": source_code,
                "route_result_id": route_result_id,
                "issue_code": issue_code,
                "repair_strategy_code": "BOUNDARY_EXPANSION_CANDIDATE",
                "candidate_operation_code": "UNION_PATCH",
                "candidate_buffer_m": 350,
                "candidate_patch_bbox": _geometry_bbox(patch),
                "candidate_boundary_patch_geometry_json": patch,
                "route_result_provider_code": provider_code,
                "route_result_quality_code": quality_code,
                "route_channel_ids": channel_ids,
                "route_edge_ids": edge_ids,
                "publish_allowed": False,
                "requires_operator_confirmation": True,
                "guardrails": [
                    "该几何只是扩边候选补丁，不能自动发布为当前边界",
                    "先检查是否真实航道边界缺失或过窄，再以草稿 UNION_PATCH 合入",
                    "发布新边界后必须重新生成中心线区段和 Graph，再重新跑路径验证",
                ],
            }
        )
    return candidates


def _boundary_expansion_patch(geometry_json: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(geometry_json, dict):
        return None
    try:
        geometry = shape(geometry_json)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(geometry, LineString) or geometry.is_empty:
        return None
    buffer_degree = 350 / 111_320
    try:
        patch = make_valid(geometry.buffer(buffer_degree, cap_style=2, join_style=2))
    except Exception:  # noqa: BLE001
        patch = geometry.buffer(buffer_degree)
    if patch.is_empty:
        return None
    return mapping(patch)


def _geometry_bbox(geometry_json: dict[str, Any] | None) -> dict[str, float] | None:
    if not isinstance(geometry_json, dict):
        return None
    try:
        geometry = shape(geometry_json)
    except Exception:  # noqa: BLE001
        return None
    if geometry.is_empty:
        return None
    min_lng, min_lat, max_lng, max_lat = geometry.bounds
    return {
        "min_lng": round(float(min_lng), 7),
        "min_lat": round(float(min_lat), 7),
        "max_lng": round(float(max_lng), 7),
        "max_lat": round(float(max_lat), 7),
    }


def _issue_payload(issue) -> dict[str, Any]:
    return {
        "issue_type_code": getattr(issue, "issue_type_code", None),
        "severity_code": getattr(issue, "severity_code", None),
        "message": getattr(issue, "message", None),
        "suggestion": getattr(issue, "suggestion", None),
        "related_edge_id": getattr(issue, "related_edge_id", None),
        "related_node_id": getattr(issue, "related_node_id", None),
        "has_geometry": bool(getattr(issue, "geometry_json", None)),
    }


def _quality_summary_value(result: NavigationRouteResult, key: str) -> Any:
    summary = result.quality_summary_json if isinstance(result.quality_summary_json, dict) else {}
    return summary.get(key)


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _audit_response_geometry(geometry_json: dict[str, Any] | None, issues) -> dict[str, Any]:
    issue_codes = [issue.issue_type_code for issue in issues]
    repair_issue_codes = sorted(set(issue_codes).intersection(REPAIR_ISSUE_CODES))
    points = _line_string_points(geometry_json)
    metrics = {
        "point_count": len(points),
        "length_km": None,
        "direct_distance_km": None,
        "length_to_direct_ratio": None,
        "max_segment_km": None,
    }
    if len(points) >= 2:
        line = shape(geometry_json)
        if isinstance(line, LineString):
            length_km = line_length_km(line)
            direct_distance_km = _haversine_km(points[0], points[-1])
            max_segment_km = max(
                point_distance_m(Point(start), Point(end)) / 1000.0
                for start, end in zip(points[:-1], points[1:])
            )
            metrics.update(
                {
                    "length_km": round(length_km, 3),
                    "direct_distance_km": round(direct_distance_km, 3),
                    "length_to_direct_ratio": round(length_km / direct_distance_km, 4) if direct_distance_km > 0 else None,
                    "max_segment_km": round(max_segment_km, 3),
                }
            )
    hard_issue = bool(repair_issue_codes or not geometry_json)
    return {
        **metrics,
        "issue_codes": issue_codes,
        "repair_issue_codes": repair_issue_codes,
        "hard_issue": hard_issue,
    }


async def _load_nodes(session) -> list[NodeItem]:
    rows = list(
        (
            await session.execute(
                select(TransportNode)
                .where(
                    TransportNode.status == 1,
                    TransportNode.longitude.is_not(None),
                    TransportNode.latitude.is_not(None),
                )
                .order_by(TransportNode.sort_order, TransportNode.id)
            )
        ).scalars()
    )
    return [
        NodeItem(
            id=int(row.id),
            code=row.code,
            name=row.name,
            longitude=float(row.longitude),
            latitude=float(row.latitude),
        )
        for row in rows
    ]


def _explicit_pair(nodes: list[NodeItem], origin_id: int | None, destination_id: int | None) -> tuple[NodeItem, NodeItem]:
    if origin_id is None or destination_id is None:
        raise SystemExit("--origin-node-id and --destination-node-id must be provided together")
    by_id = {node.id: node for node in nodes}
    try:
        return by_id[origin_id], by_id[destination_id]
    except KeyError as exc:
        raise SystemExit(f"TransportNode not found or inactive: {exc}") from exc


def _pairs_from_report(nodes: list[NodeItem], report_path: Path) -> list[tuple[NodeItem, NodeItem]]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    by_id = {node.id: node for node in nodes}
    pairs: list[tuple[NodeItem, NodeItem]] = []
    missing: list[int] = []
    for item in report.get("items") or []:
        origin_id = _int_or_none((item.get("origin") or {}).get("id"))
        destination_id = _int_or_none((item.get("destination") or {}).get("id"))
        if origin_id is None or destination_id is None:
            continue
        origin = by_id.get(origin_id)
        destination = by_id.get(destination_id)
        if origin is None:
            missing.append(origin_id)
        if destination is None:
            missing.append(destination_id)
        if origin is not None and destination is not None:
            pairs.append((origin, destination))
    if missing:
        raise SystemExit(f"TransportNode not found or inactive from pair source report: {sorted(set(missing))}")
    if not pairs:
        raise SystemExit(f"No origin/destination pairs found in report: {report_path}")
    return pairs


def _iter_pairs(
    nodes: list[NodeItem],
    *,
    offset: int,
    limit: int,
    min_distance_km: float | None,
    max_distance_km: float | None,
) -> Iterable[tuple[NodeItem, NodeItem]]:
    skipped = 0
    emitted = 0
    for index, origin in enumerate(nodes):
        for destination in nodes[index + 1 :]:
            distance = _haversine_km([origin.longitude, origin.latitude], [destination.longitude, destination.latitude])
            if min_distance_km is not None and distance < min_distance_km:
                continue
            if max_distance_km is not None and distance > max_distance_km:
                continue
            if skipped < offset:
                skipped += 1
                continue
            if emitted >= limit:
                return
            emitted += 1
            yield origin, destination


def _line_string_points(geometry: dict[str, Any] | None) -> list[list[float]]:
    if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
        return []
    points: list[list[float]] = []
    for item in geometry.get("coordinates") or []:
        if not isinstance(item, list | tuple) or len(item) < 2:
            continue
        try:
            lon = float(item[0])
            lat = float(item[1])
        except (TypeError, ValueError):
            continue
        if -180 <= lon <= 180 and -90 <= lat <= 90 and (not points or points[-1] != [lon, lat]):
            points.append([lon, lat])
    return points


def _haversine_km(a: list[float], b: list[float]) -> float:
    lon1, lat1 = math.radians(float(a[0])), math.radians(float(a[1]))
    lon2, lat2 = math.radians(float(b[0])), math.radians(float(b[1]))
    d_lon = lon2 - lon1
    d_lat = lat2 - lat1
    value = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
    return 6371.0088 * 2 * math.atan2(math.sqrt(value), math.sqrt(max(0.0, 1 - value)))


if __name__ == "__main__":
    asyncio.run(main())
