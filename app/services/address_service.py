"""地址服务 - 处理水系、区域、节点等地址体系"""
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_
from sqlalchemy.orm import selectinload
from fastapi import HTTPException

from app.models.address import (
    Waterway, Region, AdminRegion, NodeType,
    TransportNode, NodeAlias, RegionAddressRelation,
)
from app.schemas.address import (
    WaterwayCreate, WaterwayUpdate,
    RegionCreate, RegionUpdate,
    AdminRegionCreate, AdminRegionUpdate,
    NodeTypeCreate, NodeTypeUpdate,
    TransportNodeCreate, TransportNodeUpdate,
    NodeAliasCreate,
)
from app.schemas.common import PageResult
from app.services import audit_service


# ===== Waterway =====

async def get_waterways(db: AsyncSession, status: Optional[int] = None) -> List[Waterway]:
    query = select(Waterway)
    if status is not None:
        query = query.where(Waterway.status == status)
    query = query.order_by(Waterway.sort_order)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_waterway(db: AsyncSession, waterway_id: int) -> Waterway:
    result = await db.execute(select(Waterway).where(Waterway.id == waterway_id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="水系不存在")
    return obj


async def create_waterway(db: AsyncSession, data: WaterwayCreate, submitter_id: int) -> Waterway:
    obj = Waterway(**data.model_dump())
    db.add(obj)
    await db.flush()
    return obj


async def update_waterway(db: AsyncSession, waterway_id: int, data: WaterwayUpdate) -> Waterway:
    obj = await get_waterway(db, waterway_id)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(obj, field, value)
    await db.flush()
    return obj


async def delete_waterway(db: AsyncSession, waterway_id: int) -> None:
    obj = await get_waterway(db, waterway_id)
    await db.delete(obj)
    await db.flush()


# ===== Region =====

async def get_regions(db: AsyncSession, status: Optional[int] = None) -> List[Region]:
    query = select(Region)
    if status is not None:
        query = query.where(Region.status == status)
    query = query.order_by(Region.sort_order)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_region(db: AsyncSession, region_id: int) -> Region:
    result = await db.execute(select(Region).where(Region.id == region_id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="区域不存在")
    return obj


async def create_region(db: AsyncSession, data: RegionCreate, submitter_id: int) -> Region:
    obj = Region(**data.model_dump())
    db.add(obj)
    await db.flush()
    return obj


async def update_region(db: AsyncSession, region_id: int, data: RegionUpdate) -> Region:
    obj = await get_region(db, region_id)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(obj, field, value)
    await db.flush()
    return obj


async def delete_region(db: AsyncSession, region_id: int) -> None:
    obj = await get_region(db, region_id)
    await db.delete(obj)
    await db.flush()


async def get_nodes_in_region(db: AsyncSession, region_id: int) -> List[TransportNode]:
    result = await db.execute(
        select(TransportNode).where(TransportNode.region_id == region_id)
    )
    return list(result.scalars().all())


# ===== AdminRegion =====

async def get_admin_regions(
    db: AsyncSession,
    level: Optional[int] = None,
    parent_code: Optional[str] = None,
) -> List[AdminRegion]:
    query = select(AdminRegion)
    if level is not None:
        query = query.where(AdminRegion.level == level)
    if parent_code:
        query = query.where(AdminRegion.parent_code == parent_code)
    query = query.order_by(AdminRegion.sort_order)
    result = await db.execute(query)
    return list(result.scalars().all())


async def create_admin_region(db: AsyncSession, data: AdminRegionCreate) -> AdminRegion:
    obj = AdminRegion(**data.model_dump())
    db.add(obj)
    await db.flush()
    return obj


async def update_admin_region(db: AsyncSession, region_id: int, data: AdminRegionUpdate) -> AdminRegion:
    result = await db.execute(select(AdminRegion).where(AdminRegion.id == region_id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="行政区划不存在")
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(obj, field, value)
    await db.flush()
    return obj


# ===== NodeType =====

async def get_node_types(db: AsyncSession, status: Optional[int] = None) -> List[NodeType]:
    query = select(NodeType)
    if status is not None:
        query = query.where(NodeType.status == status)
    query = query.order_by(NodeType.sort_order)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_node_type(db: AsyncSession, node_type_id: int) -> NodeType:
    result = await db.execute(select(NodeType).where(NodeType.id == node_type_id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="节点类型不存在")
    return obj


async def create_node_type(db: AsyncSession, data: NodeTypeCreate) -> NodeType:
    obj = NodeType(**data.model_dump())
    db.add(obj)
    await db.flush()
    return obj


async def update_node_type(db: AsyncSession, node_type_id: int, data: NodeTypeUpdate) -> NodeType:
    obj = await get_node_type(db, node_type_id)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(obj, field, value)
    await db.flush()
    return obj


async def delete_node_type(db: AsyncSession, node_type_id: int) -> None:
    obj = await get_node_type(db, node_type_id)
    await db.delete(obj)
    await db.flush()


# ===== TransportNode =====

async def get_transport_nodes(
    db: AsyncSession,
    audit_status: Optional[int] = None,
    region_id: Optional[int] = None,
    waterway_id: Optional[int] = None,
    status: Optional[int] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    query = select(TransportNode)
    count_query = select(func.count(TransportNode.id))

    conditions = []
    if audit_status is not None:
        conditions.append(TransportNode.audit_status == audit_status)
    if region_id is not None:
        conditions.append(TransportNode.region_id == region_id)
    if waterway_id is not None:
        conditions.append(TransportNode.waterway_id == waterway_id)
    if status is not None:
        conditions.append(TransportNode.status == status)
    if keyword:
        conditions.append(TransportNode.name.ilike(f"%{keyword}%"))

    if conditions:
        query = query.where(and_(*conditions))
        count_query = count_query.where(and_(*conditions))

    total_res = await db.execute(count_query)
    total = total_res.scalar_one()

    query = query.options(selectinload(TransportNode.aliases))
    query = query.order_by(TransportNode.sort_order, TransportNode.id)
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = list(result.scalars().all())

    return PageResult(total=total, items=items, page=page, page_size=page_size)


async def get_transport_node(db: AsyncSession, node_id: int) -> TransportNode:
    result = await db.execute(
        select(TransportNode)
        .options(selectinload(TransportNode.aliases))
        .where(TransportNode.id == node_id)
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="运输节点不存在")
    return obj


async def create_transport_node(
    db: AsyncSession,
    data: TransportNodeCreate,
    submitter_id: int,
    submitter_name: str,
) -> TransportNode:
    """创建节点，audit_status=0（待审核）"""
    node = TransportNode(
        **data.model_dump(),
        audit_status=0,
        submitter_id=submitter_id,
    )
    db.add(node)
    await db.flush()

    # 创建审核记录
    await audit_service.create_audit_record(
        db=db,
        target_type="TRANSPORT_NODE",
        target_id=node.id,
        target_name=node.name,
        action="CREATE",
        before_data=None,
        after_data=data.model_dump(),
        submitter_id=submitter_id,
        submitter_name=submitter_name,
    )
    return node


async def update_transport_node(
    db: AsyncSession,
    node_id: int,
    data: TransportNodeUpdate,
    submitter_id: int,
    submitter_name: str,
) -> TransportNode:
    node = await get_transport_node(db, node_id)
    before = {c.name: getattr(node, c.name) for c in node.__table__.columns}

    updates = data.model_dump(exclude_none=True)
    for field, value in updates.items():
        setattr(node, field, value)

    # 关键字段变更需重新走审核
    critical_fields = {"name", "longitude", "latitude", "region_id", "waterway_id", "node_type_id"}
    if any(f in critical_fields for f in updates):
        node.audit_status = 0
        await audit_service.create_audit_record(
            db=db,
            target_type="TRANSPORT_NODE",
            target_id=node.id,
            target_name=node.name,
            action="UPDATE",
            before_data=before,
            after_data=updates,
            submitter_id=submitter_id,
            submitter_name=submitter_name,
        )

    await db.flush()
    return node


async def approve_transport_node(
    db: AsyncSession,
    node_id: int,
    auditor_id: int,
    auditor_name: str,
    remark: str = "",
) -> TransportNode:
    """审批通过节点 - 通过 audit_service 统一处理"""
    # 找到对应的 PENDING 审核记录
    from app.models.audit import AuditRecord
    res = await db.execute(
        select(AuditRecord).where(
            and_(
                AuditRecord.target_type == "TRANSPORT_NODE",
                AuditRecord.target_id == node_id,
                AuditRecord.audit_result == "PENDING",
            )
        ).order_by(AuditRecord.id.desc())
    )
    record = res.scalar_one_or_none()
    if not record:
        # 直接更新状态
        node = await get_transport_node(db, node_id)
        node.audit_status = 1
        node.auditor_id = auditor_id
        await db.flush()
        return node

    await audit_service.approve(db, record.id, auditor_id, auditor_name, remark)
    return await get_transport_node(db, node_id)


async def reject_transport_node(
    db: AsyncSession,
    node_id: int,
    auditor_id: int,
    auditor_name: str,
    remark: str,
) -> TransportNode:
    from app.models.audit import AuditRecord
    res = await db.execute(
        select(AuditRecord).where(
            and_(
                AuditRecord.target_type == "TRANSPORT_NODE",
                AuditRecord.target_id == node_id,
                AuditRecord.audit_result == "PENDING",
            )
        ).order_by(AuditRecord.id.desc())
    )
    record = res.scalar_one_or_none()
    if not record:
        node = await get_transport_node(db, node_id)
        node.audit_status = 2
        node.audit_remark = remark
        node.auditor_id = auditor_id
        await db.flush()
        return node

    await audit_service.reject(db, record.id, auditor_id, auditor_name, remark)
    return await get_transport_node(db, node_id)


async def delete_transport_node(db: AsyncSession, node_id: int) -> None:
    obj = await get_transport_node(db, node_id)
    await db.delete(obj)
    await db.flush()


# ===== NodeAlias =====

async def add_node_alias(db: AsyncSession, data: NodeAliasCreate) -> NodeAlias:
    # Check uniqueness
    res = await db.execute(
        select(NodeAlias).where(NodeAlias.alias_name == data.alias_name)
    )
    if res.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="别名已存在")
    alias = NodeAlias(**data.model_dump())
    db.add(alias)
    await db.flush()
    return alias


async def delete_node_alias(db: AsyncSession, node_id: int, alias_id: int) -> None:
    res = await db.execute(
        select(NodeAlias).where(
            and_(NodeAlias.id == alias_id, NodeAlias.node_id == node_id)
        )
    )
    obj = res.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="别名不存在")
    await db.delete(obj)
    await db.flush()


async def search_nodes_by_alias(
    db: AsyncSession,
    query: str,
    page: int = 1,
    page_size: int = 20,
) -> PageResult:
    """通过别名模糊搜索节点"""
    # Get matching alias node_ids
    alias_result = await db.execute(
        select(NodeAlias.node_id).where(NodeAlias.alias_name.ilike(f"%{query}%"))
    )
    node_ids = [row[0] for row in alias_result.fetchall()]

    # Also search by node name directly
    name_result = await db.execute(
        select(TransportNode.id).where(TransportNode.name.ilike(f"%{query}%"))
    )
    name_ids = [row[0] for row in name_result.fetchall()]

    all_ids = list(set(node_ids + name_ids))

    if not all_ids:
        return PageResult(total=0, items=[], page=page, page_size=page_size)

    total = len(all_ids)
    paged_ids = all_ids[(page - 1) * page_size: page * page_size]

    nodes_result = await db.execute(
        select(TransportNode).where(TransportNode.id.in_(paged_ids))
    )
    items = list(nodes_result.scalars().all())

    return PageResult(total=total, items=items, page=page, page_size=page_size)
