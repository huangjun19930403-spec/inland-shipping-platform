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


class NavigationWorkbenchChannelResponse(BaseModel):
    id: int
    channel_code: str
    channel_name: str
    display_name: str | None = None
    planning_level_code: str | None = None
    channel_type_code: str | None = None
    review_required: bool = False
    boundary_count: int = 0
    current_boundary_count: int = 0
    centerline_count: int = 0
    approved_current_centerline_count: int = 0
    active_graph_edge_count: int = 0
    boundary_status_code: str
    centerline_status_code: str
    graph_status_code: str


class NavigationWorkbenchSummaryResponse(BaseModel):
    stats: dict[str, int] = Field(default_factory=dict)
    active_graph_version: dict[str, Any] | None = None
    channels: list[NavigationWorkbenchChannelResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class NavigationWaterAreaListItemResponse(BaseModel):
    id: int
    source_code: str
    source_layer_name: str
    water_name: str | None = None
    water_type_code: str
    geometry_status_code: str
    bbox: dict[str, float | None] = Field(default_factory=dict)
    area_km2: float | None = None


class NavigationCenterlineListItemResponse(BaseModel):
    id: int
    channel_id: int
    channel_code: str | None = None
    channel_name: str | None = None
    centerline_code: str
    centerline_name: str | None = None
    source_type_code: str
    quality_code: str
    review_status_code: str
    confidence_score: int
    is_current: bool
    geometry_json: dict[str, Any] | None = None


class NavigationBoundaryListItemResponse(BaseModel):
    id: int
    channel_id: int
    channel_code: str | None = None
    channel_name: str | None = None
    boundary_quality_code: str
    geometry_status_code: str
    connectivity_status_code: str
    repair_status_code: str
    coverage_policy_code: str
    is_current: bool
    geometry_json: dict[str, Any] | None = None


class NavigationGraphVersionListItemResponse(BaseModel):
    id: int
    version_code: str
    version_name: str
    scope_code: str
    status_code: str
    is_active: bool
    node_count: int
    edge_count: int
    channel_count: int
    quality_score: int | None = None
    built_at: str | None = None
    validation_report_json: dict[str, Any] | None = None


class NavigationGeometryDraftResponse(BaseModel):
    id: int
    draft_no: str
    draft_name: str | None = None
    draft_type_code: str
    geometry_type_code: str
    channel_id: int | None = None
    channel_code: str | None = None
    channel_name: str | None = None
    target_type_code: str | None = None
    target_id: int | None = None
    geometry_json: dict[str, Any]
    source_type_code: str
    status_code: str
    quality_code: str
    review_comment: str | None = None
    publish_target_type_code: str | None = None
    publish_target_id: int | None = None
    bbox: dict[str, float | None] = Field(default_factory=dict)


class NavigationGeometryDraftCreateRequest(BaseModel):
    draft_type_code: str = Field(max_length=64)
    draft_name: str | None = Field(default=None, max_length=128)
    channel_id: int | None = None
    target_type_code: str | None = Field(default=None, max_length=64)
    target_id: int | None = None
    geometry_json: dict[str, Any]
    source_type_code: str = Field(default="GEOJSON_PASTE", max_length=64)
    source_trace_json: dict[str, Any] | None = None


class NavigationGeometryDraftUpdateRequest(BaseModel):
    draft_name: str | None = Field(default=None, max_length=128)
    channel_id: int | None = None
    target_type_code: str | None = Field(default=None, max_length=64)
    target_id: int | None = None
    geometry_json: dict[str, Any] | None = None
    source_type_code: str | None = Field(default=None, max_length=64)
    source_trace_json: dict[str, Any] | None = None
    review_comment: str | None = Field(default=None, max_length=512)


class NavigationGeometryDraftApproveRequest(BaseModel):
    review_comment: str | None = Field(default=None, max_length=512)


class NavigationGraphBuildRequest(BaseModel):
    version_code: str | None = Field(default=None, max_length=96)
    version_name: str | None = Field(default=None, max_length=128)
    scope_code: str = Field(default="REAL-JS-YRD", max_length=64)
    channel_codes: list[str] | None = None
    activate: bool = False


class NavigationGraphBuildResponse(BaseModel):
    version_code: str
    graph_version_id: int
    status_code: str
    node_count: int
    edge_count: int
    channel_count: int
    quality_score: int | None = None
    centerline_count: int = 0
    connector_edge_count: int = 0
    constraint_count: int = 0
    validation_report: dict[str, Any] | None = None


class NavigationGraphActivateResponse(BaseModel):
    graph_version_id: int
    version_code: str
    scope_code: str
    status_code: str
    is_active: bool
