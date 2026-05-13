"""第 7 轮本地验收只读检查。"""

from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import AsyncSessionLocal, engine
from app.integrations.config_keys import (
    AMAP_CONFIG_PROFILE,
    AMAP_JS_API_KEY,
    AMAP_ROUTE_GEOMETRY_MODE,
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
    ES_HISTORY_CONFIG_PROFILE,
    ES_HISTORY_INDEX_PREFIX,
    ES_HOST,
    ES_PASSWORD,
    ES_PORT,
    ES_R_HOST,
    ES_R_INDEX,
    ES_R_PASSWORD,
    ES_R_PORT,
    ES_R_USER,
    ES_REALTIME_CONFIG_PROFILE,
    ES_USER,
    HIFLEET_CONFIG_PROFILE,
    HIFLEET_BASE_URL,
    HIFLEET_CHECK_LOGIN_COOLDOWN_SECONDS,
    HIFLEET_CHECK_LOGIN_URL,
    HIFLEET_DUPLICATE_LOGIN_RECOVERY_ENABLED,
    HIFLEET_ENABLED,
    HIFLEET_LOGIN_URL,
    HIFLEET_LOGOUT_URL,
    HIFLEET_PASSWORD,
    HIFLEET_RELOGIN_CHECK_ENABLED,
    HIFLEET_ROUTE_URL,
    HIFLEET_SESSION_COOKIE_TTL_SECONDS,
    HIFLEET_SESSION_IDLE_LOGOUT_SECONDS,
    HIFLEET_SESSION_LOCK_TTL_SECONDS,
    HIFLEET_SESSION_LOGOUT_ON_SHUTDOWN,
    HIFLEET_SESSION_WARMUP_ON_START,
    HIFLEET_TIMEOUT_SECONDS,
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
    PricingDecisionRecord,
)
from app.models.audit import AuditRecord, AuditTask, AuditTaskSnapshot
from app.models.commodity import CommodityAlias, CommodityStandard
from app.models.freight import Freight, FreightBatchTask, FreightCandidate, FreightNormalizationSuggestion, FreightNormalizationTask, FreightTmsInbound
from app.models.route import ShippingRoute, ShippingRouteLine, ShippingRouteLineSegment, ShippingRouteLineTrack
from app.models.system import SysMenu, SysRole, SysRoleMenu, SystemConfig
from app.models.vessel import (
    VesselAffiliationEvidence,
    VesselAisCitySnapshotItem,
    VesselAisSnapshot,
    VesselBlacklistSignal,
    VesselBuildInfo,
    VesselCapacityDimension,
    VesselCandidateAnalysis,
    VesselCandidateAnalysisItem,
    VesselCertificate,
    VesselCertificateFile,
    VesselCertificateImageRecognition,
    VesselCertificateRequirementRule,
    VesselChangeEvent,
    VesselContact,
    VesselControllerEvidence,
    VesselCrewAssignment,
    VesselDataQualityIssue,
    VesselGovernanceTask,
    VesselIdentifierHistory,
    VesselIdentity,
    VesselIdentityLink,
    VesselLatestPositionSnapshot,
    VesselNameHistory,
    VesselNavigationConstraintEvidence,
    VesselNodeObservationItem,
    VesselNodeObservationVessel,
    VesselOperatorPeriod,
    VesselOwnerPeriod,
    VesselPersonCertificate,
    VesselPersonCertificateFile,
    VesselPersonCertificateImageRecognition,
    VesselProfile,
    VesselProfileSummary,
    VesselRecognitionAdoptionRecord,
    VesselRecognitionFieldDiff,
    VesselRegistrationInfo,
    VesselRiskSignal,
    VesselRouteSegmentMatchSample,
    VesselRouteSegmentObservationItem,
    VesselSpatialObservationSnapshot,
)
from app.modules.analysis.service import AnalysisDashboardService
from app.modules.analysis.pricing_decision_service import PricingDecisionService
from scripts.seed_local_private_config import (
    CONFIG_METADATA_BY_KEY,
    LOCAL_PRIVATE_CONFIG_KEYS,
    load_local_private_values,
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

VESSEL_TABLES = {
    "vessel_affiliation_conclusion",
    "vessel_affiliation_evidence",
    "vessel_ais_city_snapshot_item",
    "vessel_ais_snapshot",
    "vessel_blacklist_signal",
    "vessel_build_info",
    "vessel_capacity_dimension",
    "vessel_candidate_analysis",
    "vessel_candidate_analysis_annotation",
    "vessel_candidate_analysis_item",
    "vessel_certificate",
    "vessel_certificate_file",
    "vessel_certificate_image_recognition",
    "vessel_certificate_requirement_rule",
    "vessel_change_event",
    "vessel_contact",
    "vessel_controller_conclusion",
    "vessel_controller_evidence",
    "vessel_crew_assignment",
    "vessel_data_quality_issue",
    "vessel_governance_sync_batch",
    "vessel_governance_task",
    "vessel_identifier_history",
    "vessel_identity",
    "vessel_identity_link",
    "vessel_latest_position_snapshot",
    "vessel_name_history",
    "vessel_navigation_constraint_evidence",
    "vessel_node_observation_item",
    "vessel_node_observation_vessel",
    "vessel_operator_period",
    "vessel_owner_document",
    "vessel_owner_document_image_recognition",
    "vessel_owner_period",
    "vessel_person_certificate",
    "vessel_person_certificate_file",
    "vessel_person_certificate_image_recognition",
    "vessel_profile",
    "vessel_profile_summary",
    "vessel_recognition_adoption_record",
    "vessel_recognition_field_diff",
    "vessel_registration_info",
    "vessel_relation_evidence_attachment",
    "vessel_risk_review",
    "vessel_risk_signal",
    "vessel_route_segment_match_sample",
    "vessel_route_segment_observation_item",
    "vessel_spatial_observation_snapshot",
}

PRICING_TABLES = {
    "pricing_decision_record",
}

LEGACY_ROUTE_PATHS = {
    "/api/v1/ship",
    "/api/v1/ship/{ship_id}",
    "/api/v1/ship/statistics/overview",
    "/api/v1/ship/{ship_id}/capacity",
    "/api/v1/ship/{ship_id}/operation",
    "/api/v1/ship/{ship_id}/owners",
    "/api/v1/ship/{ship_id}/contacts",
    "/api/v1/ship/{ship_id}/certificates",
    "/api/v1/ship/import/batches",
    "/api/v1/ship/import/batches/{batch_id}",
    "/api/v1/ship/import/batches/{batch_id}/raw-records",
    "/api/v1/ship/import/batches/{batch_id}/records",
    "/api/v1/vessels/operation-search",
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
    "/api/v1/vessels",
    "/api/v1/vessels/assets",
    "/api/v1/vessels/quality",
    "/api/v1/vessels/{vessel_id}/profile-card",
    "/api/v1/vessels/ais/city-situation",
    "/api/v1/vessels/ais/city-vessels",
    "/api/v1/vessels/ais/vessels/{vessel_id}/situation-card",
    "/api/v1/vessels/position-monitor",
    "/api/v1/vessels/{vessel_id}",
    "/api/v1/vessels/{vessel_id}/profile",
    "/api/v1/vessels/{vessel_id}/certificate-files",
    "/api/v1/vessels/{vessel_id}/certificates/{certificate_id}/files",
    "/api/v1/freight/manual",
    "/api/v1/freight/batches/wechat",
    "/api/v1/freight/batches/{batch_id}/parse",
    "/api/v1/freight/batches/{batch_id}/candidates/bulk-confirm",
    "/api/v1/freight/batches/{batch_id}/handoff-review",
    "/api/v1/freight/tms-inbounds",
    "/api/v1/freight/tms-inbounds/{inbound_id}/parse",
    "/api/v1/freight/candidates/{candidate_id}/confirm",
    "/api/v1/freight/candidates/{candidate_id}/reject",
    "/api/v1/freight/normalization/clean",
    "/api/v1/freight/normalization/quality",
    "/api/v1/freight/normalization/tasks",
    "/api/v1/freight/normalization/tasks/{task_id}",
    "/api/v1/freight/normalization/tasks/{task_id}/suggestions",
    "/api/v1/freight/normalization/tasks/{task_id}/suggestions/bulk-apply",
    "/api/v1/freight/normalization/tasks/{task_id}/suggestions/bulk-reject",
    "/api/v1/freight/normalization/tasks/{task_id}/suggestions/{suggestion_id}/apply",
    "/api/v1/freight/normalization/tasks/{task_id}/suggestions/{suggestion_id}/reject",
    "/api/v1/analysis/freight/node-ranking",
    "/api/v1/analysis/quote-simulator/context",
    "/api/v1/analysis/quote-simulator/decision",
    "/api/v1/analysis/rate-estimator/estimate",
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
    "VESSEL_OPERATION_SEARCH",
    "VESSEL_GOVERNANCE",
    "VESSEL_QUALITY_ISSUES",
    "VESSEL_IDENTITY_CANDIDATES",
    "VESSEL_IMPORT",
}

LEGACY_MENU_PATHS = {
    "/commodity/categories",
    "/commodity/types",
    "/ship/import/batches",
    "/ship/list",
    "/vessels/operation-search",
    "/vessels/governance",
    "/vessels/quality-issues",
    "/vessels/identity-candidates",
    "/vessels/import",
    "/route/plans",
    "/analysis/cargo",
}

REQUIRED_INTEGRATION_CONFIG_KEYS = {
    AMAP_ROUTE_GEOMETRY_MODE,
    AMAP_ROUTE_WEB_API_KEY,
    AMAP_JS_API_KEY,
    AMAP_SECURITY_JS_CODE,
    DASHSCOPE_API_KEY,
    ES_R_HOST,
    ES_R_PORT,
    ES_R_USER,
    ES_R_PASSWORD,
    ES_R_INDEX,
    ES_HOST,
    ES_PORT,
    ES_USER,
    ES_PASSWORD,
    ES_HISTORY_INDEX_PREFIX,
    HIFLEET_ENABLED,
    HIFLEET_BASE_URL,
    HIFLEET_LOGIN_URL,
    HIFLEET_LOGOUT_URL,
    HIFLEET_ROUTE_URL,
    HIFLEET_CHECK_LOGIN_URL,
    HIFLEET_USERNAME,
    HIFLEET_PASSWORD,
    HIFLEET_TIMEOUT_SECONDS,
    HIFLEET_CHECK_LOGIN_COOLDOWN_SECONDS,
    HIFLEET_SESSION_IDLE_LOGOUT_SECONDS,
    HIFLEET_RELOGIN_CHECK_ENABLED,
    HIFLEET_SESSION_WARMUP_ON_START,
    HIFLEET_SESSION_LOGOUT_ON_SHUTDOWN,
    HIFLEET_SESSION_LOCK_TTL_SECONDS,
    HIFLEET_SESSION_COOKIE_TTL_SECONDS,
    HIFLEET_DUPLICATE_LOGIN_RECOVERY_ENABLED,
    COS_ENABLED,
    COS_BUCKET_NAME,
    COS_REGION,
    COS_ENDPOINT,
    COS_ACCESS_KEY,
    COS_SECRET_KEY,
    COS_PATH_STYLE_ACCESS,
    COS_IMAGE_MAX_SIZE_MB,
}

LOCAL_DEMO_REQUIRED_NON_EMPTY_CONFIG_KEYS = {
    AMAP_ROUTE_WEB_API_KEY,
    AMAP_JS_API_KEY,
    AMAP_SECURITY_JS_CODE,
    DASHSCOPE_API_KEY,
    ES_R_HOST,
    ES_R_PORT,
    ES_R_USER,
    ES_R_PASSWORD,
    ES_R_INDEX,
    ES_HOST,
    ES_PORT,
    ES_USER,
    ES_PASSWORD,
    ES_HISTORY_INDEX_PREFIX,
    HIFLEET_USERNAME,
    HIFLEET_PASSWORD,
    COS_BUCKET_NAME,
    COS_REGION,
    COS_ENDPOINT,
    COS_ACCESS_KEY,
    COS_SECRET_KEY,
}

LOCAL_DEMO_CONFIG_TEST_PROFILES = {
    AMAP_CONFIG_PROFILE,
    HIFLEET_CONFIG_PROFILE,
    ES_REALTIME_CONFIG_PROFILE,
    ES_HISTORY_CONFIG_PROFILE,
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


async def _orphan_count(session, child_model, child_column, parent_model, parent_column) -> int:
    stmt = (
        select(func.count())
        .select_from(child_model)
        .outerjoin(parent_model, child_column == parent_column)
        .where(child_column.is_not(None), parent_column.is_(None))
    )
    return int(await session.scalar(stmt) or 0)


async def _duplicate_value_count(session, model, column) -> int:
    duplicate_values = select(column).select_from(model).where(column.is_not(None)).group_by(column).having(func.count() > 1).subquery()
    stmt = select(func.count()).select_from(duplicate_values)
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

    missing_vessel_tables = sorted(VESSEL_TABLES - tables)
    results.append(
        _result(
            "vessel tables present",
            not missing_vessel_tables,
            "all present" if not missing_vessel_tables else ", ".join(missing_vessel_tables),
        )
    )
    missing_pricing_tables = sorted(PRICING_TABLES - tables)
    results.append(
        _result(
            "pricing decision tables present",
            not missing_pricing_tables,
            "all present" if not missing_pricing_tables else ", ".join(missing_pricing_tables),
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
            ("vessel profiles", await _count(session, VesselProfile), 137),
            ("vessel identities", await _count(session, VesselIdentity), 137),
            ("vessel identity links", await _count(session, VesselIdentityLink), 137),
            ("vessel registrations", await _count(session, VesselRegistrationInfo), 137),
            ("vessel capacity dimensions", await _count(session, VesselCapacityDimension), 137),
            ("vessel build info", await _count(session, VesselBuildInfo), 137),
            ("vessel owner periods", await _count(session, VesselOwnerPeriod), 137),
            ("vessel current owners", await _count(session, VesselOwnerPeriod, VesselOwnerPeriod.is_current.is_(True)), 137),
            ("vessel historical owners", await _count(session, VesselOwnerPeriod, VesselOwnerPeriod.is_current.is_(False)), 137),
            ("vessel operator periods", await _count(session, VesselOperatorPeriod), 137),
            ("vessel current operators", await _count(session, VesselOperatorPeriod, VesselOperatorPeriod.is_current.is_(True)), 137),
            ("vessel contacts", await _count(session, VesselContact), 274),
            ("vessel operator contacts", await _count(session, VesselContact, VesselContact.contact_scope_code == "OPERATOR"), 137),
            ("vessel general contacts", await _count(session, VesselContact, VesselContact.contact_scope_code == "GENERAL"), 137),
            ("vessel profile summaries", await _count(session, VesselProfileSummary), 137),
            ("vessel AIS snapshots", await _count(session, VesselAisSnapshot), 1),
            ("vessel AIS city snapshot items", await _count(session, VesselAisCitySnapshotItem), 6),
            ("vessel latest positions", await _count(session, VesselLatestPositionSnapshot), 137),
            ("vessel spatial snapshots", await _count(session, VesselSpatialObservationSnapshot), 8),
            ("vessel node observation items", await _count(session, VesselNodeObservationItem), 4),
            ("vessel node observation vessels", await _count(session, VesselNodeObservationVessel), 48),
            ("vessel route segment observation items", await _count(session, VesselRouteSegmentObservationItem), 9),
            ("vessel route segment match samples", await _count(session, VesselRouteSegmentMatchSample), 72),
            ("vessel quality issues", await _count(session, VesselDataQualityIssue), 18),
            ("vessel risk signals", await _count(session, VesselRiskSignal), 18),
            ("vessel governance tasks", await _count(session, VesselGovernanceTask), 18),
            ("vessel certificate requirement rules", await _count(session, VesselCertificateRequirementRule), 3),
            ("vessel recognition diffs", await _count(session, VesselRecognitionFieldDiff), 8),
            ("vessel recognition adoptions", await _count(session, VesselRecognitionAdoptionRecord), 8),
            ("vessel candidate analyses", await _count(session, VesselCandidateAnalysis), 7),
            ("vessel candidate analysis items", await _count(session, VesselCandidateAnalysisItem), 70),
            ("vessel navigation constraint evidence", await _count(session, VesselNavigationConstraintEvidence), 19),
            ("vessel blacklist signals", await _count(session, VesselBlacklistSignal), 6),
            ("vessel controller evidence", await _count(session, VesselControllerEvidence), 6),
            ("vessel affiliation evidence", await _count(session, VesselAffiliationEvidence), 6),
            ("vessel certificates empty-ok", await _count(session, VesselCertificate), 0),
            ("vessel change events", await _count(session, VesselChangeEvent), 137),
            ("vessel crew assignments empty-ok", await _count(session, VesselCrewAssignment), 0),
            ("vessel person certificates empty-ok", await _count(session, VesselPersonCertificate), 0),
            ("vessel person certificate files table empty-ok", await _count(session, VesselPersonCertificateFile), 0),
            ("vessel person certificate recognitions table empty-ok", await _count(session, VesselPersonCertificateImageRecognition), 0),
            ("vessel certificate files table empty-ok", await _count(session, VesselCertificateFile), 0),
            ("vessel certificate recognitions table empty-ok", await _count(session, VesselCertificateImageRecognition), 0),
            ("freights", await _count(session, Freight), 282),
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
            ("shipping routes", await _count(session, ShippingRoute), 3),
            ("pricing decision records empty-ok", await _count(session, PricingDecisionRecord), 0),
        ]
        for name, actual, expected in count_checks:
            results.append(_result(name, actual >= expected, f"{actual} >= {expected}"))

        demo_freight_count = await _count(session, Freight, Freight.freight_no.like("FR-DEMO-%"))
        demo_quote_ready_count = await _count(
            session,
            Freight,
            Freight.freight_no.like("FR-DEMO-%"),
            Freight.origin_node_id.is_not(None),
            Freight.destination_node_id.is_not(None),
            Freight.commodity_standard_id.is_not(None),
            Freight.estimated_tonnage.is_not(None),
            Freight.unit_price.is_not(None),
        )
        demo_quote_ready_ids = (
            await session.execute(
                select(Freight.id)
                .where(
                    Freight.freight_no.like("FR-DEMO-%"),
                    Freight.origin_node_id.is_not(None),
                    Freight.destination_node_id.is_not(None),
                    Freight.commodity_standard_id.is_not(None),
                    Freight.estimated_tonnage.is_not(None),
                    Freight.unit_price.is_not(None),
                )
                .order_by(Freight.id)
                .limit(5)
            )
        ).scalars().all()
        pricing_service = PricingDecisionService(session)
        parsed_quote_context_count = 0
        for freight_id in demo_quote_ready_ids:
            context = await pricing_service.quote_context(int(freight_id))
            if (
                context.current_quote is not None
                and (context.owner_quote_min is not None or context.owner_quote_max is not None)
                and context.advanced_config_text
            ):
                parsed_quote_context_count += 1
        demo_candidate_count = await _count(session, FreightCandidate, FreightCandidate.candidate_no.like("FCA-DEMO-%"))
        demo_batch_count = await _count(session, FreightBatchTask, FreightBatchTask.batch_no.like("FBT-DEMO-%"))
        demo_tms_count = await _count(session, FreightTmsInbound, FreightTmsInbound.inbound_no.like("FTI-DEMO-%"))
        demo_owner_quote_text_count = await _count(
            session,
            FreightBatchTask,
            FreightBatchTask.batch_no.like("FBT-DEMO-%"),
            FreightBatchTask.raw_text.like("%船主%"),
            FreightBatchTask.raw_text.like("%高级配置%"),
        )
        demo_candidate_analysis_count = await _count(
            session,
            VesselCandidateAnalysis,
            VesselCandidateAnalysis.context_type_code == "FREIGHT_SAMPLE",
            VesselCandidateAnalysis.source_layer_code == "LOCAL_DEMO",
        )
        demo_ais_positions = await _count(
            session,
            VesselLatestPositionSnapshot,
            VesselLatestPositionSnapshot.snapshot_id == "DEMO_AIS_EXPERIENCE_CURRENT",
        )
        demo_ais_mirror_positions = await _count(
            session,
            VesselLatestPositionSnapshot,
            VesselLatestPositionSnapshot.snapshot_id == "DEMO_AIS_EXPERIENCE_CURRENT",
            VesselLatestPositionSnapshot.source_index == "DEMO_ES_MIRROR",
        )
        results.extend(
            [
                _result("experience FR-DEMO freights seeded", demo_freight_count >= 42, f"{demo_freight_count} >= 42"),
                _result(
                    "experience quote-ready freights seeded",
                    demo_quote_ready_count >= 5,
                    f"{demo_quote_ready_count} >= 5",
                ),
                _result(
                    "experience quote context parseable",
                    parsed_quote_context_count >= 5,
                    f"{parsed_quote_context_count} >= 5 include shipper quote, owner quote and advanced config",
                ),
                _result("experience FCA-DEMO candidates seeded", demo_candidate_count >= 42, f"{demo_candidate_count} >= 42"),
                _result("experience FBT-DEMO batches seeded", demo_batch_count >= 42, f"{demo_batch_count} >= 42"),
                _result("experience FTI-DEMO inbounds seeded", demo_tms_count >= 42, f"{demo_tms_count} >= 42"),
                _result(
                    "experience quote evidence preserved",
                    demo_owner_quote_text_count >= 42,
                    f"{demo_owner_quote_text_count} >= 42 raw rows include owner quote and advanced config",
                ),
                _result(
                    "experience freight candidate analyses seeded",
                    demo_candidate_analysis_count >= 6,
                    f"{demo_candidate_analysis_count} >= 6",
                ),
                _result(
                    "experience AIS snapshot usable",
                    demo_ais_positions >= 8 and (demo_ais_mirror_positions >= 8 or demo_ais_positions - demo_ais_mirror_positions >= 8),
                    f"positions {demo_ais_positions} >= 8, DEMO_ES_MIRROR {demo_ais_mirror_positions}",
                ),
            ]
        )

        constraint_statuses = set(
            (
                await session.execute(
                    select(VesselNavigationConstraintEvidence.status_code).where(
                        VesselNavigationConstraintEvidence.source_ref.like("round11-experience%")
                    )
                )
            ).scalars().all()
        )
        required_constraint_statuses = {"PASS", "WARNING", "BLOCKED", "UNKNOWN"}
        results.append(
            _result(
                "experience navigation constraint statuses complete",
                required_constraint_statuses.issubset(constraint_statuses),
                ", ".join(sorted(constraint_statuses)) or "none",
            )
        )

        name_history_count = await _count(session, VesselNameHistory)
        identifier_history_count = await _count(session, VesselIdentifierHistory)
        results.append(
            _result(
                "vessel name and mmsi histories seeded",
                name_history_count >= 137 and identifier_history_count >= 137,
                f"name {name_history_count} >= 137, identifier {identifier_history_count} >= 137",
            )
        )

        referential_checks = [
            (
                "vessel profiles link existing identities",
                await _orphan_count(session, VesselProfile, VesselProfile.vessel_identity_id, VesselIdentity, VesselIdentity.id),
            ),
            (
                "identity links reference profiles",
                await _orphan_count(session, VesselIdentityLink, VesselIdentityLink.vessel_profile_id, VesselProfile, VesselProfile.id),
            ),
            (
                "registrations reference profiles",
                await _orphan_count(session, VesselRegistrationInfo, VesselRegistrationInfo.vessel_profile_id, VesselProfile, VesselProfile.id),
            ),
            (
                "capacity rows reference profiles",
                await _orphan_count(session, VesselCapacityDimension, VesselCapacityDimension.vessel_profile_id, VesselProfile, VesselProfile.id),
            ),
            (
                "build rows reference profiles",
                await _orphan_count(session, VesselBuildInfo, VesselBuildInfo.vessel_profile_id, VesselProfile, VesselProfile.id),
            ),
            (
                "owner periods reference profiles",
                await _orphan_count(session, VesselOwnerPeriod, VesselOwnerPeriod.vessel_profile_id, VesselProfile, VesselProfile.id),
            ),
            (
                "operator periods reference profiles",
                await _orphan_count(session, VesselOperatorPeriod, VesselOperatorPeriod.vessel_profile_id, VesselProfile, VesselProfile.id),
            ),
            (
                "contacts reference profiles",
                await _orphan_count(session, VesselContact, VesselContact.vessel_profile_id, VesselProfile, VesselProfile.id),
            ),
            (
                "contacts reference owner periods",
                await _orphan_count(session, VesselContact, VesselContact.owner_period_id, VesselOwnerPeriod, VesselOwnerPeriod.id),
            ),
            (
                "contacts reference operator periods",
                await _orphan_count(session, VesselContact, VesselContact.operator_period_id, VesselOperatorPeriod, VesselOperatorPeriod.id),
            ),
            (
                "profile summaries reference profiles",
                await _orphan_count(session, VesselProfileSummary, VesselProfileSummary.vessel_profile_id, VesselProfile, VesselProfile.id),
            ),
            (
                "latest positions reference profiles",
                await _orphan_count(session, VesselLatestPositionSnapshot, VesselLatestPositionSnapshot.vessel_profile_id, VesselProfile, VesselProfile.id),
            ),
            (
                "quality issues reference profiles",
                await _orphan_count(session, VesselDataQualityIssue, VesselDataQualityIssue.vessel_profile_id, VesselProfile, VesselProfile.id),
            ),
            (
                "risk signals reference profiles",
                await _orphan_count(session, VesselRiskSignal, VesselRiskSignal.vessel_profile_id, VesselProfile, VesselProfile.id),
            ),
            (
                "governance tasks reference profiles",
                await _orphan_count(session, VesselGovernanceTask, VesselGovernanceTask.vessel_profile_id, VesselProfile, VesselProfile.id),
            ),
            (
                "recognition diffs reference profiles",
                await _orphan_count(session, VesselRecognitionFieldDiff, VesselRecognitionFieldDiff.vessel_profile_id, VesselProfile, VesselProfile.id),
            ),
            (
                "candidate items reference analyses",
                await _orphan_count(session, VesselCandidateAnalysisItem, VesselCandidateAnalysisItem.analysis_id, VesselCandidateAnalysis, VesselCandidateAnalysis.id),
            ),
        ]
        for name, orphan_total in referential_checks:
            results.append(_result(name, orphan_total == 0, f"{orphan_total} orphan rows"))

        duplicate_checks = [
            ("vessel profile code unique", await _duplicate_value_count(session, VesselProfile, VesselProfile.vessel_profile_code)),
            ("vessel identity code unique", await _duplicate_value_count(session, VesselIdentity, VesselIdentity.identity_code)),
            ("vessel current mmsi unique", await _duplicate_value_count(session, VesselProfile, VesselProfile.current_mmsi)),
            ("vessel profile summary one per profile", await _duplicate_value_count(session, VesselProfileSummary, VesselProfileSummary.vessel_profile_id)),
            ("vessel governance task no unique", await _duplicate_value_count(session, VesselGovernanceTask, VesselGovernanceTask.task_no)),
            ("vessel risk active fingerprint unique", await _duplicate_value_count(session, VesselRiskSignal, VesselRiskSignal.fingerprint)),
        ]
        for name, duplicate_total in duplicate_checks:
            results.append(_result(name, duplicate_total == 0, f"{duplicate_total} duplicate values"))

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
            "freights": await _count(session, Freight, Freight.freight_no.like("E2E%") | Freight.source_ref_no.like("E2E%")),
        }
        e2e_left = {key: value for key, value in e2e_counts.items() if value}
        results.append(_result("legacy e2e data purged", not e2e_left, str(e2e_left or "none")))
        automated_constraint_count = await _count(
            session,
            NavigationConstraintPoint,
            NavigationConstraintPoint.name.like("自动化新增约束点-%"),
        )
        results.append(
            _result(
                "automation constraint pollution absent",
                automated_constraint_count == 0,
                f"{automated_constraint_count} automated constraint rows",
            )
        )

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
        required_vessel_paths = {
            "/vessels/assets",
            "/vessels/profile-cards",
            "/vessels/relations",
            "/vessels/governance/dashboard",
            "/vessels/governance/tasks",
            "/vessels/quality",
            "/vessels/compliance-risks",
            "/vessels/blacklist-signals",
            "/vessels/recognitions",
            "/vessels/ais-situation",
            "/vessels/node-route-analysis",
            "/vessels/candidate-analysis",
        }
        vessel_paths = {
            row[0]
            for row in (
                await session.execute(select(SysMenu.route_path).where(SysMenu.route_path.in_(required_vessel_paths)))
            ).all()
        }
        missing_vessel_paths = sorted(required_vessel_paths - vessel_paths)
        results.append(
            _result(
                "business vessel menus present",
                not missing_vessel_paths,
                "all present" if not missing_vessel_paths else ", ".join(missing_vessel_paths),
            )
        )
        required_pricing_paths = {
            "/analysis/quote-simulator",
            "/analysis/rate-estimator",
            "/analysis/prices",
        }
        pricing_paths = {
            row[0]
            for row in (
                await session.execute(select(SysMenu.route_path).where(SysMenu.route_path.in_(required_pricing_paths)))
            ).all()
        }
        missing_pricing_paths = sorted(required_pricing_paths - pricing_paths)
        results.append(
            _result(
                "pricing center menus present",
                not missing_pricing_paths,
                "all present" if not missing_pricing_paths else ", ".join(missing_pricing_paths),
            )
        )
        freight_menu_rows = (
            await session.execute(
                select(SysMenu.menu_code, SysMenu.menu_name, SysMenu.route_path, SysMenu.sort_order, SysMenu.visible_flag)
                .where(SysMenu.parent_id == select(SysMenu.id).where(SysMenu.menu_code == "FREIGHT_ROOT").scalar_subquery())
                .order_by(SysMenu.sort_order)
            )
        ).all()
        visible_freight_names = [row.menu_name for row in freight_menu_rows if row.visible_flag == 1]
        required_freight_names = [
            "货源态势总览",
            "微信语义解析",
            "TMS 结构化入站",
            "解析批次监控",
            "候选证据池",
            "机会样本库",
            "供需适配分析",
            "质量治理与回算",
        ]
        stale_freight_names = {"货源分析", "微信采集", "TMS 入站", "采集批次", "候选确认", "运输机会", "数据清洗", "手工录入"}
        results.append(
            _result(
                "freight insight menu IA renamed",
                visible_freight_names == required_freight_names and not stale_freight_names.intersection(visible_freight_names),
                " > ".join(visible_freight_names),
            )
        )
        freight_menu_map = {row.menu_code: row for row in freight_menu_rows}
        manual_menu = freight_menu_map.get("FREIGHT_MANUAL_CREATE")
        fit_menu = freight_menu_map.get("FREIGHT_SUPPLY_DEMAND_FIT")
        results.append(
            _result(
                "freight supplement create hidden",
                manual_menu is not None and manual_menu.menu_name == "补录样本" and manual_menu.visible_flag == 0,
                str((manual_menu.menu_name, manual_menu.visible_flag) if manual_menu else "missing"),
            )
        )
        results.append(
            _result(
                "freight supply-demand fit entry present",
                fit_menu is not None and fit_menu.route_path == "/freight/supply-demand-fit" and fit_menu.visible_flag == 1,
                str((fit_menu.route_path, fit_menu.visible_flag) if fit_menu else "missing"),
            )
        )
        vessel_entry_rows = (
            await session.execute(
                select(SysMenu.menu_code, SysMenu.route_path, SysMenu.component_path).where(
                    SysMenu.menu_code.in_(("VESSEL_ASSETS", "VESSEL_PROFILE_ENTRY", "VESSEL_RELATIONS_ENTRY"))
                )
            )
        ).all()
        vessel_entry_map = {code: (route_path, component_path) for code, route_path, component_path in vessel_entry_rows}
        entry_routes = [route for route, _ in vessel_entry_map.values()]
        entry_components = [component for _, component in vessel_entry_map.values()]
        distinct_entry_menus = (
            len(vessel_entry_map) == 3
            and len(set(entry_routes)) == 3
            and len(set(entry_components)) == 3
            and all(route and "entry=" not in route for route in entry_routes)
        )
        results.append(
            _result(
                "vessel core menu entries distinct",
                distinct_entry_menus,
                "assets/profile/relations use separate routes and pages"
                if distinct_entry_menus
                else str(vessel_entry_map),
            )
        )

        menu_rows = (await session.execute(select(SysMenu.id, SysMenu.menu_code, SysMenu.parent_id))).all()
        menu_code_by_id = {menu_id: menu_code for menu_id, menu_code, _ in menu_rows}
        parent_by_id = {menu_id: parent_id for menu_id, _, parent_id in menu_rows}
        role_menu_rows = (
            await session.execute(
                select(SysRole.role_code, SysRoleMenu.menu_id)
                .join(SysRoleMenu, SysRoleMenu.role_id == SysRole.id)
                .where(SysRole.role_code.in_(("DATA_STEWARD", "OPS_ANALYST", "BUSINESS_INPUTTER")))
            )
        ).all()
        assigned_menu_ids_by_role: dict[str, set[int]] = defaultdict(set)
        for role_code, menu_id in role_menu_rows:
            assigned_menu_ids_by_role[role_code].add(menu_id)
        missing_menu_parents: list[str] = []
        for role_code, assigned_menu_ids in assigned_menu_ids_by_role.items():
            for menu_id in assigned_menu_ids:
                parent_id = parent_by_id.get(menu_id)
                if parent_id and parent_id not in assigned_menu_ids:
                    missing_menu_parents.append(
                        f"{role_code}:{menu_code_by_id.get(menu_id, menu_id)}->{menu_code_by_id.get(parent_id, parent_id)}"
                    )
        results.append(
            _result(
                "role menu hierarchy complete",
                not missing_menu_parents,
                "all role menu parents assigned" if not missing_menu_parents else ", ".join(sorted(missing_menu_parents)),
            )
        )

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

        realtime_missing = sorted(
            key
            for key in {ES_R_HOST, ES_R_PORT, ES_R_USER, ES_R_PASSWORD, ES_R_INDEX}
            if not str(config_by_key.get(key, ("", ""))[0] or "").strip()
        )
        results.append(
            _result(
                "realtime ES local-demo config complete",
                not realtime_missing,
                "configured" if not realtime_missing else ", ".join(realtime_missing),
            )
        )

        history_missing = sorted(
            key
            for key in {ES_HOST, ES_PORT, ES_USER, ES_PASSWORD, ES_HISTORY_INDEX_PREFIX}
            if not str(config_by_key.get(key, ("", ""))[0] or "").strip()
        )
        results.append(
            _result(
                "history ES local-demo config complete",
                not history_missing,
                "configured" if not history_missing else ", ".join(history_missing),
            )
        )

        strict_missing = sorted(
            key
            for key in LOCAL_DEMO_REQUIRED_NON_EMPTY_CONFIG_KEYS
            if not str(config_by_key.get(key, ("", ""))[0] or "").strip()
        )
        results.append(
            _result(
                "local-demo external credentials complete",
                not strict_missing,
                "configured" if not strict_missing else ", ".join(strict_missing),
            )
        )

        route_mode = str(config_by_key.get(AMAP_ROUTE_GEOMETRY_MODE, ("", ""))[0] or "").strip().lower()
        results.append(
            _result(
                "local-demo route geometry mode real",
                route_mode == "real",
                route_mode or "empty",
            )
        )

        hifleet_enabled = str(config_by_key.get(HIFLEET_ENABLED, ("", ""))[0] or "").strip().lower()
        results.append(
            _result(
                "local-demo Hifleet enabled",
                hifleet_enabled == "true",
                hifleet_enabled or "empty",
            )
        )

        cos_enabled = str(config_by_key.get(COS_ENABLED, ("", ""))[0] or "").strip().lower()
        results.append(
            _result(
                "local-demo COS enabled",
                cos_enabled == "true",
                cos_enabled or "empty",
            )
        )

        config_test_rows = (
            (
                await session.execute(
                    select(
                        SystemConfig.config_profile_code,
                        SystemConfig.last_test_status_code,
                    ).where(SystemConfig.config_profile_code.in_(LOCAL_DEMO_CONFIG_TEST_PROFILES))
                )
            )
            .all()
        )
        test_statuses_by_profile: dict[str, set[str | None]] = defaultdict(set)
        for profile_code, status_code in config_test_rows:
            test_statuses_by_profile[profile_code].add(status_code)
        profiles_without_success = sorted(
            profile_code
            for profile_code in LOCAL_DEMO_CONFIG_TEST_PROFILES
            if "SUCCESS" not in test_statuses_by_profile.get(profile_code, set())
        )
        results.append(
            _result(
                "local-demo external connection tests successful",
                not profiles_without_success,
                "all successful" if not profiles_without_success else ", ".join(profiles_without_success),
            )
        )

        local_values = {
            key: value
            for key, value in load_local_private_values(source="auto").items()
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
