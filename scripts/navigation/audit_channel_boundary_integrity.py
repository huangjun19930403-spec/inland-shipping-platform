from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any
from datetime import UTC, datetime

from sqlalchemy import select
from shapely.geometry import LineString, mapping, shape

from app.core.database import AsyncSessionLocal
from app.models import (
    NavigationChannelCenterline,
    NavigationChannelWaterBodyMatch,
    NavigationRouteTrajectoryCache,
    NavigationWaterBody,
)
from app.models.address import NavigationChannel, NavigationChannelBoundary
from app.modules.navigation.production_pipeline.boundary_quality_audit import audit_boundary_integrity


DEFAULT_OUTPUT = Path("runtime/navigation-production/reports/channel_boundary_integrity_audit.json")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit whether channel boundaries can be trusted for route validation.")
    parser.add_argument("--channel-code", action="append", default=[], help="Limit audit to one or more channel codes.")
    parser.add_argument("--channel-name-like", default=None, help="Limit audit by channel name keyword.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--geojson-output", type=Path, default=None)
    parser.add_argument("--html-output", type=Path, default=None)
    parser.add_argument("--trajectory-limit", type=int, default=2000)
    parser.add_argument("--apply", action="store_true", help="Write audit summary back to current boundary source_trace_json and downgrade bad quality labels.")
    return parser.parse_args()


async def audit_channel_boundary_integrity(
    *,
    channel_codes: list[str] | None = None,
    channel_name_like: str | None = None,
    trajectory_limit: int = 2000,
) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        clauses = [NavigationChannel.is_enabled.is_(True)]
        if channel_codes:
            clauses.append(NavigationChannel.channel_code.in_(channel_codes))
        if channel_name_like:
            clauses.append(NavigationChannel.channel_name.like(f"%{channel_name_like}%"))
        channels = list(
            (
                await session.execute(
                    select(NavigationChannel).where(*clauses).order_by(NavigationChannel.display_priority.desc(), NavigationChannel.id)
                )
            ).scalars()
        )
        channel_ids = [int(channel.id) for channel in channels]
        boundaries = list(
            (
                await session.execute(
                    select(NavigationChannelBoundary)
                    .where(
                        NavigationChannelBoundary.channel_id.in_(channel_ids),
                        NavigationChannelBoundary.is_current.is_(True),
                    )
                    .order_by(NavigationChannelBoundary.channel_id, NavigationChannelBoundary.id.desc())
                )
            ).scalars()
        )
        centerlines = list(
            (
                await session.execute(
                    select(NavigationChannelCenterline).where(
                        NavigationChannelCenterline.channel_id.in_(channel_ids),
                        NavigationChannelCenterline.is_current.is_(True),
                    )
                )
            ).scalars()
        )
        matches = list(
            (
                await session.execute(
                    select(NavigationChannelWaterBodyMatch, NavigationWaterBody)
                    .join(NavigationWaterBody, NavigationWaterBody.id == NavigationChannelWaterBodyMatch.water_body_id)
                    .where(
                        NavigationChannelWaterBodyMatch.channel_id.in_(channel_ids),
                        NavigationChannelWaterBodyMatch.is_current.is_(True),
                    )
                    .order_by(NavigationChannelWaterBodyMatch.channel_id, NavigationChannelWaterBodyMatch.score.desc())
                )
            ).all()
        )
        trajectories = list(
            (
                await session.execute(
                    select(NavigationRouteTrajectoryCache)
                    .where(NavigationRouteTrajectoryCache.geometry_json.is_not(None))
                    .order_by(NavigationRouteTrajectoryCache.id.desc())
                    .limit(max(0, trajectory_limit))
                )
            ).scalars()
        )

    boundary_by_channel_id = {int(row.channel_id): row for row in boundaries}
    centerlines_by_channel_id: dict[int, list[NavigationChannelCenterline]] = {}
    for row in centerlines:
        centerlines_by_channel_id.setdefault(int(row.channel_id), []).append(row)
    matches_by_channel_id: dict[int, list[tuple[NavigationChannelWaterBodyMatch, NavigationWaterBody]]] = {}
    for match, body in matches:
        matches_by_channel_id.setdefault(int(match.channel_id), []).append((match, body))
    trajectories_by_channel_id = _trajectory_rows_by_channel(trajectories, set(channel_ids))

    records: list[dict[str, Any]] = []
    for channel in channels:
        boundary = boundary_by_channel_id.get(int(channel.id))
        channel_centerlines = centerlines_by_channel_id.get(int(channel.id), [])
        boundary_payload = _boundary_payload(boundary)
        audit = audit_boundary_integrity(
            channel=_channel_payload(channel),
            boundary=boundary_payload,
            centerline_geometries=[row.geometry_json for row in channel_centerlines if row.geometry_json],
            require_centerline=True,
        )
        trajectory_coverage = _trajectory_coverage(boundary_payload, trajectories_by_channel_id.get(int(channel.id), []))
        trajectory_issue_codes = [
            "TRAJECTORY_NOT_ENCLOSED_BY_BOUNDARY"
            if item["coverage_ratio"] < 0.98
            else None
            for item in trajectory_coverage
        ]
        issue_codes = sorted(set([*audit.get("issue_codes", []), *[code for code in trajectory_issue_codes if code]]))
        record = {
            "channel_id": int(channel.id),
            "channel_code": channel.channel_code,
            "channel_name": channel.channel_name,
            "planning_level_code": channel.planning_level_code,
            "technical_grade_current_code": channel.technical_grade_current_code,
            "technical_grade_planned_code": channel.technical_grade_planned_code,
            "boundary_id": int(boundary.id) if boundary else None,
            "boundary_quality_code": boundary.boundary_quality_code if boundary else "MISSING",
            "coverage_policy_code": boundary.coverage_policy_code if boundary else None,
            "audit_trust_code": "FAILED" if "TRAJECTORY_NOT_ENCLOSED_BY_BOUNDARY" in issue_codes else audit.get("trust_code"),
            "issue_codes": issue_codes,
            "blocking_issue_codes": audit.get("blocking_issue_codes", []),
            "component_count": audit.get("component_count"),
            "largest_component_ratio": audit.get("largest_component_ratio"),
            "component_gap_stats": audit.get("component_gap_stats"),
            "water_system": _water_system_with_matches(audit.get("water_system") or {}, matches_by_channel_id.get(int(channel.id), [])),
            "vessel_limit_profile": audit.get("vessel_limit_profile"),
            "centerline_count": len(channel_centerlines),
            "centerline_coverage": audit.get("centerline_coverage", []),
            "trajectory_checked_count": len(trajectory_coverage),
            "trajectory_coverage": trajectory_coverage,
        }
        records.append(record)

    return {
        "summary": _summary(records),
        "records": records,
    }


async def apply_boundary_integrity_audit(report: dict[str, Any]) -> int:
    applied_count = 0
    now = datetime.now(UTC).isoformat(timespec="seconds")
    async with AsyncSessionLocal() as session:
        for record in report.get("records") or []:
            boundary_id = record.get("boundary_id")
            if not boundary_id:
                continue
            boundary = await session.get(NavigationChannelBoundary, int(boundary_id))
            if boundary is None:
                continue
            source_trace = dict(boundary.source_trace_json or {})
            source_trace["boundary_integrity_audit"] = {
                "trust_code": record.get("audit_trust_code"),
                "issue_codes": record.get("issue_codes") or [],
                "blocking_issue_codes": record.get("blocking_issue_codes") or [],
                "component_count": record.get("component_count"),
                "largest_component_ratio": record.get("largest_component_ratio"),
                "component_gap_stats": record.get("component_gap_stats"),
                "water_system": record.get("water_system"),
                "vessel_limit_profile": record.get("vessel_limit_profile"),
                "centerline_coverage": record.get("centerline_coverage") or [],
                "trajectory_coverage": record.get("trajectory_coverage") or [],
                "verification_rule": "runtime audit: boundary must enclose source waterway components, published centerlines and cached trajectories before HIGH confidence",
                "audited_at": now,
            }
            boundary.source_trace_json = source_trace
            if record.get("audit_trust_code") in {"FAILED", "NEEDS_REVIEW"} and boundary.geometry_status_code == "AVAILABLE":
                boundary.boundary_quality_code = "REVIEW"
                boundary.repair_status_code = "REVIEW_REQUIRED"
            applied_count += 1
        await session.commit()
    report["summary"]["applied_boundary_count"] = applied_count
    return applied_count


def _channel_payload(channel: NavigationChannel) -> dict[str, Any]:
    return {
        "channel_code": channel.channel_code,
        "channel_name": channel.channel_name,
        "planning_level_code": channel.planning_level_code,
        "technical_grade_current_code": channel.technical_grade_current_code,
        "technical_grade_planned_code": channel.technical_grade_planned_code,
    }


def _boundary_payload(boundary: NavigationChannelBoundary | None) -> dict[str, Any] | None:
    if boundary is None:
        return None
    return {
        "geometry_json": boundary.geometry_json,
        "geometry_status_code": boundary.geometry_status_code,
        "boundary_quality_code": boundary.boundary_quality_code,
        "coverage_policy_code": boundary.coverage_policy_code,
        "source_trace_json": boundary.source_trace_json or {},
    }


def _water_system_with_matches(
    water_system: dict[str, Any],
    matches: list[tuple[NavigationChannelWaterBodyMatch, NavigationWaterBody]],
) -> dict[str, Any]:
    levels = [
        level
        for _match, body in matches
        for level in (body.water_level_min, body.water_level_max)
        if level is not None
    ]
    type_counts: dict[str, int] = {}
    for _match, body in matches:
        water_type = str(body.water_type_code or "UNKNOWN")
        type_counts[water_type] = type_counts.get(water_type, 0) + 1
    return {
        **water_system,
        "matched_water_body_count": len(matches),
        "matched_water_level_min": min(levels) if levels else None,
        "matched_water_level_max": max(levels) if levels else None,
        "matched_water_type_counts": dict(sorted(type_counts.items())),
        "matched_water_bodies": [
            {
                "match_id": int(match.id),
                "water_body_id": int(body.id),
                "water_body_name": body.water_body_name,
                "water_level_min": body.water_level_min,
                "water_level_max": body.water_level_max,
                "water_type_code": body.water_type_code,
                "score": match.score,
                "confidence_code": match.confidence_code,
            }
            for match, body in matches[:20]
        ],
    }


def _trajectory_rows_by_channel(
    rows: list[NavigationRouteTrajectoryCache],
    channel_ids: set[int],
) -> dict[int, list[NavigationRouteTrajectoryCache]]:
    output: dict[int, list[NavigationRouteTrajectoryCache]] = {}
    for row in rows:
        ids = row.channel_ids if isinstance(row.channel_ids, list) else []
        for channel_id in ids:
            try:
                value = int(channel_id)
            except (TypeError, ValueError):
                continue
            if value in channel_ids:
                output.setdefault(value, []).append(row)
    return output


def _trajectory_coverage(
    boundary: dict[str, Any] | None,
    rows: list[NavigationRouteTrajectoryCache],
) -> list[dict[str, Any]]:
    if not boundary or not boundary.get("geometry_json"):
        return []
    try:
        boundary_geometry = shape(boundary["geometry_json"])
    except Exception:
        return []
    output: list[dict[str, Any]] = []
    for row in rows[:20]:
        try:
            line = shape(row.geometry_json)
        except Exception:
            continue
        if not isinstance(line, LineString) or line.is_empty or line.length <= 0:
            continue
        try:
            ratio = line.intersection(boundary_geometry.buffer(0.00003)).length / line.length
        except Exception:
            ratio = 0.0
        output.append(
            {
                "trajectory_cache_id": int(row.id),
                "provider_code": row.provider_code,
                "source_type_code": row.source_type_code,
                "quality_code": row.quality_code,
                "coverage_ratio": round(max(0.0, min(1.0, ratio)), 6),
            }
        )
    return output


def _summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "channel_count": len(records),
        "boundary_missing_count": sum(1 for row in records if row["boundary_id"] is None),
        "ready_count": sum(1 for row in records if row["audit_trust_code"] in {"READY", "READY_WITH_WARNING"}),
        "needs_review_count": sum(1 for row in records if row["audit_trust_code"] == "NEEDS_REVIEW"),
        "failed_count": sum(1 for row in records if row["audit_trust_code"] == "FAILED"),
        "fragmented_source_count": sum(1 for row in records if "SOURCE_GEOMETRY_FRAGMENTED" in row["issue_codes"]),
        "centerline_missing_count": sum(1 for row in records if "CENTERLINE_MISSING_BOUNDARY_NOT_VERIFIED" in row["issue_codes"]),
        "technical_grade_unknown_count": sum(1 for row in records if "NAVIGATION_TECHNICAL_GRADE_UNKNOWN" in row["issue_codes"]),
        "trajectory_not_enclosed_count": sum(1 for row in records if "TRAJECTORY_NOT_ENCLOSED_BY_BOUNDARY" in row["issue_codes"]),
    }


async def _geojson_feature_collection(report: dict[str, Any]) -> dict[str, Any]:
    boundary_ids = [int(row["boundary_id"]) for row in report.get("records") or [] if row.get("boundary_id")]
    geometry_by_boundary_id: dict[int, dict[str, Any]] = {}
    if boundary_ids:
        async with AsyncSessionLocal() as session:
            boundaries = list(
                (
                    await session.execute(
                        select(NavigationChannelBoundary).where(NavigationChannelBoundary.id.in_(boundary_ids))
                    )
                ).scalars()
            )
            geometry_by_boundary_id = {int(row.id): row.geometry_json for row in boundaries if row.geometry_json}
    features: list[dict[str, Any]] = []
    for record in report.get("records") or []:
        if record.get("audit_trust_code") in {"READY", "READY_WITH_WARNING"}:
            continue
        boundary_id = record.get("boundary_id")
        boundary = geometry_by_boundary_id.get(int(boundary_id)) if boundary_id else None
        if not boundary:
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {key: value for key, value in record.items() if not key.startswith("_")},
                "geometry": boundary,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def _debug_html(report: dict[str, Any], geojson_path: Path | None = None) -> str:
    records = [row for row in report.get("records") or [] if row.get("audit_trust_code") not in {"READY", "READY_WITH_WARNING"}]
    rows_html = "\n".join(
        "<tr>"
        f"<td>{_html_escape(row.get('channel_code'))}</td>"
        f"<td>{_html_escape(row.get('channel_name'))}</td>"
        f"<td>{_html_escape(row.get('audit_trust_code'))}</td>"
        f"<td>{_html_escape(row.get('component_count'))}</td>"
        f"<td>{_html_escape((row.get('component_gap_stats') or {}).get('max_gap_m'))}</td>"
        f"<td>{_html_escape(row.get('centerline_count'))}</td>"
        f"<td>{_html_escape('、'.join(row.get('issue_codes') or []))}</td>"
        "</tr>"
        for row in records[:500]
    )
    geojson_note = f"<p>GeoJSON: {_html_escape(str(geojson_path))}</p>" if geojson_path else ""
    summary = report.get("summary") or {}
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>航道边界完整性审计</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #111827; }}
    h1 {{ font-size: 22px; margin: 0 0 12px; }}
    .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; margin: 16px 0; }}
    .metric {{ border: 1px solid #d1d5db; padding: 10px; border-radius: 6px; }}
    .metric b {{ display: block; font-size: 20px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th, td {{ border: 1px solid #d1d5db; padding: 6px 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f3f4f6; position: sticky; top: 0; }}
    td:last-child {{ max-width: 560px; word-break: break-word; }}
  </style>
</head>
<body>
  <h1>航道边界完整性审计</h1>
  <p>该报告用于识别不能作为高置信路径验收依据的航道边界。边界必须真实包围水道、中心线和轨迹；缺等级、缺中心线、碎片化或未独立验证的边界不能直接通过。</p>
  {geojson_note}
  <div class="summary">
    <div class="metric"><span>航道数</span><b>{_html_escape(summary.get('channel_count'))}</b></div>
    <div class="metric"><span>需复核</span><b>{_html_escape(summary.get('needs_review_count'))}</b></div>
    <div class="metric"><span>失败</span><b>{_html_escape(summary.get('failed_count'))}</b></div>
    <div class="metric"><span>碎片化</span><b>{_html_escape(summary.get('fragmented_source_count'))}</b></div>
    <div class="metric"><span>缺中心线</span><b>{_html_escape(summary.get('centerline_missing_count'))}</b></div>
    <div class="metric"><span>缺技术等级</span><b>{_html_escape(summary.get('technical_grade_unknown_count'))}</b></div>
  </div>
  <table>
    <thead><tr><th>编码</th><th>名称</th><th>可信状态</th><th>碎片数</th><th>最大间隔(m)</th><th>中心线数</th><th>问题</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
</body>
</html>"""


def _html_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


async def _main() -> None:
    args = _parse_args()
    report = await audit_channel_boundary_integrity(
        channel_codes=args.channel_code,
        channel_name_like=args.channel_name_like,
        trajectory_limit=args.trajectory_limit,
    )
    if args.apply:
        await apply_boundary_integrity_audit(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.geojson_output:
        args.geojson_output.parent.mkdir(parents=True, exist_ok=True)
        geojson = await _geojson_feature_collection(report)
        args.geojson_output.write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")
    if args.html_output:
        args.html_output.parent.mkdir(parents=True, exist_ok=True)
        args.html_output.write_text(_debug_html(report, args.geojson_output), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
