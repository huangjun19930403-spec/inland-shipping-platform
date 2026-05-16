"""Celery entrypoints for production vessel-freight fit precomputation."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from threading import Thread
from typing import Any

from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.freight import Freight
from app.models.vessel import (
    VesselAisSnapshot,
    VesselCandidateAnalysis,
    VesselCandidateAnalysisAnnotation,
    VesselCandidateAnalysisItem,
)
from app.modules.vessel.candidate_service import VesselCandidateAnalysisService
from app.modules.vessel.schemas import (
    VesselCandidateAnalysisCreateRequest,
    VesselCandidateAnalysisFilters,
)
from app.tasks.celery_app import celery_app


PRODUCTION_ANALYSIS_SOURCE_LAYER = "PRODUCTION_ANALYSIS"


def _run_coro_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] | None = None
    error: BaseException | None = None

    def runner() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - defensive bridge for eager mode
            error = exc

    thread = Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if error is not None:
        raise error
    return result


async def _cleanup_production_candidate_analyses() -> int:
    async with AsyncSessionLocal() as db:
        analysis_ids = (
            await db.execute(
                select(VesselCandidateAnalysis.id).where(
                    VesselCandidateAnalysis.source_layer_code == PRODUCTION_ANALYSIS_SOURCE_LAYER
                )
            )
        ).scalars().all()
        if not analysis_ids:
            return 0
        await db.execute(
            delete(VesselCandidateAnalysisAnnotation).where(
                VesselCandidateAnalysisAnnotation.analysis_id.in_(analysis_ids)
            )
        )
        await db.execute(delete(VesselCandidateAnalysisItem).where(VesselCandidateAnalysisItem.analysis_id.in_(analysis_ids)))
        await db.execute(delete(VesselCandidateAnalysis).where(VesselCandidateAnalysis.id.in_(analysis_ids)))
        await db.commit()
        return len(analysis_ids)


async def _precompute_production_candidate_analyses(limit: int | None = None) -> dict[str, Any]:
    limit = max(1, min(int(limit or settings.VESSEL_CANDIDATE_PRECOMPUTE_LIMIT or 20), 200))
    deleted = await _cleanup_production_candidate_analyses()
    async with AsyncSessionLocal() as db:
        latest_snapshot = await db.scalar(
            select(VesselAisSnapshot)
            .where(VesselAisSnapshot.matched_position_count > 0)
            .order_by(VesselAisSnapshot.generated_at.desc(), VesselAisSnapshot.id.desc())
            .limit(1)
        )
        freights = (
            await db.execute(
                select(Freight)
                .where(
                    Freight.deleted_at.is_(None),
                    Freight.freight_no.like("FR-TMS-%"),
                    Freight.origin_node_id.is_not(None),
                    Freight.destination_node_id.is_not(None),
                    Freight.commodity_standard_id.is_not(None),
                    Freight.estimated_tonnage.is_not(None),
                )
                .order_by(Freight.id.desc())
                .limit(limit)
            )
        ).scalars().all()
        service = VesselCandidateAnalysisService(db)
        created: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for freight in freights:
            try:
                response = await service.create_analysis(
                    VesselCandidateAnalysisCreateRequest(
                        context_type_code="FREIGHT_SAMPLE",
                        freight_id=freight.id,
                        source_ais_snapshot_id=latest_snapshot.snapshot_id if latest_snapshot else None,
                        reported_within_minutes=1440,
                        filters=VesselCandidateAnalysisFilters(
                            max_node_distance_km=Decimal("50"),
                            quality_threshold="MEDIUM",
                        ),
                    ),
                    operator_id=None,
                )
                analysis = await db.get(VesselCandidateAnalysis, response.id)
                if analysis is not None:
                    context = dict(analysis.context_json or {})
                    context["analysis_source_layer"] = PRODUCTION_ANALYSIS_SOURCE_LAYER
                    context["production_precompute"] = True
                    analysis.context_json = context
                    analysis.source_layer_code = PRODUCTION_ANALYSIS_SOURCE_LAYER
                    await db.commit()
                created.append(
                    {
                        "freight_no": freight.freight_no,
                        "analysis_id": response.id,
                        "status_code": response.status_code,
                        "candidate_count": response.candidate_count,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - batch should continue and report row-level failures
                await db.rollback()
                failed.append({"freight_no": freight.freight_no, "error": str(exc)[:500]})
        return {
            "source_layer_code": PRODUCTION_ANALYSIS_SOURCE_LAYER,
            "deleted_existing": deleted,
            "selected_freights": len(freights),
            "created": len(created),
            "failed": len(failed),
            "snapshot_id": latest_snapshot.snapshot_id if latest_snapshot else None,
            "created_samples": created[:10],
            "failed_samples": failed[:10],
        }


@celery_app.task(name="vessel.precompute_production_candidate_analyses")
def precompute_production_candidate_analyses_task(limit: int | None = None) -> dict[str, Any]:
    return _run_coro_sync(_precompute_production_candidate_analyses(limit))


if __name__ == "__main__":
    print(_run_coro_sync(_precompute_production_candidate_analyses()))
