"""vessel 模块 router。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.system import SysUser
from app.modules.vessel.schemas import (
    PageResponse,
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
    VesselCertificateResponse,
    VesselCertificateUpdateRequest,
    VesselChangeEventResponse,
    VesselContactReplaceRequest,
    VesselContactResponse,
    VesselCreateRequest,
    VesselCrewReplaceRequest,
    VesselCrewResponse,
    VesselBusinessSituationCardResponse,
    VesselDetailResponse,
    VesselListItemResponse,
    VesselListQuery,
    VesselOperatorReplaceRequest,
    VesselOperatorResponse,
    VesselOwnerDocumentImageRecognitionConfirmRequest,
    VesselOwnerDocumentImageRecognitionResponse,
    VesselOwnerDocumentResponse,
    VesselOwnerReplaceRequest,
    VesselOwnerResponse,
    VesselOwnerTransferRequest,
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
    VesselProfileResponse,
    VesselProfileUpdateRequest,
    VesselRecognitionHistoryQuery,
    VesselRegistrationResponse,
    VesselRegistrationUpsertRequest,
    VesselVoidRequest,
)
from app.modules.vessel.service import VesselService

router = APIRouter()


def _operator_id(current_user: SysUser) -> int | None:
    return int(current_user.id) if current_user is not None else None


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
