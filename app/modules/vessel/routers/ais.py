"""Vessel ais routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.system import SysUser
from app.modules.vessel.schemas import (
    PageResponse,
    VesselAisCitySituationQuery,
    VesselAisCityVesselsQuery,
    VesselAisCityBoundaryQuery,
    VesselAisMonitorQuery,
    VesselAisNodeSituationQuery,
    VesselAisNodeSituationResponse,
    VesselAisNodeVesselsQuery,
    VesselAisNodeVesselsResponse,
    VesselAisRouteSegmentVesselsQuery,
    VesselAisRouteSegmentVesselsResponse,
    VesselAisRouteSituationQuery,
    VesselAisRouteSituationResponse,
    VesselAisCityBoundaryResponse,
    VesselAisSituationCardResponse,
    VesselAisSnapshotQuery,
    VesselAisSnapshotResponse,
    VesselAisUnmatchedMmsiResponse,
    VesselAffiliationEvidenceCreateRequest,
    VesselAffiliationEvidenceResponse,
    VesselAffiliationEvidenceUpdateRequest,
    VesselAssetPageResponse,
    VesselAssetListItemResponse,
    VesselAssetListQuery,
    VesselAssetSummaryResponse,
    VesselBuildInfoResponse,
    VesselBuildInfoUpsertRequest,
    VesselCapacityResponse,
    VesselCapacityUpsertRequest,
    VesselCertificateCreateRequest,
    VesselCertificateFileResponse,
    VesselCertificateImageRecognitionConfirmRequest,
    VesselCertificateImageRecognitionCreateRequest,
    VesselCertificateImageRecognitionResponse,
    VesselCertificateLedgerItemResponse,
    VesselCertificateRequirementRulePayload,
    VesselCertificateRequirementRuleResponse,
    VesselCertificateRequirementRuleUpdateRequest,
    VesselCertificateResponse,
    VesselCertificateUpdateRequest,
    VesselChangeEventResponse,
    VesselContactCreateRequest,
    VesselContactReplaceRequest,
    VesselContactResponse,
    VesselContactUpdateRequest,
    VesselCreateRequest,
    VesselCrewCreateRequest,
    VesselCrewReplaceRequest,
    VesselCrewResponse,
    VesselCrewUpdateRequest,
    VesselBusinessSituationCardResponse,
    VesselCandidateAnalysisAnnotationRequest,
    VesselCandidateAnalysisAnnotationResponse,
    VesselCandidateAnalysisCreateRequest,
    VesselCandidateAnalysisListQuery,
    VesselCandidateAnalysisResponse,
    VesselComplianceRiskQuery,
    VesselComplianceRiskResponse,
    VesselComplianceRuleQuery,
    VesselControllerEvidenceCreateRequest,
    VesselControllerEvidenceResponse,
    VesselControllerEvidenceUpdateRequest,
    VesselBlacklistSignalCreateRequest,
    VesselBlacklistSignalGlobalQuery,
    VesselBlacklistSignalListItemResponse,
    VesselBlacklistSignalResponse,
    VesselBlacklistSignalUpdateRequest,
    VesselAffiliationConclusionResponse,
    VesselControllerConclusionResponse,
    VesselDetailResponse,
    VesselGovernanceDashboardResponse,
    VesselGovernanceTaskActionRequest,
    VesselGovernanceTaskQuery,
    VesselGovernanceTaskResponse,
    VesselGovernanceTaskSyncResponse,
    VesselListItemResponse,
    VesselListQuery,
    VesselNavigationConstraintQuery,
    VesselNavigationConstraintResponse,
    VesselOperatorCreateRequest,
    VesselOperatorReplaceRequest,
    VesselOperatorResponse,
    VesselOperatorUpdateRequest,
    VesselOwnerDocumentImageRecognitionConfirmRequest,
    VesselOwnerDocumentImageRecognitionResponse,
    VesselOwnerDocumentResponse,
    VesselOwnerCreateRequest,
    VesselOwnerReplaceRequest,
    VesselOwnerResponse,
    VesselOwnerTransferRequest,
    VesselOwnerUpdateRequest,
    VesselPersonCertificateFileResponse,
    VesselPersonCertificateImageRecognitionConfirmRequest,
    VesselPersonCertificateImageRecognitionCreateRequest,
    VesselPersonCertificateImageRecognitionResponse,
    VesselPersonCertificateReplaceRequest,
    VesselPersonCertificateResponse,
    VesselPersonCertificateUpdateRequest,
    VesselPositionCitySituationQuery,
    VesselPositionCitySituationResponse,
    VesselPositionCityVesselsQuery,
    VesselPositionCityVesselsResponse,
    VesselPositionMonitorItemResponse,
    VesselPositionMonitorQuery,
    VesselPositionMonitorResponse,
    VesselProfileCardEvidenceQuery,
    VesselProfileCardEvidenceResponse,
    VesselProfileCardResponse,
    VesselProfileResponse,
    VesselProfileUpdateRequest,
    VesselQualityIssueGlobalQuery,
    VesselQualityIssueListItemResponse,
    VesselQualityIssueQuery,
    VesselQualityIssueRecheckResponse,
    VesselQualityIssueResponse,
    VesselRelationConclusionSummaryResponse,
    VesselRecognitionHistoryQuery,
    VesselRecognitionAdoptionRequest,
    VesselRecognitionFieldDiffResponse,
    VesselRecognitionQueueItemResponse,
    VesselRecognitionQueueQuery,
    VesselRegistrationResponse,
    VesselRegistrationUpsertRequest,
    VesselRelationUpdateMeta,
    VesselSetPrimaryRequest,
    VesselVoidRequest,
    VesselRiskSignalResponse,
    VesselRiskSignalUpdateRequest,
    VesselRiskReviewRequest,
    VesselRiskReviewResponse,
    VesselSpatialSnapshotResponse,
)
from app.modules.vessel.candidate_service import VesselCandidateAnalysisService
from app.modules.vessel.governance_service import VesselGovernanceService
from app.modules.vessel.ais.service import VesselAisService

router = APIRouter()


def _operator_id(current_user: SysUser) -> int | None:
    return int(current_user.id) if current_user is not None else None




@router.get("/ais/city-situation", response_model=VesselPositionCitySituationResponse)
async def get_vessel_ais_city_situation(
    query: VesselAisCitySituationQuery = Depends(),
    force_refresh: bool = Query(False, include_in_schema=False),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    internal_query = query.to_internal_query()
    object.__setattr__(internal_query, "force_refresh", force_refresh)
    return await VesselAisService(db).position_city_situation(internal_query)


@router.get("/ais/positions", response_model=VesselPositionMonitorResponse)
async def get_vessel_ais_positions(
    query: VesselAisMonitorQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAisService(db).position_monitor(query.to_internal_query())


@router.get("/ais/city-vessels", response_model=VesselPositionCityVesselsResponse)
async def get_vessel_ais_city_vessels(
    query: VesselAisCityVesselsQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAisService(db).position_city_vessels(query.to_internal_query())


@router.get("/ais/city-boundaries", response_model=VesselAisCityBoundaryResponse)
async def get_vessel_ais_city_boundaries(
    query: VesselAisCityBoundaryQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAisService(db).ais_city_boundaries(query)


@router.get("/ais/node-situation", response_model=VesselAisNodeSituationResponse)
async def get_vessel_ais_node_situation(
    query: VesselAisNodeSituationQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAisService(db).node_situation(query)


@router.get("/ais/node-vessels", response_model=VesselAisNodeVesselsResponse)
async def get_vessel_ais_node_vessels(
    query: VesselAisNodeVesselsQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAisService(db).node_vessels(query)


@router.get("/ais/route-situation", response_model=VesselAisRouteSituationResponse)
async def get_vessel_ais_route_situation(
    query: VesselAisRouteSituationQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAisService(db).route_situation(query)


@router.get("/ais/route-segment-vessels", response_model=VesselAisRouteSegmentVesselsResponse)
async def get_vessel_ais_route_segment_vessels(
    query: VesselAisRouteSegmentVesselsQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAisService(db).route_segment_vessels(query)


@router.get("/navigation-constraints", response_model=VesselNavigationConstraintResponse)
async def get_vessel_navigation_constraints(
    query: VesselNavigationConstraintQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAisService(db).navigation_constraints(query)


@router.get("/ais/spatial-snapshots/{snapshot_id}", response_model=VesselSpatialSnapshotResponse)
async def get_vessel_ais_spatial_snapshot(
    snapshot_id: str,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAisService(db).spatial_snapshot(snapshot_id)


@router.get("/ais/snapshots/{snapshot_id}", response_model=VesselAisSnapshotResponse)
async def get_vessel_ais_snapshot(
    snapshot_id: str,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAisService(db).ais_snapshot(snapshot_id)


@router.get("/ais/unmatched-mmsi", response_model=PageResponse[VesselAisUnmatchedMmsiResponse])
async def list_vessel_ais_unmatched_mmsi(
    query: VesselAisSnapshotQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAisService(db).list_unmatched_mmsi(query)


@router.get("/ais/vessels/{vessel_id}/situation-card", response_model=VesselAisSituationCardResponse)
async def get_vessel_ais_situation_card(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAisService(db).position_ais_situation_card(vessel_id)


@router.get("/position-monitor", response_model=VesselPositionMonitorResponse)
async def monitor_vessel_positions(
    query: VesselPositionMonitorQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAisService(db).position_monitor(query)


@router.get("/position-monitor/city-situation", response_model=VesselPositionCitySituationResponse)
async def monitor_vessel_city_situation(
    query: VesselPositionCitySituationQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAisService(db).position_city_situation(query)


@router.get("/position-monitor/city-vessels", response_model=VesselPositionCityVesselsResponse)
async def monitor_vessel_city_vessels(
    query: VesselPositionCityVesselsQuery = Depends(),
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAisService(db).position_city_vessels(query)


@router.get("/position-monitor/vessels/{vessel_id}/situation-card", response_model=VesselBusinessSituationCardResponse)
async def monitor_vessel_situation_card(
    vessel_id: int,
    current_user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = current_user
    return await VesselAisService(db).position_business_card(vessel_id)
