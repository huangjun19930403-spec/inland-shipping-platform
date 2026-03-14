"""审核中心路由"""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.core.database import get_db
from app.core.security import get_current_user_roles, require_roles
from app.models.audit import AuditRecord
from app.schemas.audit import AuditRecordResponse, AuditActionRequest
from app.schemas.common import success, PageResult
from app.services import audit_service

router = APIRouter()


@router.get("/pending", summary="待审核列表（分页）")
async def list_pending(
    target_type: Optional[str] = Query(None, description="筛选类型：TRANSPORT_NODE/VESSEL/COMMODITY_STANDARD等"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    """获取所有待审核记录（分页）"""
    result = await audit_service.get_pending_audits(
        db, target_type=target_type, page=page, page_size=page_size
    )
    return success(data={
        "total": result.total,
        "items": [AuditRecordResponse.model_validate(i) for i in result.items],
        "page": result.page,
        "page_size": result.page_size,
    })


@router.get("/history", summary="审核历史（分页）")
async def list_history(
    target_type: Optional[str] = Query(None),
    target_id: Optional[int] = Query(None),
    audit_result: Optional[str] = Query(None, description="PENDING/APPROVED/REJECTED"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR", "SUPER_ADMIN")),
):
    """审核操作历史记录，支持按对象类型/ID/结果筛选"""
    conditions = []
    if target_type:
        conditions.append(AuditRecord.target_type == target_type)
    if target_id:
        conditions.append(AuditRecord.target_id == target_id)
    if audit_result:
        conditions.append(AuditRecord.audit_result == audit_result)

    count_q = select(func.count(AuditRecord.id))
    list_q = select(AuditRecord)
    if conditions:
        count_q = count_q.where(and_(*conditions))
        list_q = list_q.where(and_(*conditions))

    total = (await db.execute(count_q)).scalar_one()
    records = list((await db.execute(
        list_q.order_by(AuditRecord.submitted_at.desc())
              .offset((page - 1) * page_size)
              .limit(page_size)
    )).scalars().all())

    return success(data={
        "total": total,
        "items": [AuditRecordResponse.model_validate(r) for r in records],
        "page": page,
        "page_size": page_size,
    })


@router.post("/{audit_record_id}/approve", summary="审批通过")
async def approve_audit(
    audit_record_id: int,
    body: AuditActionRequest,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    """通过审核，同时更新被审核对象的 audit_status"""
    user, roles = user_roles
    record = await audit_service.approve(
        db,
        audit_record_id=audit_record_id,
        auditor_id=user.id,
        auditor_name=user.real_name,
        remark=body.audit_remark or "",
    )
    await db.commit()
    return success(data=AuditRecordResponse.model_validate(record), message="审核通过")


@router.post("/{audit_record_id}/reject", summary="审核驳回")
async def reject_audit(
    audit_record_id: int,
    body: AuditActionRequest,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    """驳回审核，必须填写驳回意见"""
    if not body.audit_remark:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="驳回时必须填写驳回意见")
    user, roles = user_roles
    record = await audit_service.reject(
        db,
        audit_record_id=audit_record_id,
        auditor_id=user.id,
        auditor_name=user.real_name,
        remark=body.audit_remark,
    )
    await db.commit()
    return success(data=AuditRecordResponse.model_validate(record), message="已驳回")


@router.get("/stats", summary="各类待审核数量统计")
async def audit_stats(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR", "SUPER_ADMIN")),
):
    """
    返回各对象类型的待审核数量，用于首页看板快捷显示。
    """
    types = [
        "TRANSPORT_NODE", "VESSEL", "COMMODITY_STANDARD",
        "COMMODITY_CATEGORY", "COMMODITY_TYPE", "WATERWAY",
    ]
    result = {}
    for t in types:
        count = (await db.execute(
            select(func.count(AuditRecord.id)).where(
                and_(AuditRecord.target_type == t, AuditRecord.audit_result == "PENDING")
            )
        )).scalar_one()
        result[t] = count
    result["TOTAL"] = sum(result.values())
    return success(data=result)
