"""地址路由 — 使用 DI 模式调用 AddressService"""
from typing import Optional
from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_address_service
from app.core.security import get_current_user_roles, require_roles
from app.schemas.address import (
    WaterwayCreate, WaterwayUpdate, WaterwayResponse,
    RegionCreate, RegionUpdate, RegionResponse, RegionDetailResponse,
    AdminRegionCreate, AdminRegionUpdate, AdminRegionResponse,
    NodeTypeCreate, NodeTypeUpdate, NodeTypeResponse,
    TransportNodeCreate, TransportNodeUpdate, TransportNodeResponse,
    NodeAliasCreate, NodeAliasResponse,
)
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


@router.post("/waterway", summary="创建水系（编码自动生成）")
async def create_waterway(
    data: WaterwayCreate,
    service: AddressService = Depends(get_address_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, _ = user_roles
    obj = await service.create_waterway(
        name=data.name,
        operator_id=user.id,
        **data.model_dump(exclude={"name"}, exclude_none=True),
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


@router.delete("/waterway/{waterway_id}", summary="删除水系（软删）")
async def delete_waterway(
    waterway_id: int,
    service: AddressService = Depends(get_address_service),
    user_roles=Depends(require_roles("ADMIN")),
):
    user, _ = user_roles
    await service.delete_waterway(waterway_id=waterway_id, operator_id=user.id)
    return success(message="删除成功")


@router.post("/waterway/{waterway_id}/toggle-status", summary="启用/停用水系（自动取反）")
async def toggle_waterway_status(
    waterway_id: int,
    service: AddressService = Depends(get_address_service),
    _=Depends(require_roles("ADMIN", "OPERATOR")),
):
    obj = await service.toggle_waterway_status(waterway_id=waterway_id)
    return success(data=WaterwayResponse.model_validate(obj))


@router.get("/waterway/list", summary="分页查询水系列表（支持名称模糊查询、编码精确查询）")
async def list_waterways_paged(
    name: Optional[str] = Query(None, description="水系名称（模糊查询）"),
    code: Optional[str] = Query(None, description="水系编码（精确查询）"),
    status: Optional[int] = Query(None, description="状态：1启用 0停用"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    service: AddressService = Depends(get_address_service),
    _=Depends(get_current_user_roles),
):
    result = await service.list_waterways_paged(
        name=name, code=code, status=status, page=page, page_size=page_size
    )
    return success(data={
        "total": result["total"],
        "items": [WaterwayResponse.model_validate(i) for i in result["items"]],
        "page": result["page"],
        "page_size": result["page_size"],
    })


# ===== Region =====

@router.get("/region", summary="获取商业区域列表（不分页）")
async def list_regions(
    status: Optional[int] = None,
    service: AddressService = Depends(get_address_service),
    _=Depends(get_current_user_roles),
):
    items = await service.list_regions(status=status)
    return success(data=[RegionResponse.model_validate(i) for i in items])


@router.get("/region/list", summary="分页查询商业区域（展开水系 / 城市详情）")
async def list_regions_paged(
    name: Optional[str] = Query(None, description="区域名称（模糊查询）"),
    status: Optional[int] = Query(None, description="状态：1启用 0停用"),
    audit_status: Optional[int] = Query(None, description="审核状态：0待审核 1通过 2驳回"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: AddressService = Depends(get_address_service),
    _=Depends(get_current_user_roles),
):
    result = await service.list_regions_paged(
        name=name, status=status, audit_status=audit_status,
        page=page, page_size=page_size,
    )

    from app.schemas.address import WaterwayResponse as _WR
    detail_items = []
    for item in result["items"]:
        detail = RegionDetailResponse.model_validate(item["region"])
        detail.waterways_info = [_WR.model_validate(r) for r in item["rivers_info"]]
        detail.cities_info = [AdminRegionResponse.model_validate(c) for c in item["cities_info"]]
        detail_items.append(detail)

    return success(data={
        "total": result["total"],
        "items": detail_items,
        "page": result["page"],
        "page_size": result["page_size"],
    })


@router.post("/region", summary="创建商业区域（编码/质心/城市自动计算，提交待审核）")
async def create_region(
    data: RegionCreate,
    service: AddressService = Depends(get_address_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, _ = user_roles
    obj = await service.create_region(
        name=data.name,
        operator_id=user.id,
        **data.model_dump(exclude={"name"}, exclude_none=True),
    )
    return success(data=RegionResponse.model_validate(obj))


@router.put("/region/{region_id}", summary="更新商业区域（仅限停用状态，修改后需重新审核）")
async def update_region(
    region_id: int,
    data: RegionUpdate,
    service: AddressService = Depends(get_address_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, _ = user_roles
    obj = await service.update_region(
        region_id=region_id, operator_id=user.id,
        **data.model_dump(exclude_none=True),
    )
    return success(data=RegionResponse.model_validate(obj))


@router.delete("/region/{region_id}", summary="删除商业区域（软删）")
async def delete_region(
    region_id: int,
    service: AddressService = Depends(get_address_service),
    user_roles=Depends(require_roles("ADMIN")),
):
    user, _ = user_roles
    await service.delete_region(region_id=region_id, operator_id=user.id)
    return success(message="删除成功")


@router.post("/region/{region_id}/toggle-status", summary="启用/停用商业区域（自动取反）")
async def toggle_region_status(
    region_id: int,
    service: AddressService = Depends(get_address_service),
    _=Depends(require_roles("ADMIN", "OPERATOR")),
):
    obj = await service.toggle_region_status(region_id=region_id)
    return success(data=RegionResponse.model_validate(obj))


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


@router.post("/node-type", summary="创建节点类型（编码自动生成）")
async def create_node_type(
    data: NodeTypeCreate,
    service: AddressService = Depends(get_address_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, _ = user_roles
    obj = await service.create_node_type(
        name=data.name, operator_id=user.id,
        **data.model_dump(exclude={"name"}, exclude_none=True)
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


@router.delete("/node-type/{node_type_id}", summary="删除节点类型（软删）")
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


@router.post("/transport-node", summary="创建运输节点（编码自动生成，坐标自动归属区域）")
async def create_transport_node(
    data: TransportNodeCreate,
    service: AddressService = Depends(get_address_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR", "COLLECTOR")),
):
    user, _ = user_roles
    obj = await service.create_node(
        name=data.name,
        operator_id=user.id,
        submitter_id=user.id,
        **data.model_dump(exclude={"name"}, exclude_none=True),
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


@router.put("/transport-node/{node_id}", summary="更新节点（经纬度变化时自动重新归属区域）")
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


@router.delete("/transport-node/{node_id}", summary="删除节点（软删）")
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


@router.delete("/transport-node/{node_id}/aliases/{alias_id}", summary="删除节点别名（软删）")
async def delete_node_alias(
    node_id: int,
    alias_id: int,
    service: AddressService = Depends(get_address_service),
    user_roles=Depends(require_roles("ADMIN", "OPERATOR")),
):
    user, _ = user_roles
    await service.delete_alias(node_id=node_id, alias_id=alias_id, operator_id=user.id)
    return success(message="删除成功")


# ===== 一键归属 =====

@router.post(
    "/transport-node/reassign-regions",
    summary="一键归属：重新计算所有节点的区域归属关系",
)
async def reassign_node_regions(
    service: AddressService = Depends(get_address_service),
    _=Depends(require_roles("ADMIN", "SUPER_ADMIN")),
):
    """
    遍历所有有经纬度的运输节点，判断其是否落在各已启用区域的边界内：
    - 落在区域内 且 关系不存在 → 插入 region_address_relation
    - 已存在的关系 且 坐标不再落在区域内 → 删除该关系
    """
    result = await service.reassign_all_nodes()
    return success(data=result, message="归属计算完成")
