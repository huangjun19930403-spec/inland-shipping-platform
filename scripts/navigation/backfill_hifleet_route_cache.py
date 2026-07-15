"""Backfill local HiFleet route cache for TransportNode pairs.

Examples:
    python -m scripts.navigation.backfill_hifleet_route_cache --dry-run
    python -m scripts.navigation.backfill_hifleet_route_cache --origin-node-id 645 --destination-node-id 724
    python -m scripts.navigation.backfill_hifleet_route_cache --limit 100 --offset 0 --max-distance-km 350
"""

from __future__ import annotations

import argparse
import asyncio
import math
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal, engine
from app.integrations.http.route_geometry_types import RouteGeometryQuery
from app.models.address import TransportNode
from app.models.base import Base
from app.modules.navigation.services.hifleet_route_cache_service import HifleetRouteCacheService
from app.modules.system.runtime_config import RuntimeConfigService


@dataclass(frozen=True)
class NodeItem:
    id: int
    code: str
    name: str
    longitude: float
    latitude: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill navigation_hifleet_route_cache from active TransportNode pairs.")
    parser.add_argument("--origin-node-id", type=int, default=None)
    parser.add_argument("--destination-node-id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--max-distance-km", type=float, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        nodes = await _load_nodes(session)
        total_pairs = len(nodes) * (len(nodes) - 1) // 2
        print(f"active_transport_nodes={len(nodes)}")
        print(f"candidate_pair_count={total_pairs}")
        if args.origin_node_id is not None or args.destination_node_id is not None:
            pairs = [_explicit_pair(nodes, args.origin_node_id, args.destination_node_id)]
        else:
            pairs = list(_iter_pairs(nodes, offset=max(0, args.offset), limit=max(0, args.limit), max_distance_km=args.max_distance_km))
        print(f"selected_pair_count={len(pairs)}")
        if args.dry_run:
            for origin, destination in pairs[:20]:
                distance = _haversine_km([origin.longitude, origin.latitude], [destination.longitude, destination.latitude])
                print(f"dry_run_pair={origin.id}:{origin.name} -> {destination.id}:{destination.name} distance_km={distance:.2f}")
            return

        success = 0
        failed = 0
        service = HifleetRouteCacheService(session, runtime_config=RuntimeConfigService(session))
        for origin, destination in pairs:
            query = RouteGeometryQuery(
                origin_lon=origin.longitude,
                origin_lat=origin.latitude,
                dest_lon=destination.longitude,
                dest_lat=destination.latitude,
                transport_mode="WATER",
                segment_type="TRANSPORT_NODE_PAIR_BACKFILL",
            )
            try:
                result = await service.get_or_generate(
                    query,
                    origin_ref_type_code="TRANSPORT_NODE",
                    origin_ref_id=origin.id,
                    origin_name=origin.name,
                    destination_ref_type_code="TRANSPORT_NODE",
                    destination_ref_id=destination.id,
                    destination_name=destination.name,
                )
                await session.commit()
                success += 1
                summary = result.raw_summary or {}
                print(
                    "cached_pair="
                    f"{origin.id}:{origin.name}->{destination.id}:{destination.name} "
                    f"cache_hit={summary.get('cache_hit')} cache_id={summary.get('hifleet_cache_id')} "
                    f"distance_km={result.distance_km}"
                )
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                failed += 1
                print(f"failed_pair={origin.id}:{origin.name}->{destination.id}:{destination.name} error={exc}")
                if args.stop_on_error:
                    raise
        print(f"backfill_done success={success} failed={failed}")


async def _load_nodes(session) -> list[NodeItem]:
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
        NodeItem(
            id=int(row.id),
            code=row.code,
            name=row.name,
            longitude=float(row.longitude),
            latitude=float(row.latitude),
        )
        for row in rows
    ]


def _explicit_pair(nodes: list[NodeItem], origin_id: int | None, destination_id: int | None) -> tuple[NodeItem, NodeItem]:
    if origin_id is None or destination_id is None:
        raise SystemExit("--origin-node-id and --destination-node-id must be provided together")
    by_id = {node.id: node for node in nodes}
    try:
        return by_id[origin_id], by_id[destination_id]
    except KeyError as exc:
        raise SystemExit(f"TransportNode not found or inactive: {exc}") from exc


def _iter_pairs(
    nodes: list[NodeItem],
    *,
    offset: int,
    limit: int,
    max_distance_km: float | None,
) -> Iterable[tuple[NodeItem, NodeItem]]:
    skipped = 0
    emitted = 0
    for index, origin in enumerate(nodes):
        for destination in nodes[index + 1 :]:
            if max_distance_km is not None:
                distance = _haversine_km([origin.longitude, origin.latitude], [destination.longitude, destination.latitude])
                if distance > max_distance_km:
                    continue
            if skipped < offset:
                skipped += 1
                continue
            if emitted >= limit:
                return
            emitted += 1
            yield origin, destination


def _haversine_km(a: list[float], b: list[float]) -> float:
    lon1, lat1 = math.radians(float(a[0])), math.radians(float(a[1]))
    lon2, lat2 = math.radians(float(b[0])), math.radians(float(b[1]))
    d_lon = lon2 - lon1
    d_lat = lat2 - lat1
    value = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
    return 6371.0088 * 2 * math.atan2(math.sqrt(value), math.sqrt(max(0.0, 1 - value)))


if __name__ == "__main__":
    asyncio.run(main())
