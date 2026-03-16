from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from decimal import Decimal


# ---------- Waterway ----------

class WaterwayCreate(BaseModel):
    """
    水系新增请求体。
    code 字段已移除——编码由后端依据 HJ 932-2017 规则自动生成（WW-LL-NNN），
    响应中的 WaterwayResponse.code 即为系统生成的编码。
    """
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

class RegionCreate(BaseModel):
    code: str
    name: str
    name_en: Optional[str] = None
    center_longitude: Optional[Decimal] = None
    center_latitude: Optional[Decimal] = None
    main_rivers: Optional[list] = None
    main_cities: Optional[list] = None
    boundary_coordinates: Optional[list] = None
    boundary_color: str = "#3388ff"
    area_color: str = "#3388ff"
    description: Optional[str] = None
    sort_order: int = 0
    status: int = 1


class RegionUpdate(BaseModel):
    name: Optional[str] = None
    name_en: Optional[str] = None
    center_longitude: Optional[Decimal] = None
    center_latitude: Optional[Decimal] = None
    main_rivers: Optional[list] = None
    main_cities: Optional[list] = None
    boundary_coordinates: Optional[list] = None
    boundary_color: Optional[str] = None
    area_color: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    status: Optional[int] = None


class RegionResponse(BaseModel):
    id: int
    code: str
    name: str
    name_en: Optional[str] = None
    center_longitude: Optional[Decimal] = None
    center_latitude: Optional[Decimal] = None
    main_rivers: Optional[list] = None
    main_cities: Optional[list] = None
    boundary_coordinates: Optional[list] = None
    boundary_color: Optional[str] = None
    area_color: Optional[str] = None
    description: Optional[str] = None
    sort_order: int
    status: int
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


# ---------- NodeType ----------

class NodeTypeCreate(BaseModel):
    code: str
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

class TransportNodeCreate(BaseModel):
    code: str
    name: str
    name_en: Optional[str] = None
    node_type_id: int
    node_category: int = 4
    waterway_id: Optional[int] = None
    region_id: Optional[int] = None
    province: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    address: Optional[str] = None
    longitude: Optional[Decimal] = None
    latitude: Optional[Decimal] = None
    node_level: int = 3
    is_hot_node: int = 0
    river_km: Optional[Decimal] = None
    max_tonnage: Optional[int] = None
    berth_count: Optional[int] = None
    annual_throughput: Optional[str] = None
    description: Optional[str] = None
    sort_order: int = 0
    status: int = 1


class TransportNodeUpdate(BaseModel):
    name: Optional[str] = None
    name_en: Optional[str] = None
    node_type_id: Optional[int] = None
    node_category: Optional[int] = None
    waterway_id: Optional[int] = None
    region_id: Optional[int] = None
    province: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    address: Optional[str] = None
    longitude: Optional[Decimal] = None
    latitude: Optional[Decimal] = None
    node_level: Optional[int] = None
    is_hot_node: Optional[int] = None
    river_km: Optional[Decimal] = None
    max_tonnage: Optional[int] = None
    berth_count: Optional[int] = None
    annual_throughput: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    status: Optional[int] = None


class TransportNodeResponse(BaseModel):
    id: int
    code: str
    name: str
    name_en: Optional[str] = None
    node_type_id: int
    node_category: int
    waterway_id: Optional[int] = None
    region_id: Optional[int] = None
    province: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    address: Optional[str] = None
    longitude: Optional[Decimal] = None
    latitude: Optional[Decimal] = None
    node_level: int
    is_hot_node: int
    river_km: Optional[Decimal] = None
    max_tonnage: Optional[int] = None
    berth_count: Optional[int] = None
    annual_throughput: Optional[str] = None
    description: Optional[str] = None
    sort_order: int
    status: int
    audit_status: int
    audit_remark: Optional[str] = None
    submitter_id: Optional[int] = None
    auditor_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    aliases: List[NodeAliasResponse] = []

    class Config:
        from_attributes = True
