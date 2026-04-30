"""ship 模块 repository。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ship import (
    ShipCapacity,
    ShipCertificate,
    ShipCertificateFile,
    ShipContact,
    ShipImportBatch,
    ShipImportRaw,
    ShipImportRecord,
    ShipMmsiHistory,
    ShipNameHistory,
    ShipOperation,
    ShipOwner,
    ShipProfile,
)


class ShipProfileRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_ship_by_id(self, ship_id: int) -> ShipProfile | None:
        return await self.db.scalar(
            select(ShipProfile).where(ShipProfile.id == ship_id, ShipProfile.deleted_at.is_(None))
        )

    async def get_ship_by_ais_id(self, ais_id: str) -> ShipProfile | None:
        return await self.db.scalar(
            select(ShipProfile).where(ShipProfile.ais_id == ais_id, ShipProfile.deleted_at.is_(None))
        )

    async def get_ship_by_current_mmsi(self, mmsi: str) -> ShipProfile | None:
        return await self.db.scalar(
            select(ShipProfile).where(
                ShipProfile.current_mmsi == mmsi,
                ShipProfile.deleted_at.is_(None),
            )
        )

    async def list_ships(
        self,
        keyword: str | None,
        status_code: str | None,
        ship_type_code: str | None,
        city_code: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[ShipProfile], int]:
        stmt = select(ShipProfile).where(ShipProfile.deleted_at.is_(None))
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    ShipProfile.ais_id.ilike(like_value),
                    ShipProfile.ship_name.ilike(like_value),
                    ShipProfile.ship_name_en.ilike(like_value),
                    ShipProfile.current_mmsi.ilike(like_value),
                )
            )
        if status_code:
            stmt = stmt.where(ShipProfile.profile_status_code == status_code)
        if ship_type_code:
            stmt = stmt.where(ShipProfile.ship_type_code == ship_type_code)
        if city_code:
            stmt = stmt.where(ShipProfile.registry_city_code == city_code)

        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        items = (
            await self.db.execute(
                stmt.order_by(ShipProfile.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).scalars().all()
        return list(items), total

    async def list_all_ships(self) -> list[ShipProfile]:
        rows = (
            await self.db.execute(
                select(ShipProfile)
                .where(ShipProfile.deleted_at.is_(None))
                .order_by(ShipProfile.id.asc())
            )
        ).scalars().all()
        return list(rows)

    async def create_ship(self, data: dict[str, Any]) -> ShipProfile:
        row = ShipProfile(**data)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update_ship(self, ship_id: int, data: dict[str, Any]) -> ShipProfile | None:
        row = await self.get_ship_by_id(ship_id)
        if row is None:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update_ship_status(self, ship_id: int, status_code: str) -> bool:
        row = await self.get_ship_by_id(ship_id)
        if row is None:
            return False
        row.profile_status_code = status_code
        await self.db.flush()
        return True

    async def exists_ship_code_fields(
        self,
        ais_id: str | None = None,
        mmsi: str | None = None,
        ship_name: str | None = None,
        exclude_ship_id: int | None = None,
    ) -> bool:
        conditions = []
        if ais_id:
            conditions.append(ShipProfile.ais_id == ais_id)
        if mmsi:
            conditions.append(ShipProfile.current_mmsi == mmsi)
        if ship_name:
            conditions.append(ShipProfile.ship_name == ship_name)
        if not conditions:
            return False
        stmt = select(ShipProfile).where(ShipProfile.deleted_at.is_(None), or_(*conditions))
        if exclude_ship_id is not None:
            stmt = stmt.where(ShipProfile.id != exclude_ship_id)
        return await self.db.scalar(stmt) is not None


class ShipCapacityRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_capacity_by_ship_id(self, ship_id: int) -> ShipCapacity | None:
        return await self.db.scalar(select(ShipCapacity).where(ShipCapacity.ship_id == ship_id))

    async def list_capacity_by_ship_ids(self, ship_ids: list[int]) -> dict[int, ShipCapacity]:
        if not ship_ids:
            return {}
        rows = (
            await self.db.execute(select(ShipCapacity).where(ShipCapacity.ship_id.in_(ship_ids)))
        ).scalars().all()
        return {row.ship_id: row for row in rows}

    async def upsert_capacity(self, ship_id: int, data: dict[str, Any]) -> ShipCapacity:
        row = await self.get_capacity_by_ship_id(ship_id)
        now = datetime.utcnow()
        if row is None:
            row = ShipCapacity(ship_id=ship_id, updated_at=now, **data)
            self.db.add(row)
        else:
            for key, value in data.items():
                setattr(row, key, value)
            row.updated_at = now
        await self.db.flush()
        await self.db.refresh(row)
        return row


class ShipOperationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_operation_by_ship_id(self, ship_id: int) -> ShipOperation | None:
        return await self.db.scalar(select(ShipOperation).where(ShipOperation.ship_id == ship_id))

    async def upsert_operation(self, ship_id: int, data: dict[str, Any]) -> ShipOperation:
        row = await self.get_operation_by_ship_id(ship_id)
        now = datetime.utcnow()
        if row is None:
            row = ShipOperation(ship_id=ship_id, updated_at=now, **data)
            self.db.add(row)
        else:
            for key, value in data.items():
                setattr(row, key, value)
            row.updated_at = now
        await self.db.flush()
        await self.db.refresh(row)
        return row


class ShipOwnerRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_owners(self, ship_id: int) -> list[ShipOwner]:
        return list(
            (
                await self.db.execute(
                    select(ShipOwner)
                    .where(ShipOwner.ship_id == ship_id)
                    .order_by(ShipOwner.is_primary.desc(), ShipOwner.id.asc())
                )
            )
            .scalars()
            .all()
        )

    async def replace_owners(self, ship_id: int, owners: list[dict[str, Any]]) -> list[ShipOwner]:
        await self.db.execute(delete(ShipOwner).where(ShipOwner.ship_id == ship_id))
        rows: list[ShipOwner] = []
        for item in owners:
            row = ShipOwner(ship_id=ship_id, **item)
            self.db.add(row)
            rows.append(row)
        await self.db.flush()
        return rows


class ShipContactRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_contacts(self, ship_id: int) -> list[ShipContact]:
        return list(
            (
                await self.db.execute(
                    select(ShipContact)
                    .where(ShipContact.ship_id == ship_id)
                    .order_by(ShipContact.is_primary.desc(), ShipContact.id.asc())
                )
            )
            .scalars()
            .all()
        )

    async def replace_contacts(self, ship_id: int, contacts: list[dict[str, Any]]) -> list[ShipContact]:
        await self.db.execute(delete(ShipContact).where(ShipContact.ship_id == ship_id))
        rows: list[ShipContact] = []
        for item in contacts:
            row = ShipContact(ship_id=ship_id, **item)
            self.db.add(row)
            rows.append(row)
        await self.db.flush()
        return rows


class ShipCertificateRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_certificates(self, ship_id: int) -> list[ShipCertificate]:
        return list(
            (
                await self.db.execute(
                    select(ShipCertificate)
                    .where(ShipCertificate.ship_id == ship_id)
                    .order_by(ShipCertificate.id.desc())
                )
            )
            .scalars()
            .all()
        )

    async def get_certificate(self, certificate_id: int) -> ShipCertificate | None:
        return await self.db.scalar(select(ShipCertificate).where(ShipCertificate.id == certificate_id))

    async def create_certificate(self, ship_id: int, data: dict[str, Any]) -> ShipCertificate:
        row = ShipCertificate(ship_id=ship_id, **data)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update_certificate(
        self, certificate_id: int, data: dict[str, Any]
    ) -> ShipCertificate | None:
        row = await self.get_certificate(certificate_id)
        if row is None:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def delete_certificate(self, certificate_id: int) -> bool:
        row = await self.get_certificate(certificate_id)
        if row is None:
            return False
        await self.db.delete(row)
        await self.db.flush()
        return True

    async def list_certificate_files(self, certificate_id: int) -> list[ShipCertificateFile]:
        return list(
            (
                await self.db.execute(
                    select(ShipCertificateFile)
                    .where(ShipCertificateFile.ship_certificate_id == certificate_id)
                    .order_by(ShipCertificateFile.id.asc())
                )
            )
            .scalars()
            .all()
        )

    async def replace_certificate_files(
        self, certificate_id: int, files: list[dict[str, Any]]
    ) -> list[ShipCertificateFile]:
        await self.db.execute(
            delete(ShipCertificateFile).where(ShipCertificateFile.ship_certificate_id == certificate_id)
        )
        rows: list[ShipCertificateFile] = []
        now = datetime.utcnow()
        for item in files:
            row = ShipCertificateFile(
                ship_certificate_id=certificate_id,
                created_at=now,
                **item,
            )
            self.db.add(row)
            rows.append(row)
        await self.db.flush()
        return rows


class ShipNameHistoryRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_name_history(self, ship_id: int) -> list[ShipNameHistory]:
        return list(
            (
                await self.db.execute(
                    select(ShipNameHistory)
                    .where(ShipNameHistory.ship_id == ship_id)
                    .order_by(ShipNameHistory.id.desc())
                )
            )
            .scalars()
            .all()
        )

    async def append_name_history(self, ship_id: int, data: dict[str, Any]) -> ShipNameHistory:
        row = ShipNameHistory(ship_id=ship_id, created_at=datetime.utcnow(), **data)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row


class ShipMmsiHistoryRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_mmsi_history(self, ship_id: int) -> list[ShipMmsiHistory]:
        return list(
            (
                await self.db.execute(
                    select(ShipMmsiHistory)
                    .where(ShipMmsiHistory.ship_id == ship_id)
                    .order_by(ShipMmsiHistory.id.desc())
                )
            )
            .scalars()
            .all()
        )

    async def append_mmsi_history(self, ship_id: int, data: dict[str, Any]) -> ShipMmsiHistory:
        row = ShipMmsiHistory(ship_id=ship_id, created_at=datetime.utcnow(), **data)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row


class ShipImportBatchRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_batch(self, batch_id: int) -> ShipImportBatch | None:
        return await self.db.scalar(select(ShipImportBatch).where(ShipImportBatch.id == batch_id))

    async def get_batch_by_no(self, batch_no: str) -> ShipImportBatch | None:
        return await self.db.scalar(select(ShipImportBatch).where(ShipImportBatch.batch_no == batch_no))

    async def list_batches(
        self,
        keyword: str | None,
        status_code: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[ShipImportBatch], int]:
        stmt = select(ShipImportBatch)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    ShipImportBatch.batch_no.ilike(like_value),
                    ShipImportBatch.source_type_code.ilike(like_value),
                    ShipImportBatch.remark.ilike(like_value),
                )
            )
        if status_code:
            stmt = stmt.where(ShipImportBatch.status_code == status_code)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(ShipImportBatch.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def create_batch(self, data: dict[str, Any]) -> ShipImportBatch:
        row = ShipImportBatch(**data)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update_batch(self, batch_id: int, data: dict[str, Any]) -> ShipImportBatch | None:
        row = await self.get_batch(batch_id)
        if row is None:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.db.flush()
        await self.db.refresh(row)
        return row


class ShipImportRawRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_raw_records(
        self, batch_id: int, page: int, page_size: int
    ) -> tuple[list[ShipImportRaw], int]:
        stmt = select(ShipImportRaw).where(ShipImportRaw.batch_id == batch_id)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(ShipImportRaw.row_no.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def create_raw_records(self, batch_id: int, items: list[dict[str, Any]]) -> list[ShipImportRaw]:
        rows: list[ShipImportRaw] = []
        now = datetime.utcnow()
        for item in items:
            row = ShipImportRaw(batch_id=batch_id, created_at=now, **item)
            self.db.add(row)
            rows.append(row)
        await self.db.flush()
        return rows

    async def get_raw_record(self, raw_id: int) -> ShipImportRaw | None:
        return await self.db.scalar(select(ShipImportRaw).where(ShipImportRaw.id == raw_id))


class ShipImportRecordRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_import_records(
        self, batch_id: int, page: int, page_size: int
    ) -> tuple[list[ShipImportRecord], int]:
        stmt = select(ShipImportRecord).where(ShipImportRecord.batch_id == batch_id)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(ShipImportRecord.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def create_import_record(self, data: dict[str, Any]) -> ShipImportRecord:
        row = ShipImportRecord(created_at=datetime.utcnow(), **data)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update_import_record(
        self, record_id: int, data: dict[str, Any]
    ) -> ShipImportRecord | None:
        row = await self.db.scalar(select(ShipImportRecord).where(ShipImportRecord.id == record_id))
        if row is None:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.db.flush()
        await self.db.refresh(row)
        return row
