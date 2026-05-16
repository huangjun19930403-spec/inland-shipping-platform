"""Live master-data context for commodity recognition."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.commodity.recognition.repository import CommodityRecognitionRepository
from app.modules.dictionary.labels import dict_label, load_dict_label_map

CONTEXT_DICT_CODES = [
    "COMMODITY_UNIT",
    "COMMODITY_CARGO_FORM",
    "DANGEROUS_GOODS_LEVEL",
    "POLLUTION_RISK_LEVEL",
    "PACKAGING_FORM",
    "TRANSPORT_MODE_ELEMENT",
    "SHIP_TYPE",
    "NODE_TYPE",
    "HANDLING_MODE",
    "COMMODITY_RULE_TYPE",
    "COMMODITY_OPERATION_SIDE",
    "COMMODITY_ATTRIBUTE_GROUP",
    "VALUE_TYPE",
]


@dataclass(frozen=True)
class CommodityRecognitionContext:
    categories: list[dict[str, Any]]
    types: list[dict[str, Any]]
    dict_items: dict[str, list[dict[str, Any]]]
    attribute_definitions: list[dict[str, Any]]

    def packaging_terms(self) -> set[str]:
        return {item["item_name"] for item in self.dict_items.get("PACKAGING_FORM", [])}

    def default_code(self, dict_code: str, fallback: str = "") -> str:
        options = self.dict_items.get(dict_code, [])
        for item in options:
            if item.get("is_default"):
                return str(item.get("item_code") or fallback)
        return str(options[0].get("item_code")) if options else fallback

    def label(self, dict_code: str, item_code: str | None) -> str | None:
        for item in self.dict_items.get(dict_code, []):
            if item.get("item_code") == item_code:
                return str(item.get("item_name"))
        return None

    def type_by_id(self, type_id: int | None) -> dict[str, Any] | None:
        if type_id is None:
            return None
        return next((item for item in self.types if int(item["id"]) == int(type_id)), None)

    def category_by_id(self, category_id: int | None) -> dict[str, Any] | None:
        if category_id is None:
            return None
        return next((item for item in self.categories if int(item["id"]) == int(category_id)), None)

    def compact_for_ai(
        self,
        *,
        category_hint_id: int | None = None,
        type_hint_id: int | None = None,
        limit_per_group: int = 60,
    ) -> dict[str, Any]:
        type_hint = self.type_by_id(type_hint_id)
        category_id = category_hint_id or (type_hint.get("category_id") if type_hint else None)
        types = [item for item in self.types if not category_id or int(item["category_id"]) == int(category_id)]
        return {
            "categories": self.categories[:limit_per_group],
            "types": types[:limit_per_group],
            "dict_items": {
                key: values[:limit_per_group]
                for key, values in self.dict_items.items()
                if key in {
                    "COMMODITY_UNIT",
                    "COMMODITY_CARGO_FORM",
                    "DANGEROUS_GOODS_LEVEL",
                    "POLLUTION_RISK_LEVEL",
                    "PACKAGING_FORM",
                    "TRANSPORT_MODE_ELEMENT",
                }
            },
            "attribute_definitions": self.attribute_definitions[:limit_per_group],
        }


class CommodityRecognitionContextBuilder:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = CommodityRecognitionRepository(db)

    async def build(self) -> CommodityRecognitionContext:
        categories, types = await self.repo.list_categories_and_types()
        raw_items = await self.repo.list_dict_items(CONTEXT_DICT_CODES)
        labels = await load_dict_label_map(self.db, CONTEXT_DICT_CODES)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in raw_items:
            grouped[item.dict_code].append(
                {
                    "item_code": item.item_code,
                    "item_name": item.item_name,
                    "is_default": item.is_default,
                    "sort_order": item.sort_order,
                }
            )
        definitions = []
        for item in await self.repo.list_attribute_definitions():
            definitions.append(
                {
                    **item,
                    "attribute_group_name": dict_label(labels, "COMMODITY_ATTRIBUTE_GROUP", item.get("attribute_group_code")),
                    "value_type_name": dict_label(labels, "VALUE_TYPE", item.get("value_type_code")),
                    "unit_name": dict_label(labels, "COMMODITY_UNIT", item.get("unit_code")),
                }
            )
        return CommodityRecognitionContext(
            categories=categories,
            types=types,
            dict_items=dict(grouped),
            attribute_definitions=definitions,
        )
