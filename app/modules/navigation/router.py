from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, require_permission
from app.modules.navigation.annotation_service import NavigationAnnotationTaskService
from app.modules.navigation.diagnostic_service import NavigationDiagnosticService
from app.modules.navigation.map_layer_service import NavigationMapLayerService
from app.modules.navigation.production_service import NavigationProductionService
from app.modules.navigation.routing_service import NavigationRoutingEngineService
from app.modules.navigation.schemas import (
    NavigationAnnotationSuggestionResponse,
    NavigationAnnotationTaskBatchCreateResponse,
    NavigationAnnotationTaskListResponse,
    NavigationAnnotationTaskResolveRequest,
    NavigationAnnotationTaskResponse,
    NavigationBoundaryArchiveRequest,
    NavigationBoundaryListItemResponse,
    NavigationCenterlineListItemResponse,
    NavigationChannelDiagnosticResponse,
    NavigationChannelWaterBodyMatchListResponse,
    NavigationDiagnosticsRunResponse,
    NavigationBoundaryDraftOperationRequest,
    NavigationBoundaryDraftOperationResponse,
    NavigationCenterlineSegmentGenerateRequest,
    NavigationCenterlineSegmentGenerateResponse,
    NavigationCenterlineSegmentListResponse,
    NavigationCenterlineSegmentPublishRequest,
    NavigationCenterlineSegmentPublishResponse,
    NavigationCenterlineSegmentResponse,
    NavigationCenterlineSegmentSplitRequest,
    NavigationCenterlineSegmentUpdateRequest,
    NavigationGeometryDraftCreateRequest,
    NavigationGeometryDraftResponse,
    NavigationGeometryDraftUpdateRequest,
    NavigationGeometryDraftValidateRequest,
    NavigationGeometryDraftValidationResponse,
    NavigationGraphActivateResponse,
    NavigationGraphBuildRequest,
    NavigationGraphBuildResponse,
    NavigationGraphIssueEdgeListResponse,
    NavigationGraphVersionListItemResponse,
    NavigationMapLayerResponse,
    NavigationOsmImportRequest,
    NavigationOsmImportResponse,
    NavigationChannelPipelineResponse,
    NavigationProductionChannelResponse,
    NavigationProductionSummaryResponse,
    NavigationRouteGenerateRequest,
    NavigationRouteGenerateResponse,
    NavigationSnapReferencePointResponse,
    NavigationWaterBodyListItemResponse,
    NavigationWaterBodyListResponse,
    NavigationWaterBodyCandidateListResponse,
    NavigationWaterBodyMatchCreateRequest,
    NavigationWaterBodyNameUpdateRequest,
    NavigationWaterAreaListResponse,
    NavigationCandidateConfirmRequest,
    NavigationCandidateGenerateRequest,
    NavigationCandidateGenerateResponse,
    NavigationWaterAreaSummaryResponse,
    NavigationWorkbenchSummaryResponse,
    NavigationProductionWorkspaceResponse,
)
from app.modules.navigation.services.centerline_segments import NavigationCenterlineSegmentService
from app.modules.navigation.workbench_service import NavigationWorkbenchService

router = APIRouter()


@router.get("/production/summary", response_model=NavigationProductionSummaryResponse)
async def get_navigation_production_summary(
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationProductionService(db).summary()


@router.get("/production/channels", response_model=list[NavigationProductionChannelResponse])
async def list_navigation_production_channels(
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationProductionService(db).channels()


@router.get("/channels/{channel_id}/pipeline", response_model=NavigationChannelPipelineResponse)
async def get_navigation_channel_pipeline(
    channel_id: int,
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationProductionService(db).pipeline(channel_id)


@router.get("/channels/{channel_id}/production-workspace", response_model=NavigationProductionWorkspaceResponse)
async def get_navigation_channel_production_workspace(
    channel_id: int,
    step: str = "boundary",
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationProductionService(db).production_workspace(channel_id, step=step)


@router.get("/channels/{channel_id}/diagnostics", response_model=NavigationChannelDiagnosticResponse)
async def get_navigation_channel_diagnostics(
    channel_id: int,
    include_spatial: bool = False,
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationDiagnosticService(db).channel_diagnostics(channel_id, include_spatial=include_spatial)


@router.get("/channels/{channel_id}/water-body-candidates", response_model=NavigationWaterBodyCandidateListResponse)
async def list_navigation_channel_water_body_candidates(
    channel_id: int,
    limit: int = 80,
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationDiagnosticService(db).water_body_candidates(channel_id, limit=limit)


@router.post(
    "/channels/{channel_id}/water-body-candidates/{water_body_id}/confirm",
    response_model=NavigationChannelWaterBodyMatchListResponse,
)
async def confirm_navigation_channel_water_body_candidate(
    channel_id: int,
    water_body_id: int,
    body: NavigationCandidateConfirmRequest,
    current_user=Depends(require_permission("ROUTE:WRITE")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationDiagnosticService(db).confirm_water_body_candidate(channel_id, water_body_id, body)


@router.post("/diagnostics/run", response_model=NavigationDiagnosticsRunResponse)
async def run_navigation_channel_diagnostics(
    include_spatial: bool = False,
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationDiagnosticService(db).run_diagnostics(include_spatial=include_spatial)


@router.get("/channels/{channel_id}/boundary-candidates", response_model=list[NavigationBoundaryListItemResponse])
async def list_navigation_channel_boundary_candidates(
    channel_id: int,
    limit: int = 120,
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationProductionService(db).boundary_candidates(channel_id=channel_id, limit=limit)


@router.post("/channels/{channel_id}/boundary-candidates/generate", response_model=NavigationCandidateGenerateResponse)
async def generate_navigation_channel_boundary_candidates(
    channel_id: int,
    body: NavigationCandidateGenerateRequest | None = None,
    current_user=Depends(require_permission("ROUTE:WRITE")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationProductionService(db).generate_boundary_candidates(
        channel_id=channel_id,
        body=body or NavigationCandidateGenerateRequest(),
    )


@router.get("/channels/{channel_id}/centerline-candidates", response_model=list[NavigationCenterlineListItemResponse])
async def list_navigation_channel_centerline_candidates(
    channel_id: int,
    limit: int = 120,
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationProductionService(db).centerline_candidates(channel_id=channel_id, limit=limit)


@router.post("/channels/{channel_id}/centerline-candidates/generate", response_model=NavigationCandidateGenerateResponse)
async def generate_navigation_channel_centerline_candidates(
    channel_id: int,
    body: NavigationCandidateGenerateRequest | None = None,
    current_user=Depends(require_permission("ROUTE:WRITE")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationProductionService(db).generate_centerline_candidates(
        channel_id=channel_id,
        body=body or NavigationCandidateGenerateRequest(),
    )


@router.post(
    "/channels/{channel_id}/centerline-segments/generate",
    response_model=NavigationCenterlineSegmentGenerateResponse,
)
async def generate_navigation_channel_centerline_segments(
    channel_id: int,
    body: NavigationCenterlineSegmentGenerateRequest | None = None,
    current_user=Depends(require_permission("ROUTE:WRITE")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationCenterlineSegmentService(db).generate_segments(
        channel_id=channel_id,
        body=body or NavigationCenterlineSegmentGenerateRequest(),
    )


@router.get(
    "/channels/{channel_id}/centerline-segments",
    response_model=NavigationCenterlineSegmentListResponse,
)
async def list_navigation_channel_centerline_segments(
    channel_id: int,
    status_code: str | None = None,
    only_problem: bool = False,
    issue_code: str | None = None,
    limit: int | None = None,
    page: int = 1,
    page_size: int = 50,
    include_geometry: bool = True,
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationCenterlineSegmentService(db).list_segments(
        channel_id=channel_id,
        status_code=status_code,
        only_problem=only_problem,
        issue_code=issue_code,
        limit=limit,
        page=page,
        page_size=page_size,
        include_geometry=include_geometry,
    )


@router.put("/centerline-segments/{segment_id}", response_model=NavigationCenterlineSegmentResponse)
async def update_navigation_centerline_segment(
    segment_id: int,
    body: NavigationCenterlineSegmentUpdateRequest,
    current_user=Depends(require_permission("ROUTE:WRITE")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationCenterlineSegmentService(db).update_segment(segment_id, body)


@router.post("/centerline-segments/{segment_id}/confirm", response_model=NavigationCenterlineSegmentResponse)
async def confirm_navigation_centerline_segment(
    segment_id: int,
    current_user=Depends(require_permission("ROUTE:WRITE")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationCenterlineSegmentService(db).confirm_segment(segment_id)


@router.post("/centerline-segments/{segment_id}/archive", response_model=NavigationCenterlineSegmentListResponse)
async def archive_navigation_centerline_segment(
    segment_id: int,
    current_user=Depends(require_permission("ROUTE:WRITE")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationCenterlineSegmentService(db).archive_segment(segment_id)


@router.post("/centerline-segments/{segment_id}/split", response_model=NavigationCenterlineSegmentListResponse)
async def split_navigation_centerline_segment(
    segment_id: int,
    body: NavigationCenterlineSegmentSplitRequest | None = None,
    current_user=Depends(require_permission("ROUTE:WRITE")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationCenterlineSegmentService(db).split_segment(
        segment_id,
        body or NavigationCenterlineSegmentSplitRequest(),
    )


@router.post("/centerline-segments/{segment_id}/merge-next", response_model=NavigationCenterlineSegmentListResponse)
async def merge_next_navigation_centerline_segment(
    segment_id: int,
    current_user=Depends(require_permission("ROUTE:WRITE")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationCenterlineSegmentService(db).merge_next_segment(segment_id)


@router.post("/centerline-segments/{segment_id}/reverse", response_model=NavigationCenterlineSegmentResponse)
async def reverse_navigation_centerline_segment(
    segment_id: int,
    current_user=Depends(require_permission("ROUTE:WRITE")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationCenterlineSegmentService(db).reverse_segment(segment_id)


@router.post(
    "/channels/{channel_id}/centerline-segments/publish",
    response_model=NavigationCenterlineSegmentPublishResponse,
)
async def publish_navigation_channel_centerline_segments(
    channel_id: int,
    body: NavigationCenterlineSegmentPublishRequest | None = None,
    current_user=Depends(require_permission("ROUTE:WRITE")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationCenterlineSegmentService(db).publish_segments(
        channel_id=channel_id,
        body=body or NavigationCenterlineSegmentPublishRequest(),
    )


@router.get("/channels/{channel_id}/snap-references", response_model=list[NavigationSnapReferencePointResponse])
async def list_navigation_channel_snap_references(
    channel_id: int,
    limit: int = 500,
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).snap_references(channel_id=channel_id, limit=limit)


@router.post("/osm/imports", response_model=NavigationOsmImportResponse)
async def create_navigation_osm_import(
    body: NavigationOsmImportRequest,
    current_user=Depends(require_permission("ROUTE:WRITE")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationProductionService(db).create_osm_import(body)


@router.get("/workbench/summary", response_model=NavigationWorkbenchSummaryResponse)
async def get_navigation_workbench_summary(
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).summary()


@router.get("/water-areas/summary", response_model=NavigationWaterAreaSummaryResponse)
async def get_navigation_water_area_summary(
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).water_area_summary()


@router.get("/water-bodies", response_model=NavigationWaterBodyListResponse)
async def list_navigation_water_bodies(
    keyword: str | None = None,
    channel_id: int | None = None,
    body_role_code: str | None = None,
    dedupe_status_code: str | None = None,
    source_layer_code: str | None = None,
    layer_role_code: str | None = None,
    water_type_code: str | None = None,
    geometry_status_code: str | None = None,
    name_status_code: str | None = None,
    only_matched: bool = False,
    only_unmatched: bool = False,
    include_invalid: bool = False,
    page: int = 1,
    page_size: int = 50,
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).list_water_bodies(
        keyword=keyword,
        channel_id=channel_id,
        body_role_code=body_role_code,
        dedupe_status_code=dedupe_status_code,
        source_layer_code=source_layer_code,
        layer_role_code=layer_role_code,
        water_type_code=water_type_code,
        geometry_status_code=geometry_status_code,
        name_status_code=name_status_code,
        only_matched=only_matched,
        only_unmatched=only_unmatched,
        include_invalid=include_invalid,
        page=page,
        page_size=page_size,
    )


@router.patch("/water-bodies/{water_body_id}/name", response_model=NavigationWaterBodyListItemResponse)
async def update_navigation_water_body_name(
    water_body_id: int,
    body: NavigationWaterBodyNameUpdateRequest,
    current_user=Depends(require_permission("ROUTE:WRITE")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).update_water_body_name(water_body_id=water_body_id, body=body)


@router.get("/water-bodies/{group_key}/features", response_model=NavigationWaterAreaListResponse)
async def list_navigation_water_body_features(
    group_key: str,
    page: int = 1,
    page_size: int = 100,
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).list_water_body_features(
        group_key=group_key,
        page=page,
        page_size=page_size,
    )


@router.get("/water-bodies/{group_key}/map-layers", response_model=NavigationMapLayerResponse)
async def get_navigation_water_body_map_layers(
    group_key: str,
    limit: int = 500,
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).water_body_map_layers(group_key=group_key, limit=limit)


@router.get("/water-areas", response_model=NavigationWaterAreaListResponse)
async def list_navigation_water_areas(
    keyword: str | None = None,
    channel_id: int | None = None,
    source_layer_name: str | None = None,
    source_layer_code: str | None = None,
    layer_role_code: str | None = None,
    water_type_code: str | None = None,
    geometry_status_code: str | None = None,
    only_unmatched: bool = False,
    include_invalid: bool = False,
    sort: str = "layer_order",
    page: int = 1,
    page_size: int = 50,
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).list_water_areas(
        keyword=keyword,
        channel_id=channel_id,
        source_layer_name=source_layer_name,
        source_layer_code=source_layer_code,
        layer_role_code=layer_role_code,
        water_type_code=water_type_code,
        geometry_status_code=geometry_status_code,
        only_unmatched=only_unmatched,
        include_invalid=include_invalid,
        sort=sort,
        page=page,
        page_size=page_size,
    )


@router.get("/raw-water-areas/diagnostics", response_model=NavigationWaterAreaListResponse)
async def list_navigation_raw_water_area_diagnostics(
    keyword: str | None = None,
    source_layer_code: str | None = None,
    layer_role_code: str | None = None,
    water_type_code: str | None = None,
    geometry_status_code: str | None = None,
    page: int = 1,
    page_size: int = 50,
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).list_water_areas(
        keyword=keyword,
        source_layer_code=source_layer_code,
        layer_role_code=layer_role_code,
        water_type_code=water_type_code,
        geometry_status_code=geometry_status_code,
        include_invalid=True,
        page=page,
        page_size=page_size,
    )


@router.get("/channels/{channel_id}/water-body-matches", response_model=NavigationChannelWaterBodyMatchListResponse)
async def list_navigation_channel_water_body_matches(
    channel_id: int,
    limit: int = 500,
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).list_water_body_matches(channel_id=channel_id, limit=limit)


@router.post("/channels/{channel_id}/water-body-matches", response_model=NavigationChannelWaterBodyMatchListResponse)
async def create_navigation_channel_water_body_match(
    channel_id: int,
    body: NavigationWaterBodyMatchCreateRequest,
    current_user=Depends(require_permission("ROUTE:WRITE")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).create_water_body_match(channel_id=channel_id, body=body)


@router.delete("/channels/{channel_id}/water-body-matches/{match_id}", response_model=NavigationChannelWaterBodyMatchListResponse)
async def remove_navigation_channel_water_body_match(
    channel_id: int,
    match_id: int,
    current_user=Depends(require_permission("ROUTE:WRITE")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).remove_water_body_match(channel_id=channel_id, match_id=match_id)


@router.get("/centerlines", response_model=list[NavigationCenterlineListItemResponse])
async def list_navigation_centerlines(
    channel_id: int | None = None,
    limit: int = 50,
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).list_centerlines(channel_id=channel_id, limit=limit)


@router.get("/boundaries", response_model=list[NavigationBoundaryListItemResponse])
async def list_navigation_boundaries(
    channel_id: int | None = None,
    limit: int = 50,
    include_archived: bool = False,
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).list_boundaries(
        channel_id=channel_id,
        limit=limit,
        include_archived=include_archived,
    )


@router.post("/channel-boundaries/{boundary_id}/archive", response_model=NavigationBoundaryListItemResponse)
async def archive_navigation_channel_boundary(
    boundary_id: int,
    body: NavigationBoundaryArchiveRequest | None = None,
    current_user=Depends(require_permission("ROUTE:WRITE")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).archive_boundary(
        boundary_id,
        reason=(body or NavigationBoundaryArchiveRequest()).reason,
    )


@router.get("/graph-versions", response_model=list[NavigationGraphVersionListItemResponse])
async def list_navigation_graph_versions(
    limit: int = 30,
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).list_graph_versions(limit=limit)


@router.get("/graph-versions/{graph_version_id}/issue-edges", response_model=NavigationGraphIssueEdgeListResponse)
async def list_navigation_graph_issue_edges(
    graph_version_id: int,
    issue_code: str | None = None,
    channel_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
    include_geometry: bool = True,
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).list_graph_issue_edges(
        graph_version_id,
        issue_code=issue_code,
        channel_id=channel_id,
        page=page,
        page_size=page_size,
        include_geometry=include_geometry,
    )


@router.get("/geometry-drafts", response_model=list[NavigationGeometryDraftResponse])
async def list_navigation_geometry_drafts(
    status_code: str | None = None,
    channel_id: int | None = None,
    limit: int = 50,
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).list_geometry_drafts(
        status_code=status_code,
        channel_id=channel_id,
        limit=limit,
    )


@router.post("/geometry-drafts/validate", response_model=NavigationGeometryDraftValidationResponse)
async def validate_navigation_geometry_draft(
    body: NavigationGeometryDraftValidateRequest,
    current_user=Depends(require_permission("ROUTE:READ")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).validate_geometry_draft(body)


@router.post("/geometry-drafts", response_model=NavigationGeometryDraftResponse)
async def create_navigation_geometry_draft(
    body: NavigationGeometryDraftCreateRequest,
    current_user=Depends(require_permission("ROUTE:WRITE")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).create_geometry_draft(
        body,
        created_by=getattr(current_user, "id", None),
    )


@router.patch("/geometry-drafts/{draft_id}", response_model=NavigationGeometryDraftResponse)
async def update_navigation_geometry_draft(
    draft_id: int,
    body: NavigationGeometryDraftUpdateRequest,
    current_user=Depends(require_permission("ROUTE:WRITE")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).update_geometry_draft(draft_id, body)


@router.post("/geometry-drafts/{draft_id}/publish", response_model=NavigationGeometryDraftResponse)
async def publish_navigation_geometry_draft(
    draft_id: int,
    current_user=Depends(require_permission("ROUTE:WRITE")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).publish_geometry_draft(
        draft_id,
        published_by=getattr(current_user, "id", None),
    )


@router.post("/geometry-drafts/{draft_id}/boundary-ops", response_model=NavigationBoundaryDraftOperationResponse)
async def apply_navigation_boundary_draft_operation(
    draft_id: int,
    body: NavigationBoundaryDraftOperationRequest,
    current_user=Depends(require_permission("ROUTE:WRITE")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).apply_boundary_draft_operation(draft_id, body)


@router.delete("/geometry-drafts/{draft_id}", response_model=NavigationGeometryDraftResponse)
async def archive_navigation_geometry_draft(
    draft_id: int,
    current_user=Depends(require_permission("ROUTE:WRITE")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).archive_geometry_draft(draft_id)


@router.post("/graph-versions/build", response_model=NavigationGraphBuildResponse)
async def build_navigation_graph_version(
    body: NavigationGraphBuildRequest,
    current_user=Depends(require_permission("ROUTE:WRITE")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).build_graph_version(
        body,
        created_by=getattr(current_user, "id", None),
    )


@router.post("/graph-versions/{graph_version_id}/activate", response_model=NavigationGraphActivateResponse)
async def activate_navigation_graph_version(
    graph_version_id: int,
    current_user=Depends(require_permission("ROUTE:WRITE")),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationWorkbenchService(db).activate_graph_version(graph_version_id)


@router.post("/routes/generate", response_model=NavigationRouteGenerateResponse)
async def generate_navigation_route(
    body: NavigationRouteGenerateRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationRoutingEngineService(db).generate_route(
        body,
        created_by=getattr(current_user, "id", None),
    )


@router.get("/map-layers", response_model=NavigationMapLayerResponse)
async def get_navigation_map_layers(
    channel_id: int | None = None,
    water_area_ids: str | None = None,
    min_lng: float | None = None,
    min_lat: float | None = None,
    max_lng: float | None = None,
    max_lat: float | None = None,
    route_result_id: int | None = None,
    include_water_area: bool = True,
    include_boundary: bool = True,
    include_centerline: bool = True,
    include_centerline_segments: bool = False,
    include_graph_edge: bool = True,
    limit: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await NavigationMapLayerService(db).get_layers(
        min_lng=min_lng,
        min_lat=min_lat,
        max_lng=max_lng,
        max_lat=max_lat,
        channel_id=channel_id,
        water_area_ids=_parse_id_list(water_area_ids),
        route_result_id=route_result_id,
        include_water_area=include_water_area,
        include_boundary=include_boundary,
        include_centerline=include_centerline,
        include_centerline_segments=include_centerline_segments,
        include_graph_edge=include_graph_edge,
        limit=limit,
    )


def _parse_id_list(value: str | None) -> list[int] | None:
    if not value:
        return None
    output: list[int] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            output.append(int(item))
        except ValueError:
            continue
    return output or None


@router.get("/annotation-tasks", response_model=NavigationAnnotationTaskListResponse)
async def list_navigation_annotation_tasks(
    status_code: str | None = None,
    task_type_code: str | None = None,
    target_type_code: str | None = None,
    channel_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
):
    return await NavigationAnnotationTaskService(db).list_tasks(
        status_code=status_code,
        task_type_code=task_type_code,
        target_type_code=target_type_code,
        channel_id=channel_id,
        page=page,
        page_size=page_size,
    )


@router.post("/annotation-tasks/from-route-result/{route_result_id}", response_model=NavigationAnnotationTaskBatchCreateResponse)
async def create_navigation_annotation_tasks_from_route_result(
    route_result_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationAnnotationTaskService(db).create_from_route_result(
        route_result_id,
        created_by=getattr(current_user, "id", None),
    )


@router.post("/annotation-tasks/from-graph-version/{graph_version_id}", response_model=NavigationAnnotationTaskBatchCreateResponse)
async def create_navigation_annotation_tasks_from_graph_version(
    graph_version_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationAnnotationTaskService(db).create_from_graph_version(
        graph_version_id,
        created_by=getattr(current_user, "id", None),
    )


@router.post("/annotation-tasks/from-centerlines", response_model=NavigationAnnotationTaskBatchCreateResponse)
async def create_navigation_annotation_tasks_from_centerlines(
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationAnnotationTaskService(db).create_from_centerline_quality(
        created_by=getattr(current_user, "id", None),
    )


@router.post("/annotation-tasks/from-diagnostics", response_model=NavigationAnnotationTaskBatchCreateResponse)
async def create_navigation_annotation_tasks_from_diagnostics(
    channel_id: int | None = None,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationDiagnosticService(db).create_annotation_tasks_from_diagnostics(
        channel_id=channel_id,
        created_by=getattr(current_user, "id", None),
    )


@router.post("/annotation-tasks/{task_id}/suggestion", response_model=NavigationAnnotationSuggestionResponse)
async def generate_navigation_annotation_task_suggestion(
    task_id: int,
    db: AsyncSession = Depends(get_db),
):
    return await NavigationAnnotationTaskService(db).generate_suggestion(task_id)


@router.post("/annotation-tasks/{task_id}/resolve", response_model=NavigationAnnotationTaskResponse)
async def resolve_navigation_annotation_task(
    task_id: int,
    body: NavigationAnnotationTaskResolveRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await NavigationAnnotationTaskService(db).resolve_task(
        task_id,
        body,
        reviewed_by=getattr(current_user, "id", None),
    )


@router.get("/annotation-tasks/{task_id}", response_model=NavigationAnnotationTaskResponse)
async def get_navigation_annotation_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
):
    return await NavigationAnnotationTaskService(db).get_task(task_id)
