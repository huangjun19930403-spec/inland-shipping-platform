"""commodity 模块 router。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.system import SysUser
from app.modules.commodity.schemas import (
    CommodityAliasReplaceRequest,
    CommodityAttributeReplaceRequest,
    CommodityDecisionRuleReplaceRequest,
    CommodityDefaultRuleReplaceRequest,
    CommodityMetadataResponse,
    CommodityStandardCreateRequest,
    CommodityStandardDetailResponse,
    CommodityStandardImageResponse,
    CommodityStandardImageUpdateRequest,
    CommodityStandardListQuery,
    CommodityStandardResponse,
    CommodityStandardUpdateRequest,
    PageResponse,
)
from app.modules.commodity.recognition.router import router as recognition_router
from app.modules.commodity.service import CommodityMetadataService, CommodityStandardService

router = APIRouter(dependencies=[Depends(get_current_user)])
router.include_router(recognition_router)


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
        category_id=query.category_id,
        type_id=query.type_id,
        keyword=query.keyword,
        status=query.status,
        main_unit_code=query.main_unit_code,
        cargo_form_code=query.cargo_form_code,
        is_bulk_cargo=query.is_bulk_cargo,
        is_container_suitable=query.is_container_suitable,
        is_hazardous=query.is_hazardous,
        source_type_code=query.source_type_code,
        has_alias=query.has_alias,
        has_image=query.has_image,
        used_by_freight=query.used_by_freight,
        page=query.page,
        page_size=query.page_size,
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
    body: CommodityDefaultRuleReplaceRequest,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityStandardService(db)
    await service.replace_packaging_forms(standard_id, body)
    return {"ok": True}


@router.put("/standards/{standard_id}/transport-modes")
async def replace_transport_modes(
    standard_id: int,
    body: CommodityDefaultRuleReplaceRequest,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityStandardService(db)
    await service.replace_transport_modes(standard_id, body)
    return {"ok": True}


@router.put("/standards/{standard_id}/ship-type-rules")
async def replace_ship_type_rules(
    standard_id: int,
    body: CommodityDecisionRuleReplaceRequest,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityStandardService(db)
    await service.replace_ship_type_rules(standard_id, body)
    return {"ok": True}


@router.put("/standards/{standard_id}/node-type-rules")
async def replace_node_type_rules(
    standard_id: int,
    body: CommodityDecisionRuleReplaceRequest,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityStandardService(db)
    await service.replace_node_type_rules(standard_id, body)
    return {"ok": True}


@router.put("/standards/{standard_id}/handling-mode-rules")
async def replace_handling_mode_rules(
    standard_id: int,
    body: CommodityDecisionRuleReplaceRequest,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityStandardService(db)
    await service.replace_handling_mode_rules(standard_id, body)
    return {"ok": True}


@router.get("/standards/{standard_id}/images", response_model=list[CommodityStandardImageResponse])
async def list_standard_images(
    standard_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityStandardService(db)
    return await service.list_images(standard_id)


@router.post("/standards/{standard_id}/images", response_model=CommodityStandardImageResponse)
async def create_standard_image(
    standard_id: int,
    image_type_code: str = Form(...),
    image_name: str | None = Form(default=None),
    description: str | None = Form(default=None),
    is_primary: bool = Form(default=False),
    sort_order: int = Form(default=0),
    file: UploadFile = File(...),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = CommodityStandardService(db)
    return await service.create_image(
        standard_id,
        file=file,
        image_type_code=image_type_code,
        image_name=image_name,
        description=description,
        is_primary=is_primary,
        sort_order=sort_order,
        uploaded_by=current_user.id,
    )


@router.put("/standards/{standard_id}/images/{image_id}", response_model=CommodityStandardImageResponse)
async def update_standard_image(
    standard_id: int,
    image_id: int,
    body: CommodityStandardImageUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityStandardService(db)
    return await service.update_image(standard_id, image_id, body)


@router.delete("/standards/{standard_id}/images/{image_id}")
async def delete_standard_image(
    standard_id: int,
    image_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = CommodityStandardService(db)
    await service.delete_image(standard_id, image_id)
    return {"ok": True}
