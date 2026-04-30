"""commodity 模块 service。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.modules.commodity.repository import (
    CommodityCategoryRepository,
    CommodityStandardRepository,
    CommodityTypeRepository,
)
from app.modules.dictionary.service import CodeSequenceService
from app.modules.dictionary.labels import DictLabelMap, dict_label, load_dict_label_map
from app.modules.commodity.schemas import (
    CommodityAliasReplaceRequest,
    CommodityAttributeReplaceRequest,
    CommodityDecisionRuleReplaceRequest,
    CommodityDefaultRuleReplaceRequest,
    CommodityMetadataResponse,
    CommodityCategoryResponse,
    CommodityStandardCreateRequest,
    CommodityStandardDetailResponse,
    CommodityStandardResponse,
    CommodityStandardUpdateRequest,
    CommodityTypeResponse,
    PageResponse,
)


def _category_response(row) -> CommodityCategoryResponse:
    return CommodityCategoryResponse(
        id=row.id,
        code=row.code,
        name=row.name,
        description=row.description,
        sort_order=row.sort_order,
        audit_status=row.audit_status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _type_response(row) -> CommodityTypeResponse:
    return CommodityTypeResponse(
        id=row.id,
        category_id=row.category_id,
        code=row.code,
        name=row.name,
        description=row.description,
        sort_order=row.sort_order,
        audit_status=row.audit_status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _standard_response(row, labels: DictLabelMap | None = None) -> CommodityStandardResponse:
    labels = labels or {}
    return CommodityStandardResponse(
        id=row.id,
        type_id=row.type_id,
        code=row.code,
        name=row.name,
        short_name=row.short_name,
        english_name=row.english_name,
        main_unit_code=row.main_unit_code,
        main_unit_name=dict_label(labels, "COMMODITY_UNIT", row.main_unit_code),
        density_range_desc=row.density_range_desc,
        dangerous_grade_code=row.dangerous_grade_code,
        dangerous_grade_name=dict_label(labels, "DANGEROUS_GOODS_LEVEL", row.dangerous_grade_code),
        is_active=row.is_active,
        audit_status=row.audit_status,
        audit_status_name=dict_label(labels, "AUDIT_STATUS", row.audit_status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _normalize_default_rule_items(payload: CommodityDefaultRuleReplaceRequest) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    seen_codes: set[str] = set()
    default_assigned = False
    has_explicit_default = any(item.is_default for item in payload.items)
    for index, item in enumerate(payload.items):
        code = item.code.strip()
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        is_default = item.is_default and not default_assigned
        if not has_explicit_default and index == 0:
            is_default = True
        default_assigned = default_assigned or is_default
        items.append({"code": code, "is_default": is_default})
    return items


def _normalize_decision_rule_items(payload: CommodityDecisionRuleReplaceRequest) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    seen_codes: set[str] = set()
    for item in payload.items:
        code = item.code.strip()
        if not code or code in seen_codes:
            continue
        seen_codes.add(code)
        items.append(
            {
                "code": code,
                "allow_flag": item.allow_flag,
                "rule_desc": item.rule_desc.strip() if item.rule_desc else None,
            }
        )
    return items


class CommodityMetadataService:
    def __init__(self, db: AsyncSession) -> None:
        self.category_repo = CommodityCategoryRepository(db)
        self.type_repo = CommodityTypeRepository(db)

    async def get_metadata(self) -> CommodityMetadataResponse:
        categories, _ = await self.category_repo.list_categories(None, 1, 1, 500)
        types, _ = await self.type_repo.list_types(None, None, 1, 1, 500)
        return CommodityMetadataResponse(
            categories=[_category_response(item) for item in categories],
            types=[_type_response(item) for item in types],
        )


class CommodityStandardService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = CommodityStandardRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def list_standards(
        self,
        category_id: int | None,
        type_id: int | None,
        keyword: str | None,
        status: int | None,
        page: int,
        page_size: int,
    ) -> PageResponse[CommodityStandardResponse]:
        items, total = await self.repo.list_standards(category_id, type_id, keyword, status, page, page_size)
        labels = await load_dict_label_map(
            self.db,
            ["COMMODITY_UNIT", "DANGEROUS_GOODS_LEVEL", "AUDIT_STATUS"],
        )
        return PageResponse[CommodityStandardResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_standard_response(item, labels) for item in items],
        )

    async def create_standard(self, payload: CommodityStandardCreateRequest) -> CommodityStandardResponse:
        data = payload.model_dump(exclude_none=True)
        code = await self.sequence_service.next_code("COMMODITY_STANDARD_CODE")
        data["code"] = code
        if await self.repo.get_standard_by_code(code):
            raise ConflictError(f"commodity standard code already exists: {code}")
        item = await self.repo.create_standard(data)
        await self.db.commit()
        labels = await load_dict_label_map(
            self.db,
            ["COMMODITY_UNIT", "DANGEROUS_GOODS_LEVEL", "AUDIT_STATUS"],
        )
        return _standard_response(item, labels)

    async def update_standard(self, standard_id: int, payload: CommodityStandardUpdateRequest) -> CommodityStandardResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        item = await self.repo.update_standard(standard_id, updates)
        if item is None:
            raise NotFoundError("CommodityStandard", standard_id)
        await self.db.commit()
        labels = await load_dict_label_map(
            self.db,
            ["COMMODITY_UNIT", "DANGEROUS_GOODS_LEVEL", "AUDIT_STATUS"],
        )
        return _standard_response(item, labels)

    async def get_standard_detail(self, standard_id: int) -> CommodityStandardDetailResponse:
        item = await self.repo.get_standard(standard_id)
        if item is None:
            raise NotFoundError("CommodityStandard", standard_id)

        attributes = await self.repo.list_attributes(standard_id)
        labels = await load_dict_label_map(
            self.db,
            [
                "COMMODITY_UNIT",
                "DANGEROUS_GOODS_LEVEL",
                "AUDIT_STATUS",
                "PACKAGING_FORM",
                "TRANSPORT_MODE_ELEMENT",
                "SHIP_TYPE",
                "NODE_TYPE",
                "HANDLING_MODE",
                "VALUE_TYPE",
            ],
        )
        packaging_forms = await self.repo.list_packaging_forms(standard_id)
        transport_modes = await self.repo.list_transport_modes(standard_id)
        ship_type_rules = await self.repo.list_ship_type_rules(standard_id)
        node_type_rules = await self.repo.list_node_type_rules(standard_id)
        handling_mode_rules = await self.repo.list_handling_mode_rules(standard_id)
        return CommodityStandardDetailResponse(
            standard=_standard_response(item, labels),
            aliases=await self.repo.list_aliases(standard_id),
            attributes=[
                {
                    "attribute_code": attr.attribute_code,
                    "attribute_name": attr.attribute_name,
                    "attribute_value_type_code": attr.attribute_value_type_code,
                    "attribute_value_type_name": dict_label(
                        labels, "VALUE_TYPE", attr.attribute_value_type_code
                    ),
                    "attribute_unit": attr.attribute_unit,
                    "is_required": attr.is_required,
                    "default_value": attr.default_value,
                    "value_range_desc": attr.value_range_desc,
                    "sort_order": attr.sort_order,
                }
                for attr in attributes
            ],
            packaging_forms=[
                {
                    "code": row.packaging_form_code,
                    "name": dict_label(labels, "PACKAGING_FORM", row.packaging_form_code),
                    "is_default": row.is_default,
                }
                for row in packaging_forms
            ],
            transport_modes=[
                {
                    "code": row.transport_mode_element_code,
                    "name": dict_label(labels, "TRANSPORT_MODE_ELEMENT", row.transport_mode_element_code),
                    "is_default": row.is_default,
                }
                for row in transport_modes
            ],
            ship_type_rules=[
                {
                    "code": row.ship_type_code,
                    "name": dict_label(labels, "SHIP_TYPE", row.ship_type_code),
                    "allow_flag": row.allow_flag,
                    "rule_desc": row.rule_desc,
                }
                for row in ship_type_rules
            ],
            node_type_rules=[
                {
                    "code": row.node_type_code,
                    "name": dict_label(labels, "NODE_TYPE", row.node_type_code),
                    "allow_flag": row.allow_flag,
                    "rule_desc": row.rule_desc,
                }
                for row in node_type_rules
            ],
            handling_mode_rules=[
                {
                    "code": row.handling_mode_code,
                    "name": dict_label(labels, "HANDLING_MODE", row.handling_mode_code),
                    "allow_flag": row.allow_flag,
                    "rule_desc": row.rule_desc,
                }
                for row in handling_mode_rules
            ],
        )

    async def replace_aliases(self, standard_id: int, payload: CommodityAliasReplaceRequest) -> None:
        if await self.repo.get_standard(standard_id) is None:
            raise NotFoundError("CommodityStandard", standard_id)
        await self.repo.replace_aliases(standard_id, payload.aliases)
        await self.db.commit()

    async def replace_attributes(self, standard_id: int, payload: CommodityAttributeReplaceRequest) -> None:
        if await self.repo.get_standard(standard_id) is None:
            raise NotFoundError("CommodityStandard", standard_id)
        await self.repo.replace_attributes(
            standard_id,
            [item.model_dump() for item in payload.attributes],
        )
        await self.db.commit()

    async def replace_packaging_forms(self, standard_id: int, payload: CommodityDefaultRuleReplaceRequest) -> None:
        if await self.repo.get_standard(standard_id) is None:
            raise NotFoundError("CommodityStandard", standard_id)
        await self.repo.replace_packaging_forms(standard_id, _normalize_default_rule_items(payload))
        await self.db.commit()

    async def replace_transport_modes(self, standard_id: int, payload: CommodityDefaultRuleReplaceRequest) -> None:
        if await self.repo.get_standard(standard_id) is None:
            raise NotFoundError("CommodityStandard", standard_id)
        await self.repo.replace_transport_modes(standard_id, _normalize_default_rule_items(payload))
        await self.db.commit()

    async def replace_ship_type_rules(self, standard_id: int, payload: CommodityDecisionRuleReplaceRequest) -> None:
        if await self.repo.get_standard(standard_id) is None:
            raise NotFoundError("CommodityStandard", standard_id)
        await self.repo.replace_ship_type_rules(standard_id, _normalize_decision_rule_items(payload))
        await self.db.commit()

    async def replace_node_type_rules(self, standard_id: int, payload: CommodityDecisionRuleReplaceRequest) -> None:
        if await self.repo.get_standard(standard_id) is None:
            raise NotFoundError("CommodityStandard", standard_id)
        await self.repo.replace_node_type_rules(standard_id, _normalize_decision_rule_items(payload))
        await self.db.commit()

    async def replace_handling_mode_rules(self, standard_id: int, payload: CommodityDecisionRuleReplaceRequest) -> None:
        if await self.repo.get_standard(standard_id) is None:
            raise NotFoundError("CommodityStandard", standard_id)
        await self.repo.replace_handling_mode_rules(standard_id, _normalize_decision_rule_items(payload))
        await self.db.commit()
