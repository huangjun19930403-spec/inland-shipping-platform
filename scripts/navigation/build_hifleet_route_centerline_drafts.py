"""Build full centerline drafts from local HiFleet/reference trajectory cache rows."""

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
from app.models import NavigationGeometryDraft, NavigationRouteTrajectoryCache
from app.models.navigation import NavigationHifleetRouteCache
from app.modules.navigation.schemas import NavigationGeometryDraftCreateRequest, NavigationGeometryDraftValidateRequest
from app.modules.navigation.workbench_service import ARCHIVED_DRAFT_STATUSES, NavigationWorkbenchService


OUTPUT_PATH = Path("runtime/navigation-production/reports/hifleet_route_centerline_draft_report.json")
SOURCE_TYPE_CODE = "HIFLEET_ROUTE_CENTERLINE_SEED"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create CENTERLINE drafts from full local HiFleet route geometries.")
    parser.add_argument("--trajectory-cache-id", type=int, action="append", default=None)
    parser.add_argument("--hifleet-cache-id", type=int, action="append", default=None)
    parser.add_argument("--channel-id", type=int, required=True)
    parser.add_argument("--create-drafts", action="store_true")
    parser.add_argument("--created-by", type=int, default=None)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    async with AsyncSessionLocal() as session:
        workbench = NavigationWorkbenchService(session)
        sources = await _load_sources(
            session,
            trajectory_cache_ids=args.trajectory_cache_id or [],
            hifleet_cache_ids=args.hifleet_cache_id or [],
        )
        items: list[dict[str, Any]] = []
        summary = {
            "source_count": len(sources),
            "candidate_count": 0,
            "draft_created_count": 0,
            "draft_existing_count": 0,
            "need_review_count": 0,
            "error_count": 0,
        }
        for source in sources:
            try:
                item = await _process_source(
                    session=session,
                    workbench=workbench,
                    source=source,
                    channel_id=args.channel_id,
                    create_drafts=bool(args.create_drafts),
                    created_by=args.created_by,
                )
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                item = {
                    "source": _source_ref(source),
                    "status": "ERROR",
                    "error_code": exc.__class__.__name__,
                    "error_message": str(exc),
                }
            items.append(item)
            _accumulate(summary, item)
            print(
                "hifleet_route_centerline="
                f"source={item.get('source')} status={item.get('status')} "
                f"draft={item.get('draft_id') or '-'} review={item.get('review_reason') or item.get('error_code') or '-'}"
            )
        report = {
            "report_version": "HIFLEET_ROUTE_CENTERLINE_DRAFTS_V1",
            "generated_at": datetime.now(UTC).isoformat(),
            "create_drafts": bool(args.create_drafts),
            "args": {
                "trajectory_cache_id": args.trajectory_cache_id,
                "hifleet_cache_id": args.hifleet_cache_id,
                "channel_id": args.channel_id,
            },
            "summary": summary,
            "items": items,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report_path={args.output}")
        print(json.dumps(summary, ensure_ascii=False))


async def _load_sources(
    session,
    *,
    trajectory_cache_ids: list[int],
    hifleet_cache_ids: list[int],
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    if trajectory_cache_ids:
        rows = list(
            (
                await session.execute(
                    select(NavigationRouteTrajectoryCache)
                    .where(NavigationRouteTrajectoryCache.id.in_(trajectory_cache_ids))
                    .order_by(NavigationRouteTrajectoryCache.id)
                )
            ).scalars()
        )
        for row in rows:
            sources.append(
                {
                    "source_model": "NavigationRouteTrajectoryCache",
                    "source_type": "TRAJECTORY_CACHE",
                    "source_id": int(row.id),
                    "hifleet_cache_id": row.hifleet_cache_id,
                    "geometry": row.geometry_json,
                    "distance_km": float(row.distance_km) if row.distance_km is not None else None,
                    "point_count": row.point_count,
                    "provider_code": row.provider_code,
                    "source_type_code": row.source_type_code,
                    "origin_ref_type_code": row.origin_ref_type_code,
                    "origin_ref_id": row.origin_ref_id,
                    "destination_ref_type_code": row.destination_ref_type_code,
                    "destination_ref_id": row.destination_ref_id,
                }
            )
    if hifleet_cache_ids:
        rows = list(
            (
                await session.execute(
                    select(NavigationHifleetRouteCache)
                    .where(NavigationHifleetRouteCache.id.in_(hifleet_cache_ids))
                    .order_by(NavigationHifleetRouteCache.id)
                )
            ).scalars()
        )
        for row in rows:
            sources.append(
                {
                    "source_model": "NavigationHifleetRouteCache",
                    "source_type": "HIFLEET_CACHE",
                    "source_id": int(row.id),
                    "hifleet_cache_id": int(row.id),
                    "geometry": row.geometry_json,
                    "distance_km": float(row.distance_km) if row.distance_km is not None else None,
                    "point_count": row.point_count,
                    "provider_code": "HIFLEET",
                    "source_type_code": "HIFLEET_CACHE",
                }
            )
    return sources


async def _process_source(
    *,
    session,
    workbench: NavigationWorkbenchService,
    source: dict[str, Any],
    channel_id: int,
    create_drafts: bool,
    created_by: int | None,
) -> dict[str, Any]:
    line = _line_from_source(source)
    geometry = mapping(line)
    validation = await workbench.validate_geometry_draft(
        NavigationGeometryDraftValidateRequest(
            draft_type_code="CENTERLINE",
            channel_id=channel_id,
            geometry_json=geometry,
        )
    )
    item = {
        "source": _source_ref(source),
        "status": "DRY_RUN",
        "candidate": {
            "channel_id": channel_id,
            "point_count": len(line.coords),
            "distance_km": source.get("distance_km"),
            "bbox": list(line.bounds),
        },
        "validation": _validation_summary(validation),
        "review_reason": _review_reason(validation),
    }
    if not create_drafts:
        return item
    existing = await _existing_draft(session, source=source, channel_id=channel_id)
    if existing is not None:
        item.update(
            {
                "status": "EXISTING",
                "draft_id": int(existing.id),
                "draft_status_code": existing.status_code,
                "draft_quality_code": existing.quality_code,
            }
        )
        return item
    draft = await workbench.create_geometry_draft(
        NavigationGeometryDraftCreateRequest(
            draft_type_code="CENTERLINE",
            draft_name=f"HiFleet route seed {_source_ref(source)}",
            channel_id=channel_id,
            target_type_code=source["source_type"],
            target_id=int(source["source_id"]),
            geometry_json=geometry,
            source_type_code=SOURCE_TYPE_CODE,
            source_trace_json={
                "source": "build_hifleet_route_centerline_drafts",
                "source_model": source["source_model"],
                "source_type": source["source_type"],
                "source_id": int(source["source_id"]),
                "hifleet_cache_id": source.get("hifleet_cache_id"),
                "provider_code": source.get("provider_code"),
                "source_type_code": source.get("source_type_code"),
                "distance_km": source.get("distance_km"),
                "point_count": len(line.coords),
                "origin_ref_type_code": source.get("origin_ref_type_code"),
                "origin_ref_id": source.get("origin_ref_id"),
                "destination_ref_type_code": source.get("destination_ref_type_code"),
                "destination_ref_id": source.get("destination_ref_id"),
            },
        ),
        created_by=created_by,
    )
    item.update(
        {
            "status": "CREATED",
            "draft_id": draft.id,
            "draft_status_code": draft.status_code,
            "draft_quality_code": draft.quality_code,
            "draft_review_comment": draft.review_comment,
        }
    )
    return item


async def _existing_draft(session, *, source: dict[str, Any], channel_id: int) -> NavigationGeometryDraft | None:
    return (
        await session.execute(
            select(NavigationGeometryDraft)
            .where(
                NavigationGeometryDraft.draft_type_code == "CENTERLINE",
                NavigationGeometryDraft.channel_id == channel_id,
                NavigationGeometryDraft.source_type_code == SOURCE_TYPE_CODE,
                NavigationGeometryDraft.target_type_code == source["source_type"],
                NavigationGeometryDraft.target_id == int(source["source_id"]),
                NavigationGeometryDraft.status_code.not_in(ARCHIVED_DRAFT_STATUSES),
            )
            .order_by(NavigationGeometryDraft.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _line_from_source(source: dict[str, Any]) -> LineString:
    geometry_json = source.get("geometry")
    geometry = shape(geometry_json)
    if not isinstance(geometry, LineString) or geometry.is_empty or len(geometry.coords) < 2:
        raise ValueError(f"{_source_ref(source)} geometry is not a usable LineString")
    return geometry


def _validation_summary(validation) -> dict[str, Any]:
    return {
        "quality_code": validation.quality_code,
        "publishable": validation.publishable,
        "issue_count": validation.issue_count,
        "error_count": validation.error_count,
        "warning_count": validation.warning_count,
        "length_m": validation.length_m,
        "point_count": validation.point_count,
        "issue_codes": [issue.issue_code for issue in validation.issues],
    }


def _review_reason(validation) -> str | None:
    issue = next((item for item in validation.issues if item.severity_code == "ERROR"), None)
    if issue is None:
        issue = next((item for item in validation.issues if item.severity_code == "WARNING"), None)
    return issue.issue_code if issue else None


def _source_ref(source: dict[str, Any]) -> str:
    return f"{source.get('source_type')}:{source.get('source_id')}"


def _accumulate(summary: dict[str, Any], item: dict[str, Any]) -> None:
    status = item.get("status")
    if status in {"DRY_RUN", "CREATED", "EXISTING"}:
        summary["candidate_count"] += 1
    if status == "CREATED":
        summary["draft_created_count"] += 1
    if status == "EXISTING":
        summary["draft_existing_count"] += 1
    if item.get("review_reason"):
        summary["need_review_count"] += 1
    if status == "ERROR":
        summary["error_count"] += 1


if __name__ == "__main__":
    asyncio.run(main())
