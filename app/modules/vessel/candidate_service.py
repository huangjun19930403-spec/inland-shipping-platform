"""Round 8 vessel candidate fit analysis service."""

from __future__ import annotations

import hashlib
import json
import math
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
CONFIDENCE_ORDER = {"UNKNOWN": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}


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


class VesselCandidateAnalysisService:
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

    def _score_summary(
        self,
        summary: VesselProfileSummary,
        *,
        payload: VesselCandidateAnalysisCreateRequest,
        context: _AnalysisContext,
        latest_position: VesselLatestPositionSnapshot | None,
        node_sample: VesselNodeObservationVessel | None,
        route_sample: VesselRouteSegmentMatchSample | None,
        constraint_status: str,
        coverage_rate: Decimal | None,
    ) -> VesselCandidateAnalysisItem | None:
        score_parts: dict[str, Decimal] = {}
        risk_reasons: list[str] = []
        uncertainty: list[str] = []
        not_computable: list[str] = []
        data_sources = ["VESSEL_SUMMARY"]
        cap = "HIGH"

        spatial_score, node_distance = self._spatial_score(context, payload, latest_position, node_sample, uncertainty, not_computable)
        score_parts["SPATIAL_DISTANCE"] = spatial_score
        if node_sample is not None:
            data_sources.append("VESSEL_NODE_OBSERVATION")
        if latest_position is not None:
            data_sources.append("AIS_LATEST_POSITION")

        route_score, route_match_score, direction_consistency = self._route_score(context, route_sample, uncertainty, not_computable)
        score_parts["ROUTE_TRAJECTORY"] = route_score
        if route_sample is not None:
            data_sources.append("VESSEL_ROUTE_SEGMENT_OBSERVATION")

        score_parts["DEADWEIGHT"] = self._deadweight_score(summary, context, payload, not_computable)
        score_parts["SHIP_TYPE_CARGO"] = self._ship_type_score(summary, payload, not_computable)
        score_parts["DRAFT_NAVIGATION"] = self._navigation_score(constraint_status, uncertainty, not_computable)
        score_parts["RISK_COMPLIANCE"] = self._risk_score(summary, risk_reasons, not_computable)
        score_parts["DATA_QUALITY"] = self._quality_score(summary)
        score_parts["CONTACT_TRUST"] = self._contact_score(summary)

        freshness = (latest_position.freshness_level if latest_position is not None else summary.ais_freshness_level) or "UNKNOWN"
        if freshness in {"STALE", "EXPIRED", "UNKNOWN"}:
            uncertainty.append(f"AIS_{freshness}")
            cap = self._min_confidence(cap, "LOW" if freshness in {"EXPIRED", "UNKNOWN"} else "MEDIUM")
        if summary.risk_level == "HIGH":
            cap = self._min_confidence(cap, "LOW")
        if constraint_status in {"UNKNOWN", "MISSING_SOURCE"}:
            cap = self._min_confidence(cap, "MEDIUM")
        if coverage_rate is not None and coverage_rate < Decimal("50"):
            cap = self._min_confidence(cap, "LOW")

        fit_score = sum(score_parts.values(), Decimal("0"))
        confidence_level = self._item_confidence(cap, summary, not_computable, uncertainty)
        value_level = self._candidate_value(fit_score, confidence_level, freshness, summary.risk_level, constraint_status, not_computable)
        return VesselCandidateAnalysisItem(
            analysis_id=0,
            vessel_profile_id=summary.vessel_profile_id,
            mmsi=summary.current_mmsi,
            ship_name=summary.ship_name,
            ship_type_code=summary.ship_type_code,
            deadweight_ton=summary.deadweight_ton,
            design_draft_m=summary.design_draft_m,
            latest_position_time=latest_position.position_time if latest_position is not None else summary.latest_position_time,
            ais_freshness_level=freshness,
            risk_level=summary.risk_level,
            quality_level=summary.data_quality_level,
            fit_score=fit_score.quantize(Decimal("0.01")),
            candidate_value_level=value_level,
            confidence_level=confidence_level,
            node_distance_km=node_distance,
            route_match_score=route_match_score,
            direction_consistency=direction_consistency,
            constraint_status_code=constraint_status,
            score_parts_json={key: float(value) for key, value in score_parts.items()},
            risk_reasons_json=self._dedupe(risk_reasons),
            uncertainty_reasons_json=self._dedupe(uncertainty),
            not_computable_reasons_json=self._dedupe(not_computable),
            data_sources_json=self._dedupe(data_sources),
            created_at=datetime.utcnow(),
        )

    def _spatial_score(
        self,
        context: _AnalysisContext,
        payload: VesselCandidateAnalysisCreateRequest,
        latest_position: VesselLatestPositionSnapshot | None,
        node_sample: VesselNodeObservationVessel | None,
        uncertainty: list[str],
        not_computable: list[str],
    ) -> tuple[Decimal, Decimal | None]:
        if context.origin_node_id is None and context.region_id is None:
            return Decimal("25"), None
        max_distance = payload.filters.max_node_distance_km or Decimal("50")
        if node_sample is not None and node_sample.distance_km is not None:
            distance = Decimal(str(node_sample.distance_km))
            freshness = node_sample.freshness_level or "UNKNOWN"
            if freshness in {"STALE", "EXPIRED", "UNKNOWN"}:
                uncertainty.append(f"NODE_SAMPLE_{freshness}")
                return Decimal("6"), distance
            ratio = max(Decimal("0"), Decimal("1") - (distance / max_distance))
            return (Decimal("10") + ratio * Decimal("15")).quantize(Decimal("0.01")), distance
        if latest_position is not None:
            uncertainty.append("SPATIAL_ONLY_LATEST_POSITION")
            return Decimal("8"), None
        not_computable.append("SPATIAL_SNAPSHOT_MISSING")
        return Decimal("0"), None

    def _route_score(
        self,
        context: _AnalysisContext,
        route_sample: VesselRouteSegmentMatchSample | None,
        uncertainty: list[str],
        not_computable: list[str],
    ) -> tuple[Decimal, Decimal | None, Decimal | None]:
        if context.route_id is None and context.plan_id is None:
            return Decimal("15"), None, None
        if route_sample is None:
            not_computable.append("TRACK_COVERAGE_INSUFFICIENT")
            return Decimal("0"), None, None
        match = Decimal(str(route_sample.match_score or 0))
        direction = Decimal(str(route_sample.direction_consistency)) if route_sample.direction_consistency is not None else None
        if route_sample.confidence_level in {"LOW", "UNKNOWN"} or route_sample.match_status_code == "LOW_CONFIDENCE":
            uncertainty.append("ROUTE_MATCH_LOW_CONFIDENCE")
            return min(Decimal("6"), match / Decimal("100") * Decimal("15")), match, direction
        return (match / Decimal("100") * Decimal("15")).quantize(Decimal("0.01")), match, direction

    def _deadweight_score(
        self,
        summary: VesselProfileSummary,
        context: _AnalysisContext,
        payload: VesselCandidateAnalysisCreateRequest,
        not_computable: list[str],
    ) -> Decimal:
        deadweight = Decimal(str(summary.deadweight_ton)) if summary.deadweight_ton is not None else None
        target = context.tonnage or payload.filters.min_deadweight_ton
        if deadweight is None:
            not_computable.append("DEADWEIGHT_MISSING")
            return Decimal("0")
        if target is None:
            return Decimal("15")
        if deadweight >= target:
            return Decimal("15")
        ratio = max(Decimal("0"), deadweight / target)
        return (ratio * Decimal("15")).quantize(Decimal("0.01"))

    def _ship_type_score(
        self,
        summary: VesselProfileSummary,
        payload: VesselCandidateAnalysisCreateRequest,
        not_computable: list[str],
    ) -> Decimal:
        if not summary.ship_type_code:
            not_computable.append("SHIP_TYPE_MISSING")
            return Decimal("0")
        if payload.filters.ship_type_codes and summary.ship_type_code not in payload.filters.ship_type_codes:
            return Decimal("3")
        return Decimal("10")

    def _navigation_score(self, status: str, uncertainty: list[str], not_computable: list[str]) -> Decimal:
        if status == "AVAILABLE":
            return Decimal("10")
        if status == "WARNING":
            uncertainty.append("NAVIGATION_CONSTRAINT_WARNING")
            return Decimal("6")
        if status == "BLOCKED":
            not_computable.append("NAVIGATION_CONSTRAINT_BLOCKED")
            return Decimal("0")
        if status == "NOT_APPLICABLE":
            return Decimal("8")
        if status == "STALE":
            uncertainty.append("NAVIGATION_CONSTRAINT_STALE")
            return Decimal("4")
        if status in {"UNKNOWN", "MISSING_SOURCE"}:
            not_computable.append("CONSTRAINT_SOURCE_MISSING")
            return Decimal("2")
        return Decimal("6")

    def _risk_score(self, summary: VesselProfileSummary, risk_reasons: list[str], not_computable: list[str]) -> Decimal:
        risk = summary.risk_level or "UNKNOWN"
        if risk == "LOW":
            return Decimal("10")
        if risk == "MEDIUM":
            risk_reasons.append("RISK_MEDIUM")
            return Decimal("5")
        if risk == "HIGH":
            risk_reasons.append("RISK_HIGH")
            return Decimal("0")
        not_computable.append("RISK_UNKNOWN")
        return Decimal("3")

    def _quality_score(self, summary: VesselProfileSummary) -> Decimal:
        quality = summary.data_quality_level or "UNKNOWN"
        if quality == "HIGH":
            return Decimal("10")
        if quality == "MEDIUM":
            return Decimal("7")
        if quality == "LOW":
            return Decimal("3")
        return Decimal("4")

    def _contact_score(self, summary: VesselProfileSummary) -> Decimal:
        trust = summary.contact_trust_level or "UNKNOWN"
        if trust == "HIGH":
            return Decimal("5")
        if trust == "MEDIUM":
            return Decimal("3")
        return Decimal("1")

    def _candidate_value(
        self,
        fit_score: Decimal,
        confidence_level: str,
        freshness: str,
        risk_level: str,
        constraint_status: str,
        not_computable: list[str],
    ) -> str:
        high_blocked = (
            CONFIDENCE_ORDER.get(confidence_level, 0) < CONFIDENCE_ORDER["MEDIUM"]
            or freshness in {"STALE", "EXPIRED", "UNKNOWN"}
            or risk_level in {"HIGH", "UNKNOWN"}
            or constraint_status in {"UNKNOWN", "MISSING_SOURCE"}
            or bool(not_computable)
        )
        if fit_score >= Decimal("80") and not high_blocked:
            return "HIGH"
        if fit_score >= Decimal("60"):
            return "MEDIUM"
        return "LOW"

    def _item_confidence(
        self,
        cap: str,
        summary: VesselProfileSummary,
        not_computable: list[str],
        uncertainty: list[str],
    ) -> str:
        level = "HIGH"
        if summary.data_quality_level in {"MEDIUM", "UNKNOWN"}:
            level = self._min_confidence(level, "MEDIUM")
        if summary.data_quality_level == "LOW" or summary.risk_level == "UNKNOWN":
            level = self._min_confidence(level, "LOW")
        if not_computable:
            level = self._min_confidence(level, "LOW")
        if uncertainty:
            level = self._min_confidence(level, "MEDIUM")
        return self._min_confidence(level, cap)

    def _aggregate_confidence(self, levels: list[str], coverage_rate: Decimal | None) -> str:
        if not levels:
            return "UNKNOWN"
        if coverage_rate is not None and coverage_rate < Decimal("50"):
            return "LOW"
        if any(level == "HIGH" for level in levels) and not any(level in {"LOW", "UNKNOWN"} for level in levels):
            return "HIGH"
        if any(level in {"MEDIUM", "HIGH"} for level in levels):
            return "MEDIUM"
        return "LOW"

    async def _to_response(self, analysis: VesselCandidateAnalysis, *, include_items: bool) -> VesselCandidateAnalysisResponse:
        items: list[VesselCandidateAnalysisItemResponse] = []
        if include_items:
            item_rows = (
                await self.db.execute(
                    select(VesselCandidateAnalysisItem)
                    .where(VesselCandidateAnalysisItem.analysis_id == analysis.id)
                    .order_by(desc(VesselCandidateAnalysisItem.fit_score), VesselCandidateAnalysisItem.id)
                )
            ).scalars().all()
            annotations = await self._annotations_by_item([row.id for row in item_rows])
            positions = await self._latest_positions_for_items(analysis, item_rows)
            items = [self._item_response(row, annotations.get(row.id, []), positions.get(row.vessel_profile_id)) for row in item_rows]
        return VesselCandidateAnalysisResponse(
            id=analysis.id,
            context_type_code=analysis.context_type_code,
            source_layer_code=analysis.source_layer_code,
            freight_id=analysis.freight_id,
            freight_candidate_id=analysis.freight_candidate_id,
            origin_node_id=analysis.origin_node_id,
            destination_node_id=analysis.destination_node_id,
            route_id=analysis.route_id,
            plan_id=analysis.plan_id,
            origin_city_code=analysis.origin_city_code,
            destination_city_code=analysis.destination_city_code,
            region_id=analysis.region_id,
            context=analysis.context_json or {},
            filters=analysis.filters_json or {},
            source_ais_snapshot_id=analysis.source_ais_snapshot_id,
            source_spatial_snapshot_id=analysis.source_spatial_snapshot_id,
            query_hash=analysis.query_hash,
            status_code=analysis.status_code,
            coverage_rate=analysis.coverage_rate,
            confidence_level=analysis.confidence_level,
            candidate_count=analysis.candidate_count,
            low_confidence_count=analysis.low_confidence_count,
            not_computable_reasons=analysis.not_computable_reasons_json or [],
            uncertainty_notes=analysis.uncertainty_notes_json or [],
            data_sources=self._data_source_codes(analysis.data_sources_json),
            analysis_center_path=self._analysis_center_path(analysis),
            source_context_path=self._source_context_path(analysis),
            context_quality_gaps=await self._context_quality_gaps(analysis),
            boundary_notice="候选适配只输出分析判断和不确定性，不代表可接货、不产生运输承诺。",
            uncertainty_explain=self._candidate_uncertainty_explain(analysis),
            route_layers=[],
            regional_supply_demand=self._regional_supply_demand(analysis),
            generated_at=analysis.generated_at,
            expires_at=analysis.expires_at,
            items=items,
        )

    @staticmethod
    def _candidate_uncertainty_explain(analysis: VesselCandidateAnalysis) -> str:
        reasons = [*(analysis.uncertainty_notes_json or []), *(analysis.not_computable_reasons_json or [])]
        return " / ".join(str(item) for item in reasons[:6]) or "暂无明显不确定性，仍需结合实时 AIS 和业务核验。"

    @staticmethod
    def _regional_supply_demand(analysis: VesselCandidateAnalysis) -> dict[str, Any] | None:
        context = analysis.context_json or {}
        value = context.get("regional_supply_demand") or context.get("supply_demand") or context.get("region_supply_demand")
        return value if isinstance(value, dict) else None

    @staticmethod
    def _analysis_center_path(analysis: VesselCandidateAnalysis) -> str:
        params = ["tab=candidate"]
        if analysis.generated_at:
            day = analysis.generated_at.date().isoformat()
            params.extend([f"date_from={day}", f"date_to={day}"])
        return f"/analysis/ships?{'&'.join(params)}"

    @staticmethod
    def _source_context_path(analysis: VesselCandidateAnalysis) -> str | None:
        if analysis.freight_id:
            return f"/freight/detail/{analysis.freight_id}"
        if analysis.freight_candidate_id:
            return f"/freight/candidates?candidate_id={analysis.freight_candidate_id}"
        if analysis.origin_node_id:
            return f"/address/nodes/{analysis.origin_node_id}"
        if analysis.route_id:
            return f"/route/detail/{analysis.route_id}"
        if analysis.region_id:
            return f"/address/regions?region_id={analysis.region_id}"
        return None

    async def _context_quality_gaps(self, analysis: VesselCandidateAnalysis) -> list[VesselCandidateContextQualityGap]:
        gaps: list[VesselCandidateContextQualityGap] = []
        if analysis.origin_node_id:
            node = await self.db.get(TransportNode, analysis.origin_node_id)
            if node is None:
                gaps.append(
                    self._quality_gap(
                        "TRANSPORT_NODE",
                        analysis.origin_node_id,
                        None,
                        "origin_node_id",
                        "NODE_MISSING",
                        "起运节点不存在或已不可用，空间分析无法稳定定位。",
                        f"/address/nodes/{analysis.origin_node_id}",
                    )
                )
            elif node.longitude is None or node.latitude is None:
                gaps.append(
                    self._quality_gap(
                        "TRANSPORT_NODE",
                        node.id,
                        node.name,
                        "longitude,latitude",
                        "NODE_COORDINATE_MISSING",
                        "节点缺少经纬度，候选船与节点距离只能降级计算。",
                        f"/address/nodes/{node.id}/edit",
                    )
                )
        if analysis.route_id:
            route = await self.db.get(ShippingRoute, analysis.route_id)
            if route is None:
                gaps.append(
                    self._quality_gap(
                        "SHIPPING_ROUTE",
                        analysis.route_id,
                        None,
                        "route_id",
                        "ROUTE_MISSING",
                        "航线不存在或已不可用，无法做航线匹配复盘。",
                        f"/route/detail/{analysis.route_id}",
                    )
            )
            else:
                segment_count = await self._route_segment_count(route.id)
                track_count = await self._route_track_count(route.id)
                if segment_count == 0:
                    gaps.append(
                        self._quality_gap(
                            "SHIPPING_ROUTE",
                            route.id,
                            route.name,
                            "segments",
                            "ROUTE_SEGMENT_MISSING",
                            "航线缺少保存的航段，候选分析无法判断航线关系。",
                            f"/route/detail/{route.id}",
                        )
                    )
                if track_count == 0:
                    gaps.append(
                        self._quality_gap(
                            "SHIPPING_ROUTE",
                            route.id,
                            route.name,
                            "track",
                            "ROUTE_TRACK_MISSING",
                            "航线缺少地图轨迹，空间匹配可信度会下降。",
                            f"/route/detail/{route.id}",
                        )
                    )
        if analysis.region_id:
            region = await self.db.get(Region, analysis.region_id)
            if region is None:
                gaps.append(
                    self._quality_gap(
                        "REGION",
                        analysis.region_id,
                        None,
                        "region_id",
                        "REGION_MISSING",
                        "区域不存在或已不可用，供需分布无法复盘。",
                        f"/address/regions?region_id={analysis.region_id}",
                    )
                )
            elif not region.current_boundary_version_id:
                gaps.append(
                    self._quality_gap(
                        "REGION",
                        region.id,
                        region.name,
                        "current_boundary_version_id",
                        "REGION_BOUNDARY_MISSING",
                        "区域缺少当前边界版本，空间供需分析无法精确落区。",
                        f"/address/regions?region_id={region.id}",
                    )
                )
            else:
                boundary = await self.db.get(RegionBoundaryVersion, region.current_boundary_version_id)
                if boundary is None or not boundary.geometry_json:
                    gaps.append(
                        self._quality_gap(
                            "REGION_BOUNDARY",
                            region.current_boundary_version_id,
                            region.name,
                            "geometry_json",
                            "REGION_BOUNDARY_GEOMETRY_MISSING",
                            "区域当前边界缺少几何数据，空间供需分析无法精确落区。",
                            f"/address/regions?region_id={region.id}",
                        )
                    )
        if analysis.source_spatial_snapshot_id is None and (analysis.origin_node_id or analysis.route_id or analysis.region_id):
            gaps.append(
                self._quality_gap(
                    "VESSEL_SPATIAL_OBSERVATION",
                    None,
                    None,
                    "source_spatial_snapshot_id",
                    "SPATIAL_SNAPSHOT_MISSING",
                    "本次分析没有可复盘的空间观测快照，建议先刷新 AIS 空间态势。",
                    "/vessels/node-route-analysis",
                )
            )
        return gaps

    async def _route_segment_count(self, route_id: int) -> int:
        return int(
            await self.db.scalar(
                select(func.count(ShippingRoutePlanSegment.id))
                .join(ShippingRoutePlan, ShippingRoutePlan.id == ShippingRoutePlanSegment.plan_id)
                .where(ShippingRoutePlan.route_id == route_id)
            )
            or 0
        )

    async def _route_track_count(self, route_id: int) -> int:
        return int(
            await self.db.scalar(
                select(func.count(ShippingRoutePlanTrackVersionSegment.id))
                .select_from(ShippingRoutePlanTrackVersionSegment)
                .join(ShippingRoutePlanTrackVersion, ShippingRoutePlanTrackVersion.id == ShippingRoutePlanTrackVersionSegment.version_id)
                .join(ShippingRoutePlan, ShippingRoutePlan.id == ShippingRoutePlanTrackVersion.plan_id)
                .where(
                    ShippingRoutePlan.route_id == route_id,
                    ShippingRoutePlan.current_track_version_id == ShippingRoutePlanTrackVersion.id,
                    ShippingRoutePlanTrackVersion.version_status_code == "READY",
                )
            )
            or 0
        )

    @staticmethod
    def _quality_gap(
        object_type: str,
        object_id: int | str | None,
        object_name: str | None,
        field_name: str,
        reason_code: str,
        message: str,
        target_path: str | None,
    ) -> VesselCandidateContextQualityGap:
        return VesselCandidateContextQualityGap(
            object_type=object_type,
            object_id=object_id,
            object_name=object_name,
            field_name=field_name,
            reason_code=reason_code,
            message=message,
            target_path=target_path,
        )

    def _item_response(
        self,
        row: VesselCandidateAnalysisItem,
        annotations: list[VesselCandidateAnalysisAnnotationResponse],
        latest_position: VesselLatestPositionSnapshot | None = None,
    ) -> VesselCandidateAnalysisItemResponse:
        return VesselCandidateAnalysisItemResponse(
            id=row.id,
            analysis_id=row.analysis_id,
            vessel_profile_id=row.vessel_profile_id,
            mmsi=row.mmsi,
            ship_name=row.ship_name,
            ship_type_code=row.ship_type_code,
            deadweight_ton=row.deadweight_ton,
            design_draft_m=row.design_draft_m,
            longitude=latest_position.longitude if latest_position is not None else None,
            latitude=latest_position.latitude if latest_position is not None else None,
            latest_position_time=row.latest_position_time,
            ais_freshness_level=row.ais_freshness_level,
            risk_level=row.risk_level,
            quality_level=row.quality_level,
            fit_score=row.fit_score,
            candidate_value_level=row.candidate_value_level,
            confidence_level=row.confidence_level,
            node_distance_km=row.node_distance_km,
            route_match_score=row.route_match_score,
            direction_consistency=row.direction_consistency,
            constraint_status_code=row.constraint_status_code,
            score_parts=row.score_parts_json or {},
            risk_reasons=row.risk_reasons_json or [],
            uncertainty_reasons=row.uncertainty_reasons_json or [],
            not_computable_reasons=row.not_computable_reasons_json or [],
            data_sources=self._data_source_codes(row.data_sources_json),
            annotations=annotations,
        )

    async def _latest_positions_for_items(
        self,
        analysis: VesselCandidateAnalysis,
        rows: list[VesselCandidateAnalysisItem],
    ) -> dict[int, VesselLatestPositionSnapshot]:
        if not analysis.source_ais_snapshot_id:
            return {}
        vessel_ids = [row.vessel_profile_id for row in rows if row.vessel_profile_id]
        if not vessel_ids:
            return {}
        position_rows = (
            await self.db.scalars(
                select(VesselLatestPositionSnapshot)
                .where(
                    VesselLatestPositionSnapshot.snapshot_id == analysis.source_ais_snapshot_id,
                    VesselLatestPositionSnapshot.vessel_profile_id.in_(vessel_ids),
                    VesselLatestPositionSnapshot.valid_position_flag.is_(True),
                    VesselLatestPositionSnapshot.longitude.is_not(None),
                    VesselLatestPositionSnapshot.latitude.is_not(None),
                )
                .order_by(VesselLatestPositionSnapshot.position_time.desc().nullslast())
            )
        ).all()
        result: dict[int, VesselLatestPositionSnapshot] = {}
        for row in position_rows:
            if row.vessel_profile_id is not None:
                result.setdefault(row.vessel_profile_id, row)
        return result

    async def _annotations_by_item(self, item_ids: list[int]) -> dict[int, list[VesselCandidateAnalysisAnnotationResponse]]:
        if not item_ids:
            return {}
        rows = (
            await self.db.execute(
                select(VesselCandidateAnalysisAnnotation)
                .where(VesselCandidateAnalysisAnnotation.item_id.in_(item_ids))
                .order_by(VesselCandidateAnalysisAnnotation.created_at)
            )
        ).scalars().all()
        result: dict[int, list[VesselCandidateAnalysisAnnotationResponse]] = {}
        for row in rows:
            result.setdefault(row.item_id, []).append(self._annotation_response(row))
        return result

    def _annotation_response(self, row: VesselCandidateAnalysisAnnotation) -> VesselCandidateAnalysisAnnotationResponse:
        return VesselCandidateAnalysisAnnotationResponse(
            id=row.id,
            analysis_id=row.analysis_id,
            item_id=row.item_id,
            annotation_type_code=row.annotation_type_code,
            comment=row.comment,
            created_by=row.created_by,
            created_at=row.created_at,
            source_version=row.source_version_json or {},
        )

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

    def _allowed_quality_levels(self, threshold: str) -> list[str]:
        if threshold == "HIGH":
            return ["HIGH", "GOOD"]
        if threshold == "MEDIUM":
            return ["HIGH", "MEDIUM", "GOOD", "REVIEW"]
        return ["HIGH", "MEDIUM", "GOOD", "REVIEW", "LOW", "UNKNOWN"]

    def _min_confidence(self, left: str, right: str) -> str:
        return left if CONFIDENCE_ORDER.get(left, 0) <= CONFIDENCE_ORDER.get(right, 0) else right

    def _dedupe(self, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            if value and value not in result:
                result.append(value)
        return result

    def _data_source_codes(self, values: list[Any] | None) -> list[str]:
        result: list[str] = []
        for value in values or []:
            code: str | None = None
            if isinstance(value, str):
                code = value
            elif isinstance(value, dict):
                for key in ("source_layer", "source_index", "snapshot_id", "ais_snapshot_id", "route_snapshot_id"):
                    raw = value.get(key)
                    if raw:
                        code = str(raw)
                        break
            elif value:
                code = str(value)
            if code and code not in result:
                result.append(code)
        return result

    def _contains_forbidden_terms(self, value: str | None) -> bool:
        lowered = (value or "").lower()
        return any(term in lowered for term in FORBIDDEN_ANALYSIS_TERMS)


def distance_km(lon1: Decimal | float, lat1: Decimal | float, lon2: Decimal | float, lat2: Decimal | float) -> Decimal:
    lng1, la1, lng2, la2 = map(float, [lon1, lat1, lon2, lat2])
    radius = 6371.0
    dlat = math.radians(la2 - la1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(la1)) * math.cos(math.radians(la2)) * math.sin(dlng / 2) ** 2
    return Decimal(str(radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))).quantize(Decimal("0.001"))
