"""ship 模块 service。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.address import AdminRegion, Region
from app.models.dictionary import StdDict, StdDictItem
from app.modules.dictionary.service import CodeSequenceService
from app.modules.ship.repository import (
    ShipCapacityRepository,
    ShipCertificateRepository,
    ShipContactRepository,
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
    ShipMmsiHistoryResponse,
    ShipNameHistoryResponse,
    ShipOperationResponse,
    ShipOwnerResponse,
    ShipDistributionBucketResponse,
    ShipResponse,
    ShipStatisticsOverviewResponse,
)


def _ship_age(building_year: int | None) -> int | None:
    if not building_year:
        return None
    current_year = datetime.utcnow().year
    if building_year > current_year:
        return None
    return current_year - building_year


def _size_text(capacity) -> str | None:
    if not capacity:
        return None
    parts = []
    if capacity.length_m is not None:
        parts.append(f"{capacity.length_m}m")
    if capacity.width_m is not None:
        parts.append(f"{capacity.width_m}m")
    if capacity.design_draft_m is not None:
        parts.append(f"吃水{capacity.design_draft_m}m")
    return " / ".join(parts) if parts else None


async def _load_dict_label_map(db: AsyncSession, dict_codes: list[str]) -> dict[str, dict[str, str]]:
    rows = (
        await db.execute(
            select(StdDict.dict_code, StdDictItem.item_code, StdDictItem.item_name)
            .join(StdDictItem, StdDictItem.dict_id == StdDict.id)
            .where(StdDict.dict_code.in_(dict_codes), StdDict.status == 1, StdDictItem.status == 1)
        )
    ).all()
    label_map: dict[str, dict[str, str]] = {code: {} for code in dict_codes}
    for dict_code, item_code, item_name in rows:
        label_map.setdefault(dict_code, {})[item_code] = item_name
    return label_map


async def _load_city_name_map(db: AsyncSession, city_codes: list[str]) -> dict[str, str]:
    codes = sorted({code for code in city_codes if code})
    if not codes:
        return {}
    rows = (
        await db.execute(select(AdminRegion.code, AdminRegion.name).where(AdminRegion.code.in_(codes)))
    ).all()
    return {code: name for code, name in rows}


async def _load_region_name_map(db: AsyncSession, region_ids: list[int]) -> dict[int, str]:
    ids = sorted({region_id for region_id in region_ids if region_id})
    if not ids:
        return {}
    rows = (
        await db.execute(select(Region.id, Region.name).where(Region.id.in_(ids)))
    ).all()
    return {region_id: name for region_id, name in rows}


def _to_ship_response(
    row,
    *,
    capacity=None,
    label_map: dict[str, dict[str, str]] | None = None,
    city_map: dict[str, str] | None = None,
    region_map: dict[int, str] | None = None,
) -> ShipResponse:
    label_map = label_map or {}
    city_map = city_map or {}
    region_map = region_map or {}
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
        building_year=row.building_year,
        registry_city_code=row.registry_city_code,
        registry_city_name=city_map.get(row.registry_city_code or ""),
        business_region_id=row.business_region_id,
        business_region_name=region_map.get(row.business_region_id or 0),
        operation_status_code=row.operation_status_code,
        operation_status_name=label_map.get("SHIP_OPERATION_STATUS", {}).get(row.operation_status_code or ""),
        profile_status_code=row.profile_status_code,
        profile_status_name=label_map.get("PROFILE_STATUS", {}).get(row.profile_status_code),
        source_type_code=row.source_type_code,
        source_type_name=label_map.get("SOURCE_TYPE", {}).get(row.source_type_code),
        audit_status=row.audit_status,
        audit_status_name=label_map.get("AUDIT_STATUS", {}).get(row.audit_status),
        ship_type_name=label_map.get("SHIP_TYPE", {}).get(row.ship_type_code),
        navigation_power_type_name=label_map.get("NAVIGATION_POWER_TYPE", {}).get(row.navigation_power_type_code),
        deadweight_ton=capacity.deadweight_ton if capacity else None,
        length_m=capacity.length_m if capacity else None,
        width_m=capacity.width_m if capacity else None,
        design_draft_m=capacity.design_draft_m if capacity else None,
        ship_age=_ship_age(row.building_year),
        size_text=_size_text(capacity),
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


def _age_bucket(age: int | None) -> str:
    if age is None:
        return "未知船龄"
    if age <= 5:
        return "0-5年"
    if age <= 10:
        return "6-10年"
    if age <= 20:
        return "11-20年"
    return "21年以上"


def _deadweight_bucket(deadweight: Decimal | float | int | None) -> str:
    if deadweight is None:
        return "未知载重"
    value = Decimal(deadweight)
    if value < Decimal("1000"):
        return "1000吨以下"
    if value < Decimal("3000"):
        return "1000-3000吨"
    if value < Decimal("5000"):
        return "3000-5000吨"
    if value < Decimal("10000"):
        return "5000-10000吨"
    return "10000吨以上"


def _buckets(counts: dict[str, int]) -> list[ShipDistributionBucketResponse]:
    return [
        ShipDistributionBucketResponse(code=name, name=name, count=count)
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


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
        ship_ids = [item.id for item in rows]
        capacity_map = await self.capacity_repo.list_capacity_by_ship_ids(ship_ids)
        label_map = await _load_dict_label_map(
            self.db,
            ["SHIP_TYPE", "NAVIGATION_POWER_TYPE", "PROFILE_STATUS", "SHIP_OPERATION_STATUS", "SOURCE_TYPE", "AUDIT_STATUS"],
        )
        city_map = await _load_city_name_map(self.db, [item.registry_city_code for item in rows if item.registry_city_code])
        region_map = await _load_region_name_map(
            self.db,
            [item.business_region_id for item in rows if item.business_region_id],
        )
        return PageResponse[ShipResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[
                _to_ship_response(
                    item,
                    capacity=capacity_map.get(item.id),
                    label_map=label_map,
                    city_map=city_map,
                    region_map=region_map,
                )
                for item in rows
            ],
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
        return await self._build_ship_response(row)

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
        return await self._build_ship_response(row)

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
        label_map = await _load_dict_label_map(
            self.db,
            ["SHIP_TYPE", "NAVIGATION_POWER_TYPE", "PROFILE_STATUS", "SHIP_OPERATION_STATUS", "SOURCE_TYPE", "AUDIT_STATUS"],
        )
        city_map = await _load_city_name_map(self.db, [ship.registry_city_code] if ship.registry_city_code else [])
        region_map = await _load_region_name_map(
            self.db,
            [ship.business_region_id] if ship.business_region_id else [],
        )
        return ShipDetailResponse(
            profile=_to_ship_response(
                ship,
                capacity=capacity,
                label_map=label_map,
                city_map=city_map,
                region_map=region_map,
            ),
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

    async def _build_ship_response(self, ship) -> ShipResponse:
        capacity = await self.capacity_repo.get_capacity_by_ship_id(ship.id)
        label_map = await _load_dict_label_map(
            self.db,
            ["SHIP_TYPE", "NAVIGATION_POWER_TYPE", "PROFILE_STATUS", "SHIP_OPERATION_STATUS", "SOURCE_TYPE", "AUDIT_STATUS"],
        )
        city_map = await _load_city_name_map(self.db, [ship.registry_city_code] if ship.registry_city_code else [])
        region_map = await _load_region_name_map(
            self.db,
            [ship.business_region_id] if ship.business_region_id else [],
        )
        return _to_ship_response(
            ship,
            capacity=capacity,
            label_map=label_map,
            city_map=city_map,
            region_map=region_map,
        )

    async def get_statistics_overview(self) -> ShipStatisticsOverviewResponse:
        ships = await self.repo.list_all_ships()
        capacities = await self.capacity_repo.list_capacity_by_ship_ids([item.id for item in ships])
        label_map = await _load_dict_label_map(
            self.db,
            ["SHIP_TYPE", "SHIP_OPERATION_STATUS", "PROFILE_STATUS"],
        )

        total_deadweight = Decimal("0")
        deadweight_count = 0
        type_counts: dict[str, int] = {}
        age_counts: dict[str, int] = {}
        deadweight_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}

        for ship in ships:
            type_name = label_map.get("SHIP_TYPE", {}).get(ship.ship_type_code, ship.ship_type_code)
            type_counts[type_name] = type_counts.get(type_name, 0) + 1

            age_bucket = _age_bucket(_ship_age(ship.building_year))
            age_counts[age_bucket] = age_counts.get(age_bucket, 0) + 1

            capacity = capacities.get(ship.id)
            deadweight = capacity.deadweight_ton if capacity else None
            deadweight_bucket = _deadweight_bucket(deadweight)
            deadweight_counts[deadweight_bucket] = deadweight_counts.get(deadweight_bucket, 0) + 1
            if deadweight is not None:
                total_deadweight += Decimal(deadweight)
                deadweight_count += 1

            status_code = ship.operation_status_code or ship.profile_status_code
            status_name = (
                label_map.get("SHIP_OPERATION_STATUS", {}).get(status_code)
                or label_map.get("PROFILE_STATUS", {}).get(status_code)
                or status_code
            )
            status_counts[status_name] = status_counts.get(status_name, 0) + 1

        average_deadweight = (
            (total_deadweight / Decimal(deadweight_count)).quantize(Decimal("0.01"))
            if deadweight_count
            else None
        )
        return ShipStatisticsOverviewResponse(
            total_count=len(ships),
            active_count=sum(1 for item in ships if item.profile_status_code == "ACTIVE"),
            average_deadweight_ton=average_deadweight,
            ship_type_distribution=_buckets(type_counts),
            age_distribution=_buckets(age_counts),
            deadweight_distribution=_buckets(deadweight_counts),
            status_distribution=_buckets(status_counts),
        )


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

