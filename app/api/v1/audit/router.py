"""审核中心路由 — 使用 DI 模式调用 AuditService"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.core.database import get_db
from app.core.dependencies import get_audit_service
from app.core.security import get_current_user_roles, require_roles
from app.models.audit import AuditRecord
from app.schemas.audit import AuditRecordResponse, AuditActionRequest
from app.schemas.common import success
from app.services.audit_service import AuditService

router = APIRouter()


@router.get("/pending", summary="待审核列表（分页）")
async def list_pending(
    target_type: Optional[str] = Query(None, description="筛选类型"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: AuditService = Depends(get_audit_service),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    result = await service.list_pending(
        target_type=target_type, page=page, page_size=page_size
    )
    return success(data={
        "total": result["total"],
        "items": [AuditRecordResponse.model_validate(i) for i in result["items"]],
        "page": result["page"],
        "page_size": result["page_size"],
    })


@router.get("/history", summary="审核历史（分页）")
async def list_history(
    target_type: Optional[str] = Query(None),
    target_id: Optional[int] = Query(None),
    audit_result: Optional[str] = Query(None),
    operator_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: AuditService = Depends(get_audit_service),
    _=Depends(require_roles("ADMIN", "OPERATOR", "SUPER_ADMIN")),
):
    result = await service.list_all(
        status=audit_result,
        target_type=target_type,
        operator_id=operator_id,
        page=page,
        page_size=page_size,
    )
    return success(data={
        "total": result["total"],
        "items": [AuditRecordResponse.model_validate(i) for i in result["items"]],
        "page": result["page"],
        "page_size": result["page_size"],
    })


@router.post("/{audit_record_id}/approve", summary="审批通过")
async def approve_audit(
    audit_record_id: int,
    body: AuditActionRequest,
    service: AuditService = Depends(get_audit_service),
    user_roles=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    user, roles = user_roles
    auditor_role = "SUPER_ADMIN" if "SUPER_ADMIN" in roles else "ADMIN"
    result = await service.approve(
        record_id=audit_record_id,
        auditor_id=user.id,
        auditor_role=auditor_role,
        comment=body.audit_remark,
    )
    return success(data=result, message="审核通过")


@router.post("/{audit_record_id}/reject", summary="审核驳回")
async def reject_audit(
    audit_record_id: int,
    body: AuditActionRequest,
    service: AuditService = Depends(get_audit_service),
    user_roles=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    if not body.audit_remark:
        raise HTTPException(status_code=400, detail="驳回时必须填写驳回意见")
    user, roles = user_roles
    auditor_role = "SUPER_ADMIN" if "SUPER_ADMIN" in roles else "ADMIN"
    result = await service.reject(
        record_id=audit_record_id,
        auditor_id=user.id,
        auditor_role=auditor_role,
        reason=body.audit_remark,
    )
    return success(data=result, message="已驳回")


@router.get("/stats", summary="各类待审核数量统计")
async def audit_stats(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR", "SUPER_ADMIN")),
):
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
