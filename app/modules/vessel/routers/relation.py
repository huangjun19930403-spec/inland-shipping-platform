"""Vessel relation routes."""

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
    VesselRelationConclusionConflictResolveRequest,
    VesselRelationEvidenceAttachmentResponse,
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
from app.modules.vessel.relation.service import VesselRelationService

router = APIRouter()


def _operator_id(current_user: SysUser) -> int | None:
    return int(current_user.id) if current_user is not None else None




@router.get("/{vessel_id}/controller-evidence", response_model=list[VesselControllerEvidenceResponse])
async def list_vessel_controller_evidence(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselRelationService(db).list_controller_evidence(vessel_id)


@router.post("/{vessel_id}/controller-evidence", response_model=VesselControllerEvidenceResponse)
async def create_vessel_controller_evidence(
    vessel_id: int,
    body: VesselControllerEvidenceCreateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).create_controller_evidence(vessel_id, body, operator_id=_operator_id(current_user))


@router.patch("/{vessel_id}/controller-evidence/{evidence_id}", response_model=VesselControllerEvidenceResponse)
async def update_vessel_controller_evidence(
    vessel_id: int,
    evidence_id: int,
    body: VesselControllerEvidenceUpdateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).update_controller_evidence(
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
    return await VesselRelationService(db).void_controller_evidence(
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
    return await VesselRelationService(db).list_affiliation_evidence(vessel_id)


@router.post("/{vessel_id}/affiliation-evidence", response_model=VesselAffiliationEvidenceResponse)
async def create_vessel_affiliation_evidence(
    vessel_id: int,
    body: VesselAffiliationEvidenceCreateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).create_affiliation_evidence(vessel_id, body, operator_id=_operator_id(current_user))


@router.patch("/{vessel_id}/affiliation-evidence/{evidence_id}", response_model=VesselAffiliationEvidenceResponse)
async def update_vessel_affiliation_evidence(
    vessel_id: int,
    evidence_id: int,
    body: VesselAffiliationEvidenceUpdateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).update_affiliation_evidence(
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
    return await VesselRelationService(db).void_affiliation_evidence(
        vessel_id,
        evidence_id,
        body,
        operator_id=_operator_id(current_user),
    )


@router.get("/{vessel_id}/relation-conclusions", response_model=VesselRelationConclusionSummaryResponse)
async def list_vessel_relation_conclusions(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselRelationService(db).list_relation_conclusions(vessel_id)


@router.post("/{vessel_id}/relation-conclusions/rebuild-candidates", response_model=VesselRelationConclusionSummaryResponse)
async def rebuild_vessel_relation_conclusion_candidates(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).rebuild_relation_conclusion_candidates(vessel_id, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/controller-conclusions/{conclusion_id}/confirm", response_model=VesselControllerConclusionResponse)
async def confirm_vessel_controller_conclusion(
    vessel_id: int,
    conclusion_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).confirm_controller_conclusion(vessel_id, conclusion_id, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/affiliation-conclusions/{conclusion_id}/confirm", response_model=VesselAffiliationConclusionResponse)
async def confirm_vessel_affiliation_conclusion(
    vessel_id: int,
    conclusion_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).confirm_affiliation_conclusion(vessel_id, conclusion_id, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/controller-conclusions/{conclusion_id}/void", response_model=VesselControllerConclusionResponse)
async def void_vessel_controller_conclusion(
    vessel_id: int,
    conclusion_id: int,
    body: VesselVoidRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).void_controller_conclusion(vessel_id, conclusion_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/affiliation-conclusions/{conclusion_id}/void", response_model=VesselAffiliationConclusionResponse)
async def void_vessel_affiliation_conclusion(
    vessel_id: int,
    conclusion_id: int,
    body: VesselVoidRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).void_affiliation_conclusion(vessel_id, conclusion_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/relation-evidence/{evidence_type}/{evidence_id}/attachments", response_model=VesselRelationEvidenceAttachmentResponse)
async def upload_vessel_relation_evidence_attachment(
    vessel_id: int,
    evidence_type: str,
    evidence_id: int,
    file: UploadFile = File(...),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).upload_relation_evidence_attachment(
        vessel_id,
        evidence_type,
        evidence_id,
        file,
        operator_id=_operator_id(current_user),
    )


@router.delete("/{vessel_id}/relation-evidence/{evidence_type}/{evidence_id}/attachments/{attachment_id}", response_model=VesselRelationEvidenceAttachmentResponse)
async def void_vessel_relation_evidence_attachment(
    vessel_id: int,
    evidence_type: str,
    evidence_id: int,
    attachment_id: int,
    reason: str | None = None,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).void_relation_evidence_attachment(
        vessel_id,
        evidence_type,
        evidence_id,
        attachment_id,
        reason=reason,
        operator_id=_operator_id(current_user),
    )


@router.post("/{vessel_id}/relation-conclusions/{conclusion_type}/{conclusion_id}/resolve-conflict", response_model=VesselRelationConclusionSummaryResponse)
async def resolve_vessel_relation_conclusion_conflict(
    vessel_id: int,
    conclusion_type: str,
    conclusion_id: int,
    body: VesselRelationConclusionConflictResolveRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).resolve_relation_conclusion_conflict(
        vessel_id,
        conclusion_type,
        conclusion_id,
        body,
        operator_id=_operator_id(current_user),
    )


@router.get("/{vessel_id}/owners", response_model=list[VesselOwnerResponse])
async def list_vessel_owners(
    vessel_id: int,
    current_only: bool = True,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselRelationService(db).list_owners(vessel_id, current_only=current_only)


@router.post("/{vessel_id}/owners", response_model=VesselOwnerResponse)
async def create_vessel_owner(
    vessel_id: int,
    body: VesselOwnerCreateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).create_owner(vessel_id, body, operator_id=_operator_id(current_user))


@router.patch("/{vessel_id}/owners/{owner_id}", response_model=VesselOwnerResponse)
async def update_vessel_owner(
    vessel_id: int,
    owner_id: int,
    body: VesselOwnerUpdateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).update_owner(vessel_id, owner_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/owners/{owner_id}/end", response_model=VesselOwnerResponse)
async def end_vessel_owner(
    vessel_id: int,
    owner_id: int,
    body: VesselRelationUpdateMeta,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).end_owner(vessel_id, owner_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/owners/{owner_id}/void", response_model=VesselOwnerResponse)
async def void_vessel_owner(
    vessel_id: int,
    owner_id: int,
    body: VesselRelationUpdateMeta,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).void_owner(vessel_id, owner_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/owners/{owner_id}/set-primary", response_model=VesselOwnerResponse)
async def set_primary_vessel_owner(
    vessel_id: int,
    owner_id: int,
    body: VesselSetPrimaryRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).set_primary_owner(vessel_id, owner_id, body, operator_id=_operator_id(current_user))


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
    return await VesselRelationService(db).replace_owners(vessel_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/owners/{owner_id}/documents", response_model=VesselOwnerDocumentResponse)
async def upload_vessel_owner_document(
    vessel_id: int,
    owner_id: int,
    document_type_code: str = Form(default="OTHER"),
    file: UploadFile = File(...),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).upload_owner_document(
        vessel_id,
        owner_id,
        file,
        document_type_code=document_type_code or "OTHER",
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
    return await VesselRelationService(db).list_operators(vessel_id, current_only=current_only)


@router.post("/{vessel_id}/operators", response_model=VesselOperatorResponse)
async def create_vessel_operator(
    vessel_id: int,
    body: VesselOperatorCreateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).create_operator(vessel_id, body, operator_id=_operator_id(current_user))


@router.patch("/{vessel_id}/operators/{operator_period_id}", response_model=VesselOperatorResponse)
async def update_vessel_operator(
    vessel_id: int,
    operator_period_id: int,
    body: VesselOperatorUpdateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).update_operator(vessel_id, operator_period_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/operators/{operator_period_id}/end", response_model=VesselOperatorResponse)
async def end_vessel_operator(
    vessel_id: int,
    operator_period_id: int,
    body: VesselRelationUpdateMeta,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).end_operator(vessel_id, operator_period_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/operators/{operator_period_id}/void", response_model=VesselOperatorResponse)
async def void_vessel_operator(
    vessel_id: int,
    operator_period_id: int,
    body: VesselRelationUpdateMeta,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).void_operator(vessel_id, operator_period_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/operators/{operator_period_id}/set-primary", response_model=VesselOperatorResponse)
async def set_primary_vessel_operator(
    vessel_id: int,
    operator_period_id: int,
    body: VesselSetPrimaryRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).set_primary_operator(vessel_id, operator_period_id, body, operator_id=_operator_id(current_user))


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
    return await VesselRelationService(db).replace_operators(vessel_id, body, operator_id=_operator_id(current_user))


@router.get("/{vessel_id}/contacts", response_model=list[VesselContactResponse])
async def list_vessel_contacts(
    vessel_id: int,
    current_only: bool = True,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselRelationService(db).list_contacts(vessel_id, current_only=current_only)


@router.post("/{vessel_id}/contacts", response_model=VesselContactResponse)
async def create_vessel_contact(
    vessel_id: int,
    body: VesselContactCreateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).create_contact(vessel_id, body, operator_id=_operator_id(current_user))


@router.patch("/{vessel_id}/contacts/{contact_id}", response_model=VesselContactResponse)
async def update_vessel_contact(
    vessel_id: int,
    contact_id: int,
    body: VesselContactUpdateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).update_contact(vessel_id, contact_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/contacts/{contact_id}/end", response_model=VesselContactResponse)
async def end_vessel_contact(
    vessel_id: int,
    contact_id: int,
    body: VesselRelationUpdateMeta,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).end_contact(vessel_id, contact_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/contacts/{contact_id}/void", response_model=VesselContactResponse)
async def void_vessel_contact(
    vessel_id: int,
    contact_id: int,
    body: VesselRelationUpdateMeta,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).void_contact(vessel_id, contact_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/contacts/{contact_id}/set-primary", response_model=VesselContactResponse)
async def set_primary_vessel_contact(
    vessel_id: int,
    contact_id: int,
    body: VesselSetPrimaryRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).set_primary_contact(vessel_id, contact_id, body, operator_id=_operator_id(current_user))


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
    return await VesselRelationService(db).replace_contacts(vessel_id, body, operator_id=_operator_id(current_user))


@router.get("/{vessel_id}/crew", response_model=list[VesselCrewResponse])
async def list_vessel_crew(
    vessel_id: int,
    current_only: bool = True,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselRelationService(db).list_crew(vessel_id, current_only=current_only)


@router.post("/{vessel_id}/crew", response_model=VesselCrewResponse)
async def create_vessel_crew(
    vessel_id: int,
    body: VesselCrewCreateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).create_crew(vessel_id, body, operator_id=_operator_id(current_user))


@router.patch("/{vessel_id}/crew/{crew_id}", response_model=VesselCrewResponse)
async def update_vessel_crew(
    vessel_id: int,
    crew_id: int,
    body: VesselCrewUpdateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).update_crew(vessel_id, crew_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/crew/{crew_id}/end", response_model=VesselCrewResponse)
async def end_vessel_crew(
    vessel_id: int,
    crew_id: int,
    body: VesselRelationUpdateMeta,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).end_crew(vessel_id, crew_id, body, operator_id=_operator_id(current_user))


@router.post("/{vessel_id}/crew/{crew_id}/void", response_model=VesselCrewResponse)
async def void_vessel_crew(
    vessel_id: int,
    crew_id: int,
    body: VesselRelationUpdateMeta,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).void_crew(vessel_id, crew_id, body, operator_id=_operator_id(current_user))


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
    return await VesselRelationService(db).replace_crew(vessel_id, body, operator_id=_operator_id(current_user))


@router.delete("/{vessel_id}/owners/{owner_id}/documents/{owner_document_id}", status_code=204)
async def void_vessel_owner_document(
    vessel_id: int,
    owner_id: int,
    owner_document_id: int,
    body: VesselVoidRequest | None = None,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await VesselRelationService(db).void_owner_document(
        vessel_id,
        owner_id,
        owner_document_id,
        reason=body.reason if body else None,
        operator_id=_operator_id(current_user),
    )
    return Response(status_code=204)


@router.post("/{vessel_id}/owner-transfer", response_model=VesselProfileResponse)
async def transfer_vessel_owner(
    vessel_id: int,
    body: VesselOwnerTransferRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselRelationService(db).owner_transfer(vessel_id, body, operator_id=_operator_id(current_user))


@router.get("/{vessel_id}/change-events", response_model=list[VesselChangeEventResponse])
async def get_vessel_change_events(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselRelationService(db).get_change_events(vessel_id)
