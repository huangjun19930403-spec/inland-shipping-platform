"""Load curated revier production centerline and graph seed artifacts."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, update

from app.core.database import AsyncSessionLocal, engine
from app.models import (
    NavigationAnnotationTask,
    NavigationCenterlineSegment,
    NavigationChannelCenterline,
    NavigationGraphEdge,
    NavigationGraphEdgeConstraint,
    NavigationGraphNode,
    NavigationGraphVersion,
    NavigationRouteQualityIssue,
)
from app.models.address import NavigationChannel, NavigationChannelBoundary, TransportNode
from app.models.base import Base
from app.modules.navigation.production_pipeline.constants import (
    DEFAULT_SEED_DIR,
    REVIER_GRAPH_VERSION_CODE,
    REVIER_SEED_PREFIX,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
COORDINATE_SCALE = Decimal("0.000000000000001")
LENGTH_SCALE = Decimal("0.0001")


def _load_seed(name: str, *, seed_dir: Path = DEFAULT_SEED_DIR, default: Any = None) -> Any:
    path = seed_dir / name
    if not path.exists():
        return [] if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def _decimal(value: Any, scale: Decimal = COORDINATE_SCALE) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value)).quantize(scale, rounding=ROUND_HALF_UP)


def _datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


async def _prepare_schema() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def seed_navigation_revier_production(
    *,
    seed_dir: Path = DEFAULT_SEED_DIR,
    prepare_schema: bool = True,
) -> dict[str, int]:
    if prepare_schema:
        await _prepare_schema()

    boundaries = _load_seed(f"navigation_channel_boundaries.{REVIER_SEED_PREFIX}.json", seed_dir=seed_dir)
    centerlines = _load_seed(f"navigation_channel_centerlines.{REVIER_SEED_PREFIX}.json", seed_dir=seed_dir)
    segments = _load_seed(f"navigation_centerline_segments.{REVIER_SEED_PREFIX}.json", seed_dir=seed_dir)
    graph_versions = _load_seed(f"navigation_graph_versions.{REVIER_SEED_PREFIX}.json", seed_dir=seed_dir)
    graph_nodes = _load_seed(f"navigation_graph_nodes.{REVIER_SEED_PREFIX}.json", seed_dir=seed_dir)
    graph_edges = _load_seed(f"navigation_graph_edges.{REVIER_SEED_PREFIX}.json", seed_dir=seed_dir)
    constraints = _load_seed(f"navigation_graph_edge_constraints.{REVIER_SEED_PREFIX}.json", seed_dir=seed_dir)
    annotation_tasks = _load_seed(f"navigation_annotation_tasks.{REVIER_SEED_PREFIX}.json", seed_dir=seed_dir)
    quality_report = _load_seed(
        f"navigation_production_quality_report.{REVIER_SEED_PREFIX}.json",
        seed_dir=seed_dir,
        default={},
    )

    if not graph_versions:
        return {
            "boundaries": 0,
            "centerlines": 0,
            "centerline_segments": 0,
            "graph_versions": 0,
            "graph_nodes": 0,
            "graph_edges": 0,
            "graph_edge_constraints": 0,
            "annotation_tasks": 0,
        }

    async with AsyncSessionLocal() as session:
        channel_rows = list((await session.execute(select(NavigationChannel))).scalars())
        channel_by_code = {row.channel_code: row for row in channel_rows}
        transport_rows = list((await session.execute(select(TransportNode))).scalars())
        transport_by_code = {row.code: row for row in transport_rows}

        await delete_existing_revier_graph_payload(session)
        await _upsert_boundaries(session, boundaries, channel_by_code)
        centerline_by_code = await _upsert_centerlines(session, centerlines, channel_by_code)
        await _replace_segments(session, segments, channel_by_code, centerline_by_code)
        graph_version = await _upsert_graph_version(session, graph_versions[0], quality_report)
        node_by_code = await _replace_graph_nodes(session, graph_version.id, graph_nodes, channel_by_code, transport_by_code)
        edge_by_code = await _replace_graph_edges(session, graph_version.id, graph_edges, channel_by_code, centerline_by_code, node_by_code)
        await _replace_graph_constraints(session, constraints, edge_by_code)
        await _upsert_annotation_tasks(session, annotation_tasks, channel_by_code, graph_version.id)
        await session.commit()

    return {
        "boundaries": len(boundaries),
        "centerlines": len(centerlines),
        "centerline_segments": len(segments),
        "graph_versions": len(graph_versions),
        "graph_nodes": len(graph_nodes),
        "graph_edges": len(graph_edges),
        "graph_edge_constraints": len(constraints),
        "annotation_tasks": len(annotation_tasks),
    }


async def delete_existing_revier_graph_payload(session: Any) -> None:
    graph_version = await session.scalar(
        select(NavigationGraphVersion).where(NavigationGraphVersion.version_code == REVIER_GRAPH_VERSION_CODE)
    )
    centerline_ids = [
        int(row[0])
        for row in (
            await session.execute(
                select(NavigationChannelCenterline.id).where(NavigationChannelCenterline.centerline_code.like("REVCL-%"))
            )
        ).all()
    ]
    if graph_version is not None:
        edge_ids = [
            int(row[0])
            for row in (
                await session.execute(
                    select(NavigationGraphEdge.id).where(NavigationGraphEdge.graph_version_id == graph_version.id)
                )
            ).all()
        ]
        node_ids = [
            int(row[0])
            for row in (
                await session.execute(
                    select(NavigationGraphNode.id).where(NavigationGraphNode.graph_version_id == graph_version.id)
                )
            ).all()
        ]
        if edge_ids:
            await session.execute(delete(NavigationRouteQualityIssue).where(NavigationRouteQualityIssue.related_edge_id.in_(edge_ids)))
            await session.execute(delete(NavigationGraphEdgeConstraint).where(NavigationGraphEdgeConstraint.edge_id.in_(edge_ids)))
        if node_ids:
            await session.execute(delete(NavigationRouteQualityIssue).where(NavigationRouteQualityIssue.related_node_id.in_(node_ids)))
        await session.execute(delete(NavigationGraphEdge).where(NavigationGraphEdge.graph_version_id == graph_version.id))
        await session.execute(delete(NavigationGraphNode).where(NavigationGraphNode.graph_version_id == graph_version.id))
    if centerline_ids:
        await session.execute(delete(NavigationCenterlineSegment).where(NavigationCenterlineSegment.centerline_id.in_(centerline_ids)))
        await session.execute(delete(NavigationChannelCenterline).where(NavigationChannelCenterline.id.in_(centerline_ids)))
    await session.execute(delete(NavigationAnnotationTask).where(NavigationAnnotationTask.task_no.like("REV-%")))
    await session.flush()


async def _upsert_boundaries(session: Any, rows: list[dict[str, Any]], channel_by_code: dict[str, NavigationChannel]) -> None:
    for row in rows:
        channel = channel_by_code.get(str(row.get("channel_code") or ""))
        if channel is None:
            continue
        existing = await session.scalar(
            select(NavigationChannelBoundary)
            .where(NavigationChannelBoundary.channel_id == channel.id, NavigationChannelBoundary.is_current.is_(True))
            .order_by(NavigationChannelBoundary.id.desc())
        )
        payload = dict(row)
        payload.pop("channel_code", None)
        payload["channel_id"] = channel.id
        payload["imported_at"] = _datetime(payload.get("imported_at"))
        for field in (
            "center_longitude",
            "center_latitude",
            "display_center_longitude",
            "display_center_latitude",
            "bbox_min_lng",
            "bbox_min_lat",
            "bbox_max_lng",
            "bbox_max_lat",
            "source_shape_length_degree",
            "source_shape_area_degree",
        ):
            payload[field] = _decimal(payload.get(field), LENGTH_SCALE if field.startswith("source_shape") else COORDINATE_SCALE)
        if existing is None:
            session.add(NavigationChannelBoundary(**payload))
        else:
            for key, value in payload.items():
                setattr(existing, key, value)
    await session.flush()


async def _upsert_centerlines(
    session: Any,
    rows: list[dict[str, Any]],
    channel_by_code: dict[str, NavigationChannel],
) -> dict[str, NavigationChannelCenterline]:
    output: dict[str, NavigationChannelCenterline] = {}
    for row in rows:
        channel = channel_by_code.get(str(row.get("channel_code") or ""))
        if channel is None:
            continue
        await session.execute(
            update(NavigationChannelCenterline)
            .where(
                NavigationChannelCenterline.channel_id == channel.id,
                NavigationChannelCenterline.centerline_code != row["centerline_code"],
            )
            .values(is_current=False)
        )
        existing = await session.scalar(
            select(NavigationChannelCenterline).where(NavigationChannelCenterline.centerline_code == row["centerline_code"])
        )
        payload = dict(row)
        payload.pop("channel_code", None)
        payload["channel_id"] = channel.id
        for field in ("bbox_min_lng", "bbox_min_lat", "bbox_max_lng", "bbox_max_lat"):
            payload[field] = _decimal(payload.get(field))
        if existing is None:
            existing = NavigationChannelCenterline(**payload)
            session.add(existing)
        else:
            for key, value in payload.items():
                setattr(existing, key, value)
        await session.flush()
        output[row["centerline_code"]] = existing
    return output


async def _replace_segments(
    session: Any,
    rows: list[dict[str, Any]],
    channel_by_code: dict[str, NavigationChannel],
    centerline_by_code: dict[str, NavigationChannelCenterline],
) -> None:
    for row in rows:
        channel = channel_by_code.get(str(row.get("channel_code") or ""))
        centerline = centerline_by_code.get(str(row.get("centerline_code") or ""))
        if channel is None or centerline is None:
            continue
        payload = dict(row)
        payload.pop("channel_code", None)
        payload.pop("centerline_code", None)
        payload["channel_id"] = channel.id
        payload["centerline_id"] = centerline.id
        for field in (
            "length_m",
            "start_lng",
            "start_lat",
            "end_lng",
            "end_lat",
            "bbox_min_lng",
            "bbox_min_lat",
            "bbox_max_lng",
            "bbox_max_lat",
        ):
            payload[field] = _decimal(payload.get(field), Decimal("0.01") if field == "length_m" else COORDINATE_SCALE)
        session.add(NavigationCenterlineSegment(**payload))
    await session.flush()


async def _upsert_graph_version(session: Any, row: dict[str, Any], quality_report: dict[str, Any]) -> NavigationGraphVersion:
    await session.execute(
        update(NavigationGraphVersion)
        .where(NavigationGraphVersion.version_code != REVIER_GRAPH_VERSION_CODE)
        .values(is_active=False)
    )
    existing = await session.scalar(
        select(NavigationGraphVersion).where(NavigationGraphVersion.version_code == REVIER_GRAPH_VERSION_CODE)
    )
    payload = dict(row)
    payload["built_at"] = _datetime(payload.get("built_at")) or datetime.utcnow()
    payload["validation_report_json"] = {
        **(payload.get("validation_report_json") or {}),
        "production_quality_report": quality_report,
    }
    if existing is None:
        existing = NavigationGraphVersion(**payload)
        session.add(existing)
    else:
        for key, value in payload.items():
            setattr(existing, key, value)
    await session.flush()
    return existing


async def _replace_graph_nodes(
    session: Any,
    graph_version_id: int,
    rows: list[dict[str, Any]],
    channel_by_code: dict[str, NavigationChannel],
    transport_by_code: dict[str, TransportNode],
) -> dict[str, NavigationGraphNode]:
    output: dict[str, NavigationGraphNode] = {}
    for row in rows:
        channel = channel_by_code.get(str(row.get("channel_code") or ""))
        transport = transport_by_code.get(str(row.get("related_transport_node_code") or ""))
        payload = dict(row)
        payload.pop("channel_code", None)
        payload.pop("related_transport_node_code", None)
        payload["graph_version_id"] = graph_version_id
        payload["channel_id"] = channel.id if channel else None
        payload["related_transport_node_id"] = transport.id if transport else None
        payload["related_constraint_point_id"] = None
        for field in ("longitude", "latitude", "snap_distance_m"):
            payload[field] = _decimal(payload.get(field), Decimal("0.001") if field == "snap_distance_m" else COORDINATE_SCALE)
        node = NavigationGraphNode(**payload)
        session.add(node)
        await session.flush()
        output[row["node_code"]] = node
    return output


async def _replace_graph_edges(
    session: Any,
    graph_version_id: int,
    rows: list[dict[str, Any]],
    channel_by_code: dict[str, NavigationChannel],
    centerline_by_code: dict[str, NavigationChannelCenterline],
    node_by_code: dict[str, NavigationGraphNode],
) -> dict[str, NavigationGraphEdge]:
    output: dict[str, NavigationGraphEdge] = {}
    for row in rows:
        from_node = node_by_code.get(str(row.get("from_node_code") or ""))
        to_node = node_by_code.get(str(row.get("to_node_code") or ""))
        if from_node is None or to_node is None:
            continue
        channel = channel_by_code.get(str(row.get("channel_code") or ""))
        centerline = centerline_by_code.get(str(row.get("centerline_code") or ""))
        payload = dict(row)
        payload.pop("from_node_code", None)
        payload.pop("to_node_code", None)
        payload.pop("channel_code", None)
        payload.pop("centerline_code", None)
        payload["graph_version_id"] = graph_version_id
        payload["from_node_id"] = from_node.id
        payload["to_node_id"] = to_node.id
        payload["channel_id"] = channel.id if channel else None
        payload["centerline_id"] = centerline.id if centerline else None
        payload["length_km"] = _decimal(payload.get("length_km"), LENGTH_SCALE) or Decimal("0")
        edge = NavigationGraphEdge(**payload)
        session.add(edge)
        await session.flush()
        output[row["edge_code"]] = edge
    return output


async def _replace_graph_constraints(
    session: Any,
    rows: list[dict[str, Any]],
    edge_by_code: dict[str, NavigationGraphEdge],
) -> None:
    for row in rows:
        edge = edge_by_code.get(str(row.get("edge_code") or ""))
        if edge is None:
            continue
        payload = dict(row)
        payload.pop("edge_code", None)
        payload["edge_id"] = edge.id
        session.add(NavigationGraphEdgeConstraint(**payload))
    await session.flush()


async def _upsert_annotation_tasks(
    session: Any,
    rows: list[dict[str, Any]],
    channel_by_code: dict[str, NavigationChannel],
    graph_version_id: int,
) -> None:
    for row in rows:
        channel = channel_by_code.get(str(row.get("target_code") or ""))
        payload = dict(row)
        payload.pop("target_code", None)
        payload["target_id"] = channel.id if channel and payload.get("target_type_code") == "NAVIGATION_CHANNEL" else payload.get("target_id")
        payload["channel_id"] = channel.id if channel else payload.get("channel_id")
        payload.setdefault("graph_version_id", graph_version_id)
        existing = await session.scalar(select(NavigationAnnotationTask).where(NavigationAnnotationTask.task_no == payload["task_no"]))
        if existing is None:
            session.add(NavigationAnnotationTask(**payload))
        else:
            for key, value in payload.items():
                setattr(existing, key, value)
    await session.flush()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load revier production navigation graph seed.")
    parser.add_argument("--seed-dir", type=Path, default=DEFAULT_SEED_DIR)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    print(json.dumps(asyncio.run(seed_navigation_revier_production(seed_dir=args.seed_dir)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
