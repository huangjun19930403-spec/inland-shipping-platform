"""Vessel candidate routes."""

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
from app.modules.vessel.candidate_service import VesselCandidateAnalysisService
from app.modules.vessel.governance_service import VesselGovernanceService

router = APIRouter()


def _operator_id(current_user: SysUser) -> int | None:
    return int(current_user.id) if current_user is not None else None




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
