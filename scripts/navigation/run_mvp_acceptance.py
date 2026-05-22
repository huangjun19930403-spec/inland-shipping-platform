"""Run Round 12 MVP navigation route acceptance.

The runner calls NavigationRoutingEngineService against a READY MVP graph
version and records concrete distance ranges, channel coverage, quality issues,
and unacceptable-result checks. It never creates fallback water routes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import NavigationGraphVersion, NavigationRouteResult
from app.models.address import NavigationChannel
from app.modules.navigation.routing_service import NavigationRoutingEngineService
from app.modules.navigation.schemas import NavigationEndpointRequest, NavigationRouteGenerateRequest
from scripts.navigation.seed_mvp_navigation_data import DEFAULT_DATA_PATH


@dataclass(slots=True)
class MvpAcceptanceCaseReport:
    route_code: str
    route_name: str
    origin_transport_node_id: int
    destination_transport_node_id: int
    status_code: str
    quality_code: str
    quality_score: int | None
    distance_km: float | None
    calibrated_distance_min_km: float | None
    calibrated_distance_max_km: float | None
    graph_version_id: int | None
    result_id: int | None
    provider_code: str | None
    edge_ids: list[int]
    channel_ids: list[int]
    channel_codes: list[str]
    expected_channel_codes: list[str]
    issue_types: list[str]
    expected_issue_types: list[str]
    passed: bool
    failure_reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MvpAcceptanceReport:
    graph_version_code: str
    graph_version_id: int | None
    generated_at: str
    passed_count: int
    failed_count: int
    cases: list[MvpAcceptanceCaseReport]
    notes: list[str]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["cases"] = [case.as_dict() for case in self.cases]
        return payload


def _load_data(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


async def _channel_id_to_code(session: AsyncSession) -> dict[int, str]:
    rows = list((await session.execute(select(NavigationChannel))).scalars())
    return {row.id: row.channel_code for row in rows}


def _distance_range(distance_km: float | None) -> tuple[float | None, float | None]:
    if distance_km is None:
        return None, None
    return round(distance_km * 0.85, 1), round(distance_km * 1.15, 1)


def _evaluate_case(
    *,
    route_config: dict[str, Any],
    graph_version_id: int,
    provider_code: str | None,
    response: Any,
    channel_codes: list[str],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if response.status_code != "SUCCESS":
        reasons.append(f"status_code={response.status_code}")
    if response.graph_version_id != graph_version_id:
        reasons.append("MISSING_GRAPH_VERSION")
    if not response.edge_ids:
        reasons.append("MISSING_EDGE_IDS")
    if not response.channel_ids:
        reasons.append("MISSING_CHANNEL_IDS")
    if response.geometry_json is None:
        reasons.append("MISSING_GEOMETRY")
    elif len(response.geometry_json.get("coordinates") or []) < 3:
        reasons.append("DIRECT_LINE_FALLBACK")
    if provider_code != "NAVIGATION_ENGINE":
        reasons.append(f"UNEXPECTED_PROVIDER={provider_code}")
    if response.quality_code == "READY":
        reasons.append("UNKNOWN_CONSTRAINT_ROUTE_MARKED_READY")
    if response.quality_code not in {"READY_WITH_WARNING", "NEED_REVIEW"}:
        reasons.append(f"UNEXPECTED_QUALITY={response.quality_code}")

    expected_channels = set(route_config.get("expected_channel_codes", []))
    missing_channels = sorted(expected_channels - set(channel_codes))
    if missing_channels:
        reasons.append(f"MISSING_EXPECTED_CHANNELS={','.join(missing_channels)}")

    issue_types = {issue.issue_type_code for issue in response.issues}
    missing_issues = sorted(set(route_config.get("expected_issue_types", [])) - issue_types)
    if missing_issues:
        reasons.append(f"MISSING_EXPECTED_ISSUES={','.join(missing_issues)}")

    unacceptable = set(route_config.get("unacceptable_results", []))
    if "FAILED" in unacceptable and response.status_code == "FAILED":
        reasons.append("UNACCEPTABLE_FAILED")
    if "DIRECT_LINE_FALLBACK" in unacceptable and "DIRECT_LINE_FALLBACK" in reasons:
        reasons.append("UNACCEPTABLE_DIRECT_LINE_FALLBACK")
    return not reasons, reasons


async def run_mvp_acceptance(
    *,
    session: AsyncSession,
    data_path: Path = DEFAULT_DATA_PATH,
    graph_version_code: str = "MVP-JS-YRD-20260522-V1",
    vessel_profile_json: dict[str, Any] | None = None,
) -> MvpAcceptanceReport:
    data = _load_data(data_path)
    graph_version = await session.scalar(
        select(NavigationGraphVersion).where(
            NavigationGraphVersion.version_code == graph_version_code,
            NavigationGraphVersion.status_code == "READY",
        )
    )
    if graph_version is None:
        raise ValueError(f"READY graph version not found: {graph_version_code}")

    id_to_code = await _channel_id_to_code(session)
    service = NavigationRoutingEngineService(session)
    case_reports: list[MvpAcceptanceCaseReport] = []
    for route_config in data.get("acceptance_routes", []):
        body = NavigationRouteGenerateRequest(
            origin=NavigationEndpointRequest(
                endpoint_type_code="TRANSPORT_NODE",
                transport_node_id=int(route_config["origin_transport_node_id"]),
            ),
            destination=NavigationEndpointRequest(
                endpoint_type_code="TRANSPORT_NODE",
                transport_node_id=int(route_config["destination_transport_node_id"]),
            ),
            vessel_profile_json=vessel_profile_json
            or {
                "draft_m": 2.0,
                "deadweight_ton": 1000,
                "beam_m": 12,
                "length_m": 65,
                "loaded_status": "MVP_ACCEPTANCE",
            },
            routing_preference_code="RECOMMENDED",
            graph_version_id=graph_version.id,
        )
        response = await service.generate_route(body)
        result_row = await session.scalar(select(NavigationRouteResult).where(NavigationRouteResult.id == response.result_id))
        provider_code = result_row.provider_code if result_row else None
        channel_codes = [id_to_code[channel_id] for channel_id in response.channel_ids if channel_id in id_to_code]
        passed, reasons = _evaluate_case(
            route_config=route_config,
            graph_version_id=graph_version.id,
            provider_code=provider_code,
            response=response,
            channel_codes=channel_codes,
        )
        distance_min, distance_max = _distance_range(response.distance_km)
        case_reports.append(
            MvpAcceptanceCaseReport(
                route_code=route_config["route_code"],
                route_name=route_config["route_name"],
                origin_transport_node_id=int(route_config["origin_transport_node_id"]),
                destination_transport_node_id=int(route_config["destination_transport_node_id"]),
                status_code=response.status_code,
                quality_code=response.quality_code,
                quality_score=response.quality_score,
                distance_km=response.distance_km,
                calibrated_distance_min_km=distance_min,
                calibrated_distance_max_km=distance_max,
                graph_version_id=response.graph_version_id,
                result_id=response.result_id,
                provider_code=provider_code,
                edge_ids=response.edge_ids,
                channel_ids=response.channel_ids,
                channel_codes=channel_codes,
                expected_channel_codes=list(route_config.get("expected_channel_codes", [])),
                issue_types=sorted({issue.issue_type_code for issue in response.issues}),
                expected_issue_types=list(route_config.get("expected_issue_types", [])),
                passed=passed,
                failure_reasons=reasons,
            )
        )

    passed_count = sum(1 for case in case_reports if case.passed)
    failed_count = len(case_reports) - passed_count
    return MvpAcceptanceReport(
        graph_version_code=graph_version_code,
        graph_version_id=graph_version.id,
        generated_at=datetime.now(UTC).isoformat(),
        passed_count=passed_count,
        failed_count=failed_count,
        cases=case_reports,
        notes=[
            "READY_WITH_WARNING is expected because MVP graph edges intentionally carry UNKNOWN_CONSTRAINT_DATA.",
            "Distance ranges are calibrated from the controlled MVP graph fixture and must be reviewed against the map before production use.",
            "This report proves graph-based business routing only; it is not an official navigation safety confirmation.",
        ],
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Jiangsu/Yangtze Delta MVP navigation route acceptance.")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--graph-version-code", default="MVP-JS-YRD-20260522-V1")
    parser.add_argument("--output", type=Path, default=Path("data_audit/navigation_mvp_acceptance_report.json"))
    parser.add_argument("--no-strict", action="store_true", help="Do not exit non-zero when acceptance cases fail.")
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()
    async with AsyncSessionLocal() as session:
        report = await run_mvp_acceptance(
            session=session,
            data_path=args.data,
            graph_version_code=args.graph_version_code,
        )
    payload = report.as_dict()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if args.no_strict or report.failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
