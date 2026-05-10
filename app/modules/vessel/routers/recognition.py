"""Vessel recognition routes."""

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
from app.modules.vessel.services.recognition_service import VesselRecognitionService

router = APIRouter()


def _operator_id(current_user: SysUser) -> int | None:
    return int(current_user.id) if current_user is not None else None




@router.get("/recognitions", response_model=PageResponse[VesselRecognitionQueueItemResponse])
async def list_vessel_recognition_queue(
    query: VesselRecognitionQueueQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselRecognitionService(db).list_recognition_queue(query)


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
    return await VesselRecognitionService(db).unified_recognition_field_diff(recognition_type, recognition_id)


@router.post("/recognitions/{recognition_type}/{recognition_id}/adoptions")
async def adopt_vessel_unified_recognition(
    recognition_type: str,
    recognition_id: int,
    body: VesselRecognitionAdoptionRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRecognitionService(db).unified_recognition_adoption(
        recognition_type,
        recognition_id,
        body,
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
    return await VesselRecognitionService(db).confirm_owner_document_image_recognition(
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
    return await VesselRecognitionService(db).owner_document_recognition_field_diff(
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
    return await VesselRecognitionService(db).adopt_owner_document_recognition(
        vessel_id,
        owner_id,
        owner_document_id,
        recognition_id,
        body,
        operator_id=_operator_id(current_user),
    )


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
    return await VesselRecognitionService(db).create_person_certificate_image_recognition(
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
    return await VesselRecognitionService(db).list_person_certificate_image_recognitions(
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
    return await VesselRecognitionService(db).confirm_person_certificate_image_recognition(
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
    return await VesselRecognitionService(db).person_certificate_recognition_field_diff(
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
    return await VesselRecognitionService(db).adopt_person_certificate_recognition(
        vessel_id,
        person_certificate_id,
        recognition_id,
        body,
        operator_id=_operator_id(current_user),
    )


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
    return await VesselRecognitionService(db).create_certificate_image_recognition(
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
    return await VesselRecognitionService(db).list_certificate_image_recognitions(
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
    return await VesselRecognitionService(db).confirm_certificate_image_recognition(
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
    return await VesselRecognitionService(db).certificate_recognition_field_diff(vessel_id, certificate_id, recognition_id)


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
    return await VesselRecognitionService(db).adopt_certificate_recognition(
        vessel_id,
        certificate_id,
        recognition_id,
        body,
        operator_id=_operator_id(current_user),
    )


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
    return await VesselRecognitionService(db).list_owner_document_image_recognitions(
        vessel_id,
        owner_id,
        owner_document_id,
        page=query.page,
        page_size=query.page_size,
    )
