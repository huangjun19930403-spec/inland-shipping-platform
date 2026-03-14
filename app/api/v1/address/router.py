"""地址路由"""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_roles, require_roles
from app.schemas.address import (
    WaterwayCreate, WaterwayUpdate, WaterwayResponse,
    RegionCreate, RegionUpdate, RegionResponse,
    AdminRegionCreate, AdminRegionUpdate, AdminRegionResponse,
    NodeTypeCreate, NodeTypeUpdate, NodeTypeResponse,
    TransportNodeCreate, TransportNodeUpdate, TransportNodeResponse,
    NodeAliasCreate, NodeAliasResponse,
)
from app.schemas.audit import AuditActionRequest
from app.schemas.common import success, PageResult
from app.services import address_service

router = APIRouter()


# ===== Waterway =====

@router.get("/waterway", summary="获取水系列表")
async def list_waterways(
    status: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    items = await address_service.get_waterways(db, status)
    return success(data=[WaterwayResponse.model_validate(i) for i in items])


@router.post("/waterway", summary="创建水系")
async def create_waterway(
    data: WaterwayCreate,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, roles = user_roles
    obj = await address_service.create_waterway(db, data, submitter_id=user.id)
    await db.commit()
    await db.refresh(obj)
    return success(data=WaterwayResponse.model_validate(obj))


@router.put("/waterway/{waterway_id}", summary="更新水系")
async def update_waterway(
    waterway_id: int,
    data: WaterwayUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR")),
):
    obj = await address_service.update_waterway(db, waterway_id, data)
    await db.commit()
    await db.refresh(obj)
    return success(data=WaterwayResponse.model_validate(obj))


@router.delete("/waterway/{waterway_id}", summary="删除水系")
async def delete_waterway(
    waterway_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN")),
):
    await address_service.delete_waterway(db, waterway_id)
    await db.commit()
    return success(message="删除成功")


# ===== Region =====

@router.get("/region", summary="获取区域列表")
async def list_regions(
    status: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    items = await address_service.get_regions(db, status)
    return success(data=[RegionResponse.model_validate(i) for i in items])


@router.post("/region", summary="创建区域")
async def create_region(
    data: RegionCreate,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, roles = user_roles
    obj = await address_service.create_region(db, data, submitter_id=user.id)
    await db.commit()
    await db.refresh(obj)
    return success(data=RegionResponse.model_validate(obj))


@router.put("/region/{region_id}", summary="更新区域")
async def update_region(
    region_id: int,
    data: RegionUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR")),
):
    obj = await address_service.update_region(db, region_id, data)
    await db.commit()
    await db.refresh(obj)
    return success(data=RegionResponse.model_validate(obj))


@router.delete("/region/{region_id}", summary="删除区域")
async def delete_region(
    region_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN")),
):
    await address_service.delete_region(db, region_id)
    await db.commit()
    return success(message="删除成功")


@router.get("/region/{region_id}/nodes", summary="获取区域内的节点")
async def get_region_nodes(
    region_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    items = await address_service.get_nodes_in_region(db, region_id)
    return success(data=[TransportNodeResponse.model_validate(i) for i in items])


# ===== AdminRegion =====

@router.get("/admin-region", summary="获取行政区划列表")
async def list_admin_regions(
    level: Optional[int] = None,
    parent_code: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    items = await address_service.get_admin_regions(db, level, parent_code)
    return success(data=[AdminRegionResponse.model_validate(i) for i in items])


@router.post("/admin-region", summary="创建行政区划")
async def create_admin_region(
    data: AdminRegionCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN")),
):
    obj = await address_service.create_admin_region(db, data)
    await db.commit()
    await db.refresh(obj)
    return success(data=AdminRegionResponse.model_validate(obj))


@router.put("/admin-region/{region_id}", summary="更新行政区划")
async def update_admin_region(
    region_id: int,
    data: AdminRegionUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN")),
):
    obj = await address_service.update_admin_region(db, region_id, data)
    await db.commit()
    await db.refresh(obj)
    return success(data=AdminRegionResponse.model_validate(obj))


# ===== NodeType =====

@router.get("/node-type", summary="获取节点类型列表")
async def list_node_types(
    status: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    items = await address_service.get_node_types(db, status)
    return success(data=[NodeTypeResponse.model_validate(i) for i in items])


@router.post("/node-type", summary="创建节点类型")
async def create_node_type(
    data: NodeTypeCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR")),
):
    obj = await address_service.create_node_type(db, data)
    await db.commit()
    await db.refresh(obj)
    return success(data=NodeTypeResponse.model_validate(obj))


@router.put("/node-type/{node_type_id}", summary="更新节点类型")
async def update_node_type(
    node_type_id: int,
    data: NodeTypeUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR")),
):
    obj = await address_service.update_node_type(db, node_type_id, data)
    await db.commit()
    await db.refresh(obj)
    return success(data=NodeTypeResponse.model_validate(obj))


@router.delete("/node-type/{node_type_id}", summary="删除节点类型")
async def delete_node_type(
    node_type_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN")),
):
    await address_service.delete_node_type(db, node_type_id)
    await db.commit()
    return success(message="删除成功")


# ===== TransportNode =====

@router.get("/transport-node/search", summary="模糊搜索节点（别名）")
async def search_transport_nodes(
    q: str = Query(..., description="搜索关键词"),
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    result = await address_service.search_nodes_by_alias(db, q, page, page_size)
    return success(data={
        "total": result.total,
        "items": [TransportNodeResponse.model_validate(i) for i in result.items],
        "page": result.page,
        "page_size": result.page_size,
    })


@router.get("/transport-node", summary="获取节点列表")
async def list_transport_nodes(
    audit_status: Optional[int] = None,
    region_id: Optional[int] = None,
    waterway_id: Optional[int] = None,
    status: Optional[int] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    result = await address_service.get_transport_nodes(
        db, audit_status, region_id, waterway_id, status, keyword, page, page_size
    )
    return success(data={
        "total": result.total,
        "items": [TransportNodeResponse.model_validate(i) for i in result.items],
        "page": result.page,
        "page_size": result.page_size,
    })


@router.post("/transport-node", summary="创建运输节点（待审核）")
async def create_transport_node(
    data: TransportNodeCreate,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR", "COLLECTOR")),
):
    user, roles = user_roles
    obj = await address_service.create_transport_node(
        db, data, submitter_id=user.id, submitter_name=user.real_name
    )
    await db.commit()
    await db.refresh(obj)
    return success(data=TransportNodeResponse.model_validate(obj))


@router.get("/transport-node/{node_id}", summary="获取节点详情")
async def get_transport_node(
    node_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user_roles),
):
    obj = await address_service.get_transport_node(db, node_id)
    return success(data=TransportNodeResponse.model_validate(obj))


@router.put("/transport-node/{node_id}", summary="更新节点")
async def update_transport_node(
    node_id: int,
    data: TransportNodeUpdate,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, roles = user_roles
    obj = await address_service.update_transport_node(
        db, node_id, data, submitter_id=user.id, submitter_name=user.real_name
    )
    await db.commit()
    await db.refresh(obj)
    return success(data=TransportNodeResponse.model_validate(obj))


@router.delete("/transport-node/{node_id}", summary="删除节点")
async def delete_transport_node(
    node_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN")),
):
    await address_service.delete_transport_node(db, node_id)
    await db.commit()
    return success(message="删除成功")


@router.post("/transport-node/{node_id}/aliases", summary="添加节点别名")
async def add_node_alias(
    node_id: int,
    data: NodeAliasCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR")),
):
    data.node_id = node_id
    obj = await address_service.add_node_alias(db, data)
    await db.commit()
    await db.refresh(obj)
    return success(data=NodeAliasResponse.model_validate(obj))


@router.delete("/transport-node/{node_id}/aliases/{alias_id}", summary="删除节点别名")
async def delete_node_alias(
    node_id: int,
    alias_id: int,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_roles("ADMIN", "OPERATOR")),
):
    await address_service.delete_node_alias(db, node_id, alias_id)
    await db.commit()
    return success(message="删除成功")


# ===== Audit Actions for Transport Node =====

@router.post("/transport-node/{node_id}/approve", summary="审批通过节点")
async def approve_transport_node(
    node_id: int,
    data: AuditActionRequest,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    user, roles = user_roles
    # Check submitter != auditor (unless SUPER_ADMIN)
    node = await address_service.get_transport_node(db, node_id)
    from app.services.audit_service import check_can_audit
    can = await check_can_audit(node.submitter_id or 0, user.id, roles)
    if not can:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="提交人不能审核自己提交的内容")

    obj = await address_service.approve_transport_node(
        db, node_id, auditor_id=user.id, auditor_name=user.real_name,
        remark=data.audit_remark or ""
    )
    await db.commit()
    return success(data=TransportNodeResponse.model_validate(obj))


@router.post("/transport-node/{node_id}/reject", summary="驳回节点")
async def reject_transport_node(
    node_id: int,
    data: AuditActionRequest,
    db: AsyncSession = Depends(get_db),
    user_roles=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    user, roles = user_roles
    node = await address_service.get_transport_node(db, node_id)
    from app.services.audit_service import check_can_audit
    can = await check_can_audit(node.submitter_id or 0, user.id, roles)
    if not can:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="提交人不能审核自己提交的内容")

    if not data.audit_remark:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="驳回必须填写审核意见")
    obj = await address_service.reject_transport_node(
        db, node_id, auditor_id=user.id, auditor_name=user.real_name,
        remark=data.audit_remark
    )
    await db.commit()
    return success(data=TransportNodeResponse.model_validate(obj))
