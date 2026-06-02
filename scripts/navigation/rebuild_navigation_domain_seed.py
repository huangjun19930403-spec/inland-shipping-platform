"""Delete and rebuild local navigation-domain production seed data.

This entrypoint is intentionally scoped to navigation map production assets.
It does not touch users, roles, system_config, AI provider settings, map keys,
Elasticsearch, HiFleet, or any .env file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

from sqlalchemy import delete, func, select

from app.core.database import AsyncSessionLocal, engine
from app.models import (
    NavigationAnnotationTask,
    NavigationCenterlineControlPoint,
    NavigationCenterlinePointSet,
    NavigationCenterlineSegment,
    NavigationChannelCenterline,
    NavigationChannelWaterAreaMatch,
    NavigationChannelWaterBodyMatch,
    NavigationGeometryDraft,
    NavigationGraphEdge,
    NavigationGraphEdgeConstraint,
    NavigationGraphNode,
    NavigationGraphVersion,
    NavigationRouteQualityIssue,
    NavigationRouteRequest,
    NavigationRouteResult,
    NavigationWaterArea,
    NavigationWaterBody,
    NavigationWaterBodyFeatureLink,
)
from app.models.address import (
    NavigationChannel,
    NavigationChannelBoundary,
    NavigationChannelSegment,
    NavigationChannelSourceAudit,
)
from app.modules.navigation.schemas import NavigationCenterlineSegmentGenerateRequest, NavigationCenterlineSegmentPublishRequest
from app.modules.navigation.services.centerline_segments import NavigationCenterlineSegmentService
from app.modules.navigation.services.graph_build_service import build_graph_from_centerlines
from scripts.navigation.audit_water_area_assets import audit_water_area_assets
from scripts.navigation.backfill_channel_water_body_matches import backfill_channel_water_body_matches
from scripts.navigation.build_channel_water_area_matches import build_channel_water_area_matches
from scripts.navigation.build_water_bodies import build_navigation_water_bodies
from scripts.navigation.refresh_postgis_geometry_columns import refresh_postgis_geometry_columns
from scripts.seeds.loaders.navigation_channels import seed_navigation_channels
from scripts.seeds.loaders.navigation_constraints import seed_navigation_constraints
from scripts.seeds.loaders.navigation_water_areas import seed_navigation_water_areas


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REVIER_ZIP = Path("/Users/hj/Documents/河道数据/revier.zip")
DEFAULT_OUTPUT = PROJECT_ROOT / "data_audit" / "navigation_domain_seed_rebuild_audit.json"
GRAPH_SCOPE_CODE = "REAL-JS-YRD"
T = TypeVar("T")


DELETE_ORDER = (
    NavigationRouteQualityIssue,
    NavigationRouteResult,
    NavigationRouteRequest,
    NavigationAnnotationTask,
    NavigationGraphEdgeConstraint,
    NavigationGraphEdge,
    NavigationGraphNode,
    NavigationGraphVersion,
    NavigationCenterlineControlPoint,
    NavigationCenterlinePointSet,
    NavigationCenterlineSegment,
    NavigationChannelCenterline,
    NavigationGeometryDraft,
    NavigationChannelWaterBodyMatch,
    NavigationWaterBodyFeatureLink,
    NavigationWaterBody,
    NavigationChannelWaterAreaMatch,
    NavigationWaterArea,
    NavigationChannelSourceAudit,
    NavigationChannelSegment,
    NavigationChannelBoundary,
    NavigationChannel,
)


COUNT_MODELS = {
    "navigation_channel": NavigationChannel,
    "navigation_channel_boundary": NavigationChannelBoundary,
    "navigation_channel_segment": NavigationChannelSegment,
    "navigation_channel_source_audit": NavigationChannelSourceAudit,
    "navigation_water_area": NavigationWaterArea,
    "navigation_water_body": NavigationWaterBody,
    "navigation_water_body_feature_link": NavigationWaterBodyFeatureLink,
    "navigation_channel_water_area_match": NavigationChannelWaterAreaMatch,
    "navigation_channel_water_body_match": NavigationChannelWaterBodyMatch,
    "navigation_channel_centerline": NavigationChannelCenterline,
    "navigation_centerline_segment": NavigationCenterlineSegment,
    "navigation_graph_version": NavigationGraphVersion,
    "navigation_graph_edge": NavigationGraphEdge,
}


async def _delete_navigation_domain() -> dict[str, int]:
    deleted: dict[str, int] = {}
    async with AsyncSessionLocal() as session:
        for model in DELETE_ORDER:
            result = await session.execute(delete(model))
            deleted[model.__tablename__] = int(result.rowcount or 0)
        await session.commit()
    return deleted


async def _step(name: str, callback: Callable[[], Awaitable[T]]) -> T:
    started = time.perf_counter()
    print(f"[navigation-seed] start {name}", flush=True)
    result = await callback()
    print(f"[navigation-seed] done {name} in {time.perf_counter() - started:.2f}s", flush=True)
    return result


async def _count_tables() -> dict[str, int]:
    async with AsyncSessionLocal() as session:
        output: dict[str, int] = {}
        for table_name, model in COUNT_MODELS.items():
            output[table_name] = int(await session.scalar(select(func.count()).select_from(model)) or 0)
        return output


def _sibling_report_path(output_path: Path, default_name: str) -> Path:
    if output_path.name == DEFAULT_OUTPUT.name:
        return PROJECT_ROOT / "data_audit" / default_name
    marker = ".mysql" if "mysql" in output_path.stem.lower() else f".{output_path.stem}"
    default_path = Path(default_name)
    return PROJECT_ROOT / "data_audit" / f"{default_path.stem}{marker}{default_path.suffix}"


def _database_report() -> dict[str, Any]:
    return {
        "backend": engine.url.get_backend_name(),
        "driver": engine.url.get_driver_name(),
        "database": engine.url.database,
    }


async def _status_counts() -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        boundary_rows = (
            await session.execute(
                select(
                    NavigationChannelBoundary.is_current,
                    NavigationChannelBoundary.geometry_status_code,
                    NavigationChannelBoundary.coverage_policy_code,
                    func.count(),
                ).group_by(
                    NavigationChannelBoundary.is_current,
                    NavigationChannelBoundary.geometry_status_code,
                    NavigationChannelBoundary.coverage_policy_code,
                )
            )
        ).all()
        segment_rows = (
            await session.execute(
                select(NavigationCenterlineSegment.segment_status_code, NavigationCenterlineSegment.quality_code, func.count())
                .group_by(NavigationCenterlineSegment.segment_status_code, NavigationCenterlineSegment.quality_code)
                .order_by(NavigationCenterlineSegment.segment_status_code, NavigationCenterlineSegment.quality_code)
            )
        ).all()
        graph_rows = (
            await session.execute(
                select(NavigationGraphVersion.scope_code, NavigationGraphVersion.status_code, NavigationGraphVersion.is_active, func.count())
                .group_by(NavigationGraphVersion.scope_code, NavigationGraphVersion.status_code, NavigationGraphVersion.is_active)
                .order_by(NavigationGraphVersion.scope_code, NavigationGraphVersion.status_code)
            )
        ).all()
    return {
        "boundaries": [
            {
                "is_current": bool(is_current),
                "geometry_status_code": geometry_status_code,
                "coverage_policy_code": coverage_policy_code,
                "count": int(count),
            }
            for is_current, geometry_status_code, coverage_policy_code, count in boundary_rows
        ],
        "centerline_segments": [
            {"segment_status_code": status_code, "quality_code": quality_code, "count": int(count)}
            for status_code, quality_code, count in segment_rows
        ],
        "graph_versions": [
            {"scope_code": scope_code, "status_code": status_code, "is_active": bool(is_active), "count": int(count)}
            for scope_code, status_code, is_active, count in graph_rows
        ],
    }


async def _generate_centerline_segments(channel_codes: set[str] | None) -> dict[str, Any]:
    generated: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    async with AsyncSessionLocal() as session:
        query = select(NavigationChannel).where(NavigationChannel.is_enabled.is_(True)).order_by(NavigationChannel.sort_order, NavigationChannel.id)
        if channel_codes:
            query = query.where(NavigationChannel.channel_code.in_(sorted(channel_codes)))
        channels = list((await session.execute(query)).scalars())
        service = NavigationCenterlineSegmentService(session)
        for channel in channels:
            response = await service.generate_segments(
                int(channel.id),
                NavigationCenterlineSegmentGenerateRequest(
                    force=True,
                    segment_length_km=5.0,
                    source_mode="CHANNEL_GUIDE_WITH_BOUNDARY_CLIP",
                ),
            )
            item = {
                "channel_id": int(channel.id),
                "channel_code": channel.channel_code,
                "status_code": response.status_code,
                "segment_count": response.segment_count,
                "need_repair_count": response.need_repair_count,
                "confirmed_count": response.confirmed_count,
                "blocker_codes": response.blocker_codes,
                "message": response.message,
            }
            if response.status_code == "CREATED":
                generated.append(item)
            else:
                blocked.append(item)
    return {
        "generated_channel_count": len(generated),
        "blocked_channel_count": len(blocked),
        "generated": generated,
        "blocked": blocked,
    }


async def _publish_seed_centerlines(channel_codes: set[str] | None) -> dict[str, Any]:
    published: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    async with AsyncSessionLocal() as session:
        query = select(NavigationChannel).where(NavigationChannel.is_enabled.is_(True)).order_by(NavigationChannel.sort_order, NavigationChannel.id)
        if channel_codes:
            query = query.where(NavigationChannel.channel_code.in_(sorted(channel_codes)))
        channels = list((await session.execute(query)).scalars())
        service = NavigationCenterlineSegmentService(session)
        for channel in channels:
            channel_id = int(channel.id)
            rows = await service._active_segments(channel_id, limit=10000)
            if not rows:
                blocked.append(
                    {
                        "channel_id": channel_id,
                        "channel_code": channel.channel_code,
                        "status_code": "BLOCKED",
                        "blocker_codes": ["NO_CENTERLINE_SEGMENT"],
                        "message": "No generated centerline segments available for seed publishing.",
                    }
                )
                continue
            validation_failures: list[dict[str, Any]] = []
            confirmed_count = 0
            for row in rows:
                if row.segment_status_code in {"CONFIRMED", "PUBLISHED"}:
                    confirmed_count += 1
                    continue
                issue_summary = row.issue_summary_json if isinstance(row.issue_summary_json, dict) else {}
                error_count = int(issue_summary.get("error_count") or 0)
                if error_count:
                    validation_failures.append(
                        {
                            "segment_id": int(row.id),
                            "segment_no": row.segment_no,
                            "error_code": "CENTERLINE_SEGMENT_VALIDATION_ERROR",
                            "message": "Generated seed segment has blocking validation errors.",
                            "detail": {
                                "issue_summary": issue_summary,
                                "validation_summary": row.validation_summary_json,
                            },
                        }
                    )
                    continue
                row.segment_status_code = "CONFIRMED"
                row.quality_code = "READY_WITH_WARNING" if int(issue_summary.get("warning_count") or 0) else "READY"
                trace = dict(row.source_trace_json or {})
                trace["confirmed_at"] = datetime.now(UTC).isoformat()
                trace["confirmed_by"] = "navigation_domain_seed_rebuild"
                row.source_trace_json = trace
                confirmed_count += 1
            if validation_failures:
                await session.rollback()
                blocked.append(
                    {
                        "channel_id": channel_id,
                        "channel_code": channel.channel_code,
                        "status_code": "BLOCKED",
                        "segment_count": len(rows),
                        "confirmed_count": confirmed_count,
                        "unconfirmed_count": len(rows) - confirmed_count,
                        "blocker_codes": ["CENTERLINE_SEGMENT_CONFIRM_FAILED"],
                        "confirm_failures": validation_failures[:20],
                    }
                )
                continue
            await session.flush()
            rows = await service._active_segments(channel_id, limit=10000)
            unconfirmed = [row for row in rows if row.segment_status_code != "CONFIRMED"]
            if unconfirmed:
                blocked.append(
                    {
                        "channel_id": channel_id,
                        "channel_code": channel.channel_code,
                        "status_code": "BLOCKED",
                        "segment_count": len(rows),
                        "confirmed_count": confirmed_count,
                        "unconfirmed_count": len(unconfirmed),
                        "blocker_codes": ["CENTERLINE_SEGMENT_CONFIRM_FAILED"],
                        "confirm_failures": [
                            {
                                "segment_id": int(row.id),
                                "segment_no": row.segment_no,
                                "error_code": "CENTERLINE_SEGMENT_NOT_CONFIRMED",
                                "message": f"Segment status is {row.segment_status_code}.",
                            }
                            for row in unconfirmed[:20]
                        ],
                    }
                )
                continue
            response = await service.publish_segments(
                channel_id,
                NavigationCenterlineSegmentPublishRequest(publish_name=f"{channel.channel_name}生产 seed 中心线"),
            )
            if response.status_code == "PUBLISHED":
                published.append(
                    {
                        "channel_id": channel_id,
                        "channel_code": channel.channel_code,
                        "centerline_id": response.centerline_id,
                        "segment_count": response.segment_count,
                        "quality_code": response.quality_code,
                    }
                )
            else:
                blocked.append(
                    {
                        "channel_id": channel_id,
                        "channel_code": channel.channel_code,
                        "status_code": response.status_code,
                        "segment_count": response.segment_count,
                        "blocker_codes": response.blocker_codes,
                        "message": response.message,
                    }
                )
    return {
        "published_channel_count": len(published),
        "blocked_channel_count": len(blocked),
        "published": published,
        "blocked": blocked,
    }


async def _build_graph_if_possible(channel_codes: set[str] | None) -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        stmt = select(func.count()).select_from(NavigationChannelCenterline).where(
            NavigationChannelCenterline.is_current.is_(True),
            NavigationChannelCenterline.review_status_code == "PUBLISHED",
        )
        if channel_codes:
            stmt = stmt.join(NavigationChannel, NavigationChannel.id == NavigationChannelCenterline.channel_id).where(
                NavigationChannel.channel_code.in_(sorted(channel_codes))
            )
        published_count = int(await session.scalar(stmt) or 0)
        if published_count <= 0:
            return {
                "status": "SKIPPED",
                "reason": "no published current centerlines from verifiable line sources; graph is not fabricated from boundary-derived candidate segments",
                "published_centerline_count": 0,
            }
        summary = await build_graph_from_centerlines(
            session=session,
            version_code=f"SEED-NAV-GRAPH-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            version_name="导航生产 Seed Graph",
            scope_code=GRAPH_SCOPE_CODE,
            channel_codes=sorted(channel_codes) if channel_codes else None,
            activate=True,
        )
        return summary.as_dict()


async def rebuild_navigation_domain_seed(
    *,
    revier_zip: Path = DEFAULT_REVIER_ZIP,
    output_path: Path = DEFAULT_OUTPUT,
    channel_codes: set[str] | None = None,
    skip_centerline_segments: bool = False,
) -> dict[str, Any]:
    if not revier_zip.exists():
        raise FileNotFoundError(f"revier.zip not found: {revier_zip}")

    started_at = datetime.now(UTC)
    before_counts = await _step("count_before", _count_tables)
    deleted_counts = await _step("delete_navigation_domain", _delete_navigation_domain)

    channel_seed = await _step(
        "seed_navigation_channels",
        lambda: seed_navigation_channels(drop_legacy=True, derive_missing_guides=True),
    )
    water_area_seed = await _step("seed_navigation_water_areas", seed_navigation_water_areas)
    water_body_report = await _step(
        "build_navigation_water_bodies",
        lambda: build_navigation_water_bodies(
            output_path=_sibling_report_path(output_path, "navigation_water_body_build_report.json")
        ),
    )

    async def _match_water_areas() -> Any:
        async with AsyncSessionLocal() as session:
            report = await build_channel_water_area_matches(
                session=session,
                source_code="RIVER_SHAPEFILE_2026",
                write_candidate_boundaries=True,
                channel_codes=sorted(channel_codes) if channel_codes else None,
                output_path=_sibling_report_path(output_path, "navigation_channel_water_area_match_report.json"),
            )
            await session.commit()
            return report

    water_area_match_report = await _step("build_channel_water_area_matches", _match_water_areas)

    water_body_match_report = await _step(
        "backfill_channel_water_body_matches",
        lambda: backfill_channel_water_body_matches(
            output_path=_sibling_report_path(output_path, "navigation_channel_water_body_match_backfill_report.json")
        ),
    )
    constraints_report = await _step("seed_navigation_constraints", seed_navigation_constraints)
    centerline_segment_report = await _step(
        "generate_centerline_segments",
        lambda: (
            _async_value({"skipped": True, "reason": "skip_centerline_segments requested"})
            if skip_centerline_segments
            else _generate_centerline_segments(channel_codes)
        ),
    )
    centerline_publish_report = await _step(
        "publish_seed_centerlines",
        lambda: (
            _async_value({"skipped": True, "reason": "skip_centerline_segments requested"})
            if skip_centerline_segments
            else _publish_seed_centerlines(channel_codes)
        ),
    )
    graph_report = await _step("build_graph_if_possible", lambda: _build_graph_if_possible(channel_codes))
    postgis_report = await _step("refresh_postgis_geometry_columns", refresh_postgis_geometry_columns)
    water_area_audit = await _step(
        "audit_water_area_assets",
        lambda: audit_water_area_assets(
            revier_zip=revier_zip,
            output_path=_sibling_report_path(output_path, "navigation_water_area_asset_audit.json"),
        ),
    )

    after_counts = await _step("count_after", _count_tables)
    status_counts = await _step("status_counts", _status_counts)
    source_limitations = _source_limitations(after_counts, centerline_segment_report, graph_report)
    finished_at = datetime.now(UTC)
    report = {
        "report_version": "NAVIGATION_DOMAIN_SEED_REBUILD_V1",
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 2),
        "scope": {
            "reset_scope": "navigation_domain_only",
            "sensitive_config_preserved": True,
            "system_config_preserved": True,
            "revier_zip": str(revier_zip),
            "channel_codes": sorted(channel_codes) if channel_codes else "ALL",
            "database": _database_report(),
        },
        "public_sources": [
            {"name": "Geofabrik China OSM extract", "url": "https://download.geofabrik.de/asia/china.html", "usage": "candidate waterway/centerline source when provided locally"},
            {"name": "OSM waterway key", "url": "https://wiki.openstreetmap.org/wiki/Key:waterway", "usage": "tag semantics for OSM waterway ingestion"},
            {"name": "HydroRIVERS", "url": "https://www.hydrosheds.org/products/hydrorivers", "usage": "public hydrography cross-check source"},
            {"name": "Natural Earth rivers/lake centerlines", "url": "https://www.naturalearthdata.com/downloads/10m-physical-vectors/10m-rivers-lake-centerlines/", "usage": "low precision sanity check only"},
        ],
        "counts_before": before_counts,
        "deleted_counts": deleted_counts,
        "seed_steps": {
            "navigation_channels": channel_seed,
            "navigation_water_areas": water_area_seed,
            "navigation_water_bodies": water_body_report,
            "navigation_channel_water_area_matches": water_area_match_report.as_dict(),
            "navigation_channel_water_body_matches": water_body_match_report,
            "navigation_constraints": constraints_report,
            "centerline_segments": centerline_segment_report,
            "centerline_publish": centerline_publish_report,
            "graph": graph_report,
            "postgis_geometry_columns": postgis_report,
        },
        "counts_after": after_counts,
        "status_counts": status_counts,
        "source_limitations": source_limitations,
        "water_area_audit_summary": {
            "issues": water_area_audit.get("issues", []),
            "summary": water_area_audit.get("summary", {}),
            "report_path": str(_sibling_report_path(output_path, "navigation_water_area_asset_audit.json")),
        },
        "mysql_validation": {
            "status": "CURRENT_RUN" if engine.url.get_backend_name() == "mysql" else "SKIPPED",
            "reason": (
                "this rebuild is running directly against the configured MySQL database"
                if engine.url.get_backend_name() == "mysql"
                else "runtime navigation application is bound to PostgreSQL; run this script with MYSQL DATABASE_URL to validate MySQL"
            ),
            "database": _database_report(),
        },
        "blockers": _derive_blockers(after_counts, centerline_segment_report, water_area_audit, source_limitations, graph_report),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


async def _async_value(value: T) -> T:
    return value


def _source_limitations(
    after_counts: dict[str, int],
    centerline_segment_report: dict[str, Any],
    graph_report: dict[str, Any],
) -> list[dict[str, Any]]:
    limitations: list[dict[str, Any]] = []
    if after_counts.get("navigation_channel_centerline", 0) <= 0:
        limitations.append(
            {
                "asset": "navigation_channel_centerline",
                "status": "BLOCKED",
                "reason": "revier.zip and current curated channel seed contain polygon water-system assets and channel boundaries, but no verifiable line-source centerline geometry",
                "policy": "boundary-derived candidate segments are retained for operator repair and are not published as production centerlines",
            }
        )
    if graph_report.get("status") == "SKIPPED":
        limitations.append(
            {
                "asset": "navigation_graph",
                "status": "BLOCKED",
                "reason": graph_report.get("reason"),
                "policy": "active routing graph is built only from published current centerlines",
            }
        )
    if centerline_segment_report.get("blocked_channel_count"):
        limitations.append(
            {
                "asset": "navigation_centerline_segment",
                "status": "PARTIAL",
                "reason": "some channels have no current published boundary or usable guide candidate",
                "blocked_channel_count": centerline_segment_report.get("blocked_channel_count"),
            }
        )
    return limitations


def _derive_blockers(
    after_counts: dict[str, int],
    centerline_segment_report: dict[str, Any],
    water_area_audit: dict[str, Any],
    source_limitations: list[dict[str, Any]],
    graph_report: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if after_counts.get("navigation_channel", 0) <= 0:
        blockers.append("NAVIGATION_CHANNEL_SEED_EMPTY")
    if after_counts.get("navigation_water_area", 0) <= 0:
        blockers.append("NAVIGATION_WATER_AREA_SEED_EMPTY")
    if after_counts.get("navigation_channel_boundary", 0) <= 0:
        blockers.append("NAVIGATION_BOUNDARY_SEED_EMPTY")
    if after_counts.get("navigation_centerline_segment", 0) <= 0:
        blockers.append("CENTERLINE_SEGMENT_GENERATION_EMPTY")
    if after_counts.get("navigation_channel_centerline", 0) <= 0:
        blockers.append("PUBLISHED_CENTERLINE_SOURCE_MISSING")
    if centerline_segment_report.get("blocked_channel_count"):
        blockers.append("CENTERLINE_SEGMENT_CHANNEL_BLOCKERS_REMAIN")
    if water_area_audit.get("issues"):
        blockers.append("WATER_AREA_AUDIT_ISSUES_REMAIN")
    if graph_report.get("status") == "SKIPPED" or after_counts.get("navigation_graph_edge", 0) <= 0:
        blockers.append("GRAPH_REBUILD_WAITING_FOR_PUBLISHED_CENTERLINES")
    blockers.extend(f"SOURCE_LIMITATION_{item['asset'].upper()}" for item in source_limitations if item.get("status") == "BLOCKED")
    return blockers


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Delete and rebuild navigation-domain seed data only.")
    parser.add_argument("--revier-zip", type=Path, default=DEFAULT_REVIER_ZIP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--channel-code", action="append", default=[], help="Limit centerline segment generation to selected channels.")
    parser.add_argument("--skip-centerline-segments", action="store_true")
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    report = await rebuild_navigation_domain_seed(
        revier_zip=args.revier_zip,
        output_path=args.output,
        channel_codes=set(args.channel_code) if args.channel_code else None,
        skip_centerline_segments=args.skip_centerline_segments,
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "counts_after": report["counts_after"],
                "blockers": report["blockers"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(_main())
