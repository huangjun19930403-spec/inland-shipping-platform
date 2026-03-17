"""
货品API路由层
职责：HTTP接入 — 仅负责参数验证、Service调用、响应格式化
规则：不包含业务逻辑，不直接操作数据库
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.core.security import get_current_user_roles, require_roles
from app.core.dependencies import get_cargo_service
from app.schemas.cargo import (
    CommodityCategoryCreate,
    CommodityTypeCreate,
    CommodityStandardCreate,
    CommodityAliasBody,
)
from app.schemas.common import success
from app.services.cargo_service import CargoService

router = APIRouter()


# ─────────────────────────────────────────────────
# 货品大类
# ─────────────────────────────────────────────────

@router.get("/commodity-category", summary="获取货品大类列表")
async def list_categories(
    service: CargoService = Depends(get_cargo_service),
    _=Depends(get_current_user_roles),
):
    items = await service.list_categories()
    return success(data=items)


@router.post("/commodity-category", summary="创建货品大类")
async def create_category(
    data: CommodityCategoryCreate,
    service: CargoService = Depends(get_cargo_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, _ = user_roles
    obj = await service.create_category(
        name=data.name,
        code=data.code,
        description=data.description,
        operator_id=user.id,
    )
    return success(data=obj)


# ─────────────────────────────────────────────────
# 货品类型
# ─────────────────────────────────────────────────

@router.get("/commodity-category/{category_id}/types", summary="获取货品类型列表")
async def list_types(
    category_id: int,
    service: CargoService = Depends(get_cargo_service),
    _=Depends(get_current_user_roles),
):
    items = await service.list_types_by_category(category_id)
    return success(data=items)


@router.post("/commodity-category/{category_id}/types", summary="创建货品类型")
async def create_type(
    category_id: int,
    data: CommodityTypeCreate,
    service: CargoService = Depends(get_cargo_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, _ = user_roles
    obj = await service.create_type(
        category_id=category_id,
        name=data.name,
        code=data.code,
        operator_id=user.id,
    )
    return success(data=obj)


# ─────────────────────────────────────────────────
# 标准货品
# ─────────────────────────────────────────────────

@router.get("/commodity/standards", summary="标准货品分页查询")
async def list_standards_paginated(
    type_id: Optional[int] = Query(None, description="货品类型ID"),
    keyword: Optional[str] = Query(None, description="名称关键词"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: CargoService = Depends(get_cargo_service),
    _=Depends(get_current_user_roles),
):
    result = await service.list_standards_paginated(
        type_id=type_id, keyword=keyword, page=page, page_size=page_size
    )
    return success(data=result)


@router.get("/commodity/standards/all", summary="获取所有标准货品（不分页）")
async def list_all_standards(
    type_id: Optional[int] = Query(None, description="货品类型ID"),
    service: CargoService = Depends(get_cargo_service),
    _=Depends(get_current_user_roles),
):
    items = await service.list_all_standards(type_id=type_id)
    return success(data=items)


@router.post("/commodity-type/{type_id}/standards", summary="创建标准货品")
async def create_standard(
    type_id: int,
    data: CommodityStandardCreate,
    service: CargoService = Depends(get_cargo_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, _ = user_roles
    obj = await service.create_standard(
        type_id=type_id,
        operator_id=user.id,
        **data.model_dump(),
    )
    return success(data=obj)


# ─────────────────────────────────────────────────
# 货品别名
# ─────────────────────────────────────────────────

@router.post("/commodity/standard/{standard_id}/aliases", summary="创建货品别名")
async def create_commodity_alias(
    standard_id: int,
    data: CommodityAliasBody,
    service: CargoService = Depends(get_cargo_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, _ = user_roles
    obj = await service.create_commodity_alias(
        standard_id=standard_id,
        operator_id=user.id,
        **data.model_dump(),
    )
    return success(data=obj)
