"""Quality-governance service boundary for vessel routes."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vessel import VesselDataQualityIssue
from app.modules.vessel.schemas import (
    PageResponse,
    VesselQualityIssueBatchRecheckRequest,
    VesselQualityIssueBatchRecheckResponse,
    VesselQualityIssueGlobalQuery,
    VesselQualityIssueListItemResponse,
    VesselQualityIssueQuery,
    VesselQualityIssueRecheckResponse,
    VesselQualityIssueResponse,
)
from app.modules.vessel.service import VesselService


class VesselQualityService:
    """Facade for quality queues, issue lists, and recheck entrypoints."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._facade = VesselService(db)

    async def list_quality_issue_queue(
        self,
        query: VesselQualityIssueGlobalQuery,
    ) -> PageResponse[VesselQualityIssueListItemResponse]:
        return await self._facade.list_quality_issue_queue(query)

    async def list_quality_issues(
        self,
        vessel_id: int,
        query: VesselQualityIssueQuery,
    ) -> PageResponse[VesselQualityIssueResponse]:
        return await self._facade.list_quality_issues(vessel_id, query)

    async def recheck_quality_issue(
        self,
        issue_id: int,
        *,
        operator_id: int | None = None,
        commit: bool = True,
        close_tasks: bool = True,
    ) -> VesselQualityIssueRecheckResponse:
        return await self._facade.recheck_quality_issue(
            issue_id,
            operator_id=operator_id,
            commit=commit,
            close_tasks=close_tasks,
        )

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
                await self._facade.recheck_quality_issue(
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
