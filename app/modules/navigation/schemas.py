from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class NavigationEndpointRequest(BaseModel):
    endpoint_type_code: str = Field(default="LNG_LAT", max_length=64)
    longitude: float | None = None
    latitude: float | None = None
    name: str | None = Field(default=None, max_length=128)
    ref_id: int | None = None
    transport_node_id: int | None = None
    constraint_point_id: int | None = None


class VesselProfileRequest(BaseModel):
    length_m: float | None = Field(default=None, gt=0)
    beam_m: float | None = Field(default=None, gt=0)
    draft_m: float | None = Field(default=None, gt=0)
    deadweight_ton: float | None = Field(default=None, gt=0)
    air_draft_m: float | None = Field(default=None, gt=0)
    loaded_status: str | None = Field(default=None, max_length=64)


class NavigationRouteGenerateRequest(BaseModel):
    origin: NavigationEndpointRequest
    destination: NavigationEndpointRequest
    vessel_profile: VesselProfileRequest | None = None
    vessel_profile_json: dict[str, Any] | None = None
    routing_preference_code: str = Field(default="RECOMMENDED", max_length=64)
    graph_version_id: int | None = None


class NavigationSnapResponse(BaseModel):
    role: str
    snap_type: str
    snap_distance_m: float
    snap_confidence: int
    snap_point: list[float]
    graph_node_id: int | None = None
    graph_edge_id: int | None = None
    quality_code: str


class NavigationRouteIssueResponse(BaseModel):
    issue_type_code: str
    severity_code: str
    message: str
    suggestion: str | None = None
    related_edge_id: int | None = None
    related_node_id: int | None = None


class NavigationRouteGenerateResponse(BaseModel):
    request_id: int
    result_id: int
    graph_version_id: int | None
    status_code: str
    quality_code: str
    quality_score: int | None
    geometry_json: dict[str, Any] | None = None
    distance_km: float | None = None
    estimated_duration_hour: float | None = None
    edge_ids: list[int] = Field(default_factory=list)
    channel_ids: list[int] = Field(default_factory=list)
    passed_node_ids: list[int] = Field(default_factory=list)
    passed_lock_count: int = 0
    passed_bridge_count: int = 0
    origin_snap: NavigationSnapResponse | None = None
    destination_snap: NavigationSnapResponse | None = None
    issues: list[NavigationRouteIssueResponse] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None


class NavigationMapLayerFeatureResponse(BaseModel):
    id: int | str
    layer_type_code: str
    name: str | None = None
    geometry_json: dict[str, Any] | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class NavigationMapLayerResponse(BaseModel):
    bbox: dict[str, float] | None = None
    water_areas: list[NavigationMapLayerFeatureResponse] = Field(default_factory=list)
    channel_boundaries: list[NavigationMapLayerFeatureResponse] = Field(default_factory=list)
    centerlines: list[NavigationMapLayerFeatureResponse] = Field(default_factory=list)
    graph_edges: list[NavigationMapLayerFeatureResponse] = Field(default_factory=list)
    route_results: list[NavigationMapLayerFeatureResponse] = Field(default_factory=list)
    quality_issues: list[NavigationMapLayerFeatureResponse] = Field(default_factory=list)
    truncated_layers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class NavigationAnnotationTaskResponse(BaseModel):
    id: int
    task_no: str
    task_type_code: str
    target_type_code: str
    target_id: int | None = None
    channel_id: int | None = None
    graph_version_id: int | None = None
    geometry_json: dict[str, Any] | None = None
    priority_code: str
    status_code: str
    issue_summary: str
    suggestion_json: dict[str, Any] | None = None
    assigned_to: int | None = None
    reviewed_by: int | None = None
    resolution_type_code: str | None = None
    resolution_target_type_code: str | None = None
    resolution_target_id: int | None = None
    created_by: int | None = None


class NavigationAnnotationTaskListResponse(BaseModel):
    items: list[NavigationAnnotationTaskResponse] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class NavigationAnnotationTaskBatchCreateResponse(BaseModel):
    created_count: int
    existing_count: int
    task_ids: list[int] = Field(default_factory=list)
    source_type_code: str


class NavigationAnnotationSuggestionResponse(BaseModel):
    task_id: int
    suggestion_json: dict[str, Any]


class NavigationAnnotationTaskResolveRequest(BaseModel):
    resolution_type_code: str = Field(max_length=64)
    resolution_target_type_code: str | None = Field(default=None, max_length=64)
    resolution_target_id: int | None = None
    suggestion_json: dict[str, Any] | None = None
    status_code: str = Field(default="RESOLVED", max_length=64)
