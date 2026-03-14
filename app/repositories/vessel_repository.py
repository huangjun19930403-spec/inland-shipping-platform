"""
船舶数据访问层
"""
from typing import Optional, Sequence

from sqlalchemy import select, and_, desc
from sqlalchemy.orm import selectinload

from app.models.vessel import (
    VesselTypeDict,
    Vessel,
    VesselNameHistory,
    VesselAisHistory,
    VesselDynamic,
)
from app.repositories.base import BaseRepository


class VesselRepository(BaseRepository):
    model_class = Vessel

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
        keyword: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[Vessel], int]:
        filters = []
        if vessel_type_id:
            filters.append(Vessel.vessel_type_id == vessel_type_id)
        if keyword:
            filters.append(Vessel.vessel_name.ilike(f"%{keyword}%"))

        query = select(Vessel)
        if filters:
            query = query.where(and_(*filters))

        from sqlalchemy import func
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
        if vessel:
            return await self.update(vessel, **kwargs)
        return None

    # ─────────────────────────────────────────────────
    # VesselDynamic
    # ─────────────────────────────────────────────────

    async def get_dynamic(self, vessel_id: int) -> Optional[VesselDynamic]:
        result = await self._db.execute(
            select(VesselDynamic).where(VesselDynamic.vessel_id == vessel_id)
        )
        return result.scalar_one_or_none()

    async def upsert_dynamic(
        self, vessel_id: int, **kwargs
    ) -> VesselDynamic:
        dynamic = await self.get_dynamic(vessel_id)
        if dynamic:
            for k, v in kwargs.items():
                setattr(dynamic, k, v)
        else:
            dynamic = VesselDynamic(vessel_id=vessel_id, **kwargs)
            self._db.add(dynamic)
        await self._db.flush()
        await self._db.refresh(dynamic)
        return dynamic

    # ─────────────────────────────────────────────────
    # VesselNameHistory
    # ─────────────────────────────────────────────────

    async def list_name_history(
        self, vessel_id: int
    ) -> Sequence[VesselNameHistory]:
        result = await self._db.execute(
            select(VesselNameHistory)
            .where(VesselNameHistory.vessel_id == vessel_id)
            .order_by(desc(VesselNameHistory.changed_at))
        )
        return result.scalars().all()

    async def create_name_history(
        self, history: VesselNameHistory
    ) -> VesselNameHistory:
        return await self.create(history)

    # ─────────────────────────────────────────────────
    # VesselTypeDict
    # ─────────────────────────────────────────────────

    async def list_vessel_types(self) -> Sequence[VesselTypeDict]:
        result = await self._db.execute(select(VesselTypeDict))
        return result.scalars().all()
