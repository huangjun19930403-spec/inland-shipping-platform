"""ship 模块 service。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.modules.dictionary.service import CodeSequenceService
from app.modules.ship.repository import (
    ShipCapacityRepository,
    ShipCertificateRepository,
    ShipContactRepository,
    ShipImportBatchRepository,
    ShipImportRawRepository,
    ShipImportRecordRepository,
    ShipMmsiHistoryRepository,
    ShipNameHistoryRepository,
    ShipOperationRepository,
    ShipOwnerRepository,
    ShipProfileRepository,
)
from app.modules.ship.schemas import (
    PageResponse,
    ShipCapacityResponse,
    ShipCertificateFileResponse,
    ShipCertificateResponse,
    ShipContactResponse,
    ShipDetailResponse,
    ShipImportBatchDetailResponse,
    ShipImportBatchResponse,
    ShipImportRawResponse,
    ShipImportRecordResponse,
    ShipMmsiHistoryResponse,
    ShipNameHistoryResponse,
    ShipOperationResponse,
    ShipOwnerResponse,
    ShipResponse,
)


def _to_ship_response(row) -> ShipResponse:
    return ShipResponse(
        id=row.id,
        ais_id=row.ais_id,
        ship_name=row.ship_name,
        ship_name_en=row.ship_name_en,
        current_mmsi=row.current_mmsi,
        ship_type_code=row.ship_type_code,
        navigation_power_type_code=row.navigation_power_type_code,
        home_port_code=row.home_port_code,
        home_port_name=row.home_port_name,
        owner_name=row.owner_name,
        profile_status_code=row.profile_status_code,
        source_type_code=row.source_type_code,
        audit_status=row.audit_status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_capacity_response(row) -> ShipCapacityResponse:
    return ShipCapacityResponse(
        id=row.id,
        ship_id=row.ship_id,
        deadweight_ton=row.deadweight_ton,
        reference_load_ton=row.reference_load_ton,
        total_tonnage=row.total_tonnage,
        net_tonnage=row.net_tonnage,
        length_m=row.length_m,
        width_m=row.width_m,
        depth_m=row.depth_m,
        design_draft_m=row.design_draft_m,
        design_speed_kn=row.design_speed_kn,
        hold_count=row.hold_count,
        capacity_remark=row.capacity_remark,
        updated_at=row.updated_at,
    )


def _to_operation_response(row) -> ShipOperationResponse:
    return ShipOperationResponse(
        id=row.id,
        ship_id=row.ship_id,
        operator_name=row.operator_name,
        manager_name=row.manager_name,
        main_navigation_area_desc=row.main_navigation_area_desc,
        usual_route_desc=row.usual_route_desc,
        contact_phone=row.contact_phone,
        dispatch_contact_name=row.dispatch_contact_name,
        dispatch_contact_phone=row.dispatch_contact_phone,
        risk_level_code=row.risk_level_code,
        last_active_at=row.last_active_at,
        ext_json=row.ext_json,
        updated_at=row.updated_at,
    )


def _to_owner_response(row) -> ShipOwnerResponse:
    return ShipOwnerResponse(
        id=row.id,
        ship_id=row.ship_id,
        party_name=row.party_name,
        party_relation_type_code=row.party_relation_type_code,
        certificate_no=row.certificate_no,
        mobile_phone=row.mobile_phone,
        landline_phone=row.landline_phone,
        address=row.address,
        is_primary=row.is_primary,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_contact_response(row) -> ShipContactResponse:
    return ShipContactResponse(
        id=row.id,
        ship_id=row.ship_id,
        contact_name=row.contact_name,
        contact_role_code=row.contact_role_code,
        mobile_phone=row.mobile_phone,
        wechat=row.wechat,
        email=row.email,
        is_primary=row.is_primary,
        remark=row.remark,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_certificate_response(row) -> ShipCertificateResponse:
    return ShipCertificateResponse(
        id=row.id,
        ship_id=row.ship_id,
        certificate_type_code=row.certificate_type_code,
        certificate_no=row.certificate_no,
        issuing_authority=row.issuing_authority,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        is_long_term_valid=row.is_long_term_valid,
        validity_text_raw=row.validity_text_raw,
        verify_status_code=row.verify_status_code,
        structured_payload_json=row.structured_payload_json,
        source_file_id=row.source_file_id,
        remark=row.remark,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_certificate_file_response(row) -> ShipCertificateFileResponse:
    return ShipCertificateFileResponse(
        id=row.id,
        ship_certificate_id=row.ship_certificate_id,
        storage_provider_code=row.storage_provider_code,
        file_url=row.file_url,
        file_name=row.file_name,
        file_ext=row.file_ext,
        file_size=row.file_size,
        uploaded_by=row.uploaded_by,
        uploaded_at=row.uploaded_at,
        created_at=row.created_at,
    )


def _to_name_history_response(row) -> ShipNameHistoryResponse:
    return ShipNameHistoryResponse(
        id=row.id,
        ship_id=row.ship_id,
        ship_name=row.ship_name,
        start_date=row.start_date,
        end_date=row.end_date,
        source_type_code=row.source_type_code,
        created_at=row.created_at,
    )


def _to_mmsi_history_response(row) -> ShipMmsiHistoryResponse:
    return ShipMmsiHistoryResponse(
        id=row.id,
        ship_id=row.ship_id,
        mmsi=row.mmsi,
        start_date=row.start_date,
        end_date=row.end_date,
        source_type_code=row.source_type_code,
        created_at=row.created_at,
    )


def _to_import_batch_response(row) -> ShipImportBatchResponse:
    return ShipImportBatchResponse(
        id=row.id,
        batch_no=row.batch_no,
        source_type_code=row.source_type_code,
        total_count=row.total_count,
        success_count=row.success_count,
        failed_count=row.failed_count,
        status_code=row.status_code,
        started_at=row.started_at,
        finished_at=row.finished_at,
        operator_id=row.operator_id,
        remark=row.remark,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_import_raw_response(row) -> ShipImportRawResponse:
    return ShipImportRawResponse(
        id=row.id,
        batch_id=row.batch_id,
        row_no=row.row_no,
        raw_payload_json=row.raw_payload_json,
        parse_status_code=row.parse_status_code,
        parse_message=row.parse_message,
        created_at=row.created_at,
    )


def _to_import_record_response(row) -> ShipImportRecordResponse:
    return ShipImportRecordResponse(
        id=row.id,
        batch_id=row.batch_id,
        raw_id=row.raw_id,
        ship_id=row.ship_id,
        action_type_code=row.action_type_code,
        result_code=row.result_code,
        message=row.message,
        created_at=row.created_at,
    )


class ShipProfileService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = ShipProfileRepository(db)
        self.capacity_repo = ShipCapacityRepository(db)
        self.operation_repo = ShipOperationRepository(db)
        self.owner_repo = ShipOwnerRepository(db)
        self.contact_repo = ShipContactRepository(db)
        self.certificate_repo = ShipCertificateRepository(db)
        self.name_history_repo = ShipNameHistoryRepository(db)
        self.mmsi_history_repo = ShipMmsiHistoryRepository(db)

    async def list_ships(
        self,
        keyword: str | None,
        status_code: str | None,
        ship_type_code: str | None,
        city_code: str | None,
        page: int,
        page_size: int,
    ) -> PageResponse[ShipResponse]:
        rows, total = await self.repo.list_ships(
            keyword=keyword,
            status_code=status_code,
            ship_type_code=ship_type_code,
            city_code=city_code,
            page=page,
            page_size=page_size,
        )
        return PageResponse[ShipResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_ship_response(item) for item in rows],
        )

    async def create_ship(self, payload) -> ShipResponse:
        exists = await self.repo.exists_ship_code_fields(
            ais_id=payload.ais_id.strip(),
            mmsi=payload.current_mmsi,
            ship_name=payload.ship_name.strip(),
        )
        if exists:
            raise ConflictError("ship identity fields already exists")
        row = await self.repo.create_ship(
            {
                **payload.model_dump(),
                "ais_id": payload.ais_id.strip(),
                "ship_name": payload.ship_name.strip(),
            }
        )
        await self.db.commit()
        return _to_ship_response(row)

    async def update_ship(self, ship_id: int, payload) -> ShipResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        ship = await self.repo.get_ship_by_id(ship_id)
        if ship is None:
            raise NotFoundError("ShipProfile", ship_id)

        exists = await self.repo.exists_ship_code_fields(
            ais_id=updates.get("ais_id"),
            mmsi=updates.get("current_mmsi"),
            ship_name=updates.get("ship_name"),
            exclude_ship_id=ship_id,
        )
        if exists:
            raise ConflictError("ship identity fields already exists")

        row = await self.repo.update_ship(ship_id, updates)
        if row is None:
            raise NotFoundError("ShipProfile", ship_id)
        await self.db.commit()
        return _to_ship_response(row)

    async def get_ship_detail(self, ship_id: int) -> ShipDetailResponse:
        ship = await self.repo.get_ship_by_id(ship_id)
        if ship is None:
            raise NotFoundError("ShipProfile", ship_id)
        capacity = await self.capacity_repo.get_capacity_by_ship_id(ship_id)
        operation = await self.operation_repo.get_operation_by_ship_id(ship_id)
        owners = await self.owner_repo.list_owners(ship_id)
        contacts = await self.contact_repo.list_contacts(ship_id)
        certificates = await self.certificate_repo.list_certificates(ship_id)
        name_history = await self.name_history_repo.list_name_history(ship_id)
        mmsi_history = await self.mmsi_history_repo.list_mmsi_history(ship_id)
        return ShipDetailResponse(
            profile=_to_ship_response(ship),
            capacity=_to_capacity_response(capacity) if capacity else None,
            operation=_to_operation_response(operation) if operation else None,
            owners=[_to_owner_response(item) for item in owners],
            contacts=[_to_contact_response(item) for item in contacts],
            certificates=[_to_certificate_response(item) for item in certificates],
            name_history=[_to_name_history_response(item) for item in name_history],
            mmsi_history=[_to_mmsi_history_response(item) for item in mmsi_history],
        )

    async def change_ship_status(self, ship_id: int, status_code: str) -> None:
        ok = await self.repo.update_ship_status(ship_id, status_code)
        if not ok:
            raise NotFoundError("ShipProfile", ship_id)
        await self.db.commit()


class ShipCapacityService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.ship_repo = ShipProfileRepository(db)
        self.repo = ShipCapacityRepository(db)

    async def get_capacity(self, ship_id: int) -> ShipCapacityResponse | None:
        ship = await self.ship_repo.get_ship_by_id(ship_id)
        if ship is None:
            raise NotFoundError("ShipProfile", ship_id)
        row = await self.repo.get_capacity_by_ship_id(ship_id)
        return _to_capacity_response(row) if row else None

    async def upsert_capacity(self, ship_id: int, payload) -> ShipCapacityResponse:
        ship = await self.ship_repo.get_ship_by_id(ship_id)
        if ship is None:
            raise NotFoundError("ShipProfile", ship_id)
        row = await self.repo.upsert_capacity(ship_id, payload.model_dump(exclude_none=True))
        await self.db.commit()
        return _to_capacity_response(row)


class ShipOperationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.ship_repo = ShipProfileRepository(db)
        self.repo = ShipOperationRepository(db)

    async def get_operation(self, ship_id: int) -> ShipOperationResponse | None:
        ship = await self.ship_repo.get_ship_by_id(ship_id)
        if ship is None:
            raise NotFoundError("ShipProfile", ship_id)
        row = await self.repo.get_operation_by_ship_id(ship_id)
        return _to_operation_response(row) if row else None

    async def upsert_operation(self, ship_id: int, payload) -> ShipOperationResponse:
        ship = await self.ship_repo.get_ship_by_id(ship_id)
        if ship is None:
            raise NotFoundError("ShipProfile", ship_id)
        row = await self.repo.upsert_operation(ship_id, payload.model_dump(exclude_none=True))
        await self.db.commit()
        return _to_operation_response(row)


class ShipOwnerService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.ship_repo = ShipProfileRepository(db)
        self.repo = ShipOwnerRepository(db)

    async def replace_owners(self, ship_id: int, owners: list[dict]) -> list[ShipOwnerResponse]:
        ship = await self.ship_repo.get_ship_by_id(ship_id)
        if ship is None:
            raise NotFoundError("ShipProfile", ship_id)
        rows = await self.repo.replace_owners(ship_id, owners)
        await self.db.commit()
        return [_to_owner_response(item) for item in rows]


class ShipContactService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.ship_repo = ShipProfileRepository(db)
        self.repo = ShipContactRepository(db)

    async def replace_contacts(self, ship_id: int, contacts: list[dict]) -> list[ShipContactResponse]:
        ship = await self.ship_repo.get_ship_by_id(ship_id)
        if ship is None:
            raise NotFoundError("ShipProfile", ship_id)
        rows = await self.repo.replace_contacts(ship_id, contacts)
        await self.db.commit()
        return [_to_contact_response(item) for item in rows]


class ShipCertificateService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.ship_repo = ShipProfileRepository(db)
        self.repo = ShipCertificateRepository(db)

    async def list_certificates(self, ship_id: int) -> list[ShipCertificateResponse]:
        ship = await self.ship_repo.get_ship_by_id(ship_id)
        if ship is None:
            raise NotFoundError("ShipProfile", ship_id)
        rows = await self.repo.list_certificates(ship_id)
        return [_to_certificate_response(item) for item in rows]

    async def create_certificate(self, ship_id: int, payload) -> ShipCertificateResponse:
        ship = await self.ship_repo.get_ship_by_id(ship_id)
        if ship is None:
            raise NotFoundError("ShipProfile", ship_id)
        row = await self.repo.create_certificate(ship_id, payload.model_dump(exclude_none=True))
        await self.db.commit()
        return _to_certificate_response(row)

    async def update_certificate(self, certificate_id: int, payload) -> ShipCertificateResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        row = await self.repo.update_certificate(certificate_id, updates)
        if row is None:
            raise NotFoundError("ShipCertificate", certificate_id)
        await self.db.commit()
        return _to_certificate_response(row)

    async def delete_certificate(self, certificate_id: int) -> None:
        ok = await self.repo.delete_certificate(certificate_id)
        if not ok:
            raise NotFoundError("ShipCertificate", certificate_id)
        await self.db.commit()

    async def replace_certificate_files(
        self, certificate_id: int, files: list[dict]
    ) -> list[ShipCertificateFileResponse]:
        cert = await self.repo.get_certificate(certificate_id)
        if cert is None:
            raise NotFoundError("ShipCertificate", certificate_id)
        rows = await self.repo.replace_certificate_files(certificate_id, files)
        await self.db.commit()
        return [_to_certificate_file_response(item) for item in rows]


class ShipIdentityHistoryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.ship_repo = ShipProfileRepository(db)
        self.name_repo = ShipNameHistoryRepository(db)
        self.mmsi_repo = ShipMmsiHistoryRepository(db)

    async def list_name_history(self, ship_id: int) -> list[ShipNameHistoryResponse]:
        ship = await self.ship_repo.get_ship_by_id(ship_id)
        if ship is None:
            raise NotFoundError("ShipProfile", ship_id)
        rows = await self.name_repo.list_name_history(ship_id)
        return [_to_name_history_response(item) for item in rows]

    async def append_name_history(self, ship_id: int, payload) -> ShipNameHistoryResponse:
        ship = await self.ship_repo.get_ship_by_id(ship_id)
        if ship is None:
            raise NotFoundError("ShipProfile", ship_id)
        row = await self.name_repo.append_name_history(ship_id, payload.model_dump(exclude_none=True))
        if payload.end_date is None:
            await self.ship_repo.update_ship(ship_id, {"ship_name": payload.ship_name})
        await self.db.commit()
        return _to_name_history_response(row)

    async def list_mmsi_history(self, ship_id: int) -> list[ShipMmsiHistoryResponse]:
        ship = await self.ship_repo.get_ship_by_id(ship_id)
        if ship is None:
            raise NotFoundError("ShipProfile", ship_id)
        rows = await self.mmsi_repo.list_mmsi_history(ship_id)
        return [_to_mmsi_history_response(item) for item in rows]

    async def append_mmsi_history(self, ship_id: int, payload) -> ShipMmsiHistoryResponse:
        ship = await self.ship_repo.get_ship_by_id(ship_id)
        if ship is None:
            raise NotFoundError("ShipProfile", ship_id)
        row = await self.mmsi_repo.append_mmsi_history(ship_id, payload.model_dump(exclude_none=True))
        if payload.end_date is None:
            await self.ship_repo.update_ship(ship_id, {"current_mmsi": payload.mmsi})
        await self.db.commit()
        return _to_mmsi_history_response(row)


class ShipImportService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.batch_repo = ShipImportBatchRepository(db)
        self.raw_repo = ShipImportRawRepository(db)
        self.record_repo = ShipImportRecordRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def list_batches(
        self,
        keyword: str | None,
        status_code: str | None,
        page: int,
        page_size: int,
    ) -> PageResponse[ShipImportBatchResponse]:
        rows, total = await self.batch_repo.list_batches(keyword, status_code, page, page_size)
        return PageResponse[ShipImportBatchResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_import_batch_response(item) for item in rows],
        )

    async def create_batch(self, payload) -> ShipImportBatchResponse:
        data = payload.model_dump(exclude_none=True)
        batch_no = (payload.batch_no or "").strip()
        if not batch_no:
            batch_no = await self.sequence_service.next_code("SHIP_IMPORT_BATCH_NO")
        existed = await self.batch_repo.get_batch_by_no(batch_no)
        if existed is not None:
            raise ConflictError(f"batch_no already exists: {batch_no}")
        data["batch_no"] = batch_no
        row = await self.batch_repo.create_batch(data)
        await self.db.commit()
        return _to_import_batch_response(row)

    async def get_batch_detail(self, batch_id: int) -> ShipImportBatchDetailResponse:
        batch = await self.batch_repo.get_batch(batch_id)
        if batch is None:
            raise NotFoundError("ShipImportBatch", batch_id)
        _, raw_total = await self.raw_repo.list_raw_records(batch_id, 1, 1)
        _, record_total = await self.record_repo.list_import_records(batch_id, 1, 1)
        return ShipImportBatchDetailResponse(
            batch=_to_import_batch_response(batch),
            raw_total=raw_total,
            record_total=record_total,
        )

    async def list_raw_records(
        self, batch_id: int, page: int, page_size: int
    ) -> PageResponse[ShipImportRawResponse]:
        batch = await self.batch_repo.get_batch(batch_id)
        if batch is None:
            raise NotFoundError("ShipImportBatch", batch_id)
        rows, total = await self.raw_repo.list_raw_records(batch_id, page, page_size)
        return PageResponse[ShipImportRawResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_import_raw_response(item) for item in rows],
        )

    async def list_import_records(
        self, batch_id: int, page: int, page_size: int
    ) -> PageResponse[ShipImportRecordResponse]:
        batch = await self.batch_repo.get_batch(batch_id)
        if batch is None:
            raise NotFoundError("ShipImportBatch", batch_id)
        rows, total = await self.record_repo.list_import_records(batch_id, page, page_size)
        return PageResponse[ShipImportRecordResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_import_record_response(item) for item in rows],
        )

    async def create_raw_records(self, batch_id: int, items: list[dict]) -> list[ShipImportRawResponse]:
        batch = await self.batch_repo.get_batch(batch_id)
        if batch is None:
            raise NotFoundError("ShipImportBatch", batch_id)
        rows = await self.raw_repo.create_raw_records(batch_id, items)
        await self.batch_repo.update_batch(
            batch_id,
            {
                "total_count": (batch.total_count or 0) + len(rows),
            },
        )
        await self.db.commit()
        return [_to_import_raw_response(item) for item in rows]

    async def create_import_record(self, payload) -> ShipImportRecordResponse:
        batch = await self.batch_repo.get_batch(payload.batch_id)
        if batch is None:
            raise NotFoundError("ShipImportBatch", payload.batch_id)
        row = await self.record_repo.create_import_record(payload.model_dump(exclude_none=True))
        updates = {
            "success_count": batch.success_count + (1 if row.result_code.upper() == "SUCCESS" else 0),
            "failed_count": batch.failed_count + (1 if row.result_code.upper() != "SUCCESS" else 0),
        }
        await self.batch_repo.update_batch(payload.batch_id, updates)
        await self.db.commit()
        return _to_import_record_response(row)

    async def update_import_record(self, record_id: int, payload) -> ShipImportRecordResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        row = await self.record_repo.update_import_record(record_id, updates)
        if row is None:
            raise NotFoundError("ShipImportRecord", record_id)
        await self.db.commit()
        return _to_import_record_response(row)
