"""address 模块 router。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.modules.address.schemas import (
    AdminRegionBoundaryResponse,
    AdminRegionQuery,
    AdminRegionResponse,
    BusinessRegionCreateRequest,
    BusinessRegionListQuery,
    BusinessRegionResponse,
    BusinessRegionUpdateRequest,
    NavigationConstraintPointCreateRequest,
    NavigationConstraintPointDetailResponse,
    NavigationConstraintPointListQuery,
    NavigationConstraintPointResponse,
    NavigationConstraintPointStatusChangeRequest,
    NavigationConstraintPointUpdateRequest,
    NavigationConstraintProfileResponse,
    NavigationConstraintProfileUpsertRequest,
    NodeAliasReplaceRequest,
    NodeCodeListReplaceRequest,
    PageResponse,
    RegionBoundaryVersionCreateRequest,
    RegionBoundaryVersionResponse,
    RegionCityRelationReplaceRequest,
    TransportNodeCreateRequest,
    TransportNodeDetailResponse,
    TransportNodeListQuery,
    TransportNodeProfileResponse,
    TransportNodeProfileUpsertRequest,
    TransportNodeResponse,
    TransportNodeUpdateRequest,
)
from app.modules.address.service import (
    AdminRegionService,
    BusinessRegionService,
    NavigationConstraintPointService,
    TransportNodeService,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/admin-regions", response_model=PageResponse[AdminRegionResponse])
async def list_admin_regions(
    query: AdminRegionQuery = Depends(),
    db: AsyncSession = Depends(get_db),
):
    service = AdminRegionService(db)
    return await service.list_admin_regions(query.level, query.parent_code, query.keyword, query.page, query.page_size)


@router.get("/admin-regions/{admin_code}", response_model=AdminRegionResponse)
async def get_admin_region_detail(
    admin_code: str,
    db: AsyncSession = Depends(get_db),
):
    service = AdminRegionService(db)
    return await service.get_admin_region_detail(admin_code)


@router.get("/admin-regions/{admin_code}/boundaries", response_model=list[AdminRegionBoundaryResponse])
async def list_admin_region_boundaries(
    admin_code: str,
    db: AsyncSession = Depends(get_db),
):
    service = AdminRegionService(db)
    return await service.list_boundary_versions(admin_code)


@router.get("/admin-regions/{admin_code}/current-boundary", response_model=AdminRegionBoundaryResponse | None)
async def get_current_admin_region_boundary(
    admin_code: str,
    db: AsyncSession = Depends(get_db),
):
    service = AdminRegionService(db)
    return await service.get_current_boundary(admin_code)


@router.get("/admin-regions/{admin_code}/children", response_model=list[AdminRegionResponse])
async def get_admin_region_children(
    admin_code: str,
    db: AsyncSession = Depends(get_db),
):
    service = AdminRegionService(db)
    return await service.list_children(admin_code)


@router.get("/options/cities", response_model=list[AdminRegionResponse])
async def list_city_options(db: AsyncSession = Depends(get_db)):
    service = AdminRegionService(db)
    return await service.list_city_options()


@router.get("/options/cities/{city_code}/districts", response_model=list[AdminRegionResponse])
async def list_district_options(
    city_code: str,
    db: AsyncSession = Depends(get_db),
):
    service = AdminRegionService(db)
    return await service.list_district_options(city_code)


@router.get("/regions", response_model=PageResponse[BusinessRegionResponse])
async def list_business_regions(
    query: BusinessRegionListQuery = Depends(),
    db: AsyncSession = Depends(get_db),
):
    service = BusinessRegionService(db)
    return await service.list_regions(query.keyword, query.status, query.page, query.page_size)


@router.get("/regions/{region_id}", response_model=BusinessRegionResponse)
async def get_business_region_detail(
    region_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = BusinessRegionService(db)
    return await service.get_region_detail(region_id)


@router.post("/regions", response_model=BusinessRegionResponse)
async def create_business_region(
    body: BusinessRegionCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = BusinessRegionService(db)
    return await service.create_region(body)


@router.put("/regions/{region_id}", response_model=BusinessRegionResponse)
async def update_business_region(
    region_id: int,
    body: BusinessRegionUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = BusinessRegionService(db)
    return await service.update_region(region_id, body)


@router.get("/regions/{region_id}/boundaries", response_model=list[RegionBoundaryVersionResponse])
async def list_region_boundaries(
    region_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = BusinessRegionService(db)
    return await service.list_region_boundary_versions(region_id)


@router.get("/regions/{region_id}/current-boundary", response_model=RegionBoundaryVersionResponse | None)
async def get_current_region_boundary(
    region_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = BusinessRegionService(db)
    return await service.get_current_region_boundary(region_id)


@router.post("/regions/{region_id}/boundaries", response_model=RegionBoundaryVersionResponse)
async def create_region_boundary(
    region_id: int,
    body: RegionBoundaryVersionCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = BusinessRegionService(db)
    return await service.create_region_boundary_version(region_id, body)


@router.put("/regions/{region_id}/boundaries/{version_id}/activate")
async def activate_region_boundary(
    region_id: int,
    version_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = BusinessRegionService(db)
    await service.set_current_boundary(region_id, version_id)
    return {"ok": True}


@router.put("/regions/{region_id}/cities")
async def replace_region_cities(
    region_id: int,
    body: RegionCityRelationReplaceRequest,
    db: AsyncSession = Depends(get_db),
):
    service = BusinessRegionService(db)
    items = await service.replace_region_cities(region_id, body.city_codes)
    return {"ok": True, "items": items}


@router.get("/nodes", response_model=PageResponse[TransportNodeResponse])
async def list_nodes(
    query: TransportNodeListQuery = Depends(),
    db: AsyncSession = Depends(get_db),
):
    service = TransportNodeService(db)
    return await service.list_nodes(
        query.keyword,
        query.city_code,
        query.status,
        query.category_code,
        query.page,
        query.page_size,
    )


@router.get("/nodes/{node_id}", response_model=TransportNodeDetailResponse)
async def get_node_detail(
    node_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = TransportNodeService(db)
    return await service.get_node_detail(node_id)


@router.post("/nodes", response_model=TransportNodeResponse)
async def create_node(
    body: TransportNodeCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = TransportNodeService(db)
    return await service.create_node(body)


@router.put("/nodes/{node_id}", response_model=TransportNodeResponse)
async def update_node(
    node_id: int,
    body: TransportNodeUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = TransportNodeService(db)
    return await service.update_node(node_id, body)


@router.put("/nodes/{node_id}/profile", response_model=TransportNodeProfileResponse)
async def update_node_profile(
    node_id: int,
    body: TransportNodeProfileUpsertRequest,
    db: AsyncSession = Depends(get_db),
):
    service = TransportNodeService(db)
    return await service.update_node_profile(node_id, body)


@router.put("/nodes/{node_id}/aliases")
async def replace_node_aliases(
    node_id: int,
    body: NodeAliasReplaceRequest,
    db: AsyncSession = Depends(get_db),
):
    service = TransportNodeService(db)
    await service.replace_node_aliases(node_id, body.aliases)
    return {"ok": True}


@router.put("/nodes/{node_id}/business-categories")
async def replace_node_business_categories(
    node_id: int,
    body: NodeCodeListReplaceRequest,
    db: AsyncSession = Depends(get_db),
):
    service = TransportNodeService(db)
    await service.replace_node_business_categories(node_id, body.codes)
    return {"ok": True}


@router.put("/nodes/{node_id}/packaging-forms")
async def replace_node_packaging_forms(
    node_id: int,
    body: NodeCodeListReplaceRequest,
    db: AsyncSession = Depends(get_db),
):
    service = TransportNodeService(db)
    await service.replace_node_packaging_forms(node_id, body.codes)
    return {"ok": True}


@router.put("/nodes/{node_id}/handling-modes")
async def replace_node_handling_modes(
    node_id: int,
    body: NodeCodeListReplaceRequest,
    db: AsyncSession = Depends(get_db),
):
    service = TransportNodeService(db)
    await service.replace_node_handling_modes(node_id, body.codes)
    return {"ok": True}


@router.get("/constraint-points", response_model=PageResponse[NavigationConstraintPointResponse])
async def list_constraint_points(
    query: NavigationConstraintPointListQuery = Depends(),
    db: AsyncSession = Depends(get_db),
):
    service = NavigationConstraintPointService(db)
    return await service.list_constraint_points(
        query.keyword,
        query.constraint_type_code,
        query.city_code,
        query.status,
        query.page,
        query.page_size,
    )


@router.get("/constraint-points/{point_id}", response_model=NavigationConstraintPointDetailResponse)
async def get_constraint_point_detail(
    point_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = NavigationConstraintPointService(db)
    return await service.get_constraint_point_detail(point_id)


@router.post("/constraint-points", response_model=NavigationConstraintPointResponse)
async def create_constraint_point(
    body: NavigationConstraintPointCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = NavigationConstraintPointService(db)
    return await service.create_constraint_point(body)


@router.put("/constraint-points/{point_id}", response_model=NavigationConstraintPointResponse)
async def update_constraint_point(
    point_id: int,
    body: NavigationConstraintPointUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = NavigationConstraintPointService(db)
    return await service.update_constraint_point(point_id, body)


@router.put("/constraint-points/{point_id}/profile", response_model=NavigationConstraintProfileResponse)
async def upsert_constraint_point_profile(
    point_id: int,
    body: NavigationConstraintProfileUpsertRequest,
    db: AsyncSession = Depends(get_db),
):
    service = NavigationConstraintPointService(db)
    return await service.upsert_constraint_profile(point_id, body)


@router.put("/constraint-points/{point_id}/status")
async def change_constraint_point_status(
    point_id: int,
    body: NavigationConstraintPointStatusChangeRequest,
    db: AsyncSession = Depends(get_db),
):
    service = NavigationConstraintPointService(db)
    await service.change_constraint_point_status(point_id, body)
    return {"ok": True}
