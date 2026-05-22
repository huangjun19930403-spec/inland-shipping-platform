"""AIS position, city situation, and spatial observation workflows."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.vessel.ais.methods import VesselAisMixin
from app.modules.vessel.asset.profile_methods import VesselAssetMixin
from app.modules.vessel.compliance.methods import VesselComplianceMixin
from app.modules.vessel.quality.methods import VesselQualityMixin
from app.modules.vessel.relation.methods import VesselRelationMixin
from app.modules.vessel.shared.methods import VesselCoreMixin
from app.modules.vessel.spatial_service import VesselSpatialAnalysisService


class VesselAisService(
    VesselCoreMixin,
    VesselAssetMixin,
    VesselRelationMixin,
    VesselQualityMixin,
    VesselComplianceMixin,
    VesselAisMixin,
):
    """AIS position, city situation, and spatial observation workflows."""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self._spatial = VesselSpatialAnalysisService(db)

    async def node_situation(self, query: VesselAisNodeSituationQuery) -> VesselAisNodeSituationResponse:
        return await self._spatial.node_situation(query)

    async def node_vessels(self, query: VesselAisNodeVesselsQuery) -> VesselAisNodeVesselsResponse:
        return await self._spatial.node_vessels(query)

    async def route_situation(self, query: VesselAisRouteSituationQuery) -> VesselAisRouteSituationResponse:
        return await self._spatial.route_situation(query)

    async def route_segment_vessels(self, query: VesselAisRouteSegmentVesselsQuery) -> VesselAisRouteSegmentVesselsResponse:
        return await self._spatial.route_segment_vessels(query)

    async def navigation_constraints(self, query: VesselNavigationConstraintQuery) -> VesselNavigationConstraintResponse:
        return await self._spatial.navigation_constraints(query)

    async def spatial_snapshot(self, snapshot_id: str) -> VesselSpatialSnapshotResponse:
        return await self._spatial.spatial_snapshot(snapshot_id)


__all__ = ["VesselAisService"]
