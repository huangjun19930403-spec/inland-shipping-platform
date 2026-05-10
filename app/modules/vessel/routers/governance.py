"""Vessel governance routes."""

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
    VesselBlacklistSignalGlobalQuery,
    VesselBlacklistSignalListItemResponse,
    VesselBlacklistSignalResponse,
    VesselBlacklistSignalUpdateRequest,
    VesselAffiliationConclusionResponse,
    VesselControllerConclusionResponse,
    VesselDetailResponse,
    VesselGovernanceDashboardResponse,
    VesselGovernanceRuleResponse,
    VesselGovernanceSyncBatchResponse,
    VesselGovernanceTaskActionRequest,
    VesselGovernanceTaskQuery,
    VesselGovernanceTaskResponse,
    VesselGovernanceTaskSyncResponse,
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
    VesselQualityIssueRecheckResponse,
    VesselQualityIssueResponse,
    VesselRelationConclusionSummaryResponse,
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
from app.modules.vessel.services.governance_task_service import VesselGovernanceTaskService

router = APIRouter()


def _operator_id(current_user: SysUser) -> int | None:
    return int(current_user.id) if current_user is not None else None




@router.get("/blacklist-signals", response_model=PageResponse[VesselBlacklistSignalListItemResponse])
async def list_vessel_blacklist_signal_queue(
    query: VesselBlacklistSignalGlobalQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselGovernanceTaskService(db).list_blacklist_signal_queue(query)


@router.get("/governance/dashboard", response_model=VesselGovernanceDashboardResponse)
async def get_vessel_governance_dashboard(
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselGovernanceTaskService(db).dashboard()


@router.get("/governance/tasks", response_model=PageResponse[VesselGovernanceTaskResponse])
async def list_vessel_governance_tasks(
    query: VesselGovernanceTaskQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselGovernanceTaskService(db).list_tasks(query)


@router.post("/governance/tasks/sync", response_model=VesselGovernanceTaskSyncResponse)
async def sync_vessel_governance_tasks(
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselGovernanceTaskService(db).sync_tasks_command(operator_id=_operator_id(current_user))


@router.get("/governance/sync-batches/{batch_id}", response_model=VesselGovernanceSyncBatchResponse)
async def get_vessel_governance_sync_batch(
    batch_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselGovernanceTaskService(db).get_sync_batch(batch_id)


@router.get("/governance/rules", response_model=list[VesselGovernanceRuleResponse])
async def list_vessel_governance_rules(
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselGovernanceTaskService(db).list_rule_catalog()


@router.patch("/governance/tasks/{task_id}", response_model=VesselGovernanceTaskResponse)
async def update_vessel_governance_task(
    task_id: int,
    body: VesselGovernanceTaskActionRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselGovernanceTaskService(db).update_task(
        task_id,
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
    return await VesselGovernanceTaskService(db).list_blacklist_signals(vessel_id)


@router.post("/{vessel_id}/blacklist-signals", response_model=VesselBlacklistSignalResponse)
async def create_vessel_blacklist_signal(
    vessel_id: int,
    body: VesselBlacklistSignalCreateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselGovernanceTaskService(db).create_blacklist_signal(
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
    return await VesselGovernanceTaskService(db).update_blacklist_signal(
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
    return await VesselGovernanceTaskService(db).void_blacklist_signal(
        vessel_id,
        signal_id,
        body,
        operator_id=_operator_id(current_user),
    )
