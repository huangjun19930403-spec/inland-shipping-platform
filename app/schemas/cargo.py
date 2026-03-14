from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime, date
from decimal import Decimal


# ---------- CommodityCategory ----------

class CommodityCategoryCreate(BaseModel):
    code: Optional[str] = None
    name: str
    name_en: Optional[str] = None
    description: Optional[str] = None
    sort_order: int = 0
    status: int = 1


class CommodityCategoryUpdate(BaseModel):
    name: Optional[str] = None
    name_en: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    status: Optional[int] = None


class CommodityCategoryResponse(BaseModel):
    id: int
    code: Optional[str] = None
    name: str
    name_en: Optional[str] = None
    description: Optional[str] = None
    sort_order: int
    status: int
    audit_status: int
    submitter_id: Optional[int] = None
    auditor_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- CommodityType ----------

class CommodityTypeCreate(BaseModel):
    category_id: int
    code: Optional[str] = None
    name: str
    name_en: Optional[str] = None
    description: Optional[str] = None
    sort_order: int = 0
    status: int = 1


class CommodityTypeUpdate(BaseModel):
    category_id: Optional[int] = None
    name: Optional[str] = None
    name_en: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    status: Optional[int] = None


class CommodityTypeResponse(BaseModel):
    id: int
    category_id: int
    code: Optional[str] = None
    name: str
    name_en: Optional[str] = None
    description: Optional[str] = None
    sort_order: int
    status: int
    audit_status: int
    submitter_id: Optional[int] = None
    auditor_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- CommodityStandard ----------

class CommodityStandardCreate(BaseModel):
    type_id: int
    code: Optional[str] = None
    name: str
    name_en: Optional[str] = None
    commodity_class: Optional[str] = None
    industry: Optional[str] = None
    density: Optional[Decimal] = None
    is_dangerous: int = 0
    loading_method: Optional[str] = None
    recommended_ship_type: Optional[str] = None
    description: Optional[str] = None
    sort_order: int = 0
    status: int = 1


class CommodityStandardUpdate(BaseModel):
    type_id: Optional[int] = None
    name: Optional[str] = None
    name_en: Optional[str] = None
    commodity_class: Optional[str] = None
    industry: Optional[str] = None
    density: Optional[Decimal] = None
    is_dangerous: Optional[int] = None
    loading_method: Optional[str] = None
    recommended_ship_type: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    status: Optional[int] = None


class CommodityStandardResponse(BaseModel):
    id: int
    type_id: int
    code: Optional[str] = None
    name: str
    name_en: Optional[str] = None
    commodity_class: Optional[str] = None
    industry: Optional[str] = None
    density: Optional[Decimal] = None
    is_dangerous: int
    loading_method: Optional[str] = None
    recommended_ship_type: Optional[str] = None
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


# ---------- CommodityAlias ----------

class CommodityAliasCreate(BaseModel):
    commodity_id: int
    alias_name: str
    alias_type: str = "COMMON"
    priority: int = 0
    status: int = 1


class CommodityAliasResponse(BaseModel):
    id: int
    commodity_id: int
    alias_name: str
    alias_type: str
    priority: int
    status: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- Cargo Manual Input ----------

class CargoManualInput(BaseModel):
    origin_node_id: int
    dest_node_id: int
    commodity_id: int
    tonnage: Decimal
    loading_date: Optional[date] = None
    freight_price: Optional[Decimal] = None
    price_type: Optional[int] = None
    price_unit: Optional[str] = None
    contact_person: Optional[str] = None
    contact_phone: Optional[str] = None
    source_type: str = "WECHAT_GROUP"
    remark: Optional[str] = None


# ---------- CargoRawMessage ----------

class CargoRawMessageCreate(BaseModel):
    raw_text: str
    source_type: str = "WECHAT_GROUP"
    group_name: Optional[str] = None
    sender_name: Optional[str] = None


class CargoRawMessageResponse(BaseModel):
    id: int
    raw_text: str
    source_type: str
    group_name: Optional[str] = None
    sender_name: Optional[str] = None
    collector_id: Optional[int] = None
    status: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- CargoAiParseResult ----------

class CargoAiParseResultResponse(BaseModel):
    id: int
    raw_message_id: int
    origin_text: Optional[str] = None
    dest_text: Optional[str] = None
    commodity_text: Optional[str] = None
    tonnage_text: Optional[str] = None
    loading_date_text: Optional[str] = None
    freight_text: Optional[str] = None
    contact_text: Optional[str] = None
    origin_node_id: Optional[int] = None
    dest_node_id: Optional[int] = None
    commodity_id: Optional[int] = None
    tonnage: Optional[Decimal] = None
    loading_date: Optional[date] = None
    freight_price: Optional[Decimal] = None
    price_type: Optional[int] = None
    contact_person: Optional[str] = None
    contact_phone: Optional[str] = None
    origin_confidence: int
    dest_confidence: int
    commodity_confidence: int
    tonnage_confidence: int
    overall_confidence: int
    origin_candidates: Optional[Any] = None
    dest_candidates: Optional[Any] = None
    commodity_candidates: Optional[Any] = None
    ai_model: Optional[str] = None
    parse_status: str
    confirmed_by: Optional[int] = None
    confirmed_at: Optional[datetime] = None
    discard_reason: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- CargoOpportunity ----------

class CargoOpportunityResponse(BaseModel):
    id: int
    opportunity_no: str
    origin_node_id: int
    dest_node_id: int
    commodity_id: int
    tonnage: Decimal
    origin_region_id: Optional[int] = None
    dest_region_id: Optional[int] = None
    route_id: Optional[int] = None
    loading_date: Optional[date] = None
    freight_price: Optional[Decimal] = None
    price_type: Optional[int] = None
    price_unit: Optional[str] = None
    contact_person: Optional[str] = None
    contact_phone: Optional[str] = None
    source_type: str
    remark: Optional[str] = None
    raw_message_id: Optional[int] = None
    parse_result_id: Optional[int] = None
    status: str
    input_type: str
    collector_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- CargoConfirmRequest ----------

class CargoConfirmRequest(BaseModel):
    origin_node_id: Optional[int] = None
    dest_node_id: Optional[int] = None
    commodity_id: Optional[int] = None
    tonnage: Optional[Decimal] = None
    loading_date: Optional[date] = None
    freight_price: Optional[Decimal] = None
    price_type: Optional[int] = None
    contact_person: Optional[str] = None
    contact_phone: Optional[str] = None
    remark: Optional[str] = None
