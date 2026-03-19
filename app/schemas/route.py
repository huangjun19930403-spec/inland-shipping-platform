from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime
from decimal import Decimal


# ─────────────────────────────────────────────────
# 路径节点（ShippingRoutePathNode）
# ─────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────
# 路线方案（ShippingRoutePath）
# ─────────────────────────────────────────────────

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
    """批量替换路线节点"""
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

    model_config = ConfigDict(from_attributes=True)


# ─────────────────────────────────────────────────
# 航线（ShippingRoute）
# ─────────────────────────────────────────────────

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
