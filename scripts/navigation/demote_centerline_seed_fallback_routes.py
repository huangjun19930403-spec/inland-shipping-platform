"""Demote centerline-seed fallback routes from user-returnable data.

CENTERLINE_SEED_FALLBACK is useful diagnostic evidence when the graph cannot
connect an OD pair, but it bypasses active graph validation. These rows must not
be returned as usable route geometry.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models import (
    NavigationRouteQualityIssue,
    NavigationRouteRequest,
    NavigationRouteResult,
    NavigationRouteTrajectoryCache,
)


SOURCE_TYPE = "CENTERLINE_SEED_FALLBACK"
ISSUE_CODE = "CENTERLINE_SEED_NOT_GRAPH_VALIDATED"
REPORT_DIR = Path("runtime/navigation-production/reports")


def _json_with_demote(summary: dict[str, Any] | None, *, geometry: dict[str, Any] | None, demoted_at: str) -> dict[str, Any]:
    next_summary = dict(summary or {})
    next_summary.setdefault("candidate_geometry_json", geometry)
    next_summary["centerline_seed_returnable"] = False
    next_summary["demoted_from_user_returnable_at"] = demoted_at
    next_summary["demotion_reason"] = ISSUE_CODE
    return next_summary


async def run(*, apply: bool, output: Path) -> dict[str, Any]:
    demoted_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    report: dict[str, Any] = {
        "applied": apply,
        "demoted_at": demoted_at,
        "cache_rows": [],
        "result_rows": [],
        "request_ids": [],
        "issue_rows_added": 0,
        "guardrail": (
            "CENTERLINE_SEED_FALLBACK bypasses active graph validation and is diagnostic only; "
            "route geometry is preserved in summary/issue evidence, not returned as SUCCESS geometry."
        ),
    }
    async with AsyncSessionLocal() as session:
        cache_rows = list(
            (
                await session.execute(
                    select(NavigationRouteTrajectoryCache).where(
                        NavigationRouteTrajectoryCache.source_type_code == SOURCE_TYPE,
                        NavigationRouteTrajectoryCache.cache_status_code == "VALID",
                    )
                )
            ).scalars()
        )
        result_rows = list(
            (
                await session.execute(
                    select(NavigationRouteResult).where(
                        NavigationRouteResult.result_type_code == SOURCE_TYPE,
                        NavigationRouteResult.status_code == "SUCCESS",
                    )
                )
            ).scalars()
        )
        result_ids = [int(row.id) for row in result_rows]
        existing_issue_result_ids = set()
        if result_ids:
            existing_issue_result_ids = {
                int(row[0])
                for row in (
                    await session.execute(
                        select(NavigationRouteQualityIssue.route_result_id).where(
                            NavigationRouteQualityIssue.route_result_id.in_(result_ids),
                            NavigationRouteQualityIssue.issue_type_code == ISSUE_CODE,
                        )
                    )
                ).all()
            }
        for row in cache_rows:
            report["cache_rows"].append(
                {
                    "id": int(row.id),
                    "route_key": row.route_key,
                    "previous_cache_status_code": row.cache_status_code,
                    "previous_status_code": row.status_code,
                    "previous_quality_code": row.quality_code,
                    "point_count": row.point_count,
                }
            )
            if apply:
                row.validation_summary_json = _json_with_demote(
                    row.validation_summary_json,
                    geometry=row.geometry_json,
                    demoted_at=demoted_at,
                )
                row.cache_status_code = "NEED_REVIEW"
                row.status_code = "FAILED"
                row.quality_code = "FAILED"
                row.quality_score = 0
                row.error_code = ISSUE_CODE
                row.error_message = "中心线 seed 未通过 active Graph 连通验证，不能作为可用路径返回。"
                row.geometry_json = None
                row.geometry_hash = None
                row.distance_km = None
                row.estimated_duration_hour = None
        for row in result_rows:
            report["result_rows"].append(
                {
                    "id": int(row.id),
                    "request_id": int(row.request_id),
                    "previous_status_code": row.status_code,
                    "previous_quality_code": row.quality_code,
                    "point_count": len(((row.geometry_json or {}).get("coordinates") or []))
                    if isinstance(row.geometry_json, dict)
                    else 0,
                }
            )
            if int(row.request_id) not in report["request_ids"]:
                report["request_ids"].append(int(row.request_id))
            if apply:
                candidate_geometry = row.geometry_json
                row.quality_summary_json = _json_with_demote(
                    row.quality_summary_json,
                    geometry=candidate_geometry,
                    demoted_at=demoted_at,
                )
                row.status_code = "FAILED"
                row.quality_code = "FAILED"
                row.quality_score = 0
                row.geometry_json = None
                row.distance_km = None
                row.estimated_duration_hour = None
                if int(row.id) not in existing_issue_result_ids:
                    session.add(
                        NavigationRouteQualityIssue(
                            route_result_id=row.id,
                            issue_type_code=ISSUE_CODE,
                            severity_code="ERROR",
                            geometry_json=candidate_geometry,
                            message="中心线 seed 未通过 active Graph 连通验证，已降级为诊断证据。",
                            suggestion="先把该 seed 并入生产 Graph 并重建验证，再允许返回用户路径。",
                        )
                    )
                    report["issue_rows_added"] += 1
        if apply and report["request_ids"]:
            requests = list(
                (
                    await session.execute(
                        select(NavigationRouteRequest).where(NavigationRouteRequest.id.in_(report["request_ids"]))
                    )
                ).scalars()
            )
            for request in requests:
                request.status_code = "FAILED"
                request.error_code = ISSUE_CODE
                request.error_message = "中心线 seed 未通过 active Graph 连通验证，不能作为可用路径返回。"
        if apply:
            await session.commit()
    report["cache_row_count"] = len(report["cache_rows"])
    report["result_row_count"] = len(report["result_rows"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=REPORT_DIR / f"centerline_seed_fallback_demotion_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}.json",
    )
    args = parser.parse_args()
    report = asyncio.run(run(apply=args.apply, output=args.output))
    print(json.dumps({k: report[k] for k in ("applied", "cache_row_count", "result_row_count", "issue_rows_added")}, ensure_ascii=False))
    print(args.output)


if __name__ == "__main__":
    main()
