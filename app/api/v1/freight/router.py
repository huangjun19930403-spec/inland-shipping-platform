"""
货源API路由层
职责：HTTP接入 — 仅负责参数验证、Service调用、响应格式化
规则：不包含业务逻辑，不直接操作数据库
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, BackgroundTasks

from app.core.security import get_current_user_roles, require_roles
from app.core.dependencies import get_cargo_service
from app.schemas.cargo import (
    CargoRawMessageCreate,
    CargoConfirmRequest,
    CargoManualInput,
)
from app.schemas.common import success
from app.services.cargo_service import CargoService
from app.tasks.ai_tasks import trigger_cargo_parse

router = APIRouter()


# ─────────────────────────────────────────────────
# 货源文本提交（AI解析入口）
# ─────────────────────────────────────────────────

@router.post("/text", summary="提交货运文本（触发AI解析）")
async def submit_cargo_text(
    data: CargoRawMessageCreate,
    background_tasks: BackgroundTasks,
    service: CargoService = Depends(get_cargo_service),
    user_roles=Depends(require_roles("OPERATOR", "COLLECTOR")),
):
    """
    提交原始货运文本，后台触发AI解析工作流
    解析状态通过 GET /freight/text/{id} 查询
    """
    user, _ = user_roles
    saved = await service.submit_cargo_text(
        raw_text=data.raw_text,
        source_type=data.source_type,
        group_name=data.group_name,
        sender_name=data.sender_name,
        operator_id=user.id,
    )
    background_tasks.add_task(trigger_cargo_parse, saved.id)
    return success(data={"id": saved.id, "status": "PENDING", "message": "解析任务已提交"})


@router.get("/text/{msg_id}", summary="获取货运文本详情")
async def get_raw_message(
    msg_id: int,
    service: CargoService = Depends(get_cargo_service),
    _=Depends(get_current_user_roles),
):
    msg = await service.get_raw_message(msg_id)
    return success(data=msg)


@router.get("/text", summary="货运文本列表")
async def list_raw_messages(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: CargoService = Depends(get_cargo_service),
    user_roles=Depends(get_current_user_roles),
):
    user, _ = user_roles
    result = await service.list_raw_messages(
        status=status, operator_id=user.id, page=page, page_size=page_size
    )
    return success(data=result)


# ─────────────────────────────────────────────────
# AI解析结果
# ─────────────────────────────────────────────────

@router.get("/parse-result/{msg_id}", summary="获取AI解析结果")
async def get_parse_result(
    msg_id: int,
    service: CargoService = Depends(get_cargo_service),
    _=Depends(get_current_user_roles),
):
    result = await service.get_parse_result(msg_id)
    return success(data=result)


@router.post("/parse-result/{result_id}/confirm", summary="确认AI解析结果")
async def confirm_parse_result(
    result_id: int,
    data: CargoConfirmRequest,
    service: CargoService = Depends(get_cargo_service),
    user_roles=Depends(require_roles("OPERATOR", "ADMIN")),
):
    user, _ = user_roles
    opportunity = await service.confirm_parse_result(
        result_id=result_id,
        operator_id=user.id,
        overrides=data.model_dump(exclude_none=True),
    )
    return success(data={"opportunity_id": opportunity.id, "message": "确认成功"})


# ─────────────────────────────────────────────────
# 货源机会
# ─────────────────────────────────────────────────

@router.post("/opportunity", summary="手动录入货源信息")
async def create_opportunity(
    data: CargoManualInput,
    service: CargoService = Depends(get_cargo_service),
    user_roles=Depends(require_roles("OPERATOR", "COLLECTOR")),
):
    user, _ = user_roles
    opportunity = await service.create_manual_opportunity(
        origin_node_id=data.origin_node_id,
        dest_node_id=data.dest_node_id,
        commodity_id=data.commodity_id,
        tonnage=float(data.tonnage),
        loading_date=str(data.loading_date) if data.loading_date else None,
        freight_price=float(data.freight_price) if data.freight_price else None,
        price_type=data.price_type,
        price_unit=data.price_unit,
        contact_person=data.contact_person,
        contact_phone=data.contact_phone,
        source_type=data.source_type,
        remark=data.remark,
        operator_id=user.id,
    )
    return success(data=opportunity)


@router.get("/opportunity", summary="货源信息列表")
async def list_opportunities(
    status: Optional[str] = Query(None),
    origin_node_id: Optional[int] = Query(None),
    dest_node_id: Optional[int] = Query(None),
    commodity_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: CargoService = Depends(get_cargo_service),
    _=Depends(get_current_user_roles),
):
    result = await service.list_opportunities(
        status=status,
        origin_node_id=origin_node_id,
        dest_node_id=dest_node_id,
        commodity_id=commodity_id,
        page=page,
        page_size=page_size,
    )
    return success(data=result)
