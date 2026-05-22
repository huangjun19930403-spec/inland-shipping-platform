"""Round 8 vessel candidate fit analysis service."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.models.address import Region, RegionBoundaryVersion, TransportNode
from app.models.freight import Freight, FreightCandidate
from app.models.route import ShippingRoute, ShippingRoutePlan, ShippingRoutePlanSegment, ShippingRoutePlanTrackVersion, ShippingRoutePlanTrackVersionSegment
from app.models.vessel import (
    VesselCandidateAnalysis,
    VesselCandidateAnalysisAnnotation,
    VesselCandidateAnalysisItem,
    VesselLatestPositionSnapshot,
    VesselNavigationConstraintEvidence,
    VesselNodeObservationItem,
    VesselNodeObservationVessel,
    VesselProfileSummary,
    VesselRouteSegmentMatchSample,
    VesselRouteSegmentObservationItem,
    VesselSpatialObservationSnapshot,
)
from app.modules.vessel.schemas import (
    PageResponse,
    VesselAisNodeSituationQuery,
    VesselAisRouteSituationQuery,
    VesselCandidateAnalysisAnnotationRequest,
    VesselCandidateAnalysisAnnotationResponse,
    VesselCandidateContextQualityGap,
    VesselCandidateAnalysisCreateRequest,
    VesselCandidateAnalysisItemResponse,
    VesselCandidateAnalysisListQuery,
    VesselCandidateAnalysisResponse,
)
from app.modules.vessel.candidate_scoring import VesselCandidateScoringMixin
from app.modules.vessel.candidate_responses import VesselCandidateResponseMixin
from app.modules.vessel.spatial_math import distance_km as raw_distance_km
from app.modules.vessel.spatial_service import VesselSpatialAnalysisService


ALLOWED_ANNOTATION_TYPES = {
    "DATA_TRUSTED",
    "DATA_INSUFFICIENT",
    "SAMPLE_REFERENCEABLE",
    "SAMPLE_NOT_REFERENCEABLE",
    "CONTACT_SUSPECTED_INVALID",
    "CERTIFICATE_RISK",
    "POSITION_ABNORMAL",
    "TONNAGE_MISMATCH",
    "NEEDS_REVIEW",
}
FORBIDDEN_ANALYSIS_TERMS = {
    "dispatch",
    "quote",
    "order",
    "settlement",
    "deal",
    "ship_contact",
    "派船",
    "报价",
    "成交",
    "运单",
    "结算",
    "确认承运",
}

@dataclass
class _AnalysisContext:
    context_type_code: str
    source_layer_code: str
    freight_id: int | None = None
    freight_candidate_id: int | None = None
    origin_node_id: int | None = None
    destination_node_id: int | None = None
    route_id: int | None = None
    plan_id: int | None = None
    origin_city_code: str | None = None
    destination_city_code: str | None = None
    region_id: int | None = None
    tonnage: Decimal | None = None
    cargo_category_code: str | None = None
    context_json: dict[str, Any] | None = None


class VesselCandidateAnalysisService(VesselCandidateScoringMixin, VesselCandidateResponseMixin):
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_analysis(
        self,
        payload: VesselCandidateAnalysisCreateRequest,
        *,
        operator_id: int | None = None,
    ) -> VesselCandidateAnalysisResponse:
        now = datetime.utcnow()
        context = await self._resolve_context(payload)
        filters = payload.filters.model_dump(mode="json")
        not_computable = self._base_not_computable_reasons(context)
        uncertainty_notes: list[str] = []
        data_sources = ["VESSEL_SUMMARY"]

        source_spatial_snapshot_id = payload.source_spatial_snapshot_id
        spatial_snapshot = await self._load_spatial_snapshot(source_spatial_snapshot_id) if source_spatial_snapshot_id else None
        if source_spatial_snapshot_id and spatial_snapshot is None:
            not_computable.append("SPATIAL_SNAPSHOT_MISSING")

        if spatial_snapshot is None and not not_computable:
            spatial_snapshot = await self._generate_spatial_snapshot(payload, context)
            source_spatial_snapshot_id = spatial_snapshot.snapshot_id if spatial_snapshot is not None else None
        if spatial_snapshot is not None:
            data_sources.append("VESSEL_SPATIAL_OBSERVATION")
            if spatial_snapshot.status_code in {"NOT_COMPUTABLE", "FAILED"}:
                not_computable.extend(spatial_snapshot.not_computable_reasons_json or ["SPATIAL_SNAPSHOT_MISSING"])
            if spatial_snapshot.status_code == "EXPIRED" or (spatial_snapshot.expires_at and spatial_snapshot.expires_at <= now):
                uncertainty_notes.append("SPATIAL_SNAPSHOT_EXPIRED")
            if spatial_snapshot.status_code == "PARTIAL":
                uncertainty_notes.append("SPATIAL_SNAPSHOT_PARTIAL")
        elif context.origin_node_id or context.route_id or context.plan_id:
            not_computable.append("SPATIAL_SNAPSHOT_MISSING")

        source_ais_snapshot_id = payload.source_ais_snapshot_id or (spatial_snapshot.source_snapshot_id if spatial_snapshot else None)
        if source_ais_snapshot_id:
            data_sources.append("AIS_LATEST_POSITION")
        else:
            latest_snapshot = await self._latest_ais_snapshot_id()
            source_ais_snapshot_id = latest_snapshot
            if latest_snapshot:
                data_sources.append("AIS_LATEST_POSITION")
        if not source_ais_snapshot_id and context.context_type_code not in {"MANUAL", "REGION"}:
            not_computable.append("AIS_SNAPSHOT_MISSING")

        spatial_maps = await self._load_spatial_maps(source_spatial_snapshot_id)
        latest_positions = await self._load_latest_positions(source_ais_snapshot_id)
        constraints = await self._load_constraint_status(source_spatial_snapshot_id, context)
        if constraints["status"] in {"UNKNOWN", "MISSING_SOURCE"}:
            uncertainty_notes.append("NAVIGATION_CONSTRAINT_UNKNOWN")

        summaries = await self._candidate_summaries(payload, context)
        items: list[VesselCandidateAnalysisItem] = []
        coverage_rate = Decimal(str(spatial_snapshot.coverage_rate)) if spatial_snapshot and spatial_snapshot.coverage_rate is not None else None
        if coverage_rate is None and source_ais_snapshot_id:
            coverage_rate = await self._ais_coverage_rate(source_ais_snapshot_id)
        if coverage_rate is not None and coverage_rate < Decimal("50"):
            uncertainty_notes.append("LOW_COVERAGE")

        for summary in summaries:
            item = self._score_summary(
                summary,
                payload=payload,
                context=context,
                latest_position=latest_positions.get(summary.vessel_profile_id),
                node_sample=spatial_maps["node_by_profile"].get(summary.vessel_profile_id),
                route_sample=spatial_maps["route_by_profile"].get(summary.vessel_profile_id),
                constraint_status=constraints["status"],
                coverage_rate=coverage_rate,
            )
            if item is not None:
                items.append(item)

        if not_computable:
            status_code = "NOT_COMPUTABLE"
            confidence_level = "UNKNOWN"
        elif not items:
            status_code = "PARTIAL"
            confidence_level = "LOW"
            uncertainty_notes.append("NO_CANDIDATE_SAMPLE")
        else:
            status_code = "PARTIAL" if any(item.confidence_level in {"LOW", "UNKNOWN"} for item in items) else "READY"
            confidence_level = self._aggregate_confidence([item.confidence_level for item in items], coverage_rate)

        analysis = VesselCandidateAnalysis(
            context_type_code=context.context_type_code,
            source_layer_code=context.source_layer_code,
            freight_id=context.freight_id,
            freight_candidate_id=context.freight_candidate_id,
            origin_node_id=context.origin_node_id,
            destination_node_id=context.destination_node_id,
            route_id=context.route_id,
            plan_id=context.plan_id,
            origin_city_code=context.origin_city_code,
            destination_city_code=context.destination_city_code,
            region_id=context.region_id,
            context_json=context.context_json or {},
            filters_json=filters,
            source_ais_snapshot_id=source_ais_snapshot_id,
            source_spatial_snapshot_id=source_spatial_snapshot_id,
            query_hash=self._query_hash(payload, context),
            status_code=status_code,
            coverage_rate=coverage_rate,
            confidence_level=confidence_level,
            candidate_count=len(items),
            low_confidence_count=sum(1 for item in items if item.confidence_level in {"LOW", "UNKNOWN"}),
            not_computable_reasons_json=self._dedupe(not_computable),
            uncertainty_notes_json=self._dedupe(uncertainty_notes),
            data_sources_json=self._dedupe(data_sources),
            generated_at=now,
            expires_at=now + timedelta(hours=1),
            created_by=operator_id,
            created_at=now,
            updated_at=now,
        )
        self.db.add(analysis)
        await self.db.flush()
        for item in items:
            item.analysis_id = analysis.id
            self.db.add(item)
        await self.db.flush()
        await self.db.commit()
        return await self.get_analysis(analysis.id)

    async def list_analyses(self, query: VesselCandidateAnalysisListQuery) -> PageResponse[VesselCandidateAnalysisResponse]:
        stmt = select(VesselCandidateAnalysis)
        if query.context_type_code:
            stmt = stmt.where(VesselCandidateAnalysis.context_type_code == query.context_type_code)
        if query.status_code:
            stmt = stmt.where(VesselCandidateAnalysis.status_code == query.status_code)
        if query.confidence_level:
            stmt = stmt.where(VesselCandidateAnalysis.confidence_level == query.confidence_level)
        if query.source_spatial_snapshot_id:
            stmt = stmt.where(VesselCandidateAnalysis.source_spatial_snapshot_id == query.source_spatial_snapshot_id)
        if query.freight_id:
            stmt = stmt.where(VesselCandidateAnalysis.freight_id == query.freight_id)
        if query.freight_candidate_id:
            stmt = stmt.where(VesselCandidateAnalysis.freight_candidate_id == query.freight_candidate_id)
        if query.origin_node_id:
            stmt = stmt.where(VesselCandidateAnalysis.origin_node_id == query.origin_node_id)
        if query.route_id:
            stmt = stmt.where(VesselCandidateAnalysis.route_id == query.route_id)
        if query.region_id:
            stmt = stmt.where(VesselCandidateAnalysis.region_id == query.region_id)
        if query.date_from:
            stmt = stmt.where(VesselCandidateAnalysis.generated_at >= datetime.combine(query.date_from, time.min))
        if query.date_to:
            stmt = stmt.where(VesselCandidateAnalysis.generated_at <= datetime.combine(query.date_to, time.max))
        total = await self.db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = (
            await self.db.execute(
                stmt.order_by(desc(VesselCandidateAnalysis.generated_at))
                .offset((query.page - 1) * query.page_size)
                .limit(query.page_size)
            )
        ).scalars().all()
        items = [await self._to_response(row, include_items=False) for row in rows]
        return PageResponse(total=int(total or 0), page=query.page, page_size=query.page_size, items=items)

    async def get_analysis(self, analysis_id: int) -> VesselCandidateAnalysisResponse:
        analysis = await self.db.get(VesselCandidateAnalysis, analysis_id)
        if analysis is None:
            raise NotFoundError("VesselCandidateAnalysis", analysis_id)
        return await self._to_response(analysis, include_items=True)

    async def add_annotation(
        self,
        analysis_id: int,
        item_id: int,
        payload: VesselCandidateAnalysisAnnotationRequest,
        *,
        operator_id: int | None = None,
    ) -> VesselCandidateAnalysisAnnotationResponse:
        if payload.annotation_type_code not in ALLOWED_ANNOTATION_TYPES:
            raise ValidationError("仅允许分析类标注", code="VESSEL_ANALYSIS_ANNOTATION_INVALID")
        if self._contains_forbidden_terms(payload.annotation_type_code) or self._contains_forbidden_terms(payload.comment):
            raise ValidationError("标注不得包含运输执行语义", code="VESSEL_ANALYSIS_EXECUTION_TERM_FORBIDDEN")
        analysis = await self.db.get(VesselCandidateAnalysis, analysis_id)
        if analysis is None:
            raise NotFoundError("VesselCandidateAnalysis", analysis_id)
        item = await self.db.get(VesselCandidateAnalysisItem, item_id)
        if item is None or item.analysis_id != analysis_id:
            raise NotFoundError("VesselCandidateAnalysisItem", item_id)
        now = datetime.utcnow()
        row = VesselCandidateAnalysisAnnotation(
            analysis_id=analysis_id,
            item_id=item_id,
            annotation_type_code=payload.annotation_type_code,
            comment=payload.comment,
            created_by=operator_id,
            created_at=now,
            source_version_json={
                "source_ais_snapshot_id": analysis.source_ais_snapshot_id,
                "source_spatial_snapshot_id": analysis.source_spatial_snapshot_id,
                "analysis_generated_at": analysis.generated_at.isoformat() if analysis.generated_at else None,
            },
        )
        self.db.add(row)
        await self.db.flush()
        await self.db.commit()
        return self._annotation_response(row)

    async def _resolve_context(self, payload: VesselCandidateAnalysisCreateRequest) -> _AnalysisContext:
        context_type = payload.context_type_code
        context: dict[str, Any] = payload.model_dump(mode="json")
        if context_type == "FREIGHT_SAMPLE":
            if payload.freight_id is None:
                raise ValidationError("正式货源样本分析必须提供 freight_id")
            freight = await self.db.get(Freight, payload.freight_id)
            if freight is None:
                raise NotFoundError("Freight", payload.freight_id)
            return _AnalysisContext(
                context_type_code=context_type,
                source_layer_code="STANDARD_FREIGHT_SAMPLE",
                freight_id=freight.id,
                origin_node_id=payload.origin_node_id or freight.origin_node_id,
                destination_node_id=payload.destination_node_id or freight.destination_node_id,
                origin_city_code=payload.origin_city_code or freight.origin_city_code,
                destination_city_code=payload.destination_city_code or freight.destination_city_code,
                tonnage=payload.tonnage or self._freight_tonnage(freight),
                cargo_category_code=payload.cargo_category_code or freight.packaging_form_code,
                context_json={**context, "cargo_title": freight.cargo_title, "source": "FREIGHT"},
            )
        if context_type == "FREIGHT_CANDIDATE":
            if payload.freight_candidate_id is None:
                raise ValidationError("候选货源分析必须提供 freight_candidate_id")
            candidate = await self.db.get(FreightCandidate, payload.freight_candidate_id)
            if candidate is None:
                raise NotFoundError("FreightCandidate", payload.freight_candidate_id)
            return _AnalysisContext(
                context_type_code=context_type,
                source_layer_code="FREIGHT_CANDIDATE",
                freight_candidate_id=candidate.id,
                origin_node_id=payload.origin_node_id or candidate.origin_node_id,
                destination_node_id=payload.destination_node_id or candidate.destination_node_id,
                origin_city_code=payload.origin_city_code or candidate.origin_city_code,
                destination_city_code=payload.destination_city_code or candidate.destination_city_code,
                tonnage=payload.tonnage or self._freight_tonnage(candidate),
                cargo_category_code=payload.cargo_category_code or candidate.packaging_form_code,
                context_json={**context, "cargo_title": candidate.cargo_title, "source": "FREIGHT_CANDIDATE"},
            )
        if context_type == "FREIGHT_SAMPLE_SET":
            freight_ids = payload.freight_sample_ids
            rows = (
                await self.db.execute(select(Freight).where(Freight.id.in_(freight_ids)))
            ).scalars().all() if freight_ids else []
            first = rows[0] if rows else None
            return _AnalysisContext(
                context_type_code=context_type,
                source_layer_code="STANDARD_FREIGHT_SAMPLE_SET",
                origin_node_id=payload.origin_node_id or (first.origin_node_id if first else None),
                destination_node_id=payload.destination_node_id or (first.destination_node_id if first else None),
                route_id=payload.route_id,
                plan_id=payload.plan_id,
                origin_city_code=payload.origin_city_code or (first.origin_city_code if first else None),
                destination_city_code=payload.destination_city_code or (first.destination_city_code if first else None),
                tonnage=payload.tonnage or (self._freight_tonnage(first) if first else None),
                context_json={**context, "sample_count": len(rows), "source": "FREIGHT_SAMPLE_SET"},
            )
        return _AnalysisContext(
            context_type_code=context_type,
            source_layer_code=context_type,
            origin_node_id=payload.origin_node_id,
            destination_node_id=payload.destination_node_id,
            route_id=payload.route_id,
            plan_id=payload.plan_id,
            origin_city_code=payload.origin_city_code,
            destination_city_code=payload.destination_city_code,
            region_id=payload.region_id,
            tonnage=payload.tonnage,
            cargo_category_code=payload.cargo_category_code,
            context_json=context,
        )

    async def _generate_spatial_snapshot(
        self,
        payload: VesselCandidateAnalysisCreateRequest,
        context: _AnalysisContext,
    ) -> VesselSpatialObservationSnapshot | None:
        service = VesselSpatialAnalysisService(self.db)
        if context.route_id or context.plan_id:
            cached = await self._cached_route_snapshot(context)
            if cached is not None:
                return cached
            response = await service.route_situation(
                VesselAisRouteSituationQuery(
                    route_id=context.route_id,
                    plan_id=context.plan_id,
                    reported_within_minutes=payload.reported_within_minutes,
                    ship_type_code=self._single_ship_type(payload),
                    deadweight_min=payload.filters.min_deadweight_ton,
                    deadweight_max=payload.filters.max_deadweight_ton,
                    quality_level=payload.filters.quality_threshold,
                )
            )
            return await self._load_spatial_snapshot(response.snapshot.snapshot_id)
        if context.origin_node_id:
            cached = await self._cached_node_snapshot(context.origin_node_id)
            if cached is not None:
                return cached
            response = await service.node_situation(
                VesselAisNodeSituationQuery(
                    node_id=context.origin_node_id,
                    radius_km=self._spatial_radius(payload.filters.max_node_distance_km),
                    reported_within_minutes=payload.reported_within_minutes,
                    ship_type_code=self._single_ship_type(payload),
                    deadweight_min=payload.filters.min_deadweight_ton,
                    deadweight_max=payload.filters.max_deadweight_ton,
                    quality_level=payload.filters.quality_threshold,
                )
            )
            return await self._load_spatial_snapshot(response.snapshot.snapshot_id)
        return None

    async def _cached_node_snapshot(self, node_id: int) -> VesselSpatialObservationSnapshot | None:
        now = datetime.utcnow()
        return await self.db.scalar(
            select(VesselSpatialObservationSnapshot)
            .join(VesselNodeObservationItem, VesselNodeObservationItem.snapshot_id == VesselSpatialObservationSnapshot.snapshot_id)
            .where(
                VesselNodeObservationItem.node_id == node_id,
                VesselSpatialObservationSnapshot.status_code.in_(["READY", "PARTIAL"]),
                or_(VesselSpatialObservationSnapshot.expires_at.is_(None), VesselSpatialObservationSnapshot.expires_at > now),
            )
            .order_by(desc(VesselSpatialObservationSnapshot.generated_at), desc(VesselSpatialObservationSnapshot.id))
            .limit(1)
        )

    async def _cached_route_snapshot(self, context: _AnalysisContext) -> VesselSpatialObservationSnapshot | None:
        now = datetime.utcnow()
        stmt = (
            select(VesselSpatialObservationSnapshot)
            .join(
                VesselRouteSegmentObservationItem,
                VesselRouteSegmentObservationItem.snapshot_id == VesselSpatialObservationSnapshot.snapshot_id,
            )
            .where(
                VesselSpatialObservationSnapshot.status_code.in_(["READY", "PARTIAL"]),
                or_(VesselSpatialObservationSnapshot.expires_at.is_(None), VesselSpatialObservationSnapshot.expires_at > now),
            )
        )
        if context.route_id:
            stmt = stmt.where(VesselRouteSegmentObservationItem.route_id == context.route_id)
        if context.plan_id:
            stmt = stmt.where(VesselRouteSegmentObservationItem.plan_id == context.plan_id)
        return await self.db.scalar(
            stmt.order_by(desc(VesselSpatialObservationSnapshot.generated_at), desc(VesselSpatialObservationSnapshot.id)).limit(1)
        )

    async def _load_spatial_snapshot(self, snapshot_id: str | None) -> VesselSpatialObservationSnapshot | None:
        if not snapshot_id:
            return None
        return await self.db.scalar(
            select(VesselSpatialObservationSnapshot).where(VesselSpatialObservationSnapshot.snapshot_id == snapshot_id)
        )

    async def _latest_ais_snapshot_id(self) -> str | None:
        row = await self.db.scalar(
            select(VesselLatestPositionSnapshot.snapshot_id)
            .order_by(desc(VesselLatestPositionSnapshot.created_at))
            .limit(1)
        )
        return row

    async def _load_latest_positions(self, snapshot_id: str | None) -> dict[int, VesselLatestPositionSnapshot]:
        if not snapshot_id:
            return {}
        rows = (
            await self.db.execute(
                select(VesselLatestPositionSnapshot).where(VesselLatestPositionSnapshot.snapshot_id == snapshot_id)
            )
        ).scalars().all()
        return {row.vessel_profile_id: row for row in rows if row.vessel_profile_id is not None}

    async def _load_spatial_maps(self, snapshot_id: str | None) -> dict[str, dict[int, Any]]:
        if not snapshot_id:
            return {"node_by_profile": {}, "route_by_profile": {}}
        node_rows = (
            await self.db.execute(
                select(VesselNodeObservationVessel).where(VesselNodeObservationVessel.snapshot_id == snapshot_id)
            )
        ).scalars().all()
        route_rows = (
            await self.db.execute(
                select(VesselRouteSegmentMatchSample).where(VesselRouteSegmentMatchSample.snapshot_id == snapshot_id)
            )
        ).scalars().all()
        return {
            "node_by_profile": {row.vessel_profile_id: row for row in node_rows if row.vessel_profile_id is not None},
            "route_by_profile": {row.vessel_profile_id: row for row in route_rows if row.vessel_profile_id is not None},
        }

    async def _load_constraint_status(self, snapshot_id: str | None, context: _AnalysisContext) -> dict[str, Any]:
        stmt = select(VesselNavigationConstraintEvidence)
        if snapshot_id:
            stmt = stmt.where(VesselNavigationConstraintEvidence.snapshot_id == snapshot_id)
        elif context.origin_node_id:
            stmt = stmt.where(
                VesselNavigationConstraintEvidence.context_type_code == "NODE",
                VesselNavigationConstraintEvidence.context_id == context.origin_node_id,
            )
        else:
            return {"status": "NOT_APPLICABLE", "items": []}
        rows = (await self.db.execute(stmt)).scalars().all()
        if not rows:
            return {"status": "UNKNOWN", "items": []}
        statuses = {row.status_code for row in rows}
        if statuses & {"PASS", "AVAILABLE"}:
            status = "WARNING" if statuses & {"WARNING", "STALE"} else "AVAILABLE"
        elif "WARNING" in statuses:
            status = "WARNING"
        elif "BLOCKED" in statuses:
            status = "BLOCKED"
        elif "MISSING_SOURCE" in statuses:
            status = "MISSING_SOURCE"
        elif "UNKNOWN" in statuses:
            status = "UNKNOWN"
        elif "STALE" in statuses:
            status = "STALE"
        elif "AVAILABLE" in statuses:
            status = "AVAILABLE"
        else:
            status = sorted(statuses)[0]
        return {"status": status, "items": rows}

    async def _candidate_summaries(
        self,
        payload: VesselCandidateAnalysisCreateRequest,
        context: _AnalysisContext,
    ) -> list[VesselProfileSummary]:
        stmt = select(VesselProfileSummary).where(VesselProfileSummary.summary_status_code.in_(["READY", "PARTIAL", "STALE"]))
        ship_types = payload.filters.ship_type_codes
        if ship_types:
            stmt = stmt.where(VesselProfileSummary.ship_type_code.in_(ship_types))
        if payload.filters.min_deadweight_ton is not None:
            stmt = stmt.where(
                or_(VesselProfileSummary.deadweight_ton.is_(None), VesselProfileSummary.deadweight_ton >= payload.filters.min_deadweight_ton)
            )
        if payload.filters.max_deadweight_ton is not None:
            stmt = stmt.where(
                or_(VesselProfileSummary.deadweight_ton.is_(None), VesselProfileSummary.deadweight_ton <= payload.filters.max_deadweight_ton)
            )
        if payload.filters.quality_threshold:
            stmt = stmt.where(VesselProfileSummary.data_quality_level.in_(self._allowed_quality_levels(payload.filters.quality_threshold)))
        _ = context
        rows = (await self.db.execute(stmt.order_by(desc(VesselProfileSummary.refreshed_at)).limit(60))).scalars().all()
        return list(rows)

    def _base_not_computable_reasons(self, context: _AnalysisContext) -> list[str]:
        reasons: list[str] = []
        if context.origin_node_id:
            # Coordinates are validated lazily so manual contexts can still be saved.
            pass
        return reasons

    async def _ais_coverage_rate(self, snapshot_id: str) -> Decimal | None:
        snapshot = await self.db.scalar(
            select(VesselSpatialObservationSnapshot.coverage_rate)
            .where(VesselSpatialObservationSnapshot.source_snapshot_id == snapshot_id)
            .order_by(desc(VesselSpatialObservationSnapshot.generated_at))
            .limit(1)
        )
        return Decimal(str(snapshot)) if snapshot is not None else None

    def _query_hash(self, payload: VesselCandidateAnalysisCreateRequest, context: _AnalysisContext) -> str:
        raw = json.dumps(
            {"payload": payload.model_dump(mode="json"), "context": context.context_json or {}},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _freight_tonnage(self, row: Freight | FreightCandidate | None) -> Decimal | None:
        if row is None:
            return None
        if row.estimated_tonnage is not None:
            return Decimal(str(row.estimated_tonnage))
        if row.min_tonnage is not None and row.max_tonnage is not None:
            return (Decimal(str(row.min_tonnage)) + Decimal(str(row.max_tonnage))) / Decimal("2")
        return None

    def _single_ship_type(self, payload: VesselCandidateAnalysisCreateRequest) -> str | None:
        return payload.filters.ship_type_codes[0] if len(payload.filters.ship_type_codes) == 1 else None

    def _spatial_radius(self, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        return min(value, Decimal("20"))

    def _contains_forbidden_terms(self, value: str | None) -> bool:
        lowered = (value or "").lower()
        return any(term in lowered for term in FORBIDDEN_ANALYSIS_TERMS)


def distance_km(lon1: Decimal | float, lat1: Decimal | float, lon2: Decimal | float, lat2: Decimal | float) -> Decimal:
    distance = raw_distance_km(lon1, lat1, lon2, lat2)
    return Decimal(str(distance or 0)).quantize(Decimal("0.001"))
