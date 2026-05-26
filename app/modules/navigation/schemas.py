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
    planning_mode_code: str = Field(default="RECOMMENDED", max_length=64)
    alternative_count: int = Field(default=1, ge=1, le=5)
    include_alternatives: bool = False
    include_explain: bool = True


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


class NavigationRouteAlternativeResponse(BaseModel):
    result_id: int
    result_no: int
    result_type_code: str
    quality_code: str
    quality_score: int | None = None
    distance_km: float | None = None
    estimated_duration_hour: float | None = None
    edge_ids: list[int] = Field(default_factory=list)
    channel_ids: list[int] = Field(default_factory=list)
    passed_lock_count: int = 0
    passed_bridge_count: int = 0
    issues: list[NavigationRouteIssueResponse] = Field(default_factory=list)
    explain: dict[str, Any] | None = None
    geometry_json: dict[str, Any] | None = None


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
    alternatives: list[NavigationRouteAlternativeResponse] = Field(default_factory=list)
    explain: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None


class NavigationMapLayerFeatureResponse(BaseModel):
    id: int | str
    layer_type_code: str
    name: str | None = None
    geometry_json: dict[str, Any] | None = None
    coordinate_system_code: str = "WGS84"
    display_coordinate_system_code: str = "GCJ02_AMAP"
    properties: dict[str, Any] = Field(default_factory=dict)


class NavigationMapLayerResponse(BaseModel):
    bbox: dict[str, float] | None = None
    coordinate_system_code: str = "WGS84"
    display_coordinate_system_code: str = "GCJ02_AMAP"
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
    published_current_centerline_count: int = 0
    active_graph_edge_count: int = 0
    current_water_body_match_count: int = 0
    boundary_status_code: str
    centerline_status_code: str
    graph_status_code: str
    water_body_match_status_code: str = "MISSING"


class NavigationWorkbenchSummaryResponse(BaseModel):
    stats: dict[str, int] = Field(default_factory=dict)
    active_graph_version: dict[str, Any] | None = None
    channels: list[NavigationWorkbenchChannelResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class NavigationProductionStepResponse(BaseModel):
    step_code: str
    step_name: str
    status_code: str
    count: int = 0
    blocker_code: str | None = None
    next_path: str | None = None


class NavigationProductionChannelResponse(BaseModel):
    id: int
    channel_code: str
    channel_name: str
    display_name: str | None = None
    planning_level_code: str | None = None
    channel_type_code: str | None = None
    production_stage_code: str
    production_stage_name: str
    next_action_label: str
    next_path: str
    blocker_codes: list[str] = Field(default_factory=list)
    current_water_body_match_count: int = 0
    candidate_boundary_count: int = 0
    current_boundary_count: int = 0
    centerline_candidate_count: int = 0
    published_current_centerline_count: int = 0
    active_graph_edge_count: int = 0
    route_verified_count: int = 0
    diagnostic_issue_codes: list[str] = Field(default_factory=list)
    water_body_candidate_count: int = 0
    seed_boundary_overlap_ratio: float | None = None
    steps: list[NavigationProductionStepResponse] = Field(default_factory=list)
    available_actions: list[dict[str, Any]] = Field(default_factory=list)


class NavigationProductionSummaryResponse(BaseModel):
    stats: dict[str, int] = Field(default_factory=dict)
    stage_counts: dict[str, int] = Field(default_factory=dict)
    active_graph_version: dict[str, Any] | None = None
    channels: list[NavigationProductionChannelResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class NavigationChannelPipelineResponse(BaseModel):
    channel: NavigationProductionChannelResponse
    map_layer_query: dict[str, Any] = Field(default_factory=dict)
    available_actions: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class NavigationProductionLayerLegendResponse(BaseModel):
    layer_code: str
    layer_name: str
    layer_role: str
    enabled: bool = True
    attention_level: str = "NORMAL"


class NavigationProductionWorkspaceResponse(BaseModel):
    channel: NavigationProductionChannelResponse
    step_code: str
    step_name: str
    map_layers: NavigationMapLayerResponse
    layer_legends: list[NavigationProductionLayerLegendResponse] = Field(default_factory=list)
    water_matches: NavigationChannelWaterBodyMatchListResponse | None = None
    water_candidates: NavigationWaterBodyCandidateListResponse | None = None
    boundaries: list[NavigationBoundaryListItemResponse] = Field(default_factory=list)
    centerlines: list[NavigationCenterlineListItemResponse] = Field(default_factory=list)
    drafts: list[NavigationGeometryDraftResponse] = Field(default_factory=list)
    current_boundary: NavigationBoundaryListItemResponse | None = None
    current_centerline: NavigationCenterlineListItemResponse | None = None
    active_graph_version: dict[str, Any] | None = None
    downstream_stale: dict[str, Any] = Field(default_factory=dict)
    available_actions: list[dict[str, Any]] = Field(default_factory=list)
    blocker_codes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class NavigationCandidateGenerateRequest(BaseModel):
    force: bool = False
    source_type_code: str | None = Field(default=None, max_length=64)


class NavigationCandidateGenerateResponse(BaseModel):
    status_code: str
    message: str
    created_count: int = 0
    candidate_count: int = 0
    next_path: str | None = None
    boundary_ids: list[int] = Field(default_factory=list)
    centerline_ids: list[int] = Field(default_factory=list)
    blocker_codes: list[str] = Field(default_factory=list)
    matched_water_body_count: int = 0
    candidate_types: list[str] = Field(default_factory=list)
    source_summary: dict[str, Any] = Field(default_factory=dict)


class NavigationChannelDiagnosticBoundaryResponse(BaseModel):
    id: int | None = None
    coverage_policy_code: str | None = None
    boundary_quality_code: str | None = None
    connectivity_status_code: str | None = None
    repair_status_code: str | None = None
    geometry_status_code: str | None = None
    coordinate_system_code: str | None = None
    ring_count: int = 0
    point_count: int = 0
    bbox: dict[str, float | None] = Field(default_factory=dict)


class NavigationChannelDiagnosticResponse(BaseModel):
    channel_id: int
    channel_code: str
    channel_name: str
    production_stage_code: str
    production_stage_name: str
    current_boundary: NavigationChannelDiagnosticBoundaryResponse | None = None
    boundary_source_code: str = "NONE"
    boundary_source_explanation: str
    seed_boundary_overlap_ratio: float | None = None
    current_water_body_match_count: int = 0
    water_body_candidate_count: int = 0
    candidate_boundary_count: int = 0
    current_boundary_count: int = 0
    centerline_candidate_count: int = 0
    published_current_centerline_count: int = 0
    active_graph_edge_count: int = 0
    route_verified_count: int = 0
    issue_codes: list[str] = Field(default_factory=list)
    blocker_codes: list[str] = Field(default_factory=list)
    recommended_next_action: str
    recommended_path: str
    suggested_terms: list[str] = Field(default_factory=list)
    source_trace_json: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class NavigationWaterBodyCandidateResponse(BaseModel):
    water_body_id: int
    water_body_code: str | None = None
    water_name: str | None = None
    normalized_water_name: str | None = None
    display_name: str | None = None
    production_name: str | None = None
    source_code: str
    body_role_code: str
    source_layer_name: str | None = None
    source_layer_display_name: str | None = None
    source_layer_role_code: str | None = None
    water_type_code: str
    feature_count: int = 0
    area_km2: float | None = None
    bbox: dict[str, float | None] = Field(default_factory=dict)
    display_bbox: dict[str, float | None] = Field(default_factory=dict)
    candidate_type_code: str
    matched_term: str | None = None
    score: int
    confidence_code: str
    reason_codes: list[str] = Field(default_factory=list)
    issue_codes: list[str] = Field(default_factory=list)
    source_water_area_ids: list[int] = Field(default_factory=list)
    already_matched: bool = False


class NavigationWaterBodyCandidateListResponse(BaseModel):
    channel_id: int
    channel_code: str
    channel_name: str
    total: int
    suggested_terms: list[str] = Field(default_factory=list)
    issue_codes: list[str] = Field(default_factory=list)
    items: list[NavigationWaterBodyCandidateResponse] = Field(default_factory=list)


class NavigationCandidateConfirmRequest(BaseModel):
    score: int = Field(default=92, ge=0, le=100)
    candidate_type_code: str = Field(default="CONFIRMED_MATCH", max_length=64)
    issue_codes: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class NavigationDiagnosticsRunResponse(BaseModel):
    channel_count: int
    issue_counts: dict[str, int] = Field(default_factory=dict)
    items: list[NavigationChannelDiagnosticResponse] = Field(default_factory=list)


class NavigationOsmImportRequest(BaseModel):
    source_path: str | None = Field(default=None, max_length=512)
    scope_code: str = Field(default="REAL-JS-YRD", max_length=64)
    province_codes: list[str] = Field(default_factory=lambda: ["JS", "ZJ", "SH", "AH"])
    dry_run: bool = True


class NavigationOsmImportResponse(BaseModel):
    status_code: str
    imported_count: int = 0
    candidate_count: int = 0
    message: str
    next_path: str | None = None


class NavigationWaterAreaListItemResponse(BaseModel):
    id: int
    source_code: str
    source_layer_name: str
    source_layer_code: str | None = None
    source_layer_display_name: str | None = None
    source_layer_role_code: str | None = None
    source_layer_order: int | None = None
    source_file_name: str | None = None
    source_object_id: str | None = None
    has_attributes: bool = True
    raw_properties_summary: dict[str, Any] | None = None
    water_name: str | None = None
    normalized_water_name: str | None = None
    water_type_code: str
    geometry_status_code: str
    bbox: dict[str, float | None] = Field(default_factory=dict)
    center_lng: float | None = None
    center_lat: float | None = None
    area_km2: float | None = None
    match_count: int = 0
    is_matched: bool = False
    matched_channels: list[dict[str, Any]] = Field(default_factory=list)


class NavigationWaterAreaListResponse(BaseModel):
    items: list[NavigationWaterAreaListItemResponse] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class NavigationWaterBodyListItemResponse(BaseModel):
    group_key: str
    id: int | None = None
    water_body_code: str | None = None
    source_code: str
    body_role_code: str | None = None
    dedupe_status_code: str | None = None
    source_layer_code: str | None = None
    source_layer_name: str | None = None
    source_layer_display_name: str | None = None
    source_layer_role_code: str | None = None
    source_layer_order: int | None = None
    water_name: str | None = None
    normalized_water_name: str | None = None
    display_name: str | None = None
    production_name: str | None = None
    name_status_code: str = "RAW_NAMED"
    name_source_code: str | None = None
    name_note: str | None = None
    water_type_code: str
    feature_count: int
    enabled_count: int
    repaired_count: int
    invalid_count: int
    total_area_km2: float | None = None
    quality_code: str | None = None
    source_layer_summary: dict[str, Any] | None = None
    coordinate_system_code: str = "WGS84"
    display_coordinate_system_code: str = "GCJ02_AMAP"
    bbox: dict[str, float | None] = Field(default_factory=dict)
    display_bbox: dict[str, float | None] = Field(default_factory=dict)
    match_count: int = 0
    is_matched: bool = False
    matched_channels: list[dict[str, Any]] = Field(default_factory=list)
    representative_water_area_ids: list[int] = Field(default_factory=list)


class NavigationWaterBodyListResponse(BaseModel):
    items: list[NavigationWaterBodyListItemResponse] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class NavigationWaterAreaLayerSummaryResponse(BaseModel):
    source_layer_name: str
    source_layer_code: str | None = None
    source_layer_display_name: str | None = None
    source_layer_role_code: str | None = None
    source_layer_order: int | None = None
    count: int
    raw_count: int = 0
    enabled_count: int = 0
    invalid_count: int = 0
    named_count: int = 0


class NavigationWaterAreaSummaryResponse(BaseModel):
    total_count: int
    raw_total_count: int = 0
    enabled_count: int = 0
    invalid_count: int = 0
    real_count: int
    named_count: int
    unnamed_count: int
    matched_count: int
    unmatched_count: int
    water_body_count: int = 0
    standard_body_count: int = 0
    hierarchy_body_count: int = 0
    rx_fill_body_count: int = 0
    rx_duplicate_link_count: int = 0
    rx8_body_count: int = 0
    invalid_body_count: int = 0
    matched_water_body_count: int = 0
    unmatched_water_body_count: int = 0
    unnamed_water_body_count: int = 0
    layer_counts: list[NavigationWaterAreaLayerSummaryResponse] = Field(default_factory=list)


class NavigationWaterBodyNameUpdateRequest(BaseModel):
    production_name: str = Field(min_length=1, max_length=128)
    name_note: str | None = Field(default=None, max_length=512)


class NavigationChannelWaterBodyMatchItemResponse(BaseModel):
    id: int
    channel_id: int
    channel_code: str | None = None
    channel_name: str | None = None
    water_body_id: int
    water_body_code: str | None = None
    water_name: str | None = None
    production_name: str | None = None
    source_code: str
    body_role_code: str
    source_layer_name: str | None = None
    source_layer_display_name: str | None = None
    water_type_code: str
    feature_count: int = 0
    match_batch_code: str
    match_type_code: str
    matched_term: str | None = None
    score: int
    confidence_code: str
    issue_codes: list[str] = Field(default_factory=list)
    is_current: bool
    bbox: dict[str, float | None] = Field(default_factory=dict)
    source_water_area_ids: list[int] = Field(default_factory=list)
    source_trace_json: dict[str, Any] | None = None


class NavigationChannelWaterBodyMatchListResponse(BaseModel):
    channel_id: int
    channel_code: str
    channel_name: str
    current_match_count: int
    best_score: int | None = None
    confidence_code: str = "MISSING"
    issue_codes: list[str] = Field(default_factory=list)
    match_batch_code: str | None = None
    items: list[NavigationChannelWaterBodyMatchItemResponse] = Field(default_factory=list)


class NavigationWaterBodyMatchCreateRequest(BaseModel):
    water_body_id: int
    match_type_code: str = Field(default="MANUAL_ADD", max_length=64)
    matched_term: str | None = Field(default=None, max_length=128)
    score: int = Field(default=90, ge=0, le=100)
    confidence_code: str = Field(default="MANUAL_CONFIRMED", max_length=64)
    issue_codes: list[str] = Field(default_factory=list)
    match_batch_code: str | None = Field(default=None, max_length=96)
    source_trace_json: dict[str, Any] | None = None


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
    source_trace_json: dict[str, Any] | None = None
    source_boundary_id: int | None = None
    based_on_boundary_id: int | None = None
    downstream_stale: bool = False
    created_at: str | None = None
    updated_at: str | None = None


class NavigationCenterlineSegmentGenerateRequest(BaseModel):
    force: bool = False
    segment_length_km: float = Field(default=5.0, gt=0, le=100)
    source_mode: str = Field(default="BOUNDARY", max_length=32)


class NavigationCenterlineSegmentGenerateResponse(BaseModel):
    status_code: str
    message: str
    channel_id: int
    segment_count: int = 0
    need_repair_count: int = 0
    confirmed_count: int = 0
    segment_ids: list[int] = Field(default_factory=list)
    blocker_codes: list[str] = Field(default_factory=list)
    next_path: str | None = None


class NavigationCenterlineSegmentResponse(BaseModel):
    id: int
    channel_id: int
    centerline_id: int | None = None
    segment_no: str
    segment_name: str
    segment_status_code: str
    source_type_code: str
    quality_code: str
    length_m: float | None = None
    start_lng: float | None = None
    start_lat: float | None = None
    end_lng: float | None = None
    end_lat: float | None = None
    bbox_min_lng: float | None = None
    bbox_min_lat: float | None = None
    bbox_max_lng: float | None = None
    bbox_max_lat: float | None = None
    previous_segment_id: int | None = None
    next_segment_id: int | None = None
    start_connected_flag: bool = False
    end_connected_flag: bool = False
    geometry_json: dict[str, Any] | None = None
    issue_summary_json: dict[str, Any] | None = None
    validation_summary_json: dict[str, Any] | None = None
    source_trace_json: dict[str, Any] | None = None
    source_boundary_id: int | None = None
    based_on_boundary_id: int | None = None
    source_mode: str | None = None
    source_algorithm: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class NavigationCenterlineSegmentListResponse(BaseModel):
    channel_id: int
    total_count: int
    need_repair_count: int
    confirmed_count: int
    publishable: bool
    items: list[NavigationCenterlineSegmentResponse] = Field(default_factory=list)


class NavigationCenterlineSegmentUpdateRequest(BaseModel):
    geometry_json: dict[str, Any]
    source_type_code: str = Field(default="MAP_EDIT", max_length=64)


class NavigationCenterlineSegmentSplitRequest(BaseModel):
    split_ratio: float = Field(default=0.5, gt=0, lt=1)


class NavigationCenterlineSegmentPublishRequest(BaseModel):
    publish_name: str | None = Field(default=None, max_length=128)


class NavigationCenterlineSegmentPublishResponse(BaseModel):
    status_code: str
    message: str
    channel_id: int
    centerline_id: int | None = None
    segment_count: int = 0
    quality_code: str | None = None
    blocker_codes: list[str] = Field(default_factory=list)
    next_path: str | None = None


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
    source_trace_json: dict[str, Any] | None = None
    previous_boundary_id: int | None = None
    caused_downstream_stale: bool = False
    downstream_stale: bool = False
    created_at: str | None = None
    updated_at: str | None = None


class NavigationBoundaryArchiveRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=256)


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
    source_summary_json: dict[str, Any] | None = None
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
    source_trace_json: dict[str, Any] | None = None


class NavigationGeometryDraftValidateRequest(BaseModel):
    draft_type_code: str = Field(max_length=64)
    channel_id: int | None = None
    geometry_json: dict[str, Any]


class NavigationGeometryDraftValidationIssueResponse(BaseModel):
    issue_code: str
    severity_code: str
    message: str
    suggestion: str | None = None
    geometry_json: dict[str, Any] | None = None


class NavigationGeometryDraftValidationResponse(BaseModel):
    valid: bool
    publishable: bool
    quality_code: str
    issue_count: int
    error_count: int
    warning_count: int
    length_m: float | None = None
    area_m2: float | None = None
    point_count: int = 0
    ring_count: int = 0
    bbox: dict[str, float | None] = Field(default_factory=dict)
    issues: list[NavigationGeometryDraftValidationIssueResponse] = Field(default_factory=list)


class NavigationBoundaryDraftOperationRequest(BaseModel):
    operation_code: str = Field(max_length=64)
    part_index: int | None = None
    operation_geometry_json: dict[str, Any] | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class NavigationBoundaryDraftOperationResponse(BaseModel):
    draft: NavigationGeometryDraftResponse
    validation: NavigationGeometryDraftValidationResponse
    message: str


class NavigationSnapReferencePointResponse(BaseModel):
    id: str
    ref_type_code: str
    ref_id: int | None = None
    name: str | None = None
    longitude: float
    latitude: float
    display_longitude: float | None = None
    display_latitude: float | None = None
    priority: int = 0
    properties: dict[str, Any] = Field(default_factory=dict)


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
