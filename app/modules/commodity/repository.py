"""commodity 模块 repository。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commodity import (
    CommodityAlias,
    CommodityCategory,
    CommodityHandlingModeRule,
    CommodityNodeTypeRule,
    CommodityPackagingForm,
    CommodityShipTypeRule,
    CommodityStandard,
    CommodityStandardAttribute,
    CommodityTransportMode,
    CommodityType,
)


class CommodityCategoryRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_categories(
        self, keyword: str | None, status: int | None, page: int, page_size: int
    ) -> tuple[list[CommodityCategory], int]:
        stmt = select(CommodityCategory)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    CommodityCategory.code.ilike(like_value),
                    CommodityCategory.name.ilike(like_value),
                )
            )
        if status is not None:
            if status == 1:
                stmt = stmt.where(CommodityCategory.deleted_at.is_(None))
            else:
                stmt = stmt.where(CommodityCategory.deleted_at.is_not(None))
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        items = (
            await self.db.execute(
                stmt.order_by(CommodityCategory.sort_order.asc(), CommodityCategory.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(items), total

    async def get_category(self, category_id: int) -> CommodityCategory | None:
        return await self.db.scalar(select(CommodityCategory).where(CommodityCategory.id == category_id))

    async def get_category_by_code(self, code: str) -> CommodityCategory | None:
        return await self.db.scalar(select(CommodityCategory).where(CommodityCategory.code == code))

    async def create_category(self, data: dict[str, Any]) -> CommodityCategory:
        entity = CommodityCategory(**data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def update_category(self, category_id: int, data: dict[str, Any]) -> CommodityCategory | None:
        entity = await self.get_category(category_id)
        if entity is None:
            return None
        for key, value in data.items():
            setattr(entity, key, value)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity


class CommodityTypeRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_types(
        self,
        category_id: int | None,
        keyword: str | None,
        status: int | None,
        page: int,
        page_size: int,
    ) -> tuple[list[CommodityType], int]:
        stmt = select(CommodityType)
        if category_id is not None:
            stmt = stmt.where(CommodityType.category_id == category_id)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(CommodityType.code.ilike(like_value), CommodityType.name.ilike(like_value))
            )
        if status is not None:
            if status == 1:
                stmt = stmt.where(CommodityType.deleted_at.is_(None))
            else:
                stmt = stmt.where(CommodityType.deleted_at.is_not(None))
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        items = (
            await self.db.execute(
                stmt.order_by(CommodityType.sort_order.asc(), CommodityType.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(items), total

    async def get_type(self, type_id: int) -> CommodityType | None:
        return await self.db.scalar(select(CommodityType).where(CommodityType.id == type_id))

    async def get_type_by_code(self, code: str) -> CommodityType | None:
        return await self.db.scalar(select(CommodityType).where(CommodityType.code == code))

    async def create_type(self, data: dict[str, Any]) -> CommodityType:
        entity = CommodityType(**data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def update_type(self, type_id: int, data: dict[str, Any]) -> CommodityType | None:
        entity = await self.get_type(type_id)
        if entity is None:
            return None
        for key, value in data.items():
            setattr(entity, key, value)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity


class CommodityStandardRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_standards(
        self,
        category_id: int | None,
        type_id: int | None,
        keyword: str | None,
        status: int | None,
        page: int,
        page_size: int,
    ) -> tuple[list[CommodityStandard], int]:
        stmt = select(CommodityStandard).join(CommodityType, CommodityType.id == CommodityStandard.type_id)
        if category_id is not None:
            stmt = stmt.where(CommodityType.category_id == category_id)
        if type_id is not None:
            stmt = stmt.where(CommodityStandard.type_id == type_id)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    CommodityStandard.code.ilike(like_value),
                    CommodityStandard.name.ilike(like_value),
                    CommodityStandard.short_name.ilike(like_value),
                )
            )
        if status is not None:
            if status == 1:
                stmt = stmt.where(CommodityStandard.deleted_at.is_(None))
            else:
                stmt = stmt.where(CommodityStandard.deleted_at.is_not(None))
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        items = (
            await self.db.execute(
                stmt.order_by(CommodityStandard.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(items), total

    async def get_standard(self, standard_id: int) -> CommodityStandard | None:
        return await self.db.scalar(select(CommodityStandard).where(CommodityStandard.id == standard_id))

    async def get_standard_by_code(self, code: str) -> CommodityStandard | None:
        return await self.db.scalar(select(CommodityStandard).where(CommodityStandard.code == code))

    async def create_standard(self, data: dict[str, Any]) -> CommodityStandard:
        entity = CommodityStandard(**data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def update_standard(self, standard_id: int, data: dict[str, Any]) -> CommodityStandard | None:
        entity = await self.get_standard(standard_id)
        if entity is None:
            return None
        for key, value in data.items():
            setattr(entity, key, value)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def replace_aliases(self, standard_id: int, aliases: list[str]) -> None:
        await self.db.execute(delete(CommodityAlias).where(CommodityAlias.commodity_standard_id == standard_id))
        now = datetime.utcnow()
        for idx, alias in enumerate(aliases):
            value = alias.strip()
            if not value:
                continue
            self.db.add(
                CommodityAlias(
                    commodity_standard_id=standard_id,
                    alias_name=value,
                    source_type_code="MANUAL",
                    is_primary=idx == 0,
                    created_at=now,
                    updated_at=now,
                )
            )
        await self.db.flush()

    async def replace_attributes(self, standard_id: int, attributes: list[dict[str, Any]]) -> None:
        await self.db.execute(
            delete(CommodityStandardAttribute).where(
                CommodityStandardAttribute.commodity_standard_id == standard_id
            )
        )
        now = datetime.utcnow()
        for item in attributes:
            self.db.add(
                CommodityStandardAttribute(
                    commodity_standard_id=standard_id,
                    attribute_code=item["attribute_code"],
                    attribute_name=item["attribute_name"],
                    attribute_value_type_code=item["attribute_value_type_code"],
                    attribute_unit=item.get("attribute_unit"),
                    is_required=bool(item.get("is_required", False)),
                    default_value=item.get("default_value"),
                    value_range_desc=item.get("value_range_desc"),
                    sort_order=int(item.get("sort_order", 0)),
                    created_at=now,
                    updated_at=now,
                )
            )
        await self.db.flush()

    async def replace_packaging_forms(self, standard_id: int, codes: list[str]) -> None:
        await self.db.execute(
            delete(CommodityPackagingForm).where(CommodityPackagingForm.commodity_standard_id == standard_id)
        )
        now = datetime.utcnow()
        for idx, code in enumerate(codes):
            self.db.add(
                CommodityPackagingForm(
                    commodity_standard_id=standard_id,
                    packaging_form_code=code,
                    is_default=idx == 0,
                    created_at=now,
                )
            )
        await self.db.flush()

    async def replace_transport_modes(self, standard_id: int, codes: list[str]) -> None:
        await self.db.execute(
            delete(CommodityTransportMode).where(CommodityTransportMode.commodity_standard_id == standard_id)
        )
        now = datetime.utcnow()
        for idx, code in enumerate(codes):
            self.db.add(
                CommodityTransportMode(
                    commodity_standard_id=standard_id,
                    transport_mode_element_code=code,
                    is_default=idx == 0,
                    created_at=now,
                )
            )
        await self.db.flush()

    async def replace_ship_type_rules(self, standard_id: int, codes: list[str]) -> None:
        await self.db.execute(
            delete(CommodityShipTypeRule).where(CommodityShipTypeRule.commodity_standard_id == standard_id)
        )
        now = datetime.utcnow()
        for code in codes:
            self.db.add(
                CommodityShipTypeRule(
                    commodity_standard_id=standard_id,
                    ship_type_code=code,
                    allow_flag=True,
                    rule_desc=None,
                    created_at=now,
                )
            )
        await self.db.flush()

    async def replace_node_type_rules(self, standard_id: int, codes: list[str]) -> None:
        await self.db.execute(
            delete(CommodityNodeTypeRule).where(CommodityNodeTypeRule.commodity_standard_id == standard_id)
        )
        now = datetime.utcnow()
        for code in codes:
            self.db.add(
                CommodityNodeTypeRule(
                    commodity_standard_id=standard_id,
                    node_type_code=code,
                    allow_flag=True,
                    rule_desc=None,
                    created_at=now,
                )
            )
        await self.db.flush()

    async def replace_handling_mode_rules(self, standard_id: int, codes: list[str]) -> None:
        await self.db.execute(
            delete(CommodityHandlingModeRule).where(
                CommodityHandlingModeRule.commodity_standard_id == standard_id
            )
        )
        now = datetime.utcnow()
        for code in codes:
            self.db.add(
                CommodityHandlingModeRule(
                    commodity_standard_id=standard_id,
                    handling_mode_code=code,
                    allow_flag=True,
                    rule_desc=None,
                    created_at=now,
                )
            )
        await self.db.flush()

    async def list_aliases(self, standard_id: int) -> list[str]:
        rows = (
            await self.db.execute(
                select(CommodityAlias.alias_name).where(CommodityAlias.commodity_standard_id == standard_id)
            )
        ).all()
        return [row[0] for row in rows]

    async def list_attributes(self, standard_id: int) -> list[CommodityStandardAttribute]:
        return list(
            (
                await self.db.execute(
                    select(CommodityStandardAttribute)
                    .where(CommodityStandardAttribute.commodity_standard_id == standard_id)
                    .order_by(CommodityStandardAttribute.sort_order.asc(), CommodityStandardAttribute.id.asc())
                )
            )
            .scalars()
            .all()
        )

    async def _list_codes(self, model, column, standard_id: int) -> list[str]:
        rows = (await self.db.execute(select(column).where(model.commodity_standard_id == standard_id))).all()
        return [row[0] for row in rows]

    async def list_packaging_form_codes(self, standard_id: int) -> list[str]:
        return await self._list_codes(
            CommodityPackagingForm,
            CommodityPackagingForm.packaging_form_code,
            standard_id,
        )

    async def list_transport_mode_codes(self, standard_id: int) -> list[str]:
        return await self._list_codes(
            CommodityTransportMode,
            CommodityTransportMode.transport_mode_element_code,
            standard_id,
        )

    async def list_ship_type_codes(self, standard_id: int) -> list[str]:
        return await self._list_codes(
            CommodityShipTypeRule,
            CommodityShipTypeRule.ship_type_code,
            standard_id,
        )

    async def list_node_type_codes(self, standard_id: int) -> list[str]:
        return await self._list_codes(
            CommodityNodeTypeRule,
            CommodityNodeTypeRule.node_type_code,
            standard_id,
        )

    async def list_handling_mode_codes(self, standard_id: int) -> list[str]:
        return await self._list_codes(
            CommodityHandlingModeRule,
            CommodityHandlingModeRule.handling_mode_code,
            standard_id,
        )

