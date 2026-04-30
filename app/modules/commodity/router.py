"""commodity 模块 router。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.modules.commodity.schemas import (
    CommodityAliasReplaceRequest,
    CommodityAttributeReplaceRequest,
    CommodityMetadataResponse,
    CommodityRuleCodeReplaceRequest,
    CommodityStandardCreateRequest,
    CommodityStandardDetailResponse,
    CommodityStandardListQuery,
    CommodityStandardResponse,
    CommodityStandardUpdateRequest,
    PageResponse,
)
from app.modules.commodity.service import CommodityMetadataService, CommodityStandardService

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/metadata", response_model=CommodityMetadataResponse)
async def get_commodity_metadata(db: AsyncSession = Depends(get_db)):
    service = CommodityMetadataService(db)
    return await service.get_metadata()


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
