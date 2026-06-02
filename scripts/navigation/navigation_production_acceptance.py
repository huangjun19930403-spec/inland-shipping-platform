from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models import (
    NavigationCenterlineSegment,
    NavigationChannelCenterline,
    NavigationGraphEdge,
    NavigationGraphNode,
    NavigationGraphVersion,
    NavigationWaterArea,
    NavigationWaterBody,
)
from app.models.address import NavigationChannelBoundary
from app.modules.navigation.production_pipeline.constants import DEFAULT_RUNTIME_DIR, REVIER_GRAPH_VERSION_CODE, REVIER_SOURCE_CODE

DEFAULT_REPORT_PATH = DEFAULT_RUNTIME_DIR / "reports" / "navigation_production_acceptance_report.json"
DEFAULT_ROUTING_REPORT_PATH = DEFAULT_RUNTIME_DIR / "reports" / "transport_node_routing_validation_report.json"


async def navigation_production_acceptance(
    *,
    graph_version_code: str = REVIER_GRAPH_VERSION_CODE,
    report_path: Path = DEFAULT_REPORT_PATH,
    routing_report_path: Path = DEFAULT_ROUTING_REPORT_PATH,
) -> dict[str, Any]:
    routing_report = _read_json(routing_report_path)
    async with AsyncSessionLocal() as session:
        graph_version = await session.scalar(
            select(NavigationGraphVersion).where(NavigationGraphVersion.version_code == graph_version_code)
        )
        counts = {
            "navigation_water_area": int(
                await session.scalar(
                    select(func.count()).select_from(NavigationWaterArea).where(NavigationWaterArea.source_code == REVIER_SOURCE_CODE)
                )
                or 0
            ),
            "navigation_water_body": int(await session.scalar(select(func.count()).select_from(NavigationWaterBody)) or 0),
            "navigation_channel_boundary": int(await session.scalar(select(func.count()).select_from(NavigationChannelBoundary)) or 0),
            "navigation_channel_centerline": int(
                await session.scalar(select(func.count()).select_from(NavigationChannelCenterline).where(NavigationChannelCenterline.centerline_code.like("REVCL-%")))
                or 0
            ),
            "navigation_centerline_segment": int(
                await session.scalar(select(func.count()).select_from(NavigationCenterlineSegment).where(NavigationCenterlineSegment.segment_no.like("REVSEG-%")))
                or 0
            ),
            "navigation_graph_node": int(
                await session.scalar(select(func.count()).select_from(NavigationGraphNode).where(NavigationGraphNode.graph_version_id == graph_version.id))
                or 0
            ) if graph_version else 0,
            "navigation_graph_edge": int(
                await session.scalar(select(func.count()).select_from(NavigationGraphEdge).where(NavigationGraphEdge.graph_version_id == graph_version.id))
                or 0
            ) if graph_version else 0,
        }
    gates = {
        "graph_version_exists": graph_version is not None,
        "graph_version_code": graph_version.version_code if graph_version else None,
        "graph_status_ready": bool(graph_version and graph_version.status_code == "READY"),
        "graph_active": bool(graph_version and graph_version.is_active),
        "water_area_count_gt_zero": counts["navigation_water_area"] > 0,
        "water_body_count_gt_zero": counts["navigation_water_body"] > 0,
        "boundary_count_gt_zero": counts["navigation_channel_boundary"] > 0,
        "centerline_count_gt_zero": counts["navigation_channel_centerline"] > 0,
        "centerline_segment_count_gt_zero": counts["navigation_centerline_segment"] > 0,
        "graph_node_count_gt_zero": counts["navigation_graph_node"] > 0,
        "graph_edge_count_gt_zero": counts["navigation_graph_edge"] > 0,
        "transport_routing_success_ge_5": int(routing_report.get("route_validation_success") or 0) >= 5,
        "no_straight_line_fallback": bool((routing_report.get("quality_gates") or {}).get("straight_line_fallback_allowed") is False),
        "hifleet_gate_passed": bool((routing_report.get("quality_gates") or {}).get("hifleet_gate_passed", True)),
    }
    blocking_issues = [key for key, passed in gates.items() if not passed and key not in {"graph_version_code"}]
    report = {
        "report_version": "REVIER_NAVIGATION_PRODUCTION_ACCEPTANCE_V1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "graph_version_code": graph_version_code,
        "counts": counts,
        "gates": gates,
        "routing_report_path": str(routing_report_path),
        "route_validation_success": routing_report.get("route_validation_success"),
        "route_validation_failed": routing_report.get("route_validation_failed"),
        "hifleet_benchmark": routing_report.get("hifleet_benchmark"),
        "production_seed_allowed": not blocking_issues,
        "blocking_issues": blocking_issues,
        "current_limitations": [
            "基于水系边界和运输节点生成的生产预制候选航道图，不等同于官方通航安全图。",
            "关键航段仍需结合人工审核、闸口、桥梁、航道等级、船型限制和 AIS/HiFleet 参考轨迹增强。",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run final revier navigation production acceptance gates.")
    parser.add_argument("--graph-version-code", default=REVIER_GRAPH_VERSION_CODE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--routing-report", type=Path, default=DEFAULT_ROUTING_REPORT_PATH)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report = asyncio.run(
        navigation_production_acceptance(
            graph_version_code=args.graph_version_code,
            report_path=args.report,
            routing_report_path=args.routing_report,
        )
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report.get("production_seed_allowed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
