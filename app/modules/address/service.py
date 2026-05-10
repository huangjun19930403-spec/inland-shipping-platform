"""address 模块 service。"""

from __future__ import annotations

import logging
from decimal import Decimal
from types import SimpleNamespace

from fastapi import UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.integrations.amap import AmapGeocodeClient
from app.models.address import AdminRegion, WaterSystem, WaterSystemBoundary
from app.modules.address.repository import (
    AdminRegionRepository,
    NavigationConstraintPointRepository,
    RegionRepository,
    TransportNodeRepository,
)
from app.modules.address.geometry import normalize_boundary_geometry, normalize_boundary_source_type
from app.modules.address.schemas import (
    AdminRegionBoundaryResponse,
    AdminRegionResponse,
    AddressMapCandidate,
    AddressMapGeocodeResponse,
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
    WaterSystemBoundaryResponse,
    WaterSystemDetailResponse,
    WaterSystemResponse,
    WaterSystemSummaryResponse,
    NodeAliasResponse,
    TransportNodeContactResponse,
    TransportNodeContactReplaceRequest,
    TransportNodeCreateRequest,
    TransportNodeDetailResponse,
    TransportNodePhotoResponse,
    TransportNodePhotoUpdateRequest,
    TransportNodeProfileResponse,
    TransportNodeProfileUpsertRequest,
    TransportNodeResponse,
    TransportNodeUpdateRequest,
)
from app.modules.dictionary.service import CodeSequenceService
from app.modules.dictionary.labels import (
    DictLabelMap,
    RegionLabelMap,
    dict_label,
    load_admin_region_label_map,
    load_dict_label_map,
    region_label,
    status_name,
)
from app.modules.system.runtime_config import RuntimeConfigService
from app.modules.storage.service import FileStorageService


logger = logging.getLogger(__name__)


WATER_LEVEL_LABELS = {
    0: "待补边界",
    1: "一级水系",
    2: "二级水系",
    3: "三级水系",
    4: "四级水系",
}
WATER_FEATURE_TYPE_LABELS = {
    "RIVER": "河流",
    "CANAL": "运河/航道",
    "LAKE": "湖泊",
    "RESERVOIR": "水库",
    "OTHER": "其他水域",
}
WATER_HYDROLOGY_PERIOD_LABELS = {
    "PERENNIAL": "常年",
    "SEASONAL": "时令",
    "UNKNOWN": "未知",
}
WATER_SALINITY_LABELS = {
    "SALINE": "咸水",
    "FRESH": "淡水",
    "UNKNOWN": "未知",
}
WATER_BOUNDARY_TYPE_LABELS = {
    "DOUBLE_LINE_RIVER": "双线河",
    "BOUNDARY_RIVER": "界河",
    "WATER_BODY": "水域面",
    "STANDARD": "标准边界",
    "OTHER": "其他",
}
WATER_GEOMETRY_STATUS_LABELS = {
    "AVAILABLE": "有边界",
    "MISSING": "缺少边界",
    "INVALID": "边界异常",
    "UNKNOWN": "未知",
}
WATER_NAVIGATION_CATEGORY_LABELS = {
    "MAIN_RIVER": "骨干河流",
    "TRIBUTARY": "重要支流",
    "CANAL": "运河/航道",
    "LAKE": "湖区水域",
    "DELTA_NETWORK": "三角洲水网",
}
WATER_NAVIGATION_SCOPE_LABELS = {
    "CORE": "核心航运水系",
    "IMPORTANT": "重要航运水系",
    "WATER_AREA": "重要湖区水域",
    "REVIEW": "复核保留",
    "MISSING": "待补边界",
}
WATER_AIS_SCOPE_LABELS = {
    "INCLUDED": "参与态势",
    "EXCLUDED": "暂不参与",
}
WATER_MATCH_LEVEL_LABELS = {
    "EXACT": "精确匹配",
    "ALIAS": "别名匹配",
    "SAFE_CONTAINS": "安全包含",
    "MISSING": "未命中",
}
WATER_MATCH_CONFIDENCE_LABELS = {
    "HIGH": "高",
    "MEDIUM": "中",
    "LOW": "低",
}
WATER_GEOMETRY_UNION_LABELS = {
    "SINGLE_SOURCE": "单要素",
    "MULTIPART_MERGED": "多要素合并",
    "MISSING": "缺少边界",
}
WATER_BOUNDARY_QUALITY_LABELS = {
    "HIGH_CONFIDENCE": "高置信",
    "MEDIUM_CONFIDENCE": "中置信",
    "REVIEW": "待复核",
    "MISSING": "缺少边界",
    "UNKNOWN": "未知",
}


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


def _to_region_response(row, labels: DictLabelMap | None = None) -> BusinessRegionResponse:
    labels = labels or {}
    return BusinessRegionResponse(
        id=row.id,
        code=row.code,
        name=row.name,
        short_name=row.short_name,
        region_type_code=row.region_type_code,
        region_type_name=dict_label(labels, "REGION_TYPE", row.region_type_code),
        description=row.description,
        sort_order=row.sort_order,
        status=row.status,
        status_name=status_name(row.status),
        current_boundary_version_id=row.current_boundary_version_id,
        audit_status=row.audit_status,
        audit_status_name=dict_label(labels, "AUDIT_STATUS", row.audit_status),
        submitter_id=row.submitter_id,
        auditor_id=row.auditor_id,
        audited_at=row.audited_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_admin_boundary_response(
    row,
    admin_region,
    labels: DictLabelMap | None = None,
) -> AdminRegionBoundaryResponse:
    labels = labels or {}
    source_code = normalize_boundary_source_type(row.boundary_source_type_code)
    return AdminRegionBoundaryResponse(
        id=row.id,
        admin_region_id=row.admin_region_id,
        admin_code=admin_region.code,
        admin_name=admin_region.name,
        version_no=row.version_no,
        boundary_source_type_code=source_code,
        boundary_source_type_name=dict_label(labels, "BOUNDARY_SOURCE_TYPE", source_code),
        geometry_json=normalize_boundary_geometry(row.geometry_json),
        center_longitude=row.center_longitude,
        center_latitude=row.center_latitude,
        area_km2=row.area_km2,
        is_current=row.is_current,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        imported_by=row.imported_by,
        imported_at=row.imported_at,
        remark=row.remark,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _water_level_name(level: int) -> str:
    return WATER_LEVEL_LABELS.get(level, f"{level}级水系")


def _water_feature_type_name(code: str | None) -> str:
    return WATER_FEATURE_TYPE_LABELS.get(code or "OTHER", code or "其他水域")


def _water_hydrology_period_name(code: str | None) -> str:
    return WATER_HYDROLOGY_PERIOD_LABELS.get(code or "UNKNOWN", code or "未知")


def _water_salinity_name(code: str | None) -> str:
    return WATER_SALINITY_LABELS.get(code or "UNKNOWN", code or "未知")


def _water_boundary_type_name(code: str | None) -> str:
    return WATER_BOUNDARY_TYPE_LABELS.get(code or "OTHER", code or "其他")


def _water_geometry_status_name(code: str | None) -> str:
    return WATER_GEOMETRY_STATUS_LABELS.get(code or "UNKNOWN", code or "未知")


def _water_navigation_category_name(code: str | None) -> str | None:
    return WATER_NAVIGATION_CATEGORY_LABELS.get(code or "")


def _water_navigation_scope_name(code: str | None) -> str | None:
    return WATER_NAVIGATION_SCOPE_LABELS.get(code or "")


def _water_ais_scope_name(code: str | None) -> str | None:
    return WATER_AIS_SCOPE_LABELS.get(code or "")


def _water_match_level_name(code: str | None) -> str | None:
    return WATER_MATCH_LEVEL_LABELS.get(code or "")


def _water_match_confidence_name(code: str | None) -> str | None:
    return WATER_MATCH_CONFIDENCE_LABELS.get(code or "")


def _water_geometry_union_status_name(code: str | None) -> str | None:
    return WATER_GEOMETRY_UNION_LABELS.get(code or "")


def _water_boundary_quality_name(code: str | None) -> str:
    return WATER_BOUNDARY_QUALITY_LABELS.get(code or "UNKNOWN", code or "未知")


def _source_level_names(levels: list[int] | None) -> list[str]:
    return [_water_level_name(level) for level in levels or []]


def _boundary_paths_by_precision(boundary: WaterSystemBoundary | None, precision: str) -> list[list[list[float]]]:
    if boundary is None:
        return []
    if precision == "high":
        return boundary.boundary_paths_high or []
    if precision == "medium":
        return boundary.boundary_paths_medium or []
    return boundary.boundary_paths_low or []


def _to_water_system_response(
    row: WaterSystem,
    boundary: WaterSystemBoundary | None,
) -> WaterSystemResponse:
    geometry_status_code = boundary.geometry_status_code if boundary else "MISSING"
    return WaterSystemResponse(
        id=row.id,
        water_system_code=row.water_system_code,
        water_system_name=row.water_system_name,
        standard_name=row.standard_name,
        display_name=row.display_name,
        parent_water_system_code=row.parent_water_system_code,
        water_level=row.water_level,
        water_level_name=_water_level_name(row.water_level),
        feature_type_code=row.feature_type_code,
        feature_type_name=_water_feature_type_name(row.feature_type_code),
        hydrology_period_code=row.hydrology_period_code,
        hydrology_period_name=_water_hydrology_period_name(row.hydrology_period_code),
        salinity_type_code=row.salinity_type_code,
        salinity_type_name=_water_salinity_name(row.salinity_type_code),
        water_boundary_type_code=row.water_boundary_type_code,
        water_boundary_type_name=_water_boundary_type_name(row.water_boundary_type_code),
        navigation_category_code=row.navigation_category_code,
        navigation_category_name=_water_navigation_category_name(row.navigation_category_code),
        navigation_scope_code=row.navigation_scope_code,
        navigation_scope_name=_water_navigation_scope_name(row.navigation_scope_code),
        ais_situation_scope=row.ais_situation_scope,
        ais_situation_scope_name=_water_ais_scope_name(row.ais_situation_scope),
        display_priority=row.display_priority,
        match_level_code=row.match_level_code,
        match_level_name=_water_match_level_name(row.match_level_code),
        match_confidence_code=row.match_confidence_code,
        match_confidence_name=_water_match_confidence_name(row.match_confidence_code),
        review_required=row.review_required,
        source_feature_count=row.source_feature_count,
        source_object_ids=row.source_object_ids or [],
        source_levels=row.source_levels or [],
        source_level_names=_source_level_names(row.source_levels),
        source_layer_names=row.source_layer_names or [],
        source_names=row.source_names or [],
        source_remarks=row.source_remarks or [],
        geometry_union_status=row.geometry_union_status,
        geometry_union_status_name=_water_geometry_union_status_name(row.geometry_union_status),
        business_remark=row.business_remark,
        source_remark=row.source_remark,
        source_layer_name=row.source_layer_name,
        source_version=row.source_version,
        is_enabled=row.is_enabled,
        has_boundary=bool(boundary and boundary.geometry_status_code == "AVAILABLE"),
        geometry_status_code=geometry_status_code,
        geometry_status_name=_water_geometry_status_name(geometry_status_code),
        imported_at=boundary.imported_at if boundary else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_water_system_detail_response(
    row: WaterSystem,
    boundary: WaterSystemBoundary | None,
) -> WaterSystemDetailResponse:
    base = _to_water_system_response(row, boundary).model_dump()
    return WaterSystemDetailResponse(
        **base,
        center_longitude=boundary.center_longitude if boundary else None,
        center_latitude=boundary.center_latitude if boundary else None,
        display_center_longitude=row.display_center_longitude,
        display_center_latitude=row.display_center_latitude,
        ring_count=boundary.ring_count if boundary else 0,
        point_count=boundary.point_count if boundary else 0,
        boundary_quality_code=boundary.boundary_quality_code if boundary else "MISSING",
        boundary_quality_name=_water_boundary_quality_name(boundary.boundary_quality_code if boundary else "MISSING"),
    )


def _to_water_boundary_response(
    row: WaterSystem,
    boundary: WaterSystemBoundary | None,
    precision: str,
) -> WaterSystemBoundaryResponse:
    paths = _boundary_paths_by_precision(boundary, precision)
    geometry_status_code = boundary.geometry_status_code if boundary else "MISSING"
    return WaterSystemBoundaryResponse(
        water_system_code=row.water_system_code,
        water_system_name=row.water_system_name,
        water_level=row.water_level,
        water_level_name=_water_level_name(row.water_level),
        navigation_category_code=row.navigation_category_code,
        navigation_category_name=_water_navigation_category_name(row.navigation_category_code),
        navigation_scope_code=row.navigation_scope_code,
        navigation_scope_name=_water_navigation_scope_name(row.navigation_scope_code),
        parent_water_system_code=row.parent_water_system_code,
        precision=precision,
        boundary_paths=paths,
        has_boundary=bool(paths),
        geometry_status_code=geometry_status_code,
        geometry_status_name=_water_geometry_status_name(geometry_status_code),
        boundary_quality_code=boundary.boundary_quality_code if boundary else "MISSING",
        boundary_quality_name=_water_boundary_quality_name(boundary.boundary_quality_code if boundary else "MISSING"),
        center_longitude=boundary.center_longitude if boundary else None,
        center_latitude=boundary.center_latitude if boundary else None,
        display_center_longitude=row.display_center_longitude,
        display_center_latitude=row.display_center_latitude,
    )


def _to_boundary_response(row, labels: DictLabelMap | None = None) -> RegionBoundaryVersionResponse:
    labels = labels or {}
    source_code = normalize_boundary_source_type(row.boundary_source_type_code)
    return RegionBoundaryVersionResponse(
        id=row.id,
        region_id=row.region_id,
        version_no=row.version_no,
        boundary_source_type_code=source_code,
        boundary_source_type_name=dict_label(labels, "BOUNDARY_SOURCE_TYPE", source_code),
        geometry_json=normalize_boundary_geometry(row.geometry_json),
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


def _to_node_response(
    row,
    dict_labels: DictLabelMap | None = None,
    region_labels: RegionLabelMap | None = None,
) -> TransportNodeResponse:
    dict_labels = dict_labels or {}
    region_labels = region_labels or {}
    return TransportNodeResponse(
        id=row.id,
        code=row.code,
        name=row.name,
        short_name=row.short_name,
        node_type_code=row.node_type_code,
        node_type_name=dict_label(dict_labels, "NODE_TYPE", row.node_type_code),
        province_code=row.province_code,
        province_name=region_label(region_labels, row.province_code),
        city_code=row.city_code,
        city_name=region_label(region_labels, row.city_code),
        district_code=row.district_code,
        district_name=region_label(region_labels, row.district_code),
        city_region_id=row.city_region_id,
        address=row.address,
        longitude=row.longitude,
        latitude=row.latitude,
        status=row.status,
        status_name=status_name(row.status),
        lifecycle_status_code=row.lifecycle_status_code,
        lifecycle_status_name=dict_label(dict_labels, "PROFILE_STATUS", row.lifecycle_status_code),
        sort_order=row.sort_order,
        is_hot_node=row.is_hot_node,
        audit_status=row.audit_status,
        audit_status_name=dict_label(dict_labels, "AUDIT_STATUS", row.audit_status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_node_profile_response(row) -> TransportNodeProfileResponse:
    return TransportNodeProfileResponse(
        id=row.id,
        node_id=row.node_id,
        business_nature_code=row.business_nature_code,
        channel_depth_m=row.channel_depth_m,
        max_draft_m=row.max_draft_m,
        berth_count=row.berth_count,
        annual_throughput_ton=row.annual_throughput_ton,
        open_hours_desc=row.open_hours_desc,
        ext_json=row.ext_json,
        updated_at=row.updated_at,
    )


def _to_node_contact_response(row, labels: DictLabelMap | None = None) -> TransportNodeContactResponse:
    labels = labels or {}
    return TransportNodeContactResponse(
        id=row.id,
        node_id=row.node_id,
        contact_name=row.contact_name,
        contact_type_code=row.contact_type_code,
        contact_type_name=dict_label(labels, "NODE_CONTACT_TYPE", row.contact_type_code),
        mobile_phone=row.mobile_phone,
        wechat=row.wechat,
        email=row.email,
        is_primary=row.is_primary,
        remark=row.remark,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_node_photo_response(row, storage_file, labels: DictLabelMap | None = None) -> TransportNodePhotoResponse:
    labels = labels or {}
    return TransportNodePhotoResponse(
        id=row.id,
        node_id=row.node_id,
        file_id=row.file_id,
        photo_type_code=row.photo_type_code,
        photo_type_name=dict_label(labels, "NODE_PHOTO_TYPE", row.photo_type_code),
        photo_name=row.photo_name,
        description=row.description,
        is_primary=row.is_primary,
        sort_order=row.sort_order,
        content_url=f"/api/v1/files/{row.file_id}/content",
        original_file_name=storage_file.original_file_name,
        content_type=storage_file.content_type,
        file_size=storage_file.file_size,
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

    async def list_boundary_versions(self, admin_code: str) -> list[AdminRegionBoundaryResponse]:
        row = await self.repo.get_region_by_code(admin_code)
        if row is None:
            raise NotFoundError("AdminRegion", admin_code)
        labels = await load_dict_label_map(self.db, ["BOUNDARY_SOURCE_TYPE"])
        boundaries = await self.repo.list_boundaries(row.id)
        return [_to_admin_boundary_response(item, row, labels) for item in boundaries]

    async def get_current_boundary(self, admin_code: str) -> AdminRegionBoundaryResponse | None:
        row = await self.repo.get_region_by_code(admin_code)
        if row is None:
            raise NotFoundError("AdminRegion", admin_code)
        labels = await load_dict_label_map(self.db, ["BOUNDARY_SOURCE_TYPE"])
        boundary = await self.repo.get_current_boundary(row.id)
        if boundary is None:
            return None
        return _to_admin_boundary_response(boundary, row, labels)

    async def list_city_options(self) -> list[AdminRegionResponse]:
        rows = await self.repo.list_cities()
        return [_to_admin_region_response(row) for row in rows]

    async def list_district_options(self, city_code: str) -> list[AdminRegionResponse]:
        rows = await self.repo.list_districts_by_city(city_code)
        return [_to_admin_region_response(row) for row in rows]

    async def list_children(self, admin_code: str) -> list[AdminRegionResponse]:
        rows = await self.repo.get_children(admin_code)
        return [_to_admin_region_response(row) for row in rows]


class WaterSystemService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def summary(self) -> WaterSystemSummaryResponse:
        total_count = int((await self.db.execute(select(func.count()).select_from(WaterSystem))).scalar_one() or 0)
        enabled_count = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(WaterSystem).where(WaterSystem.is_enabled.is_(True))
                )
            ).scalar_one()
            or 0
        )
        boundary_count = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(WaterSystemBoundary)
                    .join(WaterSystem, WaterSystem.id == WaterSystemBoundary.water_system_id)
                    .where(
                        WaterSystem.is_enabled.is_(True),
                        WaterSystemBoundary.is_current.is_(True),
                        WaterSystemBoundary.geometry_status_code == "AVAILABLE",
                    )
                )
            ).scalar_one()
            or 0
        )
        level_rows = (
            await self.db.execute(
                select(WaterSystem.water_level, func.count())
                .where(WaterSystem.is_enabled.is_(True))
                .group_by(WaterSystem.water_level)
            )
        ).all()
        scope_rows = (
            await self.db.execute(
                select(WaterSystem.navigation_scope_code, func.count())
                .where(WaterSystem.is_enabled.is_(True))
                .group_by(WaterSystem.navigation_scope_code)
            )
        ).all()
        category_rows = (
            await self.db.execute(
                select(WaterSystem.navigation_category_code, func.count())
                .where(WaterSystem.is_enabled.is_(True))
                .group_by(WaterSystem.navigation_category_code)
            )
        ).all()
        ais_scope_rows = (
            await self.db.execute(
                select(WaterSystem.ais_situation_scope, func.count())
                .where(WaterSystem.is_enabled.is_(True))
                .group_by(WaterSystem.ais_situation_scope)
            )
        ).all()
        version_row = await self.db.scalar(
            select(WaterSystem.source_version)
            .where(WaterSystem.is_enabled.is_(True))
            .group_by(WaterSystem.source_version)
            .order_by(func.count().desc(), WaterSystem.source_version.desc())
            .limit(1)
        )
        return WaterSystemSummaryResponse(
            total_count=total_count,
            boundary_count=boundary_count,
            enabled_count=enabled_count,
            level_counts={str(level): int(count) for level, count in level_rows},
            navigation_scope_counts={str(scope or "UNKNOWN"): int(count) for scope, count in scope_rows},
            navigation_category_counts={str(category or "UNKNOWN"): int(count) for category, count in category_rows},
            ais_situation_scope_counts={str(scope or "UNKNOWN"): int(count) for scope, count in ais_scope_rows},
            current_source_version=version_row,
        )

    async def list_water_systems(
        self,
        *,
        keyword: str | None,
        water_level: int | None,
        feature_type_code: str | None,
        hydrology_period_code: str | None,
        salinity_type_code: str | None,
        navigation_category_code: str | None,
        navigation_scope_code: str | None,
        ais_situation_scope: str | None,
        geometry_status_code: str | None,
        page: int,
        page_size: int,
    ) -> PageResponse[WaterSystemResponse]:
        stmt = (
            select(
                WaterSystem,
                WaterSystemBoundary.id.label("boundary_id"),
                WaterSystemBoundary.geometry_status_code,
                WaterSystemBoundary.imported_at,
            )
            .outerjoin(
                WaterSystemBoundary,
                (WaterSystemBoundary.water_system_id == WaterSystem.id)
                & (WaterSystemBoundary.is_current.is_(True)),
            )
            .where(WaterSystem.is_enabled.is_(True))
        )
        if keyword:
            like_value = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    WaterSystem.water_system_code.ilike(like_value),
                    WaterSystem.water_system_name.ilike(like_value),
                    WaterSystem.standard_name.ilike(like_value),
                    WaterSystem.display_name.ilike(like_value),
                    WaterSystem.source_remark.ilike(like_value),
                )
            )
        if water_level is not None:
            stmt = stmt.where(WaterSystem.water_level == water_level)
        if feature_type_code:
            stmt = stmt.where(WaterSystem.feature_type_code == feature_type_code)
        if hydrology_period_code:
            stmt = stmt.where(WaterSystem.hydrology_period_code == hydrology_period_code)
        if salinity_type_code:
            stmt = stmt.where(WaterSystem.salinity_type_code == salinity_type_code)
        if navigation_category_code:
            stmt = stmt.where(WaterSystem.navigation_category_code == navigation_category_code)
        if navigation_scope_code:
            stmt = stmt.where(WaterSystem.navigation_scope_code == navigation_scope_code)
        if ais_situation_scope:
            stmt = stmt.where(WaterSystem.ais_situation_scope == ais_situation_scope)
        if geometry_status_code:
            stmt = stmt.where(WaterSystemBoundary.geometry_status_code == geometry_status_code)

        total = int((await self.db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one())
        rows = (
            await self.db.execute(
                stmt.order_by(WaterSystem.display_priority.asc(), WaterSystem.sort_order.asc(), WaterSystem.id.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        items: list[WaterSystemResponse] = []
        for water_system, boundary_id, status_code, imported_at in rows:
            boundary = (
                SimpleNamespace(geometry_status_code=status_code, imported_at=imported_at)
                if boundary_id
                else None
            )
            items.append(_to_water_system_response(water_system, boundary))
        return PageResponse[WaterSystemResponse](total=total, page=page, page_size=page_size, items=items)

    async def get_water_system_detail(self, water_system_code: str) -> WaterSystemDetailResponse:
        row = await self.db.scalar(
            select(WaterSystem).where(
                WaterSystem.water_system_code == water_system_code,
                WaterSystem.is_enabled.is_(True),
            )
        )
        if row is None:
            raise NotFoundError("WaterSystem", water_system_code)
        boundary_row = (
            await self.db.execute(
                select(
                    WaterSystemBoundary.id,
                    WaterSystemBoundary.geometry_status_code,
                WaterSystemBoundary.imported_at,
                WaterSystemBoundary.center_longitude,
                WaterSystemBoundary.center_latitude,
                WaterSystemBoundary.boundary_quality_code,
                WaterSystemBoundary.ring_count,
                WaterSystemBoundary.point_count,
                )
                .where(
                    WaterSystemBoundary.water_system_id == row.id,
                    WaterSystemBoundary.is_current.is_(True),
                )
                .limit(1)
            )
        ).first()
        boundary = None
        if boundary_row is not None:
            boundary = SimpleNamespace(
                geometry_status_code=boundary_row.geometry_status_code,
                imported_at=boundary_row.imported_at,
                center_longitude=boundary_row.center_longitude,
                center_latitude=boundary_row.center_latitude,
                boundary_quality_code=boundary_row.boundary_quality_code,
                ring_count=boundary_row.ring_count,
                point_count=boundary_row.point_count,
            )
        return _to_water_system_detail_response(row, boundary)

    async def get_water_system_boundary(
        self,
        water_system_code: str,
        precision: str,
    ) -> WaterSystemBoundaryResponse:
        normalized_precision = precision if precision in {"low", "medium", "high"} else "medium"
        row = await self.db.scalar(
            select(WaterSystem).where(
                WaterSystem.water_system_code == water_system_code,
                WaterSystem.is_enabled.is_(True),
            )
        )
        if row is None:
            raise NotFoundError("WaterSystem", water_system_code)
        boundary = await self.db.scalar(
            select(WaterSystemBoundary)
            .where(
                WaterSystemBoundary.water_system_id == row.id,
                WaterSystemBoundary.is_current.is_(True),
            )
            .limit(1)
        )
        return _to_water_boundary_response(row, boundary, normalized_precision)


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
        labels = await load_dict_label_map(self.db, ["REGION_TYPE", "AUDIT_STATUS"])
        return PageResponse[BusinessRegionResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_region_response(item, labels) for item in items],
        )

    async def create_region(self, payload: BusinessRegionCreateRequest) -> BusinessRegionResponse:
        data = payload.model_dump(exclude_none=True)
        code = await self.sequence_service.next_code("REGION_CODE")
        data["code"] = code
        existed = await self.repo.get_business_region_by_code(code)
        if existed is not None:
            raise ConflictError(f"region code already exists: {code}")
        entity = await self.repo.create_business_region(data)
        await self.db.commit()
        labels = await load_dict_label_map(self.db, ["REGION_TYPE", "AUDIT_STATUS"])
        return _to_region_response(entity, labels)

    async def update_region(self, region_id: int, payload: BusinessRegionUpdateRequest) -> BusinessRegionResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        entity = await self.repo.update_business_region(region_id, updates)
        if entity is None:
            raise NotFoundError("Region", region_id)
        await self.db.commit()
        labels = await load_dict_label_map(self.db, ["REGION_TYPE", "AUDIT_STATUS"])
        return _to_region_response(entity, labels)

    async def get_region_detail(self, region_id: int) -> BusinessRegionResponse:
        entity = await self.repo.get_business_region(region_id)
        if entity is None:
            raise NotFoundError("Region", region_id)
        labels = await load_dict_label_map(self.db, ["REGION_TYPE", "AUDIT_STATUS"])
        return _to_region_response(entity, labels)

    async def list_region_boundary_versions(self, region_id: int) -> list[RegionBoundaryVersionResponse]:
        region = await self.repo.get_business_region(region_id)
        if region is None:
            raise NotFoundError("Region", region_id)
        rows = await self.repo.list_region_boundaries(region_id)
        labels = await load_dict_label_map(self.db, ["BOUNDARY_SOURCE_TYPE"])
        return [_to_boundary_response(row, labels) for row in rows]

    async def get_current_region_boundary(self, region_id: int) -> RegionBoundaryVersionResponse | None:
        region = await self.repo.get_business_region(region_id)
        if region is None:
            raise NotFoundError("Region", region_id)
        labels = await load_dict_label_map(self.db, ["BOUNDARY_SOURCE_TYPE"])
        row = await self.repo.get_current_region_boundary(region_id)
        if row is None:
            return None
        return _to_boundary_response(row, labels)

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
        labels = await load_dict_label_map(self.db, ["BOUNDARY_SOURCE_TYPE"])
        return _to_boundary_response(entity, labels)

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


class AddressMapService:
    def __init__(self, db: AsyncSession, client: AmapGeocodeClient | None = None) -> None:
        self.db = db
        self.client = client or AmapGeocodeClient(runtime_config=RuntimeConfigService(db))

    async def geocode(self, keyword: str, city_code: str | None = None) -> AddressMapGeocodeResponse:
        try:
            raw_items = await self.client.geocode(keyword=keyword, city_code=city_code)
        except Exception:
            logger.exception("address map geocode provider failed")
            raise

        items: list[AddressMapCandidate] = []
        for raw in raw_items:
            candidate = await self._to_candidate(raw)
            if candidate.city_code and candidate.city_region_id:
                items.append(candidate)
            else:
                logger.info(
                    "skip geocode candidate without city match adcode=%s address=%s",
                    candidate.adcode,
                    candidate.formatted_address,
                )

        if not items:
            raise ValidationError("未匹配到可用于节点回填的城市行政区划")
        return AddressMapGeocodeResponse(items=items)

    async def reverse_geocode(self, longitude: Decimal, latitude: Decimal) -> AddressMapCandidate:
        try:
            raw = await self.client.reverse_geocode(longitude=float(longitude), latitude=float(latitude))
        except Exception:
            logger.exception("address map reverse geocode provider failed")
            raise

        candidate = await self._to_candidate(raw)
        if not candidate.city_code or not candidate.city_region_id:
            raise ValidationError("逆地理编码结果未匹配到可用于节点回填的城市行政区划")
        return candidate

    async def _to_candidate(self, raw) -> AddressMapCandidate:
        province, city, district = await self._resolve_region_context(
            raw.adcode,
            raw.province,
            raw.city,
            raw.district,
        )
        city_region_id = int(city.id) if city is not None else None
        confidence = raw.confidence
        if confidence is None:
            confidence = 1.0 if city_region_id else 0.5
        return AddressMapCandidate(
            longitude=Decimal(str(raw.longitude)),
            latitude=Decimal(str(raw.latitude)),
            formatted_address=raw.formatted_address,
            province_name=province.name if province is not None else raw.province,
            province_code=province.code if province is not None else None,
            city_name=city.name if city is not None else raw.city,
            city_code=city.code if city is not None else None,
            district_name=district.name if district is not None else raw.district,
            district_code=district.code if district is not None else None,
            adcode=raw.adcode,
            city_region_id=city_region_id,
            provider="AMAP",
            confidence=confidence,
            level=raw.level,
        )

    async def _resolve_region_context(
        self,
        adcode: str | None,
        province_name: str | None,
        city_name: str | None,
        district_name: str | None,
    ) -> tuple[AdminRegion | None, AdminRegion | None, AdminRegion | None]:
        exact = await self._region_by_code(adcode)
        if exact is not None:
            if exact.level == 3:
                city = await self._region_by_code(exact.city_code or exact.parent_code)
                province = await self._region_by_code(exact.province_code or (city.province_code if city else None))
                return province, city, exact
            if exact.level == 2:
                province = await self._region_by_code(exact.province_code or exact.parent_code)
                return province, exact, None
            if exact.level == 1:
                return exact, None, None

        province = await self._region_by_name(province_name, level=1)
        city = await self._region_by_name(city_name, level=2, parent_code=province.code if province else None)
        district = await self._region_by_name(district_name, level=3, parent_code=city.code if city else None)

        if district is not None and city is None:
            city = await self._region_by_code(district.city_code or district.parent_code)
        if city is not None and province is None:
            province = await self._region_by_code(city.province_code or city.parent_code)
        return province, city, district

    async def _region_by_code(self, code: str | None) -> AdminRegion | None:
        if not code:
            return None
        return await self.db.scalar(
            select(AdminRegion).where(AdminRegion.code == code, AdminRegion.status == 1)
        )

    async def _region_by_name(
        self,
        name: str | None,
        *,
        level: int,
        parent_code: str | None = None,
    ) -> AdminRegion | None:
        if not name:
            return None
        stmt = select(AdminRegion).where(
            AdminRegion.level == level,
            AdminRegion.status == 1,
            or_(AdminRegion.name == name, AdminRegion.short_name == name),
        )
        if parent_code:
            stmt = stmt.where(AdminRegion.parent_code == parent_code)
        return await self.db.scalar(stmt.order_by(AdminRegion.sort_order.asc(), AdminRegion.code.asc()).limit(1))


class TransportNodeService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = TransportNodeRepository(db)
        self.sequence_service = CodeSequenceService(db)

    async def _resolve_city_region_id(self, city_code: str | None) -> int:
        if not city_code:
            raise ValidationError("city_code is required")
        city = await self.db.scalar(
            select(AdminRegion).where(
                AdminRegion.code == city_code,
                AdminRegion.level == 2,
                AdminRegion.status == 1,
            )
        )
        if city is None:
            raise ValidationError(f"city_code not found in admin regions: {city_code}")
        return int(city.id)

    async def _node_label_context(self, rows: list) -> tuple[DictLabelMap, RegionLabelMap]:
        dict_labels = await load_dict_label_map(
            self.db,
            [
                "NODE_TYPE",
                "PROFILE_STATUS",
                "AUDIT_STATUS",
                "NODE_CONTACT_TYPE",
                "NODE_PHOTO_TYPE",
            ],
        )
        region_codes: list[str | None] = []
        for row in rows:
            region_codes.extend([row.province_code, row.city_code, row.district_code])
        region_labels = await load_admin_region_label_map(self.db, region_codes)
        return dict_labels, region_labels

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
        dict_labels, region_labels = await self._node_label_context(items)
        return PageResponse[TransportNodeResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_node_response(item, dict_labels, region_labels) for item in items],
        )

    async def create_node(self, payload: TransportNodeCreateRequest) -> TransportNodeResponse:
        data = payload.model_dump(exclude_none=True)
        code = await self.sequence_service.next_code("NODE_CODE")
        data["code"] = code
        data["city_region_id"] = await self._resolve_city_region_id(payload.city_code)
        if await self.repo.get_node_by_code(code):
            raise ConflictError(f"node code already exists: {code}")
        entity = await self.repo.create_node(data)
        await self.db.commit()
        dict_labels, region_labels = await self._node_label_context([entity])
        return _to_node_response(entity, dict_labels, region_labels)

    async def update_node(self, node_id: int, payload: TransportNodeUpdateRequest) -> TransportNodeResponse:
        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise ValidationError("no update fields provided")
        if "city_code" in updates:
            updates["city_region_id"] = await self._resolve_city_region_id(updates["city_code"])
        entity = await self.repo.update_node(node_id, updates)
        if entity is None:
            raise NotFoundError("TransportNode", node_id)
        await self.db.commit()
        dict_labels, region_labels = await self._node_label_context([entity])
        return _to_node_response(entity, dict_labels, region_labels)

    async def get_node_detail(self, node_id: int) -> TransportNodeDetailResponse:
        node = await self.repo.get_node(node_id)
        if node is None:
            raise NotFoundError("TransportNode", node_id)
        profile = await self.repo.get_node_profile(node_id)
        aliases = await self.repo.list_node_aliases(node_id)
        business_codes = await self.repo.list_node_business_categories(node_id)
        packaging_codes = await self.repo.list_node_packaging_forms(node_id)
        handling_codes = await self.repo.list_node_handling_modes(node_id)
        contacts = await self.repo.list_node_contacts(node_id)
        photos = await self.repo.list_node_photos(node_id)
        dict_labels, region_labels = await self._node_label_context([node])

        return TransportNodeDetailResponse(
            node=_to_node_response(node, dict_labels, region_labels),
            profile=_to_node_profile_response(profile) if profile is not None else None,
            contacts=[_to_node_contact_response(row, dict_labels) for row in contacts],
            photos=[_to_node_photo_response(photo, storage_file, dict_labels) for photo, storage_file in photos],
            aliases=[row.alias_name for row in aliases],
            aliases_meta=[
                NodeAliasResponse(
                    id=row.id,
                    alias_name=row.alias_name,
                    alias_type_code=row.alias_type_code,
                    source_type_code=row.source_type_code,
                    is_primary=row.is_primary,
                )
                for row in aliases
            ],
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
        return _to_node_profile_response(profile)

    async def list_node_contacts(self, node_id: int) -> list[TransportNodeContactResponse]:
        node = await self.repo.get_node(node_id)
        if node is None:
            raise NotFoundError("TransportNode", node_id)
        labels = await load_dict_label_map(self.db, ["NODE_CONTACT_TYPE"])
        contacts = await self.repo.list_node_contacts(node_id)
        return [_to_node_contact_response(row, labels) for row in contacts]

    async def replace_node_contacts(
        self,
        node_id: int,
        payload: TransportNodeContactReplaceRequest,
    ) -> list[TransportNodeContactResponse]:
        node = await self.repo.get_node(node_id)
        if node is None:
            raise NotFoundError("TransportNode", node_id)

        rows_data = []
        primary_seen = False
        for item in payload.contacts:
            data = item.model_dump()
            data["contact_name"] = data["contact_name"].strip()
            data["contact_type_code"] = data["contact_type_code"].strip()
            for key in ("mobile_phone", "wechat", "email", "remark"):
                if isinstance(data.get(key), str):
                    data[key] = data[key].strip() or None
            if not data["contact_name"] or not data["contact_type_code"]:
                raise ValidationError("联系人名称和类型不能为空")
            if data["is_primary"] and primary_seen:
                data["is_primary"] = False
            primary_seen = primary_seen or data["is_primary"]
            rows_data.append(data)

        if rows_data and not primary_seen:
            rows_data[0]["is_primary"] = True

        contacts = await self.repo.replace_node_contacts(node_id, rows_data)
        await self.db.commit()
        labels = await load_dict_label_map(self.db, ["NODE_CONTACT_TYPE"])
        return [_to_node_contact_response(row, labels) for row in contacts]

    async def list_node_photos(self, node_id: int) -> list[TransportNodePhotoResponse]:
        node = await self.repo.get_node(node_id)
        if node is None:
            raise NotFoundError("TransportNode", node_id)
        labels = await load_dict_label_map(self.db, ["NODE_PHOTO_TYPE"])
        rows = await self.repo.list_node_photos(node_id)
        return [_to_node_photo_response(photo, storage_file, labels) for photo, storage_file in rows]

    async def create_node_photo(
        self,
        node_id: int,
        *,
        file: UploadFile,
        photo_type_code: str,
        photo_name: str | None,
        description: str | None,
        is_primary: bool,
        sort_order: int,
        uploaded_by: int | None,
    ) -> TransportNodePhotoResponse:
        node = await self.repo.get_node(node_id)
        if node is None:
            raise NotFoundError("TransportNode", node_id)

        existing_photos = await self.repo.list_node_photos(node_id)
        photo_type = photo_type_code.strip()
        if not photo_type:
            raise ValidationError("照片类型不能为空")
        storage_file = await FileStorageService(self.db).upload_image(
            file=file,
            object_prefix=f"transport-nodes/{node_id}/photos",
            uploaded_by=uploaded_by,
        )
        primary = is_primary or not existing_photos
        if primary:
            await self.repo.clear_primary_node_photos(node_id)
        display_name = (photo_name or "").strip() or storage_file.original_file_name
        photo = await self.repo.create_node_photo(
            {
                "node_id": node_id,
                "file_id": storage_file.id,
                "photo_type_code": photo_type,
                "photo_name": display_name[:128],
                "description": (description or "").strip() or None,
                "is_primary": primary,
                "sort_order": sort_order,
            }
        )
        await self.db.commit()
        labels = await load_dict_label_map(self.db, ["NODE_PHOTO_TYPE"])
        return _to_node_photo_response(photo, storage_file, labels)

    async def update_node_photo(
        self,
        node_id: int,
        photo_id: int,
        payload: TransportNodePhotoUpdateRequest,
    ) -> TransportNodePhotoResponse:
        row = await self.repo.get_node_photo_with_file(photo_id)
        if row is None:
            raise NotFoundError("TransportNodePhoto", photo_id)
        photo, storage_file = row
        if photo.node_id != node_id:
            raise NotFoundError("TransportNodePhoto", photo_id)

        updates = payload.model_dump(exclude_unset=True)
        for key in ("photo_type_code", "photo_name", "description"):
            if isinstance(updates.get(key), str):
                updates[key] = updates[key].strip() or None
        if "photo_type_code" in updates and not updates["photo_type_code"]:
            raise ValidationError("照片类型不能为空")
        if "photo_name" in updates and not updates["photo_name"]:
            raise ValidationError("照片名称不能为空")
        if not updates:
            raise ValidationError("no update fields provided")
        if updates.get("is_primary") is True:
            await self.repo.clear_primary_node_photos(node_id, except_photo_id=photo_id)

        updated = await self.repo.update_node_photo(photo_id, updates)
        if updated is None:
            raise NotFoundError("TransportNodePhoto", photo_id)
        await self.db.commit()
        labels = await load_dict_label_map(self.db, ["NODE_PHOTO_TYPE"])
        return _to_node_photo_response(updated, storage_file, labels)

    async def delete_node_photo(self, node_id: int, photo_id: int) -> None:
        row = await self.repo.get_node_photo_with_file(photo_id)
        if row is None:
            raise NotFoundError("TransportNodePhoto", photo_id)
        photo, storage_file = row
        if photo.node_id != node_id:
            raise NotFoundError("TransportNodePhoto", photo_id)
        await self.repo.delete_node_photo(photo_id)
        await FileStorageService(self.db).delete_file_entity(storage_file)
        await self.db.commit()

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


def _to_constraint_point_response(
    row,
    dict_labels: DictLabelMap | None = None,
    region_labels: RegionLabelMap | None = None,
) -> NavigationConstraintPointResponse:
    dict_labels = dict_labels or {}
    region_labels = region_labels or {}
    return NavigationConstraintPointResponse(
        id=row.id,
        code=row.code,
        name=row.name,
        constraint_type_code=row.constraint_type_code,
        constraint_type_name=dict_label(dict_labels, "NAVIGATION_CONSTRAINT_TYPE", row.constraint_type_code),
        province_code=row.province_code,
        province_name=region_label(region_labels, row.province_code),
        city_code=row.city_code,
        city_name=region_label(region_labels, row.city_code),
        longitude=row.longitude,
        latitude=row.latitude,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        severity_level=row.severity_level,
        description=row.description,
        status=row.status,
        status_name=status_name(row.status),
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

    async def _point_label_context(self, rows: list) -> tuple[DictLabelMap, RegionLabelMap]:
        dict_labels = await load_dict_label_map(self.db, ["NAVIGATION_CONSTRAINT_TYPE"])
        region_codes: list[str | None] = []
        for row in rows:
            region_codes.extend([row.province_code, row.city_code])
        region_labels = await load_admin_region_label_map(self.db, region_codes)
        return dict_labels, region_labels

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
        dict_labels, region_labels = await self._point_label_context(rows)
        return PageResponse[NavigationConstraintPointResponse](
            total=total,
            page=page,
            page_size=page_size,
            items=[_to_constraint_point_response(item, dict_labels, region_labels) for item in rows],
        )

    async def get_constraint_point_detail(self, point_id: int) -> NavigationConstraintPointDetailResponse:
        row = await self.repo.get_constraint_point(point_id)
        if row is None:
            raise NotFoundError("NavigationConstraintPoint", point_id)
        profile = await self.repo.get_constraint_profile(point_id)
        dict_labels, region_labels = await self._point_label_context([row])
        return NavigationConstraintPointDetailResponse(
            point=_to_constraint_point_response(row, dict_labels, region_labels),
            profile=_to_constraint_profile_response(profile) if profile is not None else None,
        )

    async def create_constraint_point(
        self,
        payload: NavigationConstraintPointCreateRequest,
    ) -> NavigationConstraintPointResponse:
        data = payload.model_dump(exclude_none=True)
        code = await self.sequence_service.next_code("NAV_CONSTRAINT_POINT_CODE")
        data["code"] = code
        if await self.repo.get_constraint_point_by_code(code):
            raise ConflictError(f"constraint point code already exists: {code}")
        row = await self.repo.create_constraint_point(data)
        await self.db.commit()
        dict_labels, region_labels = await self._point_label_context([row])
        return _to_constraint_point_response(row, dict_labels, region_labels)

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
        dict_labels, region_labels = await self._point_label_context([row])
        return _to_constraint_point_response(row, dict_labels, region_labels)

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
        dict_labels, region_labels = await self._point_label_context([row])
        return _to_constraint_point_response(row, dict_labels, region_labels)
