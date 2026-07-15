"""Build reviewable boundary drafts for blocked SNAP_REPAIR access centerlines."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pyproj import Geod
from sqlalchemy import select
from shapely.geometry import LineString, MultiPolygon, Polygon, mapping, shape
from shapely.ops import unary_union
from shapely.validation import make_valid

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.exceptions import ValidationError
from app.models import NavigationGeometryDraft
from app.models.address import NavigationChannelBoundary
from app.modules.navigation.schemas import NavigationGeometryDraftCreateRequest, NavigationGeometryDraftValidateRequest
from app.modules.navigation.workbench_service import ARCHIVED_DRAFT_STATUSES, NavigationWorkbenchService


OUTPUT_PATH = Path("runtime/navigation-production/reports/snap_repair_boundary_draft_report.json")
CENTERLINE_SOURCE_TYPES = {"HIFLEET_SNAP_REPAIR_ACCESS", "HIFLEET_ROUTE_CENTERLINE_SEED"}
SOURCE_TYPE_CODE = "SNAP_REPAIR_BOUNDARY_UNION_PATCH"
GEOD = Geod(ellps="WGS84")
PUBLISH_BOUNDARY_TOLERANCE_DEGREE = 0.0002


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create BOUNDARY draft candidates from blocked SNAP_REPAIR centerline drafts.")
    parser.add_argument("--centerline-draft-id", type=int, action="append", default=None)
    parser.add_argument("--task-id", type=int, action="append", default=None)
    parser.add_argument("--centerline-source-type", type=str, action="append", default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--buffer-m", type=float, default=350.0)
    parser.add_argument("--create-drafts", action="store_true")
    parser.add_argument("--created-by", type=int, default=None)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    async with AsyncSessionLocal() as session:
        centerline_drafts = await _load_centerline_drafts(
            session,
            draft_ids=args.centerline_draft_id,
            task_ids=args.task_id,
            source_types={item.upper() for item in args.centerline_source_type} if args.centerline_source_type else CENTERLINE_SOURCE_TYPES,
            limit=max(1, int(args.limit or 1)),
        )
        workbench = NavigationWorkbenchService(session)
        items: list[dict[str, Any]] = []
        summary = {
            "centerline_draft_count": len(centerline_drafts),
            "candidate_count": 0,
            "boundary_draft_created_count": 0,
            "boundary_draft_existing_count": 0,
            "need_review_count": 0,
            "error_count": 0,
        }
        for draft in centerline_drafts:
            try:
                item = await _process_centerline_draft(
                    session=session,
                    workbench=workbench,
                    centerline_draft=draft,
                    buffer_m=max(1.0, float(args.buffer_m or 350.0)),
                    create_drafts=bool(args.create_drafts),
                    created_by=args.created_by,
                )
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                item = {
                    "centerline_draft_id": draft.id,
                    "status": "ERROR",
                    "error_code": exc.__class__.__name__,
                    "error_message": str(exc),
                }
            items.append(item)
            _accumulate(summary, item)
            print(
                "snap_repair_boundary="
                f"centerline_draft={draft.id} status={item.get('status')} "
                f"boundary_draft={item.get('boundary_draft_id') or '-'} "
                f"reason={item.get('review_reason') or item.get('error_code') or '-'}"
            )
        report = {
            "report_version": "SNAP_REPAIR_BOUNDARY_DRAFTS_V1",
            "generated_at": datetime.now(UTC).isoformat(),
            "create_drafts": bool(args.create_drafts),
            "args": {
                "centerline_draft_id": args.centerline_draft_id,
                "task_id": args.task_id,
                "centerline_source_type": args.centerline_source_type,
                "limit": args.limit,
                "buffer_m": args.buffer_m,
            },
            "summary": summary,
            "items": items,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report_path={args.output}")
        print(json.dumps(summary, ensure_ascii=False))


async def _load_centerline_drafts(
    session,
    *,
    draft_ids: list[int] | None,
    task_ids: list[int] | None,
    source_types: set[str],
    limit: int,
) -> list[NavigationGeometryDraft]:
    stmt = (
        select(NavigationGeometryDraft)
        .where(
            NavigationGeometryDraft.draft_type_code == "CENTERLINE",
            NavigationGeometryDraft.source_type_code.in_(source_types),
            NavigationGeometryDraft.status_code.not_in(ARCHIVED_DRAFT_STATUSES),
        )
        .order_by(NavigationGeometryDraft.id)
    )
    if draft_ids:
        stmt = stmt.where(NavigationGeometryDraft.id.in_(draft_ids))
    if task_ids:
        stmt = stmt.where(
            NavigationGeometryDraft.target_type_code == "ANNOTATION_TASK",
            NavigationGeometryDraft.target_id.in_(task_ids),
        )
    if not draft_ids and not task_ids:
        stmt = stmt.limit(limit)
    return list((await session.execute(stmt)).scalars())


async def _process_centerline_draft(
    *,
    session,
    workbench: NavigationWorkbenchService,
    centerline_draft: NavigationGeometryDraft,
    buffer_m: float,
    create_drafts: bool,
    created_by: int | None,
) -> dict[str, Any]:
    if centerline_draft.channel_id is None:
        return _review_item(centerline_draft, "CENTERLINE_DRAFT_HAS_NO_CHANNEL")
    line = _line_from_draft(centerline_draft)
    if line is None:
        return _review_item(centerline_draft, "CENTERLINE_DRAFT_GEOMETRY_INVALID")
    current_boundary = await _current_boundary(session, int(centerline_draft.channel_id))
    patch = _buffer_patch(line, buffer_m=buffer_m)
    if current_boundary is not None:
        boundary_geometry = _polygonal(make_valid(shape(current_boundary.geometry_json)))
        if boundary_geometry is None:
            return _review_item(centerline_draft, "CURRENT_BOUNDARY_GEOMETRY_INVALID")
        candidate_geometry = _polygonal(make_valid(unary_union([boundary_geometry, patch])))
    else:
        candidate_geometry = _polygonal(make_valid(patch))
    if candidate_geometry is None or candidate_geometry.is_empty:
        return _review_item(centerline_draft, "BOUNDARY_PATCH_EMPTY")
    coverage = _coverage_payload(candidate_geometry, line)
    if not coverage["covers_centerline"] and not coverage["tolerance_covers_centerline"]:
        return {
            **_base_item(centerline_draft),
            "status": "NEED_REVIEW",
            "review_reason": "BOUNDARY_PATCH_DOES_NOT_COVER_CENTERLINE",
            "buffer_m": buffer_m,
            "current_boundary_id": current_boundary.id if current_boundary else None,
            "patch_area_m2": round(_area_m2(patch), 2),
            "candidate_area_m2": round(_area_m2(candidate_geometry), 2),
            "coverage": coverage,
        }
    geometry_json = _geometry_json(candidate_geometry)
    existing = await _existing_boundary_draft(session, centerline_draft_id=int(centerline_draft.id), channel_id=int(centerline_draft.channel_id))
    validation = await workbench.validate_geometry_draft(
        NavigationGeometryDraftValidateRequest(
            draft_type_code="BOUNDARY",
            channel_id=int(centerline_draft.channel_id),
            geometry_json=geometry_json,
        )
    )
    source_trace = _source_trace(
        centerline_draft=centerline_draft,
        current_boundary=current_boundary,
        patch=patch,
        candidate=candidate_geometry,
        buffer_m=buffer_m,
        validation_quality_code=validation.quality_code,
        validation_issue_codes=[item.issue_code for item in validation.issues],
    )
    payload = {
        **_base_item(centerline_draft),
        "buffer_m": buffer_m,
        "current_boundary_id": current_boundary.id if current_boundary else None,
        "patch_area_m2": round(_area_m2(patch), 2),
        "candidate_area_m2": round(_area_m2(candidate_geometry), 2),
        "candidate_point_count": _point_count(geometry_json),
        "coverage": coverage,
        "validation": _validation_payload(validation),
        "source_trace": source_trace,
    }
    if existing is not None:
        return {
            **payload,
            "status": "BOUNDARY_DRAFT_EXISTS",
            "boundary_draft_id": existing.id,
            "boundary_draft_status_code": existing.status_code,
            "boundary_draft_quality_code": existing.quality_code,
        }
    if not create_drafts:
        return {**payload, "status": "DRY_RUN_BOUNDARY_CANDIDATE_READY"}
    try:
        draft = await workbench.create_geometry_draft(
            NavigationGeometryDraftCreateRequest(
                draft_type_code="BOUNDARY",
                draft_name=f"SNAP_REPAIR boundary patch for centerline draft {centerline_draft.id}",
                channel_id=int(centerline_draft.channel_id),
                target_type_code="GEOMETRY_DRAFT",
                target_id=int(centerline_draft.id),
                geometry_json=geometry_json,
                source_type_code=SOURCE_TYPE_CODE,
                source_trace_json=source_trace,
            ),
            created_by=created_by,
        )
    except ValidationError as exc:
        await session.rollback()
        return {
            **payload,
            "status": "NEED_REVIEW",
            "review_reason": "BOUNDARY_DRAFT_VALIDATION_REJECTED",
            "error_message": exc.message,
        }
    return {
        **payload,
        "status": "BOUNDARY_DRAFT_CREATED",
        "boundary_draft_id": draft.id,
        "boundary_draft_status_code": draft.status_code,
        "boundary_draft_quality_code": draft.quality_code,
    }


async def _current_boundary(session, channel_id: int) -> NavigationChannelBoundary | None:
    return (
        await session.execute(
            select(NavigationChannelBoundary)
            .where(
                NavigationChannelBoundary.channel_id == channel_id,
                NavigationChannelBoundary.is_current.is_(True),
                NavigationChannelBoundary.geometry_status_code == "AVAILABLE",
            )
            .order_by(NavigationChannelBoundary.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _existing_boundary_draft(session, *, centerline_draft_id: int, channel_id: int) -> NavigationGeometryDraft | None:
    return (
        await session.execute(
            select(NavigationGeometryDraft)
            .where(
                NavigationGeometryDraft.draft_type_code == "BOUNDARY",
                NavigationGeometryDraft.source_type_code == SOURCE_TYPE_CODE,
                NavigationGeometryDraft.target_type_code == "GEOMETRY_DRAFT",
                NavigationGeometryDraft.target_id == centerline_draft_id,
                NavigationGeometryDraft.channel_id == channel_id,
                NavigationGeometryDraft.status_code.not_in(ARCHIVED_DRAFT_STATUSES),
            )
            .order_by(NavigationGeometryDraft.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _line_from_draft(draft: NavigationGeometryDraft) -> LineString | None:
    try:
        geometry = shape(draft.geometry_json)
    except Exception:  # noqa: BLE001
        return None
    if isinstance(geometry, LineString) and len(geometry.coords) >= 2:
        return geometry
    return None


def _buffer_patch(line: LineString, *, buffer_m: float) -> Polygon | MultiPolygon:
    buffer_degree = buffer_m / 111_320
    patch = make_valid(line.buffer(buffer_degree, cap_style=1, join_style=2))
    polygonal = _polygonal(patch)
    if polygonal is None:
        raise ValidationError("中心线 buffer 无法生成边界补丁", code="BOUNDARY_PATCH_BUFFER_FAILED")
    return polygonal


def _polygonal(geometry: Any) -> Polygon | MultiPolygon | None:
    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    if hasattr(geometry, "geoms"):
        parts = [part for part in geometry.geoms if isinstance(part, (Polygon, MultiPolygon)) and not part.is_empty]
        if not parts:
            return None
        return _polygonal(unary_union(parts))
    return None


def _geometry_json(geometry: Polygon | MultiPolygon) -> dict[str, Any]:
    return json.loads(json.dumps(mapping(geometry)))


def _area_m2(geometry: Polygon | MultiPolygon) -> float:
    return abs(float(GEOD.geometry_area_perimeter(geometry)[0]))


def _point_count(geometry_json: dict[str, Any]) -> int:
    count = 0

    def walk(value: Any) -> None:
        nonlocal count
        if not isinstance(value, (list, tuple)):
            return
        if len(value) >= 2 and all(isinstance(value[index], (int, float)) for index in (0, 1)):
            count += 1
            return
        for child in value:
            walk(child)

    walk(geometry_json.get("coordinates"))
    return count


def _source_trace(
    *,
    centerline_draft: NavigationGeometryDraft,
    current_boundary: NavigationChannelBoundary | None,
    patch: Polygon | MultiPolygon,
    candidate: Polygon | MultiPolygon,
    buffer_m: float,
    validation_quality_code: str,
    validation_issue_codes: list[str],
) -> dict[str, Any]:
    centerline_trace = centerline_draft.source_trace_json if isinstance(centerline_draft.source_trace_json, dict) else {}
    return {
        "source": SOURCE_TYPE_CODE,
        "generated_at": datetime.now(UTC).isoformat(),
        "centerline_draft_id": int(centerline_draft.id),
        "snap_repair_task_id": centerline_trace.get("snap_repair_task_id"),
        "route_quality_issue_id": centerline_trace.get("route_quality_issue_id"),
        "trajectory_cache_id": centerline_trace.get("trajectory_cache_id"),
        "hifleet_cache_id": centerline_trace.get("hifleet_cache_id"),
        "channel_resolution": centerline_trace.get("channel_resolution"),
        "current_boundary_id": int(current_boundary.id) if current_boundary else None,
        "operation_code": "UNION_PATCH",
        "buffer_m": buffer_m,
        "buffer_cap_style": "ROUND",
        "patch_area_m2": round(_area_m2(patch), 2),
        "candidate_area_m2": round(_area_m2(candidate), 2),
        "coverage": _coverage_payload(candidate, shape(centerline_draft.geometry_json)),
        "draft_policy": {
            "not_publish_ready_by_script": True,
            "requires_operator_confirmation": True,
            "requires_centerline_revalidation_after_boundary_publish": True,
            "requires_graph_rebuild_after_centerline_publish": True,
        },
        "validation_precheck": {
            "quality_code": validation_quality_code,
            "issue_codes": validation_issue_codes,
        },
    }


def _coverage_payload(candidate: Polygon | MultiPolygon, line: LineString) -> dict[str, Any]:
    return {
        "covers_centerline": bool(candidate.covers(line)),
        "tolerance_covers_centerline": bool(candidate.buffer(PUBLISH_BOUNDARY_TOLERANCE_DEGREE).covers(line)),
        "distance_degree": float(candidate.distance(line)),
        "intersection_length_degree": float(candidate.intersection(line).length),
        "line_length_degree": float(line.length),
        "tolerance_degree": PUBLISH_BOUNDARY_TOLERANCE_DEGREE,
    }


def _validation_payload(validation) -> dict[str, Any]:
    return {
        "valid": validation.valid,
        "publishable": validation.publishable,
        "quality_code": validation.quality_code,
        "issue_count": validation.issue_count,
        "error_count": validation.error_count,
        "warning_count": validation.warning_count,
        "area_m2": validation.area_m2,
        "point_count": validation.point_count,
        "issue_codes": [item.issue_code for item in validation.issues],
        "issues": [_issue_payload(item) for item in validation.issues],
    }


def _issue_payload(issue) -> dict[str, Any]:
    geometry = issue.geometry_json if isinstance(issue.geometry_json, dict) else None
    return {
        "issue_code": issue.issue_code,
        "severity_code": issue.severity_code,
        "message": issue.message,
        "suggestion": issue.suggestion,
        "geometry_type": geometry.get("type") if geometry else None,
        "geometry_bbox": _geometry_bbox(geometry) if geometry else None,
    }


def _geometry_bbox(geometry_json: dict[str, Any]) -> dict[str, float] | None:
    coords: list[tuple[float, float]] = []

    def walk(value: Any) -> None:
        if not isinstance(value, (list, tuple)):
            return
        if len(value) >= 2 and all(isinstance(value[index], (int, float)) for index in (0, 1)):
            coords.append((float(value[0]), float(value[1])))
            return
        for child in value:
            walk(child)

    walk(geometry_json.get("coordinates"))
    if not coords:
        return None
    return {
        "min_lng": min(item[0] for item in coords),
        "min_lat": min(item[1] for item in coords),
        "max_lng": max(item[0] for item in coords),
        "max_lat": max(item[1] for item in coords),
    }


def _base_item(centerline_draft: NavigationGeometryDraft) -> dict[str, Any]:
    trace = centerline_draft.source_trace_json if isinstance(centerline_draft.source_trace_json, dict) else {}
    return {
        "centerline_draft_id": int(centerline_draft.id),
        "centerline_draft_status_code": centerline_draft.status_code,
        "centerline_draft_quality_code": centerline_draft.quality_code,
        "channel_id": int(centerline_draft.channel_id) if centerline_draft.channel_id is not None else None,
        "snap_repair_task_id": trace.get("snap_repair_task_id"),
        "route_quality_issue_id": trace.get("route_quality_issue_id"),
        "trajectory_cache_id": trace.get("trajectory_cache_id"),
        "hifleet_cache_id": trace.get("hifleet_cache_id"),
    }


def _review_item(centerline_draft: NavigationGeometryDraft, reason: str) -> dict[str, Any]:
    return {
        **_base_item(centerline_draft),
        "status": "NEED_REVIEW",
        "review_reason": reason,
    }


def _accumulate(summary: dict[str, Any], item: dict[str, Any]) -> None:
    status = str(item.get("status") or "")
    if status in {"DRY_RUN_BOUNDARY_CANDIDATE_READY", "BOUNDARY_DRAFT_CREATED", "BOUNDARY_DRAFT_EXISTS"}:
        summary["candidate_count"] += 1
    if status == "BOUNDARY_DRAFT_CREATED":
        summary["boundary_draft_created_count"] += 1
    elif status == "BOUNDARY_DRAFT_EXISTS":
        summary["boundary_draft_existing_count"] += 1
    elif status == "NEED_REVIEW":
        summary["need_review_count"] += 1
    elif status == "ERROR":
        summary["error_count"] += 1


if __name__ == "__main__":
    asyncio.run(main())
