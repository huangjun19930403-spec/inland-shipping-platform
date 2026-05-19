"""address 模块 router。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.system import SysUser
from app.modules.address.schemas import (
    AdminRegionBoundaryResponse,
    AdminRegionQuery,
    AdminRegionResponse,
    AddressMapCandidate,
    AddressMapGeocodeQuery,
    AddressMapGeocodeResponse,
    AddressMapReverseGeocodeQuery,
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
    RegionCityRelationResponse,
    TransportNodeContactReplaceRequest,
    TransportNodeContactResponse,
    TransportNodeCreateRequest,
    TransportNodeDetailResponse,
    TransportNodeListQuery,
    TransportNodePhotoResponse,
    TransportNodePhotoUpdateRequest,
    TransportNodeProfileResponse,
    TransportNodeProfileUpsertRequest,
    TransportNodeResponse,
    TransportNodeUpdateRequest,
    NavigationChannelBoundaryResponse,
    NavigationChannelDetailResponse,
    NavigationChannelQuery,
    NavigationChannelResponse,
    NavigationChannelSegmentResponse,
    NavigationChannelSourceAuditResponse,
    NavigationChannelSummaryResponse,
)
from app.modules.address.service import (
    AdminRegionService,
    AddressMapService,
    BusinessRegionService,
    NavigationConstraintPointService,
    TransportNodeService,
    NavigationChannelService,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/map/geocode", response_model=AddressMapGeocodeResponse)
async def geocode_address(
    query: AddressMapGeocodeQuery = Depends(),
    db: AsyncSession = Depends(get_db),
):
    service = AddressMapService(db)
    return await service.geocode(query.keyword, query.city_code)


@router.get("/map/reverse-geocode", response_model=AddressMapCandidate)
async def reverse_geocode_address(
    query: AddressMapReverseGeocodeQuery = Depends(),
    db: AsyncSession = Depends(get_db),
):
    service = AddressMapService(db)
    return await service.reverse_geocode(query.longitude, query.latitude)


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


@router.get("/navigation-channels/summary", response_model=NavigationChannelSummaryResponse)
async def get_navigation_channel_summary(db: AsyncSession = Depends(get_db)):
    service = NavigationChannelService(db)
    return await service.summary()


@router.get("/navigation-channels", response_model=PageResponse[NavigationChannelResponse])
async def list_navigation_channels(
    query: NavigationChannelQuery = Depends(),
    db: AsyncSession = Depends(get_db),
):
    service = NavigationChannelService(db)
    return await service.list_navigation_channels(
        keyword=query.keyword,
        channel_type_code=query.channel_type_code,
        planning_level_code=query.planning_level_code,
        ais_scope_code=query.ais_scope_code,
        geometry_status_code=query.geometry_status_code,
        boundary_quality_code=query.boundary_quality_code,
        connectivity_status_code=query.connectivity_status_code,
        repair_status_code=query.repair_status_code,
        page=query.page,
        page_size=query.page_size,
    )


@router.get("/navigation-channels/{channel_code}", response_model=NavigationChannelDetailResponse)
async def get_navigation_channel_detail(
    channel_code: str,
    db: AsyncSession = Depends(get_db),
):
    service = NavigationChannelService(db)
    return await service.get_navigation_channel_detail(channel_code)


@router.get("/navigation-channels/{channel_code}/boundary", response_model=NavigationChannelBoundaryResponse)
async def get_navigation_channel_boundary(
    channel_code: str,
    precision: str = Query("medium", pattern="^(low|medium|high)$"),
    db: AsyncSession = Depends(get_db),
):
    service = NavigationChannelService(db)
    return await service.get_navigation_channel_boundary(channel_code, precision)


@router.get("/navigation-channels/{channel_code}/segments", response_model=list[NavigationChannelSegmentResponse])
async def list_navigation_channel_segments(
    channel_code: str,
    db: AsyncSession = Depends(get_db),
):
    service = NavigationChannelService(db)
    return await service.list_navigation_channel_segments(channel_code)


@router.get("/navigation-channels/{channel_code}/source-audit", response_model=list[NavigationChannelSourceAuditResponse])
async def list_navigation_channel_source_audit(
    channel_code: str,
    db: AsyncSession = Depends(get_db),
):
    service = NavigationChannelService(db)
    return await service.list_navigation_channel_source_audit(channel_code)


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


@router.get("/regions/{region_id}/cities", response_model=list[RegionCityRelationResponse])
async def list_region_cities(
    region_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = BusinessRegionService(db)
    return await service.list_region_cities(region_id)


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


@router.get("/nodes/{node_id}/contacts", response_model=list[TransportNodeContactResponse])
async def list_node_contacts(
    node_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = TransportNodeService(db)
    return await service.list_node_contacts(node_id)


@router.put("/nodes/{node_id}/contacts", response_model=list[TransportNodeContactResponse])
async def replace_node_contacts(
    node_id: int,
    body: TransportNodeContactReplaceRequest,
    db: AsyncSession = Depends(get_db),
):
    service = TransportNodeService(db)
    return await service.replace_node_contacts(node_id, body)


@router.get("/nodes/{node_id}/photos", response_model=list[TransportNodePhotoResponse])
async def list_node_photos(
    node_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = TransportNodeService(db)
    return await service.list_node_photos(node_id)


@router.post("/nodes/{node_id}/photos", response_model=TransportNodePhotoResponse)
async def create_node_photo(
    node_id: int,
    photo_type_code: str = Form(...),
    photo_name: str | None = Form(default=None),
    description: str | None = Form(default=None),
    is_primary: bool = Form(default=False),
    sort_order: int = Form(default=0),
    file: UploadFile = File(...),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = TransportNodeService(db)
    return await service.create_node_photo(
        node_id,
        file=file,
        photo_type_code=photo_type_code,
        photo_name=photo_name,
        description=description,
        is_primary=is_primary,
        sort_order=sort_order,
        uploaded_by=current_user.id,
    )


@router.put("/nodes/{node_id}/photos/{photo_id}", response_model=TransportNodePhotoResponse)
async def update_node_photo(
    node_id: int,
    photo_id: int,
    body: TransportNodePhotoUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = TransportNodeService(db)
    return await service.update_node_photo(node_id, photo_id, body)


@router.delete("/nodes/{node_id}/photos/{photo_id}")
async def delete_node_photo(
    node_id: int,
    photo_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = TransportNodeService(db)
    await service.delete_node_photo(node_id, photo_id)
    return {"ok": True}


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
