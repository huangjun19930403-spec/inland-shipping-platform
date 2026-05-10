"""Vessel ais schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.modules.vessel.schema_parts.base import *  # noqa: F401,F403
from app.modules.vessel.schema_parts.asset import *  # noqa: F401,F403


class VesselPositionMonitorQuery(BaseModel):
    keyword: str | None = None
    ship_type_code: str | None = None
    deadweight_min: Decimal | None = None
    deadweight_max: Decimal | None = None
    draft_max: Decimal | None = None
    contact_available: bool | None = None
    profile_status_code: str | None = None
    reported_within_minutes: int | None = Field(default=1440, ge=5, le=43200)
    max_items: int = Field(default=200, ge=1, le=500)

class VesselAisMonitorQuery(BaseModel):
    keyword: str | None = None
    ship_type_code: str | None = None
    deadweight_min: Decimal | None = None
    deadweight_max: Decimal | None = None
    draft_max: Decimal | None = None
    profile_status_code: str | None = None
    reported_within_minutes: int | None = Field(default=1440, ge=5, le=43200)
    max_items: int = Field(default=200, ge=1, le=500)

    def to_internal_query(self) -> VesselPositionMonitorQuery:
        return VesselPositionMonitorQuery(**self.model_dump(), contact_available=None)

class VesselPositionCitySituationQuery(BaseModel):
    keyword: str | None = None
    ship_type_code: str | None = None
    deadweight_min: Decimal | None = None
    deadweight_max: Decimal | None = None
    draft_max: Decimal | None = None
    contact_available: bool | None = None
    profile_status_code: str | None = None
    reported_within_minutes: int | None = Field(default=1440, ge=5, le=43200)
    include_boundary: bool = True
    boundary_precision: str = Field(default="low", pattern="^(low|medium)$")

class VesselPositionCityVesselsQuery(VesselPositionCitySituationQuery):
    city_code: str | None = None
    city_name: str | None = None
    query_snapshot_id: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

class VesselAisCitySituationQuery(BaseModel):
    keyword: str | None = None
    ship_type_code: str | None = None
    deadweight_min: Decimal | None = None
    deadweight_max: Decimal | None = None
    draft_max: Decimal | None = None
    profile_status_code: str | None = None
    reported_within_minutes: int | None = Field(default=1440, ge=5, le=43200)
    include_boundary: bool = True
    boundary_precision: str = Field(default="low", pattern="^(low|medium)$")

    def to_internal_query(self) -> VesselPositionCitySituationQuery:
        return VesselPositionCitySituationQuery(**self.model_dump(), contact_available=None)

class VesselAisCityVesselsQuery(VesselAisCitySituationQuery):
    city_code: str | None = None
    city_name: str | None = None
    query_snapshot_id: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    def to_internal_query(self) -> VesselPositionCityVesselsQuery:
        return VesselPositionCityVesselsQuery(**self.model_dump(), contact_available=None)

class VesselAisCityBoundaryQuery(BaseModel):
    city_code: str | None = None
    city_codes: str | None = None
    precision: str = Field(default="low", pattern="^(low|medium)$")

class VesselPositionWaterSystemSituationQuery(BaseModel):
    keyword: str | None = None
    ship_type_code: str | None = None
    deadweight_min: Decimal | None = None
    deadweight_max: Decimal | None = None
    draft_max: Decimal | None = None
    contact_available: bool | None = None
    profile_status_code: str | None = None
    risk_level: str | None = None
    certificate_risk_available: bool | None = None
    water_level: int | None = Field(default=None, ge=1, le=7)
    water_levels: str | None = None
    navigation_scope_codes: str | None = None
    navigation_category_codes: str | None = None
    water_system_name: str | None = None
    reported_within_minutes: int | None = Field(default=1440, ge=5, le=43200)
    include_boundary: bool = True
    include_empty_water_systems: bool = True
    boundary_precision: str = Field(default="low", pattern="^(low|medium)$")

class VesselPositionWaterSystemVesselsQuery(VesselPositionWaterSystemSituationQuery):
    water_system_code: str | None = None
    query_snapshot_id: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

class VesselAisWaterSystemSituationQuery(BaseModel):
    keyword: str | None = None
    ship_type_code: str | None = None
    deadweight_min: Decimal | None = None
    deadweight_max: Decimal | None = None
    draft_max: Decimal | None = None
    contact_available: bool | None = None
    profile_status_code: str | None = None
    risk_level: str | None = None
    certificate_risk_available: bool | None = None
    water_level: int | None = Field(default=None, ge=1, le=7)
    water_levels: str | None = None
    navigation_scope_codes: str | None = None
    navigation_category_codes: str | None = None
    water_system_name: str | None = None
    reported_within_minutes: int | None = Field(default=1440, ge=5, le=43200)
    include_boundary: bool = True
    include_empty_water_systems: bool = True
    boundary_precision: str = Field(default="low", pattern="^(low|medium)$")

    def to_internal_query(self) -> VesselPositionWaterSystemSituationQuery:
        return VesselPositionWaterSystemSituationQuery(**self.model_dump())

class VesselAisWaterSystemVesselsQuery(VesselAisWaterSystemSituationQuery):
    water_system_code: str | None = None
    query_snapshot_id: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    def to_internal_query(self) -> VesselPositionWaterSystemVesselsQuery:
        return VesselPositionWaterSystemVesselsQuery(**self.model_dump())

class VesselAisWaterSystemBoundaryQuery(BaseModel):
    water_system_code: str | None = None
    water_system_codes: str | None = None
    water_system_name: str | None = None
    water_level: int | None = Field(default=None, ge=1, le=7)
    water_levels: str | None = None
    navigation_scope_codes: str | None = None
    navigation_category_codes: str | None = None
    precision: str = Field(default="low", pattern="^(low|medium|high)$")

class VesselAisSnapshotQuery(BaseModel):
    snapshot_id: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

class VesselAisNodeSituationQuery(BaseModel):
    node_id: int = Field(ge=1)
    radius_km: Decimal | None = Field(default=None, gt=Decimal("0"), le=Decimal("20"))
    time_window_hours: int = Field(default=24, ge=1, le=168)
    reported_within_minutes: int | None = Field(default=1440, ge=5, le=43200)
    ship_type_code: str | None = None
    deadweight_min: Decimal | None = None
    deadweight_max: Decimal | None = None
    draft_max: Decimal | None = None
    quality_level: str | None = None
    risk_level: str | None = None

class VesselAisNodeVesselsQuery(VesselAisNodeSituationQuery):
    query_snapshot_id: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

class VesselAisRouteSituationQuery(BaseModel):
    route_id: int | None = Field(default=None, ge=1)
    line_id: int | None = Field(default=None, ge=1)
    time_window_hours: int = Field(default=24, ge=1, le=168)
    reported_within_minutes: int | None = Field(default=1440, ge=5, le=43200)
    ship_type_code: str | None = None
    deadweight_min: Decimal | None = None
    deadweight_max: Decimal | None = None
    draft_max: Decimal | None = None
    quality_level: str | None = None
    risk_level: str | None = None

class VesselAisRouteSegmentVesselsQuery(BaseModel):
    query_snapshot_id: str | None = None
    segment_id: int = Field(ge=1)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

class VesselNavigationConstraintQuery(BaseModel):
    context_type: str = Field(pattern="^(NODE|ROUTE_LINE|ROUTE_SEGMENT)$")
    node_id: int | None = Field(default=None, ge=1)
    line_id: int | None = Field(default=None, ge=1)
    segment_id: int | None = Field(default=None, ge=1)

class VesselPositionMonitorItemResponse(VesselListItemResponse):
    longitude: Decimal
    latitude: Decimal
    speed_kn: Decimal | None = None
    course_deg: Decimal | None = None
    heading_deg: Decimal | None = None
    position_time: datetime | None = None
    position_age_minutes: int | None = None
    city_code: str | None = None
    city_name: str | None = None
    current_city_code: str | None = None
    current_city_name: str | None = None
    current_city_source: str | None = None
    current_water_system_code: str | None = None
    current_water_system_name: str | None = None
    current_water_system_source: str | None = None
    water_system_match_distance_m: Decimal | None = None
    city_center_longitude: Decimal | None = None
    city_center_latitude: Decimal | None = None
    matched_city_candidates: list[dict[str, Any]] | None = None
    location_text: str | None = None
    position_source_code: str = "ES_REALTIME"
    position_source_name: str | None = None
    source_index: str | None = None
    freshness_level: str = "UNKNOWN"
    match_status_code: str = "MATCHED_PROFILE"
    risk_level: str | None = None
    certificate_risk_available: bool | None = None

class VesselPositionMonitorSummary(BaseModel):
    matched_profile_count: int
    positioned_count: int
    stale_position_count: int
    contactable_position_count: int
    unmatched_mmsi_count: int = 0
    invalid_position_count: int = 0
    coverage_rate: Decimal | None = None
    freshness_distribution: dict[str, int] = Field(default_factory=dict)

class VesselPositionMonitorResponse(BaseModel):
    source_status: str
    source_status_name: str
    generated_at: datetime
    message: str | None = None
    summary: VesselPositionMonitorSummary
    items: list[VesselPositionMonitorItemResponse] = Field(default_factory=list)

class VesselShipTypeDistributionItemResponse(BaseModel):
    ship_type_code: str | None = None
    ship_type_name: str | None = None
    count: int

class VesselPositionCitySituationItemResponse(BaseModel):
    city_code: str | None = None
    city_name: str
    longitude: Decimal | None = None
    latitude: Decimal | None = None
    city_center_longitude: Decimal | None = None
    city_center_latitude: Decimal | None = None
    heat_center_longitude: Decimal | None = None
    heat_center_latitude: Decimal | None = None
    boundary_paths: list[list[list[float]]] | None = None
    has_boundary: bool = False
    boundary_precision: str | None = None
    positioned_count: int
    contactable_position_count: int
    average_ship_age: Decimal | None = None
    total_deadweight_ton: Decimal | None = None
    ship_type_distribution: list[VesselShipTypeDistributionItemResponse] = Field(default_factory=list)
    stale_position_count: int = 0
    certificate_risk_count: int = 0
    unmatched_mmsi_count: int = 0
    invalid_position_count: int = 0
    freshness_distribution: dict[str, int] = Field(default_factory=dict)
    boundary_status_code: str = "UNKNOWN"
    latest_position_time: datetime | None = None
    mmsi_count: int = 0
    matched_position_count: int = 0
    unpositioned_count: int = 0
    is_partial: bool = False
    error_message: str | None = None

class VesselPositionCitySituationSummary(BaseModel):
    matched_profile_count: int
    scanned_profile_count: int = 0
    unscanned_profile_count: int = 0
    queried_mmsi_count: int
    matched_position_count: int
    unmatched_mmsi_count: int = 0
    unpositioned_count: int
    invalid_position_count: int = 0
    unknown_city_count: int = 0
    positioned_count: int
    stale_position_count: int
    contactable_position_count: int
    certificate_risk_count: int
    city_count: int
    boundary_city_count: int = 0
    missing_boundary_city_count: int = 0
    missing_boundary_cities: list[dict[str, Any]] = Field(default_factory=list)
    query_snapshot_id: str | None = None
    snapshot_status_code: str = "READY"
    snapshot_expires_at: datetime | None = None
    refresh_required: bool = False
    coverage_rate: Decimal | None = None
    freshness_distribution: dict[str, int] = Field(default_factory=dict)
    source_indices: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    failed_batch_count: int = 0
    failed_batches: list[dict[str, Any]] = Field(default_factory=list)
    is_partial: bool = False
    error_message: str | None = None

class VesselPositionCitySituationResponse(BaseModel):
    source_status: str
    source_status_name: str
    generated_at: datetime
    message: str | None = None
    cache_status: str = "MISS"
    cache_generated_at: datetime | None = None
    is_stale_cache: bool = False
    snapshot_backend: str = "memory"
    cache_backend_note: str | None = None
    summary: VesselPositionCitySituationSummary
    cities: list[VesselPositionCitySituationItemResponse] = Field(default_factory=list)

class VesselPositionCityVesselsResponse(PageResponse[VesselPositionMonitorItemResponse]):
    query_snapshot_id: str | None = None
    snapshot_hit: bool = False
    refresh_required: bool = False
    snapshot_status_code: str | None = None
    is_partial: bool = False
    error_message: str | None = None

class VesselAisCityBoundaryItemResponse(BaseModel):
    city_code: str
    city_name: str
    boundary_paths: list[list[list[float]]] = Field(default_factory=list)
    has_boundary: bool = False
    boundary_precision: str = "low"
    boundary_status_code: str = "UNKNOWN"
    city_center_longitude: Decimal | None = None
    city_center_latitude: Decimal | None = None

class VesselAisCityBoundaryResponse(BaseModel):
    generated_at: datetime
    boundary_version_id: int | None = None
    precision: str = "low"
    total: int = 0
    items: list[VesselAisCityBoundaryItemResponse] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)

class VesselPositionWaterSystemSituationItemResponse(BaseModel):
    water_system_code: str | None = None
    water_system_name: str
    parent_water_system_code: str | None = None
    water_level: int | None = None
    water_level_name: str | None = None
    feature_type_code: str | None = None
    feature_type_name: str | None = None
    hydrology_period_code: str | None = None
    hydrology_period_name: str | None = None
    salinity_type_code: str | None = None
    salinity_type_name: str | None = None
    water_boundary_type_code: str | None = None
    water_boundary_type_name: str | None = None
    navigation_category_code: str | None = None
    navigation_category_name: str | None = None
    navigation_scope_code: str | None = None
    navigation_scope_name: str | None = None
    center_longitude: Decimal | None = None
    center_latitude: Decimal | None = None
    display_center_longitude: Decimal | None = None
    display_center_latitude: Decimal | None = None
    heat_center_longitude: Decimal | None = None
    heat_center_latitude: Decimal | None = None
    boundary_paths: list[list[list[float]]] | None = None
    has_boundary: bool = False
    boundary_precision: str | None = None
    boundary_quality_code: str | None = None
    boundary_quality_name: str | None = None
    geometry_coordinate_system_code: str | None = None
    boundary_coordinate_system_code: str | None = None
    positioned_count: int
    contactable_position_count: int
    total_deadweight_ton: Decimal | None = None
    ship_type_distribution: list[VesselShipTypeDistributionItemResponse] = Field(default_factory=list)
    stale_position_count: int = 0
    certificate_risk_count: int = 0
    high_risk_count: int = 0
    unmatched_mmsi_count: int = 0
    invalid_position_count: int = 0
    freshness_distribution: dict[str, int] = Field(default_factory=dict)
    boundary_status_code: str = "UNKNOWN"
    latest_position_time: datetime | None = None
    mmsi_count: int = 0
    matched_position_count: int = 0
    unpositioned_count: int = 0
    is_partial: bool = False
    error_message: str | None = None

class VesselPositionWaterSystemSituationSummary(BaseModel):
    matched_profile_count: int
    scanned_profile_count: int = 0
    unscanned_profile_count: int = 0
    queried_mmsi_count: int
    matched_position_count: int
    unmatched_mmsi_count: int = 0
    unpositioned_count: int
    invalid_position_count: int = 0
    unknown_water_system_count: int = 0
    positioned_count: int
    stale_position_count: int
    contactable_position_count: int
    certificate_risk_count: int
    high_risk_count: int = 0
    water_system_count: int
    boundary_water_system_count: int = 0
    missing_boundary_water_system_count: int = 0
    query_snapshot_id: str | None = None
    snapshot_status_code: str = "READY"
    snapshot_expires_at: datetime | None = None
    refresh_required: bool = False
    coverage_rate: Decimal | None = None
    freshness_distribution: dict[str, int] = Field(default_factory=dict)
    source_indices: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    failed_batch_count: int = 0
    failed_batches: list[dict[str, Any]] = Field(default_factory=list)
    is_partial: bool = False
    error_message: str | None = None

class VesselPositionWaterSystemSituationResponse(BaseModel):
    source_status: str
    source_status_name: str
    generated_at: datetime
    message: str | None = None
    cache_status: str = "MISS"
    cache_generated_at: datetime | None = None
    is_stale_cache: bool = False
    snapshot_backend: str = "memory"
    cache_backend_note: str | None = None
    summary: VesselPositionWaterSystemSituationSummary
    water_systems: list[VesselPositionWaterSystemSituationItemResponse] = Field(default_factory=list)

class VesselPositionWaterSystemVesselsResponse(PageResponse[VesselPositionMonitorItemResponse]):
    query_snapshot_id: str | None = None
    snapshot_hit: bool = False
    refresh_required: bool = False
    snapshot_status_code: str | None = None
    is_partial: bool = False
    error_message: str | None = None

class VesselAisWaterSystemBoundaryItemResponse(BaseModel):
    water_system_code: str
    water_system_name: str
    parent_water_system_code: str | None = None
    water_level: int
    water_level_name: str
    navigation_category_code: str | None = None
    navigation_category_name: str | None = None
    navigation_scope_code: str | None = None
    navigation_scope_name: str | None = None
    display_center_longitude: Decimal | None = None
    display_center_latitude: Decimal | None = None
    boundary_paths: list[list[list[float]]] = Field(default_factory=list)
    has_boundary: bool = False
    boundary_precision: str = "low"
    boundary_status_code: str = "UNKNOWN"
    boundary_quality_code: str | None = None
    boundary_quality_name: str | None = None
    center_longitude: Decimal | None = None
    center_latitude: Decimal | None = None
    geometry_coordinate_system_code: str | None = None
    boundary_coordinate_system_code: str | None = None

class VesselAisWaterSystemBoundaryResponse(BaseModel):
    generated_at: datetime
    boundary_version_id: int | None = None
    precision: str = "low"
    total: int = 0
    items: list[VesselAisWaterSystemBoundaryItemResponse] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)

class VesselAisSnapshotResponse(BaseModel):
    snapshot_id: str
    query_hash: str
    query_params: dict[str, Any] = Field(default_factory=dict)
    status_code: str
    generated_at: datetime
    expires_at: datetime
    cache_backend_code: str
    scanned_profile_count: int
    queried_mmsi_count: int
    matched_profile_count: int
    matched_position_count: int
    unmatched_mmsi_count: int
    invalid_position_count: int
    unknown_city_count: int
    failed_batch_count: int
    failed_batches: list[dict[str, Any]] = Field(default_factory=list)
    coverage_rate: Decimal | None = None
    freshness_distribution: dict[str, int] = Field(default_factory=dict)
    source_indices: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    refresh_error: str | None = None

class VesselAisUnmatchedMmsiResponse(BaseModel):
    snapshot_id: str | None = None
    generated_at: datetime | None = None
    mmsi: str
    longitude: Decimal | None = None
    latitude: Decimal | None = None
    position_time: datetime | None = None
    freshness_level: str = "UNKNOWN"
    source_index: str | None = None
    city_code: str | None = None
    city_name: str | None = None
    match_status_code: str = "UNMATCHED_MMSI"

class VesselSpatialSnapshotMeta(BaseModel):
    snapshot_id: str
    source_snapshot_id: str | None = None
    observation_type_code: str
    status_code: str
    source_status_code: str
    stat_time: datetime | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    generated_at: datetime
    expires_at: datetime
    refresh_required: bool = False
    coverage_rate: Decimal | None = None
    confidence_level: str = "UNKNOWN"
    freshness_distribution: dict[str, int] = Field(default_factory=dict)
    source_indices: list[str] = Field(default_factory=list)
    failed_batch_count: int = 0
    failed_batches: list[dict[str, Any]] = Field(default_factory=list)
    unmatched_mmsi_count: int = 0
    invalid_position_count: int = 0
    stale_position_count: int = 0
    matched_position_count: int = 0
    active_vessel_count: int = 0
    not_computable_reasons: list[str] = Field(default_factory=list)
    quality_warnings: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    refresh_error: str | None = None

class VesselNavigationConstraintEvidenceResponse(BaseModel):
    id: int | None = None
    snapshot_id: str | None = None
    context_type_code: str
    context_id: int
    constraint_point_id: int | None = None
    constraint_name: str | None = None
    constraint_type_code: str | None = None
    status_code: str = "UNKNOWN"
    source_type_code: str = "BASE_DATA"
    source_ref: str | None = None
    observed_at: datetime | None = None
    expires_at: datetime | None = None
    value: dict[str, Any] = Field(default_factory=dict)
    confidence_level: str = "UNKNOWN"
    unavailable_reason: str | None = None

class VesselNodeObservationVesselResponse(BaseModel):
    id: int | None = None
    vessel_profile_id: int | None = None
    mmsi: str
    ship_name: str | None = None
    ship_type_code: str | None = None
    deadweight_ton: Decimal | None = None
    longitude: Decimal | None = None
    latitude: Decimal | None = None
    distance_km: Decimal | None = None
    position_time: datetime | None = None
    source_index: str | None = None
    freshness_level: str = "UNKNOWN"
    match_status_code: str = "NEARBY"
    stay_duration_minutes: int | None = None
    direction_status_code: str = "UNKNOWN"
    risk_level: str | None = None
    quality_level: str | None = None

class VesselNodeSituationSummary(BaseModel):
    node_id: int
    node_name: str
    node_type_code: str | None = None
    city_code: str | None = None
    radius_km: Decimal
    longitude: Decimal | None = None
    latitude: Decimal | None = None
    active_vessel_count: int = 0
    stay_vessel_count: int = 0
    passby_vessel_count: int = 0
    inflow_count: int = 0
    outflow_count: int = 0
    unmatched_mmsi_count: int = 0
    invalid_position_count: int = 0
    stale_position_count: int = 0
    coverage_rate: Decimal | None = None
    confidence_level: str = "UNKNOWN"
    freshness_distribution: dict[str, int] = Field(default_factory=dict)
    ship_type_distribution: list[VesselShipTypeDistributionItemResponse] = Field(default_factory=list)
    risk_distribution: list[VesselAssetDistributionItemResponse] = Field(default_factory=list)
    latest_position_time: datetime | None = None
    not_computable_reasons: list[str] = Field(default_factory=list)

class VesselAisNodeSituationResponse(BaseModel):
    source_status: str
    source_status_name: str
    generated_at: datetime
    message: str | None = None
    snapshot: VesselSpatialSnapshotMeta
    summary: VesselNodeSituationSummary
    vessels: list[VesselNodeObservationVesselResponse] = Field(default_factory=list)
    constraints: list[VesselNavigationConstraintEvidenceResponse] = Field(default_factory=list)

class VesselAisNodeVesselsResponse(PageResponse[VesselNodeObservationVesselResponse]):
    query_snapshot_id: str | None = None
    snapshot_hit: bool = False
    refresh_required: bool = False
    snapshot_status_code: str | None = None
    is_partial: bool = False
    error_message: str | None = None

class VesselRouteSegmentObservationResponse(BaseModel):
    id: int | None = None
    route_id: int | None = None
    line_id: int
    segment_id: int
    segment_no: int
    segment_name: str | None = None
    geometry_status_code: str = "UNKNOWN"
    geometry_source: str | None = None
    geometry_json: dict[str, Any] | None = None
    matched_vessel_count: int = 0
    active_vessel_count: int = 0
    point_count: int = 0
    gap_count: int = 0
    covered_ratio: Decimal | None = None
    average_match_score: Decimal | None = None
    coverage_rate: Decimal | None = None
    confidence_level: str = "UNKNOWN"
    not_computable_reasons: list[str] = Field(default_factory=list)

class VesselRouteSegmentMatchSampleResponse(BaseModel):
    id: int | None = None
    segment_id: int
    vessel_profile_id: int | None = None
    mmsi: str
    ship_name: str | None = None
    ship_type_code: str | None = None
    deadweight_ton: Decimal | None = None
    match_score: Decimal | None = None
    covered_ratio: Decimal | None = None
    direction_consistency: Decimal | None = None
    point_count: int = 0
    gap_count: int = 0
    latest_position_time: datetime | None = None
    source_index: str | None = None
    freshness_level: str = "UNKNOWN"
    confidence_level: str = "UNKNOWN"
    match_status_code: str = "MATCHED"

class VesselRouteSituationSummary(BaseModel):
    route_id: int | None = None
    line_id: int
    line_name: str | None = None
    segment_count: int = 0
    matched_segment_count: int = 0
    matched_vessel_count: int = 0
    active_vessel_count: int = 0
    coverage_rate: Decimal | None = None
    confidence_level: str = "UNKNOWN"
    not_computable_reasons: list[str] = Field(default_factory=list)

class VesselAisRouteSituationResponse(BaseModel):
    source_status: str
    source_status_name: str
    generated_at: datetime
    message: str | None = None
    snapshot: VesselSpatialSnapshotMeta
    summary: VesselRouteSituationSummary
    segments: list[VesselRouteSegmentObservationResponse] = Field(default_factory=list)
    samples: list[VesselRouteSegmentMatchSampleResponse] = Field(default_factory=list)
    constraints: list[VesselNavigationConstraintEvidenceResponse] = Field(default_factory=list)

class VesselAisRouteSegmentVesselsResponse(PageResponse[VesselRouteSegmentMatchSampleResponse]):
    query_snapshot_id: str | None = None
    snapshot_hit: bool = False
    refresh_required: bool = False
    snapshot_status_code: str | None = None
    is_partial: bool = False
    error_message: str | None = None

class VesselSpatialSnapshotResponse(BaseModel):
    snapshot: VesselSpatialSnapshotMeta
    node: VesselNodeSituationSummary | None = None
    route: VesselRouteSituationSummary | None = None
    segments: list[VesselRouteSegmentObservationResponse] = Field(default_factory=list)
    constraints: list[VesselNavigationConstraintEvidenceResponse] = Field(default_factory=list)

class VesselNavigationConstraintResponse(BaseModel):
    generated_at: datetime
    context_type_code: str
    context_id: int
    source_status: str = "AVAILABLE"
    uncertainty_notes: list[str] = Field(default_factory=list)
    items: list[VesselNavigationConstraintEvidenceResponse] = Field(default_factory=list)

class VesselBusinessSituationCardResponse(BaseModel):
    vessel_id: int
    generated_at: datetime
    identity: dict[str, Any]
    realtime: dict[str, Any]
    operation: dict[str, Any]
    compliance: dict[str, Any]
    business: dict[str, Any]

class VesselAisSituationCardResponse(BaseModel):
    vessel_id: int
    generated_at: datetime
    data_sources: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    identity: dict[str, Any]
    realtime: dict[str, Any]
    data_availability: dict[str, Any]
    quality: dict[str, Any]
