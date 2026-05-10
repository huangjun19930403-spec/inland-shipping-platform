"""Vessel base schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

T = TypeVar("T")


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class PageResponse(BaseModel, Generic[T]):
    total: int
    page: int
    page_size: int
    items: list[T]

def _validate_mmsi(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if len(cleaned) != 9 or not cleaned.isdigit():
        raise ValueError("MMSI 必须为 9 位数字")
    return cleaned

class VesselListQuery(BaseModel):
    keyword: str | None = None
    mmsi: str | None = None
    ship_name: str | None = None
    ship_type_code: str | None = None
    profile_status_code: str | None = None
    city_code: str | None = None
    registry_city_code: str | None = None
    business_region_id: int | None = None
    deadweight_min: Decimal | None = None
    deadweight_max: Decimal | None = None
    ship_age_min: int | None = Field(default=None, ge=0, le=200)
    ship_age_max: int | None = Field(default=None, ge=0, le=200)
    length_min: Decimal | None = None
    length_max: Decimal | None = None
    draft_min: Decimal | None = None
    draft_max: Decimal | None = None
    owner_name: str | None = None
    operator_name: str | None = None
    contact_available: bool | None = None
    updated_from: datetime | None = None
    updated_to: datetime | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)

class VesselVoidRequest(StrictBaseModel):
    reason: str | None = Field(default=None, max_length=256)
    revision: int | None = Field(default=None, ge=1)

class VesselRecommendedAction(BaseModel):
    action_type: str
    label: str
    target_path: str
    target_object_type: str | None = None
    target_object_id: str | None = None
    required_fields: list[str] = Field(default_factory=list)
    description: str | None = None
    source_object_anchor: str | None = None
    workbench_group: str | None = None
    method: str = "GET"
    payload: dict[str, Any] | None = None

class VesselGovernanceContextMixin(BaseModel):
    explain_reason: str | None = None
    next_actions: list[VesselRecommendedAction] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    source_object_anchor: str | None = None
    workbench_group: str | None = None
