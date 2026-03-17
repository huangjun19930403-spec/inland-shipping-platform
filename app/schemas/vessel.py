from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime
from decimal import Decimal


# ---------- VesselTypeDict ----------

class VesselTypeDictCreate(BaseModel):
    code: str
    name: str
    name_en: Optional[str] = None
    transport_type: str = "WATERWAY"
    applicable_goods: Optional[Any] = None
    min_tonnage: Optional[int] = None
    max_tonnage: Optional[int] = None
    description: Optional[str] = None
    sort_order: int = 0
    status: int = 1


class VesselTypeDictUpdate(BaseModel):
    name: Optional[str] = None
    name_en: Optional[str] = None
    transport_type: Optional[str] = None
    applicable_goods: Optional[Any] = None
    min_tonnage: Optional[int] = None
    max_tonnage: Optional[int] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    status: Optional[int] = None


class VesselTypeDictResponse(BaseModel):
    id: int
    code: str
    name: str
    name_en: Optional[str] = None
    transport_type: str
    applicable_goods: Optional[Any] = None
    min_tonnage: Optional[int] = None
    max_tonnage: Optional[int] = None
    description: Optional[str] = None
    sort_order: int
    status: int
    audit_status: int
    submitter_id: Optional[int] = None
    auditor_id: Optional[int] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- Vessel ----------

class VesselCreate(BaseModel):
    vessel_no: str
    vessel_name: str
    mmsi: Optional[str] = None
    call_sign: Optional[str] = None
    vessel_type_id: Optional[int] = None
    deadweight: Optional[int] = None
    gross_tonnage: Optional[Decimal] = None
    net_tonnage: Optional[Decimal] = None
    length: Optional[Decimal] = None
    breadth: Optional[Decimal] = None
    depth: Optional[Decimal] = None
    max_draft: Optional[Decimal] = None
    build_year: Optional[int] = None
    build_country: Optional[str] = None
    build_city: Optional[str] = None
    home_port: Optional[str] = None
    flag: str = "中国"
    owner_name: Optional[str] = None
    contact_phone: Optional[str] = None


class VesselUpdate(BaseModel):
    vessel_name: Optional[str] = None
    mmsi: Optional[str] = None
    call_sign: Optional[str] = None
    vessel_type_id: Optional[int] = None
    deadweight: Optional[int] = None
    gross_tonnage: Optional[Decimal] = None
    net_tonnage: Optional[Decimal] = None
    length: Optional[Decimal] = None
    breadth: Optional[Decimal] = None
    depth: Optional[Decimal] = None
    max_draft: Optional[Decimal] = None
    build_year: Optional[int] = None
    build_country: Optional[str] = None
    build_city: Optional[str] = None
    home_port: Optional[str] = None
    flag: Optional[str] = None
    owner_name: Optional[str] = None
    contact_phone: Optional[str] = None
    data_status: Optional[int] = None
    change_reason: Optional[str] = None


class VesselResponse(BaseModel):
    id: int
    vessel_no: str
    vessel_name: str
    mmsi: Optional[str] = None
    call_sign: Optional[str] = None
    vessel_type_id: Optional[int] = None
    deadweight: Optional[int] = None
    gross_tonnage: Optional[Decimal] = None
    net_tonnage: Optional[Decimal] = None
    length: Optional[Decimal] = None
    breadth: Optional[Decimal] = None
    depth: Optional[Decimal] = None
    max_draft: Optional[Decimal] = None
    build_year: Optional[int] = None
    build_country: Optional[str] = None
    build_city: Optional[str] = None
    home_port: Optional[str] = None
    flag: Optional[str] = None
    owner_name: Optional[str] = None
    contact_phone: Optional[str] = None
    data_status: int
    audit_status: int
    audit_remark: Optional[str] = None
    submitter_id: Optional[int] = None
    auditor_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- VesselDynamic ----------

class VesselDynamicUpdate(BaseModel):
    current_longitude: Optional[Decimal] = None
    current_latitude: Optional[Decimal] = None
    current_node_id: Optional[int] = None
    vessel_status: Optional[str] = None
    current_draft: Optional[Decimal] = None
    dest_node_id: Optional[int] = None
    eta: Optional[datetime] = None
    speed: Optional[Decimal] = None
    heading: Optional[Decimal] = None
    cargo_info: Optional[str] = None
    remark: Optional[str] = None


class VesselDynamicResponse(BaseModel):
    id: int
    vessel_id: Optional[int] = None
    mmsi: Optional[str] = None
    current_longitude: Optional[Decimal] = None
    current_latitude: Optional[Decimal] = None
    current_node_id: Optional[int] = None
    vessel_status: str
    current_draft: Optional[Decimal] = None
    dest_node_id: Optional[int] = None
    eta: Optional[datetime] = None
    speed: Optional[Decimal] = None
    heading: Optional[Decimal] = None
    cargo_info: Optional[str] = None
    remark: Optional[str] = None
    updated_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- History ----------

class VesselNameHistoryResponse(BaseModel):
    id: int
    vessel_id: int
    old_name: str
    new_name: str
    change_reason: Optional[str] = None
    changed_by: Optional[int] = None
    changed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class VesselAisHistoryResponse(BaseModel):
    id: int
    vessel_id: int
    old_mmsi: str
    new_mmsi: str
    change_reason: Optional[str] = None
    changed_by: Optional[int] = None
    changed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- Kafka 消息体 ----------

class VesselDynamicKafkaMessage(BaseModel):
    """Kafka Topic: vessel.dynamic — 船舶 AIS 动态消息体"""
    mmsi: str                                          # 必填：MMSI 号（唯一标识）
    current_longitude: Optional[Decimal] = None       # 当前经度
    current_latitude: Optional[Decimal] = None        # 当前纬度
    vessel_status: Optional[str] = None               # EMPTY/LOADED/IN_PORT/ANCHORED/UNDERWAY/MAINTENANCE
    current_draft: Optional[Decimal] = None           # 当前吃水(m)
    speed: Optional[Decimal] = None                   # 当前航速(节)
    heading: Optional[Decimal] = None                 # 船首向(度)
    cargo_info: Optional[str] = None                  # 载货信息
    eta: Optional[datetime] = None                    # 预计到达时间
    dest_node_id: Optional[int] = None                # 目的港节点ID
    remark: Optional[str] = None
