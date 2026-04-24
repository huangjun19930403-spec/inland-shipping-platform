"""ship 模块 router（含导入管理）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.modules.ship.schemas import (
    PageResponse,
    ShipCapacityResponse,
    ShipCapacityUpsertRequest,
    ShipCertificateCreateRequest,
    ShipCertificateFileReplaceRequest,
    ShipCertificateFileResponse,
    ShipCertificateResponse,
    ShipCertificateUpdateRequest,
    ShipContactReplaceRequest,
    ShipContactResponse,
    ShipCreateRequest,
    ShipDetailResponse,
    ShipImportBatchCreateRequest,
    ShipImportBatchDetailResponse,
    ShipImportBatchListQuery,
    ShipImportBatchResponse,
    ShipImportRawCreateRequest,
    ShipImportRawListQuery,
    ShipImportRawResponse,
    ShipImportRecordListQuery,
    ShipImportRecordResponse,
    ShipListQuery,
    ShipMmsiHistoryCreateRequest,
    ShipMmsiHistoryResponse,
    ShipNameHistoryCreateRequest,
    ShipNameHistoryResponse,
    ShipOperationResponse,
    ShipOperationUpsertRequest,
    ShipOwnerReplaceRequest,
    ShipOwnerResponse,
    ShipResponse,
    ShipStatusChangeRequest,
    ShipUpdateRequest,
)
from app.modules.ship.service import (
    ShipCapacityService,
    ShipCertificateService,
    ShipContactService,
    ShipIdentityHistoryService,
    ShipImportService,
    ShipOperationService,
    ShipOwnerService,
    ShipProfileService,
)

router = APIRouter()


@router.get("", response_model=PageResponse[ShipResponse])
async def list_ships(
    query: ShipListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipProfileService(db)
    return await service.list_ships(
        query.keyword,
        query.status_code,
        query.ship_type_code,
        query.city_code,
        query.page,
        query.page_size,
    )


@router.post("", response_model=ShipResponse)
async def create_ship(
    body: ShipCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipProfileService(db)
    return await service.create_ship(body)


@router.get("/import/batches", response_model=PageResponse[ShipImportBatchResponse])
async def list_import_batches(
    query: ShipImportBatchListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipImportService(db)
    return await service.list_batches(query.keyword, query.status_code, query.page, query.page_size)


@router.get("/import/batches/{batch_id}", response_model=ShipImportBatchDetailResponse)
async def get_import_batch_detail(
    batch_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipImportService(db)
    return await service.get_batch_detail(batch_id)


@router.post("/import/batches", response_model=ShipImportBatchResponse)
async def create_import_batch(
    body: ShipImportBatchCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipImportService(db)
    return await service.create_batch(body)


@router.get("/import/batches/{batch_id}/raw-records", response_model=PageResponse[ShipImportRawResponse])
async def list_import_raw_records(
    batch_id: int,
    query: ShipImportRawListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipImportService(db)
    return await service.list_raw_records(batch_id, query.page, query.page_size)


@router.post("/import/batches/{batch_id}/raw-records", response_model=list[ShipImportRawResponse])
async def create_import_raw_records(
    batch_id: int,
    body: ShipImportRawCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipImportService(db)
    return await service.create_raw_records(
        batch_id=batch_id,
        items=[item.model_dump(exclude_none=True) for item in body.items],
    )


@router.get("/import/batches/{batch_id}/records", response_model=PageResponse[ShipImportRecordResponse])
async def list_import_records(
    batch_id: int,
    query: ShipImportRecordListQuery = Depends(),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipImportService(db)
    return await service.list_import_records(batch_id, query.page, query.page_size)


@router.get("/{ship_id}", response_model=ShipDetailResponse)
async def get_ship_detail(
    ship_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipProfileService(db)
    return await service.get_ship_detail(ship_id)


@router.put("/{ship_id}", response_model=ShipResponse)
async def update_ship(
    ship_id: int,
    body: ShipUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipProfileService(db)
    return await service.update_ship(ship_id, body)


@router.put("/{ship_id}/status")
async def change_ship_status(
    ship_id: int,
    body: ShipStatusChangeRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipProfileService(db)
    await service.change_ship_status(ship_id, body.status_code)
    return {"ok": True}


@router.get("/{ship_id}/capacity", response_model=ShipCapacityResponse | None)
async def get_ship_capacity(
    ship_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipCapacityService(db)
    return await service.get_capacity(ship_id)


@router.put("/{ship_id}/capacity", response_model=ShipCapacityResponse)
async def upsert_ship_capacity(
    ship_id: int,
    body: ShipCapacityUpsertRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipCapacityService(db)
    return await service.upsert_capacity(ship_id, body)


@router.get("/{ship_id}/operation", response_model=ShipOperationResponse | None)
async def get_ship_operation(
    ship_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipOperationService(db)
    return await service.get_operation(ship_id)


@router.put("/{ship_id}/operation", response_model=ShipOperationResponse)
async def upsert_ship_operation(
    ship_id: int,
    body: ShipOperationUpsertRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipOperationService(db)
    return await service.upsert_operation(ship_id, body)


@router.put("/{ship_id}/owners", response_model=list[ShipOwnerResponse])
async def replace_ship_owners(
    ship_id: int,
    body: ShipOwnerReplaceRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipOwnerService(db)
    return await service.replace_owners(
        ship_id,
        [item.model_dump(exclude_none=True) for item in body.owners],
    )


@router.put("/{ship_id}/contacts", response_model=list[ShipContactResponse])
async def replace_ship_contacts(
    ship_id: int,
    body: ShipContactReplaceRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipContactService(db)
    return await service.replace_contacts(
        ship_id,
        [item.model_dump(exclude_none=True) for item in body.contacts],
    )


@router.get("/{ship_id}/certificates", response_model=list[ShipCertificateResponse])
async def list_ship_certificates(
    ship_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipCertificateService(db)
    return await service.list_certificates(ship_id)


@router.post("/{ship_id}/certificates", response_model=ShipCertificateResponse)
async def create_ship_certificate(
    ship_id: int,
    body: ShipCertificateCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipCertificateService(db)
    return await service.create_certificate(ship_id, body)


@router.put("/certificates/{certificate_id}", response_model=ShipCertificateResponse)
async def update_ship_certificate(
    certificate_id: int,
    body: ShipCertificateUpdateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipCertificateService(db)
    return await service.update_certificate(certificate_id, body)


@router.delete("/certificates/{certificate_id}")
async def delete_ship_certificate(
    certificate_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipCertificateService(db)
    await service.delete_certificate(certificate_id)
    return {"ok": True}


@router.put("/certificates/{certificate_id}/files", response_model=list[ShipCertificateFileResponse])
async def replace_ship_certificate_files(
    certificate_id: int,
    body: ShipCertificateFileReplaceRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipCertificateService(db)
    return await service.replace_certificate_files(
        certificate_id,
        [item.model_dump(exclude_none=True) for item in body.files],
    )


@router.get("/{ship_id}/name-history", response_model=list[ShipNameHistoryResponse])
async def list_ship_name_history(
    ship_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipIdentityHistoryService(db)
    return await service.list_name_history(ship_id)


@router.post("/{ship_id}/name-history", response_model=ShipNameHistoryResponse)
async def append_ship_name_history(
    ship_id: int,
    body: ShipNameHistoryCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipIdentityHistoryService(db)
    return await service.append_name_history(ship_id, body)


@router.get("/{ship_id}/mmsi-history", response_model=list[ShipMmsiHistoryResponse])
async def list_ship_mmsi_history(
    ship_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipIdentityHistoryService(db)
    return await service.list_mmsi_history(ship_id)


@router.post("/{ship_id}/mmsi-history", response_model=ShipMmsiHistoryResponse)
async def append_ship_mmsi_history(
    ship_id: int,
    body: ShipMmsiHistoryCreateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    service = ShipIdentityHistoryService(db)
    return await service.append_mmsi_history(ship_id, body)
