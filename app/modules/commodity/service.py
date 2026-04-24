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
from app.modules.commodity.schemas import (
    CommodityAliasReplaceRequest,
    CommodityAttributeReplaceRequest,
    CommodityCategoryCreateRequest,
    CommodityCategoryResponse,
    CommodityCategoryUpdateRequest,
    CommodityRuleCodeReplaceRequest,
    CommodityStandardCreateRequest,
    CommodityStandardDetailResponse,
    CommodityStandardResponse,
    CommodityStandardUpdateRequest,
    CommodityTypeCreateRequest,
    CommodityTypeResponse,
    CommodityTypeUpdateRequest,
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


def _standard_response(row) -> CommodityStandardResponse:
    return CommodityStandardResponse(
        id=row.id,
        type_id=row.type_id,
        code=row.code,
        name=row.name,
        short_name=row.short_name,
        english_name=row.english_name,
        main_unit=row.main_unit,
        density_range_desc=row.density_range_desc,
        dangerous_grade_code=row.dangerous_grade_code,
        is_active=row.is_active,
        audit_status=row.audit_status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class CommodityCategoryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = CommodityCategoryRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def list_categories(
        self,
        keyword: str | None,
        status: int | None,
        page: int,
        page_size: int,
    ) -> PageResponse[CommodityCategoryResponse]:
        items, total = await self.repo.list_categories(keyword, status, page, page_size)
        return PageResponse[CommodityCategoryResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_category_response(item) for item in items],
        )

    async def create_category(self, payload: CommodityCategoryCreateRequest) -> CommodityCategoryResponse:
        data = payload.model_dump(exclude_none=True)
        code = (payload.code or "").strip()
        if not code:
            code = await self.sequence_service.next_code("COMMODITY_CATEGORY_CODE")
        data["code"] = code
        if await self.repo.get_category_by_code(code):
            raise ConflictError(f"commodity category code already exists: {code}")
        item = await self.repo.create_category(data)
        await self.db.commit()
        return _category_response(item)

    async def update_category(self, category_id: int, payload: CommodityCategoryUpdateRequest) -> CommodityCategoryResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        item = await self.repo.update_category(category_id, updates)
        if item is None:
            raise NotFoundError("CommodityCategory", category_id)
        await self.db.commit()
        return _category_response(item)

    async def get_category_detail(self, category_id: int) -> CommodityCategoryResponse:
        item = await self.repo.get_category(category_id)
        if item is None:
            raise NotFoundError("CommodityCategory", category_id)
        return _category_response(item)


class CommodityTypeService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = CommodityTypeRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def list_types(
        self,
        category_id: int | None,
        keyword: str | None,
        status: int | None,
        page: int,
        page_size: int,
    ) -> PageResponse[CommodityTypeResponse]:
        items, total = await self.repo.list_types(category_id, keyword, status, page, page_size)
        return PageResponse[CommodityTypeResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_type_response(item) for item in items],
        )

    async def create_type(self, payload: CommodityTypeCreateRequest) -> CommodityTypeResponse:
        data = payload.model_dump(exclude_none=True)
        code = (payload.code or "").strip()
        if not code:
            code = await self.sequence_service.next_code("COMMODITY_TYPE_CODE")
        data["code"] = code
        if await self.repo.get_type_by_code(code):
            raise ConflictError(f"commodity type code already exists: {code}")
        item = await self.repo.create_type(data)
        await self.db.commit()
        return _type_response(item)

    async def update_type(self, type_id: int, payload: CommodityTypeUpdateRequest) -> CommodityTypeResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        item = await self.repo.update_type(type_id, updates)
        if item is None:
            raise NotFoundError("CommodityType", type_id)
        await self.db.commit()
        return _type_response(item)

    async def get_type_detail(self, type_id: int) -> CommodityTypeResponse:
        item = await self.repo.get_type(type_id)
        if item is None:
            raise NotFoundError("CommodityType", type_id)
        return _type_response(item)


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
        return PageResponse[CommodityStandardResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_standard_response(item) for item in items],
        )

    async def create_standard(self, payload: CommodityStandardCreateRequest) -> CommodityStandardResponse:
        data = payload.model_dump(exclude_none=True)
        code = (payload.code or "").strip()
        if not code:
            code = await self.sequence_service.next_code("COMMODITY_STANDARD_CODE")
        data["code"] = code
        if await self.repo.get_standard_by_code(code):
            raise ConflictError(f"commodity standard code already exists: {code}")
        item = await self.repo.create_standard(data)
        await self.db.commit()
        return _standard_response(item)

    async def update_standard(self, standard_id: int, payload: CommodityStandardUpdateRequest) -> CommodityStandardResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        item = await self.repo.update_standard(standard_id, updates)
        if item is None:
            raise NotFoundError("CommodityStandard", standard_id)
        await self.db.commit()
        return _standard_response(item)

    async def get_standard_detail(self, standard_id: int) -> CommodityStandardDetailResponse:
        item = await self.repo.get_standard(standard_id)
        if item is None:
            raise NotFoundError("CommodityStandard", standard_id)

        attributes = await self.repo.list_attributes(standard_id)
        return CommodityStandardDetailResponse(
            standard=_standard_response(item),
            aliases=await self.repo.list_aliases(standard_id),
            attributes=[
                {
                    "attribute_code": attr.attribute_code,
                    "attribute_name": attr.attribute_name,
                    "attribute_value_type_code": attr.attribute_value_type_code,
                    "attribute_unit": attr.attribute_unit,
                    "is_required": attr.is_required,
                    "default_value": attr.default_value,
                    "value_range_desc": attr.value_range_desc,
                    "sort_order": attr.sort_order,
                }
                for attr in attributes
            ],
            packaging_form_codes=await self.repo.list_packaging_form_codes(standard_id),
            transport_mode_codes=await self.repo.list_transport_mode_codes(standard_id),
            ship_type_codes=await self.repo.list_ship_type_codes(standard_id),
            node_type_codes=await self.repo.list_node_type_codes(standard_id),
            handling_mode_codes=await self.repo.list_handling_mode_codes(standard_id),
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

    async def replace_packaging_forms(self, standard_id: int, payload: CommodityRuleCodeReplaceRequest) -> None:
        if await self.repo.get_standard(standard_id) is None:
            raise NotFoundError("CommodityStandard", standard_id)
        await self.repo.replace_packaging_forms(standard_id, payload.codes)
        await self.db.commit()

    async def replace_transport_modes(self, standard_id: int, payload: CommodityRuleCodeReplaceRequest) -> None:
        if await self.repo.get_standard(standard_id) is None:
            raise NotFoundError("CommodityStandard", standard_id)
        await self.repo.replace_transport_modes(standard_id, payload.codes)
        await self.db.commit()

    async def replace_ship_type_rules(self, standard_id: int, payload: CommodityRuleCodeReplaceRequest) -> None:
        if await self.repo.get_standard(standard_id) is None:
            raise NotFoundError("CommodityStandard", standard_id)
        await self.repo.replace_ship_type_rules(standard_id, payload.codes)
        await self.db.commit()

    async def replace_node_type_rules(self, standard_id: int, payload: CommodityRuleCodeReplaceRequest) -> None:
        if await self.repo.get_standard(standard_id) is None:
            raise NotFoundError("CommodityStandard", standard_id)
        await self.repo.replace_node_type_rules(standard_id, payload.codes)
        await self.db.commit()

    async def replace_handling_mode_rules(self, standard_id: int, payload: CommodityRuleCodeReplaceRequest) -> None:
        if await self.repo.get_standard(standard_id) is None:
            raise NotFoundError("CommodityStandard", standard_id)
        await self.repo.replace_handling_mode_rules(standard_id, payload.codes)
        await self.db.commit()
