"""Quality-governance service boundary for vessel routes."""

from __future__ import annotations

from sqlalchemy import select

from app.models.vessel import VesselDataQualityIssue
from app.modules.vessel.schemas import (
    VesselQualityIssueBatchRecheckRequest,
    VesselQualityIssueBatchRecheckResponse,
    VesselQualityIssueRecheckResponse,
)
from app.modules.vessel.ais.methods import VesselAisMixin
from app.modules.vessel.asset.profile_methods import VesselAssetMixin
from app.modules.vessel.certificate.methods import VesselCertificateMixin
from app.modules.vessel.compliance.methods import VesselComplianceMixin
from app.modules.vessel.quality.methods import VesselQualityMixin
from app.modules.vessel.relation.methods import VesselRelationMixin
from app.modules.vessel.shared.methods import VesselCoreMixin


class VesselQualityService(
    VesselCoreMixin,
    VesselAssetMixin,
    VesselCertificateMixin,
    VesselRelationMixin,
    VesselQualityMixin,
    VesselComplianceMixin,
    VesselAisMixin,
):
    """Quality queues, issue lists, scoring, and recheck workflows."""

    async def recheck_quality_issues_batch(
        self,
        payload: VesselQualityIssueBatchRecheckRequest,
        *,
        operator_id: int | None = None,
    ) -> VesselQualityIssueBatchRecheckResponse:
        issue_ids = [int(item) for item in payload.issue_ids if item]
        if not issue_ids:
            stmt = select(VesselDataQualityIssue.id)
            if payload.vessel_id:
                stmt = stmt.where(VesselDataQualityIssue.vessel_profile_id == payload.vessel_id)
            if payload.status_code:
                stmt = stmt.where(VesselDataQualityIssue.status_code == payload.status_code)
            issue_ids = list((await self.db.scalars(stmt.order_by(VesselDataQualityIssue.updated_at.desc()).limit(200))).all())

        results: list[VesselQualityIssueRecheckResponse] = []
        for issue_id in issue_ids[:200]:
            results.append(
                await self.recheck_quality_issue(
                    int(issue_id),
                    operator_id=operator_id,
                    commit=False,
                    close_tasks=True,
                )
            )
        await self.db.commit()
        passed = sum(1 for item in results if item.recheck_status_code == "PASSED")
        resolved = sum(1 for item in results if item.resolved)
        return VesselQualityIssueBatchRecheckResponse(
            total_count=len(results),
            passed_count=passed,
            failed_count=len(results) - passed,
            resolved_count=resolved,
            results=results,
        )


__all__ = ["VesselQualityService"]
