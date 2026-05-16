"""生产标准货品、别名和装卸规则初始化脚本。"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.commodity import (
    CommodityAlias,
    CommodityAttributeDefinition,
    CommodityHandlingModeRule,
    CommodityNodeTypeRule,
    CommodityPackagingForm,
    CommodityShipTypeRule,
    CommodityStandard,
    CommodityStandardAttribute,
    CommodityTransportMode,
    CommodityType,
)


COMMODITY_STANDARD_FILE = (
    Path(__file__).resolve().parents[2]
    / "seed_data"
    / "commodity"
    / "commodity_standards.json"
)

ATTRIBUTE_DEFINITION_SEEDS = [
    {
        "attribute_code": "REFERENCE_DENSITY",
        "attribute_name": "参考密度",
        "attribute_group_code": "PHYSICAL",
        "value_type_code": "STRING",
        "unit_code": "TON",
        "description": "用于分析与估算的参考密度或堆密度描述。",
        "sort_order": 10,
    },
    {
        "attribute_code": "MOISTURE_REQUIREMENT",
        "attribute_name": "含水/防潮要求",
        "attribute_group_code": "QUALITY",
        "value_type_code": "STRING",
        "description": "货品含水率、防潮、防雨等质量和运输要求。",
        "sort_order": 20,
    },
    {
        "attribute_code": "PARTICLE_SIZE",
        "attribute_name": "粒径/规格",
        "attribute_group_code": "PHYSICAL",
        "value_type_code": "STRING",
        "description": "砂石、矿石、煤炭等散货的粒径、等级、牌号等规格。",
        "sort_order": 30,
    },
    {
        "attribute_code": "POLLUTION_CONTROL",
        "attribute_name": "环保控制要求",
        "attribute_group_code": "SAFETY",
        "value_type_code": "STRING",
        "description": "扬尘、泄漏、污染和危化相关控制要求。",
        "sort_order": 40,
    },
    {
        "attribute_code": "PRICE_ANALYSIS_TAG",
        "attribute_name": "价格分析标签",
        "attribute_group_code": "BUSINESS",
        "value_type_code": "STRING",
        "description": "用于报价模拟和价格分析的业务标签。",
        "sort_order": 50,
    },
]


def _load_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _unit_code(row: dict, fallback: str = "TON") -> str:
    raw = str(row.get("main_unit_code") or row.get("main_unit") or fallback).strip()
    return {
        "吨": "TON",
        "立方米": "CUBIC_METER",
        "件": "PIECE",
        "箱": "BOX",
        "车": "TRUCK",
        "船次": "VOYAGE",
    }.get(raw, raw or fallback)


def _default_rule_items(row: dict, key: str) -> list[dict]:
    raw_items = row.get(key) or []
    items: list[dict] = []
    seen_codes: set[str] = set()
    explicit_default = False
    for index, raw in enumerate(raw_items):
        if isinstance(raw, str):
            code = raw.strip()
            is_default = index == 0
        else:
            code = str(raw.get("code") or "").strip()
            is_default = bool(raw.get("is_default", False))
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        if is_default:
            explicit_default = True
        items.append({"code": code, "is_default": is_default})
    if items and not explicit_default:
        items[0]["is_default"] = True
    return items


def _decision_rule_items(row: dict, key: str) -> list[dict]:
    raw_items = row.get(key) or []
    items: list[dict] = []
    seen_codes: set[str] = set()
    for raw in raw_items:
        if isinstance(raw, str):
            code = raw.strip()
            allow_flag = True
            rule_desc = None
        else:
            code = str(raw.get("code") or "").strip()
            rule_type_code = str(raw.get("rule_type_code") or "").strip()
            allow_flag = bool(raw.get("allow_flag", rule_type_code != "FORBIDDEN"))
            rule_desc = raw.get("rule_desc")
            operation_side_code = raw.get("operation_side_code")
            priority = int(raw.get("priority") or 50)
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        items.append(
            {
                "code": code,
                "allow_flag": allow_flag,
                "rule_type_code": rule_type_code or ("ALLOWED" if allow_flag else "FORBIDDEN"),
                "operation_side_code": operation_side_code,
                "priority": priority if not isinstance(raw, str) else 50,
                "rule_desc": rule_desc,
            }
        )
    return items


async def _seed_attribute_definitions(session) -> dict[str, CommodityAttributeDefinition]:
    result: dict[str, CommodityAttributeDefinition] = {}
    for row in ATTRIBUTE_DEFINITION_SEEDS:
        code = row["attribute_code"]
        entity = await session.scalar(
            select(CommodityAttributeDefinition).where(CommodityAttributeDefinition.attribute_code == code)
        )
        if entity is None:
            entity = CommodityAttributeDefinition(**row, is_required_default=False, is_enabled=True)
            session.add(entity)
            await session.flush()
        else:
            for key, value in row.items():
                setattr(entity, key, value)
            entity.is_enabled = True
        result[code] = entity
    return result


async def seed_commodity_standards() -> None:
    standards = _load_json(COMMODITY_STANDARD_FILE)
    if not standards:
        return

    async with AsyncSessionLocal() as session:
        attribute_definitions = await _seed_attribute_definitions(session)
        for row in standards:
            code = str(row.get("code") or "").strip()
            type_code = str(row.get("type_code") or "").strip()
            name = str(row.get("name") or "").strip()
            if not code or not type_code or not name:
                continue

            commodity_type = await session.scalar(
                select(CommodityType).where(
                    CommodityType.code == type_code,
                    CommodityType.deleted_at.is_(None),
                )
            )
            if commodity_type is None:
                continue

            entity = await session.scalar(
                select(CommodityStandard).where(CommodityStandard.code == code)
            )
            if entity is None:
                entity = CommodityStandard(
                    category_id=commodity_type.category_id,
                    type_id=commodity_type.id,
                    code=code,
                    name=name,
                    short_name=row.get("short_name"),
                    english_name=row.get("english_name"),
                    main_unit_code=_unit_code(row),
                    specification=row.get("specification"),
                    cargo_form_code=row.get("cargo_form_code"),
                    density_range_desc=row.get("density_range_desc"),
                    dangerous_grade_code=row.get("dangerous_grade_code"),
                    is_bulk_cargo=bool(row.get("is_bulk_cargo", True)),
                    is_container_suitable=bool(row.get("is_container_suitable", False)),
                    is_hazardous=bool(row.get("is_hazardous", False)),
                    pollution_risk_level_code=row.get("pollution_risk_level_code"),
                    loading_requirement=row.get("loading_requirement"),
                    unloading_requirement=row.get("unloading_requirement"),
                    storage_requirement=row.get("storage_requirement"),
                    source_type_code=row.get("source_type_code") or "SYSTEM",
                    recognition_priority=int(row.get("recognition_priority") or 50),
                    remark=row.get("remark"),
                    is_active=bool(row.get("is_active", True)),
                )
                session.add(entity)
                await session.flush()
            else:
                entity.category_id = commodity_type.category_id
                entity.type_id = commodity_type.id
                entity.name = name
                entity.short_name = row.get("short_name")
                entity.english_name = row.get("english_name")
                entity.main_unit_code = _unit_code(row, entity.main_unit_code)
                entity.specification = row.get("specification")
                entity.cargo_form_code = row.get("cargo_form_code")
                entity.density_range_desc = row.get("density_range_desc")
                entity.dangerous_grade_code = row.get("dangerous_grade_code")
                entity.is_bulk_cargo = bool(row.get("is_bulk_cargo", True))
                entity.is_container_suitable = bool(row.get("is_container_suitable", False))
                entity.is_hazardous = bool(row.get("is_hazardous", False))
                entity.pollution_risk_level_code = row.get("pollution_risk_level_code")
                entity.loading_requirement = row.get("loading_requirement")
                entity.unloading_requirement = row.get("unloading_requirement")
                entity.storage_requirement = row.get("storage_requirement")
                entity.source_type_code = row.get("source_type_code") or "SYSTEM"
                entity.recognition_priority = int(row.get("recognition_priority") or 50)
                entity.remark = row.get("remark")
                entity.is_active = bool(row.get("is_active", True))
                entity.deleted_at = None
                await session.flush()
            entity.audit_status = "APPROVED"

            await session.execute(
                delete(CommodityAlias).where(
                    CommodityAlias.commodity_standard_id == entity.id
                )
            )
            aliases = row.get("aliases") or []
            deduped_aliases: list[dict] = []
            for alias in [name, row.get("short_name"), *aliases]:
                if isinstance(alias, dict):
                    alias_name = str(alias.get("alias_name") or "").strip()
                    alias_payload = {
                        "alias_name": alias_name,
                        "alias_type_code": alias.get("alias_type_code") or "COMMON_NAME",
                        "source_type_code": alias.get("source_type_code") or "SYSTEM",
                        "is_enabled": bool(alias.get("is_enabled", True)),
                        "match_weight": int(alias.get("match_weight") or 80),
                        "remark": alias.get("remark"),
                    }
                else:
                    alias_name = str(alias or "").strip()
                    alias_payload = {
                        "alias_name": alias_name,
                        "alias_type_code": "COMMON_NAME",
                        "source_type_code": "SYSTEM",
                        "is_enabled": True,
                        "match_weight": 90 if alias_name in {name, row.get("short_name")} else 80,
                        "remark": None,
                    }
                if alias_name and alias_name not in deduped_aliases:
                    deduped_aliases.append(alias_payload)
            seen_aliases: set[str] = set()
            final_aliases: list[dict] = []
            for item in deduped_aliases:
                if item["alias_name"] in seen_aliases:
                    continue
                seen_aliases.add(item["alias_name"])
                final_aliases.append(item)
            for index, alias in enumerate(final_aliases):
                session.add(
                    CommodityAlias(
                        commodity_standard_id=entity.id,
                        alias_name=alias["alias_name"],
                        alias_type_code=alias["alias_type_code"],
                        source_type_code=alias["source_type_code"],
                        is_primary=index == 0,
                        is_enabled=alias["is_enabled"],
                        match_weight=alias["match_weight"],
                        remark=alias["remark"],
                    )
                )

            await session.execute(
                delete(CommodityStandardAttribute).where(
                    CommodityStandardAttribute.commodity_standard_id == entity.id
                )
            )
            for index, attr in enumerate(row.get("attributes") or []):
                attr_code = str(attr.get("attribute_code") or "").strip()
                definition = attribute_definitions.get(attr_code)
                if definition is None:
                    continue
                session.add(
                    CommodityStandardAttribute(
                        commodity_standard_id=entity.id,
                        attribute_definition_id=definition.id,
                        attribute_code=definition.attribute_code,
                        attribute_name=definition.attribute_name,
                        attribute_value_type_code=definition.value_type_code,
                        attribute_unit=definition.unit_code,
                        attribute_value=str(attr.get("attribute_value") or "").strip() or None,
                        is_required=bool(attr.get("is_required", definition.is_required_default)),
                        sort_order=int(attr.get("sort_order") or index),
                    )
                )

            await session.execute(
                delete(CommodityPackagingForm).where(
                    CommodityPackagingForm.commodity_standard_id == entity.id
                )
            )
            await session.execute(
                delete(CommodityTransportMode).where(
                    CommodityTransportMode.commodity_standard_id == entity.id
                )
            )
            await session.execute(
                delete(CommodityShipTypeRule).where(
                    CommodityShipTypeRule.commodity_standard_id == entity.id
                )
            )
            await session.execute(
                delete(CommodityNodeTypeRule).where(
                    CommodityNodeTypeRule.commodity_standard_id == entity.id
                )
            )
            await session.execute(
                delete(CommodityHandlingModeRule).where(
                    CommodityHandlingModeRule.commodity_standard_id == entity.id
                )
            )
            now = datetime.utcnow()
            for item in _default_rule_items(row, "packaging_forms"):
                session.add(
                    CommodityPackagingForm(
                        commodity_standard_id=entity.id,
                        packaging_form_code=item["code"],
                        is_default=item["is_default"],
                        created_at=now,
                    )
                )
            for item in _default_rule_items(row, "transport_modes"):
                session.add(
                    CommodityTransportMode(
                        commodity_standard_id=entity.id,
                        transport_mode_element_code=item["code"],
                        is_default=item["is_default"],
                        created_at=now,
                    )
                )
            for item in _decision_rule_items(row, "ship_type_rules"):
                session.add(
                    CommodityShipTypeRule(
                        commodity_standard_id=entity.id,
                        ship_type_code=item["code"],
                        rule_type_code=item["rule_type_code"],
                        priority=item["priority"],
                        is_enabled=True,
                        allow_flag=item["allow_flag"],
                        rule_desc=item["rule_desc"],
                        created_at=now,
                    )
                )
            for item in _decision_rule_items(row, "node_type_rules"):
                session.add(
                    CommodityNodeTypeRule(
                        commodity_standard_id=entity.id,
                        node_type_code=item["code"],
                        operation_side_code=item["operation_side_code"],
                        rule_type_code=item["rule_type_code"],
                        priority=item["priority"],
                        is_enabled=True,
                        allow_flag=item["allow_flag"],
                        rule_desc=item["rule_desc"],
                        created_at=now,
                    )
                )
            for item in _decision_rule_items(row, "handling_mode_rules"):
                session.add(
                    CommodityHandlingModeRule(
                        commodity_standard_id=entity.id,
                        handling_mode_code=item["code"],
                        rule_type_code=item["rule_type_code"],
                        priority=item["priority"],
                        is_enabled=True,
                        allow_flag=item["allow_flag"],
                        rule_desc=item["rule_desc"],
                        created_at=now,
                    )
                )

        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_commodity_standards())
