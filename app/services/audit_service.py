"""审核服务 - 统一处理所有审核流程"""
from typing import Optional, List
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from fastapi import HTTPException, status

from app.models.audit import AuditRecord
from app.schemas.common import PageResult


async def create_audit_record(
    db: AsyncSession,
    target_type: str,
    target_id: int,
    target_name: str,
    action: str,
    before_data: Optional[dict],
    after_data: Optional[dict],
    submitter_id: int,
    submitter_name: str,
) -> AuditRecord:
    """创建一条审核记录"""
    record = AuditRecord(
        target_type=target_type,
        target_id=target_id,
        target_name=target_name,
        action=action,
        before_data=before_data,
        after_data=after_data,
        audit_result="PENDING",
        submitter_id=submitter_id,
        submitter_name=submitter_name,
        submitted_at=datetime.utcnow(),
    )
    db.add(record)
    await db.flush()
    return record


async def check_can_audit(submitter_id: int, auditor_id: int, user_roles: List[str]) -> bool:
    """检查是否可以审核：SUPER_ADMIN 可以自审，其他人不能审核自己提交的"""
    if "SUPER_ADMIN" in user_roles:
        return True
    if submitter_id == auditor_id:
        return False
    return True


async def approve(
    db: AsyncSession,
    audit_record_id: int,
    auditor_id: int,
    auditor_name: str,
    remark: str = "",
) -> AuditRecord:
    """审批通过"""
    result = await db.execute(select(AuditRecord).where(AuditRecord.id == audit_record_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="审核记录不存在")
    if record.audit_result != "PENDING":
        raise HTTPException(status_code=400, detail="该审核记录已处理")

    record.audit_result = "APPROVED"
    record.auditor_id = auditor_id
    record.auditor_name = auditor_name
    record.audit_remark = remark
    record.audited_at = datetime.utcnow()

    # 根据审核类型更新对应实体
    await _apply_approval(db, record)

    await db.flush()
    return record


async def reject(
    db: AsyncSession,
    audit_record_id: int,
    auditor_id: int,
    auditor_name: str,
    remark: str,
) -> AuditRecord:
    """审批驳回"""
    result = await db.execute(select(AuditRecord).where(AuditRecord.id == audit_record_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="审核记录不存在")
    if record.audit_result != "PENDING":
        raise HTTPException(status_code=400, detail="该审核记录已处理")

    record.audit_result = "REJECTED"
    record.auditor_id = auditor_id
    record.auditor_name = auditor_name
    record.audit_remark = remark
    record.audited_at = datetime.utcnow()

    # 根据类型更新对应实体的审核状态
    await _apply_rejection(db, record)

    await db.flush()
    return record


async def _apply_approval(db: AsyncSession, record: AuditRecord) -> None:
    """审批通过后更新对应实体，并执行附加操作（自动建别名等）"""
    target_type = record.target_type
    target_id = record.target_id

    if target_type == "TRANSPORT_NODE":
        from app.models.address import TransportNode, NodeAlias
        res = await db.execute(select(TransportNode).where(TransportNode.id == target_id))
        node = res.scalar_one_or_none()
        if node:
            node.audit_status = 1
            node.auditor_id = record.auditor_id
            # 自动创建标准名别名（如不存在）
            alias_res = await db.execute(
                select(NodeAlias).where(
                    and_(NodeAlias.node_id == target_id, NodeAlias.alias_name == node.name)
                )
            )
            if not alias_res.scalar_one_or_none():
                alias = NodeAlias(
                    node_id=target_id,
                    alias_name=node.name,
                    alias_type="SYSTEM",
                    priority=100,
                    status=1,
                )
                db.add(alias)

    elif target_type == "COMMODITY_STANDARD":
        from app.models.cargo import CommodityStandard, CommodityAlias
        res = await db.execute(select(CommodityStandard).where(CommodityStandard.id == target_id))
        commodity = res.scalar_one_or_none()
        if commodity:
            commodity.audit_status = 1
            commodity.auditor_id = record.auditor_id
            # 自动创建标准名别名
            alias_res = await db.execute(
                select(CommodityAlias).where(
                    and_(
                        CommodityAlias.commodity_id == target_id,
                        CommodityAlias.alias_name == commodity.name,
                    )
                )
            )
            if not alias_res.scalar_one_or_none():
                alias = CommodityAlias(
                    commodity_id=target_id,
                    alias_name=commodity.name,
                    alias_type="SYSTEM",
                    priority=100,
                    status=1,
                )
                db.add(alias)

    elif target_type == "COMMODITY_CATEGORY":
        from app.models.cargo import CommodityCategory
        res = await db.execute(select(CommodityCategory).where(CommodityCategory.id == target_id))
        obj = res.scalar_one_or_none()
        if obj:
            obj.audit_status = 1
            obj.auditor_id = record.auditor_id

    elif target_type == "COMMODITY_TYPE":
        from app.models.cargo import CommodityType
        res = await db.execute(select(CommodityType).where(CommodityType.id == target_id))
        obj = res.scalar_one_or_none()
        if obj:
            obj.audit_status = 1
            obj.auditor_id = record.auditor_id

    elif target_type == "VESSEL":
        from app.models.vessel import Vessel
        res = await db.execute(select(Vessel).where(Vessel.id == target_id))
        vessel = res.scalar_one_or_none()
        if vessel:
            vessel.audit_status = 1
            vessel.auditor_id = record.auditor_id

    elif target_type == "VESSEL_TYPE_DICT":
        from app.models.vessel import VesselTypeDict
        res = await db.execute(select(VesselTypeDict).where(VesselTypeDict.id == target_id))
        obj = res.scalar_one_or_none()
        if obj:
            obj.audit_status = 1
            obj.auditor_id = record.auditor_id

    elif target_type == "WATERWAY":
        from app.models.address import Waterway
        res = await db.execute(select(Waterway).where(Waterway.id == target_id))
        obj = res.scalar_one_or_none()
        if obj:
            obj.status = 1  # waterway doesn't have audit_status, enable on approve

    elif target_type == "REGION":
        from app.models.address import Region
        res = await db.execute(select(Region).where(Region.id == target_id))
        obj = res.scalar_one_or_none()
        if obj:
            obj.status = 1

    elif target_type == "NODE_TYPE":
        from app.models.address import NodeType
        res = await db.execute(select(NodeType).where(NodeType.id == target_id))
        obj = res.scalar_one_or_none()
        if obj:
            obj.status = 1


async def _apply_rejection(db: AsyncSession, record: AuditRecord) -> None:
    """审批驳回后更新对应实体的审核状态"""
    target_type = record.target_type
    target_id = record.target_id

    if target_type == "TRANSPORT_NODE":
        from app.models.address import TransportNode
        res = await db.execute(select(TransportNode).where(TransportNode.id == target_id))
        node = res.scalar_one_or_none()
        if node:
            node.audit_status = 2
            node.audit_remark = record.audit_remark
            node.auditor_id = record.auditor_id

    elif target_type == "COMMODITY_STANDARD":
        from app.models.cargo import CommodityStandard
        res = await db.execute(select(CommodityStandard).where(CommodityStandard.id == target_id))
        obj = res.scalar_one_or_none()
        if obj:
            obj.audit_status = 2
            obj.audit_remark = record.audit_remark
            obj.auditor_id = record.auditor_id

    elif target_type == "COMMODITY_CATEGORY":
        from app.models.cargo import CommodityCategory
        res = await db.execute(select(CommodityCategory).where(CommodityCategory.id == target_id))
        obj = res.scalar_one_or_none()
        if obj:
            obj.audit_status = 2
            obj.auditor_id = record.auditor_id

    elif target_type == "COMMODITY_TYPE":
        from app.models.cargo import CommodityType
        res = await db.execute(select(CommodityType).where(CommodityType.id == target_id))
        obj = res.scalar_one_or_none()
        if obj:
            obj.audit_status = 2
            obj.auditor_id = record.auditor_id

    elif target_type == "VESSEL":
        from app.models.vessel import Vessel
        res = await db.execute(select(Vessel).where(Vessel.id == target_id))
        vessel = res.scalar_one_or_none()
        if vessel:
            vessel.audit_status = 2
            vessel.audit_remark = record.audit_remark
            vessel.auditor_id = record.auditor_id

    elif target_type == "VESSEL_TYPE_DICT":
        from app.models.vessel import VesselTypeDict
        res = await db.execute(select(VesselTypeDict).where(VesselTypeDict.id == target_id))
        obj = res.scalar_one_or_none()
        if obj:
            obj.audit_status = 2
            obj.auditor_id = record.auditor_id


async def get_pending_audits(
    db: AsyncSession,
    target_type: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    """获取待审核列表"""
    query = select(AuditRecord).where(AuditRecord.audit_result == "PENDING")
    count_query = select(func.count(AuditRecord.id)).where(AuditRecord.audit_result == "PENDING")

    if target_type:
        query = query.where(AuditRecord.target_type == target_type)
        count_query = count_query.where(AuditRecord.target_type == target_type)

    total_res = await db.execute(count_query)
    total = total_res.scalar_one()

    query = query.order_by(AuditRecord.submitted_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()

    return PageResult(total=total, items=list(items), page=page, page_size=page_size)


async def get_audit_history(
    db: AsyncSession,
    target_type: str,
    target_id: int,
) -> List[AuditRecord]:
    """获取特定对象的审核历史"""
    result = await db.execute(
        select(AuditRecord)
        .where(
            and_(
                AuditRecord.target_type == target_type,
                AuditRecord.target_id == target_id,
            )
        )
        .order_by(AuditRecord.created_at.desc())
    )
    return list(result.scalars().all())


async def get_pending_counts_by_type(db: AsyncSession) -> dict:
    """按类型统计待审核数量"""
    result = await db.execute(
        select(AuditRecord.target_type, func.count(AuditRecord.id))
        .where(AuditRecord.audit_result == "PENDING")
        .group_by(AuditRecord.target_type)
    )
    rows = result.fetchall()
    return {row[0]: row[1] for row in rows}
