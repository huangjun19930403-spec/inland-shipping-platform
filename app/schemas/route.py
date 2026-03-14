from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from decimal import Decimal


class ShippingRoutePathCreate(BaseModel):
    node_id: int
    sequence: int
    distance_from_start: Optional[Decimal] = None
    node_role: str = "WAYPOINT"


class ShippingRoutePathResponse(BaseModel):
    id: int
    route_id: int
    node_id: int
    sequence: int
    distance_from_start: Optional[Decimal] = None
    node_role: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ShippingRouteCreate(BaseModel):
    code: str
    name: str
    origin_region_id: int
    dest_region_id: int
    distance_km: Optional[Decimal] = None
    duration_hours: Optional[Decimal] = None
    description: Optional[str] = None
    sort_order: int = 0
    status: int = 1
    path_nodes: Optional[List[ShippingRoutePathCreate]] = None


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
    path_nodes: List[ShippingRoutePathResponse] = []

    class Config:
        from_attributes = True
