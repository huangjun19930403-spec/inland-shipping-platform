"""Cross-reference waybill route evidence with the route repair queue."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPAIR_QUEUE = PROJECT_ROOT / "runtime/navigation-production/reports/route_repair_queue_graph50_20260608.json"
DEFAULT_WAYBILL_ANALYSIS = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_route_reference_analysis_20260608.json"
DEFAULT_WAYBILL_JSONL = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_route_reference_candidates_20260608.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "runtime/navigation-production/reports/waybill_repair_queue_cross_reference_20260608.json"


@dataclass(slots=True)
class EndpointEvidence:
    node_code: str
    node_name: str | None = None
    reference_count: int = 0
    geometry_reference_count: int = 0
    condition_reference_count: int = 0
    water_systems: Counter[str] = field(default_factory=Counter)
    route_codes: Counter[str] = field(default_factory=Counter)
    counterpart_nodes: Counter[str] = field(default_factory=Counter)
    best_reference: dict[str, Any] | None = None


@dataclass(slots=True)
class OdEvidence:
    pair_key: str
    reference_count: int = 0
    geometry_reference_count: int = 0
    condition_reference_count: int = 0
    water_systems: Counter[str] = field(default_factory=Counter)
    route_codes: Counter[str] = field(default_factory=Counter)
    best_reference: dict[str, Any] | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Match route repair queue endpoints with real waybill route references.")
    parser.add_argument("--repair-queue", type=Path, default=DEFAULT_REPAIR_QUEUE)
    parser.add_argument("--waybill-analysis", type=Path, default=DEFAULT_WAYBILL_ANALYSIS)
    parser.add_argument("--waybill-jsonl", type=Path, default=DEFAULT_WAYBILL_JSONL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repair_queue = json.loads(args.repair_queue.read_text(encoding="utf-8"))
    waybill_analysis = json.loads(args.waybill_analysis.read_text(encoding="utf-8"))
    endpoint_evidence, od_evidence = _load_waybill_evidence(args.waybill_jsonl)
    endpoint_matches = _endpoint_matches(repair_queue, endpoint_evidence)
    pair_matches = _pair_matches(repair_queue, od_evidence)
    report = {
        "report_version": "WAYBILL_REPAIR_QUEUE_CROSS_REFERENCE_V1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_repair_queue": str(args.repair_queue),
        "source_waybill_analysis": str(args.waybill_analysis),
        "source_waybill_jsonl": str(args.waybill_jsonl),
        "summary": _summary(waybill_analysis, endpoint_matches, pair_matches),
        "endpoint_matches": endpoint_matches,
        "pair_matches": pair_matches,
        "seed_usage_queue": _seed_usage_queue(endpoint_matches, pair_matches),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"report_path={args.output}")


def _load_waybill_evidence(path: Path) -> tuple[dict[str, EndpointEvidence], dict[str, OdEvidence]]:
    endpoint_evidence: dict[str, EndpointEvidence] = {}
    od_evidence: dict[str, OdEvidence] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            origin = row.get("origin") or {}
            destination = row.get("destination") or {}
            origin_code = str(origin.get("code") or "").strip()
            destination_code = str(destination.get("code") or "").strip()
            if not origin_code or not destination_code:
                continue
            usable_geometry = (row.get("track_metrics") or {}).get("usable_as_geometry_reference") is True
            for node_code, node_name, counterpart in (
                (origin_code, origin.get("name"), destination_code),
                (destination_code, destination.get("name"), origin_code),
            ):
                endpoint = endpoint_evidence.get(node_code)
                if endpoint is None:
                    endpoint = EndpointEvidence(node_code=node_code, node_name=node_name)
                    endpoint_evidence[node_code] = endpoint
                _update_endpoint(endpoint, row, counterpart_code=counterpart, usable_geometry=usable_geometry)
            for pair_key in (_pair_key(origin_code, destination_code), _pair_key(destination_code, origin_code)):
                od = od_evidence.get(pair_key)
                if od is None:
                    od = OdEvidence(pair_key=pair_key)
                    od_evidence[pair_key] = od
                _update_od(od, row, usable_geometry=usable_geometry)
    return endpoint_evidence, od_evidence


def _update_endpoint(endpoint: EndpointEvidence, row: dict[str, Any], *, counterpart_code: str, usable_geometry: bool) -> None:
    endpoint.reference_count += 1
    endpoint.condition_reference_count += 1
    if usable_geometry:
        endpoint.geometry_reference_count += 1
    endpoint.water_systems.update(row.get("water_systems") or [])
    endpoint.route_codes.update([str(row.get("route_code") or "-")])
    endpoint.counterpart_nodes.update([counterpart_code])
    if endpoint.best_reference is None or _reference_score(row) > _reference_score(endpoint.best_reference):
        endpoint.best_reference = _compact_reference(row)


def _update_od(od: OdEvidence, row: dict[str, Any], *, usable_geometry: bool) -> None:
    od.reference_count += 1
    od.condition_reference_count += 1
    if usable_geometry:
        od.geometry_reference_count += 1
    od.water_systems.update(row.get("water_systems") or [])
    od.route_codes.update([str(row.get("route_code") or "-")])
    if od.best_reference is None or _reference_score(row) > _reference_score(od.best_reference):
        od.best_reference = _compact_reference(row)


def _endpoint_matches(repair_queue: dict[str, Any], endpoint_evidence: dict[str, EndpointEvidence]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in repair_queue.get("endpoint_repair_queue") or []:
        endpoint = item.get("endpoint") or {}
        code = str(endpoint.get("code") or "").strip()
        evidence = endpoint_evidence.get(code)
        if evidence is None:
            output.append(
                {
                    "endpoint": endpoint,
                    "repair_action_code": item.get("repair_action_code"),
                    "reason_code": item.get("reason_code"),
                    "has_waybill_evidence": False,
                    "recommended_seed_use_code": "NO_WAYBILL_REFERENCE_FOR_ENDPOINT",
                }
            )
            continue
        output.append(
            {
                "endpoint": endpoint,
                "repair_action_code": item.get("repair_action_code"),
                "reason_code": item.get("reason_code"),
                "nearest_graph": item.get("nearest_graph"),
                "nearest_water_body": item.get("nearest_water_body"),
                "nearest_water_area": item.get("nearest_water_area"),
                "has_waybill_evidence": True,
                "reference_count": evidence.reference_count,
                "geometry_reference_count": evidence.geometry_reference_count,
                "condition_reference_count": evidence.condition_reference_count,
                "top_water_systems": evidence.water_systems.most_common(10),
                "top_route_codes": evidence.route_codes.most_common(10),
                "top_counterpart_nodes": evidence.counterpart_nodes.most_common(10),
                "best_reference": evidence.best_reference,
                "recommended_seed_use_code": _endpoint_usage_code(item, evidence),
            }
        )
    return sorted(output, key=_match_sort_key)


def _pair_matches(repair_queue: dict[str, Any], od_evidence: dict[str, OdEvidence]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in repair_queue.get("pair_repair_actions") or []:
        origin_code = _code_from_pair_endpoint(item, "origin")
        destination_code = _code_from_pair_endpoint(item, "destination")
        pair_key = _pair_key(origin_code, destination_code)
        evidence = od_evidence.get(pair_key)
        output.append(
            {
                "origin_id": item.get("origin_id"),
                "origin_name": item.get("origin_name"),
                "destination_id": item.get("destination_id"),
                "destination_name": item.get("destination_name"),
                "repair_action_code": item.get("repair_action_code"),
                "route_status_code": item.get("route_status_code"),
                "route_quality_code": item.get("route_quality_code"),
                "issue_codes": item.get("issue_codes") or [],
                "has_waybill_od_evidence": evidence is not None,
                "reference_count": evidence.reference_count if evidence else 0,
                "geometry_reference_count": evidence.geometry_reference_count if evidence else 0,
                "condition_reference_count": evidence.condition_reference_count if evidence else 0,
                "top_water_systems": evidence.water_systems.most_common(10) if evidence else [],
                "top_route_codes": evidence.route_codes.most_common(10) if evidence else [],
                "best_reference": evidence.best_reference if evidence else None,
                "recommended_seed_use_code": _pair_usage_code(item, evidence),
            }
        )
    return sorted(output, key=_match_sort_key)


def _code_from_pair_endpoint(item: dict[str, Any], role: str) -> str:
    ref = next((pair for pair in (item.get("pair_refs") or []) if isinstance(pair, dict)), {})
    key = f"{role}_code"
    if item.get(key):
        return str(item[key])
    if ref.get(key):
        return str(ref[key])
    return ""


def _summary(
    waybill_analysis: dict[str, Any],
    endpoint_matches: list[dict[str, Any]],
    pair_matches: list[dict[str, Any]],
) -> dict[str, Any]:
    endpoint_usage = Counter(item.get("recommended_seed_use_code") for item in endpoint_matches)
    pair_usage = Counter(item.get("recommended_seed_use_code") for item in pair_matches)
    return {
        "waybill_row_count": (waybill_analysis.get("summary") or {}).get("row_count"),
        "waybill_geometry_reference_count": (waybill_analysis.get("summary") or {}).get("geometry_reference_count"),
        "repair_endpoint_count": len(endpoint_matches),
        "repair_endpoint_with_waybill_evidence_count": sum(1 for item in endpoint_matches if item.get("has_waybill_evidence")),
        "repair_endpoint_with_geometry_evidence_count": sum(1 for item in endpoint_matches if int(item.get("geometry_reference_count") or 0) > 0),
        "repair_pair_count": len(pair_matches),
        "repair_pair_with_waybill_od_evidence_count": sum(1 for item in pair_matches if item.get("has_waybill_od_evidence")),
        "repair_pair_with_geometry_evidence_count": sum(1 for item in pair_matches if int(item.get("geometry_reference_count") or 0) > 0),
        "endpoint_usage_counts": dict(sorted(endpoint_usage.items())),
        "pair_usage_counts": dict(sorted(pair_usage.items())),
    }


def _seed_usage_queue(endpoint_matches: list[dict[str, Any]], pair_matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    queue: list[dict[str, Any]] = []
    for item in endpoint_matches:
        code = item.get("recommended_seed_use_code")
        if code in {"WAYBILL_ACCESS_SEED_PRIORITY", "WAYBILL_CONNECTIVITY_REPAIR_PRIORITY"}:
            queue.append(
                {
                    "target_type_code": "ENDPOINT",
                    "target_code": (item.get("endpoint") or {}).get("code"),
                    "target_name": (item.get("endpoint") or {}).get("name"),
                    "seed_use_code": code,
                    "geometry_reference_count": item.get("geometry_reference_count"),
                    "top_water_systems": item.get("top_water_systems"),
                    "best_reference": item.get("best_reference"),
                }
            )
    for item in pair_matches:
        code = item.get("recommended_seed_use_code")
        if code == "WAYBILL_OD_CENTERLINE_PRIORITY":
            best = item.get("best_reference") or {}
            queue.append(
                {
                    "target_type_code": "OD_PAIR",
                    "target_code": f"{(best.get('origin') or {}).get('code')}->{(best.get('destination') or {}).get('code')}",
                    "target_name": f"{item.get('origin_name')} -> {item.get('destination_name')}",
                    "seed_use_code": code,
                    "geometry_reference_count": item.get("geometry_reference_count"),
                    "top_water_systems": item.get("top_water_systems"),
                    "best_reference": best,
                }
            )
    return sorted(queue, key=lambda item: int(item.get("geometry_reference_count") or 0), reverse=True)


def _endpoint_usage_code(item: dict[str, Any], evidence: EndpointEvidence) -> str:
    action = str(item.get("repair_action_code") or "")
    if evidence.geometry_reference_count <= 0:
        return "WAYBILL_CONDITION_ONLY"
    if action in {"AUTO_ACCESS_SEED_CANDIDATE", "AUTO_BRANCH_CENTERLINE_AND_BOUNDARY_SEED_CANDIDATE"}:
        return "WAYBILL_ACCESS_SEED_PRIORITY"
    if action == "GRAPH_CONNECTIVITY_REPAIR_CANDIDATE":
        return "WAYBILL_CONNECTIVITY_REPAIR_PRIORITY"
    return "WAYBILL_REFERENCE_AVAILABLE"


def _pair_usage_code(item: dict[str, Any], evidence: OdEvidence | None) -> str:
    if evidence is None:
        return "NO_WAYBILL_OD_REFERENCE"
    if evidence.geometry_reference_count <= 0:
        return "WAYBILL_OD_CONDITION_ONLY"
    if item.get("repair_action_code") in {"ENDPOINT_ACCESS_SEED_REPAIR", "GRAPH_CONNECTIVITY_REPAIR"}:
        return "WAYBILL_OD_CENTERLINE_PRIORITY"
    return "WAYBILL_OD_REFERENCE_AVAILABLE"


def _compact_reference(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "waybill_code": row.get("waybill_code"),
        "route_code": row.get("route_code"),
        "route_name": row.get("route_name"),
        "origin": row.get("origin"),
        "destination": row.get("destination"),
        "water_systems": row.get("water_systems") or [],
        "quality_code": row.get("quality_code"),
        "quality_score": row.get("quality_score"),
        "track_metrics": row.get("track_metrics"),
    }


def _reference_score(row: dict[str, Any]) -> int:
    return int(row.get("quality_score") or (row.get("track_metrics") or {}).get("quality_score") or 0)


def _pair_key(origin_code: str, destination_code: str) -> str:
    return f"{origin_code}|{destination_code}"


def _match_sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
    priority = {
        "WAYBILL_ACCESS_SEED_PRIORITY": 0,
        "WAYBILL_CONNECTIVITY_REPAIR_PRIORITY": 1,
        "WAYBILL_OD_CENTERLINE_PRIORITY": 2,
        "WAYBILL_REFERENCE_AVAILABLE": 3,
        "WAYBILL_OD_REFERENCE_AVAILABLE": 3,
        "WAYBILL_CONDITION_ONLY": 4,
        "WAYBILL_OD_CONDITION_ONLY": 4,
    }.get(str(item.get("recommended_seed_use_code") or ""), 9)
    return priority, -int(item.get("geometry_reference_count") or 0), str((item.get("endpoint") or {}).get("code") or "")


if __name__ == "__main__":
    main()
