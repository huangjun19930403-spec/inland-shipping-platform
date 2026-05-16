from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from main import app
from app.core.exceptions import AppException, ConflictError, ValidationError
from app.models.vessel import VesselProfileSummary, VesselRecognitionFieldDiff
from app.models.vessel import VesselAisSnapshot, VesselAisCitySnapshotItem, VesselLatestPositionSnapshot
from app.tasks import vessel_position_tasks
from app.modules.vessel import service as vessel_service_module
from app.modules.vessel.ais.methods import _public_ais_error_message
from app.modules.vessel.ais.service import VesselAisService
from app.modules.vessel.compliance import methods as vessel_compliance_methods
from app.modules.vessel.profile_card import methods as vessel_profile_card_methods
from app.modules.vessel.service import (
    CURRENT_CITY_SOURCE_ADMIN_BOUNDARY,
    CURRENT_CITY_SOURCE_INVALID_POSITION,
    CURRENT_CITY_SOURCE_UNKNOWN,
    LOW_CONFIDENCE_SCORE_THRESHOLD,
    REQUIRED_VESSEL_CERTIFICATE_TYPES,
    UNKNOWN_CITY_NAME,
    VesselService,
    _CityBoundary,
    _boundary_paths_for_precision,
    _build_city_boundary_grid,
    _ensure_relation_writable,
    _ais_freshness_level,
    _quality_fingerprint,
    _relation_is_effective,
    _risk_fingerprint,
)
from app.modules.vessel.schemas import (
    VesselPositionCitySituationItemResponse,
    VesselPositionCitySituationQuery,
    VesselPositionCitySituationResponse,
    VesselPositionCitySituationSummary,
    VesselPositionCityVesselsResponse,
    VesselPositionNavigationChannelSituationQuery,
    VesselPositionNavigationChannelSituationResponse,
    VesselPositionNavigationChannelSituationSummary,
    VesselPositionNavigationChannelVesselsResponse,
    VesselPositionMonitorQuery,
)


def test_vessel_certificate_update_route_uses_json_body() -> None:
    operation = app.openapi()["paths"]["/api/v1/vessels/{vessel_id}/certificates/{certificate_id}"]["put"]

    assert "requestBody" in operation
    assert all(item["name"] != "body" for item in operation.get("parameters", []))


def test_vessel_dashboard_routes_removed() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/vessels/dashboard" not in paths
    assert "/api/v1/vessels/statistics/overview" not in paths


def test_vessel_person_certificate_upload_first_routes_exist() -> None:
    paths = app.openapi()["paths"]

    upload_operation = paths["/api/v1/vessels/{vessel_id}/person-certificate-files"]["post"]
    assert "post" in paths["/api/v1/vessels/{vessel_id}/person-certificate-files"]
    request_body = upload_operation.get("requestBody", {}).get("content", {}).get("multipart/form-data", {})
    schema_ref = request_body.get("schema", {}).get("$ref", "")
    schema_name = schema_ref.rsplit("/", 1)[-1]
    schema = app.openapi()["components"]["schemas"].get(schema_name, {})
    assert "crew_assignment_id" in schema.get("required", [])
    assert "post" in paths[
        "/api/v1/vessels/{vessel_id}/person-certificates/{person_certificate_id}/image-recognitions"
    ]
    assert "post" in paths[
        "/api/v1/vessels/{vessel_id}/person-certificates/{person_certificate_id}/image-recognitions/{recognition_id}/confirm"
    ]
    assert "get" in paths[
        "/api/v1/vessels/{vessel_id}/person-certificates/{person_certificate_id}/image-recognitions"
    ]


def test_vessel_owner_document_routes_exist() -> None:
    paths = app.openapi()["paths"]

    assert "post" in paths["/api/v1/vessels/{vessel_id}/owners/{owner_id}/documents"]
    assert "delete" in paths["/api/v1/vessels/{vessel_id}/owners/{owner_id}/documents/{owner_document_id}"]
    assert "post" in paths[
        "/api/v1/vessels/{vessel_id}/owners/{owner_id}/documents/{owner_document_id}/image-recognitions/{recognition_id}/confirm"
    ]
    assert "get" in paths[
        "/api/v1/vessels/{vessel_id}/owners/{owner_id}/documents/{owner_document_id}/image-recognitions"
    ]


def test_vessel_round1_relation_and_ocr_routes_exist() -> None:
    paths = app.openapi()["paths"]

    assert "post" in paths["/api/v1/vessels/{vessel_id}/owners"]
    assert "patch" in paths["/api/v1/vessels/{vessel_id}/owners/{owner_id}"]
    assert "post" in paths["/api/v1/vessels/{vessel_id}/owners/{owner_id}/end"]
    assert "post" in paths["/api/v1/vessels/{vessel_id}/owners/{owner_id}/void"]
    assert "post" in paths["/api/v1/vessels/{vessel_id}/owners/{owner_id}/set-primary"]
    assert "post" in paths["/api/v1/vessels/{vessel_id}/operators"]
    assert "post" in paths["/api/v1/vessels/{vessel_id}/operators/{operator_period_id}/set-primary"]
    assert "post" in paths["/api/v1/vessels/{vessel_id}/contacts"]
    assert "post" in paths["/api/v1/vessels/{vessel_id}/contacts/{contact_id}/set-primary"]
    assert "post" in paths["/api/v1/vessels/{vessel_id}/crew"]
    assert "post" in paths["/api/v1/vessels/{vessel_id}/crew/{crew_id}/void"]
    assert "get" in paths["/api/v1/vessels/{vessel_id}/quality-issues"]
    assert "get" in paths[
        "/api/v1/vessels/{vessel_id}/certificates/{certificate_id}/image-recognitions/{recognition_id}/field-diff"
    ]
    assert "post" in paths[
        "/api/v1/vessels/{vessel_id}/certificates/{certificate_id}/image-recognitions/{recognition_id}/adoptions"
    ]
    assert "get" in paths[
        "/api/v1/vessels/{vessel_id}/person-certificates/{person_certificate_id}/image-recognitions/{recognition_id}/field-diff"
    ]
    assert "post" in paths[
        "/api/v1/vessels/{vessel_id}/owners/{owner_id}/documents/{owner_document_id}/image-recognitions/{recognition_id}/adoptions"
    ]


def test_vessel_round2_asset_center_routes_exist_before_dynamic_id() -> None:
    paths = app.openapi()["paths"]

    assert "get" in paths["/api/v1/vessels/assets"]
    assert "get" in paths["/api/v1/vessels/quality"]
    assert "get" in paths["/api/v1/vessels/{vessel_id}/profile-card"]
    assert "get" in paths["/api/v1/vessels/ais/city-situation"]
    assert "get" in paths["/api/v1/vessels/ais/positions"]
    assert "get" in paths["/api/v1/vessels/ais/city-vessels"]
    assert "get" in paths["/api/v1/vessels/ais/city-boundaries"]
    assert "get" in paths["/api/v1/vessels/ais/snapshots/{snapshot_id}"]
    assert "get" in paths["/api/v1/vessels/ais/unmatched-mmsi"]
    assert "get" in paths["/api/v1/vessels/ais/vessels/{vessel_id}/situation-card"]

    ais_parameters = paths["/api/v1/vessels/ais/city-situation"]["get"].get("parameters", [])
    public_param_names = {item["name"] for item in ais_parameters}
    assert "es_batch_size" not in public_param_names
    assert "es_max_concurrency" not in public_param_names
    assert "profile_limit" not in public_param_names
    assert "max_profiles" not in public_param_names
    assert "force_refresh" not in public_param_names
    assert "contact_available" not in public_param_names
    for ais_path in ["/api/v1/vessels/ais/positions", "/api/v1/vessels/ais/city-vessels"]:
        ais_param_names = {item["name"] for item in paths[ais_path]["get"].get("parameters", [])}
        assert "contact_available" not in ais_param_names
        assert "es_batch_size" not in ais_param_names
        assert "es_max_concurrency" not in ais_param_names
        assert "profile_limit" not in ais_param_names
    for legacy_path in [
        "/api/v1/vessels/position-monitor/city-situation",
        "/api/v1/vessels/position-monitor/city-vessels",
    ]:
        legacy_param_names = {item["name"] for item in paths[legacy_path]["get"].get("parameters", [])}
        assert "es_batch_size" not in legacy_param_names
        assert "es_max_concurrency" not in legacy_param_names
        assert "profile_limit" not in legacy_param_names
        assert "max_profiles" not in legacy_param_names
        assert "force_refresh" not in legacy_param_names

    owner_parameters = paths["/api/v1/vessels/{vessel_id}/owners"]["get"].get("parameters", [])
    assert any(item["name"] == "current_only" and item["schema"].get("default") is True for item in owner_parameters)

    profile_card_schema_ref = paths["/api/v1/vessels/{vessel_id}/profile-card"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    profile_card_schema = app.openapi()["components"]["schemas"][profile_card_schema_ref.rsplit("/", 1)[-1]]
    profile_card_props = set(profile_card_schema["properties"])
    assert "identity_card" in profile_card_props
    assert "relation_card" in profile_card_props
    assert "certificates" not in profile_card_props
    assert "files" not in profile_card_props

    ais_card_schema_ref = paths["/api/v1/vessels/ais/vessels/{vessel_id}/situation-card"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["$ref"]
    ais_card_schema = app.openapi()["components"]["schemas"][ais_card_schema_ref.rsplit("/", 1)[-1]]
    ais_card_props = set(ais_card_schema["properties"])
    assert "data_availability" in ais_card_props
    assert "quality" in ais_card_props
    assert "operation" not in ais_card_props
    assert "business" not in ais_card_props


def test_vessel_ais_service_has_relation_rules_for_compliance_summary() -> None:
    service = VesselAisService.__new__(VesselAisService)

    assert callable(getattr(service, "_owner_required_document_types", None))


def test_vessel_domain_split_keeps_key_openapi_paths() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/vessels/assets": {"get"},
        "/api/v1/vessels/quality": {"get"},
        "/api/v1/vessels/quality/{issue_id}/recheck": {"post"},
        "/api/v1/vessels/governance/dashboard": {"get"},
        "/api/v1/vessels/governance/tasks": {"get"},
        "/api/v1/vessels/governance/tasks/sync": {"post"},
        "/api/v1/vessels/blacklist-signals": {"get"},
        "/api/v1/vessels/{vessel_id}/relation-conclusions": {"get"},
        "/api/v1/vessels/{vessel_id}/controller-evidence": {"get", "post"},
        "/api/v1/vessels/compliance-risks": {"get"},
        "/api/v1/vessels/recognitions": {"get"},
        "/api/v1/vessels/ais/city-situation": {"get"},
        "/api/v1/vessels/candidate-analyses": {"get", "post"},
    }

    for path, methods in expected.items():
        assert path in paths
        assert methods.issubset(paths[path])


def test_vessel_domain_services_are_router_boundaries() -> None:
    from app.modules.vessel.services.asset_service import VesselAssetService
    from app.modules.vessel.services.compliance_service import VesselComplianceService
    from app.modules.vessel.services.governance_task_service import VesselGovernanceTaskService
    from app.modules.vessel.services.quality_service import VesselQualityService
    from app.modules.vessel.services.recognition_service import VesselRecognitionService
    from app.modules.vessel.services.relation_service import VesselRelationService

    services = {
        VesselAssetService: ("asset_summary", "list_assets"),
        VesselQualityService: ("list_quality_issue_queue", "recheck_quality_issue"),
        VesselComplianceService: ("list_compliance_risks", "create_risk_review"),
        VesselRelationService: ("list_controller_evidence", "list_relation_conclusions"),
        VesselRecognitionService: ("list_recognition_queue", "unified_recognition_field_diff"),
        VesselGovernanceTaskService: ("dashboard", "sync_tasks_command"),
    }

    for service_cls, method_names in services.items():
        service = service_cls(SimpleNamespace())
        for method_name in method_names:
            assert callable(getattr(service, method_name))


def test_vessel_compliance_actions_use_backend_rule_map() -> None:
    from app.modules.vessel.services.compliance_rules import (
        compliance_risk_action_label,
        compliance_risk_action_path,
        compliance_risk_required_fields,
    )

    controller_risk = SimpleNamespace(id=7, vessel_profile_id=12, risk_type_code="CONTROLLER_UNKNOWN", evidence_json={})
    blacklist_risk = SimpleNamespace(
        id=8,
        vessel_profile_id=13,
        risk_type_code="OTHER",
        evidence_json={"blacklist_signal_id": 99},
    )

    assert compliance_risk_action_label(controller_risk) == "补充控制人证据"
    assert compliance_risk_action_path(controller_risk) == "/vessels/12/relations?tab=controller&risk_signal_id=7"
    assert "verified_status_code" in compliance_risk_required_fields(controller_risk)
    assert compliance_risk_action_path(blacklist_risk) == "/vessels/blacklist-signals?risk_signal_id=8&vessel_id=13&blacklist_signal_id=99"


def test_vessel_seed_menu_groups_keep_business_entries_visible() -> None:
    from scripts.seeds.loaders.system_base import MENUS, ROLE_MENU_CODES

    menu_by_code = {item["menu_code"]: item for item in MENUS}
    assert "VESSEL_SHIP_ANALYSIS" not in menu_by_code
    assert menu_by_code["ANALYSIS_SHIPS"]["parent_code"] == "VESSEL_ASSET_GROUP"
    visible_group_codes = {
        "VESSEL_WORKBENCH_GROUP",
        "VESSEL_ASSET_GROUP",
        "VESSEL_ANALYSIS_GROUP",
    }
    hidden_group_codes = {
        "VESSEL_GOVERNANCE_GROUP",
        "VESSEL_CARGO_ANALYSIS_GROUP",
    }
    assert visible_group_codes.issubset(menu_by_code)
    assert hidden_group_codes.issubset(menu_by_code)
    for code in visible_group_codes | hidden_group_codes:
        assert menu_by_code[code]["parent_code"] == "VESSEL_ROOT"
        assert menu_by_code[code]["menu_type_code"] == "DIRECTORY"
    for code in visible_group_codes:
        assert menu_by_code[code]["visible_flag"] == 1
    for code in hidden_group_codes:
        assert menu_by_code[code]["visible_flag"] == 0

    expected_parent = {
        "VESSEL_GOVERNANCE_DASHBOARD": "VESSEL_WORKBENCH_GROUP",
        "VESSEL_GOVERNANCE_TASKS": "VESSEL_WORKBENCH_GROUP",
        "VESSEL_ASSETS": "VESSEL_ASSET_GROUP",
        "VESSEL_PROFILE_ENTRY": "VESSEL_ASSET_GROUP",
        "ANALYSIS_SHIPS": "VESSEL_ASSET_GROUP",
        "VESSEL_QUALITY": "VESSEL_WORKBENCH_GROUP",
        "VESSEL_RELATIONS_ENTRY": "VESSEL_WORKBENCH_GROUP",
        "VESSEL_COMPLIANCE_RISKS": "VESSEL_WORKBENCH_GROUP",
        "VESSEL_BLACKLIST_SIGNALS": "VESSEL_WORKBENCH_GROUP",
        "VESSEL_RECOGNITIONS": "VESSEL_WORKBENCH_GROUP",
        "VESSEL_AIS_SITUATION": "VESSEL_ANALYSIS_GROUP",
        "VESSEL_NODE_ROUTE_ANALYSIS": "VESSEL_ANALYSIS_GROUP",
        "VESSEL_CANDIDATE_ANALYSIS": "VESSEL_ROOT",
    }
    for code, parent_code in expected_parent.items():
        assert menu_by_code[code]["parent_code"] == parent_code

    required_codes = {"OVERVIEW_ROOT", "DASHBOARD", "VESSEL_ROOT", *visible_group_codes, *expected_parent}
    for role_code in ("DATA_STEWARD", "OPS_ANALYST"):
        assert required_codes.issubset(set(ROLE_MENU_CODES[role_code]))


def test_vessel_round3_asset_summary_routes_and_schema_exist() -> None:
    paths = app.openapi()["paths"]

    assert "get" in paths["/api/v1/vessels/assets/summary"]
    assert "post" in paths["/api/v1/vessels/{vessel_id}/summary/refresh"]

    asset_schema_ref = paths["/api/v1/vessels/assets"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    asset_schema = app.openapi()["components"]["schemas"][asset_schema_ref.rsplit("/", 1)[-1]]
    assert {
        "coverage_rate",
        "confidence_level",
        "summary_status_counts",
        "source_updated_at",
        "uncertainty_reasons",
    }.issubset(asset_schema["properties"])

    item_schema_ref = asset_schema["properties"]["items"]["items"]["$ref"]
    item_schema = app.openapi()["components"]["schemas"][item_schema_ref.rsplit("/", 1)[-1]]
    item_props = set(item_schema["properties"])
    assert "profile_completeness_rate" in item_props
    assert "data_quality_level" in item_props
    assert "summary_status_code" in item_props
    assert "risk_evidence_summary" in item_props
    assert "dispatchable_status_code" not in item_props
    assert "operation_pool_status_code" not in item_props


def test_vessel_round4_profile_card_contract_is_evidence_first() -> None:
    paths = app.openapi()["paths"]

    assert "get" in paths["/api/v1/vessels/{vessel_id}/profile-card/evidence"]
    evidence_parameters = paths["/api/v1/vessels/{vessel_id}/profile-card/evidence"]["get"].get("parameters", [])
    assert any(item["name"] == "section" for item in evidence_parameters)

    profile_card_schema_ref = paths["/api/v1/vessels/{vessel_id}/profile-card"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    profile_card_schema = app.openapi()["components"]["schemas"][profile_card_schema_ref.rsplit("/", 1)[-1]]
    profile_card_props = set(profile_card_schema["properties"])

    assert {
        "summary_status_code",
        "refresh_available",
        "stale",
        "source_trace",
        "identity_card",
        "relation_card",
        "quality_card",
        "compliance_card",
        "trajectory_card",
        "ais_card",
        "recognition_card",
        "candidate_card",
    }.issubset(profile_card_props)
    assert {"certificates", "files", "owners", "operators", "contacts"}.isdisjoint(profile_card_props)

    forbidden_fragments = [
        "dispatch",
        "quote",
        "deal",
        "operation_pool",
        "contact_ship",
    ]
    assert not any(fragment in "|".join(sorted(profile_card_props)) for fragment in forbidden_fragments)


def test_vessel_round5_compliance_and_ocr_workbench_routes_exist() -> None:
    paths = app.openapi()["paths"]
    schemas = app.openapi()["components"]["schemas"]

    assert "get" in paths["/api/v1/vessels/compliance-risks"]
    assert "get" in paths["/api/v1/vessels/compliance-rules"]
    assert "post" in paths["/api/v1/vessels/compliance-rules"]
    assert "patch" in paths["/api/v1/vessels/compliance-rules/{rule_id}"]
    assert "post" in paths["/api/v1/vessels/compliance-rules/{rule_id}/void"]
    assert "get" in paths["/api/v1/vessels/{vessel_id}/compliance-risk"]
    assert "post" in paths["/api/v1/vessels/{vessel_id}/compliance-risk/refresh"]
    assert "patch" in paths["/api/v1/vessels/{vessel_id}/risk-signals/{signal_id}"]
    assert "get" in paths["/api/v1/vessels/{vessel_id}/controller-evidence"]
    assert "post" in paths["/api/v1/vessels/{vessel_id}/controller-evidence"]
    assert "patch" in paths["/api/v1/vessels/{vessel_id}/controller-evidence/{evidence_id}"]
    assert "post" in paths["/api/v1/vessels/{vessel_id}/controller-evidence/{evidence_id}/void"]
    assert "get" in paths["/api/v1/vessels/{vessel_id}/affiliation-evidence"]
    assert "post" in paths["/api/v1/vessels/{vessel_id}/affiliation-evidence"]
    assert "patch" in paths["/api/v1/vessels/{vessel_id}/affiliation-evidence/{evidence_id}"]
    assert "post" in paths["/api/v1/vessels/{vessel_id}/affiliation-evidence/{evidence_id}/void"]
    assert "get" in paths["/api/v1/vessels/recognitions"]
    assert "get" in paths["/api/v1/vessels/recognitions/{recognition_type}/{recognition_id}/field-diff"]
    assert "post" in paths["/api/v1/vessels/recognitions/{recognition_type}/{recognition_id}/adoptions"]

    risk_schema = schemas["VesselRiskSignalResponse"]["properties"]
    assert {
        "risk_type_code",
        "risk_level",
        "rule_code",
        "fingerprint",
        "evidence_json",
        "source_trace_json",
        "uncertainty_notes_json",
        "revision",
    }.issubset(risk_schema)

    risk_update_required = set(schemas["VesselRiskSignalUpdateRequest"]["required"])
    assert {"revision", "status_code", "resolution_reason", "evidence_json"}.issubset(risk_update_required)

    compliance_schema = schemas["VesselComplianceRiskResponse"]["properties"]
    assert {"overall_risk_level", "rule_summary", "signals", "uncertainty_notes"}.issubset(compliance_schema)

    recognition_schema = schemas["VesselRecognitionQueueItemResponse"]["properties"]
    assert {"recognition_type", "pending_diff_count", "low_confidence_diff_count", "adoption_count"}.issubset(
        recognition_schema
    )

    forbidden_fragments = ["dispatch", "quote", "candidate_score", "contact_ship"]
    checked_props = "|".join(sorted(set(risk_schema) | set(compliance_schema) | set(recognition_schema)))
    assert not any(fragment in checked_props for fragment in forbidden_fragments)


def test_vessel_round5_risk_fingerprint_is_profile_rule_and_evidence_scoped() -> None:
    first = _risk_fingerprint(1, "CERTIFICATE_MISSING", "REQ_CERT", "certificate_type|VESSEL_AIS_CERT")
    second = _risk_fingerprint(1, "CERTIFICATE_MISSING", "REQ_CERT", " certificate_type|VESSEL_AIS_CERT ")
    different_profile = _risk_fingerprint(2, "CERTIFICATE_MISSING", "REQ_CERT", "certificate_type|VESSEL_AIS_CERT")
    different_rule = _risk_fingerprint(1, "CERTIFICATE_MISSING", "REQ_OTHER", "certificate_type|VESSEL_AIS_CERT")

    assert first == second
    assert first != different_profile
    assert first != different_rule


def test_vessel_round5_context_scoped_rules_require_matching_context() -> None:
    service = VesselService.__new__(VesselService)
    profile = SimpleNamespace(ship_type_code="DRY_BULK")
    cargo_rule = SimpleNamespace(
        scope_type_code="CARGO_CATEGORY",
        ship_type_code=None,
        cargo_category_code="COAL",
        route_area_code=None,
        condition_json=None,
    )
    route_rule = SimpleNamespace(
        scope_type_code="ROUTE_AREA",
        ship_type_code=None,
        cargo_category_code=None,
        route_area_code="YANGTZE",
        condition_json=None,
    )
    profile_with_context = SimpleNamespace(
        ship_type_code="DRY_BULK",
        cargo_category_code="COAL",
        route_area_code="YANGTZE",
    )

    assert service._rule_matches_profile_context(cargo_rule, profile) is False
    assert service._rule_matches_profile_context(route_rule, profile) is False
    assert service._rule_matches_profile_context(cargo_rule, profile_with_context) is True
    assert service._rule_matches_profile_context(route_rule, profile_with_context) is True
    assert service._compliance_context_gap(profile)["not_computable"] is True
    assert service._compliance_context_gap(profile_with_context)["not_computable"] is False


@pytest.mark.asyncio
async def test_vessel_round5_not_computable_gap_blocks_low_overall() -> None:
    service = VesselService.__new__(VesselService)
    profile = SimpleNamespace(id=1, ship_type_code="DRY_BULK")

    async def require_profile(_vessel_id: int):
        return profile

    async def active_rules(_profile):
        return [SimpleNamespace(rule_code="REQ_GLOBAL")]

    async def empty_rule_summary(_vessel_id: int, _rules):
        return []

    async def empty_profiles(_ids):
        return {}

    service._require_profile = require_profile  # type: ignore[method-assign]
    service._active_certificate_rules = active_rules  # type: ignore[method-assign]
    service._certificate_rule_summary = empty_rule_summary  # type: ignore[method-assign]
    service._profiles_by_ids = empty_profiles  # type: ignore[method-assign]

    result = await service._compliance_risk_response(1, [], {}, engine_refreshed=True)

    assert result.overall_risk_level == "UNKNOWN"
    assert result.engine_status_code == "NOT_COMPUTABLE"
    assert any("NOT_COMPUTABLE" in note for note in result.uncertainty_notes)


@pytest.mark.asyncio
async def test_vessel_round5_refresh_failure_returns_explainable_status(monkeypatch) -> None:
    service = VesselService.__new__(VesselService)
    events: list[str] = []

    class FakeDb:
        async def rollback(self) -> None:
            events.append("rollback")

    async def label_map(_db):
        return {}

    async def require_profile(vessel_id: int):
        return SimpleNamespace(id=vessel_id, ship_type_code="DRY_BULK")

    async def fail_evaluate(_profile):
        raise RuntimeError("engine failed")

    async def active_signals(_vessel_id: int):
        return []

    async def response(_vessel_id: int, _signals, _label_map, **kwargs):
        return SimpleNamespace(
            engine_status_code=kwargs.get("engine_status_code"),
            uncertainty_notes=kwargs.get("extra_uncertainty_notes") or [],
        )

    monkeypatch.setattr(vessel_compliance_methods, "_load_label_map", label_map)
    service.db = FakeDb()
    service._require_profile = require_profile  # type: ignore[method-assign]
    service._evaluate_compliance_risks = fail_evaluate  # type: ignore[method-assign]
    service._active_risk_signals = active_signals  # type: ignore[method-assign]
    service._compliance_risk_response = response  # type: ignore[method-assign]

    result = await service.refresh_compliance_risk(1)

    assert events == ["rollback"]
    assert result.engine_status_code == "FAILED"
    assert result.uncertainty_notes


@pytest.mark.asyncio
async def test_vessel_round4_profile_card_uses_current_relations_and_certificate_evidence(monkeypatch) -> None:
    now = datetime(2026, 5, 9, 12, 0, 0)
    service = VesselService.__new__(VesselService)

    profile = SimpleNamespace(
        id=1,
        vessel_profile_code="VP-001",
        vessel_identity_id=None,
        ship_name="测试船",
        ship_name_en=None,
        current_mmsi="413000001",
        ship_type_code="DRY_BULK",
        profile_status_code="ACTIVE",
        identity_status_code="VERIFIED",
        operation_status_code=None,
        home_port_code=None,
        home_port_name=None,
        registry_city_code=None,
        business_region_id=None,
        source_type_code="MANUAL",
        audit_status="APPROVED",
        remark=None,
        created_at=now,
        updated_at=now,
    )
    summary = SimpleNamespace(
        summary_status_code="READY",
        uncertainty_notes_json=[],
        refresh_error=None,
        data_quality_level="HIGH",
        identity_confidence_level="HIGH",
        subject_consistency_level="UNKNOWN",
        risk_level="LOW",
        refreshed_at=now,
        source_updated_at=now,
        coverage_rate=Decimal("100"),
        latest_position_time=None,
        ais_freshness_level="UNKNOWN",
        ais_unavailable_reason=None,
        ship_name="测试船",
        current_mmsi="413000001",
        ship_type_code="DRY_BULK",
        ship_type_name="干散货船",
        deadweight_ton=Decimal("1000"),
        length_m=Decimal("60"),
        width_m=Decimal("12"),
        design_draft_m=Decimal("3.2"),
        latest_city_code=None,
        latest_city_name=None,
        primary_owner_name=None,
        primary_operator_name=None,
        primary_contact_name=None,
        primary_contact_phone_masked=None,
        profile_completeness_rate=Decimal("100"),
        data_quality_score=Decimal("95"),
        missing_field_count=0,
        conflict_count=0,
        certificate_missing_count=0,
        certificate_expiring_count=0,
        certificate_expired_count=0,
        risk_evidence_summary_json=[],
    )
    ended_owner = SimpleNamespace(
        id=10,
        party_name="历史所有方",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        is_current=False,
        is_primary=True,
        voided_at=None,
        void_reason=None,
        source_type_code="MANUAL",
        revision=1,
        verified_status_code="VERIFIED",
        created_at=now,
        updated_at=now,
    )

    class FakeDb:
        def __init__(self) -> None:
            self.calls = 0

        async def scalar(self, _stmt):
            self.calls += 1
            return summary if self.calls == 1 else 3

    class FakeRepo:
        async def get_one_by_profile(self, _model, _vessel_id):
            return SimpleNamespace(deadweight_ton=Decimal("1000"), length_m=Decimal("60"), width_m=Decimal("12"), design_draft_m=Decimal("3.2"))

        async def list_by_profile(self, model, _vessel_id, order_desc: bool = False):
            if model.__name__ == "VesselOwnerPeriod":
                return [ended_owner]
            return []

    async def require_profile(_vessel_id: int):
        return profile

    async def no_active_issues(_vessel_id: int):
        return []

    async def empty_recognition(_vessel_id: int):
        return {
            "pending_diff_count": 0,
            "low_confidence_diff_count": 0,
            "active_task_count": 0,
            "adoption_count": 0,
            "latest_adoption": None,
            "updated_at": None,
        }

    async def empty_map(_db, *args, **kwargs):
        return {}

    monkeypatch.setattr(vessel_profile_card_methods, "_load_label_map", empty_map)
    monkeypatch.setattr(vessel_profile_card_methods, "_load_city_map", empty_map)
    monkeypatch.setattr(vessel_profile_card_methods, "_load_region_map", empty_map)
    service.db = FakeDb()
    service.repo = FakeRepo()
    service._require_profile = require_profile  # type: ignore[method-assign]
    service._summary_active_issues = no_active_issues  # type: ignore[method-assign]
    service._recognition_card_metrics = empty_recognition  # type: ignore[method-assign]

    result = await service.get_profile_card(1)

    assert result.relation_card.status_code == "UNKNOWN"
    assert result.relation_card.current_relation_count == 0
    assert result.relation_card.history_relation_count == 1
    assert "当前有效主体关系缺失" in result.relation_card.uncertainty_notes
    assert result.compliance_card.evidence_count == 3


@pytest.mark.asyncio
async def test_vessel_round4_identity_evidence_includes_current_profile() -> None:
    now = datetime(2026, 5, 9, 12, 0, 0)
    service = VesselService.__new__(VesselService)
    profile = SimpleNamespace(
        id=1,
        vessel_profile_code="VP-001",
        ship_name="测试船",
        current_mmsi="413000001",
        ship_type_code="DRY_BULK",
        profile_status_code="ACTIVE",
        identity_status_code="VERIFIED",
        registry_city_code=None,
        source_type_code="MANUAL",
        created_at=now,
        updated_at=now,
    )

    class FakeRepo:
        async def get_one_by_profile(self, _model, _vessel_id):
            return SimpleNamespace(deadweight_ton=Decimal("1000"), length_m=Decimal("60"), width_m=Decimal("12"), design_draft_m=Decimal("3.2"))

        async def list_by_profile(self, _model, _vessel_id, order_desc: bool = False):
            return []

    async def require_profile(_vessel_id: int):
        return profile

    service.repo = FakeRepo()
    service._require_profile = require_profile  # type: ignore[method-assign]

    result = await service.get_profile_card_evidence(1, SimpleNamespace(section="identity", page=1, page_size=20))

    assert result.total == 1
    assert result.items[0].object_type == "VESSEL_PROFILE"
    assert result.items[0].payload["current_mmsi"] == "413000001"


def test_vessel_round3_summary_model_and_freshness_thresholds() -> None:
    assert VesselProfileSummary.__tablename__ == "vessel_profile_summary"
    assert _ais_freshness_level(None) == "UNKNOWN"
    assert _ais_freshness_level(120) == "FRESH"
    assert _ais_freshness_level(121) == "RECENT"
    assert _ais_freshness_level(720) == "RECENT"
    assert _ais_freshness_level(721) == "STALE"
    assert _ais_freshness_level(1440) == "STALE"
    assert _ais_freshness_level(1441) == "STALE"
    assert _ais_freshness_level(4320) == "STALE"
    assert _ais_freshness_level(4321) == "EXPIRED"


def test_vessel_ais_public_error_message_hides_es_internals() -> None:
    raw = 'Realtime ES 请求失败: status=400, body={"error":{"type":"parse_exception","reason":"failed to parse date field"}}'

    assert _public_ais_error_message(raw) == "部分实时 AIS 数据暂不可用，请稍后刷新或检查实时数据源配置"


def test_vessel_round6_ais_snapshot_models_and_schema_exist() -> None:
    assert VesselAisSnapshot.__tablename__ == "vessel_ais_snapshot"
    assert VesselAisCitySnapshotItem.__tablename__ == "vessel_ais_city_snapshot_item"
    assert VesselLatestPositionSnapshot.__tablename__ == "vessel_latest_position_snapshot"

    schemas = app.openapi()["components"]["schemas"]
    summary_props = schemas["VesselPositionCitySituationSummary"]["properties"]
    assert {
        "query_snapshot_id",
        "snapshot_status_code",
        "snapshot_expires_at",
        "coverage_rate",
        "freshness_distribution",
        "unmatched_mmsi_count",
        "source_indices",
        "uncertainty_notes",
    }.issubset(summary_props)
    item_props = schemas["VesselPositionMonitorItemResponse"]["properties"]
    assert {"freshness_level", "match_status_code", "source_index"}.issubset(item_props)


@pytest.mark.asyncio
async def test_vessel_city_situation_uses_cache_snapshot_without_db_persistence() -> None:
    service = VesselService.__new__(VesselService)
    events: list[str] = []

    class FakeDb:
        async def rollback(self) -> None:
            raise AssertionError("city situation should not rollback a DB transaction")

        async def commit(self) -> None:
            raise AssertionError("city situation should not commit a DB transaction")

        async def execute(self, _stmt):
            raise AssertionError("city situation should not query or write DB snapshots")

    generated_at = datetime(2026, 5, 9, 12, 0, 0)
    item = SimpleNamespace(id=1, position_time=generated_at, contact_available=True, freshness_level="FRESH")
    city = VesselPositionCitySituationItemResponse(
        city_code="320500",
        city_name="苏州市",
        positioned_count=1,
        contactable_position_count=0,
        matched_position_count=1,
    )

    async def cache_backend() -> str:
        return "memory"

    async def limits() -> dict[str, int]:
        return {"profile_limit": 10, "es_batch_size": 10, "es_max_concurrency": 1, "unmatched_scan_limit": 10}

    async def no_cached(_cache_key):
        return None

    async def profile_count(_query) -> int:
        return 1

    async def profiles(_query, limit: int):
        assert limit == 10
        return [SimpleNamespace(id=1)]

    async def realtime_host() -> str:
        return "http://es.example"

    async def positions_for_profiles(*args, **kwargs):
        assert kwargs["include_unmatched"] is False
        assert kwargs["unmatched_scan_limit"] == 0
        return SimpleNamespace(
            items=[item],
            unmatched_positions=[],
            invalid_positions=[],
            partial=False,
            error_message=None,
            queried_mmsi_count=1,
            matched_position_count=0,
            unpositioned_count=1,
            invalid_position_count=0,
            unknown_city_count=0,
            source_indices=["ship_positions"],
            failed_batch_count=0,
        )

    async def risk_by_profile(_ids):
        return {}

    async def boundaries():
        return []

    async def store_snapshot(*args, **kwargs) -> str:
        events.append("cache-snapshot")
        return "cache-snapshot-only"

    async def store_response_cache(*args, **kwargs) -> None:
        events.append("response-cache")

    service.db = FakeDb()
    service._city_cache_backend = cache_backend  # type: ignore[method-assign]
    service._ais_runtime_limits = limits  # type: ignore[method-assign]
    service._get_city_situation_response_cache = no_cached  # type: ignore[method-assign]
    service._position_monitor_profile_count = profile_count  # type: ignore[method-assign]
    service._position_monitor_profiles = profiles  # type: ignore[method-assign]
    service._realtime_es_host = realtime_host  # type: ignore[method-assign]
    service._position_monitor_items_for_profiles = positions_for_profiles  # type: ignore[method-assign]
    service._compliance_risk_by_profile = risk_by_profile  # type: ignore[method-assign]
    service._city_boundaries = boundaries  # type: ignore[method-assign]
    service._city_situation_items = lambda *args, **kwargs: [city]  # type: ignore[method-assign]
    service._store_city_situation_snapshot = store_snapshot  # type: ignore[method-assign]
    service._store_city_situation_response_cache = store_response_cache  # type: ignore[method-assign]

    result = await service.position_city_situation(
        VesselPositionCitySituationQuery(reported_within_minutes=1440, include_boundary=False)
    )

    assert result.summary.query_snapshot_id == "cache-snapshot-only"
    assert result.summary.snapshot_status_code == "READY"
    assert result.summary.refresh_required is False
    assert events == ["cache-snapshot", "response-cache"]


@pytest.mark.asyncio
async def test_vessel_city_situation_uses_realtime_cache_before_live_query() -> None:
    service = VesselService.__new__(VesselService)
    events: list[str] = []
    generated_at = datetime(2026, 5, 10, 8, 0, 0)
    cached_response = VesselPositionCitySituationResponse(
        source_status="AVAILABLE",
        source_status_name="可用",
        generated_at=generated_at,
        cache_status="MISS",
        cache_generated_at=generated_at,
        snapshot_backend="redis",
        summary=VesselPositionCitySituationSummary(
            matched_profile_count=3,
            scanned_profile_count=3,
            queried_mmsi_count=3,
            matched_position_count=3,
            unpositioned_count=0,
            positioned_count=3,
            stale_position_count=0,
            contactable_position_count=3,
            certificate_risk_count=0,
            city_count=2,
            query_snapshot_id="redis-current-ais",
            snapshot_status_code="READY",
            snapshot_expires_at=generated_at + timedelta(days=365),
            is_partial=False,
        ),
        cities=[],
    )

    async def cache_backend() -> str:
        events.append("backend")
        return "redis"

    async def no_cached(_cache_key: str):
        events.append("cache-read")
        return cached_response, "redis"

    async def live_limits():
        raise AssertionError("city situation should not load live ES limits when a realtime cache is available")

    service._city_cache_backend = cache_backend  # type: ignore[method-assign]
    service._get_city_situation_response_cache = no_cached  # type: ignore[method-assign]
    service._ais_runtime_limits = live_limits  # type: ignore[method-assign]

    result = await service.position_city_situation(
        VesselPositionCitySituationQuery(reported_within_minutes=1600, include_boundary=False)
    )

    assert result.cache_status == "HIT"
    assert result.summary.query_snapshot_id == "redis-current-ais"
    assert events == ["backend", "cache-read"]


@pytest.mark.asyncio
async def test_vessel_channel_situation_uses_response_cache_before_live_query() -> None:
    service = VesselService.__new__(VesselService)
    events: list[str] = []
    generated_at = datetime(2026, 5, 10, 8, 0, 0)
    cached_response = VesselPositionNavigationChannelSituationResponse(
        source_status="AVAILABLE",
        source_status_name="可用",
        generated_at=generated_at,
        cache_status="MISS",
        cache_generated_at=generated_at,
        snapshot_backend="redis",
        summary=VesselPositionNavigationChannelSituationSummary(
            matched_profile_count=3,
            scanned_profile_count=3,
            queried_mmsi_count=3,
            matched_position_count=3,
            unpositioned_count=0,
            positioned_count=3,
            stale_position_count=0,
            contactable_position_count=3,
            certificate_risk_count=0,
            channel_count=2,
            query_snapshot_id="redis-channel-ais",
            snapshot_status_code="READY",
            snapshot_expires_at=generated_at + timedelta(days=365),
            is_partial=False,
        ),
        channels=[],
    )

    async def cache_backend() -> str:
        events.append("backend")
        return "redis"

    async def cached(_cache_key: str):
        events.append("cache-read")
        return cached_response, "redis"

    async def live_limits():
        raise AssertionError("channel situation should not load live ES limits when a cache is available")

    service._city_cache_backend = cache_backend  # type: ignore[method-assign]
    service._get_channel_situation_response_cache = cached  # type: ignore[method-assign]
    service._ais_runtime_limits = live_limits  # type: ignore[method-assign]

    result = await service.position_channel_situation(
        VesselPositionNavigationChannelSituationQuery(reported_within_minutes=1600, include_boundary=False)
    )

    assert result.cache_status == "HIT"
    assert result.summary.query_snapshot_id == "redis-channel-ais"
    assert events == ["backend", "cache-read"]


@pytest.mark.asyncio
async def test_vessel_channel_situation_stores_response_cache_on_miss() -> None:
    service = VesselService.__new__(VesselService)
    events: list[str] = []

    async def cache_backend() -> str:
        events.append("backend")
        return "memory"

    async def no_cached(_cache_key: str):
        events.append("cache-read")
        return None

    async def limits() -> dict[str, int]:
        events.append("limits")
        return {"profile_limit": 2000, "es_batch_size": 500, "es_max_concurrency": 4, "unmatched_scan_limit": 1000}

    async def profile_count(_query) -> int:
        events.append("count")
        return 1

    async def profiles(_query, limit: int | None = None):
        events.append(f"profiles:{limit}")
        return [SimpleNamespace(id=1, current_mmsi="413000001")]

    async def realtime_host() -> str:
        events.append("realtime-host")
        return "http://localhost:9200"

    async def positions_for_profiles(*args, **kwargs):
        events.append("positions")
        return SimpleNamespace(
            items=[],
            unmatched_positions=[],
            invalid_positions=[],
            partial=False,
            error_message=None,
            queried_mmsi_count=1,
            matched_position_count=0,
            unpositioned_count=1,
            invalid_position_count=0,
            unknown_city_count=0,
            source_indices=["ship_positions"],
            failed_batch_count=0,
            failed_batches=[],
        )

    async def risk_by_profile(_ids):
        return {}

    async def boundaries():
        return []

    async def store_snapshot(*args, **kwargs) -> str:
        events.append("snapshot")
        return "channel-snapshot"

    async def store_response_cache(*args, **kwargs) -> None:
        events.append("response-cache")

    service._city_cache_backend = cache_backend  # type: ignore[method-assign]
    service._get_channel_situation_response_cache = no_cached  # type: ignore[method-assign]
    service._ais_runtime_limits = limits  # type: ignore[method-assign]
    service._position_monitor_profile_count = profile_count  # type: ignore[method-assign]
    service._position_monitor_profiles = profiles  # type: ignore[method-assign]
    service._realtime_es_host = realtime_host  # type: ignore[method-assign]
    service._position_monitor_items_for_profiles = positions_for_profiles  # type: ignore[method-assign]
    service._compliance_risk_by_profile = risk_by_profile  # type: ignore[method-assign]
    service._summary_risk_level_by_profile = risk_by_profile  # type: ignore[method-assign]
    service._channel_boundaries = boundaries  # type: ignore[method-assign]
    service._store_city_situation_snapshot = store_snapshot  # type: ignore[method-assign]
    service._store_channel_situation_response_cache = store_response_cache  # type: ignore[method-assign]

    result = await service.position_channel_situation(
        VesselPositionNavigationChannelSituationQuery(reported_within_minutes=1440, include_boundary=False, include_empty_channels=False)
    )

    assert result.cache_status == "MISS"
    assert result.summary.query_snapshot_id == "channel-snapshot"
    assert events == [
        "backend",
        "cache-read",
        "limits",
        "count",
        "profiles:2000",
        "realtime-host",
        "positions",
        "snapshot",
        "response-cache",
    ]


@pytest.mark.asyncio
async def test_vessel_channel_situation_force_refresh_skips_response_cache() -> None:
    service = VesselService.__new__(VesselService)
    events: list[str] = []

    async def cache_backend() -> str:
        events.append("backend")
        return "memory"

    async def fail_cached(_cache_key: str):
        raise AssertionError("force refresh should not read the channel response cache")

    async def limits() -> dict[str, int]:
        events.append("limits")
        return {"profile_limit": 2000, "es_batch_size": 500, "es_max_concurrency": 4, "unmatched_scan_limit": 1000}

    async def profile_count(_query) -> int:
        events.append("count")
        return 0

    async def profiles(_query, limit: int | None = None):
        events.append(f"profiles:{limit}")
        return []

    service._city_cache_backend = cache_backend  # type: ignore[method-assign]
    service._get_channel_situation_response_cache = fail_cached  # type: ignore[method-assign]
    service._ais_runtime_limits = limits  # type: ignore[method-assign]
    service._position_monitor_profile_count = profile_count  # type: ignore[method-assign]
    service._position_monitor_profiles = profiles  # type: ignore[method-assign]

    query = VesselPositionNavigationChannelSituationQuery(reported_within_minutes=1440, include_boundary=False, include_empty_channels=False)
    object.__setattr__(query, "force_refresh", True)
    result = await service.position_channel_situation(query)

    assert result.source_status == "EMPTY"
    assert result.cache_status == "MISS"
    assert events == ["backend", "limits", "count", "profiles:2000"]


@pytest.mark.asyncio
async def test_vessel_position_monitor_timeout_without_snapshot_returns_error_response() -> None:
    service = VesselService.__new__(VesselService)
    events: list[str] = []

    class FakeDb:
        async def rollback(self) -> None:
            events.append("rollback")

    async def no_snapshot(*args, **kwargs):
        events.append("snapshot")
        return None

    async def profiles(_query):
        return [
            SimpleNamespace(id=1, current_mmsi="413000001"),
            SimpleNamespace(id=2, current_mmsi="413000002"),
        ]

    async def realtime_host() -> str:
        return "http://localhost:9200"

    async def mmsi_values(_ids):
        return {1: ["413000001"], 2: ["413000002"]}

    async def limits() -> dict[str, int]:
        return {"profile_limit": 2000, "es_batch_size": 500, "es_max_concurrency": 4, "unmatched_scan_limit": 1000}

    async def positions_for_profiles(*args, **kwargs):
        raise asyncio.TimeoutError

    service.db = FakeDb()
    service._position_monitor_from_latest_snapshot = no_snapshot  # type: ignore[method-assign]
    service._position_monitor_profiles = profiles  # type: ignore[method-assign]
    service._realtime_es_host = realtime_host  # type: ignore[method-assign]
    service._mmsi_values_by_profile = mmsi_values  # type: ignore[method-assign]
    service._ais_runtime_limits = limits  # type: ignore[method-assign]
    service._position_monitor_items_for_profiles = positions_for_profiles  # type: ignore[method-assign]

    result = await service.position_monitor(VesselPositionMonitorQuery(reported_within_minutes=1440))

    assert result.source_status == "ERROR"
    assert result.summary.matched_profile_count == 2
    assert result.summary.positioned_count == 0
    assert "实时 AIS 查询超时" in (result.message or "")
    assert events == ["snapshot", "rollback", "snapshot"]


@pytest.mark.asyncio
async def test_vessel_city_situation_timeout_without_snapshot_returns_error_response() -> None:
    service = VesselService.__new__(VesselService)
    events: list[str] = []

    class FakeDb:
        async def rollback(self) -> None:
            events.append("rollback")

    async def cache_backend() -> str:
        return "memory"

    async def limits() -> dict[str, int]:
        return {"profile_limit": 2, "es_batch_size": 500, "es_max_concurrency": 4, "unmatched_scan_limit": 1000}

    async def profile_count(_query) -> int:
        return 5

    async def profiles(_query, limit: int | None = None):
        events.append(f"profiles:{limit}")
        return [
            SimpleNamespace(id=1, current_mmsi="413000001"),
            SimpleNamespace(id=2, current_mmsi="413000002"),
        ]

    async def realtime_host() -> str:
        return "http://localhost:9200"

    async def positions_for_profiles(*args, **kwargs):
        raise asyncio.TimeoutError

    async def no_snapshot(*args, **kwargs):
        events.append("snapshot")
        return None

    service.db = FakeDb()
    service._city_cache_backend = cache_backend  # type: ignore[method-assign]
    service._ais_runtime_limits = limits  # type: ignore[method-assign]
    service._position_monitor_profile_count = profile_count  # type: ignore[method-assign]
    service._position_monitor_profiles = profiles  # type: ignore[method-assign]
    service._realtime_es_host = realtime_host  # type: ignore[method-assign]
    service._position_monitor_items_for_profiles = positions_for_profiles  # type: ignore[method-assign]
    service._city_situation_from_latest_snapshot = no_snapshot  # type: ignore[method-assign]

    query = VesselPositionCitySituationQuery(reported_within_minutes=1440, include_boundary=False)
    object.__setattr__(query, "force_refresh", True)
    result = await service.position_city_situation(query)

    assert result.source_status == "ERROR"
    assert result.summary.snapshot_status_code == "FAILED"
    assert result.summary.refresh_required is True
    assert result.summary.matched_profile_count == 5
    assert result.summary.scanned_profile_count == 2
    assert result.summary.unscanned_profile_count == 3
    assert result.cities == []
    assert "实时 AIS 查询超时" in (result.message or "")
    assert events == ["snapshot", "profiles:2", "rollback", "snapshot"]


@pytest.mark.asyncio
async def test_vessel_channel_situation_timeout_returns_error_response() -> None:
    service = VesselService.__new__(VesselService)
    events: list[str] = []

    class FakeDb:
        async def rollback(self) -> None:
            events.append("rollback")

    async def cache_backend() -> str:
        return "memory"

    async def limits() -> dict[str, int]:
        return {"profile_limit": 2, "es_batch_size": 500, "es_max_concurrency": 4, "unmatched_scan_limit": 1000}

    async def profile_count(_query) -> int:
        return 4

    async def profiles(_query, limit: int | None = None):
        events.append(f"profiles:{limit}")
        return [
            SimpleNamespace(id=1, current_mmsi="413000001"),
            SimpleNamespace(id=2, current_mmsi="413000002"),
        ]

    async def realtime_host() -> str:
        return "http://localhost:9200"

    async def positions_for_profiles(*args, **kwargs):
        raise asyncio.TimeoutError

    async def boundaries():
        events.append("boundaries")
        return []

    service.db = FakeDb()
    service._city_cache_backend = cache_backend  # type: ignore[method-assign]
    service._ais_runtime_limits = limits  # type: ignore[method-assign]
    service._position_monitor_profile_count = profile_count  # type: ignore[method-assign]
    service._position_monitor_profiles = profiles  # type: ignore[method-assign]
    service._realtime_es_host = realtime_host  # type: ignore[method-assign]
    service._position_monitor_items_for_profiles = positions_for_profiles  # type: ignore[method-assign]
    service._channel_boundaries = boundaries  # type: ignore[method-assign]

    query = VesselPositionNavigationChannelSituationQuery(
        reported_within_minutes=1440,
        include_boundary=False,
        include_empty_channels=True,
    )
    object.__setattr__(query, "force_refresh", True)
    result = await service.position_channel_situation(query)

    assert result.source_status == "ERROR"
    assert result.summary.snapshot_status_code == "FAILED"
    assert result.summary.refresh_required is True
    assert result.summary.matched_profile_count == 4
    assert result.summary.scanned_profile_count == 2
    assert result.summary.unscanned_profile_count == 2
    assert result.channels == []
    assert "实时 AIS 查询超时" in (result.message or "")
    assert events == ["profiles:2", "rollback", "boundaries"]


@pytest.mark.asyncio
async def test_vessel_channel_situation_timeout_uses_persisted_snapshot_fallback() -> None:
    service = VesselService.__new__(VesselService)
    events: list[str] = []
    generated_at = datetime(2026, 5, 10, 8, 0, 0)
    fallback_response = VesselPositionNavigationChannelSituationResponse(
        source_status="PARTIAL",
        source_status_name="实时船位部分可用",
        generated_at=generated_at,
        message="实时 AIS 查询超时，已返回最近一次入库 AIS 航道快照",
        cache_status="FALLBACK",
        cache_generated_at=generated_at,
        snapshot_backend="db_snapshot",
        summary=VesselPositionNavigationChannelSituationSummary(
            matched_profile_count=4,
            scanned_profile_count=2,
            unscanned_profile_count=2,
            queried_mmsi_count=2,
            matched_position_count=2,
            unpositioned_count=0,
            positioned_count=2,
            stale_position_count=0,
            contactable_position_count=1,
            certificate_risk_count=0,
            channel_count=1,
            query_snapshot_id="DEMO_AIS_EXPERIENCE_CURRENT",
            snapshot_status_code="PARTIAL",
            refresh_required=False,
            is_partial=True,
        ),
        channels=[],
    )

    class FakeDb:
        async def rollback(self) -> None:
            events.append("rollback")

    async def cache_backend() -> str:
        return "memory"

    async def limits() -> dict[str, int]:
        return {"profile_limit": 2, "es_batch_size": 500, "es_max_concurrency": 4, "unmatched_scan_limit": 1000}

    async def profile_count(_query) -> int:
        return 4

    async def profiles(_query, limit: int | None = None):
        events.append(f"profiles:{limit}")
        return [
            SimpleNamespace(id=1, current_mmsi="413000001"),
            SimpleNamespace(id=2, current_mmsi="413000002"),
        ]

    async def realtime_host() -> str:
        return "http://localhost:9200"

    async def positions_for_profiles(*args, **kwargs):
        raise asyncio.TimeoutError

    snapshot_calls = 0

    async def snapshot_fallback(*args, **kwargs):
        nonlocal snapshot_calls
        snapshot_calls += 1
        events.append("snapshot")
        return None if snapshot_calls == 1 else fallback_response

    async def store_response_cache(*args, **kwargs) -> None:
        events.append("response-cache")

    service.db = FakeDb()
    service._city_cache_backend = cache_backend  # type: ignore[method-assign]
    service._ais_runtime_limits = limits  # type: ignore[method-assign]
    service._position_monitor_profile_count = profile_count  # type: ignore[method-assign]
    service._position_monitor_profiles = profiles  # type: ignore[method-assign]
    service._realtime_es_host = realtime_host  # type: ignore[method-assign]
    service._position_monitor_items_for_profiles = positions_for_profiles  # type: ignore[method-assign]
    service._channel_situation_from_latest_snapshot = snapshot_fallback  # type: ignore[method-assign]
    service._store_channel_situation_response_cache = store_response_cache  # type: ignore[method-assign]

    query = VesselPositionNavigationChannelSituationQuery(
        reported_within_minutes=1440,
        include_boundary=False,
        include_empty_channels=False,
    )
    object.__setattr__(query, "force_refresh", True)
    result = await service.position_channel_situation(query)

    assert result.source_status == "PARTIAL"
    assert result.cache_status == "FALLBACK"
    assert result.summary.query_snapshot_id == "DEMO_AIS_EXPERIENCE_CURRENT"
    assert result.summary.refresh_required is False
    assert events == ["snapshot", "profiles:2", "rollback", "snapshot", "response-cache"]


@pytest.mark.asyncio
async def test_vessel_channel_precompute_uses_default_fast_query(monkeypatch) -> None:
    captured: dict[str, object] = {}
    drilldowns: list[object] = []
    generated_at = datetime(2026, 5, 11, 8, 0, 0)

    class FakeSessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeVesselService:
        def __init__(self, db) -> None:
            captured["db"] = db

        async def _city_redis(self):
            return None

        async def precompute_full_ais_position_snapshot(self, query):
            captured["snapshot_query"] = query
            return {"snapshot_id": "AIS-PRODUCTION-CURRENT"}

        async def position_city_situation(self, query):
            return SimpleNamespace(
                source_status="AVAILABLE",
                generated_at=generated_at,
                summary=SimpleNamespace(
                    positioned_count=0,
                    city_count=0,
                    query_snapshot_id=None,
                    is_partial=False,
                ),
                cities=[],
                snapshot_backend="memory",
            )

        async def position_channel_situation(self, query):
            captured["query"] = query
            return SimpleNamespace(
                source_status="AVAILABLE",
                generated_at=generated_at,
                summary=SimpleNamespace(
                    positioned_count=8,
                    channel_count=2,
                    query_snapshot_id="channel-snapshot",
                    is_partial=False,
                ),
                channels=[
                    SimpleNamespace(positioned_count=8, channel_code="NC-YANGTZE", channel_name="长江干线")
                ],
                snapshot_backend="memory",
            )

        async def position_channel_vessels(self, query):
            drilldowns.append(query)
            return SimpleNamespace(total=8, items=[])

    monkeypatch.setattr(vessel_position_tasks, "AsyncSessionLocal", lambda: FakeSessionContext())
    monkeypatch.setattr(vessel_position_tasks, "VesselService", FakeVesselService)
    monkeypatch.setattr(vessel_position_tasks.settings, "VESSEL_CHANNEL_SITUATION_PRECOMPUTE_GROUP_LIMIT", 5)

    result = await vessel_position_tasks._precompute_channel_situation()
    query = captured["query"]

    assert result == {
        "source_status": "AVAILABLE",
        "generated_at": generated_at.isoformat(),
        "positioned_count": 8,
        "channel_count": 2,
        "drilldown_count": 1,
        "is_partial": False,
        "snapshot_backend": "memory",
    }
    assert query.include_boundary is False
    assert query.include_empty_channels is False
    assert query.planning_level_codes == "NATIONAL_CORE,NATIONAL_NETWORK,NATIONAL_IMPORTANT,PROVINCIAL_HIGH_GRADE,REGIONAL_IMPORTANT,REVIEW"
    assert query.channel_type_codes == "MAIN_LINE,MAIN_RIVER_CHANNEL,TRIBUTARY_CHANNEL,CANAL,CHANNEL_NETWORK,DELTA_WATERWAY"
    assert getattr(query, "force_refresh") is False
    assert len(drilldowns) == 1
    assert drilldowns[0].channel_code == "NC-YANGTZE"
    assert drilldowns[0].query_snapshot_id == "channel-snapshot"
    assert drilldowns[0].page_size == 100


@pytest.mark.asyncio
async def test_vessel_city_precompute_uses_default_cache_query_and_drilldown(monkeypatch) -> None:
    captured: dict[str, object] = {}
    drilldowns: list[object] = []
    generated_at = datetime(2026, 5, 11, 8, 0, 0)

    class FakeSessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeVesselService:
        def __init__(self, db) -> None:
            captured["db"] = db

        async def _city_redis(self):
            return None

        async def precompute_full_ais_position_snapshot(self, query):
            captured["snapshot_query"] = query
            return {"snapshot_id": "AIS-PRODUCTION-CURRENT"}

        async def position_city_situation(self, query):
            captured["query"] = query
            return SimpleNamespace(
                source_status="AVAILABLE",
                generated_at=generated_at,
                summary=SimpleNamespace(
                    positioned_count=6,
                    city_count=1,
                    query_snapshot_id="city-snapshot",
                    is_partial=False,
                ),
                cities=[
                    SimpleNamespace(positioned_count=6, city_code="320500", city_name="苏州市")
                ],
                snapshot_backend="memory",
            )

        async def position_city_vessels(self, query):
            drilldowns.append(query)
            return SimpleNamespace(total=6, items=[])

        async def position_channel_situation(self, query):
            return SimpleNamespace(
                source_status="AVAILABLE",
                generated_at=generated_at,
                summary=SimpleNamespace(
                    positioned_count=0,
                    channel_count=0,
                    query_snapshot_id=None,
                    is_partial=False,
                ),
                channels=[],
                snapshot_backend="memory",
            )

    monkeypatch.setattr(vessel_position_tasks, "AsyncSessionLocal", lambda: FakeSessionContext())
    monkeypatch.setattr(vessel_position_tasks, "VesselService", FakeVesselService)

    result = await vessel_position_tasks._precompute_city_situation()
    query = captured["query"]

    assert result == {
        "source_status": "AVAILABLE",
        "generated_at": generated_at.isoformat(),
        "positioned_count": 6,
        "city_count": 1,
        "drilldown_count": 1,
        "is_partial": False,
        "snapshot_backend": "memory",
    }
    assert query.include_boundary is False
    assert getattr(query, "force_refresh") is False
    assert len(drilldowns) == 1
    assert drilldowns[0].city_code == "320500"
    assert drilldowns[0].query_snapshot_id == "city-snapshot"
    assert drilldowns[0].page_size == 100


@pytest.mark.asyncio
async def test_vessel_city_situation_ignores_seed_cache_when_realtime_es_is_configured() -> None:
    service = VesselService.__new__(VesselService)
    events: list[str] = []
    generated_at = datetime(2026, 5, 10, 8, 0, 0)
    seed_response = VesselPositionCitySituationResponse(
        source_status="AVAILABLE",
        source_status_name="可用",
        generated_at=generated_at,
        cache_status="SNAPSHOT",
        cache_generated_at=generated_at,
        snapshot_backend="seed",
        summary=VesselPositionCitySituationSummary(
            matched_profile_count=3,
            scanned_profile_count=3,
            queried_mmsi_count=3,
            matched_position_count=3,
            unpositioned_count=0,
            positioned_count=3,
            stale_position_count=0,
            contactable_position_count=3,
            certificate_risk_count=0,
            city_count=2,
            query_snapshot_id="seed-current-ais",
            snapshot_status_code="READY",
            snapshot_expires_at=generated_at + timedelta(days=365),
            is_partial=False,
        ),
        cities=[],
    )

    async def cache_backend() -> str:
        events.append("backend")
        return "redis"

    async def cached(_cache_key: str):
        events.append("cache-read")
        return seed_response, "redis"

    async def realtime_host() -> str:
        events.append("realtime-host")
        return "http://localhost:9200"

    async def limits() -> dict[str, int]:
        events.append("limits")
        return {"profile_limit": 2000, "es_batch_size": 500, "es_max_concurrency": 4, "unmatched_scan_limit": 1000}

    async def profile_count(_query) -> int:
        events.append("count")
        return 0

    async def profiles(_query, limit: int | None = None):
        events.append(f"profiles:{limit}")
        return []

    service._city_cache_backend = cache_backend  # type: ignore[method-assign]
    service._get_city_situation_response_cache = cached  # type: ignore[method-assign]
    service._realtime_es_host = realtime_host  # type: ignore[method-assign]
    service._ais_runtime_limits = limits  # type: ignore[method-assign]
    service._position_monitor_profile_count = profile_count  # type: ignore[method-assign]
    service._position_monitor_profiles = profiles  # type: ignore[method-assign]

    result = await service.position_city_situation(
        VesselPositionCitySituationQuery(reported_within_minutes=1600, include_boundary=False)
    )

    assert result.source_status == "EMPTY"
    assert result.cache_status == "MISS"
    assert result.summary.query_snapshot_id is None
    assert events == ["backend", "cache-read", "realtime-host", "limits", "count", "profiles:2000"]


@pytest.mark.asyncio
async def test_vessel_round6_memory_cache_forbidden_in_production(monkeypatch) -> None:
    service = VesselService.__new__(VesselService)
    monkeypatch.setattr(vessel_service_module.settings, "APP_ENV", "production")
    monkeypatch.setattr(vessel_service_module.settings, "DEBUG", False)
    monkeypatch.setattr(vessel_service_module.settings, "VESSEL_CITY_SITUATION_CACHE_BACKEND", "memory")

    with pytest.raises(AppException) as exc_info:
        await service._city_cache_backend()

    assert exc_info.value.code == "VESSEL_AIS_MEMORY_CACHE_FORBIDDEN"
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_vessel_round6_production_redis_failure_does_not_store_memory_cache(monkeypatch) -> None:
    service = VesselService.__new__(VesselService)
    cache_key = "production-redis-failed"
    vessel_service_module._CITY_SITUATION_RESPONSE_CACHE.pop(cache_key, None)
    monkeypatch.setattr(vessel_service_module.settings, "APP_ENV", "production")
    monkeypatch.setattr(vessel_service_module.settings, "DEBUG", False)
    monkeypatch.setattr(vessel_service_module.settings, "VESSEL_CITY_SITUATION_CACHE_BACKEND", "redis")

    class BrokenRedis:
        async def setex(self, *args, **kwargs) -> None:
            raise RuntimeError("redis down")

    async def cache_backend() -> str:
        return "redis"

    async def redis_client():
        return BrokenRedis()

    service._city_cache_backend = cache_backend  # type: ignore[method-assign]
    service._city_redis = redis_client  # type: ignore[method-assign]
    generated_at = datetime(2026, 5, 9, 12, 0, 0)
    response = VesselPositionCitySituationResponse(
        source_status="EMPTY",
        source_status_name="暂无实时船位",
        generated_at=generated_at,
        summary=VesselPositionCitySituationSummary(
            matched_profile_count=0,
            queried_mmsi_count=0,
            matched_position_count=0,
            unpositioned_count=0,
            positioned_count=0,
            stale_position_count=0,
            contactable_position_count=0,
            certificate_risk_count=0,
            city_count=0,
        ),
        cities=[],
    )

    await service._store_city_situation_response_cache(cache_key, response)

    assert cache_key not in vessel_service_module._CITY_SITUATION_RESPONSE_CACHE


def test_vessel_round3_certificate_risk_requires_complete_verified_evidence() -> None:
    service = object.__new__(VesselService)
    pending_certs = [
        SimpleNamespace(
            certificate_type_code=code,
            certificate_no=None,
            is_long_term_valid=False,
            valid_to=None,
            verify_status_code="PENDING",
        )
        for code in REQUIRED_VESSEL_CERTIFICATE_TYPES
    ]

    pending_risk = service._summary_certificate_risk(pending_certs, [])

    assert pending_risk["risk_level"] == "UNKNOWN"
    assert pending_risk["certificate_missing_count"] == 0
    assert pending_risk["risk_evidence_summary"][1]["insufficient_certificate_type_codes"]
    assert "LOW_RISK_SAMPLE" not in service._summary_sample_tags("HIGH", pending_risk["risk_level"], "FRESH", "HIGH", {})

    verified_certs = [
        SimpleNamespace(
            certificate_type_code=code,
            certificate_no=f"CERT-{code}",
            is_long_term_valid=False,
            valid_to=date.today() + timedelta(days=120),
            verify_status_code="VERIFIED",
        )
        for code in REQUIRED_VESSEL_CERTIFICATE_TYPES
    ]

    verified_risk = service._summary_certificate_risk(verified_certs, [])

    assert verified_risk["risk_level"] == "LOW"
    assert "LOW_RISK_SAMPLE" in service._summary_sample_tags("HIGH", verified_risk["risk_level"], "FRESH", "HIGH", {})


def test_vessel_round3_effective_summary_status_marks_stale_rows() -> None:
    service = object.__new__(VesselService)
    stale = SimpleNamespace(
        summary_status_code="READY",
        source_updated_at=datetime(2026, 5, 9, 10, 5, 0),
        refreshed_at=datetime(2026, 5, 9, 10, 0, 0),
    )
    fresh = SimpleNamespace(
        summary_status_code="READY",
        source_updated_at=datetime(2026, 5, 9, 10, 0, 0),
        refreshed_at=datetime(2026, 5, 9, 10, 5, 0),
    )

    assert service._effective_summary_status(stale) == "STALE"
    assert service._effective_summary_status(fresh) == "READY"


@pytest.mark.asyncio
async def test_vessel_round3_manual_refresh_rolls_back_before_marking_failed() -> None:
    service = VesselService.__new__(VesselService)
    events: list[str] = []

    class FakeDb:
        async def rollback(self) -> None:
            events.append("rollback")

        async def commit(self) -> None:
            events.append("commit")

    async def require_profile(vessel_id: int):
        return SimpleNamespace(id=vessel_id)

    async def fail_upsert(_profile) -> None:
        events.append("upsert")
        raise RuntimeError("flush failed")

    async def mark_failed(_profile, error: str):
        assert error == "flush failed"
        assert events[-1] == "rollback"
        events.append("mark_failed")
        return SimpleNamespace(summary_status_code="FAILED")

    async def build_items(_profiles):
        events.append("build")
        return [SimpleNamespace(summary_status_code="FAILED")]

    service.db = FakeDb()
    service._require_profile = require_profile  # type: ignore[method-assign]
    service._upsert_vessel_summary = fail_upsert  # type: ignore[method-assign]
    service._mark_vessel_summary_failed = mark_failed  # type: ignore[method-assign]
    service._build_asset_items = build_items  # type: ignore[method-assign]

    result = await service.refresh_vessel_summary(1)

    assert result.summary_status_code == "FAILED"
    assert events == ["upsert", "rollback", "mark_failed", "commit", "build"]


@pytest.mark.asyncio
async def test_vessel_round2_replace_apis_are_gone() -> None:
    service = VesselService.__new__(VesselService)

    async def require_profile(vessel_id: int):
        return SimpleNamespace(id=vessel_id)

    service._require_profile = require_profile  # type: ignore[method-assign]
    replace_methods = [
        service.replace_owners,
        service.replace_operators,
        service.replace_contacts,
        service.replace_crew,
        service.replace_person_certificates,
    ]

    for method in replace_methods:
        with pytest.raises(AppException) as error:
            await method(1, [], operator_id=None)
        assert error.value.status_code == 410
        assert error.value.code == "REPLACE_API_GONE"


def test_vessel_round1_schemas_include_revision_and_contact_current_fields() -> None:
    schemas = app.openapi()["components"]["schemas"]

    owner_props = schemas["VesselOwnerResponse"]["properties"]
    contact_props = schemas["VesselContactResponse"]["properties"]
    person_props = schemas["VesselPersonCertificateResponse"]["properties"]
    set_primary_required = schemas["VesselSetPrimaryRequest"]["required"]

    assert "revision" in owner_props
    assert "cancelled_primary_ids" in owner_props
    assert "change_event_id" in owner_props
    assert "start_date" in contact_props
    assert "end_date" in contact_props
    assert "is_current" in contact_props
    assert "revision" in person_props
    assert "revision" in set_primary_required


def test_vessel_quality_fingerprint_and_current_filter_are_stable() -> None:
    first = _quality_fingerprint("MMSI_CONFLICT", 12, "mmsi", "413000001", "current_mmsi", "mmsi|413000001")
    second = _quality_fingerprint("MMSI_CONFLICT", 12, "mmsi", "413000001", "current_mmsi", " MMSI|413000001 ")
    third = _quality_fingerprint("MMSI_CONFLICT", 99, "mmsi", "413000001", "current_mmsi", "mmsi|413000001")

    assert first == second
    assert first == third
    assert _relation_is_effective(SimpleNamespace(voided_at=None, is_current=True, end_date=None)) is True
    assert _relation_is_effective(SimpleNamespace(voided_at=datetime.now(), is_current=True, end_date=None)) is False
    assert _relation_is_effective(SimpleNamespace(voided_at=None, is_current=False, end_date=None)) is False


def test_vessel_relation_write_guard_rejects_voided_and_history_rows() -> None:
    with pytest.raises(ConflictError) as voided_error:
        _ensure_relation_writable(SimpleNamespace(id=1, voided_at=datetime.now(), is_current=True, end_date=None))
    assert voided_error.value.code == "RELATION_VOIDED"

    with pytest.raises(ConflictError) as history_error:
        _ensure_relation_writable(SimpleNamespace(id=2, voided_at=None, is_current=False, end_date=None))
    assert history_error.value.code == "RELATION_NOT_CURRENT"


def test_vessel_ocr_adoption_selection_requires_diff_and_selected_fields() -> None:
    service = VesselService.__new__(VesselService)

    with pytest.raises(ConflictError) as no_diff_error:
        service._validate_ocr_adoption_selection([], {"certificate_no"}, "人工确认")
    assert no_diff_error.value.code == "OCR_DIFF_REQUIRED"

    diff = VesselRecognitionFieldDiff(field_name="certificate_no", confidence_score=95)
    with pytest.raises(ConflictError) as no_field_error:
        service._validate_ocr_adoption_selection([diff], set(), "人工确认")
    assert no_field_error.value.code == "OCR_DIFF_REQUIRED"


def test_vessel_ocr_adoption_selection_requires_reason_for_low_confidence() -> None:
    service = VesselService.__new__(VesselService)
    diff = VesselRecognitionFieldDiff(field_name="certificate_no", confidence_score=LOW_CONFIDENCE_SCORE_THRESHOLD - 1)

    with pytest.raises(ValidationError) as low_confidence_error:
        service._validate_ocr_adoption_selection([diff], {"certificate_no"}, None)
    assert low_confidence_error.value.code == "LOW_CONFIDENCE_CONFIRM_REQUIRED"

    assert service._validate_ocr_adoption_selection([diff], {"certificate_no"}, "人工确认低置信字段") == {"certificate_no"}


def test_vessel_certificate_ledger_and_void_routes_exist() -> None:
    paths = app.openapi()["paths"]

    assert "get" in paths["/api/v1/vessels/{vessel_id}/certificates/ledger"]
    assert "get" in paths["/api/v1/vessels/position-monitor/city-situation"]
    assert "get" in paths["/api/v1/vessels/position-monitor/city-vessels"]
    assert "get" in paths["/api/v1/vessels/position-monitor/vessels/{vessel_id}/situation-card"]
    assert "get" in paths[
        "/api/v1/vessels/{vessel_id}/certificates/{certificate_id}/image-recognitions"
    ]
    assert "delete" in paths["/api/v1/vessels/{vessel_id}/certificates/{certificate_id}"]
    assert "delete" in paths["/api/v1/vessels/{vessel_id}/certificates/{certificate_id}/files/{file_id}"]
    assert "delete" in paths[
        "/api/v1/vessels/{vessel_id}/person-certificates/{person_certificate_id}/files/{file_id}"
    ]


def test_vessel_certificate_risk_query_removed() -> None:
    paths = app.openapi()["paths"]
    list_parameters = paths["/api/v1/vessels"]["get"].get("parameters", [])
    monitor_parameters = paths["/api/v1/vessels/position-monitor"]["get"].get("parameters", [])

    assert all(item["name"] != "certificate_risk" for item in list_parameters)
    assert all(item["name"] != "certificate_risk" for item in monitor_parameters)


def test_vessel_recognition_long_term_validity_is_normalized() -> None:
    service = object.__new__(VesselService)

    updates = service._certificate_updates_from_recognition(
        {"certificate_no": "ABC-1", "valid_from": "2026-01-01", "valid_to": "长期"}
    )
    person_updates = service._person_certificate_updates_from_recognition(
        {"holder_name": "张三", "certificate_no": "CREW-1", "validity_text_raw": "2024-01-01 至 长期有效"}
    )

    assert updates["is_long_term_valid"] is True
    assert updates["valid_to"] is None
    assert str(updates["valid_from"]) == "2026-01-01"
    assert person_updates["is_long_term_valid"] is True
    assert person_updates["valid_to"] is None


def test_vessel_certificate_ledger_status_uses_current_task_not_history() -> None:
    service = object.__new__(VesselService)
    confirmed_history = SimpleNamespace(status_code="CONFIRMED")
    failed_current = SimpleNamespace(status_code="FAILED")

    verified_certificate = SimpleNamespace(
        voided_at=None,
        current_image_recognition=None,
        latest_image_recognition=confirmed_history,
        verify_status_code="VERIFIED",
        certificate_no="CERT-1",
        valid_to=None,
        is_long_term_valid=True,
        files=[object()],
    )
    failed_after_confirm = SimpleNamespace(
        voided_at=None,
        current_image_recognition=failed_current,
        latest_image_recognition=failed_current,
        latest_confirmed_image_recognition=confirmed_history,
        verify_status_code="VERIFIED",
        certificate_no="CERT-1",
        valid_to=None,
        is_long_term_valid=True,
        files=[object()],
    )

    assert service._certificate_ledger_status(verified_certificate) == "VERIFIED"
    assert service._certificate_ledger_status(failed_after_confirm) == "RECOGNITION_FAILED"


def test_owner_document_completeness_depends_on_party_type() -> None:
    service = object.__new__(VesselService)

    personal_owner = SimpleNamespace(party_type_code="PERSON")
    company_owner = SimpleNamespace(party_type_code="COMPANY")
    unknown_owner = SimpleNamespace(party_type_code="UNKNOWN")

    personal_partial = service._owner_document_completeness(
        personal_owner,
        [SimpleNamespace(document_type_code="PERSON_ID_FRONT")],
    )
    company_complete = service._owner_document_completeness(
        company_owner,
        [SimpleNamespace(document_type_code="BUSINESS_LICENSE")],
    )
    unknown = service._owner_document_completeness(unknown_owner, [])

    assert personal_partial.status_code == "INCOMPLETE"
    assert personal_partial.missing_document_type_codes == ["PERSON_ID_BACK"]
    assert company_complete.status_code == "COMPLETE"
    assert unknown.status_code == "UNKNOWN_OWNER_TYPE"


def test_vessel_city_resolution_uses_boundary_not_external_city_fields() -> None:
    service = object.__new__(VesselService)
    large_city = _CityBoundary(
        code="320500",
        name="大边界市",
        center_longitude=Decimal("120.00"),
        center_latitude=Decimal("31.00"),
        area_km2=Decimal("100"),
        bbox=(0.0, 0.0, 10.0, 10.0),
        bbox_area=100.0,
        polygons=[[[ (0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0) ]]],
    )
    small_city = _CityBoundary(
        code="320501",
        name="小边界市",
        center_longitude=Decimal("121.00"),
        center_latitude=Decimal("32.00"),
        area_km2=Decimal("1"),
        bbox=(1.0, 1.0, 2.0, 2.0),
        bbox_area=1.0,
        polygons=[[[ (1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0), (1.0, 1.0) ]]],
    )

    resolved = service._resolve_current_city_from_boundaries(Decimal("1.5"), Decimal("1.5"), [large_city, small_city])

    assert resolved.city_code == "320501"
    assert resolved.city_name == "小边界市"
    assert resolved.current_city_source == CURRENT_CITY_SOURCE_ADMIN_BOUNDARY
    assert resolved.matched_city_candidates is not None
    assert [item["city_code"] for item in resolved.matched_city_candidates] == ["320501", "320500"]


def test_vessel_city_resolution_unknown_and_invalid() -> None:
    service = object.__new__(VesselService)

    invalid = service._resolve_current_city_from_boundaries(Decimal("200"), Decimal("31"), [])
    unknown = service._resolve_current_city_from_boundaries(Decimal("120"), Decimal("31"), [])

    assert invalid.city_name == UNKNOWN_CITY_NAME
    assert invalid.current_city_source == CURRENT_CITY_SOURCE_INVALID_POSITION
    assert unknown.city_name == UNKNOWN_CITY_NAME
    assert unknown.current_city_source == CURRENT_CITY_SOURCE_UNKNOWN


def test_vessel_city_boundary_paths_are_simplified_for_situation_payload() -> None:
    points = [(float(index) / 100, 0.0) for index in range(100)]
    ring = points + [(1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
    paths = _boundary_paths_for_precision([[ring]], "low")

    assert paths
    assert len(paths[0]) < len(ring)
    assert paths[0][0] == paths[0][-1]


def test_vessel_city_situation_marks_boundary_coverage() -> None:
    service = object.__new__(VesselService)
    generated_at = datetime.now()

    def make_item(identifier: int, city_code: str | None, city_name: str) -> SimpleNamespace:
        return SimpleNamespace(
            id=identifier,
            current_city_code=city_code,
            city_code=None,
            current_city_name=city_name,
            city_name=None,
            city_center_longitude=Decimal("120.00") if city_code else None,
            city_center_latitude=Decimal("31.00") if city_code else None,
            longitude=Decimal("120.10") if city_code else None,
            latitude=Decimal("31.10") if city_code else None,
            position_time=generated_at,
            contact_available=True,
            ship_age=Decimal("6"),
            deadweight_ton=Decimal("1000"),
            ship_type_code="DRY_CARGO",
            ship_type_name="干货船",
        )

    cities = service._city_situation_items(
        [
            make_item(1, "320500", "有边界市"),
            make_item(2, "320600", "缺边界市"),
            make_item(3, None, UNKNOWN_CITY_NAME),
        ],
        {},
        generated_at,
        1440,
        3,
        2,
        1,
        0,
        1,
        False,
        None,
        {"320500": [[(120.0, 31.0), (120.2, 31.0), (120.2, 31.2), (120.0, 31.2), (120.0, 31.0)]]},
        "low",
    )
    by_name = {city.city_name: city for city in cities}

    assert by_name["有边界市"].has_boundary is True
    assert by_name["有边界市"].boundary_precision == "low"
    assert by_name["有边界市"].boundary_paths
    assert by_name["缺边界市"].has_boundary is False
    assert by_name["缺边界市"].boundary_paths is None
    assert by_name[UNKNOWN_CITY_NAME].has_boundary is False
    assert by_name[UNKNOWN_CITY_NAME].boundary_precision is None


@pytest.mark.asyncio
async def test_vessel_round6_city_vessels_requires_live_snapshot() -> None:
    service = VesselService.__new__(VesselService)

    async def no_cached(_cache_key):
        return None

    async def missing_snapshot(_snapshot_id):
        return None

    service._get_city_vessels_response_cache = no_cached  # type: ignore[method-assign]
    service._get_city_situation_snapshot = missing_snapshot  # type: ignore[method-assign]
    query = SimpleNamespace(
        query_snapshot_id="expired",
        city_code="320500",
        city_name=None,
        page=1,
        page_size=20,
        reported_within_minutes=1440,
    )

    result = await service.position_city_vessels(query)

    assert result.snapshot_hit is False
    assert result.refresh_required is True
    assert result.snapshot_status_code == "EXPIRED"
    assert result.error_message == "SNAPSHOT_EXPIRED"


@pytest.mark.asyncio
async def test_vessel_city_vessels_uses_drilldown_cache_before_snapshot() -> None:
    service = VesselService.__new__(VesselService)
    events: list[str] = []
    cached_response = VesselPositionCityVesselsResponse(
        total=1,
        page=1,
        page_size=20,
        items=[],
        query_snapshot_id="city-snapshot",
        snapshot_hit=True,
        is_partial=False,
    )

    async def cached(_cache_key):
        events.append("cache-read")
        return cached_response, "redis"

    async def fail_snapshot(_snapshot_id):
        raise AssertionError("cached city drilldown should not read the full situation snapshot")

    service._get_city_vessels_response_cache = cached  # type: ignore[method-assign]
    service._get_city_situation_snapshot = fail_snapshot  # type: ignore[method-assign]

    result = await service.position_city_vessels(
        SimpleNamespace(
            query_snapshot_id="city-snapshot",
            city_code="320500",
            city_name=None,
            page=1,
            page_size=20,
            reported_within_minutes=1440,
        )
    )

    assert result.total == 1
    assert result.snapshot_hit is True
    assert events == ["cache-read"]


@pytest.mark.asyncio
async def test_vessel_channel_vessels_uses_drilldown_cache_before_snapshot() -> None:
    service = VesselService.__new__(VesselService)
    events: list[str] = []
    cached_response = VesselPositionNavigationChannelVesselsResponse(
        total=1,
        page=1,
        page_size=20,
        items=[],
        query_snapshot_id="channel-snapshot",
        snapshot_hit=True,
        is_partial=False,
    )

    async def cached(_cache_key):
        events.append("cache-read")
        return cached_response, "redis"

    async def fail_snapshot(_snapshot_id):
        raise AssertionError("cached channel drilldown should not read the full situation snapshot")

    service._get_channel_vessels_response_cache = cached  # type: ignore[method-assign]
    service._get_city_situation_snapshot = fail_snapshot  # type: ignore[method-assign]

    result = await service.position_channel_vessels(
        SimpleNamespace(
            query_snapshot_id="channel-snapshot",
            channel_code="NC-YANGTZE",
            channel_name=None,
            page=1,
            page_size=20,
            reported_within_minutes=1440,
        )
    )

    assert result.total == 1
    assert result.snapshot_hit is True
    assert events == ["cache-read"]


def test_vessel_city_resolution_uses_grid_candidates_when_available() -> None:
    service = object.__new__(VesselService)
    city = _CityBoundary(
        code="320500",
        name="网格市",
        center_longitude=Decimal("120.00"),
        center_latitude=Decimal("31.00"),
        area_km2=Decimal("100"),
        bbox=(120.0, 31.0, 121.0, 32.0),
        bbox_area=1.0,
        polygons=[[[ (120.0, 31.0), (121.0, 31.0), (121.0, 32.0), (120.0, 32.0), (120.0, 31.0) ]]],
    )

    resolved = service._resolve_current_city_from_boundaries(
        Decimal("120.5"),
        Decimal("31.5"),
        [city],
        _build_city_boundary_grid([city]),
    )

    assert resolved.city_code == "320500"
    assert resolved.current_city_source == CURRENT_CITY_SOURCE_ADMIN_BOUNDARY


def test_vessel_precompute_worker_ready_queues_analysis_tasks(monkeypatch) -> None:
    queued: list[tuple[str, str | None]] = []

    class FakeTask:
        def __init__(self, name: str) -> None:
            self.name = name

        def apply_async(self, *, queue: str | None = None):
            queued.append((self.name, queue))

    monkeypatch.setattr(vessel_position_tasks.settings, "VESSEL_SITUATION_PRECOMPUTE_ON_WORKER_START", True)
    monkeypatch.setattr(vessel_position_tasks, "precompute_ais_situation_task", FakeTask("ais"))

    vessel_position_tasks.precompute_situations_on_worker_ready()

    assert queued == [("ais", "analysis")]
