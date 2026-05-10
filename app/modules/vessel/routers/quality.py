"""Vessel quality routes."""

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
    VesselQualityIssueBatchRecheckRequest,
    VesselQualityIssueBatchRecheckResponse,
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
from app.modules.vessel.services.quality_service import VesselQualityService

router = APIRouter()


def _operator_id(current_user: SysUser) -> int | None:
    return int(current_user.id) if current_user is not None else None




@router.get("/quality", response_model=PageResponse[VesselQualityIssueListItemResponse])
async def list_vessel_quality_queue(
    query: VesselQualityIssueGlobalQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselQualityService(db).list_quality_issue_queue(query)


@router.post("/quality/{issue_id}/recheck", response_model=VesselQualityIssueRecheckResponse)
async def recheck_vessel_quality_issue(
    issue_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselQualityService(db).recheck_quality_issue(issue_id, operator_id=_operator_id(current_user))


@router.post("/quality/recheck-batch", response_model=VesselQualityIssueBatchRecheckResponse)
async def recheck_vessel_quality_issue_batch(
    body: VesselQualityIssueBatchRecheckRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselQualityService(db).recheck_quality_issues_batch(body, operator_id=_operator_id(current_user))


@router.get("/{vessel_id}/quality-issues", response_model=PageResponse[VesselQualityIssueResponse])
async def list_vessel_quality_issues(
    vessel_id: int,
    query: VesselQualityIssueQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselQualityService(db).list_quality_issues(vessel_id, query)
