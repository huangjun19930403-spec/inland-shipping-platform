"""address 模块 service。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.modules.address.repository import (
    AdminRegionRepository,
    NavigationConstraintPointRepository,
    RegionRepository,
    TransportNodeRepository,
)
from app.modules.address.schemas import (
    AdminRegionResponse,
    BusinessRegionCreateRequest,
    BusinessRegionResponse,
    BusinessRegionUpdateRequest,
    NavigationConstraintPointCreateRequest,
    NavigationConstraintPointDetailResponse,
    NavigationConstraintPointResponse,
    NavigationConstraintPointStatusChangeRequest,
    NavigationConstraintPointUpdateRequest,
    NavigationConstraintProfileResponse,
    NavigationConstraintProfileUpsertRequest,
    PageResponse,
    RegionBoundaryVersionCreateRequest,
    RegionBoundaryVersionResponse,
    RegionCityRelationResponse,
    TransportNodeCreateRequest,
    TransportNodeDetailResponse,
    TransportNodeProfileResponse,
    TransportNodeProfileUpsertRequest,
    TransportNodeResponse,
    TransportNodeUpdateRequest,
)
from app.modules.dictionary.service import CodeSequenceService


def _to_admin_region_response(row) -> AdminRegionResponse:
    return AdminRegionResponse(
        id=row.id,
        code=row.code,
        name=row.name,
        short_name=row.short_name,
        level=row.level,
        parent_code=row.parent_code,
        province_code=row.province_code,
        city_code=row.city_code,
        district_code=row.district_code,
        longitude=row.longitude,
        latitude=row.latitude,
        status=row.status,
    )


def _to_region_response(row) -> BusinessRegionResponse:
    return BusinessRegionResponse(
        id=row.id,
        code=row.code,
        name=row.name,
        short_name=row.short_name,
        region_type_code=row.region_type_code,
        description=row.description,
        sort_order=row.sort_order,
        status=row.status,
        current_boundary_version_id=row.current_boundary_version_id,
        audit_status=row.audit_status,
        submitter_id=row.submitter_id,
        auditor_id=row.auditor_id,
        audited_at=row.audited_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_boundary_response(row) -> RegionBoundaryVersionResponse:
    return RegionBoundaryVersionResponse(
        id=row.id,
        region_id=row.region_id,
        version_no=row.version_no,
        boundary_source_type_code=row.boundary_source_type_code,
        geometry_json=row.geometry_json,
        center_longitude=row.center_longitude,
        center_latitude=row.center_latitude,
        area_km2=row.area_km2,
        is_current=row.is_current,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        approved_by=row.approved_by,
        approved_at=row.approved_at,
        remark=row.remark,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_node_response(row) -> TransportNodeResponse:
    return TransportNodeResponse(
        id=row.id,
        code=row.code,
        name=row.name,
        short_name=row.short_name,
        node_type_code=row.node_type_code,
        province_code=row.province_code,
        city_code=row.city_code,
        district_code=row.district_code,
        city_region_id=row.city_region_id,
        address=row.address,
        longitude=row.longitude,
        latitude=row.latitude,
        status=row.status,
        lifecycle_status_code=row.lifecycle_status_code,
        sort_order=row.sort_order,
        is_hot_node=row.is_hot_node,
        audit_status=row.audit_status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class AdminRegionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = AdminRegionRepository(db)

    async def list_admin_regions(
        self,
        level: int | None,
        parent_code: str | None,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> PageResponse[AdminRegionResponse]:
        items, total = await self.repo.list_regions(level, parent_code, keyword, page, page_size)
        return PageResponse[AdminRegionResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_admin_region_response(item) for item in items],
        )

    async def get_admin_region_detail(self, admin_code: str) -> AdminRegionResponse:
        row = await self.repo.get_region_by_code(admin_code)
        if row is None:
            raise NotFoundError("AdminRegion", admin_code)
        return _to_admin_region_response(row)

    async def list_city_options(self) -> list[AdminRegionResponse]:
        rows = await self.repo.list_cities()
        return [_to_admin_region_response(row) for row in rows]

    async def list_district_options(self, city_code: str) -> list[AdminRegionResponse]:
        rows = await self.repo.list_districts_by_city(city_code)
        return [_to_admin_region_response(row) for row in rows]

    async def list_children(self, admin_code: str) -> list[AdminRegionResponse]:
        rows = await self.repo.get_children(admin_code)
        return [_to_admin_region_response(row) for row in rows]


class BusinessRegionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = RegionRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def list_regions(
        self,
        keyword: str | None,
        status: int | None,
        page: int,
        page_size: int,
    ) -> PageResponse[BusinessRegionResponse]:
        items, total = await self.repo.list_business_regions(keyword, status, page, page_size)
        return PageResponse[BusinessRegionResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_region_response(item) for item in items],
        )

    async def create_region(self, payload: BusinessRegionCreateRequest) -> BusinessRegionResponse:
        data = payload.model_dump(exclude_none=True)
        code = (payload.code or "").strip()
        if not code:
            code = await self.sequence_service.next_code("REGION_CODE")
        data["code"] = code
        existed = await self.repo.get_business_region_by_code(code)
        if existed is not None:
            raise ConflictError(f"region code already exists: {code}")
        entity = await self.repo.create_business_region(data)
        await self.db.commit()
        return _to_region_response(entity)

    async def update_region(self, region_id: int, payload: BusinessRegionUpdateRequest) -> BusinessRegionResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        entity = await self.repo.update_business_region(region_id, updates)
        if entity is None:
            raise NotFoundError("Region", region_id)
        await self.db.commit()
        return _to_region_response(entity)

    async def get_region_detail(self, region_id: int) -> BusinessRegionResponse:
        entity = await self.repo.get_business_region(region_id)
        if entity is None:
            raise NotFoundError("Region", region_id)
        return _to_region_response(entity)

    async def list_region_boundary_versions(self, region_id: int) -> list[RegionBoundaryVersionResponse]:
        rows = await self.repo.list_region_boundaries(region_id)
        return [_to_boundary_response(row) for row in rows]

    async def create_region_boundary_version(
        self,
        region_id: int,
        payload: RegionBoundaryVersionCreateRequest,
    ) -> RegionBoundaryVersionResponse:
        region = await self.repo.get_business_region(region_id)
        if region is None:
            raise NotFoundError("Region", region_id)
        entity = await self.repo.create_boundary_version(region_id, payload.model_dump())
        if payload.is_current:
            await self.repo.set_current_boundary_version(region_id, entity.id)
        await self.db.commit()
        return _to_boundary_response(entity)

    async def set_current_boundary(self, region_id: int, version_id: int) -> None:
        ok = await self.repo.set_current_boundary_version(region_id, version_id)
        if not ok:
            raise NotFoundError("RegionBoundaryVersion", version_id)
        await self.db.commit()

    async def replace_region_cities(self, region_id: int, city_codes: list[str]) -> list[RegionCityRelationResponse]:
        region = await self.repo.get_business_region(region_id)
        if region is None:
            raise NotFoundError("Region", region_id)
        rows = await self.repo.replace_region_cities(region_id, city_codes)
        await self.db.commit()

        city_map = {}
        if city_codes:
            from app.models.address import AdminRegion
            from sqlalchemy import select

            result = await self.db.execute(select(AdminRegion).where(AdminRegion.code.in_(city_codes)))
            city_map = {row.id: row for row in result.scalars().all()}

        return [
            RegionCityRelationResponse(
                id=row.id,
                region_id=row.region_id,
                city_region_id=row.city_region_id,
                city_code=city_map.get(row.city_region_id).code if city_map.get(row.city_region_id) else "",
                city_name=city_map.get(row.city_region_id).name if city_map.get(row.city_region_id) else "",
                relation_type_code=row.relation_type_code,
                is_primary=row.is_primary,
                sort_order=row.sort_order,
            )
            for row in rows
        ]


class TransportNodeService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = TransportNodeRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def list_nodes(
        self,
        keyword: str | None,
        city_code: str | None,
        status: int | None,
        category_code: str | None,
        page: int,
        page_size: int,
    ) -> PageResponse[TransportNodeResponse]:
        items, total = await self.repo.list_nodes(keyword, city_code, status, category_code, page, page_size)
        return PageResponse[TransportNodeResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_node_response(item) for item in items],
        )

    async def create_node(self, payload: TransportNodeCreateRequest) -> TransportNodeResponse:
        data = payload.model_dump(exclude_none=True)
        code = (payload.code or "").strip()
        if not code:
            code = await self.sequence_service.next_code("NODE_CODE")
        data["code"] = code
        if await self.repo.get_node_by_code(code):
            raise ConflictError(f"node code already exists: {code}")
        entity = await self.repo.create_node(data)
        await self.db.commit()
        return _to_node_response(entity)

    async def update_node(self, node_id: int, payload: TransportNodeUpdateRequest) -> TransportNodeResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        entity = await self.repo.update_node(node_id, updates)
        if entity is None:
            raise NotFoundError("TransportNode", node_id)
        await self.db.commit()
        return _to_node_response(entity)

    async def get_node_detail(self, node_id: int) -> TransportNodeDetailResponse:
        node = await self.repo.get_node(node_id)
        if node is None:
            raise NotFoundError("TransportNode", node_id)
        profile = await self.repo.get_node_profile(node_id)
        aliases = await self.repo.list_node_aliases(node_id)
        business_codes = await self.repo.list_node_business_categories(node_id)
        packaging_codes = await self.repo.list_node_packaging_forms(node_id)
        handling_codes = await self.repo.list_node_handling_modes(node_id)

        profile_payload = None
        if profile is not None:
            profile_payload = TransportNodeProfileResponse(
                id=profile.id,
                node_id=profile.node_id,
                business_nature_code=profile.business_nature_code,
                channel_depth_m=profile.channel_depth_m,
                max_draft_m=profile.max_draft_m,
                berth_count=profile.berth_count,
                annual_throughput_ton=profile.annual_throughput_ton,
                open_hours_desc=profile.open_hours_desc,
                contact_person=profile.contact_person,
                contact_phone=profile.contact_phone,
                ext_json=profile.ext_json,
                updated_at=profile.updated_at,
            )

        return TransportNodeDetailResponse(
            node=_to_node_response(node),
            profile=profile_payload,
            aliases=[row.alias_name for row in aliases],
            business_category_codes=business_codes,
            packaging_form_codes=packaging_codes,
            handling_mode_codes=handling_codes,
        )

    async def update_node_profile(self, node_id: int, payload: TransportNodeProfileUpsertRequest) -> TransportNodeProfileResponse:
        node = await self.repo.get_node(node_id)
        if node is None:
            raise NotFoundError("TransportNode", node_id)
        profile = await self.repo.upsert_node_profile(node_id, payload.model_dump())
        await self.db.commit()
        return TransportNodeProfileResponse(
            id=profile.id,
            node_id=profile.node_id,
            business_nature_code=profile.business_nature_code,
            channel_depth_m=profile.channel_depth_m,
            max_draft_m=profile.max_draft_m,
            berth_count=profile.berth_count,
            annual_throughput_ton=profile.annual_throughput_ton,
            open_hours_desc=profile.open_hours_desc,
            contact_person=profile.contact_person,
            contact_phone=profile.contact_phone,
            ext_json=profile.ext_json,
            updated_at=profile.updated_at,
        )

    async def replace_node_aliases(self, node_id: int, aliases: list[str]) -> None:
        node = await self.repo.get_node(node_id)
        if node is None:
            raise NotFoundError("TransportNode", node_id)
        await self.repo.replace_node_aliases(node_id, aliases)
        await self.db.commit()

    async def replace_node_business_categories(self, node_id: int, category_codes: list[str]) -> None:
        node = await self.repo.get_node(node_id)
        if node is None:
            raise NotFoundError("TransportNode", node_id)
        await self.repo.replace_node_business_categories(node_id, category_codes)
        await self.db.commit()

    async def replace_node_packaging_forms(self, node_id: int, form_codes: list[str]) -> None:
        node = await self.repo.get_node(node_id)
        if node is None:
            raise NotFoundError("TransportNode", node_id)
        await self.repo.replace_node_packaging_forms(node_id, form_codes)
        await self.db.commit()

    async def replace_node_handling_modes(self, node_id: int, mode_codes: list[str]) -> None:
        node = await self.repo.get_node(node_id)
        if node is None:
            raise NotFoundError("TransportNode", node_id)
        await self.repo.replace_node_handling_modes(node_id, mode_codes)
        await self.db.commit()


def _to_constraint_point_response(row) -> NavigationConstraintPointResponse:
    return NavigationConstraintPointResponse(
        id=row.id,
        code=row.code,
        name=row.name,
        constraint_type_code=row.constraint_type_code,
        province_code=row.province_code,
        city_code=row.city_code,
        longitude=row.longitude,
        latitude=row.latitude,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        severity_level=row.severity_level,
        description=row.description,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_constraint_profile_response(row) -> NavigationConstraintProfileResponse:
    return NavigationConstraintProfileResponse(
        id=row.id,
        constraint_point_id=row.constraint_point_id,
        max_tonnage=row.max_tonnage,
        max_allowed_draft_m=row.max_allowed_draft_m,
        min_water_depth_m=row.min_water_depth_m,
        under_keel_clearance_m=row.under_keel_clearance_m,
        max_air_draft_m=row.max_air_draft_m,
        max_beam_m=row.max_beam_m,
        max_length_m=row.max_length_m,
        allowed_time_window=row.allowed_time_window,
        restriction_rule_json=row.restriction_rule_json,
        rule_description=row.rule_description,
        warning_message=row.warning_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class NavigationConstraintPointService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = NavigationConstraintPointRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def list_constraint_points(
        self,
        keyword: str | None,
        constraint_type_code: str | None,
        city_code: str | None,
        status: int | None,
        page: int,
        page_size: int,
    ) -> PageResponse[NavigationConstraintPointResponse]:
        rows, total = await self.repo.list_constraint_points(
            keyword,
            constraint_type_code,
            city_code,
            status,
            page,
            page_size,
        )
        return PageResponse[NavigationConstraintPointResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_constraint_point_response(item) for item in rows],
        )

    async def get_constraint_point_detail(self, point_id: int) -> NavigationConstraintPointDetailResponse:
        row = await self.repo.get_constraint_point(point_id)
        if row is None:
            raise NotFoundError("NavigationConstraintPoint", point_id)
        profile = await self.repo.get_constraint_profile(point_id)
        return NavigationConstraintPointDetailResponse(
            point=_to_constraint_point_response(row),
            profile=_to_constraint_profile_response(profile) if profile is not None else None,
        )

    async def create_constraint_point(
        self,
        payload: NavigationConstraintPointCreateRequest,
    ) -> NavigationConstraintPointResponse:
        data = payload.model_dump(exclude_none=True)
        code = (payload.code or "").strip()
        if not code:
            code = await self.sequence_service.next_code("NAV_CONSTRAINT_POINT_CODE")
        data["code"] = code
        if await self.repo.get_constraint_point_by_code(code):
            raise ConflictError(f"constraint point code already exists: {code}")
        row = await self.repo.create_constraint_point(data)
        await self.db.commit()
        return _to_constraint_point_response(row)

    async def upsert_constraint_profile(
        self,
        point_id: int,
        payload: NavigationConstraintProfileUpsertRequest,
    ) -> NavigationConstraintProfileResponse:
        point = await self.repo.get_constraint_point(point_id)
        if point is None:
            raise NotFoundError("NavigationConstraintPoint", point_id)
        profile = await self.repo.upsert_constraint_profile(point_id, payload.model_dump())
        await self.db.commit()
        return _to_constraint_profile_response(profile)

    async def change_constraint_point_status(
        self,
        point_id: int,
        payload: NavigationConstraintPointStatusChangeRequest,
    ) -> NavigationConstraintPointResponse:
        row = await self.repo.change_constraint_point_status(point_id, payload.status)
        if row is None:
            raise NotFoundError("NavigationConstraintPoint", point_id)
        await self.db.commit()
        return _to_constraint_point_response(row)

    async def update_constraint_point(
        self,
        point_id: int,
        payload: NavigationConstraintPointUpdateRequest,
    ) -> NavigationConstraintPointResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        row = await self.repo.update_constraint_point(point_id, updates)
        if row is None:
            raise NotFoundError("NavigationConstraintPoint", point_id)
        await self.db.commit()
        return _to_constraint_point_response(row)
