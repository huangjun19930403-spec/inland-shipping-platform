"""commodity 模块 service。"""

from __future__ import annotations

from typing import Any

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.commodity import CommodityAttributeDefinition, CommodityCategory, CommodityStandard, CommodityType
from app.modules.commodity.repository import (
    CommodityAttributeDefinitionRepository,
    CommodityCategoryRepository,
    CommodityStandardRepository,
    CommodityTypeRepository,
)
from app.modules.commodity.schemas import (
    CommodityAliasReplaceRequest,
    CommodityAliasResponse,
    CommodityAttributeDefinitionResponse,
    CommodityAttributeReplaceRequest,
    CommodityAttributeResponse,
    CommodityDecisionRuleReplaceRequest,
    CommodityDecisionRuleResponse,
    CommodityDefaultRuleReplaceRequest,
    CommodityDefaultRuleResponse,
    CommodityFreightUsageItem,
    CommodityMetadataResponse,
    CommodityCategoryResponse,
    CommodityStandardCreateRequest,
    CommodityStandardDetailResponse,
    CommodityStandardImageResponse,
    CommodityStandardImageUpdateRequest,
    CommodityStandardResponse,
    CommodityStandardUpdateRequest,
    CommodityStandardUsageSummary,
    CommodityTypeResponse,
    PageResponse,
)
from app.modules.dictionary.labels import DictLabelMap, dict_label, load_dict_label_map
from app.modules.dictionary.service import CodeSequenceService
from app.modules.storage.service import FileStorageService


LABEL_DICTS = [
    "COMMODITY_UNIT",
    "DANGEROUS_GOODS_LEVEL",
    "AUDIT_STATUS",
    "COMMODITY_CARGO_FORM",
    "POLLUTION_RISK_LEVEL",
    "SOURCE_TYPE",
    "COMMODITY_ALIAS_TYPE",
    "COMMODITY_IMAGE_TYPE",
    "COMMODITY_RULE_TYPE",
    "COMMODITY_OPERATION_SIDE",
    "COMMODITY_ATTRIBUTE_GROUP",
    "VALUE_TYPE",
    "PACKAGING_FORM",
    "TRANSPORT_MODE_ELEMENT",
    "SHIP_TYPE",
    "NODE_TYPE",
    "HANDLING_MODE",
]


def _category_response(row: CommodityCategory) -> CommodityCategoryResponse:
    return CommodityCategoryResponse(
        id=row.id,
        code=row.code,
        name=row.name,
        description=row.description,
        sort_order=row.sort_order,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _type_response(row: CommodityType) -> CommodityTypeResponse:
    return CommodityTypeResponse(
        id=row.id,
        category_id=row.category_id,
        code=row.code,
        name=row.name,
        description=row.description,
        sort_order=row.sort_order,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _attribute_definition_response(row: CommodityAttributeDefinition, labels: DictLabelMap) -> CommodityAttributeDefinitionResponse:
    return CommodityAttributeDefinitionResponse(
        id=row.id,
        attribute_code=row.attribute_code,
        attribute_name=row.attribute_name,
        attribute_group_code=row.attribute_group_code,
        attribute_group_name=dict_label(labels, "COMMODITY_ATTRIBUTE_GROUP", row.attribute_group_code),
        value_type_code=row.value_type_code,
        value_type_name=dict_label(labels, "VALUE_TYPE", row.value_type_code),
        unit_code=row.unit_code,
        unit_name=dict_label(labels, "COMMODITY_UNIT", row.unit_code),
        option_dict_code=row.option_dict_code,
        description=row.description,
        is_required_default=row.is_required_default,
        is_enabled=row.is_enabled,
        sort_order=row.sort_order,
    )


def _image_response(row, storage_file, labels: DictLabelMap) -> CommodityStandardImageResponse:
    return CommodityStandardImageResponse(
        id=row.id,
        commodity_standard_id=row.commodity_standard_id,
        file_id=row.file_id,
        image_type_code=row.image_type_code,
        image_type_name=dict_label(labels, "COMMODITY_IMAGE_TYPE", row.image_type_code),
        image_name=row.image_name,
        description=row.description,
        is_primary=row.is_primary,
        sort_order=row.sort_order,
        content_url=f"/api/v1/files/{row.file_id}/content",
        original_file_name=storage_file.original_file_name,
        content_type=storage_file.content_type,
        file_size=storage_file.file_size,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _capability_summary(
    packaging_count: int,
    transport_count: int,
    ship_count: int,
    node_count: int,
    handling_count: int,
) -> str:
    parts = []
    if packaging_count:
        parts.append(f"包装{packaging_count}")
    if transport_count:
        parts.append(f"运输{transport_count}")
    if ship_count:
        parts.append(f"船型{ship_count}")
    if node_count:
        parts.append(f"节点{node_count}")
    if handling_count:
        parts.append(f"作业{handling_count}")
    return " / ".join(parts) if parts else "未维护"


def _standard_response(
    standard: CommodityStandard,
    commodity_type: CommodityType,
    category: CommodityCategory | None,
    labels: DictLabelMap,
    *,
    alias_count: int = 0,
    attribute_count: int = 0,
    image_count: int = 0,
    freight_count: int = 0,
    capability_summary: str | None = None,
    primary_image: CommodityStandardImageResponse | None = None,
) -> CommodityStandardResponse:
    category_id = standard.category_id or commodity_type.category_id
    return CommodityStandardResponse(
        id=standard.id,
        category_id=category_id,
        category_code=category.code if category is not None else None,
        category_name=category.name if category is not None else None,
        type_id=standard.type_id,
        type_code=commodity_type.code,
        type_name=commodity_type.name,
        code=standard.code,
        name=standard.name,
        short_name=standard.short_name,
        english_name=standard.english_name,
        main_unit_code=standard.main_unit_code,
        main_unit_name=dict_label(labels, "COMMODITY_UNIT", standard.main_unit_code),
        specification=standard.specification,
        cargo_form_code=standard.cargo_form_code,
        cargo_form_name=dict_label(labels, "COMMODITY_CARGO_FORM", standard.cargo_form_code),
        density_range_desc=standard.density_range_desc,
        dangerous_grade_code=standard.dangerous_grade_code,
        dangerous_grade_name=dict_label(labels, "DANGEROUS_GOODS_LEVEL", standard.dangerous_grade_code),
        is_bulk_cargo=standard.is_bulk_cargo,
        is_container_suitable=standard.is_container_suitable,
        is_hazardous=standard.is_hazardous,
        pollution_risk_level_code=standard.pollution_risk_level_code,
        pollution_risk_level_name=dict_label(labels, "POLLUTION_RISK_LEVEL", standard.pollution_risk_level_code),
        loading_requirement=standard.loading_requirement,
        unloading_requirement=standard.unloading_requirement,
        storage_requirement=standard.storage_requirement,
        source_type_code=standard.source_type_code,
        source_type_name=dict_label(labels, "SOURCE_TYPE", standard.source_type_code),
        recognition_priority=standard.recognition_priority,
        remark=standard.remark,
        is_active=standard.is_active,
        alias_count=alias_count,
        attribute_count=attribute_count,
        image_count=image_count,
        freight_count=freight_count,
        capability_summary=capability_summary,
        primary_image=primary_image,
        created_at=standard.created_at,
        updated_at=standard.updated_at,
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
        items.append(
            {
                "code": code,
                "is_default": is_default,
                "is_enabled": item.is_enabled,
                "remark": item.remark.strip() if item.remark else None,
            }
        )
    return items


def _normalize_decision_rule_items(payload: CommodityDecisionRuleReplaceRequest) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    seen_keys: set[tuple[str, str | None]] = set()
    for item in payload.items:
        code = item.code.strip()
        operation_side = item.operation_side_code.strip() if item.operation_side_code else None
        key = (code, operation_side)
        if not code or key in seen_keys:
            continue
        seen_keys.add(key)
        rule_type = item.rule_type_code.strip() if item.rule_type_code else "ALLOWED"
        if item.allow_flag is False and rule_type == "ALLOWED":
            rule_type = "FORBIDDEN"
        items.append(
            {
                "code": code,
                "rule_type_code": rule_type,
                "priority": item.priority,
                "operation_side_code": operation_side,
                "is_enabled": item.is_enabled,
                "rule_desc": item.rule_desc.strip() if item.rule_desc else None,
            }
        )
    return items


def _alias_payload_items(payload: CommodityAliasReplaceRequest) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, item in enumerate(payload.aliases):
        if isinstance(item, str):
            value = item.strip()
            if value:
                result.append(
                    {
                        "alias_name": value,
                        "alias_type_code": "COMMON_NAME",
                        "source_type_code": "MANUAL",
                        "is_primary": index == 0,
                        "is_enabled": True,
                        "match_weight": 80,
                        "remark": None,
                    }
                )
            continue
        result.append(item.model_dump())
    return result


class CommodityMetadataService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.category_repo = CommodityCategoryRepository(db)
        self.type_repo = CommodityTypeRepository(db)
        self.attr_repo = CommodityAttributeDefinitionRepository(db)

    async def get_metadata(self) -> CommodityMetadataResponse:
        categories, _ = await self.category_repo.list_categories(None, 1, 1, 500)
        types, _ = await self.type_repo.list_types(None, None, 1, 1, 500)
        labels = await load_dict_label_map(self.db, LABEL_DICTS)
        definitions = await self.attr_repo.list_definitions(enabled_only=True)
        return CommodityMetadataResponse(
            categories=[_category_response(item) for item in categories],
            types=[_type_response(item) for item in types],
            attribute_definitions=[_attribute_definition_response(item, labels) for item in definitions],
        )


class CommodityStandardService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = CommodityStandardRepository(db)
        self.type_repo = CommodityTypeRepository(db)
        self.attr_repo = CommodityAttributeDefinitionRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def _validate_taxonomy(self, category_id: int, type_id: int) -> CommodityType:
        commodity_type = await self.type_repo.get_type(type_id)
        if commodity_type is None:
            raise ValidationError("货品类型不存在或已停用")
        if int(commodity_type.category_id) != int(category_id):
            raise ValidationError("货品类型不属于所选货品分类")
        return commodity_type

    async def _labels(self) -> DictLabelMap:
        return await load_dict_label_map(self.db, LABEL_DICTS)

    async def _primary_image(self, standard_id: int, labels: DictLabelMap) -> CommodityStandardImageResponse | None:
        images = await self.repo.list_images(standard_id)
        if not images:
            return None
        row, storage_file = images[0]
        return _image_response(row, storage_file, labels)

    async def _capability_summary(self, standard_id: int) -> str:
        return _capability_summary(
            len(await self.repo.list_packaging_forms(standard_id)),
            len(await self.repo.list_transport_modes(standard_id)),
            len(await self.repo.list_ship_type_rules(standard_id)),
            len(await self.repo.list_node_type_rules(standard_id)),
            len(await self.repo.list_handling_mode_rules(standard_id)),
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
    ) -> PageResponse[CommodityStandardResponse]:
        bundles, total = await self.repo.list_standards(
            category_id=category_id,
            type_id=type_id,
            keyword=keyword,
            status=status,
            main_unit_code=main_unit_code,
            cargo_form_code=cargo_form_code,
            is_bulk_cargo=is_bulk_cargo,
            is_container_suitable=is_container_suitable,
            is_hazardous=is_hazardous,
            source_type_code=source_type_code,
            has_alias=has_alias,
            has_image=has_image,
            used_by_freight=used_by_freight,
            page=page,
            page_size=page_size,
        )
        labels = await self._labels()
        ids = [int(bundle[0].id) for bundle in bundles]
        counts = await self.repo.bulk_counts(ids)
        items: list[CommodityStandardResponse] = []
        for standard, commodity_type, category in bundles:
            primary_image = await self._primary_image(standard.id, labels)
            items.append(
                _standard_response(
                    standard,
                    commodity_type,
                    category,
                    labels,
                    alias_count=counts["aliases"].get(standard.id, 0),
                    attribute_count=counts["attributes"].get(standard.id, 0),
                    image_count=counts["images"].get(standard.id, 0),
                    freight_count=counts["freights"].get(standard.id, 0),
                    capability_summary=await self._capability_summary(standard.id),
                    primary_image=primary_image,
                )
            )
        return PageResponse[CommodityStandardResponse](total=total, page=page, page_size=page_size, items=items)

    async def create_standard(self, payload: CommodityStandardCreateRequest) -> CommodityStandardResponse:
        await self._validate_taxonomy(payload.category_id, payload.type_id)
        data = payload.model_dump(exclude_none=True)
        data["code"] = await self.sequence_service.next_code("COMMODITY_STANDARD_CODE")
        if await self.repo.get_standard_by_code(data["code"]):
            raise ConflictError(f"commodity standard code already exists: {data['code']}")
        item = await self.repo.create_standard(data)
        await self.db.commit()
        return await self._response_by_id(item.id)

    async def update_standard(self, standard_id: int, payload: CommodityStandardUpdateRequest) -> CommodityStandardResponse:
        current = await self.repo.get_standard(standard_id)
        if current is None:
            raise NotFoundError("CommodityStandard", standard_id)
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            raise ValidationError("no update fields provided")
        current_category_id = current.category_id
        if current_category_id is None:
            current_type = await self.type_repo.get_type(current.type_id)
            current_category_id = current_type.category_id if current_type is not None else None
        category_id = int(updates.get("category_id") or current_category_id or 0)
        type_id = int(updates.get("type_id") or current.type_id)
        await self._validate_taxonomy(category_id, type_id)
        updates["category_id"] = category_id
        item = await self.repo.update_standard(standard_id, updates)
        if item is None:
            raise NotFoundError("CommodityStandard", standard_id)
        await self.db.commit()
        return await self._response_by_id(item.id)

    async def _response_by_id(self, standard_id: int) -> CommodityStandardResponse:
        bundle = await self.repo.get_standard_bundle(standard_id)
        if bundle is None:
            raise NotFoundError("CommodityStandard", standard_id)
        labels = await self._labels()
        counts = await self.repo.bulk_counts([standard_id])
        freight_count, _, _ = await self.repo.freight_usage_summary(standard_id)
        standard, commodity_type, category = bundle
        return _standard_response(
            standard,
            commodity_type,
            category,
            labels,
            alias_count=counts["aliases"].get(standard_id, 0),
            attribute_count=counts["attributes"].get(standard_id, 0),
            image_count=counts["images"].get(standard_id, 0),
            freight_count=freight_count,
            capability_summary=await self._capability_summary(standard_id),
            primary_image=await self._primary_image(standard_id, labels),
        )

    async def get_standard_detail(self, standard_id: int) -> CommodityStandardDetailResponse:
        bundle = await self.repo.get_standard_bundle(standard_id)
        if bundle is None:
            raise NotFoundError("CommodityStandard", standard_id)
        labels = await self._labels()
        standard_response = await self._response_by_id(standard_id)
        images = [_image_response(row, storage_file, labels) for row, storage_file in await self.repo.list_images(standard_id)]
        freight_count, raw_pending_count, latest = await self.repo.freight_usage_summary(standard_id)
        return CommodityStandardDetailResponse(
            standard=standard_response,
            images=images,
            aliases=[
                CommodityAliasResponse(
                    id=row.id,
                    alias_name=row.alias_name,
                    alias_type_code=row.alias_type_code,
                    alias_type_name=dict_label(labels, "COMMODITY_ALIAS_TYPE", row.alias_type_code),
                    source_type_code=row.source_type_code,
                    source_type_name=dict_label(labels, "SOURCE_TYPE", row.source_type_code),
                    is_primary=row.is_primary,
                    is_enabled=row.is_enabled,
                    match_weight=row.match_weight,
                    remark=row.remark,
                )
                for row in await self.repo.list_aliases(standard_id)
            ],
            attributes=[
                CommodityAttributeResponse(
                    id=attr.id,
                    attribute_definition_id=attr.attribute_definition_id,
                    attribute_code=definition.attribute_code if definition is not None else attr.attribute_code,
                    attribute_name=definition.attribute_name if definition is not None else attr.attribute_name,
                    attribute_group_code=definition.attribute_group_code if definition is not None else None,
                    attribute_group_name=dict_label(labels, "COMMODITY_ATTRIBUTE_GROUP", definition.attribute_group_code) if definition is not None else None,
                    value_type_code=definition.value_type_code if definition is not None else attr.attribute_value_type_code,
                    value_type_name=dict_label(labels, "VALUE_TYPE", definition.value_type_code if definition is not None else attr.attribute_value_type_code),
                    unit_code=definition.unit_code if definition is not None else attr.attribute_unit,
                    unit_name=dict_label(labels, "COMMODITY_UNIT", definition.unit_code if definition is not None else attr.attribute_unit),
                    attribute_value=attr.attribute_value or attr.default_value,
                    is_required=attr.is_required,
                    sort_order=attr.sort_order,
                )
                for attr, definition in await self.repo.list_attributes(standard_id)
            ],
            packaging_forms=[
                CommodityDefaultRuleResponse(
                    code=row.packaging_form_code,
                    name=dict_label(labels, "PACKAGING_FORM", row.packaging_form_code),
                    is_default=row.is_default,
                    is_enabled=row.is_enabled,
                    remark=row.remark,
                )
                for row in await self.repo.list_packaging_forms(standard_id)
            ],
            transport_modes=[
                CommodityDefaultRuleResponse(
                    code=row.transport_mode_element_code,
                    name=dict_label(labels, "TRANSPORT_MODE_ELEMENT", row.transport_mode_element_code),
                    is_default=row.is_default,
                    is_enabled=row.is_enabled,
                    remark=row.remark,
                )
                for row in await self.repo.list_transport_modes(standard_id)
            ],
            ship_type_rules=[
                self._decision_rule_response(row.ship_type_code, "SHIP_TYPE", row, labels)
                for row in await self.repo.list_ship_type_rules(standard_id)
            ],
            node_type_rules=[
                self._decision_rule_response(row.node_type_code, "NODE_TYPE", row, labels, operation_side_code=row.operation_side_code)
                for row in await self.repo.list_node_type_rules(standard_id)
            ],
            handling_mode_rules=[
                self._decision_rule_response(row.handling_mode_code, "HANDLING_MODE", row, labels)
                for row in await self.repo.list_handling_mode_rules(standard_id)
            ],
            usage_summary=CommodityStandardUsageSummary(
                freight_count=freight_count,
                raw_pending_count=raw_pending_count,
                latest_freight_at=latest,
                recent_freights=[
                    CommodityFreightUsageItem(
                        freight_id=int(row.id),
                        freight_no=row.freight_no,
                        cargo_title=row.cargo_title,
                        status_code=row.status_code,
                        updated_at=row.updated_at,
                    )
                    for row in await self.repo.recent_freight_usage(standard_id)
                ],
            ),
        )

    @staticmethod
    def _decision_rule_response(
        code: str,
        dict_code: str,
        row,
        labels: DictLabelMap,
        *,
        operation_side_code: str | None = None,
    ) -> CommodityDecisionRuleResponse:
        return CommodityDecisionRuleResponse(
            code=code,
            name=dict_label(labels, dict_code, code),
            rule_type_code=row.rule_type_code,
            rule_type_name=dict_label(labels, "COMMODITY_RULE_TYPE", row.rule_type_code),
            priority=row.priority,
            operation_side_code=operation_side_code,
            operation_side_name=dict_label(labels, "COMMODITY_OPERATION_SIDE", operation_side_code),
            is_enabled=row.is_enabled,
            allow_flag=row.rule_type_code != "FORBIDDEN",
            rule_desc=row.rule_desc,
        )

    async def replace_aliases(self, standard_id: int, payload: CommodityAliasReplaceRequest) -> None:
        if await self.repo.get_standard(standard_id) is None:
            raise NotFoundError("CommodityStandard", standard_id)
        await self.repo.replace_aliases(standard_id, _alias_payload_items(payload))
        await self.db.commit()

    async def replace_attributes(self, standard_id: int, payload: CommodityAttributeReplaceRequest) -> None:
        if await self.repo.get_standard(standard_id) is None:
            raise NotFoundError("CommodityStandard", standard_id)
        definitions = {item.id: item for item in await self.attr_repo.list_definitions(enabled_only=True)}
        seen_definitions: set[int] = set()
        items: list[dict[str, Any]] = []
        for item in payload.attributes:
            data = item.model_dump()
            definition_id = data.get("attribute_definition_id")
            if definition_id:
                if definition_id not in definitions:
                    raise ValidationError("属性定义不存在或已停用")
                if definition_id in seen_definitions:
                    raise ValidationError("属性定义不能重复选择")
                seen_definitions.add(definition_id)
                definition = definitions[definition_id]
                data.update(
                    {
                        "attribute_code": definition.attribute_code,
                        "attribute_name": definition.attribute_name,
                        "attribute_value_type_code": definition.value_type_code,
                        "attribute_unit": definition.unit_code,
                        "is_required": data.get("is_required") or definition.is_required_default,
                    }
                )
            elif not (data.get("attribute_code") and data.get("attribute_name")):
                raise ValidationError("请选择属性定义")
            data["attribute_value"] = (data.get("attribute_value") or "").strip() or None
            items.append(data)
        await self.repo.replace_attributes(standard_id, items)
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

    async def list_images(self, standard_id: int) -> list[CommodityStandardImageResponse]:
        if await self.repo.get_standard(standard_id) is None:
            raise NotFoundError("CommodityStandard", standard_id)
        labels = await self._labels()
        return [_image_response(row, storage_file, labels) for row, storage_file in await self.repo.list_images(standard_id)]

    async def create_image(
        self,
        standard_id: int,
        *,
        file: UploadFile,
        image_type_code: str,
        image_name: str | None,
        description: str | None,
        is_primary: bool,
        sort_order: int,
        uploaded_by: int | None,
    ) -> CommodityStandardImageResponse:
        standard = await self.repo.get_standard(standard_id)
        if standard is None:
            raise NotFoundError("CommodityStandard", standard_id)
        existing_images = await self.repo.list_images(standard_id)
        storage_file = await FileStorageService(self.db).upload_image(
            file=file,
            object_prefix=f"commodities/{standard_id}/images",
            uploaded_by=uploaded_by,
        )
        primary = is_primary or not existing_images
        if primary:
            await self.repo.clear_primary_images(standard_id)
        display_name = (image_name or "").strip() or storage_file.original_file_name
        image = await self.repo.create_image(
            {
                "commodity_standard_id": standard_id,
                "file_id": storage_file.id,
                "image_type_code": image_type_code.strip(),
                "image_name": display_name[:128],
                "description": (description or "").strip() or None,
                "is_primary": primary,
                "sort_order": sort_order,
            }
        )
        await self.db.commit()
        labels = await self._labels()
        return _image_response(image, storage_file, labels)

    async def update_image(
        self,
        standard_id: int,
        image_id: int,
        payload: CommodityStandardImageUpdateRequest,
    ) -> CommodityStandardImageResponse:
        row = await self.repo.get_image_with_file(image_id)
        if row is None:
            raise NotFoundError("CommodityStandardImage", image_id)
        image, storage_file = row
        if image.commodity_standard_id != standard_id:
            raise NotFoundError("CommodityStandardImage", image_id)
        updates = payload.model_dump(exclude_unset=True)
        for key in ("image_type_code", "image_name", "description"):
            if isinstance(updates.get(key), str):
                updates[key] = updates[key].strip() or None
        if "image_type_code" in updates and not updates["image_type_code"]:
            raise ValidationError("图片类型不能为空")
        if "image_name" in updates and not updates["image_name"]:
            raise ValidationError("图片名称不能为空")
        if updates.get("is_primary") is True:
            await self.repo.clear_primary_images(standard_id, except_image_id=image_id)
        updated = await self.repo.update_image(image_id, updates)
        if updated is None:
            raise NotFoundError("CommodityStandardImage", image_id)
        await self.db.commit()
        labels = await self._labels()
        return _image_response(updated, storage_file, labels)

    async def delete_image(self, standard_id: int, image_id: int) -> None:
        row = await self.repo.get_image_with_file(image_id)
        if row is None:
            raise NotFoundError("CommodityStandardImage", image_id)
        image, storage_file = row
        if image.commodity_standard_id != standard_id:
            raise NotFoundError("CommodityStandardImage", image_id)
        await self.repo.delete_image(image_id)
        await FileStorageService(self.db).delete_file_entity(storage_file)
        await self.db.commit()
