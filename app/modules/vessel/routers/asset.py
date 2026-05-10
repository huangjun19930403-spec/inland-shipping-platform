"""Vessel asset routes."""

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
    VesselSummaryRefreshBatchRequest,
    VesselSummaryRefreshBatchResponse,
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
from app.modules.vessel.services.asset_service import VesselAssetService

router = APIRouter()


def _operator_id(current_user: SysUser) -> int | None:
    return int(current_user.id) if current_user is not None else None




@router.get("/assets/summary", response_model=VesselAssetSummaryResponse)
async def get_vessel_asset_summary(
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAssetService(db).asset_summary()


@router.get("/assets", response_model=VesselAssetPageResponse)
async def list_vessel_assets(
    query: VesselAssetListQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAssetService(db).list_assets(query)


@router.post("/{vessel_id}/summary/refresh", response_model=VesselAssetListItemResponse)
async def refresh_vessel_summary(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAssetService(db).refresh_vessel_summary(vessel_id)

@router.post("/summaries/refresh-batch", response_model=VesselSummaryRefreshBatchResponse)
async def refresh_vessel_summaries_batch(
    body: VesselSummaryRefreshBatchRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAssetService(db).refresh_vessel_summaries_batch(body)


@router.get("", response_model=PageResponse[VesselListItemResponse])
async def list_vessels(
    query: VesselListQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAssetService(db).list_vessels(query)


@router.post("", response_model=VesselProfileResponse)
async def create_vessel(
    body: VesselCreateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselAssetService(db).create_vessel(body, operator_id=_operator_id(current_user))


@router.get("/{vessel_id}/profile-card", response_model=VesselProfileCardResponse)
async def get_vessel_profile_card(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAssetService(db).get_profile_card(vessel_id)


@router.get("/{vessel_id}/profile-card/evidence", response_model=VesselProfileCardEvidenceResponse)
async def get_vessel_profile_card_evidence(
    vessel_id: int,
    query: VesselProfileCardEvidenceQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAssetService(db).get_profile_card_evidence(vessel_id, query)


@router.get("/{vessel_id}", response_model=VesselDetailResponse)
async def get_vessel_detail(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAssetService(db).get_detail(vessel_id)


@router.put("/{vessel_id}/profile", response_model=VesselProfileResponse)
async def update_vessel_profile(
    vessel_id: int,
    body: VesselProfileUpdateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselAssetService(db).update_profile(vessel_id, body, operator_id=_operator_id(current_user))


@router.put("/{vessel_id}/registration", response_model=VesselRegistrationResponse)
async def upsert_vessel_registration(
    vessel_id: int,
    body: VesselRegistrationUpsertRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselAssetService(db).upsert_registration(vessel_id, body, operator_id=_operator_id(current_user))


@router.put("/{vessel_id}/capacity", response_model=VesselCapacityResponse)
async def upsert_vessel_capacity(
    vessel_id: int,
    body: VesselCapacityUpsertRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselAssetService(db).upsert_capacity(vessel_id, body, operator_id=_operator_id(current_user))


@router.put("/{vessel_id}/build-info", response_model=VesselBuildInfoResponse)
async def upsert_vessel_build_info(
    vessel_id: int,
    body: VesselBuildInfoUpsertRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselAssetService(db).upsert_build_info(vessel_id, body, operator_id=_operator_id(current_user))


@router.get("/{vessel_id}/person-certificates", response_model=list[VesselPersonCertificateResponse])
async def list_vessel_person_certificates(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAssetService(db).list_person_certificates(vessel_id)


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
    return await VesselAssetService(db).replace_person_certificates(vessel_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/person-certificates", response_model=VesselPersonCertificateResponse)
async def create_vessel_person_certificate(
    vessel_id: int,
    body: VesselPersonCertificateUpdateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselAssetService(db).create_person_certificate(vessel_id, body, operator_id=_operator_id(current_user))


@router.put("/{vessel_id}/person-certificates/{person_certificate_id}", response_model=VesselPersonCertificateResponse)
async def update_vessel_person_certificate(
    vessel_id: int,
    person_certificate_id: int,
    body: VesselPersonCertificateUpdateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselAssetService(db).update_person_certificate(
        vessel_id,
        person_certificate_id,
        body,
        operator_id=_operator_id(current_user),
    )


@router.delete("/{vessel_id}/person-certificates/{person_certificate_id}", status_code=204)
async def void_vessel_person_certificate(
    vessel_id: int,
    person_certificate_id: int,
    body: VesselVoidRequest | None = None,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await VesselAssetService(db).void_person_certificate(
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
    return await VesselAssetService(db).upload_person_certificate_file_first(
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
    return await VesselAssetService(db).upload_person_certificate_file(
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
    await VesselAssetService(db).void_person_certificate_file(
        vessel_id,
        person_certificate_id,
        file_id,
        reason=body.reason if body else None,
        operator_id=_operator_id(current_user),
    )
    return Response(status_code=204)


@router.get("/{vessel_id}/certificates", response_model=list[VesselCertificateResponse])
async def list_vessel_certificates(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAssetService(db).list_certificates(vessel_id)


@router.get("/{vessel_id}/certificates/ledger", response_model=list[VesselCertificateLedgerItemResponse])
async def get_vessel_certificate_ledger(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAssetService(db).get_certificate_ledger(vessel_id)


@router.post("/{vessel_id}/certificates", response_model=VesselCertificateResponse)
async def create_vessel_certificate(
    vessel_id: int,
    body: VesselCertificateCreateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselAssetService(db).create_certificate(vessel_id, body, operator_id=_operator_id(current_user))


@router.put("/{vessel_id}/certificates/{certificate_id}", response_model=VesselCertificateResponse)
async def update_vessel_certificate(
    vessel_id: int,
    certificate_id: int,
    body: VesselCertificateUpdateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselAssetService(db).update_certificate(vessel_id, certificate_id, body, operator_id=_operator_id(current_user))


@router.delete("/{vessel_id}/certificates/{certificate_id}", status_code=204)
async def void_vessel_certificate(
    vessel_id: int,
    certificate_id: int,
    body: VesselVoidRequest | None = None,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await VesselAssetService(db).void_certificate(
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
    return await VesselAssetService(db).upload_certificate_file_first(
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
    return await VesselAssetService(db).upload_certificate_file(
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
    await VesselAssetService(db).void_certificate_file(
        vessel_id,
        certificate_id,
        file_id,
        reason=body.reason if body else None,
        operator_id=_operator_id(current_user),
    )
    return Response(status_code=204)
