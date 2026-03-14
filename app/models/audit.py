"""审核记录数据模型"""
from sqlalchemy import (
    Column, BigInteger, Integer, String, Text, SmallInteger, DateTime, JSON
)
from sqlalchemy.sql import func
from app.core.database import Base


class AuditRecord(Base):
    """审核记录表 — 记录所有审核操作的完整历史"""
    __tablename__ = "audit_record"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 被审核对象
    target_type = Column(String(64), nullable=False,
                         comment="审核对象类型: TRANSPORT_NODE/COMMODITY_CATEGORY/"
                                 "COMMODITY_TYPE/COMMODITY_STANDARD/VESSEL/"
                                 "WATERWAY/REGION/NODE_TYPE/CARGO_OPPORTUNITY")
    target_id = Column(BigInteger, nullable=False, comment="被审核对象ID")
    target_name = Column(String(256), comment="被审核对象名称（快照）")
    # 审核动作
    action = Column(String(32), nullable=False,
                    comment="操作类型: CREATE/UPDATE/DISABLE/ENABLE/AI_CONFIRM")
    before_data = Column(JSON, comment="变更前数据快照")
    after_data = Column(JSON, comment="变更后数据快照（提交内容）")
    # 审核结果
    audit_result = Column(String(32), nullable=False,
                          comment="PENDING/APPROVED/REJECTED")
    audit_remark = Column(String(512), comment="审核意见")
    # 提交信息
    submitter_id = Column(BigInteger, nullable=False, comment="提交人ID")
    submitter_name = Column(String(64), comment="提交人姓名（快照）")
    submitted_at = Column(DateTime, server_default=func.now(), comment="提交时间")
    # 审核信息
    auditor_id = Column(BigInteger, comment="审核人ID")
    auditor_name = Column(String(64), comment="审核人姓名（快照）")
    audited_at = Column(DateTime, comment="审核时间")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
