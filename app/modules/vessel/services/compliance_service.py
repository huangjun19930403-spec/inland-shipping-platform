"""Compliance-domain service boundary for vessel routes."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.vessel.governance_service import VesselGovernanceService
from app.modules.vessel.service import VesselService
from app.modules.vessel.services.compliance_rules import COMPLIANCE_RISK_ACTION_RULES
from app.modules.vessel.schemas import (
    PageResponse,
    VesselCertificateRequirementRulePayload,
    VesselCertificateRequirementRuleResponse,
    VesselCertificateRequirementRuleUpdateRequest,
    VesselComplianceRiskQuery,
    VesselComplianceRiskResponse,
    VesselComplianceRuleQuery,
    VesselRiskReviewRequest,
    VesselRiskReviewResponse,
    VesselRiskSignalResponse,
    VesselRiskSignalUpdateRequest,
)


class VesselComplianceService:
    """Facade for compliance risks, rule coverage, reviews, and actions."""

    risk_action_rules = COMPLIANCE_RISK_ACTION_RULES

    def __init__(self, db: AsyncSession):
        self._vessel_facade = VesselService(db)
        self._governance_facade = VesselGovernanceService(db)

    async def list_compliance_risks(self, query: VesselComplianceRiskQuery) -> PageResponse[VesselRiskSignalResponse]:
        return await self._vessel_facade.list_compliance_risks(query)

    async def list_compliance_rules(self, query: VesselComplianceRuleQuery) -> PageResponse[VesselCertificateRequirementRuleResponse]:
        return await self._vessel_facade.list_compliance_rules(query)

    async def create_compliance_rule(self, payload: VesselCertificateRequirementRulePayload) -> VesselCertificateRequirementRuleResponse:
        return await self._vessel_facade.create_compliance_rule(payload)

    async def update_compliance_rule(
        self,
        rule_id: int,
        payload: VesselCertificateRequirementRuleUpdateRequest,
    ) -> VesselCertificateRequirementRuleResponse:
        return await self._vessel_facade.update_compliance_rule(rule_id, payload)

    async def void_compliance_rule(self, rule_id: int, payload: object) -> VesselCertificateRequirementRuleResponse:
        return await self._vessel_facade.void_compliance_rule(rule_id, payload)

    async def get_compliance_risk(self, vessel_id: int) -> VesselComplianceRiskResponse:
        return await self._vessel_facade.get_compliance_risk(vessel_id)

    async def refresh_compliance_risk(self, vessel_id: int, *, operator_id: int | None = None) -> VesselComplianceRiskResponse:
        return await self._vessel_facade.refresh_compliance_risk(vessel_id, operator_id=operator_id)

    async def update_risk_signal(
        self,
        vessel_id: int,
        signal_id: int,
        payload: VesselRiskSignalUpdateRequest,
        *,
        operator_id: int | None = None,
    ) -> VesselRiskSignalResponse:
        return await self._vessel_facade.update_risk_signal(vessel_id, signal_id, payload, operator_id=operator_id)

    async def create_risk_review(
        self,
        vessel_id: int,
        payload: VesselRiskReviewRequest,
        *,
        operator_id: int | None = None,
    ) -> VesselRiskReviewResponse:
        return await self._governance_facade.create_risk_review(vessel_id, payload, operator_id=operator_id)
