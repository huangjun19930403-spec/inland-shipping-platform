"""Seed the controlled Jiangsu/Yangtze Delta MVP navigation graph.

Round 12 uses this script to create a small, explicit MVP water/centerline/graph
asset set for automated tests and historical acceptance only. It does not import
full river shapefiles, does not overwrite seed channel boundaries, and does not
create fake fallback route geometry. Do not use this script for local production
demonstration data.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pyproj import Geod
from shapely.geometry import LineString, mapping
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import (
    NavigationChannelCenterline,
    NavigationGraphEdge,
    NavigationGraphEdgeConstraint,
    NavigationGraphNode,
    NavigationGraphVersion,
    NavigationRouteQualityIssue,
    NavigationRouteRequest,
    NavigationRouteResult,
    NavigationWaterArea,
)
from app.models.address import NavigationChannel, TransportNode
from scripts.navigation.validate_navigation_graph import validate_navigation_graph

GEOD = Geod(ellps="WGS84")
DEFAULT_DATA_PATH = Path("tests/fixtures/navigation/navigation_mvp_acceptance.json")


@dataclass(slots=True)
class MvpSeedSummary:
    version_code: str
    graph_version_id: int | None
    status_code: str
    is_active: bool
    water_area_count: int
    centerline_count: int
    node_count: int
    edge_count: int
    channel_codes: list[str]
    transport_node_ids: list[int]
    validation_report: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_data(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _line_geometry(coordinates: list[list[float]]) -> dict[str, Any]:
    return {"type": "LineString", "coordinates": [[float(lng), float(lat)] for lng, lat in coordinates]}


def _line_bounds(coordinates: list[list[float]]) -> tuple[float, float, float, float]:
    line = LineString(coordinates)
    min_lng, min_lat, max_lng, max_lat = line.bounds
    return float(min_lng), float(min_lat), float(max_lng), float(max_lat)


def _line_length_km(coordinates: list[list[float]]) -> float:
    if len(coordinates) < 2:
        return 0.0
    lons = [float(coord[0]) for coord in coordinates]
    lats = [float(coord[1]) for coord in coordinates]
    return abs(float(GEOD.line_length(lons, lats))) / 1000.0


def _polygon_from_line(coordinates: list[list[float]], *, buffer_degree: float = 0.025) -> dict[str, Any]:
    line = LineString(coordinates)
    polygon = line.buffer(buffer_degree, cap_style=2, join_style=2)
    return mapping(polygon)


def _area_km2(geometry_json: dict[str, Any]) -> float | None:
    try:
        from shapely.geometry import shape

        area_m2, _ = GEOD.geometry_area_perimeter(shape(geometry_json))
    except Exception:
        return None
    return abs(float(area_m2)) / 1_000_000


async def _load_channels(session: AsyncSession, data: dict[str, Any]) -> dict[str, NavigationChannel]:
    channel_codes = {
        item["channel_code"]
        for item in [*data.get("nodes", []), *data.get("centerline_edges", [])]
        if item.get("channel_code")
    }
    rows = list(
        (
            await session.execute(
                select(NavigationChannel).where(
                    NavigationChannel.channel_code.in_(sorted(channel_codes)),
                    NavigationChannel.is_enabled.is_(True),
                )
            )
        ).scalars()
    )
    by_code = {row.channel_code: row for row in rows}
    missing = sorted(channel_codes - set(by_code))
    if missing:
        raise ValueError(f"Missing navigation channels for MVP seed: {', '.join(missing)}")
    return by_code


async def _load_transport_nodes(session: AsyncSession, data: dict[str, Any]) -> dict[int, TransportNode]:
    transport_node_ids = {
        int(item["transport_node_id"])
        for item in data.get("nodes", [])
        if item.get("transport_node_id") is not None
    }
    if not transport_node_ids:
        return {}
    rows = list(
        (
            await session.execute(
                select(TransportNode).where(
                    TransportNode.id.in_(sorted(transport_node_ids)),
                    TransportNode.longitude.is_not(None),
                    TransportNode.latitude.is_not(None),
                )
            )
        ).scalars()
    )
    by_id = {row.id: row for row in rows}
    missing = sorted(transport_node_ids - set(by_id))
    if missing:
        raise ValueError(f"Missing transport nodes with coordinates for MVP seed: {missing}")
    return by_id


async def _delete_graph_version(session: AsyncSession, graph_version: NavigationGraphVersion) -> None:
    request_ids = list(
        (
            await session.execute(
                select(NavigationRouteRequest.id).where(NavigationRouteRequest.graph_version_id == graph_version.id)
            )
        ).scalars()
    )
    if request_ids:
        result_ids = list(
            (
                await session.execute(
                    select(NavigationRouteResult.id).where(NavigationRouteResult.request_id.in_(request_ids))
                )
            ).scalars()
        )
        if result_ids:
            await session.execute(
                delete(NavigationRouteQualityIssue).where(NavigationRouteQualityIssue.route_result_id.in_(result_ids))
            )
            await session.execute(delete(NavigationRouteResult).where(NavigationRouteResult.id.in_(result_ids)))
        await session.execute(delete(NavigationRouteRequest).where(NavigationRouteRequest.id.in_(request_ids)))

    edge_ids = list(
        (
            await session.execute(
                select(NavigationGraphEdge.id).where(NavigationGraphEdge.graph_version_id == graph_version.id)
            )
        ).scalars()
    )
    if edge_ids:
        await session.execute(delete(NavigationGraphEdgeConstraint).where(NavigationGraphEdgeConstraint.edge_id.in_(edge_ids)))
        await session.execute(delete(NavigationGraphEdge).where(NavigationGraphEdge.id.in_(edge_ids)))
    await session.execute(delete(NavigationGraphNode).where(NavigationGraphNode.graph_version_id == graph_version.id))
    await session.delete(graph_version)
    await session.flush()


async def _upsert_water_area(
    session: AsyncSession,
    *,
    source_code: str,
    edge_config: dict[str, Any],
) -> NavigationWaterArea:
    object_id = edge_config["water_area_object_id"]
    existing = await session.scalar(
        select(NavigationWaterArea).where(
            NavigationWaterArea.source_code == source_code,
            NavigationWaterArea.source_layer_name == "mvp_acceptance",
            NavigationWaterArea.source_object_id == object_id,
        )
    )
    coordinates = edge_config["coordinates"]
    geometry_json = _polygon_from_line(coordinates)
    min_lng, min_lat, max_lng, max_lat = _line_bounds(coordinates)
    payload = {
        "source_code": source_code,
        "source_layer_name": "mvp_acceptance",
        "source_object_id": object_id,
        "water_name": edge_config.get("water_name"),
        "normalized_water_name": edge_config.get("water_name"),
        "alias_names": [],
        "water_level": None,
        "water_type_code": "RIVER" if edge_config["channel_code"] == "NC-YANGTZE" else "CANAL",
        "remark": "Round 12 MVP corridor water area; generated from controlled centerline buffer.",
        "geometry_json": geometry_json,
        "geometry_status_code": "VALID",
        "simplified_geometry_low_json": None,
        "simplified_geometry_mid_json": None,
        "simplified_geometry_high_json": None,
        "bbox_min_lng": min_lng - 0.025,
        "bbox_min_lat": min_lat - 0.025,
        "bbox_max_lng": max_lng + 0.025,
        "bbox_max_lat": max_lat + 0.025,
        "center_lng": (min_lng + max_lng) / 2,
        "center_lat": (min_lat + max_lat) / 2,
        "shape_length_degree": None,
        "shape_area_degree": None,
        "area_km2": _area_km2(geometry_json),
        "is_low_value": False,
        "is_enabled": True,
    }
    if existing is None:
        row = NavigationWaterArea(**payload)
        session.add(row)
        await session.flush()
        return row
    for key, value in payload.items():
        setattr(existing, key, value)
    await session.flush()
    return existing


async def _upsert_centerline(
    session: AsyncSession,
    *,
    channel: NavigationChannel,
    edge_config: dict[str, Any],
) -> NavigationChannelCenterline:
    existing = await session.scalar(
        select(NavigationChannelCenterline).where(
            NavigationChannelCenterline.centerline_code == edge_config["centerline_code"]
        )
    )
    coordinates = edge_config["coordinates"]
    min_lng, min_lat, max_lng, max_lat = _line_bounds(coordinates)
    payload = {
        "channel_id": channel.id,
        "segment_id": None,
        "centerline_code": edge_config["centerline_code"],
        "centerline_name": edge_config.get("centerline_name"),
        "geometry_json": _line_geometry(coordinates),
        "source_type_code": "SEED_CENTERLINE",
        "direction_code": "BIDIRECTIONAL",
        "is_main_line": True,
        "confidence_score": int(edge_config.get("confidence_score", 80)),
        "quality_code": "READY",
        "review_status_code": "PUBLISHED",
        "version_no": 1,
        "parent_centerline_id": None,
        "is_current": True,
        "source_trace_json": {
            "round": "ROUND_12_MVP_ACCEPTANCE",
            "edge_code": edge_config["edge_code"],
            "water_area_object_id": edge_config["water_area_object_id"],
            "publish_rule": "published seed centerline only",
        },
        "approved_by": None,
        "approved_at": datetime.now(UTC).replace(tzinfo=None),
        "bbox_min_lng": min_lng,
        "bbox_min_lat": min_lat,
        "bbox_max_lng": max_lng,
        "bbox_max_lat": max_lat,
    }
    if existing is None:
        row = NavigationChannelCenterline(**payload)
        session.add(row)
        await session.flush()
        return row
    for key, value in payload.items():
        setattr(existing, key, value)
    await session.flush()
    return existing


async def seed_mvp_navigation_data(
    *,
    session: AsyncSession,
    data_path: Path = DEFAULT_DATA_PATH,
    version_code: str = "MVP-JS-YRD-20260522-V1",
    activate: bool = False,
    replace: bool = False,
) -> MvpSeedSummary:
    data = _load_data(data_path)
    channels = await _load_channels(session, data)
    transport_nodes = await _load_transport_nodes(session, data)

    existing_version = await session.scalar(
        select(NavigationGraphVersion).where(NavigationGraphVersion.version_code == version_code)
    )
    if existing_version is not None:
        if not replace:
            raise ValueError(f"Graph version already exists: {version_code}. Use --replace to rebuild this generated MVP graph.")
        await _delete_graph_version(session, existing_version)

    if activate:
        await session.execute(update(NavigationGraphVersion).values(is_active=False))

    water_areas: list[NavigationWaterArea] = []
    centerlines_by_edge_code: dict[str, NavigationChannelCenterline] = {}
    for edge_config in data.get("centerline_edges", []):
        water_areas.append(
            await _upsert_water_area(
                session,
                source_code=data["source_code"],
                edge_config=edge_config,
            )
        )
        centerlines_by_edge_code[edge_config["edge_code"]] = await _upsert_centerline(
            session,
            channel=channels[edge_config["channel_code"]],
            edge_config=edge_config,
        )

    graph_version = NavigationGraphVersion(
        version_code=version_code,
        version_name=data.get("version_name") or version_code,
        scope_code=data.get("scope_code", "YANGTZE_DELTA_MVP"),
        source_summary_json={
            "source_code": data["source_code"],
            "source_file": str(data_path),
            "asset_boundary": "river water areas, seed boundary assets, and MVP seed centerlines coexist; seed boundaries are not overwritten",
            "route_rule": "routing only uses navigation_graph_edge",
            "disclaimer": data.get("disclaimer"),
        },
        node_count=0,
        edge_count=0,
        channel_count=0,
        quality_score=None,
        status_code="BUILDING",
        is_active=activate,
        built_at=datetime.now(UTC).replace(tzinfo=None),
        build_scope_bbox_json=None,
        build_config_json={
            "water_area_source": "controlled_line_buffer",
            "centerline_source_type": "SEED_CENTERLINE",
            "unknown_constraint_policy": "allow route, emit UNKNOWN_CONSTRAINT_DATA, max READY_WITH_WARNING",
        },
    )
    session.add(graph_version)
    await session.flush()

    nodes_by_code: dict[str, NavigationGraphNode] = {}
    for node_config in data.get("nodes", []):
        transport_node: TransportNode | None = None
        if node_config.get("transport_node_id") is not None:
            transport_node = transport_nodes[int(node_config["transport_node_id"])]
            longitude = float(transport_node.longitude)
            latitude = float(transport_node.latitude)
            node_name = transport_node.name
        else:
            longitude = float(node_config["longitude"])
            latitude = float(node_config["latitude"])
            node_name = node_config.get("node_name") or node_config["node_code"]
        channel = channels[node_config["channel_code"]]
        row = NavigationGraphNode(
            graph_version_id=graph_version.id,
            node_code=node_config["node_code"],
            node_name=node_name,
            node_type_code=node_config["node_type_code"],
            longitude=longitude,
            latitude=latitude,
            geometry_json={"type": "Point", "coordinates": [longitude, latitude]},
            channel_id=channel.id,
            related_transport_node_id=transport_node.id if transport_node else None,
            related_constraint_point_id=None,
            is_enabled=True,
            quality_code="READY",
            source_type_code="MVP_ACCEPTANCE_SEED",
            snap_distance_m=0.0 if transport_node else None,
            snap_confidence=95 if transport_node else None,
        )
        session.add(row)
        nodes_by_code[node_config["node_code"]] = row
    await session.flush()

    bbox_points: list[list[float]] = []
    channel_ids: set[int] = set()
    for edge_config in data.get("centerline_edges", []):
        from_node = nodes_by_code[edge_config["from_node_code"]]
        to_node = nodes_by_code[edge_config["to_node_code"]]
        channel = channels[edge_config["channel_code"]]
        centerline = centerlines_by_edge_code[edge_config["edge_code"]]
        coordinates = edge_config["coordinates"]
        bbox_points.extend(coordinates)
        channel_ids.add(channel.id)
        length_km = round(_line_length_km(coordinates), 4)
        row = NavigationGraphEdge(
            graph_version_id=graph_version.id,
            edge_code=edge_config["edge_code"],
            from_node_id=from_node.id,
            to_node_id=to_node.id,
            channel_id=channel.id,
            centerline_id=centerline.id,
            geometry_json=_line_geometry(coordinates),
            length_km=length_km,
            direction_code="BIDIRECTIONAL",
            technical_grade_code=edge_config.get("technical_grade_code"),
            min_depth_m=None,
            min_width_m=None,
            max_allowed_draft_m=None,
            max_allowed_tonnage=None,
            max_air_draft_m=None,
            max_beam_m=None,
            max_length_m=None,
            lock_required=False,
            bridge_count=0,
            risk_score=20,
            base_cost=length_km,
            routing_enabled=True,
            quality_code="READY",
            source_type_code="SEED_CENTERLINE",
            confidence_score=int(edge_config.get("confidence_score", 80)),
            version_no=1,
            unknown_constraint_flag=bool(edge_config.get("unknown_constraint_flag", True)),
            validation_summary_json={
                "round": "ROUND_12_MVP_ACCEPTANCE",
                "constraint_completeness": "UNKNOWN",
                "official_navigation_safety_confirmed": False,
            },
        )
        session.add(row)
    await session.flush()

    if bbox_points:
        min_lng = min(point[0] for point in bbox_points)
        min_lat = min(point[1] for point in bbox_points)
        max_lng = max(point[0] for point in bbox_points)
        max_lat = max(point[1] for point in bbox_points)
        graph_version.build_scope_bbox_json = {
            "min_lng": min_lng,
            "min_lat": min_lat,
            "max_lng": max_lng,
            "max_lat": max_lat,
        }
    graph_version.node_count = len(nodes_by_code)
    graph_version.edge_count = len(data.get("centerline_edges", []))
    graph_version.channel_count = len(channel_ids)
    await session.flush()

    validation_report = await validate_navigation_graph(
        session=session,
        graph_version_id=graph_version.id,
        update_version=True,
    )
    if activate and validation_report.status_code == "READY":
        graph_version.is_active = True
        await session.commit()

    warnings = []
    if validation_report.warning_issue_count:
        warnings.append("MVP graph contains UNKNOWN_CONSTRAINT_DATA warnings; route quality must be READY_WITH_WARNING at most.")

    return MvpSeedSummary(
        version_code=version_code,
        graph_version_id=graph_version.id,
        status_code=validation_report.status_code,
        is_active=bool(graph_version.is_active),
        water_area_count=len(water_areas),
        centerline_count=len(centerlines_by_edge_code),
        node_count=validation_report.node_count,
        edge_count=validation_report.edge_count,
        channel_codes=sorted({item["channel_code"] for item in data.get("centerline_edges", [])}),
        transport_node_ids=sorted(transport_nodes),
        validation_report=validation_report.as_dict(),
        warnings=warnings,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed Jiangsu/Yangtze Delta MVP navigation graph data.")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--version-code", default="MVP-JS-YRD-20260522-V1")
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    async with AsyncSessionLocal() as session:
        summary = await seed_mvp_navigation_data(
            session=session,
            data_path=args.data,
            version_code=args.version_code,
            activate=args.activate,
            replace=args.replace,
        )
    payload = summary.as_dict()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
