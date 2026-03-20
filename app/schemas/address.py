from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional

from pydantic import BaseModel, field_validator


# ---------- Waterway ----------


class WaterwayCreate(BaseModel):
    """水系新增请求体。"""

    name: str
    name_en: Optional[str] = None
    level: int = 1
    parent_id: Optional[int] = None
    provinces: Optional[str] = None
    total_length_km: Optional[Decimal] = None
    navigable_length_km: Optional[Decimal] = None
    description: Optional[str] = None
    sort_order: int = 0
    status: int = 1


class WaterwayUpdate(BaseModel):
    name: Optional[str] = None
    name_en: Optional[str] = None
    level: Optional[int] = None
    parent_id: Optional[int] = None
    provinces: Optional[str] = None
    total_length_km: Optional[Decimal] = None
    navigable_length_km: Optional[Decimal] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    status: Optional[int] = None


class WaterwayResponse(BaseModel):
    id: int
    code: str
    name: str
    name_en: Optional[str] = None
    level: int
    parent_id: Optional[int] = None
    provinces: Optional[str] = None
    total_length_km: Optional[Decimal] = None
    navigable_length_km: Optional[Decimal] = None
    description: Optional[str] = None
    sort_order: int
    status: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- Region ----------


def _validate_boundary_coordinates(v: Optional[List]) -> Optional[List]:
    if v is None:
        return v
    if len(v) < 3:
        raise ValueError("边界多边形至少需要 3 个顶点")
    for i, pt in enumerate(v):
        if not hasattr(pt, "__len__") or len(pt) < 2:
            raise ValueError(f"第 {i} 个坐标点格式错误，需要 [经度, 纬度] 两个数值")
        try:
            lng, lat = float(pt[0]), float(pt[1])
        except (TypeError, ValueError):
            raise ValueError(f"第 {i} 个坐标点包含非数值内容")
        if not (-180.0 <= lng <= 180.0):
            raise ValueError(f"第 {i} 个点经度 {lng} 超出范围 [-180, 180]")
        if not (-90.0 <= lat <= 90.0):
            raise ValueError(f"第 {i} 个点纬度 {lat} 超出范围 [-90, 90]")
    return v


class RegionCreate(BaseModel):
    name: str
    name_en: Optional[str] = None
    waterway_ids: Optional[List[int]] = None
    boundary_coordinates: Optional[List[List[float]]] = None
    boundary_color: str = "#3388ff"
    area_color: str = "#3388ff"
    description: Optional[str] = None
    sort_order: int = 0

    @field_validator("boundary_coordinates")
    @classmethod
    def validate_boundary(cls, v):
        return _validate_boundary_coordinates(v)


class RegionUpdate(BaseModel):
    name: Optional[str] = None
    name_en: Optional[str] = None
    waterway_ids: Optional[List[int]] = None
    boundary_coordinates: Optional[List[List[float]]] = None
    boundary_color: Optional[str] = None
    area_color: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None

    @field_validator("boundary_coordinates")
    @classmethod
    def validate_boundary(cls, v):
        return _validate_boundary_coordinates(v)


class RegionResponse(BaseModel):
    id: int
    code: str
    name: str
    name_en: Optional[str] = None
    center_longitude: Optional[Decimal] = None
    center_latitude: Optional[Decimal] = None
    waterway_ids: List[int] = []
    city_ids: List[int] = []
    boundary_coordinates: Optional[list] = None
    boundary_color: Optional[str] = None
    area_color: Optional[str] = None
    description: Optional[str] = None
    sort_order: int
    status: int
    audit_status: int
    audit_remark: Optional[str] = None
    submitter_id: Optional[int] = None
    auditor_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- AdminRegion ----------


class AdminRegionCreate(BaseModel):
    code: str
    name: str
    short_name: Optional[str] = None
    pinyin: Optional[str] = None
    level: int
    parent_code: Optional[str] = None
    full_path: Optional[str] = None
    longitude: Optional[Decimal] = None
    latitude: Optional[Decimal] = None
    sort_order: int = 0
    status: int = 1


class AdminRegionUpdate(BaseModel):
    name: Optional[str] = None
    short_name: Optional[str] = None
    pinyin: Optional[str] = None
    full_path: Optional[str] = None
    longitude: Optional[Decimal] = None
    latitude: Optional[Decimal] = None
    sort_order: Optional[int] = None
    status: Optional[int] = None


class AdminRegionResponse(BaseModel):
    id: int
    code: str
    name: str
    short_name: Optional[str] = None
    pinyin: Optional[str] = None
    level: int
    parent_code: Optional[str] = None
    full_path: Optional[str] = None
    longitude: Optional[Decimal] = None
    latitude: Optional[Decimal] = None
    sort_order: int
    status: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RegionDetailResponse(RegionResponse):
    waterways_info: List[WaterwayResponse] = []
    cities_info: List[AdminRegionResponse] = []


# ---------- NodeType ----------


class NodeTypeCreate(BaseModel):
    name: str
    name_en: Optional[str] = None
    transport_mode: str = "WATERWAY"
    icon: Optional[str] = None
    description: Optional[str] = None
    sort_order: int = 0
    status: int = 1


class NodeTypeUpdate(BaseModel):
    name: Optional[str] = None
    name_en: Optional[str] = None
    transport_mode: Optional[str] = None
    icon: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    status: Optional[int] = None


class NodeTypeResponse(BaseModel):
    id: int
    code: str
    name: str
    name_en: Optional[str] = None
    transport_mode: str
    icon: Optional[str] = None
    description: Optional[str] = None
    sort_order: int
    status: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- NodeAlias ----------


class NodeAliasCreate(BaseModel):
    node_id: int
    alias_name: str
    alias_type: str = "COMMON"
    source: Optional[str] = None
    priority: int = 0
    status: int = 1


class NodeAliasResponse(BaseModel):
    id: int
    node_id: int
    alias_name: str
    alias_type: str
    source: Optional[str] = None
    priority: int
    status: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- TransportNode ----------


class TransportNodeProfileInput(BaseModel):
    river_km: Optional[Decimal] = None
    max_tonnage: Optional[int] = None
    berth_count: Optional[int] = None
    annual_throughput: Optional[str] = None
    extra_attributes: Optional[Any] = None


class TransportNodeProfileResponse(TransportNodeProfileInput):
    id: Optional[int] = None
    transport_node_id: Optional[int] = None

    class Config:
        from_attributes = True


class TransportNodeCreate(BaseModel):
    name: str
    name_en: Optional[str] = None
    node_type_id: int
    node_category: int = 4
    waterway_id: Optional[int] = None
    region_ids: Optional[List[int]] = None
    primary_region_id: Optional[int] = None
    province: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    province_code: Optional[str] = None
    city_code: Optional[str] = None
    district_code: Optional[str] = None
    address: Optional[str] = None
    longitude: Optional[Decimal] = None
    latitude: Optional[Decimal] = None
    node_level: int = 3
    is_hot_node: int = 0
    description: Optional[str] = None
    sort_order: int = 0
    status: int = 1
    profile: Optional[TransportNodeProfileInput] = None


class TransportNodeUpdate(BaseModel):
    name: Optional[str] = None
    name_en: Optional[str] = None
    node_type_id: Optional[int] = None
    node_category: Optional[int] = None
    waterway_id: Optional[int] = None
    region_ids: Optional[List[int]] = None
    primary_region_id: Optional[int] = None
    province: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    province_code: Optional[str] = None
    city_code: Optional[str] = None
    district_code: Optional[str] = None
    address: Optional[str] = None
    longitude: Optional[Decimal] = None
    latitude: Optional[Decimal] = None
    node_level: Optional[int] = None
    is_hot_node: Optional[int] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    status: Optional[int] = None
    profile: Optional[TransportNodeProfileInput] = None


class TransportNodeResponse(BaseModel):
    id: int
    code: str
    name: str
    name_en: Optional[str] = None
    node_type_id: int
    node_category: int
    waterway_id: Optional[int] = None
    primary_region_id: Optional[int] = None
    region_ids: List[int] = []
    province: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    province_code: Optional[str] = None
    city_code: Optional[str] = None
    district_code: Optional[str] = None
    address: Optional[str] = None
    longitude: Optional[Decimal] = None
    latitude: Optional[Decimal] = None
    node_level: int
    is_hot_node: int
    description: Optional[str] = None
    sort_order: int
    status: int
    audit_status: int
    audit_remark: Optional[str] = None
    submitter_id: Optional[int] = None
    auditor_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    profile: Optional[TransportNodeProfileResponse] = None
    aliases: List[NodeAliasResponse] = []

    class Config:
        from_attributes = True
