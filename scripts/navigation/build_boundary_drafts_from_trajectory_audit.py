"""Build reviewable boundary drafts when cached trajectories exceed current boundaries."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pyproj import Geod
from sqlalchemy import select
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Polygon, mapping, shape
from shapely.ops import unary_union
from shapely.validation import make_valid

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.exceptions import ValidationError
from app.models import NavigationGeometryDraft, NavigationRouteTrajectoryCache
from app.models.address import NavigationChannelBoundary
from app.modules.navigation.schemas import NavigationGeometryDraftCreateRequest, NavigationGeometryDraftValidateRequest
from app.modules.navigation.workbench_service import ARCHIVED_DRAFT_STATUSES, NavigationWorkbenchService


DEFAULT_AUDIT_PATH = Path("runtime/navigation-production/reports/channel_boundary_integrity_audit_all_debug.json")
DEFAULT_OUTPUT = Path("runtime/navigation-production/reports/trajectory_boundary_draft_report.json")
SOURCE_TYPE_CODE = "TRAJECTORY_BOUNDARY_UNION_PATCH"
GEOD = Geod(ellps="WGS84")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create BOUNDARY draft candidates from trajectory boundary audit failures.")
    parser.add_argument("--audit-report", type=Path, default=DEFAULT_AUDIT_PATH)
    parser.add_argument("--channel-id", type=int, action="append", default=None)
    parser.add_argument("--trajectory-cache-id", type=int, action="append", default=None)
    parser.add_argument("--min-coverage", type=float, default=0.98)
    parser.add_argument("--buffer-m", type=float, default=450.0)
    parser.add_argument("--create-drafts", action="store_true")
    parser.add_argument("--created-by", type=int, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    candidates = _load_candidates(
        args.audit_report,
        channel_ids=set(args.channel_id or []),
        trajectory_cache_ids=set(args.trajectory_cache_id or []),
        min_coverage=float(args.min_coverage or 0.98),
    )
    async with AsyncSessionLocal() as session:
        workbench = NavigationWorkbenchService(session)
        items: list[dict[str, Any]] = []
        summary = {
            "audit_candidate_count": len(candidates),
            "candidate_ready_count": 0,
            "candidate_review_required_count": 0,
            "boundary_draft_created_count": 0,
            "boundary_draft_review_required_count": 0,
            "boundary_draft_existing_count": 0,
            "need_review_count": 0,
            "error_count": 0,
        }
        for candidate in candidates:
            try:
                item = await _process_candidate(
                    session=session,
                    workbench=workbench,
                    candidate=candidate,
                    buffer_m=max(1.0, float(args.buffer_m or 450.0)),
                    create_drafts=bool(args.create_drafts),
                    created_by=args.created_by,
                )
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                item = {
                    **candidate,
                    "status": "ERROR",
                    "error_code": exc.__class__.__name__,
                    "error_message": str(exc),
                }
            items.append(item)
            _accumulate(summary, item)
            print(
                "trajectory_boundary="
                f"channel={candidate.get('channel_id')} trajectory={candidate.get('trajectory_cache_id')} "
                f"status={item.get('status')} draft={item.get('boundary_draft_id') or '-'} "
                f"reason={item.get('review_reason') or item.get('error_code') or '-'}"
            )
    report = {
        "report_version": "TRAJECTORY_BOUNDARY_DRAFTS_V1",
        "generated_at": datetime.now(UTC).isoformat(),
        "create_drafts": bool(args.create_drafts),
        "args": {
            "audit_report": str(args.audit_report),
            "channel_id": args.channel_id,
            "trajectory_cache_id": args.trajectory_cache_id,
            "min_coverage": args.min_coverage,
            "buffer_m": args.buffer_m,
        },
        "summary": summary,
        "items": items,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report_path={args.output}")
    print(json.dumps(summary, ensure_ascii=False))


def _load_candidates(
    audit_report: Path,
    *,
    channel_ids: set[int],
    trajectory_cache_ids: set[int],
    min_coverage: float,
) -> list[dict[str, Any]]:
    payload = json.loads(audit_report.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for record in payload.get("records") or []:
        channel_id = _int_or_none(record.get("channel_id"))
        if channel_id is None or (channel_ids and channel_id not in channel_ids):
            continue
        for coverage in record.get("trajectory_coverage") or []:
            cache_id = _int_or_none(coverage.get("trajectory_cache_id"))
            if cache_id is None or (trajectory_cache_ids and cache_id not in trajectory_cache_ids):
                continue
            coverage_ratio = float(coverage.get("coverage_ratio") or 0)
            if coverage_ratio >= min_coverage:
                continue
            rows.append(
                {
                    "channel_id": channel_id,
                    "channel_code": record.get("channel_code"),
                    "channel_name": record.get("channel_name"),
                    "boundary_id": _int_or_none(record.get("boundary_id")),
                    "trajectory_cache_id": cache_id,
                    "coverage_ratio": round(coverage_ratio, 6),
                    "provider_code": coverage.get("provider_code"),
                    "source_type_code": coverage.get("source_type_code"),
                    "quality_code": coverage.get("quality_code"),
                    "issue_codes": list(record.get("issue_codes") or []),
                }
            )
    return rows


async def _process_candidate(
    *,
    session,
    workbench: NavigationWorkbenchService,
    candidate: dict[str, Any],
    buffer_m: float,
    create_drafts: bool,
    created_by: int | None,
) -> dict[str, Any]:
    channel_id = int(candidate["channel_id"])
    trajectory = await session.get(NavigationRouteTrajectoryCache, int(candidate["trajectory_cache_id"]))
    if trajectory is None or not trajectory.geometry_json:
        return {**candidate, "status": "NEED_REVIEW", "review_reason": "TRAJECTORY_CACHE_GEOMETRY_MISSING"}
    line = _line_geometry(trajectory.geometry_json)
    if line is None or line.is_empty:
        return {**candidate, "status": "NEED_REVIEW", "review_reason": "TRAJECTORY_CACHE_GEOMETRY_INVALID"}
    current_boundary = await _current_boundary(session, channel_id)
    patch = _buffer_patch(line, buffer_m=buffer_m)
    if patch is None or patch.is_empty:
        return {**candidate, "status": "NEED_REVIEW", "review_reason": "TRAJECTORY_PATCH_EMPTY"}
    if current_boundary is not None and current_boundary.geometry_json:
        current_geometry = _polygonal(make_valid(shape(current_boundary.geometry_json)))
        if current_geometry is None or current_geometry.is_empty:
            return {**candidate, "status": "NEED_REVIEW", "review_reason": "CURRENT_BOUNDARY_GEOMETRY_INVALID"}
        candidate_geometry = _polygonal(make_valid(unary_union([current_geometry, patch])))
    else:
        current_geometry = None
        candidate_geometry = _polygonal(make_valid(patch))
    if candidate_geometry is None or candidate_geometry.is_empty:
        return {**candidate, "status": "NEED_REVIEW", "review_reason": "BOUNDARY_CANDIDATE_EMPTY"}
    before_coverage = _coverage_ratio(current_geometry, line) if current_geometry is not None else 0.0
    after_coverage = _coverage_ratio(candidate_geometry, line)
    geometry_json = _geometry_json(candidate_geometry)
    validation = await workbench.validate_geometry_draft(
        NavigationGeometryDraftValidateRequest(
            draft_type_code="BOUNDARY",
            channel_id=channel_id,
            geometry_json=geometry_json,
        )
    )
    source_trace = {
        "source_type_code": SOURCE_TYPE_CODE,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_audit_report": str(DEFAULT_AUDIT_PATH),
        "source_boundary_id": current_boundary.id if current_boundary else None,
        "source_trajectory_cache_id": int(candidate["trajectory_cache_id"]),
        "source_trajectory_provider_code": trajectory.provider_code,
        "source_trajectory_type_code": trajectory.source_type_code,
        "boundary_repair_reason": "TRAJECTORY_NOT_ENCLOSED_BY_BOUNDARY",
        "buffer_m": buffer_m,
        "before_coverage_ratio": round(before_coverage, 6),
        "after_coverage_ratio": round(after_coverage, 6),
        "patch_area_m2": round(_area_m2(patch), 2),
        "candidate_area_m2": round(_area_m2(candidate_geometry), 2),
        "validation_quality_code": validation.quality_code,
        "validation_issue_codes": [item.issue_code for item in validation.issues],
        "publish_allowed": False,
        "requires_operator_confirmation": True,
        "guardrails": [
            "该草稿只用于补齐轨迹超出当前边界的候选范围，不能自动发布",
            "发布前必须用底图、HiFleet 轨迹和水系资料确认该 buffer 覆盖的是真实水道",
            "发布后必须重新审计边界、中心线、Graph 和路径矩阵",
        ],
    }
    existing = await _existing_boundary_draft(session, channel_id=channel_id, trajectory_cache_id=int(candidate["trajectory_cache_id"]))
    base = {
        **candidate,
        "buffer_m": buffer_m,
        "current_boundary_id": current_boundary.id if current_boundary else None,
        "before_coverage_ratio": round(before_coverage, 6),
        "after_coverage_ratio": round(after_coverage, 6),
        "patch_area_m2": round(_area_m2(patch), 2),
        "candidate_area_m2": round(_area_m2(candidate_geometry), 2),
        "candidate_point_count": _point_count(geometry_json),
        "validation": {
            "valid": validation.valid,
            "publishable": validation.publishable,
            "quality_code": validation.quality_code,
            "error_count": validation.error_count,
            "warning_count": validation.warning_count,
            "issue_codes": [item.issue_code for item in validation.issues],
        },
        "source_trace": source_trace,
    }
    if after_coverage < 0.995:
        return {**base, "status": "NEED_REVIEW", "review_reason": "PATCH_STILL_DOES_NOT_COVER_TRAJECTORY"}
    review_required = validation.error_count > 0 or not validation.publishable
    if existing is not None:
        return {
            **base,
            "status": "BOUNDARY_DRAFT_EXISTS",
            "boundary_draft_id": existing.id,
            "boundary_draft_status_code": existing.status_code,
            "boundary_draft_quality_code": existing.quality_code,
        }
    if not create_drafts:
        return {
            **base,
            "status": "DRY_RUN_BOUNDARY_CANDIDATE_REVIEW_REQUIRED" if review_required else "DRY_RUN_BOUNDARY_CANDIDATE_READY",
            "review_reason": "BOUNDARY_DRAFT_VALIDATION_REVIEW_REQUIRED" if review_required else None,
        }
    try:
        draft = await workbench.create_geometry_draft(
            NavigationGeometryDraftCreateRequest(
                draft_type_code="BOUNDARY",
                draft_name=f"Trajectory boundary patch for cache {trajectory.id}",
                channel_id=channel_id,
                target_type_code="ROUTE_TRAJECTORY_CACHE",
                target_id=int(trajectory.id),
                geometry_json=geometry_json,
                source_type_code=SOURCE_TYPE_CODE,
                source_trace_json=source_trace,
            ),
            created_by=created_by,
        )
    except ValidationError as exc:
        await session.rollback()
        return {
            **base,
            "status": "NEED_REVIEW",
            "review_reason": "BOUNDARY_DRAFT_VALIDATION_REJECTED",
            "error_message": exc.message,
        }
    return {
        **base,
        "status": "BOUNDARY_DRAFT_CREATED_REVIEW_REQUIRED" if review_required else "BOUNDARY_DRAFT_CREATED",
        "review_reason": "BOUNDARY_DRAFT_VALIDATION_REVIEW_REQUIRED" if review_required else None,
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


async def _existing_boundary_draft(session, *, channel_id: int, trajectory_cache_id: int) -> NavigationGeometryDraft | None:
    rows = list(
        (
            await session.execute(
                select(NavigationGeometryDraft)
                .where(
                    NavigationGeometryDraft.draft_type_code == "BOUNDARY",
                    NavigationGeometryDraft.channel_id == channel_id,
                    NavigationGeometryDraft.source_type_code == SOURCE_TYPE_CODE,
                    NavigationGeometryDraft.target_type_code == "ROUTE_TRAJECTORY_CACHE",
                    NavigationGeometryDraft.target_id == trajectory_cache_id,
                    NavigationGeometryDraft.status_code.not_in(ARCHIVED_DRAFT_STATUSES),
                )
                .order_by(NavigationGeometryDraft.id.desc())
                .limit(1)
            )
        ).scalars()
    )
    return rows[0] if rows else None


def _line_geometry(geometry_json: dict[str, Any]) -> LineString | MultiLineString | None:
    try:
        geometry = shape(geometry_json)
    except Exception:  # noqa: BLE001
        return None
    if isinstance(geometry, (LineString, MultiLineString)):
        return geometry
    return None


def _buffer_patch(line: LineString | MultiLineString, *, buffer_m: float):
    buffer_degree = buffer_m / 111_320
    try:
        return _polygonal(make_valid(line.buffer(buffer_degree, cap_style=2, join_style=2)))
    except Exception:  # noqa: BLE001
        return _polygonal(make_valid(line.buffer(buffer_degree)))


def _polygonal(geometry):
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    if isinstance(geometry, GeometryCollection):
        polygons = [item for item in geometry.geoms if isinstance(item, (Polygon, MultiPolygon)) and not item.is_empty]
        if not polygons:
            return None
        return make_valid(unary_union(polygons))
    return None


def _coverage_ratio(boundary_geometry, line: LineString | MultiLineString) -> float:
    if boundary_geometry is None or boundary_geometry.is_empty or line.is_empty:
        return 0.0
    covered = line.intersection(boundary_geometry.buffer(0.0002))
    length = float(line.length or 0)
    if length <= 0:
        return 0.0
    return max(0.0, min(1.0, float(covered.length or 0) / length))


def _geometry_json(geometry) -> dict[str, Any]:
    return json.loads(json.dumps(mapping(make_valid(geometry))))


def _point_count(geometry_json: dict[str, Any]) -> int:
    def walk(value: Any) -> int:
        if isinstance(value, list) and value and all(isinstance(item, (int, float)) for item in value[:2]):
            return 1
        if isinstance(value, list):
            return sum(walk(item) for item in value)
        return 0

    return walk(geometry_json.get("coordinates"))


def _area_m2(geometry) -> float:
    total = 0.0
    polygons: list[Polygon] = []
    if isinstance(geometry, Polygon):
        polygons = [geometry]
    elif isinstance(geometry, MultiPolygon):
        polygons = list(geometry.geoms)
    for polygon in polygons:
        lon, lat = polygon.exterior.xy
        area, _ = GEOD.polygon_area_perimeter(lon, lat)
        holes = 0.0
        for interior in polygon.interiors:
            hole_lon, hole_lat = interior.xy
            hole_area, _ = GEOD.polygon_area_perimeter(hole_lon, hole_lat)
            holes += abs(hole_area)
        total += max(0.0, abs(area) - holes)
    return total


def _accumulate(summary: dict[str, int], item: dict[str, Any]) -> None:
    status = item.get("status")
    if status == "DRY_RUN_BOUNDARY_CANDIDATE_READY":
        summary["candidate_ready_count"] += 1
    elif status == "DRY_RUN_BOUNDARY_CANDIDATE_REVIEW_REQUIRED":
        summary["candidate_review_required_count"] += 1
    elif status == "BOUNDARY_DRAFT_CREATED":
        summary["boundary_draft_created_count"] += 1
    elif status == "BOUNDARY_DRAFT_CREATED_REVIEW_REQUIRED":
        summary["boundary_draft_created_count"] += 1
        summary["boundary_draft_review_required_count"] += 1
    elif status == "BOUNDARY_DRAFT_EXISTS":
        summary["boundary_draft_existing_count"] += 1
    elif status == "NEED_REVIEW":
        summary["need_review_count"] += 1
    elif status == "ERROR":
        summary["error_count"] += 1


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    asyncio.run(main())
