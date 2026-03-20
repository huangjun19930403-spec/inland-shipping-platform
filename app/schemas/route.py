from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


# ---------- 路径节点（兼容） ----------


class ShippingRoutePathNodeCreate(BaseModel):
    node_id: int
    sequence: int
    distance_from_start: Optional[Decimal] = None
    node_role: str = "WAYPOINT"


class ShippingRoutePathNodeResponse(BaseModel):
    id: int
    path_id: int
    node_id: int
    sequence: int
    distance_from_start: Optional[Decimal] = None
    node_role: str
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ---------- 路径段（一期主表达） ----------


class ShippingRoutePathSegmentCreate(BaseModel):
    sequence: int
    segment_type: str = "WATERWAY"
    transport_mode: str = "WATERWAY"
    from_node_id: Optional[int] = None
    to_node_id: Optional[int] = None
    waterway_id: Optional[int] = None
    via_region_id: Optional[int] = None
    distance_km: Optional[Decimal] = None
    duration_hours: Optional[Decimal] = None
    cost_factor: Optional[Decimal] = None
    remark: Optional[str] = None


class ShippingRoutePathSegmentUpdate(BaseModel):
    sequence: Optional[int] = None
    segment_type: Optional[str] = None
    transport_mode: Optional[str] = None
    from_node_id: Optional[int] = None
    to_node_id: Optional[int] = None
    waterway_id: Optional[int] = None
    via_region_id: Optional[int] = None
    distance_km: Optional[Decimal] = None
    duration_hours: Optional[Decimal] = None
    cost_factor: Optional[Decimal] = None
    remark: Optional[str] = None


class ShippingRoutePathSegmentResponse(BaseModel):
    id: int
    path_id: int
    sequence: int
    segment_type: str
    transport_mode: str
    from_node_id: Optional[int] = None
    to_node_id: Optional[int] = None
    waterway_id: Optional[int] = None
    via_region_id: Optional[int] = None
    distance_km: Optional[Decimal] = None
    duration_hours: Optional[Decimal] = None
    cost_factor: Optional[Decimal] = None
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ShippingRoutePathSegmentsBatchSet(BaseModel):
    segments: List[ShippingRoutePathSegmentCreate]


# ---------- 路线方案 ----------


class ShippingRoutePathCreate(BaseModel):
    name: str
    description: Optional[str] = None
    sort_order: int = 0
    status: int = 1


class ShippingRoutePathUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    status: Optional[int] = None


class ShippingRoutePathNodesBatchSet(BaseModel):
    nodes: List[ShippingRoutePathNodeCreate]


class ShippingRoutePathResponse(BaseModel):
    id: int
    route_id: int
    code: str
    name: str
    description: Optional[str] = None
    sort_order: int
    status: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    nodes: List[ShippingRoutePathNodeResponse] = []
    segments: List[ShippingRoutePathSegmentResponse] = []

    model_config = ConfigDict(from_attributes=True)


# ---------- 航线 ----------


class ShippingRouteCreate(BaseModel):
    name: str
    origin_region_id: int
    dest_region_id: int
    distance_km: Optional[Decimal] = None
    duration_hours: Optional[Decimal] = None
    description: Optional[str] = None
    sort_order: int = 0
    status: int = 1


class ShippingRouteUpdate(BaseModel):
    name: Optional[str] = None
    origin_region_id: Optional[int] = None
    dest_region_id: Optional[int] = None
    distance_km: Optional[Decimal] = None
    duration_hours: Optional[Decimal] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    status: Optional[int] = None


class ShippingRouteResponse(BaseModel):
    id: int
    code: str
    name: str
    origin_region_id: int
    dest_region_id: int
    distance_km: Optional[Decimal] = None
    duration_hours: Optional[Decimal] = None
    description: Optional[str] = None
    sort_order: int
    status: int
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    paths: List[ShippingRoutePathResponse] = []

    model_config = ConfigDict(from_attributes=True)
