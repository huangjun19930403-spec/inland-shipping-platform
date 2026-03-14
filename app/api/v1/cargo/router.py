"""货品和货源路由"""
from typing import Optional
from datetime import date
from fastapi import APIRouter, Depends, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_roles, require_roles
from app.schemas.cargo import (
    CommodityCategoryCreate, CommodityCategoryUpdate, CommodityCategoryResponse,
    CommodityTypeCreate, CommodityTypeUpdate, CommodityTypeResponse,
    CommodityStandardCreate, CommodityStandardUpdate, CommodityStandardResponse,
    CommodityAliasCreate, CommodityAliasResponse,
    CargoManualInput, CargoRawMessageCreate, CargoRawMessageResponse,
    CargoAiParseResultResponse, CargoOpportunityResponse, CargoConfirmRequest,
)
from app.schemas.audit import AuditActionRequest
from app.schemas.common import success
from app.services import cargo_service

router = APIRouter()


# ===== CommodityCategory =====

@router.get("/commodity-category", summary="获取货品大类列表")
async def list_categories(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    items = await cargo_service.get_categories(db)
    return success(data=[CommodityCategoryResponse.model_validate(i) for i in items])


@router.post("/commodity-category", summary="创建货品大类")
async def create_category(
    data: CommodityCategoryCreate,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, roles = user_roles
    obj = await cargo_service.create_category(db, data, user.id, user.real_name)
    await db.commit()
    await db.refresh(obj)
    return success(data=CommodityCategoryResponse.model_validate(obj))


@router.put("/commodity-category/{category_id}", summary="更新货品大类")
async def update_category(
    category_id: int,
    data: CommodityCategoryUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR")),
):
    obj = await cargo_service.update_category(db, category_id, data)
    await db.commit()
    await db.refresh(obj)
    return success(data=CommodityCategoryResponse.model_validate(obj))


@router.delete("/commodity-category/{category_id}", summary="删除货品大类")
async def delete_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN")),
):
    await cargo_service.delete_category(db, category_id)
    await db.commit()
    return success(message="删除成功")


@router.post("/commodity-category/{category_id}/approve", summary="审批通过货品大类")
async def approve_category(
    category_id: int,
    data: AuditActionRequest,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    user, roles = user_roles
    from app.models.audit import AuditRecord
    from sqlalchemy import select, and_
    res = await db.execute(
        select(AuditRecord).where(
            and_(
                AuditRecord.target_type == "COMMODITY_CATEGORY",
                AuditRecord.target_id == category_id,
                AuditRecord.audit_result == "PENDING",
            )
        ).order_by(AuditRecord.id.desc())
    )
    record = res.scalar_one_or_none()
    if record:
        from app.services import audit_service
        can = await audit_service.check_can_audit(record.submitter_id, user.id, roles)
        if not can:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="提交人不能审核自己提交的内容")
        await audit_service.approve(db, record.id, user.id, user.real_name, data.audit_remark or "")
    else:
        obj = await cargo_service.get_category(db, category_id)
        obj.audit_status = 1
        obj.auditor_id = user.id
    await db.commit()
    return success(message="审批通过")


@router.post("/commodity-category/{category_id}/reject", summary="驳回货品大类")
async def reject_category(
    category_id: int,
    data: AuditActionRequest,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    user, roles = user_roles
    if not data.audit_remark:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="驳回必须填写审核意见")
    from app.models.audit import AuditRecord
    from sqlalchemy import select, and_
    res = await db.execute(
        select(AuditRecord).where(
            and_(
                AuditRecord.target_type == "COMMODITY_CATEGORY",
                AuditRecord.target_id == category_id,
                AuditRecord.audit_result == "PENDING",
            )
        ).order_by(AuditRecord.id.desc())
    )
    record = res.scalar_one_or_none()
    if record:
        from app.services import audit_service
        await audit_service.reject(db, record.id, user.id, user.real_name, data.audit_remark)
    else:
        obj = await cargo_service.get_category(db, category_id)
        obj.audit_status = 2
        obj.auditor_id = user.id
    await db.commit()
    return success(message="已驳回")


# ===== CommodityType =====

@router.get("/commodity-type", summary="获取货品类型列表")
async def list_types(
    category_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    items = await cargo_service.get_types(db, category_id)
    return success(data=[CommodityTypeResponse.model_validate(i) for i in items])


@router.post("/commodity-type", summary="创建货品类型")
async def create_type(
    data: CommodityTypeCreate,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, roles = user_roles
    obj = await cargo_service.create_type(db, data, user.id, user.real_name)
    await db.commit()
    await db.refresh(obj)
    return success(data=CommodityTypeResponse.model_validate(obj))


@router.put("/commodity-type/{type_id}", summary="更新货品类型")
async def update_type(
    type_id: int,
    data: CommodityTypeUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR")),
):
    obj = await cargo_service.update_type(db, type_id, data)
    await db.commit()
    await db.refresh(obj)
    return success(data=CommodityTypeResponse.model_validate(obj))


@router.delete("/commodity-type/{type_id}", summary="删除货品类型")
async def delete_type(
    type_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN")),
):
    await cargo_service.delete_type(db, type_id)
    await db.commit()
    return success(message="删除成功")


# ===== CommodityStandard =====

@router.get("/commodity-standard", summary="获取标准货品列表")
async def list_standards(
    type_id: Optional[int] = None,
    audit_status: Optional[int] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    result = await cargo_service.get_standards(db, type_id, audit_status, keyword, page, page_size)
    return success(data={
        "total": result.total,
        "items": [CommodityStandardResponse.model_validate(i) for i in result.items],
        "page": result.page,
        "page_size": result.page_size,
    })


@router.post("/commodity-standard", summary="创建标准货品")
async def create_standard(
    data: CommodityStandardCreate,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, roles = user_roles
    obj = await cargo_service.create_standard(db, data, user.id, user.real_name)
    await db.commit()
    await db.refresh(obj)
    return success(data=CommodityStandardResponse.model_validate(obj))


@router.put("/commodity-standard/{standard_id}", summary="更新标准货品")
async def update_standard(
    standard_id: int,
    data: CommodityStandardUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR")),
):
    obj = await cargo_service.update_standard(db, standard_id, data)
    await db.commit()
    await db.refresh(obj)
    return success(data=CommodityStandardResponse.model_validate(obj))


@router.delete("/commodity-standard/{standard_id}", summary="删除标准货品")
async def delete_standard(
    standard_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN")),
):
    await cargo_service.delete_standard(db, standard_id)
    await db.commit()
    return success(message="删除成功")


@router.post("/commodity-standard/{standard_id}/approve", summary="审批通过标准货品")
async def approve_standard(
    standard_id: int,
    data: AuditActionRequest,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    user, roles = user_roles
    from app.models.audit import AuditRecord
    from sqlalchemy import select, and_
    res = await db.execute(
        select(AuditRecord).where(
            and_(
                AuditRecord.target_type == "COMMODITY_STANDARD",
                AuditRecord.target_id == standard_id,
                AuditRecord.audit_result == "PENDING",
            )
        ).order_by(AuditRecord.id.desc())
    )
    record = res.scalar_one_or_none()
    if record:
        from app.services import audit_service
        can = await audit_service.check_can_audit(record.submitter_id, user.id, roles)
        if not can:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="提交人不能审核自己提交的内容")
    obj = await cargo_service.approve_commodity(db, standard_id, user.id, user.real_name, data.audit_remark or "")
    await db.commit()
    return success(data=CommodityStandardResponse.model_validate(obj))


@router.post("/commodity-standard/{standard_id}/reject", summary="驳回标准货品")
async def reject_standard(
    standard_id: int,
    data: AuditActionRequest,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    user, roles = user_roles
    if not data.audit_remark:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="驳回必须填写审核意见")
    obj = await cargo_service.reject_commodity(db, standard_id, user.id, user.real_name, data.audit_remark)
    await db.commit()
    return success(data=CommodityStandardResponse.model_validate(obj))


# ===== CommodityAlias =====

@router.post("/commodity-alias", summary="添加货品别名")
async def add_commodity_alias(
    data: CommodityAliasCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR")),
):
    obj = await cargo_service.add_commodity_alias(db, data)
    await db.commit()
    await db.refresh(obj)
    return success(data=CommodityAliasResponse.model_validate(obj))


@router.delete("/commodity-alias/{alias_id}", summary="删除货品别名")
async def delete_commodity_alias(
    alias_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR")),
):
    await cargo_service.delete_commodity_alias(db, alias_id)
    await db.commit()
    return success(message="删除成功")


# ===== Cargo =====

@router.post("/cargo/manual", summary="手动录入货源")
async def create_cargo_manual(
    data: CargoManualInput,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR", "COLLECTOR")),
):
    user, roles = user_roles
    obj = await cargo_service.create_cargo_manual(db, data, collector_id=user.id)
    await db.commit()
    await db.refresh(obj)
    return success(data=CargoOpportunityResponse.model_validate(obj))


@router.post("/cargo/text", summary="粘贴文本触发AI解析")
async def create_cargo_text(
    data: CargoRawMessageCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR", "COLLECTOR")),
):
    """
    粘贴原始货源文本，系统自动调用 Claude AI 解析，结果异步返回。
    解析完成后通过 GET /ai/parse-status/{id} 查看结果。
    """
    user, roles = user_roles
    obj = await cargo_service.create_cargo_text(db, data, collector_id=user.id)
    await db.commit()
    raw_id = obj.id

    # 后台异步执行AI解析（不阻塞HTTP响应）
    async def _run_ai_parse(raw_message_id: int):
        from app.core.database import AsyncSessionLocal
        from app.ai_engine.parser import parse_cargo_text
        async with AsyncSessionLocal() as bg_db:
            try:
                await parse_cargo_text(bg_db, raw_message_id)
                await bg_db.commit()
            except Exception as e:
                import logging
                logging.getLogger("inland.ai").error(f"AI解析失败 raw_id={raw_message_id}: {e}")
                await bg_db.rollback()

    background_tasks.add_task(_run_ai_parse, raw_id)
    await db.refresh(obj)
    return success(data=CargoRawMessageResponse.model_validate(obj), message="已提交，AI解析正在后台进行中")


@router.get("/cargo", summary="获取货源列表")
async def list_cargo(
    status: Optional[str] = None,
    origin_region_id: Optional[int] = None,
    dest_region_id: Optional[int] = None,
    commodity_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    result = await cargo_service.get_cargo_opportunities(
        db, status, origin_region_id, dest_region_id, commodity_id, start_date, end_date, page, page_size
    )
    return success(data={
        "total": result.total,
        "items": [CargoOpportunityResponse.model_validate(i) for i in result.items],
        "page": result.page,
        "page_size": result.page_size,
    })


@router.get("/cargo/ai-results", summary="获取AI解析结果列表")
async def list_ai_results(
    parse_status: Optional[str] = "PENDING_CONFIRM",
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    result = await cargo_service.get_ai_parse_results(db, parse_status, page, page_size)
    return success(data={
        "total": result.total,
        "items": [CargoAiParseResultResponse.model_validate(i) for i in result.items],
        "page": result.page,
        "page_size": result.page_size,
    })


@router.post("/cargo/ai-results/{parse_result_id}/confirm", summary="确认AI解析结果")
async def confirm_ai_result(
    parse_result_id: int,
    data: CargoConfirmRequest,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR", "COLLECTOR")),
):
    user, roles = user_roles
    obj = await cargo_service.confirm_cargo_ai(db, parse_result_id, data, user_id=user.id)
    await db.commit()
    await db.refresh(obj)
    return success(data=CargoOpportunityResponse.model_validate(obj))


@router.post("/cargo/ai-results/{parse_result_id}/discard", summary="废弃AI解析结果")
async def discard_ai_result(
    parse_result_id: int,
    reason: Optional[str] = Query(None, description="废弃原因"),
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR", "COLLECTOR")),
):
    user, roles = user_roles
    obj = await cargo_service.discard_cargo_ai(db, parse_result_id, reason, user_id=user.id)
    await db.commit()
    return success(data=CargoAiParseResultResponse.model_validate(obj))


@router.get("/cargo/{cargo_id}", summary="获取货源详情")
async def get_cargo(
    cargo_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    obj = await cargo_service.get_cargo_opportunity(db, cargo_id)
    return success(data=CargoOpportunityResponse.model_validate(obj))


@router.delete("/cargo/{cargo_id}", summary="取消货源")
async def cancel_cargo(
    cargo_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR", "COLLECTOR")),
):
    obj = await cargo_service.cancel_cargo(db, cargo_id)
    await db.commit()
    return success(data=CargoOpportunityResponse.model_validate(obj), message="已取消")
