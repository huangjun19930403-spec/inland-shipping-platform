"""Import geometry-grade waybill tracks into the unified trajectory cache.

Rows are imported as REFERENCE_ONLY evidence, not VALID user-returnable routes.
They become a local evidence pool for seed, boundary, and route-quality repair.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models import NavigationRouteTrajectoryCache
from app.models.address import TransportNode
from app.modules.navigation.services.trajectory_cache_service import _line_points, _max_segment_km, _payload_hash


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_route_reference_candidates_20260608.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_route_reference_import_20260608.json"
PROVIDER_CODE = "REAL_WAYBILL"
SOURCE_TYPE_CODE = "WAYBILL_ROUTE_REFERENCE"
ENGINE_CODE = "WAYBILL_REFERENCE_IMPORT"
CACHE_STATUS_CODE = "REFERENCE_ONLY"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import waybill route reference tracks into NavigationRouteTrajectoryCache.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--only-geometry-ready", action="store_true")
    parser.add_argument("--min-quality-score", type=int, default=80)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    rows = _load_rows(
        args.input,
        limit=args.limit,
        only_geometry_ready=bool(args.only_geometry_ready),
        min_quality_score=int(args.min_quality_score),
    )
    async with AsyncSessionLocal() as session:
        node_ids = await _transport_node_ids(session)
        items: list[dict[str, Any]] = []
        summary = Counter()
        for row in rows:
            item = await _upsert_reference(session, row, node_ids=node_ids, dry_run=bool(args.dry_run))
            items.append(item)
            summary[item["status"]] += 1
        if not args.dry_run:
            await session.commit()
    report = {
        "report_version": "WAYBILL_ROUTE_REFERENCE_IMPORT_V1",
        "generated_at": datetime.now(UTC).isoformat(),
        "dry_run": bool(args.dry_run),
        "args": {
            "input": str(args.input),
            "limit": args.limit,
            "only_geometry_ready": bool(args.only_geometry_ready),
            "min_quality_score": int(args.min_quality_score),
        },
        "summary": {
            "selected_count": len(rows),
            "created_count": summary["CREATED"],
            "updated_count": summary["UPDATED"],
            "dry_run_create_count": summary["DRY_RUN_CREATE"],
            "dry_run_update_count": summary["DRY_RUN_UPDATE"],
            "skipped_count": summary["SKIPPED"],
        },
        "items": items[:500],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"report_path={args.output}")


def _load_rows(
    path: Path,
    *,
    limit: int | None,
    only_geometry_ready: bool,
    min_quality_score: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if only_geometry_ready and row.get("quality_code") != "GEOMETRY_REFERENCE_READY":
                continue
            if int(row.get("quality_score") or 0) < min_quality_score:
                continue
            geometry = row.get("geometry_json")
            if not isinstance(geometry, dict) or len(_line_points(geometry)) < 2:
                continue
            rows.append(row)
            if limit is not None and len(rows) >= max(0, int(limit)):
                break
    return rows


async def _transport_node_ids(session) -> dict[str, int]:
    rows = list((await session.execute(select(TransportNode.code, TransportNode.id))).all())
    return {str(code): int(row_id) for code, row_id in rows}


async def _upsert_reference(
    session,
    row: dict[str, Any],
    *,
    node_ids: dict[str, int],
    dry_run: bool,
) -> dict[str, Any]:
    route_key = _route_key(row)
    existing = await session.scalar(select(NavigationRouteTrajectoryCache).where(NavigationRouteTrajectoryCache.route_key == route_key))
    status = "DRY_RUN_UPDATE" if existing is not None and dry_run else "DRY_RUN_CREATE" if dry_run else "UPDATED" if existing is not None else "CREATED"
    if dry_run:
        return _item(row, route_key=route_key, status=status, cache_id=int(existing.id) if existing else None)
    cache = existing or NavigationRouteTrajectoryCache(route_key=route_key, normalized_pair_key=_normalized_pair_key(row))
    if existing is None:
        session.add(cache)
    now = datetime.now(UTC).replace(tzinfo=None)
    origin = row.get("origin") or {}
    destination = row.get("destination") or {}
    geometry = row.get("geometry_json")
    points = _line_points(geometry)
    metrics = row.get("track_metrics") if isinstance(row.get("track_metrics"), dict) else {}
    cache.normalized_pair_key = _normalized_pair_key(row)
    cache.transport_mode_code = "WATER"
    cache.planning_mode_code = "RECOMMENDED"
    cache.graph_version_id = None
    cache.graph_context_code = "REFERENCE_ONLY"
    cache.vessel_profile_hash = _payload_hash(_vessel_profile(row))
    cache.origin_ref_type_code = "TRANSPORT_NODE"
    cache.origin_ref_id = node_ids.get(str(origin.get("code") or ""))
    cache.origin_name = origin.get("name")
    cache.origin_lng = origin.get("longitude")
    cache.origin_lat = origin.get("latitude")
    cache.destination_ref_type_code = "TRANSPORT_NODE"
    cache.destination_ref_id = node_ids.get(str(destination.get("code") or ""))
    cache.destination_name = destination.get("name")
    cache.destination_lng = destination.get("longitude")
    cache.destination_lat = destination.get("latitude")
    cache.provider_code = PROVIDER_CODE
    cache.source_type_code = SOURCE_TYPE_CODE
    cache.engine_code = ENGINE_CODE
    cache.cache_status_code = CACHE_STATUS_CODE
    cache.status_code = "SUCCESS"
    cache.quality_code = "READY_WITH_WARNING"
    cache.quality_score = int(row.get("quality_score") or 0)
    cache.geometry_json = geometry
    cache.geometry_hash = _payload_hash(geometry)
    cache.distance_km = metrics.get("line_length_km") or row.get("declared_distance_km")
    cache.estimated_duration_hour = None
    cache.point_count = len(points)
    cache.max_segment_km = _max_segment_km(geometry)
    cache.edge_ids = []
    cache.channel_ids = []
    cache.passed_node_ids = []
    cache.passed_lock_count = 0
    cache.passed_bridge_count = 0
    cache.issue_summary_json = [
        {
            "issue_type_code": "REFERENCE_ONLY_NOT_USER_RETURNABLE",
            "severity_code": "INFO",
            "message": "Real waybill track imported as route/seed evidence only; not a validated route cache.",
            "suggestion": "Promote only after water coverage, endpoint snap, boundary, and graph validation pass.",
        }
    ]
    cache.validation_summary_json = {
        "source": "import_waybill_route_references",
        "cache_status_code": CACHE_STATUS_CODE,
        "waybill_code": row.get("waybill_code"),
        "route_code": row.get("route_code"),
        "route_name": row.get("route_name"),
        "water_systems": row.get("water_systems") or [],
        "track_metrics": metrics,
        "condition_profile": _condition_profile(row),
        "promotion_guardrails": [
            "REFERENCE_ONLY rows are excluded from get_returnable cache lookups",
            "Do not mark VALID until water/channel/boundary and graph checks pass",
            "Sparse or condition-only waybill rows must not be used as geometry",
        ],
    }
    cache.own_algorithm_summary_json = None
    cache.hifleet_summary_json = None
    cache.hifleet_cache_id = None
    cache.original_route_request_id = None
    cache.original_route_result_id = None
    cache.error_code = None
    cache.error_message = None
    cache.raw_request_json = {
        "source_type_code": SOURCE_TYPE_CODE,
        "waybill_code": row.get("waybill_code"),
        "route_code": row.get("route_code"),
        "origin": origin,
        "destination": destination,
        "vessel_profile": _vessel_profile(row),
    }
    cache.raw_response_json = row
    cache.generated_at = now
    await session.flush()
    return _item(row, route_key=route_key, status=status, cache_id=int(cache.id))


def _route_key(row: dict[str, Any]) -> str:
    return f"WAYBILL_ROUTE_REFERENCE_V1|{row.get('waybill_code') or row.get('row_no')}"


def _normalized_pair_key(row: dict[str, Any]) -> str:
    origin = row.get("origin") or {}
    destination = row.get("destination") or {}
    parts = sorted([str(origin.get("code") or ""), str(destination.get("code") or "")])
    return "WAYBILL_ROUTE_REFERENCE_V1|" + "||".join(parts)


def _vessel_profile(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "tonnage_min": row.get("tonnage_min"),
        "tonnage_max": row.get("tonnage_max"),
        "ship_width_max_m": row.get("ship_width_max_m"),
        "ship_length_max_m": row.get("ship_length_max_m"),
    }


def _condition_profile(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "water_systems": row.get("water_systems") or [],
        "cargo_codes": row.get("cargo_codes") or [],
        "declared_distance_km": row.get("declared_distance_km"),
        **_vessel_profile(row),
    }


def _item(row: dict[str, Any], *, route_key: str, status: str, cache_id: int | None) -> dict[str, Any]:
    return {
        "status": status,
        "trajectory_cache_id": cache_id,
        "route_key": route_key,
        "waybill_code": row.get("waybill_code"),
        "route_code": row.get("route_code"),
        "quality_score": row.get("quality_score"),
        "point_count": (row.get("track_metrics") or {}).get("cleaned_point_count"),
        "max_segment_km": (row.get("track_metrics") or {}).get("max_segment_km"),
    }


if __name__ == "__main__":
    asyncio.run(main())
