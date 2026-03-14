from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime


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


class AuditActionRequest(BaseModel):
    audit_result: str  # APPROVED or REJECTED
    audit_remark: Optional[str] = None
