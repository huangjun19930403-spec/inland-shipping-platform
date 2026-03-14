from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import date, datetime
from decimal import Decimal


class HeatmapStatResponse(BaseModel):
    stat_date: date
    node_id: int
    node_name: Optional[str] = None
    longitude: Optional[Decimal] = None
    latitude: Optional[Decimal] = None
    stat_type: str
    cargo_count: int
    total_tonnage: Decimal
    vessel_count: int
    total_deadweight: Decimal

    class Config:
        from_attributes = True


class DashboardStatsResponse(BaseModel):
    total_nodes: int
    approved_nodes: int
    pending_nodes: int
    total_commodities: int
    total_vessels: int
    approved_vessels: int
    pending_vessels: int
    total_routes: int
    today_cargo: int
    total_cargo: int


class CargoTrendItem(BaseModel):
    date: str
    count: int
    total_tonnage: Optional[Decimal] = None


class CargoTrendResponse(BaseModel):
    items: List[CargoTrendItem]
    days: int


class TopNodeItem(BaseModel):
    node_id: int
    node_name: Optional[str] = None
    cargo_count: int
    total_tonnage: Optional[Decimal] = None


class TopNodesResponse(BaseModel):
    stat_type: str
    items: List[TopNodeItem]
