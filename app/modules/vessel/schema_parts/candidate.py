"""Vessel candidate schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.modules.vessel.schema_parts.base import *  # noqa: F401,F403


class VesselCandidateAnalysisTimeWindow(StrictBaseModel):
    start: datetime | None = None
    end: datetime | None = None

class VesselCandidateAnalysisFilters(StrictBaseModel):
    ship_type_codes: list[str] = Field(default_factory=list)
    min_deadweight_ton: Decimal | None = None
    max_deadweight_ton: Decimal | None = None
    max_node_distance_km: Decimal | None = None
    quality_threshold: str | None = None
    risk_threshold: str | None = None

class VesselCandidateAnalysisCreateRequest(StrictBaseModel):
    context_type_code: str = Field(pattern="^(FREIGHT_SAMPLE|FREIGHT_SAMPLE_SET|FREIGHT_CANDIDATE|NODE|ROUTE|REGION|MANUAL)$")
    freight_id: int | None = Field(default=None, ge=1)
    freight_candidate_id: int | None = Field(default=None, ge=1)
    freight_sample_ids: list[int] = Field(default_factory=list)
    origin_node_id: int | None = Field(default=None, ge=1)
    destination_node_id: int | None = Field(default=None, ge=1)
    route_id: int | None = Field(default=None, ge=1)
    plan_id: int | None = Field(default=None, ge=1)
    origin_city_code: str | None = None
    destination_city_code: str | None = None
    region_id: int | None = Field(default=None, ge=1)
    cargo_category_code: str | None = None
    tonnage: Decimal | None = None
    time_window: VesselCandidateAnalysisTimeWindow | None = None
    filters: VesselCandidateAnalysisFilters = Field(default_factory=VesselCandidateAnalysisFilters)
    source_ais_snapshot_id: str | None = None
    source_spatial_snapshot_id: str | None = None
    reported_within_minutes: int = Field(default=720, ge=5, le=43200)

class VesselCandidateAnalysisListQuery(BaseModel):
    context_type_code: str | None = None
    status_code: str | None = None
    confidence_level: str | None = None
    source_spatial_snapshot_id: str | None = None
    freight_id: int | None = Field(default=None, ge=1)
    freight_candidate_id: int | None = Field(default=None, ge=1)
    origin_node_id: int | None = Field(default=None, ge=1)
    route_id: int | None = Field(default=None, ge=1)
    region_id: int | None = Field(default=None, ge=1)
    date_from: date | None = None
    date_to: date | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

class VesselCandidateAnalysisAnnotationRequest(StrictBaseModel):
    annotation_type_code: str
    comment: str | None = Field(default=None, max_length=1000)

class VesselCandidateAnalysisAnnotationResponse(BaseModel):
    id: int
    analysis_id: int
    item_id: int
    annotation_type_code: str
    comment: str | None = None
    created_by: int | None = None
    created_at: datetime
    source_version: dict[str, Any] = Field(default_factory=dict)

class VesselCandidateAnalysisItemResponse(BaseModel):
    id: int
    analysis_id: int
    vessel_profile_id: int | None = None
    mmsi: str | None = None
    ship_name: str | None = None
    ship_type_code: str | None = None
    deadweight_ton: Decimal | None = None
    design_draft_m: Decimal | None = None
    longitude: Decimal | None = None
    latitude: Decimal | None = None
    latest_position_time: datetime | None = None
    ais_freshness_level: str = "UNKNOWN"
    risk_level: str = "UNKNOWN"
    quality_level: str = "UNKNOWN"
    fit_score: Decimal = Decimal("0")
    candidate_value_level: str = "LOW"
    confidence_level: str = "UNKNOWN"
    node_distance_km: Decimal | None = None
    route_match_score: Decimal | None = None
    direction_consistency: Decimal | None = None
    constraint_status_code: str | None = None
    score_parts: dict[str, Any] = Field(default_factory=dict)
    risk_reasons: list[str] = Field(default_factory=list)
    uncertainty_reasons: list[str] = Field(default_factory=list)
    not_computable_reasons: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    annotations: list[VesselCandidateAnalysisAnnotationResponse] = Field(default_factory=list)

class VesselCandidateContextQualityGap(BaseModel):
    object_type: str
    object_id: int | str | None = None
    object_name: str | None = None
    field_name: str
    reason_code: str
    message: str
    target_path: str | None = None

class VesselCandidateSpatialLayerResponse(BaseModel):
    layer_type: str
    name: str | None = None
    path: list[tuple[float, float]] | None = None
    paths: list[list[tuple[float, float]]] | None = None
    properties: dict[str, Any] | None = None

class VesselCandidateAnalysisResponse(BaseModel):
    id: int
    context_type_code: str
    source_layer_code: str
    freight_id: int | None = None
    freight_candidate_id: int | None = None
    origin_node_id: int | None = None
    destination_node_id: int | None = None
    route_id: int | None = None
    plan_id: int | None = None
    origin_city_code: str | None = None
    destination_city_code: str | None = None
    region_id: int | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    filters: dict[str, Any] = Field(default_factory=dict)
    source_ais_snapshot_id: str | None = None
    source_spatial_snapshot_id: str | None = None
    query_hash: str
    status_code: str
    coverage_rate: Decimal | None = None
    confidence_level: str
    candidate_count: int = 0
    low_confidence_count: int = 0
    not_computable_reasons: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    analysis_center_path: str | None = None
    source_context_path: str | None = None
    context_quality_gaps: list[VesselCandidateContextQualityGap] = Field(default_factory=list)
    boundary_notice: str | None = None
    uncertainty_explain: str | None = None
    route_layers: list[VesselCandidateSpatialLayerResponse] = Field(default_factory=list)
    regional_supply_demand: dict[str, Any] | None = None
    generated_at: datetime
    expires_at: datetime | None = None
    items: list[VesselCandidateAnalysisItemResponse] = Field(default_factory=list)
