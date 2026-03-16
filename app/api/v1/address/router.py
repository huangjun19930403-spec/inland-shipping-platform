"""地址路由 — 使用 DI 模式调用 AddressService"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException

from app.core.dependencies import get_address_service
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
from app.schemas.common import success
from app.services.address_service import AddressService

router = APIRouter()


# ===== Waterway =====

@router.get("/waterway", summary="获取水系列表")
async def list_waterways(
    status: Optional[int] = None,
    service: AddressService = Depends(get_address_service),
    _=Depends(get_current_user_roles),
):
    items = await service.list_waterways(status=status)
    return success(data=[WaterwayResponse.model_validate(i) for i in items])


@router.post("/waterway", summary="创建水系")
async def create_waterway(
    data: WaterwayCreate,
    service: AddressService = Depends(get_address_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, _ = user_roles
    obj = await service.create_waterway(
        name=data.name, code=data.code, operator_id=user.id,
        **data.model_dump(exclude={"name", "code"}, exclude_none=True)
    )
    return success(data=WaterwayResponse.model_validate(obj))


@router.put("/waterway/{waterway_id}", summary="更新水系")
async def update_waterway(
    waterway_id: int,
    data: WaterwayUpdate,
    service: AddressService = Depends(get_address_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, _ = user_roles
    obj = await service.update_waterway(
        waterway_id=waterway_id, operator_id=user.id,
        **data.model_dump(exclude_none=True)
    )
    return success(data=WaterwayResponse.model_validate(obj))


@router.delete("/waterway/{waterway_id}", summary="删除水系")
async def delete_waterway(
    waterway_id: int,
    service: AddressService = Depends(get_address_service),
    user_roles=Depends(require_roles("ADMIN")),
):
    user, _ = user_roles
    await service.delete_waterway(waterway_id=waterway_id, operator_id=user.id)
    return success(message="删除成功")


# ===== Region =====

@router.get("/region", summary="获取商业区域列表")
async def list_regions(
    status: Optional[int] = None,
    service: AddressService = Depends(get_address_service),
    _=Depends(get_current_user_roles),
):
    items = await service.list_regions(status=status)
    return success(data=[RegionResponse.model_validate(i) for i in items])


@router.post("/region", summary="创建商业区域")
async def create_region(
    data: RegionCreate,
    service: AddressService = Depends(get_address_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, _ = user_roles
    obj = await service.create_region(
        name=data.name, code=data.code, operator_id=user.id,
        **data.model_dump(exclude={"name", "code"}, exclude_none=True)
    )
    return success(data=RegionResponse.model_validate(obj))


@router.put("/region/{region_id}", summary="更新商业区域")
async def update_region(
    region_id: int,
    data: RegionUpdate,
    service: AddressService = Depends(get_address_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, _ = user_roles
    obj = await service.update_region(
        region_id=region_id, operator_id=user.id,
        **data.model_dump(exclude_none=True)
    )
    return success(data=RegionResponse.model_validate(obj))


@router.delete("/region/{region_id}", summary="删除商业区域")
async def delete_region(
    region_id: int,
    service: AddressService = Depends(get_address_service),
    user_roles=Depends(require_roles("ADMIN")),
):
    user, _ = user_roles
    await service.delete_region(region_id=region_id, operator_id=user.id)
    return success(message="删除成功")


@router.get("/region/{region_id}/nodes", summary="获取区域内的节点")
async def get_region_nodes(
    region_id: int,
    service: AddressService = Depends(get_address_service),
    _=Depends(get_current_user_roles),
):
    items = await service.get_nodes_in_region(region_id)
    return success(data=[TransportNodeResponse.model_validate(i) for i in items])


# ===== AdminRegion =====

@router.get("/admin-region", summary="获取行政区划列表")
async def list_admin_regions(
    level: Optional[int] = None,
    parent_code: Optional[str] = None,
    service: AddressService = Depends(get_address_service),
    _=Depends(get_current_user_roles),
):
    items = await service.list_admin_regions(level=level, parent_code=parent_code)
    return success(data=[AdminRegionResponse.model_validate(i) for i in items])


@router.post("/admin-region", summary="创建行政区划")
async def create_admin_region(
    data: AdminRegionCreate,
    service: AddressService = Depends(get_address_service),
    _=Depends(require_roles("ADMIN")),
):
    obj = await service.create_admin_region(
        name=data.name, code=data.code,
        **data.model_dump(exclude={"name", "code"}, exclude_none=True)
    )
    return success(data=AdminRegionResponse.model_validate(obj))


@router.put("/admin-region/{region_id}", summary="更新行政区划")
async def update_admin_region(
    region_id: int,
    data: AdminRegionUpdate,
    service: AddressService = Depends(get_address_service),
    _=Depends(require_roles("ADMIN")),
):
    obj = await service.update_admin_region(
        region_id=region_id, **data.model_dump(exclude_none=True)
    )
    return success(data=AdminRegionResponse.model_validate(obj))


# ===== NodeType =====

@router.get("/node-type", summary="获取节点类型列表")
async def list_node_types(
    status: Optional[int] = None,
    service: AddressService = Depends(get_address_service),
    _=Depends(get_current_user_roles),
):
    items = await service.list_node_types(status=status)
    return success(data=[NodeTypeResponse.model_validate(i) for i in items])


@router.post("/node-type", summary="创建节点类型")
async def create_node_type(
    data: NodeTypeCreate,
    service: AddressService = Depends(get_address_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, _ = user_roles
    obj = await service.create_node_type(
        name=data.name, code=data.code, operator_id=user.id,
        **data.model_dump(exclude={"name", "code"}, exclude_none=True)
    )
    return success(data=NodeTypeResponse.model_validate(obj))


@router.put("/node-type/{node_type_id}", summary="更新节点类型")
async def update_node_type(
    node_type_id: int,
    data: NodeTypeUpdate,
    service: AddressService = Depends(get_address_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, _ = user_roles
    obj = await service.update_node_type(
        node_type_id=node_type_id, operator_id=user.id,
        **data.model_dump(exclude_none=True)
    )
    return success(data=NodeTypeResponse.model_validate(obj))


@router.delete("/node-type/{node_type_id}", summary="删除节点类型")
async def delete_node_type(
    node_type_id: int,
    service: AddressService = Depends(get_address_service),
    user_roles=Depends(require_roles("ADMIN")),
):
    user, _ = user_roles
    await service.delete_node_type(node_type_id=node_type_id, operator_id=user.id)
    return success(message="删除成功")


# ===== TransportNode =====

@router.get("/transport-node/search", summary="模糊搜索节点（按名称/别名）")
async def search_transport_nodes(
    q: str = Query(..., description="搜索关键词"),
    page: int = 1,
    page_size: int = 20,
    service: AddressService = Depends(get_address_service),
    _=Depends(get_current_user_roles),
):
    result = await service.search_nodes(q=q, page=page, page_size=page_size)
    return success(data={
        "total": result["total"],
        "items": [TransportNodeResponse.model_validate(i) for i in result["items"]],
        "page": result["page"],
        "page_size": result["page_size"],
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
    service: AddressService = Depends(get_address_service),
    _=Depends(get_current_user_roles),
):
    result = await service.list_nodes(
        audit_status=audit_status, region_id=region_id,
        waterway_id=waterway_id, status=status,
        keyword=keyword, page=page, page_size=page_size,
    )
    return success(data={
        "total": result["total"],
        "items": [TransportNodeResponse.model_validate(i) for i in result["items"]],
        "page": result["page"],
        "page_size": result["page_size"],
    })


@router.post("/transport-node", summary="创建运输节点（待审核）")
async def create_transport_node(
    data: TransportNodeCreate,
    service: AddressService = Depends(get_address_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR", "COLLECTOR")),
):
    user, _ = user_roles
    obj = await service.create_node(
        name=data.name,
        code=data.code,
        waterway_id=data.waterway_id,
        operator_id=user.id,
        submitter_id=user.id,
        region_id=getattr(data, "region_id", None),
        node_type_id=getattr(data, "node_type_id", None),
        latitude=getattr(data, "latitude", None),
        longitude=getattr(data, "longitude", None),
    )
    return success(data=TransportNodeResponse.model_validate(obj))


@router.get("/transport-node/{node_id}", summary="获取节点详情")
async def get_transport_node(
    node_id: int,
    service: AddressService = Depends(get_address_service),
    _=Depends(get_current_user_roles),
):
    obj = await service.get_node(node_id)
    return success(data=TransportNodeResponse.model_validate(obj))


@router.put("/transport-node/{node_id}", summary="更新节点")
async def update_transport_node(
    node_id: int,
    data: TransportNodeUpdate,
    service: AddressService = Depends(get_address_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, _ = user_roles
    obj = await service.update_node(
        node_id=node_id, operator_id=user.id,
        **data.model_dump(exclude_none=True)
    )
    return success(data=TransportNodeResponse.model_validate(obj))


@router.delete("/transport-node/{node_id}", summary="删除节点")
async def delete_transport_node(
    node_id: int,
    service: AddressService = Depends(get_address_service),
    user_roles=Depends(require_roles("ADMIN")),
):
    user, _ = user_roles
    await service.delete_node(node_id=node_id, operator_id=user.id)
    return success(message="删除成功")


@router.post("/transport-node/{node_id}/aliases", summary="添加节点别名")
async def add_node_alias(
    node_id: int,
    data: NodeAliasCreate,
    service: AddressService = Depends(get_address_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, _ = user_roles
    obj = await service.add_alias(
        node_id=node_id, alias_name=data.alias_name, operator_id=user.id
    )
    return success(data=NodeAliasResponse.model_validate(obj))


@router.delete("/transport-node/{node_id}/aliases/{alias_id}", summary="删除节点别名")
async def delete_node_alias(
    node_id: int,
    alias_id: int,
    service: AddressService = Depends(get_address_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, _ = user_roles
    await service.delete_alias(node_id=node_id, alias_id=alias_id, operator_id=user.id)
    return success(message="删除成功")


# ===== Audit Actions =====

@router.post("/transport-node/{node_id}/approve", summary="审批通过节点")
async def approve_transport_node(
    node_id: int,
    data: AuditActionRequest,
    service: AddressService = Depends(get_address_service),
    user_roles=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    user, roles = user_roles
    node = await service.get_node(node_id)
    if "SUPER_ADMIN" not in roles and node.submitter_id == user.id:
        raise HTTPException(status_code=403, detail="提交人不能审核自己提交的内容")
    obj = await service.approve_node(
        node_id=node_id, auditor_id=user.id, remark=data.audit_remark or ""
    )
    return success(data=TransportNodeResponse.model_validate(obj))


@router.post("/transport-node/{node_id}/reject", summary="驳回节点")
async def reject_transport_node(
    node_id: int,
    data: AuditActionRequest,
    service: AddressService = Depends(get_address_service),
    user_roles=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    user, roles = user_roles
    node = await service.get_node(node_id)
    if "SUPER_ADMIN" not in roles and node.submitter_id == user.id:
        raise HTTPException(status_code=403, detail="提交人不能审核自己提交的内容")
    if not data.audit_remark:
        raise HTTPException(status_code=400, detail="驳回必须填写审核意见")
    obj = await service.reject_node(
        node_id=node_id, auditor_id=user.id, remark=data.audit_remark
    )
    return success(data=TransportNodeResponse.model_validate(obj))
