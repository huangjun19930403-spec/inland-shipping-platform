"""
货物数据访问层
封装所有与货物相关的数据库操作
"""
from typing import Optional, Sequence

from sqlalchemy import select, and_, desc, func
from sqlalchemy.orm import selectinload

from app.models.cargo import (
    CommodityCategory,
    CommodityType,
    CommodityStandard,
    CommodityAlias,
    CargoRawMessage,
    CargoAiParseResult,
    CargoOpportunity,
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


class CommodityAliasRepository(BaseRepository):
    model_class = CommodityAlias

    async def get_all_aliases(self) -> Sequence[CommodityAlias]:
        """获取所有商品别名，用于AI模糊匹配"""
        result = await self._db.execute(select(CommodityAlias))
        return result.scalars().all()

    async def get_by_standard(self, standard_id: int) -> Sequence[CommodityAlias]:
        result = await self._db.execute(
            select(CommodityAlias).where(
                CommodityAlias.commodity_id == standard_id
            )
        )
        return result.scalars().all()


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

        count_query = select(CargoRawMessage)
        if filters:
            count_query = count_query.where(and_(*filters))

        total_result = await self._db.execute(
            select(func.count()).select_from(count_query.subquery())
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

    async def get_parse_result(self, msg_id: int) -> Optional[CargoAiParseResult]:
        result = await self._db.execute(
            select(CargoAiParseResult).where(
                CargoAiParseResult.raw_message_id == msg_id
            )
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
    # CargoOpportunity
    # ─────────────────────────────────────────────────

    async def get_opportunity(self, opp_id: int) -> Optional[CargoOpportunity]:
        result = await self._db.execute(
            select(CargoOpportunity).where(CargoOpportunity.id == opp_id)
        )
        return result.scalar_one_or_none()

    async def list_opportunities(
        self,
        status: Optional[str] = None,
        origin_node_id: Optional[int] = None,
        dest_node_id: Optional[int] = None,
        commodity_id: Optional[int] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[CargoOpportunity], int]:
        filters = []
        if status:
            filters.append(CargoOpportunity.status == status)
        if origin_node_id:
            filters.append(CargoOpportunity.origin_node_id == origin_node_id)
        if dest_node_id:
            filters.append(CargoOpportunity.dest_node_id == dest_node_id)
        if commodity_id:
            filters.append(CargoOpportunity.commodity_id == commodity_id)

        query = select(CargoOpportunity)
        if filters:
            query = query.where(and_(*filters))

        total_result = await self._db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = total_result.scalar_one()

        result = await self._db.execute(
            query.order_by(desc(CargoOpportunity.created_at))
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all(), total

    async def create_opportunity(
        self, opportunity: CargoOpportunity
    ) -> CargoOpportunity:
        return await self.create(opportunity)
