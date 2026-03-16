"""审核中心路由 — 使用 DI 模式调用 AuditService"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException

from app.core.dependencies import get_audit_service
from app.core.security import require_roles
from app.schemas.audit import (
    AuditRecordResponse,
    AuditTaskResponse,
    AuditTaskApproveRequest,
    AuditTaskRejectRequest,
    AuditActionRequest,
)
from app.schemas.common import success
from app.services.audit_service import AuditService

router = APIRouter()


# ─────────────────────────────────────────────────
# 审核任务（task-based，推荐使用）
# ─────────────────────────────────────────────────

@router.get("/tasks", summary="审核任务列表（分页）")
async def list_tasks(
    status: Optional[str] = Query(None, description="pending/approved/rejected"),
    target_type: Optional[str] = Query(None, description="目标类型筛选"),
    submitter_id: Optional[int] = Query(None, description="提交人筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: AuditService = Depends(get_audit_service),
    _=Depends(require_roles("ADMIN", "OPERATOR", "SUPER_ADMIN")),
):
    result = await service.list_all_tasks(
        status=status,
        target_type=target_type,
        submitter_id=submitter_id,
        page=page,
        page_size=page_size,
    )
    return success(data={
        "total": result["total"],
        "items": [AuditTaskResponse.model_validate(i) for i in result["items"]],
        "page": result["page"],
        "page_size": result["page_size"],
    })


@router.get("/tasks/pending", summary="待审核任务列表（分页）")
async def list_pending_tasks(
    target_type: Optional[str] = Query(None, description="筛选类型"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: AuditService = Depends(get_audit_service),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    result = await service.get_pending_tasks(
        target_type=target_type, page=page, page_size=page_size
    )
    return success(data={
        "total": result["total"],
        "items": [AuditTaskResponse.model_validate(i) for i in result["items"]],
        "page": result["page"],
        "page_size": result["page_size"],
    })


@router.post("/tasks/{task_id}/approve", summary="通过审核任务")
async def approve_task(
    task_id: int,
    body: AuditTaskApproveRequest,
    service: AuditService = Depends(get_audit_service),
    user_roles=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    user, roles = user_roles
    auditor_role = "SUPER_ADMIN" if "SUPER_ADMIN" in roles else "ADMIN"
    result = await service.approve_task(
        task_id=task_id,
        auditor_id=user.id,
        auditor_role=auditor_role,
        remark=body.remark,
    )
    return success(data=result, message="审核通过")


@router.post("/tasks/{task_id}/reject", summary="驳回审核任务")
async def reject_task(
    task_id: int,
    body: AuditTaskRejectRequest,
    service: AuditService = Depends(get_audit_service),
    user_roles=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    user, roles = user_roles
    auditor_role = "SUPER_ADMIN" if "SUPER_ADMIN" in roles else "ADMIN"
    result = await service.reject_task(
        task_id=task_id,
        auditor_id=user.id,
        auditor_role=auditor_role,
        remark=body.remark,
    )
    return success(data=result, message="已驳回")


# ─────────────────────────────────────────────────
# 审核历史（record-based）
# ─────────────────────────────────────────────────

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
    result = await service.list_records(
        status=audit_result,
        target_type=target_type,
        submitter_id=operator_id,
        page=page,
        page_size=page_size,
    )
    return success(data={
        "total": result["total"],
        "items": [AuditRecordResponse.model_validate(i) for i in result["items"]],
        "page": result["page"],
        "page_size": result["page_size"],
    })


@router.get("/stats", summary="各类待审核数量统计")
async def audit_stats(
    service: AuditService = Depends(get_audit_service),
    _=Depends(require_roles("ADMIN", "OPERATOR", "SUPER_ADMIN")),
):
    result = await service.get_stats()
    return success(data=result)


# ─────────────────────────────────────────────────
# 兼容旧接口（record_id-based，保持向后兼容）
# ─────────────────────────────────────────────────

@router.get("/pending", summary="待审核列表（旧接口，兼容）")
async def list_pending(
    target_type: Optional[str] = Query(None, description="筛选类型"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: AuditService = Depends(get_audit_service),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    result = await service.get_pending_tasks(
        target_type=target_type, page=page, page_size=page_size
    )
    return success(data={
        "total": result["total"],
        "items": [AuditTaskResponse.model_validate(i) for i in result["items"]],
        "page": result["page"],
        "page_size": result["page_size"],
    })


@router.post("/{audit_record_id}/approve", summary="审批通过（旧接口，兼容）")
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


@router.post("/{audit_record_id}/reject", summary="审核驳回（旧接口，兼容）")
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
