"""
船舶数据访问层
"""
from typing import Optional, Sequence, Tuple

from sqlalchemy import select, and_, desc, func, or_

from app.models.vessel import (
    VesselTypeDict, Vessel, VesselNameHistory, VesselAisHistory, VesselDynamic,
)
from app.repositories.base import BaseRepository


class VesselRepository(BaseRepository):
    model_class = Vessel

    # ─────────────────────────────────────────────────
    # VesselTypeDict
    # ─────────────────────────────────────────────────

    async def list_vessel_types(
        self, status: Optional[int] = None
    ) -> Sequence[VesselTypeDict]:
        q = select(VesselTypeDict)
        if status is not None:
            q = q.where(VesselTypeDict.status == status)
        result = await self._db.execute(q)
        return result.scalars().all()

    async def get_vessel_type(self, type_id: int) -> Optional[VesselTypeDict]:
        result = await self._db.execute(
            select(VesselTypeDict).where(VesselTypeDict.id == type_id)
        )
        return result.scalar_one_or_none()

    async def create_vessel_type(self, vt: VesselTypeDict) -> VesselTypeDict:
        return await self.create(vt)

    async def update_vessel_type(self, type_id: int, **kwargs) -> Optional[VesselTypeDict]:
        vt = await self.get_vessel_type(type_id)
        return await self.update(vt, **kwargs) if vt else None

    async def delete_vessel_type(self, type_id: int) -> bool:
        vt = await self.get_vessel_type(type_id)
        if not vt:
            return False
        await self.delete(vt)
        return True

    # ─────────────────────────────────────────────────
    # Vessel
    # ─────────────────────────────────────────────────

    async def get_vessel(self, vessel_id: int) -> Optional[Vessel]:
        result = await self._db.execute(
            select(Vessel).where(Vessel.id == vessel_id)
        )
        return result.scalar_one_or_none()

    async def get_vessel_by_mmsi(self, mmsi: str) -> Optional[Vessel]:
        result = await self._db.execute(
            select(Vessel).where(Vessel.mmsi == mmsi)
        )
        return result.scalar_one_or_none()

    async def list_vessels(
        self,
        vessel_type_id: Optional[int] = None,
        audit_status: Optional[int] = None,
        keyword: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> Tuple[Sequence[Vessel], int]:
        conditions = []
        if vessel_type_id is not None:
            conditions.append(Vessel.vessel_type_id == vessel_type_id)
        if audit_status is not None:
            conditions.append(Vessel.audit_status == audit_status)
        if keyword:
            conditions.append(
                or_(
                    Vessel.vessel_name.ilike(f"%{keyword}%"),
                    Vessel.mmsi.ilike(f"%{keyword}%"),
                )
            )

        query = select(Vessel)
        if conditions:
            query = query.where(and_(*conditions))

        total_result = await self._db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = total_result.scalar_one()

        result = await self._db.execute(
            query.order_by(desc(Vessel.created_at)).offset(offset).limit(limit)
        )
        return result.scalars().all(), total

    async def create_vessel(self, vessel: Vessel) -> Vessel:
        return await self.create(vessel)

    async def update_vessel(self, vessel_id: int, **kwargs) -> Optional[Vessel]:
        vessel = await self.get_vessel(vessel_id)
        return await self.update(vessel, **kwargs) if vessel else None

    async def delete_vessel(self, vessel_id: int) -> bool:
        vessel = await self.get_vessel(vessel_id)
        if not vessel:
            return False
        await self.delete(vessel)
        return True

    # ─────────────────────────────────────────────────
    # VesselDynamic
    # ─────────────────────────────────────────────────

    async def get_dynamic(self, vessel_id: int) -> Optional[VesselDynamic]:
        result = await self._db.execute(
            select(VesselDynamic).where(VesselDynamic.vessel_id == vessel_id)
        )
        return result.scalar_one_or_none()

    async def upsert_dynamic(self, vessel_id: int, **kwargs) -> VesselDynamic:
        dynamic = await self.get_dynamic(vessel_id)
        if dynamic:
            for k, v in kwargs.items():
                if hasattr(dynamic, k):
                    setattr(dynamic, k, v)
        else:
            dynamic = VesselDynamic(vessel_id=vessel_id, **kwargs)
            self._db.add(dynamic)
        await self._db.flush()
        await self._db.refresh(dynamic)
        return dynamic

    # ─────────────────────────────────────────────────
    # VesselNameHistory / AisHistory
    # ─────────────────────────────────────────────────

    async def list_name_history(self, vessel_id: int) -> Sequence[VesselNameHistory]:
        result = await self._db.execute(
            select(VesselNameHistory)
            .where(VesselNameHistory.vessel_id == vessel_id)
            .order_by(desc(VesselNameHistory.changed_at))
        )
        return result.scalars().all()

    async def create_name_history(self, history: VesselNameHistory) -> VesselNameHistory:
        return await self.create(history)

    async def list_ais_history(
        self, vessel_id: int, limit: int = 50
    ) -> Sequence[VesselAisHistory]:
        result = await self._db.execute(
            select(VesselAisHistory)
            .where(VesselAisHistory.vessel_id == vessel_id)
            .order_by(desc(VesselAisHistory.report_time))
            .limit(limit)
        )
        return result.scalars().all()
