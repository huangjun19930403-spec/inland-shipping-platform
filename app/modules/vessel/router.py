"""vessel 模块 router。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.system import SysUser
from app.modules.vessel.schemas import (
    PageResponse,
    VesselBehaviorProfileResponse,
    VesselBuildInfoResponse,
    VesselBuildInfoUpsertRequest,
    VesselCapacityResponse,
    VesselCapacityUpsertRequest,
    VesselCargoCapabilityResponse,
    VesselCargoCapabilityUpsertRequest,
    VesselCertificateCreateRequest,
    VesselCertificateFileResponse,
    VesselCertificateImageRecognitionConfirmRequest,
    VesselCertificateImageRecognitionCreateRequest,
    VesselCertificateImageRecognitionResponse,
    VesselCertificateResponse,
    VesselCertificateUpdateRequest,
    VesselChangeEventResponse,
    VesselContactReplaceRequest,
    VesselContactResponse,
    VesselCreateRequest,
    VesselCrewReplaceRequest,
    VesselCrewResponse,
    VesselDashboardResponse,
    VesselDetailResponse,
    VesselGovernanceSummaryResponse,
    VesselGovernanceTaskResponse,
    VesselIdentityCandidateResponse,
    VesselIdentityCandidateReviewRequest,
    VesselImportConfirmRequest,
    VesselImportConfirmResponse,
    VesselImportPreviewRequest,
    VesselImportPreviewResponse,
    VesselListItemResponse,
    VesselListQuery,
    VesselManualPreferenceResponse,
    VesselManualPreferenceUpsertRequest,
    VesselOperatorReplaceRequest,
    VesselOperatorResponse,
    VesselOwnerReplaceRequest,
    VesselOwnerResponse,
    VesselOwnerTransferRequest,
    VesselPersonCertificateReplaceRequest,
    VesselPersonCertificateResponse,
    VesselPositionMonitorQuery,
    VesselPositionMonitorResponse,
    VesselProfileResponse,
    VesselProfileUpdateRequest,
    VesselQualityIssueCreateRequest,
    VesselQualityIssueResponse,
    VesselQualityIssueUpdateRequest,
    VesselQualitySnapshotResponse,
    VesselRegistrationResponse,
    VesselRegistrationUpsertRequest,
)
from app.modules.vessel.service import VesselService

router = APIRouter()
quality_router = APIRouter()
identity_router = APIRouter()


def _operator_id(current_user: SysUser) -> int | None:
    return int(current_user.id) if current_user is not None else None


@router.get("/dashboard", response_model=VesselDashboardResponse)
async def get_vessel_dashboard(
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).dashboard()


@router.get("/statistics/overview", response_model=VesselDashboardResponse)
async def get_vessel_statistics_overview(
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).dashboard()


@router.get("/position-monitor", response_model=VesselPositionMonitorResponse)
async def monitor_vessel_positions(
    query: VesselPositionMonitorQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).position_monitor(query)


@router.get("/governance/summary", response_model=VesselGovernanceSummaryResponse)
async def get_vessel_governance_summary(
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).governance_summary()


@router.get("/governance/tasks", response_model=PageResponse[VesselGovernanceTaskResponse])
async def list_vessel_governance_tasks(
    task_type: str | None = None,
    status_code: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).governance_tasks(
        task_type=task_type,
        status_code=status_code,
        page=page,
        page_size=page_size,
    )


@router.get("/import/template")
async def get_import_template(
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).import_template()


@router.post("/import/preview", response_model=VesselImportPreviewResponse)
async def preview_import(
    body: VesselImportPreviewRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).import_preview(body)


@router.post("/import/confirm", response_model=VesselImportConfirmResponse)
async def confirm_import(
    body: VesselImportConfirmRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).import_confirm(body, operator_id=_operator_id(current_user))


@router.get("/quality-issues", response_model=PageResponse[VesselQualityIssueResponse])
async def list_vessel_quality_issues_in_vessels(
    vessel_profile_id: int | None = None,
    status_code: str | None = None,
    issue_type_code: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).list_quality_issues(
        vessel_profile_id=vessel_profile_id,
        status_code=status_code,
        issue_type_code=issue_type_code,
        page=page,
        page_size=page_size,
    )


@router.get("/identity-candidates", response_model=PageResponse[VesselIdentityCandidateResponse])
async def list_vessel_identity_candidates_in_vessels(
    source_profile_id: int | None = None,
    target_profile_id: int | None = None,
    status_code: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).list_identity_candidates(
        source_profile_id=source_profile_id,
        target_profile_id=target_profile_id,
        status_code=status_code,
        page=page,
        page_size=page_size,
    )


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


@router.put("/{vessel_id}/cargo-capability", response_model=VesselCargoCapabilityResponse)
async def upsert_vessel_cargo_capability(
    vessel_id: int,
    body: VesselCargoCapabilityUpsertRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).upsert_cargo_capability(vessel_id, body, operator_id=_operator_id(current_user))


@router.put("/{vessel_id}/manual-preference", response_model=VesselManualPreferenceResponse)
async def upsert_vessel_manual_preference(
    vessel_id: int,
    body: VesselManualPreferenceUpsertRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).upsert_manual_preference(vessel_id, body, operator_id=_operator_id(current_user))


@router.get("/{vessel_id}/owners", response_model=list[VesselOwnerResponse])
async def list_vessel_owners(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return (await VesselService(db).get_detail(vessel_id)).owners


@router.put("/{vessel_id}/owners", response_model=list[VesselOwnerResponse])
async def replace_vessel_owners(
    vessel_id: int,
    body: VesselOwnerReplaceRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).replace_owners(vessel_id, body, operator_id=_operator_id(current_user))


@router.get("/{vessel_id}/operators", response_model=list[VesselOperatorResponse])
async def list_vessel_operators(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return (await VesselService(db).get_detail(vessel_id)).operators


@router.put("/{vessel_id}/operators", response_model=list[VesselOperatorResponse])
async def replace_vessel_operators(
    vessel_id: int,
    body: VesselOperatorReplaceRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).replace_operators(vessel_id, body, operator_id=_operator_id(current_user))


@router.get("/{vessel_id}/contacts", response_model=list[VesselContactResponse])
async def list_vessel_contacts(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return (await VesselService(db).get_detail(vessel_id)).contacts


@router.put("/{vessel_id}/contacts", response_model=list[VesselContactResponse])
async def replace_vessel_contacts(
    vessel_id: int,
    body: VesselContactReplaceRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).replace_contacts(vessel_id, body, operator_id=_operator_id(current_user))


@router.get("/{vessel_id}/crew", response_model=list[VesselCrewResponse])
async def list_vessel_crew(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return (await VesselService(db).get_detail(vessel_id)).crew


@router.put("/{vessel_id}/crew", response_model=list[VesselCrewResponse])
async def replace_vessel_crew(
    vessel_id: int,
    body: VesselCrewReplaceRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).replace_crew(vessel_id, body, operator_id=_operator_id(current_user))


@router.get("/{vessel_id}/person-certificates", response_model=list[VesselPersonCertificateResponse])
async def list_vessel_person_certificates(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return (await VesselService(db).get_detail(vessel_id)).person_certificates


@router.put("/{vessel_id}/person-certificates", response_model=list[VesselPersonCertificateResponse])
async def replace_vessel_person_certificates(
    vessel_id: int,
    body: VesselPersonCertificateReplaceRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).replace_person_certificates(vessel_id, body, operator_id=_operator_id(current_user))


@router.get("/{vessel_id}/certificates", response_model=list[VesselCertificateResponse])
async def list_vessel_certificates(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).list_certificates(vessel_id)


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
    _ = vessel_id
    return await VesselService(db).update_certificate(certificate_id, body, operator_id=_operator_id(current_user))


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


@router.post("/{vessel_id}/owner-transfer", response_model=VesselProfileResponse)
async def transfer_vessel_owner(
    vessel_id: int,
    body: VesselOwnerTransferRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).owner_transfer(vessel_id, body, operator_id=_operator_id(current_user))


@router.get("/{vessel_id}/behavior-profile", response_model=VesselBehaviorProfileResponse | None)
async def get_vessel_behavior_profile(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).get_behavior_profile(vessel_id)


@router.get("/{vessel_id}/quality", response_model=VesselQualitySnapshotResponse | None)
async def get_vessel_quality(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).get_quality(vessel_id)


@router.get("/{vessel_id}/change-events", response_model=list[VesselChangeEventResponse])
async def get_vessel_change_events(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).get_change_events(vessel_id)


@quality_router.get("", response_model=PageResponse[VesselQualityIssueResponse])
async def list_quality_issues(
    vessel_profile_id: int | None = None,
    status_code: str | None = None,
    issue_type_code: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).list_quality_issues(
        vessel_profile_id=vessel_profile_id,
        status_code=status_code,
        issue_type_code=issue_type_code,
        page=page,
        page_size=page_size,
    )


@quality_router.post("", response_model=VesselQualityIssueResponse)
async def create_quality_issue(
    body: VesselQualityIssueCreateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).create_quality_issue(body, operator_id=_operator_id(current_user))


@quality_router.put("/{issue_id}", response_model=VesselQualityIssueResponse)
async def update_quality_issue(
    issue_id: int,
    body: VesselQualityIssueUpdateRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).update_quality_issue(issue_id, body, operator_id=_operator_id(current_user))


@identity_router.get("", response_model=PageResponse[VesselIdentityCandidateResponse])
async def list_identity_candidates(
    source_profile_id: int | None = None,
    target_profile_id: int | None = None,
    status_code: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselService(db).list_identity_candidates(
        source_profile_id=source_profile_id,
        target_profile_id=target_profile_id,
        status_code=status_code,
        page=page,
        page_size=page_size,
    )


@identity_router.post("/{candidate_id}", response_model=VesselIdentityCandidateResponse)
async def review_identity_candidate(
    candidate_id: int,
    body: VesselIdentityCandidateReviewRequest,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await VesselService(db).review_identity_candidate(
        candidate_id,
        body,
        operator_id=_operator_id(current_user),
    )
