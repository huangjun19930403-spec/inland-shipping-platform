"""Cleanup helpers for Round 11 experience seed."""

from __future__ import annotations

from sqlalchemy import delete, or_, select

from app.models.analysis import FactVesselAisFreshnessDaily
from app.models.freight import (
    Freight,
    FreightBatchTask,
    FreightCandidate,
    FreightCandidateManualFeedback,
    FreightClue,
    FreightContact,
    FreightNormalizationSuggestion,
    FreightNormalizationTask,
    FreightTagRelation,
    FreightTmsInbound,
)
from app.models.route import (
    ShippingRoute,
    ShippingRoutePlan,
    ShippingRoutePlanPoint,
    ShippingRoutePlanSegment,
    ShippingRoutePlanSegmentResult,
)
from app.models.vessel import (
    VesselAisCitySnapshotItem,
    VesselAisSnapshot,
    VesselCandidateAnalysis,
    VesselCandidateAnalysisAnnotation,
    VesselCandidateAnalysisItem,
    VesselLatestPositionSnapshot,
    VesselNavigationConstraintEvidence,
    VesselNodeObservationItem,
    VesselNodeObservationVessel,
    VesselRouteSegmentMatchSample,
    VesselRouteSegmentObservationItem,
    VesselSpatialObservationSnapshot,
)
from scripts.seeds.demo.experience.shared import AIS_SNAPSHOT_ID, NODE_SNAPSHOT_IDS, ROUTES, ROUTE_SNAPSHOT_IDS

async def _clear_experience_rows(session) -> None:
    spatial_snapshot_ids = list(NODE_SNAPSHOT_IDS.values()) + list(ROUTE_SNAPSHOT_IDS.values())
    analysis_ids = (
        await session.execute(
            select(VesselCandidateAnalysis.id).where(
                or_(
                    VesselCandidateAnalysis.query_hash.like("demo-experience-%"),
                    VesselCandidateAnalysis.source_ais_snapshot_id == AIS_SNAPSHOT_ID,
                    VesselCandidateAnalysis.source_spatial_snapshot_id.in_(spatial_snapshot_ids),
                )
            )
        )
    ).scalars().all()
    if analysis_ids:
        await session.execute(
            delete(VesselCandidateAnalysisAnnotation).where(
                VesselCandidateAnalysisAnnotation.analysis_id.in_(analysis_ids)
            )
        )
        await session.execute(delete(VesselCandidateAnalysisItem).where(VesselCandidateAnalysisItem.analysis_id.in_(analysis_ids)))
        await session.execute(delete(VesselCandidateAnalysis).where(VesselCandidateAnalysis.id.in_(analysis_ids)))

    await session.execute(
        delete(VesselNavigationConstraintEvidence).where(
            or_(
                VesselNavigationConstraintEvidence.snapshot_id.in_(spatial_snapshot_ids),
                VesselNavigationConstraintEvidence.source_ref.like("round11-experience%"),
            )
        )
    )
    await session.execute(
        delete(VesselRouteSegmentMatchSample).where(VesselRouteSegmentMatchSample.snapshot_id.in_(spatial_snapshot_ids))
    )
    await session.execute(
        delete(VesselRouteSegmentObservationItem).where(VesselRouteSegmentObservationItem.snapshot_id.in_(spatial_snapshot_ids))
    )
    await session.execute(delete(VesselNodeObservationVessel).where(VesselNodeObservationVessel.snapshot_id.in_(spatial_snapshot_ids)))
    await session.execute(delete(VesselNodeObservationItem).where(VesselNodeObservationItem.snapshot_id.in_(spatial_snapshot_ids)))
    await session.execute(delete(VesselSpatialObservationSnapshot).where(VesselSpatialObservationSnapshot.snapshot_id.in_(spatial_snapshot_ids)))
    await session.execute(delete(FactVesselAisFreshnessDaily).where(FactVesselAisFreshnessDaily.source_snapshot_id == AIS_SNAPSHOT_ID))
    await session.execute(delete(VesselLatestPositionSnapshot).where(VesselLatestPositionSnapshot.snapshot_id == AIS_SNAPSHOT_ID))
    await session.execute(delete(VesselAisCitySnapshotItem).where(VesselAisCitySnapshotItem.snapshot_id == AIS_SNAPSHOT_ID))
    await session.execute(delete(VesselAisSnapshot).where(VesselAisSnapshot.snapshot_id == AIS_SNAPSHOT_ID))

    freight_ids = (
        await session.execute(select(Freight.id).where(Freight.freight_no.like("FR-DEMO-%")))
    ).scalars().all()
    candidate_ids = (
        await session.execute(select(FreightCandidate.id).where(FreightCandidate.candidate_no.like("FCA-DEMO-%")))
    ).scalars().all()
    clue_ids = (
        await session.execute(select(FreightClue.id).where(FreightClue.clue_no.like("FCU-DEMO-%")))
    ).scalars().all()
    batch_ids = (
        await session.execute(select(FreightBatchTask.id).where(FreightBatchTask.batch_no.like("FBT-DEMO-%")))
    ).scalars().all()
    inbound_ids = (
        await session.execute(select(FreightTmsInbound.id).where(FreightTmsInbound.inbound_no.like("FTI-DEMO-%")))
    ).scalars().all()
    task_ids = (
        await session.execute(select(FreightNormalizationTask.id).where(FreightNormalizationTask.task_no.like("FNT-DEMO-%")))
    ).scalars().all()
    if freight_ids:
        await session.execute(delete(FreightNormalizationSuggestion).where(FreightNormalizationSuggestion.freight_id.in_(freight_ids)))
        await session.execute(delete(FreightContact).where(FreightContact.freight_id.in_(freight_ids)))
        await session.execute(delete(FreightTagRelation).where(FreightTagRelation.freight_id.in_(freight_ids)))
    if candidate_ids:
        await session.execute(
            delete(FreightCandidateManualFeedback).where(FreightCandidateManualFeedback.candidate_id.in_(candidate_ids))
        )
        await session.execute(delete(FreightCandidate).where(FreightCandidate.id.in_(candidate_ids)))
    if freight_ids:
        await session.execute(delete(Freight).where(Freight.id.in_(freight_ids)))
    if clue_ids:
        await session.execute(delete(FreightClue).where(FreightClue.id.in_(clue_ids)))
    if batch_ids:
        await session.execute(delete(FreightBatchTask).where(FreightBatchTask.id.in_(batch_ids)))
    if inbound_ids:
        await session.execute(delete(FreightTmsInbound).where(FreightTmsInbound.id.in_(inbound_ids)))
    if task_ids:
        await session.execute(delete(FreightNormalizationTask).where(FreightNormalizationTask.id.in_(task_ids)))

    await _delete_route_codes(
        session,
        [route.code for route in ROUTES]
        + ["ROUTE_TAICANG_WUHU", "ROUTE_SUZHOU_NANJING_STEEL", "ROUTE_HUZHOU_WUHU_CEMENT"],
    )
    await session.flush()


async def _delete_route_codes(session, route_codes: list[str]) -> None:
    route_ids = (
        await session.execute(select(ShippingRoute.id).where(ShippingRoute.code.in_(route_codes)))
    ).scalars().all()
    if not route_ids:
        return
    plan_ids = (
        await session.execute(select(ShippingRoutePlan.id).where(ShippingRoutePlan.route_id.in_(route_ids)))
    ).scalars().all()
    if plan_ids:
        segment_ids = (
            await session.execute(select(ShippingRoutePlanSegment.id).where(ShippingRoutePlanSegment.plan_id.in_(plan_ids)))
        ).scalars().all()
        if segment_ids:
            await session.execute(delete(ShippingRoutePlanSegmentResult).where(ShippingRoutePlanSegmentResult.segment_id.in_(segment_ids)))
        await session.execute(delete(ShippingRoutePlanSegment).where(ShippingRoutePlanSegment.plan_id.in_(plan_ids)))
        await session.execute(delete(ShippingRoutePlanPoint).where(ShippingRoutePlanPoint.plan_id.in_(plan_ids)))
        await session.execute(delete(ShippingRoutePlan).where(ShippingRoutePlan.id.in_(plan_ids)))
    await session.execute(delete(ShippingRoute).where(ShippingRoute.id.in_(route_ids)))
