"""
货源API路由层
职责：HTTP接入 — 仅负责参数验证、Service调用、响应格式化
规则：不包含业务逻辑，不直接操作数据库
"""
from datetime import date
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
from app.tasks.stat_tasks import refresh_cargo_stats

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
    提交原始货运文本，后台触发AI解析工作流。
    解析状态通过 GET /freight/text/{id} 查询。
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
    background_tasks: BackgroundTasks,
    service: CargoService = Depends(get_cargo_service),
    user_roles=Depends(require_roles("OPERATOR", "ADMIN")),
):
    """
    人工确认AI解析结果，写入 cargo_freight 货源记录。
    确认后触发当日统计刷新（事件驱动）。
    """
    user, _ = user_roles
    freight = await service.confirm_parse_result(
        result_id=result_id,
        operator_id=user.id,
        overrides=data.model_dump(exclude_none=True),
    )
    background_tasks.add_task(refresh_cargo_stats, date.today())
    return success(data={"freight_id": freight.id, "freight_no": freight.freight_no, "message": "确认成功"})


# ─────────────────────────────────────────────────
# 货源主记录（CargoFreight）
# ─────────────────────────────────────────────────

@router.post("/freight", summary="手动录入货源信息")
async def create_freight(
    data: CargoManualInput,
    background_tasks: BackgroundTasks,
    service: CargoService = Depends(get_cargo_service),
    user_roles=Depends(require_roles("OPERATOR", "COLLECTOR")),
):
    """
    手动录入货源（MANUAL渠道），支持节点级或城市级位置。
    录入后触发当日统计刷新。
    """
    user, _ = user_roles
    freight = await service.create_manual_freight(
        operator_id=user.id,
        origin_node_id=data.origin_node_id,
        origin_admin_code=data.origin_admin_code,
        origin_admin_name=data.origin_admin_name,
        origin_raw_text=data.origin_raw_text,
        dest_node_id=data.dest_node_id,
        dest_admin_code=data.dest_admin_code,
        dest_admin_name=data.dest_admin_name,
        dest_raw_text=data.dest_raw_text,
        commodity_id=data.commodity_id,
        commodity_text=data.commodity_text,
        tonnage=float(data.tonnage) if data.tonnage else None,
        loading_date=str(data.loading_date) if data.loading_date else None,
        freight_price=float(data.freight_price) if data.freight_price else None,
        price_type=data.price_type,
        price_unit=data.price_unit,
        contact_person=data.contact_person,
        contact_phone=data.contact_phone,
        source_type=data.source_type,
        source_message_time=data.source_message_time,
        remark=data.remark,
    )
    background_tasks.add_task(refresh_cargo_stats, date.today())
    return success(data=freight)


@router.get("/freight/{freight_id}", summary="获取货源详情")
async def get_freight(
    freight_id: int,
    service: CargoService = Depends(get_cargo_service),
    _=Depends(get_current_user_roles),
):
    freight = await service.get_freight(freight_id)
    return success(data=freight)


@router.get("/freight", summary="货源列表")
async def list_freights(
    status: Optional[str] = Query(None, description="PENDING/CONFIRMED/CANCELLED/EXPIRED"),
    source_type: Optional[str] = Query(None, description="TMS/WECHAT_AI/MANUAL"),
    analysis_status: Optional[str] = Query(None, description="PENDING/READY/ANALYZED/FAILED"),
    location_match_level: Optional[str] = Query(None, description="NODE/CITY/REGION/UNKNOWN"),
    origin_admin_code: Optional[str] = Query(None, description="装货城市行政区划代码"),
    dest_admin_code: Optional[str] = Query(None, description="卸货城市行政区划代码"),
    commodity_id: Optional[int] = Query(None),
    stat_date: Optional[date] = Query(None, description="按创建日期过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: CargoService = Depends(get_cargo_service),
    _=Depends(get_current_user_roles),
):
    result = await service.list_freights(
        status=status,
        source_type=source_type,
        analysis_status=analysis_status,
        location_match_level=location_match_level,
        origin_admin_code=origin_admin_code,
        dest_admin_code=dest_admin_code,
        commodity_id=commodity_id,
        stat_date=stat_date,
        page=page,
        page_size=page_size,
    )
    return success(data=result)
