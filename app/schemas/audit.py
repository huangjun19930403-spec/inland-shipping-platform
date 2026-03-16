from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime


# ─────────────────────────────────────────────────
# AuditRecord — 审核记录日志（不可变历史）
# ─────────────────────────────────────────────────

class AuditRecordResponse(BaseModel):
    id: int
    target_type: str
    target_id: int
    target_name: Optional[str] = None
    action: str
    before_data: Optional[Any] = None
    after_data: Optional[Any] = None
    audit_result: str
    audit_remark: Optional[str] = None
    submitter_id: int
    submitter_name: Optional[str] = None
    submitted_at: Optional[datetime] = None
    auditor_id: Optional[int] = None
    auditor_name: Optional[str] = None
    audited_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────
# AuditTask — 审核任务工单
# ─────────────────────────────────────────────────

class AuditTaskResponse(BaseModel):
    id: int
    target_type: str
    target_id: int
    target_name: Optional[str] = None
    action: str
    status: str  # pending / approved / rejected
    submitter_id: int
    submit_time: Optional[datetime] = None
    auditor_id: Optional[int] = None
    audit_time: Optional[datetime] = None
    remark: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AuditTaskApproveRequest(BaseModel):
    remark: Optional[str] = Field(None, description="审核备注（可选）")


class AuditTaskRejectRequest(BaseModel):
    remark: str = Field(..., min_length=1, description="驳回原因（必填）")


# ─────────────────────────────────────────────────
# 通用审核动作请求（兼容旧接口）
# ─────────────────────────────────────────────────

class AuditActionRequest(BaseModel):
    """兼容旧版 /audit/{record_id}/approve 和 /audit/{record_id}/reject 接口"""
    audit_remark: Optional[str] = Field(None, description="审核意见")
