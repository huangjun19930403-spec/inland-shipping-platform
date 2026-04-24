"""commodity 模块 router。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.commodity.schemas import (
    CommodityAliasReplaceRequest,
    CommodityAttributeReplaceRequest,
    CommodityCategoryCreateRequest,
    CommodityCategoryListQuery,
    CommodityCategoryResponse,
    CommodityCategoryUpdateRequest,
    CommodityRuleCodeReplaceRequest,
    CommodityStandardCreateRequest,
    CommodityStandardDetailResponse,
    CommodityStandardListQuery,
    CommodityStandardResponse,
    CommodityStandardUpdateRequest,
    CommodityTypeCreateRequest,
    CommodityTypeListQuery,
    CommodityTypeResponse,
    CommodityTypeUpdateRequest,
    PageResponse,
)
from app.modules.commodity.service import CommodityCategoryService, CommodityStandardService, CommodityTypeService

router = APIRouter()


@router.get("/categories", response_model=PageResponse[CommodityCategoryResponse])
async def list_categories(
    query: CommodityCategoryListQuery = Depends(),
    db: AsyncSession = Depends(get_db),
):
    service = CommodityCategoryService(db)
    return await service.list_categories(query.keyword, query.status, query.page, query.page_size)


@router.get("/categories/{category_id}", response_model=CommodityCategoryResponse)
async def get_category_detail(
    category_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityCategoryService(db)
    return await service.get_category_detail(category_id)


@router.post("/categories", response_model=CommodityCategoryResponse)
async def create_category(
    body: CommodityCategoryCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityCategoryService(db)
    return await service.create_category(body)


@router.put("/categories/{category_id}", response_model=CommodityCategoryResponse)
async def update_category(
    category_id: int,
    body: CommodityCategoryUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityCategoryService(db)
    return await service.update_category(category_id, body)


@router.get("/types", response_model=PageResponse[CommodityTypeResponse])
async def list_types(
    query: CommodityTypeListQuery = Depends(),
    db: AsyncSession = Depends(get_db),
):
    service = CommodityTypeService(db)
    return await service.list_types(
        query.category_id,
        query.keyword,
        query.status,
        query.page,
        query.page_size,
    )


@router.get("/types/{type_id}", response_model=CommodityTypeResponse)
async def get_type_detail(
    type_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityTypeService(db)
    return await service.get_type_detail(type_id)


@router.post("/types", response_model=CommodityTypeResponse)
async def create_type(
    body: CommodityTypeCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityTypeService(db)
    return await service.create_type(body)


@router.put("/types/{type_id}", response_model=CommodityTypeResponse)
async def update_type(
    type_id: int,
    body: CommodityTypeUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityTypeService(db)
    return await service.update_type(type_id, body)


@router.get("/standards", response_model=PageResponse[CommodityStandardResponse])
async def list_standards(
    query: CommodityStandardListQuery = Depends(),
    db: AsyncSession = Depends(get_db),
):
    service = CommodityStandardService(db)
    return await service.list_standards(
        query.category_id,
        query.type_id,
        query.keyword,
        query.status,
        query.page,
        query.page_size,
    )


@router.get("/standards/{standard_id}", response_model=CommodityStandardDetailResponse)
async def get_standard_detail(
    standard_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityStandardService(db)
    return await service.get_standard_detail(standard_id)


@router.post("/standards", response_model=CommodityStandardResponse)
async def create_standard(
    body: CommodityStandardCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityStandardService(db)
    return await service.create_standard(body)


@router.put("/standards/{standard_id}", response_model=CommodityStandardResponse)
async def update_standard(
    standard_id: int,
    body: CommodityStandardUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityStandardService(db)
    return await service.update_standard(standard_id, body)


@router.put("/standards/{standard_id}/aliases")
async def replace_aliases(
    standard_id: int,
    body: CommodityAliasReplaceRequest,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityStandardService(db)
    await service.replace_aliases(standard_id, body)
    return {"ok": True}


@router.put("/standards/{standard_id}/attributes")
async def replace_attributes(
    standard_id: int,
    body: CommodityAttributeReplaceRequest,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityStandardService(db)
    await service.replace_attributes(standard_id, body)
    return {"ok": True}


@router.put("/standards/{standard_id}/packaging-forms")
async def replace_packaging_forms(
    standard_id: int,
    body: CommodityRuleCodeReplaceRequest,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityStandardService(db)
    await service.replace_packaging_forms(standard_id, body)
    return {"ok": True}


@router.put("/standards/{standard_id}/transport-modes")
async def replace_transport_modes(
    standard_id: int,
    body: CommodityRuleCodeReplaceRequest,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityStandardService(db)
    await service.replace_transport_modes(standard_id, body)
    return {"ok": True}


@router.put("/standards/{standard_id}/ship-type-rules")
async def replace_ship_type_rules(
    standard_id: int,
    body: CommodityRuleCodeReplaceRequest,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityStandardService(db)
    await service.replace_ship_type_rules(standard_id, body)
    return {"ok": True}


@router.put("/standards/{standard_id}/node-type-rules")
async def replace_node_type_rules(
    standard_id: int,
    body: CommodityRuleCodeReplaceRequest,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityStandardService(db)
    await service.replace_node_type_rules(standard_id, body)
    return {"ok": True}


@router.put("/standards/{standard_id}/handling-mode-rules")
async def replace_handling_mode_rules(
    standard_id: int,
    body: CommodityRuleCodeReplaceRequest,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityStandardService(db)
    await service.replace_handling_mode_rules(standard_id, body)
    return {"ok": True}

