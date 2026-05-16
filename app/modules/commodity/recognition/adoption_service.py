"""Adoption transactions for commodity recognition suggestions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.modules.commodity.recognition.repository import CommodityRecognitionRepository
from app.modules.commodity.recognition.schemas import (
    CommodityRecognitionAliasAdoptRequest,
    CommodityRecognitionStandardAdoptRequest,
)
from app.modules.dictionary.service import CodeSequenceService


class CommodityRecognitionAdoptionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = CommodityRecognitionRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def adopt_alias(
        self,
        recognition_id: int,
        payload: CommodityRecognitionAliasAdoptRequest,
        *,
        operator_id: int | None,
    ) -> tuple[int, int | None]:
        record = await self.repo.get_record(recognition_id)
        if record is None:
            raise NotFoundError("CommodityRecognitionRecord", recognition_id)
        if record.adopted_action_code:
            raise ConflictError("该识别记录已采纳")
        standard = await self.repo.get_standard(payload.standard_id)
        if standard is None:
            raise NotFoundError("CommodityStandard", payload.standard_id)

        alias_name = (payload.alias_name or record.raw_name or "").strip()
        if not alias_name:
            raise ValidationError("别名不能为空")

        existing_alias = await self.repo.get_alias_by_name(alias_name)
        alias_id: int | None = None
        if existing_alias is not None:
            if int(existing_alias.commodity_standard_id) != int(payload.standard_id):
                raise ConflictError(f"别名已属于其他标准货品：{alias_name}")
            alias_id = int(existing_alias.id)
        elif alias_name.strip().lower() == (standard.name or "").strip().lower():
            alias_id = None
        else:
            now = datetime.utcnow()
            alias = await self.repo.create_alias(
                {
                    "commodity_standard_id": payload.standard_id,
                    "alias_name": alias_name,
                    "alias_type_code": payload.alias_type_code.strip() or "AI_KEYWORD",
                    "source_type_code": "AI_RECOGNITION",
                    "is_primary": False,
                    "is_enabled": True,
                    "match_weight": payload.match_weight,
                    "remark": payload.remark.strip() if payload.remark else f"来自货品 AI 识别记录 {recognition_id}",
                    "created_at": now,
                    "updated_at": now,
                }
            )
            alias_id = int(alias.id)

        await self.repo.update_record(
            recognition_id,
            {
                "adopted_action_code": "ADOPT_ALIAS",
                "adopted_standard_id": int(payload.standard_id),
                "adopted_alias_id": alias_id,
                "adopted_by_id": operator_id,
                "adopted_at": datetime.utcnow(),
            },
        )
        await self.db.commit()
        return int(payload.standard_id), alias_id

    async def adopt_standard(
        self,
        recognition_id: int,
        payload: CommodityRecognitionStandardAdoptRequest,
        *,
        operator_id: int | None,
    ) -> int:
        record = await self.repo.get_record(recognition_id)
        if record is None:
            raise NotFoundError("CommodityRecognitionRecord", recognition_id)
        if record.adopted_action_code:
            raise ConflictError("该识别记录已采纳")

        await self._validate_taxonomy(payload.category_id, payload.type_id)
        existing_standard = await self.repo.get_standard_by_name(payload.name.strip())
        if existing_standard is not None:
            raise ConflictError(f"标准货品名称已存在：{payload.name.strip()}")

        alias_names = self._alias_names(record.raw_name, payload.aliases, payload.name)
        for alias_name in alias_names:
            alias = await self.repo.get_alias_by_name(alias_name)
            if alias is not None:
                raise ConflictError(f"别名已存在：{alias_name}")

        standard_data = payload.model_dump(
            exclude={
                "aliases",
                "attributes",
                "packaging_forms",
                "transport_modes",
                "ship_type_rules",
                "node_type_rules",
                "handling_mode_rules",
            },
            exclude_none=True,
        )
        standard_data.update(
            {
                "name": payload.name.strip(),
                "code": await self.sequence_service.next_code("COMMODITY_STANDARD_CODE"),
                "source_type_code": "AI_RECOGNITION",
                "is_active": True,
            }
        )
        standard = await self.repo.create_standard(standard_data)
        standard_id = int(standard.id)
        now = datetime.utcnow()
        for index, alias_name in enumerate(alias_names):
            await self.repo.create_alias(
                {
                    "commodity_standard_id": standard_id,
                    "alias_name": alias_name,
                    "alias_type_code": "AI_KEYWORD" if index == 0 else "COMMON_NAME",
                    "source_type_code": "AI_RECOGNITION",
                    "is_primary": index == 0,
                    "is_enabled": True,
                    "match_weight": 88 if index == 0 else 80,
                    "remark": f"来自货品 AI 识别记录 {recognition_id}",
                    "created_at": now,
                    "updated_at": now,
                }
            )

        await self.repo.add_attributes(standard_id, await self._attribute_rows(payload.attributes))
        await self.repo.add_default_rules(
            standard_id,
            "PACKAGING_FORM",
            self._default_rule_rows([item.model_dump() for item in payload.packaging_forms]),
        )
        await self.repo.add_default_rules(
            standard_id,
            "TRANSPORT_MODE_ELEMENT",
            self._default_rule_rows([item.model_dump() for item in payload.transport_modes]),
        )
        await self.repo.add_decision_rules(
            standard_id,
            "SHIP_TYPE",
            self._decision_rule_rows([item.model_dump() for item in payload.ship_type_rules]),
        )
        await self.repo.add_decision_rules(
            standard_id,
            "NODE_TYPE",
            self._decision_rule_rows([item.model_dump() for item in payload.node_type_rules]),
        )
        await self.repo.add_decision_rules(
            standard_id,
            "HANDLING_MODE",
            self._decision_rule_rows([item.model_dump() for item in payload.handling_mode_rules]),
        )
        await self.repo.update_record(
            recognition_id,
            {
                "adopted_action_code": "ADOPT_STANDARD",
                "adopted_standard_id": standard_id,
                "adopted_by_id": operator_id,
                "adopted_at": datetime.utcnow(),
            },
        )
        await self.db.commit()
        return standard_id

    async def _validate_taxonomy(self, category_id: int, type_id: int) -> None:
        category = await self.repo.get_category(category_id)
        if category is None:
            raise ValidationError("货品分类不存在或已停用")
        commodity_type = await self.repo.get_type(type_id)
        if commodity_type is None:
            raise ValidationError("货品类型不存在或已停用")
        if int(commodity_type.category_id) != int(category_id):
            raise ValidationError("货品类型不属于所选货品分类")

    async def _attribute_rows(self, attributes) -> list[dict[str, Any]]:
        definitions = {int(item["id"]): item for item in await self.repo.list_attribute_definitions()}
        rows: list[dict[str, Any]] = []
        seen: set[int] = set()
        for index, item in enumerate(attributes):
            definition_id = item.attribute_definition_id
            if not definition_id:
                continue
            if int(definition_id) in seen:
                continue
            definition = definitions.get(int(definition_id))
            if definition is None:
                continue
            seen.add(int(definition_id))
            rows.append(
                {
                    "attribute_definition_id": int(definition_id),
                    "attribute_code": definition["attribute_code"],
                    "attribute_name": definition["attribute_name"],
                    "attribute_value_type_code": definition["value_type_code"],
                    "attribute_unit": definition.get("unit_code"),
                    "attribute_value": (item.attribute_value or "").strip() or None,
                    "is_required": bool(definition.get("is_required_default")),
                    "sort_order": index,
                }
            )
        return rows

    @staticmethod
    def _alias_names(raw_name: str, suggested_aliases: list[str], standard_name: str) -> list[str]:
        result: list[str] = []
        for value in [raw_name, *suggested_aliases]:
            cleaned = (value or "").strip()
            if not cleaned or cleaned == standard_name:
                continue
            if cleaned.lower() not in {item.lower() for item in result}:
                result.append(cleaned)
        return result

    @staticmethod
    def _default_rule_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, item in enumerate(items):
            code = str(item.get("code") or "").strip()
            if not code or code in seen:
                continue
            seen.add(code)
            rows.append(
                {
                    "code": code,
                    "is_default": bool(item.get("is_default", False)) or index == 0,
                    "is_enabled": bool(item.get("is_enabled", True)),
                    "remark": item.get("remark"),
                }
            )
        if rows and not any(item["is_default"] for item in rows):
            rows[0]["is_default"] = True
        return rows

    @staticmethod
    def _decision_rule_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, str | None]] = set()
        for item in items:
            code = str(item.get("code") or "").strip()
            side = str(item.get("operation_side_code") or "").strip() or None
            key = (code, side)
            if not code or key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "code": code,
                    "rule_type_code": str(item.get("rule_type_code") or "ALLOWED").strip(),
                    "priority": int(item.get("priority") or 50),
                    "operation_side_code": side,
                    "is_enabled": bool(item.get("is_enabled", True)),
                    "rule_desc": item.get("rule_desc"),
                }
            )
        return rows
