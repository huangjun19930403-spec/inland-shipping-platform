"""Build reviewable centerline drafts from SNAP_REPAIR HiFleet references."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from shapely.geometry import LineString, mapping, shape

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.exceptions import ValidationError
from app.models import NavigationAnnotationTask, NavigationGeometryDraft, NavigationRouteQualityIssue, NavigationRouteRequest, NavigationRouteResult
from app.models.address import NavigationChannel
from app.models.navigation import (
    NavigationChannelWaterAreaMatch,
    NavigationChannelWaterBodyMatch,
    NavigationWaterBodyFeatureLink,
)
from app.modules.navigation.schemas import NavigationGeometryDraftCreateRequest, NavigationGeometryDraftValidateRequest
from app.modules.navigation.workbench_service import ARCHIVED_DRAFT_STATUSES, NavigationWorkbenchService
from scripts.navigation.build_snap_repair_debug_artifacts import (
    _active_graph_version,
    _endpoint_point,
    _hifleet_references,
    _issue_role,
    _nearest_graph_edges,
    _nearest_water_areas,
)


OUTPUT_PATH = Path("runtime/navigation-production/reports/snap_repair_access_draft_report.json")
OPEN_TASK_STATUSES = {"OPEN", "IN_PROGRESS", "NEED_REVIEW"}
SOURCE_TYPE_CODE = "HIFLEET_SNAP_REPAIR_ACCESS"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create CENTERLINE draft candidates from SNAP_REPAIR tasks.")
    parser.add_argument("--task-id", type=int, action="append", default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--nearest-graph-limit", type=int, default=3)
    parser.add_argument("--nearest-water-limit", type=int, default=3)
    parser.add_argument("--hifleet-line-limit", type=int, default=3)
    parser.add_argument("--hifleet-access-point-count", type=int, default=30)
    parser.add_argument("--hifleet-access-max-km", type=float, default=20.0)
    parser.add_argument("--max-endpoint-water-distance-m", type=float, default=500.0)
    parser.add_argument("--max-access-endpoint-gap-m", type=float, default=1000.0)
    parser.add_argument("--allow-truncated-access-candidate", action="store_true")
    parser.add_argument("--create-drafts", action="store_true")
    parser.add_argument("--created-by", type=int, default=None)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    async with AsyncSessionLocal() as session:
        tasks = await _load_tasks(session, task_ids=args.task_id, limit=max(1, int(args.limit or 1)))
        workbench = NavigationWorkbenchService(session)
        items: list[dict[str, Any]] = []
        summary: dict[str, Any] = {
            "task_count": len(tasks),
            "candidate_count": 0,
            "draft_created_count": 0,
            "draft_existing_count": 0,
            "need_review_count": 0,
            "error_count": 0,
        }
        for task in tasks:
            try:
                item = await _process_task(
                    session=session,
                    workbench=workbench,
                    task=task,
                    create_drafts=bool(args.create_drafts),
                    created_by=args.created_by,
                    nearest_graph_limit=max(1, int(args.nearest_graph_limit or 1)),
                    nearest_water_limit=max(1, int(args.nearest_water_limit or 1)),
                    hifleet_line_limit=max(1, int(args.hifleet_line_limit or 1)),
                    hifleet_access_point_count=max(2, int(args.hifleet_access_point_count or 2)),
                    hifleet_access_max_km=max(0.0, float(args.hifleet_access_max_km or 0.0)),
                    max_endpoint_water_distance_m=max(0.0, float(args.max_endpoint_water_distance_m or 0.0)),
                    max_access_endpoint_gap_m=max(0.0, float(args.max_access_endpoint_gap_m or 0.0)),
                    allow_truncated_access_candidate=bool(args.allow_truncated_access_candidate),
                )
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                item = {
                    "task_id": task.id,
                    "status": "ERROR",
                    "error_code": exc.__class__.__name__,
                    "error_message": str(exc),
                }
            items.append(item)
            _accumulate(summary, item)
            print(
                "snap_repair_access="
                f"task={task.id} status={item.get('status')} "
                f"draft={item.get('draft_id') or '-'} reason={item.get('review_reason') or item.get('error_code') or '-'}"
            )
        report = {
            "report_version": "SNAP_REPAIR_ACCESS_DRAFTS_V1",
            "generated_at": datetime.now(UTC).isoformat(),
            "create_drafts": bool(args.create_drafts),
            "args": {
                "task_id": args.task_id,
                "limit": args.limit,
                "nearest_graph_limit": args.nearest_graph_limit,
                "nearest_water_limit": args.nearest_water_limit,
                "hifleet_line_limit": args.hifleet_line_limit,
                "hifleet_access_point_count": args.hifleet_access_point_count,
                "hifleet_access_max_km": args.hifleet_access_max_km,
                "max_endpoint_water_distance_m": args.max_endpoint_water_distance_m,
                "max_access_endpoint_gap_m": args.max_access_endpoint_gap_m,
                "allow_truncated_access_candidate": bool(args.allow_truncated_access_candidate),
            },
            "summary": summary,
            "items": items,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report_path={args.output}")
        print(json.dumps(summary, ensure_ascii=False))


async def _load_tasks(session, *, task_ids: list[int] | None, limit: int) -> list[NavigationAnnotationTask]:
    stmt = select(NavigationAnnotationTask).where(NavigationAnnotationTask.task_type_code == "SNAP_REPAIR")
    if task_ids:
        stmt = stmt.where(NavigationAnnotationTask.id.in_(task_ids))
    else:
        stmt = stmt.where(NavigationAnnotationTask.status_code.in_(OPEN_TASK_STATUSES)).limit(limit)
    return list((await session.execute(stmt.order_by(NavigationAnnotationTask.id))).scalars())


async def _process_task(
    *,
    session,
    workbench: NavigationWorkbenchService,
    task: NavigationAnnotationTask,
    create_drafts: bool,
    created_by: int | None,
    nearest_graph_limit: int,
    nearest_water_limit: int,
    hifleet_line_limit: int,
    hifleet_access_point_count: int,
    hifleet_access_max_km: float,
    max_endpoint_water_distance_m: float,
    max_access_endpoint_gap_m: float,
    allow_truncated_access_candidate: bool,
) -> dict[str, Any]:
    issue = await session.get(NavigationRouteQualityIssue, task.target_id) if task.target_id else None
    result = await session.get(NavigationRouteResult, issue.route_result_id) if issue else None
    request = await session.get(NavigationRouteRequest, result.request_id) if result else None
    endpoint = _endpoint_point(task, issue, request)
    if endpoint is None:
        return _review_item(task, issue, request, "NO_ENDPOINT_GEOMETRY")
    graph_version = await _active_graph_version(session, task.graph_version_id)
    nearest_graph = await _nearest_graph_edges(
        session,
        endpoint,
        graph_version.id if graph_version else None,
        limit=nearest_graph_limit,
    )
    nearest_water = await _nearest_water_areas(session, endpoint, limit=nearest_water_limit)
    hifleet_refs = await _hifleet_references(
        session,
        request,
        endpoint=endpoint,
        limit=hifleet_line_limit,
        access_point_count=hifleet_access_point_count,
        access_max_km=hifleet_access_max_km,
    )
    candidate, blocked_candidates = _best_access_candidate(
        hifleet_refs,
        max_access_endpoint_gap_m=max_access_endpoint_gap_m,
        allow_truncated_access_candidate=allow_truncated_access_candidate,
    )
    if candidate is None:
        return _review_item(
            task,
            issue,
            request,
            "NO_SAFE_HIFLEET_ACCESS_CANDIDATE" if blocked_candidates else "NO_HIFLEET_ACCESS_CANDIDATE",
            extra={
                "hifleet_access_candidate_count": len(blocked_candidates),
                "max_access_endpoint_gap_m": max_access_endpoint_gap_m,
                "allow_truncated_access_candidate": allow_truncated_access_candidate,
                "blocked_candidates": blocked_candidates[:5],
            }
            if blocked_candidates
            else None,
        )
    channel_resolution = await _candidate_channel_resolution(session, task=task, nearest_water=nearest_water, nearest_graph=nearest_graph)
    if channel_resolution["channel_id"] is None:
        return _review_item(task, issue, request, "NO_CHANNEL_FOR_CENTERLINE_DRAFT")
    channel_id = int(channel_resolution["channel_id"])
    closest_water_distance_m = _closest_water_distance_m(nearest_water)
    if closest_water_distance_m is None or closest_water_distance_m > max_endpoint_water_distance_m:
        return _review_item(
            task,
            issue,
            request,
            "ENDPOINT_NOT_NEAR_WATER_AREA",
            extra={"closest_water_distance_m": closest_water_distance_m},
        )
    existing = await _existing_draft(session, task_id=task.id, channel_id=channel_id)
    validation = await workbench.validate_geometry_draft(
        NavigationGeometryDraftValidateRequest(
            draft_type_code="CENTERLINE",
            channel_id=channel_id,
            geometry_json=candidate["geometry_json"],
        )
    )
    source_trace = _source_trace(
        task=task,
        issue=issue,
        result=result,
        request=request,
        graph_version_id=graph_version.id if graph_version else None,
        nearest_graph=nearest_graph,
        nearest_water=nearest_water,
        hifleet_candidate=candidate,
        channel_resolution=channel_resolution,
        validation_quality_code=validation.quality_code,
        validation_issue_codes=[item.issue_code for item in validation.issues],
    )
    if existing is not None:
        return {
            **_base_item(task, issue, request),
            "status": "DRAFT_EXISTS",
            "draft_id": existing.id,
            "draft_status_code": existing.status_code,
            "draft_quality_code": existing.quality_code,
            "channel_id": existing.channel_id,
            "candidate": candidate,
            "validation": _validation_payload(validation),
            "source_trace": source_trace,
        }
    if not create_drafts:
        return {
            **_base_item(task, issue, request),
            "status": "DRY_RUN_CANDIDATE_READY",
            "channel_id": channel_id,
            "candidate": candidate,
            "validation": _validation_payload(validation),
            "source_trace": source_trace,
        }
    try:
        draft = await workbench.create_geometry_draft(
            NavigationGeometryDraftCreateRequest(
                draft_type_code="CENTERLINE",
                draft_name=f"SNAP_REPAIR access task {task.id}",
                channel_id=channel_id,
                target_type_code="ANNOTATION_TASK",
                target_id=task.id,
                geometry_json=candidate["geometry_json"],
                source_type_code=SOURCE_TYPE_CODE,
                source_trace_json=source_trace,
            ),
            created_by=created_by,
        )
    except ValidationError as exc:
        await session.rollback()
        return {
            **_base_item(task, issue, request),
            "status": "NEED_REVIEW",
            "review_reason": "DRAFT_VALIDATION_REJECTED",
            "error_message": exc.message,
            "channel_id": channel_id,
            "candidate": candidate,
            "validation": _validation_payload(validation),
            "source_trace": source_trace,
        }
    return {
        **_base_item(task, issue, request),
        "status": "DRAFT_CREATED",
        "draft_id": draft.id,
        "draft_status_code": draft.status_code,
        "draft_quality_code": draft.quality_code,
        "channel_id": draft.channel_id,
        "candidate": candidate,
        "validation": _validation_payload(validation),
        "source_trace": source_trace,
    }


def _best_access_candidate(
    hifleet_refs: list[dict[str, Any]],
    *,
    max_access_endpoint_gap_m: float,
    allow_truncated_access_candidate: bool,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    for ref in hifleet_refs:
        for feature in ref.get("features") or []:
            properties = feature.get("properties") or {}
            if properties.get("kind") != "hifleet_access_candidate":
                continue
            try:
                line = shape(feature.get("geometry"))
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(line, LineString) or len(line.coords) < 2:
                continue
            candidates.append(
                {
                    "trajectory_cache_id": ref.get("cache_id"),
                    "hifleet_cache_id": ref.get("hifleet_cache_id"),
                    "geometry_json": mapping(line),
                    "access_side": properties.get("side"),
                    "endpoint_gap_m": properties.get("endpoint_gap_m"),
                    "length_km": properties.get("length_km"),
                    "point_count": properties.get("point_count"),
                    "truncated_by_max_km": bool(properties.get("truncated_by_max_km")),
                    "max_candidate_km": properties.get("max_candidate_km"),
                    "requires_densification": bool(properties.get("requires_densification")),
                    "requires_validation": True,
                    "draft_only": True,
                }
            )
    if not candidates:
        return None, []
    allowed: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for candidate in candidates:
        blockers = _access_candidate_blockers(
            candidate,
            max_access_endpoint_gap_m=max_access_endpoint_gap_m,
            allow_truncated_access_candidate=allow_truncated_access_candidate,
        )
        if blockers:
            blocked.append(_blocked_candidate_summary(candidate, blockers))
        else:
            allowed.append(candidate)
    if not allowed:
        blocked.sort(key=lambda item: (_float_or_inf(item.get("endpoint_gap_m")), float(item.get("length_km") or 0)))
        return None, blocked
    return (
        sorted(
            allowed,
            key=lambda item: (
                _float_or_inf(item.get("endpoint_gap_m")),
                bool(item.get("requires_densification")),
                bool(item.get("truncated_by_max_km")),
                float(item.get("length_km") or 0),
                int(item.get("point_count") or 0),
            ),
        )[0],
        blocked,
    )


def _access_candidate_blockers(
    candidate: dict[str, Any],
    *,
    max_access_endpoint_gap_m: float,
    allow_truncated_access_candidate: bool,
) -> list[str]:
    blockers: list[str] = []
    endpoint_gap_m = _to_float(candidate.get("endpoint_gap_m"))
    if endpoint_gap_m is None:
        blockers.append("ACCESS_ENDPOINT_GAP_UNKNOWN")
    elif endpoint_gap_m > max_access_endpoint_gap_m:
        blockers.append("ACCESS_ENDPOINT_GAP_TOO_LARGE")
    if candidate.get("truncated_by_max_km") and not allow_truncated_access_candidate:
        blockers.append("ACCESS_CANDIDATE_TRUNCATED")
    return blockers


def _blocked_candidate_summary(candidate: dict[str, Any], blockers: list[str]) -> dict[str, Any]:
    return {
        "trajectory_cache_id": candidate.get("trajectory_cache_id"),
        "hifleet_cache_id": candidate.get("hifleet_cache_id"),
        "access_side": candidate.get("access_side"),
        "endpoint_gap_m": candidate.get("endpoint_gap_m"),
        "length_km": candidate.get("length_km"),
        "point_count": candidate.get("point_count"),
        "truncated_by_max_km": bool(candidate.get("truncated_by_max_km")),
        "blockers": blockers,
    }


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_or_inf(value: Any) -> float:
    parsed = _to_float(value)
    return parsed if parsed is not None else float("inf")


async def _candidate_channel_resolution(
    session,
    *,
    task: NavigationAnnotationTask,
    nearest_water: list[dict[str, Any]],
    nearest_graph: list[dict[str, Any]],
) -> dict[str, Any]:
    water_area_ids = [int(item["water_area_id"]) for item in nearest_water if item.get("water_area_id") is not None]
    water_names = [str(item.get("water_name") or "").strip() for item in nearest_water if item.get("water_name")]
    if water_area_ids:
        match = await _channel_from_water_area_match(session, water_area_ids)
        if match is not None:
            return match
        match = await _channel_from_water_body_match(session, water_area_ids)
        if match is not None:
            return match
    for water_name in water_names:
        match = await _channel_from_water_name(session, water_name)
        if match is not None:
            return match
    if task.channel_id is not None:
        return {"channel_id": int(task.channel_id), "reason": "TASK_CHANNEL_ID"}
    for item in nearest_graph:
        if item.get("channel_id") is not None:
            return {
                "channel_id": int(item["channel_id"]),
                "reason": "NEAREST_GRAPH_EDGE_FALLBACK",
                "edge_id": item.get("edge_id"),
                "edge_code": item.get("edge_code"),
                "distance_m": item.get("distance_m"),
            }
    return {"channel_id": None, "reason": "NO_CHANNEL_CANDIDATE"}


async def _channel_from_water_area_match(session, water_area_ids: list[int]) -> dict[str, Any] | None:
    row = (
        await session.execute(
            select(NavigationChannelWaterAreaMatch, NavigationChannel)
            .join(NavigationChannel, NavigationChannel.id == NavigationChannelWaterAreaMatch.channel_id)
            .where(
                NavigationChannelWaterAreaMatch.water_area_id.in_(water_area_ids),
                NavigationChannelWaterAreaMatch.is_current.is_(True),
            )
            .order_by(NavigationChannelWaterAreaMatch.score.desc(), NavigationChannelWaterAreaMatch.id.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    match, channel = row
    return {
        "channel_id": int(channel.id),
        "channel_code": channel.channel_code,
        "channel_name": channel.channel_name,
        "reason": "WATER_AREA_CHANNEL_MATCH",
        "water_area_id": int(match.water_area_id),
        "match_id": int(match.id),
        "confidence_code": match.confidence_code,
        "score": int(match.score or 0),
    }


async def _channel_from_water_body_match(session, water_area_ids: list[int]) -> dict[str, Any] | None:
    links = list(
        (
            await session.execute(
                select(NavigationWaterBodyFeatureLink)
                .where(NavigationWaterBodyFeatureLink.water_area_id.in_(water_area_ids))
                .order_by(NavigationWaterBodyFeatureLink.is_primary.desc(), NavigationWaterBodyFeatureLink.id.desc())
            )
        ).scalars()
    )
    water_body_ids = [int(row.water_body_id) for row in links]
    if not water_body_ids:
        return None
    row = (
        await session.execute(
            select(NavigationChannelWaterBodyMatch, NavigationChannel)
            .join(NavigationChannel, NavigationChannel.id == NavigationChannelWaterBodyMatch.channel_id)
            .where(
                NavigationChannelWaterBodyMatch.water_body_id.in_(water_body_ids),
                NavigationChannelWaterBodyMatch.is_current.is_(True),
            )
            .order_by(NavigationChannelWaterBodyMatch.score.desc(), NavigationChannelWaterBodyMatch.id.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    match, channel = row
    source_area_ids = sorted({int(link.water_area_id) for link in links if int(link.water_body_id) == int(match.water_body_id)})
    return {
        "channel_id": int(channel.id),
        "channel_code": channel.channel_code,
        "channel_name": channel.channel_name,
        "reason": "WATER_BODY_CHANNEL_MATCH",
        "water_body_id": int(match.water_body_id),
        "source_water_area_ids": source_area_ids,
        "match_id": int(match.id),
        "confidence_code": match.confidence_code,
        "score": int(match.score or 0),
    }


async def _channel_from_water_name(session, water_name: str) -> dict[str, Any] | None:
    if not water_name:
        return None
    rows = list(
        (
            await session.execute(
                select(NavigationChannel)
                .where(NavigationChannel.channel_name.like(f"%{water_name}%"))
                .order_by(NavigationChannel.id)
                .limit(20)
            )
        ).scalars()
    )
    if not rows:
        return None
    rows.sort(key=lambda row: (0 if str(row.channel_name or "").startswith(water_name) else 1, len(str(row.channel_name or ""))))
    channel = rows[0]
    return {
        "channel_id": int(channel.id),
        "channel_code": channel.channel_code,
        "channel_name": channel.channel_name,
        "reason": "WATER_NAME_CHANNEL_NAME_MATCH",
        "water_name": water_name,
    }


async def _existing_draft(session, *, task_id: int, channel_id: int) -> NavigationGeometryDraft | None:
    return (
        await session.execute(
            select(NavigationGeometryDraft)
            .where(
                NavigationGeometryDraft.draft_type_code == "CENTERLINE",
                NavigationGeometryDraft.target_type_code == "ANNOTATION_TASK",
                NavigationGeometryDraft.target_id == task_id,
                NavigationGeometryDraft.source_type_code == SOURCE_TYPE_CODE,
                NavigationGeometryDraft.channel_id == channel_id,
                NavigationGeometryDraft.status_code.not_in(ARCHIVED_DRAFT_STATUSES),
            )
            .order_by(NavigationGeometryDraft.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _closest_water_distance_m(nearest_water: list[dict[str, Any]]) -> float | None:
    values = [float(item["distance_m"]) for item in nearest_water if item.get("distance_m") is not None]
    return min(values) if values else None


def _source_trace(
    *,
    task: NavigationAnnotationTask,
    issue: NavigationRouteQualityIssue | None,
    result: NavigationRouteResult | None,
    request: NavigationRouteRequest | None,
    graph_version_id: int | None,
    nearest_graph: list[dict[str, Any]],
    nearest_water: list[dict[str, Any]],
    hifleet_candidate: dict[str, Any],
    channel_resolution: dict[str, Any],
    validation_quality_code: str,
    validation_issue_codes: list[str],
) -> dict[str, Any]:
    closest_graph = nearest_graph[0] if nearest_graph else {}
    closest_water = nearest_water[0] if nearest_water else {}
    return {
        "source": SOURCE_TYPE_CODE,
        "generated_at": datetime.now(UTC).isoformat(),
        "snap_repair_task_id": task.id,
        "route_quality_issue_id": issue.id if issue else None,
        "issue_type_code": issue.issue_type_code if issue else None,
        "route_request_id": request.id if request else None,
        "route_result_id": result.id if result else None,
        "graph_version_id": graph_version_id,
        "trajectory_cache_id": hifleet_candidate.get("trajectory_cache_id"),
        "hifleet_cache_id": hifleet_candidate.get("hifleet_cache_id"),
        "access_side": hifleet_candidate.get("access_side"),
        "access_length_km": hifleet_candidate.get("length_km"),
        "access_point_count": hifleet_candidate.get("point_count"),
        "access_truncated_by_max_km": hifleet_candidate.get("truncated_by_max_km"),
        "access_requires_densification": hifleet_candidate.get("requires_densification"),
        "channel_resolution": channel_resolution,
        "nearest_graph_edge_id": closest_graph.get("edge_id"),
        "nearest_graph_edge_code": closest_graph.get("edge_code"),
        "nearest_graph_channel_id": closest_graph.get("channel_id"),
        "nearest_graph_distance_m": round(float(closest_graph["distance_m"]), 1) if closest_graph.get("distance_m") is not None else None,
        "nearest_water_area_id": closest_water.get("water_area_id"),
        "nearest_water_name": closest_water.get("water_name"),
        "nearest_water_distance_m": round(float(closest_water["distance_m"]), 1) if closest_water.get("distance_m") is not None else None,
        "draft_policy": {
            "not_publish_ready_by_script": True,
            "requires_operator_confirmation": True,
            "requires_extension_to_graph": True,
            "requires_graph_rebuild_after_publish": True,
            "do_not_use_snap_threshold_expansion": True,
        },
        "validation_precheck": {
            "quality_code": validation_quality_code,
            "issue_codes": validation_issue_codes,
        },
    }


def _validation_payload(validation) -> dict[str, Any]:
    return {
        "valid": validation.valid,
        "publishable": validation.publishable,
        "quality_code": validation.quality_code,
        "issue_count": validation.issue_count,
        "error_count": validation.error_count,
        "warning_count": validation.warning_count,
        "length_m": validation.length_m,
        "point_count": validation.point_count,
        "issue_codes": [item.issue_code for item in validation.issues],
        "issues": [item.model_dump() for item in validation.issues],
    }


def _base_item(
    task: NavigationAnnotationTask,
    issue: NavigationRouteQualityIssue | None,
    request: NavigationRouteRequest | None,
) -> dict[str, Any]:
    role = _issue_role(issue.issue_type_code if issue else task.issue_summary)
    return {
        "task_id": task.id,
        "task_no": task.task_no,
        "issue_type_code": issue.issue_type_code if issue else None,
        "issue_summary": task.issue_summary,
        "endpoint_role": role,
        "origin": _request_endpoint(request, "ORIGIN") if request else None,
        "destination": _request_endpoint(request, "DESTINATION") if request else None,
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


def _review_item(
    task: NavigationAnnotationTask,
    issue: NavigationRouteQualityIssue | None,
    request: NavigationRouteRequest | None,
    reason: str,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item = {
        **_base_item(task, issue, request),
        "status": "NEED_REVIEW",
        "review_reason": reason,
    }
    if extra:
        item.update(extra)
    return item


def _accumulate(summary: dict[str, Any], item: dict[str, Any]) -> None:
    status = str(item.get("status") or "")
    if item.get("candidate"):
        summary["candidate_count"] += 1
    if status == "DRAFT_CREATED":
        summary["draft_created_count"] += 1
    elif status == "DRAFT_EXISTS":
        summary["draft_existing_count"] += 1
    elif status == "NEED_REVIEW":
        summary["need_review_count"] += 1
    elif status == "ERROR":
        summary["error_count"] += 1


if __name__ == "__main__":
    asyncio.run(main())
