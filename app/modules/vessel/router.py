"""vessel 模块 router。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.system import SysUser
from app.modules.vessel.schemas import (
    PageResponse,
    VesselAisCitySituationQuery,
    VesselAisCityVesselsQuery,
    VesselAisCityBoundaryQuery,
    VesselAisMonitorQuery,
    VesselAisNodeSituationQuery,
    VesselAisNodeSituationResponse,
    VesselAisNodeVesselsQuery,
    VesselAisNodeVesselsResponse,
    VesselAisRouteSegmentVesselsQuery,
    VesselAisRouteSegmentVesselsResponse,
    VesselAisRouteSituationQuery,
    VesselAisRouteSituationResponse,
    VesselAisCityBoundaryResponse,
    VesselAisSituationCardResponse,
    VesselAisSnapshotQuery,
    VesselAisSnapshotResponse,
    VesselAisUnmatchedMmsiResponse,
    VesselAffiliationEvidenceCreateRequest,
    VesselAffiliationEvidenceResponse,
    VesselAffiliationEvidenceUpdateRequest,
    VesselAssetPageResponse,
    VesselAssetListItemResponse,
    VesselAssetListQuery,
    VesselAssetSummaryResponse,
    VesselBuildInfoResponse,
    VesselBuildInfoUpsertRequest,
    VesselCapacityResponse,
    VesselCapacityUpsertRequest,
    VesselCertificateCreateRequest,
    VesselCertificateFileResponse,
    VesselCertificateImageRecognitionConfirmRequest,
    VesselCertificateImageRecognitionCreateRequest,
    VesselCertificateImageRecognitionResponse,
    VesselCertificateLedgerItemResponse,
    VesselCertificateRequirementRulePayload,
    VesselCertificateRequirementRuleResponse,
    VesselCertificateRequirementRuleUpdateRequest,
    VesselCertificateResponse,
    VesselCertificateUpdateRequest,
    VesselChangeEventResponse,
    VesselContactCreateRequest,
    VesselContactReplaceRequest,
    VesselContactResponse,
    VesselContactUpdateRequest,
    VesselCreateRequest,
    VesselCrewCreateRequest,
    VesselCrewReplaceRequest,
    VesselCrewResponse,
    VesselCrewUpdateRequest,
    VesselBusinessSituationCardResponse,
    VesselCandidateAnalysisAnnotationRequest,
    VesselCandidateAnalysisAnnotationResponse,
    VesselCandidateAnalysisCreateRequest,
    VesselCandidateAnalysisListQuery,
    VesselCandidateAnalysisResponse,
    VesselComplianceRiskQuery,
    VesselComplianceRiskResponse,
    VesselComplianceRuleQuery,
    VesselControllerEvidenceCreateRequest,
    VesselControllerEvidenceResponse,
    VesselControllerEvidenceUpdateRequest,
    VesselBlacklistSignalCreateRequest,
    VesselBlacklistSignalResponse,
    VesselBlacklistSignalUpdateRequest,
    VesselDetailResponse,
    VesselGovernanceDashboardResponse,
    VesselGovernanceTaskActionRequest,
    VesselGovernanceTaskQuery,
    VesselGovernanceTaskResponse,
    VesselListItemResponse,
    VesselListQuery,
    VesselNavigationConstraintQuery,
    VesselNavigationConstraintResponse,
    VesselOperatorCreateRequest,
    VesselOperatorReplaceRequest,
    VesselOperatorResponse,
    VesselOperatorUpdateRequest,
    VesselOwnerDocumentImageRecognitionConfirmRequest,
    VesselOwnerDocumentImageRecognitionResponse,
    VesselOwnerDocumentResponse,
    VesselOwnerCreateRequest,
    VesselOwnerReplaceRequest,
    VesselOwnerResponse,
    VesselOwnerTransferRequest,
    VesselOwnerUpdateRequest,
    VesselPersonCertificateFileResponse,
    VesselPersonCertificateImageRecognitionConfirmRequest,
    VesselPersonCertificateImageRecognitionCreateRequest,
    VesselPersonCertificateImageRecognitionResponse,
    VesselPersonCertificateReplaceRequest,
    VesselPersonCertificateResponse,
    VesselPersonCertificateUpdateRequest,
    VesselPositionCitySituationQuery,
    VesselPositionCitySituationResponse,
    VesselPositionCityVesselsQuery,
    VesselPositionCityVesselsResponse,
    VesselPositionMonitorItemResponse,
    VesselPositionMonitorQuery,
    VesselPositionMonitorResponse,
    VesselProfileCardEvidenceQuery,
    VesselProfileCardEvidenceResponse,
    VesselProfileCardResponse,
    VesselProfileResponse,
    VesselProfileUpdateRequest,
    VesselQualityIssueGlobalQuery,
    VesselQualityIssueListItemResponse,
    VesselQualityIssueQuery,
    VesselQualityIssueResponse,
    VesselRecognitionHistoryQuery,
    VesselRecognitionAdoptionRequest,
    VesselRecognitionFieldDiffResponse,
    VesselRecognitionQueueItemResponse,
    VesselRecognitionQueueQuery,
    VesselRegistrationResponse,
    VesselRegistrationUpsertRequest,
    VesselRelationUpdateMeta,
    VesselSetPrimaryRequest,
    VesselVoidRequest,
    VesselRiskSignalResponse,
    VesselRiskSignalUpdateRequest,
    VesselRiskReviewRequest,
    VesselRiskReviewResponse,
    VesselSpatialSnapshotResponse,
)
from app.modules.vessel.candidate_service import VesselCandidateAnalysisService
from app.modules.vessel.governance_service import VesselGovernanceService
from app.modules.vessel.service import VesselService
from app.modules.vessel.spatial_service import VesselSpatialAnalysisService

router = APIRouter()


def _operator_id(current_user: SysUser) -> int | None:
    return int(current_user.id) if current_user is not None else None


@router.get("/assets/summary", response_model=VesselAssetSummaryResponse)
async def get_vessel_asset_summary(
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).asset_summary()


@router.get("/assets", response_model=VesselAssetPageResponse)
async def list_vessel_assets(
    query: VesselAssetListQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).list_assets(query)


@router.get("/quality", response_model=PageResponse[VesselQualityIssueListItemResponse])
async def list_vessel_quality_queue(
    query: VesselQualityIssueGlobalQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).list_quality_issue_queue(query)


@router.get("/governance/dashboard", response_model=VesselGovernanceDashboardResponse)
async def get_vessel_governance_dashboard(
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselGovernanceService(db).dashboard()


@router.get("/governance/tasks", response_model=PageResponse[VesselGovernanceTaskResponse])
async def list_vessel_governance_tasks(
    query: VesselGovernanceTaskQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselGovernanceService(db).list_tasks(query)


@router.patch("/governance/tasks/{task_id}", response_model=VesselGovernanceTaskResponse)
async def update_vessel_governance_task(
    task_id: int,
    body: VesselGovernanceTaskActionRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselGovernanceService(db).update_task(
        task_id,
        body,
        operator_id=_operator_id(current_user),
    )


@router.get("/compliance-risks", response_model=PageResponse[VesselRiskSignalResponse])
async def list_vessel_compliance_risks(
    query: VesselComplianceRiskQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).list_compliance_risks(query)


@router.get("/compliance-rules", response_model=PageResponse[VesselCertificateRequirementRuleResponse])
async def list_vessel_compliance_rules(
    query: VesselComplianceRuleQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).list_compliance_rules(query)


@router.post("/compliance-rules", response_model=VesselCertificateRequirementRuleResponse)
async def create_vessel_compliance_rule(
    body: VesselCertificateRequirementRulePayload,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).create_compliance_rule(body)


@router.patch("/compliance-rules/{rule_id}", response_model=VesselCertificateRequirementRuleResponse)
async def update_vessel_compliance_rule(
    rule_id: int,
    body: VesselCertificateRequirementRuleUpdateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).update_compliance_rule(rule_id, body)


@router.post("/compliance-rules/{rule_id}/void", response_model=VesselCertificateRequirementRuleResponse)
async def void_vessel_compliance_rule(
    rule_id: int,
    body: VesselVoidRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).void_compliance_rule(rule_id, body)


@router.get("/recognitions", response_model=PageResponse[VesselRecognitionQueueItemResponse])
async def list_vessel_recognition_queue(
    query: VesselRecognitionQueueQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).list_recognition_queue(query)


@router.get(
    "/recognitions/{recognition_type}/{recognition_id}/field-diff",
    response_model=list[VesselRecognitionFieldDiffResponse],
)
async def get_vessel_unified_recognition_field_diff(
    recognition_type: str,
    recognition_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).unified_recognition_field_diff(recognition_type, recognition_id)


@router.post("/recognitions/{recognition_type}/{recognition_id}/adoptions")
async def adopt_vessel_unified_recognition(
    recognition_type: str,
    recognition_id: int,
    body: VesselRecognitionAdoptionRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).unified_recognition_adoption(
        recognition_type,
        recognition_id,
        body,
        operator_id=_operator_id(current_user),
    )


@router.get("/ais/city-situation", response_model=VesselPositionCitySituationResponse)
async def get_vessel_ais_city_situation(
    query: VesselAisCitySituationQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).position_city_situation(query.to_internal_query())


@router.get("/ais/positions", response_model=VesselPositionMonitorResponse)
async def get_vessel_ais_positions(
    query: VesselAisMonitorQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).position_monitor(query.to_internal_query())


@router.get("/ais/city-vessels", response_model=VesselPositionCityVesselsResponse)
async def get_vessel_ais_city_vessels(
    query: VesselAisCityVesselsQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).position_city_vessels(query.to_internal_query())


@router.get("/ais/city-boundaries", response_model=VesselAisCityBoundaryResponse)
async def get_vessel_ais_city_boundaries(
    query: VesselAisCityBoundaryQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).ais_city_boundaries(query)


@router.get("/ais/node-situation", response_model=VesselAisNodeSituationResponse)
async def get_vessel_ais_node_situation(
    query: VesselAisNodeSituationQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselSpatialAnalysisService(db).node_situation(query)


@router.get("/ais/node-vessels", response_model=VesselAisNodeVesselsResponse)
async def get_vessel_ais_node_vessels(
    query: VesselAisNodeVesselsQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselSpatialAnalysisService(db).node_vessels(query)


@router.get("/ais/route-situation", response_model=VesselAisRouteSituationResponse)
async def get_vessel_ais_route_situation(
    query: VesselAisRouteSituationQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselSpatialAnalysisService(db).route_situation(query)


@router.get("/ais/route-segment-vessels", response_model=VesselAisRouteSegmentVesselsResponse)
async def get_vessel_ais_route_segment_vessels(
    query: VesselAisRouteSegmentVesselsQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselSpatialAnalysisService(db).route_segment_vessels(query)


@router.get("/navigation-constraints", response_model=VesselNavigationConstraintResponse)
async def get_vessel_navigation_constraints(
    query: VesselNavigationConstraintQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselSpatialAnalysisService(db).navigation_constraints(query)


@router.get("/ais/spatial-snapshots/{snapshot_id}", response_model=VesselSpatialSnapshotResponse)
async def get_vessel_ais_spatial_snapshot(
    snapshot_id: str,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselSpatialAnalysisService(db).spatial_snapshot(snapshot_id)


@router.post("/candidate-analyses", response_model=VesselCandidateAnalysisResponse)
async def create_vessel_candidate_analysis(
    payload: VesselCandidateAnalysisCreateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselCandidateAnalysisService(db).create_analysis(payload, operator_id=_operator_id(current_user))


@router.get("/candidate-analyses", response_model=PageResponse[VesselCandidateAnalysisResponse])
async def list_vessel_candidate_analyses(
    query: VesselCandidateAnalysisListQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselCandidateAnalysisService(db).list_analyses(query)


@router.get("/candidate-analyses/{analysis_id}", response_model=VesselCandidateAnalysisResponse)
async def get_vessel_candidate_analysis(
    analysis_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselCandidateAnalysisService(db).get_analysis(analysis_id)


@router.post(
    "/candidate-analyses/{analysis_id}/items/{item_id}/annotations",
    response_model=VesselCandidateAnalysisAnnotationResponse,
)
async def create_vessel_candidate_analysis_annotation(
    analysis_id: int,
    item_id: int,
    payload: VesselCandidateAnalysisAnnotationRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselCandidateAnalysisService(db).add_annotation(
        analysis_id,
        item_id,
        payload,
        operator_id=_operator_id(current_user),
    )


@router.get("/ais/snapshots/{snapshot_id}", response_model=VesselAisSnapshotResponse)
async def get_vessel_ais_snapshot(
    snapshot_id: str,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).ais_snapshot(snapshot_id)


@router.get("/ais/unmatched-mmsi", response_model=PageResponse[VesselAisUnmatchedMmsiResponse])
async def list_vessel_ais_unmatched_mmsi(
    query: VesselAisSnapshotQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).list_unmatched_mmsi(query)


@router.get("/ais/vessels/{vessel_id}/situation-card", response_model=VesselAisSituationCardResponse)
async def get_vessel_ais_situation_card(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).position_ais_situation_card(vessel_id)


@router.post("/{vessel_id}/summary/refresh", response_model=VesselAssetListItemResponse)
async def refresh_vessel_summary(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).refresh_vessel_summary(vessel_id)


@router.get("/position-monitor", response_model=VesselPositionMonitorResponse)
async def monitor_vessel_positions(
    query: VesselPositionMonitorQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).position_monitor(query)


@router.get("/position-monitor/city-situation", response_model=VesselPositionCitySituationResponse)
async def monitor_vessel_city_situation(
    query: VesselPositionCitySituationQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).position_city_situation(query)


@router.get("/position-monitor/city-vessels", response_model=VesselPositionCityVesselsResponse)
async def monitor_vessel_city_vessels(
    query: VesselPositionCityVesselsQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).position_city_vessels(query)


@router.get("/position-monitor/vessels/{vessel_id}/situation-card", response_model=VesselBusinessSituationCardResponse)
async def monitor_vessel_situation_card(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).position_business_card(vessel_id)


@router.get("", response_model=PageResponse[VesselListItemResponse])
async def list_vessels(
    query: VesselListQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).list_vessels(query)


@router.post("", response_model=VesselProfileResponse)
async def create_vessel(
    body: VesselCreateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).create_vessel(body, operator_id=_operator_id(current_user))


@router.get("/{vessel_id}/profile-card", response_model=VesselProfileCardResponse)
async def get_vessel_profile_card(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).get_profile_card(vessel_id)


@router.get("/{vessel_id}/profile-card/evidence", response_model=VesselProfileCardEvidenceResponse)
async def get_vessel_profile_card_evidence(
    vessel_id: int,
    query: VesselProfileCardEvidenceQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).get_profile_card_evidence(vessel_id, query)


@router.get("/{vessel_id}/compliance-risk", response_model=VesselComplianceRiskResponse)
async def get_vessel_compliance_risk(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).get_compliance_risk(vessel_id)


@router.post("/{vessel_id}/compliance-risk/refresh", response_model=VesselComplianceRiskResponse)
async def refresh_vessel_compliance_risk(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).refresh_compliance_risk(vessel_id, operator_id=_operator_id(current_user))


@router.patch("/{vessel_id}/risk-signals/{signal_id}", response_model=VesselRiskSignalResponse)
async def update_vessel_risk_signal(
    vessel_id: int,
    signal_id: int,
    body: VesselRiskSignalUpdateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).update_risk_signal(
        vessel_id,
        signal_id,
        body,
        operator_id=_operator_id(current_user),
    )


@router.post("/{vessel_id}/risk-reviews", response_model=VesselRiskReviewResponse)
async def create_vessel_risk_review(
    vessel_id: int,
    body: VesselRiskReviewRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselGovernanceService(db).create_risk_review(
        vessel_id,
        body,
        operator_id=_operator_id(current_user),
    )


@router.get("/{vessel_id}/blacklist-signals", response_model=list[VesselBlacklistSignalResponse])
async def list_vessel_blacklist_signals(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselGovernanceService(db).list_blacklist_signals(vessel_id)


@router.post("/{vessel_id}/blacklist-signals", response_model=VesselBlacklistSignalResponse)
async def create_vessel_blacklist_signal(
    vessel_id: int,
    body: VesselBlacklistSignalCreateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselGovernanceService(db).create_blacklist_signal(
        vessel_id,
        body,
        operator_id=_operator_id(current_user),
    )


@router.patch("/{vessel_id}/blacklist-signals/{signal_id}", response_model=VesselBlacklistSignalResponse)
async def update_vessel_blacklist_signal(
    vessel_id: int,
    signal_id: int,
    body: VesselBlacklistSignalUpdateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselGovernanceService(db).update_blacklist_signal(
        vessel_id,
        signal_id,
        body,
        operator_id=_operator_id(current_user),
    )


@router.post("/{vessel_id}/blacklist-signals/{signal_id}/void", response_model=VesselBlacklistSignalResponse)
async def void_vessel_blacklist_signal(
    vessel_id: int,
    signal_id: int,
    body: VesselVoidRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselGovernanceService(db).void_blacklist_signal(
        vessel_id,
        signal_id,
        body,
        operator_id=_operator_id(current_user),
    )


@router.get("/{vessel_id}/controller-evidence", response_model=list[VesselControllerEvidenceResponse])
async def list_vessel_controller_evidence(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).list_controller_evidence(vessel_id)


@router.post("/{vessel_id}/controller-evidence", response_model=VesselControllerEvidenceResponse)
async def create_vessel_controller_evidence(
    vessel_id: int,
    body: VesselControllerEvidenceCreateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).create_controller_evidence(vessel_id, body, operator_id=_operator_id(current_user))


@router.patch("/{vessel_id}/controller-evidence/{evidence_id}", response_model=VesselControllerEvidenceResponse)
async def update_vessel_controller_evidence(
    vessel_id: int,
    evidence_id: int,
    body: VesselControllerEvidenceUpdateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).update_controller_evidence(
        vessel_id,
        evidence_id,
        body,
        operator_id=_operator_id(current_user),
    )


@router.post("/{vessel_id}/controller-evidence/{evidence_id}/void", response_model=VesselControllerEvidenceResponse)
async def void_vessel_controller_evidence(
    vessel_id: int,
    evidence_id: int,
    body: VesselVoidRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).void_controller_evidence(
        vessel_id,
        evidence_id,
        body,
        operator_id=_operator_id(current_user),
    )


@router.get("/{vessel_id}/affiliation-evidence", response_model=list[VesselAffiliationEvidenceResponse])
async def list_vessel_affiliation_evidence(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).list_affiliation_evidence(vessel_id)


@router.post("/{vessel_id}/affiliation-evidence", response_model=VesselAffiliationEvidenceResponse)
async def create_vessel_affiliation_evidence(
    vessel_id: int,
    body: VesselAffiliationEvidenceCreateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).create_affiliation_evidence(vessel_id, body, operator_id=_operator_id(current_user))


@router.patch("/{vessel_id}/affiliation-evidence/{evidence_id}", response_model=VesselAffiliationEvidenceResponse)
async def update_vessel_affiliation_evidence(
    vessel_id: int,
    evidence_id: int,
    body: VesselAffiliationEvidenceUpdateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).update_affiliation_evidence(
        vessel_id,
        evidence_id,
        body,
        operator_id=_operator_id(current_user),
    )


@router.post("/{vessel_id}/affiliation-evidence/{evidence_id}/void", response_model=VesselAffiliationEvidenceResponse)
async def void_vessel_affiliation_evidence(
    vessel_id: int,
    evidence_id: int,
    body: VesselVoidRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).void_affiliation_evidence(
        vessel_id,
        evidence_id,
        body,
        operator_id=_operator_id(current_user),
    )


@router.get("/{vessel_id}", response_model=VesselDetailResponse)
async def get_vessel_detail(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).get_detail(vessel_id)


@router.put("/{vessel_id}/profile", response_model=VesselProfileResponse)
async def update_vessel_profile(
    vessel_id: int,
    body: VesselProfileUpdateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).update_profile(vessel_id, body, operator_id=_operator_id(current_user))


@router.put("/{vessel_id}/registration", response_model=VesselRegistrationResponse)
async def upsert_vessel_registration(
    vessel_id: int,
    body: VesselRegistrationUpsertRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).upsert_registration(vessel_id, body, operator_id=_operator_id(current_user))


@router.put("/{vessel_id}/capacity", response_model=VesselCapacityResponse)
async def upsert_vessel_capacity(
    vessel_id: int,
    body: VesselCapacityUpsertRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).upsert_capacity(vessel_id, body, operator_id=_operator_id(current_user))


@router.put("/{vessel_id}/build-info", response_model=VesselBuildInfoResponse)
async def upsert_vessel_build_info(
    vessel_id: int,
    body: VesselBuildInfoUpsertRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).upsert_build_info(vessel_id, body, operator_id=_operator_id(current_user))


@router.get("/{vessel_id}/owners", response_model=list[VesselOwnerResponse])
async def list_vessel_owners(
    vessel_id: int,
    current_only: bool = True,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).list_owners(vessel_id, current_only=current_only)


@router.post("/{vessel_id}/owners", response_model=VesselOwnerResponse)
async def create_vessel_owner(
    vessel_id: int,
    body: VesselOwnerCreateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).create_owner(vessel_id, body, operator_id=_operator_id(current_user))


@router.patch("/{vessel_id}/owners/{owner_id}", response_model=VesselOwnerResponse)
async def update_vessel_owner(
    vessel_id: int,
    owner_id: int,
    body: VesselOwnerUpdateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).update_owner(vessel_id, owner_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/owners/{owner_id}/end", response_model=VesselOwnerResponse)
async def end_vessel_owner(
    vessel_id: int,
    owner_id: int,
    body: VesselRelationUpdateMeta,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).end_owner(vessel_id, owner_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/owners/{owner_id}/void", response_model=VesselOwnerResponse)
async def void_vessel_owner(
    vessel_id: int,
    owner_id: int,
    body: VesselRelationUpdateMeta,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).void_owner(vessel_id, owner_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/owners/{owner_id}/set-primary", response_model=VesselOwnerResponse)
async def set_primary_vessel_owner(
    vessel_id: int,
    owner_id: int,
    body: VesselSetPrimaryRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).set_primary_owner(vessel_id, owner_id, body, operator_id=_operator_id(current_user))


@router.put("/{vessel_id}/owners", response_model=list[VesselOwnerResponse])
async def replace_vessel_owners(
    vessel_id: int,
    body: VesselOwnerReplaceRequest,
    response: Response,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    response.headers["Deprecation"] = "true"
    response.headers["X-Replacement-Endpoint"] = "POST/PATCH/end/void/set-primary owners"
    return await VesselService(db).replace_owners(vessel_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/owners/{owner_id}/documents", response_model=VesselOwnerDocumentResponse)
async def upload_vessel_owner_document(
    vessel_id: int,
    owner_id: int,
    document_type_code: str = Form(default="OTHER"),
    file: UploadFile = File(...),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).upload_owner_document(
        vessel_id,
        owner_id,
        file,
        document_type_code=document_type_code or "OTHER",
        operator_id=_operator_id(current_user),
    )


@router.post(
    "/{vessel_id}/owners/{owner_id}/documents/{owner_document_id}/image-recognitions/{recognition_id}/confirm",
    response_model=VesselOwnerResponse,
)
async def confirm_vessel_owner_document_image_recognition(
    vessel_id: int,
    owner_id: int,
    owner_document_id: int,
    recognition_id: int,
    body: VesselOwnerDocumentImageRecognitionConfirmRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).confirm_owner_document_image_recognition(
        vessel_id,
        owner_id,
        owner_document_id,
        recognition_id,
        body,
        operator_id=_operator_id(current_user),
    )


@router.get(
    "/{vessel_id}/owners/{owner_id}/documents/{owner_document_id}/image-recognitions/{recognition_id}/field-diff",
    response_model=list[VesselRecognitionFieldDiffResponse],
)
async def get_vessel_owner_document_recognition_field_diff(
    vessel_id: int,
    owner_id: int,
    owner_document_id: int,
    recognition_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).owner_document_recognition_field_diff(
        vessel_id,
        owner_id,
        owner_document_id,
        recognition_id,
    )


@router.post(
    "/{vessel_id}/owners/{owner_id}/documents/{owner_document_id}/image-recognitions/{recognition_id}/adoptions",
    response_model=VesselOwnerResponse,
)
async def adopt_vessel_owner_document_recognition(
    vessel_id: int,
    owner_id: int,
    owner_document_id: int,
    recognition_id: int,
    body: VesselRecognitionAdoptionRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).adopt_owner_document_recognition(
        vessel_id,
        owner_id,
        owner_document_id,
        recognition_id,
        body,
        operator_id=_operator_id(current_user),
    )


@router.get("/{vessel_id}/operators", response_model=list[VesselOperatorResponse])
async def list_vessel_operators(
    vessel_id: int,
    current_only: bool = True,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).list_operators(vessel_id, current_only=current_only)


@router.post("/{vessel_id}/operators", response_model=VesselOperatorResponse)
async def create_vessel_operator(
    vessel_id: int,
    body: VesselOperatorCreateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).create_operator(vessel_id, body, operator_id=_operator_id(current_user))


@router.patch("/{vessel_id}/operators/{operator_period_id}", response_model=VesselOperatorResponse)
async def update_vessel_operator(
    vessel_id: int,
    operator_period_id: int,
    body: VesselOperatorUpdateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).update_operator(vessel_id, operator_period_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/operators/{operator_period_id}/end", response_model=VesselOperatorResponse)
async def end_vessel_operator(
    vessel_id: int,
    operator_period_id: int,
    body: VesselRelationUpdateMeta,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).end_operator(vessel_id, operator_period_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/operators/{operator_period_id}/void", response_model=VesselOperatorResponse)
async def void_vessel_operator(
    vessel_id: int,
    operator_period_id: int,
    body: VesselRelationUpdateMeta,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).void_operator(vessel_id, operator_period_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/operators/{operator_period_id}/set-primary", response_model=VesselOperatorResponse)
async def set_primary_vessel_operator(
    vessel_id: int,
    operator_period_id: int,
    body: VesselSetPrimaryRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).set_primary_operator(vessel_id, operator_period_id, body, operator_id=_operator_id(current_user))


@router.put("/{vessel_id}/operators", response_model=list[VesselOperatorResponse])
async def replace_vessel_operators(
    vessel_id: int,
    body: VesselOperatorReplaceRequest,
    response: Response,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    response.headers["Deprecation"] = "true"
    response.headers["X-Replacement-Endpoint"] = "POST/PATCH/end/void/set-primary operators"
    return await VesselService(db).replace_operators(vessel_id, body, operator_id=_operator_id(current_user))


@router.get("/{vessel_id}/contacts", response_model=list[VesselContactResponse])
async def list_vessel_contacts(
    vessel_id: int,
    current_only: bool = True,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).list_contacts(vessel_id, current_only=current_only)


@router.post("/{vessel_id}/contacts", response_model=VesselContactResponse)
async def create_vessel_contact(
    vessel_id: int,
    body: VesselContactCreateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).create_contact(vessel_id, body, operator_id=_operator_id(current_user))


@router.patch("/{vessel_id}/contacts/{contact_id}", response_model=VesselContactResponse)
async def update_vessel_contact(
    vessel_id: int,
    contact_id: int,
    body: VesselContactUpdateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).update_contact(vessel_id, contact_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/contacts/{contact_id}/end", response_model=VesselContactResponse)
async def end_vessel_contact(
    vessel_id: int,
    contact_id: int,
    body: VesselRelationUpdateMeta,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).end_contact(vessel_id, contact_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/contacts/{contact_id}/void", response_model=VesselContactResponse)
async def void_vessel_contact(
    vessel_id: int,
    contact_id: int,
    body: VesselRelationUpdateMeta,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).void_contact(vessel_id, contact_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/contacts/{contact_id}/set-primary", response_model=VesselContactResponse)
async def set_primary_vessel_contact(
    vessel_id: int,
    contact_id: int,
    body: VesselSetPrimaryRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).set_primary_contact(vessel_id, contact_id, body, operator_id=_operator_id(current_user))


@router.put("/{vessel_id}/contacts", response_model=list[VesselContactResponse])
async def replace_vessel_contacts(
    vessel_id: int,
    body: VesselContactReplaceRequest,
    response: Response,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    response.headers["Deprecation"] = "true"
    response.headers["X-Replacement-Endpoint"] = "POST/PATCH/end/void/set-primary contacts"
    return await VesselService(db).replace_contacts(vessel_id, body, operator_id=_operator_id(current_user))


@router.get("/{vessel_id}/crew", response_model=list[VesselCrewResponse])
async def list_vessel_crew(
    vessel_id: int,
    current_only: bool = True,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).list_crew(vessel_id, current_only=current_only)


@router.post("/{vessel_id}/crew", response_model=VesselCrewResponse)
async def create_vessel_crew(
    vessel_id: int,
    body: VesselCrewCreateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).create_crew(vessel_id, body, operator_id=_operator_id(current_user))


@router.patch("/{vessel_id}/crew/{crew_id}", response_model=VesselCrewResponse)
async def update_vessel_crew(
    vessel_id: int,
    crew_id: int,
    body: VesselCrewUpdateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).update_crew(vessel_id, crew_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/crew/{crew_id}/end", response_model=VesselCrewResponse)
async def end_vessel_crew(
    vessel_id: int,
    crew_id: int,
    body: VesselRelationUpdateMeta,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).end_crew(vessel_id, crew_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/crew/{crew_id}/void", response_model=VesselCrewResponse)
async def void_vessel_crew(
    vessel_id: int,
    crew_id: int,
    body: VesselRelationUpdateMeta,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).void_crew(vessel_id, crew_id, body, operator_id=_operator_id(current_user))


@router.put("/{vessel_id}/crew", response_model=list[VesselCrewResponse])
async def replace_vessel_crew(
    vessel_id: int,
    body: VesselCrewReplaceRequest,
    response: Response,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    response.headers["Deprecation"] = "true"
    response.headers["X-Replacement-Endpoint"] = "POST/PATCH/end/void crew"
    return await VesselService(db).replace_crew(vessel_id, body, operator_id=_operator_id(current_user))


@router.get("/{vessel_id}/person-certificates", response_model=list[VesselPersonCertificateResponse])
async def list_vessel_person_certificates(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).list_person_certificates(vessel_id)


@router.put("/{vessel_id}/person-certificates", response_model=list[VesselPersonCertificateResponse])
async def replace_vessel_person_certificates(
    vessel_id: int,
    body: VesselPersonCertificateReplaceRequest,
    response: Response,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    response.headers["Deprecation"] = "true"
    response.headers["X-Replacement-Endpoint"] = "POST/PUT/DELETE person-certificates"
    return await VesselService(db).replace_person_certificates(vessel_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/person-certificates", response_model=VesselPersonCertificateResponse)
async def create_vessel_person_certificate(
    vessel_id: int,
    body: VesselPersonCertificateUpdateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).create_person_certificate(vessel_id, body, operator_id=_operator_id(current_user))


@router.put("/{vessel_id}/person-certificates/{person_certificate_id}", response_model=VesselPersonCertificateResponse)
async def update_vessel_person_certificate(
    vessel_id: int,
    person_certificate_id: int,
    body: VesselPersonCertificateUpdateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).update_person_certificate(
        vessel_id,
        person_certificate_id,
        body,
        operator_id=_operator_id(current_user),
    )


@router.delete("/{vessel_id}/person-certificates/{person_certificate_id}", status_code=204)
async def delete_vessel_person_certificate(
    vessel_id: int,
    person_certificate_id: int,
    body: VesselVoidRequest | None = None,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await VesselService(db).delete_person_certificate(
        vessel_id,
        person_certificate_id,
        reason=body.reason if body else None,
        revision=body.revision if body else None,
        operator_id=_operator_id(current_user),
    )
    return Response(status_code=204)


@router.post("/{vessel_id}/person-certificate-files", response_model=VesselPersonCertificateResponse)
async def upload_vessel_person_certificate_file_first(
    vessel_id: int,
    crew_assignment_id: int = Form(...),
    certificate_type_code: str = Form(default="CREW_COMPETENCY_CERT"),
    file: UploadFile = File(...),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).upload_person_certificate_file_first(
        vessel_id,
        file,
        crew_assignment_id=crew_assignment_id,
        certificate_type_code=certificate_type_code or "CREW_COMPETENCY_CERT",
        operator_id=_operator_id(current_user),
    )


@router.post(
    "/{vessel_id}/person-certificates/{person_certificate_id}/files",
    response_model=VesselPersonCertificateFileResponse,
)
async def upload_vessel_person_certificate_file(
    vessel_id: int,
    person_certificate_id: int,
    file: UploadFile = File(...),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).upload_person_certificate_file(
        vessel_id,
        person_certificate_id,
        file,
        operator_id=_operator_id(current_user),
    )


@router.delete("/{vessel_id}/person-certificates/{person_certificate_id}/files/{file_id}", status_code=204)
async def void_vessel_person_certificate_file(
    vessel_id: int,
    person_certificate_id: int,
    file_id: int,
    body: VesselVoidRequest | None = None,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await VesselService(db).void_person_certificate_file(
        vessel_id,
        person_certificate_id,
        file_id,
        reason=body.reason if body else None,
        operator_id=_operator_id(current_user),
    )
    return Response(status_code=204)


@router.post(
    "/{vessel_id}/person-certificates/{person_certificate_id}/image-recognitions",
    response_model=VesselPersonCertificateImageRecognitionResponse,
)
async def create_vessel_person_certificate_image_recognition(
    vessel_id: int,
    person_certificate_id: int,
    body: VesselPersonCertificateImageRecognitionCreateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).create_person_certificate_image_recognition(
        vessel_id,
        person_certificate_id,
        body,
        operator_id=_operator_id(current_user),
    )


@router.get(
    "/{vessel_id}/person-certificates/{person_certificate_id}/image-recognitions",
    response_model=PageResponse[VesselPersonCertificateImageRecognitionResponse],
)
async def list_vessel_person_certificate_image_recognitions(
    vessel_id: int,
    person_certificate_id: int,
    query: VesselRecognitionHistoryQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).list_person_certificate_image_recognitions(
        vessel_id,
        person_certificate_id,
        page=query.page,
        page_size=query.page_size,
    )


@router.post(
    "/{vessel_id}/person-certificates/{person_certificate_id}/image-recognitions/{recognition_id}/confirm",
    response_model=VesselPersonCertificateResponse,
)
async def confirm_vessel_person_certificate_image_recognition(
    vessel_id: int,
    person_certificate_id: int,
    recognition_id: int,
    body: VesselPersonCertificateImageRecognitionConfirmRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).confirm_person_certificate_image_recognition(
        vessel_id,
        person_certificate_id,
        recognition_id,
        body,
        operator_id=_operator_id(current_user),
    )


@router.get(
    "/{vessel_id}/person-certificates/{person_certificate_id}/image-recognitions/{recognition_id}/field-diff",
    response_model=list[VesselRecognitionFieldDiffResponse],
)
async def get_vessel_person_certificate_recognition_field_diff(
    vessel_id: int,
    person_certificate_id: int,
    recognition_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).person_certificate_recognition_field_diff(
        vessel_id,
        person_certificate_id,
        recognition_id,
    )


@router.post(
    "/{vessel_id}/person-certificates/{person_certificate_id}/image-recognitions/{recognition_id}/adoptions",
    response_model=VesselPersonCertificateResponse,
)
async def adopt_vessel_person_certificate_recognition(
    vessel_id: int,
    person_certificate_id: int,
    recognition_id: int,
    body: VesselRecognitionAdoptionRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).adopt_person_certificate_recognition(
        vessel_id,
        person_certificate_id,
        recognition_id,
        body,
        operator_id=_operator_id(current_user),
    )


@router.get("/{vessel_id}/certificates", response_model=list[VesselCertificateResponse])
async def list_vessel_certificates(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).list_certificates(vessel_id)


@router.get("/{vessel_id}/certificates/ledger", response_model=list[VesselCertificateLedgerItemResponse])
async def get_vessel_certificate_ledger(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).get_certificate_ledger(vessel_id)


@router.post("/{vessel_id}/certificates", response_model=VesselCertificateResponse)
async def create_vessel_certificate(
    vessel_id: int,
    body: VesselCertificateCreateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).create_certificate(vessel_id, body, operator_id=_operator_id(current_user))


@router.put("/{vessel_id}/certificates/{certificate_id}", response_model=VesselCertificateResponse)
async def update_vessel_certificate(
    vessel_id: int,
    certificate_id: int,
    body: VesselCertificateUpdateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).update_certificate(vessel_id, certificate_id, body, operator_id=_operator_id(current_user))


@router.delete("/{vessel_id}/certificates/{certificate_id}", status_code=204)
async def void_vessel_certificate(
    vessel_id: int,
    certificate_id: int,
    body: VesselVoidRequest | None = None,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await VesselService(db).void_certificate(
        vessel_id,
        certificate_id,
        reason=body.reason if body else None,
        operator_id=_operator_id(current_user),
    )
    return Response(status_code=204)


@router.post("/{vessel_id}/certificate-files", response_model=VesselCertificateResponse)
async def upload_vessel_certificate_file_first(
    vessel_id: int,
    certificate_type_code: str = Form(default="UNKNOWN"),
    file: UploadFile = File(...),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).upload_certificate_file_first(
        vessel_id,
        file,
        certificate_type_code=certificate_type_code or "UNKNOWN",
        operator_id=_operator_id(current_user),
    )


@router.post("/{vessel_id}/certificates/{certificate_id}/files", response_model=VesselCertificateFileResponse)
async def upload_vessel_certificate_file(
    vessel_id: int,
    certificate_id: int,
    file: UploadFile = File(...),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).upload_certificate_file(
        vessel_id,
        certificate_id,
        file,
        operator_id=_operator_id(current_user),
    )


@router.delete("/{vessel_id}/certificates/{certificate_id}/files/{file_id}", status_code=204)
async def void_vessel_certificate_file(
    vessel_id: int,
    certificate_id: int,
    file_id: int,
    body: VesselVoidRequest | None = None,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await VesselService(db).void_certificate_file(
        vessel_id,
        certificate_id,
        file_id,
        reason=body.reason if body else None,
        operator_id=_operator_id(current_user),
    )
    return Response(status_code=204)


@router.post(
    "/{vessel_id}/certificates/{certificate_id}/image-recognitions",
    response_model=VesselCertificateImageRecognitionResponse,
)
async def create_vessel_certificate_image_recognition(
    vessel_id: int,
    certificate_id: int,
    body: VesselCertificateImageRecognitionCreateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).create_certificate_image_recognition(
        vessel_id,
        certificate_id,
        body,
        operator_id=_operator_id(current_user),
    )


@router.get(
    "/{vessel_id}/certificates/{certificate_id}/image-recognitions",
    response_model=PageResponse[VesselCertificateImageRecognitionResponse],
)
async def list_vessel_certificate_image_recognitions(
    vessel_id: int,
    certificate_id: int,
    query: VesselRecognitionHistoryQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).list_certificate_image_recognitions(
        vessel_id,
        certificate_id,
        page=query.page,
        page_size=query.page_size,
    )


@router.post(
    "/{vessel_id}/certificates/{certificate_id}/image-recognitions/{recognition_id}/confirm",
    response_model=VesselCertificateResponse,
)
async def confirm_vessel_certificate_image_recognition(
    vessel_id: int,
    certificate_id: int,
    recognition_id: int,
    body: VesselCertificateImageRecognitionConfirmRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).confirm_certificate_image_recognition(
        vessel_id,
        certificate_id,
        recognition_id,
        body,
        operator_id=_operator_id(current_user),
    )


@router.get(
    "/{vessel_id}/certificates/{certificate_id}/image-recognitions/{recognition_id}/field-diff",
    response_model=list[VesselRecognitionFieldDiffResponse],
)
async def get_vessel_certificate_recognition_field_diff(
    vessel_id: int,
    certificate_id: int,
    recognition_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).certificate_recognition_field_diff(vessel_id, certificate_id, recognition_id)


@router.post(
    "/{vessel_id}/certificates/{certificate_id}/image-recognitions/{recognition_id}/adoptions",
    response_model=VesselCertificateResponse,
)
async def adopt_vessel_certificate_recognition(
    vessel_id: int,
    certificate_id: int,
    recognition_id: int,
    body: VesselRecognitionAdoptionRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).adopt_certificate_recognition(
        vessel_id,
        certificate_id,
        recognition_id,
        body,
        operator_id=_operator_id(current_user),
    )


@router.delete("/{vessel_id}/owners/{owner_id}/documents/{owner_document_id}", status_code=204)
async def void_vessel_owner_document(
    vessel_id: int,
    owner_id: int,
    owner_document_id: int,
    body: VesselVoidRequest | None = None,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await VesselService(db).void_owner_document(
        vessel_id,
        owner_id,
        owner_document_id,
        reason=body.reason if body else None,
        operator_id=_operator_id(current_user),
    )
    return Response(status_code=204)


@router.get(
    "/{vessel_id}/owners/{owner_id}/documents/{owner_document_id}/image-recognitions",
    response_model=PageResponse[VesselOwnerDocumentImageRecognitionResponse],
)
async def list_vessel_owner_document_image_recognitions(
    vessel_id: int,
    owner_id: int,
    owner_document_id: int,
    query: VesselRecognitionHistoryQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).list_owner_document_image_recognitions(
        vessel_id,
        owner_id,
        owner_document_id,
        page=query.page,
        page_size=query.page_size,
    )


@router.post("/{vessel_id}/owner-transfer", response_model=VesselProfileResponse)
async def transfer_vessel_owner(
    vessel_id: int,
    body: VesselOwnerTransferRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).owner_transfer(vessel_id, body, operator_id=_operator_id(current_user))


@router.get("/{vessel_id}/change-events", response_model=list[VesselChangeEventResponse])
async def get_vessel_change_events(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).get_change_events(vessel_id)


@router.get("/{vessel_id}/quality-issues", response_model=PageResponse[VesselQualityIssueResponse])
async def list_vessel_quality_issues(
    vessel_id: int,
    query: VesselQualityIssueQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).list_quality_issues(vessel_id, query)
