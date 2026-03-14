"""船舶服务 - 处理船舶档案、动态和历史记录"""
from typing import Optional, List
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from fastapi import HTTPException

from app.models.vessel import (
    Vessel, VesselTypeDict, VesselNameHistory, VesselAisHistory, VesselDynamic
)
from app.schemas.vessel import (
    VesselCreate, VesselUpdate, VesselDynamicUpdate,
    VesselTypeDictCreate, VesselTypeDictUpdate,
)
from app.schemas.common import PageResult
from app.services import audit_service


# ===== VesselTypeDict =====

async def get_vessel_types(db: AsyncSession, status: Optional[int] = None) -> List[VesselTypeDict]:
    query = select(VesselTypeDict)
    if status is not None:
        query = query.where(VesselTypeDict.status == status)
    query = query.order_by(VesselTypeDict.sort_order)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_vessel_type(db: AsyncSession, type_id: int) -> VesselTypeDict:
    result = await db.execute(select(VesselTypeDict).where(VesselTypeDict.id == type_id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="船舶类型不存在")
    return obj


async def create_vessel_type(
    db: AsyncSession, data: VesselTypeDictCreate, submitter_id: int, submitter_name: str
) -> VesselTypeDict:
    obj = VesselTypeDict(**data.model_dump(), audit_status=0, submitter_id=submitter_id)
    db.add(obj)
    await db.flush()
    await audit_service.create_audit_record(
        db=db,
        target_type="VESSEL_TYPE_DICT",
        target_id=obj.id,
        target_name=obj.name,
        action="CREATE",
        before_data=None,
        after_data=data.model_dump(),
        submitter_id=submitter_id,
        submitter_name=submitter_name,
    )
    return obj


async def update_vessel_type(
    db: AsyncSession, type_id: int, data: VesselTypeDictUpdate
) -> VesselTypeDict:
    obj = await get_vessel_type(db, type_id)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(obj, field, value)
    await db.flush()
    return obj


async def delete_vessel_type(db: AsyncSession, type_id: int) -> None:
    obj = await get_vessel_type(db, type_id)
    await db.delete(obj)
    await db.flush()


async def approve_vessel_type(
    db: AsyncSession, type_id: int, auditor_id: int, auditor_name: str, remark: str = ""
) -> VesselTypeDict:
    from app.models.audit import AuditRecord
    res = await db.execute(
        select(AuditRecord).where(
            and_(
                AuditRecord.target_type == "VESSEL_TYPE_DICT",
                AuditRecord.target_id == type_id,
                AuditRecord.audit_result == "PENDING",
            )
        ).order_by(AuditRecord.id.desc())
    )
    record = res.scalar_one_or_none()
    if record:
        await audit_service.approve(db, record.id, auditor_id, auditor_name, remark)
    else:
        obj = await get_vessel_type(db, type_id)
        obj.audit_status = 1
        obj.auditor_id = auditor_id
        await db.flush()
    return await get_vessel_type(db, type_id)


async def reject_vessel_type(
    db: AsyncSession, type_id: int, auditor_id: int, auditor_name: str, remark: str
) -> VesselTypeDict:
    from app.models.audit import AuditRecord
    res = await db.execute(
        select(AuditRecord).where(
            and_(
                AuditRecord.target_type == "VESSEL_TYPE_DICT",
                AuditRecord.target_id == type_id,
                AuditRecord.audit_result == "PENDING",
            )
        ).order_by(AuditRecord.id.desc())
    )
    record = res.scalar_one_or_none()
    if record:
        await audit_service.reject(db, record.id, auditor_id, auditor_name, remark)
    else:
        obj = await get_vessel_type(db, type_id)
        obj.audit_status = 2
        obj.auditor_id = auditor_id
        await db.flush()
    return await get_vessel_type(db, type_id)


# ===== Vessel =====

async def get_vessels(
    db: AsyncSession,
    audit_status: Optional[int] = None,
    vessel_type_id: Optional[int] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    query = select(Vessel).where(Vessel.is_deleted == 0)
    count_query = select(func.count(Vessel.id)).where(Vessel.is_deleted == 0)
    conditions = []
    if audit_status is not None:
        conditions.append(Vessel.audit_status == audit_status)
    if vessel_type_id:
        conditions.append(Vessel.vessel_type_id == vessel_type_id)
    if keyword:
        # Search current name; historical names handled separately if needed
        conditions.append(
            or_(
                Vessel.vessel_name.ilike(f"%{keyword}%"),
                Vessel.mmsi.ilike(f"%{keyword}%"),
                Vessel.vessel_no.ilike(f"%{keyword}%"),
            )
        )
    if conditions:
        query = query.where(and_(*conditions))
        count_query = count_query.where(and_(*conditions))

    total_res = await db.execute(count_query)
    total = total_res.scalar_one()
    query = query.order_by(Vessel.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return PageResult(total=total, items=list(result.scalars().all()), page=page, page_size=page_size)


async def get_vessel(db: AsyncSession, vessel_id: int) -> Vessel:
    result = await db.execute(
        select(Vessel).where(and_(Vessel.id == vessel_id, Vessel.is_deleted == 0))
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="船舶不存在")
    return obj


async def create_vessel(
    db: AsyncSession, data: VesselCreate, submitter_id: int, submitter_name: str
) -> Vessel:
    # Check duplicate vessel_no
    res = await db.execute(select(Vessel).where(Vessel.vessel_no == data.vessel_no))
    if res.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="船舶检验证书号已存在")

    vessel = Vessel(**data.model_dump(), audit_status=0, submitter_id=submitter_id)
    db.add(vessel)
    await db.flush()

    await audit_service.create_audit_record(
        db=db,
        target_type="VESSEL",
        target_id=vessel.id,
        target_name=vessel.vessel_name,
        action="CREATE",
        before_data=None,
        after_data=data.model_dump(),
        submitter_id=submitter_id,
        submitter_name=submitter_name,
    )
    return vessel


async def update_vessel(
    db: AsyncSession,
    vessel_id: int,
    data: VesselUpdate,
    operator_id: int,
    operator_name: str,
) -> Vessel:
    vessel = await get_vessel(db, vessel_id)
    updates = data.model_dump(exclude_none=True)
    change_reason = updates.pop("change_reason", None)

    # Handle vessel_name change
    if "vessel_name" in updates and updates["vessel_name"] != vessel.vessel_name:
        history = VesselNameHistory(
            vessel_id=vessel.id,
            old_name=vessel.vessel_name,
            new_name=updates["vessel_name"],
            change_reason=change_reason,
            changed_by=operator_id,
            changed_at=datetime.utcnow(),
        )
        db.add(history)

    # Handle mmsi change
    if "mmsi" in updates and updates["mmsi"] != vessel.mmsi:
        ais_history = VesselAisHistory(
            vessel_id=vessel.id,
            old_mmsi=vessel.mmsi or "",
            new_mmsi=updates["mmsi"],
            change_reason=change_reason,
            changed_by=operator_id,
            changed_at=datetime.utcnow(),
        )
        db.add(ais_history)

    for field, value in updates.items():
        setattr(vessel, field, value)

    await db.flush()
    return vessel


async def approve_vessel(
    db: AsyncSession, vessel_id: int, auditor_id: int, auditor_name: str, remark: str = ""
) -> Vessel:
    from app.models.audit import AuditRecord
    res = await db.execute(
        select(AuditRecord).where(
            and_(
                AuditRecord.target_type == "VESSEL",
                AuditRecord.target_id == vessel_id,
                AuditRecord.audit_result == "PENDING",
            )
        ).order_by(AuditRecord.id.desc())
    )
    record = res.scalar_one_or_none()
    if record:
        await audit_service.approve(db, record.id, auditor_id, auditor_name, remark)
    else:
        vessel = await get_vessel(db, vessel_id)
        vessel.audit_status = 1
        vessel.auditor_id = auditor_id
        await db.flush()
    return await get_vessel(db, vessel_id)


async def reject_vessel(
    db: AsyncSession, vessel_id: int, auditor_id: int, auditor_name: str, remark: str
) -> Vessel:
    from app.models.audit import AuditRecord
    res = await db.execute(
        select(AuditRecord).where(
            and_(
                AuditRecord.target_type == "VESSEL",
                AuditRecord.target_id == vessel_id,
                AuditRecord.audit_result == "PENDING",
            )
        ).order_by(AuditRecord.id.desc())
    )
    record = res.scalar_one_or_none()
    if record:
        await audit_service.reject(db, record.id, auditor_id, auditor_name, remark)
    else:
        vessel = await get_vessel(db, vessel_id)
        vessel.audit_status = 2
        vessel.audit_remark = remark
        vessel.auditor_id = auditor_id
        await db.flush()
    return await get_vessel(db, vessel_id)


async def delete_vessel(db: AsyncSession, vessel_id: int) -> None:
    vessel = await get_vessel(db, vessel_id)
    vessel.is_deleted = 1
    await db.flush()


async def get_vessel_history(db: AsyncSession, vessel_id: int) -> dict:
    """获取船舶的船名和 AIS 历史"""
    name_res = await db.execute(
        select(VesselNameHistory)
        .where(VesselNameHistory.vessel_id == vessel_id)
        .order_by(VesselNameHistory.changed_at.desc())
    )
    ais_res = await db.execute(
        select(VesselAisHistory)
        .where(VesselAisHistory.vessel_id == vessel_id)
        .order_by(VesselAisHistory.changed_at.desc())
    )
    return {
        "name_history": list(name_res.scalars().all()),
        "ais_history": list(ais_res.scalars().all()),
    }


async def update_vessel_dynamic(
    db: AsyncSession,
    vessel_id: int,
    data: VesselDynamicUpdate,
    operator_id: int,
) -> VesselDynamic:
    """UPSERT vessel dynamic - insert if not exists, update if exists"""
    result = await db.execute(
        select(VesselDynamic).where(VesselDynamic.vessel_id == vessel_id)
    )
    dynamic = result.scalar_one_or_none()

    if dynamic is None:
        dynamic = VesselDynamic(
            vessel_id=vessel_id,
            updated_by=operator_id,
            **data.model_dump(exclude_none=True),
        )
        db.add(dynamic)
    else:
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(dynamic, field, value)
        dynamic.updated_by = operator_id

    await db.flush()
    return dynamic


async def get_vessel_dynamic(db: AsyncSession, vessel_id: int) -> Optional[VesselDynamic]:
    result = await db.execute(
        select(VesselDynamic).where(VesselDynamic.vessel_id == vessel_id)
    )
    return result.scalar_one_or_none()


async def search_vessel(
    db: AsyncSession,
    keyword: str,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    """按当前船名和历史船名搜索"""
    # IDs from current name
    current_res = await db.execute(
        select(Vessel.id).where(
            and_(
                Vessel.vessel_name.ilike(f"%{keyword}%"),
                Vessel.is_deleted == 0,
            )
        )
    )
    current_ids = [row[0] for row in current_res.fetchall()]

    # IDs from historical names
    history_res = await db.execute(
        select(VesselNameHistory.vessel_id).where(
            VesselNameHistory.old_name.ilike(f"%{keyword}%")
        )
    )
    history_ids = [row[0] for row in history_res.fetchall()]

    all_ids = list(set(current_ids + history_ids))
    if not all_ids:
        return PageResult(total=0, items=[], page=page, page_size=page_size)

    total = len(all_ids)
    paged_ids = all_ids[(page - 1) * page_size: page * page_size]
    result = await db.execute(
        select(Vessel).where(and_(Vessel.id.in_(paged_ids), Vessel.is_deleted == 0))
    )
    return PageResult(total=total, items=list(result.scalars().all()), page=page, page_size=page_size)
