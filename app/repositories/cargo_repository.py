"""
货物数据访问层
封装所有与货物相关的数据库操作
"""
from datetime import date
from typing import Optional, Sequence

from sqlalchemy import select, and_, desc, func, or_
from sqlalchemy.orm import selectinload

from app.models.cargo import (
    CommodityCategory,
    CommodityType,
    CommodityStandard,
    CommodityAlias,
    CargoRawMessage,
    CargoAiParseResult,
    CargoFreight,
    TmsCargoRaw,
)
from app.repositories.base import BaseRepository


class CargoCategoryRepository(BaseRepository):
    model_class = CommodityCategory

    async def get_all_with_types(self) -> Sequence[CommodityCategory]:
        result = await self._db.execute(
            select(CommodityCategory)
            .where(CommodityCategory.deleted_at.is_(None))
            .options(selectinload(CommodityCategory.types))
        )
        return result.scalars().unique().all()


class CargoTypeRepository(BaseRepository):
    model_class = CommodityType

    async def get_by_category(self, category_id: int) -> Sequence[CommodityType]:
        result = await self._db.execute(
            select(CommodityType).where(
                CommodityType.category_id == category_id,
                CommodityType.deleted_at.is_(None),
            )
        )
        return result.scalars().all()

    async def get_with_standards(self, type_id: int) -> Optional[CommodityType]:
        result = await self._db.execute(
            select(CommodityType)
            .where(
                CommodityType.id == type_id,
                CommodityType.deleted_at.is_(None),
            )
            .options(selectinload(CommodityType.standards))
        )
        return result.scalar_one_or_none()


class CargoStandardRepository(BaseRepository):
    model_class = CommodityStandard

    async def get_by_type(self, type_id: int) -> Sequence[CommodityStandard]:
        result = await self._db.execute(
            select(CommodityStandard).where(
                CommodityStandard.type_id == type_id,
                CommodityStandard.deleted_at.is_(None),
            )
        )
        return result.scalars().all()

    async def search_by_name(self, keyword: str) -> Sequence[CommodityStandard]:
        result = await self._db.execute(
            select(CommodityStandard).where(
                CommodityStandard.name.ilike(f"%{keyword}%"),
                CommodityStandard.deleted_at.is_(None),
            )
        )
        return result.scalars().all()

    async def list_paginated(
        self,
        type_id: Optional[int] = None,
        keyword: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[CommodityStandard], int]:
        filters = [CommodityStandard.deleted_at.is_(None)]
        if type_id:
            filters.append(CommodityStandard.type_id == type_id)
        if keyword:
            filters.append(CommodityStandard.name.ilike(f"%{keyword}%"))

        query = select(CommodityStandard).where(and_(*filters))
        total_result = await self._db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = total_result.scalar_one()
        result = await self._db.execute(
            query.order_by(CommodityStandard.sort_order, CommodityStandard.id)
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all(), total

    async def get_all(
        self, type_id: Optional[int] = None
    ) -> Sequence[CommodityStandard]:
        filters = [CommodityStandard.deleted_at.is_(None)]
        if type_id:
            filters.append(CommodityStandard.type_id == type_id)
        result = await self._db.execute(
            select(CommodityStandard)
            .where(and_(*filters))
            .order_by(CommodityStandard.sort_order, CommodityStandard.id)
        )
        return result.scalars().all()


class CommodityAliasRepository(BaseRepository):
    model_class = CommodityAlias

    async def get_all_aliases(self) -> Sequence[CommodityAlias]:
        """获取所有商品别名，用于AI模糊匹配"""
        result = await self._db.execute(
            select(CommodityAlias).where(CommodityAlias.status == 1)
        )
        return result.scalars().all()

    async def get_by_standard(self, standard_id: int) -> Sequence[CommodityAlias]:
        result = await self._db.execute(
            select(CommodityAlias).where(
                CommodityAlias.commodity_id == standard_id
            )
        )
        return result.scalars().all()

    async def create_alias(self, alias: CommodityAlias) -> CommodityAlias:
        return await self.create(alias)


class CargoRepository(BaseRepository):
    """货源相关Repository — 聚合多个货物实体的数据访问"""

    model_class = CargoRawMessage

    def __init__(self, db) -> None:
        super().__init__(db)
        self.categories = CargoCategoryRepository(db)
        self.types = CargoTypeRepository(db)
        self.standards = CargoStandardRepository(db)
        self.aliases = CommodityAliasRepository(db)

    # ─────────────────────────────────────────────────
    # CargoRawMessage
    # ─────────────────────────────────────────────────

    async def get_raw_message(self, msg_id: int) -> Optional[CargoRawMessage]:
        return await self.get_by_id(msg_id)

    async def list_raw_messages(
        self,
        status: Optional[str] = None,
        operator_id: Optional[int] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[CargoRawMessage], int]:
        filters = []
        if status:
            filters.append(CargoRawMessage.status == status)
        if operator_id:
            filters.append(CargoRawMessage.collector_id == operator_id)

        query = select(CargoRawMessage)
        if filters:
            query = query.where(and_(*filters))

        total_result = await self._db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = total_result.scalar_one()

        result = await self._db.execute(
            query.order_by(desc(CargoRawMessage.created_at))
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all(), total

    async def update_parse_status(
        self, msg_id: int, status: str
    ) -> Optional[CargoRawMessage]:
        msg = await self.get_by_id(msg_id)
        if msg:
            msg.status = status
            await self._db.flush()
        return msg

    # ─────────────────────────────────────────────────
    # CargoAiParseResult
    # ─────────────────────────────────────────────────

    async def get_parse_result_by_msg(self, msg_id: int) -> Optional[CargoAiParseResult]:
        """根据原始消息ID获取解析结果"""
        result = await self._db.execute(
            select(CargoAiParseResult).where(
                CargoAiParseResult.raw_message_id == msg_id
            ).order_by(desc(CargoAiParseResult.id)).limit(1)
        )
        return result.scalar_one_or_none()

    async def get_parse_result(self, result_id: int) -> Optional[CargoAiParseResult]:
        """根据解析结果ID获取"""
        result = await self._db.execute(
            select(CargoAiParseResult).where(CargoAiParseResult.id == result_id)
        )
        return result.scalar_one_or_none()

    async def create_parse_result(
        self, parse_result: CargoAiParseResult
    ) -> CargoAiParseResult:
        return await self.create(parse_result)

    async def update_parse_result(
        self, result_id: int, **kwargs
    ) -> Optional[CargoAiParseResult]:
        result = await self._db.execute(
            select(CargoAiParseResult).where(CargoAiParseResult.id == result_id)
        )
        instance = result.scalar_one_or_none()
        if instance:
            for k, v in kwargs.items():
                setattr(instance, k, v)
            await self._db.flush()
        return instance

    # ─────────────────────────────────────────────────
    # CargoFreight
    # ─────────────────────────────────────────────────

    async def get_freight(self, freight_id: int) -> Optional[CargoFreight]:
        result = await self._db.execute(
            select(CargoFreight).where(
                CargoFreight.id == freight_id,
                CargoFreight.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_freight_by_no(self, freight_no: str) -> Optional[CargoFreight]:
        result = await self._db.execute(
            select(CargoFreight).where(
                CargoFreight.freight_no == freight_no,
                CargoFreight.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_freights(
        self,
        status: Optional[str] = None,
        source_type: Optional[str] = None,
        origin_admin_code: Optional[str] = None,
        dest_admin_code: Optional[str] = None,
        commodity_id: Optional[int] = None,
        stat_date: Optional[date] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[CargoFreight], int]:
        filters = [CargoFreight.deleted_at.is_(None)]
        if status:
            filters.append(CargoFreight.status == status)
        if source_type:
            filters.append(CargoFreight.source_type == source_type)
        if origin_admin_code:
            filters.append(CargoFreight.origin_admin_code == origin_admin_code)
        if dest_admin_code:
            filters.append(CargoFreight.dest_admin_code == dest_admin_code)
        if commodity_id:
            filters.append(CargoFreight.commodity_id == commodity_id)
        if stat_date:
            filters.append(func.date(CargoFreight.created_at) == stat_date)

        query = select(CargoFreight).where(and_(*filters))
        total_result = await self._db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = total_result.scalar_one()

        result = await self._db.execute(
            query.order_by(desc(CargoFreight.created_at))
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all(), total

    async def create_freight(self, freight: CargoFreight) -> CargoFreight:
        return await self.create(freight)

    async def update_freight_status(
        self, freight_id: int, status: str
    ) -> Optional[CargoFreight]:
        freight = await self.get_freight(freight_id)
        if freight:
            freight.status = status
            await self._db.flush()
        return freight

    # ─────────────────────────────────────────────────
    # TmsCargoRaw
    # ─────────────────────────────────────────────────

    async def get_tms_raw_by_msg_id(
        self, tms_message_id: str
    ) -> Optional[TmsCargoRaw]:
        result = await self._db.execute(
            select(TmsCargoRaw).where(
                TmsCargoRaw.tms_message_id == tms_message_id
            )
        )
        return result.scalar_one_or_none()

    async def create_tms_raw(self, tms_raw: TmsCargoRaw) -> TmsCargoRaw:
        self._db.add(tms_raw)
        await self._db.flush()
        await self._db.refresh(tms_raw)
        return tms_raw

    async def update_tms_raw(
        self, tms_id: int, **kwargs
    ) -> Optional[TmsCargoRaw]:
        result = await self._db.execute(
            select(TmsCargoRaw).where(TmsCargoRaw.id == tms_id)
        )
        instance = result.scalar_one_or_none()
        if instance:
            for k, v in kwargs.items():
                setattr(instance, k, v)
            await self._db.flush()
        return instance

    async def list_tms_raws_pending(
        self, offset: int = 0, limit: int = 20
    ) -> tuple[Sequence[TmsCargoRaw], int]:
        query = select(TmsCargoRaw).where(TmsCargoRaw.process_status == "PENDING")
        total_result = await self._db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = total_result.scalar_one()
        result = await self._db.execute(
            query.order_by(desc(TmsCargoRaw.created_at))
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all(), total
