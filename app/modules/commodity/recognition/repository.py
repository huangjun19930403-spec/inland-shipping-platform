"""Repository helpers for standard commodity recognition.

The recognition module reads the live master-data tables. It never reads seed
files at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commodity import (
    CommodityAlias,
    CommodityAttributeDefinition,
    CommodityCategory,
    CommodityHandlingModeRule,
    CommodityNodeTypeRule,
    CommodityPackagingForm,
    CommodityRecognitionRecord,
    CommodityShipTypeRule,
    CommodityStandard,
    CommodityStandardAttribute,
    CommodityTransportMode,
    CommodityType,
)
from app.models.dictionary import StdDict, StdDictItem


@dataclass(frozen=True)
class CommodityAliasMatchRow:
    id: int
    alias_name: str
    alias_type_code: str
    match_weight: int
    is_enabled: bool


@dataclass(frozen=True)
class CommodityStandardMatchRow:
    id: int
    code: str
    name: str
    short_name: str | None
    english_name: str | None
    category_id: int | None
    category_name: str | None
    type_id: int
    type_name: str | None
    main_unit_code: str
    cargo_form_code: str | None
    is_bulk_cargo: bool
    is_container_suitable: bool
    is_hazardous: bool
    pollution_risk_level_code: str | None
    recognition_priority: int
    aliases: tuple[CommodityAliasMatchRow, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CommodityDictItemRow:
    dict_code: str
    item_code: str
    item_name: str
    is_default: bool
    sort_order: int


class CommodityRecognitionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_record(self, data: dict[str, Any]) -> CommodityRecognitionRecord:
        entity = CommodityRecognitionRecord(**data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def get_record(self, recognition_id: int) -> CommodityRecognitionRecord | None:
        return await self.db.scalar(
            select(CommodityRecognitionRecord).where(CommodityRecognitionRecord.id == recognition_id)
        )

    async def update_record(self, recognition_id: int, data: dict[str, Any]) -> CommodityRecognitionRecord | None:
        entity = await self.get_record(recognition_id)
        if entity is None:
            return None
        for key, value in data.items():
            setattr(entity, key, value)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def list_match_rows(self) -> list[CommodityStandardMatchRow]:
        category_id_expr = func.coalesce(CommodityStandard.category_id, CommodityType.category_id)
        standard_rows = (
            await self.db.execute(
                select(CommodityStandard, CommodityType, CommodityCategory)
                .join(CommodityType, CommodityType.id == CommodityStandard.type_id)
                .outerjoin(CommodityCategory, CommodityCategory.id == category_id_expr)
                .where(
                    CommodityStandard.deleted_at.is_(None),
                    CommodityStandard.is_active.is_(True),
                    CommodityType.deleted_at.is_(None),
                )
                .order_by(CommodityStandard.recognition_priority.desc(), CommodityStandard.id.asc())
            )
        ).all()
        standard_ids = [int(row[0].id) for row in standard_rows]
        alias_rows: dict[int, list[CommodityAliasMatchRow]] = {standard_id: [] for standard_id in standard_ids}
        if standard_ids:
            aliases = (
                await self.db.execute(
                    select(CommodityAlias)
                    .where(
                        CommodityAlias.commodity_standard_id.in_(standard_ids),
                        CommodityAlias.is_enabled.is_(True),
                    )
                    .order_by(CommodityAlias.match_weight.desc(), CommodityAlias.id.asc())
                )
            ).scalars().all()
            for alias in aliases:
                alias_rows.setdefault(int(alias.commodity_standard_id), []).append(
                    CommodityAliasMatchRow(
                        id=int(alias.id),
                        alias_name=alias.alias_name,
                        alias_type_code=alias.alias_type_code,
                        match_weight=int(alias.match_weight or 0),
                        is_enabled=bool(alias.is_enabled),
                    )
                )

        rows: list[CommodityStandardMatchRow] = []
        for standard, commodity_type, category in standard_rows:
            rows.append(
                CommodityStandardMatchRow(
                    id=int(standard.id),
                    code=standard.code,
                    name=standard.name,
                    short_name=standard.short_name,
                    english_name=standard.english_name,
                    category_id=int(category.id) if category is not None else None,
                    category_name=category.name if category is not None else None,
                    type_id=int(commodity_type.id),
                    type_name=commodity_type.name,
                    main_unit_code=standard.main_unit_code,
                    cargo_form_code=standard.cargo_form_code,
                    is_bulk_cargo=bool(standard.is_bulk_cargo),
                    is_container_suitable=bool(standard.is_container_suitable),
                    is_hazardous=bool(standard.is_hazardous),
                    pollution_risk_level_code=standard.pollution_risk_level_code,
                    recognition_priority=int(standard.recognition_priority or 0),
                    aliases=tuple(alias_rows.get(int(standard.id), [])),
                )
            )
        return rows

    async def list_categories_and_types(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        categories = (
            await self.db.execute(
                select(CommodityCategory)
                .where(CommodityCategory.deleted_at.is_(None))
                .order_by(CommodityCategory.sort_order.asc(), CommodityCategory.id.asc())
            )
        ).scalars().all()
        types = (
            await self.db.execute(
                select(CommodityType)
                .where(CommodityType.deleted_at.is_(None))
                .order_by(CommodityType.sort_order.asc(), CommodityType.id.asc())
            )
        ).scalars().all()
        return (
            [
                {"id": int(item.id), "code": item.code, "name": item.name, "sort_order": item.sort_order}
                for item in categories
            ],
            [
                {
                    "id": int(item.id),
                    "category_id": int(item.category_id),
                    "code": item.code,
                    "name": item.name,
                    "sort_order": item.sort_order,
                }
                for item in types
            ],
        )

    async def list_dict_items(self, dict_codes: list[str]) -> list[CommodityDictItemRow]:
        if not dict_codes:
            return []
        rows = (
            await self.db.execute(
                select(StdDict.dict_code, StdDictItem.item_code, StdDictItem.item_name, StdDictItem.is_default, StdDictItem.sort_order)
                .join(StdDictItem, StdDictItem.dict_id == StdDict.id)
                .where(StdDict.dict_code.in_(dict_codes), StdDict.status == 1, StdDictItem.status == 1)
                .order_by(StdDict.dict_code.asc(), StdDictItem.sort_order.asc(), StdDictItem.id.asc())
            )
        ).all()
        return [
            CommodityDictItemRow(
                dict_code=row[0],
                item_code=row[1],
                item_name=row[2],
                is_default=bool(row[3]),
                sort_order=int(row[4] or 0),
            )
            for row in rows
        ]

    async def list_attribute_definitions(self) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(CommodityAttributeDefinition)
                .where(CommodityAttributeDefinition.is_enabled.is_(True))
                .order_by(CommodityAttributeDefinition.sort_order.asc(), CommodityAttributeDefinition.id.asc())
            )
        ).scalars().all()
        return [
            {
                "id": int(item.id),
                "attribute_code": item.attribute_code,
                "attribute_name": item.attribute_name,
                "attribute_group_code": item.attribute_group_code,
                "value_type_code": item.value_type_code,
                "unit_code": item.unit_code,
                "option_dict_code": item.option_dict_code,
                "description": item.description,
                "is_required_default": bool(item.is_required_default),
                "sort_order": int(item.sort_order or 0),
            }
            for item in rows
        ]

    async def attribute_suggestions(self, standard_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
        if not standard_ids:
            return {}
        rows = (
            await self.db.execute(
                select(CommodityStandardAttribute, CommodityAttributeDefinition)
                .outerjoin(
                    CommodityAttributeDefinition,
                    CommodityAttributeDefinition.id == CommodityStandardAttribute.attribute_definition_id,
                )
                .where(CommodityStandardAttribute.commodity_standard_id.in_(standard_ids))
                .order_by(CommodityStandardAttribute.sort_order.asc(), CommodityStandardAttribute.id.asc())
            )
        ).all()
        result: dict[int, list[dict[str, Any]]] = {standard_id: [] for standard_id in standard_ids}
        for attr, definition in rows:
            result.setdefault(int(attr.commodity_standard_id), []).append(
                {
                    "attribute_definition_id": attr.attribute_definition_id,
                    "attribute_code": definition.attribute_code if definition is not None else attr.attribute_code,
                    "attribute_name": definition.attribute_name if definition is not None else attr.attribute_name,
                    "attribute_value": attr.attribute_value or attr.default_value,
                    "unit_code": definition.unit_code if definition is not None else attr.attribute_unit,
                    "confidence_score": 80,
                    "reason": "来自已有标准货品属性",
                }
            )
        return result

    async def capability_counts(self, standard_ids: list[int]) -> dict[int, dict[str, int]]:
        result = {
            standard_id: {"packaging": 0, "transport": 0, "ship": 0, "node": 0, "handling": 0}
            for standard_id in standard_ids
        }
        if not standard_ids:
            return result

        async def _counts(model, column, key: str) -> None:
            rows = (
                await self.db.execute(
                    select(column, func.count(model.id)).where(column.in_(standard_ids)).group_by(column)
                )
            ).all()
            for row in rows:
                result.setdefault(int(row[0]), {})[key] = int(row[1] or 0)

        await _counts(CommodityPackagingForm, CommodityPackagingForm.commodity_standard_id, "packaging")
        await _counts(CommodityTransportMode, CommodityTransportMode.commodity_standard_id, "transport")
        await _counts(CommodityShipTypeRule, CommodityShipTypeRule.commodity_standard_id, "ship")
        await _counts(CommodityNodeTypeRule, CommodityNodeTypeRule.commodity_standard_id, "node")
        await _counts(CommodityHandlingModeRule, CommodityHandlingModeRule.commodity_standard_id, "handling")
        return result

    async def get_standard(self, standard_id: int) -> CommodityStandard | None:
        return await self.db.scalar(
            select(CommodityStandard).where(CommodityStandard.id == standard_id, CommodityStandard.deleted_at.is_(None))
        )

    async def get_standard_by_name(self, name: str) -> CommodityStandard | None:
        return await self.db.scalar(
            select(CommodityStandard).where(
                func.lower(CommodityStandard.name) == name.lower(),
                CommodityStandard.deleted_at.is_(None),
            )
        )

    async def get_standard_snapshot(self, standard_id: int) -> dict[str, Any] | None:
        category_id_expr = func.coalesce(CommodityStandard.category_id, CommodityType.category_id)
        row = (
            await self.db.execute(
                select(CommodityStandard, CommodityType, CommodityCategory)
                .join(CommodityType, CommodityType.id == CommodityStandard.type_id)
                .outerjoin(CommodityCategory, CommodityCategory.id == category_id_expr)
                .where(CommodityStandard.id == standard_id, CommodityStandard.deleted_at.is_(None))
            )
        ).first()
        if row is None:
            return None
        standard, commodity_type, category = row
        return {
            "id": int(standard.id),
            "code": standard.code,
            "name": standard.name,
            "category_id": int(category.id) if category is not None else None,
            "category_name": category.name if category is not None else None,
            "type_id": int(commodity_type.id),
            "type_name": commodity_type.name,
        }

    async def get_type(self, type_id: int) -> CommodityType | None:
        return await self.db.scalar(
            select(CommodityType).where(CommodityType.id == type_id, CommodityType.deleted_at.is_(None))
        )

    async def get_category(self, category_id: int) -> CommodityCategory | None:
        return await self.db.scalar(
            select(CommodityCategory).where(CommodityCategory.id == category_id, CommodityCategory.deleted_at.is_(None))
        )

    async def get_alias_by_standard_name(self, standard_id: int, alias_name: str) -> CommodityAlias | None:
        return await self.db.scalar(
            select(CommodityAlias).where(
                CommodityAlias.commodity_standard_id == standard_id,
                func.lower(CommodityAlias.alias_name) == alias_name.lower(),
            )
        )

    async def get_alias_by_name(self, alias_name: str) -> CommodityAlias | None:
        return await self.db.scalar(
            select(CommodityAlias).where(func.lower(CommodityAlias.alias_name) == alias_name.lower())
        )

    async def create_alias(self, data: dict[str, Any]) -> CommodityAlias:
        entity = CommodityAlias(**data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def create_standard(self, data: dict[str, Any]) -> CommodityStandard:
        entity = CommodityStandard(**data)
        self.db.add(entity)
        await self.db.flush()
        await self.db.refresh(entity)
        return entity

    async def add_attributes(self, standard_id: int, attributes: list[dict[str, Any]]) -> None:
        now = datetime.utcnow()
        for index, item in enumerate(attributes):
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
                    sort_order=int(item.get("sort_order", index)),
                    created_at=now,
                    updated_at=now,
                )
            )
        await self.db.flush()

    async def add_default_rules(self, standard_id: int, rule_kind: str, items: list[dict[str, Any]]) -> None:
        now = datetime.utcnow()
        for item in items:
            code = str(item.get("code") or "").strip()
            if not code:
                continue
            common = {
                "commodity_standard_id": standard_id,
                "is_default": bool(item.get("is_default", False)),
                "is_enabled": bool(item.get("is_enabled", True)),
                "remark": item.get("remark"),
                "created_at": now,
            }
            if rule_kind == "PACKAGING_FORM":
                self.db.add(CommodityPackagingForm(packaging_form_code=code, **common))
            elif rule_kind == "TRANSPORT_MODE_ELEMENT":
                self.db.add(CommodityTransportMode(transport_mode_element_code=code, **common))
        await self.db.flush()

    async def add_decision_rules(self, standard_id: int, rule_kind: str, items: list[dict[str, Any]]) -> None:
        now = datetime.utcnow()
        for item in items:
            code = str(item.get("code") or "").strip()
            if not code:
                continue
            rule_type = str(item.get("rule_type_code") or "ALLOWED").strip()
            common = {
                "commodity_standard_id": standard_id,
                "rule_type_code": rule_type,
                "priority": int(item.get("priority") or 50),
                "is_enabled": bool(item.get("is_enabled", True)),
                "allow_flag": rule_type != "FORBIDDEN",
                "rule_desc": item.get("rule_desc"),
                "created_at": now,
            }
            if rule_kind == "SHIP_TYPE":
                self.db.add(CommodityShipTypeRule(ship_type_code=code, **common))
            elif rule_kind == "NODE_TYPE":
                self.db.add(
                    CommodityNodeTypeRule(
                        node_type_code=code,
                        operation_side_code=item.get("operation_side_code"),
                        **common,
                    )
                )
            elif rule_kind == "HANDLING_MODE":
                self.db.add(CommodityHandlingModeRule(handling_mode_code=code, **common))
        await self.db.flush()
