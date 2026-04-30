"""第 7 轮本地验收只读检查。"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal, engine
from app.models.address import NavigationConstraintPoint, NodeAlias, Region, TransportNode
from app.models.analysis import (
    AnalysisJobRun,
    FactFreightDaily,
    FactFreightFlowDaily,
    FactShipFlowDaily,
)
from app.models.audit import AuditRecord, AuditTask, AuditTaskSnapshot
from app.models.commodity import CommodityAlias, CommodityStandard
from app.models.freight import Freight, FreightAiParseTask, FreightCandidate, FreightSourceInbound
from app.models.route import ShippingRoute
from app.models.ship import ShipProfile
from app.models.system import SysMenu
from main import app


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


LEGACY_TABLES = {
    "ship_import_batch",
    "ship_import_raw",
    "ship_import_record",
    "stat_cargo_daily",
    "stat_cargo_city_daily",
    "stat_cargo_flow_daily",
    "stat_cargo_commodity_daily",
    "cargo_channel_daily",
    "stat_ship_city_daily",
    "stat_ship_flow_daily",
    "stat_job_run",
}

LEGACY_ROUTE_PATHS = {
    "/api/v1/ship/import/batches",
    "/api/v1/ship/import/batches/{batch_id}",
    "/api/v1/ship/import/batches/{batch_id}/raw-records",
    "/api/v1/ship/import/batches/{batch_id}/records",
    "/api/v1/analysis/cargo/daily",
    "/api/v1/analysis/cargo/cities",
    "/api/v1/analysis/cargo/flows",
    "/api/v1/analysis/cargo/commodities",
    "/api/v1/analysis/cargo/channels",
    "/api/v1/analysis/ships/cities",
    "/api/v1/analysis/ships/flows",
    "/api/v1/commodity/categories",
    "/api/v1/commodity/categories/{category_id}",
    "/api/v1/commodity/types",
    "/api/v1/commodity/types/{type_id}",
}

LEGACY_MENU_CODES = {
    "COMMODITY_ROOT",
    "COMMODITY_CATEGORIES",
    "COMMODITY_TYPES",
    "SHIP_IMPORT_BATCHES",
    "ROUTE_PLANS",
    "ANALYSIS_CARGO",
}

LEGACY_MENU_PATHS = {
    "/commodity/categories",
    "/commodity/types",
    "/ship/import/batches",
    "/route/plans",
    "/analysis/cargo",
}


async def _table_names() -> set[str]:
    async with engine.begin() as conn:
        return await conn.run_sync(lambda sync_conn: set(sa.inspect(sync_conn).get_table_names()))


async def _count(session, model, *conditions) -> int:
    stmt = select(func.count()).select_from(model)
    if conditions:
        stmt = stmt.where(*conditions)
    return int(await session.scalar(stmt) or 0)


def _result(name: str, ok: bool, detail: str) -> CheckResult:
    return CheckResult(name=name, ok=ok, detail=detail)


async def verify() -> list[CheckResult]:
    results: list[CheckResult] = []

    tables = await _table_names()
    legacy_tables_left = sorted(tables & LEGACY_TABLES)
    results.append(
        _result(
            "legacy tables removed",
            not legacy_tables_left,
            "none" if not legacy_tables_left else ", ".join(legacy_tables_left),
        )
    )

    route_paths = {getattr(route, "path", "") for route in app.routes}
    legacy_routes_left = sorted(path for path in LEGACY_ROUTE_PATHS if path in route_paths)
    results.append(
        _result(
            "legacy api routes removed",
            not legacy_routes_left,
            "none" if not legacy_routes_left else ", ".join(legacy_routes_left),
        )
    )

    async with AsyncSessionLocal() as session:
        count_checks = [
            ("business regions", await _count(session, Region, Region.code.not_like("E2E%")), 8),
            ("transport nodes", await _count(session, TransportNode, TransportNode.code.not_like("E2E%")), 30),
            ("node aliases", await _count(session, NodeAlias), 60),
            ("commodity standards", await _count(session, CommodityStandard), 30),
            ("commodity aliases", await _count(session, CommodityAlias), 80),
            ("ships", await _count(session, ShipProfile), 80),
            ("freights", await _count(session, Freight), 200),
            ("source inbounds", await _count(session, FreightSourceInbound), 30),
            ("ai parse tasks", await _count(session, FreightAiParseTask), 20),
            ("freight candidates", await _count(session, FreightCandidate), 40),
            ("freight daily facts", await _count(session, FactFreightDaily), 90),
            ("freight flow facts", await _count(session, FactFreightFlowDaily), 600),
            ("ship flow facts", await _count(session, FactShipFlowDaily), 300),
            ("analysis jobs", await _count(session, AnalysisJobRun), 15),
            ("audit tasks", await _count(session, AuditTask), 30),
            ("audit snapshots", await _count(session, AuditTaskSnapshot), 30),
            ("audit records", await _count(session, AuditRecord), 30),
            ("navigation constraints", await _count(session, NavigationConstraintPoint), 3),
            ("shipping routes", await _count(session, ShippingRoute), 1),
        ]
        for name, actual, expected in count_checks:
            results.append(_result(name, actual >= expected, f"{actual} >= {expected}"))

        e2e_counts = {
            "regions": await _count(session, Region, Region.code.like("E2E%") | Region.name.like("%E2E%")),
            "nodes": await _count(session, TransportNode, TransportNode.code.like("E2E%") | TransportNode.name.like("%E2E%")),
            "constraints": await _count(
                session,
                NavigationConstraintPoint,
                NavigationConstraintPoint.code.like("E2E%") | NavigationConstraintPoint.name.like("%E2E%"),
            ),
            "routes": await _count(session, ShippingRoute, ShippingRoute.code.like("E2E%") | ShippingRoute.name.like("%E2E%")),
        }
        e2e_left = {key: value for key, value in e2e_counts.items() if value}
        results.append(_result("legacy e2e data purged", not e2e_left, str(e2e_left or "none")))

        menu_left = (
            (
                await session.execute(
                    select(SysMenu.menu_code, SysMenu.route_path).where(
                        (SysMenu.menu_code.in_(LEGACY_MENU_CODES))
                        | (SysMenu.route_path.in_(LEGACY_MENU_PATHS))
                    )
                )
            )
            .all()
        )
        results.append(_result("legacy menu entries removed", not menu_left, str(menu_left or "none")))

    return results


def main() -> None:
    results = asyncio.run(verify())
    failed = [item for item in results if not item.ok]
    for item in results:
        status = "OK" if item.ok else "FAIL"
        print(f"[{status}] {item.name}: {item.detail}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
