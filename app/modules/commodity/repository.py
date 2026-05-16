"""commodity 模块 repository。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commodity import (
    CommodityAlias,
    CommodityAttributeDefinition,
    CommodityCategory,
    CommodityHandlingModeRule,
    CommodityNodeTypeRule,
    CommodityPackagingForm,
    CommodityShipTypeRule,
    CommodityStandard,
    CommodityStandardAttribute,
    CommodityStandardImage,
    CommodityTransportMode,
    CommodityType,
)
from app.models.freight import Freight
from app.models.storage import StorageFile


class CommodityCategoryRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_categories(
        self, keyword: str | None, status: int | None, page: int, page_size: int
    ) -> tuple[list[CommodityCategory], int]:
        stmt = select(CommodityCategory)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(or_(CommodityCategory.code.ilike(like_value), CommodityCategory.name.ilike(like_value)))
        if status is not None:
            stmt = stmt.where(CommodityCategory.deleted_at.is_(None) if status == 1 else CommodityCategory.deleted_at.is_not(None))
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        items = (
            await self.db.execute(
                stmt.order_by(CommodityCategory.sort_order.asc(), CommodityCategory.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(items), total


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
            stmt = stmt.where(or_(CommodityType.code.ilike(like_value), CommodityType.name.ilike(like_value)))
        if status is not None:
            stmt = stmt.where(CommodityType.deleted_at.is_(None) if status == 1 else CommodityType.deleted_at.is_not(None))
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
        return await self.db.scalar(select(CommodityType).where(CommodityType.id == type_id, CommodityType.deleted_at.is_(None)))


class CommodityAttributeDefinitionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_definitions(self, *, enabled_only: bool = True) -> list[CommodityAttributeDefinition]:
        stmt = select(CommodityAttributeDefinition)
        if enabled_only:
            stmt = stmt.where(CommodityAttributeDefinition.is_enabled.is_(True))
        rows = (
            await self.db.execute(
                stmt.order_by(
                    CommodityAttributeDefinition.sort_order.asc(),
                    CommodityAttributeDefinition.id.asc(),
                )
            )
        ).scalars().all()
        return list(rows)

    async def get_definition(self, definition_id: int) -> CommodityAttributeDefinition | None:
        return await self.db.scalar(
            select(CommodityAttributeDefinition).where(
                CommodityAttributeDefinition.id == definition_id,
                CommodityAttributeDefinition.is_enabled.is_(True),
            )
        )


class CommodityStandardRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def _base_standard_stmt(self):
        category_id_expr = func.coalesce(CommodityStandard.category_id, CommodityType.category_id)
        return (
            select(CommodityStandard, CommodityType, CommodityCategory)
            .join(CommodityType, CommodityType.id == CommodityStandard.type_id)
            .outerjoin(CommodityCategory, CommodityCategory.id == category_id_expr)
        )

    async def list_standards(
        self,
        *,
        category_id: int | None,
        type_id: int | None,
        keyword: str | None,
        status: int | None,
        main_unit_code: str | None,
        cargo_form_code: str | None,
        is_bulk_cargo: bool | None,
        is_container_suitable: bool | None,
        is_hazardous: bool | None,
        source_type_code: str | None,
        has_alias: bool | None,
        has_image: bool | None,
        used_by_freight: bool | None,
        page: int,
        page_size: int,
    ) -> tuple[list[tuple[CommodityStandard, CommodityType, CommodityCategory | None]], int]:
        stmt = self._base_standard_stmt()
        category_id_expr = func.coalesce(CommodityStandard.category_id, CommodityType.category_id)
        stmt = stmt.where(CommodityStandard.deleted_at.is_(None))
        if category_id is not None:
            stmt = stmt.where(category_id_expr == category_id)
        if type_id is not None:
            stmt = stmt.where(CommodityStandard.type_id == type_id)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            alias_exists = exists(
                select(CommodityAlias.id).where(
                    CommodityAlias.commodity_standard_id == CommodityStandard.id,
                    CommodityAlias.alias_name.ilike(like_value),
                )
            )
            stmt = stmt.where(
                or_(
                    CommodityStandard.code.ilike(like_value),
                    CommodityStandard.name.ilike(like_value),
                    CommodityStandard.short_name.ilike(like_value),
                    CommodityStandard.english_name.ilike(like_value),
                    alias_exists,
                )
            )
        if status is not None:
            stmt = stmt.where(CommodityStandard.is_active.is_(status == 1))
        if main_unit_code:
            stmt = stmt.where(CommodityStandard.main_unit_code == main_unit_code.strip())
        if cargo_form_code:
            stmt = stmt.where(CommodityStandard.cargo_form_code == cargo_form_code.strip())
        if is_bulk_cargo is not None:
            stmt = stmt.where(CommodityStandard.is_bulk_cargo.is_(is_bulk_cargo))
        if is_container_suitable is not None:
            stmt = stmt.where(CommodityStandard.is_container_suitable.is_(is_container_suitable))
        if is_hazardous is not None:
            stmt = stmt.where(CommodityStandard.is_hazardous.is_(is_hazardous))
        if source_type_code:
            stmt = stmt.where(CommodityStandard.source_type_code == source_type_code.strip())

        alias_exists = exists(select(CommodityAlias.id).where(CommodityAlias.commodity_standard_id == CommodityStandard.id))
        image_exists = exists(select(CommodityStandardImage.id).where(CommodityStandardImage.commodity_standard_id == CommodityStandard.id))
        freight_exists = exists(select(Freight.id).where(Freight.commodity_standard_id == CommodityStandard.id, Freight.deleted_at.is_(None)))
        if has_alias is not None:
            stmt = stmt.where(alias_exists if has_alias else ~alias_exists)
        if has_image is not None:
            stmt = stmt.where(image_exists if has_image else ~image_exists)
        if used_by_freight is not None:
            stmt = stmt.where(freight_exists if used_by_freight else ~freight_exists)

        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(
                    CommodityStandard.recognition_priority.desc(),
                    CommodityStandard.updated_at.desc(),
                    CommodityStandard.id.desc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return [(row[0], row[1], row[2]) for row in rows], total

    async def get_standard_bundle(self, standard_id: int) -> tuple[CommodityStandard, CommodityType, CommodityCategory | None] | None:
        stmt = self._base_standard_stmt().where(CommodityStandard.id == standard_id, CommodityStandard.deleted_at.is_(None))
        row = (await self.db.execute(stmt)).first()
        if row is None:
            return None
        return row[0], row[1], row[2]

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

    async def bulk_counts(self, standard_ids: list[int]) -> dict[str, dict[int, int]]:
        if not standard_ids:
            return {"aliases": {}, "attributes": {}, "images": {}, "freights": {}}

        async def _counts(column) -> dict[int, int]:
            rows = (
                await self.db.execute(
                    select(column, func.count())
                    .where(column.in_(standard_ids))
                    .group_by(column)
                )
            ).all()
            return {int(row[0]): int(row[1]) for row in rows}

        return {
            "aliases": await _counts(CommodityAlias.commodity_standard_id),
            "attributes": await _counts(CommodityStandardAttribute.commodity_standard_id),
            "images": await _counts(CommodityStandardImage.commodity_standard_id),
            "freights": await _counts(Freight.commodity_standard_id),
        }

    async def freight_usage_summary(self, standard_id: int) -> tuple[int, int, datetime | None]:
        row = (
            await self.db.execute(
                select(func.count(Freight.id), func.max(Freight.updated_at))
                .where(Freight.commodity_standard_id == standard_id, Freight.deleted_at.is_(None))
            )
        ).one()
        raw_pending = int(
            await self.db.scalar(
                select(func.count(Freight.id)).where(
                    Freight.commodity_standard_id == standard_id,
                    Freight.deleted_at.is_(None),
                    Freight.commodity_match_level_code == "RAW",
                )
            )
            or 0
        )
        return int(row[0] or 0), raw_pending, row[1]

    async def recent_freight_usage(self, standard_id: int, *, limit: int = 8) -> list[Freight]:
        rows = (
            await self.db.execute(
                select(Freight)
                .where(Freight.commodity_standard_id == standard_id, Freight.deleted_at.is_(None))
                .order_by(Freight.updated_at.desc(), Freight.id.desc())
                .limit(limit)
            )
        ).scalars().all()
        return list(rows)

    async def list_aliases(self, standard_id: int) -> list[CommodityAlias]:
        return list(
            (
                await self.db.execute(
                    select(CommodityAlias)
                    .where(CommodityAlias.commodity_standard_id == standard_id)
                    .order_by(CommodityAlias.is_primary.desc(), CommodityAlias.match_weight.desc(), CommodityAlias.id.asc())
                )
            ).scalars().all()
        )

    async def replace_aliases(self, standard_id: int, aliases: list[dict[str, Any]]) -> None:
        await self.db.execute(delete(CommodityAlias).where(CommodityAlias.commodity_standard_id == standard_id))
        now = datetime.utcnow()
        seen: set[str] = set()
        primary_assigned = False
        for index, item in enumerate(aliases):
            alias_name = str(item.get("alias_name") or "").strip()
            if not alias_name or alias_name in seen:
                continue
            seen.add(alias_name)
            is_primary = bool(item.get("is_primary", False)) and not primary_assigned
            if index == 0 and not primary_assigned and not any(bool(raw.get("is_primary")) for raw in aliases):
                is_primary = True
            primary_assigned = primary_assigned or is_primary
            self.db.add(
                CommodityAlias(
                    commodity_standard_id=standard_id,
                    alias_name=alias_name,
                    alias_type_code=str(item.get("alias_type_code") or "COMMON_NAME").strip(),
                    source_type_code=str(item.get("source_type_code") or "MANUAL").strip(),
                    is_primary=is_primary,
                    is_enabled=bool(item.get("is_enabled", True)),
                    match_weight=int(item.get("match_weight") or 80),
                    remark=(str(item.get("remark")).strip() if item.get("remark") else None),
                    created_at=now,
                    updated_at=now,
                )
            )
        await self.db.flush()

    async def list_attributes(self, standard_id: int) -> list[tuple[CommodityStandardAttribute, CommodityAttributeDefinition | None]]:
        rows = (
            await self.db.execute(
                select(CommodityStandardAttribute, CommodityAttributeDefinition)
                .outerjoin(
                    CommodityAttributeDefinition,
                    CommodityAttributeDefinition.id == CommodityStandardAttribute.attribute_definition_id,
                )
                .where(CommodityStandardAttribute.commodity_standard_id == standard_id)
                .order_by(CommodityStandardAttribute.sort_order.asc(), CommodityStandardAttribute.id.asc())
            )
        ).all()
        return [(row[0], row[1]) for row in rows]

    async def replace_attributes(self, standard_id: int, attributes: list[dict[str, Any]]) -> None:
        await self.db.execute(
            delete(CommodityStandardAttribute).where(CommodityStandardAttribute.commodity_standard_id == standard_id)
        )
        now = datetime.utcnow()
        for item in attributes:
            self.db.add(
                CommodityStandardAttribute(
                    commodity_standard_id=standard_id,
                    attribute_definition_id=item.get("attribute_definition_id"),
                    attribute_code=item.get("attribute_code"),
                    attribute_name=item.get("attribute_name"),
                    attribute_value_type_code=item.get("attribute_value_type_code"),
                    attribute_unit=item.get("attribute_unit"),
                    attribute_value=item.get("attribute_value"),
                    is_required=bool(item.get("is_required", False)),
                    default_value=item.get("default_value"),
                    value_range_desc=item.get("value_range_desc"),
                    sort_order=int(item.get("sort_order", 0)),
                    created_at=now,
                    updated_at=now,
                )
            )
        await self.db.flush()

    async def replace_packaging_forms(self, standard_id: int, items: list[dict[str, Any]]) -> None:
        await self.db.execute(delete(CommodityPackagingForm).where(CommodityPackagingForm.commodity_standard_id == standard_id))
        now = datetime.utcnow()
        for item in items:
            code = str(item.get("code") or "").strip()
            if not code:
                continue
            self.db.add(
                CommodityPackagingForm(
                    commodity_standard_id=standard_id,
                    packaging_form_code=code,
                    is_default=bool(item.get("is_default", False)),
                    is_enabled=bool(item.get("is_enabled", True)),
                    remark=item.get("remark"),
                    created_at=now,
                )
            )
        await self.db.flush()

    async def replace_transport_modes(self, standard_id: int, items: list[dict[str, Any]]) -> None:
        await self.db.execute(delete(CommodityTransportMode).where(CommodityTransportMode.commodity_standard_id == standard_id))
        now = datetime.utcnow()
        for item in items:
            code = str(item.get("code") or "").strip()
            if not code:
                continue
            self.db.add(
                CommodityTransportMode(
                    commodity_standard_id=standard_id,
                    transport_mode_element_code=code,
                    is_default=bool(item.get("is_default", False)),
                    is_enabled=bool(item.get("is_enabled", True)),
                    remark=item.get("remark"),
                    created_at=now,
                )
            )
        await self.db.flush()

    async def replace_ship_type_rules(self, standard_id: int, items: list[dict[str, Any]]) -> None:
        await self.db.execute(delete(CommodityShipTypeRule).where(CommodityShipTypeRule.commodity_standard_id == standard_id))
        now = datetime.utcnow()
        for item in items:
            code = str(item.get("code") or "").strip()
            if not code:
                continue
            rule_type = str(item.get("rule_type_code") or "ALLOWED").strip()
            self.db.add(
                CommodityShipTypeRule(
                    commodity_standard_id=standard_id,
                    ship_type_code=code,
                    rule_type_code=rule_type,
                    priority=int(item.get("priority") or 50),
                    is_enabled=bool(item.get("is_enabled", True)),
                    allow_flag=rule_type != "FORBIDDEN",
                    rule_desc=item.get("rule_desc"),
                    created_at=now,
                )
            )
        await self.db.flush()

    async def replace_node_type_rules(self, standard_id: int, items: list[dict[str, Any]]) -> None:
        await self.db.execute(delete(CommodityNodeTypeRule).where(CommodityNodeTypeRule.commodity_standard_id == standard_id))
        now = datetime.utcnow()
        for item in items:
            code = str(item.get("code") or "").strip()
            if not code:
                continue
            rule_type = str(item.get("rule_type_code") or "ALLOWED").strip()
            self.db.add(
                CommodityNodeTypeRule(
                    commodity_standard_id=standard_id,
                    node_type_code=code,
                    operation_side_code=item.get("operation_side_code"),
                    rule_type_code=rule_type,
                    priority=int(item.get("priority") or 50),
                    is_enabled=bool(item.get("is_enabled", True)),
                    allow_flag=rule_type != "FORBIDDEN",
                    rule_desc=item.get("rule_desc"),
                    created_at=now,
                )
            )
        await self.db.flush()

    async def replace_handling_mode_rules(self, standard_id: int, items: list[dict[str, Any]]) -> None:
        await self.db.execute(delete(CommodityHandlingModeRule).where(CommodityHandlingModeRule.commodity_standard_id == standard_id))
        now = datetime.utcnow()
        for item in items:
            code = str(item.get("code") or "").strip()
            if not code:
                continue
            rule_type = str(item.get("rule_type_code") or "ALLOWED").strip()
            self.db.add(
                CommodityHandlingModeRule(
                    commodity_standard_id=standard_id,
                    handling_mode_code=code,
                    rule_type_code=rule_type,
                    priority=int(item.get("priority") or 50),
                    is_enabled=bool(item.get("is_enabled", True)),
                    allow_flag=rule_type != "FORBIDDEN",
                    rule_desc=item.get("rule_desc"),
                    created_at=now,
                )
            )
        await self.db.flush()

    async def list_packaging_forms(self, standard_id: int) -> list[CommodityPackagingForm]:
        return list(
            (
                await self.db.execute(
                    select(CommodityPackagingForm)
                    .where(CommodityPackagingForm.commodity_standard_id == standard_id)
                    .order_by(CommodityPackagingForm.is_default.desc(), CommodityPackagingForm.id.asc())
                )
            ).scalars().all()
        )

    async def list_transport_modes(self, standard_id: int) -> list[CommodityTransportMode]:
        return list(
            (
                await self.db.execute(
                    select(CommodityTransportMode)
                    .where(CommodityTransportMode.commodity_standard_id == standard_id)
                    .order_by(CommodityTransportMode.is_default.desc(), CommodityTransportMode.id.asc())
                )
            ).scalars().all()
        )

    async def list_ship_type_rules(self, standard_id: int) -> list[CommodityShipTypeRule]:
        return list(
            (
                await self.db.execute(
                    select(CommodityShipTypeRule)
                    .where(CommodityShipTypeRule.commodity_standard_id == standard_id)
                    .order_by(CommodityShipTypeRule.priority.desc(), CommodityShipTypeRule.id.asc())
                )
            ).scalars().all()
        )

    async def list_node_type_rules(self, standard_id: int) -> list[CommodityNodeTypeRule]:
        return list(
            (
                await self.db.execute(
                    select(CommodityNodeTypeRule)
                    .where(CommodityNodeTypeRule.commodity_standard_id == standard_id)
                    .order_by(CommodityNodeTypeRule.priority.desc(), CommodityNodeTypeRule.id.asc())
                )
            ).scalars().all()
        )

    async def list_handling_mode_rules(self, standard_id: int) -> list[CommodityHandlingModeRule]:
        return list(
            (
                await self.db.execute(
                    select(CommodityHandlingModeRule)
                    .where(CommodityHandlingModeRule.commodity_standard_id == standard_id)
                    .order_by(CommodityHandlingModeRule.priority.desc(), CommodityHandlingModeRule.id.asc())
                )
            ).scalars().all()
        )

    async def list_images(self, standard_id: int) -> list[tuple[CommodityStandardImage, StorageFile]]:
        rows = (
            await self.db.execute(
                select(CommodityStandardImage, StorageFile)
                .join(StorageFile, StorageFile.id == CommodityStandardImage.file_id)
                .where(CommodityStandardImage.commodity_standard_id == standard_id)
                .order_by(CommodityStandardImage.is_primary.desc(), CommodityStandardImage.sort_order.asc(), CommodityStandardImage.id.asc())
            )
        ).all()
        return [(row[0], row[1]) for row in rows]

    async def get_image_with_file(self, image_id: int) -> tuple[CommodityStandardImage, StorageFile] | None:
        row = (
            await self.db.execute(
                select(CommodityStandardImage, StorageFile)
                .join(StorageFile, StorageFile.id == CommodityStandardImage.file_id)
                .where(CommodityStandardImage.id == image_id)
            )
        ).first()
        if row is None:
            return None
        return row[0], row[1]

    async def create_image(self, data: dict[str, Any]) -> CommodityStandardImage:
        entity = CommodityStandardImage(**data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def update_image(self, image_id: int, data: dict[str, Any]) -> CommodityStandardImage | None:
        entity = await self.db.scalar(select(CommodityStandardImage).where(CommodityStandardImage.id == image_id))
        if entity is None:
            return None
        for key, value in data.items():
            setattr(entity, key, value)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def clear_primary_images(self, standard_id: int, except_image_id: int | None = None) -> None:
        stmt = select(CommodityStandardImage).where(CommodityStandardImage.commodity_standard_id == standard_id)
        rows = (await self.db.execute(stmt)).scalars().all()
        for row in rows:
            if except_image_id is not None and row.id == except_image_id:
                continue
            row.is_primary = False
        await self.db.flush()

    async def delete_image(self, image_id: int) -> bool:
        entity = await self.db.scalar(select(CommodityStandardImage).where(CommodityStandardImage.id == image_id))
        if entity is None:
            return False
        await self.db.delete(entity)
        await self.db.flush()
        return True
