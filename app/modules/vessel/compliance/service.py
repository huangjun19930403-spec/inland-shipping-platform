"""Compliance-domain service boundary for vessel routes."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.vessel.governance_service import VesselGovernanceService
from app.modules.vessel.schemas import VesselRiskReviewRequest, VesselRiskReviewResponse
from app.modules.vessel.ais.methods import VesselAisMixin
from app.modules.vessel.asset.profile_methods import VesselAssetMixin
from app.modules.vessel.certificate.methods import VesselCertificateMixin
from app.modules.vessel.compliance.methods import VesselComplianceMixin
from app.modules.vessel.quality.methods import VesselQualityMixin
from app.modules.vessel.relation.methods import VesselRelationMixin
from app.modules.vessel.services.compliance_rules import COMPLIANCE_RISK_ACTION_RULES
from app.modules.vessel.shared.methods import VesselCoreMixin


class VesselComplianceService(
    VesselCoreMixin,
    VesselAssetMixin,
    VesselCertificateMixin,
    VesselRelationMixin,
    VesselQualityMixin,
    VesselComplianceMixin,
    VesselAisMixin,
):
    """Compliance risk, rule coverage, review, and action workflows."""

    risk_action_rules = COMPLIANCE_RISK_ACTION_RULES

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self._governance_service = VesselGovernanceService(db)

    async def create_risk_review(
        self,
        vessel_id: int,
        payload: VesselRiskReviewRequest,
        *,
        operator_id: int | None = None,
    ) -> VesselRiskReviewResponse:
        return await self._governance_service.create_risk_review(vessel_id, payload, operator_id=operator_id)


__all__ = ["VesselComplianceService"]
