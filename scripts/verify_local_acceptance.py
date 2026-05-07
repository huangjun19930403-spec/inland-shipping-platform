"""第 7 轮本地验收只读检查。"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal, engine
from app.integrations.config_keys import (
    AMAP_JS_API_KEY,
    AMAP_ROUTE_WEB_API_KEY,
    AMAP_SECURITY_JS_CODE,
    COS_ACCESS_KEY,
    COS_BUCKET_NAME,
    COS_ENABLED,
    COS_ENDPOINT,
    COS_IMAGE_MAX_SIZE_MB,
    COS_PATH_STYLE_ACCESS,
    COS_REGION,
    COS_SECRET_KEY,
    DASHSCOPE_API_KEY,
    HIFLEET_ENABLED,
    HIFLEET_PASSWORD,
    HIFLEET_USERNAME,
)
from app.models.address import NavigationConstraintPoint, NodeAlias, Region, TransportNode, TransportNodeContact
from app.models.analysis import (
    AnalysisJobDefinition,
    AnalysisJobRun,
    FactFreightCityDaily,
    FactFreightDaily,
    FactFreightFlowDaily,
    FactFreightNodeDaily,
    FactShipCityDaily,
    FactShipFlowDaily,
)
from app.models.audit import AuditRecord, AuditTask, AuditTaskSnapshot
from app.models.commodity import CommodityAlias, CommodityStandard
from app.models.freight import Freight, FreightBatchTask, FreightCandidate, FreightNormalizationSuggestion, FreightNormalizationTask, FreightTmsInbound
from app.models.route import ShippingRoute, ShippingRouteLine, ShippingRouteLineSegment, ShippingRouteLineTrack
from app.models.ship import ShipProfile
from app.models.system import SysMenu, SystemConfig
from app.modules.analysis.service import AnalysisDashboardService
from scripts.seed_local_private_config import (
    CONFIG_METADATA_BY_KEY,
    LOCAL_PRIVATE_CONFIG_KEYS,
    _merged_local_values,
    _normalize_config_value,
)
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
    "freight_source_inbound",
    "freight_ai_parse_task",
    "freight_candidate_feedback",
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
    "/api/v1/freight/source-inbounds",
    "/api/v1/freight/source-inbounds/{id}",
    "/api/v1/freight/ai/parse-tasks",
    "/api/v1/freight/ai/parse-tasks/{id}",
    "/api/v1/freight/ai/parse-tasks/{id}/run",
}

REQUIRED_ROUTE_PATHS = {
    "/api/v1/freight/manual",
    "/api/v1/freight/batches/wechat",
    "/api/v1/freight/batches/{batch_id}/parse",
    "/api/v1/freight/batches/{batch_id}/candidates/bulk-confirm",
    "/api/v1/freight/batches/{batch_id}/handoff-review",
    "/api/v1/freight/tms-inbounds",
    "/api/v1/freight/tms-inbounds/{inbound_id}/parse",
    "/api/v1/freight/candidates/{candidate_id}/confirm",
    "/api/v1/freight/candidates/{candidate_id}/reject",
    "/api/v1/freight/normalization-suggestions",
    "/api/v1/freight/normalization-suggestions/bulk-apply",
    "/api/v1/freight/normalization-suggestions/{suggestion_id}/apply",
    "/api/v1/freight/normalization-suggestions/{suggestion_id}/reject",
    "/api/v1/freight/normalization/clean",
    "/api/v1/freight/normalization/quality",
    "/api/v1/freight/normalization/tasks",
    "/api/v1/freight/normalization/tasks/{task_id}",
    "/api/v1/analysis/freight/node-ranking",
    "/api/v1/address/nodes/{node_id}/contacts",
    "/api/v1/address/nodes/{node_id}/photos",
    "/api/v1/files/{file_id}/content",
}

LEGACY_MENU_CODES = {
    "COMMODITY_ROOT",
    "COMMODITY_CATEGORIES",
    "COMMODITY_TYPES",
    "SHIP_IMPORT_BATCHES",
    "ROUTE_PLANS",
    "ANALYSIS_CARGO",
    "FREIGHT_AI_PARSE_RECORDS",
    "FREIGHT_SOURCE_INBOUNDS",
}

LEGACY_MENU_PATHS = {
    "/commodity/categories",
    "/commodity/types",
    "/ship/import/batches",
    "/route/plans",
    "/analysis/cargo",
}

REQUIRED_INTEGRATION_CONFIG_KEYS = {
    AMAP_ROUTE_WEB_API_KEY,
    AMAP_JS_API_KEY,
    AMAP_SECURITY_JS_CODE,
    DASHSCOPE_API_KEY,
    HIFLEET_ENABLED,
    HIFLEET_USERNAME,
    HIFLEET_PASSWORD,
    COS_ENABLED,
    COS_BUCKET_NAME,
    COS_REGION,
    COS_ENDPOINT,
    COS_ACCESS_KEY,
    COS_SECRET_KEY,
    COS_PATH_STYLE_ACCESS,
    COS_IMAGE_MAX_SIZE_MB,
}

ROUTE_TRACK_STATUSES = {"NOT_GENERATED", "READY", "PARTIAL", "FAILED"}
ROUTE_TRANSPORT_MODES = {"WATER", "ROAD", "RAIL"}
ROUTE_GEOMETRY_SOURCES = {"AMAP", "HIFLEET", "MANUAL", "FALLBACK"}


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


def _config_value_is_valid(value: str, value_type_code: str) -> bool:
    if value_type_code == "BOOLEAN":
        return str(value).strip().lower() in {"true", "false", ""}
    if value_type_code == "INTEGER":
        try:
            int(str(value).strip())
        except ValueError:
            return False
        return True
    if value_type_code == "FLOAT":
        try:
            float(str(value).strip())
        except ValueError:
            return False
        return True
    return value_type_code == "STRING"


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
    missing_required_routes = sorted(path for path in REQUIRED_ROUTE_PATHS if path not in route_paths)
    results.append(
        _result(
            "production freight api routes present",
            not missing_required_routes,
            "all present" if not missing_required_routes else ", ".join(missing_required_routes),
        )
    )

    async with AsyncSessionLocal() as session:
        count_checks = [
            ("business regions", await _count(session, Region, Region.code.not_like("E2E%")), 8),
            ("transport nodes", await _count(session, TransportNode, TransportNode.code.not_like("E2E%")), 30),
            ("node aliases", await _count(session, NodeAlias), 60),
            ("node contacts", await _count(session, TransportNodeContact), 60),
            ("commodity standards", await _count(session, CommodityStandard), 30),
            ("commodity aliases", await _count(session, CommodityAlias), 80),
            ("ships", await _count(session, ShipProfile), 80),
            ("freights", await _count(session, Freight), 200),
            ("wechat batch tasks", await _count(session, FreightBatchTask), 25),
            ("tms inbounds", await _count(session, FreightTmsInbound), 10),
            ("freight candidates", await _count(session, FreightCandidate), 40),
            ("freight normalization tasks", await _count(session, FreightNormalizationTask), 1),
            ("freight normalization suggestions", await _count(session, FreightNormalizationSuggestion), 5),
            ("freight daily facts", await _count(session, FactFreightDaily), 90),
            ("freight city facts", await _count(session, FactFreightCityDaily), 60),
            ("freight flow facts", await _count(session, FactFreightFlowDaily), 180),
            ("freight node facts", await _count(session, FactFreightNodeDaily), 60),
            ("ship city facts", await _count(session, FactShipCityDaily), 90),
            ("ship flow facts", await _count(session, FactShipFlowDaily), 300),
            ("analysis task definitions", await _count(session, AnalysisJobDefinition), 10),
            ("analysis jobs", await _count(session, AnalysisJobRun), 15),
            ("audit tasks", await _count(session, AuditTask), 30),
            ("audit snapshots", await _count(session, AuditTaskSnapshot), 30),
            ("audit records", await _count(session, AuditRecord), 30),
            ("navigation constraints", await _count(session, NavigationConstraintPoint), 3),
            ("shipping routes", await _count(session, ShippingRoute), 1),
        ]
        for name, actual, expected in count_checks:
            results.append(_result(name, actual >= expected, f"{actual} >= {expected}"))

        raw_freight_count = int(
            await session.scalar(
                select(func.count(Freight.id)).where(
                    (Freight.origin_match_level_code == "RAW")
                    | (Freight.destination_match_level_code == "RAW")
                    | (Freight.commodity_match_level_code == "RAW")
                )
            )
            or 0
        )
        results.append(_result("raw-level formal freights seeded", raw_freight_count >= 5, f"{raw_freight_count} >= 5"))
        raw_tonnage_freight_count = int(
            await session.scalar(
                select(func.count(Freight.id)).where(Freight.raw_tonnage_text.is_not(None), Freight.raw_tonnage_text != "")
            )
            or 0
        )
        raw_tonnage_candidate_count = int(
            await session.scalar(
                select(func.count(FreightCandidate.id)).where(
                    FreightCandidate.raw_tonnage_text.is_not(None),
                    FreightCandidate.raw_tonnage_text != "",
                )
            )
            or 0
        )
        results.append(
            _result(
                "freight raw tonnage seeded",
                raw_tonnage_freight_count >= 100 and raw_tonnage_candidate_count >= 20,
                f"freight {raw_tonnage_freight_count} >= 100, candidate {raw_tonnage_candidate_count} >= 20",
            )
        )
        ai_review_candidate_count = int(
            await session.scalar(
                select(func.count(FreightCandidate.id)).where(
                    FreightCandidate.ai_review_status_code.in_(["PASS", "REVIEW_REQUIRED", "MANUAL_ACCEPTED"]),
                    FreightCandidate.ai_understanding_json.is_not(None),
                    FreightCandidate.ai_tool_match_json.is_not(None),
                    FreightCandidate.ai_review_json.is_not(None),
                )
            )
            or 0
        )
        semantic_batch_count = int(
            await session.scalar(
                select(func.count(FreightBatchTask.id)).where(
                    FreightBatchTask.source_type_code == "WECHAT",
                    FreightBatchTask.ai_pipeline_version.is_not(None),
                    FreightBatchTask.ai_semantic_map_json.is_not(None),
                )
            )
            or 0
        )
        results.append(
            _result(
                "freight ai humanized seed fields",
                ai_review_candidate_count >= 40 and semantic_batch_count >= 25,
                f"candidate ai fields {ai_review_candidate_count} >= 40, semantic batches {semantic_batch_count} >= 25",
            )
        )

        task_codes = (await session.execute(select(AnalysisJobDefinition.job_code))).scalars().all()
        results.append(
            _result(
                "analysis task codes unique",
                len(task_codes) == len(set(task_codes)),
                f"{len(set(task_codes))}/{len(task_codes)} unique",
            )
        )
        active_ship_city_count = await session.scalar(
            select(func.count(func.distinct(FactShipCityDaily.city_code))).where(FactShipCityDaily.active_ship_count > 0)
        )
        results.append(
            _result(
                "ship active city facts usable",
                int(active_ship_city_count or 0) > 0,
                f"{int(active_ship_city_count or 0)} active cities",
            )
        )
        ship_overview = await AnalysisDashboardService(session).ship_overview(None, None)
        ship_metrics = {item.code: item for item in ship_overview.metrics}
        active_city_metric = ship_metrics.get("active_city_count")
        results.append(
            _result(
                "ship overview active city metric",
                active_city_metric is not None and active_city_metric.value > 0,
                f"{active_city_metric.value if active_city_metric else 0} active cities",
            )
        )
        freight_city_keys = (
            await session.execute(
                select(
                    FactFreightCityDaily.stat_date,
                    FactFreightCityDaily.city_code,
                    FactFreightCityDaily.data_version,
                )
            )
        ).all()
        results.append(
            _result(
                "freight city facts idempotent",
                len(freight_city_keys) == len(set(freight_city_keys)),
                f"{len(set(freight_city_keys))}/{len(freight_city_keys)} unique",
            )
        )
        freight_flow_keys = (
            await session.execute(
                select(
                    FactFreightFlowDaily.stat_date,
                    FactFreightFlowDaily.origin_node_id,
                    FactFreightFlowDaily.destination_node_id,
                    FactFreightFlowDaily.origin_region_id,
                    FactFreightFlowDaily.destination_region_id,
                    FactFreightFlowDaily.origin_city_code,
                    FactFreightFlowDaily.destination_city_code,
                    FactFreightFlowDaily.commodity_standard_id,
                    FactFreightFlowDaily.data_version,
                )
            )
        ).all()
        results.append(
            _result(
                "freight flow facts idempotent",
                len(freight_flow_keys) == len(set(freight_flow_keys)),
                f"{len(set(freight_flow_keys))}/{len(freight_flow_keys)} unique",
            )
        )

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

        configs = (
            (
                await session.execute(
                    select(
                        SystemConfig.config_key,
                        SystemConfig.config_value,
                        SystemConfig.value_type_code,
                    )
                )
            )
            .all()
        )
        config_by_key = {key: (value, value_type) for key, value, value_type in configs}
        missing_configs = sorted(REQUIRED_INTEGRATION_CONFIG_KEYS - set(config_by_key))
        results.append(
            _result(
                "integration configs present",
                not missing_configs,
                "none" if not missing_configs else ", ".join(missing_configs),
            )
        )

        invalid_configs = sorted(
            key
            for key, value, value_type in configs
            if not _config_value_is_valid(value, value_type)
        )
        results.append(
            _result(
                "system config typed values valid",
                not invalid_configs,
                "none" if not invalid_configs else ", ".join(invalid_configs),
            )
        )

        local_values = {
            key: value
            for key, value in _merged_local_values().items()
            if key in LOCAL_PRIVATE_CONFIG_KEYS and str(value).strip()
        }
        local_mismatches = []
        for key, raw_value in local_values.items():
            metadata = CONFIG_METADATA_BY_KEY.get(key)
            db_config = config_by_key.get(key)
            if metadata is None or db_config is None:
                local_mismatches.append(key)
                continue
            expected = _normalize_config_value(key, raw_value, metadata["value_type_code"])
            if db_config[0] != expected:
                local_mismatches.append(key)
        results.append(
            _result(
                "local private seed applied",
                not local_mismatches,
                f"{len(local_values)} local values checked" if not local_mismatches else ", ".join(sorted(local_mismatches)),
            )
        )

        invalid_line_statuses = (
            (
                await session.execute(
                    select(ShippingRouteLine.line_code, ShippingRouteLine.track_status).where(
                        ~ShippingRouteLine.track_status.in_(ROUTE_TRACK_STATUSES)
                    )
                )
            )
            .all()
        )
        results.append(
            _result(
                "route line track statuses valid",
                not invalid_line_statuses,
                str(invalid_line_statuses or "none"),
            )
        )

        invalid_segment_values = (
            (
                await session.execute(
                    select(
                        ShippingRouteLineSegment.segment_no,
                        ShippingRouteLineSegment.transport_mode_code,
                        ShippingRouteLineSegment.segment_track_status,
                        ShippingRouteLineSegment.geometry_source,
                    ).where(
                        (~ShippingRouteLineSegment.transport_mode_code.in_(ROUTE_TRANSPORT_MODES))
                        | (~ShippingRouteLineSegment.segment_track_status.in_(ROUTE_TRACK_STATUSES))
                        | (
                            ShippingRouteLineSegment.geometry_source.is_not(None)
                            & (~ShippingRouteLineSegment.geometry_source.in_(ROUTE_GEOMETRY_SOURCES))
                        )
                    )
                )
            )
            .all()
        )
        results.append(
            _result(
                "route segment enums valid",
                not invalid_segment_values,
                str(invalid_segment_values or "none"),
            )
        )

        invalid_track_statuses = (
            (
                await session.execute(
                    select(ShippingRouteLineTrack.line_id, ShippingRouteLineTrack.track_status).where(
                        ~ShippingRouteLineTrack.track_status.in_(ROUTE_TRACK_STATUSES)
                    )
                )
            )
            .all()
        )
        results.append(
            _result(
                "stored route track statuses valid",
                not invalid_track_statuses,
                str(invalid_track_statuses or "none"),
            )
        )

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
