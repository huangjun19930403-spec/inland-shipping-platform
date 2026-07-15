"""Inventory route endpoints and generate OD pair matrix reports.

This script is intentionally separated from route generation. It answers the
first production question: what can be used as route endpoints, and how large is
the real pair matrix before any sampling or repair workflow starts?
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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.address import NavigationConstraintPoint, TransportNode
from app.models.navigation import (
    NavigationCenterlineSegment,
    NavigationGraphNode,
    NavigationGraphVersion,
    NavigationRouteTrajectoryCache,
    NavigationWaterArea,
    NavigationWaterBody,
)


REPORT_PATH = Path("runtime/navigation-production/reports/route_endpoint_inventory_report.json")
PAIR_MATRIX_PATH = Path("runtime/navigation-production/reports/route_endpoint_pair_matrix.jsonl")
ACTIVE_CENTERLINE_SEGMENT_STATUSES = {"NEED_REPAIR", "CANDIDATE", "CONFIRMED", "PUBLISH_BLOCKED", "PUBLISHED"}


@dataclass(frozen=True)
class EndpointCandidate:
    endpoint_uid: str
    endpoint_type_code: str
    source_type_code: str
    ref_id: int
    code: str
    name: str
    category_code: str | None
    longitude: float
    latitude: float
    business_endpoint_flag: bool
    seed_endpoint_flag: bool
    graph_version_id: int | None = None
    channel_id: int | None = None
    quality_code: str | None = None
    status_code: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inventory route endpoint candidates and OD pair matrix size.")
    parser.add_argument("--scope", choices=("business", "seed", "business-and-seed", "all"), default="business-and-seed")
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    parser.add_argument("--write-pair-matrix", action="store_true")
    parser.add_argument("--pair-output", type=Path, default=PAIR_MATRIX_PATH)
    parser.add_argument("--pair-limit", type=int, default=None)
    parser.add_argument("--pair-offset", type=int, default=0)
    parser.add_argument("--min-distance-km", type=float, default=None)
    parser.add_argument("--max-distance-km", type=float, default=None)
    parser.add_argument("--include-water-body-centers", action="store_true")
    parser.add_argument("--include-water-area-centers", action="store_true")
    parser.add_argument("--water-center-limit", type=int, default=500)
    parser.add_argument("--sample-size", type=int, default=20)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    async with AsyncSessionLocal() as session:
        active_graph = await _active_graph_version(session)
        inventory_counts = await _inventory_counts(session, active_graph.id if active_graph else None)
        candidates = await _load_candidates(
            session,
            scope=args.scope,
            active_graph=active_graph,
            include_water_body_centers=bool(args.include_water_body_centers),
            include_water_area_centers=bool(args.include_water_area_centers),
            water_center_limit=max(0, int(args.water_center_limit or 0)),
        )
        pair_summary = _pair_summary(candidates)
        matrix_write_summary: dict[str, Any] | None = None
        if args.write_pair_matrix:
            matrix_write_summary = _write_pair_matrix(
                candidates,
                output=args.pair_output,
                offset=max(0, int(args.pair_offset or 0)),
                limit=args.pair_limit if args.pair_limit is None else max(0, int(args.pair_limit)),
                min_distance_km=args.min_distance_km,
                max_distance_km=args.max_distance_km,
            )
        report = {
            "report_version": "ROUTE_ENDPOINT_INVENTORY_V1",
            "generated_at": datetime.now(UTC).isoformat(),
            "args": {
                "scope": args.scope,
                "write_pair_matrix": bool(args.write_pair_matrix),
                "pair_limit": args.pair_limit,
                "pair_offset": args.pair_offset,
                "min_distance_km": args.min_distance_km,
                "max_distance_km": args.max_distance_km,
                "include_water_body_centers": bool(args.include_water_body_centers),
                "include_water_area_centers": bool(args.include_water_area_centers),
                "water_center_limit": int(args.water_center_limit or 0),
            },
            "active_graph_version": _graph_payload(active_graph),
            "inventory_counts": inventory_counts,
            "selected_endpoint_count": len(candidates),
            "selected_endpoint_counts_by_source": _count_by(candidates, "source_type_code"),
            "selected_endpoint_counts_by_category": _count_by(candidates, "category_code"),
            "pair_summary": pair_summary,
            "matrix_write_summary": matrix_write_summary,
            "sample_endpoints": [asdict(item) for item in candidates[: max(0, int(args.sample_size or 0))]],
            "excluded_by_default": _excluded_by_default(args, inventory_counts),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report_path={args.output}")
        if matrix_write_summary:
            print(f"pair_matrix_path={args.pair_output}")
        print(
            json.dumps(
                {
                    "selected_endpoint_count": len(candidates),
                    "selected_pair_count": pair_summary["total_pair_count"],
                    "counts_by_source": report["selected_endpoint_counts_by_source"],
                    "matrix_written_count": (matrix_write_summary or {}).get("written_count"),
                },
                ensure_ascii=False,
            )
        )


async def _active_graph_version(session: AsyncSession) -> NavigationGraphVersion | None:
    return (
        await session.execute(
            select(NavigationGraphVersion)
            .where(
                NavigationGraphVersion.is_active.is_(True),
                NavigationGraphVersion.status_code == "READY",
                NavigationGraphVersion.scope_code.not_like("MVP%"),
                NavigationGraphVersion.edge_count > 0,
            )
            .order_by(
                NavigationGraphVersion.channel_count.desc(),
                NavigationGraphVersion.edge_count.desc(),
                NavigationGraphVersion.node_count.desc(),
                NavigationGraphVersion.id.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()


async def _inventory_counts(session: AsyncSession, active_graph_id: int | None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "transport_nodes": await _count(
            session,
            select(func.count()).select_from(TransportNode).where(
                TransportNode.status == 1,
                TransportNode.longitude.is_not(None),
                TransportNode.latitude.is_not(None),
            ),
        ),
        "constraint_points": await _count(
            session,
            select(func.count()).select_from(NavigationConstraintPoint).where(NavigationConstraintPoint.status == 1),
        ),
        "centerline_segment_endpoints": 2
        * await _count(
            session,
            select(func.count()).select_from(NavigationCenterlineSegment).where(
                NavigationCenterlineSegment.segment_status_code.in_(ACTIVE_CENTERLINE_SEGMENT_STATUSES),
                NavigationCenterlineSegment.start_lng.is_not(None),
                NavigationCenterlineSegment.start_lat.is_not(None),
                NavigationCenterlineSegment.end_lng.is_not(None),
                NavigationCenterlineSegment.end_lat.is_not(None),
            ),
        ),
        "water_body_centers": await _count(
            session,
            select(func.count()).select_from(NavigationWaterBody).where(
                NavigationWaterBody.is_enabled.is_(True),
                NavigationWaterBody.center_lng.is_not(None),
                NavigationWaterBody.center_lat.is_not(None),
            ),
        ),
        "water_area_centers": await _count(
            session,
            select(func.count()).select_from(NavigationWaterArea).where(
                NavigationWaterArea.is_enabled.is_(True),
                NavigationWaterArea.center_lng.is_not(None),
                NavigationWaterArea.center_lat.is_not(None),
            ),
        ),
        "trajectory_cache_rows": await _count(
            session,
            select(func.count()).select_from(NavigationRouteTrajectoryCache),
        ),
    }
    data["active_graph_nodes"] = (
        await _count(
            session,
            select(func.count()).select_from(NavigationGraphNode).where(
                NavigationGraphNode.graph_version_id == active_graph_id,
                NavigationGraphNode.is_enabled.is_(True),
            ),
        )
        if active_graph_id
        else 0
    )
    business_count = int(data["transport_nodes"]) + int(data["constraint_points"])
    seed_count = int(data["active_graph_nodes"]) + int(data["centerline_segment_endpoints"])
    data["business_endpoint_pair_count"] = business_count * (business_count - 1) // 2
    data["business_and_seed_endpoint_pair_count"] = (business_count + seed_count) * (business_count + seed_count - 1) // 2
    return data


async def _count(session: AsyncSession, stmt) -> int:
    return int((await session.execute(stmt)).scalar_one() or 0)


async def _load_candidates(
    session: AsyncSession,
    *,
    scope: str,
    active_graph: NavigationGraphVersion | None,
    include_water_body_centers: bool,
    include_water_area_centers: bool,
    water_center_limit: int,
) -> list[EndpointCandidate]:
    candidates: list[EndpointCandidate] = []
    if scope in {"business", "business-and-seed", "all"}:
        candidates.extend(await _load_transport_nodes(session))
        candidates.extend(await _load_constraint_points(session))
    if scope in {"seed", "business-and-seed", "all"}:
        if active_graph is not None:
            candidates.extend(await _load_graph_nodes(session, active_graph.id))
        candidates.extend(await _load_centerline_segment_endpoints(session))
    if scope == "all" or include_water_body_centers:
        candidates.extend(await _load_water_body_centers(session, limit=water_center_limit))
    if scope == "all" or include_water_area_centers:
        candidates.extend(await _load_water_area_centers(session, limit=water_center_limit))
    return _dedupe_candidates(candidates)


async def _load_transport_nodes(session: AsyncSession) -> list[EndpointCandidate]:
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
        EndpointCandidate(
            endpoint_uid=f"TRANSPORT_NODE:{row.id}",
            endpoint_type_code="TRANSPORT_NODE",
            source_type_code="TRANSPORT_NODE",
            ref_id=int(row.id),
            code=row.code,
            name=row.name,
            category_code=row.node_type_code,
            longitude=float(row.longitude),
            latitude=float(row.latitude),
            business_endpoint_flag=True,
            seed_endpoint_flag=False,
            quality_code=None,
            status_code=str(row.status),
        )
        for row in rows
        if _valid_lng_lat(row.longitude, row.latitude)
    ]


async def _load_constraint_points(session: AsyncSession) -> list[EndpointCandidate]:
    rows = list(
        (
            await session.execute(
                select(NavigationConstraintPoint)
                .where(NavigationConstraintPoint.status == 1)
                .order_by(NavigationConstraintPoint.id)
            )
        ).scalars()
    )
    return [
        EndpointCandidate(
            endpoint_uid=f"CONSTRAINT_POINT:{row.id}",
            endpoint_type_code="CONSTRAINT_POINT",
            source_type_code="CONSTRAINT_POINT",
            ref_id=int(row.id),
            code=row.code,
            name=row.name,
            category_code=row.constraint_type_code,
            longitude=float(row.longitude),
            latitude=float(row.latitude),
            business_endpoint_flag=True,
            seed_endpoint_flag=True,
            quality_code=None,
            status_code=str(row.status),
        )
        for row in rows
        if _valid_lng_lat(row.longitude, row.latitude)
    ]


async def _load_graph_nodes(session: AsyncSession, graph_version_id: int) -> list[EndpointCandidate]:
    rows = list(
        (
            await session.execute(
                select(NavigationGraphNode)
                .where(
                    NavigationGraphNode.graph_version_id == graph_version_id,
                    NavigationGraphNode.is_enabled.is_(True),
                )
                .order_by(NavigationGraphNode.id)
            )
        ).scalars()
    )
    return [
        EndpointCandidate(
            endpoint_uid=f"GRAPH_NODE:{row.graph_version_id}:{row.id}",
            endpoint_type_code="LNG_LAT",
            source_type_code="GRAPH_NODE",
            ref_id=int(row.id),
            code=row.node_code,
            name=row.node_name or row.node_code,
            category_code=row.node_type_code,
            longitude=float(row.longitude),
            latitude=float(row.latitude),
            business_endpoint_flag=False,
            seed_endpoint_flag=True,
            graph_version_id=int(row.graph_version_id),
            channel_id=int(row.channel_id) if row.channel_id is not None else None,
            quality_code=row.quality_code,
            status_code="ENABLED" if row.is_enabled else "DISABLED",
        )
        for row in rows
        if _valid_lng_lat(row.longitude, row.latitude)
    ]


async def _load_centerline_segment_endpoints(session: AsyncSession) -> list[EndpointCandidate]:
    rows = list(
        (
            await session.execute(
                select(NavigationCenterlineSegment)
                .where(
                    NavigationCenterlineSegment.segment_status_code.in_(ACTIVE_CENTERLINE_SEGMENT_STATUSES),
                    NavigationCenterlineSegment.start_lng.is_not(None),
                    NavigationCenterlineSegment.start_lat.is_not(None),
                    NavigationCenterlineSegment.end_lng.is_not(None),
                    NavigationCenterlineSegment.end_lat.is_not(None),
                )
                .order_by(NavigationCenterlineSegment.channel_id, NavigationCenterlineSegment.segment_no, NavigationCenterlineSegment.id)
            )
        ).scalars()
    )
    candidates: list[EndpointCandidate] = []
    for row in rows:
        for suffix, lng, lat in (
            ("START", row.start_lng, row.start_lat),
            ("END", row.end_lng, row.end_lat),
        ):
            if not _valid_lng_lat(lng, lat):
                continue
            candidates.append(
                EndpointCandidate(
                    endpoint_uid=f"CENTERLINE_SEGMENT_{suffix}:{row.id}",
                    endpoint_type_code="LNG_LAT",
                    source_type_code=f"CENTERLINE_SEGMENT_{suffix}",
                    ref_id=int(row.id),
                    code=f"{row.segment_no}:{suffix}",
                    name=f"{row.segment_name} {suffix.lower()}",
                    category_code=row.source_type_code,
                    longitude=float(lng),
                    latitude=float(lat),
                    business_endpoint_flag=False,
                    seed_endpoint_flag=True,
                    channel_id=int(row.channel_id),
                    quality_code=row.quality_code,
                    status_code=row.segment_status_code,
                )
            )
    return candidates


async def _load_water_body_centers(session: AsyncSession, *, limit: int) -> list[EndpointCandidate]:
    if limit <= 0:
        return []
    rows = list(
        (
            await session.execute(
                select(NavigationWaterBody)
                .where(
                    NavigationWaterBody.is_enabled.is_(True),
                    NavigationWaterBody.center_lng.is_not(None),
                    NavigationWaterBody.center_lat.is_not(None),
                )
                .order_by(NavigationWaterBody.source_layer_order, NavigationWaterBody.id)
                .limit(limit)
            )
        ).scalars()
    )
    return [
        EndpointCandidate(
            endpoint_uid=f"WATER_BODY_CENTER:{row.id}",
            endpoint_type_code="LNG_LAT",
            source_type_code="WATER_BODY_CENTER",
            ref_id=int(row.id),
            code=row.water_body_code,
            name=row.display_name or row.water_body_name or row.water_body_code,
            category_code=row.body_role_code,
            longitude=float(row.center_lng),
            latitude=float(row.center_lat),
            business_endpoint_flag=False,
            seed_endpoint_flag=True,
            quality_code=row.quality_code,
            status_code="ENABLED",
        )
        for row in rows
        if _valid_lng_lat(row.center_lng, row.center_lat)
    ]


async def _load_water_area_centers(session: AsyncSession, *, limit: int) -> list[EndpointCandidate]:
    if limit <= 0:
        return []
    rows = list(
        (
            await session.execute(
                select(NavigationWaterArea)
                .where(
                    NavigationWaterArea.is_enabled.is_(True),
                    NavigationWaterArea.center_lng.is_not(None),
                    NavigationWaterArea.center_lat.is_not(None),
                )
                .order_by(NavigationWaterArea.source_layer_order, NavigationWaterArea.id)
                .limit(limit)
            )
        ).scalars()
    )
    return [
        EndpointCandidate(
            endpoint_uid=f"WATER_AREA_CENTER:{row.id}",
            endpoint_type_code="LNG_LAT",
            source_type_code="WATER_AREA_CENTER",
            ref_id=int(row.id),
            code=row.source_object_id,
            name=row.water_name or row.source_object_id,
            category_code=row.water_type_code,
            longitude=float(row.center_lng),
            latitude=float(row.center_lat),
            business_endpoint_flag=False,
            seed_endpoint_flag=True,
            quality_code=row.geometry_status_code,
            status_code="ENABLED",
        )
        for row in rows
        if _valid_lng_lat(row.center_lng, row.center_lat)
    ]


def _dedupe_candidates(candidates: list[EndpointCandidate]) -> list[EndpointCandidate]:
    seen: set[str] = set()
    output: list[EndpointCandidate] = []
    for item in candidates:
        key = f"{item.endpoint_uid}|{item.longitude:.7f},{item.latitude:.7f}"
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _pair_summary(candidates: list[EndpointCandidate]) -> dict[str, Any]:
    total = len(candidates) * (len(candidates) - 1) // 2
    by_source: dict[str, int] = {}
    sources = sorted({item.source_type_code for item in candidates})
    counts = _count_by(candidates, "source_type_code")
    for index, source in enumerate(sources):
        count = int(counts.get(source, 0))
        by_source[f"{source}||{source}"] = count * (count - 1) // 2
        for other in sources[index + 1 :]:
            by_source[f"{source}||{other}"] = count * int(counts.get(other, 0))
    return {
        "total_pair_count": total,
        "pair_count_by_source_pair": by_source,
    }


def _write_pair_matrix(
    candidates: list[EndpointCandidate],
    *,
    output: Path,
    offset: int,
    limit: int | None,
    min_distance_km: float | None,
    max_distance_km: float | None,
) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    visited = 0
    written = 0
    matched_after_distance_filter = 0
    with output.open("w", encoding="utf-8") as handle:
        for origin, destination in _iter_pairs(candidates):
            distance_km = _haversine_km((origin.longitude, origin.latitude), (destination.longitude, destination.latitude))
            if min_distance_km is not None and distance_km < min_distance_km:
                continue
            if max_distance_km is not None and distance_km > max_distance_km:
                continue
            matched_after_distance_filter += 1
            if visited < offset:
                visited += 1
                continue
            if limit is not None and written >= limit:
                break
            handle.write(
                json.dumps(
                    {
                        "pair_no": offset + written + 1,
                        "direct_distance_km": round(distance_km, 3),
                        "origin": _pair_endpoint_payload(origin),
                        "destination": _pair_endpoint_payload(destination),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
            written += 1
    return {
        "path": str(output),
        "offset": offset,
        "limit": limit,
        "written_count": written,
        "matched_after_distance_filter": matched_after_distance_filter,
        "min_distance_km": min_distance_km,
        "max_distance_km": max_distance_km,
    }


def _iter_pairs(candidates: list[EndpointCandidate]) -> Iterable[tuple[EndpointCandidate, EndpointCandidate]]:
    for index, origin in enumerate(candidates):
        for destination in candidates[index + 1 :]:
            yield origin, destination


def _pair_endpoint_payload(item: EndpointCandidate) -> dict[str, Any]:
    return {
        "endpoint_uid": item.endpoint_uid,
        "endpoint_type_code": item.endpoint_type_code,
        "source_type_code": item.source_type_code,
        "ref_id": item.ref_id,
        "code": item.code,
        "name": item.name,
        "category_code": item.category_code,
        "longitude": item.longitude,
        "latitude": item.latitude,
    }


def _graph_payload(row: NavigationGraphVersion | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "version_code": row.version_code,
        "version_name": row.version_name,
        "scope_code": row.scope_code,
        "node_count": row.node_count,
        "edge_count": row.edge_count,
        "quality_score": row.quality_score,
        "built_at": row.built_at.isoformat() if row.built_at else None,
    }


def _excluded_by_default(args: argparse.Namespace, inventory_counts: dict[str, Any]) -> list[dict[str, Any]]:
    excluded: list[dict[str, Any]] = []
    if args.scope != "all" and not args.include_water_body_centers:
        excluded.append(
            {
                "source_type_code": "WATER_BODY_CENTER",
                "count": inventory_counts.get("water_body_centers"),
                "reason": "large water-system derived endpoint set; include with --include-water-body-centers when validating water-body centers",
            }
        )
    if args.scope != "all" and not args.include_water_area_centers:
        excluded.append(
            {
                "source_type_code": "WATER_AREA_CENTER",
                "count": inventory_counts.get("water_area_centers"),
                "reason": "very large polygon-center set; include with --include-water-area-centers and --water-center-limit for sampled seed validation",
            }
        )
    return excluded


def _count_by(candidates: list[EndpointCandidate], attr: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in candidates:
        key = str(getattr(item, attr) or "UNKNOWN")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda pair: pair[0]))


def _valid_lng_lat(lng: Any, lat: Any) -> bool:
    try:
        lon = float(lng)
        latitude = float(lat)
    except (TypeError, ValueError):
        return False
    return -180 <= lon <= 180 and -90 <= latitude <= 90


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1 = math.radians(float(a[0])), math.radians(float(a[1]))
    lon2, lat2 = math.radians(float(b[0])), math.radians(float(b[1]))
    d_lon = lon2 - lon1
    d_lat = lat2 - lat1
    value = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
    return 6371.0088 * 2 * math.atan2(math.sqrt(value), math.sqrt(max(0.0, 1 - value)))


if __name__ == "__main__":
    asyncio.run(main())
