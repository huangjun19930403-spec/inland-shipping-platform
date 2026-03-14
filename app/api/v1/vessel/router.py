"""船舶路由"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_roles, require_roles
from app.schemas.vessel import (
    VesselTypeDictCreate, VesselTypeDictUpdate, VesselTypeDictResponse,
    VesselCreate, VesselUpdate, VesselResponse,
    VesselDynamicUpdate, VesselDynamicResponse,
    VesselNameHistoryResponse, VesselAisHistoryResponse,
)
from app.schemas.audit import AuditActionRequest
from app.schemas.common import success
from app.services import vessel_service

router = APIRouter()


# ===== VesselTypeDict =====

@router.get("/vessel-type", summary="获取船舶类型列表")
async def list_vessel_types(
    status: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    items = await vessel_service.get_vessel_types(db, status)
    return success(data=[VesselTypeDictResponse.model_validate(i) for i in items])


@router.post("/vessel-type", summary="创建船舶类型")
async def create_vessel_type(
    data: VesselTypeDictCreate,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, roles = user_roles
    obj = await vessel_service.create_vessel_type(db, data, user.id, user.real_name)
    await db.commit()
    await db.refresh(obj)
    return success(data=VesselTypeDictResponse.model_validate(obj))


@router.put("/vessel-type/{type_id}", summary="更新船舶类型")
async def update_vessel_type(
    type_id: int,
    data: VesselTypeDictUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR")),
):
    obj = await vessel_service.update_vessel_type(db, type_id, data)
    await db.commit()
    await db.refresh(obj)
    return success(data=VesselTypeDictResponse.model_validate(obj))


@router.delete("/vessel-type/{type_id}", summary="删除船舶类型")
async def delete_vessel_type(
    type_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN")),
):
    await vessel_service.delete_vessel_type(db, type_id)
    await db.commit()
    return success(message="删除成功")


@router.post("/vessel-type/{type_id}/approve", summary="审批通过船舶类型")
async def approve_vessel_type(
    type_id: int,
    data: AuditActionRequest,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    user, roles = user_roles
    obj = await vessel_service.approve_vessel_type(db, type_id, user.id, user.real_name, data.audit_remark or "")
    await db.commit()
    return success(data=VesselTypeDictResponse.model_validate(obj))


@router.post("/vessel-type/{type_id}/reject", summary="驳回船舶类型")
async def reject_vessel_type(
    type_id: int,
    data: AuditActionRequest,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    user, roles = user_roles
    if not data.audit_remark:
        raise HTTPException(status_code=400, detail="驳回必须填写审核意见")
    obj = await vessel_service.reject_vessel_type(db, type_id, user.id, user.real_name, data.audit_remark)
    await db.commit()
    return success(data=VesselTypeDictResponse.model_validate(obj))


# ===== Vessel =====

@router.get("/vessel", summary="获取船舶列表")
async def list_vessels(
    audit_status: Optional[int] = None,
    vessel_type_id: Optional[int] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    result = await vessel_service.get_vessels(db, audit_status, vessel_type_id, keyword, page, page_size)
    return success(data={
        "total": result.total,
        "items": [VesselResponse.model_validate(i) for i in result.items],
        "page": result.page,
        "page_size": result.page_size,
    })


@router.post("/vessel", summary="创建船舶（待审核）")
async def create_vessel(
    data: VesselCreate,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR", "COLLECTOR")),
):
    user, roles = user_roles
    obj = await vessel_service.create_vessel(db, data, user.id, user.real_name)
    await db.commit()
    await db.refresh(obj)
    return success(data=VesselResponse.model_validate(obj))


@router.get("/vessel/{vessel_id}", summary="获取船舶详情")
async def get_vessel(
    vessel_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    obj = await vessel_service.get_vessel(db, vessel_id)
    return success(data=VesselResponse.model_validate(obj))


@router.put("/vessel/{vessel_id}", summary="更新船舶")
async def update_vessel(
    vessel_id: int,
    data: VesselUpdate,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, roles = user_roles
    obj = await vessel_service.update_vessel(db, vessel_id, data, user.id, user.real_name)
    await db.commit()
    await db.refresh(obj)
    return success(data=VesselResponse.model_validate(obj))


@router.delete("/vessel/{vessel_id}", summary="删除船舶（软删除）")
async def delete_vessel(
    vessel_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN")),
):
    await vessel_service.delete_vessel(db, vessel_id)
    await db.commit()
    return success(message="删除成功")


@router.post("/vessel/{vessel_id}/approve", summary="审批通过船舶")
async def approve_vessel(
    vessel_id: int,
    data: AuditActionRequest,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    user, roles = user_roles
    vessel = await vessel_service.get_vessel(db, vessel_id)
    from app.services.audit_service import check_can_audit
    can = await check_can_audit(vessel.submitter_id or 0, user.id, roles)
    if not can:
        raise HTTPException(status_code=403, detail="提交人不能审核自己提交的内容")
    obj = await vessel_service.approve_vessel(db, vessel_id, user.id, user.real_name, data.audit_remark or "")
    await db.commit()
    return success(data=VesselResponse.model_validate(obj))


@router.post("/vessel/{vessel_id}/reject", summary="驳回船舶")
async def reject_vessel(
    vessel_id: int,
    data: AuditActionRequest,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    user, roles = user_roles
    if not data.audit_remark:
        raise HTTPException(status_code=400, detail="驳回必须填写审核意见")
    obj = await vessel_service.reject_vessel(db, vessel_id, user.id, user.real_name, data.audit_remark)
    await db.commit()
    return success(data=VesselResponse.model_validate(obj))


@router.get("/vessel/{vessel_id}/history", summary="获取船舶历史记录（船名和MMSI）")
async def get_vessel_history(
    vessel_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    history = await vessel_service.get_vessel_history(db, vessel_id)
    return success(data={
        "name_history": [VesselNameHistoryResponse.model_validate(i) for i in history["name_history"]],
        "ais_history": [VesselAisHistoryResponse.model_validate(i) for i in history["ais_history"]],
    })


@router.put("/vessel/{vessel_id}/dynamic", summary="更新船舶动态")
async def update_vessel_dynamic(
    vessel_id: int,
    data: VesselDynamicUpdate,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR", "COLLECTOR")),
):
    user, roles = user_roles
    obj = await vessel_service.update_vessel_dynamic(db, vessel_id, data, operator_id=user.id)
    await db.commit()
    await db.refresh(obj)
    return success(data=VesselDynamicResponse.model_validate(obj))


@router.get("/vessel/{vessel_id}/dynamic", summary="获取船舶最新动态")
async def get_vessel_dynamic(
    vessel_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    obj = await vessel_service.get_vessel_dynamic(db, vessel_id)
    if not obj:
        return success(data=None, message="暂无动态信息")
    return success(data=VesselDynamicResponse.model_validate(obj))
