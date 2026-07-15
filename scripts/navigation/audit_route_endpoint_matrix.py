"""Audit real route generation across the endpoint inventory matrix."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from app.core.database import AsyncSessionLocal
from app.modules.navigation.annotation_service import NavigationAnnotationTaskService
from app.modules.navigation.routing_service import NavigationRoutingEngineService
from app.modules.navigation.schemas import NavigationEndpointRequest, NavigationRouteGenerateRequest

from scripts.navigation.audit_transport_node_route_pairs import (
    _audit_response_geometry,
    _boundary_repair_candidates,
    _load_fallback_original_route,
)
from scripts.navigation.inventory_route_endpoint_matrix import (
    EndpointCandidate,
    _active_graph_version,
    _haversine_km,
    _load_candidates,
    _pair_endpoint_payload,
)


REPORT_PATH = Path("runtime/navigation-production/reports/route_endpoint_matrix_audit_report.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit OD pairs from the full route endpoint inventory.")
    parser.add_argument("--scope", choices=("business", "seed", "business-and-seed", "all"), default="business-and-seed")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--min-distance-km", type=float, default=None)
    parser.add_argument("--max-distance-km", type=float, default=None)
    parser.add_argument("--source-type", action="append", default=None)
    parser.add_argument("--origin-uid", type=str, default=None)
    parser.add_argument("--destination-uid", type=str, default=None)
    parser.add_argument("--pair-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--include-water-body-centers", action="store_true")
    parser.add_argument("--include-water-area-centers", action="store_true")
    parser.add_argument("--water-center-limit", type=int, default=500)
    parser.add_argument("--create-annotation-tasks", action="store_true")
    parser.add_argument("--bypass-trajectory-cache", action="store_true")
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    parser.add_argument("--stop-on-error", action="store_true")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    async with AsyncSessionLocal() as session:
        active_graph = await _active_graph_version(session)
        candidates = await _load_candidates(
            session,
            scope=args.scope,
            active_graph=active_graph,
            include_water_body_centers=bool(args.include_water_body_centers),
            include_water_area_centers=bool(args.include_water_area_centers),
            water_center_limit=max(0, int(args.water_center_limit or 0)),
        )
        if args.source_type:
            allowed = {item.upper() for item in args.source_type}
            candidates = [item for item in candidates if item.source_type_code.upper() in allowed]
        pair_iterable = _select_pairs(
            candidates,
            origin_uid=args.origin_uid,
            destination_uid=args.destination_uid,
            offset=max(0, int(args.offset or 0)),
            limit=max(0, int(args.limit or 0)),
            min_distance_km=args.min_distance_km,
            max_distance_km=args.max_distance_km,
        )
        pairs = list(pair_iterable)
        routing_service = NavigationRoutingEngineService(session)
        annotation_service = NavigationAnnotationTaskService(session)
        summary: dict[str, Any] = {
            "selected_endpoint_count": len(candidates),
            "candidate_pair_count": len(candidates) * (len(candidates) - 1) // 2,
            "selected_pair_count": len(pairs),
            "success_count": 0,
            "failed_count": 0,
            "hard_issue_count": 0,
            "final_hard_issue_count": 0,
            "graph_repair_backlog_count": 0,
            "self_repaired_count": 0,
            "trajectory_cache_hit_count": 0,
            "trajectory_cache_row_count": 0,
            "hifleet_provider_count": 0,
            "navigation_engine_provider_count": 0,
            "annotation_task_created_count": 0,
            "annotation_task_existing_count": 0,
            "boundary_repair_candidate_count": 0,
            "provider_counts": {},
            "source_counts": {},
            "repair_issue_counts": {},
        }
        items: list[dict[str, Any]] = []
        for origin, destination in pairs:
            try:
                item = await _audit_pair(
                    routing_service=routing_service,
                    annotation_service=annotation_service,
                    origin=origin,
                    destination=destination,
                    create_annotation_tasks=bool(args.create_annotation_tasks),
                    bypass_trajectory_cache=bool(args.bypass_trajectory_cache),
                    pair_timeout_seconds=max(1.0, float(args.pair_timeout_seconds or 120.0)),
                )
                items.append(item)
                _accumulate_success(summary, item)
                print(
                    "pair_audited="
                    f"{origin.endpoint_uid}->{destination.endpoint_uid} "
                    f"status={item['route']['status_code']} quality={item['route']['quality_code']} "
                    f"provider={item['route'].get('provider_code')} hard_issue={item['audit']['hard_issue']} "
                    f"issues={','.join(item['audit']['repair_issue_codes']) or '-'}"
                )
            except asyncio.TimeoutError:
                await session.rollback()
                failure = _failure_item(origin, destination, "PAIR_TIMEOUT", f"Pair audit exceeded {args.pair_timeout_seconds:.1f}s")
                items.append(failure)
                summary["failed_count"] += 1
                print(f"pair_failed={origin.endpoint_uid}->{destination.endpoint_uid} error=PAIR_TIMEOUT")
                if args.stop_on_error:
                    raise
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                failure = _failure_item(origin, destination, exc.__class__.__name__, str(exc))
                items.append(failure)
                summary["failed_count"] += 1
                print(f"pair_failed={origin.endpoint_uid}->{destination.endpoint_uid} error={exc}")
                if args.stop_on_error:
                    raise
        report = {
            "report_version": "ROUTE_ENDPOINT_MATRIX_AUDIT_V1",
            "generated_at": datetime.now(UTC).isoformat(),
            "args": {
                "scope": args.scope,
                "limit": args.limit,
                "offset": args.offset,
                "min_distance_km": args.min_distance_km,
                "max_distance_km": args.max_distance_km,
                "source_type": args.source_type,
                "origin_uid": args.origin_uid,
                "destination_uid": args.destination_uid,
                "pair_timeout_seconds": float(args.pair_timeout_seconds or 120.0),
                "include_water_body_centers": bool(args.include_water_body_centers),
                "include_water_area_centers": bool(args.include_water_area_centers),
                "water_center_limit": int(args.water_center_limit or 0),
                "create_annotation_tasks": bool(args.create_annotation_tasks),
                "bypass_trajectory_cache": bool(args.bypass_trajectory_cache),
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
    routing_service: NavigationRoutingEngineService,
    annotation_service: NavigationAnnotationTaskService,
    origin: EndpointCandidate,
    destination: EndpointCandidate,
    create_annotation_tasks: bool,
    bypass_trajectory_cache: bool,
    pair_timeout_seconds: float,
) -> dict[str, Any]:
    return await asyncio.wait_for(
        _audit_pair_inner(
            routing_service=routing_service,
            annotation_service=annotation_service,
            origin=origin,
            destination=destination,
            create_annotation_tasks=create_annotation_tasks,
            bypass_trajectory_cache=bypass_trajectory_cache,
        ),
        timeout=pair_timeout_seconds,
    )


async def _audit_pair_inner(
    *,
    routing_service: NavigationRoutingEngineService,
    annotation_service: NavigationAnnotationTaskService,
    origin: EndpointCandidate,
    destination: EndpointCandidate,
    create_annotation_tasks: bool,
    bypass_trajectory_cache: bool,
) -> dict[str, Any]:
    response = await routing_service.generate_route(
        NavigationRouteGenerateRequest(
            origin=_endpoint_request(origin),
            destination=_endpoint_request(destination),
            include_alternatives=bool(bypass_trajectory_cache),
            include_explain=True,
        )
    )
    final_audit = _audit_response_geometry(response.geometry_json, response.issues)
    original_self_route = await _load_fallback_original_route(routing_service.session, response)
    original_repair_codes = set(original_self_route["audit"]["repair_issue_codes"]) if original_self_route else set()
    final_repair_codes = set(final_audit["repair_issue_codes"])
    self_repaired_graph_issue = (
        response.provider_code == "NAVIGATION_ENGINE"
        and response.source_type_code == "CENTERLINE_SEED_FALLBACK"
        and response.status_code == "SUCCESS"
        and response.quality_code in {"READY", "READY_WITH_WARNING"}
        and not final_repair_codes
        and bool(original_repair_codes)
    )
    repair_codes = sorted(final_repair_codes if self_repaired_graph_issue else final_repair_codes.union(original_repair_codes))
    audit = {
        **final_audit,
        "final_repair_issue_codes": final_audit["repair_issue_codes"],
        "original_self_repair_issue_codes": sorted(original_repair_codes),
        "graph_repair_backlog_issue_codes": sorted(original_repair_codes),
        "self_repaired_graph_issue": self_repaired_graph_issue,
        "repair_issue_codes": repair_codes,
        "hard_issue": bool(final_repair_codes or (original_repair_codes and not self_repaired_graph_issue) or not response.geometry_json),
    }
    boundary_candidates = _boundary_repair_candidates(
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
    return {
        "origin": _pair_endpoint_payload(origin),
        "destination": _pair_endpoint_payload(destination),
        "straight_distance_km": round(_haversine_km((origin.longitude, origin.latitude), (destination.longitude, destination.latitude)), 3),
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
        "boundary_repair_candidates": boundary_candidates,
        "annotation_tasks": task_summary,
    }


def _endpoint_request(item: EndpointCandidate) -> NavigationEndpointRequest:
    if item.source_type_code == "TRANSPORT_NODE":
        return NavigationEndpointRequest(
            endpoint_type_code="TRANSPORT_NODE",
            transport_node_id=item.ref_id,
            name=item.name,
        )
    if item.source_type_code == "CONSTRAINT_POINT":
        return NavigationEndpointRequest(
            endpoint_type_code="CONSTRAINT_POINT",
            constraint_point_id=item.ref_id,
            name=item.name,
        )
    return NavigationEndpointRequest(
        endpoint_type_code="LNG_LAT",
        longitude=item.longitude,
        latitude=item.latitude,
        name=item.name,
        ref_id=item.ref_id,
    )


def _select_pairs(
    candidates: list[EndpointCandidate],
    *,
    origin_uid: str | None,
    destination_uid: str | None,
    offset: int,
    limit: int,
    min_distance_km: float | None,
    max_distance_km: float | None,
) -> Iterable[tuple[EndpointCandidate, EndpointCandidate]]:
    if origin_uid or destination_uid:
        by_uid = {item.endpoint_uid: item for item in candidates}
        if origin_uid not in by_uid or destination_uid not in by_uid:
            missing = [uid for uid in (origin_uid, destination_uid) if uid not in by_uid]
            raise SystemExit(f"Endpoint uid not found in selected scope: {missing}")
        yield by_uid[str(origin_uid)], by_uid[str(destination_uid)]
        return
    skipped = 0
    emitted = 0
    for origin, destination in _iter_pairs(candidates):
        distance_km = _haversine_km((origin.longitude, origin.latitude), (destination.longitude, destination.latitude))
        if min_distance_km is not None and distance_km < min_distance_km:
            continue
        if max_distance_km is not None and distance_km > max_distance_km:
            continue
        if skipped < offset:
            skipped += 1
            continue
        if emitted >= limit:
            return
        emitted += 1
        yield origin, destination


def _iter_pairs(candidates: list[EndpointCandidate]) -> Iterable[tuple[EndpointCandidate, EndpointCandidate]]:
    for index, origin in enumerate(candidates):
        for destination in candidates[index + 1 :]:
            yield origin, destination


def _accumulate_success(summary: dict[str, Any], item: dict[str, Any]) -> None:
    route = item.get("route") or {}
    audit = item.get("audit") or {}
    if route.get("status_code") == "SUCCESS":
        summary["success_count"] += 1
    else:
        summary["failed_count"] += 1
    if audit.get("hard_issue"):
        summary["hard_issue_count"] += 1
    if audit.get("final_repair_issue_codes") or not item.get("route", {}).get("distance_km"):
        summary["final_hard_issue_count"] += 1
    if audit.get("graph_repair_backlog_issue_codes"):
        summary["graph_repair_backlog_count"] += 1
    if audit.get("self_repaired_graph_issue"):
        summary["self_repaired_count"] += 1
    if route.get("cache_hit") and route.get("trajectory_cache_id"):
        summary["trajectory_cache_hit_count"] += 1
    if route.get("trajectory_cache_id"):
        summary["trajectory_cache_row_count"] += 1
    provider = str(route.get("provider_code") or "NONE")
    source = str(route.get("source_type_code") or "NONE")
    summary["provider_counts"][provider] = int(summary["provider_counts"].get(provider, 0)) + 1
    summary["source_counts"][source] = int(summary["source_counts"].get(source, 0)) + 1
    if provider == "HIFLEET":
        summary["hifleet_provider_count"] += 1
    if provider == "NAVIGATION_ENGINE":
        summary["navigation_engine_provider_count"] += 1
    for code in audit.get("repair_issue_codes") or []:
        summary["repair_issue_counts"][code] = int(summary["repair_issue_counts"].get(code, 0)) + 1
    task_summary = item.get("annotation_tasks") or {}
    summary["annotation_task_created_count"] += int(task_summary.get("created_count") or 0)
    summary["annotation_task_existing_count"] += int(task_summary.get("existing_count") or 0)
    summary["boundary_repair_candidate_count"] += len(item.get("boundary_repair_candidates") or [])


def _failure_item(origin: EndpointCandidate, destination: EndpointCandidate, error_code: str, error: str) -> dict[str, Any]:
    return {
        "origin": asdict(origin),
        "destination": asdict(destination),
        "straight_distance_km": round(_haversine_km((origin.longitude, origin.latitude), (destination.longitude, destination.latitude)), 3),
        "error_code": error_code,
        "error": error,
    }


if __name__ == "__main__":
    asyncio.run(main())
