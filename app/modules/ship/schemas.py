"""ship 模块 schema。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResponse(BaseModel, Generic[T]):
    total: int
    page: int
    page_size: int
    items: list[T]


class ShipListQuery(BaseModel):
    keyword: str | None = None
    status_code: str | None = None
    ship_type_code: str | None = None
    city_code: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class ShipCreateRequest(BaseModel):
    ais_id: str = Field(min_length=1, max_length=32)
    ship_name: str = Field(min_length=1, max_length=128)
    ship_name_en: str | None = Field(default=None, max_length=256)
    current_mmsi: str | None = Field(default=None, max_length=16)
    ship_type_code: str = Field(min_length=1, max_length=64)
    navigation_power_type_code: str = Field(min_length=1, max_length=64)
    home_port_code: str | None = Field(default=None, max_length=12)
    home_port_name: str | None = Field(default=None, max_length=128)
    owner_name: str | None = Field(default=None, max_length=128)
    profile_status_code: str = Field(default="ACTIVE", min_length=1, max_length=64)
    source_type_code: str = Field(default="MANUAL", min_length=1, max_length=64)


class ShipUpdateRequest(BaseModel):
    ship_name: str | None = Field(default=None, min_length=1, max_length=128)
    ship_name_en: str | None = Field(default=None, max_length=256)
    current_mmsi: str | None = Field(default=None, max_length=16)
    ship_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    navigation_power_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    home_port_code: str | None = Field(default=None, max_length=12)
    home_port_name: str | None = Field(default=None, max_length=128)
    owner_name: str | None = Field(default=None, max_length=128)
    source_type_code: str | None = Field(default=None, min_length=1, max_length=64)


class ShipStatusChangeRequest(BaseModel):
    status_code: str = Field(min_length=1, max_length=64)


class ShipResponse(BaseModel):
    id: int
    ais_id: str
    ship_name: str
    ship_name_en: str | None
    current_mmsi: str | None
    ship_type_code: str
    navigation_power_type_code: str
    home_port_code: str | None
    home_port_name: str | None
    owner_name: str | None
    profile_status_code: str
    source_type_code: str
    audit_status: str
    created_at: datetime
    updated_at: datetime


class ShipCapacityUpsertRequest(BaseModel):
    deadweight_ton: Decimal | None = None
    reference_load_ton: Decimal | None = None
    total_tonnage: Decimal | None = None
    net_tonnage: Decimal | None = None
    length_m: Decimal | None = None
    width_m: Decimal | None = None
    depth_m: Decimal | None = None
    design_draft_m: Decimal | None = None
    design_speed_kn: Decimal | None = None
    hold_count: int | None = None
    capacity_remark: str | None = Field(default=None, max_length=512)


class ShipCapacityResponse(BaseModel):
    id: int
    ship_id: int
    deadweight_ton: Decimal | None
    reference_load_ton: Decimal | None
    total_tonnage: Decimal | None
    net_tonnage: Decimal | None
    length_m: Decimal | None
    width_m: Decimal | None
    depth_m: Decimal | None
    design_draft_m: Decimal | None
    design_speed_kn: Decimal | None
    hold_count: int | None
    capacity_remark: str | None
    updated_at: datetime


class ShipOperationUpsertRequest(BaseModel):
    operator_name: str | None = Field(default=None, max_length=128)
    manager_name: str | None = Field(default=None, max_length=128)
    main_navigation_area_desc: str | None = Field(default=None, max_length=256)
    usual_route_desc: str | None = Field(default=None, max_length=256)
    contact_phone: str | None = Field(default=None, max_length=32)
    dispatch_contact_name: str | None = Field(default=None, max_length=64)
    dispatch_contact_phone: str | None = Field(default=None, max_length=32)
    risk_level_code: str | None = Field(default=None, max_length=64)
    last_active_at: datetime | None = None
    ext_json: dict | None = None


class ShipOperationResponse(BaseModel):
    id: int
    ship_id: int
    operator_name: str | None
    manager_name: str | None
    main_navigation_area_desc: str | None
    usual_route_desc: str | None
    contact_phone: str | None
    dispatch_contact_name: str | None
    dispatch_contact_phone: str | None
    risk_level_code: str | None
    last_active_at: datetime | None
    ext_json: dict | None
    updated_at: datetime


class ShipOwnerItem(BaseModel):
    party_name: str = Field(min_length=1, max_length=128)
    party_relation_type_code: str = Field(min_length=1, max_length=64)
    certificate_no: str | None = Field(default=None, max_length=64)
    mobile_phone: str | None = Field(default=None, max_length=32)
    landline_phone: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=256)
    is_primary: bool = False


class ShipOwnerReplaceRequest(BaseModel):
    owners: list[ShipOwnerItem] = Field(default_factory=list)


class ShipOwnerResponse(BaseModel):
    id: int
    ship_id: int
    party_name: str
    party_relation_type_code: str
    certificate_no: str | None
    mobile_phone: str | None
    landline_phone: str | None
    address: str | None
    is_primary: bool
    created_at: datetime
    updated_at: datetime


class ShipContactItem(BaseModel):
    contact_name: str = Field(min_length=1, max_length=64)
    contact_role_code: str = Field(min_length=1, max_length=64)
    mobile_phone: str | None = Field(default=None, max_length=32)
    wechat: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=128)
    is_primary: bool = False
    remark: str | None = Field(default=None, max_length=512)


class ShipContactReplaceRequest(BaseModel):
    contacts: list[ShipContactItem] = Field(default_factory=list)


class ShipContactResponse(BaseModel):
    id: int
    ship_id: int
    contact_name: str
    contact_role_code: str
    mobile_phone: str | None
    wechat: str | None
    email: str | None
    is_primary: bool
    remark: str | None
    created_at: datetime
    updated_at: datetime


class ShipCertificateCreateRequest(BaseModel):
    certificate_type_code: str = Field(min_length=1, max_length=64)
    certificate_no: str | None = Field(default=None, max_length=128)
    issuing_authority: str | None = Field(default=None, max_length=128)
    valid_from: date | None = None
    valid_to: date | None = None
    is_long_term_valid: bool = False
    validity_text_raw: str | None = Field(default=None, max_length=256)
    verify_status_code: str = Field(default="PENDING", min_length=1, max_length=64)
    structured_payload_json: dict | None = None
    source_file_id: int | None = None
    remark: str | None = Field(default=None, max_length=512)


class ShipCertificateUpdateRequest(BaseModel):
    certificate_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    certificate_no: str | None = Field(default=None, max_length=128)
    issuing_authority: str | None = Field(default=None, max_length=128)
    valid_from: date | None = None
    valid_to: date | None = None
    is_long_term_valid: bool | None = None
    validity_text_raw: str | None = Field(default=None, max_length=256)
    verify_status_code: str | None = Field(default=None, min_length=1, max_length=64)
    structured_payload_json: dict | None = None
    source_file_id: int | None = None
    remark: str | None = Field(default=None, max_length=512)


class ShipCertificateResponse(BaseModel):
    id: int
    ship_id: int
    certificate_type_code: str
    certificate_no: str | None
    issuing_authority: str | None
    valid_from: date | None
    valid_to: date | None
    is_long_term_valid: bool
    validity_text_raw: str | None
    verify_status_code: str
    structured_payload_json: dict | None
    source_file_id: int | None
    remark: str | None
    created_at: datetime
    updated_at: datetime


class ShipCertificateFileItem(BaseModel):
    storage_provider_code: str = Field(min_length=1, max_length=64)
    file_url: str = Field(min_length=1, max_length=512)
    file_name: str = Field(min_length=1, max_length=256)
    file_ext: str | None = Field(default=None, max_length=32)
    file_size: int | None = None
    uploaded_by: int | None = None
    uploaded_at: datetime | None = None


class ShipCertificateFileReplaceRequest(BaseModel):
    files: list[ShipCertificateFileItem] = Field(default_factory=list)


class ShipCertificateFileResponse(BaseModel):
    id: int
    ship_certificate_id: int | None
    storage_provider_code: str
    file_url: str
    file_name: str
    file_ext: str | None
    file_size: int | None
    uploaded_by: int | None
    uploaded_at: datetime | None
    created_at: datetime


class ShipNameHistoryCreateRequest(BaseModel):
    ship_name: str = Field(min_length=1, max_length=128)
    start_date: date | None = None
    end_date: date | None = None
    source_type_code: str = Field(default="MANUAL", min_length=1, max_length=64)


class ShipNameHistoryResponse(BaseModel):
    id: int
    ship_id: int
    ship_name: str
    start_date: date | None
    end_date: date | None
    source_type_code: str
    created_at: datetime


class ShipMmsiHistoryCreateRequest(BaseModel):
    mmsi: str = Field(min_length=1, max_length=16)
    start_date: date | None = None
    end_date: date | None = None
    source_type_code: str = Field(default="MANUAL", min_length=1, max_length=64)


class ShipMmsiHistoryResponse(BaseModel):
    id: int
    ship_id: int
    mmsi: str
    start_date: date | None
    end_date: date | None
    source_type_code: str
    created_at: datetime


class ShipImportBatchListQuery(BaseModel):
    keyword: str | None = None
    status_code: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class ShipImportBatchCreateRequest(BaseModel):
    batch_no: str | None = Field(default=None, max_length=32)
    source_type_code: str = Field(min_length=1, max_length=64)
    status_code: str = Field(default="PENDING", min_length=1, max_length=64)
    operator_id: int | None = None
    remark: str | None = Field(default=None, max_length=512)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ShipImportBatchResponse(BaseModel):
    id: int
    batch_no: str
    source_type_code: str
    total_count: int
    success_count: int
    failed_count: int
    status_code: str
    started_at: datetime | None
    finished_at: datetime | None
    operator_id: int | None
    remark: str | None
    created_at: datetime
    updated_at: datetime


class ShipImportRawListQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class ShipImportRawCreateItem(BaseModel):
    row_no: int = Field(ge=1)
    raw_payload_json: dict
    parse_status_code: str = Field(default="PENDING", min_length=1, max_length=64)
    parse_message: str | None = Field(default=None, max_length=512)


class ShipImportRawCreateRequest(BaseModel):
    items: list[ShipImportRawCreateItem] = Field(default_factory=list)


class ShipImportRawResponse(BaseModel):
    id: int
    batch_id: int
    row_no: int
    raw_payload_json: dict
    parse_status_code: str
    parse_message: str | None
    created_at: datetime


class ShipImportRecordListQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)


class ShipImportRecordCreateRequest(BaseModel):
    batch_id: int
    raw_id: int
    ship_id: int | None = None
    action_type_code: str = Field(min_length=1, max_length=64)
    result_code: str = Field(min_length=1, max_length=64)
    message: str | None = Field(default=None, max_length=512)


class ShipImportRecordUpdateRequest(BaseModel):
    ship_id: int | None = None
    action_type_code: str | None = Field(default=None, min_length=1, max_length=64)
    result_code: str | None = Field(default=None, min_length=1, max_length=64)
    message: str | None = Field(default=None, max_length=512)


class ShipImportRecordResponse(BaseModel):
    id: int
    batch_id: int
    raw_id: int
    ship_id: int | None
    action_type_code: str
    result_code: str
    message: str | None
    created_at: datetime


class ShipImportBatchDetailResponse(BaseModel):
    batch: ShipImportBatchResponse
    raw_total: int
    record_total: int


class ShipDetailResponse(BaseModel):
    profile: ShipResponse
    capacity: ShipCapacityResponse | None
    operation: ShipOperationResponse | None
    owners: list[ShipOwnerResponse]
    contacts: list[ShipContactResponse]
    certificates: list[ShipCertificateResponse]
    name_history: list[ShipNameHistoryResponse]
    mmsi_history: list[ShipMmsiHistoryResponse]
