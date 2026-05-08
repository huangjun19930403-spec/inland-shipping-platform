"""vessel 模块 repository。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vessel import (
    VesselBuildInfo,
    VesselCapacityDimension,
    VesselCertificate,
    VesselCertificateFile,
    VesselCertificateImageRecognition,
    VesselContact,
    VesselCrewAssignment,
    VesselIdentifierHistory,
    VesselNameHistory,
    VesselOperatorPeriod,
    VesselOwnerPeriod,
    VesselPersonCertificate,
    VesselProfile,
    VesselRegistrationInfo,
)

T = TypeVar("T")


class VesselRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_profile(self, vessel_id: int) -> VesselProfile | None:
        return await self.db.scalar(
            select(VesselProfile).where(VesselProfile.id == vessel_id, VesselProfile.deleted_at.is_(None))
        )

    async def create_profile(self, data: dict[str, Any]) -> VesselProfile:
        entity = VesselProfile(**data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def update_profile(self, vessel_id: int, data: dict[str, Any]) -> VesselProfile | None:
        entity = await self.get_profile(vessel_id)
        if entity is None:
            return None
        for key, value in data.items():
            setattr(entity, key, value)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def get_one_by_profile(self, model: type[T], vessel_id: int) -> T | None:
        return await self.db.scalar(select(model).where(model.vessel_profile_id == vessel_id))  # type: ignore[attr-defined]

    async def upsert_one_by_profile(self, model: type[T], vessel_id: int, data: dict[str, Any]) -> T:
        entity = await self.get_one_by_profile(model, vessel_id)
        now = datetime.utcnow()
        if entity is None:
            entity = model(vessel_profile_id=vessel_id, updated_at=now, **data)  # type: ignore[call-arg]
            self.db.add(entity)  # type: ignore[arg-type]
        else:
            for key, value in data.items():
                setattr(entity, key, value)
            if hasattr(entity, "updated_at"):
                setattr(entity, "updated_at", now)
        await self.db.flush()
        await self.db.refresh(entity)  # type: ignore[arg-type]
        return entity

    async def list_by_profile(self, model: type[T], vessel_id: int, *, order_desc: bool = False) -> list[T]:
        stmt = select(model).where(model.vessel_profile_id == vessel_id)  # type: ignore[attr-defined]
        if hasattr(model, "is_primary"):
            stmt = stmt.order_by(model.is_primary.desc(), model.id.asc())  # type: ignore[attr-defined]
        elif order_desc:
            stmt = stmt.order_by(model.id.desc())  # type: ignore[attr-defined]
        else:
            stmt = stmt.order_by(model.id.asc())  # type: ignore[attr-defined]
        return list((await self.db.execute(stmt)).scalars().all())

    async def replace_many_by_profile(
        self,
        model: type[T],
        vessel_id: int,
        rows: list[dict[str, Any]],
    ) -> list[T]:
        await self.db.execute(delete(model).where(model.vessel_profile_id == vessel_id))  # type: ignore[attr-defined]
        entities: list[T] = []
        for item in rows:
            entity = model(vessel_profile_id=vessel_id, **item)  # type: ignore[call-arg]
            self.db.add(entity)  # type: ignore[arg-type]
            entities.append(entity)
        await self.db.flush()
        return entities

    async def add_name_history(self, vessel_id: int, ship_name: str, source_type_code: str = "MANUAL") -> VesselNameHistory:
        row = VesselNameHistory(
            vessel_profile_id=vessel_id,
            ship_name=ship_name,
            start_date=None,
            end_date=None,
            source_type_code=source_type_code,
            created_at=datetime.utcnow(),
        )
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def add_identifier_history(
        self,
        vessel_id: int,
        identifier_type_code: str,
        identifier_value: str,
        source_type_code: str = "MANUAL",
    ) -> VesselIdentifierHistory:
        row = VesselIdentifierHistory(
            vessel_profile_id=vessel_id,
            identifier_type_code=identifier_type_code,
            identifier_value=identifier_value,
            start_date=None,
            end_date=None,
            source_type_code=source_type_code,
            created_at=datetime.utcnow(),
        )
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def get_certificate(self, certificate_id: int) -> VesselCertificate | None:
        return await self.db.scalar(select(VesselCertificate).where(VesselCertificate.id == certificate_id))

    async def create_certificate(self, vessel_id: int, data: dict[str, Any]) -> VesselCertificate:
        entity = VesselCertificate(vessel_profile_id=vessel_id, **data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def update_certificate(self, certificate_id: int, data: dict[str, Any]) -> VesselCertificate | None:
        entity = await self.get_certificate(certificate_id)
        if entity is None:
            return None
        for key, value in data.items():
            setattr(entity, key, value)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def create_certificate_file(self, data: dict[str, Any]) -> VesselCertificateFile:
        entity = VesselCertificateFile(**data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def get_certificate_file_by_storage_file(
        self,
        certificate_id: int,
        storage_file_id: int,
    ) -> VesselCertificateFile | None:
        return await self.db.scalar(
            select(VesselCertificateFile).where(
                VesselCertificateFile.vessel_certificate_id == certificate_id,
                VesselCertificateFile.storage_file_id == storage_file_id,
            )
        )

    async def create_image_recognition(self, data: dict[str, Any]) -> VesselCertificateImageRecognition:
        entity = VesselCertificateImageRecognition(**data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def get_image_recognition(self, recognition_id: int) -> VesselCertificateImageRecognition | None:
        return await self.db.scalar(
            select(VesselCertificateImageRecognition).where(VesselCertificateImageRecognition.id == recognition_id)
        )


SINGLETON_MODELS = (
    VesselRegistrationInfo,
    VesselCapacityDimension,
    VesselBuildInfo,
)

LIST_MODELS = (
    VesselOwnerPeriod,
    VesselOperatorPeriod,
    VesselContact,
    VesselCrewAssignment,
    VesselPersonCertificate,
)
