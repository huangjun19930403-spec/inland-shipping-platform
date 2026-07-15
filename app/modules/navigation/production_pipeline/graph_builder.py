from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, Point, mapping

from app.modules.navigation.production_pipeline.boundary_quality_audit import vessel_limit_profile
from app.modules.navigation.production_pipeline.centerline_builder import (
    clean_line_coords,
    derive_boundary_centerline,
    derive_boundary_centerlines,
    line_length_m,
    line_seed_fields,
    point_distance_m,
    validate_centerline_against_boundary,
)
from app.modules.navigation.production_pipeline.constants import (
    DEFAULT_SEED_DIR,
    REVIER_GRAPH_SCOPE_CODE,
    REVIER_GRAPH_VERSION_CODE,
    REVIER_SEED_PREFIX,
)
from app.modules.navigation.production_pipeline.seed_exporter import write_json


@dataclass(slots=True)
class CenterlineAsset:
    channel_code: str
    centerline_code: str
    line: LineString
    channel_name: str | None
    channel_type_code: str | None
    technical_grade_code: str | None = None
    vessel_limit_profile: dict[str, Any] = field(default_factory=dict)
    boundary_trust_code: str | None = None
    quality_code: str = "READY_WITH_WARNING"
    confidence_score: int = 88
    review_issue_codes: list[str] = field(
        default_factory=lambda: ["REVIER_DERIVED_NEEDS_OPERATOR_REVIEW", "GUIDE_PASSTHROUGH_BOUNDARY_REVIEW"]
    )


@dataclass(slots=True)
class TransportSnap:
    transport_node_code: str
    transport_node_name: str
    transport_node_id_hint: int | None
    point: Point
    snap_point: Point
    snap_ratio: float
    snap_distance_m: float
    channel_code: str
    centerline_code: str


@dataclass(slots=True)
class GraphSeedBuild:
    boundaries: list[dict[str, Any]]
    centerlines: list[dict[str, Any]]
    centerline_segments: list[dict[str, Any]]
    graph_versions: list[dict[str, Any]]
    graph_nodes: list[dict[str, Any]]
    graph_edges: list[dict[str, Any]]
    graph_edge_constraints: list[dict[str, Any]]
    annotation_tasks: list[dict[str, Any]]
    report: dict[str, Any] = field(default_factory=dict)


def _clean_code(value: Any, max_len: int = 96) -> str:
    text = re.sub(r"[^0-9A-Za-z_-]+", "-", str(value or "")).strip("-")
    return (text or "UNKNOWN")[:max_len]


def _round_point(point: Point) -> tuple[float, float]:
    return (round(float(point.x), 7), round(float(point.y), 7))


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _transport_node_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload if isinstance(payload, list) else (payload.get("nodes") or payload.get("records") or [])
    output: list[dict[str, Any]] = []
    for row in rows:
        lng = _float(row.get("longitude"))
        lat = _float(row.get("latitude"))
        if lng is None or lat is None or not (-180 <= lng <= 180 and -90 <= lat <= 90):
            continue
        if int(row.get("status") or 0) != 1:
            continue
        output.append({**row, "longitude": lng, "latitude": lat})
    return output


def build_centerline_seed_rows(
    *,
    channel_records: list[dict[str, Any]],
    boundary_rows: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[CenterlineAsset], list[dict[str, Any]]]:
    centerlines: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    assets: list[CenterlineAsset] = []
    annotation_tasks: list[dict[str, Any]] = []
    boundary_by_channel = {str(row.get("channel_code") or ""): row for row in (boundary_rows or [])}
    for record in channel_records:
        channel = dict(record.get("channel") or {})
        channel_code = str(channel.get("channel_code") or "")
        if not channel_code:
            continue
        boundary = dict(boundary_by_channel.get(channel_code) or record.get("boundary") or {})
        if boundary.get("geometry_status_code") != "AVAILABLE" or not boundary.get("geometry_json"):
            continue
        component_lines = derive_boundary_centerlines(boundary["geometry_json"])
        if not component_lines:
            line = derive_boundary_centerline(boundary["geometry_json"])
            component_lines = [line] if line is not None else []
        if not component_lines:
            annotation_tasks.append(
                {
                    "task_no": f"REV-CL-FAILED-{channel_code}",
                    "task_type_code": "CENTERLINE_REPAIR",
                    "target_type_code": "NAVIGATION_CHANNEL",
                    "target_code": channel_code,
                    "priority_code": "HIGH",
                    "status_code": "OPEN",
                    "issue_summary": "revier 生产 pipeline 无法从当前航道边界稳定生成中心线。",
                    "suggestion_json": {"issue_code": "CENTERLINE_DERIVATION_FAILED"},
                }
            )
            continue
        for component_index, line in enumerate(component_lines, start=1):
            validation = validate_centerline_against_boundary(line, boundary["geometry_json"])
            if validation["status_code"] != "READY":
                annotation_tasks.append(
                    {
                        "task_no": f"REV-CL-INVALID-{channel_code}-{component_index:03d}",
                        "task_type_code": "CENTERLINE_REPAIR",
                        "target_type_code": "NAVIGATION_CHANNEL",
                        "target_code": channel_code,
                        "priority_code": "HIGH",
                        "status_code": "OPEN",
                        "issue_summary": "revier 生产 pipeline 生成的组件中心线未通过边界内、点数、折返等质量校验，已拒绝进入路径图。",
                        "suggestion_json": {
                            "issue_code": "CENTERLINE_VALIDATION_FAILED",
                            "validation": validation,
                        },
                    }
                )
                continue
            component_water_area = _component_water_area_summary(line, boundary)
            is_direct_water_area = _component_is_direct_water_area(component_water_area)
            boundary_audit = _boundary_integrity_audit(boundary)
            boundary_issue_codes = list(boundary_audit.get("issue_codes") or [])
            vessel_profile = vessel_limit_profile(
                current_grade_code=channel.get("technical_grade_current_code"),
                planned_grade_code=channel.get("technical_grade_planned_code"),
            )
            review_issue_codes = ["REVIER_DERIVED_NEEDS_OPERATOR_REVIEW", "GUIDE_PASSTHROUGH_BOUNDARY_REVIEW"]
            if not is_direct_water_area:
                review_issue_codes.append("REVIER_BRIDGE_WATER_AREA_NEEDS_REVIEW")
            for issue_code in boundary_issue_codes:
                if issue_code not in review_issue_codes:
                    review_issue_codes.append(issue_code)
            for issue_code in vessel_profile.get("issue_codes") or []:
                if issue_code not in review_issue_codes:
                    review_issue_codes.append(issue_code)
            quality_code = "READY_WITH_WARNING" if is_direct_water_area else "LOW_CONFIDENCE"
            confidence_score = 88 if is_direct_water_area else 72
            if boundary_audit.get("trust_code") in {"FAILED", "NEEDS_REVIEW"}:
                quality_code = "LOW_CONFIDENCE"
                confidence_score = min(confidence_score, 60)
            centerline_code = f"REVCL-{_clean_code(channel_code, 64)}-{component_index:03d}"
            line_fields = line_seed_fields(line)
            algorithm_code = "REVIER_BANK_PAIR_CENTERLINE_V2"
            centerline = {
                "channel_code": channel_code,
                "centerline_code": centerline_code,
                "centerline_name": f"{channel.get('channel_name') or channel_code} revier 生产中心线 {component_index}",
                "geometry_json": line_fields["geometry_json"],
                "source_type_code": "REVIER_WATER_AREA_CENTERLINE",
                "direction_code": "BIDIRECTIONAL",
                "is_main_line": component_index == 1,
                "confidence_score": confidence_score,
                "quality_code": quality_code,
                "review_status_code": "PUBLISHED",
                "version_no": 1,
                "is_current": True,
                "source_trace_json": {
                    "source": "navigation_revier_production_seed",
                    "algorithm": algorithm_code,
                    "source_boundary_channel_code": channel_code,
                    "component_index": component_index,
                    "component_water_area": component_water_area,
                    "boundary_integrity_audit": boundary_audit,
                    "water_system": boundary_audit.get("water_system"),
                    "vessel_limit_profile": vessel_profile,
                    "manual_publish_gate": "production_seed",
                    "validation": validation,
                    "hifleet_benchmark_policy": "same water-route guardrails: no straight fallback, enough points, anchored path, provider/edge trace required",
                },
                "bbox_min_lng": line_fields["bbox_min_lng"],
                "bbox_min_lat": line_fields["bbox_min_lat"],
                "bbox_max_lng": line_fields["bbox_max_lng"],
                "bbox_max_lat": line_fields["bbox_max_lat"],
            }
            segment = {
                "channel_code": channel_code,
                "centerline_code": centerline_code,
                "segment_no": f"REVSEG-{_clean_code(channel_code, 20)}-{component_index:03d}",
                "segment_name": f"{channel.get('channel_name') or channel_code} revier 生产分段 {component_index}",
                "segment_status_code": "PUBLISHED",
                "geometry_json": line_fields["geometry_json"],
                "source_type_code": "REVIER_WATER_AREA_CENTERLINE",
                "quality_code": quality_code,
                "length_m": line_fields["length_m"],
                "start_lng": line_fields["start_lng"],
                "start_lat": line_fields["start_lat"],
                "end_lng": line_fields["end_lng"],
                "end_lat": line_fields["end_lat"],
                "bbox_min_lng": line_fields["bbox_min_lng"],
                "bbox_min_lat": line_fields["bbox_min_lat"],
                "bbox_max_lng": line_fields["bbox_max_lng"],
                "bbox_max_lat": line_fields["bbox_max_lat"],
                "start_connected_flag": True,
                "end_connected_flag": True,
                "issue_summary_json": {"warning_count": len(review_issue_codes), "warnings": review_issue_codes},
                "validation_summary_json": {
                    "quality_code": validation["quality_code"],
                    "issue_codes": sorted(set([*review_issue_codes, *validation["issue_codes"]])),
                    "centerline_validation": validation,
                },
                "source_trace_json": {
                    "source": "navigation_revier_production_seed",
                    "centerline_code": centerline_code,
                    "algorithm": algorithm_code,
                    "component_water_area": component_water_area,
                    "boundary_integrity_audit": boundary_audit,
                    "vessel_limit_profile": vessel_profile,
                },
            }
            centerlines.append(centerline)
            segments.append(segment)
            assets.append(
                CenterlineAsset(
                    channel_code=channel_code,
                    centerline_code=centerline_code,
                    line=line,
                    channel_name=channel.get("channel_name"),
                    channel_type_code=channel.get("channel_type_code"),
                    technical_grade_code=vessel_profile.get("technical_grade_code"),
                    vessel_limit_profile=vessel_profile,
                    boundary_trust_code=boundary_audit.get("trust_code"),
                    quality_code=quality_code,
                    confidence_score=confidence_score,
                    review_issue_codes=review_issue_codes,
                )
            )
    return centerlines, segments, assets, annotation_tasks


def _boundary_integrity_audit(boundary: dict[str, Any]) -> dict[str, Any]:
    source_trace = boundary.get("source_trace_json") if isinstance(boundary.get("source_trace_json"), dict) else {}
    audit = source_trace.get("boundary_integrity_audit") if isinstance(source_trace, dict) else None
    return dict(audit) if isinstance(audit, dict) else {}


def _component_water_area_summary(line: LineString, boundary: dict[str, Any]) -> dict[str, Any] | None:
    trace = boundary.get("source_trace_json") if isinstance(boundary.get("source_trace_json"), dict) else {}
    summaries = trace.get("selected_water_areas") if isinstance(trace, dict) else None
    if not isinstance(summaries, list):
        return None
    point = line.interpolate(0.5, normalized=True)
    line_min_lng, line_min_lat, line_max_lng, line_max_lat = line.bounds
    candidates: list[tuple[float, dict[str, Any]]] = []
    tolerance = 0.0005
    for summary in summaries:
        bbox = summary.get("bbox") if isinstance(summary, dict) else None
        if not isinstance(bbox, list | tuple) or len(bbox) < 4:
            continue
        min_lng, min_lat, max_lng, max_lat = [float(value) for value in bbox[:4]]
        contains_midpoint = (
            min_lng - tolerance <= float(point.x) <= max_lng + tolerance
            and min_lat - tolerance <= float(point.y) <= max_lat + tolerance
        )
        intersects_line_bbox = not (
            min_lng > line_max_lng + tolerance
            or max_lng < line_min_lng - tolerance
            or min_lat > line_max_lat + tolerance
            or max_lat < line_min_lat - tolerance
        )
        if not contains_midpoint or not intersects_line_bbox:
            continue
        bbox_area = max((max_lng - min_lng) * (max_lat - min_lat), 0.0)
        candidates.append((bbox_area, summary))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return dict(candidates[0][1])


def _component_is_direct_water_area(summary: dict[str, Any] | None) -> bool:
    if summary is None:
        return True
    return bool(summary.get("direct_match"))


def _nearest_centerline(point: Point, assets: list[CenterlineAsset]) -> tuple[CenterlineAsset, Point, float, float] | None:
    best: tuple[CenterlineAsset, Point, float, float] | None = None
    for asset in assets:
        projected_distance = asset.line.project(point)
        snap_point = asset.line.interpolate(projected_distance)
        distance_m = point_distance_m(point, snap_point)
        ratio = 0.0 if asset.line.length <= 0 else projected_distance / asset.line.length
        if best is None or distance_m < best[2]:
            best = (asset, snap_point, distance_m, ratio)
    return best


def asset_limit_profile(source_type_code: str, centerline_code: str | None, assets: list[CenterlineAsset]) -> dict[str, Any]:
    if source_type_code == "TRANSPORT_NODE_CONNECTOR":
        return {
            "technical_grade_code": None,
            "unknown_constraint_flag": True,
            "constraint_data_completeness_code": "CONNECTOR_UNKNOWN",
            "source_code": "TRANSPORT_NODE_CONNECTOR",
            "issue_codes": ["TRANSPORT_CONNECTOR_NAVIGATION_CONSTRAINT_UNKNOWN"],
            "note": "运输节点接入段需要现场/作业区水域资料复核。",
        }
    if centerline_code:
        for asset in assets:
            if asset.centerline_code == centerline_code:
                return dict(asset.vessel_limit_profile or {})
    return {
        "technical_grade_code": None,
        "unknown_constraint_flag": True,
        "constraint_data_completeness_code": "UNKNOWN",
        "source_code": "CENTERLINE_ASSET_MISSING",
        "issue_codes": ["NAVIGATION_TECHNICAL_GRADE_UNKNOWN"],
        "note": "图边没有可追溯的中心线技术等级。",
    }


def _asset_boundary_trust(centerline_code: str | None, assets: list[CenterlineAsset]) -> str | None:
    if not centerline_code:
        return None
    for asset in assets:
        if asset.centerline_code == centerline_code:
            return asset.boundary_trust_code
    return None


def _component_summary(node_codes: list[str], edge_rows: list[dict[str, Any]]) -> dict[str, int]:
    parent = {code: code for code in node_codes}

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        l_root = find(left)
        r_root = find(right)
        if l_root != r_root:
            parent[r_root] = l_root

    for edge in edge_rows:
        if edge.get("routing_enabled"):
            union(edge["from_node_code"], edge["to_node_code"])
    groups: dict[str, set[str]] = {}
    for code in node_codes:
        groups.setdefault(find(code), set()).add(code)
    return {
        "connected_component_count": len(groups),
        "largest_component_node_count": max((len(items) for items in groups.values()), default=0),
    }


def build_graph_seed_rows(
    *,
    assets: list[CenterlineAsset],
    transport_node_seed_path: Path,
    max_transport_snap_m: float = 3000.0,
    max_component_connector_m: float = 18000.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    transport_nodes = _transport_node_rows(transport_node_seed_path)
    snaps: list[TransportSnap] = []
    for row in transport_nodes:
        nearest = _nearest_centerline(Point(row["longitude"], row["latitude"]), assets)
        if nearest is None:
            continue
        asset, snap_point, distance_m, ratio = nearest
        if distance_m > max_transport_snap_m:
            continue
        snaps.append(
            TransportSnap(
                transport_node_code=str(row.get("code") or ""),
                transport_node_name=str(row.get("name") or row.get("code") or ""),
                transport_node_id_hint=None,
                point=Point(row["longitude"], row["latitude"]),
                snap_point=snap_point,
                snap_ratio=max(0.0, min(1.0, float(ratio))),
                snap_distance_m=distance_m,
                channel_code=asset.channel_code,
                centerline_code=asset.centerline_code,
            )
        )

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    asset_endpoint_nodes: list[tuple[CenterlineAsset, str, Point, str, Point]] = []

    def add_node(
        node_code: str,
        *,
        point: Point,
        node_type_code: str,
        source_type_code: str,
        channel_code: str | None = None,
        node_name: str | None = None,
        related_transport_node_code: str | None = None,
        snap_distance_m: float | None = None,
        snap_confidence: int | None = None,
    ) -> None:
        if node_code in nodes:
            return
        nodes[node_code] = {
            "node_code": node_code,
            "node_name": node_name,
            "node_type_code": node_type_code,
            "longitude": float(point.x),
            "latitude": float(point.y),
            "geometry_json": mapping(point),
            "channel_code": channel_code,
            "related_transport_node_code": related_transport_node_code,
            "is_enabled": True,
            "quality_code": "READY",
            "source_type_code": source_type_code,
            "snap_distance_m": round(float(snap_distance_m), 3) if snap_distance_m is not None else None,
            "snap_confidence": snap_confidence,
        }

    def add_edge(
        edge_code: str,
        *,
        from_node_code: str,
        to_node_code: str,
        channel_code: str | None,
        centerline_code: str | None,
        line: LineString,
        source_type_code: str,
        confidence_score: int,
        quality_code: str = "READY",
        routing_enabled: bool = True,
        validation_summary_json: dict[str, Any] | None = None,
    ) -> None:
        vessel_profile = asset_limit_profile(source_type_code, centerline_code, assets)
        edges.append(
            {
                "edge_code": edge_code,
                "from_node_code": from_node_code,
                "to_node_code": to_node_code,
                "channel_code": channel_code,
                "centerline_code": centerline_code,
                "geometry_json": mapping(line),
                "length_km": round(line_length_m(line) / 1000.0, 4),
                "direction_code": "BIDIRECTIONAL",
                "technical_grade_code": vessel_profile.get("technical_grade_code"),
                "min_depth_m": vessel_profile.get("min_depth_m"),
                "min_width_m": vessel_profile.get("min_width_m"),
                "max_allowed_draft_m": vessel_profile.get("max_allowed_draft_m"),
                "max_allowed_tonnage": vessel_profile.get("max_allowed_tonnage"),
                "max_air_draft_m": vessel_profile.get("max_air_draft_m"),
                "max_beam_m": vessel_profile.get("max_beam_m"),
                "max_length_m": vessel_profile.get("max_length_m"),
                "routing_enabled": routing_enabled,
                "quality_code": quality_code,
                "source_type_code": source_type_code,
                "confidence_score": confidence_score,
                "version_no": 1,
                "unknown_constraint_flag": bool(vessel_profile.get("unknown_constraint_flag")),
                "validation_summary_json": {
                    **(validation_summary_json or {}),
                    "vessel_limit_profile": vessel_profile,
                    "boundary_trust_code": _asset_boundary_trust(centerline_code, assets),
                },
            }
        )

    snaps_by_centerline: dict[str, list[TransportSnap]] = {}
    for snap in snaps:
        snaps_by_centerline.setdefault(snap.centerline_code, []).append(snap)

    for asset in assets:
        split_ratios = {0.0, 1.0}
        for snap in snaps_by_centerline.get(asset.centerline_code, []):
            split_ratios.add(round(snap.snap_ratio, 7))
        ordered = sorted(split_ratios)
        snap_node_by_ratio: dict[float, str] = {}
        for index, ratio in enumerate(ordered, start=1):
            point = asset.line.interpolate(ratio, normalized=True)
            node_code = f"{REVIER_GRAPH_VERSION_CODE}-N-{_clean_code(asset.centerline_code, 56)}-{index:04d}"
            snap_node_by_ratio[ratio] = node_code
            add_node(
                node_code,
                point=point,
                node_type_code="CENTERLINE_VERTEX" if ratio in {0.0, 1.0} else "SNAP_CONNECTOR",
                source_type_code="REVIER_WATER_AREA_CENTERLINE",
                channel_code=asset.channel_code,
                node_name=f"{asset.channel_name or asset.channel_code} {index}",
            )
        asset_endpoint_nodes.append(
            (
                asset,
                snap_node_by_ratio[0.0],
                asset.line.interpolate(0.0, normalized=True),
                snap_node_by_ratio[1.0],
                asset.line.interpolate(1.0, normalized=True),
            )
        )
        for index in range(len(ordered) - 1):
            start_ratio = ordered[index]
            end_ratio = ordered[index + 1]
            if end_ratio <= start_ratio:
                continue
            line = _subline(asset.line, start_ratio, end_ratio)
            if line is None:
                continue
            add_edge(
                f"{REVIER_GRAPH_VERSION_CODE}-E-{_clean_code(asset.centerline_code, 56)}-{index + 1:04d}",
                from_node_code=snap_node_by_ratio[start_ratio],
                to_node_code=snap_node_by_ratio[end_ratio],
                channel_code=asset.channel_code,
                centerline_code=asset.centerline_code,
                line=line,
                source_type_code="REVIER_WATER_AREA_CENTERLINE",
                confidence_score=asset.confidence_score,
                quality_code=asset.quality_code,
                validation_summary_json={
                    "issue_codes": asset.review_issue_codes,
                },
            )
        for snap in snaps_by_centerline.get(asset.centerline_code, []):
            ratio = round(snap.snap_ratio, 7)
            snap_node_code = snap_node_by_ratio[ratio]
            transport_code = f"{REVIER_GRAPH_VERSION_CODE}-TN-{_clean_code(snap.transport_node_code, 64)}"
            add_node(
                transport_code,
                point=snap.point,
                node_type_code="TERMINAL",
                source_type_code="TRANSPORT_NODE",
                channel_code=snap.channel_code,
                node_name=snap.transport_node_name,
                related_transport_node_code=snap.transport_node_code,
                snap_distance_m=snap.snap_distance_m,
                snap_confidence=95 if snap.snap_distance_m <= max_transport_snap_m else 70,
            )
            connector_line = LineString([_round_point(snap.point), _round_point(snap.snap_point)])
            if line_length_m(connector_line) <= 0:
                continue
            add_edge(
                f"{REVIER_GRAPH_VERSION_CODE}-C-{_clean_code(snap.transport_node_code, 64)}",
                from_node_code=transport_code,
                to_node_code=snap_node_code,
                channel_code=snap.channel_code,
                centerline_code=None,
                line=connector_line,
                source_type_code="TRANSPORT_NODE_CONNECTOR",
                confidence_score=95,
                quality_code="READY",
                validation_summary_json={
                    "snap_distance_m": round(snap.snap_distance_m, 3),
                    "issue_codes": [],
                },
            )

    _add_component_connector_edges(
        asset_endpoint_nodes=asset_endpoint_nodes,
        add_edge=add_edge,
        max_component_connector_m=max_component_connector_m,
    )

    bbox = _bbox_from_nodes(list(nodes.values()))
    component_summary = _component_summary(list(nodes), edges)
    report = {
        "transport_node_count": len(transport_nodes),
        "snapped_transport_node_count": len({snap.transport_node_code for snap in snaps}),
        "unsnapped_transport_node_count": max(len(transport_nodes) - len({snap.transport_node_code for snap in snaps}), 0),
        "graph_node_count": len(nodes),
        "graph_edge_count": len(edges),
        "disabled_edge_count": sum(1 for edge in edges if not edge.get("routing_enabled")),
        "component_connector_edge_count": sum(1 for edge in edges if edge.get("source_type_code") == "REVIER_WATER_COMPONENT_CONNECTOR"),
        "build_scope_bbox": bbox,
        **component_summary,
    }
    return list(nodes.values()), edges, report


def _add_component_connector_edges(
    *,
    asset_endpoint_nodes: list[tuple[CenterlineAsset, str, Point, str, Point]],
    add_edge: Any,
    max_component_connector_m: float,
    nearest_per_endpoint: int = 8,
) -> None:
    endpoint_rows_by_channel: dict[str, list[dict[str, Any]]] = {}
    for asset, start_code, start_point, end_code, end_point in asset_endpoint_nodes:
        endpoint_rows_by_channel.setdefault(asset.channel_code, []).append({"asset": asset, "node_code": start_code, "point": start_point})
        endpoint_rows_by_channel.setdefault(asset.channel_code, []).append({"asset": asset, "node_code": end_code, "point": end_point})

    emitted: set[tuple[str, str]] = set()
    connector_index = 0
    max_delta_degree = max_component_connector_m / 90_000.0
    parent: dict[str, str] = {}
    for endpoint_rows in endpoint_rows_by_channel.values():
        for row in endpoint_rows:
            parent.setdefault(row["asset"].centerline_code, row["asset"].centerline_code)

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    def emit_connector(channel_code: str, row: dict[str, Any], other: dict[str, Any], distance_m: float) -> bool:
        nonlocal connector_index
        edge_pair = tuple(sorted([row["node_code"], other["node_code"]]))
        if edge_pair in emitted:
            return False
        line = LineString([_round_point(row["point"]), _round_point(other["point"])])
        if line_length_m(line) <= 1.0 and distance_m > 1.0:
            return False
        emitted.add(edge_pair)
        connector_index += 1
        add_edge(
            f"{REVIER_GRAPH_VERSION_CODE}-X-{_clean_code(channel_code, 36)}-{connector_index:05d}",
            from_node_code=row["node_code"],
            to_node_code=other["node_code"],
            channel_code=channel_code,
            centerline_code=None,
            line=line,
            source_type_code="REVIER_WATER_COMPONENT_CONNECTOR",
            confidence_score=50,
            quality_code="NEED_REVIEW",
            validation_summary_json={
                "connector_distance_m": round(distance_m, 3),
                "issue_codes": [
                    "REVIER_COMPONENT_CONNECTOR_NEEDS_REVIEW",
                    "GUIDE_PASSTHROUGH_BOUNDARY_REVIEW",
                ],
            },
        )
        union(row["asset"].centerline_code, other["asset"].centerline_code)
        return True

    for channel_code, endpoint_rows in endpoint_rows_by_channel.items():
        for row in endpoint_rows:
            candidates: list[tuple[float, dict[str, Any]]] = []
            row_point = row["point"]
            for other in endpoint_rows:
                if row["node_code"] == other["node_code"]:
                    continue
                if row["asset"].centerline_code == other["asset"].centerline_code:
                    continue
                other_point = other["point"]
                if abs(float(row_point.x) - float(other_point.x)) > max_delta_degree:
                    continue
                if abs(float(row_point.y) - float(other_point.y)) > max_delta_degree:
                    continue
                distance_m = point_distance_m(row_point, other_point)
                if distance_m <= max_component_connector_m:
                    candidates.append((distance_m, other))
            candidates.sort(key=lambda item: item[0])
            for distance_m, other in candidates[:nearest_per_endpoint]:
                emit_connector(channel_code, row, other, distance_m)

        while True:
            best: tuple[float, dict[str, Any], dict[str, Any]] | None = None
            for left_index, row in enumerate(endpoint_rows):
                row_point = row["point"]
                row_component = find(row["asset"].centerline_code)
                for other in endpoint_rows[left_index + 1 :]:
                    if row["asset"].centerline_code == other["asset"].centerline_code:
                        continue
                    if row_component == find(other["asset"].centerline_code):
                        continue
                    other_point = other["point"]
                    if abs(float(row_point.x) - float(other_point.x)) > max_delta_degree:
                        continue
                    if abs(float(row_point.y) - float(other_point.y)) > max_delta_degree:
                        continue
                    distance_m = point_distance_m(row_point, other_point)
                    if distance_m <= max_component_connector_m and (best is None or distance_m < best[0]):
                        best = (distance_m, row, other)
            if best is None:
                break
            distance_m, row, other = best
            if not emit_connector(channel_code, row, other, distance_m):
                union(row["asset"].centerline_code, other["asset"].centerline_code)


def _subline(line: LineString, start_ratio: float, end_ratio: float) -> LineString | None:
    start = line.interpolate(start_ratio, normalized=True)
    end = line.interpolate(end_ratio, normalized=True)
    interior: list[tuple[float, float]] = []
    for coord in line.coords[1:-1]:
        point = Point(coord)
        ratio = line.project(point) / line.length if line.length > 0 else 0.0
        if start_ratio < ratio < end_ratio:
            interior.append((float(point.x), float(point.y)))
    coords = clean_line_coords([(float(start.x), float(start.y)), *interior, (float(end.x), float(end.y))])
    if len(coords) < 2:
        return None
    segment = LineString(coords)
    return segment if line_length_m(segment) > 1.0 else None


def _bbox_from_nodes(nodes: list[dict[str, Any]]) -> dict[str, float] | None:
    if not nodes:
        return None
    return {
        "min_lng": min(float(node["longitude"]) for node in nodes),
        "min_lat": min(float(node["latitude"]) for node in nodes),
        "max_lng": max(float(node["longitude"]) for node in nodes),
        "max_lat": max(float(node["latitude"]) for node in nodes),
    }


def build_revier_graph_seed(
    *,
    channel_records: list[dict[str, Any]],
    boundary_rows: list[dict[str, Any]],
    boundary_annotation_tasks: list[dict[str, Any]],
    transport_node_seed_path: Path,
    seed_dir: Path = DEFAULT_SEED_DIR,
    max_transport_snap_m: float = 3000.0,
) -> GraphSeedBuild:
    centerlines, segments, assets, centerline_tasks = build_centerline_seed_rows(
        channel_records=channel_records,
        boundary_rows=boundary_rows,
    )
    graph_nodes, graph_edges, graph_report = build_graph_seed_rows(
        assets=assets,
        transport_node_seed_path=transport_node_seed_path,
        max_transport_snap_m=max_transport_snap_m,
    )
    graph_version = {
        "version_code": REVIER_GRAPH_VERSION_CODE,
        "version_name": "revier 生产预制航道图 V1",
        "scope_code": REVIER_GRAPH_SCOPE_CODE,
        "source_summary_json": {
            "source": "revier.zip",
            "centerline_count": len(centerlines),
            "centerline_segment_count": len(segments),
            "transport_connector_policy": f"transport nodes within {max_transport_snap_m:.0f}m",
        },
        "node_count": len(graph_nodes),
        "edge_count": len(graph_edges),
        "channel_count": len({row["channel_code"] for row in centerlines}),
        "quality_score": 88 if graph_edges else 0,
        "status_code": "READY" if graph_edges else "FAILED",
        "is_active": bool(graph_edges),
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "build_scope_bbox_json": graph_report.get("build_scope_bbox"),
        "build_config_json": {
            "source": "navigation_revier_production_pipeline",
            "max_transport_snap_m": max_transport_snap_m,
            "graph_version_code": REVIER_GRAPH_VERSION_CODE,
        },
        "validation_report_json": {
            "status_code": "READY" if graph_edges else "FAILED",
            "quality_code": "READY_WITH_WARNING" if graph_edges else "FAILED",
            "build_report": graph_report,
            "boundary_integrity_summary": _boundary_integrity_summary(boundary_rows),
        },
    }
    all_tasks = [*boundary_annotation_tasks, *centerline_tasks]
    build = GraphSeedBuild(
        boundaries=boundary_rows,
        centerlines=centerlines,
        centerline_segments=segments,
        graph_versions=[graph_version],
        graph_nodes=graph_nodes,
        graph_edges=graph_edges,
        graph_edge_constraints=[],
        annotation_tasks=all_tasks,
        report={
            **graph_report,
            "boundary_integrity_summary": _boundary_integrity_summary(boundary_rows),
            "boundary_count": len(boundary_rows),
            "centerline_count": len(centerlines),
            "centerline_segment_count": len(segments),
            "annotation_task_count": len(all_tasks),
            "graph_version_code": REVIER_GRAPH_VERSION_CODE,
        },
    )
    _write_graph_seed_files(seed_dir, build)
    return build


def _boundary_integrity_summary(boundary_rows: list[dict[str, Any]]) -> dict[str, Any]:
    audits: list[dict[str, Any]] = []
    for row in boundary_rows:
        source_trace = row.get("source_trace_json") if isinstance(row.get("source_trace_json"), dict) else {}
        audit = source_trace.get("boundary_integrity_audit") if isinstance(source_trace, dict) else None
        if isinstance(audit, dict):
            audits.append(audit)
    return {
        "audited_boundary_count": len(audits),
        "ready_count": sum(1 for audit in audits if audit.get("trust_code") in {"READY", "READY_WITH_WARNING"}),
        "needs_review_count": sum(1 for audit in audits if audit.get("trust_code") == "NEEDS_REVIEW"),
        "failed_count": sum(1 for audit in audits if audit.get("trust_code") == "FAILED"),
        "fragmented_source_count": sum(1 for audit in audits if "SOURCE_GEOMETRY_FRAGMENTED" in (audit.get("issue_codes") or [])),
        "technical_grade_unknown_count": sum(
            1 for audit in audits if "NAVIGATION_TECHNICAL_GRADE_UNKNOWN" in (audit.get("issue_codes") or [])
        ),
        "basemap_not_verified_count": sum(
            1 for audit in audits if "BOUNDARY_NOT_INDEPENDENTLY_BASEMAP_VERIFIED" in (audit.get("issue_codes") or [])
        ),
    }


def _write_graph_seed_files(seed_dir: Path, build: GraphSeedBuild) -> None:
    files = {
        f"navigation_channel_boundaries.{REVIER_SEED_PREFIX}.json": build.boundaries,
        f"navigation_channel_centerlines.{REVIER_SEED_PREFIX}.json": build.centerlines,
        f"navigation_centerline_segments.{REVIER_SEED_PREFIX}.json": build.centerline_segments,
        f"navigation_graph_versions.{REVIER_SEED_PREFIX}.json": build.graph_versions,
        f"navigation_graph_nodes.{REVIER_SEED_PREFIX}.json": build.graph_nodes,
        f"navigation_graph_edges.{REVIER_SEED_PREFIX}.json": build.graph_edges,
        f"navigation_graph_edge_constraints.{REVIER_SEED_PREFIX}.json": build.graph_edge_constraints,
        f"navigation_annotation_tasks.{REVIER_SEED_PREFIX}.json": build.annotation_tasks,
    }
    for name, payload in files.items():
        write_json(seed_dir / name, payload)
